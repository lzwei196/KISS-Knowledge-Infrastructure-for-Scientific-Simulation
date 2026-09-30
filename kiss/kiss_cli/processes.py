"""Process-tree cleanup shared by installation and model execution."""
from __future__ import annotations

import functools
import os
from pathlib import Path
import signal
import subprocess


# --- Windows process table -------------------------------------------------
#
# Windows has no process groups a console-less child can be signalled through,
# and ``taskkill /T`` follows parent links only from a *living* root: once the
# direct child has exited, its model or compiler descendants are unreachable
# by PID tree. We therefore snapshot the tree before anything is killed, and
# verify each process' creation time before terminating it, so a PID recycled
# by an unrelated process in the meantime is never touched.

_TH32CS_SNAPPROCESS = 0x00000002
_PROCESS_TERMINATE = 0x0001
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


@functools.lru_cache(maxsize=1)                 # polled ~20x/s per process during a Stop grace
def _kernel32():
    import ctypes
    from ctypes import wintypes

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_wchar * 260),
        ]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    k32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    k32.Process32FirstW.restype = wintypes.BOOL
    k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    k32.Process32NextW.restype = wintypes.BOOL
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    k32.GetProcessTimes.restype = wintypes.BOOL
    k32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    k32.TerminateProcess.restype = wintypes.BOOL
    k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    k32.GetExitCodeProcess.restype = wintypes.BOOL
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.CloseHandle.restype = wintypes.BOOL
    return k32, PROCESSENTRY32W


def _windows_process_table() -> dict[int, int]:
    """``{pid: parent_pid}`` for every process visible to this user."""
    import ctypes
    from ctypes import wintypes

    k32, entry_type = _kernel32()
    snapshot = k32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if not snapshot or snapshot == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    table: dict[int, int] = {}
    try:
        entry = entry_type()
        entry.dwSize = ctypes.sizeof(entry)
        ok = k32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            table[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
            ok = k32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        k32.CloseHandle(snapshot)
    return table


def _windows_creation_time(pid: int) -> int | None:
    """The process' creation FILETIME, or None when it is gone/inaccessible."""
    import ctypes
    from ctypes import wintypes

    k32, _ = _kernel32()
    handle = k32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not handle:
        return None
    try:
        times = [wintypes.FILETIME() for _ in range(4)]
        if not k32.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
            return None
        created = times[0]
        return (int(created.dwHighDateTime) << 32) | int(created.dwLowDateTime)
    finally:
        k32.CloseHandle(handle)


_STILL_ACTIVE = 259


def _handle_running(k32, handle, created: int) -> bool:
    """``handle`` names the process created at ``created``, and it has not exited."""
    import ctypes
    from ctypes import wintypes

    times = [wintypes.FILETIME() for _ in range(4)]
    if not k32.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
        return False
    if ((int(times[0].dwHighDateTime) << 32) | int(times[0].dwLowDateTime)) != created:
        return False
    code = wintypes.DWORD()
    if not k32.GetExitCodeProcess(handle, ctypes.byref(code)):
        return False
    return code.value == _STILL_ACTIVE


def _windows_running(pid: int, created: int) -> bool:
    """Still executing as the same process (not exited, PID not recycled).

    An exited process whose handle another process still holds keeps its PID
    and creation time, so presence alone is not liveness.
    """
    k32, _ = _kernel32()
    handle = k32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not handle:
        return False
    try:
        return _handle_running(k32, handle, created)
    finally:
        k32.CloseHandle(handle)


def windows_descendants(pid: int, *, root_created: int | None = None,
                        strict: bool = False) -> list[tuple[int, int]]:
    """Snapshot ``pid``'s living descendants as ``(pid, creation_time)``.

    A child must have been created no earlier than its parent: Windows keeps a
    dead parent's PID in the child's record, and that PID can later be reused
    by an unrelated process whose older children we must never adopt. With
    ``root_created`` (captured earlier), orphans of a root that has since exited
    are still found, while a root PID now held by another process yields none.
    ``strict`` raises when the process table cannot be read, so a caller can
    fall back to another mechanism instead of seeing "no descendants".
    """
    if os.name != "nt":
        return []
    current = _windows_creation_time(pid)
    if root_created is not None and current is not None and current != root_created:
        return []                             # the root's PID now names another process
    try:
        table = _windows_process_table()
    except OSError:
        if strict:
            raise
        return []
    children: dict[int, list[int]] = {}
    for child, parent in table.items():
        if child != parent:
            children.setdefault(parent, []).append(child)
    found: list[tuple[int, int]] = []
    seen = {int(pid), os.getpid()}
    todo = [(int(pid), root_created if root_created is not None else current)]
    while todo:
        parent, parent_time = todo.pop()
        for child in children.get(parent, ()):
            if child in seen:
                continue
            created = _windows_creation_time(child)
            if created is None:
                continue
            if parent_time is not None and created < parent_time:
                continue                      # the parent's PID was reused
            seen.add(child)
            found.append((child, created))
            todo.append((child, created))
    return found


def terminate_snapshot(entries: list[tuple[int, int]]) -> None:
    """Terminate snapshotted processes whose identity has not changed."""
    if os.name != "nt" or not entries:
        return
    k32, _ = _kernel32()
    for pid, created in entries:
        if pid == os.getpid():
            continue
        # One handle both proves the identity and terminates: with two opens
        # the PID could be recycled in between and the wrong process killed.
        handle = k32.OpenProcess(
            _PROCESS_TERMINATE | _PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            continue                          # already gone
        try:
            if _handle_running(k32, handle, created):
                k32.TerminateProcess(handle, 1)
        finally:
            k32.CloseHandle(handle)


def any_alive(entries: list[tuple[int, int]]) -> bool:
    """True while any snapshotted process still runs as the same process."""
    return os.name == "nt" and any(
        _windows_running(pid, created) for pid, created in entries)


def _taskkill_tree(pid: int) -> bool:
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    taskkill = Path(system_root) / "System32" / "taskkill.exe"
    try:
        result = subprocess.run(
            [str(taskkill), "/PID", str(pid), "/T", "/F"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def terminate_process_tree(proc: subprocess.Popen) -> None:
    """Stop a timed-out or cancelled command and every process it started.

    ``Popen.communicate(timeout=...)`` only terminates the direct child when a
    caller reacts with ``proc.kill()``. Build wrappers commonly leave their
    compiler, ``find``, or network helper descendants alive with our output
    pipes still open. Tear down the Windows process tree, or the private
    process group created for this command on POSIX.
    """
    if os.name == "nt":
        # Snapshot first: taskkill /T cannot find the descendants of a root
        # that has already exited (an npm .cmd shim, a build script), and it
        # follows parent PIDs unchecked, so it can kill an unrelated older
        # process whose dead parent's PID our root reused.
        try:
            root_created = _windows_creation_time(proc.pid)
            descendants = windows_descendants(proc.pid, strict=True)
        except Exception:  # noqa: BLE001 — no process table: taskkill's walk is all there is
            if not _taskkill_tree(proc.pid):
                try:
                    proc.kill()
                except OSError:
                    pass
            return
        try:
            proc.kill()                       # our own handle: it cannot name another process
        except OSError:
            pass
        try:
            # Plus anything the root started after the first walk; the pinned
            # creation time rejects a root PID another process now holds.
            late = windows_descendants(proc.pid, root_created=root_created)
        except Exception:  # noqa: BLE001 — the first snapshot still stands
            late = []
        try:
            terminate_snapshot(descendants + late)
        except OSError:
            pass
        return

    # ``start_new_session=True`` below guarantees that proc.pid is a process
    # group created by us, so killpg cannot target GeoForge's own group.
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        return
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass
    # The wrapper may exit before a descendant that ignored SIGTERM. The
    # process group continues to exist until every member is gone, so always
    # issue the final bounded kill and harmlessly ignore a vanished group.
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        pass
