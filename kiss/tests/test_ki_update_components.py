"""Coherent KI/helper sources without modifying the app or older study copies."""
import json
from pathlib import Path
from unittest import mock

import pytest

from kiss_cli import api, catalog, gui, ki_updates, paths, project_paths, prompt, setup
from . import test_ki_updates as updater_tests


def helper_snapshot(root, version="a"):
    package = root / "ki_tools_common/ki_tools_common"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(f"VERSION = {version!r}\n", encoding="utf-8")
    (root / "ki_tools_common/pyproject.toml").write_text(
        '[project]\nname="ki_tools_common"\nversion="0.1.0"\n', encoding="utf-8")
    (root / ki_updates.SNAPSHOT_MANIFEST).write_text(json.dumps({
        "schema_version": 1, "source_commit": version * 40,
        "trees": {"shared_tools": version * 40}}), encoding="utf-8")
    return root


def test_new_helper_revision_gets_separate_copy_and_preserves_local_source(tmp_path):
    app = helper_snapshot(tmp_path / "app", "a")
    updated = helper_snapshot(tmp_path / "snapshot", "b")
    original = (app / "ki_tools_common/ki_tools_common/__init__.py").read_bytes()
    cfg = paths.KissConfig.default(tmp_path / "install")
    first = setup.prepare_common(cfg, app)
    first_bytes = (first / "ki_tools_common/__init__.py").read_bytes()
    second = setup.prepare_common(cfg, updated)
    assert second != first and cfg.roles["ki_tools_common"] == second
    assert (first / "ki_tools_common/__init__.py").read_bytes() == first_bytes
    assert (app / "ki_tools_common/ki_tools_common/__init__.py").read_bytes() == original
    assert "'b'" in (second / "ki_tools_common/__init__.py").read_text()
    assert paths.with_ki_tools_common(cfg, {})["PYTHONPATH"].startswith(str(second.resolve()))


def test_pinned_copy_reuses_clean_source_but_preserves_and_rejects_local_edit(tmp_path):
    source = helper_snapshot(tmp_path / "source")
    cfg = paths.KissConfig.default(tmp_path / "install")
    target = setup.prepare_common(cfg, source)
    cache = target / "ki_tools_common/__pycache__/cache.pyc"
    cache.parent.mkdir()
    cache.write_bytes(b"generated cache")
    assert setup.prepare_common(cfg, source) == target
    edited = target / "ki_tools_common/__init__.py"
    edited.write_text("LOCAL_FIX = True\n", encoding="utf-8")
    with pytest.raises(ValueError, match="changed locally"):
        setup.prepare_common(cfg, source)
    assert edited.read_text() == "LOCAL_FIX = True\n"


def test_existing_project_helper_binding_is_preserved(tmp_path, monkeypatch):
    project = tmp_path / "project"
    shared = paths.KissConfig.default(tmp_path / "install")
    saved = project_paths.model_config(project, "M", shared)
    old_common = tmp_path / "old-common"
    old_common.mkdir()
    (old_common / "patch.py").write_text("local patch")
    saved.roles["ki_tools_common"] = old_common
    home = project / "models/M"
    home.mkdir(parents=True)
    (home / paths.CONFIG_NAME).write_text(saved.dumps(), encoding="utf-8")
    request = object.__new__(gui.Handler)
    request.repo_root = tmp_path / "app"
    request.library_root = helper_snapshot(tmp_path / "new-library", "b")
    request._config = lambda _ki: shared
    monkeypatch.setattr(setup, "prepare_common", lambda *_a: pytest.fail("existing binding was refreshed"))
    cfg = request._session_config(project, catalog.KI("M", tmp_path / "model"))
    assert cfg.roles["ki_tools_common"] == old_common
    assert (old_common / "patch.py").read_text() == "local patch"


def test_fresh_project_uses_active_snapshot_without_repointing_app(tmp_path):
    project = tmp_path / "project"
    app = helper_snapshot(tmp_path / "app", "a")
    snapshot = helper_snapshot(tmp_path / "snapshot", "b")
    request = object.__new__(gui.Handler)
    request.repo_root, request.library_root = app, snapshot
    request._config = lambda _ki: paths.KissConfig.default(tmp_path / "install")
    cfg = request._session_config(project, catalog.KI("M", tmp_path / "model"))
    assert request.repo_root == app
    assert "'b'" in (cfg.roles["ki_tools_common"] / "ki_tools_common/__init__.py").read_text()


def test_old_snapshot_fallback_is_explicit_and_new_missing_helper_fails(tmp_path):
    old = tmp_path / "old"
    old.mkdir()
    app = helper_snapshot(tmp_path / "app")
    assert ki_updates.shared_tools_root(old, app) == app
    report = ki_updates.component_sources(old)
    assert report["shared_tools"] == {"state": "bundled_fallback", "tree_sha": None, "source_commit": None}
    (old / ki_updates.SNAPSHOT_MANIFEST).write_text('{"schema_version":1}')
    with pytest.raises(ValueError, match="missing"):
        ki_updates.shared_tools_root(old, app)
    with pytest.raises(RuntimeError, match="required ki_tools_common"):
        ki_updates.UpdateManager(old, lambda _: None)._validate(old)


def test_data_ki_source_uses_snapshot_when_present_and_reports_fallback(tmp_path):
    snapshot = helper_snapshot(tmp_path / "snapshot")
    bundled = tmp_path / "bundled-data"
    bundled.mkdir()
    assert ki_updates.data_ki_root(snapshot, bundled) == bundled
    assert ki_updates.component_sources(snapshot)["data_kis"]["state"] == "bundled_fallback"
    data = snapshot / "kiss/data_kis"
    data.mkdir(parents=True)
    assert ki_updates.data_ki_root(snapshot, bundled) == data
    assert ki_updates.component_sources(snapshot)["data_kis"]["state"] == "snapshot"


@pytest.mark.parametrize("component", ["ki_tools_common", "data_kis"])
def test_helper_or_data_only_change_invalidates_revision(tmp_path, component):
    manager = ki_updates.UpdateManager(tmp_path, lambda _: None)
    def resolve(common_sha, data_sha):
        replies = [{"sha": "1" * 40, "commit": {"tree": {"sha": "2" * 40}}},
            {"tree": [{"path": "models", "sha": "3" * 40}, {"path": "kiss", "sha": "4" * 40},
                      {"path": "ki_tools_common", "sha": common_sha}]},
            {"tree": [{"path": "manifests", "sha": "5" * 40}, {"path": "data_kis", "sha": data_sha}]}]
        with mock.patch.object(manager, "_request_json", side_effect=replies):
            return manager._remote_revision()[0]
    before = resolve("6" * 40, "7" * 40)
    after = resolve("8" * 40 if component == "ki_tools_common" else "6" * 40,
                    "8" * 40 if component == "data_kis" else "7" * 40)
    assert after != before


def test_archive_keeps_shared_tools_and_data_kis_but_excludes_app_code(tmp_path):
    case = updater_tests.KiUpdateTests()
    case.setUp()
    try:
        archive = case._archive({"M": "model"}, extra={
            "kiss/data_kis/D/SKILL.md": "data KI", "kiss/kiss_cli/gui.py": "do not update app"})
        manager = ki_updates.UpdateManager(case.base, lambda _: None)
        target = tmp_path / "incoming"
        manager._extract(archive, target)
        assert (target / "ki_tools_common/ki_tools_common/__init__.py").is_file()
        assert (target / "kiss/data_kis/D/SKILL.md").is_file()
        assert not (target / "kiss/kiss_cli/gui.py").exists()
    finally:
        case.tearDown()


def test_windows_supplement_activates_with_provenance_and_unchanged_guard(tmp_path):
    case = updater_tests.KiUpdateTests()
    case.setUp()
    try:
        case._write_ki(case.base, "Demo", "old model")
        generic = 'kiss_manifest_version: 1\nmodel: Demo\npython_deps: ["numpy>=1"]\nbinary_type: ELF\n'
        (case.base / "models/Demo/kiss.yaml").write_text(generic)
        (case.base / "models/Demo/kiss.windows.yaml").write_text(generic.replace("ELF", "PE32+"))
        notes = case.base / "models/Demo/docs/install.windows.md"
        notes.parent.mkdir()
        notes.write_text("Retained Windows instructions.")
        archive = case._archive({"Demo": "new model"}, extra={
            "models/Demo/kiss.yaml": generic.replace("numpy>=1", "numpy>=2")})
        activated = []
        revision = "a" * 16 + "-" + "b" * 16
        with mock.patch.object(ki_updates, "installation_platform", return_value="windows"), \
             mock.patch.object(catalog, "installation_platform", return_value="windows"):
            report, _ = case._run_update(archive, activated, revision)
            assert report["state"] == "updated", report
            snapshot = activated[0]
            assert report["windows_overlay"]["setup_reverification_required"] is True
            assert len(report["active_revision"]) == 32
            assert report["active_revision"] != revision
            assert json.loads((snapshot / ki_updates.SNAPSHOT_MANIFEST).read_text())["upstream_revision"] == revision
            assert len(report["windows_overlay"]["files"]) == 2
            assert ki_updates._lost_guidance(case.base, snapshot) == []
            assert ki_updates._snapshot_valid(snapshot)
            recipe = (snapshot / "models/Demo/kiss.windows.yaml").read_text()
            assert "numpy>=2" in recipe and "PE32+" in recipe
            assert notes.read_text() == "Retained Windows instructions."
            # Another app process starts from the old library but must actually
            # switch its catalog when it observes this validated shared cache.
            again, download = case._run_update(archive, activated, revision)
            assert again["state"] == "up_to_date"
            assert activated[-1] == snapshot and len(activated) == 2
            assert download.call_count == 0
    finally:
        case.tearDown()


@pytest.mark.parametrize("damage", ["helper", "marker", "data", "content"])
def test_new_snapshot_damage_cannot_pass_as_legacy(tmp_path, monkeypatch, damage):
    home = tmp_path / "updates"
    monkeypatch.setenv("GEOFORGE_KI_UPDATE_HOME", str(home))
    revision = "a" * 32
    root = helper_snapshot(home / "snapshots" / revision)
    (root / "models/M").mkdir(parents=True)
    (root / "models/M/SKILL.md").write_text("model")
    data = root / "kiss/data_kis"
    data.mkdir(parents=True)
    meta = {"schema_version": 1, "revision": revision, "trees": {
        "models": "a" * 40, "manifests": "b" * 40,
        "shared_tools": "c" * 40, "data_kis": "d" * 40},
        "content_sha256": ki_updates._snapshot_content_hash(root)}
    (root / ki_updates.SNAPSHOT_MANIFEST).write_text(json.dumps(meta))
    (home / "state.json").write_text(json.dumps({"active_snapshot": revision,
                                                 "component_trees": meta["trees"]}))
    assert ki_updates.active_library_root() == root
    if damage == "helper":
        (root / "ki_tools_common/ki_tools_common/__init__.py").unlink()
    elif damage == "marker":
        (root / ki_updates.SNAPSHOT_MANIFEST).unlink()
    elif damage == "data":
        data.rmdir()
    else:
        (root / "models/M/SKILL.md").write_text("locally changed")
    assert ki_updates.active_library_root() is None


def test_compact_snapshot_identity_preserves_windows_path_budget():
    trees = {key: letter * 40 for key, letter in zip(
        ("models", "manifests", "shared_tools", "data_kis"), "abcd")}
    before = "a" * 16 + "-" + "b" * 16
    revision = ki_updates._revision_identity(trees, "e" * 64)
    assert len(revision) == 32 and len(revision) <= len(before)
    assert revision != ki_updates._revision_identity(trees, "f" * 64)
    assert revision == ki_updates._revision_identity(dict(reversed(list(trees.items()))), "e" * 64)


def test_snapshot_identity_includes_validation_policy(monkeypatch):
    trees = {"models": "a" * 40, "manifests": "b" * 40, "shared_tools": "c" * 40}
    monkeypatch.setattr(ki_updates.doctor, "VALIDATION_POLICY_VERSION", "policy-a", raising=False)
    before = ki_updates._revision_identity(trees)
    monkeypatch.setattr(ki_updates.doctor, "VALIDATION_POLICY_VERSION", "policy-b")
    assert ki_updates._revision_identity(trees) != before


def test_reference_binding_warnings_are_visible_beyond_generic_preview(tmp_path, monkeypatch):
    source = helper_snapshot(tmp_path / "source")
    folder = source / "models/M"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text("reference case")
    findings = [ki_updates.doctor.Finding("M", "WARN", "generic", f"warning{i}") for i in range(25)]
    findings += [ki_updates.doctor.Finding("M", "WARN", "reference-case-binding", "bind the executable", 2),
                 ki_updates.doctor.Finding("M", "WARN", "reference-case-provenance", "historical paths", 1)]
    monkeypatch.setattr(ki_updates.doctor, "check_ki", lambda _: findings)
    monkeypatch.setattr(ki_updates.doctor, "check_cross_model", lambda _: [])
    monkeypatch.setattr(ki_updates.reference_portability, "classify_reference_paths", lambda _: {
        "test_cases/case/run_reference.py": [{"classification": "configurable_default"}],
        "test_cases/case/manifest.json": [{"classification": "runtime_binding_metadata"}],
        "test_cases/case/expected.json": [{"classification": "provenance"}]})
    manager = ki_updates.UpdateManager(source, lambda _: None)
    _packages, count, preview = manager._validate(source)
    assert count == 27 and preview[0]["check"] == "reference-case-binding"
    summary = manager._reference_case_summary
    assert summary["native_verification"] == "not_performed"
    assert summary["configurable_path_count"] == summary["historical_path_count"] == summary["runtime_binding_metadata_count"] == 1
    assert summary["affected_kis"] == ["M"] and len(summary["warnings"]) == 2


def test_changed_validation_policy_rechecks_existing_component_revision():
    case = updater_tests.KiUpdateTests()
    case.setUp()
    try:
        case._write_ki(case.base, "Demo", "old")
        archive = case._archive({"Demo": "new"})
        activated = []
        manager = ki_updates.UpdateManager(case.base, activated.append)
        trees = {"models": "a" * 40, "manifests": "b" * 40, "shared_tools": "c" * 40, "data_kis": None}
        manager._component_trees = trees
        revision = ki_updates._revision_identity(trees)
        case.home.mkdir(parents=True)
        (case.home / "state.json").write_text(json.dumps({"revision": revision,
            "validation_policy": "obsolete-policy"}))
        with mock.patch.object(manager, "_remote_revision", return_value=(revision, "a" * 40, "b" * 40)), \
             mock.patch.object(ki_updates, "active_library_root", return_value=case.base), \
             mock.patch.object(manager, "_download", side_effect=lambda target: __import__("shutil").copyfile(archive, target)) as download, \
             mock.patch.object(manager, "_validate", wraps=manager._validate) as validate:
            manager._run()
        assert download.call_count == validate.call_count == 1 and len(activated) == 1
        marker = json.loads((activated[0] / ki_updates.SNAPSHOT_MANIFEST).read_text(encoding="utf-8"))
        assert marker["validation_policy"] == ki_updates._validation_policy()
        assert marker["reference_cases"]["native_verification"] == "not_performed"
    finally:
        case.tearDown()


def test_missing_saved_versioned_helper_requires_repair(tmp_path):
    project = tmp_path / "project"
    shared = paths.KissConfig.default(tmp_path / "install")
    saved = project_paths.model_config(project, "M", shared)
    saved.roles["ki_tools_common"] = tmp_path / "ktc/aaaaaaaaaaaa"
    folder = project / "models/M"
    folder.mkdir(parents=True)
    (folder / paths.CONFIG_NAME).write_text(saved.dumps(), encoding="utf-8")
    request = object.__new__(gui.Handler)
    request._config = lambda _: shared
    with pytest.raises(ValueError, match="restore the recorded revision"):
        request._session_config(project, catalog.KI("M", tmp_path / "model"))


def _snapshot_project(tmp_path):
    project = tmp_path / "project"
    snapshot = helper_snapshot(tmp_path / "new-library", "b")
    source = snapshot / "models/M"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("NEW library guidance")
    (source / "new_tool.py").write_text("NEW tool")
    shared = paths.KissConfig.default(tmp_path / "install")
    shared.roles["ki_tools_common"].mkdir(parents=True)
    saved = project_paths.model_config(project, "M", shared)
    home = project / "models/M"
    live = home / "ki"
    live.mkdir(parents=True)
    (live / "SKILL.md").write_text("OLD project guidance and local fix")
    (live / "tool.py").write_text("OLD project tool")
    (home / paths.CONFIG_NAME).write_text(saved.dumps(), encoding="utf-8")
    request = object.__new__(gui.Handler)
    request.repo_root = tmp_path / "app"
    request.library_root = snapshot
    request._config = lambda _: shared
    return request, project, catalog.KI("M", source), saved, live


def test_snapshot_continuation_preserves_pair_and_reads_retained_guidance(tmp_path, monkeypatch):
    request, project, ki, saved, live = _snapshot_project(tmp_path)
    original = {p.name: p.read_bytes() for p in live.iterdir()}
    config_bytes = (live.parent / paths.CONFIG_NAME).read_bytes()
    monkeypatch.setattr(gui.port, "materialise", lambda *_a: pytest.fail("retained KI was refreshed"))
    monkeypatch.setattr(gui, "_copy_missing_assets", lambda *_a: pytest.fail("new shared code was mixed in"))
    resolved, cfg = request._session_workspace(project, ki)
    assert cfg.roles["ki_tools_common"] == saved.roles["ki_tools_common"]
    assert {p.name: p.read_bytes() for p in live.iterdir()} == original
    assert (live.parent / paths.CONFIG_NAME).read_bytes() == config_bytes
    text = api.execute_tool("read_ki_file", {"path": "SKILL.md"}, resolved, cfg)
    assert "OLD project guidance and local fix" in text and "NEW" not in text
    assert "OLD project tool" in api.execute_tool("read_ki_file", {"path": "tool.py"}, resolved, cfg)
    system = prompt.compose(resolved, cfg, execute=False)
    assert str(live) in system and str(ki.root) not in system


@pytest.mark.parametrize("damage", ["working_ki", "helpers", "bindings"])
def test_snapshot_continuation_requires_complete_unchanged_pair(tmp_path, damage):
    request, project, ki, saved, live = _snapshot_project(tmp_path)
    if damage == "working_ki":
        (live / "SKILL.md").unlink()
    elif damage == "helpers":
        saved.roles["ki_tools_common"].rmdir()
    else:
        request._config = lambda _: paths.KissConfig.default(tmp_path / "different-install")
    with pytest.raises(ValueError, match="(restore the recorded KI/helper pair|repair the retained KI/helper pair)"):
        request._session_workspace(project, ki)
    assert not (live / "new_tool.py").exists()


def test_fresh_snapshot_project_materialises_matching_new_pair(tmp_path):
    request, _existing_project, ki, _saved, _live = _snapshot_project(tmp_path)
    project = tmp_path / "fresh-project"
    resolved, cfg = request._session_workspace(project, ki)
    assert resolved.skill.read_text() == "NEW library guidance"
    assert (resolved.root / "new_tool.py").read_text() == "NEW tool"
    assert "'b'" in (cfg.roles["ki_tools_common"] / "ki_tools_common/__init__.py").read_text()
