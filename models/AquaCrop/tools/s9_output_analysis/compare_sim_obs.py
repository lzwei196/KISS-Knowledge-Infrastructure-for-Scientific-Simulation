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

    # NSE (Nash-Sutcliffe efficiency: 1 - SS_res/SS_tot; can be negative).
    # NOTE: this was historically (mis)labeled "R_squared". True coefficient of
    # determination is the SQUARED Pearson r (always >=0); NSE is what this
    # formula computes. The SKILL multi-year recipe promises r / NSE / KGE, so
    # we report all three via the canonical ki_tools_common.metrics impls and
    # keep "R_squared" as a back-compat alias for NSE.
    ss_res = np.sum((obs - sim) ** 2)
    ss_tot = np.sum((obs - obs_mean) ** 2)
    nse_val = 1.0 - ss_res / ss_tot if ss_tot != 0 else 0.0

    # Pearson r / NSE / KGE / PBIAS from the shared, validated implementations.
    try:
        # ki_tools_common.metrics functions all take (obs, sim) order.
        from ki_tools_common.metrics import nse as _nse, kge as _kge, \
            pearson_r as _pr, pbias as _pbias
        r_val = float(_pr(obs, sim))
        nse_val = float(_nse(obs, sim))
        kge_val = float(_kge(obs, sim))
        pbias = float(_pbias(obs, sim))
    except Exception:
        # Fallback: Pearson r and KGE computed inline if the shared lib is absent.
        sim_mean = np.mean(sim)
        sd_o, sd_s = np.std(obs), np.std(sim)
        if sd_o > 0 and sd_s > 0:
            r_val = float(np.corrcoef(sim, obs)[0, 1])
            alpha = sd_s / sd_o
            beta = sim_mean / obs_mean if obs_mean != 0 else np.nan
            kge_val = 1.0 - np.sqrt((r_val - 1) ** 2 + (alpha - 1) ** 2
                                    + (beta - 1) ** 2)
        else:
            r_val, kge_val = float('nan'), float('nan')

    metrics = {
        "n": n,
        "RMSE": round(rmse, 4),
        "NRMSE": round(nrmse, 4),
        "d_index": round(d_index, 4),
        "bias": round(bias, 4),
        "PBIAS_pct": round(pbias, 2),
        "r": round(r_val, 4),
        "NSE": round(nse_val, 4),
        "KGE": round(kge_val, 4),
        "R_squared": round(nse_val, 4),  # back-compat alias (== NSE, not Pearson r^2)
        "obs_mean": round(obs_mean, 4),
        "sim_mean": round(np.mean(sim), 4),
    }

    print(json.dumps(metrics, indent=2))
    return metrics


def compute_aggregate_metrics(simulated, observed, years):
    """
    Metrics for a `regional_aggregate_time_series` obs_shape (e.g. FAOSTAT /
    GDHY national-yield series). Per dag.yaml `outputs.DryYield.observability`,
    the ONLY scientifically valid metric_families for this obs_shape are
    `magnitude_accuracy` and `trend_match` -- raw NSE / Pearson r / KGE on the
    inter-annual series are INAPPROPRIATE because a national aggregate is
    dominated by a technology/management trend a weather-only model cannot
    reproduce. Both series trend upward over decades, so a raw r looks high
    (~0.85 for China maize 2000-2018) while the detrended residuals share no
    co-movement (detrended_r ~ 0.00). The dag-driven retry gate rejects raw
    NSE/r here as REJECT_WRONG_METRIC; use the metrics this function returns.

    Args:
        simulated: array-like, one value per year (aligned with `years`)
        observed:  array-like, one value per year (aligned with `years`)
        years:     array-like of integer years, same length

    Returns:
        dict with:
          magnitude_accuracy: PBIAS_pct, RMSE, NRMSE, obs_mean, sim_mean
          trend_match:        sim_slope, obs_slope, slope_ratio, detrended_r,
                              decadal_pbias_early, decadal_pbias_late
          obs_shape:          'regional_aggregate_time_series'
          valid_metric_families / invalid_metrics (advisory)
    """
    sim = np.asarray(simulated, dtype=float)
    obs = np.asarray(observed, dtype=float)
    yrs = np.asarray(years, dtype=float)
    mask = ~(np.isnan(sim) | np.isnan(obs) | np.isnan(yrs))
    sim, obs, yrs = sim[mask], obs[mask], yrs[mask]
    n = len(sim)
    if n < 3:
        return {"error": "Need >=3 aligned year pairs for aggregate/trend metrics"}

    obs_mean = float(np.mean(obs))
    rmse = float(np.sqrt(np.mean((sim - obs) ** 2)))
    pbias = 100.0 * float(np.mean(sim - obs)) / obs_mean if obs_mean else float("inf")
    nrmse = rmse / obs_mean if obs_mean else float("inf")

    # trend_match: linear-slope agreement + detrended-residual correlation.
    sim_slope = float(np.polyfit(yrs, sim, 1)[0])
    obs_slope = float(np.polyfit(yrs, obs, 1)[0])
    slope_ratio = sim_slope / obs_slope if obs_slope else float("nan")
    sim_dt = sim - np.polyval(np.polyfit(yrs, sim, 1), yrs)
    obs_dt = obs - np.polyval(np.polyfit(yrs, obs, 1), yrs)
    if np.std(sim_dt) > 0 and np.std(obs_dt) > 0:
        detrended_r = float(np.corrcoef(sim_dt, obs_dt)[0, 1])
    else:
        detrended_r = float("nan")

    # decadal-mean PBIAS: split the window in half, compare period means.
    half = n // 2
    def _pb(a, b):
        bm = float(np.mean(b))
        return 100.0 * (float(np.mean(a)) - bm) / bm if bm else float("inf")
    dec_early = _pb(sim[:half], obs[:half])
    dec_late = _pb(sim[half:], obs[half:])

    out = {
        "n": n,
        "obs_shape": "regional_aggregate_time_series",
        "valid_metric_families": ["magnitude_accuracy", "trend_match"],
        "invalid_metrics": ["raw NSE", "raw Pearson r", "raw KGE"],
        "magnitude_accuracy": {
            "PBIAS_pct": round(pbias, 2),
            "RMSE": round(rmse, 4),
            "NRMSE": round(nrmse, 4),
            "obs_mean": round(obs_mean, 4),
            "sim_mean": round(float(np.mean(sim)), 4),
        },
        "trend_match": {
            "sim_slope_per_yr": round(sim_slope, 5),
            "obs_slope_per_yr": round(obs_slope, 5),
            "slope_ratio": round(slope_ratio, 3) if np.isfinite(slope_ratio) else None,
            "detrended_r": round(detrended_r, 3) if np.isfinite(detrended_r) else None,
            "decadal_pbias_early": round(dec_early, 2),
            "decadal_pbias_late": round(dec_late, 2),
        },
    }
    print(json.dumps(out, indent=2))
    return out


if __name__ == "__main__":
    logger.info("Usage: from compare_sim_obs import compute_metrics")
    logger.info("       metrics = compute_metrics(simulated_array, observed_array)")
    logger.info("For FAOSTAT/GDHY national series (regional_aggregate_time_series):")
    logger.info("       from compare_sim_obs import compute_aggregate_metrics")
    logger.info("       m = compute_aggregate_metrics(sim, obs, years)  # PBIAS + trend, NOT raw NSE/r")
    sys.exit(0)
