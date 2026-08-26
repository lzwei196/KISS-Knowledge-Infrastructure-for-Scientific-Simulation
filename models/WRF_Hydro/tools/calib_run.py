#!/usr/bin/env python3
"""
calib_run.py -- programmatic run+score of ONE WRF-Hydro parameter candidate.

TARGET CASE (pinned, NOT overridable from the environment):
    case_id      SITE:wangjiaba
    obs          china_gaugeflux -> KISSPATH_DATA/china_water_level/淮河txt/王家坝.txt
                 (stcd 50101100 == gauge 51030, Huai River main stem, ~30,630 km2)
    gauge        32.4275 N / 115.595 E, matched to a CHRTOUT channel feature with
                 Strahler order >= 2 (real_case WRF_Hydro_20260719T082141Z_172227)
    target       streamflow -> point_time_series, determining metric NSE

Usage
-----
    python calib_run.py --workdir <wd> --out <metrics.json>

injection.mode = runner.  The kit writes the candidate vector to the JSON at
$KDT_CALIB_PARAMS; this script injects every value into the artifacts WRF-Hydro
actually consumes (soil_properties.nc, GWBUCKPARM.nc, Fulldom_hires.nc,
CHANPARM.TBL), reads each one BACK out of that artifact, runs the model through
the KI's own run tool, extracts discharge through the KI's own extraction tool,
and scores against the pinned Wangjiaba obs.

Failure policy: any staging / injection / read-back / run / extraction problem
exits non-zero having written NO metrics file (the kit scores that as +inf).

Cost control: the model is warm-started from the completed reference run's
monthly RESTART + HYDRO_RST pair six months ahead of the scoring window, FORCING
is symlinked rather than copied, and the LDASOUT / RTOUT / CHRTOUT_GRID / GWOUT
output streams are switched off (only CHRTOUT is scored).  That turns the 11-year
cold-start reference run (2 h, ~300 MB of unused output) into a 42-month eval of
~40-65 min.  Nothing is downloaded or rebuilt per eval.
"""

import argparse
import json
import os
import shutil
import sys
import traceback
from pathlib import Path

import numpy as np

# --------------------------------------------------------------------------
# TARGET CASE — pinned constants.  Deliberately NOT read from the environment:
# an env-overridable gauge would let a mis-set variable score a different site
# while still self-declaring this one.
# --------------------------------------------------------------------------
CASE_ID = "SITE:wangjiaba"
OBS_DATASET = "china_gaugeflux"
OBS_FILE = Path("KISSPATH_DATA/china_water_level/淮河txt/王家坝.txt")
GAUGE_STCD = "50101100"
GAUGE_NAME = "王家坝 Wangjiaba"
GAUGE_LAT = 32.4275
GAUGE_LON = 115.595
MIN_ORDER = 2

# The channel feature the validated run scored (real_case_20260719T082156Z:
# idx=31, order 2, 32.511 N / 115.808 E, 22 km from the gauge = one coarse cell).
# Guard only: if a candidate's flow guard picks a different cell the eval is not
# comparable to the baseline, so it fails closed rather than silently rescoring
# somewhere else.
REF_CELL_LAT = 32.511
REF_CELL_LON = 115.808
REF_CELL_TOL_DEG = 0.05

# Completed reference run supplying DOMAIN, FORCING and the warm-start restarts.
REF_RUN = Path("KISSPATH_OUTPUTS/bengbu_wrfhydro_025deg_1980_1990")

KI_ROOT = Path(__file__).resolve().parent.parent
TOOLS = KI_ROOT / "tools"

# Blocked-temporal split.  Each split warm-starts 6 months before its scoring
# window so the conceptual GW bucket (which cold-starts at Zinit, GW_RESTART=0)
# and the soil column equilibrate under the CANDIDATE's parameters before any
# scored day.
# The holdout stops at 1988 because every 1989 day in the obs file is the -99
# missing marker (0 of 365 valid), so a 1989 model year would cost ~8 min per
# evaluation and contribute no scoreable day.
SPLITS = {
    "calibration": {"restart": "1980-07-01", "start": "1981-01-01", "end": "1983-12-31"},
    "holdout":     {"restart": "1986-07-01", "start": "1987-01-01", "end": "1988-12-31"},
}

# Read-back tolerance.  All of these fields are float32 on disk, so a requested
# float64 never round-trips bit-exactly; 1e-5 relative is ~80x float32 epsilon.
RTOL = 1e-5
ATOL = 1e-8


def die(msg):
    print(f"FATAL: {msg}", file=sys.stderr)
    sys.exit(1)


# --------------------------------------------------------------------------
# KI tool imports (reuse — the model is never reimplemented here)
# --------------------------------------------------------------------------
def load_ki_tools():
    sys.path.insert(0, str(TOOLS / "s10_execution"))
    sys.path.insert(0, str(TOOLS / "s11_output"))
    import run_wrfhydro
    import extract_discharge
    return run_wrfhydro, extract_discharge


def load_all_metrics():
    """Shared metric implementation; prefer the canonical package over the
    kdt-release copy, which has been observed stale and shadowing it."""
    for p in ("KISSPATH_KI_TOOLS_COMMON",
              "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect_multi_agent"):
        if Path(p, "ki_tools_common").is_dir():
            sys.path.insert(0, p)
            break
    from ki_tools_common.metrics import all_metrics
    return all_metrics


# --------------------------------------------------------------------------
# Parameter registry.  Each entry knows how to APPLY a value into the artifact
# WRF-Hydro consumes and how to READ IT BACK out of that same artifact.
# --------------------------------------------------------------------------
PARAMS = {
    # --- soil_properties.nc -------------------------------------------------
    "refkdt":       {"file": "soil_properties.nc", "kind": "nc_uniform", "var": "refkdt",
                     "default": 3.0},
    "slope":        {"file": "soil_properties.nc", "kind": "nc_uniform", "var": "slope",
                     "default": 0.1},
    "smcmax_mult":  {"file": "soil_properties.nc", "kind": "nc_scale", "var": "smcmax",
                     "default": 1.0, "skip_above": 0.9},
    # --- GWBUCKPARM.nc ------------------------------------------------------
    "gw_coeff":     {"file": "GWBUCKPARM.nc", "kind": "nc_uniform", "var": "Coeff",
                     "default": 44.84479904174805},
    "gw_expon":     {"file": "GWBUCKPARM.nc", "kind": "nc_uniform", "var": "Expon",
                     "default": 3.0},
    "gw_zmax":      {"file": "GWBUCKPARM.nc", "kind": "nc_uniform", "var": "Zmax",
                     "default": 250.0},
    "gw_zinit":     {"file": "GWBUCKPARM.nc", "kind": "nc_uniform", "var": "Zinit",
                     "default": 25.0},
    # --- Fulldom_hires.nc ---------------------------------------------------
    "ovroughrtfac": {"file": "Fulldom_hires.nc", "kind": "nc_uniform", "var": "OVROUGHRTFAC",
                     "default": 1.0},
    "retdeprtfac":  {"file": "Fulldom_hires.nc", "kind": "nc_uniform", "var": "RETDEPRTFAC",
                     "default": 1.0},
    "lksatfac":     {"file": "Fulldom_hires.nc", "kind": "nc_uniform", "var": "LKSATFAC",
                     "default": 1000.0},
    # --- CHANPARM.TBL -------------------------------------------------------
    "mann_n_mult":  {"file": "CHANPARM.TBL", "kind": "chanparm_scale", "var": "MannN",
                     "default": 1.0},
}

# Files copied (not symlinked) into the eval workdir because they are written to.
MUTABLE_DOMAIN = ["soil_properties.nc", "GWBUCKPARM.nc", "Fulldom_hires.nc", "hydro2dtbl.nc"]
LINKED_DOMAIN = ["geo_em.d01.nc", "wrfinput_d01.nc", "GWBASINS.nc",
                 "GEOGRID_LDASOUT_Spatial_Metadata.nc"]


# --------------------------------------------------------------------------
# Staging
# --------------------------------------------------------------------------
def stage_workdir(wd, split):
    wd.mkdir(parents=True, exist_ok=True)
    dom = wd / "DOMAIN"
    dom.mkdir(exist_ok=True)

    for f in LINKED_DOMAIN:
        src = REF_RUN / "DOMAIN" / f
        if not src.exists():
            die(f"reference DOMAIN file missing: {src}")
        dst = dom / f
        if not dst.exists():
            dst.symlink_to(src)
    for f in MUTABLE_DOMAIN:
        src = REF_RUN / "DOMAIN" / f
        if not src.exists():
            die(f"reference DOMAIN file missing: {src}")
        shutil.copy2(src, dom / f)

    forcing = wd / "FORCING"
    if not forcing.exists():
        if not (REF_RUN / "FORCING").is_dir():
            die(f"reference FORCING missing: {REF_RUN/'FORCING'}")
        forcing.symlink_to(REF_RUN / "FORCING")

    # Warm-start pair.  Copied, never symlinked: the model writes restarts into
    # the run dir and must not be able to touch the reference run's files.
    rdate = split["restart"]
    lsm_src = REF_RUN / f"RESTART.{rdate.replace('-','')}00_DOMAIN1"
    hyd_src = REF_RUN / f"HYDRO_RST.{rdate}_00:00_DOMAIN1"
    for src in (lsm_src, hyd_src):
        if not src.exists():
            die(f"warm-start restart missing: {src}")
        shutil.copy2(src, wd / src.name)
    return lsm_src.name, hyd_src.name


def hours_between(start, end):
    """Inclusive-of-end-day run length in hours, from restart date to end date."""
    import datetime as dt
    a = dt.date.fromisoformat(start)
    b = dt.date.fromisoformat(end)
    return int((b - a).days + 1) * 24


def write_namelists(wd, split, lsm_rst, hyd_rst):
    import datetime as dt
    r = dt.date.fromisoformat(split["restart"])
    khour = hours_between(split["restart"], split["end"])

    src_h = (REF_RUN / "namelist.hrldas").read_text()
    out = []
    for line in src_h.splitlines():
        s = line.strip()
        if s.startswith("START_YEAR"):
            out.append(f"START_YEAR  = {r.year}")
        elif s.startswith("START_MONTH"):
            out.append(f"START_MONTH = {r.month:02d}")
        elif s.startswith("START_DAY"):
            out.append(f"START_DAY   = {r.day:02d}")
        elif s.startswith("KHOUR"):
            out.append(f"KHOUR = {khour}")
        elif s.startswith("OUTPUT_TIMESTEP"):
            # Suppress per-day LDASOUT: it is ~270 MB per eval and calibration
            # scores CHRTOUT only.  A timestep longer than the run leaves just
            # the t0 file.
            out.append(f"OUTPUT_TIMESTEP  = {khour * 3600}")
        elif s.startswith("HRLDAS_SETUP_FILE"):
            out.append(line)
            out.append(f'RESTART_FILENAME_REQUESTED = "./{lsm_rst}"')
        else:
            out.append(line)
    (wd / "namelist.hrldas").write_text("\n".join(out) + "\n")

    src_y = (REF_RUN / "hydro.namelist").read_text()
    out = []
    for line in src_y.splitlines():
        s = line.strip()
        if s.startswith("RESTART_FILE"):
            out.append(f'RESTART_FILE = "./{hyd_rst}"')
        elif s.startswith("CHRTOUT_GRID"):
            out.append("CHRTOUT_GRID   = 0")
        elif s.startswith("RTOUT_DOMAIN"):
            out.append("RTOUT_DOMAIN   = 0")
        elif s.startswith("output_gw"):
            out.append("output_gw      = 0")
        elif s.startswith("GW_RESTART"):
            # 0 = bucket cold-starts at the candidate's Zinit, which is what
            # makes gw_zinit a real (screenable) parameter.  The 6-month spinup
            # ahead of every scoring window absorbs the transient.
            out.append("GW_RESTART = 0")
        else:
            out.append(line)
    (wd / "hydro.namelist").write_text("\n".join(out) + "\n")


# --------------------------------------------------------------------------
# Injection + read-back
# --------------------------------------------------------------------------
def _nc_open(path):
    import netCDF4 as nc
    return nc.Dataset(str(path), "r+")


def apply_params(wd, values):
    """Write every parameter into the artifact the model consumes.

    CHANPARM.TBL is NOT written here: run_wrfhydro.setup_symlinks() replaces
    every *.TBL in the run dir with a symlink to the shared model Run/ table,
    which would silently discard the injection.  It is written after that step
    (see main), and the shared table is never modified.
    """
    dom = wd / "DOMAIN"
    base = {}
    by_file = {}
    for name, val in values.items():
        spec = PARAMS[name]
        by_file.setdefault(spec["file"], []).append((name, val, spec))

    for fname, items in by_file.items():
        if fname == "CHANPARM.TBL":
            continue
        ds = _nc_open(dom / fname)
        try:
            for name, val, spec in items:
                v = ds.variables[spec["var"]]
                arr = np.asarray(v[:], dtype=np.float64)
                if spec["kind"] == "nc_uniform":
                    arr[...] = float(val)
                elif spec["kind"] == "nc_scale":
                    ref = np.asarray(
                        _read_original(fname, spec["var"]), dtype=np.float64)
                    mask = ref < spec["skip_above"]
                    base[name] = (ref, mask)
                    arr = np.where(mask, ref * float(val), ref)
                else:
                    die(f"unknown kind for {name}")
                v[:] = arr
        finally:
            ds.close()
    return base


_ORIG_CACHE = {}


def _read_original(fname, var):
    """Pristine field from the reference DOMAIN — the denominator for
    multiplier-style parameters, so scaling is never applied twice."""
    key = (fname, var)
    if key not in _ORIG_CACHE:
        import netCDF4 as nc
        ds = nc.Dataset(str(REF_RUN / "DOMAIN" / fname), "r")
        _ORIG_CACHE[key] = np.asarray(ds.variables[var][:], dtype=np.float64)
        ds.close()
    return _ORIG_CACHE[key]


def parse_chanparm(path):
    """Return (header_lines, rows) where rows are [order, Bw, HLINK, ChSSlp, MannN]."""
    lines = Path(path).read_text().splitlines()
    header, rows = [], []
    for ln in lines:
        parts = [p.strip() for p in ln.split(",")]
        if len(parts) == 5 and parts[0].lstrip("-").isdigit():
            try:
                rows.append([int(parts[0])] + [float(x) for x in parts[1:]])
                continue
            except ValueError:
                pass
        header.append(ln)
    if not rows:
        die(f"could not parse any channel rows from {path}")
    return header, rows


def write_chanparm(dst, mult):
    """Scale MannN on every Strahler order by `mult`, relative to the shared
    model table (never modified in place)."""
    src = Path(os.environ.get("WRFHYDRO_TBL_DIR", DEFAULT_TBL_DIR)) / "CHANPARM.TBL"
    header, rows = parse_chanparm(src)
    out = list(header)
    for r in rows:
        out.append(f"{r[0]},{r[1]:.6f},{r[2]:.6f},{r[3]:.6f},{r[4]*mult:.8f}")
    Path(dst).write_text("\n".join(out) + "\n")


def read_back(wd, values, base):
    """Read each applied value back out of the artifact the model consumes."""
    dom = wd / "DOMAIN"
    applied = {}
    import netCDF4 as nc
    for name, val in values.items():
        spec = PARAMS[name]
        if spec["file"] == "CHANPARM.TBL":
            _, rows = parse_chanparm(wd / "CHANPARM.TBL")
            _, orows = parse_chanparm(
                Path(os.environ.get("WRFHYDRO_TBL_DIR", DEFAULT_TBL_DIR)) / "CHANPARM.TBL")
            ratios = [r[4] / o[4] for r, o in zip(rows, orows) if o[4] != 0]
            if not ratios:
                die("CHANPARM read-back found no usable MannN rows")
            if max(ratios) - min(ratios) > 1e-6:
                die(f"CHANPARM MannN scaled inconsistently across orders: {ratios}")
            applied[name] = float(np.mean(ratios))
            continue

        ds = nc.Dataset(str(dom / spec["file"]), "r")
        try:
            arr = np.asarray(ds.variables[spec["var"]][:], dtype=np.float64)
        finally:
            ds.close()

        if spec["kind"] == "nc_uniform":
            u = np.unique(arr)
            if u.size != 1:
                die(f"{name}: expected a uniform field, found {u.size} distinct values")
            applied[name] = float(u[0])
        elif spec["kind"] == "nc_scale":
            ref, mask = base[name]
            if not mask.any():
                die(f"{name}: no cells eligible for scaling")
            ratios = arr[mask] / ref[mask]
            if float(ratios.max() - ratios.min()) > 1e-4:
                die(f"{name}: inconsistent scaling ratio across cells")
            applied[name] = float(np.mean(ratios))
    return applied


def verify(requested, applied):
    bad = []
    for k, want in requested.items():
        got = applied.get(k)
        if got is None:
            bad.append(f"{k}: not read back")
        elif not np.isclose(got, float(want), rtol=RTOL, atol=ATOL):
            bad.append(f"{k}: requested {want!r} but artifact holds {got!r}")
    if bad:
        die("parameter read-back mismatch (injection did not reach the model):\n  "
            + "\n  ".join(bad))


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------
def load_obs():
    """china_gaugeflux tab-separated gauge file.  -99 is the missing marker;
    Q == 0 is a REAL low-flow value on this intermittent gauge, so the filter is
    > -90, not > 0."""
    import pandas as pd
    if not OBS_FILE.exists():
        die(f"obs file missing: {OBS_FILE}")
    df = pd.read_csv(OBS_FILE, sep="\t", encoding="utf-8", encoding_errors="replace")
    stcds = set(str(int(s)) for s in df["stcd"].dropna().unique())
    if GAUGE_STCD not in stcds:
        die(f"{OBS_FILE} does not contain the target gauge stcd {GAUGE_STCD} "
            f"(found {sorted(stcds)})")
    df = df[df["stcd"].astype("Int64").astype(str) == GAUGE_STCD]
    df["date"] = pd.to_datetime(df["dates"])
    df = df.set_index("date")[["Q"]].astype(float)
    df = df[df["Q"] > -90.0]
    return df.rename(columns={"Q": "Q_obs"})


def score(wd, split, extract_discharge, all_metrics):
    """Extract at the gauge-matched feature through the KI tool, then score."""
    idx = extract_discharge.find_gauge_feature(
        wd, GAUGE_LAT, GAUGE_LON, min_order=MIN_ORDER)

    import netCDF4 as nc
    files = sorted(Path(wd).glob("*.CHRTOUT_DOMAIN1"))
    if not files:
        die("no CHRTOUT_DOMAIN1 produced by the run")
    ds = nc.Dataset(str(files[len(files) // 2]), "r")
    cell_lat = float(np.asarray(ds.variables["latitude"][:]).ravel()[idx])
    cell_lon = float(np.asarray(ds.variables["longitude"][:]).ravel()[idx])
    cell_order = int(np.asarray(ds.variables["order"][:]).ravel()[idx])
    ds.close()

    # Guard: the scored cell must be the one the validated run scored.  If a
    # candidate's parameters dried the channel and the flow guard moved the
    # match elsewhere, the eval is not comparable -> fail closed.
    if (abs(cell_lat - REF_CELL_LAT) > REF_CELL_TOL_DEG
            or abs(cell_lon - REF_CELL_LON) > REF_CELL_TOL_DEG):
        die(f"gauge match moved to {cell_lat:.4f}N/{cell_lon:.4f}E, expected "
            f"{REF_CELL_LAT}N/{REF_CELL_LON}E — not the validated Wangjiaba cell")

    daily = extract_discharge.extract_daily_discharge(wd, idx)
    obs = load_obs()
    merged = obs.join(daily, how="inner").dropna()
    merged = merged.loc[split["start"]:split["end"]]
    if len(merged) < 365:
        die(f"only {len(merged)} scoreable days in "
            f"{split['start']}..{split['end']} — refusing to score")

    m = all_metrics(merged["Q_obs"].values, merged["Q_sim"].values)
    if not np.isfinite(m.get("NSE", np.nan)):
        die("NSE is not finite")

    scored_obs = (f"{OBS_DATASET}:{GAUGE_STCD} ({GAUGE_NAME}) "
                  f"{OBS_FILE} @ {GAUGE_LAT}N/{GAUGE_LON}E -> CHRTOUT feature "
                  f"idx={idx} order={cell_order} {cell_lat:.4f}N/{cell_lon:.4f}E; "
                  f"{split['start']}..{split['end']} n={len(merged)}")
    return m, scored_obs, len(merged)


# --------------------------------------------------------------------------
DEFAULT_TBL_DIR = os.path.join(
    os.environ.get("HYDROCRAFT_ROOT", "KISSPATH_ROOT"),
    "model/wrf_hydro/source/trunk/NDHMS/Run")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--nproc", type=int,
                    default=int(os.environ.get("KDT_CALIB_NPROC", "8")))
    ap.add_argument("--timeout", type=int,
                    default=int(os.environ.get("KDT_CALIB_TIMEOUT", "7200")))
    args = ap.parse_args()

    wd = Path(args.workdir).resolve()
    out = Path(args.out)

    split_name = os.environ.get("KDT_CALIB_SPLIT", "calibration").strip().lower()
    if split_name not in SPLITS:
        die(f"KDT_CALIB_SPLIT={split_name!r} is not one of {sorted(SPLITS)}")
    split = SPLITS[split_name]

    # ---- candidate vector -------------------------------------------------
    requested = {}
    pfile = os.environ.get("KDT_CALIB_PARAMS")
    if pfile:
        if not Path(pfile).exists():
            die(f"KDT_CALIB_PARAMS points at a missing file: {pfile}")
        requested = json.loads(Path(pfile).read_text())
    unknown = set(requested) - set(PARAMS)
    if unknown:
        die(f"unknown parameter(s) in KDT_CALIB_PARAMS: {sorted(unknown)}")

    # Every registered parameter is applied, so the run is fully determined;
    # frozen/absent ones take their default.
    values = {k: float(requested.get(k, PARAMS[k]["default"])) for k in PARAMS}

    run_wrfhydro, extract_discharge = load_ki_tools()
    all_metrics = load_all_metrics()

    # ---- stage + inject ---------------------------------------------------
    lsm_rst, hyd_rst = stage_workdir(wd, split)
    write_namelists(wd, split, lsm_rst, hyd_rst)
    base = apply_params(wd, values)

    ok, msgs = run_wrfhydro.preflight_check(wd)
    if not ok:
        die("run_wrfhydro preflight failed:\n  " + "\n  ".join(msgs))

    # setup_symlinks re-links every *.TBL, so CHANPARM.TBL must be written after
    # it, and run_model() invoked directly rather than re-entering the CLI.
    tbl_dir = os.environ.get("WRFHYDRO_TBL_DIR", DEFAULT_TBL_DIR)
    exe = os.environ.get("WRFHYDRO_EXE", str(run_wrfhydro.DEFAULT_WRF_HYDRO_EXE))
    mpirun = os.environ.get("WRFHYDRO_MPIRUN", str(run_wrfhydro.DEFAULT_MPIRUN))
    run_wrfhydro.setup_symlinks(wd, exe, tbl_dir)

    chanparm = wd / "CHANPARM.TBL"
    if chanparm.is_symlink():
        chanparm.unlink()
    write_chanparm(chanparm, values["mann_n_mult"])

    # ---- read back BEFORE running; a value that did not land never runs ----
    applied = read_back(wd, values, base)
    verify(values, applied)

    # ---- run --------------------------------------------------------------
    res = run_wrfhydro.run_model(wd, mpirun, args.nproc, args.timeout)
    if not res.get("success"):
        die(f"WRF-Hydro did not finish (rc={res.get('returncode')}, "
            f"{res.get('elapsed_s')}s): {res.get('diag_last_lines')}")

    # ---- score ------------------------------------------------------------
    m, scored_obs, n = score(wd, split, extract_discharge, all_metrics)

    payload = {
        "nse": float(m["NSE"]),
        "kge": float(m["KGE"]),
        "pbias": float(m["PBIAS"]),
        "r": float(m["r"]),
        "rmse": float(m["RMSE"]),
        "__kdt__": {
            # Echo EVERY key handed to us (including any frozen at default in a
            # staged round), reporting the value actually read back out of the
            # model's own inputs.
            "applied_params": {k: applied[k] for k in requested} if requested
                              else {k: applied[k] for k in PARAMS},
            "case_id": CASE_ID,
            # Derived from the same variables used to read the obs and pick the
            # model cell, so the declaration cannot diverge from what was scored.
            "scored_obs": scored_obs,
            "split": split_name,
            "n_days": n,
            "elapsed_s": res.get("elapsed_s"),
        },
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2))
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        sys.exit(1)
