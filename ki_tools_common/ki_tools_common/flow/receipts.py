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
from pathlib import Path

RECEIPT_DIR = ".geoforge/receipts"
RUNS_SUB = "model-runs"
DATA_SUB = "data-receipts"


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
    try:
        k = _key(project, create=False)
    except ReceiptError:
        return False
    sig = (doc or {}).get("signature") or {}
    if not k or sig.get("alg") != "HMAC-SHA256" or not sig.get("value") \
            or sig.get("key_id") != project_id(project):
        return False
    return hmac.compare_digest(sig["value"], hmac.new(k, _canonical(doc), "sha256").hexdigest())


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
        text = path.read_text(errors="ignore")
        cols: dict[int, list[float]] = {}
        rows = 0
        for line in text.splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            rows += 1
            for j, tok in enumerate(line.replace(",", " ").replace(";", " ").split()):
                try:
                    cols.setdefault(j, []).append(float(tok))
                except ValueError:
                    pass
            if rows > 500000:
                break
        # Drop the index/time axis only: a LEADING column that is strictly increasing with a
        # constant step (1,2,3… or 20030101,20030102… or evenly spaced times). A cumulative
        # data column (kimi #8) is increasing but rarely constant-step, and is never dropped
        # when it is not the first numeric column.
        data_cols = []
        first = True
        for j in sorted(cols):
            c = cols[j]
            steps = [round(b - a, 9) for a, b in zip(c, c[1:])]
            axis_like = first and len(c) >= 2 and all(s > 0 for s in steps) and len(set(steps)) <= 2
            first = False
            if not axis_like:
                data_cols.append(c)
        if not data_cols and cols:
            data_cols = [cols[max(cols)]]
        vals = [v for c in data_cols for v in c]
        return vals, rows, "text"
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
        if finite and len(finite) > 10 and max(finite) == min(finite):
            add(f"not_constant:{p.name}", False, f"all values == {finite[0]}", level="warn")
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
    approval's plan_sha256`), name a selected KI and a planned step. COMPLETED needs every
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
    cur = str(approval.get("plan_sha256") or "")
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
        if (ok and cur and d.get("approval_sha256") == cur
                and _download_files_valid(project, d)
                and (inventory is None or _download_still_valid(project, d, inventory))):
            bound_dl.append(d)
        elif ok and _download_still_valid(project, d, inventory):
            bound_dl.append(d)
        else:
            rejected.append({"path": str(p), "why": "signature" if not ok else
                             "not bound to the current approval"})

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
