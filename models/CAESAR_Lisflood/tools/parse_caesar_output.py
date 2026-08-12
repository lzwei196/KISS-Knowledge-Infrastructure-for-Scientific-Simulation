#!/usr/bin/env python3
"""
Parse HAIL-CAESAR output files to extract timeseries and raster data.

Handles:
  - Timeseries file (catchment.dat): discharge, sediment flux by fraction
  - Raster outputs (.asc): water depth, elevation, grain size, elev diff
  - Converts time index to actual model minutes/hours
  - Exports to CSV for analysis

Output timeseries columns (from HAIL-CAESAR / CAESAR-Lisflood format):
  Col 1: Time index (row number at save interval)
  Col 2: Actual discharge (m3/s)
  Col 3: Expected discharge (m3/s, TOPMODEL)
  Col 4: Sand output (m3, legacy)
  Col 5: Total sediment Q (m3)
  Cols 6-14: Grain fraction sediment Q (m3 each, fractions 1-9)

Usage:
    python parse_caesar_output.py \\
        --timeseries_file results/catchment.dat \\
        --save_interval 5 \\
        --output_csv results/hydrograph.csv \\
        --raster_dir results/ \\
        --raster_prefix WaterDepths
"""

import argparse
import os
import sys
import numpy as np
from pathlib import Path


TIMESERIES_COLUMNS = [
    "time_index",
    "discharge_m3s",
    "expected_discharge_m3s",
    "sand_output_m3",
    "total_sediment_m3",
    "grain1_m3",
    "grain2_m3",
    "grain3_m3",
    "grain4_m3",
    "grain5_m3",
    "grain6_m3",
    "grain7_m3",
    "grain8_m3",
    "grain9_m3",
]


def validate_input(file_path: str) -> None:
    """Validate input file exists and is non-empty."""
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")
    if os.path.getsize(file_path) == 0:
        raise ValueError(f"File is empty: {file_path}")


def parse_timeseries(file_path: str, save_interval_min: float = 60) -> dict:
    """Parse HAIL-CAESAR timeseries output file.

    Args:
        file_path: Path to the timeseries .dat file
        save_interval_min: The timeseries_save_interval from params (minutes)

    Returns:
        Dict with arrays for each variable and computed time in minutes/hours.
    """
    validate_input(file_path)

    data = np.loadtxt(file_path)
    if data.ndim == 1:
        data = data.reshape(1, -1)

    n_rows, n_cols = data.shape
    print(f"Parsed timeseries: {n_rows} rows, {n_cols} columns")

    if n_cols < 5:
        raise ValueError(
            f"Expected at least 5 columns, got {n_cols}. "
            f"File may not be HAIL-CAESAR format."
        )

    result = {
        "time_index": data[:, 0],
        "time_minutes": data[:, 0] * save_interval_min,
        "time_hours": data[:, 0] * save_interval_min / 60.0,
        "discharge_m3s": data[:, 1],
        "expected_discharge_m3s": data[:, 2],
    }

    if n_cols >= 5:
        result["sand_output_m3"] = data[:, 3]
        result["total_sediment_m3"] = data[:, 4]

    if n_cols >= 14:
        for i in range(9):
            result[f"grain{i + 1}_m3"] = data[:, 5 + i]

    # Compute summary statistics
    q = result["discharge_m3s"]
    result["stats"] = {
        "peak_discharge_m3s": float(np.max(q)),
        "peak_time_hours": float(result["time_hours"][np.argmax(q)]),
        "mean_discharge_m3s": float(np.mean(q)),
        "total_volume_m3": float(
            (np.trapezoid if hasattr(np, "trapezoid") else np.trapz)(
                q, result["time_minutes"] * 60)),
        "n_timesteps": n_rows,
        "duration_hours": float(result["time_hours"][-1]),
    }

    if "total_sediment_m3" in result:
        sed = result["total_sediment_m3"]
        result["stats"]["total_sediment_m3"] = float(np.sum(sed))
        result["stats"]["peak_sediment_m3"] = float(np.max(sed))

    return result


def write_csv(output_path: str, data: dict) -> None:
    """Write parsed timeseries to CSV."""
    n = len(data["time_index"])

    # Determine which columns to write
    columns = ["time_index", "time_minutes", "time_hours", "discharge_m3s",
               "expected_discharge_m3s"]
    if "total_sediment_m3" in data:
        columns.extend(["sand_output_m3", "total_sediment_m3"])
    for i in range(1, 10):
        key = f"grain{i}_m3"
        if key in data:
            columns.append(key)

    with open(output_path, "w") as f:
        f.write(",".join(columns) + "\n")
        for row in range(n):
            values = []
            for col in columns:
                val = data[col][row]
                if col in ("time_index",):
                    values.append(f"{int(val)}")
                else:
                    values.append(f"{val:.6f}")
            f.write(",".join(values) + "\n")

    print(f"Written CSV: {output_path} ({n} rows, {len(columns)} columns)")


def parse_rasters(raster_dir: str, prefix: str, extension: str = "asc") -> list:
    """Find and summarize raster output files.

    Returns list of dicts with raster metadata and summary statistics.
    """
    import glob

    pattern = os.path.join(raster_dir, f"{prefix}*.{extension}")
    files = sorted(glob.glob(pattern))

    if not files:
        print(f"No raster files found matching: {pattern}")
        return []

    print(f"Found {len(files)} raster files matching {prefix}*.{extension}")

    summaries = []
    for fpath in files:
        summary = {"path": fpath, "filename": os.path.basename(fpath)}

        try:
            # Read ASCII header
            header = {}
            with open(fpath, "r") as f:
                for _ in range(6):
                    line = f.readline().strip()
                    parts = line.split()
                    if len(parts) == 2:
                        header[parts[0].lower()] = parts[1]

            ncols = int(header.get("ncols", 0))
            nrows = int(header.get("nrows", 0))
            nodata = float(header.get("nodata_value", -9999))

            # Read raster data (skip 6 header lines)
            data = np.loadtxt(fpath, skiprows=6)
            valid = data[data != nodata]

            summary.update({
                "ncols": ncols,
                "nrows": nrows,
                "min": float(np.min(valid)) if valid.size > 0 else None,
                "max": float(np.max(valid)) if valid.size > 0 else None,
                "mean": float(np.mean(valid)) if valid.size > 0 else None,
                "nonzero_cells": int(np.sum(valid > 0)),
                "total_cells": int(valid.size),
            })
        except Exception as e:
            summary["error"] = str(e)

        summaries.append(summary)

    return summaries


def write_raster_summary(output_path: str, summaries: list) -> None:
    """Write raster summary statistics to CSV."""
    if not summaries:
        return

    columns = ["filename", "ncols", "nrows", "min", "max", "mean",
               "nonzero_cells", "total_cells"]

    with open(output_path, "w") as f:
        f.write(",".join(columns) + "\n")
        for s in summaries:
            values = [str(s.get(c, "")) for c in columns]
            f.write(",".join(values) + "\n")

    print(f"Written raster summary: {output_path}")


def print_summary(data: dict) -> None:
    """Print summary statistics to console."""
    stats = data.get("stats", {})
    print("\n=== Timeseries Summary ===")
    print(f"Duration: {stats.get('duration_hours', 0):.1f} hours")
    print(f"Timesteps: {stats.get('n_timesteps', 0)}")
    print(f"Peak discharge: {stats.get('peak_discharge_m3s', 0):.4f} m3/s "
          f"at t={stats.get('peak_time_hours', 0):.1f} hours")
    print(f"Mean discharge: {stats.get('mean_discharge_m3s', 0):.4f} m3/s")
    print(f"Total volume: {stats.get('total_volume_m3', 0):.1f} m3")
    if "total_sediment_m3" in stats:
        print(f"Total sediment: {stats.get('total_sediment_m3', 0):.4f} m3")


def validate_output(output_path: str) -> None:
    """Validate the output CSV was written correctly."""
    if not os.path.isfile(output_path):
        raise RuntimeError(f"Output file not created: {output_path}")

    with open(output_path, "r") as f:
        header = f.readline()
        first_data = f.readline()

    if not header.strip():
        raise RuntimeError("Output CSV has no header")
    if not first_data.strip():
        raise RuntimeError("Output CSV has no data rows")

    n_cols = len(header.strip().split(","))
    n_vals = len(first_data.strip().split(","))
    if n_cols != n_vals:
        raise RuntimeError(f"Header has {n_cols} columns but data has {n_vals}")

    print(f"Output validation passed: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Parse HAIL-CAESAR output files")
    parser.add_argument("--timeseries_file", help="Path to timeseries output (.dat)")
    parser.add_argument("--save_interval", type=float, default=60,
                        help="timeseries_save_interval from params (minutes)")
    parser.add_argument("--output_csv", help="Output CSV path for timeseries")
    parser.add_argument("--raster_dir", help="Directory containing output rasters")
    parser.add_argument("--raster_prefix", default="WaterDepths",
                        help="Prefix for raster files to summarize")
    parser.add_argument("--raster_ext", default="asc",
                        help="Raster file extension")
    parser.add_argument("--raster_summary_csv", help="Output CSV for raster summaries")

    args = parser.parse_args()

    if not args.timeseries_file and not args.raster_dir:
        parser.error("Specify at least --timeseries_file or --raster_dir")

    # Parse timeseries
    if args.timeseries_file:
        data = parse_timeseries(args.timeseries_file, args.save_interval)
        print_summary(data)

        if args.output_csv:
            os.makedirs(os.path.dirname(os.path.abspath(args.output_csv)), exist_ok=True)
            write_csv(args.output_csv, data)
            validate_output(args.output_csv)

    # Parse rasters
    if args.raster_dir:
        summaries = parse_rasters(args.raster_dir, args.raster_prefix, args.raster_ext)
        if summaries and args.raster_summary_csv:
            write_raster_summary(args.raster_summary_csv, summaries)

    print("\nDone.")


if __name__ == "__main__":
    main()
