#!/usr/bin/env python3
"""
parse_ogs_output.py — Parse OpenGeoSys VTU/PVD output to CSV time series.

Reads OGS output (VTU files indexed by a PVD collection file) and extracts
time series at specified points, or spatial statistics per timestep.
Outputs CSV for analysis and JSON summary for pipeline integration.

CRITICAL CONSTRAINTS:
  - VTU files use VTK XML format — requires meshio or vtk library
  - PVD file is XML index linking timesteps to VTU files
  - OGS output variables are in SI units (Pa, K, m, m/s)
  - Point extraction uses nearest-node interpolation
  - Large 3D simulations may produce multi-GB VTU files

Usage:
    python parse_ogs_output.py --pvd_file results/result.pvd \\
        --variables pressure,v --point "50.0,25.0" --output timeseries.csv
    python parse_ogs_output.py --pvd_file results/result.pvd \\
        --variables pressure --stats --output spatial_stats.csv
"""

import argparse
import csv
import json
import os
import re
import sys
from xml.etree import ElementTree as ET

import numpy as np


def validate_inputs(args):
    """Validate input arguments."""
    errors = []

    if not os.path.isfile(args.pvd_file):
        # Try to find VTU files directly
        vtu_dir = os.path.dirname(args.pvd_file)
        if not os.path.isdir(vtu_dir):
            errors.append(f"PVD file not found and directory doesn't exist: {args.pvd_file}")
    if args.point:
        try:
            coords = [float(x) for x in args.point.split(",")]
            if len(coords) not in (2, 3):
                errors.append("Point must have 2 or 3 coordinates (x,y or x,y,z)")
        except ValueError:
            errors.append(f"Invalid point coordinates: {args.point}")

    if not args.variables:
        errors.append("At least one variable name required (--variables)")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)


def parse_pvd(pvd_path):
    """Parse PVD file to get list of (timestep, time, vtu_path) tuples."""
    tree = ET.parse(pvd_path)
    root = tree.getroot()

    pvd_dir = os.path.dirname(os.path.abspath(pvd_path))
    timesteps = []

    for dataset in root.iter("DataSet"):
        ts = dataset.get("timestep", "0")
        time_val = float(ts)
        vtu_file = dataset.get("file", "")

        # Resolve relative path
        if not os.path.isabs(vtu_file):
            vtu_file = os.path.join(pvd_dir, vtu_file)

        timesteps.append({
            "time_s": time_val,
            "file": vtu_file,
        })

    return sorted(timesteps, key=lambda x: x["time_s"])


def find_vtu_files(directory, prefix=None):
    """Find VTU files by pattern when PVD is missing."""
    import glob
    pattern = os.path.join(directory, "*.vtu")
    files = sorted(glob.glob(pattern))

    timesteps = []
    for f in files:
        match = re.search(r"_ts_(\d+)_t_([\d.eE+-]+)\.vtu", f)
        if match:
            timesteps.append({
                "time_s": float(match.group(2)),
                "file": f,
            })

    return sorted(timesteps, key=lambda x: x["time_s"])


def read_vtu_simple(vtu_path):
    """Read VTU file using basic XML parsing (no meshio dependency).

    Returns dict with 'points' (Nx3 array), 'point_data' (dict of arrays),
    and 'cell_data' (dict of arrays).
    """
    tree = ET.parse(vtu_path)
    root = tree.getroot()

    result = {"points": None, "point_data": {}, "cell_data": {}}

    # Find UnstructuredGrid/Piece
    piece = root.find(".//Piece")
    if piece is None:
        return result

    n_points = int(piece.get("NumberOfPoints", 0))

    # Parse points
    points_elem = piece.find(".//Points/DataArray")
    if points_elem is not None and points_elem.text:
        values = np.array([float(x) for x in points_elem.text.split()])
        n_components = int(points_elem.get("NumberOfComponents", 3))
        result["points"] = values.reshape(-1, n_components)

    # Parse point data
    point_data = piece.find("PointData")
    if point_data is not None:
        for da in point_data.findall("DataArray"):
            name = da.get("Name", "unknown")
            n_comp = int(da.get("NumberOfComponents", 1))
            if da.text:
                try:
                    values = np.array([float(x) for x in da.text.split()])
                    if n_comp > 1:
                        values = values.reshape(-1, n_comp)
                    result["point_data"][name] = values
                except ValueError:
                    pass

    # Parse cell data
    cell_data = piece.find("CellData")
    if cell_data is not None:
        for da in cell_data.findall("DataArray"):
            name = da.get("Name", "unknown")
            n_comp = int(da.get("NumberOfComponents", 1))
            if da.text:
                try:
                    values = np.array([float(x) for x in da.text.split()])
                    if n_comp > 1:
                        values = values.reshape(-1, n_comp)
                    result["cell_data"][name] = values
                except ValueError:
                    pass

    return result


def read_vtu_meshio(vtu_path):
    """Read VTU file using meshio library."""
    try:
        import meshio
        mesh = meshio.read(vtu_path)
        return {
            "points": mesh.points,
            "point_data": dict(mesh.point_data),
            "cell_data": {k: v[0] if isinstance(v, list) and len(v) == 1 else v
                          for k, v in mesh.cell_data.items()},
        }
    except ImportError:
        return read_vtu_simple(vtu_path)


def find_nearest_node(points, target):
    """Find index of nearest node to target coordinates."""
    target = np.array(target)
    if len(target) == 2:
        # 2D: only compare x,y
        dists = np.sqrt(np.sum((points[:, :2] - target[:2]) ** 2, axis=1))
    else:
        dists = np.sqrt(np.sum((points[:, :3] - target[:3]) ** 2, axis=1))
    idx = np.argmin(dists)
    return idx, float(dists[idx])


def extract_point_timeseries(timesteps, variables, target_point):
    """Extract time series at a specific point."""
    target = [float(x) for x in target_point.split(",")]

    records = []
    nearest_idx = None
    nearest_dist = None

    for i, ts in enumerate(timesteps):
        if not os.path.isfile(ts["file"]):
            continue

        try:
            data = read_vtu_meshio(ts["file"])
        except Exception as e:
            continue

        if data["points"] is None:
            continue

        # Find nearest node (only on first timestep, assume mesh is static)
        if nearest_idx is None:
            nearest_idx, nearest_dist = find_nearest_node(data["points"], target)

        record = {"time_s": ts["time_s"], "time_days": ts["time_s"] / 86400.0}

        for var in variables:
            if var in data["point_data"]:
                val = data["point_data"][var]
                if val.ndim == 1:
                    record[var] = float(val[nearest_idx])
                else:
                    # Vector variable: extract magnitude and components
                    vec = val[nearest_idx]
                    record[f"{var}_magnitude"] = float(np.linalg.norm(vec))
                    for j, comp in enumerate(["x", "y", "z"][:len(vec)]):
                        record[f"{var}_{comp}"] = float(vec[j])
            elif var in data["cell_data"]:
                record[f"{var}_cell"] = "cell_data_not_interpolated"

        records.append(record)

    return records, nearest_idx, nearest_dist


def extract_spatial_stats(timesteps, variables):
    """Extract spatial statistics (min, max, mean, std) per timestep."""
    records = []

    for ts in timesteps:
        if not os.path.isfile(ts["file"]):
            continue

        try:
            data = read_vtu_meshio(ts["file"])
        except Exception:
            continue

        record = {"time_s": ts["time_s"], "time_days": ts["time_s"] / 86400.0}

        for var in variables:
            values = None
            if var in data["point_data"]:
                values = data["point_data"][var]
            elif var in data["cell_data"]:
                values = data["cell_data"][var]

            if values is not None:
                if values.ndim > 1:
                    magnitudes = np.linalg.norm(values, axis=1)
                    record[f"{var}_min"] = float(np.min(magnitudes))
                    record[f"{var}_max"] = float(np.max(magnitudes))
                    record[f"{var}_mean"] = float(np.mean(magnitudes))
                    record[f"{var}_std"] = float(np.std(magnitudes))
                else:
                    record[f"{var}_min"] = float(np.min(values))
                    record[f"{var}_max"] = float(np.max(values))
                    record[f"{var}_mean"] = float(np.mean(values))
                    record[f"{var}_std"] = float(np.std(values))

        records.append(record)

    return records


def process(args):
    """Main processing: parse VTU output files."""
    warnings = []

    variables = [v.strip() for v in args.variables.split(",")]

    # Get timestep list
    if os.path.isfile(args.pvd_file):
        timesteps = parse_pvd(args.pvd_file)
    else:
        vtu_dir = os.path.dirname(args.pvd_file)
        timesteps = find_vtu_files(vtu_dir)
        if timesteps:
            warnings.append(f"PVD file not found, discovered {len(timesteps)} VTU files by pattern")
        else:
            return {"status": "error", "errors": ["No PVD or VTU files found"]}

    if len(timesteps) == 0:
        return {"status": "error", "errors": ["No timesteps found in PVD file"]}

    # Extract data
    if args.point:
        records, node_idx, node_dist = extract_point_timeseries(timesteps, variables, args.point)
        extraction_info = {
            "mode": "point",
            "target_point": args.point,
            "nearest_node_index": int(node_idx) if node_idx is not None else None,
            "nearest_node_distance_m": node_dist,
        }
        if node_dist and node_dist > 1.0:
            warnings.append(f"Nearest node is {node_dist:.2f} m from target point")
    else:
        records = extract_spatial_stats(timesteps, variables)
        extraction_info = {"mode": "spatial_stats"}

    # Write CSV
    if records:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        fieldnames = list(records[0].keys())
        with open(args.output, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(records)

    result = {
        "status": "success",
        "pvd_file": args.pvd_file,
        "output": args.output,
        "variables": variables,
        "extraction": extraction_info,
        "n_timesteps": len(timesteps),
        "n_records": len(records),
        "time_range_s": [timesteps[0]["time_s"], timesteps[-1]["time_s"]],
        "time_range_days": [timesteps[0]["time_s"] / 86400.0, timesteps[-1]["time_s"] / 86400.0],
        "warnings": warnings,
    }

    # Add summary stats for each variable
    if records:
        for var in variables:
            vals = []
            for r in records:
                if var in r:
                    vals.append(r[var])
                elif f"{var}_mean" in r:
                    vals.append(r[f"{var}_mean"])
            if vals:
                result[f"{var}_summary"] = {
                    "min": float(np.min(vals)),
                    "max": float(np.max(vals)),
                    "mean": float(np.mean(vals)),
                }

    return result


def validate_outputs(result):
    """Validate parsed outputs."""
    if result["status"] != "success":
        return result

    warnings = result.get("warnings", [])

    if result["n_records"] == 0:
        warnings.append("No records extracted — check variable names and VTU contents")

    if result["n_records"] < result["n_timesteps"]:
        warnings.append(
            f"Only {result['n_records']}/{result['n_timesteps']} timesteps parsed — "
            "some VTU files may be missing or unreadable"
        )

    result["warnings"] = warnings
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Parse OGS VTU/PVD output to CSV time series"
    )
    parser.add_argument("--pvd_file", type=str, required=True,
                        help="Path to PVD collection file or directory with VTU files")
    parser.add_argument("--variables", type=str, required=True,
                        help="Comma-separated variable names (e.g., pressure,v,temperature)")
    parser.add_argument("--point", type=str, default=None,
                        help="Point coordinates for extraction: 'x,y' or 'x,y,z'")
    parser.add_argument("--stats", action="store_true",
                        help="Extract spatial statistics instead of point values")
    parser.add_argument("--output", type=str, required=True,
                        help="Output CSV file path")

    args = parser.parse_args()

    validate_inputs(args)
    result = process(args)
    result = validate_outputs(result)

    output_json = json.dumps(result, indent=2)

    summary_path = args.output.replace(".csv", "_summary.json")
    os.makedirs(os.path.dirname(summary_path) or ".", exist_ok=True)
    with open(summary_path, "w") as f:
        f.write(output_json)

    print(f"Output written to {args.output}", file=sys.stderr)
    print(output_json)


if __name__ == "__main__":
    main()
