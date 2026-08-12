#!/usr/bin/env python3
"""
parse_rapid_output.py — Parse RAPID output NetCDF and compute evaluation metrics.

Reads RAPID Qout (discharge, m³/s) and optionally V (volume, m³) NetCDF files,
computes hydrological performance metrics against observations, and exports
results to CSV and summary JSON.

Supported metrics:
  - NSE (Nash-Sutcliffe Efficiency)
  - KGE (Kling-Gupta Efficiency)
  - PBIAS (Percent Bias)
  - RMSE (Root Mean Square Error)
  - Correlation coefficient (r)

Usage:
  python parse_rapid_output.py \\
    --qout_file /path/to/Qout.nc \\
    --obs_file /path/to/Qobs.nc \\
    --reach_id 74120836 \\
    --output_csv /path/to/results.csv \\
    --output_json /path/to/metrics.json \\
    --figure /path/to/hydrograph.png
"""

import argparse
import json
import os
import sys
from datetime import datetime

import netCDF4 as nc
import numpy as np


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_inputs(args):
    """Check input files exist and are readable NetCDF."""
    errors = []

    if not os.path.isfile(args.qout_file):
        errors.append(f"Qout file not found: {args.qout_file}")
    else:
        try:
            ds = nc.Dataset(args.qout_file, "r")
            if "Qout" not in ds.variables:
                errors.append(f"Variable 'Qout' not found in {args.qout_file}")
            ds.close()
        except Exception as e:
            errors.append(f"Cannot read {args.qout_file}: {e}")

    if args.obs_file and not os.path.isfile(args.obs_file):
        errors.append(f"Observation file not found: {args.obs_file}")

    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


def validate_outputs(metrics):
    """Check computed metrics are within plausible ranges."""
    warnings = []

    if "nse" in metrics:
        if metrics["nse"] < -10:
            warnings.append(f"NSE = {metrics['nse']:.3f} is extremely poor — "
                            "check if observed/simulated are aligned in time")

    if "pbias" in metrics:
        if abs(metrics["pbias"]) > 100:
            warnings.append(f"PBIAS = {metrics['pbias']:.1f}% — "
                            "indicates severe systematic error, check units")

    if "r" in metrics:
        if metrics["r"] < 0:
            warnings.append("Negative correlation — simulated and observed may be misaligned")

    for w in warnings:
        print(f"WARNING: {w}", file=sys.stderr)

    return warnings


# ---------------------------------------------------------------------------
# Metric computation
# ---------------------------------------------------------------------------

def compute_nse(obs, sim):
    """Nash-Sutcliffe Efficiency: 1 = perfect, 0 = mean, <0 = worse than mean."""
    obs_mean = np.nanmean(obs)
    numerator = np.nansum((obs - sim) ** 2)
    denominator = np.nansum((obs - obs_mean) ** 2)
    if denominator == 0:
        return float("nan")
    return 1.0 - numerator / denominator


def compute_kge(obs, sim):
    """Kling-Gupta Efficiency: 1 = perfect."""
    r = np.corrcoef(obs[~np.isnan(obs) & ~np.isnan(sim)],
                     sim[~np.isnan(obs) & ~np.isnan(sim)])[0, 1]
    alpha = np.nanstd(sim) / np.nanstd(obs)
    beta = np.nanmean(sim) / np.nanmean(obs)
    return 1.0 - np.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2)


def compute_pbias(obs, sim):
    """Percent bias: 0 = perfect, positive = overestimate."""
    return 100.0 * np.nansum(sim - obs) / np.nansum(obs)


def compute_rmse(obs, sim):
    """Root Mean Square Error in same units as input."""
    return np.sqrt(np.nanmean((obs - sim) ** 2))


def compute_all_metrics(obs, sim):
    """Compute all standard hydrological metrics."""
    # Coerce masked arrays / float32 to plain float64 with masked -> NaN so the
    # NaN-aware reductions work and the returned dict is JSON-serializable.
    obs = np.ma.filled(np.ma.asarray(obs).astype(np.float64), np.nan)
    sim = np.ma.filled(np.ma.asarray(sim).astype(np.float64), np.nan)
    mask = ~np.isnan(obs) & ~np.isnan(sim)
    if mask.sum() < 10:
        return {"error": "Too few valid data points for metrics"}

    obs_clean = obs[mask]
    sim_clean = sim[mask]

    return {
        "nse": float(round(compute_nse(obs_clean, sim_clean), 4)),
        "kge": float(round(compute_kge(obs_clean, sim_clean), 4)),
        "pbias": float(round(compute_pbias(obs_clean, sim_clean), 2)),
        "rmse": float(round(compute_rmse(obs_clean, sim_clean), 4)),
        "r": float(round(float(np.corrcoef(obs_clean, sim_clean)[0, 1]), 4)),
        "n_valid": int(mask.sum()),
        "obs_mean": float(round(float(np.mean(obs_clean)), 4)),
        "sim_mean": float(round(float(np.mean(sim_clean)), 4)),
    }


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------

def read_qout_netcdf(filepath, reach_id=None):
    """
    Read RAPID Qout NetCDF.
    Returns (times, riv_ids, data) where data shape is (n_time, n_riv) or (n_time,).
    """
    ds = nc.Dataset(filepath, "r")

    # Read river IDs
    riv_ids = ds.variables["rivid"][:]

    # Read time
    time_var = ds.variables["time"]
    times = nc.num2date(time_var[:], time_var.units,
                        time_var.calendar if hasattr(time_var, "calendar") else "standard")

    # Read discharge
    qout = ds.variables["Qout"][:]

    ds.close()

    if reach_id is not None:
        idx = np.where(riv_ids == reach_id)[0]
        if len(idx) == 0:
            print(f"ERROR: reach_id {reach_id} not found in Qout file", file=sys.stderr)
            print(f"Available IDs (first 10): {riv_ids[:10]}", file=sys.stderr)
            sys.exit(1)
        return times, reach_id, qout[:, idx[0]]

    return times, riv_ids, qout


def read_obs_netcdf(filepath, reach_id):
    """Read observed discharge from NetCDF (same format as Qout or Qobs)."""
    ds = nc.Dataset(filepath, "r")

    # Try different variable names
    for var_name in ["Qobs", "Qout", "discharge", "streamflow"]:
        if var_name in ds.variables:
            break
    else:
        available = list(ds.variables.keys())
        ds.close()
        raise KeyError(f"No discharge variable found in {filepath}. Available: {available}")

    riv_ids = ds.variables["rivid"][:]
    time_var = ds.variables["time"]
    times = nc.num2date(time_var[:], time_var.units,
                        time_var.calendar if hasattr(time_var, "calendar") else "standard")
    data = ds.variables[var_name][:]
    ds.close()

    idx = np.where(riv_ids == reach_id)[0]
    if len(idx) == 0:
        raise ValueError(f"reach_id {reach_id} not in observation file")

    return times, data[:, idx[0]]


def write_csv(filepath, times, sim, obs=None):
    """Write time series to CSV."""
    os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
    with open(filepath, "w") as f:
        if obs is not None:
            f.write("time,simulated_m3s,observed_m3s\n")
            for t, s, o in zip(times, sim, obs):
                f.write(f"{t},{s:.4f},{o:.4f}\n")
        else:
            f.write("time,simulated_m3s\n")
            for t, s in zip(times, sim):
                f.write(f"{t},{s:.4f}\n")
    print(f"Wrote CSV to {filepath}")


def plot_hydrograph(filepath, times, sim, obs=None, metrics=None, reach_id=None):
    """Generate hydrograph plot with optional observed comparison."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
    except ImportError:
        print("WARNING: matplotlib not available, skipping plot", file=sys.stderr)
        return

    fig, ax = plt.subplots(figsize=(12, 5))

    # Convert times to matplotlib dates
    time_dates = [datetime(t.year, t.month, t.day, t.hour, t.minute, t.second)
                  if hasattr(t, 'year') else t for t in times]

    if obs is not None:
        ax.plot(time_dates, obs, color="black", linewidth=1.0, label="Observed", alpha=0.8)

    ax.plot(time_dates, sim, color="#2563EB", linewidth=1.0, label="RAPID simulated", alpha=0.9)

    ax.set_xlabel("Time")
    ax.set_ylabel("Discharge (m³/s)")
    title = "RAPID Discharge"
    if reach_id:
        title += f" — Reach {reach_id}"
    ax.set_title(title)
    ax.legend(loc="upper left")
    ax.grid(True, alpha=0.3)

    # Format x-axis
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    fig.autofmt_xdate()

    # Metrics box
    if metrics and "nse" in metrics:
        text = (f"NSE = {metrics['nse']:.3f}\n"
                f"KGE = {metrics['kge']:.3f}\n"
                f"PBIAS = {metrics['pbias']:.1f}%\n"
                f"r = {metrics['r']:.3f}")
        ax.text(0.98, 0.95, text, transform=ax.transAxes, fontsize=9,
                verticalalignment="top", horizontalalignment="right",
                bbox=dict(boxstyle="round,pad=0.4", facecolor="white", alpha=0.8))

    os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
    fig.savefig(filepath, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved figure to {filepath}")


# ---------------------------------------------------------------------------
# Summary statistics (no observations needed)
# ---------------------------------------------------------------------------

def compute_summary(times, qout_data, riv_ids):
    """Compute summary statistics for all reaches."""
    n_time, n_riv = qout_data.shape

    peak_q = np.nanmax(qout_data, axis=0)
    mean_q = np.nanmean(qout_data, axis=0)

    # Find top 10 reaches by peak discharge
    top_idx = np.argsort(peak_q)[-10:][::-1]

    top_reaches = []
    for i in top_idx:
        top_reaches.append({
            "reach_id": int(riv_ids[i]),
            "peak_q_m3s": round(float(peak_q[i]), 2),
            "mean_q_m3s": round(float(mean_q[i]), 4),
        })

    return {
        "n_time_steps": n_time,
        "n_reaches": n_riv,
        "global_peak_m3s": round(float(np.nanmax(qout_data)), 2),
        "global_mean_m3s": round(float(np.nanmean(qout_data)), 4),
        "zero_reaches": int(np.sum(peak_q == 0)),
        "top_10_reaches": top_reaches,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def process(args):
    """Main pipeline: read → compute → write → validate."""
    # Read simulated output
    if args.reach_id:
        times, rid, sim = read_qout_netcdf(args.qout_file, args.reach_id)
        print(f"Read {len(sim)} time steps for reach {rid}")
    else:
        times, riv_ids, qout_all = read_qout_netcdf(args.qout_file)
        summary = compute_summary(times, qout_all, riv_ids)
        print(json.dumps(summary, indent=2))
        return summary

    result = {"reach_id": args.reach_id, "n_time_steps": len(sim)}

    # Compare with observations if available
    if args.obs_file:
        obs_times, obs = read_obs_netcdf(args.obs_file, args.reach_id)

        # Align time series (simple: assume same time steps)
        n = min(len(sim), len(obs))
        sim_aligned = sim[:n]
        obs_aligned = obs[:n]
        times_aligned = times[:n]

        metrics = compute_all_metrics(obs_aligned, sim_aligned)
        result["metrics"] = metrics
        validate_outputs(metrics)

        if args.output_csv:
            write_csv(args.output_csv, times_aligned, sim_aligned, obs_aligned)

        if args.figure:
            plot_hydrograph(args.figure, times_aligned, sim_aligned, obs_aligned,
                            metrics, args.reach_id)
    else:
        if args.output_csv:
            write_csv(args.output_csv, times, sim)

        if args.figure:
            plot_hydrograph(args.figure, times, sim, reach_id=args.reach_id)

    if args.output_json:
        os.makedirs(os.path.dirname(os.path.abspath(args.output_json)), exist_ok=True)
        with open(args.output_json, "w") as f:
            json.dump(result, f, indent=2)
        print(f"Wrote metrics to {args.output_json}")

    print(json.dumps(result, indent=2, default=str))
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Parse RAPID Qout NetCDF, compute metrics, generate plots")
    parser.add_argument("--qout_file", required=True, help="RAPID Qout NetCDF file")
    parser.add_argument("--obs_file", default=None, help="Observed discharge NetCDF")
    parser.add_argument("--reach_id", type=int, default=None,
                        help="Specific reach ID to extract (omit for summary of all)")
    parser.add_argument("--output_csv", default=None, help="Output CSV path")
    parser.add_argument("--output_json", default=None, help="Output metrics JSON path")
    parser.add_argument("--figure", default=None, help="Output hydrograph PNG path")
    args = parser.parse_args()

    validate_inputs(args)
    process(args)


if __name__ == "__main__":
    main()
