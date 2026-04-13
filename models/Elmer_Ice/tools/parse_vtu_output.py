#!/usr/bin/env python3
"""
parse_vtu_output.py — Parse Elmer/Ice VTU output files to CSV.

Reads VTK Unstructured Grid (.vtu) XML files produced by ElmerSolver and
extracts nodal variables to CSV format for analysis and validation.

CRITICAL ISSUES:
  - Velocity in VTU is in m/s (SI). Glaciology papers use m/a.
    Conversion: 1 m/s = 31556926 m/a. If not converted, velocity
    looks 10^7x too small when comparing to literature (dt_001).
  - Stress is in Pa. Glaciology uses MPa or kPa. Divide by 1e6 for MPa.
  - Multiple VTU files for time series: results0001.vtu, results0002.vtu, etc.
  - For parallel runs, each partition has separate VTU files:
    results_t0001_p0.vtu, results_t0001_p1.vtu, etc.

Expected input:
  One or more .vtu files from ElmerSolver output.

Expected output:
  CSV file with columns: node_id, x, y, z, var1, var2, ...
  Or time-series CSV: time, mean_var1, max_var1, min_var1, ...

Usage:
    python parse_vtu_output.py --vtu_dir ./run --pattern "results*.vtu" \
        --variables SSAVelocity,H,Zs,Zb --output results.csv \
        --convert_velocity_to_ma

    python parse_vtu_output.py --vtu_file results0001.vtu \
        --variables SSAVelocity,H --output snapshot.csv
"""

import argparse
import glob
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from collections import OrderedDict

import numpy as np


SEC_PER_YEAR = 31556926.0


def validate_inputs(args):
    """Check input arguments."""
    errors = []

    if args.vtu_file:
        if not os.path.isfile(args.vtu_file):
            errors.append(f"VTU file not found: {args.vtu_file}")
    elif args.vtu_dir:
        if not os.path.isdir(args.vtu_dir):
            errors.append(f"VTU directory not found: {args.vtu_dir}")
        else:
            pattern = os.path.join(args.vtu_dir, args.pattern)
            files = sorted(glob.glob(pattern))
            if not files:
                errors.append(f"No files matching {pattern}")
    else:
        errors.append("Must provide --vtu_file or --vtu_dir")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)


def parse_vtu_file(filepath):
    """Parse a single VTU file and extract point data.

    VTU format (XML):
    <VTKFile type="UnstructuredGrid">
      <UnstructuredGrid>
        <Piece NumberOfPoints="N" NumberOfCells="M">
          <Points>
            <DataArray type="Float64" NumberOfComponents="3">
              x1 y1 z1 x2 y2 z2 ...
            </DataArray>
          </Points>
          <PointData>
            <DataArray Name="variable" NumberOfComponents="1|3|6">
              v1 v2 v3 ...
            </DataArray>
          </PointData>
        </Piece>
      </UnstructuredGrid>
    </VTKFile>
    """
    tree = ET.parse(filepath)
    root = tree.getroot()

    result = {"coordinates": None, "variables": OrderedDict()}

    # Find the Piece element
    piece = root.find(".//{http://www.vtk.org/XMLFileFormat}Piece")
    if piece is None:
        # Try without namespace
        piece = root.find(".//Piece")
    if piece is None:
        raise ValueError(f"No Piece element found in {filepath}")

    n_points = int(piece.get("NumberOfPoints", 0))

    # Parse coordinates
    points = piece.find("Points") or piece.find(
        "{http://www.vtk.org/XMLFileFormat}Points")
    if points is not None:
        for da in points.iter():
            if da.tag.endswith("DataArray") or da.tag == "DataArray":
                text = da.text.strip()
                coords = np.array([float(x) for x in text.split()])
                n_comp = int(da.get("NumberOfComponents", 3))
                result["coordinates"] = coords.reshape(-1, n_comp)
                break

    # Parse point data
    point_data = piece.find("PointData") or piece.find(
        "{http://www.vtk.org/XMLFileFormat}PointData")
    if point_data is not None:
        for da in point_data:
            if da.tag.endswith("DataArray") or da.tag == "DataArray":
                name = da.get("Name", "unknown")
                n_comp = int(da.get("NumberOfComponents", 1))
                if da.text and da.text.strip():
                    values = np.array([float(x) for x in da.text.strip().split()])
                    if n_comp > 1:
                        values = values.reshape(-1, n_comp)
                    result["variables"][name] = {
                        "values": values,
                        "n_components": n_comp,
                    }

    result["n_points"] = n_points
    return result


def extract_timestep_from_filename(filename):
    """Extract time step number from VTU filename.

    Patterns: results0001.vtu, results_t0001.vtu, results_t0001_p0.vtu
    """
    base = os.path.basename(filename)
    match = re.search(r'(\d{4,})', base)
    if match:
        return int(match.group(1))
    return 0


def process_single(args, filepath, var_list):
    """Process a single VTU file and return data dict."""
    data = parse_vtu_file(filepath)

    rows = []
    coords = data["coordinates"]
    if coords is None:
        return [], []

    n_points = len(coords)
    headers = ["node_id", "x", "y", "z"]

    for i in range(n_points):
        row = [i + 1, coords[i, 0], coords[i, 1],
               coords[i, 2] if coords.shape[1] > 2 else 0.0]

        for varname in var_list:
            if varname in data["variables"]:
                vinfo = data["variables"][varname]
                if vinfo["n_components"] == 1:
                    val = float(vinfo["values"][i])
                    if args.convert_velocity_to_ma and "velocity" in varname.lower():
                        val *= SEC_PER_YEAR
                    row.append(val)
                else:
                    for c in range(vinfo["n_components"]):
                        val = float(vinfo["values"][i, c])
                        if args.convert_velocity_to_ma and "velocity" in varname.lower():
                            val *= SEC_PER_YEAR
                        row.append(val)
            else:
                row.append(np.nan)

        rows.append(row)

    # Build headers for multi-component variables
    for varname in var_list:
        if varname in data["variables"]:
            nc = data["variables"][varname]["n_components"]
            if nc == 1:
                unit = "_m_per_a" if (args.convert_velocity_to_ma and
                                      "velocity" in varname.lower()) else ""
                headers.append(f"{varname}{unit}")
            else:
                for c in range(nc):
                    headers.append(f"{varname}_{c+1}")
        else:
            headers.append(varname)

    return headers, rows


def process_timeseries(args, files, var_list):
    """Process multiple VTU files into a time-series summary."""
    headers = ["timestep", "time_years"]
    for varname in var_list:
        headers.extend([f"{varname}_mean", f"{varname}_max",
                        f"{varname}_min", f"{varname}_std"])

    rows = []
    for filepath in files:
        ts = extract_timestep_from_filename(filepath)
        data = parse_vtu_file(filepath)

        row = [ts, ts * args.dt_years if args.dt_years > 0 else ts]

        for varname in var_list:
            if varname in data["variables"]:
                vals = data["variables"][varname]["values"]
                if vals.ndim > 1:
                    # Use magnitude for vector fields
                    vals = np.sqrt(np.sum(vals**2, axis=1))
                if args.convert_velocity_to_ma and "velocity" in varname.lower():
                    vals = vals * SEC_PER_YEAR
                row.extend([
                    float(np.nanmean(vals)),
                    float(np.nanmax(vals)),
                    float(np.nanmin(vals)),
                    float(np.nanstd(vals)),
                ])
            else:
                row.extend([np.nan, np.nan, np.nan, np.nan])

        rows.append(row)

    return headers, rows


def validate_outputs(headers, rows, args):
    """Check parsed data for common issues."""
    warnings = []

    if not rows:
        warnings.append("No data rows produced — VTU files may be empty")
        return warnings

    data = np.array(rows)

    # Check for all-NaN columns
    for i, h in enumerate(headers):
        if i < len(headers) and i < data.shape[1]:
            col = data[:, i]
            if np.all(np.isnan(col.astype(float))):
                warnings.append(f"Column '{h}' is all NaN — variable not in VTU?")

    # Check velocity magnitudes
    for i, h in enumerate(headers):
        if "velocity" in h.lower() and "mean" in h.lower():
            vals = data[:, i].astype(float)
            max_v = np.nanmax(np.abs(vals))
            if args.convert_velocity_to_ma and max_v > 20000:
                warnings.append(f"Max velocity = {max_v:.0f} m/a — "
                                "unrealistically fast for ice")
            elif not args.convert_velocity_to_ma and max_v < 1e-4:
                warnings.append(f"Max velocity = {max_v:.2e} m/s — "
                                "did you forget --convert_velocity_to_ma?")

    for w in warnings:
        print(f"WARNING: {w}", file=sys.stderr)
    return warnings


def main():
    parser = argparse.ArgumentParser(
        description="Parse Elmer/Ice VTU output to CSV")
    parser.add_argument("--vtu_file", type=str, default=None,
                        help="Single VTU file to parse")
    parser.add_argument("--vtu_dir", type=str, default=None,
                        help="Directory containing VTU files")
    parser.add_argument("--pattern", type=str, default="results*.vtu",
                        help="Glob pattern for VTU files in directory")
    parser.add_argument("--variables", type=str,
                        default="SSAVelocity,H,Zs,Zb",
                        help="Comma-separated list of variables to extract")
    parser.add_argument("--output", type=str, required=True,
                        help="Output CSV file path")
    parser.add_argument("--convert_velocity_to_ma", action="store_true",
                        help="Convert velocity from m/s to m/a")
    parser.add_argument("--timeseries", action="store_true",
                        help="Produce time-series summary instead of snapshot")
    parser.add_argument("--dt_years", type=float, default=1.0,
                        help="Time step in years (for time axis in timeseries)")

    args = parser.parse_args()
    validate_inputs(args)

    var_list = [v.strip() for v in args.variables.split(",")]

    if args.vtu_file:
        headers, rows = process_single(args, args.vtu_file, var_list)
    else:
        pattern = os.path.join(args.vtu_dir, args.pattern)
        files = sorted(glob.glob(pattern))

        if args.timeseries:
            headers, rows = process_timeseries(args, files, var_list)
        else:
            # Parse last file (final state)
            headers, rows = process_single(args, files[-1], var_list)

    warnings = validate_outputs(headers, rows, args)

    # Write CSV
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w") as f:
        f.write(",".join(headers) + "\n")
        for row in rows:
            f.write(",".join(str(v) for v in row) + "\n")

    status = {
        "status": "success",
        "output_file": args.output,
        "n_rows": len(rows),
        "n_columns": len(headers),
        "variables_found": [h for h in headers if h not in
                            ["node_id", "x", "y", "z", "timestep", "time_years"]],
        "warnings": warnings,
    }
    print(json.dumps(status, indent=2), file=sys.stderr)


if __name__ == "__main__":
    main()
