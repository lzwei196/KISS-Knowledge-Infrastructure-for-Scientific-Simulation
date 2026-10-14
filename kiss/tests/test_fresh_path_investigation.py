"""Portable adoption rechecks fresh path proof before any active KI mutation.

Only KDT reports are synthetic signed fixtures. Projection, saved configuration
parsing, source/runtime hashing and proof validation use their real code.
"""
from copy import deepcopy
from pathlib import Path

import pytest

from kiss_cli import kdtstudio, ki_adaptations, ki_fresh_paths, ki_investigation
from kiss_cli import paths, software_verification
from .test_fresh_path_callers import gui_case
from .test_ki_adaptations import accepted


@pytest.fixture
def verification_case(gui_case, monkeypatch):
    c = gui_case
    monkeypatch.delenv("GEOFORGE_KDT_ENGINE", raising=False)
    monkeypatch.setattr(kdtstudio, "engine_source_digest", lambda: "e" * 64)
    active, cfg = c.handler._session_workspace(c.cfg.root, c.ki, cfg=c.cfg,
                                              write_project_config=False)
    runtime = c.base / "portable-runtime-candidate"
    _, proof = ki_adaptations.project_runtime(c.source, runtime, cfg,
        model="WOFOST", target_root=active.root)
    doc = {"project": str(cfg.root), "draft": {
        "path": str(c.source), "authoring_scope": "portable", "ki_name": "WOFOST",
        "active_root": str(active.root)}, "verification": {
        "portable_report": accepted(c.source), "runtime_candidate": str(runtime),
        "runtime_identity": software_verification.runtime_identity(cfg),
        "path_projection": proof, "report": accepted(runtime)}}
    c.document, c.runtime = doc, runtime
    return c


def test_portable_wofost_exact_current_proof_is_accepted_without_adoption(verification_case):
    c = verification_case
    active_before = ki_fresh_paths.tree_files(c.target)
    config_path = c.target.parent / paths.CONFIG_NAME
    config_before = config_path.read_bytes()
    assert ki_investigation._require_verified_candidates(c.document) == c.runtime
    assert ki_fresh_paths.tree_files(c.target) == active_before
    assert config_path.read_bytes() == config_before


@pytest.mark.parametrize("missing", ["absent", "null"])
def test_portable_wofost_legacy_verification_requires_fresh_path_proof(verification_case, missing):
    doc = deepcopy(verification_case.document)
    if missing == "absent":
        doc["verification"].pop("path_projection")
    else:
        doc["verification"]["path_projection"] = None
    with pytest.raises(ki_investigation.InvestigationError, match="lacks current path projection evidence"):
        ki_investigation._require_verified_candidates(doc)


def test_portable_proof_is_bound_to_saved_configuration_not_only_outer_identity(verification_case):
    c = verification_case
    doc = deepcopy(c.document)
    # Model an inconsistent historical host verification: its outer runtime
    # binding is current, but the embedded path proof belongs to another config.
    doc["verification"]["path_projection"]["runtime"]["config_sha256"] = "0" * 64
    assert doc["verification"]["runtime_identity"] == software_verification.runtime_identity(c.cfg)
    with pytest.raises(ki_investigation.InvestigationError, match="saved project configuration"):
        ki_investigation._require_verified_candidates(doc)


def test_portable_proof_cannot_retarget_a_different_active_ki(verification_case):
    c = verification_case
    doc = deepcopy(c.document)
    doc["verification"]["path_projection"]["logical_target"] = str(c.target.parent / "other-ki")
    with pytest.raises(ki_investigation.InvestigationError, match="another deployment target"):
        ki_investigation._require_verified_candidates(doc)


def test_portable_wofost_rechecks_current_normalizer_even_when_kdt_is_unchanged(verification_case, monkeypatch):
    c = verification_case
    monkeypatch.setattr(ki_fresh_paths, "source_digest", lambda: "0" * 64)
    with pytest.raises(ValueError, match="projection"):
        ki_investigation._require_verified_candidates(c.document)
