#!/usr/bin/env python3
"""
parse_output.py — Parse SuperflexPy output to standardized CSV and compute metrics.

Reads JSON output from run_superflexpy.py (or raw numpy arrays) and produces:
- Standardized CSV with dates, simulated Q, observed Q
- Hydrological performance metrics (NSE, KGE, PBIAS, RMSE)
- Summary statistics

Usage:
    python parse_output.py --input results.json --output streamflow.csv
    python parse_output.py --input results.json --output streamflow.csv --warmup 365
    python parse_output.py --input results.json --metrics-only
"""

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np


def validate_inputs(args):
    """Validate command-line arguments."""
    errors = []

    input_path = Path(args.input)
    if not input_path.exists():
        errors.append(f"Input file not found: {args.input}")

    if args.warmup < 0:
        errors.append(f"Warmup must be non-negative, got {args.warmup}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)


def compute_nse(obs, sim):
    """Nash-Sutcliffe Efficiency."""
    obs = np.array(obs, dtype=float)
    sim = np.array(sim, dtype=float)
    mask = ~(np.isnan(obs) | np.isnan(sim))
    obs, sim = obs[mask], sim[mask]
    if len(obs) == 0:
        return float("nan")
    numerator = np.sum((obs - sim) ** 2)
    denominator = np.sum((obs - np.mean(obs)) ** 2)
    if denominator == 0:
        return float("nan")
    return 1.0 - numerator / denominator


def compute_kge(obs, sim):
    """Kling-Gupta Efficiency (2009 formulation)."""
    obs = np.array(obs, dtype=float)
    sim = np.array(sim, dtype=float)
    mask = ~(np.isnan(obs) | np.isnan(sim))
    obs, sim = obs[mask], sim[mask]
    if len(obs) < 2:
        return float("nan")

    r = np.corrcoef(obs, sim)[0, 1]
    alpha = np.std(sim) / np.std(obs) if np.std(obs) > 0 else float("nan")
    beta = np.mean(sim) / np.mean(obs) if np.mean(obs) > 0 else float("nan")

    if math.isnan(r) or math.isnan(alpha) or math.isnan(beta):
        return float("nan")

    return 1.0 - math.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2)


def compute_pbias(obs, sim):
    """Percent Bias. Positive = model overestimates."""
    obs = np.array(obs, dtype=float)
    sim = np.array(sim, dtype=float)
    mask = ~(np.isnan(obs) | np.isnan(sim))
    obs, sim = obs[mask], sim[mask]
    if len(obs) == 0 or np.sum(obs) == 0:
        return float("nan")
    return 100.0 * np.sum(sim - obs) / np.sum(obs)


def compute_rmse(obs, sim):
    """Root Mean Square Error."""
    obs = np.array(obs, dtype=float)
    sim = np.array(sim, dtype=float)
    mask = ~(np.isnan(obs) | np.isnan(sim))
    obs, sim = obs[mask], sim[mask]
    if len(obs) == 0:
        return float("nan")
    return float(np.sqrt(np.mean((obs - sim) ** 2)))


def compute_r(obs, sim):
    """Pearson correlation coefficient."""
    obs = np.array(obs, dtype=float)
    sim = np.array(sim, dtype=float)
    mask = ~(np.isnan(obs) | np.isnan(sim))
    obs, sim = obs[mask], sim[mask]
    if len(obs) < 2:
        return float("nan")
    return float(np.corrcoef(obs, sim)[0, 1])


def process(args):
    """Parse model output and compute metrics."""
    with open(args.input, "r") as f:
        data = json.load(f)

    if data.get("status") != "success":
        return {"status": "error", "errors": ["Input data indicates error"]}

    Q_sim = np.array(data["Q_sim"])
    n_total = len(Q_sim)
    warmup = min(args.warmup, n_total - 1)

    # Apply warmup
    Q_sim_eval = Q_sim[warmup:]
    dates = data.get("dates", None)
    if dates:
        dates_eval = dates[warmup:]
    else:
        dates_eval = list(range(warmup, n_total))

    result = {
        "status": "success",
        "n_timesteps_total": n_total,
        "n_timesteps_eval": len(Q_sim_eval),
        "warmup_days": warmup,
        "Q_sim_statistics": {
            "mean": float(np.nanmean(Q_sim_eval)),
            "median": float(np.nanmedian(Q_sim_eval)),
            "max": float(np.nanmax(Q_sim_eval)),
            "min": float(np.nanmin(Q_sim_eval)),
            "std": float(np.nanstd(Q_sim_eval)),
        },
    }

    # Compute metrics if observed data available
    if "Q_obs" in data:
        Q_obs = np.array(data["Q_obs"])
        Q_obs_eval = Q_obs[warmup:]

        metrics = {
            "NSE": round(compute_nse(Q_obs_eval, Q_sim_eval), 4),
            "KGE": round(compute_kge(Q_obs_eval, Q_sim_eval), 4),
            "PBIAS": round(compute_pbias(Q_obs_eval, Q_sim_eval), 2),
            "RMSE": round(compute_rmse(Q_obs_eval, Q_sim_eval), 4),
            "r": round(compute_r(Q_obs_eval, Q_sim_eval), 4),
        }
        result["metrics"] = metrics
        result["Q_obs_statistics"] = {
            "mean": float(np.nanmean(Q_obs_eval)),
            "median": float(np.nanmedian(Q_obs_eval)),
            "max": float(np.nanmax(Q_obs_eval)),
            "min": float(np.nanmin(Q_obs_eval)),
        }

        # Build CSV rows
        csv_rows = []
        csv_rows.append("date,Q_sim_mm_d,Q_obs_mm_d")
        for i, d in enumerate(dates_eval):
            q_s = f"{Q_sim_eval[i]:.6f}" if not np.isnan(Q_sim_eval[i]) else ""
            q_o = f"{Q_obs_eval[i]:.6f}" if i < len(Q_obs_eval) and not np.isnan(Q_obs_eval[i]) else ""
            csv_rows.append(f"{d},{q_s},{q_o}")
        result["csv_content"] = "\n".join(csv_rows)
    else:
        csv_rows = []
        csv_rows.append("date,Q_sim_mm_d")
        for i, d in enumerate(dates_eval):
            q_s = f"{Q_sim_eval[i]:.6f}" if not np.isnan(Q_sim_eval[i]) else ""
            csv_rows.append(f"{d},{q_s}")
        result["csv_content"] = "\n".join(csv_rows)

    return result


def validate_outputs(result):
    """Validate parsed outputs for common issues."""
    if result["status"] != "success":
        return result

    warnings = []

    # Check metrics quality
    if "metrics" in result:
        nse = result["metrics"].get("NSE", None)
        if nse is not None and not math.isnan(nse):
            if nse < 0:
                warnings.append(
                    f"WARNING: NSE = {nse:.3f} < 0 — model is worse than mean. "
                    "Check parameter values and forcing units."
                )
            elif nse < 0.5:
                warnings.append(
                    f"WARNING: NSE = {nse:.3f} — considered 'unsatisfactory'. "
                    "Consider calibration."
                )

        pbias = result["metrics"].get("PBIAS", None)
        if pbias is not None and not math.isnan(pbias):
            if abs(pbias) > 25:
                warnings.append(
                    f"WARNING: |PBIAS| = {abs(pbias):.1f}% > 25% — "
                    "large systematic bias, check units (dt_001, dt_002)"
                )

    if warnings:
        result["warnings"] = warnings
        for w in warnings:
            print(w, file=sys.stderr)

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Parse SuperflexPy output to CSV and compute metrics"
    )
    parser.add_argument("--input", type=str, required=True, help="Input JSON from run_superflexpy.py")
    parser.add_argument("--output", type=str, default=None, help="Output CSV file path")
    parser.add_argument("--warmup", type=int, default=0, help="Warmup period in timesteps to exclude")
    parser.add_argument("--metrics-only", action="store_true", help="Only print metrics, no CSV")

    args = parser.parse_args()

    validate_inputs(args)
    result = process(args)
    result = validate_outputs(result)

    if args.metrics_only:
        output = {
            "status": result["status"],
            "metrics": result.get("metrics", {}),
            "warnings": result.get("warnings", []),
        }
        print(json.dumps(output, indent=2))
    elif args.output and "csv_content" in result:
        with open(args.output, "w") as f:
            f.write(result["csv_content"])
        # Print metrics to stderr
        if "metrics" in result:
            print(f"Metrics: {json.dumps(result['metrics'])}", file=sys.stderr)
        print(f"CSV written to {args.output}", file=sys.stderr)
    else:
        # Print full JSON to stdout
        # Remove csv_content from JSON output to keep it manageable
        result_compact = {k: v for k, v in result.items() if k != "csv_content"}
        print(json.dumps(result_compact, indent=2))


if __name__ == "__main__":
    main()
