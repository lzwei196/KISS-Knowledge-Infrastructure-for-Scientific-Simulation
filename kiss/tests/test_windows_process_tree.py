"""Windows Stop on real process trees: a CLI ends at once, our run-tool wrapper may finish.

No signal reaches a console-less child on Windows, so the tree is found by a
process snapshot and each process is pinned by its creation time.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest import mock

import pytest

from kiss_cli import execution, processes

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows process trees")

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
_SLEEP = [sys.executable, "-c", "import time; time.sleep(60)"]
_BOTH = processes._PROCESS_TERMINATE | processes._PROCESS_QUERY_LIMITED_INFORMATION


def _spawner(pidfile: Path, child: list[str], then: str) -> list[str]:
    """A Python process that starts ``child``, records "<own pid> <child pid>", then runs ``then``."""
    code = (
        "import os, subprocess, sys, time\n"
        f"child = subprocess.Popen({child!r}, stdin=subprocess.DEVNULL,\n"
        "    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=0x08000000)\n"
        f"pidfile = {str(pidfile)!r}\n"
        "with open(pidfile + '.tmp', 'w') as f:\n"
        "    f.write(f'{os.getpid()} {child.pid}')\n"
        "os.replace(pidfile + '.tmp', pidfile)\n"
        + then)
    return [sys.executable, "-c", code]


def _launch(argv: list[str]) -> subprocess.Popen:
    return subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, creationflags=_NO_WINDOW)


def _pids(pidfile: Path, timeout: float = 30) -> list[int]:
    deadline = time.monotonic() + timeout
    while not pidfile.exists():
        assert time.monotonic() < deadline, f"{pidfile.name} was never written"
        time.sleep(0.05)
    return [int(p) for p in pidfile.read_text().split()]


def _identity(pid: int) -> tuple[int, int]:
    created = processes._windows_creation_time(pid)
    assert created is not None, f"process {pid} is not running"
    return pid, created


def _wait_dead(entries, timeout: float) -> list:
    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        alive = [entry for entry in entries if processes._windows_running(*entry)]
        if not alive or time.monotonic() >= deadline:
            return alive
        time.sleep(0.02)


def _cleanup(procs, entries) -> None:
    processes.terminate_snapshot(list(entries))
    for proc in procs:
        if proc.poll() is None:
            proc.kill()
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            pass
    execution.wait_for_stops()


def test_stop_ends_an_agent_cli_and_its_commands_at_once(tmp_path):
    # Nothing reaches a CLI root on Windows: a grace period would only let the
    # agent keep streaming and start new commands after the user's Stop.
    root = _launch(_spawner(tmp_path / "cli.pids", _SLEEP, "time.sleep(60)\n"))
    entries = []
    try:
        root_pid, command_pid = _pids(tmp_path / "cli.pids")
        assert root_pid == root.pid
        entries = [_identity(command_pid)]
        started = time.monotonic()
        execution.terminate_tree(root)                      # the gui/providers call
        root.wait(timeout=2)                                # TimeoutExpired under a grace
        assert _wait_dead(entries, 2 - (time.monotonic() - started)) == []
        assert time.monotonic() - started < 2
    finally:
        _cleanup([root], entries)


_WRAPPER = (
    "while child.poll() is None:\n"
    "    time.sleep(0.05)\n"
    "time.sleep(0.3)                          # receipt bookkeeping after the model ended\n"
    "with open(pidfile + '.receipt', 'w') as f:\n"
    "    f.write('written')\n"
    "sys.exit(7)\n"
)


def test_run_tool_stop_ends_the_model_now_and_lets_the_wrapper_write_its_receipt(tmp_path):
    pidfile = tmp_path / "wrapper.pids"
    box = {}
    worker = threading.Thread(target=lambda: box.update(run=execution.run_process(
        _spawner(pidfile, _SLEEP, _WRAPPER), cwd=tmp_path, env=dict(os.environ),
        timeout=60, project=tmp_path, graceful_stop=True)))
    entries = []
    worker.start()
    try:
        wrapper_pid, model_pid = _pids(pidfile)
        entries = [_identity(model_pid), _identity(wrapper_pid)]
        execution.request_stop(tmp_path)
        stopped_at = time.monotonic()
        # The watcher polls once a second; the model then ends without any grace.
        assert _wait_dead(entries[:1], 3) == [], "the model outlived Stop"
        assert time.monotonic() - stopped_at < 3
        worker.join(10)
        assert not worker.is_alive()
        run = box["run"]
        # Exit 7 is the wrapper's own: it was not forced (TerminateProcess exits 1).
        assert run.status == "stopped" and run.returncode == 7
        assert (tmp_path / "wrapper.pids.receipt").read_text() == "written"
    finally:
        processes.terminate_snapshot(entries)
        worker.join(10)
        execution.wait_for_stops()


def test_tree_kill_reaches_commands_orphaned_by_killing_their_root(tmp_path):
    middle = _spawner(tmp_path / "middle.pids", _SLEEP, "time.sleep(60)\n")
    root = _launch(_spawner(tmp_path / "root.pids", middle, "time.sleep(60)\n"))
    entries = []
    try:
        _, middle_pid = _pids(tmp_path / "root.pids")
        _, leaf_pid = _pids(tmp_path / "middle.pids")
        entries = [_identity(middle_pid), _identity(leaf_pid)]
        with mock.patch.object(processes, "_taskkill_tree",
                               wraps=processes._taskkill_tree) as taskkill:
            processes.terminate_process_tree(root)
        taskkill.assert_not_called()                        # no unchecked parent-PID walk
        root.wait(timeout=5)
        assert _wait_dead(entries, 3) == []
    finally:
        _cleanup([root], entries)


def test_tree_kill_reaches_the_orphan_of_a_root_that_already_exited(tmp_path):
    # An npm .cmd shim or a build driver: the root is gone, its child is not.
    root = _launch(_spawner(tmp_path / "shim.pids", _SLEEP, ""))
    entries = []
    try:
        _, child_pid = _pids(tmp_path / "shim.pids")
        entries = [_identity(child_pid)]
        root.wait(timeout=20)
        assert processes._windows_running(*entries[0])
        with mock.patch.object(processes, "_taskkill_tree",
                               wraps=processes._taskkill_tree) as taskkill:
            processes.terminate_process_tree(root)
        taskkill.assert_not_called()
        assert _wait_dead(entries, 3) == []
    finally:
        _cleanup([root], entries)


def test_a_snapshot_taken_before_the_parent_exited_still_reaches_the_orphan(tmp_path):
    middle = _spawner(tmp_path / "middle.pids", _SLEEP,
                      "while not os.path.exists(pidfile + '.go'):\n    time.sleep(0.05)\n")
    root = _launch(_spawner(tmp_path / "root.pids", middle, "time.sleep(60)\n"))
    entries = []
    try:
        _, middle_pid = _pids(tmp_path / "root.pids")
        _, leaf_pid = _pids(tmp_path / "middle.pids")
        entries = [_identity(middle_pid), _identity(leaf_pid)]
        snapshot = processes.windows_descendants(root.pid)
        assert set(entries) <= set(snapshot)
        (tmp_path / "middle.pids.go").touch()               # the parent exits
        assert _wait_dead(entries[:1], 20) == []
        assert processes._windows_running(*entries[1]), "the orphan must still run"
        processes.terminate_snapshot(snapshot)
        assert _wait_dead(entries[1:], 3) == []
    finally:
        _cleanup([root], entries)


def test_only_our_run_tool_wrapper_is_given_a_grace_period():
    proc = mock.MagicMock(spec=subprocess.Popen)
    with mock.patch.object(execution, "_terminate_tree_windows") as windows:
        execution.terminate_tree(proc)
        execution.terminate_tree(proc, wrapper_grace=True)
    assert windows.call_args_list == [
        mock.call(proc, grace=0.0),
        mock.call(proc, grace=execution._STOP_GRACE_SECONDS),
    ]


# --- PID reuse ---------------------------------------------------------------
# Real PIDs are recycled: every identity check uses creation times, mocked here.

def test_the_descendant_walk_never_adopts_children_of_a_recycled_parent_pid():
    root, child, stranger, grandchild, strangers_child = 900100, 900200, 900300, 900400, 900500
    table = {root: 4, child: root, stranger: root, grandchild: child, strangers_child: stranger}
    created = {root: 1000, child: 1100, stranger: 900, grandchild: 1200, strangers_child: 950}
    with mock.patch.object(processes, "_windows_process_table", return_value=table), \
         mock.patch.object(processes, "_windows_creation_time", side_effect=created.get):
        # ``stranger`` is older than the root: it only names a reused parent PID.
        assert sorted(processes.windows_descendants(root)) == [(child, 1100), (grandchild, 1200)]
        # The root's PID now names another process: adopt nothing at all.
        assert processes.windows_descendants(root, root_created=999) == []
        assert sorted(processes.windows_descendants(root, root_created=1000)) == [
            (child, 1100), (grandchild, 1200)]


class _Kernel32:
    """Processes by PID: (creation time, exit code); a handle is PID + 1."""

    def __init__(self, table):
        self.table, self.opened, self.terminated, self.closed = table, [], [], []

    def OpenProcess(self, access, _inherit, pid):
        self.opened.append((pid, access))
        return pid + 1 if pid in self.table else None

    def GetProcessTimes(self, handle, created, *_rest):
        value = self.table[handle - 1][0]
        created._obj.dwLowDateTime, created._obj.dwHighDateTime = value & 0xFFFFFFFF, value >> 32
        return True

    def GetExitCodeProcess(self, handle, code):
        code._obj.value = self.table[handle - 1][1]
        return True

    def TerminateProcess(self, handle, _code):
        self.terminated.append(handle - 1)
        return True

    def CloseHandle(self, handle):
        self.closed.append(handle)
        return True


def test_termination_checks_identity_on_the_handle_it_terminates():
    running = processes._STILL_ACTIVE
    ours, recycled, exited, gone = 900200, 900300, 900400, 900500
    k32 = _Kernel32({
        ours: ((7 << 32) | 1100, running),
        recycled: (5555, running),                          # same PID, another process
        exited: (1400, 0),
    })
    with mock.patch.object(processes, "_kernel32", return_value=(k32, None)):
        processes.terminate_snapshot([(ours, (7 << 32) | 1100), (recycled, 1300),
                                      (exited, 1400), (gone, 1500)])
    assert k32.terminated == [ours]
    # One open per process, with both rights: no window between check and kill.
    assert k32.opened == [(pid, _BOTH) for pid in (ours, recycled, exited, gone)]
    assert sorted(k32.closed) == [ours + 1, recycled + 1, exited + 1]


def test_kernel32_bindings_are_built_once():
    assert processes._kernel32() is processes._kernel32()
