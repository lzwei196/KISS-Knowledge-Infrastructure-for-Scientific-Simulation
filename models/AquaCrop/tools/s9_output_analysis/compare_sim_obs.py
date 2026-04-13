#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
Tool ID:      compare_sim_obs
Stage:        s9_output_analysis
Description:  Compares simulated yield/ET/phenology against observed data.
              Computes RMSE, NRMSE, d-index (Willmott), bias.

Inputs:
  - simulated: Simulated values (pandas Series or array)
  - observed: Observed values (pandas Series or array)

Outputs:
  - JSON with RMSE, NRMSE, d-index, bias, r-squared

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import json
import logging
import numpy as np
sys.path.insert(0, "/home/server/knowledge-dissection-toolkit/auto_dissect")
from ki_tools_common.metrics import nse as calc_nse, kge as calc_kge, pbias as calc_pbias, rmse as calc_rmse

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def compute_metrics(simulated, observed):
    """
    Compute performance metrics between simulated and observed values.

    Args:
        simulated: array-like of simulated values
        observed: array-like of observed values

    Returns:
        dict with RMSE, NRMSE, d_index, bias, r_squared, n
    """
    sim = np.asarray(simulated, dtype=float)
    obs = np.asarray(observed, dtype=float)

    # Remove NaN pairs
    mask = ~(np.isnan(sim) | np.isnan(obs))
    sim = sim[mask]
    obs = obs[mask]

    n = len(sim)
    if n == 0:
        return {"error": "No valid data pairs after removing NaN"}

    # RMSE
    rmse = calc_rmse(obs, sim)

    # NRMSE (normalized by observed mean)
    obs_mean = np.mean(obs)
    nrmse = rmse / obs_mean if obs_mean != 0 else float('inf')

    # Bias
    bias = np.mean(sim - obs)
    pbias = 100 * bias / obs_mean if obs_mean != 0 else float('inf')

    # Willmott d-index
    diff_sq = np.sum((sim - obs) ** 2)
    denom = np.sum((np.abs(sim - obs_mean) + np.abs(obs - obs_mean)) ** 2)
    d_index = 1.0 - diff_sq / denom if denom != 0 else 0.0

    # R-squared
    ss_res = np.sum((obs - sim) ** 2)
    ss_tot = np.sum((obs - obs_mean) ** 2)
    r_squared = 1.0 - ss_res / ss_tot if ss_tot != 0 else 0.0

    metrics = {
        "n": n,
        "RMSE": round(rmse, 4),
        "NRMSE": round(nrmse, 4),
        "d_index": round(d_index, 4),
        "bias": round(bias, 4),
        "PBIAS_pct": round(pbias, 2),
        "R_squared": round(r_squared, 4),
        "obs_mean": round(obs_mean, 4),
        "sim_mean": round(np.mean(sim), 4),
    }

    print(json.dumps(metrics, indent=2))
    return metrics


if __name__ == "__main__":
    logger.info("Usage: from compare_sim_obs import compute_metrics")
    logger.info("       metrics = compute_metrics(simulated_array, observed_array)")
    sys.exit(0)
