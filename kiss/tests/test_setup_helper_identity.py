"""Helper content/runtime identity survives unrelated upstream commits."""
import hashlib
import json
from pathlib import Path
import sys

import pytest

from kiss_cli import helper_identity, ki_guard, ki_updates, paths, port, setup


def snapshot(root, commit="a", text="VALUE = 1\n"):
    package = root / "ki_tools_common"
    package.mkdir(parents=True)
    (package / "helper.py").write_text(text, encoding="utf-8")
    (root / ki_updates.SNAPSHOT_MANIFEST).write_text(json.dumps({
        "source_commit": commit * 40, "trees": {"shared_tools": "f" * 40}}))
    return root


def config(root):
    root.mkdir()
    cfg = paths.KissConfig.default(root)
    cfg.python = sys.executable
    return cfg


def activate(cfg):
    live = cfg.root / "ki"
    live.mkdir()
    (live / "SKILL.md").write_text("# Fixture\n", encoding="utf-8")
    (live / "helper-location.txt").write_text(str(cfg.roles["ki_tools_common"]))
    ki_guard.enroll(live)
    (cfg.root / paths.CONFIG_NAME).write_text(cfg.dumps(), encoding="utf-8")
    return ki_guard.require_intact(live)


def legacy_copy(cfg, source):
    marker = json.loads((source / ki_updates.SNAPSHOT_MANIFEST).read_text())
    binding = {"source_commit": marker["source_commit"], "source_tree": marker["trees"]["shared_tools"],
               "roles": {key: str(value) for key, value in sorted(cfg.roles.items()) if key != "ki_tools_common"}}
    identity = hashlib.sha256(json.dumps(binding, sort_keys=True).encode()).hexdigest()
    target = cfg.root / "ktc" / identity[:12]
    cfg.roles["ki_tools_common"] = target
    port.materialise(source / "ki_tools_common", target, cfg)
    (target / ".geoforge-common.json").write_text(json.dumps({
        **binding, "binding_sha256": identity, "files": ki_updates._file_digests(target)}))
    return target


def test_unrelated_commit_keeps_helper_path_and_active_ki_bytes(tmp_path):
    before = snapshot(tmp_path / "before")
    after = snapshot(tmp_path / "after", "b")
    cfg = config(tmp_path / "work")
    target = setup.prepare_common(cfg, before)
    baseline = activate(cfg)
    original_marker = (target / ".geoforge-common.json").read_bytes()
    assert setup.prepare_common(cfg, after) == target
    assert cfg.roles["ki_tools_common"] == target
    assert ki_guard.require_intact(cfg.root / "ki") == baseline
    # Reuse retains the original materialization provenance, not a false rewrite.
    assert (target / ".geoforge-common.json").read_bytes() == original_marker


def test_same_manifest_but_changed_helper_bytes_gets_new_immutable_identity(tmp_path):
    before = snapshot(tmp_path / "before")
    after = snapshot(tmp_path / "after", text="VALUE = 2\n")
    cfg = config(tmp_path / "work")
    first = setup.prepare_common(cfg, before)
    original = (first / "helper.py").read_bytes()
    second = setup.prepare_common(cfg, after)
    assert second != first
    assert (first / "helper.py").read_bytes() == original
    assert (second / "helper.py").read_text() == "VALUE = 2\n"


@pytest.mark.parametrize("field", ["python", "relocation", "policy", "platform"])
def test_runtime_or_policy_change_is_not_an_identical_helper_binding(tmp_path, monkeypatch, field):
    source = snapshot(tmp_path / "source")
    cfg = config(tmp_path / "work")
    first = setup.prepare_common(cfg, source)
    if field == "policy":
        monkeypatch.setattr(setup, "COMMON_MATERIALISATION_POLICY", "test-next-policy", raising=False)
    elif field == "platform":
        monkeypatch.setattr(setup.sys, "platform", "test-other-platform")
    else:
        setattr(cfg, field, "different-runtime-value")
    assert setup.prepare_common(cfg, source) != first
    assert first.is_dir()


def test_legacy_active_binding_is_reused_only_after_exact_projection(tmp_path):
    source = snapshot(tmp_path / "source", text="ROOT = 'KISSPATH_KI_TOOLS_COMMON'\n")
    updated = snapshot(tmp_path / "updated", "b", "ROOT = 'KISSPATH_KI_TOOLS_COMMON'\n")
    cfg = config(tmp_path / "work")
    target = legacy_copy(cfg, source)
    baseline = activate(cfg)
    marker = (target / ".geoforge-common.json").read_bytes()
    assert setup.prepare_common(cfg, updated) == target
    assert ki_guard.require_intact(cfg.root / "ki") == baseline
    assert (target / ".geoforge-common.json").read_bytes() == marker


@pytest.mark.parametrize("legacy", [False, True])
def test_active_helpers_that_changed_upstream_preserve_saved_binding(tmp_path, legacy):
    source = snapshot(tmp_path / "source")
    updated = snapshot(tmp_path / "updated", "b", "VALUE = 2\n")
    cfg = config(tmp_path / "work")
    target = legacy_copy(cfg, source) if legacy else setup.prepare_common(cfg, source)
    baseline = activate(cfg)
    saved = (cfg.root / paths.CONFIG_NAME).read_bytes()
    with pytest.raises(ValueError, match="Active KI|active KI"):
        setup.prepare_common(cfg, updated)
    assert cfg.roles["ki_tools_common"] == target
    assert (cfg.root / paths.CONFIG_NAME).read_bytes() == saved
    assert ki_guard.require_intact(cfg.root / "ki") == baseline
    assert (target / "helper.py").read_text() == "VALUE = 1\n"


@pytest.mark.parametrize("damage", ["bytes", "marker", "missing"])
def test_bound_cache_tampering_is_not_bypassed_by_an_upstream_commit(tmp_path, damage):
    source = snapshot(tmp_path / "source")
    updated = snapshot(tmp_path / "updated", "b")
    cfg = config(tmp_path / "work")
    target = setup.prepare_common(cfg, source)
    if damage == "bytes":
        (target / "helper.py").write_text("LOCAL = True\n")
    elif damage == "marker":
        (target / ".geoforge-common.json").write_text("{}")
    else:
        (target / "helper.py").unlink()
    with pytest.raises(ValueError, match="changed locally|missing"):
        setup.prepare_common(cfg, updated)
    assert cfg.roles["ki_tools_common"] == target


def test_generated_metadata_does_not_change_identity(tmp_path):
    source = snapshot(tmp_path / "source")
    cfg = config(tmp_path / "work")
    first = setup.prepare_common(cfg, source)
    cache = source / "ki_tools_common/__pycache__"
    cache.mkdir()
    (cache / "x.pyc").write_bytes(b"generated")
    egg = source / "ki_tools_common/pkg.egg-info"
    egg.mkdir()
    (egg / "PKG-INFO").write_text("generated")
    assert setup.prepare_common(cfg, source) == first


@pytest.mark.parametrize("legacy", [False, True])
def test_active_binding_changes_fail_before_repointing_even_when_no_tokens(tmp_path, legacy):
    source = snapshot(tmp_path / "source")
    cfg = config(tmp_path / "work")
    target = legacy_copy(cfg, source) if legacy else setup.prepare_common(cfg, source)
    activate(cfg)
    cfg.python = "changed-interpreter"
    with pytest.raises(ValueError, match="saved runtime binding"):
        setup.prepare_common(cfg, source)
    assert cfg.roles["ki_tools_common"] == target


def test_self_reference_reuses_an_existing_target_without_mutating_on_failure(tmp_path):
    source = snapshot(tmp_path / "source", text="ROOT = 'KISSPATH_KI_TOOLS_COMMON'\n")
    cfg = config(tmp_path / "work")
    target = setup.prepare_common(cfg, source)
    cfg.roles["ki_tools_common"] = cfg.root / "ki_tools_common"
    assert setup.prepare_common(cfg, source) == target
    (target / "helper.py").write_text("LOCAL = True\n")
    cfg.roles["ki_tools_common"] = cfg.root / "ki_tools_common"
    before = cfg.roles.copy()
    with pytest.raises(ValueError, match="changed locally"):
        setup.prepare_common(cfg, source)
    assert cfg.roles == before


def test_source_identity_uses_portable_bytes_not_commit_or_generated_files(tmp_path):
    first = snapshot(tmp_path / "first")
    second = snapshot(tmp_path / "second", "b")
    expected = helper_identity.source_identity(first)
    assert helper_identity.source_identity(second) == expected
    (second / "ki_tools_common/extra.pyc").write_bytes(b"cache")
    assert helper_identity.source_identity(second) == expected
    (second / "ki_tools_common/helper.py").write_text("VALUE = 2\n")
    assert helper_identity.source_identity(second) != expected


@pytest.mark.parametrize("kind", ["missing", "empty", "escaping_alias", "root_alias"])
def test_source_identity_rejects_missing_or_escaping_trees(tmp_path, kind):
    source = tmp_path / "source"
    if kind == "empty":
        (source / "ki_tools_common").mkdir(parents=True)
    elif kind != "missing":
        snapshot(source)
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "file.py").write_text("VALUE = 1\n")
        if kind == "escaping_alias":
            (source / "ki_tools_common/escape.py").symlink_to(outside / "file.py")
        else:
            (source / "ki_tools_common/helper.py").unlink()
            (source / "ki_tools_common").rmdir()
            (source / "ki_tools_common").symlink_to(outside, target_is_directory=True)
    with pytest.raises((ValueError, OSError)):
        helper_identity.source_identity(source)


def test_prepared_source_identity_is_portable_not_materialized_digest(tmp_path):
    source = snapshot(tmp_path / "source", text="ROOT = 'KISSPATH_KI_TOOLS_COMMON'\n")
    cfg = config(tmp_path / "work")
    target = setup.prepare_common(cfg, source)
    assert helper_identity.prepared_source_identity(target) == helper_identity.source_identity(source)
    assert helper_identity.package_files(target) != helper_identity.package_files(source / "ki_tools_common")


def test_legacy_marker_cannot_claim_a_portable_source_digest(tmp_path):
    source = snapshot(tmp_path / "source")
    cfg = config(tmp_path / "work")
    assert helper_identity.prepared_source_identity(legacy_copy(cfg, source)) is None


@pytest.mark.parametrize("damage", ["missing_marker", "missing_file", "edited_file", "source_inventory", "binding"])
def test_prepared_source_identity_rejects_missing_or_tampered_evidence(tmp_path, damage):
    source = snapshot(tmp_path / "source")
    cfg = config(tmp_path / "work")
    target = setup.prepare_common(cfg, source)
    marker = target / helper_identity.MARKER
    if damage == "missing_marker":
        marker.unlink()
    elif damage == "missing_file":
        (target / "helper.py").unlink()
    elif damage == "edited_file":
        (target / "helper.py").write_text("CHANGED = True\n")
    else:
        value = json.loads(marker.read_text())
        value["binding"]["source_files" if damage == "source_inventory" else "python"] = {}
        marker.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="changed locally"):
        helper_identity.prepared_source_identity(target)
