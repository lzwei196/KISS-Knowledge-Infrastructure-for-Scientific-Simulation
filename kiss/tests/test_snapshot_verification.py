"""Updated KIs cannot inherit an unrelated machine verification result."""
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import shutil
import sys

import pytest
import yaml

from kiss_cli import (catalog, gui, install, ki_guard, ki_updates, ki_verification,
                      paths, setup, software_verification)
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
    shared = library / "ki_tools_common" / "ki_tools_common"
    shared.mkdir(parents=True)
    (shared / "__init__.py").write_text("# fixture helpers\n", encoding="utf-8")
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
    setup.prepare_common(cfg, library)
    (workspace / "kiss.toml").write_text(cfg.dumps(), encoding="utf-8")
    ki_guard.enroll(source)
    setup.materialise_active(source, workspace / "ki", cfg)
    return handler, ki, cfg, binary


def write_status(cfg, **extra):
    path = cfg.root / "status.json"
    path.write_text(json.dumps({"ok": True, "checked_at": 12, "verified_at": 12,
                               "steps": [{"name": "preflight", "ok": True}], **extra}))
    return path


def expected(handler, ki):
    return software_verification.identity(ki, handler._manifest(ki), handler.library_root)


def current_status(handler, ki, cfg):
    return write_status(cfg, verification_identity=expected(handler, ki),
                        runtime_identity=software_verification.runtime_identity(cfg),
                        ki_content_digest=ki_verification.content_digest(cfg.root / "ki"))


def working_ki(ki, cfg):
    return catalog.KI(ki.name, cfg.root / "ki")


def test_legacy_snapshot_report_requires_recheck_without_mutation(example):
    handler, ki, cfg, binary = example
    path = write_status(cfg)
    original = path.read_bytes()
    state = handler._status_for(ki)
    assert state["requires_reverification"] and not state["can_run"]
    assert state["verified_at"] is None
    assert path.read_bytes() == original and binary.read_bytes() == b"existing native bytes"
    # Out of date, not broken: each project's exact check runs with its approved plan.
    assert state["label"] == "Installed · checked when it runs"
    assert gui._project_check_allowed_by_shared_status(state, shared_root=cfg.root)


@pytest.mark.parametrize("python", ["python3", "missing"])
def test_out_of_date_check_a_run_cannot_make_says_setup_needed(example, python):
    handler, ki, cfg, _ = example
    write_status(cfg)
    saved = replace(cfg, python=python if python == "python3" else str(cfg.root / "missing" / "python.exe"))
    (cfg.root / "kiss.toml").write_text(saved.dumps(), encoding="utf-8")
    state = handler._status_for(ki)
    # A run would stop for setup (no absolute saved interpreter), not check it itself.
    assert not gui._project_check_allowed_by_shared_status(state, shared_root=cfg.root)
    assert state["label"] == "Setup needed" and not state["can_run"]


def test_matching_snapshot_identity_is_verified(example):
    handler, ki, cfg, _ = example
    current_status(handler, ki, cfg)
    assert handler._status_for(ki)["can_run"]


@pytest.mark.parametrize("change", ["ki", "helpers", "recipe"])
def test_each_effective_component_invalidates_saved_verification(example, change, tmp_path):
    handler, ki, cfg, _ = example
    current_status(handler, ki, cfg)
    old_identity = expected(handler, ki)
    updated = tmp_path / "updated-snapshot"
    shutil.copytree(handler.library_root, updated)
    new_ki = catalog.KI(ki.name, updated / "models" / ki.name)
    if change == "recipe":
        doc = yaml.safe_load(new_ki.manifest.read_text())
        doc["python_deps"] = ["new-scientific-package>=2"]
        new_ki.manifest.write_text(yaml.safe_dump(doc))
    elif change == "ki":
        (new_ki.root / "SKILL.md").write_text("Updated Demo instructions")
    else:
        (updated / "ki_tools_common/ki_tools_common/__init__.py").write_text("# changed helper behavior\n")
    ki_guard.enroll(new_ki.root)  # independently accepted source fixture
    handler.library_root = updated
    assert expected(handler, new_ki) != old_identity
    status = handler._status_for(new_ki)
    assert not status["can_run"]
    assert status["primary_error"]["name"] == "snapshot-changed"


def test_unrelated_snapshot_changes_preserve_current_verification(example, tmp_path):
    handler, ki, cfg, binary = example
    status_path = current_status(handler, ki, cfg)
    before = status_path.read_bytes()
    old_identity = expected(handler, ki)
    updated = tmp_path / "updated-snapshot"
    shutil.copytree(handler.library_root, updated)
    other = updated / "models/Other"
    other.mkdir()
    (other / "SKILL.md").write_text("Another model was updated")
    (updated / ki_updates.SNAPSHOT_MANIFEST).write_text(json.dumps({
        "content_sha256": "c" * 64, "source_commit": "d" * 40,
        "trees": {"shared_tools": "e" * 40, "models": "f" * 40}}))
    new_ki = catalog.KI(ki.name, updated / "models" / ki.name)
    ki_guard.enroll(new_ki.root)
    handler.library_root = updated
    assert expected(handler, new_ki) == old_identity
    assert handler._status_for(new_ki)["can_run"]
    assert status_path.read_bytes() == before
    assert binary.read_bytes() == b"existing native bytes"


def test_effective_recipe_change_invalidates_without_a_ki_tree_change(example):
    handler, ki, _cfg, _binary = example
    man = handler._manifest(ki)
    before = software_verification.identity(ki, man, handler.library_root)
    changed = replace(man, python_deps=["new-package>=2"])
    assert software_verification.identity(ki, changed, handler.library_root) != before


def test_old_whole_library_identity_requires_one_fresh_check(example, monkeypatch):
    handler, ki, cfg, binary = example
    legacy = {"schema_version": 1, "ki": "models/Demo", "library_content": "a" * 64,
              "shared_tools": "b" * 40, "effective_manifest": asdict(handler._manifest(ki))}
    path = current_status(handler, ki, cfg)
    state = json.loads(path.read_text())
    state["verification_identity"] = hashlib.sha256(json.dumps(legacy, sort_keys=True).encode()).hexdigest()
    path.write_text(json.dumps(state))
    before = path.read_bytes()
    assert not handler._status_for(ki)["can_run"]
    assert path.read_bytes() == before
    assert binary.read_bytes() == b"existing native bytes"
    monkeypatch.setattr(software_verification, "requirements", lambda *a, **kw:
                        install.Step("manifest-requirements", True, "fresh fixture requirement check"))
    assert handler._record_agent_preflight(ki, working_ki(ki, cfg), cfg, cfg.root, lambda _: None,
        check=install.Step("preflight", True, "fresh fixture preflight"))
    assert handler._status_for(ki)["can_run"]
    assert json.loads(path.read_text())["verification_identity"] == expected(handler, ki)


@pytest.mark.parametrize("component", ["ki", "helpers"])
def test_missing_relevant_bytes_fail_closed(example, component, tmp_path):
    handler, ki, cfg, _ = example
    current_status(handler, ki, cfg)
    source = ki.root if component == "ki" else handler.library_root / "ki_tools_common"
    source.rename(tmp_path / "retained-missing-component")
    with pytest.raises((ValueError, OSError)):
        expected(handler, ki)
    assert not handler._status_for(ki)["can_run"]


@pytest.mark.parametrize("component", ["ki", "helpers"])
def test_relevant_external_directory_alias_fails_closed(example, component, tmp_path):
    handler, ki, cfg, _ = example
    current_status(handler, ki, cfg)
    source = ki.root if component == "ki" else handler.library_root / "ki_tools_common"
    external = tmp_path / "external-component"
    source.rename(external)
    try:
        source.symlink_to(external, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"Directory symlinks unavailable: {error}")
    with pytest.raises((ValueError, OSError)):
        expected(handler, ki)
    assert not handler._status_for(ki)["can_run"]


def test_bundled_legacy_status_requires_current_revision_without_erasing_history(example):
    handler, ki, cfg, _ = example
    (handler.library_root / ki_updates.SNAPSHOT_MANIFEST).unlink()
    path = write_status(cfg)
    before = path.read_bytes()
    status = handler._status_for(ki)
    assert not status["can_run"] and status["requires_reverification"]
    assert status["previous_verification_passed"] and status["checked_at"] == 12
    assert status["verified_at"] is None and path.read_bytes() == before


def test_successful_agent_preflight_records_identity_and_requirements(example, monkeypatch):
    handler, ki, cfg, binary = example
    monkeypatch.setattr(software_verification, "requirements",
        lambda *a, **kw: install.Step("manifest-requirements", True, "fresh requirements checked"))
    assert handler._record_agent_preflight(ki, working_ki(ki, cfg), cfg, cfg.root, lambda _: None,
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
    assert not handler._record_agent_preflight(ki, working_ki(ki, cfg), cfg, cfg.root, lambda _: None,
        check=install.Step("preflight", True, "old script passed"))
    saved = json.loads((cfg.root / "status.json").read_text())
    assert not saved["ok"] and saved["verification_identity"] is None
    assert saved["verified_at"] is None and "scipy" in saved["primary_error"]["detail"]
    assert not handler._status_for(ki)["can_run"]


def test_failed_native_preflight_clears_identity(example):
    handler, ki, cfg, _ = example
    write_status(cfg, verification_identity=expected(handler, ki))
    assert not handler._record_agent_preflight(ki, working_ki(ki, cfg), cfg, cfg.root, lambda _: None,
        check=install.Step("preflight", False, "real preflight failed"))
    assert json.loads((cfg.root / "status.json").read_text())["verification_identity"] is None


def test_interrupted_snapshot_setup_invalidates_previous_success(example, monkeypatch):
    handler, ki, cfg, binary = example
    write_status(cfg, verification_identity=expected(handler, ki))
    monkeypatch.setattr(setup, "prepare_python", lambda *a, **k: (_ for _ in ()).throw(ValueError("setup interrupted")))
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


@pytest.mark.parametrize("installed_copy", [True, False])
def test_old_unregistered_installation_cannot_inherit_ready_status(example, installed_copy):
    handler, ki, cfg, _ = example
    legacy = cfg.root.parent / "legacy"
    legacy.mkdir()
    if installed_copy:
        shutil.copytree(cfg.root / "ki", legacy / "ki")
    old_cfg = paths.KissConfig.default(legacy)
    status_path = write_status(old_cfg, verification_identity=expected(handler, ki),
        ki_content_digest=ki_verification.content_digest(legacy / "ki"))
    before = status_path.read_bytes()
    handler._workdir = lambda _ki: legacy
    handler._default_status_files = {ki.name.casefold(): status_path}
    status = handler._status_for(ki)
    assert not status["can_run"] and status["requires_reverification"]
    assert status["previous_verification_passed"]
    assert not ki_guard.is_managed(legacy / "ki")
    assert status_path.read_bytes() == before


def test_post_startup_source_drift_invalidates_ready_badge(example):
    handler, ki, cfg, _ = example
    status_path = current_status(handler, ki, cfg)
    handler.catalogue_integrity_errors = {}
    assert handler._status_for(ki)["can_run"]
    (ki.root / "SKILL.md").write_text("changed after startup")
    saved = status_path.read_bytes()
    state = handler._status_for(ki)
    assert not state["can_run"] and state["requires_reverification"]
    assert state["primary_error"]["name"] == "ki-source"
    assert "changed" in state["primary_error"]["detail"].lower()
    assert state["label"] == "Edited — needs verification"
    assert state["primary_error"]["trust"] == "edited"
    assert status_path.read_bytes() == saved


def test_library_card_separates_trust_install_route_and_installation(example, tmp_path, monkeypatch):
    handler, ki, cfg, _ = example
    monkeypatch.setattr(catalog, "installation_platform", lambda: "windows")
    current_status(handler, ki, cfg)
    handler.catalogue_integrity_errors = {}
    assert handler._status_for(ki)["label"] == "Installed"
    handler.catalogue_integrity_errors = {ki.name: (
        "New catalogue KI has no current KDT acceptance or exact recorded legacy provenance; "
        "a new --models directory cannot restart migration")}
    refused = handler._status_for(ki)
    assert refused["label"] == "Not accepted on this computer" and not refused["can_run"]
    assert refused["primary_error"]["trust"] == "not_accepted"
    handler.catalogue_integrity_errors = {}
    handler._workdir = lambda _ki: tmp_path / "never-installed"
    handler._default_status_files = {}
    handler._manifest_setup_kind = lambda _ki: "manual"
    # No recipe, source repository or package: the platform note decides.
    assert handler._status_for(ki)["label"] == "No install route"
    from kiss_cli import gui
    monkeypatch.setattr(gui, "_recorded_platform_install", lambda _root: True)
    assert handler._status_for(ki)["label"] == "Setup needed"


@pytest.mark.parametrize("note, routed", [
    (None, False),
    ("Latest recorded attempt: **needs-user** (2026-09-04).\n", False),
    ("Latest recorded attempt: **installed** (2026-09-05).\n", True),
    ("Observed 2026-10-01: builds and runs natively on Windows x64.\n", True),
])
def test_install_route_comes_from_this_platforms_install_note(tmp_path, monkeypatch, note, routed):
    from kiss_cli import gui
    monkeypatch.setattr(catalog, "installation_platform", lambda: "windows")
    if note is not None:
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "install.windows.md").write_text(note, encoding="utf-8")
        (tmp_path / "docs" / "install.macos.md").write_text(
            "Latest recorded attempt: **installed**\n", encoding="utf-8")
    assert gui._recorded_platform_install(tmp_path) is routed
