"""SHAW uses the same setup review/adoption lifecycle as EPANET.

These tests isolate host orchestration with an explicit recipe gate fixture;
the separate SHAW recipe tests cover its real exact-diff and runtime checks.
"""
from pathlib import Path
import shutil

import pytest

from kiss_cli import (ki_adaptations, ki_guard, ki_investigation as inv,
    paths, setup, setup_ki_repair as repair)
from kiss_cli.manifest import Manifest
from .test_setup_ki_repair import case as epanet_setup, fixture_gate, reviewer as epanet_reviewer


@pytest.fixture
def case(epanet_setup):
    old_root, _, library, old_cfg, _ = epanet_setup
    source = library / "models/SHAW"
    source.mkdir()
    (source / "SKILL.md").write_text("# SHAW setup fixture\n")
    (source / "preflight_check.py").write_text("print('original fixture')\n")
    root = old_root.parent / "shaw-setup"
    root.mkdir()
    cfg = paths.KissConfig.default(root)
    cfg.python, cfg.relocation = old_cfg.python, "none"
    setup.prepare_common(cfg, library)
    (root / "kiss.toml").write_text(cfg.dumps(), encoding="utf-8")
    manifest = Manifest(model="SHAW")
    ki_adaptations.materialise(source, root / "ki", cfg, model="SHAW", library_root=library, manifest=manifest)
    (root / "outputs").mkdir()
    (root / "outputs/reference.out").write_bytes(b"retained native result\n")
    return root, source, library, cfg, manifest


def args(case):
    _, source, library, _, manifest = case
    return dict(ki_name="SHAW", source_root=source, library_root=library,
                manifest=manifest, issue="Repair exact Windows SHAW runtime paths")


def read_args(case):
    return {key: value for key, value in args(case).items() if key in {"source_root", "library_root", "manifest"}}


def reviewer(role, context, digest, stop, emit):
    result = epanet_reviewer(role, context, digest, stop, emit)
    result["findings"][0]["evidence"] = ["kis/SHAW/preflight_check.py"]
    return result


def install_gate(monkeypatch, tmp_path):
    from kiss_cli import ki_maintenance_registry as registry
    fixture_gate(monkeypatch, tmp_path, model_name="SHAW", recipe_name="shaw_runtime_paths", dispatcher=registry)


def draft(case, monkeypatch, tmp_path):
    install_gate(monkeypatch, tmp_path)
    root = case[0]
    binding = repair.capture(root, **args(case))
    job = inv.create(root, {}, {"SHAW": root / "ki"}, "api:deepseek", setup_binding=binding)
    assert inv.run_reviews(root, job["id"], reviewer)["status"] == "reviewed"
    return inv.create_draft(root, job["id"], "SHAW", repair_mode="maintenance", maintenance_recipe="shaw_runtime_paths")


def test_shaw_setup_uses_same_review_verify_adopt_and_reopen(case, monkeypatch, tmp_path):
    install_gate(monkeypatch, tmp_path)
    root = case[0]
    original_projection = ki_adaptations._read(ki_adaptations._location(root / "ki"))
    result = repair.run(root, **args(case), provider="api:deepseek", recipe="shaw_runtime_paths", reviewer=reviewer)
    assert result["status"] == "applied"
    assert len(result["reviewers"]) == 3
    assert result["draft"]["maintenance_recipe"] == "shaw_runtime_paths"
    assert result["verification"]["runtime_identity"] == result["draft"]["maintenance_runtime_identity"]
    assert result["verification"]["native_regression"]["verified"] is False
    assert result["apply"]["pending_preflight"] is True
    assert (root / "outputs/reference.out").read_bytes() == b"retained native result\n"
    assert ki_adaptations._read(ki_adaptations._location(root / "ki")) == original_projection
    saved = repair.require_adoption(root, **read_args(case), cfg=case[3])
    assert saved["adopted_digest"] == ki_guard.require_intact(root / "ki")["digest"]
    assert setup.materialise_active(case[1], root / "ki", case[3], manifest=case[4], library_root=case[2]).dest == root / "ki"


@pytest.mark.parametrize("stage", ["before_verify", "before_apply", "after_apply"])
def test_shaw_saved_runtime_drift_denies_each_boundary(case, monkeypatch, tmp_path, stage):
    root = case[0]
    job = draft(case, monkeypatch, tmp_path)
    if stage != "before_verify":
        job = inv.verify_draft(root, job["id"])
    if stage == "after_apply":
        repair.apply(root, job["id"], job["verification"]["id"])
    cfg = setup.load_runtime_config(root)
    cfg.roles["binaries"] = root / "different-binaries"
    (root / "kiss.toml").write_text(cfg.dumps(), encoding="utf-8")
    with pytest.raises((ValueError, RuntimeError)):
        if stage == "before_verify":
            inv.verify_draft(root, job["id"])
        elif stage == "before_apply":
            repair.apply(root, job["id"], job["verification"]["id"])
        else:
            repair.require_adoption(root, **read_args(case))
    if stage != "after_apply":
        assert not repair._pointer(root).exists()


def test_shaw_runtime_report_identity_is_mandatory(case, monkeypatch, tmp_path):
    root = case[0]
    job = draft(case, monkeypatch, tmp_path)
    inv.verify_draft(root, job["id"])
    doc = inv._load(root, job["id"])
    doc["verification"]["runtime_identity"] = "different-runtime"
    inv._save(root, doc)
    with pytest.raises(ValueError, match="Runtime bindings changed"):
        inv._require_verified_candidates(doc)
    assert not repair._pointer(root).exists()


def test_shaw_still_requires_setup_ownership_and_all_reviews(case, monkeypatch, tmp_path):
    install_gate(monkeypatch, tmp_path)
    root = case[0]
    binding = repair.capture(root, **args(case))
    with pytest.raises(ValueError, match="exact target"):
        inv.create(root, {}, {"EPANET": root / "ki"}, "api:deepseek", setup_binding=binding)
    job = inv.create(root, {}, {"SHAW": root / "ki"}, "api:deepseek", setup_binding=binding)
    with pytest.raises(ValueError, match="three reviews"):
        inv.create_draft(root, job["id"], "SHAW", repair_mode="maintenance", maintenance_recipe="shaw_runtime_paths")
    assert not repair._pointer(root).exists()


def test_new_same_byte_source_cannot_borrow_old_shaw_maintenance(case, monkeypatch, tmp_path):
    from kiss_cli import ki_maintenance_registry
    install_gate(monkeypatch, tmp_path)
    root, source, library, cfg, manifest = case
    applied = repair.run(root, **args(case), provider="api:deepseek", recipe="shaw_runtime_paths", reviewer=reviewer)
    assert applied["status"] == "applied"
    old_record = repair.require_adoption(root, **read_args(case))
    new_library = tmp_path / "new-selected-library"
    shutil.copytree(library, new_library)
    new_source = new_library / "models/SHAW"
    assert (new_source / "preflight_check.py").read_bytes() == (source / "preflight_check.py").read_bytes()
    with pytest.raises(ValueError, match="Selected source"):
        repair.require_adoption(root, source_root=new_source, library_root=new_library, manifest=manifest)
    with pytest.raises(ValueError, match="Selected source"):
        setup.materialise_active(new_source, root / "ki", cfg, manifest=manifest, library_root=new_library)
    assert repair.require_adoption(root, **read_args(case)) == old_record

    # A new selection starts with its own authentic working copy, not an old
    # setup's approval/status. The common repair remains available if it fails.
    fresh = tmp_path / "fresh-selected-setup"
    fresh.mkdir()
    fresh_cfg = paths.KissConfig.default(fresh)
    fresh_cfg.python, fresh_cfg.relocation = cfg.python, "none"
    setup.prepare_common(fresh_cfg, new_library)
    (fresh / "kiss.toml").write_text(fresh_cfg.dumps(), encoding="utf-8")
    setup.materialise_active(new_source, fresh / "ki", fresh_cfg,
                             manifest=manifest, library_root=new_library)
    assert repair.require_adoption(fresh, source_root=new_source, library_root=new_library, manifest=manifest) is None
    assert not (fresh / "status.json").exists()
    assert ki_maintenance_registry.setup_recipe("SHAW") == "shaw_runtime_paths"
    assert repair.require_adoption(root, **read_args(case)) == old_record
