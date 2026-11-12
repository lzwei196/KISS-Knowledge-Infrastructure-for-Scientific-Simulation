#!/usr/bin/env python3
"""Programmatic run+score for MARRMoT calibration (NOT a claude agent).

Usage:  python calib_run.py --workdir <wd> --out <metrics.json>

Contract (calibration.yaml, injection.mode: runner): the calibration kit hands this
candidate's parameters as a JSON object {x1,x2,x3,x4} at $KDT_CALIB_PARAMS.
This script:
  1. reads the CURRENT theta from that file (x1,x2,x3,x4 -> [x1,x2,x3,x4]);
  2. runs the model end-to-end via the KI's tools/run_marrmot.py (the SAME forward
     path the validated Bengbu 51080 real-case used), over the CMFD/Oudin forcing
     and the Bengbu obs, cached under <workdir>/calib. Input selection is: an
     existing valid workdir cache, else the KI's calib/forcing.csv + calib/obs_q.csv
     (read only, copied), else a rebuild from the original Bengbu sources. Every
     source is checked to cover the run window (1979-01-01 .. 1990-12-31, spin-up
     1979-1980 included) before it is used; if none does, the script fails loudly.
     Date checks do not establish basin identity: use an empty workdir or a cache
     known to contain the Bengbu inputs. The generic detached/real_case is not used;
  3. scores simulated Q (mm/d) vs observed Q with ki_tools_common.metrics.all_metrics
     on the split selected by env KDT_CALIB_SPLIT ("calibration" | "holdout");
  4. writes a FLAT lowercase metrics dict {nse,kge,pbias,r,...} as JSON to --out,
     echoing the theta it ran as __kdt__.applied_params plus __kdt__.case_id /
     __kdt__.scored_obs (the gauge it scored).

The KI is read in place and never written: on a desktop it is the project's
verified copy, which the integrity guard refuses once a byte changes. Every file
this script writes (cached inputs, the forward-run scratch) lives under --workdir.

Determining metric for Q/point_time_series is NSE (temporal_pattern_match); PBIAS
(magnitude_accuracy) is also gate-valid. objectives.py reads flat lowercase keys
'nse' and 'pbias', so those are emitted verbatim (all_metrics returns UPPERCASE
NSE/KGE/PBIAS + lowercase r -> we lowercase them here).

On ANY failure the script writes NO metrics file and exits nonzero, so the kit
scores that candidate +inf (never a fake pass). Keep it FAST: a single ~5 s Octave
forward run per eval; forcing/obs are deterministic and cached, never rebuilt in
the optimization loop.

Splits (spin-up 1979-1980 discarded from both):
  calibration : 1981-01-01 .. 1985-12-31
  holdout     : 1986-01-01 .. 1990-12-31
Default (KDT_CALIB_SPLIT unset) scores the CALIBRATION window so the optimizer
never trains on held-out years.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True

import numpy as np
import pandas as pd

KI = "KISSPATH_KI_ROOT/MARRMoT/knowledge_infrastructure"
KTC = "KISSPATH_KI_TOOLS_COMMON"
MODEL = "m_07_gr4j_4p_2s"
sys.path.insert(0, os.path.join(KI, "tools"))
from octave_runtime import marrmot_source  # noqa: E402
# The installed source (binaries/MARRMoT/source/repo/MARRMoT on a desktop), else the server checkout.
MARRMOT_SRC = marrmot_source() or "KISSPATH_KI_ROOT/MARRMoT/source/repo/MARRMoT"
AREA_KM2 = 121330.0
CENTROID_LAT = 33.0
START_Y, END_Y = 1979, 1990
CMFD_DIR = "KISSPATH_FORCING/huai/Data_forcing_01dy_025deg"
OBS_TXT = "KISSPATH_OBS/BB/51080_bengbu.txt"

# The gauge this driver scores. case_id / scored_obs in __kdt__ are built from these.
GAUGE_CODE, GAUGE_NAME = os.path.basename(OBS_TXT)[:-len(".txt")].split("_", 1)  # "51080", "bengbu"
CASE_ID = f"SITE:{GAUGE_NAME}"

# Cached deterministic inputs: <workdir>/calib, set by main() from --workdir.
CACHE = FORCING = OBS = None
# Read-only source after the workdir cache: cached Bengbu 1979-1990 inputs.
KI_CACHE = os.path.join(KI, "calib")

CAL_WIN = ("1981-01-01", "1985-12-31")
VAL_WIN = ("1986-01-01", "1990-12-31")

sys.path.insert(0, KI)
sys.path.insert(0, KTC)
from ki_tools_common.metrics import all_metrics  # noqa: E402


def _die(msg):
    print(f"calib_run FAILED: {msg}", file=sys.stderr, flush=True)
    sys.exit(1)


def require_external(path):
    """Reject a resolved write destination inside the read-only KI."""
    resolved = os.path.realpath(path)
    if os.path.commonpath([resolved, os.path.realpath(KI)]) == os.path.realpath(KI):
        raise ValueError(f"write destination is inside KI: {path}")
    return resolved


def read_theta():
    """Read the CURRENT candidate theta the kit handed over in $KDT_CALIB_PARAMS."""
    pf = os.environ.get("KDT_CALIB_PARAMS")
    if not pf:
        _die("KDT_CALIB_PARAMS is not set; the calibration kit hands each candidate there")
    try:
        d = json.load(open(pf))
        return [float(d["x1"]), float(d["x2"]), float(d["x3"]), float(d["x4"])]
    except Exception as e:
        _die(f"cannot read theta from {pf}: {e}")


def check_inputs(forcing, obs):
    """Return None if the forcing/obs pair is usable for THIS case, else the reason.
    Usable = forcing is daily with no gaps from exactly START_Y-01-01 (the validated
    spin-up start) to at least END_Y-12-31; obs has the SAME date column row by row
    (score() pairs them by row); and both scoring windows have >= 30 finite obs."""
    try:
        fc = pd.read_csv(forcing, comment="#")
        ob = pd.read_csv(obs)
        fd = pd.to_datetime(fc["date"])
        od = pd.to_datetime(ob["date"])
        q = pd.to_numeric(ob["Q_mm_d"], errors="coerce")
    except Exception as e:
        return f"unreadable ({type(e).__name__}: {e})"
    if len(fd) == 0:
        return "forcing is empty"
    want_lo, want_hi = pd.Timestamp(f"{START_Y}-01-01"), pd.Timestamp(f"{END_Y}-12-31")
    if fd.iloc[0] != want_lo or fd.iloc[-1] < want_hi:
        return (f"forcing covers {fd.iloc[0].date()}..{fd.iloc[-1].date()}, "
                f"needs {want_lo.date()}..{want_hi.date()} (spin-up + calibration + holdout)")
    if len(fd) > 1 and not (fd.diff().dropna() == pd.Timedelta(days=1)).all():
        return "forcing dates are not one row per day without gaps"
    if len(od) != len(fd) or not (od.values == fd.values).all():
        return "obs dates do not match forcing dates row by row"
    for lo, hi in (CAL_WIN, VAL_WIN):
        n = int(((od >= lo) & (od <= hi) & np.isfinite(q)).sum())
        if n < 30:
            return f"only {n} finite obs in {lo}..{hi}"
    return None


def _copy_in(src, dst):
    """Copy src -> dst (dst is under --workdir). Temp + rename, so a crash never
    leaves a half file. copyfile, not copy2: no mode bits from a read-only KI."""
    tmp = f"{dst}.tmp.{os.getpid()}"
    require_external(tmp)
    require_external(dst)
    shutil.copyfile(src, tmp)
    os.replace(tmp, dst)


def ensure_inputs():
    """Guarantee the cached CMFD/Oudin forcing + Bengbu obs exist under <workdir>/calib
    and cover the run window. These are theta-independent and set up ONCE per workdir
    (not in the optimization loop). Order: workdir cache, KI calib/ (read only),
    rebuild from the original Bengbu sources. Every source is date-checked; none passing -> fail."""
    os.makedirs(CACHE, exist_ok=True)
    rejected = []
    if os.path.exists(FORCING) and os.path.exists(OBS):
        why = check_inputs(FORCING, OBS)
        if why is None:
            return
        rejected.append(f"workdir cache {CACHE}: {why}")
        print(f"calib_run: replacing bad workdir cache ({why})", file=sys.stderr, flush=True)
    for label, d in (("KI calib", KI_CACHE),):
        src_f, src_o = os.path.join(d, "forcing.csv"), os.path.join(d, "obs_q.csv")
        if not (os.path.exists(src_f) and os.path.exists(src_o)):
            rejected.append(f"{label} {d}: forcing.csv/obs_q.csv missing")
            continue
        why = check_inputs(src_f, src_o)
        if why is not None:
            rejected.append(f"{label} {d}: {why}")
            continue
        _copy_in(src_f, FORCING)
        _copy_in(src_o, OBS)
        return
    try:
        _rebuild_inputs()
    except Exception as e:
        rejected.append(f"rebuild from CMFD {CMFD_DIR}: {type(e).__name__}: {e}")
    else:
        why = (check_inputs(FORCING, OBS) if os.path.exists(FORCING) and os.path.exists(OBS)
               else "rebuild wrote no forcing/obs")
        if why is None:
            return
        rejected.append(f"rebuild from CMFD {CMFD_DIR}: {why}")
    _die("no forcing/obs source covers the run window: " + " | ".join(rejected))


def _rebuild_inputs():
    """Self-contained rebuild of forcing+obs via the KI tools (slow: load_forcing
    over CMFD). Only hit when no cached copy exists anywhere."""
    from ki_tools_common.load_forcing import load_daily_forcing
    cmfd_csv = os.path.join(CACHE, "cmfd_daily.csv")
    if not os.path.exists(cmfd_csv):
        lats, lons = [32.0, 33.0, 34.0], [114.5, 116.0, 117.5]
        Ps, Ts, ref = [], [], None
        for la in lats:
            for lo in lons:
                d = load_daily_forcing("cmfd", la, lo, START_Y, END_Y,
                                       forcing_dir=CMFD_DIR)
                idx = pd.to_datetime(d["dates"])
                Ps.append(pd.Series(np.asarray(d["precip_mm"], float), index=idx))
                Ts.append(pd.Series(np.asarray(d["temp_mean_c"], float), index=idx))
                ref = idx
        P = pd.concat(Ps, axis=1).mean(axis=1)
        T = pd.concat(Ts, axis=1).mean(axis=1)
        pd.DataFrame({"date": P.index.strftime("%Y-%m-%d"),
                      "precip_mm_d": P.values, "temp_c": T.values}).to_csv(cmfd_csv, index=False)
    cf = os.path.join(KI, "tools", "convert_forcing.py")
    subprocess.run([sys.executable, "-B", cf, "--format", "csv", "--input", cmfd_csv,
                    "--p-col", "precip_mm_d", "--t-col", "temp_c", "--date-col", "date",
                    "--pet-method", "oudin", "--lat", str(CENTROID_LAT),
                    "--output", FORCING], check=True, cwd=CACHE)
    fc = pd.read_csv(FORCING, comment="#")
    fc["date"] = pd.to_datetime(fc["date"])
    raw = pd.read_csv(OBS_TXT, sep="\t", encoding="latin-1")
    raw["date"] = pd.to_datetime(raw["dates"], format="%Y-%m-%d", errors="coerce")
    raw["Q"] = pd.to_numeric(raw["Q"], errors="coerce")
    raw.loc[raw["Q"] < 0, "Q"] = np.nan
    raw["Q_mm_d"] = raw["Q"] * 86400.0 / (AREA_KM2 * 1e6) * 1000.0
    aligned = raw.set_index("date")["Q_mm_d"].reindex(fc["date"]).values
    pd.DataFrame({"date": fc["date"].dt.strftime("%Y-%m-%d"),
                  "Q_mm_d": aligned}).to_csv(OBS, index=False)


def run_model(theta, workdir):
    """One forward run of m_07 with theta over the cached forcing. Returns the
    simulated Q_mm_d array, or dies (no metrics -> +inf) on failure."""
    run_dir = os.path.join(workdir, "calib_run_scratch")
    os.makedirs(run_dir, exist_ok=True)
    ts_csv = os.path.join(run_dir, "marrmot_timeseries.csv")
    run_json = os.path.join(run_dir, "run.json")
    for p in (ts_csv, run_json):                  # never read a stale run
        try:
            os.unlink(p)
        except OSError:
            pass
    cmd = [sys.executable, "-B", os.path.join(KI, "tools", "run_marrmot.py"),
           "--forcing", FORCING, "--model", MODEL,
           "--theta", json.dumps(theta),
           "--marrmot-path", MARRMOT_SRC,
           "--output", run_json, "--timeout", "240"]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=run_dir)
    if r.returncode != 0 or not os.path.exists(ts_csv):
        _die(f"run_marrmot failed (rc={r.returncode}): {r.stderr[-500:]}")
    ts = pd.read_csv(ts_csv)
    if "Q_mm_d" not in ts.columns or len(ts) == 0:
        _die("run_marrmot produced no Q_mm_d timeseries")
    return ts["Q_mm_d"].values


def score(sim, workdir):
    fc = pd.read_csv(FORCING, comment="#")
    dates = pd.to_datetime(fc["date"]).values
    obs = pd.read_csv(OBS)["Q_mm_d"].values
    n = min(len(sim), len(obs), len(dates))
    sim, obs, dates = np.asarray(sim[:n], float), np.asarray(obs[:n], float), dates[:n]

    split = os.environ.get("KDT_CALIB_SPLIT", "calibration").strip().lower()
    lo, hi = VAL_WIN if split == "holdout" else CAL_WIN
    win = (dates >= np.datetime64(lo)) & (dates <= np.datetime64(hi))
    msk = win & np.isfinite(sim) & np.isfinite(obs)
    if int(msk.sum()) < 30:
        _die(f"too few finite points in split '{split}' ({int(msk.sum())})")

    m = all_metrics(obs[msk], sim[msk])
    def g(k):
        v = m.get(k)
        return round(float(v), 6) if v is not None and np.isfinite(v) else None
    return {
        "nse": g("NSE"), "kge": g("KGE"), "pbias": g("PBIAS"), "r": g("r"),
        "rmse": g("RMSE"),
        "split": split,
        "period": f"{lo}..{hi}",
        "n": int(msk.sum()),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", required=True)    # runner.py always passes {workdir}
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    args.workdir = require_external(args.workdir)
    args.out = require_external(args.out)
    require_external(args.out + ".tmp")
    # Check existing nested symlinks before creating or writing any runtime file.
    for relative in ("calib", "calib/forcing.csv", "calib/obs_q.csv", "calib/cmfd_daily.csv",
                     "calib_run_scratch", "calib_run_scratch/marrmot_timeseries.csv",
                     "calib_run_scratch/run.json", "calib_run_scratch/normcdf.m"):
        require_external(os.path.join(args.workdir, relative))
    global CACHE, FORCING, OBS
    CACHE = os.path.join(os.path.abspath(args.workdir), "calib")
    FORCING = os.path.join(CACHE, "forcing.csv")
    OBS = os.path.join(CACHE, "obs_q.csv")

    theta = read_theta()
    # feasibility mirror of the contract's ranges (cheap reject, no run)
    lo = [1.0, -20.0, 1.0, 0.5]
    hi = [2000.0, 20.0, 300.0, 15.0]
    for i, (t, a, b) in enumerate(zip(theta, lo, hi)):
        if not (a <= t <= b):
            _die(f"theta[{i}]={t} outside parRange [{a},{b}]")

    ensure_inputs()
    sim = run_model(theta, args.workdir)
    metrics = score(sim, args.workdir)
    # Runner-mode proof the kit checks: echo every parameter it handed over, and
    # name the gauge this eval scored (checked when a case is pinned).
    metrics["__kdt__"] = {
        "applied_params": dict(zip(("x1", "x2", "x3", "x4"), theta)),
        "case_id": CASE_ID,
        "scored_obs": f"{GAUGE_CODE} {GAUGE_NAME} Q (m3/s -> mm/d over {AREA_KM2:g} km2) "
                      f":: {OBS_TXT}",
    }

    # Write only on full success (atomic-ish): temp then rename.
    tmp = args.out + ".tmp"
    with open(tmp, "w") as f:
        json.dump(metrics, f, indent=2)
    os.replace(tmp, args.out)
    print(json.dumps(metrics), flush=True)


if __name__ == "__main__":
    main()
