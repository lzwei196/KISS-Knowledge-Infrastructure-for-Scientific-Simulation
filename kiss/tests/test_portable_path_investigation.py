"""Portable investigation accepts only its exact current declared-path evidence.

KDT reports are explicitly synthetic signed fixtures. Source projection,
registration preparation, signatures and host provenance checks are real.
No preflight, native model, runtime probe or live-project action is performed.
"""
from copy import deepcopy
from pathlib import Path

import pytest

from kiss_cli import kdtstudio, ki_adaptations as adapt, ki_copy, ki_investigation as inv
from kiss_cli import paths, project_verification, software_verification
from kiss_cli.catalog import KI
from .test_ki_adaptations import accepted
from .test_portable_path_route import fixture, files, materialized
from .test_fresh_path_callers import gui_case
from .test_fresh_path_investigation import verification_case as legacy_case


@pytest.fixture
def investigation_case(fixture, monkeypatch):
    monkeypatch.delenv("GEOFORGE_KDT_ENGINE", raising=False)
    monkeypatch.setattr(kdtstudio, "engine_source_digest", lambda: "e" * 64)
    _, cfg, live, origin = materialized(fixture)
    config_path = live.parent / paths.CONFIG_NAME
    config_path.write_text(cfg.dumps(), encoding="utf-8")
    portable = fixture.base / "portable-repair"
    ki_copy.copytree(Path(origin["portable_root"]), portable)
    with (portable / "run.py").open("a", encoding="utf-8") as stream:
        stream.write("# Reviewed portable fixture correction.\n")
    runtime = fixture.base / "runtime-candidate"
    report, proof = adapt.project_runtime(portable, runtime, cfg, model="WOFOST",
        target_root=live, manifest=origin["effective_manifest"])
    assert not report.unresolved and not report.corrupted and proof is None
    portable_report, runtime_report = accepted(portable), accepted(runtime)
    registration = adapt.prepare_registration(live, cfg, portable, portable_report, runtime, runtime_report)
    document = {"project": str(cfg.root), "draft": {
        "path": str(portable), "authoring_scope": "portable", "ki_name": "WOFOST", "active_root": str(live)},
        "verification": {"portable_report": portable_report, "runtime_candidate": str(runtime),
            "runtime_identity": software_verification.runtime_identity(cfg), "path_projection": None,
            "report": runtime_report, "registration": registration}}

    def saved(project, model, active):
        assert project == cfg.root and model == "WOFOST" and active == live
        return cfg

    monkeypatch.setattr(inv, "_project_runtime_config", saved)
    fixture.cfg, fixture.live, fixture.origin = cfg, live, origin
    fixture.portable, fixture.runtime, fixture.document = portable, runtime, document
    fixture.config_path = config_path
    return fixture


def test_current_declared_registration_is_accepted_without_adoption(investigation_case):
    c = investigation_case
    before, config_before = files(c.live), c.config_path.read_bytes()

    assert inv._require_verified_candidates(c.document) == c.runtime

    assert files(c.live) == before and c.config_path.read_bytes() == config_before
    assert adapt.projection(c.live, c.cfg) == c.origin
    assert not (adapt._home() / "registry").exists(), "Verification must not publish repair reuse authority"
    assert project_verification.status(c.cfg.root, KI("WOFOST", c.live))["can_run"] is False


@pytest.mark.parametrize("change", ["missing", "null", "unsigned", "tampered"])
def test_registration_is_mandatory_and_authenticated(investigation_case, change):
    doc = deepcopy(investigation_case.document)
    if change == "missing":
        doc["verification"].pop("registration")
    elif change == "null":
        doc["verification"]["registration"] = None
    elif change == "unsigned":
        doc["verification"]["registration"].pop("signature")
    else:
        doc["verification"]["registration"]["runtime_digest"] = "0" * 64

    with pytest.raises(ValueError, match="provenance"):
        inv._require_verified_candidates(doc)


@pytest.mark.parametrize("change", ["origin", "logical-target", "kind"])
def test_authentic_but_mismatched_registration_cannot_authorize_candidates(investigation_case, change):
    c = investigation_case
    doc = deepcopy(c.document)
    registration = doc["verification"]["registration"]
    if change == "origin":
        registration["origin"]["upstream_digest"] = "0" * 64
    elif change == "logical-target":
        registration["origin"]["logical_target"] = str(c.cfg.root / "models/Other/ki")
    else:
        registration["kind"] = "portable_adaptation"
    # Model a mismatched host record, not an agent's ability to sign one.
    doc["verification"]["registration"] = adapt._seal(registration)

    with pytest.raises(inv.InvestigationError, match="registration is stale"):
        inv._require_verified_candidates(doc)


@pytest.mark.parametrize("candidate", ["runtime", "portable"])
def test_newly_accepted_different_bytes_do_not_reuse_old_registration(investigation_case, candidate):
    c = investigation_case
    doc = deepcopy(c.document)
    replacement = c.base / ("different-" + candidate)
    ki_copy.copytree(c.runtime if candidate == "runtime" else c.portable, replacement)
    with (replacement / "run.py").open("a", encoding="utf-8") as stream:
        stream.write("# Different accepted candidate.\n")
    if candidate == "runtime":
        doc["verification"].update(runtime_candidate=str(replacement), report=accepted(replacement))
    else:
        doc["draft"]["path"] = str(replacement)
        doc["verification"]["portable_report"] = accepted(replacement)

    with pytest.raises(inv.InvestigationError, match="registration is stale"):
        inv._require_verified_candidates(doc)


def test_declared_route_refuses_an_unrelated_legacy_path_proof(investigation_case):
    doc = deepcopy(investigation_case.document)
    doc["verification"]["path_projection"] = {"logical_target": doc["draft"]["active_root"]}
    with pytest.raises(inv.InvestigationError, match="registration is stale"):
        inv._require_verified_candidates(doc)


@pytest.mark.parametrize("change", ["policy", "helpers", "configuration"])
def test_investigation_rechecks_current_host_context(investigation_case, monkeypatch, change):
    c = investigation_case
    if change == "policy":
        monkeypatch.setattr(adapt, "_portable_path_identity", lambda: "changed-policy")
    elif change == "helpers":
        (c.helpers / "helper.py").write_text("VALUE = 2\n", encoding="utf-8")
    else:
        c.cfg.python = str(c.cfg.root / "changed-runtime/python.exe")

    with pytest.raises(ValueError):
        inv._require_verified_candidates(c.document)


def test_undeclared_legacy_wofost_cannot_use_the_declared_registration_branch(legacy_case):
    c = legacy_case
    doc = deepcopy(c.document)
    origin = adapt.projection(c.target, c.cfg)
    assert not origin["context"].get("runtime_paths")
    doc["verification"]["path_projection"] = None
    # Even a host-signed registration-shaped record cannot opt the active KI
    # into a declaration absent from its authenticated projection provenance.
    doc["verification"]["registration"] = adapt._seal({**adapt._base(),
        "kind": "prepared_registration", "origin": origin,
        "runtime_paths": {"version": 1, "mode": "role_tokens"}})

    with pytest.raises(inv.InvestigationError, match="lacks current path projection evidence"):
        inv._require_verified_candidates(doc)
