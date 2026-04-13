#!/usr/bin/env python3
"""
parse_cwatm_output.py — Extract CWatM results from NetCDF outputs to CSV/analysis format.

CWatM produces:
  - NetCDF time series at gauge locations (discharge, ET, runoff, etc.)
  - NetCDF gridded maps (spatial variables at different temporal aggregations)
  - TSS text files (legacy format)

This tool:
  1. Reads discharge/state variable NetCDFs from the output directory
  2. Extracts time series at specified gauge locations
  3. Computes summary statistics and hydrological metrics
  4. Exports to CSV for analysis

Usage:
    python parse_cwatm_output.py \\
        --output_dir /path/to/cwatm/output/ \\
        --variable discharge \\
        --gauge_index 0 \\
        --csv_out discharge_timeseries.csv

    python parse_cwatm_output.py \\
        --output_dir /path/to/cwatm/output/ \\
        --variable discharge \\
        --all_gauges \\
        --csv_out all_gauges.csv \\
        --compute_metrics \\
        --observed_csv /path/to/observed.csv

    python parse_cwatm_output.py \\
        --output_dir /path/to/cwatm/output/ \\
        --summary \\
        --csv_out summary.csv
"""

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timedelta

import numpy as np

try:
    import netCDF4 as nc
except ImportError:
    nc = None


def validate_inputs(args):
    """Validate input arguments."""
    errors = []

    if not os.path.isdir(args.output_dir):
        errors.append(f"Output directory not found: {args.output_dir}")

    if nc is None:
        errors.append("netCDF4 package required. Install with: pip install netCDF4")

    if args.observed_csv and not os.path.isfile(args.observed_csv):
        errors.append(f"Observed data file not found: {args.observed_csv}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}, indent=2))
        sys.exit(1)


def find_output_files(output_dir):
    """Discover CWatM output files and their variables."""
    import glob

    files = {}
    for nc_path in sorted(glob.glob(os.path.join(output_dir, "*.nc"))):
        basename = os.path.basename(nc_path)
        try:
            ds = nc.Dataset(nc_path)
            variables = []
            for vname in ds.variables:
                if vname not in ("time", "lat", "lon", "latitude", "longitude", "x", "y"):
                    var = ds.variables[vname]
                    variables.append({
                        "name": vname,
                        "shape": list(var.shape),
                        "units": getattr(var, "units", "unknown"),
                        "long_name": getattr(var, "long_name", vname),
                    })
            has_time = "time" in ds.variables
            n_times = len(ds.variables["time"]) if has_time else 0
            ds.close()
            files[basename] = {
                "path": nc_path,
                "variables": variables,
                "n_timesteps": n_times,
            }
        except Exception as e:
            files[basename] = {"path": nc_path, "error": str(e)}

    return files


def extract_timeseries(nc_path, variable, gauge_index=0):
    """
    Extract time series from a CWatM output NetCDF.

    Returns
    -------
    dates : list of datetime
    values : np.ndarray
    metadata : dict
    """
    ds = nc.Dataset(nc_path)

    # Get time dimension
    if "time" not in ds.variables:
        ds.close()
        raise ValueError(f"No time dimension in {nc_path}")

    time_var = ds.variables["time"]
    times = nc.num2date(time_var[:], time_var.units,
                        getattr(time_var, "calendar", "standard"))

    # Find the data variable
    if variable not in ds.variables:
        # Try case-insensitive search
        found = None
        for vname in ds.variables:
            if vname.lower() == variable.lower():
                found = vname
                break
        if found is None:
            available = [v for v in ds.variables if v not in ("time", "lat", "lon")]
            ds.close()
            raise ValueError(
                f"Variable '{variable}' not found. Available: {available}"
            )
        variable = found

    data_var = ds.variables[variable]
    data = data_var[:]

    metadata = {
        "variable": variable,
        "units": getattr(data_var, "units", "unknown"),
        "long_name": getattr(data_var, "long_name", variable),
        "shape": list(data.shape),
    }

    # Extract based on dimensions
    if data.ndim == 1:
        # Single gauge time series
        values = data
    elif data.ndim == 2:
        # (time, gauge) — extract specific gauge
        if gauge_index >= data.shape[1]:
            ds.close()
            raise ValueError(
                f"Gauge index {gauge_index} out of range. "
                f"Available gauges: 0 to {data.shape[1]-1}"
            )
        values = data[:, gauge_index]
    elif data.ndim == 3:
        # (time, lat, lon) — spatial data, need coordinates
        values = data  # Return full spatial data
    else:
        values = data

    ds.close()

    dates = [datetime(t.year, t.month, t.day) if hasattr(t, "year") else t
             for t in times]
    return dates, np.array(values), metadata


def compute_hydrological_metrics(sim, obs, dates=None):
    """
    Compute standard hydrological performance metrics.

    Parameters
    ----------
    sim : np.ndarray
        Simulated values
    obs : np.ndarray
        Observed values
    dates : list of datetime, optional

    Returns
    -------
    dict with metrics: NSE, KGE, PBIAS, RMSE, R², MAE
    """
    # Remove NaN pairs
    mask = ~(np.isnan(sim) | np.isnan(obs))
    sim = sim[mask]
    obs = obs[mask]

    if len(sim) < 10:
        return {"error": f"Too few valid data points: {len(sim)}"}

    # Nash-Sutcliffe Efficiency
    nse = 1.0 - np.sum((sim - obs) ** 2) / np.sum((obs - np.mean(obs)) ** 2)

    # Kling-Gupta Efficiency
    r = np.corrcoef(sim, obs)[0, 1]
    alpha = np.std(sim) / np.std(obs)
    beta = np.mean(sim) / np.mean(obs)
    kge = 1.0 - np.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2)

    # Percent Bias
    pbias = 100.0 * np.sum(sim - obs) / np.sum(obs)

    # RMSE
    rmse = np.sqrt(np.mean((sim - obs) ** 2))

    # R-squared
    r2 = r ** 2

    # Mean Absolute Error
    mae = np.mean(np.abs(sim - obs))

    return {
        "NSE": round(float(nse), 4),
        "KGE": round(float(kge), 4),
        "PBIAS": round(float(pbias), 2),
        "RMSE": round(float(rmse), 4),
        "R2": round(float(r2), 4),
        "R": round(float(r), 4),
        "MAE": round(float(mae), 4),
        "mean_sim": round(float(np.mean(sim)), 4),
        "mean_obs": round(float(np.mean(obs)), 4),
        "n_points": int(len(sim)),
    }


def read_observed_csv(csv_path):
    """Read observed data from CSV. Expects columns: date, value."""
    dates = []
    values = []

    with open(csv_path, "r") as f:
        reader = csv.reader(f)
        header = next(reader)

        for row in reader:
            if len(row) >= 2:
                try:
                    # Try multiple date formats
                    date_str = row[0].strip()
                    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d", "%m/%d/%Y"):
                        try:
                            d = datetime.strptime(date_str, fmt)
                            break
                        except ValueError:
                            continue
                    else:
                        continue
                    val = float(row[1])
                    dates.append(d)
                    values.append(val)
                except (ValueError, IndexError):
                    continue

    return dates, np.array(values)


def write_csv(dates, values, output_path, variable="value", metadata=None):
    """Write time series to CSV."""
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)

        # Write header comment with metadata
        if metadata:
            f.write(f"# Variable: {metadata.get('variable', variable)}\n")
            f.write(f"# Units: {metadata.get('units', 'unknown')}\n")
            f.write(f"# Generated: {datetime.now().isoformat()}\n")

        writer.writerow(["date", variable])
        for date, val in zip(dates, values):
            date_str = date.strftime("%Y-%m-%d") if hasattr(date, "strftime") else str(date)
            writer.writerow([date_str, f"{val:.6f}"])

    return output_path


def validate_outputs(dates, values, variable):
    """Post-extraction validation."""
    warnings = []

    if len(values) == 0:
        warnings.append(f"No data extracted for variable '{variable}'")
        return warnings

    if np.all(np.isnan(values)):
        warnings.append(f"All NaN values for variable '{variable}'")

    if variable.lower() == "discharge":
        max_q = float(np.nanmax(values))
        min_q = float(np.nanmin(values))
        if max_q > 1e6:
            warnings.append(
                f"UNIT TRAP: Max discharge = {max_q:.1f} m³/s — extremely high. "
                f"Check precipitation unit conversion."
            )
        if min_q < -0.01:
            warnings.append(f"Negative discharge: min = {min_q:.4f} m³/s")
        if max_q == 0:
            warnings.append("All discharge values are 0. Model may not be generating runoff.")

    return warnings


def main():
    parser = argparse.ArgumentParser(description="Parse CWatM output files")
    parser.add_argument("--output_dir", required=True, help="CWatM output directory")
    parser.add_argument("--variable", default="discharge", help="Variable to extract")
    parser.add_argument("--gauge_index", type=int, default=0, help="Gauge index (0-based)")
    parser.add_argument("--all_gauges", action="store_true", help="Extract all gauges")
    parser.add_argument("--csv_out", default=None, help="Output CSV path")
    parser.add_argument("--summary", action="store_true", help="Print summary of all outputs")
    parser.add_argument("--compute_metrics", action="store_true", help="Compute NSE/KGE metrics")
    parser.add_argument("--observed_csv", default=None, help="Observed data CSV for metrics")

    args = parser.parse_args()

    print("=== CWatM Output Parser ===")
    validate_inputs(args)

    # Summary mode
    if args.summary:
        files = find_output_files(args.output_dir)
        print(f"\nFound {len(files)} output files:")
        for fname, info in files.items():
            if "error" in info:
                print(f"  {fname}: ERROR - {info['error']}")
            else:
                vars_str = ", ".join(v["name"] for v in info["variables"])
                print(f"  {fname}: {info['n_timesteps']} timesteps, vars: [{vars_str}]")
        print(json.dumps(files, indent=2, default=str))
        return

    # Find the output file containing our variable
    files = find_output_files(args.output_dir)
    target_file = None
    for fname, info in files.items():
        if "variables" in info:
            for v in info["variables"]:
                if v["name"].lower() == args.variable.lower() or \
                   args.variable.lower() in v["name"].lower():
                    target_file = info["path"]
                    break
        if target_file:
            break

    if target_file is None:
        # Try the most likely filename
        import glob
        candidates = glob.glob(
            os.path.join(args.output_dir, f"*{args.variable}*.nc")
        )
        if candidates:
            target_file = candidates[0]
        else:
            print(f"ERROR: Cannot find output file containing variable '{args.variable}'")
            print(f"Available files: {list(files.keys())}")
            sys.exit(1)

    print(f"Reading from: {target_file}")

    # Extract time series
    dates, values, metadata = extract_timeseries(
        target_file, args.variable, args.gauge_index
    )

    if values.ndim > 1:
        print(f"Spatial data extracted: shape = {values.shape}")
        print(f"Use --gauge_index to extract a point time series")
        return

    # Validate extracted data
    warnings = validate_outputs(dates, values, args.variable)
    for w in warnings:
        print(f"  WARNING: {w}")

    # Print statistics
    print(f"\n  Variable: {metadata['variable']} [{metadata['units']}]")
    print(f"  Period: {dates[0]} to {dates[-1]} ({len(dates)} timesteps)")
    print(f"  Min: {np.nanmin(values):.4f}")
    print(f"  Max: {np.nanmax(values):.4f}")
    print(f"  Mean: {np.nanmean(values):.4f}")

    # Write CSV
    if args.csv_out:
        write_csv(dates, values, args.csv_out, args.variable, metadata)
        print(f"\n  CSV written to: {args.csv_out}")

    # Compute metrics against observed data
    if args.compute_metrics and args.observed_csv:
        obs_dates, obs_values = read_observed_csv(args.observed_csv)
        print(f"\n  Observed data: {len(obs_dates)} points from {args.observed_csv}")

        # Align dates
        sim_dict = {d.strftime("%Y-%m-%d"): v for d, v in zip(dates, values)}
        obs_dict = {d.strftime("%Y-%m-%d"): v for d, v in zip(obs_dates, obs_values)}
        common_dates = sorted(set(sim_dict.keys()) & set(obs_dict.keys()))

        if len(common_dates) < 10:
            print(f"  ERROR: Only {len(common_dates)} overlapping dates")
        else:
            sim_aligned = np.array([sim_dict[d] for d in common_dates])
            obs_aligned = np.array([obs_dict[d] for d in common_dates])

            metrics = compute_hydrological_metrics(sim_aligned, obs_aligned)
            print(f"\n  === Performance Metrics ({len(common_dates)} days) ===")
            for k, v in metrics.items():
                print(f"  {k}: {v}")

            print(json.dumps({"status": "success", "metrics": metrics}, indent=2))

    result = {
        "status": "success",
        "variable": metadata["variable"],
        "units": metadata["units"],
        "n_timesteps": len(dates),
        "min": float(np.nanmin(values)),
        "max": float(np.nanmax(values)),
        "mean": float(np.nanmean(values)),
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
