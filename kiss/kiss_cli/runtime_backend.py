"""Host-owned named-user WSL transport; callers retain execution authority.

No operation accepts a shell command, changes a distro, installs software or
grants readiness. Persisted selection/approval must be checked by the caller.
"""
from __future__ import annotations

import base64
from dataclasses import asdict, dataclass, field
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import queue
import re
import subprocess
import sys
import threading
import time
import uuid

PROTOCOL = "geoforge.wsl-worker.v1"
MAX_REQUEST = 24 * 1024 * 1024
MAX_LINE = 24 * 1024 * 1024
MAX_OUTPUT = 8 * 1024 * 1024


class RuntimeBackendError(RuntimeError):
    def __init__(self, message, *, process_started=None, evidence=None):
        super().__init__(message)
        self.process_started = process_started
        self.evidence = evidence or {}


@dataclass(frozen=True)
class WSLBinding:
    distro: str
    user: str
    workspace: str
    workspace_id: str
    python: str = "/usr/bin/python3"

    def __post_init__(self):
        if (not isinstance(self.distro, str) or not self.distro or len(self.distro) > 128
                or self.distro.startswith("-") or any(ord(c) < 32 for c in self.distro)):
            raise ValueError("invalid named WSL distribution")
        if not isinstance(self.user, str) or not re.fullmatch(r"[a-z_][a-z0-9_-]{0,63}\$?", self.user) or self.user == "root":
            raise ValueError("a named non-root Linux user is required")
        if not re.fullmatch(r"[0-9a-f]{32}", self.workspace_id):
            raise ValueError("workspace_id must be a fresh UUID hex value")
        for label, value in (("workspace", self.workspace), ("python", self.python)):
            if (not isinstance(value, str) or not PurePosixPath(value).is_absolute()
                    or "\\" in value or "\0" in value or any(p in {".", ".."} for p in value.split("/"))):
                raise ValueError(f"{label} must be an absolute canonical POSIX path")
        if not self.workspace.endswith("/.local/share/geoforge/runtimes/" + self.workspace_id):
            raise ValueError("workspace must use the binding-owned Linux runtime directory")
        if not self.python.startswith(("/usr/bin/", "/usr/local/bin/")):
            raise ValueError("worker Python must be a system Linux interpreter")


@dataclass
class RunResult:
    status: str
    returncode: int | None
    stdout: str = ""
    stderr: str = ""
    detail: str = ""
    evidence: dict = field(default_factory=dict)
    process_started: bool | None = False


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def application_source_root():
    """Locate checked Linux source, including when host modules live in PYZ.

    A frozen Windows executable cannot send its bytecode archive to a Linux
    interpreter. Its build carries a separate source payload; never fall back
    to the checkout, working directory or an installed Python package.
    """
    if getattr(sys, "frozen", False):
        bundle = getattr(sys, "_MEIPASS", None)
        if not bundle:
            raise RuntimeBackendError("Frozen application has no bundled Linux source location")
        return Path(bundle).resolve() / "linux-runtime"
    return Path(__file__).resolve().parents[2]


def _source_file(name):
    return application_source_root() / "kiss" / "kiss_cli" / name


def implementation_digest():
    h = hashlib.sha256()
    for file in (_source_file("runtime_backend.py"), _source_file("_wsl_worker.py")):
        h.update(file.name.encode())
        h.update(file.read_bytes())
    return h.hexdigest()


def binding_identity(binding):
    return hashlib.sha256(_canonical({"binding": asdict(binding), "implementation": implementation_digest()})).hexdigest()


def _command(binding):
    if os.name != "nt":
        raise RuntimeBackendError("WSL transport requires the Windows host")
    executable = Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32" / "wsl.exe"
    if not executable.is_file():
        raise RuntimeBackendError("Windows WSL executable is unavailable")
    source = _source_file("_wsl_worker.py").read_text(encoding="utf-8")
    return [str(executable), "--distribution", binding.distro, "--user", binding.user,
            "--exec", binding.python, "-I", "-S", "-c", source]


def _local_command(binding):
    if sys.platform != "linux":
        raise RuntimeBackendError("local guest transport requires Linux")
    source = _source_file("_wsl_worker.py").read_text(encoding="utf-8")
    return [binding.python, "-I", "-S", "-c", source]


def _exchange(binding, op, *, transport_timeout=60, stop=None, _local=False, **payload):
    if stop is not None and stop():
        raise RuntimeBackendError("stopped before starting WSL")
    request_id = uuid.uuid4().hex
    request = {"protocol": PROTOCOL, "request_id": request_id, "op": op,
               "binding": asdict(binding), **payload}
    raw = _canonical(request) + b"\n"
    if len(raw) > MAX_REQUEST:
        raise RuntimeBackendError("runtime request exceeds the byte limit")
    implementation = implementation_digest()
    command = _local_command(binding) if _local else _command(binding)
    if implementation_digest() != implementation:
        raise RuntimeBackendError("runtime implementation changed before launch", process_started=False)
    # No host API credentials, proxies, PYTHONPATH or Windows PATH enter Linux.
    env = {k: v for k, v in os.environ.items()
           if k.upper() in {"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "USERPROFILE", "LOCALAPPDATA"}}
    proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, env=env,
                            **({"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)} if os.name == "nt" else {}))
    events = queue.Queue()
    def stdout_reader():
        try:
            while True:
                line = proc.stdout.readline(MAX_LINE + 1)
                if not line:
                    break
                if len(line) > MAX_LINE:
                    events.put(("protocol_error", "oversized worker response"))
                    return
                events.put(("line", line))
        finally:
            events.put(("eof", None))
    stderr_parts, stderr_size = [], [0]
    def stderr_reader():
        while True:
            block = proc.stderr.read(4096)
            if not block:
                return
            stderr_size[0] += len(block)
            if stderr_size[0] <= 65536:
                stderr_parts.append(block)
    threading.Thread(target=stdout_reader, daemon=True).start()
    threading.Thread(target=stderr_reader, daemon=True).start()
    started, result, failure = None, None, None
    streams = {"stdout": bytearray(), "stderr": bytearray()}
    cancelled, deadline = False, time.monotonic() + transport_timeout
    try:
        proc.stdin.write(raw)
        proc.stdin.flush()
        while result is None:
            now = time.monotonic()
            if not cancelled and ((stop is not None and stop()) or now >= deadline):
                cancelled = True
                try:
                    proc.stdin.write(_canonical({"cancel": request_id}) + b"\n")
                    proc.stdin.flush()
                except (BrokenPipeError, OSError):
                    pass
                deadline = now + 10
            elif cancelled and now >= deadline:
                failure = "guest cancellation was not acknowledged; guest state is uncertain"
                break
            try:
                kind, value = events.get(timeout=.05)
            except queue.Empty:
                continue
            if kind == "eof":
                failure = "worker disconnected before a final result; guest state is uncertain"
                break
            if kind == "protocol_error":
                failure = value
                break
            event = json.loads(value)
            name = event.get("event")
            if name == "started":
                if started is not None or event.get("request_id") != request_id:
                    raise RuntimeBackendError("invalid worker start receipt")
                started = event
            elif name in streams:
                if started is None:
                    raise RuntimeBackendError("worker output preceded its start receipt")
                block = base64.b64decode(event["data"], validate=True)
                streams[name].extend(block)
                if len(streams[name]) > MAX_OUTPUT:
                    raise RuntimeBackendError("worker output exceeds byte limit")
            elif name == "result":
                if event.get("request_id") != request_id:
                    raise RuntimeBackendError("worker result belongs to another request")
                result = event
            else:
                raise RuntimeBackendError("unknown worker response")
        if failure:
            raise RuntimeBackendError(failure)
        if not result.get("ok"):
            raise RuntimeBackendError(result.get("error") or "guest worker failed")
        observed = result.get("identity") or {}
        if (observed.get("protocol") != PROTOCOL or observed.get("user") != binding.user
                or observed.get("uid") in {None, 0}):
            raise RuntimeBackendError("worker identity does not match the bound Linux user")
        if op != "discover" and (observed.get("workspace") != binding.workspace
                                 or observed.get("workspace_id") != binding.workspace_id):
            raise RuntimeBackendError("worker result has a different workspace binding")
        if cancelled and op != "run":
            raise RuntimeBackendError("runtime operation exceeded its deadline or was stopped")
        if op == "run":
            process = result["result"]
            if (started is None or started.get("argv") != payload.get("argv")
                    or started.get("cwd") != payload.get("cwd")
                    or process.get("process_started") is not True
                    or process.get("group_stopped") is not True
                    or type(process.get("returncode")) is not int
                    or process.get("status") not in {"finished", "stopped", "timed_out", "output_limit"}):
                raise RuntimeBackendError("incomplete or mismatched process execution evidence")
            if process["status"] != "output_limit" and any(
                    process.get(name + "_bytes") != len(value) for name, value in streams.items()):
                raise RuntimeBackendError("process stream lengths do not match received bytes")
        if implementation_digest() != implementation:
            raise RuntimeBackendError("runtime implementation changed during this operation")
        return result["result"], {"binding_identity": binding_identity(binding),
                "implementation": implementation, "request_sha256": hashlib.sha256(raw).hexdigest(),
                "request_id": request_id, "identity": observed, "start": started,
                "host_cancel_requested": cancelled,
                "streams": {name: {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                            for name, data in streams.items()}}, streams
    except (RuntimeBackendError, ValueError, UnicodeError, KeyError, OSError) as exc:
        known = True if started is not None else (False if result is not None else None)
        diagnostic = b"".join(stderr_parts).decode("utf-8", "replace")[-2000:]
        raise RuntimeBackendError(f"runtime transport failed: {exc}" + ("; " + diagnostic if diagnostic else ""), process_started=known,
                evidence={"request_id": request_id, "start": started,
                          "host_cancel_requested": cancelled}) from exc
    finally:
        try:
            proc.stdin.close()  # EOF makes the worker stop its own child group.
        except (BrokenPipeError, OSError):
            pass
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()  # only our Windows client, never the distro
            proc.wait(timeout=5)


def prepare(binding: WSLBinding, *, _local=False):
    result, proof, _ = _exchange(binding, "prepare", _local=_local)
    return {**result, "identity_sha256": hashlib.sha256(_canonical(result)).hexdigest(), "transport": proof}


def inspect(binding: WSLBinding, *, _local=False):
    result, proof, _ = _exchange(binding, "inspect", _local=_local)
    return {**result, "identity_sha256": hashlib.sha256(_canonical(result)).hexdigest(), "transport": proof}


def write_files(binding: WSLBinding, files: dict[str, bytes], *, _local=False):
    if not isinstance(files, dict) or any(not isinstance(v, bytes) for v in files.values()):
        raise ValueError("files must map relative paths to bytes")
    encoded = {k: base64.b64encode(v).decode("ascii") for k, v in files.items()}
    result, proof, _ = _exchange(binding, "write_files", files=encoded, _local=_local)
    for name, data in files.items():
        if result.get(name) != {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}:
            raise RuntimeBackendError("staged file evidence does not match host bytes")
    return {"files": result, "transport": proof}


def read_files(binding: WSLBinding, paths: list[str], *, _local=False):
    result, _proof, _ = _exchange(binding, "read_files", paths=paths, _local=_local)
    if set(result) != set(paths):
        raise RuntimeBackendError("read response does not match requested files")
    decoded = {}
    for name, record in result.items():
        data = base64.b64decode(record["data"], validate=True)
        if len(data) != record["bytes"] or hashlib.sha256(data).hexdigest() != record["sha256"]:
            raise RuntimeBackendError("read response bytes do not match their evidence")
        decoded[name] = {**record, "data": data}
    return decoded


def run(binding: WSLBinding, argv, *, cwd, env=None, timeout=60, stop=None, stdin=None, _local=False):
    if not isinstance(argv, (list, tuple)) or not argv or any(not isinstance(arg, str) for arg in argv):
        raise ValueError("argv must be an explicit list of strings")
    if stdin is not None and not isinstance(stdin, bytes):
        raise ValueError("stdin must be exact bytes")
    if stop is not None and stop():
        return RunResult("stopped", None, detail="stopped before starting WSL", process_started=False)
    try:
        result, proof, streams = _exchange(binding, "run", transport_timeout=float(timeout) + 10, stop=stop,
                argv=list(argv), cwd=str(cwd), env=dict(env or {}),
                stdin=base64.b64encode(stdin or b"").decode("ascii"), _local=_local,
                **{"timeout": float(timeout)})
    except RuntimeBackendError as exc:
        return RunResult("transport_error", None, detail=str(exc), evidence=exc.evidence,
                         process_started=exc.process_started)
    return RunResult(result["status"], result["returncode"],
                     streams["stdout"].decode("utf-8", "replace"),
                     streams["stderr"].decode("utf-8", "replace"),
                     evidence={**proof, "process": result},
                     process_started=result["process_started"])


class LocalExecutor:
    """Same worker protocol inside the bound Linux sidecar; never calls WSL."""
    @staticmethod
    def prepare(binding):
        return prepare(binding, _local=True)

    @staticmethod
    def inspect(binding):
        return inspect(binding, _local=True)

    @staticmethod
    def run(binding, argv, **kwargs):
        return run(binding, argv, _local=True, **kwargs)

    @staticmethod
    def write_files(binding, files):
        return write_files(binding, files, _local=True)

    @staticmethod
    def read_files(binding, paths):
        return read_files(binding, paths, _local=True)
