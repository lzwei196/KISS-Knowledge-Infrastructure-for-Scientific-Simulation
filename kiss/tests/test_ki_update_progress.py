"""Current-attempt stages and actual package counts, with shipped bilingual UI."""
from __future__ import annotations

import json
import shutil
import threading
from types import SimpleNamespace

import pytest

from kiss_cli import ki_updates, published_acceptance
from . import test_ki_update_controls_ui as controls
from . import test_ki_updates as updater


@pytest.fixture
def case(monkeypatch):
    fixture = updater.KiUpdateTests()
    fixture.setUp()
    fixture._write_ki(fixture.base, "Demo", "old")
    manager = ki_updates.UpdateManager(fixture.base, lambda _: None, branch="main")
    # No network or model execution: retain real extraction/composition and the
    # updater's existing isolated publication-engine fixture.
    monkeypatch.setattr(manager, "_request_json", lambda *_: pytest.fail("Unexpected live network"))
    yield SimpleNamespace(fixture=fixture, manager=manager, monkeypatch=monkeypatch)
    fixture.tearDown()


def previous_failure(manager):
    refused = {"revision": "old", "reference": "old-reference", "lost": ["old guidance"]}
    manager._set(state="error", summary="Old failure", error="OLD ERROR",
        refused=refused, validation_failure={"error": "OLD DIAGNOSTICS"},
        ki_verification=[{"name": "OldModel", "state": "PublicationRejected"}],
        checked_at=100, source_commit="old-commit", warning_count=99,
        warnings=[{"detail": "old-warning"}], changes=[{"name": "OldModel"}],
        added=["OldModel"], updated=["OldModel"], removed=["OldModel"], package_count=99)
    return refused


def test_new_attempt_clears_stale_results_but_retains_refusal_cache(case):
    manager = case.manager
    prior_refusal = previous_failure(manager)
    manager._begin_attempt()
    report = manager.status()
    assert report["state"] == "checking"
    assert report["progress"] == {"stage": "check_main", "checked": None, "total": None, "current": None}
    for key in ("error", "refused", "validation_failure", "checked_at", "source_commit", "package_count"):
        assert report[key] is None
    for key in ("ki_verification", "warnings", "changes", "added", "updated", "removed"):
        assert report[key] == []
    assert report["warning_count"] == 0 and manager._previous_refusal == prior_refusal
    persisted = json.loads((case.fixture.home / "last-report.json").read_text(encoding="utf-8"))
    assert persisted == report


def test_start_resets_before_worker_and_double_start_preserves_attempt(case, monkeypatch):
    manager = case.manager
    previous_failure(manager)
    release = threading.Event()
    monkeypatch.setattr(manager, "_run", lambda: release.wait(5))
    try:
        assert manager.start()
        manager._progress("validate", checked=1, total=3, current="Demo")
        current = manager.status()
        assert current["error"] is None and current["ki_verification"] == []
        assert not manager.start()
        assert manager.status() == current
    finally:
        release.set()
        manager.wait(5)


def test_interrupted_attempt_does_not_resume_old_progress(case):
    case.manager._begin_attempt()
    case.manager._progress("validate", checked=4, total=127, current="CRHM")
    reopened = ki_updates.UpdateManager(case.fixture.base, lambda _: None)
    assert reopened.status()["state"] == "idle"
    assert reopened.status()["progress"] is None
    assert "interrupted" in reopened.status()["summary"]


def test_early_network_failure_cannot_reuse_previous_commit_or_findings(case, monkeypatch):
    manager = case.manager
    previous_failure(manager)
    manager._source_commit = "old-internal-commit"
    def unavailable():
        report = manager.status()
        assert report["state"] == "checking" and report["progress"]["stage"] == "check_main"
        assert report["error"] is None and report["source_commit"] is None
        raise RuntimeError("Current network failure")
    monkeypatch.setattr(manager, "_remote_revision", unavailable)
    manager._run()
    report = manager.status()
    assert report["state"] == "error" and report["error"] == "Current network failure"
    assert report["progress"] is None and report["source_commit"] is None
    assert report["validation_failure"] is None and report["ki_verification"] == []


def run_pipeline(case, *, reject=False):
    manager, fixture, monkeypatch = case.manager, case.fixture, case.monkeypatch
    archive = fixture._archive({"Demo": "new", "Other": "new"})
    manager._component_trees = {"models": "a" * 40, "manifests": "b" * 40,
                               "shared_tools": "c" * 40, "data_kis": None}
    manager._source_commit = "d" * 40
    monkeypatch.setattr(manager, "_remote_revision", lambda: (
        ki_updates._revision_identity(manager._component_trees), "a" * 40, "b" * 40))
    monkeypatch.setattr(manager, "_download", lambda target: shutil.copyfile(archive, target))
    frames = []
    actual_progress = manager._progress
    def progress(*args, **kwargs):
        actual_progress(*args, **kwargs)
        frames.append(manager.status())
    monkeypatch.setattr(manager, "_progress", progress)
    if reject:
        actual_verify = published_acceptance.verify_candidate
        def verify(root, **kwargs):
            if kwargs["name"] == "Demo":
                return {"ok": False, "failures": ["Fixture package rejected"]}
            return actual_verify(root, **kwargs)
        monkeypatch.setattr(published_acceptance, "verify_candidate", verify)
    manager._run()
    return manager.status(), frames


def test_real_update_flow_reports_stages_and_only_finished_package_counts(case):
    report, frames = run_pipeline(case)
    assert report["state"] == "updated", report.get("error")
    assert report["progress"] is None
    stages = [frame["progress"]["stage"] for frame in frames]
    order = ["check_main", "download", "extract", "compose", "validate", "activate"]
    assert [stages.index(stage) for stage in order] == sorted(stages.index(stage) for stage in order)
    packages = [frame["progress"] for frame in frames if frame["progress"].get("total") == 2]
    assert packages[0] == {"stage": "validate", "checked": 0, "total": 2, "current": None}
    assert [(p["checked"], p["current"]) for p in packages if p["current"]] == [(0, "Demo"), (1, "Other")]
    assert [(p["checked"], p["current"]) for p in packages if not p["current"]] == [(0, None), (1, None), (2, None)]
    assert all(frame["state"] == "checking" for frame in frames)
    assert len(report["ki_verification"]) == 2


def test_rejected_package_finishes_a_check_without_claiming_a_pass(case):
    report, frames = run_pipeline(case, reject=True)
    assert report["state"] == "error" and "Fixture package rejected" in report["error"]
    assert report["progress"] is None
    counts = [f["progress"] for f in frames if f["progress"].get("total") == 2]
    assert counts[-1] == {"stage": "validate", "checked": 2, "total": 2, "current": None}
    assert not any(f["progress"]["stage"] == "activate" for f in frames)
    assert {row["state"] for row in report["ki_verification"]} == {"PublicationRejected", "PublishedPackageAccepted"}
    assert "passed" not in frames[-1]["summary"].lower()


def test_success_then_failed_real_revision_lookup_clears_private_and_public_identity(case, monkeypatch):
    manager = case.manager
    first, _ = run_pipeline(case)
    assert first["state"] == "updated" and first["source_commit"]
    monkeypatch.setattr(manager, "_remote_revision", ki_updates.UpdateManager._remote_revision.__get__(manager))
    def unavailable(_url):
        raise RuntimeError("Latest commit lookup failed")
    monkeypatch.setattr(manager, "_request_json", unavailable)
    manager._run()
    report = manager.status()
    assert report["state"] == "error" and report["error"] == "Latest commit lookup failed"
    assert report["source_commit"] is None and report["ki_verification"] == []
    assert report["validation_failure"] is None and report["progress"] is None
    assert manager._source_commit == "" and manager._component_trees == {}
    assert manager._archive_ref == "refs/heads/main"
    assert report["active_revision"] == first["active_revision"]


@pytest.mark.parametrize("values", [dict(checked=2, total=1), dict(checked=True, total=1),
    dict(checked=1), dict(total=1), dict(checked=-1, total=1)])
def test_progress_rejects_untrustworthy_counts(case, values):
    with pytest.raises(ValueError, match="counts"):
        case.manager._progress("validate", **values)


@pytest.mark.skipif(controls.NODE is None, reason="Node is required for shipped UI")
@pytest.mark.parametrize("zh", [False, True])
@pytest.mark.parametrize("stage", ["check_main", "raw_windows", "download", "extract", "compose", "validate", "activate"])
def test_shipped_ui_shows_each_current_stage_in_both_languages(stage, zh):
    report = {"state": "checking", "branch": "main", "started_at": 1700000000,
        "source_commit": "a" * 40, "summary": "OLD SUMMARY", "error": "OLD ERROR",
        "validation_failure": {"error": "OLD FINDINGS"},
        "progress": {"stage": stage, "checked": 5 if stage == "validate" else None,
                     "total": 127 if stage == "validate" else None, "current": "CRHM" if stage == "validate" else None}}
    frame = controls.render("drawKiUpdate();", report=report, zh=zh)["final"]
    summary = controls.node(frame, "#updatesummary")["html"]
    details = controls.node(frame, "#updatedetails")["html"]
    assert "OLD" not in summary and "OLD" not in details
    assert ("候选提交：" if zh else "Candidate commit: ") in summary
    assert ("上次检查的提交" if zh else "Previous checked commit") not in summary
    assert ("开始时间：" if zh else "Started: ") in summary
    assert controls.node(frame, "#updateretry")["disabled"]
    if stage == "validate":
        assert "5/127" in summary and "CRHM" in summary
        assert ("已完成" if zh else "checks finished") in summary
    assert ("正在" in summary) if zh else ("正在" not in summary)


@pytest.mark.skipif(controls.NODE is None, reason="Node is required for shipped UI")
def test_current_package_is_escaped_and_bad_counts_not_displayed():
    frame = controls.render("drawKiUpdate();", report={"state": "checking", "progress": {
        "stage": "validate", "checked": 999, "total": 2, "current": '<img src=x onerror="bad()">'}})["final"]
    summary = controls.node(frame, "#updatesummary")["html"]
    assert "999/2" not in summary and "<img" not in summary and "&lt;img" in summary


@pytest.mark.skipif(controls.NODE is None, reason="Node is required for shipped UI")
def test_terminal_report_does_not_render_stale_running_progress():
    frame = controls.render("drawKiUpdate();", report={"state": "error", "summary": "Current failure",
        "error": "Current cause", "progress": {"stage": "validate", "checked": 9, "total": 127, "current": "OldModel"}})["final"]
    summary = controls.node(frame, "#updatesummary")["html"]
    assert "Current failure" in summary and "OldModel" not in summary and "9/127" not in summary
    assert not controls.node(frame, "#updateretry")["disabled"]
