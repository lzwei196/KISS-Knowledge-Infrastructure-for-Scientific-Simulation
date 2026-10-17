"""Repair continuation separates signed applied bytes from review hypotheses."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path

import pytest

from kiss_cli import gui, ki_investigation as inv, sessions
from .test_gui_investigation import case, apply_verified, make_verified


def resumed(case, monkeypatch):
    result = apply_verified(case, monkeypatch)
    return result, sessions.load(case.work, case.session["id"])


def test_current_signed_adoption_reports_real_paths_hashes_separate_from_review(case, monkeypatch):
    result, saved = resumed(case, monkeypatch)
    saved["ki_repair_resume"]["summary"] = "Hypothesis: add argparse and --crop flags."
    _, seed = gui._repair_history(saved, project=case.project)
    fact_text = seed.split("Authenticated applied-change facts (rechecked for this turn):\n", 1)[1].split("\nInspect the current changed", 1)[0]
    facts = json.loads(fact_text)
    assert facts["active_bytes_match_verified_adoption"] is True
    assert facts["active_ki_sha256"] == result["job"]["apply"]["adopted_digest"]
    assert facts["recipe"] is None and facts["repair_mode"] == "authoring"
    reader = next(row for row in facts["changed_files"] if row["path"] == "tools/reader.py")
    assert reader["after_sha256"] == hashlib.sha256((case.root / "tools/reader.py").read_bytes()).hexdigest()
    assert "argparse" not in fact_text and "--crop" not in fact_text
    assert "recommendations may be unimplemented" in seed
    assert "not a user scientific choice" in seed
    assert "never offer dropping a required check" in seed
    assert "Fresh plan approval and required preflight/receipts still apply" in seed


@pytest.mark.parametrize("damage", ["live", "candidate", "journal", "generation", "different_project"])
def test_stale_or_unauthenticated_evidence_cannot_claim_current_source(case, monkeypatch, tmp_path, damage):
    result, saved = resumed(case, monkeypatch)
    project = case.project
    if damage == "live":
        path = case.root / "tools/reader.py"
        before = path.stat()
        path.write_bytes(path.read_bytes().replace(b"return 2", b"return 9"))
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    elif damage == "candidate":
        path = Path(result["job"]["draft"]["path"]) / "tools/reader.py"
        path.write_text("def read(): return 9\n", encoding="utf-8")
    elif damage == "journal":
        path = inv._root(project, result["job"]["id"]) / "job.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["apply"]["generation"] = "forged"
        path.write_text(json.dumps(doc), encoding="utf-8")
    elif damage == "generation":
        saved["ki_repair_generation"] = "another-generation"
    else:
        project = tmp_path / "another-project"
        project.mkdir()
    _, seed = gui._repair_history(saved, project=project)
    assert "Current applied-change facts unavailable" in seed
    assert '"active_bytes_match_verified_adoption": true' not in seed


def test_reviewer_caveats_survive_combined_summary_and_memory_reset(case, monkeypatch):
    job = make_verified(case, monkeypatch)
    saved_job = inv._load(case.project, job["id"])
    saved_job["combined_report"]["summary"] = "The proposed repair looks straightforward."
    saved_job["reviewers"][0]["report"].update(
        uncertainties=["Whether the current tool accepts named flags remains unverified."],
        tests_not_run=["No native crop execution was run by this reviewer."])
    inv._save(case.project, saved_job)
    applied = inv.apply(case.project, job["id"], job["verification"]["id"])
    session = {"messages": []}
    gui._reconcile_ki_repair(session, case.project, applied)
    session["ki_repair_resume"].pop("review_limits")  # session saved before this host improvement
    _, seed = gui._repair_history(session, project=case.project)
    assert "Whether the current tool accepts named flags remains unverified" in seed
    assert "No native crop execution was run by this reviewer" in seed
    memory = case.project / "memory" / f"ki-repair-{session['ki_repair_generation']}.json"
    assert json.loads(memory.read_text(encoding="utf-8"))["reviewers"][0]["report"]["uncertainties"]


def test_missing_project_binding_never_uses_cached_session_claims():
    session = {"ki_repair_generation": "pretend", "ki_repair_resume": {
        "history_started_at": 1, "job_id": "pretend", "applied_facts": {"verified": True},
        "summary": "Unverified review text"}, "messages": []}
    _, seed = gui._repair_history(session)
    assert "no project binding was supplied" in seed
    assert '"verified": true' not in seed


def test_reviewer_limits_are_bounded():
    job = {"reviewers": [{"role": "reviewer", "report": {
        "uncertainties": ["u" * 10000] * 100, "tests_not_run": ["t" * 10000] * 100}}] * 3}
    text = gui._repair_review_limits(job)
    assert len(text) <= 2400
