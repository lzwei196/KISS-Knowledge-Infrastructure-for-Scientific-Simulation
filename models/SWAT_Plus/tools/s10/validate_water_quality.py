#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
Tool ID:      validate_water_quality
Stage:        s10_water_quality
Description:  Validate SWAT+ nutrient/sediment output against observations.
              Computes PBIAS for annual loads and Pearson R for monthly
              concentrations, following Moriasi et al. (2007) thresholds.

Usage:
    python validate_water_quality.py --sim_csv <path> --obs_csv <path> \
        [--variable TN|TP|sediment] [--timestep monthly|annual]

sim_csv: output from parse_nutrient_output.py (daily nutrient time series)
obs_csv: observed water quality data with columns:
         date (YYYY-MM-DD), TN_kg (or TN_mg_l), TP_kg (or TP_mg_l), sed_tons
         OR: year, month, TN_kg, TP_kg, sed_tons (for monthly/annual data)

Performance thresholds (Moriasi et al., 2007; 2015):
    Nitrogen:  PBIAS < +/-25%  => Satisfactory
    Phosphorus: PBIAS < +/-40% => Satisfactory (higher tolerance due to P complexity)
    Sediment:  PBIAS < +/-30%  => Satisfactory
    Monthly R: > 0.6 => Acceptable correlation

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import argparse
import logging
import json
import csv
import math
from pathlib import Path
from collections import defaultdict

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Moriasi et al. (2007, 2015) performance rating thresholds
THRESHOLDS = {
    "TN": {
        "pbias_very_good": 15,
        "pbias_good": 20,
        "pbias_satisfactory": 25,
        "r_satisfactory": 0.60,
    },
    "TP": {
        "pbias_very_good": 25,
        "pbias_good": 30,
        "pbias_satisfactory": 40,
        "r_satisfactory": 0.60,
    },
    "sediment": {
        "pbias_very_good": 15,
        "pbias_good": 20,
        "pbias_satisfactory": 30,
        "r_satisfactory": 0.60,
    },
}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Validate SWAT+ water quality output against observations"
    )
    parser.add_argument(
        "--sim_csv", required=True,
        help="Simulated nutrient CSV from parse_nutrient_output.py"
    )
    parser.add_argument(
        "--obs_csv", required=True,
        help="Observed water quality data CSV"
    )
    parser.add_argument(
        "--variable", nargs="+", default=["TN", "TP", "sediment"],
        choices=["TN", "TP", "sediment"],
        help="Variables to validate (default: all)"
    )
    parser.add_argument(
        "--timestep", default="monthly",
        choices=["monthly", "annual"],
        help="Aggregation timestep for comparison (default: monthly)"
    )
    parser.add_argument(
        "--obs_is_daily_rate", action="store_true",
        help="Each obs row is an INSTANTANEOUS or DAILY load (a grab sample), not a "
             "period total. The period value is then mean(samples) x days-in-period "
             "instead of a raw sum, which otherwise makes the observed load scale "
             "with sampling effort. See aggregate_obs_data()."
    )
    return parser.parse_args()


def validate_inputs(args):
    errors = []
    if not Path(args.sim_csv).exists():
        errors.append(f"Simulated CSV not found: {args.sim_csv}")
    if not Path(args.obs_csv).exists():
        errors.append(f"Observed CSV not found: {args.obs_csv}")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def read_csv_data(filepath):
    """Read CSV and return list of dicts."""
    records = []
    with open(filepath) as f:
        reader = csv.DictReader(f)
        for row in reader:
            records.append(row)
    return records


def aggregate_sim_data(records, timestep):
    """Aggregate daily simulated data to monthly or annual."""
    agg = defaultdict(lambda: defaultdict(float))
    counts = defaultdict(int)

    for rec in records:
        date_str = rec.get("date", "")
        if not date_str:
            continue

        parts = date_str.split("-")
        if len(parts) < 3:
            continue
        yr, mo = int(parts[0]), int(parts[1])

        if timestep == "monthly":
            key = (yr, mo)
        else:
            key = (yr,)

        for col in ["TN_kg", "TP_kg", "sed_out"]:
            if col in rec and rec[col]:
                try:
                    agg[key][col] += float(rec[col])
                except (ValueError, TypeError):
                    pass

        # Also aggregate flow for concentration if available
        if "flo_out_m3s" in rec and rec["flo_out_m3s"]:
            try:
                agg[key]["flo_out_m3s"] += float(rec["flo_out_m3s"])
            except (ValueError, TypeError):
                pass

        counts[key] += 1

    # Convert flow sum to average
    for key in agg:
        if counts[key] > 0 and "flo_out_m3s" in agg[key]:
            agg[key]["flo_out_m3s"] /= counts[key]

    return dict(agg)


def aggregate_obs_data(records, timestep, obs_is_daily_rate=False):
    """Aggregate observed data. Handles both daily and pre-aggregated formats.

    ⚠️ SAMPLING-EFFORT TRAP (documented 2026-08-20).
    The default behaviour is a RAW SUM of every observed value inside the period,
    which is only correct when the obs rows are already period totals or a complete
    daily series. Water-quality observations are almost never that: they are grab
    samples, so a "monthly observed load" built this way is
    ``n_samples x (instantaneous daily load)`` and therefore scales with SAMPLING
    EFFORT, while the simulated side genuinely sums 28-31 daily values. The two
    sides then sit on different time bases and the resulting PBIAS/NSE are not
    interpretable. On the Rio San Pedro Mezquital (13 stations, ~10 grab samples a
    month) this understated the observed monthly load by roughly 3x.

    Pass ``obs_is_daily_rate=True`` (CLI: --obs_is_daily_rate) when each obs row is
    an INSTANTANEOUS or DAILY load: the period value is then the MEAN of the samples
    scaled by the number of days in the period, which is the standard grab-sample
    averaging estimator.
    """
    import calendar as _cal

    agg = defaultdict(lambda: defaultdict(float))
    counts = defaultdict(lambda: defaultdict(int))

    for rec in records:
        # Try date column first
        date_str = rec.get("date", "")
        yr = mo = None

        if date_str:
            parts = date_str.split("-")
            if len(parts) >= 2:
                yr, mo = int(parts[0]), int(parts[1])
        else:
            # Try year/month columns
            if "year" in rec:
                yr = int(rec["year"])
            if "month" in rec:
                mo = int(rec["month"])

        if yr is None:
            continue

        if timestep == "monthly":
            if mo is None:
                continue
            key = (yr, mo)
        else:
            key = (yr,)

        # Map observed column names (flexible)
        col_mapping = {
            "TN_kg": ["TN_kg", "tn_kg", "TN", "tn", "total_n_kg"],
            "TP_kg": ["TP_kg", "tp_kg", "TP", "tp", "total_p_kg"],
            "sed_out": ["sed_tons", "sed_out", "sediment", "sed", "tss_tons"],
        }

        for target, aliases in col_mapping.items():
            for alias in aliases:
                if alias in rec and rec[alias]:
                    try:
                        agg[key][target] += float(rec[alias])
                        counts[key][target] += 1
                    except (ValueError, TypeError):
                        pass
                    break

    if obs_is_daily_rate:
        for key in agg:
            if len(key) == 2:
                yr, mo = key
                ndays = _cal.monthrange(yr, mo)[1]
            else:
                yr = key[0]
                ndays = 366 if _cal.isleap(yr) else 365
            for target in list(agg[key]):
                n = counts[key][target]
                if n > 0:
                    agg[key][target] = agg[key][target] / n * ndays
    else:
        multi = sum(1 for k in counts for t in counts[k] if counts[k][t] > 1)
        if multi:
            logger.warning(
                "%d period(s) contain MORE THAN ONE observation row and were "
                "RAW-SUMMED. If those rows are grab samples (instantaneous or "
                "daily loads) the aggregate scales with sampling effort, not with "
                "the period, and the comparison against the summed simulated "
                "period is meaningless. Re-run with --obs_is_daily_rate.", multi)

    return dict(agg)


def compute_pbias(sim_values, obs_values):
    """Percent Bias: 100 * sum(obs - sim) / sum(obs)."""
    total_obs = sum(obs_values)
    if total_obs == 0:
        return float("inf")
    return 100.0 * sum(o - s for o, s in zip(obs_values, sim_values)) / total_obs


def compute_pearson_r(sim_values, obs_values):
    """Pearson correlation coefficient."""
    n = len(sim_values)
    if n < 3:
        return float("nan")

    sim_mean = sum(sim_values) / n
    obs_mean = sum(obs_values) / n

    sim_std = math.sqrt(sum((s - sim_mean) ** 2 for s in sim_values) / n)
    obs_std = math.sqrt(sum((o - obs_mean) ** 2 for o in obs_values) / n)

    if sim_std == 0 or obs_std == 0:
        return 0.0

    r = sum((s - sim_mean) * (o - obs_mean) for s, o in zip(sim_values, obs_values))
    r /= (n * sim_std * obs_std)
    return r


def compute_rmse(sim_values, obs_values):
    """Root Mean Square Error."""
    n = len(sim_values)
    if n == 0:
        return float("nan")
    return math.sqrt(sum((o - s) ** 2 for o, s in zip(obs_values, sim_values)) / n)


def compute_nse(sim_values, obs_values):
    """Nash-Sutcliffe Efficiency."""
    obs_mean = sum(obs_values) / len(obs_values)
    numerator = sum((o - s) ** 2 for o, s in zip(obs_values, sim_values))
    denominator = sum((o - obs_mean) ** 2 for o in obs_values)
    if denominator == 0:
        return float("-inf")
    return 1 - numerator / denominator


def rate_wq_performance(variable, pbias, r):
    """Rate performance using Moriasi et al. thresholds."""
    thresh = THRESHOLDS.get(variable, THRESHOLDS["TN"])

    abs_pbias = abs(pbias)

    if abs_pbias <= thresh["pbias_very_good"] and r >= 0.80:
        return "Very Good"
    elif abs_pbias <= thresh["pbias_good"] and r >= 0.70:
        return "Good"
    elif abs_pbias <= thresh["pbias_satisfactory"] and r >= thresh["r_satisfactory"]:
        return "Satisfactory"
    else:
        return "Unsatisfactory"


def process(args):
    sim_records = read_csv_data(args.sim_csv)
    obs_records = read_csv_data(args.obs_csv)

    sim_agg = aggregate_sim_data(sim_records, args.timestep)
    obs_agg = aggregate_obs_data(obs_records, args.timestep,
                                 obs_is_daily_rate=args.obs_is_daily_rate)

    # Find common time keys
    common_keys = sorted(set(sim_agg.keys()) & set(obs_agg.keys()))

    if not common_keys:
        raise ValueError("No overlapping time periods between simulated and observed data. "
                         "Check date ranges and column names.")

    logger.info(f"Found {len(common_keys)} common {args.timestep} periods")

    # Variable mapping
    var_col_map = {
        "TN": "TN_kg",
        "TP": "TP_kg",
        "sediment": "sed_out",
    }

    results = {}

    for variable in args.variable:
        col = var_col_map[variable]

        # Extract paired values
        sim_vals = []
        obs_vals = []
        for key in common_keys:
            sim_v = sim_agg[key].get(col, 0)
            obs_v = obs_agg[key].get(col, None)
            if obs_v is not None and obs_v > 0:
                sim_vals.append(sim_v)
                obs_vals.append(obs_v)

        if len(sim_vals) < 3:
            logger.warning(f"{variable}: Only {len(sim_vals)} paired data points; "
                           f"skipping (need >= 3)")
            results[variable] = {
                "status": "insufficient_data",
                "n_pairs": len(sim_vals),
            }
            continue

        pbias = compute_pbias(sim_vals, obs_vals)
        r = compute_pearson_r(sim_vals, obs_vals)
        nse = compute_nse(sim_vals, obs_vals)
        rmse = compute_rmse(sim_vals, obs_vals)
        rating = rate_wq_performance(variable, pbias, r)

        results[variable] = {
            "status": "computed",
            "n_pairs": len(sim_vals),
            "PBIAS_pct": round(pbias, 2),
            "Pearson_R": round(r, 4),
            "NSE": round(nse, 4),
            "RMSE": round(rmse, 3),
            "rating": rating,
            "threshold_PBIAS": THRESHOLDS.get(variable, THRESHOLDS["TN"])["pbias_satisfactory"],
            "sim_mean": round(sum(sim_vals) / len(sim_vals), 3),
            "obs_mean": round(sum(obs_vals) / len(obs_vals), 3),
        }

        logger.info(f"  {variable}: PBIAS={pbias:.1f}%, R={r:.3f}, NSE={nse:.3f} [{rating}]")

    return {
        "status": "success",
        "timestep": args.timestep,
        "n_common_periods": len(common_keys),
        "variables": results,
        "notes": [
            "PBIAS > 0 means model underestimates (obs > sim)",
            "PBIAS < 0 means model overestimates (sim > obs)",
            "SIGN WARNING: this tool follows Moriasi et al. (2007), 100*sum(obs-sim)"
            "/sum(obs). ki_tools_common.metrics.all_metrics uses the OPPOSITE sign "
            "(there, PBIAS > 0 means the model OVER-predicts). Do not compare the "
            "two PBIAS values without flipping one of them.",
            "For N: PBIAS < +/-25% is Satisfactory (Moriasi et al., 2007)",
            "For P: PBIAS < +/-40% is Satisfactory (higher tolerance)",
            "For sediment: PBIAS < +/-30% is Satisfactory",
            "If Unsatisfactory, calibrate NPERCO, PPERCO, CDN, SDNCO, USLE_P in codes.bsn",
        ],
    }


def validate_outputs(result):
    any_computed = False
    for var, metrics in result["variables"].items():
        if metrics["status"] == "computed":
            any_computed = True
            if metrics["rating"] == "Unsatisfactory":
                logger.warning(f"{var} performance is Unsatisfactory "
                               f"(PBIAS={metrics['PBIAS_pct']:.1f}%, "
                               f"R={metrics['Pearson_R']:.3f}). "
                               f"Calibration recommended.")
    if not any_computed:
        logger.warning("No variables could be validated. Check observed data format.")
    logger.info("Output validation passed.")


if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    args = parse_args()
    validate_inputs(args)
    try:
        result = process(args)
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        sys.exit(2)
    validate_outputs(result)
    print(json.dumps(result, indent=2))
    sys.exit(0)
