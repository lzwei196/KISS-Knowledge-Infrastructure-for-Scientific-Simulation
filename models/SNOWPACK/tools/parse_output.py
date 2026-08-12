#!/usr/bin/env python3
"""
parse_output.py — Parse SNOWPACK output files to CSV.

Purpose:
    Reads SNOWPACK .met (time series) and .pro (profile) output files and
    extracts selected variables into clean CSV format for analysis.

SNOWPACK output formats:
    .met files — Tab-separated time series with a 2-line header. Contains
    surface energy fluxes, mass fluxes, snow state, and meteorological data
    at each output timestep.

    .pro files — Layer-by-layer profile data written at profile intervals.
    Contains temperature, density, grain properties, and stability indices
    for each snow/soil layer.

Output CSV format:
    datetime, var1, var2, ... (one row per timestep)

Key output variables and units:
    HS          — Snow depth (m)
    SWE         — Snow water equivalent (kg/m²)
    TA          — Air temperature (K)
    TSS         — Snow surface temperature (K)
    TSG         — Ground surface temperature (K)
    ISWR        — Incoming shortwave radiation (W/m²)
    OSWR        — Outgoing shortwave radiation (W/m²)
    ILWR        — Incoming longwave radiation (W/m²)
    OLWR        — Outgoing longwave radiation (W/m²)
    qs          — Sensible heat flux (W/m²)
    ql          — Latent heat flux (W/m²)
    qg          — Ground heat flux (W/m²)
    qr          — Rain energy flux (W/m²)
    MS_HNW      — New snow precipitation rate (kg/m² per output interval)
    MS_RAIN     — Rain rate (kg/m² per output interval)
    MS_EVAP     — Evaporation/sublimation mass loss (kg/m² per output interval)
    MS_RUNOFF   — Snowpack runoff (kg/m² per output interval)
    Albedo      — Surface albedo (0-1)
    RHO_mean    — Mean snowpack density (kg/m³)

CRITICAL NOTES:
    - .met files have a 2-line header; first line is field names, second is units
    - nodata values (usually -999) must be handled
    - Timestamps in output are in the timezone specified in the config
    - Profile (.pro) files have a different structure with block headers per timestep

Usage:
    # Parse time series
    python parse_output.py \\
        --input output/MST96.met \\
        --output results/MST96_ts.csv \\
        --variables HS,SWE,TA,qs,ql,MS_RUNOFF

    # Parse with nodata handling
    python parse_output.py \\
        --input output/MST96.met \\
        --output results/MST96_ts.csv \\
        --nodata -999 \\
        --variables HS,SWE,Albedo

    # Parse profile file
    python parse_output.py \\
        --input output/MST96.pro \\
        --output results/MST96_profiles.csv \\
        --file_type pro \\
        --variables T,Rho,rg
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd


def validate_inputs(args):
    """Validate input arguments."""
    errors = []

    if not os.path.isfile(args.input):
        errors.append(f"Input file not found: {args.input}")

    if not args.variables:
        errors.append("No variables specified (use --variables HS,SWE,...)")

    valid_types = ["auto", "met", "pro"]
    if args.file_type not in valid_types:
        errors.append(f"file_type must be one of {valid_types}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)
    return errors


def detect_file_type(filepath):
    """Auto-detect file type from extension."""
    ext = Path(filepath).suffix.lower()
    if ext == ".met":
        return "met"
    elif ext == ".pro":
        return "pro"
    else:
        return "met"  # default


def parse_met_file(filepath, variables, nodata):
    """Parse SNOWPACK .met time series output.

    SNOWPACK .met format has block headers: [STATION_PARAMETERS], [HEADER], [DATA].
    Within [HEADER]: comment (#...), column-number row (,,1,2,3,...),
    column-name row (ID,Date,...), units row.
    Data rows are comma-delimited starting with field-code 0203.
    Datetime format: DD.MM.YYYY HH:MM:SS
    """
    columns = None
    data_rows = []

    with open(filepath, "r") as f:
        in_header = False
        header_subrow = 0   # tracks position inside [HEADER] block
        for line in f:
            line_s = line.rstrip("\n")
            if line_s.strip() == "[HEADER]":
                in_header = True
                header_subrow = 0
                continue
            if line_s.strip() == "[DATA]":
                in_header = False
                continue
            if line_s.strip().startswith("["):
                in_header = False
                continue
            if in_header:
                stripped = line_s.strip()
                if not stripped:
                    continue
                if stripped.startswith("#"):   # run-info comment
                    continue
                parts = stripped.split(",")
                if header_subrow == 0:
                    # first non-comment row: column-number row (starts with empty/ID)
                    # skip it — it's ,,1,2,3,...
                    header_subrow += 1
                    continue
                if header_subrow == 1:
                    # second non-comment, non-blank row: column names
                    columns = [p.strip() for p in parts]
                    header_subrow += 1
                    continue
                # third row and beyond: units row(s) — skip
                continue
            # Data rows start with 0203
            if line_s.startswith("0203,"):
                data_rows.append(line_s)

    if columns is None or not data_rows:
        # Fallback: treat file as simple 2-row-header whitespace-delimited
        with open(filepath, "r") as f:
            header_line = f.readline().strip()
            f.readline()  # units
        columns = re.split(r"\s+", header_line)
        df = pd.read_csv(filepath, sep=r"\s+", skiprows=2, header=None,
                         names=columns, na_values=[str(nodata), "nodata"])
        date_col = columns[0]
        df[date_col] = pd.to_datetime(df[date_col])
        df = df.rename(columns={date_col: "datetime"})
    else:
        # Parse comma-delimited data rows
        from io import StringIO
        csv_text = "\n".join(data_rows)
        df = pd.read_csv(StringIO(csv_text), header=None, sep=",",
                         na_values=[str(nodata), "-999", "-99900"])
        # Trim columns list if file has more or fewer columns
        n_cols = df.shape[1]
        if len(columns) < n_cols:
            columns = columns + [f"col_{i}" for i in range(len(columns), n_cols)]
        df.columns = columns[:n_cols]
        # SNOWPACK date column: "Date" in DD.MM.YYYY HH:MM:SS format
        date_col = "Date" if "Date" in df.columns else df.columns[1]
        df[date_col] = pd.to_datetime(df[date_col], format="%d.%m.%Y %H:%M:%S",
                                      errors="coerce")
        df = df.rename(columns={date_col: "datetime"})
        # Drop the record-type field (first col = 0203)
        if df.columns[0] not in ("datetime",) and "ID" not in df.columns[0]:
            df = df.drop(columns=df.columns[0])

    # Select requested variables
    available = [c for c in df.columns if c != "datetime"]
    selected = ["datetime"]
    missing = []
    for v in variables:
        if v in df.columns:
            selected.append(v)
        else:
            missing.append(v)

    if missing:
        print(f"WARNING: Variables not found in output: {missing}", file=sys.stderr)
        print(f"Available: {available[:30]}", file=sys.stderr)

    df_out = df[selected].copy()

    return df_out, available, missing


def parse_pro_file(filepath, variables, nodata):
    """Parse SNOWPACK .pro profile output.

    .pro files contain blocks for each output timestep:
    - Header line: @timestamp, nElems, ...
    - Data lines: one per layer with properties

    This parser extracts layer data and reshapes to long format.
    """
    records = []
    current_timestamp = None
    current_columns = None

    with open(filepath, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            if line.startswith("0500"):
                # Profile header — extract timestamp
                parts = re.split(r"[,\s]+", line)
                if len(parts) >= 2:
                    try:
                        # Format: 0500,date
                        current_timestamp = parts[1] if len(parts) > 1 else None
                    except (ValueError, IndexError):
                        pass
                continue

            if line.startswith("0501"):
                # Column definitions
                continue

            if line.startswith("0502") or line.startswith("0503") or line.startswith("0504"):
                # Data lines
                parts = re.split(r"[,\s]+", line)
                if current_timestamp and len(parts) > 3:
                    record = {"datetime": current_timestamp}
                    # Parse layer data
                    try:
                        record["layer_height"] = float(parts[1])
                        if len(parts) > 2:
                            record["T"] = float(parts[2])
                        if len(parts) > 3:
                            record["Rho"] = float(parts[3])
                        if len(parts) > 4:
                            record["rg"] = float(parts[4])
                    except (ValueError, IndexError):
                        pass
                    records.append(record)

    if records:
        df = pd.DataFrame(records)
        df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
        df = df.replace(nodata, np.nan)
    else:
        df = pd.DataFrame(columns=["datetime"] + variables)

    return df, list(df.columns), []


def process(args):
    """Main processing: parse output file and write CSV."""
    variables = [v.strip() for v in args.variables.split(",")]

    if args.file_type == "auto":
        args.file_type = detect_file_type(args.input)

    print(f"Parsing {args.file_type} file: {args.input}", file=sys.stderr)
    print(f"Requested variables: {variables}", file=sys.stderr)

    if args.file_type == "met":
        df, available, missing = parse_met_file(args.input, variables, args.nodata)
    else:
        df, available, missing = parse_pro_file(args.input, variables, args.nodata)

    # Write CSV
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    df.to_csv(args.output, index=False, float_format="%.6f")

    # Compute basic stats
    stats = {}
    for col in df.columns:
        if col != "datetime" and df[col].dtype in [np.float64, np.int64]:
            stats[col] = {
                "min": float(df[col].min()) if not df[col].isna().all() else None,
                "max": float(df[col].max()) if not df[col].isna().all() else None,
                "mean": float(df[col].mean()) if not df[col].isna().all() else None,
                "n_valid": int(df[col].notna().sum()),
                "n_missing": int(df[col].isna().sum()),
            }

    result = {
        "status": "success",
        "input_file": args.input,
        "output_file": args.output,
        "file_type": args.file_type,
        "n_records": len(df),
        "n_variables": len(df.columns) - 1,
        "variables_found": [c for c in df.columns if c != "datetime"],
        "variables_missing": missing,
        "available_variables": available[:50],
        "stats": stats,
    }

    if len(df) > 0 and "datetime" in df.columns:
        result["period_start"] = str(df["datetime"].iloc[0])
        result["period_end"] = str(df["datetime"].iloc[-1])

    return result


def validate_outputs(result):
    """Check parsed output for issues."""
    warnings = []

    stats = result.get("stats", {})
    for var, s in stats.items():
        if s.get("n_valid", 0) == 0:
            warnings.append(f"{var}: all values are missing/nodata")

        if var == "HS" and s.get("max") is not None:
            if s["max"] > 50:
                warnings.append(f"HS max={s['max']:.1f}m — unrealistic snow depth?")
            if s["max"] == 0 and s.get("n_valid", 0) > 100:
                warnings.append("HS always zero — model may not have accumulated snow")

        if var == "SWE" and s.get("min") is not None and s["min"] < 0:
            warnings.append(f"SWE negative ({s['min']:.1f}) — mass conservation issue")

    if result.get("n_records", 0) == 0:
        warnings.append("No records parsed — check file format and nodata value")

    if warnings:
        result["warnings"] = warnings
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Parse SNOWPACK output files to CSV"
    )
    parser.add_argument("--input", required=True,
                        help="Input .met or .pro file")
    parser.add_argument("--output", required=True,
                        help="Output CSV file path")
    parser.add_argument("--variables", required=True,
                        help="Comma-separated list of variables to extract")
    parser.add_argument("--file_type", default="auto",
                        choices=["auto", "met", "pro"],
                        help="File type (default: auto-detect from extension)")
    parser.add_argument("--nodata", type=float, default=-999,
                        help="Nodata value to replace with NaN")

    args = parser.parse_args()

    validate_inputs(args)
    result = process(args)
    result = validate_outputs(result)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
