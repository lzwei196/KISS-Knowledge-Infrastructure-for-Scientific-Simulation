"""An approved KI wrapper may name its exact checked external executable."""
from __future__ import annotations

import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from kiss_cli import api, cli, execution, flowgate, ki_guard, paths, project_paths
from kiss_cli import project_verification as pv
from kiss_cli.catalog import KI
from kiss_cli.manifest import Manifest


@pytest.fixture
def case(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    project = tmp_path / "project"
    root = project / "models/CRHM/ki"
    (root / "tools").mkdir(parents=True)
    (project / "runs").mkdir()
    external = tmp_path / "old-install/crhm.exe"
    external.parent.mkdir()
    external.write_bytes(b"fixture native product, never executed")
    external.chmod(0o755)
    binaries = tmp_path / "shared/binaries"
    alias = binaries / "crhm/build/crhm"
    alias.parent.mkdir(parents=True)
    alias.symlink_to(external)
    (root / "SKILL.md").write_text("# CRHM fixture\n")
    (root / "preflight_check.py").write_text("print('Harmless exact runtime fixture check')\n")
    (root / "kiss.yaml").write_text("kiss_manifest_version: 1\nmodel: CRHM\n")
    (root / "knowledge_infrastructure.yaml").write_text(
        "model:\n  binary:\n    path: " + json.dumps(str(alias)) + "\n", encoding="utf-8")
    tool = root / "tools/run.py"
    # It records arguments, so the test launches real Python without a model run.
    tool.write_text("import json,sys\nfrom pathlib import Path\n"
                    "Path('launched.json').write_text(json.dumps(sys.argv[1:]))\n")
    cfg = project_paths.model_config(project, "CRHM", paths.KissConfig.default(project))
    cfg.python = sys.executable
    cfg.roles["binaries"] = binaries
    (root.parent / paths.CONFIG_NAME).write_text(cfg.dumps(), encoding="utf-8")
    (project / paths.CONFIG_NAME).write_text(
        project_paths.project_config(project, python=sys.executable).dumps(), encoding="utf-8")
    ki_guard.enroll(root)
    ki = KI("CRHM", root)
    fs = flowgate.FlowSession.open(project, {"CRHM": root}, python=sys.executable)
    fs.move("task_received")
    fs.move("kis_resolved", {"selected_kis": ["CRHM"]})
    plan = {"schema_version": "1.0", "goal": "Exercise an exact runtime reference", "created_at": "test",
            "selected_kis": ["CRHM"], "unresolved_questions": [], "scientific_choices": [],
            "steps": [{"id": "CRHM:run", "ki": "CRHM", "tool": str(tool), "kind": "run",
                       "inputs": [], "outputs": [], "status": "planned"}]}
    assert fs.write_plan(plan, {"schema_version": "1.0", "items": []}) == []
    fs.flow.approval.approve(project, by="user")
    fs.reload_artifacts()
    fs.move("plan_written", {"plan_valid": True})
    fs.move("approved", {"approval": "OK"})
    fs.move("execution_started", {"setup_verified": True})
    return SimpleNamespace(project=project, ki=ki, cfg=cfg, flow=fs, tool=tool,
                           alias=alias, external=external, binaries=binaries)


def verify(case):
    result = pv.verify(case.project, case.ki, Manifest.load(case.ki.root / "kiss.yaml"))
    assert result["ok"], result
    return result["receipt"]


def invoke(case, adapter, arguments, capsys):
    if adapter == "api":
        return api.execute_tool("run_ki_tool", {"tool_path": "tools/run.py", "plan_step_id": "CRHM:run",
            "arguments": arguments}, case.ki, case.cfg, project_mode=True, flow=case.flow)
    result = cli.main(["run-tool", "--project", str(case.project), "--step", "CRHM:run",
                       "CRHM", "tools/run.py", "--", *arguments])
    return result, capsys.readouterr().err


def denied(case, adapter, arguments, capsys):
    if adapter == "api":
        with pytest.raises(api.ToolError):
            invoke(case, adapter, arguments, capsys)
    else:
        result, error = invoke(case, adapter, arguments, capsys)
        assert result == 3, error
    assert not (case.project / "launched.json").exists()
    assert not list((case.project / ".geoforge/receipts/model-runs").glob("*.json"))


@pytest.mark.parametrize("adapter", ["api", "cli"])
@pytest.mark.parametrize("form", ["separate", "equals"])
def test_checked_external_file_alias_is_allowed_as_named_runtime_only(case, capsys, monkeypatch, adapter, form):
    verify(case)
    monkeypatch.setattr(pv.install, "run_preflight", lambda *a, **k: pytest.fail("dispatch must not rerun checks"))
    arguments = ["--crhm_exe", str(case.alias)] if form == "separate" else ["--crhm_exe=" + str(case.alias)]
    result = invoke(case, adapter, arguments, capsys)
    assert (result[0] == 0) if adapter == "cli" else result.startswith("exit_code=0")
    assert json.loads((case.project / "launched.json").read_text()) == arguments


@pytest.mark.parametrize("adapter", ["api", "cli"])
@pytest.mark.parametrize("kind", ["positional", "output", "output-equals", "output-exe", "wrong-model-option",
                                   "directory", "sibling", "shared-output", "undeclared", "external-target",
                                   "bare-parent", "bare-link", "home"])
def test_runtime_capability_does_not_grant_shared_outputs_or_subtrees(case, capsys, adapter, kind):
    verify(case)
    undeclared = case.binaries / "other.exe"
    undeclared.write_bytes(b"not the declared product")
    undeclared.chmod(0o755)
    (case.project / "output-link").symlink_to(case.external)
    arguments = {"positional": [str(case.alias)], "output": ["--output", str(case.alias)],
                 "output-equals": ["--output=" + str(case.alias)],
                 "output-exe": ["--output_exe", str(case.alias)],
                 "wrong-model-option": ["--vic_exe", str(case.alias)],
                 "directory": ["--crhm_exe", str(case.alias.parent)],
                 "sibling": ["--crhm_exe", str(case.external.with_name("other.exe"))],
                 "undeclared": ["--binary", str(undeclared)],
                 "external-target": ["--binary", str(case.external)],
                 "bare-parent": ["--output", ".."],
                 "bare-link": ["--output", "output-link"],
                 "home": ["--output", "~"],
                 "shared-output": ["--output", str(case.binaries / "result.csv")]}[kind]
    denied(case, adapter, arguments, capsys)


@pytest.mark.parametrize("adapter", ["api", "cli"])
@pytest.mark.parametrize("kind", ["missing", "stale-cfg", "retargeted", "legacy-receipt", "unsigned"])
def test_external_runtime_requires_current_signed_resolved_binding(case, capsys, adapter, kind):
    doc = verify(case)
    receipt = pv._receipt_path(case.project, "CRHM")
    if kind == "missing":
        receipt.unlink()
    elif kind == "stale-cfg":
        case.cfg.roles["binaries"] = case.binaries.parent / "different"
        (case.ki.root.parent / paths.CONFIG_NAME).write_text(case.cfg.dumps(), encoding="utf-8")
    elif kind == "retargeted":
        other = case.external.with_name("other.exe")
        other.write_bytes(b"unverified different product")
        other.chmod(0o755)
        case.alias.unlink()
        case.alias.symlink_to(other)
    elif kind == "legacy-receipt":
        doc.pop("declared_runtime_bindings", None)
        receipt.write_text(json.dumps(case.flow.flow.receipts.sign(case.project, doc)), encoding="utf-8")
    else:
        receipt.write_text(json.dumps({"state": "verified", "ok": True}), encoding="utf-8")
    denied(case, adapter, ["--crhm_exe", str(case.alias)], capsys)


@pytest.mark.parametrize("adapter", ["api", "cli"])
def test_old_policy_requests_normal_project_reverification_before_dispatch(case, capsys, adapter):
    doc = verify(case)
    doc.pop("declared_runtime_bindings", None)
    doc["policy"] = "project-runtime-preflight-v2-scratch"
    pv._receipt_path(case.project, "CRHM").write_text(
        json.dumps(case.flow.flow.receipts.sign(case.project, doc)), encoding="utf-8")
    assert not pv.status(case.project, case.ki)["can_run"]
    arguments = ["--output", "outputs/new.csv"]
    denied(case, adapter, arguments, capsys)
    verify(case)
    result = invoke(case, adapter, arguments, capsys)
    assert (result[0] == 0) if adapter == "cli" else result.startswith("exit_code=0")


@pytest.mark.parametrize("adapter", ["api", "cli"])
def test_other_selected_binary_role_cannot_adopt_a_declared_outside_file(case, capsys, adapter):
    case.cfg.roles["binaries"] = case.project.parent / "other-model/binaries"
    (case.ki.root.parent / paths.CONFIG_NAME).write_text(case.cfg.dumps(), encoding="utf-8")
    verify(case)
    denied(case, adapter, ["--binary", str(case.alias)], capsys)


@pytest.mark.parametrize("adapter", ["api", "cli"])
def test_model_alias_cannot_promote_an_interpreter_target(case, capsys, adapter):
    interpreter = case.external.with_name("python.exe")
    interpreter.write_bytes(b"interpreter fixture, never executed")
    interpreter.chmod(0o755)
    case.alias.unlink()
    case.alias.symlink_to(interpreter)
    assert verify(case)["declared_runtime_bindings"] == {}
    denied(case, adapter, ["--binary", str(case.alias)], capsys)


def test_legacy_nonmaterialized_route_cannot_borrow_external_runtime_capability(case):
    from kiss_cli import runtime_arguments
    legacy = case.project.parent / "legacy-ki"
    legacy.mkdir()
    (legacy / "knowledge_infrastructure.yaml").write_text(
        (case.ki.root / "knowledge_infrastructure.yaml").read_text(), encoding="utf-8")
    with pytest.raises(ValueError, match="exact models"):
        runtime_arguments.validate(project=case.project, ki="CRHM", ki_root=legacy,
            cfg=case.cfg, arguments=["--binary", str(case.alias)], cwd=case.project, allow_runtime=True)


def test_alias_retargeted_during_verification_cannot_get_a_pass(case, monkeypatch):
    original = pv.software_verification.requirements
    def retarget(*args, **kwargs):
        other = case.external.with_name("other.exe")
        other.write_bytes(b"changed during check")
        other.chmod(0o755)
        case.alias.unlink()
        case.alias.symlink_to(other)
        return original(*args, **kwargs)
    monkeypatch.setattr(pv.software_verification, "requirements", retarget)
    result = pv.verify(case.project, case.ki, Manifest.load(case.ki.root / "kiss.yaml"))
    assert not result["ok"]
    assert not pv.status(case.project, case.ki)["can_run"]
