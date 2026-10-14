"""Setup owns runtime probes and their children, including silent processes."""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from kiss_cli import execution, install, paths, processes, runnable


def _script_case(tmp_path, monkeypatch, source):
    root = tmp_path / "setup"
    root.mkdir()
    ki_root = root / "ki"
    ki_root.mkdir()
    product = root / "installed_fixture.py"
    product.write_text(source, encoding="utf-8")
    ki = SimpleNamespace(name="fixture", root=ki_root, preflight=None,
                         meta={"language": "python"})
    cfg = paths.KissConfig.default(root)
    cfg.python = sys.executable
    monkeypatch.setattr(runnable, "find_binary", lambda *args, **kwargs: product)
    return root, ki, cfg


def _pid_running(pid):
    if os.name == "nt":
        created = processes._windows_creation_time(pid)
        return created is not None and processes._windows_running(pid, created)
    try:
        stat = Path(f"/proc/{pid}/stat")
        if stat.exists() and stat.read_text().split(")", 1)[1].split()[0] == "Z":
            return False
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def test_without_context_forwards_subprocess_options_unchanged(monkeypatch):
    recorded = []
    expected = subprocess.CompletedProcess(["fixture"], 7, b"bytes", b"error")

    def run(command, **kwargs):
        recorded.append((command, kwargs))
        return expected

    monkeypatch.setattr(runnable.subprocess, "run", run)
    options = {"capture_output": True, "input": b"fixture input", "timeout": 3}
    assert runnable._probe_run(["fixture"], **options) is expected
    assert recorded == [(["fixture"], options)]


def test_supervised_probe_preserves_utf8_output_exit_code_and_environment(tmp_path):
    env = {**os.environ, "PROBE_FIXTURE_VALUE": "bound"}
    command = [sys.executable, "-c",
               "import os,sys; sys.stdout.buffer.write('水文\\n'.encode('utf-8')); "
               "sys.stderr.buffer.write(os.environ['PROBE_FIXTURE_VALUE'].encode()); sys.exit(3)"]
    with runnable.cancellation_context(tmp_path):
        result = runnable._probe_run(command, capture_output=True, text=True,
                                     encoding="utf-8", errors="strict", env=env,
                                     cwd=tmp_path, timeout=5)
    assert isinstance(result, subprocess.CompletedProcess)
    assert result.args == command and result.returncode == 3
    assert result.stdout == "水文\n" and result.stderr == "bound"


def test_supervised_launch_failure_retains_oserror(tmp_path):
    with runnable.cancellation_context(tmp_path), pytest.raises(FileNotFoundError):
        runnable._probe_run([str(tmp_path / "missing-runtime.exe")],
                            capture_output=True, text=True, timeout=1)


def test_supervised_timeout_remains_a_failed_runnable_verdict(tmp_path, monkeypatch):
    root, ki, cfg = _script_case(tmp_path, monkeypatch,
        "import time\nprint('fixture before timeout', flush=True)\ntime.sleep(30)\n")
    with runnable.cancellation_context(root):
        verdict = runnable.check(ki, cfg=cfg, timeout=0.5)
    assert not verdict.usable and not verdict.responds
    assert verdict.probe_timed_out
    assert "fixture before timeout" in verdict.probe_output
    assert "timed out" in verdict.detail


def test_supervised_import_checks_still_distinguish_missing_modules(tmp_path):
    with runnable.cancellation_context(tmp_path):
        assert runnable.missing_imports(["json"], sys.executable, tmp_path) == []
        assert runnable.missing_imports(["geoforge_absent_probe_fixture"], sys.executable, tmp_path) == [
            "geoforge_absent_probe_fixture"]


@pytest.mark.parametrize("action", ["callback", "marker", "old_generation"])
def test_stopped_scope_prevents_later_probe_launch(tmp_path, monkeypatch, action):
    generation = execution.begin_turn(tmp_path)
    stop = threading.Event()

    def forbidden_launch(*args, **kwargs):
        pytest.fail("a stopped runtime probe must not launch")

    with runnable.cancellation_context(tmp_path, stop=stop.is_set, turn_id=generation):
        if action == "callback":
            stop.set()
        elif action == "marker":
            execution.request_stop(tmp_path)
        else:
            execution.begin_turn(tmp_path)
        monkeypatch.setattr(execution, "run_process", forbidden_launch)
        with pytest.raises(install.InstallStopped):
            runnable._probe_run([sys.executable, "-V"], capture_output=True, text=True)


def test_nested_scopes_restore_owner_and_do_not_leak_after_failure(tmp_path):
    outer = tmp_path / "outer"
    inner = tmp_path / "inner"
    outer.mkdir()
    inner.mkdir()
    command = [sys.executable, "-c", "print('fixture')"]
    with runnable.cancellation_context(outer):
        with pytest.raises(install.InstallStopped):
            with runnable.cancellation_context(inner):
                execution.request_stop(inner)
                runnable._probe_run(command, capture_output=True, text=True, timeout=5)
        assert runnable._probe_run(command, capture_output=True, text=True, timeout=5).returncode == 0
        execution.request_stop(outer)
        with pytest.raises(install.InstallStopped):
            runnable._probe_run(command, capture_output=True, text=True, timeout=5)
    # A later unrelated caller retains subprocess.run's original bytes contract.
    assert runnable._probe_run(command, capture_output=True, timeout=5).stdout.strip() == b"fixture"


@pytest.mark.parametrize("control", ["callback", "marker"])
def test_quiet_probe_and_child_stop_while_unrelated_process_survives(tmp_path, monkeypatch, control):
    marker = tmp_path / "owned-processes.json"
    source = (
        "import json, os, subprocess, sys, time\nfrom pathlib import Path\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(45)'], "
        "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, "
        "creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))\n"
        f"Path({str(marker)!r}).write_text(json.dumps([os.getpid(), child.pid]))\n"
        "time.sleep(45)\n"
    )
    root, ki, cfg = _script_case(tmp_path, monkeypatch, source)
    generation = execution.begin_turn(root)
    stop = threading.Event()
    observed = []
    owned_windows_identities = []
    sentinel = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(45)"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def stop_after_child_starts():
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                observed.extend(json.loads(marker.read_text()))
                if os.name == "nt":
                    owned_windows_identities.extend(
                        (pid, processes._windows_creation_time(pid)) for pid in observed)
                break
            except (OSError, ValueError):
                time.sleep(0.025)
        if control == "marker":
            execution.request_stop(root)
        else:
            stop.set()

    stopper = threading.Thread(target=stop_after_child_starts, daemon=True)
    try:
        stopper.start()
        started = time.monotonic()
        with runnable.cancellation_context(root, stop=stop.is_set, turn_id=generation):
            with pytest.raises(install.InstallStopped):
                runnable.check(ki, cfg=cfg, timeout=30)
        stopper.join(timeout=2)
        assert len(observed) == 2, "the real probe and its child must have started"
        assert time.monotonic() - started < 15, "quiet output must not delay Stop until timeout"
        deadline = time.monotonic() + 3
        while any(_pid_running(pid) for pid in observed) and time.monotonic() < deadline:
            time.sleep(0.025)
        assert not any(_pid_running(pid) for pid in observed)
        assert sentinel.poll() is None, "Stop is scoped to this probe's process tree"
    finally:
        stop.set()
        stopper.join(timeout=2)
        if sentinel.poll() is None:
            sentinel.terminate()
        sentinel.wait(timeout=5)
        # Failures must not leave fixture descendants running on a developer's machine.
        if os.name == "nt":
            processes.terminate_snapshot([(pid, created) for pid, created in owned_windows_identities if created])
        else:
            import signal
            for pid in observed:
                if _pid_running(pid):
                    os.kill(pid, signal.SIGKILL)
