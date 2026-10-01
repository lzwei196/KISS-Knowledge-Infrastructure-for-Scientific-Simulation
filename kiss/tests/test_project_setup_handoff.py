"""Software setup stays bounded until the host's real preflight hands off to Flow."""
from types import SimpleNamespace

import pytest

from kiss_cli import api, execution, flowrun, gui, paths


@pytest.mark.parametrize("preflight_ok", [True, False])
def test_project_setup_recipe_precedes_host_preflight_and_only_verified_handoff(
        tmp_path, monkeypatch, preflight_ok):
    project, setup_wd = tmp_path / "project", tmp_path / "software"
    project.mkdir()
    ki = SimpleNamespace(name="M", root=tmp_path / "ki")
    cfg = paths.KissConfig.default(setup_wd)
    handle = api.TurnHandle()
    turn_id = execution.begin_turn(project)
    events = {"_handle": handle, "_turn_id": turn_id}
    calls = []
    flow = SimpleNamespace(check_tool=lambda _name: None)
    setup_turn = SimpleNamespace(kind="setup", session=flow)

    def prepare(*_args):
        setup_wd.mkdir(exist_ok=True)
        (setup_wd / "CLAUDE.md").write_text("Set up M", encoding="utf-8")
        return None, cfg

    def install(_ki, _manifest, workdir, emit, _repo, **kwargs):
        calls.append("builtin")
        assert workdir == setup_wd
        assert kwargs["installation_only"] is True
        assert kwargs["project"] == project and kwargs["turn_id"] == turn_id
        assert kwargs["stop"]() is False
        emit("Installed software. No model run.\n")

    def agent(_provider, live_ki, config, _system, _task, **kwargs):
        calls.append("agent")
        assert kwargs["setup_mode"] and kwargs["project_mode"]
        assert kwargs["flow"] is flow
        context = kwargs["setup_context"]
        assert context["installation_only"] is True and context["project_root"] == project
        # Exercise the actual API tool -> GUI recipe callback, not a direct mock call.
        result = api.execute_tool("run_builtin_setup", {}, live_ki, config,
                                  setup_mode=True, project_mode=True, flow=flow,
                                  setup_context=context)
        assert "Installed software" in result
        yield "Software installation finished."

    def preflight(_ki, live_ki, config, workdir, _emit, **kwargs):
        calls.append("host-preflight")
        assert live_ki is ki and config is cfg and workdir == setup_wd
        assert kwargs["project"] == project and kwargs["turn_id"] == turn_id
        assert kwargs["stop"]() is False
        return preflight_ok

    def verified(actual_project, models, config):
        calls.append("setup-verified")
        assert actual_project == project and models == [ki] and config is cfg

    handler = SimpleNamespace(
        _ki=lambda _name: ki, _workdir=lambda _ki: setup_wd,
        _status_for=lambda _ki: {"can_run": False}, _manifest=lambda _ki: {},
        repo_root=tmp_path, catalog=SimpleNamespace(models_dir=tmp_path),
        _software_status_prompt=lambda *_args: "", _record_agent_preflight=preflight,
    )
    monkeypatch.setattr(gui.setup_flow, "prepare", prepare)
    monkeypatch.setattr(gui.prompt, "compose_multi", lambda *_args, **_kwargs: "KI contract")
    monkeypatch.setattr(gui.calibration, "prompt_block", lambda *_args: "")
    monkeypatch.setattr(gui.settings, "database_access_mode", lambda: "off")
    monkeypatch.setattr(gui.skilllib, "prompt_block", lambda *_args: "")
    monkeypatch.setattr(gui.skilllib, "roots", lambda: [])
    monkeypatch.setattr(gui.mcp, "prompt_block", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(gui, "run_install", install)
    monkeypatch.setattr(api, "run", agent)
    monkeypatch.setattr(flowrun, "setup_allowed", lambda _project: True)
    monkeypatch.setattr(flowrun, "setup_turn", lambda *_args, **_kwargs: setup_turn)
    monkeypatch.setattr(flowrun, "setup_verified", verified)

    result = gui.Handler._chat_with_models(
        handler, ["M"], "api:deepseek", "Install the approved model", lambda _piece: True,
        project, flow_pre=SimpleNamespace(gated=True), runtime_events=events)

    assert result is setup_turn
    assert calls == ["agent", "builtin", "host-preflight"] + (["setup-verified"] if preflight_ok else [])
