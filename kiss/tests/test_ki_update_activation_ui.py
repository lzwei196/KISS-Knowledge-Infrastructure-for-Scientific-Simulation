"""Actual shipped controls distinguish session activation from saved selection."""
from __future__ import annotations

import pytest

from . import test_ki_update_controls_ui as controls

pytestmark = pytest.mark.skipif(controls.NODE is None, reason="Node is required for shipped UI")


def report(outcome):
    return {"state": "error", "summary": "Could not update; the current library was kept.",
        "error": "Fixture activation failure", "activation": {
            "outcome": outcome, "previous_root": "C:/library/previous",
            "candidate_root": "C:/library/candidate",
            "current_root": None if outcome == "uncertain" else "C:/library/candidate" if outcome == "committed" else "C:/library/previous",
            "saved_selection": "candidate", "error": "Fixture callback failure",
            "rollback_error": "Fixture restore failed" if outcome == "uncertain" else None,
            "restart_required": outcome == "uncertain"},
        "components": {"models": {"state": "snapshot", "source_commit": "old-snapshot"}},
        "windows_overlay": {"files": [{"mode": "retained_windows_notes"}]}}


@pytest.mark.parametrize("zh", [False, True])
@pytest.mark.parametrize("outcome", ["committed", "uncertain", "restored"])
def test_activation_failure_uses_outcome_instead_of_claiming_the_old_library_was_kept(zh, outcome):
    frame = controls.render("drawKiUpdate();", report=report(outcome), zh=zh)["final"]
    summary, details = (controls.node(frame, selector)["html"] for selector in ("#updatesummary", "#updatedetails"))
    assert "the current library was kept" not in summary
    assert "Current library kept safely" not in details and "已安全保留当前 KI 库" not in details
    assert "GeoForge 保留了当前 KI 库" not in summary
    expected = {
        "committed": ("The new KI library is active", "新 KI 库已启用"),
        "uncertain": ("could not confirm which KI library is active", "无法确认当前启用的 KI 库"),
        "restored": ("This session returned to its previous KI library", "当前会话已恢复使用之前的 KI 库"),
    }
    assert expected[outcome][int(zh)] in summary
    assert ("KI 库启用诊断" if zh else "Library activation diagnostics") in details
    assert "C:/library/previous" in details and "C:/library/candidate" in details


@pytest.mark.parametrize("zh", [False, True])
def test_uncertain_outcome_hides_stale_active_panels_and_requires_restart(zh):
    frame = controls.render("drawKiUpdate(); await checkKiUpdate();", report=report("uncertain"), zh=zh)["final"]
    details = controls.node(frame, "#updatedetails")["html"]
    assert ("当前组件来源" if zh else "Active component sources") not in details
    assert ("当前 Windows 支持" if zh else "Active Windows support") not in details
    assert "old-snapshot" not in details
    assert "Fixture restore failed" in details
    assert ("重新启动 GeoForge" if zh else "Restart GeoForge") in details
    retry = controls.node(frame, "#updateretry")
    assert retry["disabled"] and retry["text"] == ("需要重新启动" if zh else "Restart required")
    assert frame["requests"] == []


@pytest.mark.parametrize("zh", [False, True])
@pytest.mark.parametrize("outcome", ["restored", "committed"])
def test_proven_session_preserves_component_panels_and_distinguishes_saved_selection(zh, outcome):
    frame = controls.render("drawKiUpdate();", report=report(outcome), zh=zh)["final"]
    details = controls.node(frame, "#updatedetails")["html"]
    assert ("当前组件来源" if zh else "Active component sources") in details
    assert ("已保存的库选择" if zh else "Saved library selection") in details
    assert ("候选快照" if zh else "Candidate snapshot") in details
    assert ("两者可能不同" if zh else "they may differ") in details
    assert not controls.node(frame, "#updateretry")["disabled"]


@pytest.mark.parametrize("zh", [False, True])
@pytest.mark.parametrize("outcome", [None, "unchanged"])
def test_pre_activation_failure_retains_existing_safe_kept_message(zh, outcome):
    state = report("unchanged")
    if outcome is None:
        state.pop("activation")
    frame = controls.render("drawKiUpdate();", report=state, zh=zh)["final"]
    details = controls.node(frame, "#updatedetails")["html"]
    assert ("已安全保留当前 KI 库" if zh else "Current library kept safely") in details
    assert not controls.node(frame, "#updateretry")["disabled"]


def test_activation_diagnostics_escape_paths_and_errors():
    state = report("uncertain")
    payload = '<img src=x onerror="bad()">'
    state["activation"].update(previous_root=payload, candidate_root=payload, error=payload, rollback_error=payload)
    frame = controls.render("drawKiUpdate();", report=state)["final"]
    details = controls.node(frame, "#updatedetails")["html"]
    assert "<img" not in details and "&lt;img" in details


@pytest.mark.parametrize("zh", [False, True])
def test_scope_describes_current_checks_for_every_incoming_package(zh):
    frame = controls.render("drawKiUpdate();", report={"state": "idle"}, zh=zh)["final"]
    text = controls.node(frame, "#updatescope")["text"]
    assert ("每个传入的 KI 都必须通过当前 KDT" if zh else "Every incoming KI must pass current KDT") in text
    assert "New or edited KIs" not in text and "新增或修改的 KI" not in text


def test_completed_activation_keeps_success_summary_without_an_error_notice():
    state = report("committed")
    state.update(state="updated", summary="Library updated successfully", error=None)
    frame = controls.render("drawKiUpdate();", report=state)["final"]
    assert "Library updated successfully" in controls.node(frame, "#updatesummary")["html"]
    assert "follow-up failed" not in controls.node(frame, "#updatedetails")["html"]
    assert "Library activation diagnostics" not in controls.node(frame, "#updatedetails")["html"]


def test_historical_uncertainty_does_not_block_a_restarted_session():
    state = report("uncertain")
    state["previous_activation"] = state.pop("activation")
    state.update(state="idle", activation=None, error=None, summary="A new session can check again")
    frame = controls.render("drawKiUpdate();", report=state)["final"]
    assert not controls.node(frame, "#updateretry")["disabled"]
    assert "Restart required" not in controls.node(frame, "#updatedetails")["html"]
    assert "could not confirm" not in controls.node(frame, "#updatesummary")["html"]
    assert "Active component sources" in controls.node(frame, "#updatedetails")["html"]
