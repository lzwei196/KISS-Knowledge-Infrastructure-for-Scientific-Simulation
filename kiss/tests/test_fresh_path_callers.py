"""Fresh GUI projections preserve signed path provenance, never readiness.

The published WOFOST preflight and runner are projected as text. The runtime
identity is a harmless fixture; no interpreter, preflight or model is launched.
"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from kiss_cli import catalog, gui, ki_adaptations as adapt, ki_copy, ki_fresh_paths
from kiss_cli import ki_guard, ki_updates, paths, project_verification
from kiss_cli.manifest import Manifest
from .test_fresh_path_projection import case


@pytest.fixture
def gui_case(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_KI_ADAPTATION_HOME", str(tmp_path / "authority"))
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    source, cfg, target = case(tmp_path)
    library = tmp_path / "bundled-library"
    library.mkdir()
    shared = paths.KissConfig.default(tmp_path / "shared-install")
    legacy = shared.root / "ki"
    legacy.mkdir(parents=True)
    (legacy / "legacy_tool.py").write_bytes(b"# Old installed code must not reappear\n")
    (legacy / "test_cases").mkdir()
    (legacy / "test_cases/removed-case.txt").write_bytes(b"old removed case\n")
    handler = object.__new__(gui.Handler)
    handler.repo_root = handler.library_root = library
    handler._manifest = lambda ki: Manifest(model=ki.name)
    handler._config = lambda ki: shared
    return SimpleNamespace(base=tmp_path, source=source, cfg=cfg, target=target,
                           library=library, legacy=legacy, handler=handler,
                           ki=catalog.KI("WOFOST", source))


@pytest.mark.parametrize("snapshot", [False, True])
def test_gui_fresh_wofost_keeps_signed_projection_without_merging_old_assets(gui_case, monkeypatch, snapshot):
    c = gui_case
    if snapshot:
        (c.library / ki_updates.SNAPSHOT_MANIFEST).write_text(json.dumps({
            "source_commit": "a" * 40, "content_sha256": "b" * 64,
            "trees": {"shared_tools": "c" * 40}}), encoding="utf-8")
    source_before = ki_fresh_paths.tree_files(c.source)
    legacy_before = ki_fresh_paths.tree_files(c.legacy)
    def forbid_old_merge(*args, **kwargs):
        pytest.fail("A complete published WOFOST KI must not merge old shared code")
    monkeypatch.setattr(gui, "_copy_missing_assets", forbid_old_merge)

    working, cfg = c.handler._session_workspace(c.cfg.root, c.ki, cfg=c.cfg,
                                               write_project_config=False)

    assert working.root == c.target
    assert not (working.root / "legacy_tool.py").exists()
    assert not (working.root / "test_cases/removed-case.txt").exists()
    assert ki_fresh_paths.tree_files(c.source) == source_before
    assert ki_fresh_paths.tree_files(c.legacy) == legacy_before
    assert (working.root / "test_cases/data.txt").read_bytes() == (c.source / "test_cases/data.txt").read_bytes()
    # This reads authenticated stored provenance and rechecks the exact current
    # runtime/helper/source/candidate binding, rather than trusting a return value.
    lineage = adapt.projection(working.root, cfg)
    proof = lineage["path_projection"]
    assert Path(proof["logical_target"]) == working.root
    assert Path(proof["physical_root"]) == working.root
    assert Path(proof["source_root"]) == Path(lineage["portable_root"])
    assert proof["policy_sha256"] == ki_fresh_paths.source_digest()
    ki_fresh_paths.require_fresh_current(proof, candidate_root=working.root)
    assert all(proof[key] is False for key in ("runtime_bound", "native_execution",
        "model_execution", "preflight_passed", "scientific_validation"))
    assert lineage["adaptation_id"] is None
    assert ki_guard.is_managed(working.root)
    assert not project_verification.status(c.cfg.root, working)["can_run"]
    saved = paths.KissConfig.load(working.root.parent)
    assert saved.python == cfg.python and saved.roles == cfg.roles


def test_gui_existing_wofost_keeps_saved_pair_after_new_upstream_source(gui_case, monkeypatch):
    c = gui_case
    working, cfg = c.handler._session_workspace(c.cfg.root, c.ki, cfg=c.cfg,
                                               write_project_config=False)
    baseline = ki_guard.require_intact(working.root)
    before = ki_fresh_paths.tree_files(working.root)
    config_path = working.root.parent / paths.CONFIG_NAME
    saved = config_path.read_bytes()
    provenance = adapt._location(working.root).read_bytes()
    next_source = c.base / "new-upstream"
    ki_copy.copytree(c.source, next_source)
    (next_source / "new-upstream-file.txt").write_bytes(b"upstream changed\n")
    ki_guard.enroll(next_source)
    def forbid_projection(*args, **kwargs):
        pytest.fail("An existing project must retain its exact saved KI/helper pair")
    monkeypatch.setattr(adapt, "materialise", forbid_projection)
    monkeypatch.setattr(adapt, "project_runtime", forbid_projection)
    monkeypatch.setattr(gui, "_copy_missing_assets", forbid_projection)

    repeated, repeated_cfg = c.handler._session_workspace(c.cfg.root,
        catalog.KI("WOFOST", next_source), cfg=cfg, write_project_config=False)

    assert repeated.root == working.root
    assert repeated_cfg.python == cfg.python and repeated_cfg.roles == cfg.roles
    assert ki_guard.require_intact(working.root) == baseline
    assert ki_fresh_paths.tree_files(working.root) == before
    assert config_path.read_bytes() == saved
    assert adapt._location(working.root).read_bytes() == provenance
    assert not (working.root / "new-upstream-file.txt").exists()
    assert not project_verification.status(c.cfg.root, repeated)["can_run"]
