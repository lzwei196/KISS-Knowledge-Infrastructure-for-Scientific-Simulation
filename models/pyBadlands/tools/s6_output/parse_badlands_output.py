#!/usr/bin/env python3
"""
parse_badlands_output.py — Extract pyBadlands HDF5 output to CSV and compute budgets.

Reads the HDF5 time series output from a pyBadlands simulation and extracts:
- Elevation time series at specified points
- Erosion/deposition budgets per time step
- Summary statistics (total eroded volume, deposited volume, mean denudation rate)
- Spatial maps at specified time steps

Output formats:
- CSV time series (time, elevation, cumdiff, discharge, ...)
- JSON summary with budget statistics

Usage:
    python parse_badlands_output.py --output-dir output/ --csv results.csv
    python parse_badlands_output.py --output-dir output/ --csv results.csv \\
        --points "100000,200000;150000,250000"
    python parse_badlands_output.py --output-dir output/ --summary budget.json

CRITICAL:
    - HDF5 files are in output/h5/ subdirectory
    - Elevation is in metres, cumdiff is cumulative (not per-step)
    - Discharge is m³/year
"""

import argparse
import json
import os
import sys
import glob
import numpy as np


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_inputs(args):
    """Validate output directory and HDF5 files exist."""
    errors = []

    if not os.path.isdir(args.output_dir):
        errors.append(f"Output directory not found: {args.output_dir}")

    h5_dir = os.path.join(args.output_dir, "h5")
    if not os.path.isdir(h5_dir):
        # Try direct path
        h5_dir = args.output_dir

    tin_files = sorted(glob.glob(os.path.join(h5_dir, "tin.time*.hdf5")))
    if not tin_files:
        errors.append(f"No tin.time*.hdf5 files found in {h5_dir}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)

    return h5_dir, tin_files


def parse_points(points_str):
    """Parse point string 'x1,y1;x2,y2' into list of (x,y) tuples."""
    if not points_str:
        return []
    points = []
    for pair in points_str.split(";"):
        xy = pair.strip().split(",")
        if len(xy) == 2:
            points.append((float(xy[0]), float(xy[1])))
    return points


# ---------------------------------------------------------------------------
# HDF5 Reader
# ---------------------------------------------------------------------------

def read_timestep(h5_path):
    """
    Read a single HDF5 timestep file.

    Returns dict with arrays: coords, cumdiff, cumhill, cumfail, cumflex, discharge.
    """
    try:
        import h5py
    except ImportError:
        print(json.dumps({"status": "error",
                          "errors": ["h5py not installed: pip install h5py"]}))
        sys.exit(1)

    data = {}
    with h5py.File(h5_path, "r") as f:
        # Core datasets
        if "coords" in f:
            data["coords"] = f["coords"][:]  # (N, 3) → x, y, z
        elif "x" in f and "y" in f and "z" in f:
            x = f["x"][:]
            y = f["y"][:]
            z = f["z"][:]
            data["coords"] = np.column_stack([x, y, z])

        for var in ["cumdiff", "cumhill", "cumfail", "cumflex", "discharge",
                     "slopeTIN", "rain"]:
            if var in f:
                data[var] = f[var][:]

    return data


def find_nearest_node(coords, target_x, target_y):
    """Find index of nearest TIN node to target coordinates."""
    dists = (coords[:, 0] - target_x) ** 2 + (coords[:, 1] - target_y) ** 2
    return int(np.argmin(dists))


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

def extract_timeseries(h5_dir, tin_files, points):
    """
    Extract time series at specified points (or domain-wide statistics).

    Returns list of dicts, one per timestep.
    """
    records = []

    for i, h5_path in enumerate(tin_files):
        data = read_timestep(h5_path)
        if "coords" not in data:
            continue

        coords = data["coords"]
        elev = coords[:, 2]

        record = {
            "step": i,
            "file": os.path.basename(h5_path),
            "n_nodes": len(elev),
            "elev_min": float(np.nanmin(elev)),
            "elev_max": float(np.nanmax(elev)),
            "elev_mean": float(np.nanmean(elev)),
        }

        # Cumulative erosion/deposition
        if "cumdiff" in data:
            cd = data["cumdiff"]
            record["cumdiff_min"] = float(np.nanmin(cd))
            record["cumdiff_max"] = float(np.nanmax(cd))
            record["cumdiff_mean"] = float(np.nanmean(cd))
            record["total_erosion_m"] = float(np.nansum(cd[cd < 0]))
            record["total_deposition_m"] = float(np.nansum(cd[cd > 0]))

        if "cumhill" in data:
            record["cumhill_mean"] = float(np.nanmean(data["cumhill"]))

        if "discharge" in data:
            record["discharge_max"] = float(np.nanmax(data["discharge"]))

        # Point extractions
        for j, (px, py) in enumerate(points):
            idx = find_nearest_node(coords, px, py)
            record[f"point{j}_x"] = float(coords[idx, 0])
            record[f"point{j}_y"] = float(coords[idx, 1])
            record[f"point{j}_elev"] = float(elev[idx])
            if "cumdiff" in data:
                record[f"point{j}_cumdiff"] = float(data["cumdiff"][idx])
            if "discharge" in data:
                record[f"point{j}_discharge"] = float(data["discharge"][idx])

        records.append(record)

    return records


def compute_budget_summary(records):
    """Compute erosion/deposition budget summary from time series."""
    if not records:
        return {"status": "error", "message": "No records to summarize"}

    first = records[0]
    last = records[-1]

    summary = {
        "n_timesteps": len(records),
        "n_nodes": last.get("n_nodes", 0),
        "initial_elev_range": [first.get("elev_min", 0), first.get("elev_max", 0)],
        "final_elev_range": [last.get("elev_min", 0), last.get("elev_max", 0)],
        "mean_elevation_change": last.get("cumdiff_mean", 0),
        "max_erosion_m": last.get("cumdiff_min", 0),
        "max_deposition_m": last.get("cumdiff_max", 0),
    }

    # Track elevation evolution
    elev_means = [r.get("elev_mean", 0) for r in records]
    summary["elev_mean_trend"] = {
        "start": elev_means[0],
        "end": elev_means[-1],
        "change": elev_means[-1] - elev_means[0],
    }

    return summary


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

def write_csv(records, csv_path):
    """Write records to CSV file."""
    if not records:
        return

    # Determine all keys
    all_keys = []
    for r in records:
        for k in r.keys():
            if k not in all_keys:
                all_keys.append(k)

    with open(csv_path, "w") as f:
        f.write(",".join(all_keys) + "\n")
        for r in records:
            vals = [str(r.get(k, "")) for k in all_keys]
            f.write(",".join(vals) + "\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def process(args):
    """Main processing pipeline."""
    h5_dir, tin_files = validate_inputs(args)
    points = parse_points(args.points)

    # Extract time series
    records = extract_timeseries(h5_dir, tin_files, points)

    result = {
        "status": "success",
        "n_timesteps": len(records),
        "h5_dir": h5_dir,
        "n_points_extracted": len(points),
    }

    # Write CSV
    if args.csv:
        write_csv(records, args.csv)
        result["csv_output"] = args.csv

    # Compute budget summary
    summary = compute_budget_summary(records)
    result["budget_summary"] = summary

    # Write summary JSON
    if args.summary:
        with open(args.summary, "w") as f:
            json.dump({"summary": summary, "records": records}, f, indent=2)
        result["summary_output"] = args.summary

    return result


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--output-dir", dest="output_dir", required=True,
                        help="Path to pyBadlands output directory")
    parser.add_argument("--csv", default=None,
                        help="Write time series to CSV file")
    parser.add_argument("--summary", default=None,
                        help="Write budget summary to JSON file")
    parser.add_argument("--points", default=None,
                        help="Extract at points: 'x1,y1;x2,y2;...'")

    args = parser.parse_args()
    result = process(args)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
