"""Inspection is a host capability, not an implicit setup/replanning request.

Synthetic project/provider fixtures only; no scientific model or CLI is run.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from kiss_cli import api, execution, flowgate, flowrun, gui, ki_guard, paths, sessions, setup as setup_flow
from .test_execution_context import _handler
from .test_readonly_followup import phase  # noqa: F401


def _deny(label):
    def denied(*_args, **_kwargs):
        pytest.fail(f"inspection called {label}")
    return denied


def _protected(project):
    """Conversation history may grow; science/lifecycle documents may not."""
    return {p.relative_to(project).as_posix(): p.read_bytes()
            for p in project.rglob("*") if p.is_file()
            and p.relative_to(project).parts[0] != "memory"
            and p.name not in {"session.json", "session.tmp"}}


def _retained(project, ki):
    live = project / "models" / ki.name / "ki"
    shutil.copytree(ki.root, live)
    ki_guard.enroll(live)
    # A loader which tries to repair Windows TOML will change these bytes.
    (project / "kiss.toml").write_bytes(b'[kiss]\nroot = "C:\\unescaped\\project"\n')
    (live.parent / "kiss.toml").write_bytes(b'broken model config = [\n')
    (project / "status.json").write_text('{"can_run":false,"reason":"source changed"}')
    for name in ("project-run.json", "project-agent-status.json"):
        (project / name).write_text('{"status":"complete","summary":"retained"}')
    (project / setup_flow.REQUEST_FILE).write_text(json.dumps({
        "id": "keep-pending", "status": "waiting", "kind": "other",
        "message": "Do not consume this unanswered setup request"}))
    return live


def _inspection_handler(project, ki, monkeypatch, provider):
    capture = {}
    handler = _handler(SimpleNamespace(project=project, ki=ki,
                                      cfg=paths.KissConfig.default(project)),
                       monkeypatch, provider, capture)
    handler._status_for = _deny("shared software status")
    handler._software_status_prompt = _deny("software status prompt")
    handler._session_workspaces = _deny("runtime materialisation")
    handler._prepare_setup_workspace = _deny("setup preparation")
    handler._manifest = _deny("installation manifest")
    handler._workdir = lambda _ki: project.parent / "must-not-create-shared-setup"
    monkeypatch.setattr(gui.Handler, "_project_setup_ok", _deny("project readiness"))
    monkeypatch.setattr(gui.Handler, "_verify_project_preflight", _deny("project preflight"))
    monkeypatch.setattr(gui.ki_investigation, "pending_preflight", _deny("repair preflight"))
    monkeypatch.setattr(paths.KissConfig, "load", _deny("saved config loader"))

    def read_api(_provider, runtime_ki, cfg, system, task, **kw):
        fs = kw["flow"]
        capture.update(kind="api", flow=fs, cfg=cfg, ki=runtime_ki, prompt=system)
        assert fs.readonly and not kw["setup_mode"]
        assert fs.api_tools() <= flowgate.READONLY_API_TOOLS
        # Exercise the real read tool, not only schema inspection.
        read = api.execute_tool("read_project_file", {"path": "runs/plan.json"},
            runtime_ki, cfg, project_mode=True, flow=fs,
            setup_context={"project_root": project})
        assert "goal" in str(read)
        for name in ("request_replan", "run_preflight", "run_ki_tool", "write_plan",
                     "run_setup_command", "fetch_data"):
            with pytest.raises(api.ToolError, match="read-only"):
                api.execute_tool(name, {}, runtime_ki, cfg, project_mode=True, flow=fs)
        yield "Existing artifacts inspected; runtime readiness was not renewed."

    def read_cli(_provider, **kw):
        capture.update(kind="cli", **kw)
        assert kw["flow_policy"].state.value == "COMPLETED"
        assert kw["flow_policy"].argv_extra[-2:] == ["--tools", "Read,Glob,Grep"]
        assert "Bash(" not in str(kw["flow_policy"].argv_delta)
        return {"returncode": 0}

    monkeypatch.setattr(api, "run", read_api)
    handler._cli_turn = read_cli
    return handler, capture


@pytest.mark.parametrize("provider", ["api", "cli"])
@pytest.mark.parametrize("state", ["COMPLETED", "WAITING_FOR_USER", "EXECUTING", "SETUP_RUNNING", "FAILED"])
def test_inspection_never_enters_stale_setup_or_changes_retained_documents(phase, monkeypatch, provider, state):
    project, fs, ki = phase
    fs.ctx.state = fs.flow.states.State(state)
    fs.ctx.save()
    live = _retained(project, ki)
    if state == "WAITING_FOR_USER":
        (project / setup_flow.REQUEST_FILE).write_text(json.dumps({
            "id": flowrun.APPROVAL_REQUEST_ID_PREFIX + "fixture", "status": "waiting", "kind": "choice"}))
    handler, capture = _inspection_handler(project, ki, monkeypatch, provider)
    baseline = _protected(project)
    action = None if state in {"COMPLETED", "WAITING_FOR_USER"} else {"kind": flowrun.INSPECT_ACTION}
    pre = flowrun.pre(project, "Explain existing results", [ki.name], [ki], action,
                      setup_flow.request(project, archive_obsolete=False), setup_ok=False)
    assert pre.readonly and not pre.replan_reason
    turn = gui.Handler._chat_with_models(handler, [ki.name],
        "api:deepseek" if provider == "api" else "cli:claude", "Explain existing results",
        lambda _text: True, project, bare_task="Explain existing results", flow_pre=pre)
    assert turn.kind == "readonly" and turn.session.state.value == state
    assert turn.session.ki_roots[ki.name] == live
    assert capture["cfg"].root == project
    assert "READ-ONLY PROJECT" in capture.get("prompt", capture.get("replay_prompt", ""))
    result = flowrun.after(project, turn, "Existing artifacts inspected")
    assert not result.continue_now and not result.retry_planning and not result.request
    assert _protected(project) == baseline
    assert not (project.parent / "must-not-create-shared-setup").exists()


@pytest.mark.parametrize("state", ["COMPLETED", "EXECUTING", "SETUP_RUNNING", "FAILED", "ACQUIRING"])
def test_inspection_precedes_recovery_acquisition_and_review(phase, monkeypatch, state):
    project, fs, ki = phase
    fs.ctx.state = fs.flow.states.State(state)
    fs.ctx.save()
    for name in ("_project_preflight_recovery", "_take_acquisition_replan", "_uncertain_acquisition_replan"):
        monkeypatch.setattr(flowrun, name, _deny(name))
    monkeypatch.setattr(flowrun.plan_review, "respond", _deny("plan approval handling"))
    before = _protected(project)
    action = None if state == "COMPLETED" else {"kind": flowrun.INSPECT_ACTION}
    result = flowrun.pre(project, "inspect", [ki.name], [ki], action, None, setup_ok=False)
    assert result.readonly and result.message is None
    assert _protected(project) == before


def test_malformed_inspection_action_never_consumes_pending_choice(phase, monkeypatch):
    project, _, ki = phase
    monkeypatch.setattr(flowrun.plan_review, "respond", _deny("plan approval handling"))
    before = _protected(project)
    result = flowrun.pre(project, "inspect", [ki.name], [ki],
        {"kind": flowrun.INSPECT_ACTION, "option_id": "approve"}, {"id": "pending"})
    assert result.readonly and result.message and not result.replan_reason
    assert _protected(project) == before


@pytest.mark.parametrize("provider", ["claude", "codex"])
def test_explicit_inspection_cli_policy_cannot_inherit_running_or_changed_state(phase, provider):
    project, fs, ki = phase
    fs.ctx.state = fs.flow.states.State.EXECUTING
    fs.ctx.save()
    turn = flowrun.readonly_turn(project, [ki], paths.KissConfig.default(project), "cli", provider)
    for state in (fs.flow.states.State.SETUP_RUNNING, fs.flow.states.State.REPLAN_REQUIRED):
        turn.session.ctx.state = state
        policy = flowrun.policy_for_cli(turn, provider, None)
        assert policy.state.value == "COMPLETED"
        if provider == "codex":
            assert policy.argv_delta == ["--sandbox", "read-only"]
        else:
            assert policy.argv_extra[-1] == "Read,Glob,Grep"
        assert not turn.wrappers and not turn.session.write_allowed(project / "runs/plan.json")


def test_ordinary_execution_still_refuses_stale_project_before_provider(phase, monkeypatch):
    project, fs, ki = phase
    fs.ctx.state = fs.flow.states.State.EXECUTING
    fs.ctx.save()
    capture = {}
    handler = _handler(SimpleNamespace(project=project, ki=ki,
        cfg=paths.KissConfig.default(project)), monkeypatch, "api", capture)
    monkeypatch.setattr(gui.Handler, "_project_setup_ok", lambda *_: False)
    monkeypatch.setattr(api, "run", _deny("provider before stale execution refusal"))
    calls, pieces = [], []
    monkeypatch.setattr(flowrun, "project_setup_failed", lambda *_a, **_k: calls.append(True))
    turn = gui.Handler._chat_with_models(handler, [ki.name], "api:deepseek", "Continue execution",
        lambda piece: pieces.append(piece) or True, project, flow_pre=flowrun.Pre(names=[ki.name]))
    assert turn is None and calls == [True]
    assert "verification is missing or stale" in "".join(pieces)


@pytest.mark.parametrize("state,explicit", [("COMPLETED", False), ("EXECUTING", True)])
@pytest.mark.parametrize("provider", ["api", "cli"])
def test_real_chat_controller_keeps_inspection_out_of_mutating_bookkeeping(phase, monkeypatch, state, explicit, provider):
    old_project, _, ki = phase
    workroot = old_project.parent / "chat-work"
    session = sessions.create(workroot, [ki.name], "api:deepseek" if provider == "api" else "cli:claude",
                              project_parent=old_project.parent / "projects")
    project = sessions.project_path(workroot, session)
    shutil.copytree(old_project / "runs", project / "runs", dirs_exist_ok=True)
    flow = flowgate.load()
    flow.approval.approve(project, by="user")
    ctx = flow.states.FlowContext(project=project)
    ctx.selected_kis = [ki.name]
    ctx.state = flow.states.State(state)
    ctx.save()
    session.update(title="Inspection fixture", project_named=True)
    sessions.save(workroot, session)
    _retained(project, ki)
    mock, capture = _inspection_handler(project, ki, monkeypatch, provider)
    handler = object.__new__(gui.Handler)
    handler.__dict__.update(mock.__dict__)
    handler.workroot, handler.catalog = workroot, [ki]
    pieces = []
    handler._open_stream = handler._end_stream = lambda: None
    handler._chunk = lambda text: pieces.append(text) or True
    handler._json = lambda payload, status=200: pytest.fail(f"unexpected HTTP {status}: {payload}")
    monkeypatch.setattr(gui, "_reconcile_ki_repair", _deny("KI handoff reconciliation"))
    monkeypatch.setattr(gui.projectrun, "begin_turn", _deny("project status begin"))
    monkeypatch.setattr(gui.projectrun, "finish_turn", _deny("project status finish"))
    monkeypatch.setattr(gui.calibration, "ensure_project", _deny("calibration materialisation"))
    monkeypatch.setattr(setup_flow, "resume", _deny("pending request consumption"))
    original_request = setup_flow.request
    def request(root, *, archive_obsolete=True):
        assert not archive_obsolete, "inspection used a mutating request reader"
        return original_request(root, archive_obsolete=False)
    monkeypatch.setattr(setup_flow, "request", request)
    baseline = _protected(project)
    req = {"message": "Read the existing logs; explain their evidence."}
    if explicit:
        req["action"] = {"kind": flowrun.INSPECT_ACTION}
    try:
        handler._stream_session_chat(session["id"], req)
    finally:
        gui._LIVE_AGENT_RUNS.pop(session["id"], None)
    assert capture, "provider inspection was not reached"
    assert not any("could not" in piece.lower() for piece in pieces)
    assert _protected(project) == baseline


def test_explicit_inspection_without_selected_ki_does_not_promote_auto_intake(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(flowrun.plan_review, "respond", _deny("automatic plan handling"))
    before = _protected(project)
    result = flowrun.pre(project, "Inspect existing files", [], [], {"kind": flowrun.INSPECT_ACTION}, None)
    assert result.readonly and result.message and not result.names and not result.replan_reason
    assert _protected(project) == before


def test_prior_execution_stop_does_not_block_inspection_but_current_handle_stop_does(phase):
    project, _, ki = phase
    old_turn = execution.begin_turn(project)
    execution.request_stop(project)
    baseline = _protected(project)
    turn = flowrun.readonly_turn(project, [ki], paths.KissConfig.default(project), "api", "deepseek")
    handle = api.TurnHandle()
    context = {"project_root": project, "_turn_id": "new-inspection-turn", "_handle": handle}
    page = api.execute_tool("read_project_file", {"path": "runs/plan.json"}, ki,
        paths.KissConfig.default(project), project_mode=True, flow=turn.session, setup_context=context)
    assert "goal" in str(page)
    assert execution.current_turn_id(project) == old_turn
    assert _protected(project) == baseline
    handle.stop()
    with pytest.raises(api.ToolError, match="Stopped by the user"):
        api.execute_tool("read_project_file", {"path": "runs/plan.json"}, ki,
            paths.KissConfig.default(project), project_mode=True, flow=turn.session, setup_context=context)
    assert _protected(project) == baseline


def test_stopping_inspection_keeps_execution_stop_and_generation_unchanged(phase, monkeypatch):
    project, _, _ = phase
    execution.begin_turn(project)
    execution.request_stop(project)
    before = _protected(project)
    handle = api.TurnHandle()
    sid = "012345abcdef"
    monkeypatch.setattr(execution, "request_stop", _deny("persistent execution Stop marker"))
    gui._LIVE_AGENT_RUNS[sid] = {"project": str(project), "readonly": True, "_handle": handle}
    try:
        assert gui._stop_agent_run(sid) == {"ok": True, "stopped": True}
    finally:
        gui._LIVE_AGENT_RUNS.pop(sid, None)
    assert handle.stopped.is_set() and _protected(project) == before


def test_waiting_question_and_explicit_answer_keep_existing_answer_route(phase):
    project, fs, _ = phase
    fs.ctx.state = fs.flow.states.State.WAITING_FOR_USER
    fs.ctx.save()
    question = {"id": "planning-question", "kind": "choice", "status": "waiting",
                "options": [{"id": "one", "label": "One", "response": "Use one"}]}
    (project / setup_flow.REQUEST_FILE).write_text(json.dumps(question))
    before = _protected(project)
    answer = {"request_id": question["id"], "option_id": "one"}
    assert not flowrun.inspection_requested(project)
    assert not flowrun.inspection_requested(project, answer)
    assert setup_flow.choice_response(setup_flow.request(project, archive_obsolete=False), answer)["id"] == "one"
    assert flowrun.inspection_requested(project, {"kind": flowrun.INSPECT_ACTION})
    assert _protected(project) == before
