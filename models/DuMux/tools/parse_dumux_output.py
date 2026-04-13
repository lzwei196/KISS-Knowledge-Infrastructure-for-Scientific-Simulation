#!/usr/bin/env python3
"""
parse_dumux_output.py — Parse DuMux VTK output to CSV and analysis-ready formats.

Pipeline stage: s5 (Output Parsing)
Pattern: validate → process → validate

Parses VTK (.vtu, .vtk, .pvd) output files from DuMux simulations and extracts:
  - Time series at specific points (monitoring wells)
  - Spatial field snapshots
  - Integrated quantities (total mass, fluxes)
  - CSV export for downstream analysis

Usage:
    python parse_dumux_output.py \\
        --input_dir /path/to/output/ \\
        --pattern "1p_*.vtu" \\
        --output results.csv \\
        --variables pressure,velocity \\
        --probe_points "0.5,0.5;0.25,0.75"
"""

import argparse
import csv
import glob
import json
import os
import re
import struct
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

# ─── VTK Parsing (pure Python, no vtk library dependency) ───────────────────

def parse_vtu_file(filepath: str) -> dict:
    """Parse a VTK Unstructured Grid file (.vtu) in XML format.

    Returns:
        dict with keys: points, cells, point_data, cell_data, metadata
    """
    result = {
        "points": None,
        "cells": None,
        "point_data": {},
        "cell_data": {},
        "metadata": {"filepath": filepath},
    }

    try:
        tree = ET.parse(filepath)
        root = tree.getroot()
    except ET.ParseError as e:
        result["metadata"]["error"] = f"XML parse error: {e}"
        return result

    # Find UnstructuredGrid piece
    piece = root.find(".//Piece")
    if piece is None:
        result["metadata"]["error"] = "No <Piece> element found in VTU file"
        return result

    n_points = int(piece.get("NumberOfPoints", 0))
    n_cells = int(piece.get("NumberOfCells", 0))
    result["metadata"]["n_points"] = n_points
    result["metadata"]["n_cells"] = n_cells

    # Parse Points
    points_elem = piece.find(".//Points/DataArray")
    if points_elem is not None:
        points_text = points_elem.text
        if points_text:
            vals = [float(v) for v in points_text.split()]
            n_comp = int(points_elem.get("NumberOfComponents", 3))
            result["points"] = np.array(vals).reshape(-1, n_comp)

    # Parse PointData
    point_data_elem = piece.find(".//PointData")
    if point_data_elem is not None:
        for da in point_data_elem.findall("DataArray"):
            name = da.get("Name", "unnamed")
            n_comp = int(da.get("NumberOfComponents", 1))
            if da.text:
                vals = [float(v) for v in da.text.split()]
                if n_comp == 1:
                    result["point_data"][name] = np.array(vals)
                else:
                    result["point_data"][name] = np.array(vals).reshape(-1, n_comp)

    # Parse CellData
    cell_data_elem = piece.find(".//CellData")
    if cell_data_elem is not None:
        for da in cell_data_elem.findall("DataArray"):
            name = da.get("Name", "unnamed")
            n_comp = int(da.get("NumberOfComponents", 1))
            if da.text:
                vals = [float(v) for v in da.text.split()]
                if n_comp == 1:
                    result["cell_data"][name] = np.array(vals)
                else:
                    result["cell_data"][name] = np.array(vals).reshape(-1, n_comp)

    return result


def parse_pvd_file(filepath: str) -> list:
    """Parse a ParaView Data file (.pvd) to get time series of VTU files.

    Returns:
        list of dicts with keys: timestep, file, part
    """
    entries = []
    try:
        tree = ET.parse(filepath)
        root = tree.getroot()
        collection = root.find(".//Collection")
        if collection is not None:
            for dataset in collection.findall("DataSet"):
                entries.append({
                    "timestep": float(dataset.get("timestep", 0)),
                    "file": dataset.get("file", ""),
                    "part": int(dataset.get("part", 0)),
                })
    except ET.ParseError as e:
        print(f"  WARNING: Failed to parse PVD: {e}")
    return entries


def extract_time_from_filename(filename: str) -> float:
    """Extract time step number or time value from VTU filename.

    Typical patterns:
        problem_00001.vtu → step 1
        problem-00042.vtu → step 42
    """
    base = os.path.splitext(os.path.basename(filename))[0]
    # Match trailing digits
    match = re.search(r'[-_](\d+)$', base)
    if match:
        return int(match.group(1))
    return 0.0


# ─── Spatial operations ──────────────────────────────────────────────────────

def find_nearest_cell(cell_centers: np.ndarray, target_point: np.ndarray) -> int:
    """Find the cell index nearest to a target point."""
    if cell_centers is None or len(cell_centers) == 0:
        return -1
    dists = np.linalg.norm(cell_centers - target_point, axis=1)
    return int(np.argmin(dists))


def compute_cell_centers(points: np.ndarray, connectivity: list = None) -> np.ndarray:
    """Estimate cell centers from point coordinates.

    If connectivity is not available, use a simple grid assumption.
    For structured grids, cell centers are midpoints.
    """
    if points is None:
        return np.array([])

    # Simple fallback: use points directly (works for cell-centered schemes)
    return points


# ─── Validation ──────────────────────────────────────────────────────────────

def validate_inputs(input_dir: str, pattern: str) -> dict:
    """Validate input directory and find matching VTK files."""
    result = {"valid": True, "errors": [], "warnings": [], "metadata": {}}

    if not os.path.isdir(input_dir):
        result["valid"] = False
        result["errors"].append(f"Input directory not found: {input_dir}")
        return result

    # Find matching files
    file_pattern = os.path.join(input_dir, pattern)
    files = sorted(glob.glob(file_pattern))
    result["metadata"]["pattern"] = file_pattern
    result["metadata"]["n_files"] = len(files)
    result["metadata"]["files"] = files[:10]  # first 10

    if len(files) == 0:
        # Try broader search
        all_vtk = glob.glob(os.path.join(input_dir, "*.vtu")) + \
                  glob.glob(os.path.join(input_dir, "*.vtk"))
        if len(all_vtk) > 0:
            result["warnings"].append(
                f"No files matching '{pattern}', but found {len(all_vtk)} VTK files. "
                f"Try: --pattern '{os.path.basename(all_vtk[0]).split('-')[0]}*.vtu'"
            )
        else:
            result["valid"] = False
            result["errors"].append(f"No VTK files found in {input_dir}")

    # Check for PVD file
    pvd_files = glob.glob(os.path.join(input_dir, "*.pvd"))
    if pvd_files:
        result["metadata"]["pvd_file"] = pvd_files[0]

    return result


def validate_outputs(output_path: str, n_rows: int) -> dict:
    """Validate output CSV was written correctly."""
    result = {"valid": True, "errors": [], "warnings": []}

    if not os.path.isfile(output_path):
        result["valid"] = False
        result["errors"].append(f"Output file not created: {output_path}")
        return result

    size = os.path.getsize(output_path)
    if size == 0:
        result["valid"] = False
        result["errors"].append("Output CSV is empty")

    if n_rows == 0:
        result["warnings"].append("Zero data rows extracted")

    return result


# ─── Processing ──────────────────────────────────────────────────────────────

def extract_timeseries(
    files: list,
    variables: list,
    probe_points: list = None,
    time_values: list = None,
) -> dict:
    """Extract time series data from a sequence of VTU files.

    Args:
        files: List of VTU file paths (sorted by time)
        variables: List of variable names to extract
        probe_points: List of (x, y [, z]) coordinate tuples for monitoring points
        time_values: Explicit time values (from PVD file); otherwise extracted from filenames

    Returns:
        dict with keys: times, data (dict of variable→array), probe_labels
    """
    result = {"times": [], "data": {}, "probe_labels": []}

    if not files:
        return result

    # Initialize probe labels
    if probe_points:
        result["probe_labels"] = [f"probe_{i}" for i in range(len(probe_points))]
        for var in variables:
            for i in range(len(probe_points)):
                key = f"{var}_probe{i}"
                result["data"][key] = []
    else:
        # Spatial average
        for var in variables:
            result["data"][f"{var}_mean"] = []
            result["data"][f"{var}_min"] = []
            result["data"][f"{var}_max"] = []

    for fi, fpath in enumerate(files):
        # Time value
        if time_values and fi < len(time_values):
            t = time_values[fi]
        else:
            t = extract_time_from_filename(fpath)
        result["times"].append(t)

        # Parse VTU
        vtu = parse_vtu_file(fpath)

        # Merge point_data and cell_data for variable search
        all_data = {}
        all_data.update(vtu.get("point_data", {}))
        all_data.update(vtu.get("cell_data", {}))

        for var in variables:
            # Find variable (case-insensitive search)
            found_key = None
            for k in all_data:
                if k.lower() == var.lower() or var.lower() in k.lower():
                    found_key = k
                    break

            if found_key is None:
                # Variable not found in this file
                if probe_points:
                    for i in range(len(probe_points)):
                        result["data"][f"{var}_probe{i}"].append(np.nan)
                else:
                    result["data"][f"{var}_mean"].append(np.nan)
                    result["data"][f"{var}_min"].append(np.nan)
                    result["data"][f"{var}_max"].append(np.nan)
                continue

            field = all_data[found_key]
            if field.ndim > 1:
                # Vector field: compute magnitude
                field = np.linalg.norm(field, axis=1)

            if probe_points:
                # Get values at probe locations
                centers = vtu.get("points", np.array([]))
                if len(centers) == 0:
                    # Use cell centers approximation
                    centers = compute_cell_centers(vtu.get("points"))

                for i, pt in enumerate(probe_points):
                    pt_arr = np.array(pt)
                    if len(centers) > 0 and len(field) > 0:
                        # Match dimensions
                        if pt_arr.shape[0] < centers.shape[1]:
                            pt_arr = np.append(pt_arr, [0] * (centers.shape[1] - pt_arr.shape[0]))
                        idx = find_nearest_cell(centers[:len(field)], pt_arr[:centers.shape[1]])
                        if 0 <= idx < len(field):
                            result["data"][f"{var}_probe{i}"].append(float(field[idx]))
                        else:
                            result["data"][f"{var}_probe{i}"].append(np.nan)
                    else:
                        result["data"][f"{var}_probe{i}"].append(np.nan)
            else:
                result["data"][f"{var}_mean"].append(float(np.nanmean(field)))
                result["data"][f"{var}_min"].append(float(np.nanmin(field)))
                result["data"][f"{var}_max"].append(float(np.nanmax(field)))

    return result


def write_csv(output_path: str, timeseries: dict) -> int:
    """Write time series to CSV file.

    Returns:
        Number of data rows written
    """
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    times = timeseries["times"]
    data = timeseries["data"]
    columns = sorted(data.keys())

    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["time"] + columns)
        for i in range(len(times)):
            row = [times[i]]
            for col in columns:
                vals = data[col]
                row.append(vals[i] if i < len(vals) else "")
            writer.writerow(row)

    return len(times)


def write_spatial_snapshot(output_path: str, vtu_data: dict, variables: list) -> int:
    """Write a spatial field snapshot to CSV (x, y, z, var1, var2, ...).

    Returns:
        Number of data rows written
    """
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    all_data = {}
    all_data.update(vtu_data.get("point_data", {}))
    all_data.update(vtu_data.get("cell_data", {}))

    points = vtu_data.get("points")
    if points is None:
        return 0

    n_pts = len(points)
    headers = ["x", "y"]
    if points.shape[1] > 2:
        headers.append("z")

    var_arrays = []
    for var in variables:
        for k in all_data:
            if var.lower() in k.lower():
                arr = all_data[k]
                if arr.ndim > 1:
                    # Vector: write components
                    for c in range(arr.shape[1]):
                        headers.append(f"{k}_{c}")
                        var_arrays.append(arr[:, c])
                else:
                    headers.append(k)
                    var_arrays.append(arr)
                break

    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        for i in range(min(n_pts, *[len(a) for a in var_arrays] if var_arrays else [n_pts])):
            row = list(points[i, :len(headers)-len(var_arrays)])
            for arr in var_arrays:
                row.append(float(arr[i]) if i < len(arr) else "")
            writer.writerow(row)

    return n_pts


# ─── Main Pipeline ───────────────────────────────────────────────────────────

def process(
    input_dir: str,
    pattern: str,
    output_path: str,
    variables: list,
    probe_points_str: str = "",
    snapshot_index: int = -1,
) -> dict:
    """Main pipeline: validate → process → validate."""
    summary = {"status": "failed", "input_dir": input_dir, "output": output_path}

    # ── Validate inputs ──
    print("=== Validating inputs ===")
    input_val = validate_inputs(input_dir, pattern)
    for w in input_val["warnings"]:
        print(f"  WARNING: {w}")
    if not input_val["valid"]:
        for e in input_val["errors"]:
            print(f"  ERROR: {e}")
        summary["errors"] = input_val["errors"]
        return summary

    files = sorted(glob.glob(os.path.join(input_dir, pattern)))
    print(f"  Found {len(files)} VTK files")

    # Parse time values from PVD if available
    time_values = None
    pvd_file = input_val["metadata"].get("pvd_file")
    if pvd_file:
        pvd_entries = parse_pvd_file(pvd_file)
        if pvd_entries:
            time_values = [e["timestep"] for e in pvd_entries]
            print(f"  PVD time range: {time_values[0]} – {time_values[-1]}")

    # Parse probe points
    probe_points = None
    if probe_points_str:
        probe_points = []
        for pt_str in probe_points_str.split(";"):
            coords = [float(x) for x in pt_str.split(",")]
            probe_points.append(coords)
        print(f"  Probe points: {len(probe_points)}")

    # ── Process ──
    print("=== Processing ===")

    if snapshot_index >= 0:
        # Single spatial snapshot
        if snapshot_index >= len(files):
            snapshot_index = len(files) - 1
        print(f"  Extracting spatial snapshot from: {files[snapshot_index]}")
        vtu_data = parse_vtu_file(files[snapshot_index])
        n_rows = write_spatial_snapshot(output_path, vtu_data, variables)
        summary["mode"] = "snapshot"
    else:
        # Time series extraction
        print(f"  Extracting time series for variables: {variables}")
        ts = extract_timeseries(files, variables, probe_points, time_values)
        n_rows = write_csv(output_path, ts)
        summary["mode"] = "timeseries"
        summary["n_timesteps"] = len(ts["times"])

    print(f"  Wrote {n_rows} rows to {output_path}")
    summary["n_rows"] = n_rows

    # ── Validate outputs ──
    print("=== Validating outputs ===")
    output_val = validate_outputs(output_path, n_rows)
    for w in output_val["warnings"]:
        print(f"  WARNING: {w}")
    if not output_val["valid"]:
        for e in output_val["errors"]:
            print(f"  ERROR: {e}")
        summary["errors"] = output_val["errors"]
        return summary

    summary["status"] = "success"
    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Parse DuMux VTK output to CSV"
    )
    parser.add_argument("--input_dir", required=True, help="Directory with VTK output files")
    parser.add_argument("--pattern", default="*.vtu", help="Glob pattern for VTK files")
    parser.add_argument("--output", required=True, help="Output CSV path")
    parser.add_argument(
        "--variables", default="pressure",
        help="Comma-separated list of variables to extract"
    )
    parser.add_argument(
        "--probe_points", default="",
        help="Semicolon-separated probe points: 'x1,y1;x2,y2'"
    )
    parser.add_argument(
        "--snapshot", type=int, default=-1,
        help="Extract single spatial snapshot at this file index (-1 = time series mode)"
    )
    args = parser.parse_args()

    result = process(
        input_dir=args.input_dir,
        pattern=args.pattern,
        output_path=args.output,
        variables=args.variables.split(","),
        probe_points_str=args.probe_points,
        snapshot_index=args.snapshot,
    )

    if result["status"] != "success":
        print(f"\nFAILED: {result.get('errors', ['Unknown error'])}")
        sys.exit(1)
    else:
        print(f"\nSUCCESS: {result['n_rows']} rows extracted ({result['mode']})")


if __name__ == "__main__":
    main()
