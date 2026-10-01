"""A chat turn reaches its end, and its outcome reaches the user.

- A reloaded or closed browser tab must not end the turn. On Windows a write to
  a tab that has gone raises ConnectionAbortedError (WinError 10053), which the
  stream writer did not catch: the turn failed with "GeoForge could not finish
  this turn" while the agent kept working unseen.
- The run that starts right after a successful setup must report the Flow
  verdict ("Completed." / "GeoForge verification: not complete yet …").
- Archiving a chat whose folder Windows will not move says why.
"""
from __future__ import annotations

import io
from types import SimpleNamespace

import pytest

from kiss_cli import api, flowrun, gui, sessions


class _GoneAfter:
    """A socket file that accepts ``n`` writes, then raises like a closed tab."""

    def __init__(self, n: int, error: type[BaseException]):
        self.n, self.error, self.data = n, error, b""

    def write(self, data: bytes) -> None:
        if self.n <= 0:
            raise self.error(10053, "connection aborted")
        self.n -= 1
        self.data += data

    def flush(self) -> None:
        pass


@pytest.mark.parametrize("error", [ConnectionAbortedError, ConnectionResetError, BrokenPipeError])
def test_a_write_to_a_gone_browser_reports_it_instead_of_raising(error):
    handler = object.__new__(gui.Handler)
    handler.wfile = _GoneAfter(1, error)
    assert handler._chunk("first") is True
    assert handler._chunk("second") is False
    handler._end_stream()                                   # no raise either


def test_the_turn_runs_to_the_end_and_saves_the_whole_reply_after_a_reload(tmp_path, monkeypatch):
    workroot = tmp_path / "work"
    session = sessions.create(workroot, [], "api:deepseek", project_parent=tmp_path / "projects")
    handler = object.__new__(gui.Handler)
    handler.workroot, handler.catalog = workroot, SimpleNamespace(get=lambda name: {}[name])
    handler._open_stream = lambda: None
    handler.wfile = _GoneAfter(1, ConnectionAbortedError)    # the tab reloads after one piece
    monkeypatch.setattr(flowrun, "pre", lambda *_a, **_k: flowrun.Pre(names=[]))
    accepted = []

    def agent(_want, _task, out, *_a, **_k):
        for piece in ("Reading the case. ", "Running FSM2. ", "Peak SWE 312 mm."):
            accepted.append(out(piece))

    handler._chat_auto = agent
    try:
        handler._stream_session_chat(session["id"], {"message": "run the Alptal example"})
        live = gui._LIVE_AGENT_RUNS[session["id"]]
        assert live.get("browser_detached_at") and live.get("finished_at")
    finally:
        gui._LIVE_AGENT_RUNS.pop(session["id"], None)
    assert accepted == [True, True, True], "the agent was told to stop when the tab went away"
    saved = sessions.load(workroot, session["id"])["messages"][-1]
    assert saved["role"] == "assistant"
    text = sessions.message_text(saved)
    assert "Peak SWE 312 mm." in text and "could not finish" not in text


def test_stop_still_ends_a_turn_whose_browser_has_gone(tmp_path, monkeypatch):
    workroot = tmp_path / "work"
    session = sessions.create(workroot, [], "api:deepseek", project_parent=tmp_path / "projects")
    handler = object.__new__(gui.Handler)
    handler.workroot, handler.catalog = workroot, SimpleNamespace(get=lambda name: {}[name])
    handler._open_stream = lambda: None
    handler.wfile = _GoneAfter(0, ConnectionAbortedError)
    monkeypatch.setattr(flowrun, "pre", lambda *_a, **_k: flowrun.Pre(names=[]))
    handles: list[api.TurnHandle] = []
    handler._chat_auto = lambda *_a, runtime_events=None, **_k: handles.append(runtime_events["_handle"])
    try:
        handler._stream_session_chat(session["id"], {"message": "go"})
        assert gui._stop_agent_run(session["id"])["reason"] == "no live turn"
    finally:
        gui._LIVE_AGENT_RUNS.pop(session["id"], None)
    assert handles and not handles[0].stopped.is_set()


def test_archiving_a_chat_whose_folder_is_in_use_says_so(tmp_path, monkeypatch):
    # Windows refuses to move a folder while another program has a file in it open.
    session = sessions.create(tmp_path)
    responses = []
    handler = object.__new__(gui.Handler)
    handler.workroot = tmp_path
    handler.path = f"/api/session/{session['id']}/delete"
    handler.headers = {"Content-Length": "2"}
    handler.rfile = io.BytesIO(b"{}")
    handler._browser_write_allowed = lambda: (True, "")
    handler._json = lambda payload, status=200: responses.append((payload, status))

    def in_use(*_a, **_k):
        raise PermissionError(32, "The process cannot access the file because it is being used by another process")

    monkeypatch.setattr(sessions, "delete", in_use)
    handler.do_POST()
    (payload, status), = responses
    assert status == 409 and payload["ok"] is False
    assert "open in another program" in payload["error"]


def test_the_run_after_setup_reports_the_flow_verdict_in_the_chat(tmp_path, monkeypatch):
    # Approve -> setup verified -> execution starts in the same request. The
    # execution turn's verdict must reach the chat like any other turn's.
    workroot = tmp_path / "work"
    session = sessions.create(workroot, ["FSM2"], "api:deepseek", project_parent=tmp_path / "projects")
    handler = object.__new__(gui.Handler)
    handler.workroot, handler.catalog = workroot, SimpleNamespace(get=lambda name: {}[name])
    handler._open_stream = lambda: None
    handler._chunk = lambda _text: True
    handler._end_stream = lambda: None
    monkeypatch.setattr(flowrun, "pre", lambda *_a, **_k: flowrun.Pre(names=["FSM2"]))
    monkeypatch.setattr(flowrun, "describe_policy", lambda *_a: "")
    monkeypatch.setattr(flowrun, "current_state", lambda *_a: "EXECUTING")
    verdicts = iter([
        flowrun.Result(continue_now=True),                                   # setup turn: verified
        flowrun.Result(message="**GeoForge verification:** not complete yet — regenerate or remove them: `x.csv`."),
    ])
    monkeypatch.setattr(flowrun, "after", lambda *_a, **_k: next(verdicts))

    def turn(names, want, task, out, *_a, **_k):
        out("agent work. ")
        return SimpleNamespace(kind="execution", provider_succeeded=True)

    handler._chat_with_models = turn
    try:
        handler._stream_session_chat(session["id"], {"message": "Approve and start"})
    finally:
        gui._LIVE_AGENT_RUNS.pop(session["id"], None)
    text = sessions.message_text(sessions.load(workroot, session["id"])["messages"][-1])
    assert flowrun.RUN_AFTER_SETUP in text
    assert "GeoForge verification:** not complete yet" in text
