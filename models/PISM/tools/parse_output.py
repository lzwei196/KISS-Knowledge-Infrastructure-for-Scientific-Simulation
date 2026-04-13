#!/usr/bin/env python3
"""
parse_output.py — Extract PISM output variables to CSV for analysis and validation.

Reads PISM NetCDF output files (main output, scalar time series, spatial diagnostics)
and extracts requested variables into CSV format. Supports both scalar (time series)
and spatial (point extraction, transect, spatial mean) modes.

Usage:
    # Extract scalar time series
    python parse_output.py \\
        --input scalar_output.nc \\
        --mode scalar \\
        --variables ice_volume_glacierized,ice_area_glacierized,max_hor_vel \\
        --output timeseries.csv

    # Extract spatial field at final time step
    python parse_output.py \\
        --input output.nc \\
        --mode spatial \\
        --variables thk,usurf,velsurf_mag \\
        --output spatial.csv

    # Extract point time series
    python parse_output.py \\
        --input spatial_output.nc \\
        --mode point \\
        --variables thk,velsurf_mag \\
        --point-x -200000 --point-y -2500000 \\
        --output point_ts.csv
"""

import argparse
import csv
import json
import os
import sys

try:
    import numpy as np
    from netCDF4 import Dataset, num2date
except ImportError as e:
    print(json.dumps({
        "status": "error",
        "errors": [f"Missing dependency: {e}. Install with: pip install numpy netCDF4"]
    }))
    sys.exit(1)


def validate_inputs(args):
    """Validate input file and arguments."""
    errors = []

    if not os.path.isfile(args.input):
        errors.append(f"Input file not found: {args.input}")
    else:
        try:
            ds = Dataset(args.input, "r")
            available = list(ds.variables.keys())
            for vname in args.variables.split(","):
                vname = vname.strip()
                if vname and vname not in available:
                    errors.append(f"Variable '{vname}' not found. "
                                  f"Available: {available[:20]}...")
            ds.close()
        except Exception as e:
            errors.append(f"Cannot open input: {e}")

    if args.mode == "point":
        if args.point_x is None or args.point_y is None:
            errors.append("Point mode requires --point-x and --point-y")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}, indent=2))
        sys.exit(1)


def extract_scalar(ds, var_names):
    """Extract scalar time series variables."""
    rows = []
    headers = ["time"]

    # Get time
    time_var = None
    for tname in ["time", "t"]:
        if tname in ds.variables:
            time_var = ds.variables[tname]
            break

    if time_var is None:
        return headers, rows

    times = time_var[:]
    try:
        units = time_var.units
        calendar = getattr(time_var, "calendar", "365_day")
        dates = num2date(times, units, calendar)
        time_strs = [str(d) for d in dates]
    except Exception:
        time_strs = [str(t) for t in times]

    headers.extend(var_names)

    for i, t_str in enumerate(time_strs):
        row = [t_str]
        for vname in var_names:
            if vname in ds.variables:
                v = ds.variables[vname]
                try:
                    val = float(v[i]) if v.ndim >= 1 else float(v[:])
                    row.append(val)
                except Exception:
                    row.append(np.nan)
            else:
                row.append(np.nan)
        rows.append(row)

    return headers, rows


def extract_spatial(ds, var_names, time_index=-1):
    """Extract spatial fields at given time index, flattened to CSV."""
    rows = []

    # Get coordinates
    x_var = y_var = None
    for name in ["x", "x1"]:
        if name in ds.variables:
            x_var = ds.variables[name]
            break
    for name in ["y", "y1"]:
        if name in ds.variables:
            y_var = ds.variables[name]
            break

    if x_var is None or y_var is None:
        return ["error"], [["No spatial coordinates found"]]

    x_vals = x_var[:]
    y_vals = y_var[:]

    headers = ["x", "y"] + var_names

    for j in range(len(y_vals)):
        for i in range(len(x_vals)):
            row = [float(x_vals[i]), float(y_vals[j])]
            for vname in var_names:
                if vname in ds.variables:
                    v = ds.variables[vname]
                    try:
                        if v.ndim == 2:
                            val = float(v[j, i])
                        elif v.ndim == 3:
                            val = float(v[time_index, j, i])
                        elif v.ndim == 4:
                            val = float(v[time_index, -1, j, i])
                        else:
                            val = np.nan
                    except Exception:
                        val = np.nan
                    row.append(val)
                else:
                    row.append(np.nan)
            rows.append(row)

    return headers, rows


def extract_point(ds, var_names, point_x, point_y):
    """Extract time series at nearest grid point."""
    # Find nearest grid point
    x_var = y_var = None
    for name in ["x", "x1"]:
        if name in ds.variables:
            x_var = ds.variables[name]
            break
    for name in ["y", "y1"]:
        if name in ds.variables:
            y_var = ds.variables[name]
            break

    if x_var is None or y_var is None:
        return ["error"], [["No coordinates"]]

    x_vals = np.array(x_var[:])
    y_vals = np.array(y_var[:])
    ix = int(np.argmin(np.abs(x_vals - point_x)))
    iy = int(np.argmin(np.abs(y_vals - point_y)))

    # Get time
    time_var = None
    for tname in ["time", "t"]:
        if tname in ds.variables:
            time_var = ds.variables[tname]
            break

    headers = ["time", "x_actual", "y_actual"] + var_names
    rows = []

    if time_var is None:
        return headers, rows

    times = time_var[:]
    for ti in range(len(times)):
        row = [float(times[ti]), float(x_vals[ix]), float(y_vals[iy])]
        for vname in var_names:
            if vname in ds.variables:
                v = ds.variables[vname]
                try:
                    if v.ndim == 3:
                        val = float(v[ti, iy, ix])
                    elif v.ndim == 4:
                        val = float(v[ti, -1, iy, ix])
                    else:
                        val = np.nan
                except Exception:
                    val = np.nan
                row.append(val)
            else:
                row.append(np.nan)
        rows.append(row)

    return headers, rows


def extract_summary(ds, var_names):
    """Extract spatial summary statistics over time."""
    time_var = None
    for tname in ["time", "t"]:
        if tname in ds.variables:
            time_var = ds.variables[tname]
            break

    headers = ["time"]
    for vname in var_names:
        headers.extend([f"{vname}_min", f"{vname}_max", f"{vname}_mean"])

    rows = []
    if time_var is None:
        return headers, rows

    times = time_var[:]
    for ti in range(len(times)):
        row = [float(times[ti])]
        for vname in var_names:
            if vname in ds.variables:
                v = ds.variables[vname]
                try:
                    if v.ndim == 3:
                        data = v[ti, :, :]
                    elif v.ndim == 2:
                        data = v[:, :]
                    else:
                        data = v[:]
                    arr = np.ma.filled(data, np.nan) if hasattr(data, "filled") else data
                    row.extend([
                        float(np.nanmin(arr)),
                        float(np.nanmax(arr)),
                        float(np.nanmean(arr)),
                    ])
                except Exception:
                    row.extend([np.nan, np.nan, np.nan])
            else:
                row.extend([np.nan, np.nan, np.nan])
        rows.append(row)

    return headers, rows


def process(args):
    """Main extraction logic."""
    ds = Dataset(args.input, "r")
    var_names = [v.strip() for v in args.variables.split(",") if v.strip()]
    warnings = []

    if args.mode == "scalar":
        headers, rows = extract_scalar(ds, var_names)
    elif args.mode == "spatial":
        headers, rows = extract_spatial(ds, var_names, args.time_index)
    elif args.mode == "point":
        headers, rows = extract_point(ds, var_names, args.point_x, args.point_y)
    elif args.mode == "summary":
        headers, rows = extract_summary(ds, var_names)
    else:
        ds.close()
        return {"status": "error", "errors": [f"Unknown mode: {args.mode}"]}

    ds.close()

    # Write CSV
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)

    return {
        "status": "success",
        "output_file": args.output,
        "mode": args.mode,
        "variables": var_names,
        "n_rows": len(rows),
        "n_columns": len(headers),
        "headers": headers,
        "warnings": warnings,
    }


def validate_outputs(result):
    """Verify the output CSV."""
    if result["status"] != "success":
        return result

    output_file = result["output_file"]
    if not os.path.isfile(output_file):
        result["warnings"].append("Output CSV file not created")
        return result

    size_bytes = os.path.getsize(output_file)
    if size_bytes == 0:
        result["warnings"].append("Output CSV is empty")
    result["output_size_bytes"] = size_bytes

    return result


def main():
    parser = argparse.ArgumentParser(description="Extract PISM output to CSV")
    parser.add_argument("--input", required=True, help="Input PISM NetCDF file")
    parser.add_argument("--output", required=True, help="Output CSV file")
    parser.add_argument("--variables", required=True,
                        help="Comma-separated variable names")
    parser.add_argument("--mode", default="scalar",
                        choices=["scalar", "spatial", "point", "summary"],
                        help="Extraction mode")
    parser.add_argument("--time-index", type=int, default=-1,
                        help="Time index for spatial extraction")
    parser.add_argument("--point-x", type=float, default=None,
                        help="X coordinate for point extraction (m)")
    parser.add_argument("--point-y", type=float, default=None,
                        help="Y coordinate for point extraction (m)")
    parser.add_argument("--output-json", default=None,
                        help="Write result JSON to file")

    args = parser.parse_args()
    validate_inputs(args)
    result = process(args)
    result = validate_outputs(result)

    output_json = json.dumps(result, indent=2)
    if args.output_json:
        os.makedirs(os.path.dirname(args.output_json) or ".", exist_ok=True)
        with open(args.output_json, "w") as f:
            f.write(output_json)
    print(output_json)


if __name__ == "__main__":
    main()
