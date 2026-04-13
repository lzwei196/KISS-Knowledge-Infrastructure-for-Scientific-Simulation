#!/usr/bin/env python3
"""
calibrate_glm.py — GLUE-style calibration for GLM lake model.

Samples key calibration parameters and evaluates against observed temperature.
Parameters (in priority order):
  1. Kw (light extinction) — controls thermocline depth
  2. coef_wind_stir — controls surface mixed layer depth
  3. wind_factor — scales wind speed
  4. coef_mix_hyp — controls deep mixing rate
  5. sw_factor — scales shortwave radiation

Uses RMSE of temperature at observed depths as the objective function.

Usage:
    python calibrate_glm.py \
        --run_dir /path/to/glm_sim \
        --observed_temp observed_temp.csv \
        --n_samples 100 \
        --output calibration_results.json
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime

import numpy as np
import pandas as pd


GLM_BINARY = "/mnt/disk1/Hydrocraft_server/model/glm/bin/glm"

# Parameter ranges
PARAM_RANGES = {
    'Kw': (0.1, 3.0),
    'coef_wind_stir': (0.1, 1.0),
    'wind_factor': (0.5, 2.0),
    'coef_mix_hyp': (0.1, 1.0),
    'sw_factor': (0.8, 1.2),
    'coef_mix_conv': (0.1, 0.5),
}


def validate_inputs(args):
    """Validate inputs."""
    errors = []
    if not os.path.isdir(args.run_dir):
        errors.append(f"Run directory not found: {args.run_dir}")
    nml = os.path.join(args.run_dir, 'glm3.nml')
    if not os.path.exists(nml):
        errors.append(f"glm3.nml not found in {args.run_dir}")
    if args.observed_temp and not os.path.exists(args.observed_temp):
        errors.append(f"Observed temperature file not found: {args.observed_temp}")
    if args.n_samples < 5:
        errors.append("--n_samples should be >= 5")
    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)


def modify_nml(nml_path, params):
    """Modify glm3.nml with new parameter values."""
    import re
    with open(nml_path) as f:
        content = f.read()

    for param, value in params.items():
        # Match patterns like: Kw = 0.5  or  wind_factor = 1.0
        pattern = rf'({param}\s*=\s*)([\d.eE+-]+)'
        replacement = rf'\g<1>{value}'
        content = re.sub(pattern, replacement, content)

    with open(nml_path, 'w') as f:
        f.write(content)


def run_single(run_dir, params, glm_binary, timeout=600):
    """Run GLM once with given parameters. Returns lake.csv path or None."""
    # Modify namelist
    nml_path = os.path.join(run_dir, 'glm3.nml')
    modify_nml(nml_path, params)

    # Clear old output
    out_dir = os.path.join(run_dir, 'output')
    for fname in ['output.nc', 'lake.csv', 'overflow.csv']:
        fpath = os.path.join(out_dir, fname)
        if os.path.exists(fpath):
            os.remove(fpath)

    try:
        result = subprocess.run(
            [glm_binary], cwd=run_dir,
            capture_output=True, text=True, timeout=timeout)
        if result.returncode == 0:
            lake_csv = os.path.join(out_dir, 'lake.csv')
            if os.path.exists(lake_csv):
                return lake_csv
    except subprocess.TimeoutExpired:
        pass
    except Exception:
        pass

    return None


def compute_rmse(simulated_csv, observed_csv, depth_col='depth', temp_col='temp'):
    """Compute RMSE between simulated and observed temperature."""
    sim = pd.read_csv(simulated_csv)
    obs = pd.read_csv(observed_csv)

    # Find time column in both
    sim_time = [c for c in sim.columns if 'time' in c.lower() or 'date' in c.lower()]
    obs_time = [c for c in obs.columns if 'time' in c.lower() or 'date' in c.lower()]

    if not sim_time or not obs_time:
        return float('inf')

    sim[sim_time[0]] = pd.to_datetime(sim[sim_time[0]])
    obs[obs_time[0]] = pd.to_datetime(obs[obs_time[0]])

    # For lake.csv, compare surface temperature
    sim_temp_cols = [c for c in sim.columns
                     if 'temp' in c.lower() and 'time' not in c.lower()
                     and 'date' not in c.lower()]
    obs_temp_cols = [c for c in obs.columns
                     if 'temp' in c.lower() and 'time' not in c.lower()
                     and 'date' not in c.lower()]

    if not sim_temp_cols or not obs_temp_cols:
        return float('inf')

    # Merge on date (daily)
    sim['date'] = sim[sim_time[0]].dt.date
    obs['date'] = obs[obs_time[0]].dt.date

    merged = sim[['date', sim_temp_cols[0]]].merge(
        obs[['date', obs_temp_cols[0]]], on='date', how='inner')

    if len(merged) < 10:
        return float('inf')

    diff = merged[sim_temp_cols[0]].values - merged[obs_temp_cols[0]].values
    rmse = np.sqrt(np.nanmean(diff ** 2))
    return float(rmse)


def process(args):
    """Run GLUE calibration."""
    print(f"Starting GLUE calibration with {args.n_samples} samples...",
          file=sys.stderr)

    # Create working copy of the simulation
    work_dir = os.path.join(args.run_dir, '_calibration_work')
    if os.path.exists(work_dir):
        shutil.rmtree(work_dir)
    shutil.copytree(args.run_dir, work_dir,
                    ignore=shutil.ignore_patterns('_calibration_*'))

    # Ensure output directory exists
    os.makedirs(os.path.join(work_dir, 'output'), exist_ok=True)

    # Read original namelist for backup
    nml_orig = os.path.join(args.run_dir, 'glm3.nml')
    with open(nml_orig) as f:
        nml_backup = f.read()

    # Sample parameters
    np.random.seed(args.seed)
    params_to_calibrate = args.params.split(',') if args.params else \
        ['Kw', 'coef_wind_stir', 'wind_factor', 'coef_mix_hyp']

    results = []
    best_rmse = float('inf')
    best_params = {}

    for i in range(args.n_samples):
        # Latin Hypercube-ish sampling
        params = {}
        for p in params_to_calibrate:
            lo, hi = PARAM_RANGES.get(p, (0.1, 1.0))
            params[p] = round(lo + (hi - lo) * np.random.random(), 4)

        # Run GLM
        t0 = time.time()
        lake_csv = run_single(work_dir, params, args.glm_binary,
                              timeout=args.timeout_per_run)
        elapsed = time.time() - t0

        if lake_csv:
            rmse = compute_rmse(lake_csv, args.observed_temp)
        else:
            rmse = float('inf')

        run_result = {
            "run": i + 1,
            "params": params,
            "rmse": round(rmse, 4) if rmse != float('inf') else None,
            "elapsed_s": round(elapsed, 1),
            "success": lake_csv is not None,
        }
        results.append(run_result)

        if rmse < best_rmse:
            best_rmse = rmse
            best_params = params.copy()

        if (i + 1) % 10 == 0 or i == 0:
            print(f"  Run {i+1}/{args.n_samples}: RMSE={rmse:.3f} "
                  f"(best={best_rmse:.3f})", file=sys.stderr)

    # Clean up work directory
    if os.path.exists(work_dir):
        shutil.rmtree(work_dir)

    # Restore original namelist
    with open(nml_orig, 'w') as f:
        f.write(nml_backup)

    # Sort by RMSE
    valid_results = [r for r in results if r['rmse'] is not None]
    valid_results.sort(key=lambda x: x['rmse'])

    return {
        "status": "success",
        "n_samples": args.n_samples,
        "n_successful": len(valid_results),
        "best_rmse": round(best_rmse, 4) if best_rmse != float('inf') else None,
        "best_params": best_params,
        "top_10": valid_results[:10],
        "params_calibrated": params_to_calibrate,
    }


def main():
    parser = argparse.ArgumentParser(
        description="GLUE-style GLM calibration")
    parser.add_argument("--run_dir", type=str, required=True,
                        help="GLM simulation directory")
    parser.add_argument("--observed_temp", type=str, required=True,
                        help="Observed temperature CSV (time, temp columns)")
    parser.add_argument("--n_samples", type=int, default=100,
                        help="Number of parameter samples (default: 100)")
    parser.add_argument("--params", type=str,
                        help="Comma-separated parameter names to calibrate")
    parser.add_argument("--seed", type=int, default=42,
                        help="Random seed (default: 42)")
    parser.add_argument("--glm_binary", type=str, default=GLM_BINARY,
                        help="GLM binary path")
    parser.add_argument("--timeout_per_run", type=int, default=300,
                        help="Timeout per GLM run in seconds (default: 300)")
    parser.add_argument("--output", type=str,
                        help="Output JSON results path")
    args = parser.parse_args()

    validate_inputs(args)
    result = process(args)

    output_json = json.dumps(result, indent=2)
    if args.output:
        os.makedirs(os.path.dirname(args.output) or '.', exist_ok=True)
        with open(args.output, 'w') as f:
            f.write(output_json)
        print(f"Results written to {args.output}", file=sys.stderr)
    else:
        print(output_json)


if __name__ == "__main__":
    main()
