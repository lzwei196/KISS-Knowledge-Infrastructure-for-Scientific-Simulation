"""Observable execution contracts for the direct-provider and CLI adapters.

Tiny local programs exercise real process launches and signed receipts. These are
execution lifecycle fixtures, not scientific-model or live-provider tests.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from kiss_cli import api, cli, flowgate, paths, project_paths


@pytest.fixture(autouse=True)
def _isolated_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))


def _project(tmp_path, source, *, tool_name="run.py", approved=True, step_env=None):
    project = (tmp_path / "project").resolve()
    root = project / "models" / "M" / "ki"
    (root / "tools").mkdir(parents=True)
    (project / "runs").mkdir()
    (root / "SKILL.md").write_text(
        "# M\n> **MANDATORY EXECUTION POLICY**\n> run the declared tool\n\n")
    (root / "dag.yaml").write_text(
        "outputs:\n- var: discharge\n  validation_rank: 1\n  unit: m3/s\n")
    tool = root / "tools" / tool_name
    tool.write_text(source)
    if tool.suffix != ".py":
        tool.chmod(0o700)
    ki = SimpleNamespace(name="M", root=root)
    shared = paths.KissConfig.default(project)
    shared.python = Path(sys.executable)
    cfg = project_paths.model_config(project, "M", shared)
    (root.parent / paths.CONFIG_NAME).write_text(cfg.dumps(), encoding="utf-8")
    neutral = project_paths.project_config(project, python=sys.executable)
    (project / paths.CONFIG_NAME).write_text(neutral.dumps(), encoding="utf-8")
    fs = flowgate.FlowSession.open(project, {"M": root}, python=sys.executable)
    fs.move("task_received")
    fs.move("kis_resolved", {"selected_kis": ["M"]})
    plan = {
        "schema_version": "1.0", "goal": "Exercise the local execution adapter",
        "selected_kis": ["M"], "created_at": "test", "unresolved_questions": [],
        "scientific_choices": [{"id": "fixture", "kind": "other", "high_impact": False}],
        "steps": [{"id": "M:run", "ki": "M", "tool": str(tool), "kind": "run",
                   "inputs": ["forcing"], "outputs": ["q"], "status": "planned",
                   **({"env": step_env} if step_env else {})}],
    }
    inventory = {"schema_version": "1.0", "items": [{
        "id": "forcing", "required_by": ["M"], "status": "resolved",
        "acceptable_sources": ["local_fixture"], "chosen_source": "local_fixture",
        "local_paths": [], "agent_resolvable": True, "needs_user": False,
    }]}
    assert fs.write_plan(plan, inventory) == []
    if approved:
        fs.flow.approval.approve(project, by="auto")
        fs.reload_artifacts()
        fs.move("plan_written", {"plan_valid": True})
        fs.move("approved", {"approval": "OK"})
        fs.move("execution_started", {"setup_verified": True})
    return SimpleNamespace(project=project, ki=ki, cfg=cfg, flow=fs, tool=tool,
                           plan=plan, inventory=inventory)


def _invoke(adapter, ctx, capsys, *, arguments=(), step="M:run", setup_context=None, **kwargs):
    relative_tool = ctx.tool.relative_to(ctx.ki.root).as_posix()
    if adapter == "direct":
        output = api.execute_tool(
            "run_ki_tool", {"tool_path": relative_tool, "plan_step_id": step,
                            "arguments": list(arguments), **kwargs},
            ctx.ki, ctx.cfg, project_mode=True, flow=ctx.flow, setup_context=setup_context)
        return output, ""
    rc = cli.main(["run-tool", "--project", str(ctx.project), "--step", step,
                   "M", relative_tool, "--", *arguments])
    captured = capsys.readouterr()
    return f"exit_code={rc}\n{captured.out}", captured.err


def _receipts(ctx):
    docs = [json.loads(path.read_text(encoding="utf-8")) for path in
            (ctx.project / ".geoforge" / "receipts" / "model-runs").glob("*.json")]
    assert all(ctx.flow.flow.receipts.verify(ctx.project, doc) for doc in docs)
    return docs


@pytest.mark.parametrize("adapter", ["direct", "cli"])
@pytest.mark.parametrize("refusal", ["planning", "unapproved_step", "changed_plan"])
def test_refusal_never_launches_or_issues_execution_receipt(
        tmp_path, capsys, adapter, refusal):
    ctx = _project(tmp_path, "from pathlib import Path\nPath('launched').write_text('bad')\n",
                   approved=refusal != "planning")
    if refusal == "changed_plan":
        ctx.plan["goal"] = "Changed since consent"
        ctx.flow.flow.plan.write_artifacts(ctx.project, ctx.plan, ctx.inventory)
    step = "M:absent" if refusal == "unapproved_step" else "M:run"
    if adapter == "direct":
        with pytest.raises(api.ToolError):
            _invoke(adapter, ctx, capsys, step=step)
    else:
        out, err = _invoke(adapter, ctx, capsys, step=step)
        assert out.startswith("exit_code=3") and "refused" in err
    assert not (ctx.project / "launched").exists()
    assert _receipts(ctx) == []


@pytest.mark.parametrize("adapter", ["direct", "cli"])
def test_failed_scientific_tool_is_returned_once_without_host_retry(tmp_path, capsys, adapter):
    ctx = _project(tmp_path,
        "from pathlib import Path\nimport sys\n"
        "p = Path('attempts.txt')\np.write_text(p.read_text() + 'x' if p.exists() else 'x')\n"
        "print('diagnose this failure')\nprint('missing forcing column', file=sys.stderr)\n"
        "sys.exit(7)\n")
    output, errors = _invoke(adapter, ctx, capsys)
    assert output.startswith("exit_code=7") and "[RECEIPT]" in output
    assert "diagnose this failure" in output and "missing forcing column" in output
    assert not errors and (ctx.project / "attempts.txt").read_text() == "x"
    receipts = _receipts(ctx)
    assert len(receipts) == 1
    assert receipts[0]["exit_code"] == 7 and receipts[0]["plan_step_id"] == "M:run"
    assert receipts[0]["approval_sha256"] == ctx.flow.approval_id
    assert receipts[0]["validation"]["status"] != "passed"
    assert ctx.flow.state.value == "EXECUTING"


@pytest.mark.parametrize("adapter", ["direct", "cli"])
def test_execution_cannot_gain_a_receipt_if_approval_changes_during_run(
        tmp_path, capsys, adapter):
    ctx = _project(tmp_path,
        "from pathlib import Path\n"
        "p = Path('attempts.txt'); p.write_text(p.read_text() + 'x' if p.exists() else 'x')\n"
        "Path('runs/plan.json').write_text('{}')\nprint('ran but changed the plan')\n")
    if adapter == "direct":
        with pytest.raises(api.ToolError, match="receipt cannot be written") as error:
            _invoke(adapter, ctx, capsys)
        assert "ran but changed the plan" in str(error.value)
    else:
        output, errors = _invoke(adapter, ctx, capsys)
        assert output.startswith("exit_code=3") and "ran but changed the plan" in output
        assert "receipt NOT written" in errors
    assert (ctx.project / "attempts.txt").read_text() == "x"
    assert _receipts(ctx) == []


@pytest.mark.parametrize("adapter", ["direct", "cli"])
def test_missing_interpreter_returns_a_signed_not_launched_attempt(tmp_path, capsys, adapter):
    ctx = _project(tmp_path, "from pathlib import Path\nPath('launched').write_text('bad')\n")
    ctx.cfg.python = ctx.project / "absent-interpreter"
    (ctx.ki.root.parent / paths.CONFIG_NAME).write_text(ctx.cfg.dumps(), encoding="utf-8")
    output, errors = _invoke(adapter, ctx, capsys)
    assert "Could not launch KI tool" in output + errors
    assert "absent-interpreter" in output + errors
    assert "[RECEIPT]" in output
    if adapter == "cli":
        assert output.startswith("exit_code=1")
    else:
        assert output.startswith("Could not launch KI tool")
    assert not (ctx.project / "launched").exists()
    receipts = _receipts(ctx)
    assert len(receipts) == 1
    receipt = receipts[0]
    assert receipt["execution_status"] == "not_launched"
    assert receipt["exit_code"] is None and receipt["process_started"] is False
    assert receipt["binary_actually_ran"] is False
    assert receipt["validation"]["status"] == "failed"
    assert "Could not launch KI tool" in Path(receipt["stdout_log"]).read_text(encoding="utf-8")


@pytest.mark.parametrize("adapter", ["direct", "cli"])
@pytest.mark.parametrize("failure_at", ["flow_recording", "receipt_writer"])
def test_receipt_io_failure_preserves_process_diagnostics_without_retry(
        tmp_path, capsys, monkeypatch, adapter, failure_at):
    ctx = _project(tmp_path,
        "from pathlib import Path\nimport sys\n"
        "p = Path('attempts.txt'); p.write_text(p.read_text() + 'x' if p.exists() else 'x')\n"
        "print('useful stdout evidence')\nprint('useful stderr evidence', file=sys.stderr)\n")
    recording_attempts = []

    def unavailable(*args, **kwargs):
        recording_attempts.append(kwargs)
        raise OSError("fixture receipt storage unavailable")

    if failure_at == "flow_recording":
        monkeypatch.setattr(flowgate.FlowSession, "record_tool_run", unavailable)
    else:
        monkeypatch.setattr(ctx.flow.flow.receipts, "record_run", unavailable)
    if adapter == "direct":
        with pytest.raises(api.ToolError, match="receipt NOT written") as error:
            _invoke(adapter, ctx, capsys)
        message = str(error.value)
        assert "exit_code=0" in message
    else:
        output, errors = _invoke(adapter, ctx, capsys)
        assert output.startswith("exit_code=3") and "receipt NOT written" in errors
        message = output + errors
    assert "fixture receipt storage unavailable" in message
    assert "useful stdout evidence" in message and "useful stderr evidence" in message
    assert len(recording_attempts) == 1
    assert (ctx.project / "attempts.txt").read_text() == "x"
    assert _receipts(ctx) == []


@pytest.mark.parametrize("adapter", ["direct", "cli"])
def test_child_gets_sanitized_environment_and_signed_step_values(
        tmp_path, capsys, monkeypatch, adapter):
    secret_names = ["PRIVATE_API_KEY", "PRIVATE_TOKEN", "PRIVATE_SECRET",
                    "PRIVATE_PASSWORD", "PRIVATE_CREDENTIAL"]
    for name in secret_names:
        monkeypatch.setenv(name, "fixture-secret")
    monkeypatch.setenv("ORDINARY_MODEL_SETTING", "retained")
    ctx = _project(tmp_path,
        "import os, json\nfrom pathlib import Path\n"
        "p = Path(os.environ['MODEL_OUTPUT']); p.parent.mkdir(parents=True, exist_ok=True)\n"
        "p.write_text(json.dumps({'keys': [k for k in os.environ if k.startswith('PRIVATE_')], "
        "'ordinary': os.environ['ORDINARY_MODEL_SETTING'], 'root': os.environ['KISS_ROOT'], "
        "'ki': os.environ['MODEL_KI_ROOT'], 'cwd': str(Path.cwd())}))\n",
        step_env={"MODEL_OUTPUT": "${PROJECT}/outputs/env.json", "MODEL_KI_ROOT": "${KI_ROOT}"})
    output, errors = _invoke(adapter, ctx, capsys)
    assert output.startswith("exit_code=0") and not errors
    observed = json.loads((ctx.project / "outputs" / "env.json").read_text(encoding="utf-8"))
    # KISS_ROOT selects the exact KI config; tool cwd remains the project.
    assert observed == {"keys": [], "ordinary": "retained", "root": str(ctx.ki.root.parent),
                        "ki": str(ctx.ki.root), "cwd": str(ctx.project)}
    assert len(_receipts(ctx)) == 1


@pytest.mark.parametrize("adapter", ["direct", "cli"])
def test_only_direct_adapter_applies_the_selected_provider_proxy(
        tmp_path, capsys, monkeypatch, adapter):
    from kiss_cli import settings

    proxy_calls = []

    def provider_proxy(provider_id, env):
        proxy_calls.append(provider_id)
        return {**env, "FIXTURE_PROVIDER_PROXY": provider_id}

    monkeypatch.delenv("FIXTURE_PROVIDER_PROXY", raising=False)
    monkeypatch.setattr(settings, "with_provider_proxy", provider_proxy)
    ctx = _project(tmp_path,
        "from pathlib import Path\nimport os\n"
        "Path('observed-proxy.txt').write_text(os.environ.get('FIXTURE_PROVIDER_PROXY', 'none'))\n")
    output, errors = _invoke(adapter, ctx, capsys, setup_context={"provider_id": "deepseek"})
    assert output.startswith("exit_code=0") and not errors
    expected = "deepseek" if adapter == "direct" else "none"
    assert (ctx.project / "observed-proxy.txt").read_text() == expected
    assert proxy_calls == (["deepseek"] if adapter == "direct" else [])


def test_direct_timeout_is_an_interrupted_attempt_without_a_retry(tmp_path, capsys):
    ctx = _project(tmp_path,
        "import time\nfrom pathlib import Path\n"
        "p = Path('attempts.txt'); p.write_text(p.read_text() + 'x' if p.exists() else 'x')\n"
        "print('started and waiting', flush=True)\ntime.sleep(3)\n"
        "Path('finished').write_text('finished')\n")
    output, _ = _invoke("direct", ctx, capsys, timeout_seconds=1)
    assert output.startswith("TIMEOUT after 1s") and "started and waiting" in output
    assert (ctx.project / "attempts.txt").read_text() == "x"
    assert not (ctx.project / "finished").exists()
    receipts = _receipts(ctx)
    assert len(receipts) == 1 and receipts[0]["exit_code"] is None
    assert receipts[0]["validation"]["status"] != "passed"


def test_cli_does_not_adopt_the_direct_callers_one_second_timeout(tmp_path, capsys):
    ctx = _project(tmp_path,
        "import time\nfrom pathlib import Path\ntime.sleep(1.1)\n"
        "Path('finished').write_text('finished')\n")
    output, errors = _invoke("cli", ctx, capsys)
    assert output.startswith("exit_code=0") and not errors
    assert (ctx.project / "finished").read_text() == "finished"
    assert len(_receipts(ctx)) == 1


def test_direct_tool_may_use_a_project_subdirectory_as_cwd(tmp_path, capsys):
    ctx = _project(tmp_path, "from pathlib import Path\nprint(Path.cwd())\n")
    cwd = ctx.project / "inputs" / "case"
    cwd.mkdir(parents=True)
    output, _ = _invoke("direct", ctx, capsys, cwd="inputs/case")
    assert str(cwd) in output and _receipts(ctx)[0]["cwd"] == str(cwd)


def test_direct_tool_rejects_an_argument_outside_project_and_ki(tmp_path, capsys):
    ctx = _project(tmp_path, "from pathlib import Path\nPath('launched').write_text('bad')\n")
    with pytest.raises(api.ToolError, match="argument path escapes"):
        _invoke("direct", ctx, capsys, arguments=[str(tmp_path / "unapproved-input.csv")])
    assert not (ctx.project / "launched").exists()
    assert _receipts(ctx) == []


@pytest.mark.skipif(os.name == "nt", reason="POSIX executable-shell adapter contract")
def test_cli_accepts_shipped_shell_tool_but_direct_adapter_remains_python_only(tmp_path, capsys):
    ctx = _project(tmp_path, "#!/bin/sh\nprintf shell-ran > launched\n", tool_name="run.sh")
    with pytest.raises(api.ToolError, match="only shipped Python"):
        _invoke("direct", ctx, capsys)
    assert not (ctx.project / "launched").exists() and _receipts(ctx) == []
    output, errors = _invoke("cli", ctx, capsys)
    assert output.startswith("exit_code=0") and not errors
    assert (ctx.project / "launched").read_text() == "shell-ran"
    assert len(_receipts(ctx)) == 1
