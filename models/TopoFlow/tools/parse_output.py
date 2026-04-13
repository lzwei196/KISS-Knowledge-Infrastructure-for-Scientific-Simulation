#!/usr/bin/env python3
"""
parse_output.py — Parse TopoFlow output files to CSV and summary metrics.

Reads:
  - *_0D-Q.txt          Outlet discharge time series (m³/s)
  - *_0D-d.txt          Outlet depth time series (m)
  - *_0D-u.txt          Outlet velocity time series (m/s)
  - *_2D-Q.nc           Spatiotemporal discharge grids
  - *_report.txt        Run summary report

Outputs:
  - hydrograph.csv      Time, Q_m3s, depth_m, velocity_ms
  - summary.json        Peak Q, time to peak, total volume, mass balance
  - grid_max_Q.csv      Maximum Q at each grid cell (if 2D output available)

Usage:
  python parse_output.py \\
    --output_dir /path/to/model_output/ \\
    --prefix June_20_67 \\
    --dt 6.0 \\
    --save_dir ./parsed_results/
"""

import argparse
import csv
import json
import os
import sys
from pathlib import Path

import numpy as np


def validate_inputs(output_dir, prefix, dt):
    """Validate inputs before parsing.

    Returns (errors, warnings).
    """
    errors = []
    warnings = []

    if not os.path.isdir(output_dir):
        errors.append(f"Output directory does not exist: {output_dir}")
        return errors, warnings

    # Check for at least one output file
    out_path = Path(output_dir)
    q_files = list(out_path.rglob(f"*0D-Q*"))
    nc_files = list(out_path.rglob("*.nc"))
    report_files = list(out_path.rglob("*report*"))

    if not q_files and not nc_files:
        errors.append("No TopoFlow output files found (*_0D-Q* or *.nc)")

    if not q_files:
        warnings.append("No outlet discharge file found; hydrograph CSV will be empty.")

    if dt <= 0:
        errors.append(f"Timestep dt must be positive, got {dt}")

    return errors, warnings


def read_0d_timeseries(output_dir, prefix, var_suffix, dt):
    """Read a 0-D (pixel) time-series text file.

    Parameters
    ----------
    output_dir : str
    prefix : str
    var_suffix : str
        e.g. "Q", "d", "u"
    dt : float
        Timestep in seconds for generating time axis.

    Returns
    -------
    time_s : np.ndarray
        Time in seconds.
    values : np.ndarray
        Variable values.
    """
    # Search for the file with flexible naming
    patterns = [
        f"{prefix}_0D-{var_suffix}.txt",
        f"{prefix}_0D-{var_suffix}.csv",
        f"*_0D-{var_suffix}.txt",
        f"*0D-{var_suffix}*",
    ]

    filepath = None
    out_path = Path(output_dir)
    for pat in patterns:
        candidates = list(out_path.rglob(pat))
        if candidates:
            filepath = str(candidates[0])
            break

    if filepath is None:
        return None, None

    try:
        data = np.loadtxt(filepath)
        if data.ndim == 0:
            data = np.array([float(data)])

        # If multi-column, first col may be time
        if data.ndim == 2:
            if data.shape[1] >= 2:
                return data[:, 0], data[:, 1]
            else:
                data = data[:, 0]

        # Single column — generate time axis
        n = len(data)
        time_s = np.arange(n) * dt
        return time_s, data

    except Exception as e:
        print(f"WARNING: Failed to read {filepath}: {e}", file=sys.stderr)
        return None, None


def read_netcdf_grid(output_dir, prefix, var_suffix):
    """Read 2-D NetCDF grid stack and extract max values.

    Returns (max_grid, time_of_max) or (None, None).
    """
    try:
        import netCDF4 as nc
    except ImportError:
        return None, None

    patterns = [f"{prefix}_2D-{var_suffix}.nc", f"*2D-{var_suffix}*.nc"]
    filepath = None
    for pat in patterns:
        candidates = list(Path(output_dir).rglob(pat))
        if candidates:
            filepath = str(candidates[0])
            break

    if filepath is None:
        return None, None

    try:
        ds = nc.Dataset(filepath, "r")
        # Find the main data variable
        var_names = [v for v in ds.variables if v not in ("time", "x", "y", "lat", "lon")]
        if not var_names:
            ds.close()
            return None, None

        data = ds.variables[var_names[0]][:]  # shape: (time, nrows, ncols)
        ds.close()

        if data.ndim == 3:
            max_grid = np.max(data, axis=0)
            time_of_max = np.argmax(data, axis=0)
            return max_grid, time_of_max
        return None, None
    except Exception as e:
        print(f"WARNING: Failed to read NetCDF {filepath}: {e}", file=sys.stderr)
        return None, None


def compute_metrics(time_s, q_m3s, dt, observed=None):
    """Compute hydrologic summary metrics.

    Parameters
    ----------
    time_s : np.ndarray
    q_m3s : np.ndarray
    dt : float
    observed : np.ndarray, optional
        Observed discharge for comparison metrics.

    Returns
    -------
    metrics : dict
    """
    metrics = {}

    if q_m3s is None or len(q_m3s) == 0:
        return {"error": "No discharge data available"}

    metrics["Q_peak_m3s"] = float(np.max(q_m3s))
    metrics["Q_min_m3s"] = float(np.min(q_m3s))
    metrics["Q_mean_m3s"] = float(np.mean(q_m3s))

    peak_idx = int(np.argmax(q_m3s))
    metrics["T_peak_seconds"] = float(time_s[peak_idx])
    metrics["T_peak_minutes"] = float(time_s[peak_idx] / 60.0)
    metrics["T_peak_hours"] = float(time_s[peak_idx] / 3600.0)

    # Total volume via trapezoidal integration
    total_vol = float(np.trapz(q_m3s, time_s))
    metrics["total_volume_m3"] = total_vol

    # Duration
    metrics["simulation_duration_s"] = float(time_s[-1] - time_s[0])
    metrics["n_timesteps"] = len(q_m3s)

    # Rising and recession limbs
    if peak_idx > 0:
        metrics["rising_limb_duration_min"] = float(time_s[peak_idx] / 60.0)
    if peak_idx < len(q_m3s) - 1:
        metrics["recession_limb_duration_min"] = float(
            (time_s[-1] - time_s[peak_idx]) / 60.0
        )

    # Comparison metrics (if observed data provided)
    if observed is not None and len(observed) == len(q_m3s):
        obs = np.array(observed)
        sim = np.array(q_m3s)

        # Nash-Sutcliffe Efficiency
        ss_res = np.sum((obs - sim) ** 2)
        ss_tot = np.sum((obs - np.mean(obs)) ** 2)
        if ss_tot > 0:
            metrics["NSE"] = float(1.0 - ss_res / ss_tot)

        # Kling-Gupta Efficiency
        r = float(np.corrcoef(obs, sim)[0, 1]) if np.std(obs) > 0 and np.std(sim) > 0 else 0.0
        alpha = float(np.std(sim) / np.std(obs)) if np.std(obs) > 0 else 1.0
        beta = float(np.mean(sim) / np.mean(obs)) if np.mean(obs) > 0 else 1.0
        metrics["KGE"] = float(1.0 - np.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2))
        metrics["r"] = r

        # Percent Bias
        if np.sum(obs) > 0:
            metrics["PBIAS_pct"] = float(100.0 * np.sum(sim - obs) / np.sum(obs))

        # RMSE
        metrics["RMSE_m3s"] = float(np.sqrt(np.mean((obs - sim) ** 2)))

    return metrics


def write_hydrograph_csv(time_s, q_m3s, depth_m, velocity_ms, save_dir, prefix):
    """Write hydrograph CSV.

    Returns path to the written file.
    """
    filepath = os.path.join(save_dir, f"{prefix}_hydrograph.csv")
    n = len(time_s)

    with open(filepath, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["time_s", "time_min", "Q_m3s", "depth_m", "velocity_ms"])
        for i in range(n):
            row = [
                f"{time_s[i]:.1f}",
                f"{time_s[i] / 60.0:.2f}",
                f"{q_m3s[i]:.6f}" if q_m3s is not None and i < len(q_m3s) else "",
                f"{depth_m[i]:.6f}" if depth_m is not None and i < len(depth_m) else "",
                f"{velocity_ms[i]:.6f}" if velocity_ms is not None and i < len(velocity_ms) else "",
            ]
            writer.writerow(row)

    return filepath


def write_grid_max_csv(max_grid, save_dir, prefix, var_name="Q"):
    """Write max-over-time grid to CSV.

    Returns path.
    """
    if max_grid is None:
        return None
    filepath = os.path.join(save_dir, f"{prefix}_grid_max_{var_name}.csv")
    np.savetxt(filepath, max_grid, delimiter=",", fmt="%.6f")
    return filepath


def process(output_dir, prefix, dt, save_dir, observed_file=None):
    """Main processing pipeline.

    Returns result dict.
    """
    os.makedirs(save_dir, exist_ok=True)

    # Read time series
    time_q, q_m3s = read_0d_timeseries(output_dir, prefix, "Q", dt)
    time_d, depth_m = read_0d_timeseries(output_dir, prefix, "d", dt)
    time_u, velocity_ms = read_0d_timeseries(output_dir, prefix, "u", dt)

    files_written = {}

    # Write hydrograph CSV
    if time_q is not None:
        csv_path = write_hydrograph_csv(
            time_q, q_m3s, depth_m, velocity_ms, save_dir, prefix
        )
        files_written["hydrograph_csv"] = csv_path

    # Read observed data if provided
    observed = None
    if observed_file and os.path.exists(observed_file):
        try:
            obs_data = np.loadtxt(observed_file)
            if obs_data.ndim == 2:
                observed = obs_data[:, 1]  # assume col 0 is time
            else:
                observed = obs_data
        except Exception as e:
            print(f"WARNING: Could not read observed file: {e}", file=sys.stderr)

    # Compute metrics
    metrics = compute_metrics(time_q, q_m3s, dt, observed)

    # Write summary JSON
    summary_path = os.path.join(save_dir, f"{prefix}_summary.json")
    with open(summary_path, "w") as f:
        json.dump(metrics, f, indent=2)
    files_written["summary_json"] = summary_path

    # Read 2D grids
    max_q_grid, _ = read_netcdf_grid(output_dir, prefix, "Q")
    if max_q_grid is not None:
        grid_path = write_grid_max_csv(max_q_grid, save_dir, prefix, "Q")
        files_written["grid_max_Q_csv"] = grid_path

    return {
        "status": "success",
        "metrics": metrics,
        "files_written": files_written,
        "n_timesteps": len(time_q) if time_q is not None else 0,
    }


def validate_outputs(result):
    """Post-processing validation.

    Returns (errors, warnings).
    """
    errors = []
    warnings = []

    metrics = result.get("metrics", {})

    if "error" in metrics:
        errors.append(metrics["error"])
        return errors, warnings

    q_peak = metrics.get("Q_peak_m3s", 0)
    if q_peak <= 0:
        warnings.append("Peak Q is zero — model may not have produced any flow.")
    if q_peak > 1e6:
        warnings.append(
            f"Peak Q = {q_peak:.0f} m³/s — extremely large. "
            "Verify precipitation units are mm/hr not m/s."
        )

    nse = metrics.get("NSE")
    if nse is not None and nse < 0:
        warnings.append(
            f"NSE = {nse:.3f} (negative). Model is worse than mean-observed."
        )

    return errors, warnings


def main():
    parser = argparse.ArgumentParser(description="Parse TopoFlow output to CSV and metrics")
    parser.add_argument("--output_dir", required=True, help="TopoFlow output directory")
    parser.add_argument("--prefix", required=True, help="Case prefix for output files")
    parser.add_argument("--dt", type=float, default=6.0, help="Timestep in seconds")
    parser.add_argument("--save_dir", default="./parsed_results/", help="Where to save parsed output")
    parser.add_argument("--observed", default=None, help="Path to observed discharge file")

    args = parser.parse_args()

    errors, warnings = validate_inputs(args.output_dir, args.prefix, args.dt)
    for w in warnings:
        print(f"WARNING: {w}", file=sys.stderr)
    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)

    result = process(args.output_dir, args.prefix, args.dt, args.save_dir, args.observed)

    out_errors, out_warnings = validate_outputs(result)
    result["output_warnings"] = out_warnings
    if out_errors:
        result["output_errors"] = out_errors

    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
