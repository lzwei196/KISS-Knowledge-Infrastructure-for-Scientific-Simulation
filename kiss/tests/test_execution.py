"""Shared execution lifecycle through the same interface used by both adapters.

Small local project fixtures provide genuine approval and signed receipts. Process
exceptions are injected for deterministic failure coverage; these are execution
contract tests, not scientific-model or live-provider tests.
"""
from __future__ import annotations

import copy
import io
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from kiss_cli import execution, flowgate, paths


@pytest.fixture(autouse=True)
def _isolated_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))


def _project(tmp_path, *, python_tool=True):
    project = (tmp_path / "project").resolve()
    root = project / "models" / "M" / "ki"
    (root / "tools").mkdir(parents=True)
    (project / "runs").mkdir()
    (root / "SKILL.md").write_text(
        "# M\n> **MANDATORY EXECUTION POLICY**\n> run the declared tool\n\n")
    (root / "dag.yaml").write_text(
        "outputs:\n- var: discharge\n  validation_rank: 1\n  unit: m3/s\n")
    tool = root / "tools" / ("run.py" if python_tool else "run.sh")
    tool.write_text("print('local execution fixture')\n" if python_tool
                    else "#!/bin/sh\nprintf 'local execution fixture'\n")
    cfg = paths.KissConfig.default(project)
    cfg.python = Path(sys.executable)
    (project / paths.CONFIG_NAME).write_text(cfg.dumps(), encoding="utf-8")
    fs = flowgate.FlowSession.open(project, {"M": root}, python=sys.executable)
    fs.move("task_received")
    fs.move("kis_resolved", {"selected_kis": ["M"]})
    plan = {
        "schema_version": "1.0", "goal": "Exercise an approved execution attempt",
        "selected_kis": ["M"], "created_at": "test", "unresolved_questions": [],
        "scientific_choices": [{"id": "fixture", "kind": "other", "high_impact": False}],
        "steps": [{"id": "M:run", "ki": "M", "tool": str(tool), "kind": "run",
                   "inputs": ["forcing"], "outputs": ["q"], "status": "planned"}],
    }
    inventory = {"schema_version": "1.0", "items": [{
        "id": "forcing", "required_by": ["M"], "status": "resolved",
        "acceptable_sources": ["local_fixture"], "chosen_source": "local_fixture",
        "local_paths": [], "agent_resolvable": True, "needs_user": False,
    }]}
    assert fs.write_plan(plan, inventory) == []
    fs.flow.approval.approve(project, by="auto")
    fs.reload_artifacts()
    fs.move("plan_written", {"plan_valid": True})
    fs.move("approved", {"approval": "OK"})
    fs.move("execution_started", {"setup_verified": True})
    return SimpleNamespace(project=project, root=root, cfg=cfg, flow=fs, tool=tool,
                           plan=plan, inventory=inventory, python_tool=python_tool)


def _execute(ctx, **overrides):
    arguments = dict(flow=ctx.flow, cfg=ctx.cfg, project=ctx.project, ki="M",
                     ki_root=ctx.root, tool=ctx.tool, arguments=[], cwd=ctx.project,
                     plan_step_id="M:run", python_tool=ctx.python_tool)
    arguments.update(overrides)
    return execution.execute_ki_tool(**arguments)


def _receipt_docs(ctx):
    docs = [json.loads(p.read_text()) for p in
            (ctx.project / ".geoforge" / "receipts" / "model-runs").glob("*.json")]
    assert all(ctx.flow.flow.receipts.verify(ctx.project, doc) for doc in docs)
    return docs


class _Child:
    """A launched child: observation failure cannot be mistaken for launch failure."""

    def __init__(self, returncode=0, stdout="", stderr="", *, failure=None, on_communicate=None):
        self.returncode = None
        self.expected_returncode = returncode
        self.output = (stdout, stderr)
        self.stdout, self.stderr = io.StringIO(stdout), io.StringIO(stderr)
        self.failure = failure
        self.on_communicate = on_communicate
        self.timeouts = []
        self.kills = 0
        self.waits = 0

    def communicate(self, timeout=None):
        self.timeouts.append(timeout)
        if len(self.timeouts) == 1:
            if self.on_communicate:
                self.on_communicate()
            if self.failure:
                raise self.failure
        if self.returncode is None:
            self.returncode = self.expected_returncode
        return self.output

    def kill(self):
        self.kills += 1
        self.returncode = -9

    def wait(self, timeout=None):
        self.waits += 1
        if self.returncode is None:
            self.returncode = self.expected_returncode
        return self.returncode

    def poll(self):
        return self.returncode


@pytest.mark.parametrize("phase,failure,status,started", [
    ("launch", FileNotFoundError("fixture interpreter is unavailable"), "not_launched", False),
    ("observe", subprocess.TimeoutExpired(["fixture"], 2, output=b"before timeout\n",
               stderr=b"stderr before timeout\n"), "timed_out", True),
    ("launch", KeyboardInterrupt(), "interrupted", None),
    ("launch", RuntimeError("unexpected process launch failure"), "outcome_unknown", None),
    ("observe", OSError("output stream read failed after launch"), "outcome_unknown", True),
    ("observe", KeyboardInterrupt(), "interrupted", True),
])
def test_abnormal_attempt_is_recorded_once_without_inventing_process_success(
        tmp_path, monkeypatch, phase, failure, status, started):
    ctx = _project(tmp_path)
    calls = []
    child = _Child(stdout="before timeout\n", stderr="stderr before timeout\n", failure=failure)

    def fail(command, **kwargs):
        calls.append(command)
        if phase == "launch":
            raise failure
        return child

    monkeypatch.setattr(execution.subprocess, "Popen", fail)
    result = _execute(ctx, timeout=2)
    assert result.status == status
    assert result.exit_code is None and result.receipt_error is None
    assert len(calls) == 1
    docs = _receipt_docs(ctx)
    assert len(docs) == 1
    doc = docs[0]
    assert doc["execution_status"] == status
    assert doc["process_started"] is started
    # The legacy field remains boolean; the nullable process_started field
    # distinguishes a proven launch failure from an unknown launch outcome.
    assert doc["binary_actually_ran"] is (started is True)
    assert doc["exit_code"] is None
    assert doc["validation"]["status"] != "passed"
    assert result.receipt["execution_status"] == status
    if phase == "observe":
        assert child.kills == 1
        assert len(child.timeouts) >= 2 or child.waits >= 1
        assert child.stdout.closed and child.stderr.closed
    if status == "timed_out":
        assert "before timeout" in result.output and "stderr before timeout" in result.output
        assert result.timeout == 2


def test_cleanup_interrupt_and_unconfirmed_wait_preserve_original_timeout(tmp_path, monkeypatch):
    ctx = _project(tmp_path)
    launches = []

    class UncertainCleanup(_Child):
        def communicate(self, timeout=None):
            self.timeouts.append(timeout)
            if len(self.timeouts) == 1:
                raise subprocess.TimeoutExpired(["fixture"], timeout,
                                                output=b"last observed tool output\n")
            raise OSError("fixture output pipe is unreadable")

        def kill(self):
            self.kills += 1
            raise KeyboardInterrupt("fixture kill interrupted")

        def wait(self, timeout=None):
            self.waits += 1
            raise subprocess.TimeoutExpired(["fixture"], timeout)

    child = UncertainCleanup()

    def launch(command, **kwargs):
        launches.append(command)
        return child

    monkeypatch.setattr(execution.subprocess, "Popen", launch)
    result = _execute(ctx, timeout=2)
    assert len(launches) == 1 and child.kills == child.waits == 1
    assert child.timeouts == [2, 5]
    assert child.stdout.closed and child.stderr.closed
    assert result.status == "timed_out" and result.exit_code is None
    assert "last observed tool output" in result.output
    assert "cleanup" in result.detail and "termination was not confirmed" in result.detail
    assert result.receipt_error is None
    [receipt] = _receipt_docs(ctx)
    assert receipt["execution_status"] == "timed_out" and receipt["process_started"] is True
    assert receipt["validation"]["status"] != "passed"
    assert "termination was not confirmed" in Path(receipt["stdout_log"]).read_text()


def test_pipe_close_failure_preserves_failed_tool_outcome_and_receipt(tmp_path, monkeypatch):
    ctx = _project(tmp_path)
    launches = []

    class UnclosablePipe:
        def close(self):
            raise RuntimeError("fixture close failure")

    child = _Child(7, "tool diagnosed a scientific failure\n", "forcing column absent\n")
    child.stdout = UnclosablePipe()

    def launch(command, **kwargs):
        launches.append(command)
        return child

    monkeypatch.setattr(execution.subprocess, "Popen", launch)
    result = _execute(ctx)
    assert len(launches) == 1 and child.kills == child.waits == 0
    assert child.stderr.closed
    assert result.status == "failed" and result.exit_code == 7
    assert "scientific failure" in result.output and "forcing column absent" in result.output
    assert "pipe" in result.detail.casefold() and "cleanup" in result.detail.casefold()
    assert result.receipt_error is None
    [receipt] = _receipt_docs(ctx)
    assert receipt["execution_status"] == "failed" and receipt["exit_code"] == 7
    assert receipt["validation"]["status"] != "passed"
    assert "pipe cleanup" in Path(receipt["stdout_log"]).read_text().casefold()


@pytest.mark.parametrize("returncode,status", [(0, "succeeded"), (7, "failed")])
def test_receipt_failure_preserves_process_outcome_and_output_without_retry(
        tmp_path, monkeypatch, returncode, status):
    ctx = _project(tmp_path)
    calls = []
    record_calls = []

    def launch(command, **kwargs):
        calls.append(command)
        return _Child(returncode, "tool stdout\n", "tool stderr\n")

    def cannot_record(*args, **kwargs):
        record_calls.append(kwargs)
        raise OSError("receipt destination is read-only")

    monkeypatch.setattr(execution.subprocess, "Popen", launch)
    monkeypatch.setattr(ctx.flow.flow.receipts, "record_run", cannot_record)
    result = _execute(ctx)
    assert result.status == status and result.exit_code == returncode
    assert "tool stdout" in result.output and "tool stderr" in result.output
    assert result.receipt is None and "read-only" in result.receipt_error
    assert len(calls) == len(record_calls) == 1
    assert _receipt_docs(ctx) == []


def test_valid_reapproval_during_attempt_cannot_rebind_its_receipt(tmp_path, monkeypatch):
    ctx = _project(tmp_path)
    original_approval = ctx.flow.approval_id
    calls = []

    def reapprove():
        # Same plan and tool, but a different signed approval issuance.
        ctx.flow.flow.approval.approve(ctx.project, by="auto")
        assert ctx.flow.flow.approval.check(ctx.project) == "OK"

    def launch(command, **kwargs):
        calls.append(command)
        return _Child(0, "completed under the old approval\n", on_communicate=reapprove)

    monkeypatch.setattr(execution.subprocess, "Popen", launch)
    result = _execute(ctx)
    current = ctx.flow.flow.approval.read(ctx.project)
    assert ctx.flow.flow.approval.approval_id(current) != original_approval
    assert len(calls) == 1 and result.status == "succeeded" and result.exit_code == 0
    assert "completed under the old approval" in result.output
    assert result.receipt is None and result.receipt_error
    assert "approval" in result.receipt_error.casefold()
    assert _receipt_docs(ctx) == []


def test_fresh_plan_rejects_old_tool_even_when_supplied_session_is_stale(tmp_path, monkeypatch):
    ctx = _project(tmp_path)
    replacement = ctx.root / "tools" / "replacement.py"
    replacement.write_text("print('replacement fixture')\n")
    new_plan = copy.deepcopy(ctx.plan)
    new_plan["steps"][0]["tool"] = str(replacement)
    ctx.flow.flow.plan.write_artifacts(ctx.project, new_plan, ctx.inventory)
    ctx.flow.flow.approval.approve(ctx.project, by="auto")
    assert ctx.flow.approval_status() == "OK"
    assert ctx.flow.plan["steps"][0]["tool"] == str(ctx.tool)
    calls = []

    def forbidden(command, **kwargs):
        calls.append(command)
        return _Child(0, "must not launch")

    monkeypatch.setattr(execution.subprocess, "Popen", forbidden)
    with pytest.raises(flowgate.FlowDenied, match="approved for tool"):
        _execute(ctx)
    assert calls == [] and _receipt_docs(ctx) == []


def test_fresh_state_refuses_execution_from_a_stale_executing_session(tmp_path, monkeypatch):
    ctx = _project(tmp_path)
    fresh = flowgate.FlowSession.open(ctx.project, {"M": ctx.root}, python=sys.executable)
    fresh.move("replan")
    assert ctx.flow.state.value == "EXECUTING"
    assert fresh.state.value == "REPLAN_REQUIRED"
    calls = []

    def forbidden(command, **kwargs):
        calls.append(command)
        return _Child(0, "must not launch")

    monkeypatch.setattr(execution.subprocess, "Popen", forbidden)
    with pytest.raises(flowgate.FlowDenied, match="REPLAN_REQUIRED"):
        _execute(ctx)
    assert calls == [] and _receipt_docs(ctx) == []


def test_rapid_attempts_keep_distinct_logs_and_signed_receipts(tmp_path, monkeypatch):
    ctx = _project(tmp_path)
    outputs = iter(["first attempt\n", "second attempt\n"])

    def launch(command, **kwargs):
        return _Child(0, next(outputs))

    monkeypatch.setattr(execution.subprocess, "Popen", launch)
    monkeypatch.setattr(execution.time, "time", lambda: 1800000000.0)
    first, second = _execute(ctx), _execute(ctx)
    assert first.status == second.status == "succeeded"
    docs = _receipt_docs(ctx)
    assert len(docs) == 2
    assert len({doc["run_id"] for doc in docs}) == 2
    assert len({doc["stdout_log"] for doc in docs}) == 2
    assert {Path(doc["stdout_log"]).read_text() for doc in docs} == {
        "first attempt\n", "second attempt\n"}
    assert all(doc["execution_status"] == "succeeded" for doc in docs)


@pytest.mark.parametrize("python_tool", [True, False])
def test_receipt_records_relative_input_from_real_cwd_including_binary_first_argument(
        tmp_path, monkeypatch, python_tool):
    ctx = _project(tmp_path, python_tool=python_tool)
    cwd = ctx.project / "inputs" / "case"
    cwd.mkdir(parents=True)
    input_file = cwd / "forcing.csv"
    input_file.write_text("t,forcing\n1,2\n")
    observed = []

    def launch(command, **kwargs):
        observed.append((command, kwargs))
        return _Child(0, "read local fixture\n")

    monkeypatch.setattr(execution.subprocess, "Popen", launch)
    result = _execute(ctx, arguments=["forcing.csv"], cwd=cwd)
    assert result.status == "succeeded" and result.receipt_error is None
    assert len(observed) == 1 and observed[0][1]["cwd"] == str(cwd)
    expected = ([str(ctx.cfg.python), str(ctx.tool)] if python_tool else [str(ctx.tool)])
    assert observed[0][0] == expected + ["forcing.csv"]
    [receipt] = _receipt_docs(ctx)
    assert receipt["inputs"] == [{
        "path": "inputs/case/forcing.csv", "bytes": input_file.stat().st_size,
        "sha256": ctx.flow.flow.receipts.sha256_file(input_file),
    }]


@pytest.mark.parametrize("requested,expected", [(None, 600), (0, 600), (-2, 1), (9000, 3600)])
def test_direct_adapter_preserves_its_default_and_bounded_deadline(
        tmp_path, monkeypatch, requested, expected):
    from kiss_cli import api

    ctx = _project(tmp_path)
    children = []

    def launch(command, **kwargs):
        child = _Child(0, "local fixture done\n")
        children.append(child)
        return child

    monkeypatch.setattr(execution.subprocess, "Popen", launch)
    arguments = {"tool_path": "tools/run.py", "plan_step_id": "M:run"}
    if requested is not None:
        arguments["timeout_seconds"] = requested
    output = api.execute_tool("run_ki_tool", arguments,
                              SimpleNamespace(name="M", root=ctx.root), ctx.cfg,
                              project_mode=True, flow=ctx.flow)
    assert output.startswith("exit_code=0")
    assert len(children) == 1 and children[0].timeouts == [expected]
    assert children[0].stdout.closed and children[0].stderr.closed
    assert len(_receipt_docs(ctx)) == 1


def test_cli_adapter_keeps_no_deadline_instead_of_adopting_direct_default(
        tmp_path, monkeypatch, capsys):
    from kiss_cli import cli

    ctx = _project(tmp_path)
    children = []

    def launch(command, **kwargs):
        child = _Child(0, "local fixture done\n")
        children.append(child)
        return child

    monkeypatch.setattr(execution.subprocess, "Popen", launch)
    # The command adapter is the execution seam; CLI startup shell discovery is
    # unrelated and intentionally outside this deterministic process fixture.
    assert cli.cmd_run_tool(SimpleNamespace(project=str(ctx.project), step="M:run",
                                           ki="M", tool="tools/run.py", argv=[])) == 0
    output = capsys.readouterr()
    assert not output.err and "local fixture done" in output.out
    assert len(children) == 1 and children[0].timeouts == [None]
    assert len(_receipt_docs(ctx)) == 1
