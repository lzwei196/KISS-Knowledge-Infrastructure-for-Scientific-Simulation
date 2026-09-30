"""The browser's acquisition tick advances transport, not manual consent or a model.

Real HTTP handler/Flow/acquisition paths, in-memory HTTP transport, and synthetic
downloads in isolated projects. No socket, provider, real catalogue or user data.
"""
from __future__ import annotations

import io
from pathlib import Path

import pytest

from kiss_cli import acquire, flowrun, gui, obs_access, obs_subset, sessions, setup as setup_flow
from .test_acquisition_mixed_delivery import _Downloads, _approve, _continue, _place, _review, _subset_done


SID = "123456abcdef"
COOKIE = "synthetic-acquisition-test-cookie"


@pytest.fixture(autouse=True)
def isolated_host(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    monkeypatch.setenv("GEOFORGE_FLOW_REGISTRY", str(tmp_path / "registry.json"))
    monkeypatch.setattr(gui.settings, "load", lambda: {})
    monkeypatch.setattr(flowrun, "ACQ_POLL_SECONDS", 0)


def _handler(monkeypatch, project, *, sid=SID, headers=None):
    handler = object.__new__(gui.Handler)
    handler.workroot = project.parent / "app"
    handler.path = f"/api/session/{sid}/acquire"
    handler.headers = {
        "Content-Length": "2", "Content-Type": "application/json",
        "Host": "127.0.0.1:8877", "Origin": "http://127.0.0.1:8877",
        "Sec-Fetch-Site": "same-origin", "Cookie": f"geoforge_csrf={COOKIE}",
    }
    if headers:
        handler.headers.update(headers)
    handler.csrf_token = COOKIE
    handler.rfile = io.BytesIO(b"{}")
    responses = []
    handler._json = lambda body, code=200: responses.append((body, code))
    handler._setup_ok_for = lambda _session: True
    handler._stream_session_chat = lambda *_a, **_k: pytest.fail("a download tick must not invoke an agent")
    monkeypatch.setattr(sessions, "load", lambda _root, ident:
                        {"id": SID, "models": ["M"]} if ident == SID else None)
    monkeypatch.setattr(sessions, "project_path", lambda _root, _session: project)
    return handler, responses


def _request(monkeypatch, project, **kwargs):
    handler, responses = _handler(monkeypatch, project, **kwargs)
    handler.do_POST()
    assert len(responses) == 1
    return responses[0]


def _subset_pending(tmp_path, monkeypatch, *, finish=True):
    project, fs, ki, card = _review(tmp_path, monkeypatch, "subset", True)
    downloads, advances = _Downloads(), []
    monkeypatch.setattr(obs_access, "Client", lambda: downloads)

    def advance(project, ident, client=None):
        advances.append(ident)
        if not finish or len(advances) == 1:
            return {"status": "running", "receipt": None}
        target = project / "inputs" / "subset-fixture.dat"
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
    assert advances == ["a" * 32]
    assert acquire.status(project)["items"]["automatic"]["status"] == "pending"
    return project, fs, ki, downloads, advances


def _manual_receipt(project, fs):
    _, inventory = fs.flow.plan.read_artifacts(project)
    item = next(item for item in inventory["items"] if item["id"] == "manual")
    approval = fs.flow.approval.approval_id(fs.flow.approval.read(project))
    return fs.flow.receipts.find_download(project, item, approval_sha256=approval)


def test_background_request_completes_subset_but_never_receipts_an_unfinished_manual_copy(
        tmp_path, monkeypatch):
    project, fs, ki, downloads, advances = _subset_pending(tmp_path, monkeypatch)
    request_path = project / setup_flow.REQUEST_FILE
    original_card = request_path.read_bytes()
    card = setup_flow.request(project)
    destination = Path(card["rows"][0]["expected_path"])
    destination.mkdir(parents=True)
    # A file copying under its final name passes simple presence checks. Only
    # explicit user continuation, not the background tick, can acknowledge it.
    manual_file = destination / "yearbook.csv"
    manual_file.write_bytes(b"date,flow\n2003-01-01,")
    before = manual_file.read_bytes()

    body, status = _request(monkeypatch, project)

    assert status == 200
    assert _manual_receipt(project, fs) is None, "A background tick must not sign a copy still in progress"
    assert body["advanced"] == "waiting"
    assert advances == ["a" * 32, "a" * 32]
    state = acquire.status(project)
    assert state["items"]["automatic"]["status"] == "done"
    assert Path(state["items"]["automatic"]["receipt"]).is_file()
    assert state["items"]["manual"]["status"] == "waiting"
    assert request_path.read_bytes() == original_card
    assert manual_file.read_bytes() == before
    assert downloads.calls == ["manual-yearbook"]
    assert flowrun.current_state(project) == "ACQUIRING"
    assert not (project / ".geoforge" / "receipts" / "model-runs").exists()

    # A later explicit handoff remains compatible with the existing workflow.
    manual_file.write_bytes(b"date,flow\n2003-01-01,12\n")
    result = flowrun.pre(
        project, "Files are in place, continue", [ki.name], [ki],
        {"request_id": card["id"], "option_id": "continue"}, card, setup_ok=True)
    assert result.message is None
    assert _manual_receipt(project, fs) is not None
    assert acquire.status(project)["items"]["manual"]["status"] == "done"
    assert setup_flow.request(project) is None
    assert flowrun.current_state(project) == "EXECUTING"
    assert not (project / ".geoforge" / "receipts" / "model-runs").exists()


@pytest.mark.parametrize("headers", [
    {"Cookie": ""}, {"Cookie": "geoforge_csrf=wrong"},
    {"Origin": "https://evil.example"}, {"Sec-Fetch-Site": "cross-site"},
])
def test_acquire_rejects_unsafe_browser_requests_before_any_flow_or_transport(
        tmp_path, monkeypatch, headers):
    project = tmp_path / "project"
    monkeypatch.setattr(flowrun, "poll_acquisition", lambda *_a, **_k: pytest.fail("unsafe request polled"))
    monkeypatch.setattr(gui.project_status, "snapshot", lambda *_a, **_k: pytest.fail("unsafe request read project"))
    body, status = _request(monkeypatch, project, headers=headers)
    assert status == 403 and "blocked unsafe" in body["error"]
    assert not project.exists()


@pytest.mark.parametrize("sid,status", [("invalid", 400), ("abcdef123456", 404)])
def test_acquire_rejects_invalid_or_missing_session(tmp_path, monkeypatch, sid, status):
    project = tmp_path / "project"
    monkeypatch.setattr(flowrun, "poll_acquisition", lambda *_a, **_k: pytest.fail("missing session polled"))
    body, actual = _request(monkeypatch, project, sid=sid)
    assert actual == status and body.get("error")
    assert not project.exists()


@pytest.mark.parametrize("approval", ["not_yet_approved", "revoked"])
def test_acquire_needs_current_approved_acquisition(tmp_path, monkeypatch, approval):
    if approval == "revoked":
        project, fs, _ki, _downloads, advances = _subset_pending(tmp_path, monkeypatch)
        fs.flow.approval.revoke(project, "Synthetic revocation")
    else:
        project, fs, _ki, _card = _review(tmp_path, monkeypatch, "subset", True)
        advances = []
    before = flowrun.current_state(project)
    monkeypatch.setattr(flowrun, "poll_acquisition", lambda *_a, **_k: pytest.fail("unapproved project polled"))
    body, status = _request(monkeypatch, project)
    assert status == 200 and body["advanced"] is None
    assert flowrun.current_state(project) == before
    assert len(advances) == (1 if approval == "revoked" else 0)


def test_manual_only_wait_does_not_poll_or_adopt_files(tmp_path, monkeypatch):
    project, fs, ki, card = _review(tmp_path, monkeypatch, "served", True)
    monkeypatch.setattr(obs_access, "Client", _Downloads)
    _approve(project, ki, card)
    card = setup_flow.request(project)
    dest = Path(card["rows"][0]["expected_path"])
    dest.mkdir(parents=True)
    (dest / "copying.csv").write_bytes(b"incomplete")
    monkeypatch.setattr(flowrun, "poll_acquisition", lambda *_a, **_k: pytest.fail("only manual work remains"))
    body, status = _request(monkeypatch, project)
    assert status == 200 and body["advanced"] is None
    assert _manual_receipt(project, fs) is None
    assert setup_flow.request(project)["id"] == acquire.MANUAL_REQUEST_ID


def test_duplicate_requests_obey_core_rate_limit(tmp_path, monkeypatch):
    project, _fs, _ki, _downloads, advances = _subset_pending(tmp_path, monkeypatch, finish=False)
    monkeypatch.setattr(flowrun, "ACQ_POLL_SECONDS", 30)
    monkeypatch.setattr(flowrun.time, "time", lambda: 2000000000.0)
    first, first_status = _request(monkeypatch, project)
    second, second_status = _request(monkeypatch, project)
    assert first_status == second_status == 200
    assert first["advanced"] == "waiting" and second["advanced"] is None
    assert advances == ["a" * 32, "a" * 32]


def test_request_does_not_overlap_a_chat_driven_acquisition_pass(tmp_path, monkeypatch):
    project, _fs, _ki, _downloads, advances = _subset_pending(tmp_path, monkeypatch, finish=False)
    lock = flowrun._acq_lock(project)
    with lock:
        body, status = _request(monkeypatch, project)
    assert status == 200 and body["advanced"] is None
    assert advances == ["a" * 32]
    body, status = _request(monkeypatch, project)
    assert status == 200 and body["advanced"] == "waiting"
    assert advances == ["a" * 32, "a" * 32]


def test_status_get_observes_pending_acquisition_without_advancing_it(tmp_path, monkeypatch):
    project, _fs, _ki, _downloads, advances = _subset_pending(tmp_path, monkeypatch)
    handler, responses = _handler(monkeypatch, project)
    handler.path = f"/api/session/{SID}/run"
    monkeypatch.setattr(gui, "_agent_run_snapshot", lambda _sid: {})
    monkeypatch.setattr(flowrun, "poll_acquisition", lambda *_a, **_k: pytest.fail("status GET is read-only"))
    handler.do_GET()
    assert len(responses) == 1 and responses[0][1] == 200
    assert advances == ["a" * 32]
    assert acquire.status(project)["items"]["automatic"]["status"] == "pending"


def test_rate_limited_tick_reads_project_status_once(tmp_path, monkeypatch):
    project, _fs, _ki, _downloads, advances = _subset_pending(tmp_path, monkeypatch, finish=False)
    monkeypatch.setattr(flowrun, "ACQ_POLL_SECONDS", 30)
    monkeypatch.setattr(flowrun.time, "time", lambda: 2000000000.0)
    real, reads = gui.project_status.snapshot, []
    monkeypatch.setattr(gui.project_status, "snapshot", lambda *a, **k: reads.append(a) or real(*a, **k))
    first, _status = _request(monkeypatch, project)
    assert first["advanced"] == "waiting" and len(reads) == 2
    second, _status = _request(monkeypatch, project)
    assert second["advanced"] is None
    assert len(reads) == 3, "a tick that ran no pass must reuse its first status read"


@pytest.mark.parametrize("turn,setup_ok", [("idle", True), ("running", True), ("idle", False)])
def test_tick_that_finishes_acquisition_asks_the_user_to_start_the_run(tmp_path, monkeypatch, turn, setup_ok):
    project, fs, ki, _downloads, _advances = _subset_pending(tmp_path, monkeypatch, finish=False)
    card = setup_flow.request(project)
    _place(card)
    _continue(project, ki, card)                    # manual handed off, subset still running
    monkeypatch.setattr(obs_subset, "advance_approved", lambda _p, _ident, client=None: _subset_done(project, fs))
    monkeypatch.setattr(gui, "_agent_run_snapshot", lambda _sid: {"state": turn, "process_alive": turn == "running"})
    handler, responses = _handler(monkeypatch, project)
    handler._setup_ok_for = lambda _s: setup_ok     # unverified KI software: normal before first use

    handler.do_POST()

    body, status = responses[0]
    assert status == 200 and body["advanced"] == "done"
    run = body["run"]
    assert run["flow_state"] == ("EXECUTING" if setup_ok else "SETUP_REQUIRED")
    assert run["ready_to_start"] is (turn == "idle")
    assert run["next_actor"] == ("user" if turn == "idle" else "agent")
    if not setup_ok:
        assert "set up" in run["summary"] and "Start the approved run" in run["summary"]
    assert not (project / ".geoforge" / "receipts" / "model-runs").exists()


def test_project_panel_poll_never_receipts_an_unfinished_manual_copy(tmp_path, monkeypatch):
    project, fs, _ki, _downloads, advances = _subset_pending(tmp_path, monkeypatch, finish=False)
    _place(setup_flow.request(project), b"PK\x03\x04 half copied")
    handler, _responses = _handler(monkeypatch, project)

    class StopAfterPoll(Exception):
        pass

    def missing_ki(name):
        raise KeyError(name)

    def stop(*_a, **_k):
        raise StopAfterPoll

    handler._ki = missing_ki
    monkeypatch.setattr(sessions, "input_files", stop)
    with pytest.raises(StopAfterPoll):
        handler._session_data({"id": SID, "models": ["M"]})

    assert advances == ["a" * 32, "a" * 32], "the panel poll must still advance automatic data"
    assert _manual_receipt(project, fs) is None, "the panel poll signed a copy still in progress"
    assert acquire.status(project)["items"]["manual"]["status"] == "waiting"
