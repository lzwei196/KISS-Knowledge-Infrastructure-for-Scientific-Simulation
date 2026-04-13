#!/usr/bin/env python3
"""
parse_output.py — Extract HydroCNHS simulation results to CSV and compute metrics.

Parses the Data_collector object from a completed HydroCNHS run, exports
streamflow time series to CSV, and computes evaluation metrics (NSE, KGE, r,
RMSE, etc.) against observed data.

Output units:
  - Discharge Q_routed: cms (m³/s)
  - Metrics: unitless (except RMSE which has units of Q)

Usage:
    python parse_output.py \\
        --results-pickle results.pickle \\
        --observed-csv observed_streamflow.csv \\
        --start-date "1981/1/1" \\
        --warmup-years 2 \\
        --output-csv simulated.csv \\
        --metrics-json metrics.json \\
        --plot validation.png
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta

import numpy as np
import pandas as pd


def validate_inputs(args):
    """Validate inputs before processing."""
    errors = []

    if not os.path.exists(args.results_pickle):
        errors.append(f"Results pickle not found: {args.results_pickle}")

    if args.observed_csv and not os.path.exists(args.observed_csv):
        errors.append(f"Observed CSV not found: {args.observed_csv}")

    if args.warmup_years < 0:
        errors.append(f"warmup_years must be >= 0, got: {args.warmup_years}")

    return errors


def compute_nse(obs, sim):
    """Nash-Sutcliffe Efficiency. Range: (-inf, 1], 1 = perfect."""
    obs, sim = np.array(obs), np.array(sim)
    mask = ~(np.isnan(obs) | np.isnan(sim))
    obs, sim = obs[mask], sim[mask]
    numerator = np.sum((obs - sim) ** 2)
    denominator = np.sum((obs - np.mean(obs)) ** 2)
    if denominator == 0:
        return float("nan")
    return 1 - numerator / denominator


def compute_kge(obs, sim):
    """Kling-Gupta Efficiency. Range: (-inf, 1], 1 = perfect."""
    obs, sim = np.array(obs), np.array(sim)
    mask = ~(np.isnan(obs) | np.isnan(sim))
    obs, sim = obs[mask], sim[mask]
    r = np.corrcoef(obs, sim)[0, 1]
    alpha = np.std(sim) / np.std(obs)
    beta = np.mean(sim) / np.mean(obs)
    return 1 - np.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2)


def compute_rmse(obs, sim):
    """Root Mean Square Error in same units as Q."""
    obs, sim = np.array(obs), np.array(sim)
    mask = ~(np.isnan(obs) | np.isnan(sim))
    obs, sim = obs[mask], sim[mask]
    return np.sqrt(np.mean((obs - sim) ** 2))


def compute_pbias(obs, sim):
    """Percent Bias. 0 = perfect, positive = underestimation."""
    obs, sim = np.array(obs), np.array(sim)
    mask = ~(np.isnan(obs) | np.isnan(sim))
    obs, sim = obs[mask], sim[mask]
    if np.sum(obs) == 0:
        return float("nan")
    return 100.0 * np.sum(sim - obs) / np.sum(obs)


def compute_r(obs, sim):
    """Pearson correlation coefficient."""
    obs, sim = np.array(obs), np.array(sim)
    mask = ~(np.isnan(obs) | np.isnan(sim))
    obs, sim = obs[mask], sim[mask]
    return float(np.corrcoef(obs, sim)[0, 1])


def validate_output(sim_values, obs_values, log):
    """Check that output values are physically plausible."""
    sim = np.array(sim_values)

    if np.any(sim < 0):
        log.append("[WARN] Negative simulated discharge detected — possible model instability")

    if np.max(sim) > 10000:
        log.append(f"[WARN] Max simulated Q = {np.max(sim):.1f} cms — verify precipitation units")

    if obs_values is not None:
        obs = np.array(obs_values)
        ratio = np.mean(sim) / np.mean(obs) if np.mean(obs) > 0 else float("inf")
        if ratio > 5:
            log.append(
                f"[CRITICAL] Sim/Obs mean ratio = {ratio:.1f}× — "
                f"precipitation likely in mm/day instead of cm/day"
            )
        elif ratio < 0.2:
            log.append(
                f"[CRITICAL] Sim/Obs mean ratio = {ratio:.1f}× — "
                f"area likely in km² instead of ha, or precipitation in m/day"
            )

    return True


def process(args):
    """Parse results, compute metrics, export CSV."""
    import pickle

    log = []

    # Load results
    with open(args.results_pickle, "rb") as f:
        data = pickle.load(f)

    q_routed = data.get("Q_routed", {})
    dc = data.get("dc", None)

    if not q_routed and dc is not None:
        q_routed = dc.Q_routed

    outlets = list(q_routed.keys())
    log.append(f"Loaded results for {len(outlets)} outlets: {outlets}")

    # Build date index
    start = datetime.strptime(args.start_date, "%Y/%m/%d")
    n_days = len(next(iter(q_routed.values())))
    dates = pd.date_range(start=start, periods=n_days, freq="D")

    # Build DataFrame
    df = pd.DataFrame(index=dates)
    for outlet in outlets:
        df[f"Q_{outlet}_cms"] = np.array(q_routed[outlet])

    # Apply warmup
    warmup_days = args.warmup_years * 365
    if warmup_days > 0 and warmup_days < len(df):
        df_eval = df.iloc[warmup_days:]
        log.append(f"Warmup: skipping first {args.warmup_years} years ({warmup_days} days)")
    else:
        df_eval = df

    # Export to CSV
    if args.output_csv:
        df.to_csv(args.output_csv)
        log.append(f"Simulated data written to {args.output_csv}")

    # Compute metrics against observed data
    metrics = {}
    if args.observed_csv:
        obs_df = pd.read_csv(args.observed_csv, index_col=0, parse_dates=True)
        log.append(f"Loaded observed data: {list(obs_df.columns)}")

        for col in obs_df.columns:
            outlet = col.replace("Q_", "").replace("_cms", "")
            sim_col = f"Q_{outlet}_cms"

            if sim_col not in df_eval.columns:
                log.append(f"[WARN] No simulated data for observed outlet '{outlet}'")
                continue

            # Align dates
            common = df_eval.index.intersection(obs_df.index)
            if len(common) == 0:
                log.append(f"[WARN] No overlapping dates for {outlet}")
                continue

            obs = obs_df.loc[common, col].values
            sim = df_eval.loc[common, sim_col].values

            # Validate
            validate_output(sim, obs, log)

            # Compute metrics
            metrics[outlet] = {
                "NSE": round(compute_nse(obs, sim), 4),
                "KGE": round(compute_kge(obs, sim), 4),
                "r": round(compute_r(obs, sim), 4),
                "RMSE": round(compute_rmse(obs, sim), 4),
                "PBIAS": round(compute_pbias(obs, sim), 2),
                "n_points": len(common),
            }
            log.append(
                f"  {outlet}: NSE={metrics[outlet]['NSE']}, "
                f"KGE={metrics[outlet]['KGE']}, r={metrics[outlet]['r']}"
            )

    # Save metrics
    if args.metrics_json and metrics:
        with open(args.metrics_json, "w") as f:
            json.dump(metrics, f, indent=2)
        log.append(f"Metrics written to {args.metrics_json}")

    # Generate plot
    if args.plot and args.observed_csv and metrics:
        generate_plot(df_eval, obs_df, metrics, args.plot, log)

    return {
        "status": "success",
        "output": {
            "outlets": outlets,
            "n_timesteps": n_days,
            "warmup_days": warmup_days,
            "metrics": metrics,
        },
        "log": log
    }


def generate_plot(sim_df, obs_df, metrics, output_path, log):
    """Generate validation time series plot."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    outlets_with_data = list(metrics.keys())
    n = len(outlets_with_data)

    fig, axes = plt.subplots(n, 1, figsize=(14, 4 * n), squeeze=False)

    for i, outlet in enumerate(outlets_with_data):
        ax = axes[i, 0]
        sim_col = f"Q_{outlet}_cms"
        obs_col = [c for c in obs_df.columns if outlet in c]

        if not obs_col:
            continue
        obs_col = obs_col[0]

        common = sim_df.index.intersection(obs_df.index)
        ax.plot(common, obs_df.loc[common, obs_col], color="black",
                linewidth=0.8, label="Observed", alpha=0.8)
        ax.plot(common, sim_df.loc[common, sim_col], color="#2563EB",
                linewidth=0.8, label="Simulated", alpha=0.8)

        # Metrics box
        m = metrics[outlet]
        text = f"NSE={m['NSE']:.3f}\nKGE={m['KGE']:.3f}\nr={m['r']:.3f}\nPBIAS={m['PBIAS']:.1f}%"
        ax.text(0.98, 0.95, text, transform=ax.transAxes, fontsize=9,
                verticalalignment="top", horizontalalignment="right",
                bbox=dict(boxstyle="round", facecolor="white", alpha=0.8))

        ax.set_ylabel(f"Q at {outlet} (cms)")
        ax.legend(loc="upper left", fontsize=8)
        ax.set_title(f"HydroCNHS Validation — {outlet}")

    plt.tight_layout()
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close()
    log.append(f"Validation plot saved to {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Parse HydroCNHS output and compute metrics")
    parser.add_argument("--results-pickle", required=True, help="Results pickle from run_hydrocnhs.py")
    parser.add_argument("--observed-csv", default=None, help="Observed streamflow CSV")
    parser.add_argument("--start-date", required=True, help="Simulation start date YYYY/M/D")
    parser.add_argument("--warmup-years", type=int, default=2, help="Years to skip for warmup")
    parser.add_argument("--output-csv", default=None, help="Output CSV file path")
    parser.add_argument("--metrics-json", default=None, help="Output metrics JSON file")
    parser.add_argument("--plot", default=None, help="Output validation plot PNG")

    args = parser.parse_args()

    errors = validate_inputs(args)
    if errors:
        print(json.dumps({"status": "error", "errors": errors}, indent=2))
        sys.exit(1)

    result = process(args)

    if args.output_csv is None and args.metrics_json is None:
        print(json.dumps(result, indent=2))
    else:
        for line in result.get("log", []):
            print(line)

    if result["status"] == "error":
        sys.exit(1)


if __name__ == "__main__":
    main()
