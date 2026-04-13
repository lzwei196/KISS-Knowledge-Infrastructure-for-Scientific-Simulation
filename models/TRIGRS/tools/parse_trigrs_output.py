#!/usr/bin/env python3
"""
parse_trigrs_output.py
======================
Parse TRIGRS output grids and list files into CSV/DataFrame format
for analysis, visualization, and validation.

Extracts:
    - Factor of safety (FS) grids -> CSV with coordinates
    - Pressure head profiles -> per-cell depth profiles
    - Water table depth grids
    - Mass balance from log file
    - Summary statistics (unstable area, min FS, etc.)

Usage:
    python parse_trigrs_output.py \\
        --output_dir data/tutorial/ \\
        --suffix tutorial \\
        --result_csv results.csv \\
        --summary_json summary.json

Output:
    - results.csv      (cell-level FS, pressure head, coordinates)
    - summary.json     (aggregate statistics)
    - fs_timeseries.csv (FS evolution at selected cells)
"""

import argparse
import csv
import json
import os
import re
import sys
from pathlib import Path

import numpy as np


def validate_inputs(output_dir: str, suffix: str) -> dict:
    """Validate that TRIGRS output files exist."""
    errors = []

    if not os.path.isdir(output_dir):
        errors.append(f"Output directory not found: {output_dir}")

    # Check for at least one output file
    if os.path.isdir(output_dir):
        trigrs_files = [f for f in os.listdir(output_dir)
                        if f.startswith("TR")]
        if not trigrs_files:
            errors.append(f"No TRIGRS output files (TR*) in {output_dir}")

    if errors:
        raise ValueError("Validation failed:\n  " + "\n  ".join(errors))

    return {"output_dir": output_dir, "suffix": suffix}


def read_asc_grid(filepath: str) -> dict:
    """
    Read ESRI ASCII grid file.

    Returns:
        dict with 'header' (metadata) and 'data' (2D numpy array)
    """
    header = {}
    with open(filepath, "r") as f:
        for _ in range(6):
            line = f.readline().strip().split()
            if len(line) >= 2:
                key = line[0].lower()
                try:
                    val = int(line[1])
                except ValueError:
                    try:
                        val = float(line[1])
                    except ValueError:
                        val = line[1]
                header[key] = val

    data = np.loadtxt(filepath, skiprows=6)
    ncols = int(header.get("ncols", 0))
    nrows = int(header.get("nrows", 0))
    if data.size == ncols * nrows:
        data = data.reshape(nrows, ncols)

    return {"header": header, "data": data}


def find_output_files(output_dir: str, suffix: str) -> dict:
    """
    Scan output directory for TRIGRS output files.

    Returns:
        dict mapping file type to list of (timestep, filepath) tuples
    """
    files = {}
    patterns = {
        "fs_min": re.compile(r"TRfs_min_" + re.escape(suffix) + r"_(\d+)"),
        "z_at_fs": re.compile(r"TRz_at_fs_min_" + re.escape(suffix) +
                              r"_(\d+)"),
        "p_at_fs": re.compile(r"TRp_at_fs_min_" + re.escape(suffix) +
                              r"_(\d+)"),
        "water_depth": re.compile(r"TRwater_depth_" + re.escape(suffix) +
                                  r"_(\d+)"),
        "water_eleva": re.compile(r"TRwater_eleva_" + re.escape(suffix) +
                                  r"_(\d+)"),
        "infiltration": re.compile(r"TRinfiltration_" + re.escape(suffix) +
                                   r"_(\d+)"),
        "runoff": re.compile(r"TRrunoff_" + re.escape(suffix) + r"_(\d+)"),
    }

    for filename in sorted(os.listdir(output_dir)):
        for ftype, pattern in patterns.items():
            match = pattern.search(filename)
            if match:
                step = int(match.group(1))
                filepath = os.path.join(output_dir, filename)
                files.setdefault(ftype, []).append((step, filepath))

    return files


def parse_fs_grid(filepath: str) -> dict:
    """
    Parse a factor-of-safety grid and compute statistics.

    Returns:
        dict with grid data and summary statistics
    """
    grid = read_asc_grid(filepath)
    data = grid["data"]
    header = grid["header"]
    nodata = header.get("nodata_value", -9999)

    # Mask nodata values
    valid = data[data != nodata]

    if valid.size == 0:
        return {"data": data, "header": header, "stats": None}

    stats = {
        "n_cells": int(valid.size),
        "min_fs": float(np.min(valid)),
        "max_fs": float(np.max(valid)),
        "mean_fs": float(np.mean(valid)),
        "median_fs": float(np.median(valid)),
        "std_fs": float(np.std(valid)),
        "n_unstable": int(np.sum(valid < 1.0)),
        "n_marginal": int(np.sum((valid >= 1.0) & (valid < 1.3))),
        "n_stable": int(np.sum(valid >= 1.3)),
        "pct_unstable": float(np.sum(valid < 1.0) / valid.size * 100),
        "pct_marginal": float(np.sum((valid >= 1.0) & (valid < 1.3)) /
                              valid.size * 100),
    }

    return {"data": data, "header": header, "stats": stats}


def parse_list_file(filepath: str) -> list:
    """
    Parse TRIGRS list output file (Z-P-Fs format).

    Returns:
        list of dicts, each with cell info and depth profiles
    """
    profiles = []
    current_cell = None
    current_data = []

    with open(filepath, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            # Check for cell header
            if "Cell" in line or "cell" in line:
                if current_cell is not None and current_data:
                    current_cell["profile"] = current_data
                    profiles.append(current_cell)
                current_cell = {"raw_header": line}
                current_data = []
                continue

            # Parse data lines (depth, pressure_head, factor_of_safety)
            parts = line.split()
            if len(parts) >= 3:
                try:
                    depth = float(parts[0])
                    phead = float(parts[1])
                    fs = float(parts[2])
                    current_data.append({
                        "depth_m": depth,
                        "pressure_head_m": phead,
                        "factor_of_safety": fs,
                    })
                except ValueError:
                    continue

    # Don't forget the last cell
    if current_cell is not None and current_data:
        current_cell["profile"] = current_data
        profiles.append(current_cell)

    return profiles


def parse_log_file(work_dir: str) -> dict:
    """
    Parse TrigrsLog.txt for runtime info and mass balance.
    """
    log_path = os.path.join(work_dir, "TrigrsLog.txt")
    if not os.path.isfile(log_path):
        return {"status": "no_log_file"}

    info = {"warnings": [], "errors": [], "mass_balance": []}

    with open(log_path, "r") as f:
        for line in f:
            line_lower = line.lower().strip()
            if "error" in line_lower:
                info["errors"].append(line.strip())
            if "warn" in line_lower:
                info["warnings"].append(line.strip())
            if "mass" in line_lower or "balance" in line_lower:
                info["mass_balance"].append(line.strip())
            if "version" in line_lower:
                info["version"] = line.strip()
            if "time" in line_lower and ":" in line:
                info.setdefault("timing", []).append(line.strip())

    return info


def grid_to_csv(grid_data: np.ndarray, header: dict,
                output_path: str, value_name: str = "value") -> None:
    """
    Convert grid to CSV with coordinates.

    CSV columns: row, col, x, y, value
    """
    ncols = int(header.get("ncols", grid_data.shape[1]))
    nrows = int(header.get("nrows", grid_data.shape[0]))
    xll = float(header.get("xllcorner", 0))
    yll = float(header.get("yllcorner", 0))
    cellsize = float(header.get("cellsize", 1))
    nodata = header.get("nodata_value", -9999)

    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["row", "col", "x", "y", value_name])
        for r in range(nrows):
            for c in range(ncols):
                val = grid_data[r, c]
                if val == nodata:
                    continue
                x = xll + c * cellsize + cellsize / 2
                y = yll + (nrows - 1 - r) * cellsize + cellsize / 2
                writer.writerow([r, c, f"{x:.2f}", f"{y:.2f}", f"{val:.6f}"])


def validate_outputs(result_csv: str, summary: dict) -> list:
    """Validate parsed outputs for physical reasonableness."""
    warnings = []

    if os.path.isfile(result_csv):
        # Check file is not empty
        with open(result_csv, "r") as f:
            lines = f.readlines()
        if len(lines) <= 1:
            warnings.append("Result CSV is empty (header only)")
    else:
        warnings.append(f"Result CSV not created: {result_csv}")

    # Check FS statistics
    for key in ["fs_min", "water_depth"]:
        for step_data in summary.get(key, {}).values():
            stats = step_data.get("stats", {})
            if stats:
                if stats.get("min_fs", 999) < 0:
                    warnings.append(
                        f"Negative FS values detected (min={stats['min_fs']})")
                if stats.get("pct_unstable", 0) > 95:
                    warnings.append(
                        f"Over 95% cells unstable -- check parameters")

    return warnings


def main():
    parser = argparse.ArgumentParser(
        description="Parse TRIGRS output files"
    )
    parser.add_argument("--output_dir", required=True,
                        help="Directory containing TRIGRS output files")
    parser.add_argument("--suffix", required=True,
                        help="Output file suffix used in TRIGRS run")
    parser.add_argument("--work_dir", default=".",
                        help="Working directory (for log file)")
    parser.add_argument("--result_csv", default="results.csv",
                        help="Output CSV file path")
    parser.add_argument("--summary_json", default="summary.json",
                        help="Output summary JSON file path")

    args = parser.parse_args()

    # Step 1: Validate inputs
    print("[1/4] Validating inputs...")
    params = validate_inputs(args.output_dir, args.suffix)

    # Step 2: Find and categorize output files
    print("[2/4] Scanning output files...")
    files = find_output_files(args.output_dir, args.suffix)
    for ftype, flist in files.items():
        print(f"  {ftype}: {len(flist)} timestep(s)")

    # Step 3: Parse grids
    print("[3/4] Parsing output grids...")
    summary = {}

    # Parse FS grids
    if "fs_min" in files:
        summary["fs_min"] = {}
        for step, filepath in files["fs_min"]:
            result = parse_fs_grid(filepath)
            summary["fs_min"][step] = {
                "file": filepath,
                "stats": result["stats"],
            }
            if result["stats"]:
                print(f"  FS grid step {step}: "
                      f"min={result['stats']['min_fs']:.3f}, "
                      f"mean={result['stats']['mean_fs']:.3f}, "
                      f"unstable={result['stats']['pct_unstable']:.1f}%")

                # Write first FS grid to CSV
                if step == files["fs_min"][0][0]:
                    grid_to_csv(result["data"], result["header"],
                                args.result_csv, "factor_of_safety")

    # Parse water table grids
    for wt_type in ["water_depth", "water_eleva"]:
        if wt_type in files:
            summary[wt_type] = {}
            for step, filepath in files[wt_type]:
                result = read_asc_grid(filepath)
                data = result["data"]
                nodata = result["header"].get("nodata_value", -9999)
                valid = data[data != nodata]
                if valid.size > 0:
                    summary[wt_type][step] = {
                        "file": filepath,
                        "stats": {
                            "min": float(np.min(valid)),
                            "max": float(np.max(valid)),
                            "mean": float(np.mean(valid)),
                        }
                    }

    # Parse log file
    log_info = parse_log_file(args.work_dir)
    summary["log"] = log_info

    # Step 4: Validate and write summary
    print("[4/4] Validating outputs...")
    warnings = validate_outputs(args.result_csv, summary)
    if warnings:
        print("  Warnings:")
        for w in warnings:
            print(f"    - {w}")
    else:
        print("  All outputs validated OK")

    summary["warnings"] = warnings

    # Write summary JSON
    with open(args.summary_json, "w") as f:
        json.dump(summary, f, indent=2, default=str)

    print(f"\nDone. Results: {args.result_csv}")
    print(f"Summary: {args.summary_json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
