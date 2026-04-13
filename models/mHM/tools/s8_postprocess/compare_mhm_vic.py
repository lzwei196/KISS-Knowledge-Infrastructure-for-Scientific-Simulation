#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
Tool ID:      compare_mhm_vic
Stage:        s8_postprocess
Description:  Compare mHM vs VIC discharge at the same basin for cross-model benchmarking.

This tool reads discharge from both mHM (output_b1/discharge.nc or daily_discharge.out)
and VIC (routing output) and computes comparative metrics.

Inputs:
  - MHM_OUTPUT_DIR: mHM output_b1/ directory
  - VIC_DISCHARGE_FILE: VIC routed discharge file (from Lohmann routing or CaMa-Flood)
  - OBS_FILE: optional observed discharge for three-way comparison
  - WARMUP_DAYS: days to skip

Outputs:
  - Comparison report (JSON with metrics for both models)
"""

import sys
import os
import json
import logging
import numpy as np
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

MHM_OUTPUT_DIR = ""
VIC_DISCHARGE_FILE = ""
OBS_FILE = ""
WARMUP_DAYS = 365

if len(sys.argv) > 1:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--mhm_output", required=True)
    parser.add_argument("--vic_discharge", required=True)
    parser.add_argument("--obs_file", default="")
    parser.add_argument("--warmup_days", type=int, default=365)
    args = parser.parse_args()
    MHM_OUTPUT_DIR = args.mhm_output
    VIC_DISCHARGE_FILE = args.vic_discharge
    OBS_FILE = args.obs_file
    WARMUP_DAYS = args.warmup_days


def compute_metrics(obs, sim):
    mask = ~(np.isnan(obs) | np.isnan(sim) | (obs < 0) | (sim < 0))
    obs, sim = obs[mask], sim[mask]
    if len(obs) < 10:
        return {"error": "insufficient data"}

    ss_res = np.sum((obs - sim) ** 2)
    ss_tot = np.sum((obs - np.mean(obs)) ** 2)
    nse = 1 - ss_res / ss_tot if ss_tot > 0 else float('nan')

    r = np.corrcoef(obs, sim)[0, 1]
    alpha = np.std(sim) / np.std(obs) if np.std(obs) > 0 else 1
    beta = np.mean(sim) / np.mean(obs) if np.mean(obs) > 0 else 1
    kge = 1 - np.sqrt((r-1)**2 + (alpha-1)**2 + (beta-1)**2)

    return {
        "NSE": round(float(nse), 4),
        "KGE": round(float(kge), 4),
        "RMSE": round(float(np.sqrt(np.mean((obs-sim)**2))), 2),
        "PBIAS": round(float(100 * np.sum(sim-obs) / np.sum(obs)), 2),
        "r": round(float(r), 4),
        "mean_sim": round(float(np.mean(sim)), 2),
        "mean_obs": round(float(np.mean(obs)), 2),
        "n": int(len(obs)),
    }


def read_mhm_discharge(output_dir):
    """Read mHM simulated discharge."""
    out_dir = Path(output_dir)

    # Try daily_discharge.out first
    daily_out = out_dir / "daily_discharge.out"
    if daily_out.exists():
        sim = []
        with open(daily_out) as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 6:
                    try:
                        sim.append(float(parts[5]))
                    except ValueError:
                        continue
        return np.array(sim)

    # Try discharge.nc
    try:
        import xarray as xr
        ds = xr.open_dataset(out_dir / "discharge.nc")
        for v in ["Qrouted", "Q", "discharge"]:
            if v in ds.data_vars:
                data = ds[v].values
                if data.ndim == 2:
                    return data[:, 0]
                return data
    except Exception:
        pass

    return None


def read_vic_discharge(filepath):
    """Read VIC routed discharge."""
    q = []
    with open(filepath) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) >= 4:
                try:
                    q.append(float(parts[3]))  # Q typically in column 4
                except (ValueError, IndexError):
                    continue
    return np.array(q) if q else None


def validate_inputs():
    errors = []
    if not MHM_OUTPUT_DIR or not Path(MHM_OUTPUT_DIR).exists():
        errors.append(f"mHM output not found: {MHM_OUTPUT_DIR}")
    if not VIC_DISCHARGE_FILE or not Path(VIC_DISCHARGE_FILE).exists():
        errors.append(f"VIC discharge not found: {VIC_DISCHARGE_FILE}")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)


def process():
    mhm_q = read_mhm_discharge(MHM_OUTPUT_DIR)
    vic_q = read_vic_discharge(VIC_DISCHARGE_FILE)

    if mhm_q is None:
        logger.error("Could not read mHM discharge")
        sys.exit(2)
    if vic_q is None:
        logger.error("Could not read VIC discharge")
        sys.exit(2)

    # Align lengths
    n = min(len(mhm_q), len(vic_q))
    mhm_q = mhm_q[:n]
    vic_q = vic_q[:n]

    # Skip warmup
    skip = min(WARMUP_DAYS, n // 2)
    mhm_eval = mhm_q[skip:]
    vic_eval = vic_q[skip:]

    result = {
        "status": "success",
        "n_timesteps": int(n),
        "warmup_skipped": skip,
        "mhm_stats": {
            "mean_Q": round(float(np.nanmean(mhm_eval)), 2),
            "max_Q": round(float(np.nanmax(mhm_eval)), 2),
            "min_Q": round(float(np.nanmin(mhm_eval)), 2),
        },
        "vic_stats": {
            "mean_Q": round(float(np.nanmean(vic_eval)), 2),
            "max_Q": round(float(np.nanmax(vic_eval)), 2),
            "min_Q": round(float(np.nanmin(vic_eval)), 2),
        },
        "mhm_vs_vic_correlation": round(float(np.corrcoef(mhm_eval, vic_eval)[0, 1]), 4),
    }

    # If observed data available, compute metrics for both
    if OBS_FILE and Path(OBS_FILE).exists():
        obs_q = []
        with open(OBS_FILE) as f:
            f.readline()  # skip header
            for line in f:
                parts = line.strip().split('\t')
                if len(parts) < 4:
                    parts = line.strip().split()
                if len(parts) >= 4:
                    try:
                        obs_q.append(float(parts[3]))
                    except ValueError:
                        obs_q.append(-9999)

        obs_arr = np.array(obs_q[:n])
        obs_eval = obs_arr[skip:]

        result["mhm_vs_obs"] = compute_metrics(obs_eval, mhm_eval)
        result["vic_vs_obs"] = compute_metrics(obs_eval, vic_eval)

        if "NSE" in result["mhm_vs_obs"] and "NSE" in result["vic_vs_obs"]:
            mhm_nse = result["mhm_vs_obs"]["NSE"]
            vic_nse = result["vic_vs_obs"]["NSE"]
            if mhm_nse > vic_nse:
                result["winner"] = "mHM"
                result["nse_advantage"] = round(mhm_nse - vic_nse, 4)
            else:
                result["winner"] = "VIC"
                result["nse_advantage"] = round(vic_nse - mhm_nse, 4)

    print(json.dumps(result, indent=2))
    return str(MHM_OUTPUT_DIR)


if __name__ == "__main__":
    validate_inputs()
    try:
        process()
    except Exception as e:
        logger.error(f"Failed: {e}")
        import traceback; traceback.print_exc()
        sys.exit(2)
    sys.exit(0)
