#!/usr/bin/env python3
"""
Stage 7: score a SWAP point simulation against a point observation series.

Simulated evapotranspiration follows the dag definition
    evapotranspiration = transpiration + soil evaporation + interception
so the scored series is

    ET [mm/d] = (Tact + Eact + Interc) * 10.0        (.inc is cm/d)

Dropping `Interc` — as an earlier run-local score_et.py did — removes
30-57 mm/yr at a maize site and biases every metric.

Annual irrigation totals are reported alongside the metrics: a SWAP run left
to schedule its own irrigation (SCHEDULE=1 / TCS=1 in the .crp) holds Tact
near Tpot by construction, and scoring actual ET under that closure is
near-circular (dt_023). The totals make the closure visible in the result.

Usage:
    python score_swap_point_obs.py \\
        --sim  work/mycase/parsed/daily_increments.csv \\
        --obs  data/obs/fluxnet/sites/US-Ne1/FULLSET_DD.csv \\
        --obs-var LE_CORR --obs-qc LE_F_MDS_QC \\
        --spinup-end 2001-12-31 \\
        --cal 2002-01-01:2007-12-31 --val 2008-01-01:2013-12-31 \\
        --water-balance work/mycase/parsed/water_balance.csv \\
        --output work/mycase/et_metrics.json
"""

import argparse
import csv
import json
import os
import sys
from datetime import datetime

import numpy as np

from ki_tools_common.metrics import all_metrics

# FLUXNET latent heat flux (W/m2) -> evapotranspiration (mm/d):
#   86400 s/d / 2.45e6 J/kg / 1000 kg/m3 * 1000 mm/m
LE_WM2_TO_MM_D = 86400.0 / 2.45e6
FLUXNET_MISSING = -9999.0


def _parse_date(text):
    """Accept YYYY-MM-DD, YYYYMMDD or a trailing-space SWAP date."""
    s = str(text).strip().strip("'\"")
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Unrecognised date: '{text}'")


def _parse_window(spec):
    """Parse a `START:END` window into a (date, date) pair."""
    if not spec:
        return None
    if ":" not in spec:
        raise ValueError(f"Window must be START:END, got '{spec}'")
    a, b = spec.split(":", 1)
    return _parse_date(a), _parse_date(b)


def _float(text):
    try:
        return float(str(text).strip())
    except (TypeError, ValueError):
        return np.nan


def load_sim_et(sim_path):
    """
    Read parsed daily_increments.csv and build the dag's ET series.

    Returns (dates, et_mm, irrigation_mm) as parallel lists/arrays.
    """
    if not os.path.isfile(sim_path):
        print(f"ERROR: simulated series not found: {sim_path}", file=sys.stderr)
        sys.exit(1)

    dates, et, irrig = [], [], []
    missing_interc = 0

    with open(sim_path, "r", newline="") as f:
        reader = csv.DictReader(f)
        cols = {c.strip().lower(): c for c in (reader.fieldnames or [])}
        for want in ("date", "tact", "eact"):
            if want not in cols:
                print(f"ERROR: {sim_path} has no '{want}' column "
                      f"(found: {reader.fieldnames})", file=sys.stderr)
                sys.exit(1)
        if "interc" not in cols:
            print("ERROR: no 'Interc' column — the dag defines ET as "
                  "transpiration + soil evaporation + interception, so this "
                  "series cannot be scored", file=sys.stderr)
            sys.exit(1)

        for row in reader:
            try:
                d = _parse_date(row[cols["date"]])
            except ValueError:
                continue
            tact = _float(row[cols["tact"]])
            eact = _float(row[cols["eact"]])
            inter = _float(row[cols["interc"]])
            if np.isnan(inter):
                missing_interc += 1
                inter = 0.0
            dates.append(d)
            et.append((tact + eact + inter) * 10.0)   # cm/d -> mm/d
            irrig.append(_float(row[cols["irrig"]]) * 10.0
                         if "irrig" in cols else np.nan)

    if not dates:
        print(f"ERROR: no usable rows in {sim_path}", file=sys.stderr)
        sys.exit(1)
    if missing_interc:
        print(f"WARNING: {missing_interc} rows had a blank Interc — treated as 0")

    print(f"[OK] Simulated ET: {len(dates)} days, "
          f"{dates[0]} to {dates[-1]}, mean {np.nanmean(et):.2f} mm/d")
    return dates, np.asarray(et, dtype=float), np.asarray(irrig, dtype=float)


def load_obs_le(obs_path, obs_var, obs_qc=None, qc_min=None):
    """
    Read a FLUXNET daily FULLSET file and convert a latent-heat column to
    ET in mm/d. -9999 is the missing sentinel.
    """
    if not os.path.isfile(obs_path):
        print(f"ERROR: observation file not found: {obs_path}", file=sys.stderr)
        sys.exit(1)

    obs = {}
    n_missing = 0
    n_qc_dropped = 0

    with open(obs_path, "r", newline="") as f:
        reader = csv.DictReader(f)
        if obs_var not in (reader.fieldnames or []):
            print(f"ERROR: '{obs_var}' not in {obs_path}", file=sys.stderr)
            sys.exit(1)
        if obs_qc and obs_qc not in reader.fieldnames:
            print(f"WARNING: QC column '{obs_qc}' absent — no QC filtering")
            obs_qc = None

        for row in reader:
            try:
                d = _parse_date(row["TIMESTAMP"])
            except (KeyError, ValueError):
                continue
            v = _float(row[obs_var])
            if np.isnan(v) or v <= FLUXNET_MISSING + 1.0:
                n_missing += 1
                continue
            if obs_qc is not None and qc_min is not None:
                q = _float(row[obs_qc])
                if np.isnan(q) or q <= FLUXNET_MISSING + 1.0 or q < qc_min:
                    n_qc_dropped += 1
                    continue
            obs[d] = v * LE_WM2_TO_MM_D

    if not obs:
        print(f"ERROR: no valid {obs_var} values in {obs_path}", file=sys.stderr)
        sys.exit(1)

    print(f"[OK] Observed ET from {obs_var}: {len(obs)} days "
          f"({n_missing} missing, {n_qc_dropped} QC-dropped), "
          f"mean {np.mean(list(obs.values())):.2f} mm/d")
    return obs


def annual_irrigation(dates, irrig_mm, wb_path=None):
    """
    Annual irrigation totals (mm/yr) from the daily series, cross-checked
    against the .blc-derived water_balance.csv when available.
    """
    totals = {}
    if irrig_mm is not None and not np.all(np.isnan(irrig_mm)):
        for d, v in zip(dates, irrig_mm):
            if not np.isnan(v):
                totals.setdefault(d.year, 0.0)
                totals[d.year] += v

    wb_totals = {}
    if wb_path and os.path.isfile(wb_path):
        with open(wb_path, "r", newline="") as f:
            for row in csv.DictReader(f):
                year = row.get("year")
                gi = row.get("gross_irrigation_cm")
                if year and gi not in (None, ""):
                    try:
                        wb_totals[int(year)] = float(gi) * 10.0
                    except ValueError:
                        continue

    return {"from_daily_inc_mm": {str(k): round(v, 1)
                                  for k, v in sorted(totals.items())},
            "from_water_balance_mm": {str(k): round(v, 1)
                                      for k, v in sorted(wb_totals.items())}}


def score_window(dates, sim, obs, window, label):
    """Pair sim and obs on shared dates inside `window` and score."""
    pairs = []
    for d, s in zip(dates, sim):
        if window and not (window[0] <= d <= window[1]):
            continue
        o = obs.get(d)
        if o is None or np.isnan(s):
            continue
        pairs.append((d, o, s))

    if len(pairs) < 30:
        print(f"WARNING: {label}: only {len(pairs)} paired days — not scored")
        return {"label": label, "n": len(pairs), "error": "insufficient overlap"}

    d_arr = [p[0] for p in pairs]
    o_arr = np.array([p[1] for p in pairs])
    s_arr = np.array([p[2] for p in pairs])

    m = all_metrics(o_arr, s_arr, dates=d_arr, label=label)
    m["n"] = len(pairs)
    m["period"] = (f"{window[0]}:{window[1]}" if window
                   else f"{d_arr[0]}:{d_arr[-1]}")
    m["obs_mean_mm_d"] = round(float(o_arr.mean()), 3)
    m["sim_mean_mm_d"] = round(float(s_arr.mean()), 3)
    print(f"[OK] {label}: n={len(pairs)}  "
          f"obs={o_arr.mean():.2f}  sim={s_arr.mean():.2f} mm/d")
    return m


def main():
    p = argparse.ArgumentParser(
        description="Score SWAP ET against a point observation series"
    )
    p.add_argument("--sim", required=True,
                   help="parsed/daily_increments.csv from parse_swap_output.py")
    p.add_argument("--obs", required=True, help="FLUXNET daily FULLSET CSV")
    p.add_argument("--obs-var", default="LE_CORR",
                   help="Latent heat column to score (W/m2)")
    p.add_argument("--obs-qc", default=None, help="QC column name")
    p.add_argument("--qc-min", type=float, default=None,
                   help="Minimum QC value to keep (omit for no filtering)")
    p.add_argument("--spinup-end", default=None,
                   help="Drop simulated days up to and including this date")
    p.add_argument("--cal", default=None, metavar="START:END")
    p.add_argument("--val", default=None, metavar="START:END")
    p.add_argument("--water-balance", default=None,
                   help="parsed/water_balance.csv for irrigation cross-check")
    p.add_argument("--output", required=True, help="Metrics JSON to write")
    args = p.parse_args()

    dates, sim_et, sim_irr = load_sim_et(args.sim)
    obs = load_obs_le(args.obs, args.obs_var, args.obs_qc, args.qc_min)

    if args.spinup_end:
        cutoff = _parse_date(args.spinup_end)
        keep = [i for i, d in enumerate(dates) if d > cutoff]
        n_dropped = len(dates) - len(keep)
        dates = [dates[i] for i in keep]
        sim_et = sim_et[keep]
        sim_irr = sim_irr[keep]
        print(f"[OK] Dropped {n_dropped} spin-up days (<= {cutoff})")

    result = {
        "model": "SWAP v4.2.0",
        "sim_file": os.path.abspath(args.sim),
        "obs_file": os.path.abspath(args.obs),
        "obs_variable": args.obs_var,
        "sim_definition": "ET = (Tact + Eact + Interc) * 10  [mm/d]",
        "metrics": {},
        "annual_irrigation": annual_irrigation(dates, sim_irr,
                                               args.water_balance),
    }

    result["metrics"]["headline"] = score_window(dates, sim_et, obs, None,
                                                 "headline")
    for name, spec in (("calibration", args.cal), ("validation", args.val)):
        if spec:
            result["metrics"][name] = score_window(
                dates, sim_et, obs, _parse_window(spec), name
            )

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(result, f, indent=2, default=str)
    print(f"[OK] Wrote metrics to {args.output}")


if __name__ == "__main__":
    main()
