#!/usr/bin/env python3
"""Parse PorePy VTU/VTK output files and extract results to CSV.

This tool reads PorePy's VTU output files (produced by pp.Exporter) and
extracts scalar/vector fields into flat CSV format for analysis, plotting,
and comparison with observations.

CRITICAL NOTES:
- PorePy stores results in SI units (Pa, m, K, m³/s)
- VTU files are per-subdomain (matrix, fractures, intersections)
- Time series are collected via .pvd files
- Cell data is at cell centers; face data requires interpolation

Usage:
    python parse_porepy_output.py --input-dir porepy_output/ --output results.csv
    python parse_porepy_output.py --pvd-file data.pvd --variables pressure,displacement \\
        --output timeseries.csv
    python parse_porepy_output.py --vtu-file domain_0.vtu --output snapshot.csv
"""

import argparse
import csv
import json
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def validate_inputs(args: argparse.Namespace) -> List[str]:
    """Validate input arguments."""
    errors = []

    if args.input_dir and not os.path.isdir(args.input_dir):
        errors.append(f"Input directory not found: {args.input_dir}")

    if args.pvd_file and not os.path.isfile(args.pvd_file):
        errors.append(f"PVD file not found: {args.pvd_file}")

    if args.vtu_file and not os.path.isfile(args.vtu_file):
        errors.append(f"VTU file not found: {args.vtu_file}")

    if not args.input_dir and not args.pvd_file and not args.vtu_file:
        errors.append("Must specify --input-dir, --pvd-file, or --vtu-file")

    return errors


def find_vtu_files(directory: str) -> List[str]:
    """Recursively find all VTU files in a directory."""
    vtu_files = sorted(Path(directory).rglob("*.vtu"))
    return [str(f) for f in vtu_files]


def parse_pvd_file(pvd_path: str) -> List[Dict[str, Any]]:
    """Parse a PVD (ParaView Data) file to get timestep→file mapping.

    PVD format:
    <VTKFile type="Collection">
      <Collection>
        <DataSet timestep="0.0" file="data_0000.vtu"/>
        <DataSet timestep="3600.0" file="data_0001.vtu"/>
      </Collection>
    </VTKFile>
    """
    tree = ET.parse(pvd_path)
    root = tree.getroot()
    collection = root.find(".//Collection")
    if collection is None:
        return []

    entries = []
    base_dir = os.path.dirname(pvd_path)
    for ds in collection.findall("DataSet"):
        timestep = float(ds.get("timestep", 0))
        filepath = ds.get("file", "")
        full_path = os.path.join(base_dir, filepath)
        entries.append({"timestep": timestep, "file": full_path})

    return entries


def parse_vtu_file(vtu_path: str,
                   variables: Optional[List[str]] = None) -> Dict[str, Any]:
    """Parse a VTU (VTK Unstructured Grid) file.

    Extracts:
    - Cell center coordinates
    - Cell data arrays (pressure, displacement, etc.)
    - Point data if available

    Returns:
        Dictionary with arrays and metadata.
    """
    try:
        import numpy as np
    except ImportError:
        return {"error": "numpy required for VTU parsing"}

    result = {
        "file": vtu_path,
        "cell_data": {},
        "point_data": {},
        "coordinates": {"x": [], "y": [], "z": []},
        "n_cells": 0,
        "n_points": 0,
    }

    try:
        tree = ET.parse(vtu_path)
        root = tree.getroot()
        grid = root.find(".//UnstructuredGrid")
        if grid is None:
            # Try PolyData format
            grid = root.find(".//PolyData")
        if grid is None:
            return {"error": f"No grid data found in {vtu_path}"}

        piece = grid.find("Piece")
        if piece is None:
            return {"error": f"No Piece element in {vtu_path}"}

        result["n_cells"] = int(piece.get("NumberOfCells", 0))
        result["n_points"] = int(piece.get("NumberOfPoints", 0))

        # Parse point coordinates
        points_elem = piece.find(".//Points/DataArray")
        if points_elem is not None and points_elem.text:
            coords = [float(v) for v in points_elem.text.strip().split()]
            n_components = int(points_elem.get("NumberOfComponents", 3))
            for i in range(0, len(coords), n_components):
                result["coordinates"]["x"].append(coords[i] if i < len(coords) else 0)
                result["coordinates"]["y"].append(
                    coords[i + 1] if i + 1 < len(coords) else 0
                )
                result["coordinates"]["z"].append(
                    coords[i + 2] if i + 2 < len(coords) else 0
                )

        # Parse cell data
        cell_data_elem = piece.find("CellData")
        if cell_data_elem is not None:
            for arr in cell_data_elem.findall("DataArray"):
                name = arr.get("Name", "unknown")
                if variables and name not in variables:
                    continue
                if arr.text:
                    values = [float(v) for v in arr.text.strip().split()]
                    result["cell_data"][name] = values

        # Parse point data
        point_data_elem = piece.find("PointData")
        if point_data_elem is not None:
            for arr in point_data_elem.findall("DataArray"):
                name = arr.get("Name", "unknown")
                if variables and name not in variables:
                    continue
                if arr.text:
                    values = [float(v) for v in arr.text.strip().split()]
                    result["point_data"][name] = values

    except ET.ParseError as e:
        result["error"] = f"XML parse error: {e}"
    except Exception as e:
        result["error"] = f"Error parsing VTU: {e}"

    return result


def compute_cell_centers(vtu_data: Dict) -> List[Tuple[float, float, float]]:
    """Approximate cell centers from point coordinates.

    For proper cell centers, PorePy stores them in the Grid object.
    This is an approximation from VTU point data.
    """
    coords = vtu_data.get("coordinates", {})
    x = coords.get("x", [])
    y = coords.get("y", [])
    z = coords.get("z", [])

    if not x:
        return []

    # Simple approximation: use point coordinates directly
    # (actual cell centers would require connectivity info)
    centers = []
    for i in range(len(x)):
        centers.append((x[i], y[i], z[i]))
    return centers


def process(
    vtu_files: List[str],
    variables: Optional[List[str]],
    timesteps: Optional[List[float]] = None,
) -> List[Dict[str, Any]]:
    """Process VTU files and extract data.

    Returns:
        List of record dictionaries for CSV export.
    """
    records = []

    for i, vtu_file in enumerate(vtu_files):
        timestep = timesteps[i] if timesteps and i < len(timesteps) else i
        data = parse_vtu_file(vtu_file, variables)

        if "error" in data:
            records.append({
                "timestep": timestep,
                "file": vtu_file,
                "error": data["error"],
            })
            continue

        # Create one record per cell
        n_cells = data.get("n_cells", 0)
        cell_data = data.get("cell_data", {})

        # Determine record count from data arrays
        if cell_data:
            first_key = next(iter(cell_data))
            n_records = len(cell_data[first_key])
        else:
            n_records = n_cells

        for j in range(n_records):
            record = {
                "timestep_s": timestep,
                "cell_id": j,
                "file": os.path.basename(vtu_file),
            }
            for var_name, values in cell_data.items():
                if j < len(values):
                    record[var_name] = values[j]
            records.append(record)

    return records


def validate_outputs(records: List[Dict]) -> List[str]:
    """Validate parsed output data."""
    warnings = []

    if not records:
        warnings.append("WARNING: No data records extracted from VTU files.")
        return warnings

    # Check for common issues
    n_records = len(records)
    warnings.append(f"Extracted {n_records} records from VTU files.")

    # Check for NaN values
    nan_count = 0
    for rec in records:
        for key, val in rec.items():
            if isinstance(val, float) and (val != val):  # NaN check
                nan_count += 1
    if nan_count > 0:
        warnings.append(
            f"CRITICAL: {nan_count} NaN values found in output. "
            f"Simulation may have diverged."
        )

    # Check pressure ranges (if present)
    pressures = [r.get("pressure", None) for r in records if "pressure" in r]
    if pressures:
        p_min = min(p for p in pressures if p is not None)
        p_max = max(p for p in pressures if p is not None)
        if abs(p_max) < 1:
            warnings.append(
                f"WARNING: Max |pressure| = {p_max:.2e} Pa — very low. "
                f"Check if results are in user units rather than SI."
            )

    return warnings


def write_csv(records: List[Dict], output_path: str) -> None:
    """Write records to CSV file."""
    if not records:
        return

    # Collect all field names
    fieldnames = []
    for rec in records:
        for key in rec.keys():
            if key not in fieldnames:
                fieldnames.append(key)

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)


def main():
    parser = argparse.ArgumentParser(
        description="Parse PorePy VTU output to CSV.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--input-dir", help="Directory containing VTU files")
    parser.add_argument("--pvd-file", help="PVD collection file for time series")
    parser.add_argument("--vtu-file", help="Single VTU file to parse")
    parser.add_argument("--output", required=True, help="Output CSV file path")
    parser.add_argument(
        "--variables", help="Comma-separated list of variables to extract"
    )
    args = parser.parse_args()

    # Step 1: Validate inputs
    errors = validate_inputs(args)
    if errors:
        print(json.dumps({"status": "error", "errors": errors}, indent=2))
        sys.exit(1)

    # Step 2: Collect VTU files
    vtu_files = []
    timesteps = None

    if args.pvd_file:
        pvd_entries = parse_pvd_file(args.pvd_file)
        vtu_files = [e["file"] for e in pvd_entries]
        timesteps = [e["timestep"] for e in pvd_entries]
    elif args.vtu_file:
        vtu_files = [args.vtu_file]
    elif args.input_dir:
        vtu_files = find_vtu_files(args.input_dir)

    if not vtu_files:
        print(json.dumps({"status": "error", "errors": ["No VTU files found"]},
                          indent=2))
        sys.exit(1)

    # Parse variable list
    variables = None
    if args.variables:
        variables = [v.strip() for v in args.variables.split(",")]

    # Step 3: Process
    records = process(vtu_files, variables, timesteps)

    # Step 4: Validate outputs
    warnings = validate_outputs(records)

    # Step 5: Write CSV
    write_csv(records, args.output)

    print(json.dumps({
        "status": "success",
        "output_file": args.output,
        "n_files": len(vtu_files),
        "n_records": len(records),
        "variables": list(records[0].keys()) if records else [],
        "warnings": warnings,
    }, indent=2))


if __name__ == "__main__":
    main()
