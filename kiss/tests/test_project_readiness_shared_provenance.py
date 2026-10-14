"""A stale shared KI cannot stand in for an exact project preflight.

The source, old shared KI, fresh project projection and verification receipts
are real temporary fixtures. Only provider calls/flow transitions are doubled;
harmless native Python preflights actually execute. No model is run.
"""
import json
from dataclasses import replace
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from kiss_cli import api, catalog, flowrun, gui, ki_guard, ki_updates, paths
from kiss_cli import project_verification, setup, software_verification
from kiss_cli.manifest import Manifest


def build_case(tmp_path, monkeypatch, *, passed=True, coupled=False, requirements=False):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    monkeypatch.setenv("GEOFORGE_KI_ADAPTATION_HOME", str(tmp_path / "adaptations"))
    library = tmp_path / "library"
    source = library / "models/Demo"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("# Harmless project-readiness fixture\n")
    (source / "kiss.yaml").write_text(
        "kiss_manifest_version: 1\nmodel: Demo\n" +
        ("depends_on: [MissingDependency]\n" if coupled else "") +
        ("python_deps: [geoforge_nonexistent_test_dependency_937526]\n" if requirements else ""))
    (source / "preflight_check.py").write_text(
        "print('EXACT_PROJECT_PREFLIGHT_EXECUTED')\n" +
        ("raise SystemExit('REAL_PROJECT_PREFLIGHT_FAILURE')\n" if not passed else ""))
    helpers = library / "ki_tools_common/ki_tools_common"
    helpers.mkdir(parents=True)
    (helpers / "__init__.py").write_text("# Harmless helper fixture\n")
    (library / ki_updates.SNAPSHOT_MANIFEST).write_text(json.dumps({
        "source_commit": "a" * 40, "content_sha256": "b" * 64,
        "trees": {"shared_tools": "c" * 40}}))
    ki_guard.enroll(source)
    workroot = tmp_path / "workroot"
    shared = paths.KissConfig.default(workroot / "demo")
    shared.root.mkdir(parents=True)
    shared.python, shared.relocation = sys.executable, "none"
    setup.prepare_common(shared, library)
    setup.materialise_active(source, shared.root / "ki", shared,
        manifest=Manifest.load(source / "kiss.yaml"), library_root=library)
    (shared.root / paths.CONFIG_NAME).write_text(shared.dumps(), encoding="utf-8")
    ki = catalog.KI("Demo", source)
    (shared.root / "status.json").write_text(json.dumps({
        "ok": True, "ki_content_digest": gui.ki_verification.content_digest(shared.root / "ki"),
        "runtime_identity": software_verification.runtime_identity(shared),
        "verification_identity": software_verification.identity(ki, Manifest.load(ki.manifest), library)}))
    # Preserve the genuine enrolled baseline, then reproduce the observed old
    # shared-KI drift. That invalid copy must never run or be re-enrolled.
    old_baseline = ki_guard._read(shared.root / "ki")
    old_preflight = shared.root / "ki/preflight_check.py"
    old_preflight.write_text("raise SystemExit('OLD_SHARED_KI_MUST_NOT_RUN')\n")
    handler = object.__new__(gui.Handler)
    handler.repo_root = handler.library_root = library
    handler.workroot = workroot
    handler.catalog = catalog.Catalog(library / "models")
    handler._manifest = lambda item: Manifest.load(item.manifest)
    project = tmp_path / "project"
    project.mkdir()
    assert handler._status_for(ki)["primary_error"]["name"] == "ki-edit"
    transitions, messages = [], []
    turn = SimpleNamespace(kind="setup")
    monkeypatch.setattr(flowrun, "provider_refusal", lambda *args: None)
    monkeypatch.setattr(flowrun, "setup_allowed", lambda project: True)
    monkeypatch.setattr(flowrun, "setup_turn", lambda *args, **kwargs: turn)
    monkeypatch.setattr(flowrun, "setup_verified", lambda *args: transitions.append("verified"))
    monkeypatch.setattr(flowrun, "project_setup_failed", lambda *args: transitions.append("failed"))
    monkeypatch.setattr(gui.setup_flow, "prepare", lambda *args, **kwargs:
        pytest.fail("Old shared KI setup must not precede the exact project check"))
    monkeypatch.setattr(gui.api, "run", lambda *args, **kwargs:
        pytest.fail("Exact host project check must precede provider"))
    monkeypatch.setattr(gui.providers, "run", lambda *args, **kwargs:
        pytest.fail("Exact host project check must precede provider"))
    return SimpleNamespace(handler=handler, ki=ki, source=source, project=project,
        shared=shared, baseline=old_baseline, old_bytes=old_preflight.read_bytes(),
        status_bytes=(shared.root / "status.json").read_bytes(), turn=turn,
        transitions=transitions, messages=messages)


def chat(c, provider="api:deepseek", *, events=None):
    return c.handler._chat_with_models(["Demo"], provider, "Run the approved preflight",
        c.messages.append, c.project, flow_pre=SimpleNamespace(gated=True, replan_reason=None), runtime_events=events)


def assert_old_shared_preserved(c):
    assert (c.shared.root / "ki/preflight_check.py").read_bytes() == c.old_bytes
    assert (c.shared.root / "status.json").read_bytes() == c.status_bytes
    assert ki_guard._read(c.shared.root / "ki") == c.baseline
    with pytest.raises(ValueError, match="changed"):
        ki_guard.require_intact(c.shared.root / "ki")


@pytest.mark.parametrize("provider", ["api:deepseek", "cli:claude"])
def test_stale_shared_ki_uses_real_project_preflight_and_current_receipt(tmp_path, monkeypatch, provider):
    c = build_case(tmp_path, monkeypatch)
    assert chat(c, provider) is c.turn
    assert c.transitions == ["verified"]
    working = catalog.KI("Demo", c.project / "models/Demo/ki")
    receipt = project_verification.status(c.project, working)
    assert receipt["can_run"]
    check = receipt["receipt"]["checks"][0]
    assert check["evidence"]["launch_attempted"] is True
    assert check["evidence"]["source_root"] == str(working.root)
    assert "EXACT_PROJECT_PREFLIGHT_EXECUTED" in check["detail"]
    assert "OLD_SHARED_KI_MUST_NOT_RUN" not in check["detail"]
    assert_old_shared_preserved(c)
    monkeypatch.setattr(gui.install, "run_preflight", lambda *args, **kwargs:
        pytest.fail("Read-only readiness must not launch another preflight"))
    assert c.handler._project_setup_ok(c.project, ["Demo"])
    assert c.handler._status_for(c.ki)["can_run"] is False


@pytest.mark.parametrize("kind", ["preflight", "coupled", "requirements"])
def test_provenance_exception_never_turns_failed_project_requirements_into_readiness(tmp_path, monkeypatch, kind):
    c = build_case(tmp_path, monkeypatch, passed=kind != "preflight",
                   coupled=kind == "coupled", requirements=kind == "requirements")
    assert chat(c) is c.turn
    assert c.transitions == ["failed"]
    working = catalog.KI("Demo", c.project / "models/Demo/ki")
    result = project_verification.status(c.project, working)
    assert not result["can_run"] and result["receipt"]["state"] == "failed"
    assert result["receipt"]["checks"][0]["evidence"]["launch_attempted"] is True
    expected = {"preflight": "REAL_PROJECT_PREFLIGHT_FAILURE", "coupled": "MissingDependency",
                "requirements": "geoforge_nonexistent_test_dependency_937526"}[kind]
    assert expected in result["detail"]
    assert not c.handler._project_setup_ok(c.project, ["Demo"])
    assert_old_shared_preserved(c)


@pytest.mark.parametrize("reason", ["setup-active", "ki-source", "runtime-config", "unknown", None])
def test_other_shared_failures_keep_the_existing_installation_gate(tmp_path, monkeypatch, reason):
    c = build_case(tmp_path, monkeypatch)
    c.handler._status_for = lambda ki: {"can_run": False,
        "primary_error": {"name": reason} if reason else None}
    attempts = []
    def old_setup(*args, **kwargs):
        attempts.append(args[2])
        raise ValueError("Existing installation route retained")
    monkeypatch.setattr(gui.setup_flow, "prepare", old_setup)
    assert chat(c) is None
    assert attempts == [c.shared.root]
    assert "Existing installation route retained" in "".join(c.messages)
    assert not list(c.project.rglob("execution.json"))
    assert c.transitions == []


def test_missing_saved_interpreter_hidden_by_shared_ki_edit_never_falls_back(tmp_path, monkeypatch):
    c = build_case(tmp_path, monkeypatch)
    c.shared.python = str(c.shared.root / "missing-selected-runtime/python.exe")
    (c.shared.root / paths.CONFIG_NAME).write_text(c.shared.dumps(), encoding="utf-8")
    assert c.handler._status_for(c.ki)["primary_error"]["name"] == "ki-edit"
    monkeypatch.setattr(gui.setup_flow, "prepare", lambda *args, **kwargs:
        (_ for _ in ()).throw(ValueError("Saved interpreter needs repair")))
    monkeypatch.setattr(gui.install, "runtime_python", lambda *args:
        pytest.fail("A missing selected interpreter must not trigger base-Python fallback"))
    assert chat(c) is None
    assert "Saved interpreter needs repair" in "".join(c.messages)
    assert not (c.project / "models/Demo/kiss.toml").exists()
    assert not list(c.project.rglob("execution.json"))


@pytest.mark.parametrize("invalid", ["missing", "malformed", "foreign_root"])
def test_stale_shared_ki_needs_exact_saved_runtime_before_project_projection(tmp_path, monkeypatch, invalid):
    c = build_case(tmp_path, monkeypatch)
    saved = c.shared.root / paths.CONFIG_NAME
    if invalid == "missing":
        saved.unlink()
    elif invalid == "malformed":
        saved.write_text("not a TOML binding [[", encoding="utf-8")
    else:
        saved.write_text(replace(c.shared, root=c.project).dumps(), encoding="utf-8")
    monkeypatch.setattr(gui.setup_flow, "prepare", lambda *args, **kwargs:
        (_ for _ in ()).throw(ValueError("Exact saved runtime must be restored")))
    assert chat(c) is None
    assert "Exact saved runtime must be restored" in "".join(c.messages)
    assert not (c.project / "models/Demo/kiss.toml").exists()
    assert not list(c.project.rglob("execution.json"))


@pytest.mark.parametrize("launcher", ["current_frozen", "mac_bundle"])
def test_frozen_app_launcher_cannot_be_treated_as_selected_python(tmp_path, monkeypatch, launcher):
    c = build_case(tmp_path, monkeypatch)
    if launcher == "mac_bundle":
        selected = tmp_path / "GeoForge.app/Contents/MacOS/kiss"
        selected.parent.mkdir(parents=True)
        selected.write_bytes(b"fixture app launcher, never executed")
        c.shared.python = str(selected)
        (c.shared.root / paths.CONFIG_NAME).write_text(c.shared.dumps(), encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(gui.setup_flow, "prepare", lambda *args, **kwargs:
        (_ for _ in ()).throw(ValueError("Saved launcher needs explicit runtime repair")))
    monkeypatch.setattr(gui.install, "runtime_python", lambda *args:
        pytest.fail("App launcher must not trigger replacement interpreter discovery"))
    assert chat(c) is None
    assert "Saved launcher needs explicit runtime repair" in "".join(c.messages)
    assert not (c.project / "models/Demo/kiss.toml").exists()


def test_changed_library_source_is_rejected_before_any_project_preparation(tmp_path, monkeypatch):
    c = build_case(tmp_path, monkeypatch)
    (c.source / "preflight_check.py").write_text("print('unverified source')")
    assert chat(c) is None
    assert "KI draft requires verification" in "".join(c.messages)
    assert not (c.project / "models/Demo/kiss.toml").exists()
    assert not list(c.project.rglob("execution.json"))


@pytest.mark.parametrize("reason", ["ki-revision", "snapshot-changed"])
def test_other_provenance_staleness_still_requires_real_project_preflight(tmp_path, monkeypatch, reason):
    c = build_case(tmp_path, monkeypatch)
    # Restore the temporary shared fixture's original bytes, then stale only
    # the appropriate old software receipt field to exercise real status code.
    (c.shared.root / "ki/preflight_check.py").write_bytes((c.source / "preflight_check.py").read_bytes())
    ki_guard.require_intact(c.shared.root / "ki")
    status_path = c.shared.root / "status.json"
    status = json.loads(status_path.read_text())
    status["ki_content_digest" if reason == "ki-revision" else "verification_identity"] = "0" * 64
    status_path.write_text(json.dumps(status))
    assert c.handler._status_for(c.ki)["primary_error"]["name"] == reason
    assert chat(c) is c.turn and c.transitions == ["verified"]
    assert c.handler._project_setup_ok(c.project, ["Demo"])
    assert c.handler._status_for(c.ki)["can_run"] is False


def test_stop_after_real_project_check_prevents_success_handoff(tmp_path, monkeypatch):
    c = build_case(tmp_path, monkeypatch)
    handle = api.TurnHandle()
    original = project_verification.verify
    def stopped_after_check(*args, **kwargs):
        result = original(*args, **kwargs)
        assert result["can_run"]
        handle.stop()
        return result
    monkeypatch.setattr(project_verification, "verify", stopped_after_check)
    assert chat(c, events={"_handle": handle}) is c.turn
    assert c.transitions == ["failed"]
    assert_old_shared_preserved(c)


@pytest.mark.parametrize("damage", ["project_ki", "saved_runtime", "helper", "receipt"])
def test_existing_project_damage_cannot_inherit_stale_shared_status_exception(tmp_path, monkeypatch, damage):
    c = build_case(tmp_path, monkeypatch)
    assert chat(c) is c.turn
    root = c.project / "models/Demo/ki"
    cfg_path = root.parent / paths.CONFIG_NAME
    cfg = paths.KissConfig.load(root.parent)
    if damage == "project_ki":
        (root / "preflight_check.py").write_text("print('unverified edit')\n")
    elif damage == "saved_runtime":
        cfg.python = str(c.project / "missing-python.exe")
        cfg_path.write_text(cfg.dumps(), encoding="utf-8")
    elif damage == "helper":
        (cfg.roles["ki_tools_common"] / "ki_tools_common/__init__.py").write_text("unverified helper edit")
    else:
        receipt = project_verification._receipt_path(c.project, "Demo")
        doc = json.loads(receipt.read_text(encoding="utf-8"))
        doc["ki_content_digest"] = "0" * 64
        receipt.write_text(json.dumps(doc), encoding="utf-8")
    monkeypatch.setattr(gui.install, "run_preflight", lambda *args, **kwargs:
        pytest.fail("Damaged existing project must be rejected before preflight"))
    c.messages.clear(); c.transitions.clear()
    if damage == "receipt":
        assert not c.handler._project_setup_ok(c.project, ["Demo"])
    else:
        assert chat(c) is None
        assert "could not prepare selected KI workspaces" in "".join(c.messages)
    assert_old_shared_preserved(c)


def test_planning_can_project_intact_ki_but_never_run_preflight(tmp_path, monkeypatch):
    c = build_case(tmp_path, monkeypatch)
    monkeypatch.setattr(flowrun, "setup_allowed", lambda project: False)
    monkeypatch.setattr(flowrun, "current_state", lambda project: "PLANNING")
    planning = SimpleNamespace(kind="planning", execute=False, extra_prompt="",
                               drop_scope_rules=False, session=object())
    monkeypatch.setattr(flowrun, "turn", lambda *args, **kwargs: planning)
    monkeypatch.setattr(gui.install, "run_preflight", lambda *args, **kwargs:
        pytest.fail("Planning must not execute preflight"))
    monkeypatch.setattr(gui.prompt, "compose_multi", lambda *args, **kwargs: "KI contract")
    monkeypatch.setattr(gui.calibration, "prompt_block", lambda *args: "")
    monkeypatch.setattr(gui.settings, "database_access_mode", lambda: "off")
    monkeypatch.setattr(gui.skilllib, "prompt_block", lambda *args: "")
    monkeypatch.setattr(gui.skilllib, "roots", lambda: [])
    monkeypatch.setattr(gui.mcp, "prompt_block", lambda *args, **kwargs: "")
    planned = []
    def plan_only(*args, **kwargs):
        planned.append(True)
        assert kwargs["setup_mode"] is False
        yield "Read-only planning"
    monkeypatch.setattr(gui.api, "run", plan_only)
    assert chat(c) is planning and planned == [True]
    assert not list(c.project.rglob("execution.json"))
    assert not c.handler._project_setup_ok(c.project, ["Demo"])
    assert c.transitions == []
    assert_old_shared_preserved(c)
