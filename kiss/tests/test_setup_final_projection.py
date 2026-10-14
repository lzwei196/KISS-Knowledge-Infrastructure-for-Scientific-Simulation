"""Real harmless preflights must check the final projected runtime paths.

No provider, package installer, scientific engine or network is used. Tests
retain active KI/helper bytes and create replacement projections only in new
fixture-owned workspaces/projects.
"""
from copy import deepcopy
import json
import sys
from types import SimpleNamespace

import pytest

from kiss_cli import (catalog, gui, helper_identity, install, ki_adaptations,
                      ki_guard, paths, project_verification, setup, software_verification)


@pytest.fixture
def case(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_KI_ADAPTATION_HOME", str(tmp_path / "adaptations"))
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    library = tmp_path / "library"
    source = library / "models/Demo"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("# Harmless final runtime fixture\n", encoding="utf-8")
    (source / "kiss.yaml").write_text("kiss_manifest_version: 1\nmodel: Demo\n", encoding="utf-8")
    (source / "preflight_check.py").write_text(
        "from pathlib import Path\n"
        "engine = Path('KISSPATH_BINARIES/ready.txt')\n"
        "print('CHECKED_ENGINE=' + str(engine))\n"
        "assert engine.read_text() == 'ready'\n", encoding="utf-8")
    common = library / "ki_tools_common/ki_tools_common"
    common.mkdir(parents=True)
    (common / "__init__.py").write_text("# harmless helpers\n", encoding="utf-8")
    (common / "binding.py").write_text("ENGINE = 'KISSPATH_BINARIES'\n", encoding="utf-8")
    ki_guard.enroll(source)
    root = tmp_path / "work/demo"
    root.mkdir(parents=True)
    cfg = paths.KissConfig.default(root)
    cfg.python, cfg.relocation = sys.executable, "none"
    cfg.roles["binaries"].mkdir()
    (cfg.roles["binaries"] / "ready.txt").write_text("ready", encoding="utf-8")
    setup.prepare_common(cfg, library)
    config = root / paths.CONFIG_NAME
    config.write_text(cfg.dumps(), encoding="utf-8")
    setup.materialise_active(source, root / "ki", cfg, library_root=library)
    ki, live = catalog.KI("Demo", source), catalog.KI("Demo", root / "ki")
    handler = object.__new__(gui.Handler)
    handler.repo_root = handler.library_root = library
    handler.workroot = root.parent
    handler.catalog = catalog.Catalog(library / "models")
    return SimpleNamespace(base=tmp_path, library=library, ki=ki, live=live, root=root,
                           cfg=cfg, config=config, handler=handler)


def finish(c, cfg=None):
    return c.handler._record_agent_preflight(c.ki, c.live, cfg or c.cfg, c.root, lambda _: None)


def status(c):
    return json.loads((c.root / "status.json").read_text(encoding="utf-8"))


def test_unchanged_final_projection_runs_real_preflight(case):
    c = case
    before = ki_guard.require_intact(c.live.root)
    helpers = helper_identity.package_files(c.cfg.roles["ki_tools_common"])
    assert finish(c)
    check = status(c)["steps"][-1]
    assert check["evidence"]["launch_attempted"]
    assert str(c.cfg.roles["binaries"] / "ready.txt") in check["detail"]
    assert ki_guard.require_intact(c.live.root) == before
    assert helper_identity.package_files(c.cfg.roles["ki_tools_common"]) == helpers


@pytest.mark.parametrize("installed", [False, True])
def test_changed_engine_path_cannot_inherit_old_preflight_and_fresh_project_checks_it(case, monkeypatch, installed):
    c = case
    assert finish(c), "the original embedded path genuinely passed"
    baseline = ki_guard.require_intact(c.live.root)
    helpers = helper_identity.package_files(c.cfg.roles["ki_tools_common"])
    changed = deepcopy(c.cfg)
    changed.roles["binaries"] = c.root / "replacement-engine"
    if installed:
        changed.roles["binaries"].mkdir()
        (changed.roles["binaries"] / "ready.txt").write_text("ready", encoding="utf-8")
    c.config.write_text(changed.dumps(), encoding="utf-8")
    saved = c.config.read_bytes()
    with monkeypatch.context() as patch:
        patch.setattr(install, "run_preflight", lambda *a, **k:
                      pytest.fail("stale embedded paths must be rejected before launching a check"))
        assert not finish(c)
    result = status(c)
    assert result["primary_error"]["name"] == "runtime-projection"
    assert not result["ok"] and result["runtime_identity"] is None
    assert "unused Model installation workspace" in result["primary_error"]["detail"]
    assert not c.handler._status_for(c.ki)["can_run"]
    assert c.config.read_bytes() == saved
    assert ki_guard.require_intact(c.live.root) == baseline
    assert helper_identity.package_files(c.cfg.roles["ki_tools_common"]) == helpers
    assert gui._project_check_allowed_by_shared_status(c.handler._status_for(c.ki), shared_root=c.root)
    project = c.base / "fresh-project"
    working, cfg = c.handler._session_workspace(project, c.ki)
    checked = project_verification.verify(project, working, c.handler._manifest(working))
    assert checked["can_run"] is installed
    assert checked["receipt"]["checks"][0]["evidence"]["launch_attempted"]
    assert str(changed.roles["binaries"] / "ready.txt") in checked["receipt"]["checks"][0]["detail"]
    assert not c.handler._status_for(c.ki)["can_run"], "project verification cannot relabel the old setup"


def test_unused_setup_workspace_can_verify_a_new_correctly_projected_runtime(case):
    c = case
    old = ki_guard.require_intact(c.live.root)
    root = c.base / "replacement-workspace"
    root.mkdir()
    cfg = paths.KissConfig.default(root)
    cfg.python, cfg.relocation = sys.executable, "none"
    cfg.roles["binaries"].mkdir()
    (cfg.roles["binaries"] / "ready.txt").write_text("ready", encoding="utf-8")
    setup.prepare_common(cfg, c.library)
    (root / paths.CONFIG_NAME).write_text(cfg.dumps(), encoding="utf-8")
    setup.materialise_active(c.ki.root, root / "ki", cfg, library_root=c.library)
    live = catalog.KI("Demo", root / "ki")
    assert c.handler._record_agent_preflight(c.ki, live, cfg, root, lambda _: None)
    checked = json.loads((root / "status.json").read_text(encoding="utf-8"))
    assert str(cfg.roles["binaries"] / "ready.txt") in checked["steps"][-1]["detail"]
    assert ki_guard.require_intact(c.live.root) == old


def test_final_check_rejects_a_project_ki_as_the_shared_installation(case, monkeypatch):
    c = case
    working, _cfg = c.handler._session_workspace(c.base / "project", c.ki)
    before = ki_guard.require_intact(working.root)
    monkeypatch.setattr(install, "run_preflight", lambda *a, **k:
                        pytest.fail("project paths must not be checked with shared installation config"))
    assert not c.handler._record_agent_preflight(c.ki, working, c.cfg, c.root, lambda _: None)
    assert status(c)["primary_error"]["name"] == "runtime-projection"
    assert ki_guard.require_intact(working.root) == before
    assert not project_verification.status(c.base / "project", working)["can_run"]


def test_helper_change_during_real_preflight_cannot_publish_readiness(case, monkeypatch):
    c = case
    run = install.run_preflight
    def changing_helpers(*args, **kwargs):
        result = run(*args, **kwargs)
        assert result.ok
        (c.cfg.roles["ki_tools_common"] / "ki_tools_common/binding.py").write_text(
            "ENGINE = 'different-runtime'\n", encoding="utf-8")
        return result
    monkeypatch.setattr(install, "run_preflight", changing_helpers)
    assert not finish(c)
    result = status(c)
    assert result["primary_error"]["name"] == "runtime-projection"
    assert result["steps"][-1]["evidence"]["launch_attempted"]
    assert result["runtime_identity"] is None


def test_legacy_projection_is_compared_without_reenrollment(case):
    c = case
    ki_adaptations._location(c.live.root).unlink()  # isolated pre-provenance fixture
    before = ki_guard.require_intact(c.live.root)
    assert finish(c)
    assert ki_guard.require_intact(c.live.root) == before
    assert not ki_adaptations._location(c.live.root).exists()


def test_changed_legacy_binding_is_not_accepted_without_provenance(case, monkeypatch):
    c = case
    ki_adaptations._location(c.live.root).unlink()
    before = ki_guard.require_intact(c.live.root)
    changed = deepcopy(c.cfg)
    changed.roles["binaries"] = c.root / "missing-new-engine"
    c.config.write_text(changed.dumps(), encoding="utf-8")
    monkeypatch.setattr(install, "run_preflight", lambda *a, **k:
                        pytest.fail("legacy absence cannot authorize old embedded paths"))
    assert not finish(c)
    assert "legacy KI differs" in status(c)["primary_error"]["detail"]
    assert ki_guard.require_intact(c.live.root) == before
    assert not ki_adaptations._location(c.live.root).exists()


def test_restoring_original_binding_can_be_checked_again(case):
    c = case
    assert finish(c)
    before = ki_guard.require_intact(c.live.root)
    changed = deepcopy(c.cfg)
    changed.roles["binaries"] = c.root / "missing-replacement"
    c.config.write_text(changed.dumps(), encoding="utf-8")
    assert not finish(c)
    assert status(c)["primary_error"]["name"] == "runtime-projection"
    c.config.write_text(c.cfg.dumps(), encoding="utf-8")
    assert finish(c)
    assert c.handler._status_for(c.ki)["can_run"]
    assert ki_guard.require_intact(c.live.root) == before


def test_status_rejects_historical_false_pass_without_reprojecting_or_mutating(case, monkeypatch):
    c = case
    assert finish(c)
    changed = deepcopy(c.cfg)
    changed.roles["binaries"] = c.root / "missing-replacement"
    c.config.write_text(changed.dumps(), encoding="utf-8")
    record = status(c)
    record["runtime_identity"] = software_verification.runtime_identity(changed)
    status_path = c.root / "status.json"
    status_path.write_text(json.dumps(record), encoding="utf-8")
    status_before, config_before = status_path.read_bytes(), c.config.read_bytes()
    before = ki_guard.require_intact(c.live.root)
    monkeypatch.setattr(ki_adaptations, "projection", lambda *a, **k:
                        pytest.fail("status must not invoke full adaptation/KDT verification"))
    monkeypatch.setattr(ki_adaptations, "project_runtime", lambda *a, **k:
                        pytest.fail("status must not render a new projection"))
    monkeypatch.setattr(install, "run_preflight", lambda *a, **k:
                        pytest.fail("status must not run preflight"))
    result = c.handler._status_for(c.ki)
    assert not result["can_run"] and result["requires_reverification"]
    assert result["primary_error"]["name"] == "runtime-projection"
    assert status_path.read_bytes() == status_before and c.config.read_bytes() == config_before
    assert ki_guard.require_intact(c.live.root) == before


@pytest.mark.parametrize("marker", [True, False])
def test_new_ki_projection_cannot_certify_helpers_with_old_embedded_paths(case, monkeypatch, marker):
    c = case
    root = c.base / "new-workspace"
    root.mkdir()
    cfg = deepcopy(c.cfg)
    cfg.root = root
    cfg.roles["binaries"] = root / "new-engine"
    # The new KI has authentic current lineage, but its selected helper copy
    # was prepared for the old runtime. Test both v2 and legacy helper copies.
    if not marker:
        (cfg.roles["ki_tools_common"] / helper_identity.MARKER).unlink()
    (root / paths.CONFIG_NAME).write_text(cfg.dumps(), encoding="utf-8")
    setup.materialise_active(c.ki.root, root / "ki", cfg, library_root=c.library)
    live = catalog.KI("Demo", root / "ki")
    assert ki_adaptations.projection(live.root, cfg)
    before = helper_identity.package_files(cfg.roles["ki_tools_common"])
    monkeypatch.setattr(install, "run_preflight", lambda *a, **k:
                        pytest.fail("stale helpers must be rejected before preflight"))
    assert not c.handler._record_agent_preflight(c.ki, live, cfg, root, lambda _: None)
    result = json.loads((root / "status.json").read_text(encoding="utf-8"))
    assert result["primary_error"]["name"] == "runtime-projection"
    assert "shared helpers" in result["primary_error"]["detail"]
    assert helper_identity.package_files(cfg.roles["ki_tools_common"]) == before
