"""Fresh projects own final-bound helpers; active setup/projects never migrate.

Only harmless text projections are used. No interpreter/model is launched and
no software-readiness receipt is created by these workspace tests.
"""
from dataclasses import replace
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from kiss_cli import catalog, gui, helper_identity, ki_guard, ki_updates
from kiss_cli import paths, project_verification, setup
from kiss_cli.manifest import Manifest


@pytest.fixture
def case(tmp_path):
    library = tmp_path / "snapshot"
    package = library / "ki_tools_common/ki_tools_common"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("# harmless source\n", encoding="utf-8")
    (package / "binding.py").write_text(
        "PYTHON = 'KISSPATH_PYTHON_ENV/bin/python'\n"
        "OUTPUTS = 'KISSPATH_OUTPUTS'\n"
        "HELPERS = 'KISSPATH_KI_TOOLS_COMMON'\n", encoding="utf-8")
    (library / ki_updates.SNAPSHOT_MANIFEST).write_text(json.dumps({
        "source_commit": "a" * 40, "content_sha256": "b" * 64,
        "trees": {"shared_tools": "c" * 40}}), encoding="utf-8")
    source = library / "models/Demo"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("# Harmless project projection\n", encoding="utf-8")
    (source / "binding.py").write_text(
        "PYTHON = 'KISSPATH_PYTHON_ENV/bin/python'\n"
        "HELPERS = 'KISSPATH_KI_TOOLS_COMMON'\n", encoding="utf-8")
    ki_guard.enroll(source)
    shared = paths.KissConfig.default(tmp_path / "install")
    shared.root.mkdir()
    shared.python, shared.relocation = sys.executable, "none"
    helpers = setup.prepare_common(shared, library)
    setup.materialise_active(source, shared.root / "ki", shared)
    (shared.root / paths.CONFIG_NAME).write_text(shared.dumps(), encoding="utf-8")
    (shared.root / "status.json").write_text('{"fixture":"existing setup status"}', encoding="utf-8")
    old = {"config": (shared.root / paths.CONFIG_NAME).read_bytes(),
           "status": (shared.root / "status.json").read_bytes(),
           "helper_files": helper_identity.package_files(helpers),
           "marker": (helpers / helper_identity.MARKER).read_bytes(),
           "baseline": ki_guard.require_intact(shared.root / "ki")}
    updated_python = shared.root / "python312/python.exe"
    updated_python.parent.mkdir()
    updated_python.write_bytes(b"fixture only; never launched")
    updated = replace(shared, python=str(updated_python),
                      roles={**shared.roles, "python_env": updated_python.parent})
    (shared.root / paths.CONFIG_NAME).write_text(updated.dumps(), encoding="utf-8")
    final_config = (shared.root / paths.CONFIG_NAME).read_bytes()
    handler = object.__new__(gui.Handler)
    handler.repo_root = handler.library_root = library
    handler._config = lambda _ki: updated
    handler._manifest = lambda ki: Manifest.stub_for(ki)
    ki = catalog.KI("Demo", source)
    return SimpleNamespace(base=tmp_path, handler=handler, library=library, ki=ki,
                           shared=shared, updated=updated, old=old,
                           final_config=final_config, helpers=helpers)


def assert_setup_untouched(c):
    assert (c.shared.root / paths.CONFIG_NAME).read_bytes() == c.final_config
    assert (c.shared.root / "status.json").read_bytes() == c.old["status"]
    assert helper_identity.package_files(c.helpers) == c.old["helper_files"]
    assert (c.helpers / helper_identity.MARKER).read_bytes() == c.old["marker"]
    assert ki_guard.require_intact(c.shared.root / "ki") == c.old["baseline"]
    assert c.updated.roles["ki_tools_common"] == c.helpers


def test_final_setup_runtime_gets_fresh_project_helper_ki_pair(case):
    c = case
    # The old active setup copy really is incompatible with the saved runtime.
    with pytest.raises(ValueError, match="shared-helper/runtime binding"):
        setup.prepare_common(c.updated, c.library)
    project = c.base / "first-project"
    working, cfg = c.handler._session_workspace(project, c.ki)
    assert cfg.root == project
    common = cfg.roles["ki_tools_common"]
    assert common.is_relative_to(project / "models/Demo/ktc")
    assert cfg.python == c.updated.python
    assert cfg.roles["python_env"] == c.updated.roles["python_env"]
    assert cfg.roles["binaries"] == c.updated.roles["binaries"]
    for tree in (working.root, common / "ki_tools_common"):
        text = (tree / "binding.py").read_text(encoding="utf-8")
        assert c.updated.python.replace("\\", "/") in text
        assert common.as_posix() in text
    assert cfg.roles["outputs"].as_posix() in (common / "ki_tools_common/binding.py").read_text()
    assert helper_identity.prepared_source_identity(common) == helper_identity.source_identity(c.library)
    baseline = ki_guard.require_intact(working.root)
    config = (working.root.parent / paths.CONFIG_NAME).read_bytes()
    marker = (common / helper_identity.MARKER).read_bytes()
    repeated, cfg2 = c.handler._session_workspace(project, c.ki)
    assert repeated.root == working.root and cfg2.roles == cfg.roles
    assert ki_guard.require_intact(working.root) == baseline
    assert (working.root.parent / paths.CONFIG_NAME).read_bytes() == config
    assert (common / helper_identity.MARKER).read_bytes() == marker
    assert not project_verification.status(project, working)["can_run"]
    assert_setup_untouched(c)


def test_upstream_helper_change_keeps_existing_project_and_setup(case):
    c = case
    project = c.base / "old-project"
    working, cfg = c.handler._session_workspace(project, c.ki)
    common = cfg.roles["ki_tools_common"]
    original = helper_identity.package_files(common)
    (c.library / "ki_tools_common/ki_tools_common/__init__.py").write_text("VERSION = 2\n")
    retained, cfg2 = c.handler._session_workspace(project, c.ki)
    assert retained.root == working.root and cfg2.roles["ki_tools_common"] == common
    assert helper_identity.package_files(common) == original
    new_project = c.base / "new-project"
    _, new_cfg = c.handler._session_workspace(new_project, c.ki)
    new_common = new_cfg.roles["ki_tools_common"]
    assert new_common != common and new_common.is_relative_to(new_project / "models/Demo")
    assert (new_common / "ki_tools_common/__init__.py").read_text() == "VERSION = 2\n"
    assert helper_identity.package_files(common) == original
    assert_setup_untouched(c)


@pytest.mark.parametrize("damage", ["missing", "missing_marker", "tampered"])
def test_retained_project_helper_damage_is_never_recreated(case, damage):
    c = case
    project = c.base / "project"
    working, cfg = c.handler._session_workspace(project, c.ki)
    common = cfg.roles["ki_tools_common"]
    marker = common / helper_identity.MARKER
    if damage == "missing":
        common.rename(common.with_name(common.name + "-retained"))
    elif damage == "missing_marker":
        marker.unlink()
    else:
        (common / "ki_tools_common/__init__.py").write_text("EDITED = True\n")
    original_config = (working.root.parent / paths.CONFIG_NAME).read_bytes()
    baseline = ki_guard.require_intact(working.root)
    with pytest.raises(ValueError, match="missing|changed locally"):
        c.handler._session_workspace(project, c.ki)
    assert (working.root.parent / paths.CONFIG_NAME).read_bytes() == original_config
    assert ki_guard.require_intact(working.root) == baseline
    assert_setup_untouched(c)


def test_existing_project_runtime_change_is_not_silent_helper_migration(case):
    c = case
    project = c.base / "project"
    working, cfg = c.handler._session_workspace(project, c.ki)
    common = cfg.roles["ki_tools_common"]
    original = helper_identity.package_files(common)
    c.handler._config = lambda _ki: replace(c.updated, python="another-runtime", roles=dict(c.updated.roles))
    with pytest.raises(ValueError, match="path bindings changed"):
        c.handler._session_workspace(project, c.ki)
    assert helper_identity.package_files(common) == original
    assert_setup_untouched(c)


def test_fresh_project_helper_homes_are_separate_per_ki(case):
    c = case
    project = c.base / "multi-project"
    _, first = c.handler._session_workspace(project, c.ki)
    other = catalog.KI("Other", c.ki.root)
    second = c.handler._session_config(project, other)
    assert first.roles["ki_tools_common"].is_relative_to(project / "models/Demo")
    assert second.roles["ki_tools_common"].is_relative_to(project / "models/Other")
    assert first.roles["ki_tools_common"] != second.roles["ki_tools_common"]
    assert_setup_untouched(c)


def test_bundled_helpers_also_use_fresh_project_binding(case):
    c = case
    (c.library / ki_updates.SNAPSHOT_MANIFEST).unlink()
    project = c.base / "bundled-project"
    cfg = c.handler._session_config(project, c.ki)
    common = cfg.roles["ki_tools_common"]
    assert common == project / "models/Demo/ki_tools_common"
    text = (common / "ki_tools_common/binding.py").read_text(encoding="utf-8")
    assert c.updated.python.replace("\\", "/") in text
    assert cfg.roles["outputs"].as_posix() in text
    assert common.as_posix() in text
    assert_setup_untouched(c)


def test_redirected_model_home_is_rejected_before_helper_writes(case):
    c = case
    project = c.base / "redirected-project"
    outside = c.base / "unrelated-user-folder"
    outside.mkdir()
    (outside / "keep.txt").write_text("unchanged")
    (project / "models").mkdir(parents=True)
    (project / "models/Demo").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="aliased"):
        c.handler._session_config(project, c.ki)
    assert sorted(p.name for p in outside.iterdir()) == ["keep.txt"]
    assert_setup_untouched(c)


@pytest.mark.parametrize("destination", ["ktc", "ki_tools_common"])
def test_redirected_fresh_helper_destination_is_rejected_before_writes(case, destination):
    c = case
    if destination == "ki_tools_common":
        (c.library / ki_updates.SNAPSHOT_MANIFEST).unlink()
    project = c.base / "redirected-helper-project"
    outside = c.base / "unrelated-helper-folder"
    outside.mkdir()
    (outside / "keep.txt").write_text("unchanged")
    home = project / "models/Demo"
    home.mkdir(parents=True)
    (home / destination).symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="helper destination is aliased"):
        c.handler._session_config(project, c.ki)
    assert sorted(p.name for p in outside.iterdir()) == ["keep.txt"]
    assert not (home / "ki").exists()
    assert_setup_untouched(c)
