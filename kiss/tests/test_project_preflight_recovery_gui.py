"""The real chat controller leaves failed-check choices to the flow authority."""
from __future__ import annotations

import pytest

from kiss_cli import flowrun, gui, sessions, setup as setup_flow
from .test_project_preflight_recovery import failed_case  # noqa: F401


@pytest.mark.parametrize("provider", ["api:deepseek", "cli:claude", "cli:codex", "cli:kimi"])
@pytest.mark.parametrize("choice", [None, "revise", "retry"])
def test_chat_routes_recovery_choice_to_real_flow(failed_case, monkeypatch, provider, choice):
    c = failed_case
    workroot = c.project.parent / "chat-work"
    session = {"id": c.project.name.rsplit("--", 1)[1], "title": "Project recovery fixture",
               "project_named": True, "project_root": str(c.project),
               "provider": provider, "models": [c.ki.name], "messages": []}
    sessions.save(workroot, session)
    assert sessions.project_path(workroot, session) == c.project
    handler = object.__new__(gui.Handler)
    handler.workroot, handler.catalog = workroot, [c.ki]
    handler._ki = lambda name: c.ki
    handler._workdir = lambda ki: c.project.parent / "unused-shared-setup"
    handler._open_stream = handler._end_stream = lambda: None
    pieces, handoffs = [], []
    handler._chunk = lambda piece: pieces.append(piece) or True
    # The controller's pre-turn readiness query is read-only. This fixture is
    # deliberately not ready; real recovery and approval/state checks still run.
    monkeypatch.setattr(gui.Handler, "_project_setup_ok", lambda *_: False)
    monkeypatch.setattr(gui.calibration, "ensure_project", lambda *_: None)
    monkeypatch.setattr(setup_flow, "resume", lambda *_a, **_k: pytest.fail("flow card must not be generically answered"))

    def handoff(*_args, flow_pre=None, **_kwargs):
        handoffs.append((flow_pre, flowrun.current_state(c.project)))
        return None

    handler._chat_with_models = handoff
    pending = setup_flow.request(c.project)
    before = (c.project / setup_flow.REQUEST_FILE).read_bytes()
    request = {"message": "Inspect the missing data and explain the next step"}
    if choice:
        request["action"] = {"request_id": pending["id"], "option_id": choice,
                             "note": "Investigate the missing reference data"}
    try:
        handler._stream_session_chat(session["id"], request)
    finally:
        gui._LIVE_AGENT_RUNS.pop(session["id"], None)

    if choice is None:
        assert handoffs == []
        assert (c.project / setup_flow.REQUEST_FILE).read_bytes() == before
        assert "Review and revise plan" in "".join(pieces)
        assert c.flow.approval.check(c.project) == "OK"
    else:
        assert len(handoffs) == 1
        pre, state = handoffs[0]
        assert pre.message is None
        if choice == "revise":
            assert state == "REPLAN_REQUIRED" and pre.replan_reason
            assert c.flow.approval.check(c.project) != "OK"
        else:
            assert state == "SETUP_REQUIRED" and not pre.replan_reason
            assert c.flow.approval.check(c.project) == "OK"
