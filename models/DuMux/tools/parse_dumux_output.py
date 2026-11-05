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
        "cell_centers": None,
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
    pieces = root.findall(".//Piece")
    if not pieces:
        result["metadata"]["error"] = "No <Piece> element found in VTU file"
        return result
    if len(pieces) > 1:
        result["metadata"]["error"] = (f"{len(pieces)} <Piece> elements; only single-piece "
                                       "VTU files are supported")
        return result
    piece = pieces[0]

    n_points = int(piece.get("NumberOfPoints", 0))
    n_cells = int(piece.get("NumberOfCells", 0))
    result["metadata"]["n_points"] = n_points
    result["metadata"]["n_cells"] = n_cells

    # Only ASCII DataArrays are read; binary/appended data would be misread
    for da in piece.iter("DataArray"):
        fmt = da.get("format", "ascii")
        if fmt != "ascii":
            result["metadata"]["error"] = (
                f"DataArray '{da.get('Name')}' has format='{fmt}'; only ASCII VTU is "
                f"supported (set Vtk.OutputFormat / write ascii)")
            return result

    # Parse Points
    points_elem = piece.find(".//Points/DataArray")
    if points_elem is not None:
        points_text = points_elem.text
        if points_text:
            vals = [float(v) for v in points_text.split()]
            n_comp = int(points_elem.get("NumberOfComponents", 3))
            result["points"] = np.array(vals).reshape(-1, n_comp)

    # Cell centres = mean of each cell's vertices (cell data belong to cells,
    # not to the first n_cells vertices)
    conn_elem = piece.find(".//Cells/DataArray[@Name='connectivity']")
    offs_elem = piece.find(".//Cells/DataArray[@Name='offsets']")
    if result["points"] is not None and conn_elem is not None and offs_elem is not None \
            and conn_elem.text and offs_elem.text:
        conn = np.array(conn_elem.text.split(), dtype=np.int64)
        offs = np.array(offs_elem.text.split(), dtype=np.int64)
        starts = np.concatenate(([0], offs[:-1]))
        counts = offs - starts
        n_pts = len(result["points"])
        if (len(offs) != n_cells or len(offs) == 0 or np.any(counts <= 0)
                or offs[-1] != len(conn) or np.any(conn < 0) or np.any(conn >= n_pts)):
            result["metadata"]["error"] = (
                "cell connectivity/offsets are not consistent (cell count, increasing offsets, "
                "last offset = connectivity length, vertex ids in range)")
            return result
        cell_ids = np.repeat(np.arange(len(offs)), counts)
        sums = np.zeros((len(offs), result["points"].shape[1]))
        np.add.at(sums, cell_ids, result["points"][conn])
        result["cell_centers"] = sums / counts[:, None]

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

    # Every data array must have one value (tuple) per cell / per point
    for kind, n in (("cell_data", n_cells), ("point_data", n_points)):
        for name, arr in result[kind].items():
            if len(arr) != n:
                result["metadata"]["error"] = (f"{kind} '{name}' has {len(arr)} values, "
                                               f"expected {n}")
                return result
    if result["points"] is not None and len(result["points"]) != n_points:
        result["metadata"]["error"] = (f"{len(result['points'])} points, expected {n_points}")
        return result

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


# ─── Variable lookup ─────────────────────────────────────────────────────────

# DuMux names the pressure of single-phase models "p" (2p models: p_w/p_n, p_liq/p_gas).
VARIABLE_ALIASES = {"pressure": ["p"]}


def resolve_variable(vtus: list, var: str):
    """Field name to use for var across all files: (name, None) or (None, reason).

    Order: exact name, then case-insensitive exact, then alias (exact), then a
    case-insensitive substring match - the last only for names of 3+ characters
    and only if exactly one field name matches. A better match in any file wins for
    all files, so e.g. 'p' is never taken from 'process rank'.
    """
    names = []
    for vtu in vtus:
        for data in (vtu.get("cell_data", {}), vtu.get("point_data", {})):
            for k in data:
                if k not in names:
                    names.append(k)
    for test in (lambda k: k == var,
                 lambda k: k.lower() == var.lower(),
                 lambda k: k in VARIABLE_ALIASES.get(var.lower(), [])):
        hits = [k for k in names if test(k)]
        if len(hits) == 1:
            return hits[0], None
        if len(hits) > 1:
            return None, f"'{var}' is ambiguous: {hits}"
    if len(var) >= 3:
        hits = [k for k in names if var.lower() in k.lower()]
        if len(hits) == 1:
            return hits[0], None
        if len(hits) > 1:
            return None, f"'{var}' matches several fields: {hits}; give the exact name"
    return None, f"'{var}' not found"


def get_field(vtu: dict, key: str):
    """(array, 'cell'|'point') for an exact field name, else (None, None)."""
    if key in vtu.get("cell_data", {}):
        return vtu["cell_data"][key], "cell"
    if key in vtu.get("point_data", {}):
        return vtu["point_data"][key], "point"
    return None, None


def find_variable(vtu: dict, var: str):
    """Return (name, array, location) for var in one file, else (None, None, None)."""
    key, _ = resolve_variable([vtu], var)
    if key is None:
        return None, None, None
    arr, loc = get_field(vtu, key)
    return key, arr, loc


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

    vtus = []
    for fpath in files:
        vtu = parse_vtu_file(fpath)
        if vtu["metadata"].get("error"):
            raise ValueError(f"{fpath}: {vtu['metadata']['error']}")
        vtus.append(vtu)
    resolved = {var: resolve_variable(vtus, var) for var in variables}
    keys = {var: r[0] for var, r in resolved.items()}
    result["matched"] = {v: k for v, k in keys.items() if k is not None}
    result["missing_variables"] = [r[1] for v, r in resolved.items() if r[0] is None]
    result["files_without"] = {}
    result["nonfinite"] = {}

    for fi, fpath in enumerate(files):
        # Time value: from the .pvd entry of this file, else the file number
        if isinstance(time_values, dict):
            t = time_values.get(os.path.normpath(os.path.abspath(fpath)))
            if t is None:
                t = extract_time_from_filename(fpath)
                result.setdefault("time_from_filename", []).append(os.path.basename(fpath))
        elif time_values and fi < len(time_values):
            t = time_values[fi]
        else:
            t = extract_time_from_filename(fpath)
        result["times"].append(t)

        vtu = vtus[fi]

        for var in variables:
            found_key = keys[var]
            field, loc = get_field(vtu, found_key) if found_key else (None, None)

            if field is None:
                # Variable not found in this file
                result["files_without"].setdefault(var, []).append(os.path.basename(fpath))
                if probe_points:
                    for i in range(len(probe_points)):
                        result["data"][f"{var}_probe{i}"].append(np.nan)
                else:
                    result["data"][f"{var}_mean"].append(np.nan)
                    result["data"][f"{var}_min"].append(np.nan)
                    result["data"][f"{var}_max"].append(np.nan)
                continue

            if field.ndim > 1:
                # Vector field: compute magnitude
                field = np.linalg.norm(field, axis=1)
            n_bad = int(np.count_nonzero(~np.isfinite(field)))
            if n_bad:
                result["nonfinite"].setdefault(var, []).append((os.path.basename(fpath), n_bad))

            if probe_points:
                # Locations of the values: cell centres for cell data, vertices for point data
                centers = vtu.get("cell_centers") if loc == "cell" else vtu.get("points")
                if centers is None or len(centers) != len(field):
                    raise ValueError(f"{fpath}: no coordinates for the {loc} data '{found_key}' "
                                     f"(need {len(field)} {loc} locations)")

                for i, pt in enumerate(probe_points):
                    pt_arr = np.array(pt, dtype=float)
                    if pt_arr.shape[0] < centers.shape[1]:
                        pt_arr = np.append(pt_arr, [0] * (centers.shape[1] - pt_arr.shape[0]))
                    idx = find_nearest_cell(centers, pt_arr[:centers.shape[1]])
                    if 0 <= idx < len(field):
                        result["data"][f"{var}_probe{i}"].append(float(field[idx]))
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

    headers = []
    var_arrays = []
    locs = set()
    missing = []
    for var in variables:
        k, arr, loc = find_variable(vtu_data, var)
        if k is None:
            missing.append(var)
            continue
        locs.add(loc)
        if arr.ndim > 1:
            # Vector: write components
            for c in range(arr.shape[1]):
                headers.append(f"{k}_{c}")
                var_arrays.append(arr[:, c])
        else:
            headers.append(k)
            var_arrays.append(arr)
    if missing:
        raise ValueError(f"variable(s) {missing} not in this file")
    if len(locs) > 1:
        raise ValueError("cannot mix cell data and point data in one snapshot; "
                         "run once per kind")

    # Coordinates of the values: cell centres for cell data, vertices for point data
    loc = locs.pop() if locs else "point"
    coords = vtu_data.get("cell_centers") if loc == "cell" else vtu_data.get("points")
    if coords is None:
        raise ValueError(f"no {loc} coordinates in this file")
    n_rows = len(coords)
    if any(len(a) != n_rows for a in var_arrays):
        raise ValueError(f"{loc} coordinates ({n_rows}) and data lengths differ")
    coord_headers = ["x", "y"] + (["z"] if coords.shape[1] > 2 else [])
    for name, arr in zip(headers, var_arrays):
        n_bad = int(np.count_nonzero(~np.isfinite(arr)))
        if n_bad:
            print(f"  WARNING: '{name}' has {n_bad} non-finite values (written as they are)")

    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(coord_headers + headers)
        for i in range(n_rows):
            row = list(coords[i, :len(coord_headers)])
            for arr in var_arrays:
                row.append(float(arr[i]))
            writer.writerow(row)

    return n_rows


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
    if not files:
        msg = f"No files match '{pattern}' in {input_dir}"
        print(f"  ERROR: {msg}")
        summary["errors"] = [msg]
        return summary

    # Time values from the .pvd files, matched to each .vtu by file name
    # (not by position: the folder can hold other .vtu files, e.g. 1p.vtu)
    time_values = {}
    for pvd_file in sorted(glob.glob(os.path.join(input_dir, "*.pvd"))):
        pvd_entries = parse_pvd_file(pvd_file)
        pvd_dir = os.path.dirname(os.path.abspath(pvd_file))
        for e in pvd_entries:
            key = os.path.normpath(os.path.join(pvd_dir, e["file"]))
            if key in time_values and time_values[key] != e["timestep"]:
                msg = (f"{key} has time {time_values[key]} in one .pvd and {e['timestep']} "
                       f"in {pvd_file}")
                print(f"  ERROR: {msg}")
                summary["errors"] = [msg]
                return summary
            time_values[key] = e["timestep"]
        if pvd_entries:
            print(f"  PVD {os.path.basename(pvd_file)}: {len(pvd_entries)} files, time "
                  f"{pvd_entries[0]['timestep']} – {pvd_entries[-1]['timestep']}")

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
            msg = f"--snapshot {snapshot_index} out of range: {len(files)} files match"
            print(f"  ERROR: {msg}")
            summary["errors"] = [msg]
            return summary
        print(f"  Extracting spatial snapshot from: {files[snapshot_index]}")
        vtu_data = parse_vtu_file(files[snapshot_index])
        try:
            if vtu_data["metadata"].get("error"):
                raise ValueError(vtu_data["metadata"]["error"])
            n_rows = write_spatial_snapshot(output_path, vtu_data, variables)
        except ValueError as exc:
            avail = sorted(set(vtu_data.get("cell_data", {})) | set(vtu_data.get("point_data", {})))
            msg = f"{files[snapshot_index]}: {exc}. Fields in file: {avail}"
            print(f"  ERROR: {msg}")
            summary["errors"] = [msg]
            return summary
        summary["mode"] = "snapshot"
    else:
        # Time series extraction
        print(f"  Extracting time series for variables: {variables}")
        try:
            ts = extract_timeseries(files, variables, probe_points, time_values)
        except ValueError as exc:
            print(f"  ERROR: {exc}")
            summary["errors"] = [str(exc)]
            return summary
        if ts.get("missing_variables"):
            avail = set()
            for fpath in files:
                v = parse_vtu_file(fpath)
                avail |= set(v.get("cell_data", {})) | set(v.get("point_data", {}))
            msg = (f"{'; '.join(ts['missing_variables'])} (checked {len(files)} files); "
                   f"fields present: {sorted(avail)}")
            print(f"  ERROR: {msg}")
            summary["errors"] = [msg]
            return summary
        for var, key in ts.get("matched", {}).items():
            if key != var:
                print(f"  Variable '{var}' read from field '{key}'")
        for var, fns in ts.get("files_without", {}).items():
            print(f"  WARNING: '{var}' not in {len(fns)} of {len(files)} files (NaN there): {fns[:5]}")
        for var, bad in ts.get("nonfinite", {}).items():
            print(f"  WARNING: '{var}' has non-finite values (file, count): {bad[:5]}; "
                  "NaN is left out of mean/min/max, +-inf is kept")
        if ts.get("time_from_filename"):
            print(f"  WARNING: {len(ts['time_from_filename'])} file(s) not in any .pvd; their "
                  f"'time' is the file number, not a time: {ts['time_from_filename']}")
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
