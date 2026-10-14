"""A signed rejected package can produce a checked draft, never adoption."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from kiss_cli import ki_copy, ki_guard, ki_investigation as inv, ki_maintenance, ki_updates
from kiss_cli import ki_verification, published_acceptance
from .test_ki_maintenance import case


@pytest.fixture
def rejected(case, monkeypatch):
    monkeypatch.setenv("GEOFORGE_KI_INVESTIGATION_HOME", str(case.root / "investigations"))
    monkeypatch.setenv("GEOFORGE_KDT_HOME", str(case.root / "studio"))
    staging = ki_updates.update_root() / ".incoming-rejected"
    package = staging / "models/Demo"
    ki_copy.copytree(case.base, package)
    origin = published_acceptance._issue_origin(staging, source_commit="a" * 40,
        archive_sha256="b" * 64, source_content_sha256=ki_updates._snapshot_content_hash(staging),
        overlay={}, trees={})
    case.engine.ok = False
    report = published_acceptance.verify_candidate(package, name="Demo", kind="process_model", origin=origin)
    quarantine = ki_updates.update_root() / "quarantine/fixture"
    quarantine.parent.mkdir(parents=True)
    staging.rename(quarantine)
    package = quarantine / "models/Demo"
    saved = {"validation_failure": {"quarantine_path": str(quarantine), "ki_verification": [{"name":"Demo", "report":report}]}}
    (ki_updates.update_root() / "last-report.json").write_text(json.dumps(saved), encoding="utf-8")
    case.engine.ok = True
    project = case.root / "project"
    project.mkdir()
    def apply(candidate, *, source, recipe, name):
        changes = case.recipes.expected_changes(source, name)
        for relative, value in changes.items():
            (candidate / relative).write_bytes(value)
        return {"recipe":recipe, "changed_files":list(changes)}
    monkeypatch.setattr(case.recipes, "apply_recipe", apply)
    yield case, package, report, project, saved
    inv._RUNNING.clear();inv._STOPS.clear()


def review(role, context, digest, stop, emit):
    return {"status":"completed", "summary":"Read exact rejected source", "context_digest":digest,
        "findings":[{"category":"package", "severity":"medium", "claim":"Inventory mismatch",
                     "evidence":["kis/Demo/SKILL.md"], "recommendation":"Bounded maintenance"}],
        "tests_not_run":["Native model"], "uncertainties":[]}


def make_reviewed(rejected):
    _, package, report, project, _ = rejected
    job = inv.create(project, {"id":"fixture"}, {"Demo":package}, "api:deepseek",
                     publication_sources={"Demo":report})
    return inv.run_reviews(project, job["id"], review)


def test_rejected_source_selector_authenticates_only_selected_ki(rejected):
    _, package, _, _, _ = rejected
    assert inv.rejected_update_sources(["Other"]) == []
    rows = inv.rejected_update_sources(["Demo"])
    assert len(rows) == 1 and rows[0]["root"] == str(package)
    assert inv.resolve_rejected_update_source(rows[0]["id"], ["Demo"]) == rows[0]
    with pytest.raises(ValueError):
        inv.resolve_rejected_update_source("f" * 64, ["Demo"])
    with pytest.raises(ValueError):
        inv.resolve_rejected_update_source(rows[0]["id"], ["Other"])


@pytest.mark.parametrize("damage", ["signature", "outside", "bytes", "profile", "wrapper", "rows"])
def test_rejected_selection_fails_closed_on_drift_or_untrusted_report(rejected, monkeypatch, damage):
    case, package, _, _, saved = rejected
    if damage == "signature":saved["validation_failure"]["ki_verification"][0]["report"]["ok"] = True
    elif damage == "outside":saved["validation_failure"]["quarantine_path"] = str(case.root)
    elif damage == "bytes":(package / "SKILL.md").write_text("changed")
    elif damage == "profile":monkeypatch.setattr(published_acceptance, "profile_digest", lambda:"changed")
    elif damage == "wrapper":saved["validation_failure"] = ["bad"]
    elif damage == "rows":saved["validation_failure"]["ki_verification"] = 3
    (ki_updates.update_root() / "last-report.json").write_text(json.dumps(saved), encoding="utf-8")
    assert inv.rejected_update_sources(["Demo"]) == []


def test_rejected_source_requires_reviews_and_cannot_enter_authoring(rejected):
    _, package, report, project, _ = rejected
    job = inv.create(project, {"id":"fixture"}, {"Demo":package}, "api:deepseek",
                     publication_sources={"Demo":report})
    with pytest.raises(ValueError, match="three reviews"):
        inv.create_draft(project, job["id"], "Demo", repair_mode="maintenance", maintenance_recipe="tool_inventory")
    inv.run_reviews(project, job["id"], review)
    with pytest.raises(ValueError, match="maintenance drafts only"):
        inv.create_draft(project, job["id"], "Demo")


def test_rejected_source_is_frozen_then_checked_but_never_enrolled_or_adopted(rejected):
    _, package, _, project, _ = rejected
    digest = ki_verification.content_digest(package)
    job = make_reviewed(rejected)
    frozen = Path(job["maintenance_sources"]["Demo"]["base_root"])
    assert frozen != package and ki_verification.content_digest(frozen) == digest
    job = inv.create_draft(project, job["id"], "Demo", repair_mode="maintenance", maintenance_recipe="tool_inventory")
    assert not job["draft"]["project_local"]
    job = inv.verify_draft(project, job["id"])
    assert job["verification"]["ok"] and not job["can_apply"]
    assert job["verification"]["report"]["state"] == "MaintenanceVerified"
    with pytest.raises(ValueError, match="project-local"):
        inv.apply(project, job["id"], job["verification"]["id"])
    assert not ki_guard.is_managed(package)
    assert ki_verification.content_digest(package) == digest
    assert not (project / "models/Demo/ki").exists()

