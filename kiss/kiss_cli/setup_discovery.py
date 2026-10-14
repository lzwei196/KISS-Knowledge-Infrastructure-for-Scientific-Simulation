"""A bounded host discovery pass, not an agent filesystem sandbox.

All inspection of external locations happens in a disposable supervised child.
The result describes a finite search scope; it never proves machine-wide absence.
"""
from __future__ import annotations

from itertools import islice
import json
import os
from pathlib import Path
import re
import stat
import sys
import time
import uuid


SCHEMA_VERSION = 1
MAX_BYTES = 64 * 1024
MAX_ENTRIES = 512
MAX_RESULTS = 24
MAX_HINTS = 12
MAX_ROOTS = 64
MAX_SECONDS = 8.0


def _document(path: Path) -> dict:
    with path.open("rb") as handle:
        raw = handle.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("discovery document exceeds 64 KiB")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("discovery document must be an object")
    return value


def _encode(value: dict) -> bytes:
    result = json.dumps(value, ensure_ascii=False, allow_nan=False,
                        separators=(",", ":")).encode("utf-8")
    if len(result) > MAX_BYTES:
        raise ValueError("discovery document exceeds 64 KiB")
    return result


def _report(request: dict, *, state="complete", reason="") -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "request_id": request["request_id"], "model": request["model"],
        "candidates": [],
        "scope": {"recursive": False, "indexed": False,
                  "hints": request["hints"],
                  "sources": ["exact selected paths", "exact PATH names",
                              "direct conventional-location entries"]},
        "limits": {"timeout_seconds": request["timeout"], "entries": MAX_ENTRIES,
                   "results": request["limit"], "hints": MAX_HINTS,
                   "roots": MAX_ROOTS, "document_bytes": MAX_BYTES},
        "stats": {"entries_checked": 0, "roots_checked": 0,
                  "candidates_found": 0, "elapsed_seconds": 0.0},
        "state": state, "complete": state == "complete", "reason": reason,
        "checked_at": time.time(),
    }


def _hints(model, hints) -> tuple[list[str], bool]:
    names, cut = [], False
    # Bound iteration as well as the number of accepted names.
    raw_names = [str(model), *islice(hints, MAX_HINTS + 1)]
    for raw in raw_names:
        if raw is None:
            continue
        raw = re.split(r"[/\\]", str(raw))[-1].strip()
        name = "".join(c for c in raw if c.isalnum() or c in "_.+-")
        if not name or name in {".", ".."}:
            continue
        if len(name) > 128:
            cut = True
            continue
        if name.casefold() in {item.casefold() for item in names}:
            continue
        if len(names) >= MAX_HINTS:
            cut = True
            break
        names.append(name)
    if len(raw_names) > MAX_HINTS + 1:
        cut = True
    return names, cut


def _command(request: Path, result: Path) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "_setup-discovery-worker", str(request), str(result)]
    # Never import a worker from its agent-writable cwd. Isolated execution of
    # this host-owned, stdlib-only file also ignores workspace shadow modules.
    return [sys.executable, "-I", "-S", str(Path(__file__).absolute()), str(request), str(result)]


def _valid_result(result: dict, request: dict) -> bool:
    expected = _report(request)
    candidates, stats = result.get("candidates"), result.get("stats")
    return bool(
        result.get("schema_version") == SCHEMA_VERSION and
        result.get("request_id") == request["request_id"] and
        result.get("model") == request["model"] and
        isinstance(result.get("state"), str) and
        result.get("state") in {"complete", "limited", "failed"} and
        result.get("complete") is (result.get("state") == "complete") and
        result.get("scope") == expected["scope"] and
        result.get("limits") == expected["limits"] and
        isinstance(result.get("reason"), str) and
        isinstance(result.get("checked_at"), (int, float)) and
        isinstance(candidates, list) and len(candidates) <= request["limit"] and
        all(isinstance(item, str) and Path(item).is_absolute() for item in candidates) and
        isinstance(stats, dict) and
        all(type(stats.get(key)) is int and 0 <= stats[key] <= maximum
            for key, maximum in (("entries_checked", MAX_ENTRIES), ("roots_checked", MAX_ROOTS),
                                 ("candidates_found", request["limit"]))) and
        stats["candidates_found"] == len(candidates) and
        isinstance(stats.get("elapsed_seconds"), (int, float)))


def discover(model, hints=(), *, root, existing_paths=(), limit=24, timeout=8,
             stop=None, turn_id=None) -> dict:
    """Return candidates within one bounded scope, or raise InstallStopped.

    ``root`` is the already selected writable setup workspace. External path
    resolution/stat/listing belongs to the worker, never the HTTP thread.
    """
    from . import execution, install

    root = Path(root).absolute()
    names, cut = _hints(model, hints)
    selected = [str(item) for item in islice(existing_paths, MAX_RESULTS + 1)]
    cut = cut or len(selected) > MAX_RESULTS
    request = {"schema_version": SCHEMA_VERSION, "request_id": uuid.uuid4().hex,
               "model": str(model)[:128], "hints": names,
               "existing_paths": selected[:MAX_RESULTS],
               "limit": max(1, min(int(limit), MAX_RESULTS)),
               "timeout": max(0.05, min(float(timeout), MAX_SECONDS)),
               "input_limited": cut}

    def cancelled():
        if ((stop is not None and stop()) or
                execution.stop_requested(root, turn_id=turn_id)):
            raise install.InstallStopped("Stopped during installation discovery.")

    cancelled()
    try:
        payload = _encode(request)
    except (ValueError, UnicodeError) as error:
        return _report(request, state="limited", reason=str(error))
    # Deliberately omit agent credentials and arbitrary Python startup settings.
    keys = {"PATH", "PATHEXT", "SystemRoot", "SYSTEMROOT", "WINDIR", "HOME",
            "USERPROFILE", "ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA",
            "TEMP", "TMP", "LANG", "LC_ALL"}
    env = {key: value for key, value in os.environ.items()
           if key.upper() in {item.upper() for item in keys}}
    env.update(PYTHONPATH=str(Path(__file__).absolute().parent.parent),
               PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
    env = execution.turn_environment(root, turn_id=turn_id, env=env)
    started = time.monotonic()
    try:
        with install.scratch_directory(".geoforge-discovery-", root) as folder:
            input_path, output_path = Path(folder) / "request.json", Path(folder) / "result.json"
            input_path.write_bytes(payload)
            proc = execution.run_process(_command(input_path, output_path), cwd=root,
                env=env, timeout=request["timeout"], project=root, stop=stop,
                turn_id=turn_id, encoding="utf-8")
            cancelled()
            if proc.status in {"stopped", "interrupted"}:
                raise install.InstallStopped("Stopped during installation discovery.")
            if proc.status == "timed_out":
                result = _report(request, state="limited",
                    reason="Discovery time limit reached; no machine-wide absence was established.")
            elif proc.status != "succeeded":
                result = _report(request, state="failed", reason="Discovery worker did not complete.")
            else:
                result = _document(output_path)
                if not _valid_result(result, request):
                    raise ValueError("invalid or stale discovery result")
    except install.InstallStopped:
        raise
    except (OSError, ValueError, UnicodeError) as error:
        cancelled()
        result = _report(request, state="failed",
                         reason=f"Cannot read discovery evidence: {type(error).__name__}.")
    result["stats"]["elapsed_seconds"] = round(time.monotonic() - started, 3)
    return result


def _conventional_roots() -> list[Path]:
    if os.name == "nt":
        roots = [Path(os.environ[key]) for key in ("ProgramFiles", "ProgramFiles(x86)")
                 if os.environ.get(key)]
        if os.environ.get("LOCALAPPDATA"):
            roots.append(Path(os.environ["LOCALAPPDATA"]) / "Programs")
        return roots
    roots = [Path("/usr/local/bin"), Path("/usr/bin"), Path("/opt")]
    if sys.platform == "darwin":
        roots += [Path("/opt/homebrew/bin"), Path("/Applications"), Path.home() / "Applications"]
    return roots


class _LimitReached(Exception):
    pass


def _scan(request: dict) -> dict:
    result = _report(request)
    stats, candidates = result["stats"], result["candidates"]
    reasons = ["Input hint or selected-path limit reached."] if request["input_limited"] else []
    deadline = time.monotonic() + request["timeout"]
    home = Path.home().resolve()
    roots_seen, root_operations, candidate_keys = set(), set(), set()
    names = request["hints"]
    tokens = [re.sub(r"[^\w]", "", name.casefold()) for name in names]

    def visit():
        if stats["entries_checked"] >= MAX_ENTRIES:
            reasons.append("Discovery entry limit reached.")
            raise _LimitReached
        if time.monotonic() >= deadline:
            reasons.append("Discovery time limit reached.")
            raise _LimitReached
        stats["entries_checked"] += 1

    def add(path, *, selected=False, exact_executable=False):
        visit()
        path = Path(path).expanduser()
        if not path.is_absolute():
            if selected:
                reasons.append("A selected path was not absolute.")
            return
        try:
            # Reparse directory candidates are never traversed or promoted to
            # an external read/exec grant. Exact executable links are retained
            # under their original launcher spelling, matching runtime binding.
            info = path.lstat()
            reparse = bool(getattr(info, "st_file_attributes", 0) & 0x400)
            linked = stat.S_ISLNK(info.st_mode) or reparse
            if linked and not (exact_executable and path.is_file()):
                if selected:
                    reasons.append("A selected link or junction was excluded from discovery.")
                return
            resolved = path.resolve()
            if resolved == home or resolved == Path(resolved.anchor):
                if selected:
                    reasons.append("A selected disk/home root was refused.")
                return
            if not (path.is_file() if exact_executable else path.is_file() or path.is_dir()):
                return
            if exact_executable and os.name != "nt" and not os.access(path, os.X_OK):
                return
        except FileNotFoundError:
            return
        except (OSError, RuntimeError):
            reasons.append("Some candidate paths could not be inspected.")
            return
        shown = str(path.absolute()) if exact_executable else str(resolved)
        key = os.path.normcase(shown)
        if key in candidate_keys:
            return
        candidates.append(shown)
        candidate_keys.add(key)
        if len(candidates) >= request["limit"]:
            reasons.append("Discovery result limit reached.")
            raise _LimitReached

    def root_once(path, operation):
        path = Path(path).expanduser()
        if not path.is_absolute():
            return None
        resolved = path.resolve()
        if resolved == home or resolved == Path(resolved.anchor):
            return None
        key = os.path.normcase(str(resolved))
        if (key, operation) in root_operations:
            return None
        if key not in roots_seen and len(roots_seen) >= MAX_ROOTS:
            reasons.append("Discovery root limit reached.")
            raise _LimitReached
        roots_seen.add(key)
        root_operations.add((key, operation))
        stats["roots_checked"] = len(roots_seen)
        return resolved

    try:
        for path in request["existing_paths"]:
            add(path, selected=True)
        path_parts = os.environ.get("PATH", "").split(os.pathsep)
        suffixes = [""]
        if os.name == "nt":
            suffixes += [item.lower() for item in os.environ.get("PATHEXT", ".EXE;.CMD;.BAT").split(";")[:8]
                         if re.fullmatch(r"\.[A-Za-z0-9]{1,8}", item)]
        for raw in path_parts:
            if not raw.strip():
                continue
            try:
                base = root_once(raw.strip('"'), "exact-path")
                if base is None:
                    continue
                for name in names:
                    for suffix in suffixes:
                        add(base / (name if name.lower().endswith(suffix) else name + suffix),
                            exact_executable=True)
            except (OSError, RuntimeError):
                reasons.append("Some PATH locations could not be inspected.")
        # Conventional roots use one directory level only. Every enumerated
        # entry consumes budget, including names that do not match anything.
        for raw in _conventional_roots():
            try:
                base = root_once(raw, "direct-listing")
                if base is None:
                    continue
                with os.scandir(base) as entries:
                    for entry in entries:
                        visit()
                        compact = re.sub(r"[^\w]", "", entry.name.casefold())
                        if any(token and token in compact for token in tokens):
                            add(Path(entry.path))
            except FileNotFoundError:
                continue
            except (OSError, RuntimeError):
                reasons.append("Some conventional locations could not be inspected.")
    except _LimitReached:
        pass
    stats["candidates_found"] = len(candidates)
    if reasons:
        result.update(state="limited", complete=False, reason=" ".join(dict.fromkeys(reasons)))
    else:
        result["reason"] = "Known-location scope exhausted; this does not establish machine-wide absence."
    # Very long Windows/UNC paths must not turn a result cap into unbounded IPC.
    while True:
        try:
            _encode(result)
            return result
        except ValueError:
            if not candidates:
                raise
            candidates.pop()
            stats["candidates_found"] = len(candidates)
            result.update(state="limited", complete=False, reason="Discovery result document limit reached.")


def worker_main(input_path, output_path) -> int:
    """Internal source/frozen entry; never prints unbounded paths or tracebacks."""
    try:
        source, destination = Path(input_path), Path(output_path)
        if source.parent.resolve() != destination.parent.resolve() or source == destination:
            return 2
        request = _document(source)
        if (request.get("schema_version") != SCHEMA_VERSION or
                not re.fullmatch(r"[a-f0-9]{32}", str(request.get("request_id", ""))) or
                not isinstance(request.get("model"), str) or len(request["model"]) > 128 or
                not isinstance(request.get("input_limited"), bool) or
                not isinstance(request.get("hints"), list) or len(request["hints"]) > MAX_HINTS or
                not all(isinstance(item, str) and 0 < len(item) <= 128 and
                        item not in {".", ".."} and
                        all(c.isalnum() or c in "_.+-" for c in item)
                        for item in request["hints"]) or
                not isinstance(request.get("existing_paths"), list) or
                len(request["existing_paths"]) > MAX_RESULTS or
                not all(isinstance(item, str) for item in request["existing_paths"]) or
                not 1 <= request["limit"] <= MAX_RESULTS or
                not 0 < request["timeout"] <= MAX_SECONDS):
            return 2
        destination.write_bytes(_encode(_scan(request)))
        return 0
    except Exception:
        return 2


if __name__ == "__main__":
    raise SystemExit(worker_main(*sys.argv[1:]) if len(sys.argv) == 3 else 2)
