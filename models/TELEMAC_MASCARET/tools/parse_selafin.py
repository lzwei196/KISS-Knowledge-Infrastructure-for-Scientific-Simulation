#!/usr/bin/env python3
"""
parse_selafin.py - Parse TELEMAC SELAFIN (.slf) result files to CSV.

Reads a SELAFIN/SERAFIN binary file and extracts time-series data for
specified variables and nodes, writing the output to CSV format.

Usage:
    # Extract all variables at all nodes for all timesteps
    python parse_selafin.py results.slf --output results.csv

    # Extract specific variables at specific node IDs
    python parse_selafin.py results.slf --variables U,V,H \
        --nodes 100,200,300 --output timeseries.csv

    # Extract a single timestep (spatial snapshot)
    python parse_selafin.py results.slf --timestep 100 --output snapshot.csv

    # Print file metadata only
    python parse_selafin.py results.slf --info

Supports both SERAFIN (single precision) and SERAFIND (double precision) formats.
Handles big-endian byte order (TELEMAC default).

Follows validate -> process -> validate pattern.
"""

import argparse
import csv
import json
import os
import struct
import sys

import numpy as np


# ---------------------------------------------------------------------------
# SELAFIN format constants
# ---------------------------------------------------------------------------
TITLE_LEN = 80
VAR_NAME_LEN = 32
ENDIAN = ">"  # big-endian default


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------
def validate_inputs(args):
    """Check input file exists and parameters are valid."""
    errors = []
    if not os.path.isfile(args.input):
        errors.append(f"Input SELAFIN file not found: {args.input}")
    if args.timestep is not None and args.timestep < 0:
        errors.append("Timestep index must be >= 0")
    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)
    return True


def validate_outputs(output_path, n_rows, n_cols):
    """Verify CSV output was written correctly."""
    errors = []
    if not os.path.isfile(output_path):
        errors.append(f"Output file not created: {output_path}")
    elif os.path.getsize(output_path) == 0:
        errors.append("Output CSV file is empty")
    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)
    print(json.dumps({
        "status": "success",
        "output": output_path,
        "rows": n_rows,
        "columns": n_cols,
        "size_bytes": os.path.getsize(output_path),
    }))


# ---------------------------------------------------------------------------
# SELAFIN reader
# ---------------------------------------------------------------------------
class SelafinReader:
    """Read SELAFIN/SERAFIN binary files."""

    def __init__(self, filepath):
        self.filepath = filepath
        self.f = None
        self.title = ""
        self.var_names = []
        self.nvar = 0
        self.iparams = []
        self.nelem = 0
        self.npoin = 0
        self.ndp = 0
        self.ikle = None
        self.ipobo = None
        self.x = None
        self.y = None
        self.precision = "f"  # 'f' = single, 'd' = double
        self.rs = 4  # bytes per real
        self.ntimes = 0
        self.data_offset = 0
        self._time_offsets = []

    def _read_record(self):
        """Read a Fortran unformatted record (big-endian)."""
        raw = self.f.read(4)
        if len(raw) < 4:
            return None
        n = struct.unpack(f"{ENDIAN}i", raw)[0]
        data = self.f.read(n)
        self.f.read(4)  # trailing marker
        return data

    def _detect_precision(self, title_bytes):
        """Detect single vs double precision from title string."""
        title_str = title_bytes.decode("ascii", errors="replace")
        if "SERAFIND" in title_str:
            self.precision = "d"
            self.rs = 8
        else:
            self.precision = "f"
            self.rs = 4

    def open(self):
        """Open and read the file header."""
        self.f = open(self.filepath, "rb")

        # Title
        title_bytes = self._read_record()
        self._detect_precision(title_bytes)
        self.title = title_bytes.decode("ascii", errors="replace").strip()

        # Number of variables
        rec = self._read_record()
        self.nvar = struct.unpack(f"{ENDIAN}ii", rec)[0]

        # Variable names
        self.var_names = []
        for _ in range(self.nvar):
            vn = self._read_record().decode("ascii", errors="replace").strip()
            self.var_names.append(vn)

        # Integer parameters
        rec = self._read_record()
        self.iparams = list(struct.unpack(f"{ENDIAN}" + "i" * 10, rec))

        # Date block (optional)
        if self.iparams[9] != 0:
            self._read_record()

        # Mesh topology
        rec = self._read_record()
        self.nelem, self.npoin, self.ndp, _ = struct.unpack(f"{ENDIAN}iiii", rec)

        # IKLE connectivity
        rec = self._read_record()
        ikle_flat = struct.unpack(f"{ENDIAN}" + "i" * (self.nelem * self.ndp), rec)
        self.ikle = np.array(ikle_flat).reshape(self.nelem, self.ndp)

        # IPOBO
        rec = self._read_record()
        self.ipobo = np.array(struct.unpack(f"{ENDIAN}" + "i" * self.npoin, rec))

        # Coordinates
        fmt = f"{ENDIAN}" + self.precision * self.npoin
        rec = self._read_record()
        self.x = np.array(struct.unpack(fmt, rec))
        rec = self._read_record()
        self.y = np.array(struct.unpack(fmt, rec))

        # Record current position (start of data frames)
        self.data_offset = self.f.tell()

        # Count timesteps by scanning
        self._scan_timesteps()

    def _scan_timesteps(self):
        """Scan the file to count timesteps and record offsets."""
        self.f.seek(self.data_offset)
        self._time_offsets = []
        record_size = 4 + self.rs + 4  # time record
        var_record_size = 4 + self.npoin * self.rs + 4  # per-variable record
        frame_size = record_size + self.nvar * var_record_size

        while True:
            pos = self.f.tell()
            raw = self.f.read(4)
            if len(raw) < 4:
                break
            self._time_offsets.append(pos)
            # Skip rest of frame
            self.f.seek(pos + frame_size)

        self.ntimes = len(self._time_offsets)

    def read_timestep(self, t_idx):
        """Read data for a single timestep. Returns (time, data_dict)."""
        if t_idx >= self.ntimes:
            return None, None

        self.f.seek(self._time_offsets[t_idx])

        # Time value
        rec = self._read_record()
        time_val = struct.unpack(f"{ENDIAN}{self.precision}", rec)[0]

        # Variable arrays
        data = {}
        fmt = f"{ENDIAN}" + self.precision * self.npoin
        for i in range(self.nvar):
            rec = self._read_record()
            vals = np.array(struct.unpack(fmt, rec))
            data[self.var_names[i]] = vals

        return time_val, data

    def close(self):
        if self.f:
            self.f.close()

    def get_info(self):
        """Return file metadata."""
        return {
            "title": self.title,
            "precision": "double" if self.precision == "d" else "single",
            "variables": self.var_names,
            "nvar": self.nvar,
            "npoin": self.npoin,
            "nelem": self.nelem,
            "ndp": self.ndp,
            "ntimes": self.ntimes,
            "x_range": [float(self.x.min()), float(self.x.max())],
            "y_range": [float(self.y.min()), float(self.y.max())],
        }


# ---------------------------------------------------------------------------
# CSV extraction
# ---------------------------------------------------------------------------
def extract_timeseries(reader, variables, node_ids, output_path):
    """Extract time series for selected variables and nodes to CSV."""
    if not variables:
        variables = reader.var_names

    # Validate variable names
    avail = set(reader.var_names)
    for v in variables:
        if v not in avail:
            # Try partial match
            matches = [a for a in avail if v.upper() in a.upper()]
            if not matches:
                print(f"WARNING: Variable '{v}' not found. Available: {reader.var_names}",
                      file=sys.stderr)

    if not node_ids:
        node_ids = list(range(reader.npoin))

    # Build header
    header = ["time"]
    for nid in node_ids:
        for var in variables:
            header.append(f"{var}_node{nid}")

    rows = []
    for t_idx in range(reader.ntimes):
        time_val, data = reader.read_timestep(t_idx)
        row = [time_val]
        for nid in node_ids:
            for var in variables:
                if var in data and nid < len(data[var]):
                    row.append(data[var][nid])
                else:
                    row.append(np.nan)
        rows.append(row)

    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)

    return len(rows), len(header)


def extract_snapshot(reader, variables, timestep, output_path):
    """Extract a single timestep as a spatial snapshot to CSV."""
    if not variables:
        variables = reader.var_names

    time_val, data = reader.read_timestep(timestep)
    if data is None:
        print(json.dumps({"status": "error",
                          "errors": [f"Timestep {timestep} out of range (max {reader.ntimes - 1})"]}))
        sys.exit(1)

    header = ["node_id", "x", "y"] + variables
    rows = []
    for nid in range(reader.npoin):
        row = [nid, reader.x[nid], reader.y[nid]]
        for var in variables:
            row.append(data.get(var, np.full(reader.npoin, np.nan))[nid])
        rows.append(row)

    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)

    return len(rows), len(header)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Parse TELEMAC SELAFIN files to CSV")
    parser.add_argument("input", help="Input SELAFIN (.slf) file")
    parser.add_argument("--output", "-o", default=None, help="Output CSV file")
    parser.add_argument("--variables", "-v", default=None,
                        help="Comma-separated variable names to extract")
    parser.add_argument("--nodes", "-n", default=None,
                        help="Comma-separated node IDs (0-based)")
    parser.add_argument("--timestep", "-t", type=int, default=None,
                        help="Extract single timestep (spatial snapshot)")
    parser.add_argument("--info", action="store_true",
                        help="Print file metadata and exit")
    args = parser.parse_args()

    # Step 1: Validate inputs
    validate_inputs(args)

    # Step 2: Open and read header
    reader = SelafinReader(args.input)
    reader.open()

    # Info mode
    if args.info:
        info = reader.get_info()
        print(json.dumps(info, indent=2))
        reader.close()
        return

    # Parse variable and node selections
    variables = [v.strip() for v in args.variables.split(",")] if args.variables else None
    node_ids = [int(n) for n in args.nodes.split(",")] if args.nodes else None

    # Default output name
    if args.output is None:
        base = os.path.splitext(args.input)[0]
        args.output = base + ".csv"

    # Step 3: Extract data
    if args.timestep is not None:
        n_rows, n_cols = extract_snapshot(reader, variables, args.timestep, args.output)
    else:
        n_rows, n_cols = extract_timeseries(reader, variables, node_ids, args.output)

    reader.close()

    # Step 4: Validate output
    validate_outputs(args.output, n_rows, n_cols)


if __name__ == "__main__":
    main()
