"""One setup attempt cannot mix independently activated KI libraries."""
import json
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

import pytest
import yaml

from kiss_cli import (api, catalog, gui, install, ki_guard, ki_updates, paths,
                      providers, setup, setup_jobs, software_verification)


@pytest.fixture
def libraries(tmp_path, monkeypatch):
    made = []
    for revision in ("a", "b"):
        library = tmp_path / revision
        source = library / "models" / "Demo"
        source.mkdir(parents=True)
        (source / "SKILL.md").write_text(f"# Demo {revision}\n", encoding="utf-8")
        (source / "preflight_check.py").write_text("print('fixture preflight')\n")
        manifests = library / "kiss" / "manifests"
        manifests.mkdir(parents=True)
        (manifests / "Demo.yaml").write_text(yaml.safe_dump({
            "kiss_manifest_version": 1, "model": "Demo", "verified": "unverified",
            "python_deps": [f"fixture-{revision}"]}), encoding="utf-8")
        shared = library / "ki_tools_common" / "ki_tools_common"
        shared.mkdir(parents=True)
        (shared / "__init__.py").write_text(f"# helpers {revision}\n", encoding="utf-8")
        (library / ki_updates.SNAPSHOT_MANIFEST).write_text(json.dumps({
            "content_sha256": revision * 64, "trees": {"shared_tools": revision * 40}}))
        ki_guard.enroll(source)
        made.append((library, catalog.Catalog(library / "models")))
    (library_a, catalogue_a), (library_b, catalogue_b) = made
    workroot = tmp_path / "work"
    root = workroot / "demo"
    root.mkdir(parents=True)
    cfg = paths.KissConfig.default(root)
    cfg.python, cfg.relocation = sys.executable, "none"
    setup.prepare_common(cfg, library_a)
    (root / "kiss.toml").write_text(cfg.dumps(), encoding="utf-8")
    (root / "CLAUDE.md").write_text("Fixture setup instructions", encoding="utf-8")
    source_ki = catalogue_a.get("Demo")
    setup.materialise_active(source_ki.root, root / "ki", cfg)
    live = catalog.KI("Demo", root / "ki")

    class Handler(gui.Handler):
        pass
    Handler.catalog, Handler.library_root = catalogue_a, library_a
    Handler.repo_root, Handler.workroot = library_a, workroot
    Handler.catalogue_integrity_errors = {}
    handler = object.__new__(Handler)
    output, responses, prepared, requirements = [], [], [], []
    handler._open_stream = handler._end_stream = lambda: None
    handler._chunk = lambda piece: output.append(piece) or True
    handler._json = lambda payload, status=200: responses.append((status, payload))
    handler._validate_binding = lambda _req: None
    monkeypatch.setattr(gui.prompt, "compose", lambda *args, **kwargs: "Fixture prompt")
    monkeypatch.setattr(setup, "agent_task", lambda *args, **kwargs: "Fixture task")

    def prepare(ki, manifest, workspace, helpers, models):
        prepared.append((ki.root, manifest.python_deps, helpers, models))
        return live, cfg
    monkeypatch.setattr(setup, "prepare", prepare)
    def check_requirements(manifest, *_args, **_kwargs):
        requirements.append(manifest.python_deps)
        return install.Step("manifest-requirements", True, "fixture dependencies available")
    monkeypatch.setattr(software_verification, "requirements", check_requirements)
    count = []
    def preflight(*args, **kwargs):
        count.append(True)
        return install.Step("preflight", len(count) > 1, "fixture check")
    monkeypatch.setattr(install, "run_preflight", preflight)

    def activate():
        Handler.catalog = catalogue_b
        Handler.catalogue_integrity_errors = {}
        Handler.library_root = library_b

    return SimpleNamespace(handler=handler, handler_type=Handler, a=library_a, b=library_b,
        catalogue_a=catalogue_a, catalogue_b=catalogue_b, ki=source_ki, cfg=cfg, root=root,
        live=live, workroot=workroot, activate=activate, output=output, responses=responses,
        prepared=prepared, requirements=requirements)


def identity(c, library, catalogue):
    manifest = gui.Manifest.load(library / "kiss" / "manifests" / "Demo.yaml")
    return software_verification.identity(catalogue.get("Demo"), manifest, library)


@pytest.mark.parametrize("kind", ["api", "cli"])
@pytest.mark.parametrize("activate", [False, True])
def test_provider_finish_records_only_its_original_library(libraries, monkeypatch, kind, activate):
    c = libraries
    def provider(*args, **kwargs):
        if activate:
            c.activate()
        yield "Provider fixture completed\n"
    if kind == "api":
        monkeypatch.setattr(api, "run", provider)
        want = "api:deepseek"
    else:
        fake = providers.Provider(name="fixture", binary="fixture", argv=["fixture"],
                                  output="text", label="Fixture CLI")
        monkeypatch.setitem(providers.PROVIDERS, "fixture", fake)
        monkeypatch.setattr(providers, "run", provider)
        want = "cli:fixture"
    c.handler._stream_agent_setup({"model": "Demo", "provider": want})
    receipt = json.loads((c.root / "status.json").read_text())
    assert receipt["ok"], (receipt, c.output)
    assert receipt["verification_identity"] == identity(c, c.a, c.catalogue_a)
    assert receipt["verification_identity"] != identity(c, c.b, c.catalogue_b)
    assert c.requirements == [["fixture-a"]]
    assert c.prepared == [(c.ki.root, ["fixture-a"], c.a, c.a / "models")]
    assert setup_jobs.status(c.workroot, "Demo")["state"] == "completed"
    assert c.handler.library_root == (c.b if activate else c.a)
    assert c.handler.catalog is (c.catalogue_b if activate else c.catalogue_a)
    current = c.handler.catalog.get("Demo")
    state = c.handler._status_for(current)
    assert state["can_run"] is not activate
    if activate:
        assert state["primary_error"]["name"] == "snapshot-changed"


def test_activation_during_early_preflight_keeps_initial_context(libraries, monkeypatch):
    c = libraries
    def preflight(*args, **kwargs):
        c.activate()
        return install.Step("preflight", True, "fixture early pass")
    monkeypatch.setattr(install, "run_preflight", preflight)
    monkeypatch.setattr(api, "run", lambda *args, **kwargs: pytest.fail("early pass needs no provider"))
    c.handler._stream_agent_setup({"model": "Demo", "provider": "api:deepseek"})
    receipt = json.loads((c.root / "status.json").read_text())
    assert receipt["ok"] and receipt["verification_identity"] == identity(c, c.a, c.catalogue_a)
    assert c.requirements == [["fixture-a"]]
    assert c.handler.library_root == c.b


def test_api_builtin_callback_after_activation_uses_original_helpers(libraries, monkeypatch):
    c = libraries
    calls = []
    def builtin(ki, manifest, root, emit, helper_root, **kwargs):
        calls.append((ki.root, manifest.python_deps, helper_root))
    monkeypatch.setattr(gui, "run_install", builtin)
    def provider(*args, **kwargs):
        c.activate()
        kwargs["setup_context"]["run_builtin"]()
        yield "Provider fixture completed\n"
    monkeypatch.setattr(api, "run", provider)
    c.handler._stream_agent_setup({"model": "Demo", "provider": "api:deepseek"})
    assert calls == [(c.ki.root, ["fixture-a"], c.a)]


@pytest.mark.parametrize("activation_stage", ["job_start", "install"])
def test_builtin_init_captures_library_before_install_callback(libraries, monkeypatch, activation_stage):
    c = libraries
    for name in ("ensure_python_env", "check_system_deps", "install_python_deps"):
        monkeypatch.setattr(install, name, lambda *args, **kwargs: install.Step("prerequisite", True, "fixture"))
    monkeypatch.setattr(install, "needs_shared_tools", lambda *_: False)
    monkeypatch.setattr(install, "acquire", lambda *args, **kwargs: (
        install.Step("acquire", True, "existing fixture"), None))
    monkeypatch.setattr(install, "run_preflight", lambda *args, **kwargs:
        install.Step("preflight", True, "fixture pass"))
    original = gui.run_install if activation_stage == "install" else setup_jobs.start
    def activated(*args, **kwargs):
        c.activate()
        return original(*args, **kwargs)
    if activation_stage == "install":
        monkeypatch.setattr(gui, "run_install", activated)
    else:
        monkeypatch.setattr(setup_jobs, "start", activated)
    c.handler._stream_init({"model": "Demo"})
    receipt = json.loads((c.root / "status.json").read_text())
    assert receipt["ok"], (receipt, c.output)
    assert receipt["verification_identity"] == identity(c, c.a, c.catalogue_a)
    assert setup_jobs.status(c.workroot, "Demo")["state"] == "completed"
    assert c.handler.library_root == c.b
    assert not c.handler._status_for(c.catalogue_b.get("Demo"))["can_run"]


def test_setup_exception_does_not_leave_handler_pinned(libraries, monkeypatch):
    c = libraries
    def fail(*args, **kwargs):
        c.activate()
        raise OSError("fixture preparation failure")
    monkeypatch.setattr(setup, "prepare", fail)
    c.handler._stream_agent_setup({"model": "Demo", "provider": "api:deepseek"})
    assert c.handler.library_root == c.b and c.handler.catalog is c.catalogue_b
    assert not {"library_root", "catalog", "catalogue_integrity_errors"}.intersection(vars(c.handler))
    assert setup_jobs.status(c.workroot, "Demo")["state"] == "failed"


def test_incomplete_activation_cannot_drop_catalogue_enrollment_errors(libraries):
    c = libraries
    # Activation's catalogue assignment has happened but its error/root pair
    # has not. Do not reinterpret B using A's clean enrollment error map.
    c.handler_type.catalog = c.catalogue_b
    c.handler._stream_agent_setup({"model": "Demo", "provider": "api:deepseek"})
    assert c.responses[-1][0] == 409
    assert "library changed" in c.responses[-1][1]["error"]
    assert setup_jobs.status(c.workroot, "Demo") is None
    assert not (c.root / "status.json").exists()


def test_context_restores_explicit_instance_overrides_and_clears_lookup_caches(libraries):
    c = libraries
    c.handler.catalog, c.handler.library_root = c.catalogue_a, c.a
    prior_errors = {"Demo": "fixture enrollment error"}
    c.handler.catalogue_integrity_errors = prior_errors
    c.handler._default_status_files = {"old": "cached"}
    c.handler._install_location_index = {"models": {"old": "cached"}}
    def operation():
        c.activate()
        assert c.handler.catalogue_integrity_errors == prior_errors
        assert c.handler.library_root == c.a
        raise OSError("fixture operation failure")
    with pytest.raises(OSError, match="operation failure"):
        c.handler._with_setup_library(operation)
    assert c.handler.catalog is c.catalogue_a and c.handler.library_root == c.a
    assert c.handler.catalogue_integrity_errors is prior_errors
    assert c.handler._default_status_files is None
    assert c.handler._install_location_index is None


@pytest.mark.parametrize("kind", ["bundled", "imported", "custom-model-directory"])
def test_capture_keeps_existing_library_membership_rules(libraries, kind):
    c = libraries
    name = "Demo"
    if kind == "bundled":
        (c.a / ki_updates.SNAPSHOT_MANIFEST).unlink()
    elif kind == "imported":
        user_dir = c.a.parent / "user_models"
        imported = user_dir / "Imported"
        shutil.copytree(c.ki.root, imported)
        ki_guard.enroll(imported)
        c.handler_type.catalog = catalog.Catalog(c.a / "models", user_dir=user_dir)
        name = "Imported"
    else:
        custom = c.a / "custom_model_directory"
        shutil.copytree(c.a / "models", custom)
        ki_guard.enroll(custom / "Demo")
        c.handler_type.catalog = catalog.Catalog(custom)
    def inspect():
        selected = c.handler._ki(name)
        return c.handler.library_root, software_verification.identity(
            selected, c.handler._manifest(selected), c.handler.library_root)
    pinned_root, receipt_identity = c.handler._with_setup_library(inspect)
    assert pinned_root == c.a
    assert (receipt_identity is None) is (kind != "custom-model-directory")
