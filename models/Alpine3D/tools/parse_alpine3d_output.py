#!/usr/bin/env python3
"""
parse_alpine3d_output.py — Parse Alpine3D gridded output to CSV time series.

Reads ARC ASCII grid files produced by Alpine3D (one file per timestep per parameter)
and extracts time series at specific points or computes domain-wide statistics.

Output formats:
  - CSV time series at specific pixel coordinates
  - CSV domain statistics (mean, min, max, std per timestep)
  - CSV basin-integrated values (e.g., total SWE volume)

Alpine3D grid filename convention:
  YYYYMMDDHHMI_PARAM.asc  (e.g., 201412231200_SWE.asc)

Usage:
    # Extract time series at a specific pixel
    python parse_alpine3d_output.py \\
        --grid-dir ./output/grids/ \\
        --params SWE HS TA \\
        --output results.csv \\
        --mode point --row 40 --col 50

    # Domain statistics
    python parse_alpine3d_output.py \\
        --grid-dir ./output/grids/ \\
        --params SWE HS \\
        --output domain_stats.csv \\
        --mode domain

    # Basin-integrated SWE volume
    python parse_alpine3d_output.py \\
        --grid-dir ./output/grids/ \\
        --params SWE \\
        --output basin_swe.csv \\
        --mode basin --cellsize 25
"""

import argparse
import csv
import glob
import json
import os
import re
import sys
from datetime import datetime


def validate_inputs(args):
    """Validate command-line arguments."""
    errors = []

    if not os.path.exists(args.grid_dir):
        errors.append(f"Grid directory not found: {args.grid_dir}")

    if not args.params:
        errors.append("At least one parameter must be specified (--params)")

    if args.mode == "point":
        if args.row is None or args.col is None:
            errors.append("Point mode requires --row and --col")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)


def parse_timestamp_from_filename(filename):
    """Extract timestamp from Alpine3D grid filename.

    Expected format: YYYYMMDDHHMI_PARAM.asc
    Example: 201412231200_SWE.asc → 2014-12-23T12:00
    """
    basename = os.path.basename(filename)
    match = re.match(r"(\d{12})_(\w+)\.asc", basename)
    if match:
        ts_str = match.group(1)
        param = match.group(2)
        try:
            dt = datetime.strptime(ts_str, "%Y%m%d%H%M")
            return dt.strftime("%Y-%m-%dT%H:%M"), param
        except ValueError:
            return None, None
    return None, None


def read_arc_grid(filepath):
    """Read an ARC ASCII grid file. Returns header dict and 2D data array."""
    header = {}
    data = []

    with open(filepath, "r") as f:
        # Read header lines
        for _ in range(6):
            line = f.readline().strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 2:
                key = parts[0].lower()
                try:
                    header[key] = int(parts[1])
                except ValueError:
                    header[key] = float(parts[1])

        # Read data
        for line in f:
            line = line.strip()
            if line:
                row = []
                for val in line.split():
                    try:
                        row.append(float(val))
                    except ValueError:
                        row.append(None)
                data.append(row)

    return header, data


def compute_domain_stats(data, nodata=-9999):
    """Compute domain-wide statistics from a 2D grid."""
    valid_values = []
    for row in data:
        for val in row:
            if val is not None and val != nodata and abs(val - nodata) > 0.1:
                valid_values.append(val)

    if not valid_values:
        return {"mean": None, "min": None, "max": None, "std": None, "n_valid": 0}

    n = len(valid_values)
    mean_val = sum(valid_values) / n
    min_val = min(valid_values)
    max_val = max(valid_values)

    # Standard deviation
    if n > 1:
        variance = sum((x - mean_val) ** 2 for x in valid_values) / (n - 1)
        std_val = variance ** 0.5
    else:
        std_val = 0.0

    return {
        "mean": round(mean_val, 6),
        "min": round(min_val, 6),
        "max": round(max_val, 6),
        "std": round(std_val, 6),
        "n_valid": n,
    }


def compute_basin_integral(data, cellsize, nodata=-9999):
    """Compute basin-integrated value (sum × cell_area)."""
    cell_area = cellsize * cellsize  # m²
    total = 0.0
    n_valid = 0

    for row in data:
        for val in row:
            if val is not None and val != nodata and abs(val - nodata) > 0.1:
                total += val * cell_area
                n_valid += 1

    return {
        "total": round(total, 2),
        "mean": round(total / n_valid, 6) if n_valid > 0 else None,
        "n_valid": n_valid,
        "total_area_km2": round(n_valid * cell_area / 1e6, 3),
    }


def discover_grid_files(grid_dir, params):
    """Discover all grid files for the requested parameters."""
    files_by_time = {}

    for param in params:
        pattern = os.path.join(grid_dir, f"*_{param}.asc")
        matches = sorted(glob.glob(pattern))

        for fpath in matches:
            timestamp, file_param = parse_timestamp_from_filename(fpath)
            if timestamp and file_param == param:
                if timestamp not in files_by_time:
                    files_by_time[timestamp] = {}
                files_by_time[timestamp][param] = fpath

    return files_by_time


def process_point_mode(files_by_time, params, row, col, nodata=-9999):
    """Extract time series at a specific grid cell."""
    records = []

    for timestamp in sorted(files_by_time.keys()):
        record = {"timestamp": timestamp}
        for param in params:
            if param in files_by_time[timestamp]:
                header, data = read_arc_grid(files_by_time[timestamp][param])
                if row < len(data) and col < len(data[row]):
                    val = data[row][col]
                    if val is not None and abs(val - nodata) > 0.1:
                        record[param] = val
                    else:
                        record[param] = None
                else:
                    record[param] = None
            else:
                record[param] = None
        records.append(record)

    return records


def process_domain_mode(files_by_time, params, nodata=-9999):
    """Compute domain statistics for each timestep."""
    records = []

    for timestamp in sorted(files_by_time.keys()):
        record = {"timestamp": timestamp}
        for param in params:
            if param in files_by_time[timestamp]:
                header, data = read_arc_grid(files_by_time[timestamp][param])
                nodata_val = header.get("nodata_value", nodata)
                stats = compute_domain_stats(data, nodata=nodata_val)
                record[f"{param}_mean"] = stats["mean"]
                record[f"{param}_min"] = stats["min"]
                record[f"{param}_max"] = stats["max"]
                record[f"{param}_std"] = stats["std"]
                record[f"{param}_n"] = stats["n_valid"]
        records.append(record)

    return records


def process_basin_mode(files_by_time, params, cellsize, nodata=-9999):
    """Compute basin-integrated values for each timestep."""
    records = []

    for timestamp in sorted(files_by_time.keys()):
        record = {"timestamp": timestamp}
        for param in params:
            if param in files_by_time[timestamp]:
                header, data = read_arc_grid(files_by_time[timestamp][param])
                nodata_val = header.get("nodata_value", nodata)
                cs = cellsize if cellsize else header.get("cellsize", 25)
                basin = compute_basin_integral(data, cs, nodata=nodata_val)
                record[f"{param}_total"] = basin["total"]
                record[f"{param}_mean"] = basin["mean"]
                record[f"{param}_area_km2"] = basin["total_area_km2"]
        records.append(record)

    return records


def write_csv(filepath, records):
    """Write records to CSV file."""
    if not records:
        return

    fieldnames = list(records[0].keys())
    os.makedirs(os.path.dirname(filepath) if os.path.dirname(filepath) else ".", exist_ok=True)

    with open(filepath, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)


def validate_output(records, params):
    """Validate output for physical plausibility."""
    warnings = []

    if not records:
        warnings.append("No data records found")
        return warnings

    for param in params:
        vals = []
        for r in records:
            v = r.get(param) or r.get(f"{param}_mean")
            if v is not None:
                vals.append(v)

        if not vals:
            warnings.append(f"No valid data for parameter {param}")
            continue

        if param == "SWE":
            if max(vals) > 5000:
                warnings.append(f"SWE max={max(vals):.0f} kg/m² seems too high")
        elif param == "HS":
            if max(vals) > 20:
                warnings.append(f"HS max={max(vals):.1f} m seems too high")
        elif param == "TA":
            if min(vals) < 200 or max(vals) > 340:
                warnings.append(f"TA range [{min(vals):.0f}, {max(vals):.0f}] K seems wrong")

    return warnings


def process(args):
    """Main processing."""
    params = args.params

    # Discover grid files
    files_by_time = discover_grid_files(args.grid_dir, params)

    if not files_by_time:
        return {
            "status": "error",
            "errors": [f"No grid files found for params {params} in {args.grid_dir}"],
        }

    # Process based on mode
    if args.mode == "point":
        records = process_point_mode(files_by_time, params, args.row, args.col)
    elif args.mode == "domain":
        records = process_domain_mode(files_by_time, params)
    elif args.mode == "basin":
        records = process_basin_mode(files_by_time, params, args.cellsize)
    else:
        return {"status": "error", "errors": [f"Unknown mode: {args.mode}"]}

    # Validate output
    warnings = validate_output(records, params)
    for w in warnings:
        print(f"WARNING: {w}", file=sys.stderr)

    # Write CSV
    write_csv(args.output, records)

    return {
        "status": "success",
        "output": args.output,
        "n_timesteps": len(records),
        "n_params": len(params),
        "params": params,
        "time_range": [records[0]["timestamp"], records[-1]["timestamp"]] if records else [],
        "warnings": warnings,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Parse Alpine3D gridded output to CSV",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--grid-dir", required=True,
                        help="Directory containing ARC grid output files")
    parser.add_argument("--params", nargs="+", required=True,
                        help="Parameters to extract (e.g., SWE HS TA)")
    parser.add_argument("--output", required=True, help="Output CSV file path")
    parser.add_argument("--mode", default="domain",
                        choices=["point", "domain", "basin"],
                        help="Extraction mode (default: domain)")
    parser.add_argument("--row", type=int, default=None,
                        help="Grid row for point mode")
    parser.add_argument("--col", type=int, default=None,
                        help="Grid column for point mode")
    parser.add_argument("--cellsize", type=float, default=None,
                        help="Cell size in meters for basin integration")

    args = parser.parse_args()

    validate_inputs(args)
    result = process(args)

    print(json.dumps(result, indent=2))

    if result.get("status") == "error":
        sys.exit(1)


if __name__ == "__main__":
    main()
