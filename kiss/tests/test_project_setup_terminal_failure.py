"""Post-agent host checks end setup truthfully for both provider paths.

Provider/installer execution is doubled. Repaired-KI failure runs the real
harmless native project preflight and writes its signed failure receipt; flow
state, setup failure transition, user request and turn finalization are real.
"""
from types import SimpleNamespace

import pytest

from kiss_cli import api, flowrun, gui, projectrun, project_verification
from .test_gui_project_verification import project_case


@pytest.mark.parametrize("provider", ["api:deepseek", "cli:claude"])
@pytest.mark.parametrize("scope", ["repaired", "shared"])
@pytest.mark.parametrize("passed", [False, True])
def test_post_agent_preflight_releases_failed_setup_phase(
        project_case, monkeypatch, provider, scope, passed):
    c = project_case
    name = "A" if passed else "B"
    working, cfg = next(pair for pair in c.pairs if pair[0].name == name)
    handler = c.handler
    setup_dir = handler._workdir(working)
    setup_dir.mkdir(parents=True, exist_ok=True)
    shared_verified = scope == "repaired"
    handler._status_for = lambda _ki: {"can_run": shared_verified}
    handler._helper_repo_root = lambda: handler.repo_root
    handler._software_status_prompt = lambda *_args: ""
    handler._agent_runtime_env = lambda _project: {}
    calls = []

    fs = flowrun.flowgate.FlowSession.open(c.project, {name: working.root})
    fs.ctx.state = fs.flow.states.State.SETUP_REQUIRED
    fs.ctx.selected_kis = [name]
    fs.ctx.save()
    monkeypatch.setattr(gui.ki_investigation, "pending_preflight",
                        lambda _project: {"pending": scope == "repaired", "kis": {}})

    def prepare(*_args):
        (setup_dir / "CLAUDE.md").write_text("Install dependencies only.", encoding="utf-8")
        return working, cfg

    def shared_preflight(*_args, **_kwargs):
        nonlocal shared_verified
        calls.append("shared-preflight")
        shared_verified = passed
        return passed

    handler._record_agent_preflight = shared_preflight
    monkeypatch.setattr(gui.setup_flow, "prepare", prepare)
    original_preflight = gui.Handler._verify_project_preflight

    def project_preflight(self, project, pairs, out, runtime_events=None):
        calls.append("project-preflight")
        if scope == "repaired" and passed and calls == ["project-preflight"]:
            # Simulate a dependency initially missing, which the doubled setup
            # provider repairs. The final check below is the real native probe.
            return False
        return original_preflight(self, project, pairs, out, runtime_events)

    monkeypatch.setattr(gui.Handler, "_verify_project_preflight", project_preflight)
    monkeypatch.setattr(gui.prompt, "compose_multi", lambda *_args, **_kwargs: "KI contract")
    monkeypatch.setattr(gui.calibration, "prompt_block", lambda *_args: "")
    monkeypatch.setattr(gui.calibration, "framework_root", lambda: None)
    monkeypatch.setattr(gui.settings, "database_access_mode", lambda: "off")
    monkeypatch.setattr(gui.skilllib, "prompt_block", lambda *_args: "")
    monkeypatch.setattr(gui.skilllib, "roots", lambda: [])
    monkeypatch.setattr(gui.skilllib, "selected", lambda *_args: [])
    monkeypatch.setattr(gui.mcp, "prompt_block", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(gui, "_grant_setup_execution", lambda *_args: None)

    def provider_finished():
        calls.append("provider")
        assert flowrun.current_state(c.project) == "SETUP_RUNNING"
        # A real pending user request must survive failure finalization.
        gui.setup_flow.request_user(c.project, {
            "kind": "other", "title": "Select the missing dependency",
            "message": "Provide its location.", "options": []})

    def api_run(*_args, **kwargs):
        assert kwargs["setup_mode"] is True
        provider_finished()
        yield "Setup attempt finished."

    def cli_turn(*_args, **_kwargs):
        provider_finished()
        return {"returncode": 0}

    monkeypatch.setattr(api, "run", api_run)
    cli_provider = SimpleNamespace(name="claude")
    monkeypatch.setattr(gui.providers, "available", lambda: [cli_provider])
    monkeypatch.setattr(gui.providers, "get", lambda _name: cli_provider)
    handler._cli_turn = cli_turn
    original_verified = flowrun.setup_verified

    def verified(*args):
        calls.append("verified")
        original_verified(*args)

    monkeypatch.setattr(flowrun, "setup_verified", verified)
    # Do not acquire data or launch a scientific execution turn in this lifecycle
    # regression. The actual successful SETUP_RUNNING→VERIFIED→APPROVED stays real.
    monkeypatch.setattr(flowrun, "_start_execution", lambda *_args: {})
    messages = []
    result = handler._chat_with_models([name], provider, "Continue setup", messages.append,
        c.project, flow_pre=SimpleNamespace(gated=True))

    assert result.kind == "setup"
    assert calls.count("provider") == 1
    assert ("verified" in calls) is passed
    assert flowrun.current_state(c.project) == ("APPROVED" if passed else "SETUP_REQUIRED")
    if scope == "repaired" or passed:
        assert project_verification.status(c.project, working)["can_run"] is passed
    if scope == "repaired" and not passed:
        assert calls == ["project-preflight", "provider", "project-preflight"]
        assert "project B fails" in "".join(messages)
    closed = flowrun.after(c.project, result, "Setup attempt finished.", setup_ok=passed)
    assert closed.continue_now is False
    request = gui.setup_flow.request(c.project)
    assert request["status"] == "waiting" and request["title"] == "Select the missing dependency"
    final = projectrun.finish_turn(c.project, request=request)
    assert final["status"] == "waiting_for_user"
    assert flowrun.current_state(c.project) != "EXECUTING"
