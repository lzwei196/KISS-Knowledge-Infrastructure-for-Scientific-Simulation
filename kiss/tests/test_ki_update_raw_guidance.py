"""Update from independent raw Windows inputs, never a previous merged library.

The updater, composer, signed component and snapshot gates are real. Only the
official network and published KDT engine use the existing isolated fixtures.
No native model, provider, live network or Git process is needed.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from kiss_cli import catalog, ki_guard, ki_platform_overlay, ki_updates
from kiss_cli import raw_windows_guidance as raw
from . import test_ki_updates as updater_tests
from .test_raw_windows_guidance import prepare_fixture


def generic(version=1, name="Demo"):
    return {"kiss_manifest_version": 1, "model": name, "binary_type": "ELF",
            "verified": "unverified", "install_dir": name,
            "acquire": {"strategy": "download", "url": f"https://example.org/linux-{version}.zip",
                        "produces": "bin/solver"}, "python_deps": [f"numpy>={version}"]}


def windows(version=1, name="Demo"):
    return {**generic(1, name), "binary_type": "PE32", "verified": "manual",
            "acquire": {"strategy": "manual", "exe": "solver.exe"},
            "agent_hint": f"Windows guidance revision {version}."}


def raw_files(recipe, *, base=None):
    name = recipe["model"]
    return {f"models/{name}/SKILL.md": f"Official {name} membership\n",
            f"models/{name}/kiss.windows.yaml": yaml.safe_dump(recipe),
            f"models/{name}/docs/install.windows.md": "Use the native Windows executable.\n",
            f"kiss/manifests/{name}.yaml": yaml.safe_dump(base if base is not None else recipe)}


@pytest.fixture
def update_case(monkeypatch):
    case = updater_tests.KiUpdateTests()
    case.setUp()
    monkeypatch.setattr(ki_updates, "installation_platform", lambda: "windows")
    monkeypatch.setattr(catalog, "installation_platform", lambda: "windows")
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(case.root / "raw-flow-keys"))
    monkeypatch.setenv("GEOFORGE_KI_VERIFICATION_HOME", str(case.root / "raw-verification"))
    case._write_ki(case.base, "Demo", "Installed original model")
    activated = []
    manager = ki_updates.UpdateManager(case.base, activated.append, branch="main")
    monkeypatch.setattr(manager, "_request_json", lambda *_: pytest.fail("Live network requested"))
    # A new raw route must not silently authenticate yesterday's merged output.
    monkeypatch.setattr(manager, "_check_overlay_source", lambda *_: pytest.fail("Legacy source reused"))
    yield SimpleNamespace(case=case, manager=manager, activated=activated, monkeypatch=monkeypatch)
    case.tearDown()


def run_update(c, component, *, version=1, model="Demo", main_windows=None, native=None):
    main = generic(version, model) if native is None else native
    extra = {f"models/{model}/kiss.yaml": yaml.safe_dump(main),
             "ki_tools_common/ki_tools_common/revision.py": f"VERSION = {version}\n"}
    if main_windows is not None:
        extra.update({f"models/{model}/kiss.windows.yaml": yaml.safe_dump(main_windows),
                      f"models/{model}/docs/install.windows.md": "Main owns these Windows notes.\n"})
    archive = c.case._archive({model: f"Main scientific KI revision {version}"}, extra=extra)
    token = hashlib.sha1(f"main-{version}-{model}".encode()).hexdigest()
    trees = {"models": token, "manifests": token, "shared_tools": token, "data_kis": None}
    c.manager._component_trees, c.manager._source_commit = trees, token
    revision = ki_updates._revision_identity(trees)
    c.monkeypatch.setattr(c.manager, "_windows_guidance", lambda: component)
    c.monkeypatch.setattr(c.manager, "_remote_revision", lambda: (revision, token, token))
    downloads = []
    def download(destination):
        downloads.append(destination)
        shutil.copyfile(archive, destination)
    c.monkeypatch.setattr(c.manager, "_download", download)
    c.manager._run()
    return c.manager.status(), downloads


def success(c, report):
    assert report["state"] in {"updated", "up_to_date"}, report.get("error", report)
    assert c.activated and ki_updates._snapshot_valid(c.activated[-1])
    return c.activated[-1]


def test_actual_apex_uses_raw_bytes_instead_of_previous_serialized_recipe(update_case):
    c = update_case
    source = Path(__file__).parents[2] / "models/APEX/kiss.windows.yaml"
    original = source.read_bytes()
    recipe = yaml.safe_load(original)
    files = raw_files(recipe)
    files["models/APEX/kiss.windows.yaml"] = original
    component = prepare_fixture(files)
    # Packaged route is genuine: this fixture has no Git checkout or SKILL copy.
    assert not (component["root"] / ".git").exists()
    assert not (component["root"] / "models/APEX/SKILL.md").exists()
    first_report, _ = run_update(c, component, model="APEX")
    first = success(c, first_report)
    composed = (first / "models/APEX/kiss.windows.yaml").read_bytes()
    assert composed != original and yaml.safe_load(composed)["verified"] == "unverified"
    second_report, _ = run_update(c, component, version=2, model="APEX")
    second = success(c, second_report)
    row = next(row for row in second_report["windows_overlay"]["files"]
               if row["source"]["path"].endswith("kiss.windows.yaml"))
    assert row["source"]["sha256"] == hashlib.sha256(original).hexdigest()
    assert row["source"]["sha256"] != hashlib.sha256(composed).hexdigest()
    assert yaml.safe_load((second / row["output"]["path"]).read_text(encoding="utf-8"))["acquire"] == recipe["acquire"]
    assert (first / "models/APEX/kiss.windows.yaml").read_bytes() == composed


def test_two_main_updates_do_not_rebase_on_previous_composition(update_case):
    c = update_case
    component = prepare_fixture(raw_files(windows()))
    first_report, _ = run_update(c, component)
    first = success(c, first_report)
    first_digest = ki_updates._snapshot_content_hash(first)
    # Reproduce the old false conflict with exactly the first snapshot as base.
    control = c.case.root / "old-route-control/models/Demo"
    control.mkdir(parents=True)
    (control / "SKILL.md").write_text("Demo")
    (control / "kiss.yaml").write_text(yaml.safe_dump(generic(2)))
    with pytest.raises(ki_platform_overlay.OverlayConflict, match="acquire"):
        ki_platform_overlay.apply_windows_overlay(first, control.parents[1])
    second_report, _ = run_update(c, component, version=2)
    second = success(c, second_report)
    result = yaml.safe_load((second / "models/Demo/kiss.windows.yaml").read_text())
    assert result["acquire"] == windows()["acquire"] and result["python_deps"] == ["numpy>=2"]
    assert second != first and ki_updates._snapshot_content_hash(first) == first_digest
    assert second_report["windows_overlay"]["composition"]["windows"]["component_id"] == component["evidence"]["component_id"]


@pytest.mark.parametrize("main_owns_windows", [False, True])
def test_windows_only_change_invalidates_fast_path_even_without_overlay_files(update_case, main_owns_windows):
    c = update_case
    first_component = prepare_fixture(raw_files(windows(1)), commit="a" * 40)
    options = {"main_windows": windows(9)} if main_owns_windows else {}
    first_report, _ = run_update(c, first_component, **options)
    first = success(c, first_report)
    second_component = prepare_fixture(raw_files(windows(2)), commit="b" * 40)
    second_report, downloads = run_update(c, second_component, **options)
    second = success(c, second_report)
    assert second != first and second_report["active_revision"] != first_report["active_revision"]
    assert not downloads  # Same immutable main archive, fresh composition/validation.
    composition = second_report["windows_overlay"]["composition"]
    assert composition["windows"]["component_id"] == second_component["evidence"]["component_id"]
    state = json.loads((c.case.home / "state.json").read_text())
    assert state["windows_component_id"] == second_component["evidence"]["component_id"]
    result = yaml.safe_load((second / "models/Demo/kiss.windows.yaml").read_text())
    assert result["agent_hint"] == windows(9 if main_owns_windows else 2)["agent_hint"]
    if main_owns_windows:
        assert second_report["windows_overlay"]["files"] == []
        assert ki_updates._snapshot_content_hash(first) == ki_updates._snapshot_content_hash(second)
    report, downloads = run_update(c, second_component, **options)
    assert report["state"] == "up_to_date" and report["active_revision"] == second_report["active_revision"]
    assert not downloads and c.activated[-1] == second


def test_raw_metadata_never_replaces_main_helpers_or_existing_project_bindings(update_case):
    c = update_case
    files = raw_files(windows())
    files["ki_tools_common/ki_tools_common/revision.py"] = "WRONG_WINDOWS_HELPER = True\n"
    component = prepare_fixture(files)
    assert not ki_guard.is_managed(c.case.base / "models/Demo")
    project = c.case.root / "existing-project/models/Demo"
    project.mkdir(parents=True)
    config = project / "kiss.toml"
    config.write_bytes(b'[kiss]\nroot="saved-project"\npython="saved-python"\n')
    helper = c.case.root / "existing-helper/reader.py"
    helper.parent.mkdir()
    helper.write_bytes(b"EXISTING_HELPER = True\n")
    original = config.read_bytes(), helper.read_bytes(), ki_updates._snapshot_content_hash(c.case.base)
    report, _ = run_update(c, component)
    snapshot = success(c, report)
    assert (snapshot / "ki_tools_common/ki_tools_common/revision.py").read_text() == "VERSION = 1\n"
    assert (config.read_bytes(), helper.read_bytes(), ki_updates._snapshot_content_hash(c.case.base)) == original
    assert not (component["root"] / "ki_tools_common").exists()
    # Reading an old unmanaged KI does not grant it a guard baseline. Incoming
    # packages still passed the real updater publication envelope independently.
    assert not ki_guard.is_managed(c.case.base / "models/Demo")
    assert report["ki_verification"]
    assert json.loads((snapshot / ki_updates.SNAPSHOT_MANIFEST).read_text())["publication_acceptance"]


@pytest.mark.parametrize("damage", ["bytes", "proof"])
def test_invalid_raw_component_cannot_reuse_current_snapshot_or_legacy_guidance(update_case, damage):
    c = update_case
    component = prepare_fixture(raw_files(windows()))
    report, _ = run_update(c, component)
    current = success(c, report)
    state = (c.case.home / "state.json").read_bytes()
    if damage == "bytes":
        (component["root"] / "models/Demo/kiss.windows.yaml").write_text("altered raw metadata")
    else:
        component["evidence"] = dict(component["evidence"], source_commit="f" * 40)
    report, downloads = run_update(c, component)
    assert report["state"] == "error" and not downloads
    assert c.manager.current_library_root == current and c.activated == [current]
    assert (c.case.home / "state.json").read_bytes() == state


def test_true_raw_generic_conflict_quarantines_without_partial_guidance(update_case):
    c = update_case
    component = prepare_fixture(raw_files(windows(), base=generic(1)))
    report, _ = run_update(c, component, version=2)
    assert report["state"] == "error" and c.activated == []
    assert "acquire" in report["error"]
    failure = report["validation_failure"]
    assert failure["stage"] == "windows_overlay" and not failure["activated"]
    rejected = Path(failure["quarantine_path"])
    assert not (rejected / "models/Demo/kiss.windows.yaml").exists()
    assert not (rejected / "models/Demo/docs/install.windows.md").exists()
    assert raw.require_current(component["root"], component["evidence"])
    assert not (c.case.home / "state.json").exists()


def test_new_raw_component_cannot_hide_changed_registered_active_ki(update_case):
    c = update_case
    component = prepare_fixture(raw_files(windows()))
    report, _ = run_update(c, component)
    current = success(c, report)
    active = current / "models/Demo"
    # The live GUI enrolls selected source KIs; the isolated activation callback
    # above only records paths, so mirror that explicit existing guard baseline.
    ki_guard.enroll(active)
    assert ki_guard.is_managed(active)
    (active / "SKILL.md").write_text("unreviewed active edit")
    newer = prepare_fixture(raw_files(windows(2)), commit="b" * 40)
    report, _ = run_update(c, newer, version=2)
    assert report["state"] == "error" and c.activated == [current]
    assert c.manager.current_library_root == current
    assert (active / "SKILL.md").read_text() == "unreviewed active edit"


def test_registered_ki_with_only_shared_generic_manifest_is_still_guarded(update_case):
    c = update_case
    active = c.case.base / "models/Demo"
    assert (c.case.base / "kiss/manifests/Demo.yaml").is_file()
    assert not list(active.glob("kiss*.yaml"))
    ki_guard.enroll(active)
    (active / "SKILL.md").write_text("changed generic-only KI")
    component = prepare_fixture(raw_files(windows()))
    report, downloads = run_update(c, component)
    assert report["state"] == "error" and not downloads and c.activated == []
    assert c.manager.current_library_root == c.case.base
    assert (active / "SKILL.md").read_text() == "changed generic-only KI"
    assert not (c.case.home / "state.json").exists()
