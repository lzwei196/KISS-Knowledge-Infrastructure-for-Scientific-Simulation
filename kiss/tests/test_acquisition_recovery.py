"""Recovery of approved acquisition UI, using isolated files and transport fixtures."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import threading

import pytest

from kiss_cli import acquire, api, flowgate, flowrun, obs_access, obs_subset, plan_review, project_status
from kiss_cli import setup as setup_flow
from .test_acquisition_mixed_delivery import (
    _Downloads, _approve, _continue, _mixed, _place, _review, _subset_done,
)
from .test_flowgate import _cfg


def _manual_project(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    project, fs, ki, approval_card = _review(tmp_path, monkeypatch, "subset", True)
    downloads = _Downloads()
    download = downloads.download

    def manual_details(dataset_id, project):
        info = download(dataset_id, project)
        return dict(info, baidu_pwd="fixture-code", path_in_share="yearbooks/2003")

    monkeypatch.setattr(downloads, "download", manual_details)
    monkeypatch.setattr(obs_access, "Client", lambda: downloads)
    monkeypatch.setattr(obs_subset, "advance_approved",
        lambda *args, **kwargs: {"status": "running", "receipt": None})
    monkeypatch.setattr(flowrun, "ACQ_POLL_SECONDS", 0)
    _approve(project, ki, approval_card)
    original = setup_flow.request(project)
    assert original["rows"][0]["code"] == "fixture-code"
    return project, fs, ki, original, downloads


def test_background_reissued_manual_card_keeps_link_code_and_share_path(tmp_path, monkeypatch):
    project, fs, ki, original, downloads = _manual_project(tmp_path, monkeypatch)
    setup_flow.clear_request(project)
    calls_before = list(downloads.calls)

    assert flowrun.poll_acquisition(project, True, automatic_only=True) == "waiting"
    reissued = setup_flow.request(project)
    assert reissued["rows"] == original["rows"], "background recovery lost manual download instructions"
    assert downloads.calls == calls_before, "background recovery must not fetch fresh manual links"
    assert acquire.status(project)["items"]["manual"]["status"] == "waiting"
    snapshot = project_status.snapshot(project)
    public_summary = json.dumps([snapshot["progress"]["acquisition"],
                                 snapshot["progress"]["summary"], snapshot["observations"]])
    assert "fixture-code" not in public_summary and "https://example.invalid" not in public_summary


def test_saved_manual_download_credentials_are_not_readable_or_listed_by_agent_tools(tmp_path, monkeypatch):
    project, fs, ki, original, downloads = _manual_project(tmp_path, monkeypatch)
    session = flowgate.FlowSession.open(project, {ki.name: ki.root})
    private_path = acquire.MANUAL_DETAILS_FILE.as_posix()
    assert (project / private_path).is_file()
    listing = api.execute_tool("list_project_files", {"subdir": ".geoforge"}, ki, _cfg(project),
                               project_mode=True, flow=session,
                               setup_context={"project_root": str(project)})
    assert acquire.MANUAL_DETAILS_FILE.name not in listing
    with pytest.raises(api.ToolError, match="request card|user-only"):
        api.execute_tool("read_project_file", {"path": private_path}, ki, _cfg(project),
                         project_mode=True, flow=session,
                         setup_context={"project_root": str(project)})
    setup_listing = api.execute_tool("list_work_files", {}, ki, _cfg(project), setup_mode=True)
    assert acquire.MANUAL_DETAILS_FILE.name not in setup_listing
    with pytest.raises(api.ToolError, match="user-only"):
        api.execute_tool("read_work_file", {"path": private_path}, ki, _cfg(project), setup_mode=True)


@pytest.mark.parametrize("case", ["old_approval", "other_dataset", "unsafe_url", "old_project"])
def test_reissued_manual_details_are_approval_scoped_safe_and_have_an_honest_fallback(
        tmp_path, monkeypatch, case):
    project, fs, ki, original, downloads = _manual_project(tmp_path, monkeypatch)
    doc = json.loads((project / acquire.MANUAL_DETAILS_FILE).read_text())
    saved = doc["items"]["manual"]
    if case == "old_approval":
        doc["approval_sha256"] = "superseded-approval"
    elif case == "other_dataset":
        saved["dataset_id"] = "unapproved-yearbook"
    elif case == "unsafe_url":
        saved["url"] = "javascript:alert(1)"
    else:
        doc["items"] = {}
    obs_access._atomic_json(project / acquire.MANUAL_DETAILS_FILE, doc)
    setup_flow.clear_request(project)
    calls_before = list(downloads.calls)

    assert flowrun.poll_acquisition(project, True, automatic_only=True) == "waiting"
    card = setup_flow.request(project)
    assert not card["rows"][0]["url"]
    if case != "unsafe_url":
        assert not card["rows"][0]["code"]
    assert "Send a chat message to refresh" in card["message"]
    assert downloads.calls == calls_before


@pytest.mark.parametrize("transfer_result", ["running", "done"])
def test_change_plan_returns_while_download_runs_then_applies_under_acquisition_lock(
        tmp_path, monkeypatch, transfer_result):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    entered, release = threading.Event(), threading.Event()
    armed = []

    def advance(_n):
        if not armed:
            return "running"
        entered.set()
        assert release.wait(5), "fixture download was not released"
        return _subset_done(project, fs) if transfer_result == "done" else "running"

    project, fs, ki, card, _calls = _mixed(tmp_path, monkeypatch, advance)
    _place(card)
    _continue(project, ki, card)
    approval = fs.flow.approval.approval_id(fs.flow.approval.read(project))
    armed.append(True)
    outcome = {}
    tick = threading.Thread(target=lambda: outcome.update(
        tick=flowrun.poll_acquisition(project, True, automatic_only=True)))

    def modify():
        outcome["pre"] = flowrun.pre(
            project, "Please change the plan", [ki.name], [ki],
            {"request_id": acquire.MANUAL_REQUEST_ID, "option_id": "modify"}, card,
            note="Use the station data instead", setup_ok=True)

    click = threading.Thread(target=modify)
    tick.start()
    try:
        assert entered.wait(2)
        click.start()
        click.join(0.3)
        assert not click.is_alive(), "Modify plan blocked behind the in-flight subset download"
        assert outcome["pre"].message, "the user needs confirmation that the change is queued"
        assert not outcome["pre"].replan_reason, "do not start a planning turn during the old download"
        assert flowrun.current_state(project) == "ACQUIRING"
        assert fs.flow.approval.check(project) == "OK", "only the lock owner may revoke approval"
    finally:
        release.set()
        tick.join(5)
        if click.ident:
            click.join(5)

    assert flowrun.current_state(project) == "PLANNING"
    assert fs.flow.approval.check(project) != "OK"
    assert setup_flow.request(project) is None
    assert outcome["tick"] == "replanning"
    if transfer_result == "done":
        receipt = acquire.status(project)["items"]["automatic"]["receipt"]
        assert json.loads(Path(receipt).read_text())["approval_sha256"] == approval
    followup = flowrun.pre(project, "Continue", [ki.name], [ki], None, None, setup_ok=True)
    assert followup.replan_reason == "Use the station data instead"
    assert not flowrun.pre(project, "Continue again", [ki.name], [ki], None, None,
                           setup_ok=True).replan_reason


def _queue_intent(project, approval):
    obs_access._atomic_json(project / acquire.REPLAN_FILE, {
        "status": "queued", "approval_sha256": approval, "reason": "Use the station data instead",
    })


def test_restart_consumes_persisted_replan_before_any_more_network(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    project, fs, ki, card, calls = _mixed(tmp_path, monkeypatch, lambda n: "running")
    _queue_intent(project, fs.flow.approval.approval_id(fs.flow.approval.read(project)))
    before = list(calls)
    assert flowrun.poll_acquisition(project, True, automatic_only=True) == "replanning"
    assert calls == before
    assert flowrun.current_state(project) == "PLANNING"
    assert fs.flow.approval.check(project) != "OK"


def test_stale_replan_intent_cannot_revoke_current_approval(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    project, fs, ki, card, calls = _mixed(tmp_path, monkeypatch, lambda n: "running")
    _queue_intent(project, "superseded-approval")
    assert flowrun.poll_acquisition(project, True, automatic_only=True) == "waiting"
    assert fs.flow.approval.check(project) == "OK"
    assert flowrun.current_state(project) == "ACQUIRING"
    assert acquire.replan_intent(project)["status"] == "stale"


def test_interrupted_final_intent_write_surfaces_saved_note_without_assuming_it_applied(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    project, fs, ki, card, calls = _mixed(tmp_path, monkeypatch, lambda n: "running")
    _queue_intent(project, fs.flow.approval.approval_id(fs.flow.approval.read(project)))
    atomic_json = obs_access._atomic_json

    def interrupted(path, payload):
        if path == project / acquire.REPLAN_FILE and payload.get("status") == "applied":
            raise OSError("synthetic interruption after Flow moved")
        return atomic_json(path, payload)

    monkeypatch.setattr(obs_access, "_atomic_json", interrupted)
    assert flowrun.poll_acquisition(project, True, automatic_only=True) is None
    assert flowrun.current_state(project) == "PLANNING"
    assert acquire.replan_intent(project)["status"] == "queued"
    monkeypatch.setattr(obs_access, "_atomic_json", atomic_json)

    resumed = flowrun.pre(project, "Continue", [ki.name], [ki], None, None, setup_ok=True)
    assert resumed.message and "Use the station data instead" in resumed.message
    assert "confirm" in resumed.message.lower()
    assert not resumed.replan_reason, "uncertain recovery must not silently apply an old note"
    assert flowrun.current_state(project) == "PLANNING"
    assert acquire.replan_intent(project)["status"] == "needs_confirmation"


def test_queued_modify_keeps_current_receipt_but_never_starts_the_next_automatic_input(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    project, fs, ki, card = _review(tmp_path, monkeypatch, "subset", True)
    plan, inventory = fs.flow.plan.read_artifacts(project)
    later = deepcopy(inventory["items"][1])
    later.update(id="later", acquisition_id="b" * 32)
    inventory["items"].append(later)
    plan["steps"][0]["inputs"].append("later")
    assert not fs.write_plan(plan, inventory)
    card = plan_review.issue(project, fs, plan, inventory, "Three-input recovery fixture")
    monkeypatch.setattr(obs_access, "Client", _Downloads)
    monkeypatch.setattr(flowrun, "ACQ_POLL_SECONDS", 0)
    armed, calls, clicked = [], [], []

    def advance(project_, ident, client=None):
        calls.append(ident)
        if armed:
            assert ident == "a" * 32, "a later automatic input started after Modify"
            clicked.append(flowrun.pre(
                project, "Change the plan", [ki.name], [ki],
                {"request_id": acquire.MANUAL_REQUEST_ID, "option_id": "modify"},
                setup_flow.request(project), note="Use stations", setup_ok=True))
            return _subset_done(project, fs)
        return {"status": "running", "receipt": None}

    monkeypatch.setattr(obs_subset, "advance_approved", advance)
    _approve(project, ki, card)
    calls.clear()
    armed.append(True)
    assert flowrun.poll_acquisition(project, True, automatic_only=True) == "replanning"
    assert calls == ["a" * 32]
    assert clicked[0].message and not clicked[0].replan_reason
    assert acquire.status(project)["items"]["automatic"]["status"] == "done"
    assert flowrun.current_state(project) == "PLANNING"


def test_modify_during_receipt_lookup_prevents_admitting_the_next_remote_request(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    project, fs, ki, card, calls = _mixed(tmp_path, monkeypatch, lambda n: "running")
    find_download = fs.flow.receipts.find_download
    queued = []

    def find_with_click(project_, item, **kwargs):
        result = find_download(project_, item, **kwargs)
        if item["id"] == "automatic" and not queued:
            queued.append(flowrun.pre(
                project, "Change the plan", [ki.name], [ki],
                {"request_id": acquire.MANUAL_REQUEST_ID, "option_id": "modify"}, card,
                note="Use stations", setup_ok=True))
        return result

    monkeypatch.setattr(fs.flow.receipts, "find_download", find_with_click)
    before = list(calls)
    assert flowrun.poll_acquisition(project, True, automatic_only=True) == "replanning"
    assert queued[0].message
    assert calls == before, "a remote request was admitted after Modify acknowledged the intent"
    assert flowrun.current_state(project) == "PLANNING"


def test_completed_old_pass_cannot_promote_a_new_approval_with_another_required_input(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    armed = []

    def advance(_n):
        if not armed:
            return "running"
        outcome = _subset_done(project, fs)
        plan, inventory = fs.flow.plan.read_artifacts(project)
        extra = deepcopy(inventory["items"][0])
        extra.update(id="new-required", dataset_id="new-yearbook", chosen_source="new-yearbook",
                     acceptable_sources=["new-yearbook"])
        inventory["items"].append(extra)
        plan["steps"][0]["inputs"].append("new-required")
        assert not fs.write_plan(plan, inventory)
        approved = fs.flow.approval.approve(project, by="user")
        acquire._write(project, {"status": "pending", "items": {},
                                 "approval_sha256": fs.flow.approval.approval_id(approved)})
        return outcome

    project, fs, ki, card, calls = _mixed(tmp_path, monkeypatch, advance)
    _place(card)
    _continue(project, ki, card)
    original = fs.flow.approval.approval_id(fs.flow.approval.read(project))
    armed.append(True)

    assert flowrun.poll_acquisition(project, True, automatic_only=True) == "stale"
    assert fs.flow.approval.check(project) == "OK"
    assert fs.flow.approval.approval_id(fs.flow.approval.read(project)) != original
    assert flowrun.current_state(project) == "ACQUIRING", "old input receipts advanced a new approval"
    assert acquire.status(project)["approval_sha256"] != original, "old pass overwrote the new status"


def test_acquisition_result_without_approval_identity_cannot_start_execution(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    project, fs, ki, card, calls = _mixed(tmp_path, monkeypatch, lambda n: "running")
    monkeypatch.setattr(acquire, "run", lambda *args, **kwargs: {"status": "done", "items": {}})
    assert flowrun.poll_acquisition(project, True, automatic_only=True) == "stale"
    assert flowrun.current_state(project) == "ACQUIRING"
