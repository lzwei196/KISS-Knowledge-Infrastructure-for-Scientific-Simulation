"""Host-owned WSL protocol worker. Standalone stdlib source, never an agent tool.

The caller authorizes commands before transport. This is a process supervisor
and workspace binding, not an OS filesystem sandbox for arbitrary programs.
"""
from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import pwd
import queue
import re
import select
import signal
import socket
import stat
import subprocess
import sys
import threading
import time

PROTOCOL = "geoforge.wsl-worker.v1"
MAX_REQUEST = 24 * 1024 * 1024
MAX_FILE = 8 * 1024 * 1024
MAX_FILES = 64
MAX_OUTPUT = 8 * 1024 * 1024
MARKER = ".geoforge-runtime-binding.json"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def emit(value):
    sys.stdout.buffer.write(canonical(value) + b"\n")
    sys.stdout.buffer.flush()


def ordinary(path, limit=MAX_FILE):
    flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(path, flags), "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError("file must be ordinary and within the byte limit")
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError("file exceeds the byte limit")
    return data


def identity():
    if sys.platform != "linux":
        raise ValueError("worker requires Linux")
    account = pwd.getpwuid(os.getuid())
    machine = ordinary("/etc/machine-id", 4096).decode("ascii").strip()
    executable = Path(sys.executable).resolve()
    return {"protocol": PROTOCOL, "uid": os.getuid(), "user": account.pw_name,
            "home": account.pw_dir, "machine_id": machine,
            "kernel": os.uname().release, "architecture": os.uname().machine,
            "python": str(sys.executable), "python_realpath": str(executable),
            "python_sha256": digest(ordinary(executable, 64 * 1024 * 1024)),
            "python_version": list(sys.version_info[:3])}


def native_filesystem(path):
    # Linux statfs starts with a native signed long containing the filesystem
    # magic. A generously sized buffer avoids architecture-dependent tail layout.
    buf = ctypes.create_string_buffer(512)
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.statfs(os.fsencode(path), ctypes.byref(buf)) != 0:
        raise OSError(ctypes.get_errno(), "cannot inspect guest filesystem")
    magic = ctypes.c_long.from_buffer(buf).value & 0xffffffff
    if magic not in {0xEF53, 0x58465342, 0x9123683E}:
        raise ValueError(f"workspace requires native Linux ext/xfs/btrfs storage (observed {magic:#x})")
    return f"{magic:#x}"


def no_links(path):
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if current.is_symlink():
            raise ValueError("workspace path contains a symbolic link")


def workspace(binding, observed, create=False):
    if observed["uid"] == 0 or binding["user"] != observed["user"]:
        raise ValueError("runtime must use the bound non-root Linux user")
    root = Path(binding["workspace"])
    home = Path(observed["home"])
    expected = home / ".local" / "share" / "geoforge" / "runtimes" / binding["workspace_id"]
    if not root.is_absolute() or root != expected:
        raise ValueError(f"workspace must be the binding-owned path {expected}")
    no_links(root)
    marker = root / MARKER
    authority = {"protocol": PROTOCOL, "workspace_id": binding["workspace_id"],
                 "user": observed["user"], "uid": observed["uid"],
                 "machine_id": observed["machine_id"], "workspace": str(root)}
    if create:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        no_links(root)
        if not marker.exists():
            if any(root.iterdir()):
                raise ValueError("unbound workspace is not empty; existing files were preserved")
            with marker.open("xb") as stream:
                stream.write(canonical(authority))
    if not root.is_dir() or root.stat().st_uid != observed["uid"]:
        raise ValueError("bound workspace is absent or owned by another user")
    no_links(marker)
    if ordinary(marker, 4096) != canonical(authority):
        raise ValueError("workspace binding marker is missing or changed")
    filesystem = native_filesystem(root)
    if create:
        probe = root / (".filename-probe:" + binding["workspace_id"])
        data = b"geoforge-native-linux-filename-probe\n"
        created = False
        try:
            with probe.open("xb") as stream:
                created = True
                stream.write(data)
            if ordinary(probe) != data:
                raise ValueError("native filename round trip failed")
        finally:
            if created and probe.is_file() and not probe.is_symlink() and ordinary(probe) == data:
                probe.unlink()
    info = root.stat()
    observed.update(workspace=str(root), workspace_id=binding["workspace_id"],
                    filesystem=filesystem, workspace_device=info.st_dev,
                    workspace_inode=info.st_ino, marker_sha256=digest(canonical(authority)))
    return root


def relative(root, value, *, existing=False):
    if not isinstance(value, str) or not value or "\0" in value or "\\" in value:
        raise ValueError("file path must be a nonempty relative POSIX path")
    rel = PurePosixPath(value)
    if rel.is_absolute() or any(part in {".", ".."} for part in value.split("/")):
        raise ValueError("file path escapes the runtime workspace")
    result = root.joinpath(*rel.parts)
    no_links(result)
    if existing and not result.exists():
        raise ValueError("runtime file does not exist")
    return result


def contained(root, value):
    path = Path(value)
    if not path.is_absolute() or str(path) != value or not path.is_relative_to(root):
        raise ValueError("working directory must be an absolute bound workspace path")
    no_links(path)
    if not path.is_dir():
        raise ValueError("working directory does not exist")
    return path


def write_files(root, files):
    if not isinstance(files, dict) or not files or len(files) > MAX_FILES:
        raise ValueError("invalid file batch")
    pending, total = [], 0
    for name, encoded in files.items():
        path = relative(root, name)
        if path == root / MARKER:
            raise ValueError("binding marker cannot be overwritten")
        data = base64.b64decode(encoded, validate=True)
        total += len(data)
        if len(data) > MAX_FILE or total > 16 * 1024 * 1024:
            raise ValueError("file batch exceeds byte limit")
        if path.exists():
            if ordinary(path) != data:
                raise ValueError(f"file already exists with different bytes: {name}")
        pending.append((name, path, data))
    result = {}
    for name, path, data in pending:
        path.parent.mkdir(parents=True, exist_ok=True)
        no_links(path)
        if not path.exists():
            with path.open("xb") as stream:
                stream.write(data)
        if ordinary(path) != data:
            raise ValueError("file changed while staging")
        result[name] = {"bytes": len(data), "sha256": digest(data)}
    return result


def read_files(root, names):
    if not isinstance(names, list) or not names or len(names) > MAX_FILES or len(set(names)) != len(names):
        raise ValueError("invalid read batch")
    result, total = {}, 0
    for name in names:
        data = ordinary(relative(root, name, existing=True))
        total += len(data)
        if total > 16 * 1024 * 1024:
            raise ValueError("file batch exceeds byte limit")
        result[name] = {"data": base64.b64encode(data).decode("ascii"),
                        "bytes": len(data), "sha256": digest(data)}
    return result


def descendants():
    """Only this supervisor's descendants, including adopted detached workers."""
    rows = {}
    for item in Path("/proc").iterdir():
        if not item.name.isdecimal():
            continue
        try:
            fields = (item / "stat").read_text().rsplit(") ", 1)[1].split()
            rows[int(item.name)] = (int(fields[1]), fields[0], fields[19])
        except (OSError, ValueError, IndexError):
            continue
    owned, frontier = {}, {os.getpid()}
    while frontier:
        children = {pid for pid, row in rows.items() if row[0] in frontier and pid not in owned}
        owned.update({pid: rows[pid] for pid in children})
        frontier = children
    return owned


def signal_descendants(sig):
    for pid, row in sorted(descendants().items(), reverse=True):
        if row[1] == "Z":
            continue
        try:
            current = Path(f"/proc/{pid}/stat").read_text().rsplit(") ", 1)[1].split()
            if current[19] == row[2]:  # do not signal a reused process identifier
                os.kill(pid, sig)
        except (ProcessLookupError, FileNotFoundError):
            pass


def stop_group(proc):
    signal_descendants(signal.SIGTERM)
    deadline = time.monotonic() + 2
    while any(row[1] != "Z" for row in descendants().values()) and time.monotonic() < deadline:
        time.sleep(.05)
    signal_descendants(signal.SIGKILL)
    proc.wait(timeout=5)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            while os.waitpid(-1, os.WNOHANG)[0]:
                pass
        except ChildProcessError:
            pass
        remaining = descendants()
        if not remaining:
            return
        time.sleep(.05)
    raise RuntimeError("guest process-tree termination could not be confirmed")


def run(root, request, observed):
    argv, env = request.get("argv"), request.get("env", {})
    if (not isinstance(argv, list) or not argv or len(argv) > 128
            or any(not isinstance(v, str) or not v or len(v) > 8192 or "\0" in v for v in argv)):
        raise ValueError("invalid argv")
    cwd = contained(root, request["cwd"])
    if not isinstance(env, dict) or len(env) > 128:
        raise ValueError("invalid environment")
    clean = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": observed["home"],
             "USER": observed["user"], "LOGNAME": observed["user"], "LANG": "C.UTF-8"}
    for key, value in env.items():
        if (not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key)
                or not isinstance(value, str) or len(value) > 8192 or "\0" in value
                or key in {"HOME", "USER", "LOGNAME", "WSLENV", "WSL_INTEROP", "LD_PRELOAD"}):
            raise ValueError("invalid or forbidden environment override")
        if key in {"PATH", "LD_LIBRARY_PATH", "PYTHONPATH"}:
            for entry in value.split(":"):
                p = Path(entry)
                if not p.is_absolute() or not any(p == base or p.is_relative_to(base)
                        for base in (root, Path("/usr"), Path("/bin"), Path("/lib"), Path("/lib64"))):
                    raise ValueError("environment path is outside the bound runtime/system roots")
        clean[key] = value
    name = Path(argv[0]).name.lower()
    if name in {"sh", "bash", "dash", "zsh", "ksh", "fish", "sudo", "su",
                "wsl", "wsl.exe", "cmd.exe", "powershell.exe", "pwsh"}:
        raise ValueError("shell/elevation/interop launch is not a runtime operation")
    if "/" in argv[0]:
        executable = Path(argv[0])
        if not executable.is_absolute() or not any(executable.is_relative_to(base)
                for base in (root, Path("/usr"), Path("/bin"), Path("/sbin"))):
            raise ValueError("executable is outside the runtime/system roots")
    timeout = request.get("timeout")
    if not isinstance(timeout, (float, int)) or isinstance(timeout, bool) or not 0 < timeout <= 86400:
        raise ValueError("timeout must be between zero and 86400 seconds")
    data = base64.b64decode(request.get("stdin", ""), validate=True)
    if len(data) > 65536:
        raise ValueError("stdin exceeds byte limit")
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
        raise OSError(ctypes.get_errno(), "cannot supervise detached guest descendants")
    proc = subprocess.Popen(argv, cwd=str(cwd), env=clean, start_new_session=True,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    emit({"event": "started", "request_id": request["request_id"], "pid": proc.pid,
          "argv": argv, "cwd": str(cwd)})
    cancel = threading.Event()
    def control():
        while True:
            line = sys.stdin.buffer.readline(4097)
            if not line:
                cancel.set()
                return
            try:
                value = json.loads(line)
                if value == {"cancel": request["request_id"]}:
                    cancel.set()
                    return
            except (ValueError, UnicodeError):
                cancel.set()
                return
    threading.Thread(target=control, daemon=True).start()
    def feed():
        try:
            proc.stdin.write(data)
            proc.stdin.close()
        except (BrokenPipeError, OSError):
            pass
    threading.Thread(target=feed, daemon=True).start()
    streams = {proc.stdout.fileno(): (proc.stdout, "stdout"), proc.stderr.fileno(): (proc.stderr, "stderr")}
    counts = {"stdout": 0, "stderr": 0}
    deadline, status = time.monotonic() + timeout, "finished"
    try:
        while streams or proc.poll() is None:
            if cancel.is_set():
                status = "stopped"
                stop_group(proc)
                break
            if time.monotonic() >= deadline:
                status = "timed_out"
                stop_group(proc)
                break
            ready, _, _ = select.select(list(streams), [], [], .05)
            for fd in ready:
                stream, channel = streams[fd]
                block = os.read(fd, 16384)
                if not block:
                    del streams[fd]
                    continue
                counts[channel] += len(block)
                if counts[channel] > MAX_OUTPUT:
                    status = "output_limit"
                    stop_group(proc)
                    break
                emit({"event": channel, "data": base64.b64encode(block).decode("ascii")})
            if status == "output_limit":
                break
        # Even a normally exited parent must not leave detached-in-group workers.
        stop_group(proc)
        return {"status": status, "returncode": proc.returncode, "process_started": True,
                "group_stopped": True, "stdout_bytes": counts["stdout"], "stderr_bytes": counts["stderr"]}
    finally:
        if proc.poll() is None or descendants():
            stop_group(proc)


def main():
    request_id = None
    try:
        line = sys.stdin.buffer.readline(MAX_REQUEST + 1)
        if len(line) > MAX_REQUEST or not line.endswith(b"\n"):
            raise ValueError("invalid or oversized request")
        request = json.loads(line)
        request_id = request["request_id"]
        if request.get("protocol") != PROTOCOL or not re.fullmatch(r"[0-9a-f]{32}", request_id):
            raise ValueError("invalid request identity")
        observed = identity()
        if request["op"] == "discover":
            result = observed
        else:
            root = workspace(request["binding"], observed, create=request["op"] == "prepare")
            if request["op"] in {"prepare", "inspect"}:
                result = observed
            elif request["op"] == "write_files":
                result = write_files(root, request["files"])
            elif request["op"] == "read_files":
                result = read_files(root, request["paths"])
            elif request["op"] == "run":
                result = run(root, request, observed)
            else:
                raise ValueError("unknown operation")
        emit({"event": "result", "request_id": request_id, "ok": True,
              "identity": observed, "result": result})
    except Exception as exc:
        emit({"event": "result", "request_id": request_id, "ok": False,
              "error": f"{type(exc).__name__}: {exc}"})
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
