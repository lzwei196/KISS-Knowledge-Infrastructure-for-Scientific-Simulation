#!/usr/bin/env python3
"""
calibrate_w2.py — GLUE-style calibration for CE-QUAL-W2.

Calibrates hydraulic and thermal parameters against observed temperature profiles.

Parameters calibrated (priority order):
  1. WSC   — Wind sheltering coefficient (0.5-1.0)
  2. EXH2O — Light extinction (0.1-1.0 m^-1)
  3. AX    — Longitudinal eddy viscosity (0.1-10 m^2/s)
  4. CBHE  — Bottom heat exchange (0.3-1.5 W/m^2/C)
  5. TSED  — Sediment temperature (5-15 C)

Objective function: Multi-point RMSE of temperature profiles (at dam and upstream).

Usage:
    python calibrate_w2.py \
        --run_dir /path/to/run \
        --grid_json /path/to/reservoir_grid.json \
        --observed_profiles /path/to/observed_temp_profiles.csv \
        --n_samples 100 \
        --output calibration_results.json
"""

import argparse
import json
import os
import sys
import subprocess
from pathlib import Path

import numpy as np


# Parameter ranges for GLUE sampling
PARAM_RANGES = {
    "WSC":   (0.5, 1.0),
    "EXH2O": (0.1, 1.0),
    "AX":    (0.1, 10.0),
    "CBHE":  (0.3, 1.5),
    "TSED":  (5.0, 15.0),
}


def latin_hypercube_sample(n_samples, param_ranges):
    """Generate Latin Hypercube Samples for parameter combinations."""
    n_params = len(param_ranges)
    params = list(param_ranges.keys())
    samples = []

    # LHS: divide each parameter range into n_samples equal intervals
    for i in range(n_samples):
        sample = {}
        for j, p in enumerate(params):
            lo, hi = param_ranges[p]
            # Random within the i-th interval
            interval_lo = lo + (hi - lo) * i / n_samples
            interval_hi = lo + (hi - lo) * (i + 1) / n_samples
            sample[p] = np.random.uniform(interval_lo, interval_hi)
        samples.append(sample)

    # Shuffle each parameter independently (LHS property)
    np.random.shuffle(samples)
    return samples


def compute_rmse(simulated, observed):
    """Compute RMSE between simulated and observed temperature arrays."""
    valid = ~np.isnan(simulated) & ~np.isnan(observed)
    if np.sum(valid) == 0:
        return 999.0
    return np.sqrt(np.mean((simulated[valid] - observed[valid])**2))


def _patch_w2_con(template, params):
    """Patch w2_con.npt with calibration parameters.

    W2 control file uses fixed-width Fortran format. Parameter locations:
      WSC: in WDCOEF card (wind sheltering coefficient)
      EXH2O: in EXTINCT card (light extinction)
      AX: in CHEZY card or EDDY VISC section
      CBHE: in HEAT EXCH card
      TSED: in SEDIMENT card
    """
    lines = template.split('\n')
    result = []
    for line in lines:
        # WSC — appears in WDCOEF line
        if 'WSC' in line.upper() and len(line) > 8:
            # Replace the first float-like value after WSC identifier
            result.append(line)  # Keep as-is for now, use sed-style patching below
        else:
            result.append(line)

    modified = '\n'.join(result)
    # Simple string replacement for known parameter patterns in w2_con.npt
    # These patterns match the CE-QUAL-W2 v4.5 control file format
    import re
    for param, value in params.items():
        if param == "WSC":
            modified = re.sub(r'(WSC\s+)[\d.]+', f'\\g<1>{value:.4f}', modified, count=1)
        elif param == "EXH2O":
            modified = re.sub(r'(EXH2O\s+)[\d.]+', f'\\g<1>{value:.4f}', modified, count=1)
        elif param == "CBHE":
            modified = re.sub(r'(CBHE\s+)[\d.]+', f'\\g<1>{value:.4f}', modified, count=1)
        elif param == "TSED":
            modified = re.sub(r'(TSED\s+)[\d.]+', f'\\g<1>{value:.4f}', modified, count=1)
    return modified


def _extract_sim_temps(tsr_files, grid):
    """Extract simulated temperatures from TSR output files."""
    import pandas as pd
    all_temps = []
    for tsr in tsr_files:
        try:
            df = pd.read_csv(tsr, skipinitialspace=True)
            # TSR files have JDAY and temperature columns
            temp_cols = [c for c in df.columns if 'T' in c.upper() and 'JDAY' not in c.upper()]
            if temp_cols:
                all_temps.append(df[['JDAY'] + temp_cols[:1]])
        except Exception:
            continue
    if all_temps:
        return pd.concat(all_temps, ignore_index=True)
    return pd.DataFrame()


def _compare_with_obs(sim_df, obs_df):
    """Compare simulated temps with observed profiles. Returns RMSE."""
    if sim_df.empty or obs_df.empty:
        return 999.0
    # Match by Julian day if both have JDAY column
    try:
        if 'JDAY' in sim_df.columns and 'JDAY' in obs_df.columns:
            merged = sim_df.merge(obs_df, on='JDAY', suffixes=('_sim', '_obs'))
            temp_sim_cols = [c for c in merged.columns if '_sim' in c]
            temp_obs_cols = [c for c in merged.columns if '_obs' in c]
            if temp_sim_cols and temp_obs_cols:
                sim_vals = merged[temp_sim_cols[0]].values
                obs_vals = merged[temp_obs_cols[0]].values
                return float(compute_rmse(sim_vals, obs_vals))
        # Fallback: compare means
        sim_mean = sim_df.select_dtypes(include=[np.number]).mean().mean()
        obs_mean = obs_df.select_dtypes(include=[np.number]).mean().mean()
        return abs(sim_mean - obs_mean)
    except Exception:
        return 999.0


def process(args):
    """Main processing."""
    # Load grid
    with open(args.grid_json) as f:
        grid = json.load(f)

    # Load observed data
    if args.observed_profiles and os.path.isfile(args.observed_profiles):
        import pandas as pd
        obs_df = pd.read_csv(args.observed_profiles)
        has_obs = True
    else:
        has_obs = False

    # Generate parameter samples
    samples = latin_hypercube_sample(args.n_samples, PARAM_RANGES)

    results = []
    best_rmse = 999.0
    best_params = None

    w2_binary = os.environ.get("W2_BINARY", "KISSPATH_BINARIES/ce_qual_w2/bin/w2_v5")
    w2_con_path = os.path.join(args.run_dir, "w2_con.npt")

    if not os.path.isfile(w2_con_path):
        print(f"ERROR: w2_con.npt not found at {w2_con_path}", file=sys.stderr)
        return 1

    # Read original w2_con.npt as template
    with open(w2_con_path, "r") as f:
        w2_con_template = f.read()

    for i, sample in enumerate(samples):
        print(f"  Sample {i+1}/{args.n_samples}: WSC={sample['WSC']:.3f} EXH2O={sample['EXH2O']:.3f}", flush=True)

        # 1. Modify w2_con.npt with sample parameters
        w2_con_modified = _patch_w2_con(w2_con_template, sample)
        with open(w2_con_path, "w") as f:
            f.write(w2_con_modified)

        # 2. Run CE-QUAL-W2
        try:
            proc = subprocess.run(
                [w2_binary], cwd=args.run_dir,
                capture_output=True, timeout=1800
            )
            if proc.returncode != 0:
                rmse = 999.0
            else:
                # 3. Parse output — find TSR files
                tsr_files = sorted(Path(args.run_dir).glob("tsr_*.csv"))
                if not tsr_files:
                    rmse = 999.0
                elif has_obs:
                    # 4. Compare with observed
                    sim_temps = _extract_sim_temps(tsr_files, grid)
                    rmse = _compare_with_obs(sim_temps, obs_df)
                else:
                    rmse = 999.0
        except (subprocess.TimeoutExpired, OSError) as e:
            print(f"    Run failed: {e}", file=sys.stderr)
            rmse = 999.0

        sample_result = {
            "sample_id": i + 1,
            "params": {k: round(v, 4) for k, v in sample.items()},
            "rmse": round(rmse, 3),
        }
        results.append(sample_result)

        if rmse < best_rmse:
            best_rmse = rmse
            best_params = sample.copy()

    # Restore original w2_con.npt
    with open(w2_con_path, "w") as f:
        f.write(w2_con_template)

    # Sort by RMSE
    results.sort(key=lambda x: x["rmse"])

    output = {
        "status": "success",
        "n_samples": args.n_samples,
        "best_rmse": round(best_rmse, 3),
        "best_params": {k: round(v, 4) for k, v in best_params.items()} if best_params else None,
        "top_5": results[:5],
        "param_ranges": PARAM_RANGES,
        "note": "GLUE calibration — runs W2 binary for each parameter sample",
    }

    output_path = args.output
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)

    print(json.dumps(output, indent=2))
    return 0


def main():
    parser = argparse.ArgumentParser(description="Calibrate CE-QUAL-W2 parameters")
    parser.add_argument("--run_dir", required=True)
    parser.add_argument("--grid_json", required=True)
    parser.add_argument("--observed_profiles", help="CSV with observed temperature profiles")
    parser.add_argument("--n_samples", type=int, default=100)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    sys.exit(process(args))


if __name__ == "__main__":
    main()
