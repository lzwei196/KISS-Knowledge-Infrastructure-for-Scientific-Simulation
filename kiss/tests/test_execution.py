"""Shared execution lifecycle through the same interface used by both adapters.

Small local project fixtures provide genuine approval and signed receipts. Process
exceptions are injected for deterministic failure coverage; these are execution
contract tests, not scientific-model or live-provider tests.
"""
from __future__ import annotations

import copy
import os
import io
import json
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from kiss_cli import execution, flowgate, paths


@pytest.fixture(autouse=True)
def _isolated_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))


def _project(tmp_path, *, python_tool=True, source=None):
    project = (tmp_path / "project").resolve()
    root = project / "models" / "M" / "ki"
    (root / "tools").mkdir(parents=True)
    (project / "runs").mkdir()
    (root / "SKILL.md").write_text(
        "# M\n> **MANDATORY EXECUTION POLICY**\n> run the declared tool\n\n")
    (root / "dag.yaml").write_text(
        "outputs:\n- var: discharge\n  validation_rank: 1\n  unit: m3/s\n")
    tool = root / "tools" / ("run.py" if python_tool else "run.sh")
    tool.write_text(source or "print('local execution fixture')\n" if python_tool
                    else "#!/bin/sh\nprintf 'local execution fixture'\n")
    cfg = paths.KissConfig.default(project)
    cfg.python = Path(sys.executable)
    (project / paths.CONFIG_NAME).write_text(cfg.dumps(), encoding="utf-8")
    (root.parent / paths.CONFIG_NAME).write_text(cfg.dumps(), encoding="utf-8")
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
    docs = [json.loads(p.read_text(encoding="utf-8")) for p in
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
    assert "termination was not confirmed" in Path(receipt["stdout_log"]).read_text(encoding="utf-8")


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
    assert "pipe cleanup" in Path(receipt["stdout_log"]).read_text(encoding="utf-8").casefold()


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
    assert {Path(doc["stdout_log"]).read_text(encoding="utf-8") for doc in docs} == {
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


_SLOW_TOOL = """import os, subprocess, sys, time
child = subprocess.Popen(["sleep", "30"])
open(sys.argv[1], "w").write(f"{os.getpid()} {child.pid}")
time.sleep(30)
"""

# A model the tool starts in a session of its own (setsid, a daemonising solver),
# either still holding the tool's stdout ("pipe") or writing to a log ("log").
_SESSION_TOOL = """import os, subprocess, sys
out = None if sys.argv[2] == "pipe" else subprocess.DEVNULL
child = subprocess.Popen(["sleep", "30"], start_new_session=True, stdout=out, stderr=out)
open(sys.argv[1], "w").write(f"{os.getpid()} {child.pid}")
child.wait()
"""

_OUTPUT_TOOL = ("import pathlib\np = pathlib.Path('outputs'); p.mkdir(exist_ok=True)\n"
                "(p / 'q.csv').write_text('t,q\\n1,0.5\\n2,1.2\\n3,0.8\\n')\n")


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _run_slow_tool(ctx, *, timeout, stop_after=None, extra=()):
    import threading
    pidfile = ctx.project / "runs" / "pids.txt"
    box = {}
    worker = threading.Thread(target=lambda: box.update(result=_execute(
        ctx, arguments=[str(pidfile), *extra], timeout=timeout)))
    started = time.time()
    worker.start()
    while not pidfile.exists() or not pidfile.read_text():
        assert time.time() - started < 10, "fixture tool never started"
        time.sleep(0.05)
    pids = [int(p) for p in pidfile.read_text().split()]
    if stop_after is not None:
        time.sleep(stop_after)
        execution.request_stop(ctx.project)
    worker.join(timeout=15)
    assert not worker.is_alive(), "Stop did not end the tool attempt"
    deadline = time.time() + 5
    while any(map(_alive, pids)) and time.time() < deadline:
        time.sleep(0.05)
    return box["result"], pids, time.time() - started


def _evidence(ctx):
    return ctx.flow.flow.receipts.evidence(ctx.project, ctx.flow.plan, ctx.flow.approval_doc,
                                           inventory=ctx.flow.inventory)


@pytest.mark.skipif(os.name == "nt", reason="process groups are POSIX")
def test_stop_ends_a_running_tool_and_the_model_processes_it_started(tmp_path):
    ctx = _project(tmp_path, source=_SLOW_TOOL)
    result, pids, elapsed = _run_slow_tool(ctx, timeout=None, stop_after=0.2)   # CLI: no deadline
    assert elapsed < 10 and not any(map(_alive, pids))
    assert result.status == "stopped" and "stopped by the user" in result.detail.lower()
    assert "signalled" in result.detail
    [receipt] = _receipt_docs(ctx)
    # Stopped is its own outcome: not passed, not failed, so the step is simply still to do.
    assert receipt["execution_status"] == "stopped" and receipt["validation"]["status"] == "stopped"
    ev = _evidence(ctx)
    assert ev["validation"] == "incomplete" and ev["steps_missing"] == ["M:run"]


@pytest.mark.skipif(os.name == "nt", reason="process groups are POSIX")
def test_timeout_does_not_leave_the_model_child_running(tmp_path):
    ctx = _project(tmp_path, source=_SLOW_TOOL)
    result, pids, _ = _run_slow_tool(ctx, timeout=1)
    assert result.status == "timed_out" and not any(map(_alive, pids))


@pytest.mark.skipif(os.name == "nt", reason="process groups are POSIX")
@pytest.mark.parametrize("how", ["stop", "timeout"])
@pytest.mark.parametrize("stdout", ["pipe", "log"])
def test_a_model_in_its_own_session_is_ended_with_its_tool(tmp_path, how, stdout):
    ctx = _project(tmp_path, source=_SESSION_TOOL)
    result, pids, elapsed = _run_slow_tool(
        ctx, timeout=None if how == "stop" else 1, stop_after=0.2 if how == "stop" else None,
        extra=[stdout])
    assert not any(map(_alive, pids)), "the model outlived the Stop or timeout"
    assert elapsed < 12 and result.status == ("stopped" if how == "stop" else "timed_out")


def test_a_stop_refuses_new_attempts_until_the_next_turn_begins(tmp_path, monkeypatch):
    from kiss_cli import projectrun
    ctx = _project(tmp_path, source=_OUTPUT_TOOL)
    assert _execute(ctx).status == "succeeded" and _evidence(ctx)["validation"] == "passed"
    execution.request_stop(ctx.project)
    launches = []
    real_popen = subprocess.Popen
    monkeypatch.setattr(execution.subprocess, "Popen",
                        lambda *a, **k: launches.append(a) or real_popen(*a, **k))
    with pytest.raises(flowgate.FlowDenied, match="stopped by the user; no process was launched"):
        _execute(ctx)
    # A refused launch is not an attempt: no receipt, and the step that passed still stands.
    assert launches == [] and len(_receipt_docs(ctx)) == 1
    assert _evidence(ctx)["validation"] == "passed"
    projectrun.begin_turn(ctx.project, "continue")          # the user's next message
    assert not (ctx.project / execution.STOP_MARKER).exists()
    assert _execute(ctx).status == "succeeded" and len(_receipt_docs(ctx)) == 2


def test_a_stop_during_preparation_launches_nothing(tmp_path, monkeypatch):
    ctx = _project(tmp_path, source=_OUTPUT_TOOL)
    launches = []
    real_popen, real_snapshot = subprocess.Popen, flowgate._snapshot

    def snapshot_then_stop(*args, **kwargs):
        taken = real_snapshot(*args, **kwargs)
        execution.request_stop(ctx.project)                 # the click lands mid-preparation
        return taken

    monkeypatch.setattr(flowgate, "_snapshot", snapshot_then_stop)
    monkeypatch.setattr(execution.subprocess, "Popen",
                        lambda *a, **k: launches.append(a) or real_popen(*a, **k))
    with pytest.raises(flowgate.FlowDenied, match="no process was launched"):
        _execute(ctx)
    assert launches == [] and _receipt_docs(ctx) == []
    assert not (ctx.project / "outputs").exists()


@pytest.mark.parametrize("adapter", ["api", "cli"])
def test_requested_ki_uses_its_runtime_not_first_or_last_model(
        tmp_path, monkeypatch, adapter):
    from kiss_cli import api, cli, project_paths

    ctx = _project(tmp_path)
    other_root = ctx.project / "models" / "A" / "ki"
    other_root.mkdir(parents=True)
    shared = paths.KissConfig.default(tmp_path / "installed-M")
    shared.python = str(tmp_path / "installed-M" / "python")
    shared.roles["binaries"].mkdir(parents=True)
    common = shared.roles["ki_tools_common"] / "ki_tools_common"
    common.mkdir(parents=True)
    (common / "__init__.py").write_text("# fixture shared package\n")
    binary = shared.roles["binaries"] / "model"
    binary.write_text("fixture executable")
    # The saved M fixture initially uses project-wide defaults; remove it so
    # this test gets the normal per-model output paths of a fresh workspace.
    (ctx.root.parent / paths.CONFIG_NAME).unlink()
    model = project_paths.model_config(ctx.project, "M", shared)
    (ctx.root.parent / paths.CONFIG_NAME).write_text(model.dumps(), encoding="utf-8")
    wrong = paths.KissConfig.default(ctx.project)
    wrong.python = str(tmp_path / "installed-A" / "python")
    wrong.roles["outputs"] = ctx.project / "outputs" / "A"
    wrong.roles["binaries"] = tmp_path / "installed-A" / "binaries"
    (ctx.project / paths.CONFIG_NAME).write_text(wrong.dumps(), encoding="utf-8")
    ctx.flow.ki_roots["A"] = other_root
    ctx.flow.ctx.selected_kis = ["A", "M"]
    ctx.flow.ctx.save()
    launches = []

    def launch(command, **kwargs):
        launches.append((command, kwargs))
        return _Child(0, "correct KI fixture")

    monkeypatch.setattr(execution.subprocess, "Popen", launch)
    if adapter == "api":
        result = api.execute_tool("run_ki_tool", {
            "ki": "M", "tool_path": "tools/run.py", "plan_step_id": "M:run",
            "arguments": [str(binary)],
        }, SimpleNamespace(name="A", root=other_root), wrong,
            project_mode=True, flow=ctx.flow)
        assert "exit_code=0" in result
    else:
        assert cli.cmd_run_tool(SimpleNamespace(
            project=str(ctx.project), step="M:run", ki="M", tool="tools/run.py",
            argv=[str(binary)])) == 0
    assert len(launches) == 1
    command, options = launches[0]
    assert command[0] == shared.python
    assert options["cwd"] == str(ctx.project)
    assert options["env"]["KISS_ROOT"] == str(ctx.root.parent)
    assert str(shared.roles["ki_tools_common"]) in options["env"]["PYTHONPATH"]
    assert len(_receipt_docs(ctx)) == 1


def test_materialized_missing_runtime_never_falls_back_to_project_config(tmp_path, monkeypatch):
    ctx = _project(tmp_path)
    (ctx.root.parent / paths.CONFIG_NAME).unlink()
    launches = []
    monkeypatch.setattr(execution.subprocess, "Popen", lambda *a, **k: launches.append(a))
    with pytest.raises(flowgate.FlowDenied, match="model-specific"):
        _execute(ctx)
    assert launches == []
    assert _receipt_docs(ctx) == []


def test_model_child_and_host_agree_on_moved_and_relative_roles(tmp_path):
    from kiss_cli import project_paths

    project = (tmp_path / "moved-project").resolve()
    model_home = project / "models" / "M"
    (model_home / "ki").mkdir(parents=True)
    run_dir = project / "runs" / "nested"
    run_dir.mkdir(parents=True)
    old = (tmp_path / "old-project").resolve()
    saved = paths.KissConfig.default(old)
    saved.python = sys.executable
    saved.roles["outputs"] = old / "outputs" / "M"
    saved.roles["forcing"] = Path("inputs/forcing/user-weather")
    (model_home / paths.CONFIG_NAME).write_text(saved.dumps(), encoding="utf-8")
    host = project_paths.load_model_config(project, "M")
    source = str(Path(paths.__file__).resolve().parents[1])
    code = (
        f"import sys;sys.path.insert(0, {source!r});"
        "import json;from kiss_cli.paths import active,P;"
        "print(json.dumps({'root':str(active().root),'forcing':str(P('forcing')),'outputs':str(P('outputs'))}))"
    )
    env = dict(__import__("os").environ, KISS_ROOT=str(model_home))
    child = subprocess.run([sys.executable, "-c", code], cwd=run_dir, env=env,
                           capture_output=True, text=True, check=True, timeout=10)
    result = json.loads(child.stdout)
    assert result == {"root": str(project), "forcing": str(host.roles["forcing"]),
                      "outputs": str(host.roles["outputs"])}


def _run_tool_process(ctx, *args, pythonpath=(), new_session=False):
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([*map(str, pythonpath),
        str(Path(execution.__file__).parents[1]), str(Path(execution.__file__).parents[2] / "ki_tools_common")])}
    return subprocess.Popen([sys.executable, "-m", "kiss_cli", "run-tool", "--step", "M:run",
                             "--project", str(ctx.project), "M", "tools/run.py", "--", *map(str, args)],
                            env=env, cwd=str(ctx.project), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            start_new_session=new_session)


@pytest.mark.skipif(os.name == "nt", reason="process groups are POSIX")
@pytest.mark.parametrize("user_stop", [True, False])
def test_sigterm_to_a_direct_cli_run_tool_still_ends_the_model_and_receipts_it(tmp_path, user_stop):
    # Stop SIGTERMs the agent CLI's process tree; a source-build run-tool is inside it.
    import signal
    ctx = _project(tmp_path, source=_SLOW_TOOL)
    pidfile = ctx.project / "runs" / "pids.txt"
    proc = _run_tool_process(ctx, pidfile)
    deadline = time.time() + 20
    while not pidfile.exists() or not pidfile.read_text():
        assert time.time() < deadline and proc.poll() is None, proc.communicate()
        time.sleep(0.05)
    pids = [int(p) for p in pidfile.read_text().split()]
    if user_stop:
        execution.request_stop(ctx.project)         # _stop_agent_run writes it before signalling
    proc.send_signal(signal.SIGTERM)
    proc.wait(15)
    deadline = time.time() + 5
    while any(map(_alive, pids)) and time.time() < deadline:
        time.sleep(0.05)
    assert not any(map(_alive, pids)), "the model outlived its supervisor"
    [receipt] = _receipt_docs(ctx)
    assert receipt["execution_status"] == ("stopped" if user_stop else "interrupted")


@pytest.mark.skipif(os.name == "nt", reason="signals are POSIX")
@pytest.mark.parametrize("how", ["direct", "tree"])
def test_sigterm_while_the_receipt_is_written_does_not_lose_a_finished_run(tmp_path, how):
    import signal
    ctx = _project(tmp_path, source=_OUTPUT_TOOL)
    slow = tmp_path / "slowreceipt"; slow.mkdir()
    (slow / "sitecustomize.py").write_text(
        "import time\nfrom kiss_cli import flowgate\n_orig = flowgate.FlowSession.record_tool_run\n"
        "def slow(self, **kw):\n    (kw['cwd'] / 'runs' / 'recording.flag').touch()\n"
        "    time.sleep(2)\n    return _orig(self, **kw)\n"
        "flowgate.FlowSession.record_tool_run = slow\n")
    proc = _run_tool_process(ctx, pythonpath=[slow], new_session=how == "tree")
    flag, deadline = ctx.project / "runs" / "recording.flag", time.time() + 20
    while not flag.exists():
        assert time.time() < deadline and proc.poll() is None, proc.communicate()
        time.sleep(0.02)
    # The tool has finished; its receipt is being written. The GUI's tree Stop
    # must allow this cleanup as well as a direct SIGTERM to the source CLI.
    if how == "tree":
        execution.terminate_tree(proc)
    else:
        proc.send_signal(signal.SIGTERM)
    out, err = proc.communicate(timeout=20)
    [receipt] = _receipt_docs(ctx)
    assert receipt["execution_status"] == "succeeded" and proc.returncode == 0, err


def test_run_tool_started_after_a_stop_launches_nothing(tmp_path):
    # The compiled app bridges run-tool into a Desktop child outside the CLI's tree:
    # a Stop that lands while it starts up must still keep the model from running.
    ctx = _project(tmp_path, source=_SLOW_TOOL)
    pidfile = ctx.project / "runs" / "pids.txt"
    execution.request_stop(ctx.project)
    proc = _run_tool_process(ctx, pidfile)
    out, err = proc.communicate(timeout=30)
    assert proc.returncode == 3 and b"stopped by the user" in err
    assert not pidfile.exists() and _receipt_docs(ctx) == []
