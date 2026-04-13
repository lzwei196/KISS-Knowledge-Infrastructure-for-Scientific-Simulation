#!/usr/bin/env python3
"""
parse_output.py — COAWST Output Parser and Metrics Calculator
==============================================================

Extracts time series and spatial fields from COAWST/ROMS NetCDF output
(history, average, station files) and computes validation metrics.

SUPPORTED OPERATIONS:
  - Extract variable time series at a point (lon, lat) or station index
  - Extract surface/bottom/depth-level 2D snapshots
  - Compute domain-averaged statistics
  - Compare to observations and compute metrics (RMSE, bias, correlation, skill)
  - Export to CSV for further analysis

OUTPUT UNITS (ROMS conventions):
  - Temperature: °C (NOT Kelvin)
  - Salinity: PSU (dimensionless)
  - Velocity: m/s
  - Sea level (zeta): m
  - Wave height (Hsig): m

Usage:
  # Extract SST time series at a point
  python3 parse_output.py \\
    --history sandy_his.nc \\
    --variable temp --level surface \\
    --lon -74.0 --lat 39.5 \\
    --output sst_timeseries.csv

  # Compare to observations
  python3 parse_output.py \\
    --history sandy_his.nc \\
    --variable zeta --level surface \\
    --station-index 0 \\
    --observations obs_waterlevel.csv \\
    --output comparison.csv --metrics

  # Domain-averaged SST
  python3 parse_output.py \\
    --history sandy_his.nc \\
    --variable temp --level surface \\
    --domain-average \\
    --output domain_sst.csv
"""

import argparse
import csv
import json
import os
import sys
from datetime import datetime

import numpy as np

try:
    import netCDF4 as nc
    HAS_NETCDF = True
except ImportError:
    HAS_NETCDF = False

try:
    import xarray as xr
    HAS_XARRAY = True
except ImportError:
    HAS_XARRAY = False


def validate_inputs(args):
    """Validate parser inputs."""
    errors = []
    warnings = []

    # Check input file
    input_file = args.history or args.station or args.average
    if not input_file:
        errors.append("Provide one of --history, --station, or --average")
    elif not os.path.exists(input_file):
        errors.append(f"Input file not found: {input_file}")

    if not HAS_NETCDF and not HAS_XARRAY:
        errors.append("netCDF4 or xarray required. pip install netCDF4 xarray")

    if args.observations and not os.path.exists(args.observations):
        errors.append(f"Observation file not found: {args.observations}")

    if args.level not in ("surface", "bottom", "all") and not args.level.replace(".", "").replace("-", "").isdigit():
        errors.append(f"Level must be 'surface', 'bottom', 'all', or a numeric depth. Got: {args.level}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors, "warnings": warnings}, indent=2))
        sys.exit(1)

    return warnings


def find_nearest_point(lon_grid, lat_grid, target_lon, target_lat):
    """Find nearest grid point indices to target coordinates."""
    dist = np.sqrt((lon_grid - target_lon)**2 + (lat_grid - target_lat)**2)
    idx = np.unravel_index(np.argmin(dist), dist.shape)
    return idx


def extract_time_variable(ds, time_var_name="ocean_time"):
    """Extract and convert time variable to datetime array."""
    possible_names = ["ocean_time", "time", "scrum_time"]
    time_var = None
    for name in possible_names:
        if name in ds.variables:
            time_var = ds.variables[name]
            break

    if time_var is None:
        return None, None

    times_raw = time_var[:]
    units = getattr(time_var, "units", "seconds since 2000-01-01")

    try:
        times = nc.num2date(times_raw, units, calendar="standard")
    except Exception:
        # Fallback: treat as seconds since epoch
        times = times_raw

    return times, times_raw


def extract_timeseries_at_point(ds, variable, level, j, i):
    """Extract time series of a variable at grid point (j, i)."""
    var = ds.variables[variable]
    dims = var.dimensions

    if len(dims) == 4:  # (time, s_rho, eta, xi) — 3D variable
        if level == "surface":
            data = var[:, -1, j, i]
        elif level == "bottom":
            data = var[:, 0, j, i]
        else:
            level_idx = int(float(level))
            data = var[:, level_idx, j, i]
    elif len(dims) == 3:  # (time, eta, xi) — 2D variable
        data = var[:, j, i]
    elif len(dims) == 2:  # (time, station) — station file
        data = var[:, i]
    else:
        raise ValueError(f"Unexpected dimensions for {variable}: {dims}")

    return np.array(data)


def extract_domain_average(ds, variable, level, mask=None):
    """Extract domain-averaged time series."""
    var = ds.variables[variable]
    dims = var.dimensions

    all_data = []
    nt = var.shape[0]

    for t in range(nt):
        if len(dims) == 4:
            if level == "surface":
                field = var[t, -1, :, :]
            elif level == "bottom":
                field = var[t, 0, :, :]
            else:
                field = var[t, int(float(level)), :, :]
        elif len(dims) == 3:
            field = var[t, :, :]
        else:
            field = var[t]

        field = np.array(field, dtype=float)
        if mask is not None:
            field[mask == 0] = np.nan

        all_data.append(np.nanmean(field))

    return np.array(all_data)


def compute_metrics(simulated, observed):
    """Compute validation metrics between simulated and observed time series.

    Returns dict with:
      - rmse: Root Mean Square Error
      - mae: Mean Absolute Error
      - bias: Mean bias (sim - obs)
      - correlation: Pearson correlation coefficient
      - skill: Willmott skill score (0-1)
      - nse: Nash-Sutcliffe Efficiency (-inf to 1)
    """
    # Ensure same length
    n = min(len(simulated), len(observed))
    sim = np.array(simulated[:n], dtype=float)
    obs = np.array(observed[:n], dtype=float)

    # Remove NaN pairs
    valid = ~(np.isnan(sim) | np.isnan(obs))
    sim = sim[valid]
    obs = obs[valid]

    if len(sim) < 2:
        return {"error": "Fewer than 2 valid data points for comparison"}

    diff = sim - obs

    # RMSE
    rmse = np.sqrt(np.mean(diff**2))

    # MAE
    mae = np.mean(np.abs(diff))

    # Bias
    bias = np.mean(diff)

    # Correlation
    if np.std(sim) > 0 and np.std(obs) > 0:
        correlation = np.corrcoef(sim, obs)[0, 1]
    else:
        correlation = 0.0

    # Nash-Sutcliffe Efficiency
    ss_res = np.sum(diff**2)
    ss_tot = np.sum((obs - np.mean(obs))**2)
    nse = 1.0 - ss_res / max(ss_tot, 1e-10)

    # Willmott Skill Score
    obs_mean = np.mean(obs)
    denom = np.sum((np.abs(sim - obs_mean) + np.abs(obs - obs_mean))**2)
    skill = 1.0 - ss_res / max(denom, 1e-10)

    return {
        "rmse": round(float(rmse), 6),
        "mae": round(float(mae), 6),
        "bias": round(float(bias), 6),
        "correlation": round(float(correlation), 6),
        "nse": round(float(nse), 6),
        "skill": round(float(skill), 6),
        "n_points": int(len(sim)),
    }


def read_observations(obs_path):
    """Read observation CSV (columns: time, value)."""
    times = []
    values = []

    with open(obs_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Try common column names
            for time_key in ["time", "datetime", "date", "timestamp"]:
                if time_key in row:
                    times.append(row[time_key])
                    break
            for val_key in ["value", "observed", "obs", "measurement"]:
                if val_key in row:
                    try:
                        values.append(float(row[val_key]))
                    except ValueError:
                        values.append(np.nan)
                    break

    return times, np.array(values)


def write_csv(output_path, times, data, variable_name, metrics=None):
    """Write time series to CSV."""
    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)

        # Header
        header = ["time", variable_name]
        if metrics:
            header.append("observed")
        writer.writerow(header)

        # Data
        for i in range(len(data)):
            row = [str(times[i]) if i < len(times) else "", f"{data[i]:.6f}"]
            writer.writerow(row)

        # Metrics as comment rows
        if metrics:
            writer.writerow([])
            writer.writerow(["# Metrics"])
            for key, val in metrics.items():
                writer.writerow([f"# {key}", val])

    return output_path


def process(args, warnings):
    """Main extraction and analysis process."""
    input_file = args.history or args.station or args.average

    print(f"  Opening: {input_file}", file=sys.stderr)
    ds = nc.Dataset(input_file)

    # Check variable exists
    if args.variable not in ds.variables:
        available = [v for v in ds.variables if not v.startswith("_")]
        ds.close()
        return {
            "status": "error",
            "errors": [f"Variable '{args.variable}' not found. Available: {available[:20]}"],
        }

    # Extract time
    times, times_raw = extract_time_variable(ds)

    # Extract data
    if args.domain_average:
        # Domain average
        mask = ds.variables["mask_rho"][:] if "mask_rho" in ds.variables else None
        data = extract_domain_average(ds, args.variable, args.level, mask)
        print(f"  Domain average: {args.variable}, n_times={len(data)}", file=sys.stderr)
    elif args.station_index is not None:
        # Station extraction
        data = extract_timeseries_at_point(ds, args.variable, args.level, 0, args.station_index)
        print(f"  Station {args.station_index}: {args.variable}, n_times={len(data)}", file=sys.stderr)
    elif args.lon is not None and args.lat is not None:
        # Point extraction
        lon_rho = ds.variables["lon_rho"][:] if "lon_rho" in ds.variables else None
        lat_rho = ds.variables["lat_rho"][:] if "lat_rho" in ds.variables else None

        if lon_rho is None or lat_rho is None:
            ds.close()
            return {"status": "error", "errors": ["Grid coordinates not found in output file"]}

        j, i = find_nearest_point(lon_rho, lat_rho, args.lon, args.lat)
        actual_lon = float(lon_rho[j, i])
        actual_lat = float(lat_rho[j, i])
        print(f"  Nearest point: ({actual_lon:.4f}, {actual_lat:.4f}) [j={j}, i={i}]", file=sys.stderr)

        data = extract_timeseries_at_point(ds, args.variable, args.level, j, i)
    else:
        ds.close()
        return {"status": "error", "errors": ["Specify --lon/--lat, --station-index, or --domain-average"]}

    ds.close()

    # Summary statistics
    stats = {
        "mean": round(float(np.nanmean(data)), 6),
        "std": round(float(np.nanstd(data)), 6),
        "min": round(float(np.nanmin(data)), 6),
        "max": round(float(np.nanmax(data)), 6),
        "n_valid": int(np.sum(~np.isnan(data))),
        "n_nan": int(np.sum(np.isnan(data))),
    }

    # Compare to observations if provided
    metrics = None
    if args.observations:
        obs_times, obs_values = read_observations(args.observations)
        metrics = compute_metrics(data, obs_values)
        print(f"  Metrics: RMSE={metrics.get('rmse')}, r={metrics.get('correlation')}, "
              f"NSE={metrics.get('nse')}", file=sys.stderr)

    # Write output CSV
    if args.output:
        time_strings = [str(t) for t in times] if times is not None else [str(i) for i in range(len(data))]
        write_csv(args.output, time_strings, data, args.variable, metrics)
        print(f"  Written: {args.output}", file=sys.stderr)

    result = {
        "status": "success",
        "variable": args.variable,
        "level": args.level,
        "n_timesteps": len(data),
        "statistics": stats,
        "output": args.output,
        "warnings": warnings,
    }

    if metrics:
        result["metrics"] = metrics

    return result


def validate_outputs(result):
    """Post-processing validation."""
    if result["status"] != "success":
        return result

    # Check for suspicious values
    stats = result.get("statistics", {})
    if stats.get("n_nan", 0) > stats.get("n_valid", 1) * 0.5:
        result["warnings"].append(
            f"More than 50% NaN values ({stats['n_nan']}/{stats['n_valid'] + stats['n_nan']}). "
            f"Check extraction point and variable level."
        )

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Parse COAWST/ROMS output NetCDF and compute metrics",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    # Input files (mutually exclusive)
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--history", help="ROMS history file")
    input_group.add_argument("--station", help="ROMS station file")
    input_group.add_argument("--average", help="ROMS average file")

    # Variable selection
    parser.add_argument("--variable", required=True, help="Variable name (temp, salt, zeta, u, v, etc.)")
    parser.add_argument("--level", default="surface",
                        help="Vertical level: 'surface', 'bottom', or integer index (default: surface)")

    # Point selection
    parser.add_argument("--lon", type=float, help="Longitude of extraction point")
    parser.add_argument("--lat", type=float, help="Latitude of extraction point")
    parser.add_argument("--station-index", type=int, help="Station index (for station files)")
    parser.add_argument("--domain-average", action="store_true", help="Compute domain average")

    # Comparison
    parser.add_argument("--observations", help="CSV with observed data (columns: time, value)")
    parser.add_argument("--metrics", action="store_true", help="Compute validation metrics")

    # Output
    parser.add_argument("--output", help="Output CSV file path")

    args = parser.parse_args()
    warnings = validate_inputs(args)
    result = process(args, warnings)
    result = validate_outputs(result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
