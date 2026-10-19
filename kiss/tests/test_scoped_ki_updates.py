"""Selection transport fixtures keep signing/doctor/closure checks real."""
from __future__ import annotations

import json
import shutil
from types import SimpleNamespace
import zipfile
from pathlib import Path

import pytest

from kiss_cli import catalog, ki_guard, ki_updates, published_acceptance, scoped_ki_updates as scoped
from .test_ki_verification_boundaries import isolated_engine, package_files


@pytest.fixture
def case(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_KI_UPDATE_HOME", str(tmp_path / "updates"))
    base = tmp_path / "base"
    (base / "models").mkdir(parents=True)
    monkeypatch.setattr(ki_updates.UpdateManager, "_windows_guidance", lambda _: None)
    monkeypatch.setattr(ki_updates, "_guards_guidance", lambda: False)
    monkeypatch.setattr(ki_updates, "installation_platform", lambda: "linux")
    monkeypatch.setattr(catalog, "installation_platform", lambda: "linux")
    def remote(manager):
        manager._source_commit = "d" * 40
        manager._archive_ref = manager._source_commit
        manager._component_trees = {"models": "a" * 40, "manifests": "b" * 40,
                                    "shared_tools": "c" * 40, "data_kis": None}
        return "f" * 32, "a" * 40, "b" * 40
    monkeypatch.setattr(ki_updates.UpdateManager, "_remote_revision", remote)
    with isolated_engine(tmp_path) as engine:
        yield tmp_path, base, monkeypatch, engine


def archive(case, *, dependencies=None, bad=None, include_dependency=True, unsafe=False, manifests=None,
            missing_manifests=()):
    tmp, base, monkeypatch, engine = case
    path = tmp / "source.zip"
    packages = ["Demo", "Unrelated"] + (["Dependency"] if include_dependency else [])
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("repo/ki_tools_common/pyproject.toml", '[project]\nname="ki_tools_common"\nversion="1"\n')
        z.writestr("repo/ki_tools_common/ki_tools_common/__init__.py", "# exact official helpers\n")
        for name in packages:
            for relative, text in package_files(name).items():
                if bad == name and relative == "preflight_check.py":
                    text = "print('missing report contract')\n"
                z.writestr(f"repo/models/{name}/{relative}", text)
            deps = "\ndepends_on: " + json.dumps(dependencies) if name == "Demo" and dependencies is not None else ""
            if name not in missing_manifests:
                z.writestr(f"repo/kiss/manifests/{name}.yaml", (manifests or {}).get(name,
                           f"kiss_manifest_version: 1\nmodel: {name}\nverified: unverified\n" + deps))
        if unsafe:
            z.writestr("repo/models/../escape.py", "bad")
    monkeypatch.setattr(ki_updates.UpdateManager, "_download", lambda _, dest: shutil.copyfile(path, dest))
    return path


def build(case, **kwargs):
    return scoped._Builder(case[1], ["Demo"], kwargs.pop("expected_commit", "d" * 40)).build()


def test_missing_install_recipe_keeps_checked_package_available_for_agent_setup(case):
    from kiss_cli.manifest import Manifest
    archive(case, missing_manifests={"Demo"})

    result = build(case)

    assert result["state"] == "ready", result
    root, meta = scoped.require_selection(result["scope_id"])
    ki = catalog.Catalog(root / "models").get("Demo")
    assert ki.manifest is None
    assert not (root / "kiss/manifests/Demo.yaml").exists(), "Do not fabricate official recipe bytes"
    stub = Manifest.stub_for(ki)
    assert stub.verified == "unverified" and not stub.trustworthy
    assert stub.depends_on == []
    assert meta["selected_models"] == ["Demo"]
    assert meta["publication_acceptance"]["native_regression"] == "not_run"
    assert [row["name"] for row in meta["publication_acceptance"]["packages"]] == ["Demo"]
    assert {row[0] for row in case[3].seen} >= {"candidate"}, "Missing recipe cannot skip KDT"
    assert ki_guard.require_intact(ki.root)
    assert result["global_library_changed"] is False


def test_declared_dependency_without_its_own_recipe_is_still_included_and_checked(case):
    archive(case, dependencies=["Dependency"], missing_manifests={"Dependency"})

    result = build(case)

    assert result["state"] == "ready", result
    root, meta = scoped.require_selection(result["scope_id"])
    assert meta["selected_models"] == ["Demo", "Dependency"]
    assert {row["name"] for row in meta["publication_acceptance"]["packages"]} == {"Demo", "Dependency"}
    assert not (root / "kiss/manifests/Dependency.yaml").exists()
    assert ki_guard.require_intact(root / "models/Dependency")


def test_windows_shaw_with_only_macos_recipe_uses_unverified_inferred_route(case):
    from kiss_cli.manifest import Manifest
    path = archive(case)
    case[2].setattr(ki_updates, "installation_platform", lambda: "windows")
    case[2].setattr(catalog, "installation_platform", lambda: "windows")
    with zipfile.ZipFile(path, "a") as zipped:
        for relative, text in package_files("SHAW").items():
            if relative == "dag.yaml":
                text = text.replace("  repo_url: https://example.org/model\n", "")
            zipped.writestr(f"repo/models/SHAW/{relative}", text)
        zipped.writestr("repo/models/SHAW/kiss.macos.arm64.yaml",
                        "kiss_manifest_version: 1\nmodel: SHAW\nverified: unverified\n")

    result = scoped._Builder(case[1], ["SHAW"], "d" * 40).build()

    assert result["state"] == "ready", result
    root, meta = scoped.require_selection(result["scope_id"])
    ki = catalog.Catalog(root / "models").get("SHAW")
    assert ki.manifest is None, "A macOS-only recipe must not become the Windows recipe"
    assert (ki.root / "kiss.macos.arm64.yaml").is_file()
    assert not (ki.root / "kiss.windows.yaml").exists()
    assert not (root / "kiss/manifests/SHAW.yaml").exists()
    stub = Manifest.stub_for(ki)
    assert stub.verified == "unverified" and stub.acquire.strategy == "manual"
    assert meta["selected_models"] == ["SHAW"]
    assert [row["name"] for row in meta["publication_acceptance"]["packages"]] == ["SHAW"]
    assert meta["publication_acceptance"]["native_regression"] == "not_run"
    assert {row[0] for row in case[3].seen} >= {"candidate"}
    assert ki_guard.require_intact(ki.root)


@pytest.mark.parametrize("failure", ["package", "kdt"])
def test_missing_recipe_never_bypasses_package_or_kdt_failure(case, failure):
    archive(case, missing_manifests={"Demo"}, bad="Demo" if failure == "package" else None)
    if failure == "kdt":
        case[3].ok = False

    result = build(case)

    assert result["state"] == "error" and result["scope_id"] is None
    assert not list((ki_updates.update_root() / "scoped-snapshots").glob("*"))
    if failure == "kdt":
        assert "fixture KDT failure" in result["error"]


@pytest.mark.parametrize("placement", ["shipped", "platform"])
@pytest.mark.parametrize("recipe", [
    "kiss_manifest_version: 1\nmodel: Foreign\n",
    "kiss_manifest_version: 999\nmodel: Demo\n",
    "kiss_manifest_version: 1\nmodel: [\n",
    "kiss_manifest_version: 1\nmodel: Demo\nruntime_paths: {version: 1, mode: unknown}\n",
])
def test_existing_invalid_recipe_is_not_replaced_by_an_inferred_stub(case, placement, recipe):
    if placement == "shipped":
        archive(case, manifests={"Demo": recipe})
    else:
        # A valid fallback must not hide a broken preferred platform recipe.
        path = archive(case)
        with zipfile.ZipFile(path, "a") as zipped:
            zipped.writestr("repo/models/Demo/kiss.linux.yaml", recipe)

    result = build(case)

    assert result["state"] == "error" and result["scope_id"] is None
    assert not list((ki_updates.update_root() / "scoped-snapshots").glob("*"))


def test_present_nonfile_recipe_is_not_treated_as_missing(case):
    root = case[0] / "nonfile-source"
    ki = root / "models/Demo"
    ki.mkdir(parents=True)
    (ki / "SKILL.md").write_text("# Demo\n", encoding="utf-8")
    # The regular fallback path exists but is a directory, not absent metadata.
    (root / "kiss/manifests/Demo.yaml").mkdir(parents=True)

    with pytest.raises(ValueError, match="not a regular file"):
        scoped._closure(root, ["Demo"])


def test_adding_recipe_after_acceptance_invalidates_missing_recipe_selection(case):
    archive(case, missing_manifests={"Demo"})
    result = build(case)
    assert result["state"] == "ready", result
    root, _ = scoped.require_selection(result["scope_id"])
    (root / "kiss/manifests/Demo.yaml").write_text(
        "kiss_manifest_version: 1\nmodel: Demo\n", encoding="utf-8")

    with pytest.raises(ValueError):
        scoped.require_selection(result["scope_id"])


def test_unrelated_invalid_package_does_not_enter_selection_or_change_global_state(case):
    archive(case, bad="Unrelated")
    home = ki_updates.update_root()
    home.mkdir(parents=True)
    (home / "state.json").write_text('{"active_snapshot":"keep"}')
    (home / "last-report.json").write_text('{"state":"error","error":"whole library rejected"}')
    before = {p.name: p.read_bytes() for p in (home / "state.json", home / "last-report.json")}
    result = build(case)
    assert result["state"] == "ready", result
    root, meta = scoped.require_selection(result["scope_id"])
    assert result["global_library_changed"] is False
    assert meta["selected_models"] == ["Demo"]
    assert set(catalog.Catalog(root / "models").packages) == {"Demo"}
    assert meta["source_commit"] == "d" * 40
    assert result["components"]["data_kis"]["state"] == "not_in_source"
    assert meta["publication_acceptance"]["scope"] == "official_published_selection"
    assert meta["publication_acceptance"]["package_validation"] != published_acceptance.SNAPSHOT_CONTRACT
    assert (root / "ki_tools_common/ki_tools_common/__init__.py").read_text() == "# exact official helpers\n"
    assert all((home / name).read_bytes() == data for name, data in before.items())
    assert published_acceptance.catalogue_bindings(catalog.Catalog(root / "models"))["Demo"]
    assert ki_guard.require_intact(root / "models/Demo")
    with pytest.raises(ValueError, match="signed acceptance"):
        published_acceptance.require_snapshot(root, meta)


def test_dependency_closure_is_included_and_checked(case):
    archive(case, dependencies=["Dependency"])
    result = build(case)
    assert result["state"] == "ready", result
    _, meta = scoped.require_selection(result["scope_id"])
    assert meta["selected_models"] == ["Demo", "Dependency"]
    assert {row[0] for row in case[3].seen} >= {"candidate"}
    assert len(meta["publication_acceptance"]["packages"]) == 2


@pytest.mark.parametrize("bad", ["Demo", "Dependency"])
def test_selected_or_required_bad_package_blocks_selection(case, bad):
    archive(case, dependencies=["Dependency"], bad=bad)
    result = build(case)
    assert result["state"] == "error"
    assert result["scope_id"] is None
    assert not list((ki_updates.update_root() / "scoped-snapshots").glob("*"))


def test_missing_dependency_fails_closed(case):
    archive(case, dependencies=["Missing"])
    result = build(case)
    assert result["state"] == "error" and "Missing" in result["error"]


@pytest.mark.parametrize("dependency", [["demo"], ["../Demo"], "Dependency"])
def test_nonexact_or_malformed_dependency_is_not_guessed(case, dependency):
    archive(case, dependencies=dependency)
    assert build(case)["state"] == "error"


def test_changed_main_commit_requires_refresh(case):
    archive(case)
    result = build(case, expected_commit="e" * 40)
    assert result["state"] == "error" and "revision changed" in result["error"]


def test_unsafe_archive_rejected_before_selection(case):
    archive(case, unsafe=True)
    result = build(case)
    assert result["state"] == "error" and "unsafe path" in result["error"]


@pytest.mark.parametrize("target", ["model", "helper", "manifest", "selected", "requested", "signature", "extra_ki"])
def test_reopen_rejects_tampering(case, target):
    archive(case)
    result = build(case)
    assert result["state"] == "ready", result
    root, meta = scoped.require_selection(result["scope_id"])
    if target in {"selected", "requested", "signature"}:
        if target == "signature":
            meta["publication_acceptance"]["signature"] = {}
        else:
            meta[target + "_models"] = ["Unrelated"]
        (root / ki_updates.SNAPSHOT_MANIFEST).write_text(json.dumps(meta))
    elif target == "extra_ki":
        shutil.copytree(root / "models/Demo", root / "models/Unrelated")
    else:
        path = {"model": "models/Demo/SKILL.md", "helper": "ki_tools_common/ki_tools_common/__init__.py",
                "manifest": "kiss/manifests/Demo.yaml"}[target]
        with (root / path).open("a") as handle:
            handle.write("\n# changed\n")
    with pytest.raises((ValueError, TypeError)):
        scoped.require_selection(result["scope_id"])
    assert published_acceptance.catalogue_bindings(catalog.Catalog(root / "models")) == {}


def test_failed_kdt_cannot_produce_selection(case):
    archive(case)
    case[3].ok = False
    result = build(case)
    assert result["state"] == "error" and "fixture KDT failure" in result["error"]


def test_changed_registered_source_remains_blocked(case):
    archive(case)
    live = case[1] / "models/Demo"
    live.mkdir()
    for relative, text in package_files("Demo").items():
        (live / relative).write_text(text)
    ki_guard.enroll(live)
    (live / "SKILL.md").write_text("changed active package")
    result = build(case)
    assert result["state"] == "error" and result["scope_id"] is None


def test_mutation_after_verification_cannot_be_sealed(case):
    archive(case)
    original = ki_updates.UpdateManager._validate
    def changed(manager, root):
        result = original(manager, root)
        (root / "models/Demo/SKILL.md").write_text("after check")
        return result
    case[2].setattr(ki_updates.UpdateManager, "_validate", changed)
    result = build(case)
    assert result["state"] == "error" and "changed after" in result["error"]


def test_current_engine_identity_is_required_on_reopen(case):
    from kiss_cli import kdtstudio
    archive(case)
    result = build(case)
    assert result["state"] == "ready", result
    case[2].setattr(kdtstudio, "engine_source_digest", lambda *_: "e" * 64)
    with pytest.raises(ValueError):
        scoped.require_selection(result["scope_id"])


@pytest.mark.parametrize("damage", [None, "component", "required_notes"])
def test_windows_authenticated_composition_selection(case, damage):
    import yaml
    from kiss_cli import ki_guidance_composition, raw_windows_guidance
    from .test_raw_windows_guidance import prepare_fixture
    from .test_ki_update_raw_guidance import generic, windows, raw_files
    main_recipe = {**generic(), "python_deps": ["numpy>=2"]}
    archive(case, manifests={"Demo": yaml.safe_dump(main_recipe)})
    component = prepare_fixture(raw_files(windows(), base=generic()))
    monkeypatch = case[2]
    monkeypatch.setattr(ki_updates, "installation_platform", lambda: "windows")
    monkeypatch.setattr(catalog, "installation_platform", lambda: "windows")
    monkeypatch.setattr(ki_updates, "_guards_guidance", lambda: True)
    monkeypatch.setattr(ki_updates.UpdateManager, "_windows_guidance", lambda _: component)
    if damage == "component":
        (component["root"] / "models/Demo/docs/install.windows.md").write_text("tampered official notes")
    elif damage == "required_notes":
        original = ki_guidance_composition.compose
        def missing(*args, **kwargs):
            result = original(*args, **kwargs)
            (args[1] / "models/Demo/docs/install.windows.md").unlink()
            return result
        monkeypatch.setattr(ki_guidance_composition, "compose", missing)
    result = build(case)
    if damage:
        assert result["state"] == "error", result
        if damage == "required_notes":
            assert "Demo: docs/install.windows.md" in result["error"], result
        return
    assert result["state"] == "ready", result
    root, meta = scoped.require_selection(result["scope_id"])
    recipe = yaml.safe_load((root / "models/Demo/kiss.windows.yaml").read_text())
    assert recipe["acquire"] == windows()["acquire"]
    assert recipe["python_deps"] == generic(2)["python_deps"]
    assert meta["windows_overlay"]["composition"]["windows"]["component_id"] == component["evidence"]["component_id"]
    assert raw_windows_guidance.require_current(component["root"], component["evidence"])


@pytest.mark.parametrize("damage", [[], ["bad"], "bad", 3])
def test_malformed_envelope_is_a_validation_error(case, damage):
    archive(case)
    result = build(case)
    root, meta = scoped.require_selection(result["scope_id"])
    meta["publication_acceptance"] = damage
    (root / ki_updates.SNAPSHOT_MANIFEST).write_text(json.dumps(meta))
    with pytest.raises(ValueError):
        scoped.require_selection(result["scope_id"])


def test_repeat_revalidates_and_reuses_identical_selection(case):
    archive(case)
    first = build(case)
    second = build(case)
    assert first["state"] == second["state"] == "ready", (first, second)
    assert first["scope_id"] == second["scope_id"]
    assert first["job_id"] != second["job_id"]
    assert len(case[3].seen) == 2


def test_new_commit_with_identical_packages_keeps_both_pinned_selections_valid(case):
    archive(case)
    first = build(case)
    assert first["state"] == "ready"
    old_root, old_meta = scoped.require_selection(first["scope_id"])
    original = ki_updates.UpdateManager._remote_revision

    def new_commit(manager):
        result = original(manager)
        manager._source_commit = "e" * 40
        manager._archive_ref = manager._source_commit
        return result

    case[2].setattr(ki_updates.UpdateManager, "_remote_revision", new_commit)
    second = build(case, expected_commit="e" * 40)
    assert second["state"] == "ready", second
    new_root, new_meta = scoped.require_selection(second["scope_id"])
    assert first["scope_id"] != second["scope_id"]
    assert old_meta["content_sha256"] == new_meta["content_sha256"]
    assert old_meta["source_commit"] == "d" * 40
    assert new_meta["source_commit"] == "e" * 40
    assert scoped.require_selection(first["scope_id"]) == (old_root, old_meta)
    assert scoped.require_selection(second["scope_id"]) == (new_root, new_meta)


def test_async_job_can_be_polled_without_full_update_side_effect(case):
    archive(case)
    result = scoped.start(case[1], ["Demo"], expected_commit="d" * 40)
    scoped._JOBS[result["job_id"]].join(timeout=30)
    finished = scoped.status(result["job_id"])
    assert finished["state"] == "ready", finished
    assert not (ki_updates.update_root() / "state.json").exists()
    assert not (ki_updates.update_root() / "last-report.json").exists()


@pytest.mark.parametrize("value", ["../x", "", "A" * 32, None])
def test_invalid_scope_id_refused(value):
    with pytest.raises(ValueError):
        scoped.require_selection(value)


def frozen_module(monkeypatch, tmp_path):
    """Keep real module code but model its source-free frozen import surface."""
    source = Path(scoped.__file__).read_text(encoding="utf-8")
    code = [compile(source, scoped.__name__, "exec")]
    requested = []
    def get_code(name):
        requested.append(name)
        return code[0]
    monkeypatch.setattr(scoped, "__file__", str(tmp_path / "frozen" / "scoped_ki_updates.pyc"))
    monkeypatch.setattr(scoped, "__loader__", SimpleNamespace(get_code=get_code))
    return source, code, requested


def test_source_free_frozen_module_can_publish_and_reopen_checked_selection(case):
    archive(case)
    _, _, requested = frozen_module(case[2], case[0])
    result = build(case)
    assert result["state"] == "ready", result
    root, meta = scoped.require_selection(result["scope_id"])
    assert (root / "models/Demo/SKILL.md").is_file()
    assert meta["publication_acceptance"]["implementation"] == scoped._implementation()
    assert requested and set(requested) == {scoped.__name__}


def test_changed_frozen_implementation_invalidates_acceptance_without_grandfathering(case):
    archive(case)
    source, code, _ = frozen_module(case[2], case[0])
    first = build(case)
    assert first["state"] == "ready", first
    first_identity = scoped._implementation()
    # Changing any part of the loader's complete module, not only the identity
    # function, must break currentness of already signed publication acceptance.
    code[0] = compile(source + '\nFROZEN_IMPLEMENTATION_REVISION = "changed"\n', scoped.__name__, "exec")
    assert scoped._implementation() != first_identity
    with pytest.raises(ValueError, match="no current signed acceptance"):
        scoped.require_selection(first["scope_id"])
    second = build(case)
    assert second["state"] == "ready", second
    assert second["scope_id"] != first["scope_id"]
    scoped.require_selection(second["scope_id"])
    with pytest.raises(ValueError, match="no current signed acceptance"):
        scoped.require_selection(first["scope_id"])


@pytest.mark.parametrize("loader", [None, SimpleNamespace(get_code=lambda name: None),
                                    SimpleNamespace(get_code=lambda name: b"not a code object")])
def test_unidentifiable_frozen_implementation_cannot_publish_or_reopen(case, loader):
    archive(case)
    frozen_module(case[2], case[0])
    result = build(case)
    assert result["state"] == "ready", result
    case[2].setattr(scoped, "__loader__", loader)
    with pytest.raises(ValueError, match="Cannot identify"):
        scoped.require_selection(result["scope_id"])
    failed = build(case)
    assert failed["state"] == "error" and failed["scope_id"] is None
    assert "Cannot identify" in failed["error"]


def test_readable_source_and_loader_code_have_distinct_identities(case):
    archive(case)
    source_result = build(case)
    assert source_result["state"] == "ready", source_result
    source_identity = scoped._implementation()
    frozen_module(case[2], case[0])
    assert scoped._implementation() != source_identity
    with pytest.raises(ValueError, match="no current signed acceptance"):
        scoped.require_selection(source_result["scope_id"])
