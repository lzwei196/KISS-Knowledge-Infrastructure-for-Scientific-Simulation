#!/usr/bin/env python3
"""Programmatic run+score for MARRMoT calibration (NOT a claude agent).

Usage:  python calib_run.py --workdir <wd> --out <metrics.json>

Contract (calibration.yaml): the calibration kit has already written this
candidate's parameters into <KI>/calib/params.json (json_path addresses x1..x4).
This script:
  1. reads the CURRENT theta from that file (x1,x2,x3,x4 -> [x1,x2,x3,x4]);
  2. runs the model end-to-end via the KI's tools/run_marrmot.py (the SAME forward
     path the validated Bengbu 51080 real-case used), over the cached CMFD/Oudin
     forcing and the Bengbu obs (reused from the real-case run, or rebuilt once);
  3. scores simulated Q (mm/d) vs observed Q with ki_tools_common.metrics.all_metrics
     on the split selected by env KDT_CALIB_SPLIT ("calibration" | "holdout");
  4. writes a FLAT lowercase metrics dict {nse,kge,pbias,r,...} as JSON to --out.

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

import numpy as np
import pandas as pd

KI = "/mnt/disk1/Hydrocraft_server/models/MARRMoT/knowledge_infrastructure"
KTC = "/mnt/disk1/Hydrocraft_server/models/ki_tools_common"
MODEL = "m_07_gr4j_4p_2s"
MARRMOT_SRC = "/mnt/disk1/Hydrocraft_server/models/MARRMoT/source/repo/MARRMoT"
AREA_KM2 = 121330.0
CENTROID_LAT = 33.0
START_Y, END_Y = 1979, 1990
CMFD_DIR = "/media/server/hc_ssd/forcing/huai/Data_forcing_01dy_025deg"
OBS_TXT = "/mnt/disk1/Hydrocraft_server/data/obs/BB/51080_bengbu.txt"

PARAMS_JSON = os.path.join(KI, "calib", "params.json")
CACHE = os.path.join(KI, "calib")                 # cached deterministic inputs
FORCING = os.path.join(CACHE, "forcing.csv")
OBS = os.path.join(CACHE, "obs_q.csv")
# Fallback source: the validated real-case run already built these exact files.
REAL_CASE = "/mnt/disk1/Hydrocraft_server/models/MARRMoT/detached/real_case"

CAL_WIN = ("1981-01-01", "1985-12-31")
VAL_WIN = ("1986-01-01", "1990-12-31")

sys.path.insert(0, KI)
sys.path.insert(0, KTC)
from ki_tools_common.metrics import all_metrics  # noqa: E402


def _die(msg):
    print(f"calib_run FAILED: {msg}", file=sys.stderr, flush=True)
    sys.exit(1)


def read_theta():
    """Read the CURRENT candidate theta the kit wrote into calib/params.json."""
    try:
        d = json.load(open(PARAMS_JSON))
        return [float(d["x1"]), float(d["x2"]), float(d["x3"]), float(d["x4"])]
    except Exception as e:
        _die(f"cannot read theta from {PARAMS_JSON}: {e}")


def ensure_inputs():
    """Guarantee the cached CMFD/Oudin forcing + Bengbu obs exist. These are
    theta-independent and built ONCE (not in the optimization loop). Prefer the
    validated real-case artifacts; rebuild via the KI pipeline only if absent."""
    if os.path.exists(FORCING) and os.path.exists(OBS):
        return
    os.makedirs(CACHE, exist_ok=True)
    rc_f = os.path.join(REAL_CASE, "forcing.csv")
    rc_o = os.path.join(REAL_CASE, "obs_q.csv")
    if os.path.exists(rc_f) and os.path.exists(rc_o):
        shutil.copy2(rc_f, FORCING)
        shutil.copy2(rc_o, OBS)
        return
    _rebuild_inputs()
    if not (os.path.exists(FORCING) and os.path.exists(OBS)):
        _die("could not obtain forcing/obs (no cache, no real-case, rebuild failed)")


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
    subprocess.run([sys.executable, cf, "--format", "csv", "--input", cmfd_csv,
                    "--p-col", "precip_mm_d", "--t-col", "temp_c", "--date-col", "date",
                    "--pet-method", "oudin", "--lat", str(CENTROID_LAT),
                    "--output", FORCING], check=True)
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
    run_dir = os.path.join(workdir or CACHE, "calib_run_scratch")
    os.makedirs(run_dir, exist_ok=True)
    ts_csv = os.path.join(run_dir, "marrmot_timeseries.csv")
    run_json = os.path.join(run_dir, "run.json")
    for p in (ts_csv, run_json):                  # never read a stale run
        try:
            os.unlink(p)
        except OSError:
            pass
    cmd = [sys.executable, os.path.join(KI, "tools", "run_marrmot.py"),
           "--forcing", FORCING, "--model", MODEL,
           "--theta", json.dumps(theta),
           "--marrmot-path", MARRMOT_SRC,
           "--output", run_json, "--timeout", "240"]
    r = subprocess.run(cmd, capture_output=True, text=True)
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
    ap.add_argument("--workdir", default=CACHE)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

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

    # Write only on full success (atomic-ish): temp then rename.
    tmp = args.out + ".tmp"
    with open(tmp, "w") as f:
        json.dump(metrics, f, indent=2)
    os.replace(tmp, args.out)
    print(json.dumps(metrics), flush=True)


if __name__ == "__main__":
    main()
