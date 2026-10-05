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
import base64
import glob
import json
import os
import re
import struct
import sys
import xml.etree.ElementTree as ET
from collections import OrderedDict

import numpy as np


SEC_PER_YEAR = 31556926.0

# VTK XML data types -> numpy
VTK_TYPES = {"Float32": "f4", "Float64": "f8", "Int8": "i1", "UInt8": "u1",
             "Int16": "i2", "UInt16": "u2", "Int32": "i4", "UInt32": "u4",
             "Int64": "i8", "UInt64": "u8"}


def _local(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _child(elem, name):
    for c in elem:
        if _local(c.tag) == name:
            return c
    return None


def _load_vtu(filepath):
    """Return (xml root, appended bytes or None, appended encoding or None).

    Elmer's default VTU keeps the arrays in <AppendedData encoding="raw">, which
    is binary and not valid XML; only the XML part before it is parsed.
    """
    with open(filepath, "rb") as f:
        raw = f.read()
    m = re.search(rb"<AppendedData\b[^>]*>", raw)
    if m is None:
        return ET.fromstring(raw), None, None
    tag = m.group(0).decode("latin-1")
    enc = re.search(r"""encoding\s*=\s*["']([^"']+)["']""", tag)
    enc = enc.group(1) if enc else "raw"
    us = raw.find(b"_", m.end())
    if us < 0:
        raise ValueError(f"{filepath}: AppendedData has no '_' marker")
    end = raw.rfind(b"</AppendedData>")
    if end < us:
        raise ValueError(f"{filepath}: AppendedData is not closed (truncated file?)")
    root = ET.fromstring(raw[:m.start()] + b"</VTKFile>")
    # payload = bytes between '_' and the closing tag (binary bytes are not stripped)
    return root, raw[us + 1:end], enc


class _VtuDecoder:
    def __init__(self, root, appended, encoding, filepath):
        if root.get("compressor"):
            raise ValueError(f"{filepath}: compressed VTU ({root.get('compressor')}) "
                             "is not supported")
        self.end = "<" if root.get("byte_order", "LittleEndian") == "LittleEndian" else ">"
        htype = root.get("header_type", "UInt32")
        if htype not in ("UInt32", "UInt64"):
            raise ValueError(f"{filepath}: unsupported header_type {htype}")
        self.hfmt = self.end + ("I" if htype == "UInt32" else "Q")
        self.hsize = struct.calcsize(self.hfmt)
        self.appended, self.encoding, self.path = appended, encoding, filepath

    def values(self, da):
        """DataArray -> 1-D float64 array (None if it holds no data)."""
        fmt = da.get("format", "ascii")
        vtype = da.get("type", "Float64")
        if fmt == "ascii":
            if not (da.text and da.text.strip()):
                return None
            return np.array([float(x) for x in da.text.strip().split()])
        if vtype not in VTK_TYPES:
            raise ValueError(f"{self.path}: unsupported DataArray type {vtype}")
        dtype = np.dtype(self.end + VTK_TYPES[vtype])
        if fmt == "binary":
            text = "".join((da.text or "").split())
            blob = base64.b64decode(text)
            n = struct.unpack(self.hfmt, blob[:self.hsize])[0]
            data = blob[self.hsize:self.hsize + n]
            if len(data) != n:  # header and data base64-encoded separately
                hlen = 4 * ((self.hsize + 2) // 3)
                n = struct.unpack(self.hfmt, base64.b64decode(text[:hlen])[:self.hsize])[0]
                data = base64.b64decode(text[hlen:])[:n]
            if len(data) != n:
                raise ValueError(f"{self.path}: truncated binary DataArray {da.get('Name')}")
        elif fmt == "appended":
            if self.appended is None:
                raise ValueError(f"{self.path}: DataArray is 'appended' but no AppendedData")
            if self.encoding != "raw":
                raise ValueError(f"{self.path}: AppendedData encoding '{self.encoding}' "
                                 "is not supported (only raw)")
            off = int(da.get("offset", "0"))
            if off < 0 or off + self.hsize > len(self.appended):
                raise ValueError(f"{self.path}: offset {off} out of range")
            n = struct.unpack(self.hfmt, self.appended[off:off + self.hsize])[0]
            if off + self.hsize + n > len(self.appended):
                raise ValueError(f"{self.path}: appended DataArray {da.get('Name')} runs past "
                                 "the end of AppendedData (truncated or corrupt file)")
            data = self.appended[off + self.hsize:off + self.hsize + n]
            if len(data) != n:
                raise ValueError(f"{self.path}: truncated appended DataArray {da.get('Name')}")
        else:
            raise ValueError(f"{self.path}: unsupported DataArray format {fmt}")
        if n % dtype.itemsize:
            raise ValueError(f"{self.path}: byte count {n} is not a multiple of {vtype}")
        return np.frombuffer(data, dtype=dtype).astype(np.float64)


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
    root, appended, encoding = _load_vtu(filepath)
    dec = _VtuDecoder(root, appended, encoding, filepath)

    result = {"coordinates": None, "variables": OrderedDict()}

    # Find the Piece element
    piece = next((e for e in root.iter() if _local(e.tag) == "Piece"), None)
    if piece is None:
        raise ValueError(f"No Piece element found in {filepath}")

    n_points = int(piece.get("NumberOfPoints", 0))

    # Parse coordinates
    points = _child(piece, "Points")
    if points is not None:
        for da in points.iter():
            if _local(da.tag) == "DataArray":
                coords = dec.values(da)
                if coords is not None:
                    n_comp = int(da.get("NumberOfComponents", 3))
                    if coords.size != n_points * n_comp:
                        raise ValueError(f"{filepath}: Points has {coords.size} values, "
                                         f"expected {n_points} x {n_comp}")
                    result["coordinates"] = coords.reshape(-1, n_comp)
                break

    # Parse point data
    point_data = _child(piece, "PointData")
    if point_data is not None:
        for da in point_data:
            if _local(da.tag) == "DataArray":
                name = da.get("Name", "unknown")
                n_comp = int(da.get("NumberOfComponents", 1))
                values = dec.values(da)
                if values is not None:
                    if values.size != n_points * n_comp:
                        raise ValueError(f"{filepath}: {name} has {values.size} values, "
                                         f"expected {n_points} x {n_comp}")
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
