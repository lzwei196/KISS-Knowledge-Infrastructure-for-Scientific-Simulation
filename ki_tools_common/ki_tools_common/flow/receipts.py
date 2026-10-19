"""flow.receipts — app-owned, signed proof of what was downloaded and what was run.

Plan v3 map A6. Field names follow the issue (`data-receipts/<item>.json`,
`model-runs/<run-id>.json`) plus the reviewers' additions (`plan_step_id`,
`approval_sha256`, `wrapper_pid`, `signature`). Where they overlap with the
self-improve loop's proven provenance columns (hydrocraft.db `test_runs`:
binary_path, binary_hash, exit_code, binary_actually_ran, output_files_count,
runtime_seconds, forcing_source) the same names are used, so phase 3 can feed
that table from a receipt.

Fail-closed run validity is adopted from chat's validation_ladder.run_validity
(L149-177): a run must AFFIRM it did not error and that its output is non-empty;
an unstated fact is a failure, and empty evidence is REJECT (result_validity_gate
L76-83). The dag-driven output checks are new (issue "模型执行与结果凭据").

Tamper evidence: receipts are written to `<project>/.geoforge/receipts/` by app
processes only and carry an HMAC-SHA256 over their canonical JSON with a
per-project key kept OUTSIDE the project (`keys_dir`, default
`$GEOFORGE_FLOW_KEYS` or `~/.config/geoforge/flow-keys`; a key dir inside the
project is refused). `verify()` is the only thing `evidence()` trusts.

Codex review (2026-08-30): `record_run` now REQUIRES `approval_sha256` and
`plan_step_id`; `evidence(project, plan, approval)` binds every receipt to the
CURRENT approval, to a selected KI and to a planned step, and requires every
executable step to have a verified, passed receipt; rank-1 aliases (CaMa's
`outflw`, `rivout`, …) and NetCDF rank-1 variable selection were added.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import secrets
import stat
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

RECEIPT_DIR = ".geoforge/receipts"
RUNS_SUB = "model-runs"
DATA_SUB = "data-receipts"
REGISTRY_DEFAULT = Path("/mnt/disk1/Hydrocraft_server/.flow_registry")


class ReceiptError(ValueError):
    """A receipt could not be written honestly (missing binding, bad key location)."""


# ---------------------------------------------------------------------------
# keys + signing
# ---------------------------------------------------------------------------

def keys_dir() -> Path:
    d = os.environ.get("GEOFORGE_FLOW_KEYS")
    return (Path(d) if d else Path.home() / ".config" / "geoforge" / "flow-keys").expanduser()


def project_id(project: Path) -> str:
    return hashlib.sha256(str(Path(project).resolve()).encode("utf-8")).hexdigest()[:24]


def _inside(p: Path, root: Path) -> bool:
    try:
        Path(p).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


def _key(project: Path, create: bool = True) -> bytes | None:
    d = keys_dir()
    if _inside(d, project):
        raise ReceiptError(f"flow key dir {d} is inside the project {project}; refusing — the key "
                           f"must live outside any agent-writable tree")
    p = d / f"{project_id(project)}.key"
    if p.is_file():
        return p.read_bytes()
    if not create:
        return None
    d.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    k = secrets.token_bytes(32)
    try:
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)   # exclusive: no race
    except FileExistsError:
        return p.read_bytes()
    with os.fdopen(fd, "wb") as f:
        f.write(k)
    return k


def _canonical(doc: dict) -> bytes:
    body = {k: v for k, v in doc.items() if k != "signature"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sign(project: Path, doc: dict) -> dict:
    k = _key(project, create=True)
    doc["signature"] = {"alg": "HMAC-SHA256", "key_id": project_id(project),
                        "value": hmac.new(k, _canonical(doc), "sha256").hexdigest()}
    return doc


def verify(project: Path, doc: dict) -> bool:
    if not isinstance(doc, dict):
        return False
    try:
        k = _key(project, create=False)
    except ReceiptError:
        return False
    sig = doc.get("signature") or {}
    if not isinstance(sig, dict):
        return False
    value = sig.get("value")
    if not k or sig.get("alg") != "HMAC-SHA256" or not isinstance(value, str) or not value \
            or sig.get("key_id") != project_id(project):
        return False
    try:
        expected = hmac.new(k, _canonical(doc), "sha256").hexdigest()
        return hmac.compare_digest(value, expected)
    except (TypeError, ValueError):
        return False


# ---------------------------------------------------------------------------
# server-side current-document registry
# ---------------------------------------------------------------------------

def registry_dir() -> Path:
    """App-owned registry outside the workspace; the agent guard protects this tree.

    Server: the fixed tree the guard hook protects. Desktop (no server tree): beside the
    receipt-signing keys under the user's config dir, the same way the key dir resolves.
    """
    configured = os.environ.get("GEOFORGE_FLOW_REGISTRY")
    if configured:
        return Path(configured).expanduser()
    if REGISTRY_DEFAULT.parent.is_dir():
        return REGISTRY_DEFAULT
    import sys as _sys
    if "kiss_cli" in _sys.modules or getattr(_sys, "frozen", False):
        return keys_dir().parent / "flow-registry"      # the desktop app: beside its signing keys
    # The server tree is missing (disk mismount): never fail open to an empty registry.
    raise RuntimeError(f"flow registry unavailable: {REGISTRY_DEFAULT.parent} is not mounted "
                       "and GEOFORGE_FLOW_REGISTRY is not set")


def registry_entry(project: Path) -> Path:
    ws = str(Path(project).resolve())
    return registry_dir() / (hashlib.sha1(ws.encode("utf-8")).hexdigest() + ".json")


def _signature_value(doc: dict) -> str | None:
    sig = (doc or {}).get("signature") if isinstance(doc, dict) else None
    value = sig.get("value") if isinstance(sig, dict) else None
    return value if isinstance(value, str) and len(value) == 64 else None


@contextmanager
def _registry_lock(stream):
    """Serialize registry writers on both Windows and POSIX, failing closed."""
    if os.name == "nt":
        import msvcrt
        # Windows byte-range locks also cover a byte beyond EOF. Use the same
        # byte for every writer and bound contention rather than dropping it.
        deadline = time.monotonic() + 30
        while True:
            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError as exc:
                if time.monotonic() >= deadline:
                    raise ReceiptError("flow registry lock unavailable") from exc
                time.sleep(0.05)
        try:
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _update_registry(project: Path, update) -> dict:
    """Lock, merge, and atomically replace one canonical workspace registry entry."""
    project = Path(project).resolve()
    root = registry_dir().resolve()
    if _inside(root, project):
        raise ReceiptError(f"flow registry {root} is inside project {project}; refusing")
    root.mkdir(parents=True, exist_ok=True)
    entry = registry_entry(project)
    lock_path = entry.with_suffix(entry.suffix + ".lock")
    lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    tmp: Path | None = None
    try:
        with os.fdopen(lock_fd, "r+b") as lock_file, _registry_lock(lock_file):
            if entry.exists():
                try:
                    current = json.loads(entry.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    raise ReceiptError(f"flow registry entry unreadable: {entry}") from exc
                if not isinstance(current, dict):
                    raise ReceiptError(f"flow registry entry is not an object: {entry}")
                registered_ws = current.get("ws")
                if registered_ws and Path(registered_ws).resolve() != project:
                    raise ReceiptError(f"flow registry workspace mismatch: {entry}")
            else:
                current = {}
            current.setdefault("schema_version", "1.0")
            current["ws"] = str(project)
            current.setdefault("current", {})
            if not isinstance(current["current"], dict):
                raise ReceiptError(f"flow registry current pointer is invalid: {entry}")
            updated = update(current)
            if not isinstance(updated, dict):
                raise ReceiptError("flow registry update did not return an object")
            updated["updated_at"] = time.time()
            tmp = entry.with_name(f".{entry.name}.{os.getpid()}.{secrets.token_hex(6)}.tmp")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(updated, fh, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, entry)
            tmp = None
            return updated
    finally:
        if tmp is not None:
            try:
                tmp.unlink()
            except OSError:
                pass


def publish_current(project: Path, kind: str, doc: dict | None) -> None:
    """Make one signed state/approval document current, or revoke it with ``None``."""
    if kind not in ("state", "approval"):
        raise ReceiptError(f"unsupported current-document kind: {kind}")
    value = None if doc is None else _signature_value(doc)
    if doc is not None and value is None:
        raise ReceiptError(f"cannot publish unsigned {kind} document")

    def _set(current: dict) -> dict:
        current["current"][kind] = value
        return current

    _update_registry(project, _set)


def register_workspace(project: Path, **metadata) -> None:
    """Add server metadata without overwriting current approval/state pointers."""
    def _register(current: dict) -> dict:
        for key, value in metadata.items():
            current.setdefault(key, value)
        return current

    _update_registry(project, _register)


def current_value(project: Path, kind: str) -> str | None:
    """Read the server-authoritative signature pointer; malformed entries fail closed."""
    if kind not in ("state", "approval"):
        return None
    entry = registry_entry(project)
    try:
        current = json.loads(entry.read_text(encoding="utf-8"))
        registered_ws = current.get("ws") if isinstance(current, dict) else None
        if not registered_ws or Path(registered_ws).resolve() != Path(project).resolve():
            return None
        pointers = current.get("current")
        value = pointers.get(kind) if isinstance(pointers, dict) else None
        return value if isinstance(value, str) and len(value) == 64 else None
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def current_matches(project: Path, kind: str, doc: dict) -> bool:
    """A signature is usable only while it is the registry's current signature."""
    value = _signature_value(doc)
    current = current_value(project, kind)
    return value is not None and current is not None and hmac.compare_digest(value, current)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _rel(path: Path, project: Path) -> str:
    path = Path(path)
    if _inside(path, project):
        return Path(path).resolve().relative_to(Path(project).resolve()).as_posix()
    return str(path)


def _file_entry(p: str | Path, project: Path) -> dict:
    path = Path(p)
    rel = _rel(path, project)
    if path.is_file():
        return {"path": rel, "sha256": sha256_file(path), "bytes": path.stat().st_size}
    return {"path": rel, "sha256": None, "bytes": None, "missing": True}


def _dir(project: Path, sub: str) -> Path:
    d = Path(project) / RECEIPT_DIR / sub
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write(project: Path, sub: str, name: str, doc: dict) -> Path:
    doc = sign(project, doc)
    p = _dir(project, sub) / f"{name}.json"
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)
    return p


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def upload_origin_dir(project: Path, *, create: bool = False) -> Path:
    """Protected host provenance, never project-supplied input metadata."""
    base = registry_dir()
    if _inside(base, project):
        raise ReceiptError("Upload origin registry must be outside the project")
    directory = base / "input-uploads" / project_id(project)
    for path in (base, base / "input-uploads", directory):
        if create:
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
        if path.exists() or path.is_symlink():
            info = path.lstat()
            if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode) or (
                    getattr(info, "st_file_attributes", 0) & 0x400):
                raise ReceiptError("Upload origin registry is not an ordinary directory")
    return directory


def _upload_file(project: Path, raw: str) -> dict:
    """Hash one ordinary upload with stable identity; links never gain provenance."""
    root = Path(project).resolve()
    if not isinstance(raw, str) or "\\" in raw or ":" in raw:
        raise ReceiptError("Invalid upload path")
    parts = raw.split("/")
    if (any(part in ("", ".", "..") for part in parts)
            or not (len(parts) == 3 and parts[:2] == ["inputs", "uploads"]
                    or len(parts) == 4 and parts[:2] == ["inputs", "user"])):
        raise ReceiptError("Upload must be in the exact browser input namespace")
    path = root.joinpath(*parts)

    def inspect():
        for candidate in (root, *[root.joinpath(*parts[:i]) for i in range(1, len(parts) + 1)]):
            info = candidate.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise ReceiptError("Upload path must not contain links or reparse points")
            if candidate != path and not stat.S_ISDIR(info.st_mode):
                raise ReceiptError("Upload parent is not an ordinary directory")
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ReceiptError("Upload must be an ordinary single-link file")
        if path.resolve() != path:
            raise ReceiptError("Upload path changed")
        return info

    def identity(info):
        return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)

    before = inspect()
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0))
    digest = hashlib.sha256()
    with os.fdopen(fd, "rb") as handle:
        opened = os.fstat(handle.fileno())
        if identity(opened) != identity(before) or not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
            raise ReceiptError("Upload changed before reading")
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
        after = os.fstat(handle.fileno())
        if identity(after) != identity(before) or after.st_nlink != 1:
            raise ReceiptError("Upload changed during reading")
    if identity(inspect()) != identity(before):
        raise ReceiptError("Upload changed after reading")
    return {"path": raw, "bytes": before.st_size, "sha256": digest.hexdigest()}


def record_user_upload(project: Path, path: Path, data: bytes, *, reconfirm: Path | None = None) -> None:
    """Called only after a browser upload; origin is neither approval nor validation.

    A filename collision still creates a new exclusive file. Only a fresh body
    can also reconfirm the exact original name, and only while its bytes match.
    There is no directory enrollment or automatic migration of existing inputs.
    """
    root = Path(project).resolve()
    expected = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    current = _upload_file(root, Path(path).absolute().relative_to(root).as_posix())
    if any(current[key] != value for key, value in expected.items()):
        raise ReceiptError("Saved upload differs from the browser body")
    entries = [current]
    if reconfirm is not None and Path(reconfirm) != Path(path):
        try:
            original = _upload_file(root, Path(reconfirm).absolute().relative_to(root).as_posix())
            if all(original[key] == value for key, value in expected.items()):
                entries.append(original)
        except (OSError, ValueError, RuntimeError):
            pass  # An unsafe or different collision remains untrusted and untouched.
    directory = upload_origin_dir(root, create=True)
    for entry in entries:
        # Recheck immediately before publication, including a reconfirmed name.
        if _upload_file(root, entry["path"]) != entry:
            raise ReceiptError("Upload changed before origin recording")
        doc = sign(root, {"kind": "browser-input-upload", "version": 1,
                          "project_id": project_id(root), "file": entry, "uploaded_at": _now()})
        target = directory / (hashlib.sha256(entry["path"].encode("utf-8")).hexdigest() + ".json")
        temporary = target.with_name(target.name + "." + secrets.token_hex(8) + ".tmp")
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(doc, handle, ensure_ascii=False, sort_keys=True)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)


def uploaded_input_files(project: Path) -> set[str]:
    """Intact authenticated upload-origin paths; never sufficient to produce results."""
    trusted: set[str] = set()
    try:
        directory = upload_origin_dir(project)
        paths = list(directory.glob("*.json"))
        if len(paths) > 4096:
            return trusted
    except (OSError, ValueError, RuntimeError):
        return trusted
    for path in paths:
        try:
            info = path.lstat()
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 8192
                    or stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400):
                continue
            doc = json.loads(path.read_text(encoding="utf-8"))
            if (not verify(project, doc) or doc.get("kind") != "browser-input-upload"
                    or type(doc.get("version")) is not int or doc["version"] != 1
                    or doc.get("project_id") != project_id(project)):
                continue
            entry = doc.get("file")
            if (not isinstance(entry, dict) or set(entry) != {"path", "bytes", "sha256"}
                    or path.stem != hashlib.sha256(entry["path"].encode("utf-8")).hexdigest()
                    or _upload_file(project, entry["path"]) != entry):
                continue
            trusted.add(entry["path"])
        except (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError):
            continue
    return trusted


# ---------------------------------------------------------------------------
# record
# ---------------------------------------------------------------------------

def selection_sha256(item: dict) -> str:
    """Bind acquisition evidence to item ID, source AND requirements.

    Excludes mutable progress/local paths. Unknown legacy selections cannot be
    reused across approvals; a source or scope change must be reviewed again.
    """
    selection = {k: item[k] for k in (
        "id", "dataset_id", "chosen_source", "requirements", "acquisition_id",
        "acquisition_request_sha256") if k in item}
    if not any(selection.get(k) for k in ("dataset_id", "chosen_source", "acquisition_id")):
        return ""
    # A conservative fingerprint: differing metadata never silently reuses bytes.
    return hashlib.sha256(_canonical(selection)).hexdigest()


def record_download(project: Path, *, item_id: str, source: str, request_url: str,
                    http_status: int | None, raw_files: list, approval_sha256: str,
                    processed_files: list | None = None, transform_tool: str | None = None,
                    units_before: dict | None = None, units_after: dict | None = None,
                    requested_at: str | None = None, plan_step_id: str | None = None,
                    inventory_item: dict | None = None, acquisition: dict | None = None,
                    recovery: dict | None = None, expected_files: dict | None = None) -> Path:
    """Issue host evidence. Recovery must pass the previously verified file entries.

    Check freshly collected entries against ``expected_files`` before signing so
    a concurrent file change cannot be promoted to trusted recovery evidence.
    """
    if not approval_sha256:
        raise ReceiptError("a download receipt must be bound to the current approval")
    doc = {
        "kind": "download", "item_id": item_id, "source": source, "request_url": request_url,
        "requested_at": requested_at or _now(), "http_status": http_status,
        "raw_files": [_file_entry(f, project) for f in raw_files],
        "processed_files": [_file_entry(f, project) for f in (processed_files or [])],
        "transform_tool": transform_tool, "units_before": units_before or {},
        "units_after": units_after or {},
        "plan_step_id": plan_step_id, "approval_sha256": approval_sha256,
        "wrapper_pid": os.getpid(), "recorded_at": _now(),
        "selection_sha256": selection_sha256(inventory_item or {}),
        "acquisition": acquisition or {},
    }
    if recovery is not None:
        doc["recovery"] = recovery
    if expected_files is not None:
        for field in ("raw_files", "processed_files"):
            if doc[field] != expected_files.get(field):
                raise ReceiptError("acquired files changed during recovery; refusing to sign new bytes")
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in item_id)[:80]
    return _write(project, DATA_SUB, safe, doc)


def record_run(project: Path, *, ki: str, executable: str, command: list[str], cwd: str,
               started_at: float, finished_at: float, exit_code: int | None,
               inputs: list, outputs: list, approval_sha256: str, plan_step_id: str,
               stdout_log: str | None = None, stderr_log: str | None = None,
               forcing_source: str | None = None, validation: dict | None = None,
               run_id: str | None = None, execution_status: str | None = None,
               process_started: bool | None = None, project_data_tool: dict | None = None,
               data_ki: dict | None = None, stdout_artifact: dict | None = None,
               declared_outputs: dict | None = None, input_snapshot: dict | None = None) -> Path:
    if not approval_sha256 or not plan_step_id:
        raise ReceiptError("a run receipt must name the approval it runs under and the plan step "
                           "it executes (codex review #2)")
    exe = Path(executable)
    rid = run_id or f"{ki}_{time.strftime('%Y%m%dT%H%M%S', time.localtime(started_at))}_" \
                    f"{secrets.token_hex(3)}"
    outs = [_file_entry(f, project) for f in outputs]
    if declared_outputs is not None:
        roles = {row["path"]: ("declared_json_report" if row["validation"] == "json_report_v1"
                             else "declared_scientific_result")
                 for row in declared_outputs.get("outputs", [])}
        for entry in outs:
            entry["output_role"] = roles.get(entry["path"], "supporting_execution_artifact")
    exe_sha = sha256_file(exe) if exe.is_file() else None
    doc = {
        "kind": "run", "run_id": rid, "ki": ki,
        "executable": str(exe), "binary_path": str(exe),
        "executable_sha256": exe_sha, "binary_hash": exe_sha,
        "command": [str(c) for c in command], "cwd": str(cwd),
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(started_at)),
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(finished_at)),
        "finished_at_epoch": finished_at,
        "runtime_seconds": round(max(0.0, finished_at - started_at), 3),
        "exit_code": exit_code,
        "binary_actually_ran": exit_code is not None,
        "stdout_log": stdout_log, "stderr_log": stderr_log,
        "inputs": input_snapshot["inputs"] if input_snapshot is not None else [_file_entry(f, project) for f in inputs],
        "outputs": outs, "output_files_count": sum(1 for o in outs if not o.get("missing")),
        "forcing_source": forcing_source,
        "plan_step_id": plan_step_id, "approval_sha256": approval_sha256,
        "validation": validation or {"status": "not_run", "checks": []},
        "wrapper_pid": os.getpid(), "recorded_at": _now(),
    }
    if declared_outputs is not None:
        doc["declared_outputs"] = declared_outputs
    if input_snapshot is not None:
        doc["input_coverage"] = input_snapshot["input_coverage"]
        runtime_errors = _runtime_coverage_errors(project, doc)
        if runtime_errors:
            # Keep a failed attempt if the binding changed during execution or
            # validation. Never sign it as a passed run of the verified target.
            doc["validation"] = {**doc["validation"], "status": "failed",
                "checks": [*doc["validation"].get("checks", []),
                           {"check": "runtime_argument_binding", "ok": False,
                            "level": "fail", "detail": "; ".join(runtime_errors)}]}
    if execution_status is not None:
        doc.update(execution_status=execution_status, process_started=process_started,
                   binary_actually_ran=process_started is True)
    if project_data_tool is not None:
        doc.update(execution_scope="project_data_tool", model_executed=False,
                   project_data_tool=project_data_tool)
    elif data_ki is not None:
        doc.update(execution_scope="data_ki", model_executed=False, data_ki=data_ki)
    if stdout_artifact is not None:
        doc.update(stdout_artifact=stdout_artifact, execution_scope="ki_check_stdout_artifact",
                   model_executed=False)
    return _write(project, RUNS_SUB, rid, doc)


def update_validation(project: Path, receipt_path: Path, validation: dict) -> Path:
    doc = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
    if not verify(project, doc):
        raise ReceiptError(f"refusing to update an unverified receipt: {receipt_path}")
    doc["validation"] = validation
    doc = sign(project, doc)
    Path(receipt_path).write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    return Path(receipt_path)


# ---------------------------------------------------------------------------
# dag-driven output validation
# ---------------------------------------------------------------------------

# rank-1 variables that must carry positive values somewhere (issue: "输出是否包含物理上必要的正值")
_POSITIVE_ALIASES = ("discharge", "runoff", "streamflow", "outflw", "rivout", "flow", "flddph",
                     "fldfrc", "depth", "yield", "biomass", "swe", "evap", "et", "lai",
                     "storage", "level", "stage", "q", "qout", "flux", "sto", "wse")
_POSITIVE_UNITS = ("m3/s", "m^3/s", "m³/s", "mm", "mm/day", "mm/d", "m", "t/ha", "kg/ha", "kg/m2",
                   "w/m2", "%", "fraction", "1")


def _dag_rank1(ki_root: Path) -> list[dict]:
    try:
        import yaml
        d = yaml.safe_load((Path(ki_root) / "dag.yaml").read_text(encoding="utf-8", errors="ignore")) or {}
    except Exception:
        return []
    outs = d.get("outputs") or []
    if isinstance(outs, dict):
        outs = list(outs.values())
    return [o for o in outs if isinstance(o, dict) and str(o.get("validation_rank")) == "1"]


def _positive_required(rank1: list[dict]) -> bool:
    for o in rank1:
        name = str(o.get("var") or o.get("name") or "").lower()
        unit = str(o.get("unit") or "").lower().replace(" ", "")
        if any(a == name or a in name.split("_") or a in name for a in _POSITIVE_ALIASES):
            return True
        if unit in _POSITIVE_UNITS:
            return True
    return False


_AXIS_HEADERS = frozenset({
    # unmistakable coordinate / date / time / index names ONLY — never a name a model uses for a
    # result (`level`, `t`, `x`, `z` … are results somewhere; codex round-6 #3: Ribasim water level)
    "time", "date", "datetime", "timestamp", "year", "yr", "month", "mon", "day", "hour", "hr",
    "minute", "second", "doy", "jday", "julian", "step", "index", "idx", "row", "col",
    "cell_id", "lat", "latitude", "lon", "longitude"})


def _text_cells(line: str) -> list[str]:
    """One text line → cells. A leading `#` is dropped (commented header/data), quoted cells are
    honoured for `,`/`;` files (csv reader), whitespace-separated otherwise; every cell is stripped
    of quotes and blanks; empty cells are kept so positions match between header and data."""
    import csv, io
    body = line.lstrip()
    if body.startswith("#"):
        body = body.lstrip("#").strip()
    if "," in body or ";" in body:
        delim = "," if body.count(",") >= body.count(";") else ";"
        try:
            parts = next(csv.reader(io.StringIO(body), delimiter=delim))
        except Exception:
            parts = body.replace(";", ",").split(",")
    else:
        # whitespace files have no empty cells; quotes group a cell (`" time "` is one cell)
        import re, shlex
        # a unit annotation `(day)` / `[m3/s]` / `(days since 2000-01-01)` belongs to the name before
        # it, not to a column — removed as a whole BEFORE splitting (codex rounds 6 and 8)
        body = re.sub(r"[\(\[][^\)\]]*[\)\]]", " ", body)
        try:
            parts = shlex.split(body)
        except ValueError:
            parts = body.split()
        parts = [p for p in parts if not (p.startswith("(") or p.startswith("["))]
        return [t for t in (p.strip().strip("'\"").strip() for p in parts) if t != ""]
    # positions are PRESERVED in delimited files: an empty cell stays an empty string (codex round-5 #2)
    return [p.strip().strip("'\"").strip() for p in parts]


def _axis_name(cell: str) -> str:
    """A header cell reduced to its name: a trailing unit annotation `time(day)` / `time (day)` /
    `lat [deg]` is dropped (codex round-7), quotes/blanks stripped, lower-cased."""
    import re
    return re.sub(r"\s*[\(\[].*$", "", cell.strip().strip("'\"")).strip().lower()


def _is_number(tok: str) -> bool:
    try:
        float(tok)
        return True
    except ValueError:
        return False


def _netcdf_container(path: Path) -> bool:
    """Recognize container bytes, never a model-specific filename extension.

    A signature selects the NetCDF decoder; it does not establish that the
    container is valid or contains a scientific result. HDF5 may contain
    unrelated data and still has to pass that decoder and the existing checks.
    """
    with path.open("rb") as stream:
        prefix = stream.read(8)
    return prefix[:4] in (b"CDF\x01", b"CDF\x02", b"CDF\x05") or prefix == b"\x89HDF\r\n\x1a\n"


def _load_series(path: Path, prefer_vars: tuple[str, ...] = ()) -> tuple[list[float] | None, int | None, str]:
    """Numeric read of one output. NetCDF: ONLY the rank-1 variable(s) when present in the
    file (codex #5), else all data variables (and say so). Text/CSV: per-column, dropping
    strictly-increasing index/time columns so a time axis can never satisfy 'has positive
    values'. Returns (values, n_rows_or_steps, note)."""
    netcdf = False
    try:
        netcdf = _netcdf_container(path)
        if not netcdf and path.suffix.lower() in (".nc", ".nc4", ".netcdf"):
            return None, None, "NETCDF_UNINSPECTABLE: file has no NetCDF/HDF5 container signature"
        if netcdf:
            try:
                import xarray as xr
                import numpy as np
            except ImportError:
                xr = None
                try:
                    import numpy as np
                except ImportError:
                    return None, None, "NETCDF_UNINSPECTABLE: numpy not installed"
            if xr is not None:
                ds = None
                last = None
                for eng in (None, "h5netcdf", "scipy", "netcdf4"):  # engine/file-lock quirks
                    try:
                        ds = xr.open_dataset(path, engine=eng) if eng else xr.open_dataset(path)
                        break
                    except Exception as e:  # noqa: BLE001
                        last = e
                if ds is not None:
                    try:
                        names = [v for v in ds.data_vars]
                        lower = {v.lower(): v for v in names}
                        picked = [lower[p.lower()] for p in prefer_vars if p.lower() in lower]
                        # When the KI names a rank-1 variable and this file does not carry it,
                        # another variable's positive values may not stand in for it.
                        note = "netcdf rank-1 var(s) " + ",".join(picked) if picked else \
                               ("NETCDF_RANK1_ABSENT: " + ",".join(prefer_vars) if prefer_vars
                                else "netcdf ALL vars (KI declares no rank-1 variable)")
                        vals: list[float] = []
                        n = None
                        for v in (picked or names):
                            arr = np.asarray(ds[v].values, dtype="float64").ravel()
                            vals.extend(arr[:400000].tolist())
                            if "time" in ds[v].dims:
                                n = int(ds[v].sizes["time"])
                        return vals, n, note
                    finally:
                        ds.close()
            # The frozen Desktop intentionally does not bundle pandas/xarray.
            # netCDF4 is the compact inspection backend and handles VIC/CaMa HDF5 files.
            try:
                import netCDF4
            except ImportError:
                detail = type(last).__name__ if xr is not None and last is not None else \
                         "xarray and netCDF4 not installed"
                return None, None, f"NETCDF_UNINSPECTABLE: {detail}"
            try:
                with netCDF4.Dataset(path, mode="r") as ds4:
                    names = [name for name in ds4.variables if name not in ds4.dimensions]
                    lower = {v.lower(): v for v in names}
                    picked = [lower[p.lower()] for p in prefer_vars if p.lower() in lower]
                    note = "netcdf rank-1 var(s) " + ",".join(picked) if picked else \
                           ("NETCDF_RANK1_ABSENT: " + ",".join(prefer_vars) if prefer_vars
                            else "netcdf ALL vars (KI declares no rank-1 variable)")
                    vals = []
                    n = None
                    for name in (picked or names):
                        var = ds4.variables[name]
                        arr = np.ma.filled(var[:], np.nan)
                        values = np.asarray(arr, dtype="float64").ravel()
                        vals.extend(values[:400000].tolist())
                        if "time" in var.dimensions:
                            n = int(var.shape[var.dimensions.index("time")])
                    return vals, n, note
            except Exception as error:  # noqa: BLE001
                return None, None, f"NETCDF_UNINSPECTABLE: {type(error).__name__}"
        text = path.read_text(encoding="utf-8").replace("\ufeff", "")
        if "\x00" in text:
            return None, None, "unreadable (binary data is not a numeric text result)"
        lines = [ln for ln in text.splitlines() if ln.strip()]
        # (web defect 3, codex rounds 2-4) the HEADER is the LAST number-free line before the first
        # data row — commented (`# time q`) or not, after any prose preamble; cells are parsed with the csv reader (quotes, inner spaces) so header and data
        # column positions agree. Header-named coordinate / date / time columns are never result data.
        parsed = [_text_cells(ln) for ln in lines[:500000]]
        is_comment = [ln.lstrip().startswith("#") for ln in lines[:500000]]
        # a DATA row is an UNCOMMENTED row with at least one number (an ISO date cell next to a value
        # still counts); a comment line with a number in it (`# model version 5`) is metadata, never
        # data (codex round-5 #1); the HEADER is the last number-free row before the first data row
        first_data = next((i for i, c in enumerate(parsed)
                           if not is_comment[i] and c and any(_is_number(t) for t in c)), None)
        axis_cols: set[int] = set()
        header_row = None
        if first_data is not None:
            # the HEADER BLOCK = the contiguous number-free rows right above the data (names row,
            # then an optional units row — bracketed `(deg)` or plain `degrees_north` (ERDDAP), codex
            # rounds 9-10). Axis columns are the UNION over the block: a units row never names an
            # axis, a names row does, so the union is exact whichever row is which. Uncommented rows
            # are preferred; commented rows count only when no plain header exists.
            for want_comment in (False, True):
                i = first_data - 1
                while i >= 0:
                    c = parsed[i]
                    if not c:
                        i -= 1                    # a units-only row that tokenised to nothing (`(days) (deg)`)
                        continue
                    if any(_is_number(t) for t in c):
                        break
                    if is_comment[i] != want_comment:
                        if want_comment:
                            break
                        i -= 1
                        continue
                    header_row = i
                    axis_cols |= {j for j, t in enumerate(c) if _axis_name(t) in _AXIS_HEADERS}
                    i -= 1
                if header_row is not None:
                    break
        cols: dict[int, list[float]] = {}
        rows = 0
        for i, c in enumerate(parsed):
            if first_data is None or i < first_data or is_comment[i]:
                continue
            rows += 1
            for j, tok in enumerate(c):
                try:
                    cols.setdefault(j, []).append(float(tok))
                except ValueError:
                    pass                      # an empty / non-numeric cell keeps its position
        for j in axis_cols:
            cols.pop(j, None)
        # Drop the index/time axis only: a LEADING column that is strictly increasing with a
        # constant step (1,2,3… or 20030101,20030102… or evenly spaced times). A cumulative
        # data column (kimi #8) is increasing but rarely constant-step, and is never dropped
        # when it is not the first numeric column.
        data_cols = []
        for j in sorted(cols):
            c = cols[j]
            steps = [round(b - a, 9) for a, b in zip(c, c[1:])]
            # the spacing heuristic applies to the ORIGINAL first column only (j == 0) and only when
            # no header named the axis columns — never to a later column that became "first" after
            # a header-named axis was dropped (a rising discharge series is data)
            # (codex round-5 #3 / round-6) a header-named single result column (`discharge` rising
            # evenly) is never an axis; but an unlisted first column (`t`, `i`) next to a result column
            # still is when it looks like one — the result column is the OTHER column
            axis_like = (j == 0 and (header_row is None or len(cols) > 1) and len(c) >= 2
                         and all(s > 0 for s in steps) and len(set(steps)) <= 2)
            if not axis_like:
                data_cols.append(c)
        # (web defect 3, codex 2026-09-16) a discarded coordinate/time column is NEVER restored as
        # result data: a file with only a time axis has no model result in it
        vals = [v for c in data_cols for v in c]
        return vals, rows, ("text" if vals else "text: only an axis-like column, no result column")
    except Exception as e:
        prefix = "NETCDF_UNINSPECTABLE" if netcdf else "unreadable"
        return None, None, f"{prefix}: {type(e).__name__}"


def _diagnostic_stream_log(path: Path) -> bool:
    """Recognize explicit stdout/stderr captures, never generic model .log files."""
    name = path.name.lower()
    return name in {"stdout.log", "stderr.log"} or name.endswith((".stdout.log", ".stderr.log"))


def _diagnostic_result_log(path: Path) -> bool:
    """Conventional diagnostics cannot supply scientific numeric evidence.

    This is a generic filename convention, not a model allowlist or a claim
    to classify arbitrary prose. A separately produced structured data file
    such as result.stderr.log.csv is still inspected as data. All artifacts
    remain hashed by the receipt regardless of this classification.
    """
    import re
    if _diagnostic_stream_log(path):
        return True
    if path.suffix.lower() in {".csv", ".tsv", ".nc", ".nc4", ".netcdf"}:
        return False
    return bool(re.search(r"(?:^|[._-])(?:log|logs|diag|diagnostic|diagnostics|stdout|stderr)(?:$|[._-])",
                          path.name.lower()))


def _validate_png(path: Path) -> tuple[bool, str]:
    """Check real PNG integrity and pixel decoding, never numeric model content."""
    try:
        import warnings
        from PIL import Image
        # Pillow stops at IEND without checking its CRC/truncation. Walk only
        # chunk headers (seek over payloads) to require a complete first IEND
        # and no trailing/duplicate chunks; Pillow verifies the other chunks.
        with path.open("rb") as stream:
            if stream.read(8) != b"\x89PNG\r\n\x1a\n":
                raise ValueError("invalid PNG signature")
            while True:
                header = stream.read(8)
                if len(header) != 8:
                    raise ValueError("PNG is missing a complete IEND chunk")
                length = int.from_bytes(header[:4], "big")
                if header[4:] == b"IEND":
                    if length != 0 or stream.read(4) != b"\xae\x42\x60\x82" or stream.read(1):
                        raise ValueError("PNG IEND length/CRC or trailing data is invalid")
                    break
                stream.seek(length + 4, 1)
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as picture:
                if picture.format != "PNG":
                    raise ValueError("file is not a PNG image")
                width, height = picture.size
                picture.verify()
            # verify() checks PNG chunk integrity; load() also detects a valid
            # container whose compressed pixel stream is incomplete/corrupt.
            with Image.open(path) as picture:
                picture.load()
        return True, f"{width}x{height} PNG decoded; presentation artifact, excluded from numeric model evidence"
    except Exception as error:
        return False, f"PNG decode/verification failed: {type(error).__name__}: {error}"


def validate_outputs(ki_root: Path, outputs: list, *, expected_steps: int | None = None,
                     run_facts: dict | None = None, physical: bool = True) -> dict:
    """Return {"status": passed|failed|warning, "checks": [...]}.

    run_facts (REQUIRED in practice, validation_ladder.run_validity L149-177 contract):
      {"errored": bool, "continuity_pct": float|None, "output_nonempty": bool}
    physical=False: skip the rank-1 "physically required positive values" rule — for
    preparation-step outputs (forcing files, parameter decks) that are not the model's
    headline output. Model-run / routing / calibration steps keep physical=True.
    Explicit stdout/stderr .log captures remain receipt-hashed artifacts, but are
    diagnostic text (possibly empty), never numerical model-result evidence.
    """
    checks: list[dict] = []

    def add(name, ok, detail="", level="fail"):
        checks.append({"check": name, "ok": bool(ok), "detail": detail, "level": level})

    # kimi #7: run facts are REQUIRED. A wrapper that does not affirm them fails closed
    # (validation_ladder.run_validity L149-177: an unstated fact is not proof).
    rf = run_facts or {}
    add("run_affirmed_error_free", rf.get("errored") is False,
        "run must affirm errored=false" + ("" if run_facts is not None else " (no run facts supplied)"))
    c = rf.get("continuity_pct")
    if c is not None:
        add("mass_conservation", abs(float(c)) < 5.0, f"continuity {c}% (must be < 5%)")
    add("output_affirmed_nonempty", rf.get("output_nonempty") is True,
        "run must affirm output_nonempty=true")
    if not outputs:
        add("outputs_named", False, "no outputs named — nothing to validate (artifact)")
        return {"status": "failed", "checks": checks}

    rank1 = _dag_rank1(Path(ki_root))
    rank1_vars = tuple(str(o.get("var") or o.get("name") or "") for o in rank1)
    positive_needed = physical and _positive_required(rank1)

    any_numeric = False
    any_presentation = False
    for out in outputs:
        p = Path(out)
        if not p.is_file():
            add(f"exists:{p.name}", False, str(p)); continue
        if _diagnostic_result_log(p):
            add(f"diagnostic_log:{p.name}", True,
                f"{p.stat().st_size} bytes; retained as evidence, excluded from numeric result checks")
            continue
        if p.stat().st_size == 0:
            add(f"non_empty:{p.name}", False, "0 bytes"); continue
        add(f"exists_non_empty:{p.name}", True, f"{p.stat().st_size} bytes")
        if p.suffix.lower() == ".png":
            valid, detail = _validate_png(p)
            add(f"png_decode:{p.name}", valid, detail)
            any_presentation |= valid
            continue
        vals, n, note = _load_series(p, rank1_vars)
        if vals is None:
            # an output the app cannot inspect is a FAIL for NetCDF (the model's main output
            # format, kimi #4); other unreadable formats are a warning that blocks 'passed'
            add(f"readable:{p.name}", False, note,
                level="fail" if note.startswith("NETCDF_UNINSPECTABLE") else "warn"); continue
        if not vals:
            add(f"numeric_content:{p.name}", False, f"no numeric values ({note})", level="warn")
            continue
        any_numeric = True
        nan = sum(1 for v in vals if math.isnan(v) or math.isinf(v))
        add(f"no_nan_inf:{p.name}", nan == 0, f"{nan} NaN/Inf of {len(vals)} ({note})")
        if expected_steps and n is not None:
            add(f"time_axis_complete:{p.name}", n >= expected_steps,
                f"{n} rows/steps vs expected {expected_steps}")
        finite = [v for v in vals if not (math.isnan(v) or math.isinf(v))]
        if positive_needed and note.startswith("NETCDF_RANK1_ABSENT"):
            add(f"physically_required_positive:{p.name}", False,
                f"the model's rank-1 output ({', '.join(rank1_vars)}) is not in this file; other "
                f"variables cannot stand in for it")
        elif positive_needed and finite:
            pos = sum(1 for v in finite if v > 0)
            add(f"physically_required_positive:{p.name}", pos > 0,
                f"{pos} positive of {len(finite)} values; rank-1 output "
                f"({', '.join(rank1_vars) or '?'}) must have positive values")
        if physical and finite and len(finite) > 2 and max(finite) == min(finite):
            # kimi block-A review: when the dag declares no usable rank-1, a constant/all-zero
            # file must still FAIL — a flat output is never a model result (fail-closed even
            # for thin dags); with a rank-1 the positive check above already covers zeros.
            # physical=False (a preparation step): a constant file can be legitimate (a mask
            # of ones) — no check emitted, so prep validation is not downgraded to 'warning'.
            add(f"not_constant:{p.name}", False, f"all values == {finite[0]}")
    if not any_numeric and (physical or not any_presentation):
        add("any_numeric_output", False, "no output file had numeric content to check", level="warn")

    fails = [c for c in checks if not c["ok"] and c["level"] == "fail"]
    warns = [c for c in checks if not c["ok"] and c["level"] == "warn"]
    status = "failed" if fails else ("warning" if warns else "passed")
    return {"status": status, "checks": checks}


# ---------------------------------------------------------------------------
# evidence — bound to the current plan and approval (codex #2)
# ---------------------------------------------------------------------------

def _read_all(project: Path, sub: str) -> list[tuple[Path, dict, bool]]:
    d = Path(project) / RECEIPT_DIR / sub
    out = []
    if not d.is_dir():
        return out
    for p in sorted(d.glob("*.json")):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            out.append((p, {}, False)); continue
        if not isinstance(doc, dict):
            out.append((p, {}, False)); continue
        out.append((p, doc, verify(project, doc)))
    return out


from .plan import EXECUTABLE_STEP_KINDS


@dataclass(frozen=True)
class DownloadEvidence:
    """Read-only conclusion at inspection time, not an authorization or scientific check.

    ``reusable`` means exact request + intact files. ``recoverable`` additionally
    allows rename-only or missing-ZIP recovery, but the host must explicitly issue
    a replacement receipt before consumers may rely on that recovery. ``bound``
    preserves final evidence's older current-approval receipt rules; it is NOT a
    synonym for reusable. Local integrity establishes neither remote freshness
    nor scientific suitability. Do not cache a conclusion across file changes.
    """
    path: Path
    receipt: dict
    request_match: str
    files: str
    reason: str
    reusable: bool = False
    recoverable: bool = False
    bound: bool = False
    source_freshness: str = "unknown"
    scientific_validation: str = "not_assessed"


def _entry_status(project: Path, entry) -> str:
    if (not isinstance(entry, dict) or not isinstance(entry.get("path"), str)
            or not entry["path"] or not isinstance(entry.get("sha256"), str)
            or not entry["sha256"]):
        return "malformed"
    path = Path(project) / entry["path"]
    try:
        if not _inside(path, project):
            return "unsafe"
        if not path.exists():
            if path.is_symlink():
                return "unsafe"
            return "missing"
        if not path.is_file():
            return "unsafe"
        return "intact" if sha256_file(path) == entry["sha256"] else "changed"
    except (OSError, ValueError, RuntimeError):
        return "unsafe"  # unreadable or unresolvable paths cannot support recovery


def _download_file_status(project: Path, receipt: dict) -> str:
    raw, processed = receipt.get("raw_files", []), receipt.get("processed_files", [])
    if not isinstance(raw, list) or not isinstance(processed, list):
        return "malformed"
    raw_status = [_entry_status(project, e) for e in raw]
    processed_status = [_entry_status(project, e) for e in processed]
    for failure in ("unsafe", "malformed", "changed"):
        if failure in raw_status + processed_status:
            return failure
    if not raw:
        return "missing"
    if all(s == "intact" for s in raw_status + processed_status):
        return "intact"
    # Only lost transport ZIPs may be replaced by their recorded extraction.
    # A changed archive, arbitrary missing input, or missing extraction is not
    # recovery evidence. Check every raw entry, including surviving archives.
    if (processed and all(s == "intact" for s in processed_status)
            and receipt.get("transform_tool") == "verified_zip_extract"
            and all(Path(e["path"]).suffix.lower() == ".zip" for e in raw)
            and "missing" in raw_status):
        return "extracted_only"
    return "missing"


def _inspect_download(project: Path, path: Path, doc: dict, verified: bool,
                      item: dict | None, approval_sha256: str, selection_required: bool) -> DownloadEvidence:
    if not verified or doc.get("kind") != "download":
        return DownloadEvidence(path, doc, "unknown", "malformed",
                                "signature" if not verified else "not a download receipt")
    fingerprint = doc.get("selection_sha256")
    match = "unknown" if not fingerprint else "mismatch"
    if fingerprint and item is not None:
        if str(item.get("id")) == str(doc.get("item_id")):
            if fingerprint == selection_sha256(item):
                match = "exact"
        elif doc.get("item_id") and fingerprint == selection_sha256({**item, "id": doc["item_id"]}):
            match = "renamed"
    files = _download_file_status(project, doc)
    reusable = match == "exact" and files == "intact"
    recoverable = match in ("exact", "renamed") and files in ("intact", "extracted_only")
    bound = reusable
    current = bool(approval_sha256) and doc.get("approval_sha256") == approval_sha256
    # Legacy final-evidence compatibility is intentionally weaker than reuse.
    # No fingerprint must never gain new scope proof or cross-approval authority.
    if current and (not fingerprint or not selection_required):
        no_files = doc.get("raw_files", []) == [] and doc.get("processed_files", []) == []
        bound = files == "intact" or no_files
    if match in ("renamed", "mismatch") and selection_required:
        bound = False
    if match == "unknown":
        reason = "receipt has no selected-request fingerprint; automatic reuse is unavailable"
    elif match == "mismatch":
        reason = "selected source or requirements changed, or item is no longer in the inventory"
    elif files == "extracted_only":
        reason = "transport ZIP missing; intact extraction requires explicit host recovery"
    elif files != "intact":
        reason = f"acquired files are {files}; automatic reuse is unavailable"
    elif match == "renamed":
        reason = "request unchanged except item name; explicit host rebinding required"
    else:
        reason = "exact selected request and intact acquired files"
    return DownloadEvidence(path, doc, match, files, reason, reusable, recoverable, bound)


def inspect_downloads(project: Path, inventory: dict | None = None, *,
                      approval_sha256: str = "") -> list[DownloadEvidence]:
    """Inspect all acquisition receipts without writes, downloads or re-signing.

    Returns rejected records too, with explanations. An omitted inventory retains
    legacy current-approval final-evidence behavior, but never proves exact reuse.
    Uses local file hashes only; there is no remote freshness lookup.
    """
    items = {str(i.get("id")): i for i in (inventory or {}).get("items") or [] if isinstance(i, dict)}
    return [_inspect_download(project, p, d, ok, items.get(str(d.get("item_id"))),
                              approval_sha256, inventory is not None)
            for p, d, ok in _read_all(project, DATA_SUB)]


def find_download(project: Path, item: dict, *, approval_sha256: str = "",
                  recover: bool = False, source: str | None = None) -> DownloadEvidence | None:
    """Find intact exact-request evidence, or explicitly opt into recovery candidates.

    Even with ``recover=True`` this ONLY inspects. Prefer exact reusable records,
    then current-approval records; never infer a request from a dataset directory.
    Rename matching preserves the historical fingerprint algorithm (including ID).
    """
    candidates = []
    for path, doc, ok in _read_all(project, DATA_SUB):
        if source is not None and doc.get("source") != source:
            continue
        result = _inspect_download(project, path, doc, ok, item, approval_sha256, True)
        if result.reusable or (recover and result.recoverable):
            candidates.append(result)
    return max(candidates, key=lambda r: (r.reusable, r.receipt.get("approval_sha256") == approval_sha256),
               default=None)


def _finished_at(run: dict) -> float:
    """Parsed, so a UTC-offset change between attempts cannot reorder them."""
    epoch = run.get("finished_at_epoch")
    if type(epoch) in (int, float) and math.isfinite(epoch):
        return epoch
    try:
        return datetime.strptime(run["finished_at"], "%Y-%m-%dT%H:%M:%S%z").timestamp()
    except (KeyError, TypeError, ValueError):
        return float("-inf")


def _historical_outputs(project: Path, runs: list[tuple[Path, dict, bool]],
                        current_approval: str, current_outputs: set[str]) -> list[dict]:
    """Classify intact prior output bytes as history, never current-step evidence.

    A failed attempt can leave useful diagnostics. Its signed, unchanged files
    retain their failed status here; they neither pass a step nor validate data.
    The latest signed writer wins, and current-approval outputs are handled only
    by the current-attempt rules in evidence(). No receipt is changed or rebound.
    """
    latest: dict[str, tuple[Path, dict, dict]] = {}
    rank = {"passed": 0, "failed": 2}
    valid_runs = [(path, doc) for path, doc, ok in runs if ok and doc.get("kind") == "run"
                  and isinstance(doc.get("validation"), dict)]
    for receipt_path, doc in sorted(valid_runs, key=lambda row: (
            _finished_at(row[1]), rank.get(row[1]["validation"].get("status"), 1))):
        for entry in doc.get("outputs") or []:
            if isinstance(entry, dict) and isinstance(entry.get("path"), str):
                latest[entry["path"]] = (receipt_path, doc, entry)
    retained = []
    root = project.resolve()
    for relative, (receipt_path, doc, entry) in sorted(latest.items()):
        validation = (doc.get("validation") or {}).get("status")
        if (relative in current_outputs or not doc.get("approval_sha256")
                or doc.get("approval_sha256") == current_approval
                or validation not in {"passed", "warning", "failed"}
                or doc.get("binary_actually_ran") is not True
                or entry.get("missing") or type(entry.get("bytes")) is not int):
            continue
        # A 'passed' label cannot override contradictory signed process facts.
        if validation in {"passed", "warning"} and (doc.get("exit_code") != 0 or
                doc.get("execution_status") not in (None, "succeeded")):
            continue
        path = root / relative
        try:
            if _entry_status(root, entry) != "intact" or path.stat().st_size != entry["bytes"]:
                continue
            resolved_relative = path.resolve().relative_to(root).as_posix()
            if resolved_relative in current_outputs:
                continue
        except (OSError, ValueError, RuntimeError):
            continue
        retained.append({"path": resolved_relative, "sha256": entry["sha256"], "bytes": entry["bytes"],
                         "receipt_path": receipt_path.relative_to(project).as_posix(),
                         "run_id": doc.get("run_id"), "ki": doc.get("ki"),
                         "approval_sha256": doc["approval_sha256"], "plan_step_id": doc.get("plan_step_id"),
                         "validation": validation, "exit_code": doc.get("exit_code"),
                         "classification": {"failed": "failed_attempt", "warning": "validation_warning",
                                            "passed": "passed_run"}[validation],
                         "satisfies_current_step": False})
    return retained


#: Files the host itself writes (not agent or model results): the calibration manifest every
#: desktop project gets at creation, and the Project View manifest the host validates and
#: renders when the agent publishes it through its own tool (presentation, not data).
HOST_BOOKKEEPING = frozenset({"calibration/framework.json", "artifacts/project-view.json"})

MAX_INPUT_FILES = 4096
MAX_INPUT_ENTRIES = 8192


def _runtime_binding_rows(project, arguments, bindings, cwd):
    """Check exact named runtime tokens without granting inventory path access."""
    if not isinstance(bindings, (list, tuple)) or not bindings or len(bindings) > 100:
        raise ValueError("Invalid runtime argument bindings")
    rows, seen = [], set()
    for binding in bindings:
        if not isinstance(binding, (list, tuple)) or len(binding) != 4:
            raise ValueError("Malformed runtime argument binding")
        index, option, alias, target = binding
        if (type(index) is not int or index < 0 or index >= len(arguments) or index in seen
                or not isinstance(option, str) or not option.startswith("--")
                or not isinstance(alias, str) or not isinstance(target, str)):
            raise ValueError("Malformed runtime argument binding")
        token = arguments[index]
        if token.startswith("--") and "=" in token:
            actual_option, value = token.split("=", 1)
        else:
            actual_option, value = (arguments[index - 1] if index else ""), token
        candidate = Path(value).expanduser()
        lexical = Path(os.path.abspath(candidate if candidate.is_absolute() else Path(cwd) / candidate))
        source = Path(alias)
        resolved = _input_path(project, target)
        if (actual_option != option or "=" in option or not source.is_absolute()
                or str(source) != str(Path(os.path.abspath(source))) or lexical != source
                or not Path(target).is_absolute() or str(resolved) != target
                or source.resolve(strict=True) != resolved or not resolved.is_file()):
            raise ValueError("Verified runtime argument binding changed: " + alias)
        seen.add(index)
        rows.append({"argument_index": index, "option": option, "path": alias, "target": target})
    return rows


@dataclass(frozen=True)
class RuntimeArgumentCapture:
    """Internal host capability, never accepted from request or plan JSON.

    The desktop constructs this only after authenticated runtime validation.
    This is not a sandbox against trusted Python code, which can already sign
    receipts. Immutable tuples bind the exact invocation and lexical paths.
    """
    project: str
    cwd: str
    arguments: tuple[str, ...]
    bindings: tuple[tuple[int, str, str, str], ...]
    expected_files: tuple[tuple[str, int, str], ...] = ()

    def checked_bindings(self, project, arguments, cwd):
        if (str(Path(project).resolve()) != self.project or str(Path(cwd).resolve()) != self.cwd
                or tuple(arguments) != self.arguments or not isinstance(self.arguments, tuple)
                or not isinstance(self.bindings, tuple)
                or any(not isinstance(binding, tuple) for binding in self.bindings)):
            raise ValueError("Runtime argument authorization differs from this invocation")
        rows = _runtime_binding_rows(Path(project).resolve(), arguments, self.bindings, cwd)
        if self.expected_files:
            if (not isinstance(self.expected_files, tuple)
                    or any(not isinstance(row, tuple) or len(row) != 3 for row in self.expected_files)):
                raise ValueError("Malformed verified runtime file identities")
            targets = {row["target"] for row in rows}
            seen = set()
            for target, size, digest in self.expected_files:
                if (not isinstance(target, str) or target not in targets or target in seen
                        or type(size) is not int or not 0 < size <= 256 * 1024 * 1024
                        or not isinstance(digest, str) or len(digest) != 64
                        or any(c not in "0123456789abcdef" for c in digest)):
                    raise ValueError("Malformed verified runtime file identity")
                seen.add(target)
                path = Path(target)
                if path.stat().st_size != size:
                    raise ValueError("Verified runtime argument bytes changed: " + target)
                observed, remaining = hashlib.sha256(), size + 1
                with path.open("rb") as stream:
                    while remaining:
                        block = stream.read(min(1024 * 1024, remaining))
                        if not block:
                            break
                        observed.update(block)
                        remaining -= len(block)
                if remaining != 1 or observed.hexdigest() != digest:
                    raise ValueError("Verified runtime argument bytes changed: " + target)
            if seen != targets:
                raise ValueError("Verified runtime file identities do not cover every argument")
        return rows


def _runtime_coverage_errors(project, receipt):
    coverage = receipt.get("input_coverage") or {}
    if "runtime_arguments" not in coverage:
        return []  # Legacy receipts retain their existing coverage policy.
    try:
        rows = coverage["runtime_arguments"]
        count = coverage.get("argument_count")
        command = receipt.get("command")
        if (not isinstance(rows, list) or not rows or not isinstance(command, list)
                or not all(isinstance(token, str) for token in command)
                or type(count) is not int or not 0 < count <= min(100, len(command))
                or any(not isinstance(row, dict) or set(row) !=
                       {"argument_index", "option", "path", "target"} for row in rows)):
            raise ValueError("Malformed recorded runtime argument coverage")
        bindings = [(row["argument_index"], row["option"], row["path"], row["target"]) for row in rows]
        _runtime_binding_rows(project, command[-count:], bindings, receipt.get("cwd", ""))
        recorded = {entry.get("path") for entry in receipt.get("inputs") or [] if isinstance(entry, dict)}
        argument_files = set(coverage.get("argument_files") or [])
        if any(_rel(Path(row["target"]), project) not in recorded & argument_files for row in rows):
            raise ValueError("Recorded runtime target lacks its signed input hash")
        return []
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as error:
        return [str(error)]


def _input_bindings(step, inventory):
    bindings = []
    for ident in step.get("inputs") or []:
        matches = [item for item in (inventory or {}).get("items") or []
                   if isinstance(item, dict) and item.get("id") == ident]
        if len(matches) != 1:
            raise ValueError(f"Input {ident!r} needs exactly one approved inventory item")
        paths = matches[0].get("local_paths") or []
        if not isinstance(paths, list) or any(not isinstance(raw, str) for raw in paths):
            raise ValueError(f"Input {ident!r} local_paths must be an array of literal paths")
        bindings.append({"id": ident, "local_paths": paths})
    return bindings


def _input_path(project, raw):
    if (not isinstance(raw, str) or not raw or len(raw) > 4096
            or any(c in raw for c in "\0\r\n*?[]")):
        raise ValueError("Approved input paths must be literal file or data-directory paths")
    value = raw.replace("${PROJECT}", str(project))
    if "${" in value:
        raise ValueError("Approved input path uses an unresolved expansion")
    candidate = Path(value).expanduser()
    if candidate.drive and not candidate.is_absolute():
        raise ValueError("Approved input paths cannot be drive-relative")
    path = Path(os.path.abspath(candidate if candidate.is_absolute() else project / candidate))
    if path.resolve() != path or path.is_symlink():
        raise ValueError("Approved input path contains an alias: " + raw)
    for host in (project / ".geoforge", project / ".git", keys_dir().resolve()):
        if path == host or host in path.parents:
            raise ValueError("Host metadata is not an approved physical input: " + raw)
    return path


def _input_directory(project, path):
    """Enumerate only an explicitly approved data directory, with finite bounds."""
    if (path == project or path in project.parents or path == Path.home().resolve()
            or path.parent == path or path in keys_dir().resolve().parents):
        raise ValueError("Approved input directory is too broad; name the exact data directory or files")
    files, directories, pending, count = [], [], [path], 0
    while pending:
        parent = pending.pop()
        children = []
        with os.scandir(parent) as entries:
            for entry in entries:
                count += 1
                if count > MAX_INPUT_ENTRIES:
                    raise ValueError("Approved input directory exceeds the entry limit; name precise input files")
                children.append(Path(entry.path))
        for child in sorted(children):
            child = _input_path(project, str(child))
            if not child.is_relative_to(path):
                raise ValueError("Approved input directory contains an escaping path")
            if child.is_dir():
                directories.append(_rel(child, project))
                pending.append(child)
            elif child.is_file():
                files.append(_rel(child, project))
                if len(files) > MAX_INPUT_FILES:
                    raise ValueError("Approved input directory exceeds the file limit; name precise input files")
            else:
                raise ValueError("Approved input directory contains a nonordinary entry")
    return {"path": _rel(path, project), "files": sorted(files), "subdirectories": sorted(directories)}


def capture_inputs(project: Path, step: dict, inventory: dict, arguments: list[str], cwd: Path, *,
                   runtime_authorization: RuntimeArgumentCapture | None = None) -> dict:
    """Capture declared physical inputs before launch, plus literal file arguments.

    Descriptive inventory rows may have no local paths. Argument directories
    are never traversed: only a reviewed inventory directory grants that scope.
    """
    project = Path(project).resolve()
    runtime_rows = []
    if runtime_authorization is not None:
        if not isinstance(runtime_authorization, RuntimeArgumentCapture):
            raise ValueError("Runtime argument capture requires host authorization")
        runtime_rows = runtime_authorization.checked_bindings(project, arguments, cwd)
    runtime_by_index = {row["argument_index"]: row for row in runtime_rows}
    bindings = _input_bindings(step, inventory)
    files, directories, argument_files = set(), {}, set()
    for binding in bindings:
        for raw in binding["local_paths"]:
            path = _input_path(project, raw)
            if path.is_dir():
                listing = _input_directory(project, path)
                directories[listing["path"]] = listing
                files.update(listing["files"])
            elif path.is_file():
                files.add(_rel(path, project))
            else:
                raise ValueError(f"Approved input {binding['id']!r} is missing: {raw}")
    for index, token in enumerate(arguments):
        if index in runtime_by_index:
            # The checked canonical target, not the alias token's spelling
            # (which may contain '~'), is the signed physical input.
            path = _input_path(project, runtime_by_index[index]["target"])
            argument_files.add(_rel(path, project))
            continue
        value = token.split("=", 1)[1] if token.startswith("-") and "=" in token else token
        candidate = Path(value)
        candidate = candidate if candidate.is_absolute() else Path(cwd) / candidate
        if candidate.is_file():
            path = _input_path(project, str(candidate))
            argument_files.add(_rel(path, project))
    all_files = files | argument_files
    if len(all_files) > MAX_INPUT_FILES:
        raise ValueError("Approved input capture exceeds the file limit; select precise input files")
    entries = []
    for raw in sorted(all_files):
        path = project / raw
        before = path.stat()
        entry = _file_entry(path, project)
        after = path.stat()
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns, before.st_ino) != (
                after.st_size, after.st_mtime_ns, after.st_ctime_ns, after.st_ino):
            raise ValueError("Approved input changed during pre-launch capture: " + raw)
        entries.append(entry)
    if runtime_authorization is not None:
        runtime_authorization.checked_bindings(project, arguments, cwd)
    coverage = {"version": 1,
        "inventory_bindings": bindings, "files": sorted(files),
        "argument_files": sorted(argument_files),
        "directories": [directories[p] for p in sorted(directories)]}
    if runtime_rows:
        coverage.update(runtime_arguments=runtime_rows, argument_count=len(arguments))
    return {"inputs": entries, "input_coverage": coverage}


def _approved_output_paths(project, step, inventory):
    return {_rel(_input_path(project, raw), project)
            for item in (inventory or {}).get("items") or []
            if isinstance(item, dict) and item.get("id") in (step.get("outputs") or [])
            for raw in item.get("local_paths") or []}


def _input_coverage_errors(project, step, inventory, receipt, directory_observations):
    """A legacy file entry can prove file coverage; directory membership needs a snapshot."""
    try:
        bindings = _input_bindings(step, inventory)
        physical = [raw for binding in bindings for raw in binding["local_paths"]]
        coverage = receipt.get("input_coverage")
        rows = receipt.get("inputs") or []
        recorded = {row.get("path") for row in rows if isinstance(row, dict)}
        if coverage is None:
            for raw in physical:
                path = _input_path(project, raw)
                if path.is_dir() or _rel(path, project) not in recorded:
                    raise ValueError("Legacy receipt lacks complete approved input coverage: " + raw)
            return []
        if (not isinstance(coverage, dict) or coverage.get("version") != 1
                or coverage.get("inventory_bindings") != bindings
                or not isinstance(coverage.get("files"), list)
                or not isinstance(coverage.get("argument_files"), list)
                or not isinstance(coverage.get("directories"), list)):
            raise ValueError("Recorded input coverage differs from the approved inventory")
        files = set(coverage["files"])
        if not files.issubset(recorded) or not set(coverage["argument_files"]).issubset(recorded):
            raise ValueError("Recorded input coverage lacks its signed file hashes")
        directories = {row["path"]: row for row in coverage["directories"]}
        expected_files = set()
        own_outputs = ({row.get("path") for row in receipt.get("outputs") or []}
                       & _approved_output_paths(project, step, inventory))
        for raw in physical:
            path = _input_path(project, raw)
            relative = _rel(path, project)
            if relative in directories:
                previous = directories[relative]
                if relative not in directory_observations:
                    directory_observations[relative] = _input_directory(project, path)
                current = directory_observations[relative]
                # A tool can intentionally transform an input file or emit a
                # receipted result within its input case. Extra unreceipted
                # members can change wildcard/default reads and make it stale.
                output_parents = {_rel(parent, project) for raw_output in own_outputs
                                  for parent in (project / raw_output).parents
                                  if parent != path and parent.is_relative_to(path)}
                new_directories = set(current["subdirectories"]) - set(previous["subdirectories"])
                if (set(current["files"]) - own_outputs != set(previous["files"]) - own_outputs
                        or set(previous["subdirectories"]) - set(current["subdirectories"])
                        or new_directories - output_parents):
                    raise ValueError("Approved input directory membership changed: " + relative)
                expected_files.update(previous["files"])
            else:
                expected_files.add(relative)
        if files != expected_files:
            raise ValueError("Recorded input coverage omits or adds approved files")
        return _runtime_coverage_errors(project, receipt)
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as error:
        return [str(error)]


def _current_file_status(project: Path, entry, observations: dict, *, output=False) -> str:
    """Compare signed bytes with one call-local observation, including same-size edits.

    No result is cached across evidence calls. Only recorded files are read;
    shared inputs/outputs are hashed once, not once per dependent receipt.
    """
    if (not isinstance(entry, dict) or not isinstance(entry.get("path"), str)
            or not entry["path"] or entry.get("missing")
            or type(entry.get("bytes")) is not int or entry["bytes"] < 0
            or not isinstance(entry.get("sha256"), str) or len(entry["sha256"]) != 64):
        return "malformed"
    try:
        path = Path(os.path.abspath(project / entry["path"]))
        if output and (not _inside(path, project) or path.resolve() != path):
            return "unsafe"
        key = os.path.normcase(str(path))
        if key not in observations:
            if not path.is_file():
                observations[key] = (None, None, "missing" if not path.exists() else "unsafe")
            else:
                before = path.stat()
                # Do not read unexpectedly enlarged files just to reject them.
                if before.st_size != entry["bytes"]:
                    return "changed"
                digest = sha256_file(path)
                after = path.stat()
                identity = lambda st: (st.st_size, st.st_mtime_ns, st.st_ctime_ns, st.st_ino)
                observations[key] = (after.st_size, digest,
                                     "intact" if identity(before) == identity(after) else "changed")
        size, digest, state = observations[key]
        if state != "intact":
            return state
        return "intact" if (size, digest) == (entry["bytes"], entry["sha256"]) else "changed"
    except (OSError, ValueError, RuntimeError):
        return "unsafe"


def plan_dependencies(plan: dict | None) -> dict[str, set[str]]:
    """Declared input edges use the most recent preceding producer in plan order."""
    producers, dependencies = {}, {}
    for step in (plan or {}).get("steps") or []:
        if not isinstance(step, dict):
            continue
        sid = str(step.get("id"))
        dependencies[sid] = {producers[item] for item in step.get("inputs") or []
                             if item in producers and producers[item] != sid}
        for item in step.get("outputs") or []:
            producers[item] = sid
    return dependencies


def evidence(project: Path, plan: dict | None, approval: dict | None,
             output_dirs: tuple[str, ...] = ("outputs", "artifacts", "inputs", "calibration"),
             artifact_suffixes: tuple[str, ...] = (".nc", ".csv", ".txt", ".out", ".dat", ".tif",
                                                   ".png", ".json", ".bin"),
             enforcement: str = "none", inventory: dict | None = None, *,
             _download_inspection: list[DownloadEvidence] | None = None,
             include_history: bool = True) -> dict:
    """Machine-readable summary the UI shows and COMPLETED requires. Trusts ONLY receipts
    that verify AND are bound to the current approval (`approval_sha256 == the signed
    approval issuance's unique signature`), name a selected KI and a planned step. COMPLETED needs every
    executable planned step's latest bound attempt to have passed, and no unreceipted artifacts.
    Intact signed outputs from older approvals are separately retained as history;
    their pass/fail status never satisfies or validates a current planned step.

    `enforcement` = how the EXECUTING provider was contained (flow.policy Enforcement value).
    kimi #2: the HMAC key lives in the user's config dir; a provider whose agent runs as the
    user with broad reads (codex workspace-write, kimi) COULD read it, so for those the
    receipts are `assurance: containment`, not `cryptographic`. Only when the provider's tool
    wall was EXACT (Claude allowedTools without a Read grant on the key dir; the API proxy,
    which gives the agent no file access at all) is the signature a proof against the agent."""
    # Display-only callers may omit history, but never while classifying
    # artifacts for completion: historical paths affect orphan classification.
    output_dirs = tuple(output_dirs)
    if type(include_history) is not bool or (not include_history and output_dirs):
        raise ValueError("Omitting receipt history requires output_dirs=() (display-only query)")
    project = Path(project)
    plan = plan or {}
    approval = approval or {}
    sig = approval.get("signature") if isinstance(approval, dict) else None
    cur = str(sig.get("value") or "") if isinstance(sig, dict) else ""
    selected = set(plan.get("selected_kis") or approval.get("selected_kis") or [])
    steps = {str(s.get("id")): s for s in (plan.get("steps") or []) if isinstance(s, dict)}
    from .plan import step_kind
    plan_errors, invalid_steps, exec_steps = [], set(), set()
    for sid, step in steps.items():
        try:
            kind = step_kind(step)
        except ValueError as error:
            plan_errors.append(f"step {sid!r}: {error}")
            invalid_steps.add(sid)
            exec_steps.add(sid)
        else:
            if kind in EXECUTABLE_STEP_KINDS or step.get("tool"):
                exec_steps.add(sid)

    runs = _read_all(project, RUNS_SUB)
    # An in-process status query can share its already computed inspection with
    # this summary. Enforcement callers omit it and always inspect afresh.
    dl = (inspect_downloads(project, inventory, approval_sha256=cur)
          if _download_inspection is None else _download_inspection)
    rejected: list[dict] = []
    bound_runs: list[dict] = []
    typed_output_failures: dict[int, str] = {}

    def _same_file(a: str | None, b: str | None) -> bool:
        if not a or not b:
            return False
        try:
            return Path(a).resolve() == Path(b).resolve()
        except OSError:
            return str(a) == str(b)

    for p, d, ok in runs:
        why = None
        sid = str(d.get("plan_step_id"))
        if not ok:
            why = "signature"
        elif not cur or d.get("approval_sha256") != cur:
            why = "not bound to the current approval"
        elif d.get("ki") not in selected:
            why = f"KI {d.get('ki')!r} not selected"
        elif sid not in steps:
            why = f"plan step {d.get('plan_step_id')!r} not in the approved plan"
        else:
            # codex R2 #4: the receipt must show the APPROVED step's tool actually ran —
            # the executable or one of the command tokens must be that tool
            tool = (steps[sid] or {}).get("tool")
            if tool and not (_same_file(d.get("executable"), tool)
                             or any(_same_file(c, tool) for c in (d.get("command") or []))):
                why = f"ran {d.get('command')!r}, not the approved tool {tool!r} for step {sid}"
        if why:
            rejected.append({"path": str(p), "why": why})
        else:
            step = steps[sid]
            from .plan import invocation_receipt_errors
            invocation_errors = invocation_receipt_errors(step, project, d)
            if invocation_errors:
                typed_output_failures[id(d)] = "; ".join(invocation_errors)
            from . import declared_outputs
            if ("declared_outputs" in d or (declared_outputs.ordinary(step)
                    and d.get("execution_scope") not in {"data_ki", "project_data_tool", "ki_check_stdout_artifact"})):
                errors = declared_outputs.receipt_errors(project, step, inventory, d, check_files=False)
                if errors:
                    typed_output_failures[id(d)] = "; ".join(
                        [typed_output_failures[id(d)], *errors] if id(d) in typed_output_failures else errors)
            if "stdout_artifact" in step or "stdout_artifact" in d:
                from .stdout_artifacts import receipt_errors
                errors = receipt_errors(project, step, inventory, d)
                if errors:
                    typed_output_failures[id(d)] = "; ".join(errors)
            approved_data = step.get("project_data_tool")
            recorded_data = d.get("project_data_tool")
            if ((isinstance(approved_data, dict) and approved_data.get("version") == 2)
                    or (isinstance(recorded_data, dict) and recorded_data.get("version") == 2)):
                from .project_tools import typed_output_errors
                if (approved_data != recorded_data or not isinstance(approved_data, dict)
                        or approved_data.get("version") != 2
                        or d.get("execution_scope") != "project_data_tool"
                        or d.get("model_executed") is not False):
                    errors = ["typed data receipt does not match the approved binding"]
                else:
                    errors = typed_output_errors(project, step, d.get("validation"), d.get("outputs"))
                if errors:
                    # Retain this authentic attempt in latest-attempt ordering.
                    # Dropping it could make an older passing run win instead.
                    typed_output_failures[id(d)] = "; ".join(errors)
            bound_runs.append(d)
    bound_dl: list[dict] = []
    for result in dl:
        if result.bound:
            bound_dl.append(result.receipt)
        else:
            rejected.append({"path": str(result.path), "why": result.reason})
    from .public_downloads import step_complete as public_download_complete
    passed_downloads = {str(d.get("plan_step_id")) for d in bound_dl
                        if str(d.get("plan_step_id")) in steps
                        and str(d.get("plan_step_id")) not in invalid_steps
                        and steps[str(d.get("plan_step_id"))].get("kind") == "download"
                        and d.get("raw_files") and not any(f.get("missing") for f in d["raw_files"])
                        and public_download_complete(steps[str(d.get("plan_step_id"))],
                                                     inventory or {}, bound_dl)}

    # Every attempt keeps its receipt, but each step stands on its LATEST bound attempt and each
    # output file on the latest attempt that wrote it. So a retry supersedes a failure, a later
    # failure counts again, and a file only a failed attempt wrote is not vouched for by a pass.
    # New receipts retain subsecond ordering; legacy timestamps and exact ties
    # retain the conservative failed > other > passed rule. A backwards wall
    # clock jump remains a limitation of historical attempt ordering.
    def status(d):
        validation = d.get("validation")
        recorded = validation.get("status") if isinstance(validation, dict) else None
        if id(d) in typed_output_failures and recorded not in {"failed", "stopped"}:
            return "failed"
        return recorded
    def failure_summary(sid, d):
        validation = d.get("validation")
        validation = validation if isinstance(validation, dict) else {}
        checks = validation.get("checks")
        checks = checks if isinstance(checks, list) else []
        return {
            "plan_step_id": sid, "run_id": d.get("run_id"), "exit_code": d.get("exit_code"),
            "validation_reason": typed_output_failures.get(id(d)) or
                validation.get("reason") or "Required run validation failed",
            "failed_checks": [{"check": str(check.get("check") or "")[:200],
                               "detail": str(check.get("detail") or "")[:600]}
                              for check in checks
                              if isinstance(check, dict) and check.get("ok") is False][:10],
        }
    rank = {"passed": 0, "failed": 2}
    attempts = sorted(bound_runs, key=lambda d: (_finished_at(d), rank.get(status(d), 1)))
    latest: dict[str, dict] = {}
    writer: dict[str, tuple[dict, str | None]] = {}
    for d in attempts:
        latest[str(d.get("plan_step_id"))] = d
        for o in d.get("outputs") or []:
            writer[o.get("path")] = (d, o.get("sha256"))
    observations, directory_observations, stale_reasons, invalid_output_files = {}, {}, {}, []

    def stale(sid, reason):
        reasons = stale_reasons.setdefault(sid, [])
        if reason not in reasons:
            reasons.append(reason)

    # Only the latest owner of a path must still have its bytes on disk. Earlier
    # approved stages can intentionally produce and then transform the same file.
    receipted_outputs = set()
    for path, (d, _) in writer.items():
        if status(d) != "passed":
            continue
        entry = next(o for o in d.get("outputs") or [] if o.get("path") == path)
        current = _current_file_status(project, entry, observations, output=True)
        if current == "intact":
            receipted_outputs.add(path)
        else:
            sid = str(d.get("plan_step_id"))
            invalid_output_files.append({"path": path, "plan_step_id": sid, "reason": current})
            if latest.get(sid) is d:
                stale(sid, f"Recorded output {path!r} is {current}")

    dependencies = {sid: set() for sid in latest}
    for sid, d in latest.items():
        if status(d) != "passed":
            continue
        for reason in _input_coverage_errors(project, steps[sid], inventory, d, directory_observations):
            stale(sid, reason)
        own_outputs = ({o.get("path") for o in d.get("outputs") or []}
                       & _approved_output_paths(project, steps[sid], inventory))
        for entry in d.get("inputs") or []:
            path = entry.get("path") if isinstance(entry, dict) else None
            # An in-place transform owns the resulting output version. Its
            # original input version is not expected to survive its own write.
            if path in own_outputs:
                continue
            current = _current_file_status(project, entry, observations)
            if current != "intact":
                stale(sid, f"Recorded input {path!r} is {current}")
            if path in writer:
                producer, digest = writer[path]
                producer_id = str(producer.get("plan_step_id"))
                if producer_id != sid:
                    dependencies[sid].add(producer_id)
                    if digest != entry.get("sha256"):
                        stale(sid, f"Recorded input {path!r} was replaced by step {producer_id!r}")
    # Receipt inputs cover literal file arguments. Plan item edges also cover
    # tools that locate inputs through a case/configuration or modify them in
    # place, so stale upstream provenance cannot leave downstream passes current.
    for sid, required in plan_dependencies(plan).items():
        if sid in dependencies:
            dependencies[sid].update(required)
    pending = True
    while pending:
        pending = False
        for sid, required in dependencies.items():
            if status(latest[sid]) != "passed" or sid in stale_reasons:
                continue
            unavailable = sorted(p for p in required if p not in passed_downloads and (
                p in stale_reasons or p in invalid_steps or p not in latest or status(latest[p]) != "passed"))
            if unavailable:
                stale(sid, "Upstream step evidence is not current: " + ", ".join(unavailable))
                pending = True
    stale_steps = sorted(stale_reasons)
    # Unchanged bytes from stale runs remain reviewable but cannot vouch for
    # current artifacts or allow continuation to consume stale evidence.
    receipted_outputs = {path for path in receipted_outputs
                         if str(writer[path][0].get("plan_step_id")) not in stale_reasons}
    superseded = [{"plan_step_id": d.get("plan_step_id"), "run_id": d.get("run_id"),
                   "finished_at": d.get("finished_at"), "command": d.get("command")}
                  for d in attempts if status(d) == "failed"
                  and status(latest[str(d.get("plan_step_id"))]) == "passed"]
    for d in bound_dl:
        for o in (d.get("raw_files") or []) + (d.get("processed_files") or []):
            receipted_outputs.add(o.get("path"))
    historical_outputs = _historical_outputs(project, runs, cur, set(writer)) if include_history else []
    historical_paths = {entry["path"] for entry in historical_outputs}
    # Inputs the approved inventory names under inputs/ are the plan's data, not results, and
    # the host's own calibration manifest is written at project creation: neither is an
    # unvouched output. Only inputs/ paths count, so a result cannot be declared into this set.
    root = project.resolve()
    declared_inputs = set(HOST_BOOKKEEPING)
    declared_input_dirs: set[Path] = set()
    # Calibration cases are prepared inputs in their own project namespace.
    # Only inputs consumed by a typed calibration step qualify, never a plan's
    # produced items or arbitrary files somewhere under calibration/.
    produced = {item for step in steps.values() for item in step.get("outputs") or []}
    calibration_inputs = {item for step in steps.values()
                          if step.get("kind") == "calibrate" and isinstance(step.get("calibration"), dict)
                          for item in step.get("inputs") or []} - produced
    # A browser upload proves input origin, not a model result. Explicit
    # produced paths (including directory descendants) and every authenticated
    # run's output remain producer-bound, even after an upload of equal bytes.
    produced_paths: set[Path] = set()
    for item in (inventory or {}).get("items") or []:
        if isinstance(item, dict) and item.get("id") in produced:
            for raw in item.get("local_paths") or []:
                try:
                    path = Path(str(raw))
                    produced_paths.add((path if path.is_absolute() else root / path).resolve())
                except (OSError, ValueError, RuntimeError):
                    continue
    recorded_outputs = {str(entry.get("path")) for _, doc, valid in runs if valid
                        for entry in doc.get("outputs") or [] if isinstance(entry, dict)}
    uploaded_inputs = uploaded_input_files(root)
    for item in (inventory or {}).get("items") or []:
        for raw in (item.get("local_paths") or []) if isinstance(item, dict) else []:
            try:
                path = Path(str(raw))
                rel = (path.resolve() if path.is_absolute() else (root / path).resolve()) \
                    .relative_to(root).as_posix()
            except (OSError, ValueError, RuntimeError):
                continue
            if rel.startswith("inputs/") and item.get("id") not in produced:
                declared_inputs.add(rel)
                resolved = root / rel
                if resolved.is_dir():
                    declared_input_dirs.add(resolved)
            elif item.get("id") in calibration_inputs and rel.startswith("calibration/cases/"):
                declared_inputs.add(rel)
                resolved = root / rel
                if resolved.is_dir():
                    for child in resolved.rglob("*"):
                        if child.is_file() and child.resolve().is_relative_to(resolved):
                            declared_inputs.add(child.resolve().relative_to(root).as_posix())
    unreceipted: list[str] = []
    for sub in output_dirs:
        base = root / sub
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            if p.is_file() and p.suffix.lower() in artifact_suffixes:
                try:
                    resolved = p.resolve()
                    rel = resolved.relative_to(root).as_posix()
                except (OSError, ValueError, RuntimeError):
                    # A linked input that escapes the project cannot become a
                    # declared child, or abort evidence for every other file.
                    unreceipted.append(p.absolute().relative_to(root).as_posix())
                    continue
                # Use the existing artifact scan rather than walking every
                # declared directory again. Both lexical and resolved paths
                # must remain inputs; output aliases gain no directory exemption.
                declared_child = ((root / "inputs") in p.absolute().parents and
                                  any(resolved.is_relative_to(directory)
                                      for directory in declared_input_dirs))
                producer_bound = rel in recorded_outputs or any(
                    resolved == path or resolved.is_relative_to(path) for path in produced_paths)
                uploaded_original = (rel in uploaded_inputs and
                    p.absolute().relative_to(root).as_posix() == rel)
                input_only = not producer_bound and (
                    rel in declared_inputs or declared_child or uploaded_original)
                if (rel not in receipted_outputs and not input_only
                        and rel not in historical_paths):
                    unreceipted.append(rel)

    passed_steps = {sid for sid, d in latest.items()
                    if status(d) == "passed" and sid not in stale_steps and sid not in invalid_steps}
    # codex R2 #2: a planned 'download' step is satisfied by a bound download receipt that
    # names it and whose raw files all exist (no missing entries)
    passed_steps.update(passed_downloads)
    failed_any = bool(plan_errors) or any(status(d) == "failed" for d in latest.values())
    missing_steps = sorted(exec_steps - passed_steps)
    complete = bool(bound_runs) and not missing_steps and not unreceipted and not failed_any
    # A direct API wall does not turn reviewed, agent-authored Python into an
    # OS sandbox. Keep signature verification, but describe that execution's
    # assurance honestly, including a retained historical data-tool receipt.
    project_data_involved = any(isinstance(s.get("project_data_tool"), dict) for s in steps.values()) or any(
        ok and (d.get("execution_scope") == "project_data_tool" or isinstance(d.get("project_data_tool"), dict))
        for _, d, ok in runs)
    return {
        "approval_sha256": cur or None,
        "assurance": "cryptographic" if str(enforcement).lower() == "exact" and not project_data_involved else "containment",
        "runs_total": len(runs), "runs_bound": len(bound_runs),
        "downloads_total": len(dl), "downloads_bound": len(bound_dl),
        "rejected_receipts": rejected,
        "historical_outputs": historical_outputs,
        "unreceipted_artifacts": unreceipted[:200],
        "executable_steps": sorted(exec_steps), "steps_passed": sorted(passed_steps),
        "steps_missing": missing_steps, "stale_steps": stale_steps,
        "plan_errors": plan_errors, "stale_step_reasons": stale_reasons,
        "invalid_output_files": invalid_output_files,
        "superseded_failures": superseded,
        # Only the latest authentic attempt for a currently required step. This
        # must not be reconstructed from file order or historical chat failures.
        "current_failures": [failure_summary(sid, d) for sid, d in sorted(latest.items())
                             if sid in exec_steps and status(d) == "failed"],
        "validation": "failed" if failed_any else ("passed" if complete else "incomplete"),
        "receipts_verified": complete,
        "runs": [{"run_id": d.get("run_id"), "ki": d.get("ki"), "exit_code": d.get("exit_code"),
                  "outputs": d.get("output_files_count"),
                  "validation": status(d),
                  **({"validation_reason": typed_output_failures[id(d)]}
                     if id(d) in typed_output_failures else {}),
                  "plan_step_id": d.get("plan_step_id"),
                  **({"execution_scope": "ki_check_stdout_artifact", "model_executed": False,
                      "step_kind": "check"}
                     if "stdout_artifact" in (steps.get(str(d.get("plan_step_id"))) or {}) else
                     {"execution_scope": ("data_ki" if d.get("execution_scope") == "data_ki"
                                          else "project_data_tool"), "model_executed": False,
                      "step_kind": (steps.get(str(d.get("plan_step_id"))) or {}).get("kind")}
                     if d.get("execution_scope") in {"project_data_tool", "data_ki"} or
                     isinstance((steps.get(str(d.get("plan_step_id"))) or {}).get("project_data_tool"), dict)
                     else {})} for d in bound_runs],
    }
