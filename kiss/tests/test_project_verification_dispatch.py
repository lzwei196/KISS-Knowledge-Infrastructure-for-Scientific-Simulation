"""Scientific dispatch cannot inherit a different project's installation pass."""
from __future__ import annotations

import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from kiss_cli import api, calibration, cli, execution, flowgate, ki_guard, paths, project_paths
from kiss_cli import project_verification
from kiss_cli.catalog import KI
from kiss_cli.manifest import Manifest


@pytest.fixture
def case(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    project = tmp_path / "project"
    root = project / "models" / "M" / "ki"
    (root / "tools").mkdir(parents=True)
    (project / "runs").mkdir()
    (root / "SKILL.md").write_text("# Fixture KI\n")
    (root / "preflight_check.py").write_text("print('Harmless project preflight passed')\n")
    (root / "kiss.yaml").write_text("kiss_manifest_version: 1\nmodel: M\n")
    tool = root / "tools" / "run.py"
    tool.write_text("from pathlib import Path\nPath('launched').write_text('fresh run')\n")
    ki_guard.enroll(root)
    ki = KI("M", root)
    cfg = project_paths.model_config(project, "M", paths.KissConfig.default(project))
    cfg.python = sys.executable
    (root.parent / paths.CONFIG_NAME).write_text(cfg.dumps(), encoding="utf-8")
    (project / paths.CONFIG_NAME).write_text(
        project_paths.project_config(project, python=sys.executable).dumps(), encoding="utf-8")
    fs = flowgate.FlowSession.open(project, {"M": root}, python=sys.executable)
    fs.move("task_received")
    fs.move("kis_resolved", {"selected_kis": ["M"]})
    plan = {"schema_version": "1.0", "goal": "Run the local fixture", "selected_kis": ["M"],
            "created_at": "test", "unresolved_questions": [], "scientific_choices": [],
            "steps": [{"id": "M:run", "ki": "M", "tool": str(tool), "kind": "run",
                       "command": [], "cwd": ".",
                       "inputs": [], "outputs": [], "status": "planned"}]}
    inventory = {"schema_version": "1.0", "items": []}
    assert fs.write_plan(plan, inventory) == []
    fs.flow.approval.approve(project, by="user")
    fs.reload_artifacts()
    fs.move("plan_written", {"plan_valid": True})
    fs.move("approved", {"approval": "OK"})
    # A retained EXECUTING state is deliberately not enough authorization.
    fs.move("execution_started", {"setup_verified": True})
    return SimpleNamespace(project=project, ki=ki, cfg=cfg, flow=fs, tool=tool,
                           manifest=Manifest.load(root / "kiss.yaml"))


def verified(case):
    result = project_verification.verify(case.project, case.ki, case.manifest)
    assert result["ok"], result
    return project_verification._receipt_path(case.project, "M")


def damage(case, kind):
    if kind == "missing":
        return
    receipt = verified(case)
    if kind == "runtime-changed":
        case.cfg.roles["binaries"] = case.project / "different-binaries"
        (case.ki.root.parent / paths.CONFIG_NAME).write_text(case.cfg.dumps(), encoding="utf-8")
    elif kind == "unsigned":
        receipt.write_text(json.dumps({"state": "verified", "ok": True}), encoding="utf-8")
    elif kind == "tampered":
        value = json.loads(receipt.read_text(encoding="utf-8"))
        value["runtime_identity"] = "0" * 64
        receipt.write_text(json.dumps(value), encoding="utf-8")
    elif kind == "other-project":
        value = json.loads(receipt.read_text(encoding="utf-8"))
        value["project"] = str(case.project.parent / "another-project")
        receipt.write_text(json.dumps(case.flow.flow.receipts.sign(case.project, value)), encoding="utf-8")


def invoke(case, adapter, capsys):
    if adapter == "api":
        return api.execute_tool("run_ki_tool", {"tool_path": "tools/run.py", "plan_step_id": "M:run"},
                                case.ki, case.cfg, project_mode=True, flow=case.flow)
    result = cli.main(["run-tool", "--project", str(case.project), "--step", "M:run", "M", "tools/run.py"])
    captured = capsys.readouterr()
    return result, captured.err


@pytest.mark.parametrize("adapter", ["api", "cli"])
@pytest.mark.parametrize("kind", ["missing", "runtime-changed", "unsigned", "tampered", "other-project"])
def test_missing_stale_or_forged_project_verification_blocks_real_dispatch(case, capsys, adapter, kind):
    damage(case, kind)
    approval = case.flow.approval_id
    if adapter == "api":
        with pytest.raises(api.ToolError, match="project KI verification required"):
            invoke(case, adapter, capsys)
    else:
        result, error = invoke(case, adapter, capsys)
        assert result == 3 and "project KI verification required" in error
    assert not (case.project / "launched").exists()
    assert not list((case.project / ".geoforge/receipts/model-runs").glob("*.json"))
    assert case.flow.approval_id == approval


@pytest.mark.parametrize("adapter", ["api", "cli"])
def test_valid_project_preflight_allows_exact_tool_without_automatic_recheck(case, capsys, monkeypatch, adapter):
    verified(case)
    monkeypatch.setattr(project_verification.install, "run_preflight", Mock(side_effect=AssertionError("no implicit preflight")))
    result = invoke(case, adapter, capsys)
    assert (result[0] == 0) if adapter == "cli" else result.startswith("exit_code=0")
    assert (case.project / "launched").read_text() == "fresh run"


def test_new_receipt_for_changed_runtime_does_not_authorize_already_selected_old_runtime(case, monkeypatch):
    verified(case)
    snapshot = flowgate._snapshot

    def change_after_runtime_selection(*args, **kwargs):
        case.cfg.roles["binaries"] = case.project / "newly-verified-binaries"
        (case.ki.root.parent / paths.CONFIG_NAME).write_text(case.cfg.dumps(), encoding="utf-8")
        verified(case)
        return snapshot(*args, **kwargs)

    monkeypatch.setattr(flowgate, "_snapshot", change_after_runtime_selection)
    with pytest.raises(api.ToolError, match="project KI verification required"):
        api.execute_tool("run_ki_tool", {"tool_path": "tools/run.py", "plan_step_id": "M:run"},
                         case.ki, case.cfg, project_mode=True, flow=case.flow)
    assert project_verification.status(case.project, case.ki)["ok"]
    assert not (case.project / "launched").exists()


@pytest.mark.parametrize("kind", ["missing", "runtime-changed", "unsigned", "valid"])
def test_calibration_has_the_same_project_verification_boundary(case, monkeypatch, kind):
    if kind == "valid":
        verified(case)
    else:
        damage(case, kind)
    binding = {"obs_shape_by_var": {"Q": "point_time_series"}, "algorithm": "dds", "budget": 2,
               "seed": 0, "determining_metric": None, "expected_case_id": "fixture"}
    adapter = SimpleNamespace(runner_path=case.project / "calibration/kis/M/tools/calib_run.py")
    monkeypatch.setattr(calibration, "ensure_project", lambda *_args: None)
    monkeypatch.setattr(calibration, "prepare_invocation", lambda *_args: (binding, adapter))
    launch = Mock(return_value={"report": {"status": "completed"}})
    monkeypatch.setattr(calibration, "run_project", launch)
    # The receipt gate is also required without a Flow object; project_mode is
    # the established legacy API adapter surface, not a receipt exemption.
    if kind == "valid":
        result = api.execute_tool("run_calibration", {}, case.ki, case.cfg, project_mode=True)
        assert json.loads(result)["status"] == "completed"
        launch.assert_called_once()
    else:
        with pytest.raises(api.ToolError, match="project|Project"):
            api.execute_tool("run_calibration", {}, case.ki, case.cfg, project_mode=True)
        launch.assert_not_called()


def test_missing_receipt_does_not_block_planning_inspection(case):
    case.flow.ctx.state = case.flow.flow.states.State.PLANNING
    assert "Fixture KI" in api.execute_tool("read_ki_file", {"path": "SKILL.md"},
                                             case.ki, case.cfg, project_mode=True, flow=case.flow)


def test_nonmaterialized_legacy_tool_keeps_explicit_runtime_fallback(tmp_path, monkeypatch):
    project = tmp_path / "legacy-project"
    root = tmp_path / "legacy-ki"
    project.mkdir()
    (root / "tools").mkdir(parents=True)
    tool = root / "tools/run.py"
    tool.write_text("from pathlib import Path\nPath('legacy-launched').write_text('ok')\n")
    cfg = paths.KissConfig.default(project)
    cfg.python = sys.executable
    result = execution.execute_ki_tool(flow=None, cfg=cfg, project=project, ki="Legacy", ki_root=root,
        tool=tool, arguments=[], cwd=project, plan_step_id=None, python_tool=True, timeout=5)
    assert result.exit_code == 0
    assert (project / "legacy-launched").read_text() == "ok"
