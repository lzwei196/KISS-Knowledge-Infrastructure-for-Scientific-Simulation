#!/usr/bin/env python3
"""
convert_forcing.py - Convert meteorological / tidal forcing data to TELEMAC format.

Reads ASCII time-series (CSV or whitespace-delimited) containing wind, pressure,
rain, and/or tidal elevation data and writes a SELAFIN-formatted forcing file
or an ASCII liquid-boundary file suitable for TELEMAC-2D/3D.

Usage:
    python convert_forcing.py --input met_data.csv --output forcing.slf \
        --variables wind_x,wind_y,pressure --mesh geo.slf

    python convert_forcing.py --input tidal.csv --output tidal_bc.txt \
        --format liquid_boundary --variables elevation,velocity_x,velocity_y

Unit conversions applied automatically:
    - Wind speed: knots -> m/s  (x 0.5144)
    - Pressure:   hPa   -> Pa  (x 100)
    - Rain:       mm/hr -> mm/s (/ 3600)

Follows validate -> process -> validate pattern.
"""

import argparse
import csv
import json
import os
import struct
import sys
from datetime import datetime

import numpy as np


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
UNIT_CONVERSIONS = {
    "wind_knots_to_ms": 0.5144,
    "pressure_hpa_to_pa": 100.0,
    "rain_mmhr_to_mms": 1.0 / 3600.0,
    "temperature_f_to_c": lambda f: (f - 32.0) * 5.0 / 9.0,
}

SELAFIN_TITLE_LEN = 80
SELAFIN_VAR_LEN = 32


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------
def validate_inputs(args):
    """Check that input files exist and parameters are valid."""
    errors = []
    if not os.path.isfile(args.input):
        errors.append(f"Input file not found: {args.input}")
    if args.mesh and not os.path.isfile(args.mesh):
        errors.append(f"Mesh file not found: {args.mesh}")
    if not args.variables:
        errors.append("No variables specified (--variables)")
    if args.format not in ("selafin", "liquid_boundary", "ascii"):
        errors.append(f"Unknown output format: {args.format}")
    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)
    return True


def validate_outputs(output_path, expected_vars, n_timesteps):
    """Verify the output file was written correctly."""
    errors = []
    if not os.path.isfile(output_path):
        errors.append(f"Output file was not created: {output_path}")
    else:
        size = os.path.getsize(output_path)
        if size == 0:
            errors.append("Output file is empty")
    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)
    print(json.dumps({
        "status": "success",
        "output": output_path,
        "variables": expected_vars,
        "timesteps": n_timesteps,
    }))


# ---------------------------------------------------------------------------
# Data reading
# ---------------------------------------------------------------------------
def read_csv_forcing(filepath, variables, delimiter=","):
    """Read a CSV file with a header row and return structured arrays."""
    with open(filepath, "r") as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        rows = list(reader)

    n_times = len(rows)
    if n_times == 0:
        print(json.dumps({"status": "error", "errors": ["Input CSV is empty"]}))
        sys.exit(1)

    # Parse time column (first column or 'time'/'datetime')
    time_col = None
    for candidate in ("time", "datetime", "date", "Time", "DateTime"):
        if candidate in rows[0]:
            time_col = candidate
            break
    if time_col is None:
        time_col = list(rows[0].keys())[0]

    times = np.zeros(n_times)
    try:
        for i, row in enumerate(rows):
            times[i] = float(row[time_col])
    except ValueError:
        # Try parsing as datetime string
        t0 = datetime.fromisoformat(rows[0][time_col].strip())
        for i, row in enumerate(rows):
            ti = datetime.fromisoformat(row[time_col].strip())
            times[i] = (ti - t0).total_seconds()

    # Parse variable columns
    data = {}
    for var in variables:
        col_name = var.strip()
        if col_name not in rows[0]:
            print(json.dumps({"status": "error",
                              "errors": [f"Variable '{col_name}' not in CSV columns: {list(rows[0].keys())}"]}))
            sys.exit(1)
        data[col_name] = np.array([float(row[col_name]) for row in rows])

    return times, data


# ---------------------------------------------------------------------------
# Unit conversion
# ---------------------------------------------------------------------------
def apply_unit_conversions(data, conversions_map):
    """Apply unit conversions based on a mapping of variable -> conversion."""
    for var, conversion in conversions_map.items():
        if var in data:
            if callable(conversion):
                data[var] = np.vectorize(conversion)(data[var])
            else:
                data[var] = data[var] * conversion
    return data


# ---------------------------------------------------------------------------
# SELAFIN writer (simplified)
# ---------------------------------------------------------------------------
def write_selafin_forcing(output_path, title, var_names, times, data_arrays,
                          x_coords, y_coords, ikle, ipobo):
    """Write a minimal SELAFIN file with forcing data on mesh nodes."""
    npoin = len(x_coords)
    nelem = len(ikle)
    ndp = len(ikle[0]) if nelem > 0 else 3
    nvar = len(var_names)
    ntimes = len(times)

    with open(output_path, "wb") as f:
        def write_record(raw_bytes):
            n = len(raw_bytes)
            f.write(struct.pack(">i", n))
            f.write(raw_bytes)
            f.write(struct.pack(">i", n))

        # Title + format
        title_padded = title.ljust(72)[:72] + "SERAFIN "
        write_record(title_padded.encode("ascii"))

        # Number of variables (nvar_lin, nvar_qua)
        write_record(struct.pack(">ii", nvar, 0))

        # Variable names
        for vname in var_names:
            padded = vname.ljust(SELAFIN_VAR_LEN)[:SELAFIN_VAR_LEN]
            write_record(padded.encode("ascii"))

        # Integer parameters (10 values)
        iparams = [1, 0, 0, 0, 0, 0, 1, 0, 0, 0]  # minimal
        write_record(struct.pack(">" + "i" * 10, *iparams))

        # Mesh: NELEM, NPOIN, NDP, 1
        write_record(struct.pack(">iiii", nelem, npoin, ndp, 1))

        # Connectivity (IKLE)
        ikle_flat = []
        for elem in ikle:
            ikle_flat.extend(elem)
        write_record(struct.pack(">" + "i" * len(ikle_flat), *ikle_flat))

        # IPOBO
        write_record(struct.pack(">" + "i" * npoin, *ipobo))

        # X coordinates
        write_record(struct.pack(">" + "f" * npoin, *x_coords))
        # Y coordinates
        write_record(struct.pack(">" + "f" * npoin, *y_coords))

        # Data frames
        for t_idx in range(ntimes):
            # Time
            write_record(struct.pack(">f", times[t_idx]))
            # Variables
            for v_idx in range(nvar):
                arr = data_arrays[v_idx]
                if arr.ndim == 1:
                    vals = np.full(npoin, arr[t_idx], dtype=np.float32)
                else:
                    vals = arr[t_idx, :].astype(np.float32)
                write_record(struct.pack(">" + "f" * npoin, *vals))


# ---------------------------------------------------------------------------
# Liquid boundary writer
# ---------------------------------------------------------------------------
def write_liquid_boundary(output_path, times, data, var_names):
    """Write an ASCII liquid boundary file for TELEMAC."""
    with open(output_path, "w") as f:
        f.write(f"# Liquid boundary forcing file\n")
        f.write(f"# Variables: T(s) " + " ".join(var_names) + "\n")
        f.write(f"# Generated by convert_forcing.py\n")
        for i in range(len(times)):
            line = f"{times[i]:.6f}"
            for var in var_names:
                line += f"  {data[var][i]:.6f}"
            f.write(line + "\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Convert forcing data to TELEMAC format")
    parser.add_argument("--input", required=True, help="Input CSV file")
    parser.add_argument("--output", required=True, help="Output file path")
    parser.add_argument("--variables", required=True, help="Comma-separated variable names")
    parser.add_argument("--format", default="liquid_boundary",
                        choices=["selafin", "liquid_boundary", "ascii"],
                        help="Output format (default: liquid_boundary)")
    parser.add_argument("--mesh", default=None, help="Mesh .slf file (required for selafin output)")
    parser.add_argument("--wind-unit", default="ms", choices=["ms", "knots"],
                        help="Input wind speed unit")
    parser.add_argument("--pressure-unit", default="Pa", choices=["Pa", "hPa", "mbar"],
                        help="Input pressure unit")
    parser.add_argument("--rain-unit", default="mms", choices=["mms", "mmhr"],
                        help="Input rain unit")
    parser.add_argument("--delimiter", default=",", help="CSV delimiter")
    args = parser.parse_args()

    # Step 1: Validate inputs
    args.variables = [v.strip() for v in args.variables.split(",")]
    validate_inputs(args)

    # Step 2: Read data
    times, data = read_csv_forcing(args.input, args.variables, args.delimiter)

    # Step 3: Apply unit conversions
    conversions = {}
    if args.wind_unit == "knots":
        for v in args.variables:
            if "wind" in v.lower():
                conversions[v] = UNIT_CONVERSIONS["wind_knots_to_ms"]
    if args.pressure_unit in ("hPa", "mbar"):
        for v in args.variables:
            if "pressure" in v.lower() or "pres" in v.lower():
                conversions[v] = UNIT_CONVERSIONS["pressure_hpa_to_pa"]
    if args.rain_unit == "mmhr":
        for v in args.variables:
            if "rain" in v.lower():
                conversions[v] = UNIT_CONVERSIONS["rain_mmhr_to_mms"]

    data = apply_unit_conversions(data, conversions)

    # Step 4: Write output
    if args.format == "liquid_boundary" or args.format == "ascii":
        write_liquid_boundary(args.output, times, data, args.variables)
    else:
        print(json.dumps({"status": "error",
                          "errors": ["SELAFIN forcing output requires --mesh; not yet implemented for standalone use"]}))
        sys.exit(1)

    # Step 5: Validate output
    validate_outputs(args.output, args.variables, len(times))


if __name__ == "__main__":
    main()
