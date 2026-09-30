"""Entry points of the windowed frozen Windows Desktop.

The shipped exe is built with console=False: started from Explorer it has no
sys.stdout/sys.stderr, its pipes use the cp936 locale strictly, and an uncaught
exception in a worker child becomes PyInstaller's modal traceback dialog while
the parent waits with no timeout.
"""
from __future__ import annotations

import io
import json
import os
import sys
import threading
import time
from dataclasses import asdict
from pathlib import Path
from unittest import mock

import pytest

from kiss_cli import calibration, cli, execution, gui, ki_updates, obs_access
from kiss_cli.manifest import Acquire

windows_only = pytest.mark.skipif(os.name != "nt", reason="Windows file locking / frozen stdio")


@pytest.fixture
def no_turn(monkeypatch):
    for key in (execution.TURN_PROJECT_ENV, execution.TURN_ID_ENV):
        monkeypatch.delenv(key, raising=False)


def test_download_worker_crash_exits_with_a_traceback_not_a_dialog(tmp_path, capsys, no_turn):
    # An HTML error page saved as .zip with no sha256: extraction raises
    # BadZipFile, which main() does not report.
    page = tmp_path / "model.zip"
    page.write_text("<html>rate limited</html>", encoding="utf-8")
    prefix = tmp_path / "prefix"
    prefix.mkdir()
    work = tmp_path / "worker"
    work.mkdir()
    request = work / "request.json"
    request.write_text(json.dumps({
        "project": None, "prefix": str(prefix), "python": sys.executable,
        "acquire": asdict(Acquire(strategy="download", url=page.as_uri(), produces="model.exe")),
    }), encoding="utf-8")

    assert cli.main(["_install-download-worker", str(request)]) == 1
    err = capsys.readouterr().err
    assert "Traceback" in err and "BadZipFile" in err


def test_calibration_worker_crash_exits_with_a_traceback(tmp_path, capsys, monkeypatch, no_turn):
    project = tmp_path / "project"
    run_dir = project / "calibration" / "run"
    run_dir.mkdir(parents=True)
    request = run_dir / "request.json"
    request.write_text(json.dumps({"project": str(project), "run_dir": str(run_dir)}), encoding="utf-8")
    monkeypatch.setattr(calibration, "framework_root", lambda: None)

    assert cli.main(["_calibration-worker", str(request)]) == 1
    err = capsys.readouterr().err
    assert "RuntimeError" in err and "calibration framework source is missing" in err


def test_run_tool_crash_exits_with_a_traceback(capsys, monkeypatch):
    def broken(_project):
        raise PermissionError(13, "Access is denied", "runs/flow-state.json")
    monkeypatch.setattr(cli, "_flow_project", broken)

    assert cli.main(["run-tool", "--step", "M:run", "M", "tools/run.py"]) == 1
    err = capsys.readouterr().err
    assert "Traceback" in err and "PermissionError" in err


def test_worker_errors_main_reports_keep_their_message_and_status(tmp_path, capsys, no_turn):
    request = tmp_path / "request.json"
    request.write_text("{not json", encoding="utf-8")

    assert cli.main(["_install-download-worker", str(request)]) == 2
    err = capsys.readouterr().err
    assert err.startswith("kiss: ") and "Traceback" not in err


def test_workers_without_stderr_still_exit(monkeypatch):
    monkeypatch.setattr(cli, "_flow_project", mock.Mock(side_effect=RuntimeError("boom")))
    monkeypatch.setattr(sys, "stderr", None)
    assert cli.main(["run-tool", "--step", "M:run", "M", "tools/run.py"]) == 1


def _strict_locale_stream():
    return io.TextIOWrapper(io.BytesIO(), encoding="cp936", errors="strict", newline="\n")


@windows_only
def test_frozen_output_with_replacement_characters_cannot_raise(monkeypatch):
    # run_process decoded non-GBK tool bytes as U+FFFD; the frozen child's
    # stdout is the strict cp936 locale because PYTHONIOENCODING is ignored.
    out, err = _strict_locale_stream(), _strict_locale_stream()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)

    replacement = chr(0xFFFD)                      # not encodable in GBK

    def list_with_tool_output(args):
        print(f"discharge 12{replacement} m3/s")
        print(f"warning {replacement}", file=sys.stderr)
        return 0
    monkeypatch.setattr(cli, "cmd_list", list_with_tool_output)

    assert cli.main(["list"]) == 0
    out.flush()
    err.flush()
    assert out.encoding == "cp936"                 # still what run_process decodes
    assert out.buffer.getvalue().decode("cp936") == "discharge 12? m3/s\n"
    assert err.buffer.getvalue().decode("cp936") == "warning ?\n"


def test_unfrozen_streams_are_left_as_they_are(monkeypatch):
    out = _strict_locale_stream()
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(cli, "cmd_list", lambda args: 0)
    assert cli.main(["list"]) == 0
    assert out.errors == "strict"


def test_frozen_windowed_app_without_streams_starts(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    monkeypatch.setattr(cli, "cmd_list", lambda args: 0)
    assert cli.main(["list"]) == 0


def test_serve_checks_the_activated_library_against_the_bundled_one(tmp_path):
    # An install that already activated a guidance-less snapshot must fall
    # back to the bundled library; that needs the bundled root as reference.
    catalog = mock.MagicMock(models_dir=tmp_path / "bundle" / "models")
    catalog.__len__.return_value = 127
    with mock.patch.object(gui, "Handler"), \
            mock.patch.object(gui.Catalog, "discover", return_value=catalog), \
            mock.patch.object(gui, "GeoForgeHTTPServer") as server, \
            mock.patch.object(ki_updates, "active_library_root", return_value=None) as active, \
            mock.patch.object(ki_updates, "UpdateManager") as manager, \
            mock.patch.object(gui.obs_access, "refresh_catalogue"), \
            mock.patch.object(gui.atexit, "register"), \
            mock.patch("kiss_cli.firstrun.data_dir", return_value=tmp_path):
        server.return_value.serve_forever.side_effect = KeyboardInterrupt
        assert gui.serve(None, open_browser=False, workroot=tmp_path / "work",
                         auto_update=True) == 0
    active.assert_called_once_with(tmp_path / "bundle")
    assert manager.call_args.args[0] == tmp_path / "bundle"


def _hold_open_for(path: Path, seconds: float) -> threading.Thread:
    """A reader holding the file the way Python's open() does (no FILE_SHARE_DELETE)."""
    opened = threading.Event()

    def hold():
        with path.open("r", encoding="utf-8"):
            opened.set()
            time.sleep(seconds)
    reader = threading.Thread(target=hold, daemon=True)
    reader.start()
    assert opened.wait(5)
    return reader


@windows_only
def test_atomic_json_waits_out_a_brief_reader(tmp_path):
    target = tmp_path / "acquisition-replan.json"
    target.write_text('{"old": true}\n', encoding="utf-8")
    reader = _hold_open_for(target, 0.2)

    obs_access._atomic_json(target, {"replan": "requested"})

    reader.join(5)
    assert json.loads(target.read_text(encoding="utf-8")) == {"replan": "requested"}
    assert not list(tmp_path.glob(".acquisition-replan.json-*.tmp"))


@windows_only
def test_atomic_json_retry_is_bounded(tmp_path):
    target = tmp_path / "manual-download-details.json"
    target.write_text("{}\n", encoding="utf-8")
    reader = _hold_open_for(target, 3.5)
    started = time.monotonic()
    with pytest.raises(PermissionError):
        obs_access._atomic_json(target, {"late": True})
    assert time.monotonic() - started < 3             # 40 x 25 ms, then give up
    reader.join(5)
    assert json.loads(target.read_text(encoding="utf-8")) == {}
    assert not list(tmp_path.glob(".manual-download-details.json-*.tmp"))


@windows_only
def test_frozen_stderr_that_cannot_raise_keeps_exact_diagnostics(monkeypatch):
    err = io.TextIOWrapper(io.BytesIO(), encoding="cp936", errors="backslashreplace")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "stdout", _strict_locale_stream())
    monkeypatch.setattr(sys, "stderr", err)
    monkeypatch.setattr(cli, "cmd_list", lambda args: 0)
    assert cli.main(["list"]) == 0
    assert err.errors == "backslashreplace"


@windows_only
def test_every_frozen_child_command_exits_on_a_crash(monkeypatch, capsys):
    # fetch is forwarded to the windowed exe by the Agent bridge like run-tool.
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(cli, "cmd_list", mock.Mock(side_effect=RuntimeError("boom")))
    assert cli.main(["list"]) == 1
    assert "RuntimeError: boom" in capsys.readouterr().err
