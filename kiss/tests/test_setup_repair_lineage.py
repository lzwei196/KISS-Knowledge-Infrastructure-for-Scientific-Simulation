"""Setup-repair consumers, not maintenance authorization or native acceptance.

The adapter authority is deliberately mocked here; its own lifecycle tests
exercise real signatures. These tests keep real source copies, guard baselines
and portable projection records to ensure consumption cannot rewrite them or
fall back after an explicit stale-authority failure. No model is executed.
"""
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from kiss_cli import ki_adaptations as adapt, ki_guard, paths, setup
from kiss_cli.manifest import Manifest, document
from .test_setup_projection_binding import case as runtime_case


@pytest.fixture
def case(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_KI_ADAPTATION_HOME", str(tmp_path / "adaptations"))
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    source = tmp_path / "library" / "models" / "Demo"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("# Setup lineage consumer fixture\n")
    (source / "preflight_check.py").write_text("raise RuntimeError('must never execute')\n")
    (source / "reader.py").write_text("path = 'KISSPATH_OUTPUTS/result.txt'\n")
    ki_guard.enroll(source)
    cfg = paths.KissConfig.default(tmp_path / "installation")
    cfg.python, cfg.relocation = sys.executable, "none"
    man = Manifest(model="Demo")
    live = cfg.root / "ki"
    adapt.materialise(source, live, cfg, model="Demo", library_root=source.parent.parent, manifest=man)
    return SimpleNamespace(source=source, library=source.parent.parent, live=live,
                           cfg=cfg, man=man, projection=adapt._location(live))


def authority(monkeypatch, fn):
    from kiss_cli import setup_ki_repair
    monkeypatch.setattr(setup_ki_repair, "require_adoption", fn)


def read(case, **overrides):
    arguments = dict(source=case.source, model="Demo", library_root=case.library, manifest=case.man)
    arguments.update(overrides)
    return adapt.setup_repair(case.live, case.cfg, **arguments)


def test_reader_delegates_exact_selected_bindings_and_preserves_distinct_record(case, monkeypatch):
    record = {"job_id": "fixture", "adopted_digest": "fixture", "pending_preflight": True}
    def check(root, *, source_root, library_root, manifest, cfg):
        assert root == case.cfg.root
        assert source_root == case.source
        assert library_root == case.library
        assert manifest == document(case.man)
        assert cfg is case.cfg
        return record
    authority(monkeypatch, check)
    before = case.projection.read_bytes()
    assert read(case) is record
    assert "kind" not in record, "a repair must not be presented as an upstream projection"
    assert case.projection.read_bytes() == before


def test_reader_absence_is_not_adoption(case, monkeypatch):
    authority(monkeypatch, lambda *a, **k: None)
    assert read(case) is None


@pytest.mark.parametrize("target", ["project", "foreign", "relative"])
def test_reader_rejects_non_installation_target_before_authority(case, monkeypatch, target):
    authority(monkeypatch, lambda *a, **k: pytest.fail("invalid target reached authority"))
    live = {"project": case.cfg.root / "models" / "Demo" / "ki",
            "foreign": case.cfg.root.parent / "other" / "ki", "relative": Path("ki")}[target]
    with pytest.raises(adapt.AdaptationError, match="exact unaliased KI"):
        adapt.setup_repair(live, case.cfg, source=case.source, model="Demo",
                           library_root=case.library, manifest=case.man)


def test_reader_rejects_wrong_effective_model_before_authority(case, monkeypatch):
    authority(monkeypatch, lambda *a, **k: pytest.fail("wrong recipe reached authority"))
    with pytest.raises(adapt.AdaptationError, match="another model"):
        read(case, manifest=Manifest(model="Other"))


def test_reader_rejects_path_contract_disagreement_before_authority(case, monkeypatch):
    # This is a separate candidate source, so no baseline is modified.
    source = case.source.parent / "declared"
    source.mkdir()
    (source / "kiss.yaml").write_text(
        "kiss_manifest_version: 1\nmodel: Demo\nruntime_paths:\n  version: 1\n  mode: role_tokens\n")
    authority(monkeypatch, lambda *a, **k: pytest.fail("contract mismatch reached authority"))
    with pytest.raises(adapt.AdaptationError, match="declaration differs"):
        read(case, source=source)


def test_current_adoption_is_retained_without_projection_or_readiness(case, monkeypatch):
    authority(monkeypatch, lambda *a, **k: {"pending_preflight": True})
    before = case.projection.read_bytes()
    baseline = ki_guard.require_intact(case.live)
    monkeypatch.setattr(adapt, "materialise", lambda *a, **k: pytest.fail("must not reproject adopted KI"))
    result = setup.materialise_active(case.source, case.live, case.cfg,
                                     manifest=case.man, library_root=case.library)
    assert result.dest == case.live and not result.unresolved and not result.corrupted
    assert case.projection.read_bytes() == before
    assert ki_guard.require_intact(case.live) == baseline
    assert not (case.cfg.root / "status.json").exists()
    assert not list(case.live.parent.glob("ki-draft-*"))


@pytest.mark.parametrize("reason", ["source changed", "helpers changed", "config changed",
                                     "candidate changed", "policy changed", "invalid signature"])
def test_invalid_saved_authority_never_falls_back_or_reprojects(case, monkeypatch, reason):
    def rejected(*args, **kwargs):
        raise ValueError(reason)
    authority(monkeypatch, rejected)
    before = case.projection.read_bytes()
    monkeypatch.setattr(adapt, "materialise", lambda *a, **k: pytest.fail("stale repair fell back"))
    with pytest.raises(ValueError, match=reason):
        setup.materialise_active(case.source, case.live, case.cfg,
                                 manifest=case.man, library_root=case.library)
    assert case.projection.read_bytes() == before
    assert not (case.cfg.root / "status.json").exists()


def test_absent_repair_keeps_normal_exact_projection_check(case, monkeypatch):
    authority(monkeypatch, lambda *a, **k: None)
    before = case.projection.read_bytes()
    result = setup.materialise_active(case.source, case.live, case.cfg,
                                     manifest=case.man, library_root=case.library)
    assert not result.corrupted and not result.unresolved
    assert case.projection.read_bytes() == before


def test_absent_repair_cannot_preserve_different_upstream_as_current(case, tmp_path, monkeypatch):
    authority(monkeypatch, lambda *a, **k: None)
    source = tmp_path / "updated" / "Demo"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("# Different selected upstream\n")
    ki_guard.enroll(source)
    before = case.projection.read_bytes()
    with pytest.raises(ki_guard.KIIntegrityError, match="different working copy"):
        setup.materialise_active(source, case.live, case.cfg,
                                 manifest=case.man, library_root=case.library)
    assert case.projection.read_bytes() == before
    ki_guard.require_intact(case.live)


def test_active_byte_drift_is_rejected_even_before_repair_lookup(case, monkeypatch):
    authority(monkeypatch, lambda *a, **k: pytest.fail("drift reached repair authority"))
    (case.live / "reader.py").write_text("unapproved = True\n")
    with pytest.raises(ki_guard.KIIntegrityError, match="changed"):
        setup.materialise_active(case.source, case.live, case.cfg,
                                 manifest=case.man, library_root=case.library)


def test_unchanged_config_preserves_exact_commented_bytes(case):
    config = case.cfg.root / paths.CONFIG_NAME
    raw = ("# A user comment is part of signed maintenance evidence.\n\n" + case.cfg.dumps()).encode()
    config.write_bytes(raw)
    assert setup.save_runtime_config(case.cfg) is False
    assert config.read_bytes() == raw


@pytest.mark.parametrize("change", ["python", "role", "role_spelling", "relocation"])
def test_changed_runtime_is_written_and_old_byte_identity_becomes_stale(case, change):
    config = case.cfg.root / paths.CONFIG_NAME
    raw = ("# Previous reviewed configuration\n" + case.cfg.dumps()).encode()
    config.write_bytes(raw)
    if change == "python":
        case.cfg.python = str(case.cfg.root / "another-python.exe")
    elif change == "role":
        case.cfg.roles["outputs"] = case.cfg.root / "other-outputs"
    elif change == "role_spelling":
        case.cfg.roles["outputs"] = case.cfg.root / "OUTPUTS"
    else:
        case.cfg.relocation = "port"
    assert setup.save_runtime_config(case.cfg) is True
    assert config.read_bytes() != raw
    assert setup.load_runtime_config(case.cfg.root) == case.cfg


def test_invalid_existing_config_is_preserved_not_repaired_during_save(case):
    config = case.cfg.root / paths.CONFIG_NAME
    raw = b"invalid = ["
    config.write_bytes(raw)
    with pytest.raises(ValueError):
        setup.save_runtime_config(case.cfg)
    assert config.read_bytes() == raw


@pytest.mark.parametrize("route", ["prepare", "builtin"])
def test_normal_setup_retry_preserves_commented_config_before_repair_lookup(runtime_case, monkeypatch, route):
    from kiss_cli import gui
    c = runtime_case
    setup.prepare(c.ki, c.man, c.root, c.library, c.library / "models")
    config = c.root / paths.CONFIG_NAME
    raw = b"# Kept from the reviewed maintenance configuration\n\n" + config.read_bytes()
    config.write_bytes(raw)
    calls = []
    def check(root, **kwargs):
        assert root == c.root
        assert config.read_bytes() == raw, "ordinary setup invalidated its exact evidence by reformatting"
        calls.append(kwargs)
        return {"pending_preflight": True}
    authority(monkeypatch, check)
    if route == "prepare":
        setup.prepare(c.ki, c.man, c.root, c.library, c.library / "models")
    else:
        gui.run_install(c.ki, c.man, c.root, lambda _: None, c.library)
    assert calls
    assert config.read_bytes() == raw
