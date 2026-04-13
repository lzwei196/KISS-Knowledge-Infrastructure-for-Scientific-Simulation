#!/usr/bin/env python3
"""
parse_w2_output.py — Parse CE-QUAL-W2 output files into structured data.

Handles three output types:
  - Snapshot files (snp_wb*.opt): Full 2D fields at specified times
  - Time series files (tsr_*.opt): Time series at specific segment-layer cells
  - Spreadsheet files (spr_*.opt): Summary tables

Output: JSON summary + optional CSV/NetCDF for downstream analysis.

Usage:
    python parse_w2_output.py \
        --run_dir /path/to/run \
        --grid_json /path/to/reservoir_grid.json \
        --output results_summary.json
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd


def parse_snapshot_file(snp_path, n_segments, n_layers):
    """
    Parse CE-QUAL-W2 snapshot file.
    Returns list of snapshots, each with jday + 2D temperature/velocity fields.
    """
    snapshots = []
    current_snap = None

    with open(snp_path) as f:
        for line in f:
            line = line.rstrip()

            # Look for JDAY marker
            if "JDAY" in line or "Snapshot" in line:
                jday_match = re.search(r'[\d]+\.[\d]+', line)
                if jday_match:
                    if current_snap is not None:
                        snapshots.append(current_snap)
                    current_snap = {
                        "jday": float(jday_match.group()),
                        "temperature": [],
                        "velocity_x": [],
                        "raw_lines": [],
                    }
                continue

            if current_snap is not None:
                current_snap["raw_lines"].append(line)

                # Try parsing as numeric data
                parts = line.split()
                if len(parts) >= 3:
                    try:
                        values = [float(p) for p in parts]
                        current_snap["temperature"].append(values)
                    except ValueError:
                        pass

    if current_snap is not None:
        snapshots.append(current_snap)

    return snapshots


def parse_timeseries_file(tsr_path):
    """
    Parse CE-QUAL-W2 time series file.
    Returns DataFrame with jday, temperature, and other variables at a location.
    """
    data = []
    header = None

    with open(tsr_path) as f:
        for line in f:
            if line.startswith("$") or line.strip() == "":
                if "JDAY" in line:
                    header = line.strip().strip("$").split()
                continue

            parts = line.split()
            if len(parts) >= 2:
                try:
                    row = [float(p) for p in parts]
                    data.append(row)
                except ValueError:
                    continue

    if not data:
        return pd.DataFrame()

    df = pd.DataFrame(data)
    if header and len(header) == len(df.columns):
        df.columns = header
    elif len(df.columns) >= 2:
        cols = ["JDAY"]
        for i in range(1, len(df.columns)):
            cols.append(f"VAR_{i}")
        df.columns = cols[:len(df.columns)]

    return df


def parse_spreadsheet_file(spr_path):
    """Parse CE-QUAL-W2 spreadsheet output file."""
    try:
        # Try tab-delimited first, then space-delimited
        df = pd.read_csv(spr_path, sep=r"\s+", comment="$", header=None)
        return df
    except Exception:
        return pd.DataFrame()


def process(args):
    """Main processing."""
    run_dir = Path(args.run_dir)

    # Parse all output file types
    results = {
        "snapshots": [],
        "timeseries": [],
        "spreadsheets": [],
    }

    # Load grid info if available
    grid = None
    if args.grid_json and os.path.isfile(args.grid_json):
        with open(args.grid_json) as f:
            grid = json.load(f)
        n_seg = grid["n_segments"]
        n_layers = grid["n_layers"]
    else:
        n_seg = 50  # default guess
        n_layers = 30

    # Parse snapshot files
    for snp_file in sorted(run_dir.glob("snp_*.opt")):
        snapshots = parse_snapshot_file(str(snp_file), n_seg, n_layers)
        for snap in snapshots:
            results["snapshots"].append({
                "file": str(snp_file),
                "jday": snap["jday"],
                "n_data_rows": len(snap["temperature"]),
            })

    # Parse time series files
    for tsr_file in sorted(run_dir.glob("tsr_*.opt")):
        df = parse_timeseries_file(str(tsr_file))
        if not df.empty:
            summary = {
                "file": str(tsr_file),
                "n_timesteps": len(df),
                "columns": list(df.columns),
            }
            if "JDAY" in df.columns:
                summary["jday_range"] = [float(df["JDAY"].min()), float(df["JDAY"].max())]

            # Save to CSV for downstream use
            csv_path = tsr_file.with_suffix(".csv")
            df.to_csv(csv_path, index=False)
            summary["csv_output"] = str(csv_path)

            results["timeseries"].append(summary)

    # Parse spreadsheet files
    for spr_file in sorted(run_dir.glob("spr_*.opt")):
        df = parse_spreadsheet_file(str(spr_file))
        if not df.empty:
            csv_path = spr_file.with_suffix(".csv")
            df.to_csv(csv_path, index=False)
            results["spreadsheets"].append({
                "file": str(spr_file),
                "n_rows": len(df),
                "n_cols": len(df.columns),
                "csv_output": str(csv_path),
            })

    # Summary statistics
    summary = {
        "status": "success",
        "run_dir": str(run_dir),
        "n_snapshots": len(results["snapshots"]),
        "n_timeseries": len(results["timeseries"]),
        "n_spreadsheets": len(results["spreadsheets"]),
        "details": results,
    }

    if not (results["snapshots"] or results["timeseries"] or results["spreadsheets"]):
        summary["status"] = "warning"
        summary["warnings"] = ["No output data found — check w2_con.npt output cards (dt_025)"]

    # Write summary JSON
    output_path = args.output
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(summary, f, indent=2)

    print(json.dumps(summary, indent=2))
    return 0


def main():
    parser = argparse.ArgumentParser(description="Parse CE-QUAL-W2 output files")
    parser.add_argument("--run_dir", required=True, help="CE-QUAL-W2 run directory")
    parser.add_argument("--grid_json", help="Reservoir grid JSON (for spatial reference)")
    parser.add_argument("--output", required=True, help="Output summary JSON path")
    args = parser.parse_args()
    sys.exit(process(args))


if __name__ == "__main__":
    main()
