#!/usr/bin/env python3
"""calibrate_kineros2_multipliers.py -- calibrate KINEROS2 run-time multipliers against an observed
event hydrograph, running the REAL engine for every trial.

KINEROS2's own calibration handle is the multiplier file (Input.pdf 'Run-Time Input'): one factor
each for Ks, Manning n, CV of Ks, G, interception, cohesion, splash (+ optional channel Ks, channel
G, channel n, Woolhiser coefficient, channel length, initial saturation) applied to EVERY element.
Goodrich et al. (2012, K2/AGWA) calibrate exactly these, Ks and n first.

  --params ks:0.1:3,manning:0.5:2      name:low:high (multiplier bounds; names = multiplier keys)
  --fixed  g=1.5                       multipliers held constant
  --objective nse | kge | peak_volume  (peak_volume minimises |peak error| + |volume error|)
  --method grid [--n-grid 5] | nelder-mead [--max-evals 60] (starts from the best grid point)

Every trial: run_kineros2_engine.run_case -> score_kineros2_event.score (obs interpolated onto the
sim times, absolute units).  A failed run scores -inf and is logged, never skipped silently.
Output: trials.csv, best.json, best/ (the best run's files).  The result is IN-SAMPLE for the
event(s) used -- report it as calibration skill, never as validation.

Exit codes: 0 done | 2 bad input | 3 every trial failed
"""
from __future__ import annotations

import argparse
import csv
import itertools
import json
import math
import shutil
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _k2lib as k2  # noqa: E402
from run_kineros2_engine import run_case  # noqa: E402
from score_kineros2_event import read_obs, read_sim, score  # noqa: E402


def _objective(sc: dict, kind: str) -> float:
    if kind == "nse":
        return sc["nse"]
    if kind == "kge":
        return sc["kge"]
    return -(abs(sc["peak_error_pct"]) + abs(sc["volume_error_pct"])) / 100.0


def _repoint_result(result_file: Path, old_dir: Path, new_dir: Path) -> None:
    """Rewrite every path in a copied run_result.json from old_dir (_trial/, which the next trial
    overwrites and the end of calibration deletes) to new_dir (best/), so best/ stays usable."""
    old_s, new_s = str(old_dir), str(new_dir)

    def fix(v):
        if isinstance(v, str) and (v == old_s or v.startswith(old_s + "/")):
            return new_s + v[len(old_s):]
        if isinstance(v, dict):
            return {k: fix(x) for k, x in v.items()}
        if isinstance(v, list):
            return [fix(x) for x in v]
        return v

    res = fix(json.loads(result_file.read_text()))
    k2.write_json(result_file, res)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--par", required=True); ap.add_argument("--rain", required=True)
    ap.add_argument("--tfin", type=float, required=True); ap.add_argument("--dt", type=float, required=True)
    ap.add_argument("--courant", action="store_true")
    ap.add_argument("--obs", required=True); ap.add_argument("--obs-offset-min", type=float, required=True)
    ap.add_argument("--params", required=True); ap.add_argument("--fixed", default="")
    ap.add_argument("--objective", choices=["nse", "kge", "peak_volume"], default="nse")
    ap.add_argument("--method", choices=["grid", "nelder-mead"], default="grid")
    ap.add_argument("--n-grid", type=int, default=5); ap.add_argument("--max-evals", type=int, default=60)
    ap.add_argument("--outlet-id", type=int)
    ap.add_argument("--out-dir", required=True)
    a = ap.parse_args(argv)
    out = Path(a.out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    try:
        space = []
        for item in a.params.split(","):
            n, lo, hi = item.split(":")
            if n not in k2.MULT_KEYS + k2.CHANNEL_MULT_KEYS:
                raise ValueError(f"unknown multiplier {n!r}")
            lo, hi = float(lo), float(hi)
            if not 0 < lo < hi:
                raise ValueError(f"{n}: need 0 < low < high")
            space.append((n, lo, hi))
        fixed = {k: float(v) for k, v in (p.split("=") for p in a.fixed.split(",") if p)}
        to, qo, ometa = read_obs(Path(a.obs))
        to = to + a.obs_offset_min
    except (ValueError, KeyError, FileNotFoundError) as e:
        print(f"INPUT ERROR: {e}", file=sys.stderr)
        return 2

    trials, best = [], {"obj": -math.inf}
    names = [s[0] for s in space]

    def evaluate(vals):
        i = len(trials)
        mult = dict(fixed); mult.update(dict(zip(names, (float(v) for v in vals))))
        d = out / "_trial"
        shutil.rmtree(d, ignore_errors=True)
        row = {"trial": i, **{n: mult[n] for n in names}}
        try:
            res = run_case(a.par, a.rain, d, a.tfin, a.dt, courant=a.courant, mult=mult,
                           title=f"calibration trial {i}", outlet_id=a.outlet_id)
            if res["status"] != "success":
                raise RuntimeError("; ".join(res["failures"])[:200])
            ts, qs, _ = read_sim(d / "run_result.json", None)
            sc = score(ts, qs, to, qo)
            obj = _objective(sc, a.objective)
            row.update(objective=obj, nse=sc["nse"], kge=sc["kge"], peak_error_pct=sc["peak_error_pct"],
                       volume_error_pct=sc["volume_error_pct"], peak_timing_error_min=sc["peak_timing_error_min"],
                       status="ok")
            if obj > best["obj"]:
                best.update(obj=obj, mult=mult, score=sc, trial=i)
                shutil.rmtree(out / "best", ignore_errors=True)
                shutil.copytree(d, out / "best")
                _repoint_result(out / "best" / "run_result.json", d, out / "best")
        except Exception as e:      # a failed trial is recorded as -inf, never dropped
            obj = -math.inf
            row.update(objective=obj, status=f"failed: {str(e)[:150]}")
        trials.append(row)
        print(f"  trial {i:3d} " + " ".join(f"{n}={row[n]:.3f}" for n in names) + f"  obj={obj:.4f}")
        return obj

    try:
        grids = [np.geomspace(lo, hi, a.n_grid) for _, lo, hi in space]
        for combo in itertools.product(*grids):
            if len(trials) >= a.max_evals:
                break
            evaluate(combo)
        if a.method == "nelder-mead" and len(trials) < a.max_evals and best.get("mult"):
            from scipy.optimize import minimize
            lo = np.log([s[1] for s in space]); hi = np.log([s[2] for s in space])
            x0 = np.log([best["mult"][n] for n in names])
            minimize(lambda x: -evaluate(np.exp(np.clip(x, lo, hi))), x0, method="Nelder-Mead",
                     options={"maxfev": a.max_evals - len(trials), "xatol": 0.01, "fatol": 1e-4})
    finally:
        shutil.rmtree(out / "_trial", ignore_errors=True)
        if trials:
            keys = list(dict.fromkeys(k for r in trials for k in r))
            with open(out / "trials.csv", "w", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=keys); w.writeheader(); w.writerows(trials)
    if not best.get("mult"):
        print("every trial failed -- see trials.csv", file=sys.stderr)
        return 3
    summary = {"tool": "calibrate_kineros2_multipliers.py", "objective": a.objective, "method": a.method,
               "n_trials": len(trials), "best_trial": best["trial"], "best_multipliers": best["mult"],
               "best_score": best["score"], "obs": ometa, "obs_offset_min": a.obs_offset_min,
               "caveat": "IN-SAMPLE calibration on the observed event(s) given; not a validation result",
               "best_run_dir": str(out / "best")}
    k2.write_json(out / "best.json", summary)
    print(f"best trial {best['trial']}: {best['mult']}  {a.objective}={best['obj']:.4f}  "
          f"NSE={best['score']['nse']:.3f} peak {best['score']['peak_error_pct']:+.1f}% "
          f"volume {best['score']['volume_error_pct']:+.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
