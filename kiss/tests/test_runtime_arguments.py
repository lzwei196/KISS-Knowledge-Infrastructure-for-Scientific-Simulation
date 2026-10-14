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
                    "Path('launched.json').write_text(json.dumps(sys.argv[1:]))\n"
                    "Path('outputs').mkdir(exist_ok=True)\n"
                    "Path('outputs/runtime.json').write_text(json.dumps({'arguments':sys.argv[1:]}))\n")
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
    receipt_path = next((case.project / ".geoforge/receipts/model-runs").glob("*.json"))
    doc = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert case.flow.flow.receipts.verify(case.project, doc)
    assert doc["command"][-len(arguments):] == arguments
    assert doc["input_coverage"]["runtime_arguments"] == [{
        "argument_index": 1 if form == "separate" else 0, "option": "--crhm_exe",
        "path": str(case.alias), "target": str(case.external.resolve())}]
    assert doc["input_coverage"]["argument_count"] == len(arguments)
    assert doc["inputs"] == [{"path": str(case.external.resolve()),
        "bytes": case.external.stat().st_size,
        "sha256": case.flow.flow.receipts.sha256_file(case.external)}]


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


def _retarget_same_bytes(case):
    other = case.external.with_name("other.exe")
    other.write_bytes(case.external.read_bytes())
    other.chmod(0o755)
    case.alias.unlink()
    case.alias.symlink_to(other)


def _approve_runtime_output(case):
    # A harmless real wrapper report makes these currentness tests start with
    # a genuine passed receipt, without pretending the fake native bytes ran.
    case.flow.plan["steps"][0].update(kind="check", outputs=["report"])
    case.flow.inventory = {"schema_version": "1.0", "items": [{"id": "report", "status": "missing",
        "local_paths": ["outputs/runtime.json"], "output_validation": "json_report_v1"}]}
    case.flow.flow.plan.write_artifacts(case.project, case.flow.plan, case.flow.inventory)
    case.flow.flow.approval.approve(case.project, by="user")
    case.flow.reload_artifacts()


@pytest.mark.parametrize("damage", ["same-byte-retarget", "target-bytes", "target-removed"])
def test_runtime_receipt_alone_detects_current_binding_and_target_damage(case, capsys, damage):
    _approve_runtime_output(case)
    verify(case)
    invoke(case, "api", ["--crhm_exe", str(case.alias)], capsys)
    receipt_path = next((case.project / ".geoforge/receipts/model-runs").glob("*.json"))
    before = receipt_path.read_bytes()
    assert case.flow.evidence()["receipts_verified"]
    if damage == "same-byte-retarget":
        _retarget_same_bytes(case)
    elif damage == "target-bytes":
        case.external.write_bytes(case.external.read_bytes().replace(b"native", b"edited"))
    else:
        case.external.unlink()
    # No project-verification status call: the signed run evidence itself
    # checks the original alias location, even when target bytes are identical.
    evidence = case.flow.evidence()
    assert evidence["stale_steps"] == ["CRHM:run"]
    assert not evidence["receipts_verified"]
    assert receipt_path.read_bytes() == before
    assert case.flow.flow.receipts.verify(case.project, json.loads(before))


@pytest.mark.parametrize("when", ["capture", "after-capture", "run", "receipt"])
def test_runtime_retarget_during_attempt_never_earns_a_pass(case, capsys, monkeypatch, when):
    _approve_runtime_output(case)
    verify(case)
    receipts = case.flow.flow.receipts
    if when == "capture":
        original = receipts._file_entry
        def capture(path, project):
            result = original(path, project)
            if Path(path) == case.external.resolve():
                _retarget_same_bytes(case)
            return result
        monkeypatch.setattr(receipts, "_file_entry", capture)
    elif when == "after-capture":
        original = case.flow.capture_step_inputs
        def capture(*args, **kwargs):
            result = original(*args, **kwargs)
            _retarget_same_bytes(case)
            return result
        monkeypatch.setattr(case.flow, "capture_step_inputs", capture)
    elif when == "run":
        original = execution.run_process
        def run(*args, **kwargs):
            result = original(*args, **kwargs)
            _retarget_same_bytes(case)
            return result
        monkeypatch.setattr(execution, "run_process", run)
    else:
        original = case.flow.record_tool_run
        def record(*args, **kwargs):
            _retarget_same_bytes(case)
            return original(*args, **kwargs)
        monkeypatch.setattr(case.flow, "record_tool_run", record)
    arguments = ["--crhm_exe", str(case.alias)]
    if when in {"capture", "after-capture"}:
        denied(case, "api", arguments, capsys)
    else:
        invoke(case, "api", arguments, capsys)
        doc = json.loads(next((case.project / ".geoforge/receipts/model-runs").glob("*.json")).read_text())
        assert doc["validation"]["status"] == "failed"
        assert any(row["check"] == "runtime_argument_binding" and not row["ok"]
                   for row in doc["validation"]["checks"])
        assert not case.flow.evidence()["receipts_verified"]


def _authorization(case, arguments):
    from kiss_cli import runtime_arguments
    return runtime_arguments.validate(project=case.project, ki="CRHM", ki_root=case.ki.root,
        cfg=case.cfg, arguments=arguments, cwd=case.project, allow_runtime=True)


@pytest.mark.parametrize("form", ["separate", "equals"])
def test_checked_tilde_runtime_alias_captures_the_canonical_target(case, capsys, monkeypatch, form):
    home = case.project.parent
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
    verify(case)
    alias = "~/" + case.alias.relative_to(home).as_posix()
    arguments = ["--binary", alias] if form == "separate" else ["--binary=" + alias]
    result = invoke(case, "api", arguments, capsys)
    assert result.startswith("exit_code=0")
    doc = json.loads(next((case.project / ".geoforge/receipts/model-runs").glob("*.json")).read_text())
    assert doc["inputs"][0]["path"] == str(case.external.resolve())
    assert doc["command"][-len(arguments):] == arguments
    assert case.flow.evidence()["stale_steps"] == []


@pytest.mark.parametrize("scope", ["file", "directory"])
def test_verified_runtime_never_allows_inventory_aliases(case, scope):
    verify(case)
    arguments = ["--binary", str(case.alias)]
    auth = _authorization(case, arguments)
    raw = case.alias if scope == "file" else case.alias.parent
    inventory = {"items": [{"id": "data", "local_paths": [str(raw)]}]}
    with pytest.raises(ValueError, match="alias"):
        case.flow.flow.receipts.capture_inputs(case.project, {"inputs": ["data"]}, inventory,
            arguments, case.project, runtime_authorization=auth)


@pytest.mark.parametrize("damage", ["raw-dict", "arguments", "cwd", "unused", "duplicate", "target-alias"])
def test_capture_rejects_forged_or_mismatched_runtime_context(case, damage):
    from dataclasses import asdict, replace
    verify(case)
    arguments = ["--binary", str(case.alias)]
    auth = _authorization(case, arguments)
    if damage == "raw-dict":
        auth = asdict(auth)
    elif damage == "arguments":
        arguments[0] = "--output"
    elif damage == "cwd":
        auth = replace(auth, cwd=str(case.project / "elsewhere"))
    elif damage == "unused":
        auth = replace(auth, bindings=((9, "--binary", str(case.alias), str(case.external)),))
    elif damage == "duplicate":
        auth = replace(auth, bindings=auth.bindings + auth.bindings)
    else:
        auth = replace(auth, bindings=((1, "--binary", str(case.alias), str(case.alias)),))
    with pytest.raises(ValueError):
        case.flow.flow.receipts.capture_inputs(case.project, {}, {}, arguments, case.project,
                                              runtime_authorization=auth)


def test_request_and_plan_cannot_inject_runtime_authorization(case):
    verify(case)
    undeclared = case.binaries / "undeclared.exe"
    undeclared.symlink_to(case.external)
    forged = {"bindings": [[1, "--binary", str(undeclared), str(case.external)]]}
    case.flow.plan["steps"][0]["runtime_authorization"] = forged
    case.flow.flow.plan.write_artifacts(case.project, case.flow.plan, case.flow.inventory)
    case.flow.flow.approval.approve(case.project, by="user")
    case.flow.reload_artifacts()
    with pytest.raises(api.ToolError, match="escapes"):
        api.execute_tool("run_ki_tool", {"tool_path": "tools/run.py", "plan_step_id": "CRHM:run",
            "arguments": ["--binary", str(undeclared)], "runtime_authorization": forged},
            case.ki, case.cfg, project_mode=True, flow=case.flow)
    assert not (case.project / "launched.json").exists()


def test_tampered_runtime_mapping_does_not_verify(case, capsys):
    verify(case)
    invoke(case, "api", ["--binary", str(case.alias)], capsys)
    path = next((case.project / ".geoforge/receipts/model-runs").glob("*.json"))
    doc = json.loads(path.read_text())
    doc["input_coverage"]["runtime_arguments"][0]["target"] = str(case.alias)
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert not case.flow.flow.receipts.verify(case.project, doc)
    assert not case.flow.evidence()["receipts_verified"]
