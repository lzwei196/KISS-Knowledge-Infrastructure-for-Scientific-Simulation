"""Real bundled helper preparation, with no setup/model execution."""
import json
import sys

import pytest

from kiss_cli import helper_identity, ki_adaptations, ki_fresh_paths, port, setup
from .test_fresh_path_projection import case


def bundled(tmp_path):
    source, cfg, target = case(tmp_path)
    repo = tmp_path / "bundled-repository"
    helpers = repo / "ki_tools_common"
    helpers.mkdir(parents=True)
    (helpers / "helper.py").write_bytes(b"PYTHON = 'KISSPATH_PYTHON'\n")
    cfg.roles["ki_tools_common"] = cfg.root / "fresh-bundled-helper"
    return source, cfg, target, repo


def test_real_new_bundled_helper_has_bound_marker_and_supports_fresh_wofost(tmp_path):
    source, cfg, target, repo = bundled(tmp_path)
    original = helper_identity.package_files(repo / "ki_tools_common")
    helper = setup.prepare_common(cfg, repo)
    binding, files, legacy = helper_identity.checked_marker(helper)
    assert legacy is False
    assert binding == {"policy": setup.COMMON_MATERIALISATION_POLICY, "source_files": original,
                       "python": cfg.python, "relocation": cfg.relocation, "platform": sys.platform,
                       "roles": {key: str(value) for key, value in cfg.roles.items() if key != "ki_tools_common"}}
    assert files == helper_identity.package_files(helper)
    assert original == helper_identity.package_files(repo / "ki_tools_common")
    marker = json.loads((helper / helper_identity.MARKER).read_text(encoding="utf-8"))
    assert marker["source_commit"] is None and marker["source_tree"] is None
    _, proof = ki_adaptations.project_runtime(source, tmp_path / "stage", cfg,
                                              model="WOFOST", target_root=target)
    ki_fresh_paths.require_fresh_current(proof)
    assert proof["runtime"]["helper_root"] == str(helper)
    assert proof["preflight_passed"] is False and not target.exists()


def test_existing_legacy_bundled_helper_is_not_rewritten_or_given_new_authority(tmp_path):
    source, cfg, target, repo = bundled(tmp_path)
    helper = cfg.roles["ki_tools_common"]
    port.materialise(repo / "ki_tools_common", helper, cfg)
    before = ki_fresh_paths.tree_files(helper)
    assert setup.prepare_common(cfg, repo) == helper
    assert ki_fresh_paths.tree_files(helper) == before
    assert not (helper / helper_identity.MARKER).exists()
    with pytest.raises(ki_adaptations.AdaptationError, match="Unsupported WOFOST"):
        ki_adaptations.project_runtime(source, tmp_path / "stage", cfg, model="WOFOST", target_root=target)


def test_bundled_source_race_fails_before_any_marker_is_written(tmp_path, monkeypatch):
    _, cfg, _, repo = bundled(tmp_path)
    materialise = port.materialise
    def changed(source, target, config):
        result = materialise(source, target, config)
        (source / "helper.py").write_text("changed during projection")
        return result
    monkeypatch.setattr(port, "materialise", changed)
    with pytest.raises(ValueError, match="source changed"):
        setup.prepare_common(cfg, repo)
    assert not (cfg.roles["ki_tools_common"] / helper_identity.MARKER).exists()


def test_bundled_destination_mutation_cannot_be_signed_as_prepared_helpers(tmp_path, monkeypatch):
    _, cfg, _, repo = bundled(tmp_path)
    destination = cfg.roles["ki_tools_common"]
    materialise = port.materialise
    def changed(source, target, config):
        result = materialise(source, target, config)
        if target == destination:
            (target / "unexpected.py").write_text("introduced outside the source projection")
        return result
    monkeypatch.setattr(port, "materialise", changed)
    with pytest.raises(ValueError, match="exact source/runtime projection"):
        setup.prepare_common(cfg, repo)
    assert not (destination / helper_identity.MARKER).exists()
