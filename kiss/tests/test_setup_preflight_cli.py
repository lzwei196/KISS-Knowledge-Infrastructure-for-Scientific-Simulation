"""CLI providers use the same isolated preflight boundary as API providers."""
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from kiss_cli import cli, handoff, install, ki_guard, paths, setup
from kiss_cli.catalog import KI


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell native-argument regression")
def test_powershell_command_preserves_literal_arguments(tmp_path):
    arguments = ["folder with spaces", "owner's folder", "$(not-a-command)"]
    code = "import json,sys; print(json.dumps(sys.argv[1:]))"
    command = setup._format_runtime_command(
        [sys.executable, "-c", code, *arguments],
        pythonpath=str(tmp_path / "owner's helper path"), platform="win32")
    result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == arguments


def test_setup_handoff_does_not_launch_preflight_in_protected_ki(tmp_path):
    source = tmp_path / "models" / "Tiny"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("# Tiny\n", encoding="utf-8")
    ki = KI(name="Tiny", root=source)
    cfg = paths.KissConfig.default(tmp_path / "work")
    command = "host-preflight-command"
    handoff.write_setup(ki, None, cfg, cfg.root, built_in_command="host-init-command",
                        preflight_command=command)
    body = (cfg.root / "CLAUDE.md").read_text(encoding="utf-8")
    assert command in body
    assert f"{cfg.python} {ki.root / 'preflight_check.py'}" not in body
    assert "preflight_check.py directly" in body
    result = install.InstallResult(model=ki.name)
    result.add(install.Step("preflight", False, "missing real input"))
    body = handoff.render(ki, result, None, cfg, preflight_command=command)
    assert command in body
    assert f"{cfg.python} preflight_check.py" not in body


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_KI_GUARD_HOME", str(tmp_path / "guard"))
    source = tmp_path / "models" / "Tiny"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("# Tiny\n", encoding="utf-8")
    (source / "preflight_check.py").write_text(
        "print('PREFLIGHT_REPORT={\"model_id\":\"Tiny\",\"checks\":[]}')\n", encoding="utf-8")
    root = tmp_path / "work"
    root.mkdir()
    cfg = paths.KissConfig.default(root)
    cfg.python = sys.executable
    (root / paths.CONFIG_NAME).write_text(cfg.dumps(), encoding="utf-8")
    ki_guard.enroll(source)
    setup.materialise_active(source, root / "ki", cfg)
    return SimpleNamespace(models=source.parent, model="Tiny", workdir=str(root), json=True), cfg


def test_cli_preflight_uses_saved_runtime_and_host_runner(prepared, monkeypatch, capsys):
    args, cfg = prepared
    calls = []
    def probe(ki, python, loaded, **kwargs):
        calls.append((ki.root, python, loaded.root, kwargs.get("project")))
        return install.Step("preflight", True, "actual host report")
    monkeypatch.setattr(install, "run_preflight", probe)
    assert cli.cmd_preflight(args) == 0
    assert calls == [(cfg.root / "ki", cfg.python, cfg.root, cfg.root)]
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is True
    assert not (cfg.root / "status.json").exists()


def test_cli_preflight_refuses_changed_runtime_during_check(prepared, monkeypatch, capsys):
    args, cfg = prepared
    def probe(*_args, **_kwargs):
        cfg.roles["data"] = cfg.root / "another-data"
        (cfg.root / paths.CONFIG_NAME).write_text(cfg.dumps(), encoding="utf-8")
        return install.Step("preflight", True, "not a verdict for the new binding")
    monkeypatch.setattr(install, "run_preflight", probe)
    assert cli.cmd_preflight(args) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is False
    assert "changed" in result["detail"].lower()


def test_cli_preflight_refuses_changed_active_ki(prepared, monkeypatch, capsys):
    args, cfg = prepared
    (cfg.root / "ki" / "SKILL.md").write_text("changed", encoding="utf-8")
    def forbidden(*args, **kwargs):
        pytest.fail("unverified code reached the preflight runner")
    monkeypatch.setattr(install, "run_preflight", forbidden)
    assert cli.cmd_preflight(args) == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False


def test_cli_preflight_runs_real_check_without_enrolling_or_ready_receipt(prepared, capsys):
    args, cfg = prepared
    before = ki_guard.require_intact(cfg.root / "ki")
    assert cli.cmd_preflight(args) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is True
    assert "PREFLIGHT_REPORT=" in result["detail"]
    assert Path(result["evidence"]["execution_root"]) != cfg.root / "ki"
    assert Path(result["evidence"]["output_path"]).is_file()
    assert ki_guard.require_intact(cfg.root / "ki") == before
    assert not (cfg.root / "status.json").exists()


def test_preflight_parser_requires_exact_workspace():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["preflight", "Tiny"])


def test_posix_command_quotes_source_and_workspace():
    import shlex
    command = setup._format_runtime_command(
        ["/host/python", "-m", "kiss_cli", "preflight", "Tiny", "-w", "/tmp/a'b c"],
        pythonpath="/source with spaces", platform="linux")
    assert shlex.split(command) == ["env", "PYTHONPATH=/source with spaces", "/host/python",
                                  "-m", "kiss_cli", "preflight", "Tiny", "-w", "/tmp/a'b c"]
