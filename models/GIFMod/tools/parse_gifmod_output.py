#!/usr/bin/env python3
"""
parse_gifmod_output.py - Parse GIFMod time series output to CSV.

GIFMod produces columnar text output with block-level time series for:
  - Head (H) in meters
  - Flow (Q) in m^3/day
  - Concentration (C) in user-defined units
  - Moisture content (theta) as fraction
  - Mass balance (MB) cumulative error

This tool reads the raw output, identifies columns, and writes a clean CSV
with optional variable selection, time range filtering, and unit annotations.

Output CSV format:
  datetime,Time_days,Block1_Head_m,Block1_Flow_m3day,Block2_Conc_mgL,...

Usage:
    python parse_gifmod_output.py --input model_output.txt --output results.csv
    python parse_gifmod_output.py --input model_output.txt --output results.csv \\
        --variables Head,Flow --start-day 10 --end-day 365
"""

import argparse
import csv
import json
import os
import re
import sys
from datetime import datetime, timedelta


def validate_inputs(args):
    """Validate input file exists and is readable."""
    errors = []

    if not os.path.isfile(args.input):
        errors.append(f"Input file not found: {args.input}")
    else:
        # Check file is not empty
        if os.path.getsize(args.input) == 0:
            errors.append(f"Input file is empty: {args.input}")

    if args.variables:
        valid_vars = {"Head", "Flow", "Concentration", "Moisture", "MassBalance",
                      "Storage", "Velocity", "Area"}
        for v in args.variables.split(","):
            v = v.strip()
            if v and v not in valid_vars:
                errors.append(
                    f"Unknown variable '{v}'. Valid: {sorted(valid_vars)}"
                )

    if args.start_day is not None and args.end_day is not None:
        if args.start_day >= args.end_day:
            errors.append("start-day must be less than end-day")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)

    return {"status": "ok"}


def detect_format(filepath):
    """Auto-detect GIFMod output format from header line."""
    with open(filepath, "r") as f:
        # Read up to 20 lines looking for header
        for i, line in enumerate(f):
            if i > 20:
                break
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            # GIFMod headers typically have "Time" as first column
            parts = re.split(r"\s+|\t|,", line)
            if parts and parts[0].lower() in ("time", "t", "time(day)"):
                return {
                    "header_line": i,
                    "columns": parts,
                    "delimiter": "\t" if "\t" in line else (",") if "," in line else " ",
                }

    return None


def process(args):
    """Read GIFMod output and convert to CSV."""
    fmt = detect_format(args.input)
    warnings = []

    if fmt is None:
        # Try to parse as simple whitespace-delimited
        warnings.append("Could not detect header; treating as whitespace-delimited")
        fmt = {"header_line": 0, "columns": None, "delimiter": None}

    rows_out = 0
    output_rows = []
    columns = []

    variable_filter = None
    if args.variables:
        variable_filter = set(v.strip() for v in args.variables.split(","))

    with open(args.input, "r") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            # Parse based on delimiter
            if fmt["delimiter"] and fmt["delimiter"] != " ":
                parts = line.split(fmt["delimiter"])
            else:
                parts = line.split()

            # Header line
            if i == fmt["header_line"]:
                columns = [p.strip() for p in parts]

                # Filter columns if requested
                if variable_filter:
                    filtered_cols = [columns[0]]  # Always keep Time
                    for c in columns[1:]:
                        for v in variable_filter:
                            if v.lower() in c.lower():
                                filtered_cols.append(c)
                                break
                    columns = filtered_cols

                continue

            if i <= fmt["header_line"]:
                continue

            # Data line
            try:
                values = [float(p.strip()) for p in parts if p.strip()]
            except ValueError:
                warnings.append(f"Line {i+1}: cannot parse as numbers, skipping")
                continue

            if len(values) == 0:
                continue

            time_days = values[0]

            # Time range filter
            if args.start_day is not None and time_days < args.start_day:
                continue
            if args.end_day is not None and time_days > args.end_day:
                continue

            # Build row dict
            row = {"Time_days": f"{time_days:.6f}"}

            # Add datetime if reference date provided
            if args.ref_date:
                ref = datetime.strptime(args.ref_date, "%Y-%m-%d")
                dt = ref + timedelta(days=time_days)
                row["datetime"] = dt.strftime("%Y-%m-%d %H:%M:%S")

            # Map values to column names
            all_cols = fmt.get("columns") or [f"col_{j}" for j in range(len(values))]
            for j, val in enumerate(values[1:], 1):
                if j < len(all_cols):
                    col_name = all_cols[j]
                else:
                    col_name = f"col_{j}"

                # Apply variable filter
                if variable_filter:
                    matched = False
                    for v in variable_filter:
                        if v.lower() in col_name.lower():
                            matched = True
                            break
                    if not matched:
                        continue

                row[col_name] = f"{val:.6g}"

            output_rows.append(row)
            rows_out += 1

    # Determine output columns
    if output_rows:
        out_cols = list(output_rows[0].keys())
    else:
        out_cols = ["Time_days"]

    # Write CSV
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=out_cols, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(output_rows)

    # Compute summary statistics
    stats = {}
    if output_rows:
        numeric_cols = [c for c in out_cols if c not in ("Time_days", "datetime")]
        for col in numeric_cols[:10]:
            vals = []
            for row in output_rows:
                try:
                    vals.append(float(row.get(col, 0)))
                except (ValueError, TypeError):
                    pass
            if vals:
                stats[col] = {
                    "min": round(min(vals), 6),
                    "max": round(max(vals), 6),
                    "mean": round(sum(vals) / len(vals), 6),
                    "n": len(vals),
                }

    return {
        "status": "success",
        "rows_out": rows_out,
        "columns": out_cols,
        "n_columns": len(out_cols),
        "output_file": args.output,
        "statistics": stats,
        "warnings": warnings[:20],
    }


def validate_outputs(result):
    """Verify output quality."""
    errors = []

    if result["rows_out"] == 0:
        errors.append("No output rows — check input format or time range filter")

    if not os.path.isfile(result["output_file"]):
        errors.append(f"Output file not created: {result['output_file']}")

    if errors:
        result["status"] = "error"
        result["errors"] = errors
        print(json.dumps(result, indent=2))
        sys.exit(1)

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Parse GIFMod output to CSV"
    )
    parser.add_argument("--input", required=True,
                        help="GIFMod output file")
    parser.add_argument("--output", required=True,
                        help="Output CSV file")
    parser.add_argument("--variables", default=None,
                        help="Comma-separated variable filter (e.g., Head,Flow)")
    parser.add_argument("--start-day", type=float, default=None,
                        help="Start time in days (inclusive)")
    parser.add_argument("--end-day", type=float, default=None,
                        help="End time in days (inclusive)")
    parser.add_argument("--ref-date", default=None,
                        help="Reference date for datetime column (YYYY-MM-DD)")

    args = parser.parse_args()

    validate_inputs(args)
    result = process(args)
    result = validate_outputs(result)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
