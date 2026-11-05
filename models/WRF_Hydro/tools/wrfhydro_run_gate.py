"""
wrfhydro_run_gate.py -- one strict rule for "is this WRF-Hydro run folder finished?"

Used by the run_and_score*.py runners (model root and knowledge_infrastructure/).
Added 2026-10-05 to replace CHRTOUT file counting (>= 98 %, >= 95 %, >= 50 %
"score AS-IS", EXPECTED_DAYS - 5 / - 10). A file count is no proof: a run that
stops at the last hour leaves almost every file, and a folder built from other
inputs has the same count.

A run folder counts as finished only if BOTH hold:
  (a) WRF-Hydro's own banner "The model finished successfully" is in a current
      diag_hydro.* file directly in the run folder (not in previous_diag_*/ or
      previous_run_*/ folders), and
  (b) run_inputs.json, written by the runner just before launch, equals the
      inputs the folder holds now: sha256 of namelist.hrldas, hydro.namelist and
      every file under DOMAIN/, a listing (relative name, size, mtime) of the
      forcing folder named by INDIR (FORCING/ by default; files are not hashed),
      the forcing folder's real path, and the runner's start/end dates (plus any
      extra items the runner adds).

Missing inputs (no namelist, no DOMAIN/, no forcing folder, empty forcing)
raise an error: they are never filled or skipped.

Parameter tables (2026-10-15): with tables=True the sha256 of every *.TBL in
the run folder is part of the identity (read only; a check never changes a
file), so a changed GENPARM.TBL / SOILPARM.TBL makes an old run "not finished".
stage_tables() is the separate launch-time step: it makes the run folder hold
the install tables (as s10 run_wrfhydro.py does at launch) and MOVES any
run-local table that differs into a kept folder first, never deleting it.
Without tables=True the identity is the old one (model-root runners).

Ships inside the KI (knowledge_infrastructure/tools/); WRF_Hydro/wrfhydro_run_gate.py
at the model root only loads this file. WRF_Hydro_NWM keeps its own copy.
"""
import datetime as _dt
import hashlib
import json
import os
import re
from pathlib import Path

BANNER = "The model finished successfully"
RUN_INPUTS = "run_inputs.json"
# Written by require_finished_after_run ONLY, i.e. after the launcher returned
# exit 0 and the folder passed the check; holds the sha256 of run_inputs.json.
# A banner left by a run whose process then failed (non-zero MPI exit) has no
# such record, so a resume never takes it as finished.
RUN_COMPLETE = "run_complete.json"
SCHEMA = "wrfhydro_run_inputs/v1"

# Files a WRF-Hydro run writes into its run folder. They are moved aside (kept,
# never deleted) before a fresh run. run_inputs.json goes with them.
OUTPUT_PATTERNS = (
    "*.CHRTOUT_DOMAIN1", "*.CHRTOUT_GRID1", "*.CHANOBS_DOMAIN1", "*.LDASOUT_DOMAIN1",
    "*.RTOUT_DOMAIN1", "*.GWOUT_DOMAIN1", "*.LAKEOUT_DOMAIN1", "*.LSMOUT_DOMAIN1",
    "RESTART.*", "HYDRO_RST.*", "diag_hydro.*", "frxst_pts_out.txt",
    "qstrmvolrt_accum.txt", "GW_inflow.txt", "GW_outflow.txt", "GW_zlev.txt",
    RUN_INPUTS, RUN_COMPLETE,
)


class RunGateError(RuntimeError):
    """Inputs needed for the identity check are missing or unreadable."""


def _sha256(path, bufsize=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(bufsize)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def banner_found(run_dir):
    """True if the completion banner is in a current diag_hydro.* file
    directly inside run_dir (old copies in previous_* folders do not count)."""
    for f in sorted(Path(run_dir).glob("diag_hydro.*")):
        if not f.is_file():
            continue
        try:
            if BANNER in f.read_text(errors="replace"):
                return True
        except OSError:
            continue
    return False


def _forcing_dir(run_dir):
    """Forcing folder the run reads: INDIR from namelist.hrldas (relative to
    run_dir), else run_dir/FORCING."""
    run_dir = Path(run_dir)
    nl = run_dir / "namelist.hrldas"
    indir = None
    if nl.is_file():
        m = re.search(r"(?mi)^\s*INDIR\s*=\s*['\"]([^'\"]+)['\"]", nl.read_text(errors="replace"))
        if m:
            indir = m.group(1).strip()
    if not indir:
        indir = "./FORCING"
    p = Path(indir)
    return p if p.is_absolute() else (run_dir / p)


def domain_hashes(domain_dir):
    """sha256 of every file under domain_dir (symlinks followed), by relative name."""
    domain_dir = Path(domain_dir)
    if not domain_dir.is_dir():
        raise RunGateError(f"DOMAIN folder missing: {domain_dir}")
    out = {}
    for root, _dirs, files in os.walk(os.path.realpath(domain_dir), followlinks=True):
        for name in files:
            fp = Path(root) / name
            rel = os.path.relpath(fp, os.path.realpath(domain_dir))
            out[rel] = _sha256(fp)
    if not out:
        raise RunGateError(f"DOMAIN folder is empty: {domain_dir}")
    return dict(sorted(out.items()))


def forcing_listing(forcing_dir):
    """(relative name, size, mtime_ns) of every file under forcing_dir; files are
    not hashed. Returns a short summary plus the sha256 of the full listing."""
    forcing_dir = Path(forcing_dir)
    if not forcing_dir.is_dir():
        raise RunGateError(f"forcing folder missing: {forcing_dir}")
    real = os.path.realpath(forcing_dir)
    rows = []
    for root, _dirs, files in os.walk(real, followlinks=True):
        for name in files:
            fp = os.path.join(root, name)
            st = os.stat(fp)
            rows.append([os.path.relpath(fp, real), int(st.st_size), int(st.st_mtime_ns)])
    if not rows:
        raise RunGateError(f"forcing folder is empty: {forcing_dir}")
    rows.sort()
    h = hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode()).hexdigest()
    return {"realpath": real, "n_files": len(rows), "first": rows[0][0],
            "last": rows[-1][0], "listing_sha256": h}


def stage_tables(run_dir, tbl_dir, keep_dir=None):
    """Launch-time only (never called by a check). Make every *.TBL of tbl_dir
    a real file in run_dir with the install content, the same copy s10
    run_wrfhydro.py makes at launch. A run-local real table whose content
    differs is first MOVED into keep_dir (default run_dir/previous_tables_<time>/),
    so its values are kept; a symlink is removed (its target is untouched).
    Returns (names staged, folder with kept tables or None)."""
    import shutil
    run_dir, tbl_dir = Path(run_dir), Path(tbl_dir)
    tbls = sorted(tbl_dir.glob("*.TBL"))
    if not tbls:
        raise RunGateError(f"no *.TBL parameter tables in {tbl_dir}")
    kept = None
    for src in tbls:
        dest = run_dir / src.name
        if dest.is_symlink():
            dest.unlink()
        elif dest.is_file():
            if _sha256(dest) == _sha256(src.resolve()):
                continue
            if kept is None:
                kept = Path(keep_dir) if keep_dir else (
                    run_dir / f"previous_tables_{_dt.datetime.now():%Y%m%dT%H%M%S}")
                kept.mkdir(parents=True, exist_ok=True)
            os.replace(dest, kept / dest.name)
        elif dest.exists():
            raise RunGateError(f"{dest} exists but is not a regular file")
        shutil.copyfile(src.resolve(), dest)
    return [s.name for s in tbls], kept


def table_hashes(run_dir):
    """sha256 of every *.TBL in the run folder; a link (shared table) or no table stops."""
    run_dir = Path(run_dir)
    out = {}
    for f in sorted(run_dir.glob("*.TBL")):
        if f.is_symlink():
            raise RunGateError(f"{f} is a symlink; parameter tables must be real files in the run folder")
        out[f.name] = _sha256(f)
    if not out:
        raise RunGateError(f"no *.TBL parameter tables in {run_dir}")
    return out


def current_inputs(run_dir, start, end, extra=None, tables=False, exe=None, tbl_dir=None):
    """Identity of the inputs the run folder holds right now (read only). With
    tables=True the run folder's own *.TBL hashes are included."""
    run_dir = Path(run_dir)
    nls = {}
    for name in ("namelist.hrldas", "hydro.namelist"):
        p = run_dir / name
        if not p.is_file():
            raise RunGateError(f"{name} missing in {run_dir}")
        nls[name] = _sha256(p)
    ident = {
        "schema": SCHEMA,
        "start": str(start),
        "end": str(end),
        "namelists_sha256": nls,
        "domain_sha256": domain_hashes(run_dir / "DOMAIN"),
        "forcing": forcing_listing(_forcing_dir(run_dir)),
    }
    if tables:
        ident["tables_sha256"] = table_hashes(run_dir)
    if tbl_dir is not None:
        # the install tables the next launch copies in (stage_tables /
        # run_wrfhydro.py --tbl_dir): read only, so a changed GENPARM.TBL in the
        # install makes an old run "not finished" before anything is staged
        src = {}
        for f in sorted(Path(tbl_dir).glob("*.TBL")):
            src[f.name] = _sha256(f.resolve())
        if not src:
            raise RunGateError(f"no *.TBL parameter tables in {tbl_dir}")
        ident["source_tables_sha256"] = src
    if exe is not None:
        # the executable the next launch runs (the runner passes the same path
        # to run_wrfhydro.py --exe): a rebuilt binary makes an old run "not finished"
        ex = Path(exe)
        if not ex.resolve().is_file():
            raise RunGateError(f"model executable missing: {exe}")
        ident["exe"] = {"realpath": os.path.realpath(ex), "sha256": _sha256(ex.resolve())}
    if extra:
        ident["extra"] = json.loads(json.dumps(extra, sort_keys=True, default=str))
    return ident


def write_run_inputs(run_dir, start, end, extra=None, tables=False, exe=None, tbl_dir=None):
    """Write run_inputs.json just before launching the model. Returns the identity."""
    ident = current_inputs(run_dir, start, end, extra, tables=tables, exe=exe, tbl_dir=tbl_dir)
    rec = dict(ident)
    rec["written_at"] = _dt.datetime.now().isoformat(timespec="seconds")
    p = Path(run_dir) / RUN_INPUTS
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(rec, indent=1, sort_keys=True))
    os.replace(tmp, p)
    return ident


def _diff_keys(a, b, prefix=""):
    out = []
    for k in sorted(set(a) | set(b)):
        if k not in a or k not in b:
            out.append(prefix + k)
        elif isinstance(a[k], dict) and isinstance(b[k], dict):
            out.extend(_diff_keys(a[k], b[k], prefix + k + "."))
        elif a[k] != b[k]:
            out.append(prefix + k)
    return out


def check_finished(run_dir, start, end, extra=None, tables=False, _need_complete=True, exe=None,
                   tbl_dir=None):
    """(True, reason) only if the banner is present AND run_inputs.json matches
    the current inputs AND run_complete.json (written only after a launch that
    exited 0) belongs to this run_inputs.json. The banner is checked first;
    run_inputs.json is only read after it."""
    run_dir = Path(run_dir)
    if not banner_found(run_dir):
        return False, f"no '{BANNER}' in a current diag_hydro.* in {run_dir}"
    p = run_dir / RUN_INPUTS
    if not p.is_file():
        return False, f"banner found but no {RUN_INPUTS} written at launch in {run_dir}"
    try:
        saved = json.loads(p.read_text())
    except (OSError, ValueError) as e:
        return False, f"{RUN_INPUTS} unreadable in {run_dir}: {e}"
    saved.pop("written_at", None)
    try:
        now = current_inputs(run_dir, start, end, extra, tables=tables, exe=exe, tbl_dir=tbl_dir)
    except RunGateError as e:
        # Inputs gone: the folder cannot be shown to match; never "finished".
        return False, f"cannot check inputs: {e}"
    if saved != now:
        diff = _diff_keys(saved, now)
        return False, f"inputs differ from {RUN_INPUTS} ({', '.join(diff[:8])}{' ...' if len(diff) > 8 else ''})"
    if _need_complete:
        c = run_dir / RUN_COMPLETE
        if not c.is_file():
            return False, (f"banner and inputs match but no {RUN_COMPLETE}: the launch was never "
                           f"confirmed to exit 0")
        try:
            comp = json.loads(c.read_text())
        except (OSError, ValueError) as e:
            return False, f"{RUN_COMPLETE} unreadable: {e}"
        if comp.get("run_inputs_sha256") != _sha256(p):
            return False, f"{RUN_COMPLETE} belongs to another {RUN_INPUTS}"
        return True, f"banner found, inputs match {RUN_INPUTS}, launch exit 0 recorded"
    return True, f"banner found and inputs match {RUN_INPUTS}"


def move_outputs_aside(run_dir, label="previous_run"):
    """Move old output files into run_dir/<label>_<time>/ (kept, never deleted).
    Files named in namelist.hrldas / hydro.namelist (e.g. a requested restart
    file) are inputs and are left in place. Returns (folder or None, n_moved)."""
    run_dir = Path(run_dir)
    referenced = ""
    for name in ("namelist.hrldas", "hydro.namelist"):
        p = run_dir / name
        if p.is_file():
            referenced += p.read_text(errors="replace")
    files = []
    for pat in OUTPUT_PATTERNS:
        for f in run_dir.glob(pat):
            if (f.is_file() or f.is_symlink()) and f.name not in referenced and f not in files:
                files.append(f)
    if not files:
        return None, 0
    dest = run_dir / f"{label}_{_dt.datetime.now().strftime('%Y%m%dT%H%M%S')}"
    n = 1
    while dest.exists():
        dest = run_dir / f"{label}_{_dt.datetime.now().strftime('%Y%m%dT%H%M%S')}_{n}"
        n += 1
    dest.mkdir()
    for f in files:
        os.rename(f, dest / f.name)
    return dest, len(files)


def invalidate_completion(run_dir):
    """Call at EVERY real launch, before MPI starts: an older run_complete.json
    must never vouch for this launch (a banner written before a non-zero exit
    would otherwise be taken with the old record). It is renamed, not deleted.
    run_inputs.json is left in place: the runners write it just before the
    launch as this launch's identity, and without a new run_complete.json it
    can never make the folder "finished". Returns the kept path or None."""
    c = Path(run_dir) / RUN_COMPLETE
    if not c.exists():
        return None
    keep = c.with_name(f"{RUN_COMPLETE}.superseded_{_dt.datetime.now():%Y%m%dT%H%M%S%f}")
    os.replace(c, keep)
    return keep


def require_finished_after_run(run_dir, start, end, extra=None, tables=False, exe=None, tbl_dir=None):
    """Call ONLY after the launcher returned exit 0: the folder must pass the
    same strict rule (banner + inputs), else raise; then run_complete.json is
    written, tied to run_inputs.json by its sha256."""
    ok, why = check_finished(run_dir, start, end, extra, tables=tables, _need_complete=False, exe=exe,
                             tbl_dir=tbl_dir)
    if not ok:
        raise RuntimeError(f"WRF-Hydro run in {run_dir} is not finished after launch: {why}")
    run_dir = Path(run_dir)
    rec = {"run_inputs_sha256": _sha256(run_dir / RUN_INPUTS),
           "written_at": _dt.datetime.now().isoformat(timespec="seconds"),
           "launcher_exit": 0}
    tmp = run_dir / (RUN_COMPLETE + ".tmp")
    tmp.write_text(json.dumps(rec, indent=1))
    os.replace(tmp, run_dir / RUN_COMPLETE)
    return why


FORCING_STAMP = "forcing_geo_em.sha256"


def forcing_matches_domain(forcing_dir, geo_em):
    """(ok, why): forcing interpolated onto a grid may be reused only for the same
    geo_em. The runner writes FORCING_STAMP (sha256 of the geo_em used) after it
    builds forcing; no LDASIN yet -> ok (nothing to reuse); LDASIN without a stamp
    or with another hash -> not ok."""
    fd = Path(forcing_dir)
    if not fd.is_dir() or not any(fd.glob("*.LDASIN_DOMAIN1")):
        return True, "no forcing yet"
    st = fd / FORCING_STAMP
    if not Path(geo_em).is_file():
        raise RunGateError(f"{geo_em} missing; cannot tell which grid the forcing must be on")
    if not st.is_file():
        return False, f"no {FORCING_STAMP}: cannot show the forcing is for this geo_em"
    if st.read_text().strip() != _sha256(geo_em):
        return False, "forcing was built for another geo_em (sha256 differs)"
    return True, "forcing built for this geo_em"


def stamp_forcing(forcing_dir, geo_em):
    """Write the stamp only if its content changes: forcing_listing() includes
    file mtimes, so rewriting an equal stamp would make a finished run look
    changed."""
    st = Path(forcing_dir) / FORCING_STAMP
    want = _sha256(geo_em)
    if st.is_file() and st.read_text().strip() == want:
        return False
    st.write_text(want + "\n")
    return True


def move_forcing_aside(forcing_dir, log=print):
    """Keep forcing that cannot be reused (moved to a dated sibling); start empty."""
    fd = Path(forcing_dir)
    stamp = f"{fd.name}.other_domain_{_dt.datetime.now():%Y%m%dT%H%M%S}"
    dest, n = fd.with_name(stamp), 1
    while dest.exists():
        dest, n = fd.with_name(f"{stamp}_{n}"), n + 1
    os.rename(fd, dest)
    fd.mkdir(parents=True)
    log(f"  forcing: moved to {dest.name} (kept)")
    return dest


def require_forcing_source(run_dir, expected_dir):
    """The forcing folder the run reads (INDIR, usually a FORCING link) must be
    the runner's own forcing folder; a link to other forcing stops the run."""
    got = os.path.realpath(_forcing_dir(run_dir))
    want = os.path.realpath(expected_dir)
    if got != want:
        raise RunGateError(f"{run_dir}: forcing folder resolves to {got}, expected {want}")
    return got


# ---------------------------------------------------------------------------
# Forcing must be finite: no nearest-neighbour (or any) fill. Added 2026-10-05.
FORCING_VARS = ("T2D", "Q2D", "U2D", "V2D", "PSFC", "SWDOWN", "LWDOWN", "RAINRATE")
_STAMP = _dt.datetime.now().strftime("%Y%m%dT%H%M%S")


def retire_prefilled_month(fdir, y, m):
    """The old runners nearest-filled non-finite cells IN PLACE and left a
    .sanitized_YYYYMM marker. Such a month may hold filled values, so its LDASIN
    files and the marker are moved to a sibling folder <fdir>.prefill_aside_<time>/
    (kept, never deleted); the caller then regenerates the month from source.
    Returns the number of files moved."""
    fdir = Path(os.path.realpath(fdir))
    marker = fdir / f".sanitized_{y}{m:02d}"
    if not marker.exists():
        return 0
    dest = fdir.parent / f"{fdir.name}.prefill_aside_{_STAMP}"
    dest.mkdir(exist_ok=True)
    files = sorted(fdir.glob(f"{y}{m:02d}*.LDASIN_DOMAIN1"))
    for f in files:
        os.rename(f, dest / f.name)
    os.rename(marker, dest / marker.name)
    for old in fdir.glob(f".finite_checked_{y}{m:02d}"):
        os.rename(old, dest / old.name)
    return len(files)


def _land_mask(wrfinput):
    """XLAND from wrfinput (1 = land, 2 = water), for the error message only."""
    try:
        import numpy as np
        import netCDF4 as nc
        with nc.Dataset(str(wrfinput)) as ds:
            if "XLAND" in ds.variables:
                return np.squeeze(np.asarray(ds["XLAND"][:], dtype="f8"))
    except Exception:
        pass
    return None


def check_forcing_month(fdir, y, m, wrfinput=None, vnames=FORCING_VARS):
    """Every LDASIN file of month y-m must carry all forcing variables with only
    finite values. Nothing is filled. On any non-finite cell, raise naming the
    variable, the file time and the cell count (and how many of those cells are
    land in wrfinput XLAND, as evidence; the run still stops either way, because
    nothing here proves the model never reads them). A passed month is recorded
    in .finite_checked_YYYYMM with its file listing; it is re-checked whenever
    the listing changes."""
    import numpy as np
    import netCDF4 as nc
    fdir = Path(fdir)
    files = sorted(fdir.glob(f"{y}{m:02d}*.LDASIN_DOMAIN1"))
    if not files:
        raise RunGateError(f"no LDASIN files for {y}-{m:02d} in {fdir}")
    listing = [[f.name, f.stat().st_size, f.stat().st_mtime_ns] for f in files]
    lh = hashlib.sha256(json.dumps([list(vnames), listing]).encode()).hexdigest()
    rec = fdir / f".finite_checked_{y}{m:02d}"
    if rec.is_file() and rec.read_text().strip() == lh:
        return 0
    xland = _land_mask(wrfinput) if wrfinput else None
    problems, total = [], 0
    for fp in files:
        with nc.Dataset(str(fp)) as ds:
            for v in vnames:
                if v not in ds.variables:
                    raise RunGateError(f"{fp.name}: forcing variable {v} missing")
                arr = np.ma.filled(ds[v][0].astype("f8"), np.nan)
                bad = ~np.isfinite(arr) | (np.abs(arr) > 1e19)
                n = int(bad.sum())
                if n:
                    total += n
                    land = (int((bad & (xland < 1.5)).sum())
                            if xland is not None and xland.shape == bad.shape else None)
                    problems.append(f"{v} at {fp.name.split('.')[0]}: {n} of {bad.size} cells"
                                    + (f" ({land} on land per XLAND)" if land is not None else ""))
    if problems:
        raise RunGateError(
            f"non-finite forcing in {fdir} for {y}-{m:02d}: {len(problems)} variable/time "
            f"slices, {total} cells; not filled. First: " + "; ".join(problems[:10]))
    rec.write_text(lh + "\n")
    return 0


def exit_by_result(result_path, t0, key="status", ok_values=("completed", "success", "applied")):
    """Call right after a runner's main(). A run must not exit 0 unless the
    result.json written by THIS call (mtime >= t0) says completed/success/applied
    and, when it carries metrics, has an NSE. Otherwise exit 1 with the reason."""
    import sys
    p = Path(result_path)
    if not p.is_file() or p.stat().st_mtime < t0:
        sys.exit(f"no new {p} written by this run -> exit 1")
    try:
        res = json.loads(p.read_text())
    except (OSError, ValueError) as e:
        sys.exit(f"{p} unreadable ({e}) -> exit 1")
    st = res.get(key)
    if st not in ok_values:
        sys.exit(f"result {key}={st!r} in {p} -> exit 1")
    m = res.get("metrics")
    if isinstance(m, dict) and "nse" in m and m.get("nse") is None:
        sys.exit(f"result {key}={st!r} but metrics.nse is None in {p} -> exit 1")
    return 0
