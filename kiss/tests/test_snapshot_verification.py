"""Updated KIs cannot inherit an unrelated machine verification result."""
import json
from pathlib import Path
import sys

import pytest
import yaml

from kiss_cli import catalog, gui, install, ki_updates, paths, software_verification
from kiss_cli.manifest import Manifest


@pytest.fixture
def example(tmp_path):
    library = tmp_path / "snapshot"
    source = library / "models/Demo"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("Demo")
    (source / "preflight_check.py").write_text("print('OK example')\n")
    (source / "kiss.yaml").write_text(yaml.safe_dump({
        "kiss_manifest_version": 1, "model": "Demo", "verified": "unverified"}))
    (library / ki_updates.SNAPSHOT_MANIFEST).write_text(json.dumps({
        "content_sha256": "a" * 64, "trees": {"shared_tools": "b" * 40}}))
    workroot = tmp_path / "work"
    workspace = workroot / "demo"
    workspace.mkdir(parents=True)
    binary = workspace / "existing.exe"
    binary.write_bytes(b"existing native bytes")
    handler = object.__new__(gui.Handler)
    handler.repo_root = handler.library_root = library
    handler.workroot = workroot
    ki = catalog.KI("Demo", source)
    cfg = paths.KissConfig.default(workspace)
    cfg.python = sys.executable
    return handler, ki, cfg, binary


def write_status(cfg, **extra):
    path = cfg.root / "status.json"
    path.write_text(json.dumps({"ok": True, "checked_at": 12, "verified_at": 12,
                               "steps": [{"name": "preflight", "ok": True}], **extra}))
    return path


def expected(handler, ki):
    return software_verification.identity(ki, handler._manifest(ki), handler.library_root)


def test_legacy_snapshot_report_requires_recheck_without_mutation(example):
    handler, ki, cfg, binary = example
    path = write_status(cfg)
    original = path.read_bytes()
    state = handler._status_for(ki)
    assert state["requires_reverification"] and not state["can_run"]
    assert state["verified_at"] is None
    assert path.read_bytes() == original and binary.read_bytes() == b"existing native bytes"


def test_matching_snapshot_identity_is_verified(example):
    handler, ki, cfg, _ = example
    write_status(cfg, verification_identity=expected(handler, ki))
    assert handler._status_for(ki)["can_run"]


@pytest.mark.parametrize("change", ["ki", "helpers", "recipe"])
def test_each_effective_component_invalidates_saved_verification(example, change):
    handler, ki, cfg, _ = example
    write_status(cfg, verification_identity=expected(handler, ki))
    if change == "recipe":
        doc = yaml.safe_load(ki.manifest.read_text())
        doc["python_deps"] = ["new-scientific-package>=2"]
        ki.manifest.write_text(yaml.safe_dump(doc))
    else:
        marker = handler.library_root / ki_updates.SNAPSHOT_MANIFEST
        meta = json.loads(marker.read_text())
        if change == "ki": meta["content_sha256"] = "c" * 64
        else: meta["trees"]["shared_tools"] = "d" * 40
        marker.write_text(json.dumps(meta))
    assert not handler._status_for(ki)["can_run"]


def test_bundled_legacy_status_retains_existing_behavior(example):
    handler, ki, cfg, _ = example
    (handler.library_root / ki_updates.SNAPSHOT_MANIFEST).unlink()
    write_status(cfg)
    assert handler._status_for(ki)["can_run"]


def test_successful_agent_preflight_records_identity_and_requirements(example, monkeypatch):
    handler, ki, cfg, binary = example
    monkeypatch.setattr(software_verification, "requirements",
        lambda *a, **kw: install.Step("manifest-requirements", True, "fresh requirements checked"))
    assert handler._record_agent_preflight(ki, ki, cfg, cfg.root, lambda _: None,
        check=install.Step("preflight", True, "fresh model check"))
    saved = json.loads((cfg.root / "status.json").read_text())
    assert saved["verification_identity"] == expected(handler, ki)
    assert saved["steps"][-2]["name"] == "manifest-requirements"
    assert handler._status_for(ki)["can_run"]
    assert binary.read_bytes() == b"existing native bytes"


def test_new_dependency_failure_cannot_retain_a_successful_report(example, monkeypatch):
    handler, ki, cfg, _ = example
    write_status(cfg, verification_identity=expected(handler, ki))
    monkeypatch.setattr(software_verification, "requirements",
        lambda *a, **kw: install.Step("manifest-requirements", False, "missing scipy>=99"))
    assert not handler._record_agent_preflight(ki, ki, cfg, cfg.root, lambda _: None,
        check=install.Step("preflight", True, "old script passed"))
    saved = json.loads((cfg.root / "status.json").read_text())
    assert not saved["ok"] and saved["verification_identity"] is None
    assert saved["verified_at"] is None and "scipy" in saved["primary_error"]["detail"]
    assert not handler._status_for(ki)["can_run"]


def test_failed_native_preflight_clears_identity(example):
    handler, ki, cfg, _ = example
    write_status(cfg, verification_identity=expected(handler, ki))
    assert not handler._record_agent_preflight(ki, ki, cfg, cfg.root, lambda _: None,
        check=install.Step("preflight", False, "real preflight failed"))
    assert json.loads((cfg.root / "status.json").read_text())["verification_identity"] is None


def test_interrupted_snapshot_setup_invalidates_previous_success(example, monkeypatch):
    handler, ki, cfg, binary = example
    write_status(cfg, verification_identity=expected(handler, ki))
    monkeypatch.setattr(install, "runtime_python", lambda *_: (_ for _ in ()).throw(ValueError("setup interrupted")))
    with pytest.raises(ValueError, match="interrupted"):
        gui.run_install(ki, handler._manifest(ki), cfg.root, lambda _: None, handler.library_root)
    assert not json.loads((cfg.root / "status.json").read_text())["ok"]
    assert binary.read_bytes() == b"existing native bytes"


def test_builtin_success_records_original_snapshot_identity_after_materialising(example, monkeypatch):
    handler, ki, cfg, binary = example
    for name in ("ensure_python_env", "check_system_deps", "install_python_deps"):
        monkeypatch.setattr(install, name, lambda *a, **kw: install.Step("prerequisite", True, "fixture ready"))
    monkeypatch.setattr(install, "needs_shared_tools", lambda *_: False)
    monkeypatch.setattr(install, "acquire", lambda *a, **kw: (install.Step("acquire", True, "existing software"), None))
    monkeypatch.setattr(install, "run_preflight", lambda *a, **kw: install.Step("preflight", True, "fresh native check"))
    gui.run_install(ki, handler._manifest(ki), cfg.root, lambda _: None, handler.library_root)
    saved = json.loads((cfg.root / "status.json").read_text())
    assert saved["ok"] and saved["verification_identity"] == expected(handler, ki)
    assert handler._status_for(ki)["can_run"]
    assert binary.read_bytes() == b"existing native bytes"


@pytest.mark.parametrize("deps,ok", [(["pip>=0"], True), (["pip>=9999"], False),
    (["geoforge-deliberately-missing-test-package"], False),
    (["geoforge-deliberately-missing-test-package; python_version<'1'"], True)])
def test_python_requirements_are_checked_in_recorded_interpreter(example, deps, ok):
    _, _, cfg, _ = example
    step = software_verification.requirements(Manifest(model="Demo", python_deps=deps), cfg)
    assert step.ok is ok


def test_coupled_requirements_fail_closed_until_current_verification(example):
    _, _, cfg, _ = example
    man = Manifest(model="Demo", depends_on=["Routing"])
    assert not software_verification.requirements(man, cfg).ok
    assert not software_verification.requirements(man, cfg, dependency_check=lambda _: False).ok
    assert software_verification.requirements(man, cfg, dependency_check=lambda n: n == "Routing").ok
