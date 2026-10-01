"""Project setup cannot produce scientific results before receipted execution."""
from types import SimpleNamespace
from pathlib import Path
import sys

import pytest

from kiss_cli import api, execution


def setup_flow():
    return SimpleNamespace(
        state=SimpleNamespace(value="SETUP_RUNNING"),
        check_tool=lambda _name: None,
        api_tools=lambda: {"run_setup_command", "run_ki_tool", "run_preflight",
                           "run_calibration", "publish_setup_output",
                           "read_work_file", "request_user_action"},
    )


def workspace(tmp_path):
    root = tmp_path / "software"
    root.mkdir()
    binary = root / "model.exe"
    binary.write_bytes(b"MZfixture")
    ki = SimpleNamespace(root=root / "ki", name="fixture")
    cfg = SimpleNamespace(root=root, python=sys.executable, roles={"binaries": root})
    return ki, cfg, binary


@pytest.mark.parametrize("name", ["run_ki_tool", "run_preflight", "run_calibration",
                                  "publish_setup_output"])
def test_project_setup_blocks_scientific_tools_without_opt_in(tmp_path, name):
    ki, cfg, _ = workspace(tmp_path)
    with pytest.raises(api.ToolError, match="installation-only"):
        api.execute_tool(name, {}, ki, cfg, setup_mode=True, project_mode=True,
                         flow=setup_flow(), setup_context={"installation_only": False})


def test_project_setup_refuses_model_command_before_launch(tmp_path, monkeypatch):
    ki, cfg, binary = workspace(tmp_path)
    launched = []
    monkeypatch.setattr(execution, "run_process", lambda *a, **k: launched.append(a))
    with pytest.raises(api.ToolError, match="model/example"):
        api.execute_tool("run_setup_command", {"argv": [str(binary), "case.nml"]},
                         ki, cfg, setup_mode=True, project_mode=True, flow=setup_flow())
    assert not launched


def test_project_setup_startup_probe_is_bounded_and_isolated(tmp_path, monkeypatch):
    ki, cfg, binary = workspace(tmp_path)
    calls = []

    def launch(argv, **kwargs):
        calls.append(kwargs)
        assert Path(kwargs["cwd"]).is_dir()
        return execution.ProcessRun("succeeded", 0, "usage", "", process_started=True)

    monkeypatch.setattr(execution, "run_process", launch)
    api.execute_tool("run_setup_command", {"argv": [str(binary), "--help"],
                     "timeout_seconds": 1800}, ki, cfg, setup_mode=True,
                     project_mode=True, flow=setup_flow())
    assert 0 < calls[0]["timeout"] <= 25
    assert Path(calls[0]["cwd"]) != cfg.root
    assert calls[0]["stdin"] is not None


def test_project_setup_keeps_installation_scope_across_api_turns(tmp_path, monkeypatch):
    ki, cfg, _ = workspace(tmp_path)
    prov = SimpleNamespace(name="fixture", label="Fixture", key=lambda: "fixture",
                           default_model="fixture", models={}, wire="openai")
    offered = []
    contexts = []

    def turn(_prov, _model, _system, _messages, tools, _key, **_kwargs):
        offered.append({tool["name"] for tool in tools})
        if len(offered) == 1:
            return "", [("1", "read_work_file", {"path": "README"})], {
                "role": "assistant", "content": ""}
        return "Installed", [], {"role": "assistant", "content": "Installed"}

    monkeypatch.setattr(api, "_openai_turn", turn)
    monkeypatch.setattr(api, "execute_tool", lambda *a, **kw: contexts.append(kw["setup_context"]) or "ok")
    list(api.run(prov, ki, cfg, "Install only", "Install", setup_mode=True,
                 project_mode=True, flow=setup_flow()))
    assert len(offered) == 2
    for tools in offered:
        assert "run_setup_command" in tools
        assert not tools & {"run_preflight", "run_ki_tool", "run_calibration", "publish_setup_output"}
    assert contexts[0]["installation_only"] is True
