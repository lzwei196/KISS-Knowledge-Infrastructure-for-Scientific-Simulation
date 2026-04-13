#!/usr/bin/env python3
"""
parse_ef5_output.py — Parse EF5 output time series and compute performance metrics.

EF5 outputs:
  - Gauge time series files: CSV with datetime, simulated streamflow (m^3/s)
  - Gridded output files: GeoTIFF grids of streamflow, soil moisture, etc.

This tool:
  1. Reads EF5 gauge time series output
  2. Optionally reads observed data for comparison
  3. Computes hydrologic performance metrics (NSE, KGE, PBIAS, R, RMSE)
  4. Exports merged observed+simulated CSV
  5. Generates diagnostic plots

Pipeline: validate inputs → read sim data → read obs data → compute metrics → export → validate
"""

import argparse
import csv
import math
import os
import sys
from datetime import datetime
from pathlib import Path

import numpy as np


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
def compute_nse(obs, sim):
    """Nash-Sutcliffe Efficiency. Perfect=1, poor<0."""
    obs_mean = np.mean(obs)
    numerator = np.sum((obs - sim) ** 2)
    denominator = np.sum((obs - obs_mean) ** 2)
    if denominator == 0:
        return float("nan")
    return 1.0 - numerator / denominator


def compute_kge(obs, sim):
    """Kling-Gupta Efficiency. Perfect=1."""
    r = np.corrcoef(obs, sim)[0, 1]
    alpha = np.std(sim) / np.std(obs) if np.std(obs) > 0 else float("nan")
    beta = np.mean(sim) / np.mean(obs) if np.mean(obs) > 0 else float("nan")
    kge = 1.0 - math.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2)
    return kge


def compute_pbias(obs, sim):
    """Percent bias. 0=perfect, positive=overestimation."""
    obs_sum = np.sum(obs)
    if obs_sum == 0:
        return float("nan")
    return 100.0 * np.sum(sim - obs) / obs_sum


def compute_rmse(obs, sim):
    """Root Mean Squared Error."""
    return math.sqrt(np.mean((obs - sim) ** 2))


def compute_r(obs, sim):
    """Pearson correlation coefficient."""
    if len(obs) < 2:
        return float("nan")
    return np.corrcoef(obs, sim)[0, 1]


def compute_all_metrics(obs, sim):
    """Compute all standard hydrologic metrics."""
    mask = ~(np.isnan(obs) | np.isnan(sim))
    obs_clean = obs[mask]
    sim_clean = sim[mask]

    if len(obs_clean) < 5:
        return {"n_valid": len(obs_clean), "error": "Insufficient valid data pairs"}

    return {
        "n_valid": int(len(obs_clean)),
        "nse": round(compute_nse(obs_clean, sim_clean), 4),
        "kge": round(compute_kge(obs_clean, sim_clean), 4),
        "pbias": round(compute_pbias(obs_clean, sim_clean), 2),
        "rmse": round(compute_rmse(obs_clean, sim_clean), 4),
        "r": round(compute_r(obs_clean, sim_clean), 4),
        "obs_mean": round(float(np.mean(obs_clean)), 4),
        "sim_mean": round(float(np.mean(sim_clean)), 4),
        "obs_max": round(float(np.max(obs_clean)), 4),
        "sim_max": round(float(np.max(sim_clean)), 4),
    }


# ---------------------------------------------------------------------------
# I/O: Read EF5 output time series
# ---------------------------------------------------------------------------
def read_ef5_timeseries(filepath):
    """
    Read EF5 gauge output time series.

    EF5 outputs CSV in format: YYYY/MM/DD HH:UU:SS,value
    Returns list of (datetime, float) tuples.
    """
    data = []
    with open(filepath, "r") as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) < 2:
                continue
            try:
                # Try EF5 date format
                dt_str = row[0].strip()
                for fmt in [
                    "%Y/%m/%d %H:%M:%S",
                    "%Y/%m/%d %H:%M",
                    "%Y-%m-%d %H:%M:%S",
                    "%Y-%m-%d %H:%M",
                    "%Y%m%d%H%M%S",
                    "%Y%m%d%H%M",
                ]:
                    try:
                        dt = datetime.strptime(dt_str, fmt)
                        break
                    except ValueError:
                        continue
                else:
                    continue

                val = float(row[1].strip())
                data.append((dt, val))
            except (ValueError, IndexError):
                continue

    return data


def read_observed_timeseries(filepath):
    """
    Read observed streamflow time series (same CSV format).

    Returns list of (datetime, float) tuples.
    """
    return read_ef5_timeseries(filepath)


# ---------------------------------------------------------------------------
# Merge and align
# ---------------------------------------------------------------------------
def align_timeseries(sim_data, obs_data, tolerance_seconds=1800):
    """
    Align simulated and observed time series by datetime matching.

    Parameters
    ----------
    sim_data : list of (datetime, float) — simulated
    obs_data : list of (datetime, float) — observed
    tolerance_seconds : int — max time difference for matching

    Returns
    -------
    times : list[datetime]
    obs_vals : np.ndarray
    sim_vals : np.ndarray
    """
    obs_dict = {}
    for dt, val in obs_data:
        obs_dict[dt] = val

    times = []
    obs_vals = []
    sim_vals = []

    for dt_sim, val_sim in sim_data:
        # Exact match first
        if dt_sim in obs_dict:
            times.append(dt_sim)
            obs_vals.append(obs_dict[dt_sim])
            sim_vals.append(val_sim)
        else:
            # Try nearest within tolerance
            best_dt = None
            best_diff = tolerance_seconds + 1
            for dt_obs in obs_dict:
                diff = abs((dt_sim - dt_obs).total_seconds())
                if diff < best_diff:
                    best_diff = diff
                    best_dt = dt_obs
            if best_dt and best_diff <= tolerance_seconds:
                times.append(dt_sim)
                obs_vals.append(obs_dict[best_dt])
                sim_vals.append(val_sim)

    return times, np.array(obs_vals), np.array(sim_vals)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def validate_inputs(sim_path, obs_path=None):
    """Validate input file paths."""
    errors = []
    if not os.path.isfile(sim_path):
        errors.append(f"Simulated data file not found: {sim_path}")
    if obs_path and not os.path.isfile(obs_path):
        errors.append(f"Observed data file not found: {obs_path}")
    if errors:
        for e in errors:
            print(f"[ERROR] {e}", file=sys.stderr)
        return False
    return True


def validate_outputs(output_csv, metrics):
    """Validate outputs are reasonable."""
    if not os.path.isfile(output_csv):
        print(f"[ERROR] Output CSV not created: {output_csv}", file=sys.stderr)
        return False

    if "nse" in metrics:
        nse = metrics["nse"]
        if nse < -10:
            print(f"[WARNING] NSE = {nse} — very poor fit, check units and parameters", file=sys.stderr)
        elif nse > 0.5:
            print(f"[OK] NSE = {nse} — acceptable to good fit")
        else:
            print(f"[INFO] NSE = {nse} — marginal fit, calibration may be needed")

    return True


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------
def export_csv(times, obs_vals, sim_vals, output_path):
    """Export merged observed+simulated time series to CSV."""
    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["datetime", "observed_cms", "simulated_cms"])
        for t, o, s in zip(times, obs_vals, sim_vals):
            writer.writerow([t.strftime("%Y-%m-%d %H:%M:%S"), f"{o:.4f}", f"{s:.4f}"])
    print(f"[OK] Exported {len(times)} records to {output_path}")


def plot_timeseries(times, obs_vals, sim_vals, metrics, output_path):
    """Generate comparison plot with metrics box."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates

        fig, ax = plt.subplots(figsize=(12, 5))
        ax.plot(times, obs_vals, color="black", linewidth=0.8, label="Observed")
        ax.plot(times, sim_vals, color="#2563EB", linewidth=0.8, label="Simulated", alpha=0.85)
        ax.set_xlabel("Date")
        ax.set_ylabel("Streamflow (m³/s)")
        ax.set_title("EF5 Simulation vs Observed")
        ax.legend(loc="upper left")

        # Metrics box
        metrics_text = "\n".join([
            f"NSE = {metrics.get('nse', 'N/A')}",
            f"KGE = {metrics.get('kge', 'N/A')}",
            f"PBIAS = {metrics.get('pbias', 'N/A')}%",
            f"R = {metrics.get('r', 'N/A')}",
            f"N = {metrics.get('n_valid', 'N/A')}",
        ])
        props = dict(boxstyle="round", facecolor="wheat", alpha=0.8)
        ax.text(0.98, 0.95, metrics_text, transform=ax.transAxes,
                verticalalignment="top", horizontalalignment="right",
                bbox=props, fontsize=9, family="monospace")

        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
        fig.autofmt_xdate()
        plt.tight_layout()
        plt.savefig(output_path, dpi=150)
        plt.close()
        print(f"[OK] Plot saved to {output_path}")
    except ImportError:
        print("[WARNING] matplotlib not available, skipping plot", file=sys.stderr)


# ---------------------------------------------------------------------------
# Gridded output parsing
# ---------------------------------------------------------------------------
def list_gridded_outputs(output_dir):
    """List all gridded output files from EF5 run."""
    patterns = ["*.tif", "*.asc", "*.bif"]
    files = []
    for pat in patterns:
        files.extend(sorted(Path(output_dir).glob(pat)))
    return files


def extract_grid_stats(grid_path):
    """Extract basic statistics from a gridded output file."""
    try:
        from osgeo import gdal
        ds = gdal.Open(str(grid_path))
        if ds:
            band = ds.GetRasterBand(1)
            data = band.ReadAsArray().astype(np.float64)
            nd = band.GetNoDataValue()
            if nd is not None:
                data[data == nd] = np.nan
            valid = data[~np.isnan(data)]
            ds = None
            if len(valid) > 0:
                return {
                    "file": str(grid_path),
                    "min": float(np.min(valid)),
                    "max": float(np.max(valid)),
                    "mean": float(np.mean(valid)),
                    "std": float(np.std(valid)),
                    "n_valid": int(len(valid)),
                }
    except ImportError:
        pass
    return {"file": str(grid_path), "error": "GDAL not available"}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def parse_output(sim_path, obs_path=None, output_dir=".", plot=True):
    """
    Parse EF5 output and compute metrics.

    Parameters
    ----------
    sim_path : str — Path to simulated time series CSV
    obs_path : str — Path to observed time series CSV (optional)
    output_dir : str — Directory for output files
    plot : bool — Generate comparison plot
    """
    if not validate_inputs(sim_path, obs_path):
        return None

    os.makedirs(output_dir, exist_ok=True)

    # Read simulated data
    sim_data = read_ef5_timeseries(sim_path)
    print(f"Read {len(sim_data)} simulated timesteps from {sim_path}")

    if not sim_data:
        print("[ERROR] No data found in simulated file", file=sys.stderr)
        return None

    if obs_path:
        # Read observed data
        obs_data = read_observed_timeseries(obs_path)
        print(f"Read {len(obs_data)} observed timesteps from {obs_path}")

        # Align
        times, obs_vals, sim_vals = align_timeseries(sim_data, obs_data)
        print(f"Aligned: {len(times)} matched timesteps")

        # Compute metrics
        metrics = compute_all_metrics(obs_vals, sim_vals)
        print("\n--- Performance Metrics ---")
        for k, v in metrics.items():
            print(f"  {k}: {v}")

        # Export
        csv_path = os.path.join(output_dir, "comparison.csv")
        export_csv(times, obs_vals, sim_vals, csv_path)

        # Plot
        if plot and len(times) > 0:
            plot_path = os.path.join(output_dir, "comparison.png")
            plot_timeseries(times, obs_vals, sim_vals, metrics, plot_path)

        # Validate
        validate_outputs(csv_path, metrics)
        return metrics
    else:
        # No obs — just export sim data
        csv_path = os.path.join(output_dir, "simulated.csv")
        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["datetime", "simulated_cms"])
            for dt, val in sim_data:
                writer.writerow([dt.strftime("%Y-%m-%d %H:%M:%S"), f"{val:.4f}"])
        print(f"[OK] Exported {len(sim_data)} simulated records to {csv_path}")
        return {"n_timesteps": len(sim_data)}


def main():
    parser = argparse.ArgumentParser(description="Parse EF5 output and compute metrics")
    parser.add_argument("--sim", required=True, help="Simulated time series CSV")
    parser.add_argument("--obs", help="Observed time series CSV")
    parser.add_argument("--output-dir", default=".", help="Output directory")
    parser.add_argument("--no-plot", action="store_true", help="Skip plotting")
    parser.add_argument("--grid-dir", help="Directory with gridded outputs to summarize")
    args = parser.parse_args()

    metrics = parse_output(args.sim, args.obs, args.output_dir, not args.no_plot)

    if args.grid_dir:
        grids = list_gridded_outputs(args.grid_dir)
        if grids:
            print(f"\n--- Gridded Output Summary ({len(grids)} files) ---")
            for g in grids[:10]:
                stats = extract_grid_stats(g)
                if "error" not in stats:
                    print(f"  {g.name}: [{stats['min']:.2f}, {stats['max']:.2f}], mean={stats['mean']:.2f}")

    if metrics:
        import json
        metrics_path = os.path.join(args.output_dir, "metrics.json")
        with open(metrics_path, "w") as f:
            json.dump(metrics, f, indent=2)
        print(f"\n[OK] Metrics saved to {metrics_path}")

    sys.exit(0)


if __name__ == "__main__":
    main()
