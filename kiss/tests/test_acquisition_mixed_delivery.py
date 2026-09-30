"""Approved automatic acquisition must continue while a manual input is outstanding.

Synthetic project and transport only: no real database, model, keys or user files.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import threading

import pytest

from kiss_cli import acquire, flowrun, obs_access, obs_subset, plan_review, project_status, settings
from kiss_cli import setup as setup_flow
from .test_flowgate import _cfg, _ki, _plan, _session


@pytest.fixture(autouse=True)
def _isolated_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))


def _review(tmp_path, monkeypatch, delivery, manual_first):
    ki = _ki(tmp_path)
    project, fs = _session(tmp_path, ki, [
        ("task_received", None), ("kis_resolved", {"selected_kis": ["M"]})])
    plan, inventory = _plan(ki)
    plan["scientific_choices"] = []
    manual = deepcopy(inventory["items"][0])
    manual.update(id="manual", dataset_id="manual-yearbook", chosen_source="manual-yearbook",
                  acceptable_sources=["manual-yearbook"], delivery="manual")
    automatic = deepcopy(inventory["items"][0])
    automatic.update(id="automatic", dataset_id="automatic-forcing", chosen_source="automatic-forcing",
                     acceptable_sources=["automatic-forcing"], delivery=delivery)
    inventory["items"] = [manual, automatic] if manual_first else [automatic, manual]
    plan["steps"][0]["inputs"] = ["automatic", "manual"]
    if delivery == "subset":
        automatic["acquisition_id"] = "a" * 32
        # Synthetic transport binding; keep the real plan review and host acquisition.
        monkeypatch.setattr(obs_subset, "stamp_item", lambda project, item: {})
        monkeypatch.setattr(obs_subset, "refresh_inventory", lambda project, inventory: {})
        monkeypatch.setattr(obs_subset, "approve_inventory", lambda project, inventory: [])
        monkeypatch.setattr(obs_subset, "bind_approved", lambda project, ident=None: [])
    catalogue = {"ok": True, "datasets": [
        {"id": "manual-yearbook", "name": "Manual yearbook", "delivery": "manual"},
        {"id": "automatic-forcing", "name": "Automatic forcing", "delivery": delivery},
    ]}
    # These tests exercise approved Database acquisition, not credential setup.
    # Never let activation depend on the developer's real Settings/Keychain/cache.
    monkeypatch.setattr(settings, "database_access_mode", lambda: "direct")
    monkeypatch.setattr(obs_access, "token_state", lambda: "configured")
    monkeypatch.setattr(obs_access, "load_catalogue", lambda: catalogue)
    monkeypatch.setattr(obs_access, "refresh_catalogue", lambda **kwargs: catalogue)
    monkeypatch.setattr(obs_access, "resolved_records", lambda: [])
    assert fs.write_plan(plan, inventory) == []
    fs.move("plan_written", {"plan_valid": True})
    card = plan_review.issue(project, fs, plan, inventory, "Synthetic mixed-delivery test")
    return project, fs, ki, card


def _approve(project, ki, card):
    return flowrun.pre(project, "Approve the reviewed plan", [ki.name], [ki],
                       {"request_id": card["id"], "option_id": "approve"}, card,
                       setup_ok=True)


class _Downloads:
    def __init__(self):
        self.calls = []

    def download(self, dataset_id, project):
        self.calls.append(dataset_id)
        if dataset_id == "manual-yearbook":
            return {"served": False, "name": "Manual yearbook", "size": 10,
                    "baidu_url": "https://example.invalid/manual-yearbook",
                    "destination": str(project / "inputs" / "observations" / dataset_id)}
        assert dataset_id == "automatic-forcing"
        target = project / "inputs" / "observations" / dataset_id / "forcing.dat"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"synthetic transport fixture")
        return {"served": True, "destination": str(target.parent),
                "raw_file": str(target), "files": [str(target)]}


@pytest.mark.parametrize("manual_first", [False, True])
def test_approval_downloads_served_input_even_while_manual_input_is_missing(
        tmp_path, monkeypatch, manual_first):
    project, fs, ki, card = _review(tmp_path, monkeypatch, "served", manual_first)
    downloads = _Downloads()
    monkeypatch.setattr(obs_access, "Client", lambda: downloads)
    _approve(project, ki, card)

    assert "automatic-forcing" in downloads.calls
    state = acquire.status(project)
    assert state["items"]["automatic"]["status"] == "done"
    assert Path(state["items"]["automatic"]["receipt"]).is_file()
    assert state["items"]["manual"]["status"] == "waiting"
    assert flowrun.current_state(project) == "ACQUIRING"
    assert flowrun.turn(project, [ki], _cfg(project), "api", "deepseek", None, "continue") is None


@pytest.mark.parametrize("manual_first", [False, True])
def test_poll_completes_automatic_subset_while_manual_card_remains_open(
        tmp_path, monkeypatch, manual_first):
    project, fs, ki, card = _review(tmp_path, monkeypatch, "subset", manual_first)
    downloads = _Downloads()
    monkeypatch.setattr(obs_access, "Client", lambda: downloads)
    advances = []

    def advance(project, ident, client=None):
        advances.append(ident)
        if len(advances) == 1:
            return {"status": "running", "receipt": None}
        target = project / "inputs" / "subset-fixture.dat"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"synthetic completed subset")
        _, inventory = fs.flow.plan.read_artifacts(project)
        item = next(item for item in inventory["items"] if item["id"] == "automatic")
        receipt = fs.flow.receipts.record_download(
            project, item_id="automatic", source="Synthetic subset transport",
            request_url="https://example.invalid/subset", http_status=200, raw_files=[target],
            approval_sha256=fs.flow.approval.approval_id(fs.flow.approval.read(project)),
            inventory_item=item, plan_step_id="M:run")
        return {"status": "downloaded", "receipt": str(receipt), "path": str(target)}

    monkeypatch.setattr(obs_subset, "advance_approved", advance)
    _approve(project, ki, card)
    initial = acquire.status(project)
    assert advances == ["a" * 32]
    assert initial["items"]["automatic"]["status"] == "pending"
    assert initial["items"]["manual"]["status"] == "waiting"
    manual_card = setup_flow.request(project)
    assert manual_card["id"] == acquire.MANUAL_REQUEST_ID
    assert not Path(manual_card["rows"][0]["expected_path"]).exists()

    # Simulate the next desktop status poll, without sending a chat message or
    # answering the manual card. All state movement/acquisition logic is real.
    monkeypatch.setattr(flowrun, "ACQ_POLL_SECONDS", 0)
    assert flowrun.poll_acquisition(project, setup_ok=True, automatic_only=True) == "waiting"
    assert advances == ["a" * 32, "a" * 32], "Manual wait must not suppress automatic progress"
    current = acquire.status(project)
    assert current["items"]["automatic"]["status"] == "done"
    assert current["items"]["manual"]["status"] == "waiting"
    assert setup_flow.request(project)["id"] == acquire.MANUAL_REQUEST_ID
    assert flowrun.current_state(project) == "ACQUIRING"
    assert flowrun.turn(project, [ki], _cfg(project), "api", "deepseek", None, "continue") is None
    assert not (project / ".geoforge" / "receipts" / "model-runs").exists()


def _subset_done(project, fs):
    target = project / "inputs" / "subset-fixture.dat"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"synthetic completed subset")
    _, inventory = fs.flow.plan.read_artifacts(project)
    item = next(item for item in inventory["items"] if item["id"] == "automatic")
    receipt = fs.flow.receipts.record_download(
        project, item_id="automatic", source="Synthetic subset transport",
        request_url="https://example.invalid/subset", http_status=200, raw_files=[target],
        approval_sha256=fs.flow.approval.approval_id(fs.flow.approval.read(project)),
        inventory_item=item, plan_step_id="M:run")
    return {"status": "downloaded", "receipt": str(receipt), "path": str(target)}


def _mixed(tmp_path, monkeypatch, advance):
    """Approved subset+manual plan; ``advance(n)`` answers the n-th subset call (1 = approval)."""
    project, fs, ki, card = _review(tmp_path, monkeypatch, "subset", True)
    monkeypatch.setattr(obs_access, "Client", _Downloads)
    monkeypatch.setattr(flowrun, "ACQ_POLL_SECONDS", 0)
    calls = []

    def subset(project_, ident, client=None):
        calls.append(ident)
        outcome = advance(len(calls)) if len(calls) > 1 else "running"
        if isinstance(outcome, dict):
            return outcome
        return _subset_done(project, fs) if outcome == "done" else {"status": outcome, "receipt": None}

    monkeypatch.setattr(obs_subset, "advance_approved", subset)
    _approve(project, ki, card)
    card = setup_flow.request(project)
    assert card["id"] == acquire.MANUAL_REQUEST_ID
    return project, fs, ki, card, calls


def _place(card, data=b"date,flow\n2003-01-01,12\n"):
    destination = Path(card["rows"][0]["expected_path"])
    destination.mkdir(parents=True, exist_ok=True)
    placed = destination / "yearbook.csv"
    placed.write_bytes(data)
    return placed


def _continue(project, ki, card):
    return flowrun.pre(project, "Files are in place, continue", [ki.name], [ki],
                       {"request_id": card["id"], "option_id": "continue"}, card, setup_ok=True)


def _manual_receipt(project, fs):
    _, inventory = fs.flow.plan.read_artifacts(project)
    item = next(item for item in inventory["items"] if item["id"] == "manual")
    approval = fs.flow.approval.approval_id(fs.flow.approval.read(project))
    return fs.flow.receipts.find_download(project, item, approval_sha256=approval)


@pytest.mark.parametrize("retry_outcome", ["running", "done"])
def test_chat_continue_uses_the_flow_state_a_background_tick_just_wrote(
        tmp_path, monkeypatch, retry_outcome):
    def advance(n):
        if n == 2:      # the background tick hits a transient network failure
            raise obs_access.ObsAccessError("network_error", "temporary network failure")
        return retry_outcome
    project, fs, ki, card, _calls = _mixed(tmp_path, monkeypatch, advance)
    _place(card)
    real_lock = flowrun._acq_lock

    class TickFinishesFirst:
        # pre() has already loaded ACQUIRING. The tick holds the real lock, blocks
        # the project and only then lets the chat pass in.
        def __enter__(self):
            monkeypatch.setattr(flowrun, "_acq_lock", real_lock)
            assert flowrun.poll_acquisition(project, True, automatic_only=True) == "failed"
            real_lock(project).acquire()

        def __exit__(self, *_exc):
            real_lock(project).release()

    monkeypatch.setattr(flowrun, "_acq_lock", lambda _project: TickFinishesFirst())
    reply = _continue(project, ki, card)

    assert flowrun.current_state(project) == "BLOCKED", "a stale chat pass overwrote BLOCKED"
    blocked = setup_flow.request(project)
    assert blocked["id"] == flowrun.BLOCKED_REQUEST_ID
    assert reply.message and "could not be fetched" in reply.message
    flowrun.pre(project, "Retry the data acquisition.", [ki.name], [ki],
                {"request_id": blocked["id"], "option_id": "retry"}, blocked, setup_ok=True)
    assert flowrun.current_state(project) == ("EXECUTING" if retry_outcome == "done" else "ACQUIRING")


def test_change_plan_click_is_queued_during_a_background_pass_and_is_kept(tmp_path, monkeypatch):
    click = {}

    def advance(n):
        if n == 2:      # the tick holds the acquisition lock while the user clicks
            def change_plan():
                click["pre"] = flowrun.pre(
                    project, "Please change the plan: use station data", [ki.name], [ki],
                    {"request_id": acquire.MANUAL_REQUEST_ID, "option_id": "modify"}, card,
                    setup_ok=True)
            click["thread"] = threading.Thread(target=change_plan)
            click["thread"].start()
            click["thread"].join(0.3)
            click["waited"] = click["thread"].is_alive()
        return "running"
    project, fs, ki, card, _calls = _mixed(tmp_path, monkeypatch, advance)

    assert flowrun.poll_acquisition(project, True, automatic_only=True) == "replanning"
    click["thread"].join(5)

    assert flowrun.current_state(project) == "PLANNING", "the background pass overwrote Change the plan"
    assert fs.flow.approval.check(project) != "OK"
    assert not click["waited"], "Saving a change request must not wait for the transfer"
    assert click["pre"].message and not click["pre"].replan_reason
    assert setup_flow.request(project) is None


@pytest.mark.parametrize("writer", ["modify", "revoke"])
def test_background_pass_never_writes_back_a_flow_changed_while_it_ran(tmp_path, monkeypatch, writer):
    armed = {}

    def advance(n):
        if not armed:
            return "running"
        # A concurrent writer that does not take the acquisition lock.
        outcome = _subset_done(project, fs) if writer == "revoke" else "running"
        fs.flow.approval.revoke(project, "synthetic concurrent change")
        if writer == "modify":
            fs.flow.states.FlowContext.load(project).move("modify")
        return outcome
    project, fs, ki, card, _calls = _mixed(tmp_path, monkeypatch, advance)
    _place(card)
    assert _continue(project, ki, card).message          # manual receipted, subset still running
    armed["on"] = True

    flowrun.poll_acquisition(project, True, automatic_only=True)

    assert flowrun.current_state(project) == ("PLANNING" if writer == "modify" else "ACQUIRING")
    assert fs.flow.approval.check(project) != "OK"


@pytest.mark.parametrize("setup_ok", [True, False])
def test_background_completion_waits_for_the_user_to_start_the_run(tmp_path, monkeypatch, setup_ok):
    project, fs, ki, card, _calls = _mixed(tmp_path, monkeypatch, lambda n: "done" if n >= 3 else "running")
    _place(card)
    reply = _continue(project, ki, card)
    assert "every input has a receipt" in reply.message
    assert flowrun.current_state(project) == "ACQUIRING"

    # The KI software may still be unverified: acquisition runs before setup by design.
    assert flowrun.poll_acquisition(project, setup_ok, automatic_only=True) == "done"
    assert flowrun.current_state(project) == ("EXECUTING" if setup_ok else "SETUP_REQUIRED")
    progress = project_status.snapshot(project)["progress"]
    assert progress["ready_to_start"] is True
    assert (progress["status"], progress["next_actor"]) == ("waiting_for_user", "user")
    assert "Start the approved run" in progress["summary"]

    # The banner's button sends an ordinary chat message; pre()/turn() own the start.
    start = flowrun.pre(project, "Start the approved run.", [ki.name], [ki], None, None, setup_ok=setup_ok)
    assert start.gated and start.message is None
    assert flowrun.turn(project, [ki], _cfg(project), "api", "deepseek", None,
                        "Start the approved run.").kind == ("execution" if setup_ok else "setup")


@pytest.mark.parametrize("change", ["resaved", "replaced"])
def test_background_tick_never_signs_a_manual_file_the_user_has_not_handed_off(tmp_path, monkeypatch, change):
    finish = {}
    project, fs, ki, card, _calls = _mixed(tmp_path, monkeypatch,
                                           lambda n: "done" if finish else "running")
    placed = _place(card)
    _continue(project, ki, card)                           # the user handed off this file
    assert acquire.status(project)["items"]["manual"]["status"] == "done"
    assert setup_flow.request(project) is None

    if change == "replaced":                               # a new copy still in progress
        placed.unlink()
        placed = placed.with_name("yearbook-2004.csv")
    placed.write_bytes(b"date,flow\n2004-01-01,")
    finish["now"] = True
    assert flowrun.poll_acquisition(project, True, automatic_only=True) == "waiting"

    assert _manual_receipt(project, fs) is None, "a tick signed a file the user never handed off"
    items = acquire.status(project)["items"]
    assert (items["automatic"]["status"], items["manual"]["status"]) == ("done", "waiting")
    assert flowrun.current_state(project) == "ACQUIRING"
    reissued = setup_flow.request(project)
    assert reissued["id"] == acquire.MANUAL_REQUEST_ID and reissued["status"] == "waiting"
    assert reissued["rows"][0]["expected_path"] == card["rows"][0]["expected_path"]

    placed.write_bytes(b"date,flow\n2004-01-01,15\n")     # copy finished; the user confirms again
    assert _continue(project, ki, reissued).message is None
    assert _manual_receipt(project, fs) is not None
    assert flowrun.current_state(project) == "EXECUTING"


def test_background_tick_reissues_a_missing_manual_card_without_signing(tmp_path, monkeypatch):
    project, fs, ki, card, _calls = _mixed(tmp_path, monkeypatch, lambda n: "running")
    setup_flow.clear_request(project)                      # e.g. dismissed or replaced earlier
    _place(card, b"date,flow\n2003-01-01,")               # a copy still in progress

    assert flowrun.poll_acquisition(project, True, automatic_only=True) == "waiting"
    reissued = setup_flow.request(project)
    assert reissued and reissued["id"] == acquire.MANUAL_REQUEST_ID and reissued["status"] == "waiting"
    assert reissued["rows"][0]["expected_path"] == card["rows"][0]["expected_path"]
    assert _manual_receipt(project, fs) is None
    assert project_status.snapshot(project)["progress"]["next_actor"] == "host_and_user"

    request_path = project / setup_flow.REQUEST_FILE
    before = request_path.read_bytes()
    assert flowrun.poll_acquisition(project, True, automatic_only=True) == "waiting"
    assert request_path.read_bytes() == before, "an open card must not be rewritten"
