"""Real Windows command supervision, including the extra Python venv launcher."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
from unittest import mock
import venv

import pytest

from kiss_cli import execution, processes


pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows process supervision")


@pytest.fixture(scope="module")
def interpreters(tmp_path_factory):
    folder = tmp_path_factory.mktemp("supervision-venv")
    venv.EnvBuilder(with_pip=False).create(folder)
    return {"base": Path(sys._base_executable), "venv": folder / "Scripts/python.exe"}


def _until(predicate, seconds=5):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.02)
    raise AssertionError("bounded wait did not observe the expected condition")


@pytest.mark.parametrize("interpreter", ["base", "venv"])
@pytest.mark.parametrize("scenario", ["stop", "grace", "crash", "success", "timeout"])
def test_run_process_cleans_observed_tree_and_preserves_outcome(tmp_path, interpreters,
                                                              interpreter, scenario):
    wrapper = tmp_path / "wrapper.py"
    wrapper.write_text(
        "import json, os, subprocess, sys, time\n"
        "from pathlib import Path\n"
        "base, mode, directory = sys.argv[1:]\n"
        "directory = Path(directory)\n"
        # Inherit stdout/stderr: a surviving child would also prevent EOF.
        "child = subprocess.Popen([base, '-c', 'import time; time.sleep(12)'],\n"
        "    stdin=subprocess.DEVNULL, creationflags=0x08000000)\n"
        "(directory/'pids.tmp').write_text(json.dumps([os.getpid(), child.pid]))\n"
        "os.replace(directory/'pids.tmp', directory/'pids.json')\n"
        "print('wrapper output', flush=True)\n"
        "print('wrapper error', file=sys.stderr, flush=True)\n"
        "if mode == 'grace':\n"
        "    child.wait()\n"
        "    time.sleep(0.2)\n"
        "    (directory/'receipt').write_text('written')\n"
        "    sys.exit(7)\n"
        "if mode in ('crash', 'success'):\n"
        "    while not (directory/'exit-now').exists(): time.sleep(0.02)\n"
        "    os._exit(23 if mode == 'crash' else 0)\n"
        "time.sleep(12)\n", encoding="utf-8")
    argv = [str(interpreters[interpreter]), str(wrapper), str(interpreters["base"]),
            scenario, str(tmp_path)]
    box, entries, proc = {}, [], None
    worker = threading.Thread(target=lambda: box.update(result=execution.run_process(
        argv, cwd=tmp_path, env=dict(os.environ), timeout=2 if scenario == "timeout" else 6,
        project=tmp_path, graceful_stop=scenario == "grace")))
    worker.start()
    try:
        _until(lambda: (tmp_path / "pids.json").exists())
        wrapper_pid, child_pid = json.loads((tmp_path / "pids.json").read_text())
        for pid in (wrapper_pid, child_pid):
            created = processes._windows_creation_time(pid)
            assert created is not None
            entries.append((pid, created))
        proc = _until(lambda: next((p for p in list(execution.LIVE_PROCESSES)
                                   if p.args == argv), None))
        tracker = proc._geoforge_process_tree
        _until(lambda: entries[-1] in tracker.refresh())
        assert (wrapper_pid == proc.pid) == (interpreter == "base")
        if scenario == "grace":
            assert tracker.grace_entries() == ([entries[0]] if interpreter == "venv" else [])
        if scenario in {"stop", "grace"}:
            execution.request_stop(tmp_path)
        elif scenario in {"crash", "success"}:
            (tmp_path / "exit-now").touch()
        worker.join(8)
        assert not worker.is_alive()
        result = box["result"]
        expected = {"stop": ("stopped", 1), "grace": ("stopped", 7),
                    "crash": ("failed", 23), "success": ("succeeded", 0),
                    "timeout": ("timed_out", None)}[scenario]
        assert (result.status, result.returncode) == expected
        assert result.stdout.strip() == "wrapper output"
        assert result.stderr.strip() == "wrapper error"
        assert not processes.any_alive(entries + tracker.refresh())
        assert not tracker._thread.is_alive()
        assert proc not in execution.LIVE_PROCESSES
        if scenario == "grace":
            assert (tmp_path / "receipt").read_text() == "written"
        else:
            assert not (tmp_path / "receipt").exists()
    finally:
        # Only the recorded identities and Popen handles from this fixture.
        processes.terminate_snapshot(entries)
        if proc is not None:
            processes.terminate_process_tree(proc)
        worker.join(8)
        execution.wait_for_stops()


def test_tracker_retains_known_children_but_never_adopts_through_gone_or_reused_parent():
    root, middle, leaf, stranger = 900001, 900002, 900003, 900004
    created = {root: 100, middle: 110, leaf: 120}
    table = {root: 4, middle: root, leaf: middle}
    with mock.patch.object(processes, "_windows_creation_time", side_effect=created.get), \
         mock.patch.object(processes, "_windows_process_table", side_effect=lambda: table), \
         mock.patch.object(processes, "_windows_running", side_effect=lambda pid, stamp:
                           created.get(pid) == stamp), \
         mock.patch.object(processes, "_venv_images", return_value=None):
        tracker = processes.WindowsProcessTracker(SimpleNamespace(pid=root), [])
        assert set(tracker.refresh()) == {(middle, 110), (leaf, 120)}
        del created[middle]
        table[stranger] = middle
        created[stranger] = 130
        assert set(tracker.refresh()) == {(leaf, 120)}
        created[middle] = 125                 # parent PID reused by someone else
        table[middle] = 4                     # new process is not our root's child
        assert set(tracker.refresh()) == {(leaf, 120)}
        del created[root]
        table[stranger] = root               # even a gone original root grants nothing
        assert set(tracker.refresh()) == {(leaf, 120)}


@pytest.mark.parametrize("root_image,child_images,expected", [
    ("launcher", {900002: "base"}, [(900002, 110)]),
    ("other-launcher", {900002: "base"}, []),
    ("launcher", {900002: "other-base"}, []),
    ("launcher", {900002: "base", 900003: "base"}, []),
])
def test_grace_requires_exact_images_and_unique_verified_direct_child(root_image, child_images,
                                                                     expected):
    created = {900001: 100, 900002: 110, 900003: 120}
    with mock.patch.object(processes, "_windows_creation_time", side_effect=created.get), \
         mock.patch.object(processes, "_venv_images", return_value=("launcher", "base")), \
         mock.patch.object(processes, "_windows_image", side_effect=lambda pid, stamp:
                           root_image if pid == 900001 else child_images.get(pid)), \
         mock.patch.object(processes.WindowsProcessTracker, "refresh"):
        tracker = processes.WindowsProcessTracker(SimpleNamespace(pid=900001), [])
        tracker._known = {(pid, created[pid]) for pid in child_images}
        tracker._parents = {entry: tracker.root for entry in tracker._known}
        assert tracker.grace_entries() == expected
        tracker._parents = {entry: (900099, 99) for entry in tracker._known}
        assert tracker.grace_entries() == []   # matching grandchildren do not get grace


def test_venv_configuration_is_read_only_and_requires_exact_absolute_paths(interpreters, tmp_path):
    launcher = interpreters["venv"]
    cfg = launcher.parent.parent / "pyvenv.cfg"
    original = cfg.read_bytes()
    assert processes._venv_images([str(launcher)]) == (
        os.path.normcase(str(launcher.resolve())),
        os.path.normcase(str(interpreters["base"].resolve())))
    assert cfg.read_bytes() == original
    assert processes._venv_images([str(interpreters["base"])]) is None
    assert processes._venv_images(["python.exe"]) is None
    assert processes._venv_images(str(launcher)) is None
    other = tmp_path / "Scripts/python.exe"
    other.parent.mkdir()
    other.write_bytes(b"not a real interpreter")
    config = tmp_path / "pyvenv.cfg"
    config.write_text("home = relative-folder\nexecutable = relative.exe\n")
    before = config.read_bytes()
    assert processes._venv_images([str(other)]) is None
    assert config.read_bytes() == before


def test_cleanup_reuses_creation_identity_and_does_not_kill_recycled_child():
    from .test_windows_process_tree import _Kernel32

    original = (900002, 110)
    k32 = _Kernel32({original[0]: (999, processes._STILL_ACTIVE)})
    tracker = processes.WindowsProcessTracker.__new__(processes.WindowsProcessTracker)
    tracker._done = threading.Event()
    tracker._thread = threading.Thread()
    with mock.patch.object(tracker, "refresh", return_value=[original]), \
         mock.patch.object(processes, "_kernel32", return_value=(k32, None)):
        tracker.close()
    assert k32.terminated == []


@pytest.mark.parametrize("interpreter", ["base", "venv"])
@pytest.mark.parametrize("error_type,status", [
    (KeyboardInterrupt, "interrupted"), (OSError, "outcome_unknown"),
    (RuntimeError, "outcome_unknown"),
])
def test_observation_failure_still_closes_tracker_and_live_descendants(
        tmp_path, interpreters, interpreter, error_type, status):
    from .test_windows_process_tree import _spawner

    pidfile = tmp_path / "exception.pids"
    argv = _spawner(pidfile, [str(interpreters["base"]), "-c", "import time; time.sleep(12)"],
                    "print('before observation failure', flush=True)\n"
                    f"with open({str(tmp_path / 'output-ready')!r}, 'w') as f: f.write('ready')\n"
                    "time.sleep(12)\n")
    argv[0] = str(interpreters[interpreter])
    original = subprocess.Popen.communicate
    captured, entries = [], []

    def observe_then_fail(proc, *args, **kwargs):
        if not captured and proc.args == argv:
            captured.append(proc)
            _until(pidfile.exists)
            _until(lambda: (tmp_path / "output-ready").exists())
            for pid in map(int, pidfile.read_text().split()):
                created = processes._windows_creation_time(pid)
                assert created is not None
                entries.append((pid, created))
            _until(lambda: entries[-1] in proc._geoforge_process_tree.refresh())
            raise error_type("injected observation failure")
        return original(proc, *args, **kwargs)

    try:
        with mock.patch.object(subprocess.Popen, "communicate", new=observe_then_fail):
            result = execution.run_process(argv, cwd=tmp_path, env=dict(os.environ), timeout=6)
        assert result.status == status
        assert result.returncode is None
        assert result.process_started is True
        assert result.stdout.strip() == "before observation failure"
        assert len(captured) == 1
        tracker = captured[0]._geoforge_process_tree
        assert not tracker._thread.is_alive()
        assert not processes.any_alive(entries + tracker.refresh())
        assert captured[0] not in execution.LIVE_PROCESSES
    finally:
        processes.terminate_snapshot(entries)
        for proc in captured:
            processes.terminate_process_tree(proc)
