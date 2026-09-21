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
import time
import fcntl
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
        with os.fdopen(lock_fd, "r+") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
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


# ---------------------------------------------------------------------------
# record
# ---------------------------------------------------------------------------

def selection_sha256(item: dict) -> str:
    """Bind acquisition evidence to source AND requirements, not a display ID.

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
                    inventory_item: dict | None = None, acquisition: dict | None = None) -> Path:
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
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in item_id)[:80]
    return _write(project, DATA_SUB, safe, doc)


def record_run(project: Path, *, ki: str, executable: str, command: list[str], cwd: str,
               started_at: float, finished_at: float, exit_code: int | None,
               inputs: list, outputs: list, approval_sha256: str, plan_step_id: str,
               stdout_log: str | None = None, stderr_log: str | None = None,
               forcing_source: str | None = None, validation: dict | None = None,
               run_id: str | None = None) -> Path:
    if not approval_sha256 or not plan_step_id:
        raise ReceiptError("a run receipt must name the approval it runs under and the plan step "
                           "it executes (codex review #2)")
    exe = Path(executable)
    rid = run_id or f"{ki}_{time.strftime('%Y%m%dT%H%M%S', time.localtime(started_at))}_" \
                    f"{secrets.token_hex(3)}"
    outs = [_file_entry(f, project) for f in outputs]
    exe_sha = sha256_file(exe) if exe.is_file() else None
    doc = {
        "kind": "run", "run_id": rid, "ki": ki,
        "executable": str(exe), "binary_path": str(exe),
        "executable_sha256": exe_sha, "binary_hash": exe_sha,
        "command": [str(c) for c in command], "cwd": str(cwd),
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(started_at)),
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(finished_at)),
        "runtime_seconds": round(max(0.0, finished_at - started_at), 3),
        "exit_code": exit_code,
        "binary_actually_ran": exit_code is not None,
        "stdout_log": stdout_log, "stderr_log": stderr_log,
        "inputs": [_file_entry(f, project) for f in inputs],
        "outputs": outs, "output_files_count": sum(1 for o in outs if not o.get("missing")),
        "forcing_source": forcing_source,
        "plan_step_id": plan_step_id, "approval_sha256": approval_sha256,
        "validation": validation or {"status": "not_run", "checks": []},
        "wrapper_pid": os.getpid(), "recorded_at": _now(),
    }
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
        d = yaml.safe_load((Path(ki_root) / "dag.yaml").read_text(errors="ignore")) or {}
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


def _load_series(path: Path, prefer_vars: tuple[str, ...] = ()) -> tuple[list[float] | None, int | None, str]:
    """Numeric read of one output. NetCDF: ONLY the rank-1 variable(s) when present in the
    file (codex #5), else all data variables (and say so). Text/CSV: per-column, dropping
    strictly-increasing index/time columns so a time axis can never satisfy 'has positive
    values'. Returns (values, n_rows_or_steps, note)."""
    suf = path.suffix.lower()
    try:
        if suf in (".nc", ".nc4", ".netcdf"):
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
        text = path.read_text(errors="ignore").replace("\ufeff", "")
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
        return None, None, f"unreadable ({type(e).__name__})"


def validate_outputs(ki_root: Path, outputs: list, *, expected_steps: int | None = None,
                     run_facts: dict | None = None, physical: bool = True) -> dict:
    """Return {"status": passed|failed|warning, "checks": [...]}.

    run_facts (REQUIRED in practice, validation_ladder.run_validity L149-177 contract):
      {"errored": bool, "continuity_pct": float|None, "output_nonempty": bool}
    physical=False: skip the rank-1 "physically required positive values" rule — for
    preparation-step outputs (forcing files, parameter decks) that are not the model's
    headline output. Model-run / routing / calibration steps keep physical=True.
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
    for out in outputs:
        p = Path(out)
        if not p.is_file():
            add(f"exists:{p.name}", False, str(p)); continue
        if p.stat().st_size == 0:
            add(f"non_empty:{p.name}", False, "0 bytes"); continue
        add(f"exists_non_empty:{p.name}", True, f"{p.stat().st_size} bytes")
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
    if not any_numeric:
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
        except (OSError, json.JSONDecodeError):
            out.append((p, {}, False)); continue
        out.append((p, doc, verify(project, doc)))
    return out


EXECUTABLE_STEP_KINDS = (
    "process", "run", "model_run", "calibrate", "route", "couple", "prepare", "download",
)


def _download_files_valid(project: Path, receipt: dict) -> bool:
    """Recheck both acquired and extracted files; reject paths outside the project."""
    raw = receipt.get("raw_files") or []
    if not raw:
        return False
    for entry in raw + (receipt.get("processed_files") or []):
        if not isinstance(entry, dict):
            return False
        path = Path(project) / str(entry.get("path") or "")
        try:
            if not _inside(path, project) or not path.is_file() or sha256_file(path) != str(entry.get("sha256") or ""):
                return False
        except OSError:
            return False
    return True


def _download_still_valid(project: Path, receipt: dict, inventory: dict | None) -> bool:
    """Reuse only an identical selected source/scope with intact acquired files."""
    item = next((it for it in (inventory or {}).get("items") or []
                 if isinstance(it, dict) and str(it.get("id")) == str(receipt.get("item_id"))), None)
    if item is None or not receipt.get("selection_sha256"):
        return False
    return receipt["selection_sha256"] == selection_sha256(item) and _download_files_valid(project, receipt)


def evidence(project: Path, plan: dict | None, approval: dict | None,
             output_dirs: tuple[str, ...] = ("outputs", "artifacts", "inputs", "calibration"),
             artifact_suffixes: tuple[str, ...] = (".nc", ".csv", ".txt", ".out", ".dat", ".tif",
                                                   ".png", ".json", ".bin"),
             enforcement: str = "none", inventory: dict | None = None) -> dict:
    """Machine-readable summary the UI shows and COMPLETED requires. Trusts ONLY receipts
    that verify AND are bound to the current approval (`approval_sha256 == the signed
    approval issuance's unique signature`), name a selected KI and a planned step. COMPLETED needs every
    executable planned step to have a passed receipt and no unreceipted artifacts.

    `enforcement` = how the EXECUTING provider was contained (flow.policy Enforcement value).
    kimi #2: the HMAC key lives in the user's config dir; a provider whose agent runs as the
    user with broad reads (codex workspace-write, kimi) COULD read it, so for those the
    receipts are `assurance: containment`, not `cryptographic`. Only when the provider's tool
    wall was EXACT (Claude allowedTools without a Read grant on the key dir; the API proxy,
    which gives the agent no file access at all) is the signature a proof against the agent."""
    project = Path(project)
    plan = plan or {}
    approval = approval or {}
    sig = approval.get("signature") if isinstance(approval, dict) else None
    cur = str(sig.get("value") or "") if isinstance(sig, dict) else ""
    selected = set(plan.get("selected_kis") or approval.get("selected_kis") or [])
    steps = {str(s.get("id")): s for s in (plan.get("steps") or []) if isinstance(s, dict)}
    exec_steps = {sid for sid, s in steps.items()
                  if (s.get("kind") or "process") in EXECUTABLE_STEP_KINDS}

    runs = _read_all(project, RUNS_SUB)
    dl = _read_all(project, DATA_SUB)
    rejected: list[dict] = []
    bound_runs: list[dict] = []

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
            bound_runs.append(d)
    bound_dl: list[dict] = []
    for p, d, ok in dl:
        if not ok:
            rejected.append({"path": str(p), "why": "signature"}); continue
        if not cur or d.get("approval_sha256") != cur:
            # A download made under an EARLIER approval survives a re-plan when the inventory
            # still pins the same selected source/scope and the files are intact (desktop
            # ACQUIRING: the data need not be fetched twice). Anything else is unbound.
            if d.get("selection_sha256") and inventory is not None and _download_still_valid(project, d, inventory):
                bound_dl.append(d)
            else:
                rejected.append({"path": str(p), "why": "not bound to the current approval"})
            continue
        if d.get("selection_sha256") and inventory is not None:
            # desktop receipts since 2026-09: the selected source/scope must still be the
            # one in the inventory, and the acquired files must be intact
            valid, why = _download_still_valid(project, d, inventory), "selected source or files changed"
        elif d.get("raw_files"):
            # receipts from before selection_sha256 existed (web chats, older desktop
            # projects): approval-bound, and the files they name are still intact
            valid, why = _download_files_valid(project, d), "acquired files changed or missing"
        else:
            valid, why = True, ""            # bound receipt without file entries: the web's rule
        if valid:
            bound_dl.append(d)
        else:
            rejected.append({"path": str(p), "why": why})

    receipted_outputs = set()
    for d in bound_runs:
        for o in d.get("outputs") or []:
            receipted_outputs.add(o.get("path"))
    for d in bound_dl:
        for o in (d.get("raw_files") or []) + (d.get("processed_files") or []):
            receipted_outputs.add(o.get("path"))
    unreceipted: list[str] = []
    for sub in output_dirs:
        base = project / sub
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            if p.is_file() and p.suffix.lower() in artifact_suffixes:
                rel = p.resolve().relative_to(project.resolve()).as_posix()
                if rel not in receipted_outputs:
                    unreceipted.append(rel)

    passed_steps = {str(d.get("plan_step_id")) for d in bound_runs
                    if (d.get("validation") or {}).get("status") == "passed"}
    # codex R2 #2: a planned 'download' step is satisfied by a bound download receipt that
    # names it and whose raw files all exist (no missing entries)
    for d in bound_dl:
        sid = str(d.get("plan_step_id"))
        if sid in steps and (steps[sid] or {}).get("kind") == "download" and \
                (d.get("raw_files") or []) and not any(f.get("missing") for f in d.get("raw_files") or []):
            passed_steps.add(sid)
    failed_any = any((d.get("validation") or {}).get("status") == "failed" for d in bound_runs)
    missing_steps = sorted(exec_steps - passed_steps)
    complete = bool(bound_runs) and not missing_steps and not unreceipted and not failed_any
    return {
        "approval_sha256": cur or None,
        "assurance": "cryptographic" if str(enforcement).lower() == "exact" else "containment",
        "runs_total": len(runs), "runs_bound": len(bound_runs),
        "downloads_total": len(dl), "downloads_bound": len(bound_dl),
        "rejected_receipts": rejected,
        "unreceipted_artifacts": unreceipted[:200],
        "executable_steps": sorted(exec_steps), "steps_passed": sorted(passed_steps),
        "steps_missing": missing_steps,
        "validation": "failed" if failed_any else ("passed" if complete else "incomplete"),
        "receipts_verified": complete,
        "runs": [{"run_id": d.get("run_id"), "ki": d.get("ki"), "exit_code": d.get("exit_code"),
                  "outputs": d.get("output_files_count"),
                  "validation": (d.get("validation") or {}).get("status"),
                  "plan_step_id": d.get("plan_step_id")} for d in bound_runs],
    }
