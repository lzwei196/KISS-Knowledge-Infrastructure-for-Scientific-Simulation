#!/usr/bin/env python3
"""
parse_dart_output.py — Extract DART NetCDF output to CSV for analysis.

CRITICAL:
  - DART output files are NetCDF. Requires netCDF4 or xarray Python package.
  - State variable names depend on the model (e.g., 'state' for Lorenz,
    'T', 'U', 'V' for CAM).
  - The 'time' dimension in DART output may be in days since a model epoch,
    NOT a standard calendar. Check the time:units attribute.
  - Missing data is stored as -888888.0 — do NOT treat as valid data.
  - DART writes separate files for mean, sd, and individual members.
    Parse the _mean.nc and _sd.nc files for ensemble statistics.

Output format: CSV with columns for time, variable, location, value.

Usage:
  python parse_dart_output.py \\
      --input preassim_mean.nc \\
      --output preassim_mean.csv

  python parse_dart_output.py \\
      --input analysis_mean.nc \\
      --output analysis_mean.csv \\
      --variables state

  python parse_dart_output.py \\
      --input obs_seq.final \\
      --output obs_diagnostics.csv \\
      --parse_obs_seq

  python parse_dart_output.py \\
      --input obs_diag_output.nc \\
      --output obs_diag.csv \\
      --variables bias rmse totalspread
"""

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np

try:
    import netCDF4
    HAS_NETCDF4 = True
except ImportError:
    HAS_NETCDF4 = False

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False


DART_MISSING = -888888.0


def validate_inputs(args):
    """Pre-processing validation."""
    errors = []

    if not os.path.isfile(args.input):
        errors.append(f"Input file not found: {args.input}")

    if args.input.endswith(".nc") and not HAS_NETCDF4:
        errors.append(
            "netCDF4 package not installed. "
            "Install with: pip install netCDF4"
        )

    if not HAS_PANDAS:
        errors.append(
            "pandas package not installed. "
            "Install with: pip install pandas"
        )

    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)


def parse_netcdf_state(input_path, variables=None):
    """Parse DART state NetCDF file (mean, sd, or member).

    Returns list of dicts with columns: time, variable, index, value.
    """
    ds = netCDF4.Dataset(input_path, "r")
    records = []

    # Get time if available
    time_var = None
    time_vals = None
    if "time" in ds.variables:
        time_var = ds.variables["time"]
        time_vals = time_var[:]
    elif "MemberMetadata" in ds.variables:
        # Some DART files don't have time
        pass

    # Determine which variables to extract
    all_vars = list(ds.variables.keys())
    skip_vars = {"time", "copy", "CopyMetaData", "MemberMetadata",
                 "location", "StateVariable"}

    if variables:
        target_vars = [v for v in variables if v in all_vars]
        if not target_vars:
            # Try case-insensitive match
            var_lower = {v.lower(): v for v in all_vars}
            target_vars = [var_lower[v.lower()] for v in variables
                           if v.lower() in var_lower]
    else:
        target_vars = [v for v in all_vars if v not in skip_vars]

    for var_name in target_vars:
        var = ds.variables[var_name]
        data = var[:]

        # Handle masked arrays
        if hasattr(data, "filled"):
            data = data.filled(DART_MISSING)

        if data.ndim == 1:
            # 1D state vector (e.g., Lorenz models)
            for i, val in enumerate(data):
                if val != DART_MISSING:
                    records.append({
                        "variable": var_name,
                        "index": i,
                        "value": float(val),
                    })
        elif data.ndim == 2:
            # 2D: (time, state) or (copy, state)
            for t in range(data.shape[0]):
                for i in range(data.shape[1]):
                    val = data[t, i]
                    if val != DART_MISSING:
                        rec = {
                            "variable": var_name,
                            "index": i,
                            "value": float(val),
                        }
                        if time_vals is not None and t < len(time_vals):
                            rec["time"] = float(time_vals[t])
                        else:
                            rec["time_index"] = t
                        records.append(rec)
        else:
            # Higher dimensional (e.g., 3D model grids) — flatten
            flat = data.flatten()
            for i, val in enumerate(flat):
                if val != DART_MISSING:
                    records.append({
                        "variable": var_name,
                        "index": i,
                        "value": float(val),
                    })

    ds.close()
    return records


def parse_obs_seq_final(input_path):
    """Parse DART obs_seq.final ASCII file.

    Extracts observation values, prior/posterior ensemble means,
    and QC codes.
    """
    records = []

    with open(input_path, "r") as f:
        lines = f.readlines()

    # Find copy metadata
    copy_names = []
    qc_names = []
    i = 0
    num_copies = 0
    num_qc = 0
    num_obs = 0

    while i < len(lines):
        line = lines[i].strip()
        if "num_copies:" in line:
            parts = line.split()
            for j, p in enumerate(parts):
                if p == "num_copies:":
                    num_copies = int(parts[j + 1])
                if p == "num_qc:":
                    num_qc = int(parts[j + 1])
                if p == "num_obs:":
                    num_obs = int(parts[j + 1])
            i += 1
            # Read copy names
            for _ in range(num_copies):
                copy_names.append(lines[i].strip())
                i += 1
            # Read QC names
            for _ in range(num_qc):
                qc_names.append(lines[i].strip())
                i += 1
            break
        i += 1

    # Parse observations
    obs_count = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("OBS"):
            obs_count += 1
            rec = {"obs_key": obs_count}
            i += 1
            # Read copy values
            for c in range(num_copies):
                if i < len(lines):
                    try:
                        val = float(lines[i].strip())
                        safe_name = copy_names[c] if c < len(copy_names) else f"copy_{c}"
                        rec[safe_name] = val
                    except ValueError:
                        pass
                    i += 1
            # Read QC values
            for q in range(num_qc):
                if i < len(lines):
                    try:
                        val = float(lines[i].strip())
                        safe_name = qc_names[q] if q < len(qc_names) else f"qc_{q}"
                        rec[safe_name] = val
                    except ValueError:
                        pass
                    i += 1
            records.append(rec)
        else:
            i += 1

    return records


def parse_obs_diag_nc(input_path, variables=None):
    """Parse obs_diag_output.nc file."""
    ds = netCDF4.Dataset(input_path, "r")
    records = []

    target_vars = variables if variables else ["bias", "rmse", "totalspread",
                                                "NbadDartQC", "Nposs", "Nused"]

    for var_name in target_vars:
        if var_name in ds.variables:
            data = ds.variables[var_name][:]
            if hasattr(data, "filled"):
                data = data.filled(np.nan)
            for i, val in enumerate(data.flatten()):
                if not np.isnan(val):
                    records.append({
                        "variable": var_name,
                        "index": i,
                        "value": float(val),
                    })

    ds.close()
    return records


def process(args):
    """Main processing: read input and extract records."""
    if args.parse_obs_seq:
        return parse_obs_seq_final(args.input)
    elif args.input.endswith(".nc"):
        if "obs_diag" in args.input:
            return parse_obs_diag_nc(args.input, args.variables)
        else:
            return parse_netcdf_state(args.input, args.variables)
    else:
        print(json.dumps({
            "status": "error",
            "errors": [f"Unknown file format: {args.input}. "
                       f"Expected .nc or use --parse_obs_seq for obs_seq files."]
        }), file=sys.stderr)
        sys.exit(1)


def validate_outputs(records, args):
    """Post-processing validation."""
    warnings = []

    if len(records) == 0:
        warnings.append("CRITICAL: No records extracted from input file")
        for w in warnings:
            print(f"WARNING: {w}", file=sys.stderr)
        return warnings

    # Check for DART missing values that leaked through
    if any("value" in r and r["value"] == DART_MISSING for r in records):
        warnings.append(
            "WARNING: DART missing values (-888888.0) found in output. "
            "These should be filtered before analysis."
        )

    # Check for QC issues in obs_seq output
    if args.parse_obs_seq:
        qc_keys = [k for k in records[0].keys() if "qc" in k.lower() or "QC" in k]
        for qc_key in qc_keys:
            qc_vals = [r.get(qc_key, 0) for r in records]
            rejected = sum(1 for v in qc_vals if v > 0)
            if rejected > 0:
                pct = 100.0 * rejected / len(records)
                warnings.append(
                    f"INFO: {rejected}/{len(records)} ({pct:.1f}%) observations "
                    f"have non-zero QC in '{qc_key}'"
                )

    for w in warnings:
        print(f"WARNING: {w}", file=sys.stderr)

    return warnings


def main():
    parser = argparse.ArgumentParser(
        description="Extract DART NetCDF output to CSV"
    )
    parser.add_argument("--input", required=True,
                        help="Input file (NetCDF or obs_seq)")
    parser.add_argument("--output", required=True,
                        help="Output CSV file")
    parser.add_argument("--variables", nargs="*", default=None,
                        help="Variables to extract (default: all)")
    parser.add_argument("--parse_obs_seq", action="store_true",
                        help="Parse obs_seq.final ASCII file instead of NetCDF")

    args = parser.parse_args()

    # Step 1: validate
    validate_inputs(args)

    # Step 2: process
    records = process(args)

    # Step 3: validate
    warnings = validate_outputs(records, args)

    # Step 4: write CSV
    if records:
        df = pd.DataFrame(records)
        df.to_csv(args.output, index=False)
    else:
        with open(args.output, "w") as f:
            f.write("")

    # Step 5: report
    result = {
        "status": "success",
        "input_file": args.input,
        "output_file": args.output,
        "num_records": len(records),
        "columns": list(records[0].keys()) if records else [],
        "warnings": warnings,
    }
    print(json.dumps(result, indent=2), file=sys.stderr)
    print(f"Wrote {len(records)} records to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
