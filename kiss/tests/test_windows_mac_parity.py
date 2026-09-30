"""Windows-specific contracts required by the September mac parity update."""
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest import mock
import shutil
import subprocess

import pytest

from kiss_cli import agent_bridge, execution, flowrun, obs_access, runnable


def test_bridge_output_uses_utf8_even_in_frozen_python():
    with mock.patch.object(sys, "stdout") as stdout, mock.patch.object(sys, "stderr") as stderr:
        agent_bridge._utf8_stdio()
    stdout.reconfigure.assert_called_once_with(encoding="utf-8", errors="replace")
    stderr.reconfigure.assert_called_once_with(encoding="utf-8", errors="replace")


def test_database_offline_diagnostics_never_read_credentials(monkeypatch):
    monkeypatch.setenv("GEOFORGE_DATABASE_OFFLINE", "1")
    with mock.patch.object(obs_access.secret_store, "get_secret") as read:
        assert obs_access.token() is None
        read.assert_not_called()


def test_import_helpers_keep_windows_contracts_and_optional_flags(tmp_path):
    preflight = tmp_path / "preflight_check.py"
    preflight.write_text(
        "REQUIRED_IMPORT_MODULES = ['yaml']\n"
        "def check_python_import(label, module, critical=True): pass\n"
        "check_python_import('real package', 'numpy')\n"
        "check_python_import('optional', 'plotly', False)\n"
        "for module, required in [('netCDF4', True), ('PIL', False)]:\n"
        " check_python_import(module, module, required)\n", encoding="utf-8")
    assert runnable.declared_imports(SimpleNamespace(preflight=preflight)) == [
        "yaml", "numpy", "netCDF4"]


@pytest.mark.skipif(os.name != "nt", reason="Windows console launcher")
def test_frozen_bridge_uses_bundled_runtime_not_python_on_path(tmp_path, monkeypatch):
    executable = tmp_path / "Program Files" / "GeoForge Desktop.exe"
    executable.parent.mkdir()
    helper = executable.with_name("geoforge-agent-bridge.exe")
    helper.touch()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(executable))
    assert flowrun._windows_bridge_command("flow") == f'"{helper}" flow'
    helper.unlink()
    with pytest.raises(OSError, match="missing"):
        flowrun._windows_bridge_command("database")


def test_bridge_forwards_unicode_question_and_refuses_unavailable_session(monkeypatch, capsys):
    for key in ("GEOFORGE_AGENT_FLOW_URL", "GEOFORGE_AGENT_DATABASE_TOKEN",
                "GEOFORGE_AGENT_QUESTION_TOKEN"):
        monkeypatch.delenv(key, raising=False)
    assert agent_bridge.main(["flow", "ask-question", "--json", "{}"]) == 3
    monkeypatch.setenv("GEOFORGE_AGENT_FLOW_URL", "http://127.0.0.1:1234/api/agent/flow-command")
    monkeypatch.setenv("GEOFORGE_AGENT_DATABASE_TOKEN", "fixture-capability")
    monkeypatch.setenv("GEOFORGE_AGENT_QUESTION_TOKEN", "fixture-question")
    payload = json.dumps({"title": "选择数据源"}, ensure_ascii=False)
    import io
    with mock.patch("urllib.request.urlopen", return_value=io.BytesIO(
            b'{"returncode":0,"stdout":"question saved"}')) as post:
        assert agent_bridge.main(["flow", "ask-question", "--json", payload]) == 0
    sent = json.loads(post.call_args.args[0].data)
    assert sent["argv"] == ["ask-question", "--json", payload]
    assert "question saved" in capsys.readouterr().out


@pytest.mark.skipif(os.name != "nt", reason="Windows child-tree cleanup")
def test_shared_execution_stops_child_tree():
    child = mock.MagicMock(spec=subprocess.Popen)
    child.pid = 12345
    child.communicate.return_value = ("last output", "")
    with mock.patch("kiss_cli.processes.terminate_process_tree") as terminate:
        stdout, stderr, detail = execution._stop_process(child)
    terminate.assert_called_once_with(child)
    assert stdout == "last output" and stderr == "" and not detail
    child.communicate.assert_called_once_with(timeout=5)


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is required")
def test_settings_provider_links_do_not_include_hint_punctuation():
    page = (Path(__file__).parents[1] / "kiss_cli/web/app.html").read_text(encoding="utf-8")
    code = page[page.index("function providerHelpUrl("):page.index("function drawLocalSettings(")]
    script = code + """
const assert=require('node:assert/strict');
assert.equal(providerHelpUrl('Get a key (https://platform.deepseek.com/api_keys)'), 'https://platform.deepseek.com/api_keys');
assert.equal(providerHelpUrl('See https://example.org/path.'), 'https://example.org/path');
assert.equal(providerHelpUrl('no link'), '');
const PROV={providers:[]};
const esc=s=>String(s).replaceAll('&','&amp;').replaceAll('"','&quot;');
assert.match(settingsProviderOptions('api:deepseek'), /value="api:deepseek" selected/);
PROV.providers=[{name:'api:deepseek',label:'DeepSeek'},{name:'cli:codex',label:'Codex'}];
assert.match(settingsProviderOptions('api:deepseek'), /value="api:deepseek" selected>DeepSeek/);
assert.equal((settingsProviderOptions('api:deepseek').match(/value="api:deepseek"/g)||[]).length,1);
"""
    result = subprocess.run([shutil.which("node"), "-e", script], capture_output=True, text=True,
                            encoding="utf-8")
    assert result.returncode == 0, result.stderr
    startup = page[page.index("[STATUS,PROV]=await Promise.all"):page.index("},750);")]
    assert "drawLocalSettings()" in startup
    assert "drawProxyProviderSettings()" in startup


@pytest.mark.skipif(os.name != "nt", reason="Windows sharing violations")
def test_a_new_turn_waits_out_a_watcher_reading_the_generation(tmp_path):
    import threading
    first = execution.begin_turn(tmp_path)
    # Python opens without FILE_SHARE_DELETE: replacing the file fails until closed.
    reader = open(tmp_path / execution.TURN_FILE, encoding="utf-8")
    threading.Timer(0.2, reader.close).start()
    try:
        second = execution.begin_turn(tmp_path)
    finally:
        reader.close()
    assert execution.current_turn_id(tmp_path) == second != first


def test_turn_rotation_retries_only_windows_sharing_violations_and_is_bounded(tmp_path):
    with mock.patch.object(Path, "replace", side_effect=PermissionError(13, "denied")) as replace, \
         mock.patch.object(execution.time, "sleep") as sleep:
        with pytest.raises(PermissionError):
            execution.begin_turn(tmp_path)
    # POSIX rename is not blocked by readers: a PermissionError is real at once.
    assert replace.call_count == (40 if os.name == "nt" else 1)
    assert sleep.call_count == replace.call_count - 1


def test_an_unlaunchable_command_line_is_named_in_full(tmp_path):
    missing = str(tmp_path / "no-such-build-tool")
    line = f"{missing} CC=gcc"                              # a Windows command-line string
    run = execution.run_process(line, cwd=tmp_path, env=dict(os.environ), timeout=5)
    assert run.status == "not_launched" and repr(line) in run.detail
    run = execution.run_process([missing, "CC=gcc"], cwd=tmp_path, env=dict(os.environ), timeout=5)
    assert run.status == "not_launched" and repr(missing) in run.detail


@pytest.mark.skipif(os.name != "nt", reason="Windows tray")
def test_tray_exit_stops_everything_first_and_exits_even_if_that_fails(monkeypatch):
    from kiss_cli import windows_tray
    calls = []
    monkeypatch.setattr(windows_tray.os, "_exit", lambda code: calls.append(("exit", code)))
    windows_tray._exit(lambda: calls.append("stop"))
    windows_tray._exit(mock.Mock(side_effect=RuntimeError("cleanup failed")))
    windows_tray._exit(None)
    assert calls == ["stop", ("exit", 0), ("exit", 0), ("exit", 0)]


def test_frozen_windows_app_gives_the_tray_exit_the_desktop_stop(monkeypatch, tmp_path):
    import kiss_cli
    from kiss_cli import app, gui
    tray = SimpleNamespace(start=mock.Mock())
    monkeypatch.setitem(sys.modules, "webview", None)       # the frozen Windows path
    monkeypatch.setitem(sys.modules, "kiss_cli.windows_tray", tray)
    monkeypatch.setattr(kiss_cli, "windows_tray", tray, raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(gui, "serve", mock.Mock(return_value=0))
    assert app.run_app(tmp_path) == 0
    assert tray.start.call_args.kwargs["on_exit"] is gui._stop_everything


def test_long_job_rule_uses_nohup_on_windows_even_with_a_foreign_setsid():
    from kiss_cli import prompt
    with mock.patch.object(prompt.shutil, "which", return_value=r"C:\msys64\usr\bin\setsid.exe"):
        assert prompt._long_job_detach() == ("nohup" if os.name == "nt" else "setsid nohup")
    with mock.patch.object(prompt.shutil, "which", return_value=None):
        assert prompt._long_job_detach() == "nohup"
    assert ("setsid" in prompt.HEADLESS_LONG_JOB_RULE) == (
        bool(shutil.which("setsid")) and os.name != "nt")


@pytest.mark.parametrize("name", ["python.exe", "Rscript.exe", "julia.exe", "node.exe",
                                  "cmd.exe", "powershell.exe", "pwsh.exe", "bash.exe"])
def test_windows_interpreters_cannot_masquerade_as_declared_models(tmp_path, name):
    from ki_tools_common.flow.tools import declared_binaries
    binary = tmp_path / name
    binary.write_bytes(b"MZ")
    (tmp_path / "knowledge_infrastructure.yaml").write_text(
        "model:\n  binary:\n    path: " + binary.as_posix() + "\n", encoding="utf-8")
    assert declared_binaries(tmp_path) == set()
