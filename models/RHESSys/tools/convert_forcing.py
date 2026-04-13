#!/usr/bin/env python3
"""
convert_forcing.py — Convert global meteorological data to RHESSys ASCII format.

RHESSys requires daily climate forcing in individual ASCII files per variable,
with a start-date header line (YYYY M D HH) followed by one value per line.

Supported input formats:
  - CSV with columns: date, tmax, tmin, precip (and optionally rh, wind, rad)
  - NASA POWER daily CSV
  - CMFD gridded (pre-extracted to point CSV)

CRITICAL UNIT CONVERSIONS:
  - Precipitation: input mm/day -> output m/day (divide by 1000)
  - Temperature: if input in Kelvin -> output Celsius (subtract 273.15)

Usage:
    python convert_forcing.py --input forcing.csv --output-dir clim/ --prefix site_daily
    python convert_forcing.py --input forcing.csv --output-dir clim/ --prefix site_daily --precip-unit mm
    python convert_forcing.py --input nasa_power.csv --output-dir clim/ --prefix site_daily --format nasa_power
"""

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timedelta


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_inputs(args):
    """Validate command-line arguments and input file."""
    errors = []

    if not os.path.isfile(args.input):
        errors.append(f"Input file not found: {args.input}")

    if args.precip_unit not in ("mm", "m"):
        errors.append(f"Invalid precip unit: {args.precip_unit}. Must be 'mm' or 'm'.")

    if args.temp_unit not in ("C", "K"):
        errors.append(f"Invalid temp unit: {args.temp_unit}. Must be 'C' or 'K'.")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)


def validate_output(output_dir, prefix, start_date):
    """Validate that output files were created and contain reasonable values."""
    errors = []
    warnings = []

    for var, ext in [("tmax", ".tmax"), ("tmin", ".tmin"), ("rain", ".rain")]:
        fpath = os.path.join(output_dir, prefix + ext)
        if not os.path.isfile(fpath):
            errors.append(f"Output file missing: {fpath}")
            continue

        with open(fpath) as f:
            lines = f.readlines()
            if len(lines) < 2:
                errors.append(f"Output file {fpath} has fewer than 2 lines")
                continue

            # Check header
            header_parts = lines[0].strip().split()
            if len(header_parts) != 4:
                errors.append(f"Invalid header in {fpath}: {lines[0].strip()}")

            # Check value ranges
            values = []
            for line in lines[1:]:
                line = line.strip()
                if line:
                    try:
                        values.append(float(line))
                    except ValueError:
                        errors.append(f"Non-numeric value in {fpath}: {line}")
                        break

            if values and var == "rain":
                if max(values) > 1.0:
                    warnings.append(
                        f"UNIT TRAP: Max rain = {max(values):.3f} m/day "
                        f"({max(values)*1000:.1f} mm/day). "
                        f"If this seems too high, check that input was converted from mm to m."
                    )
                if any(v < 0 for v in values):
                    errors.append(f"Negative precipitation values in {fpath}")

            if values and var == "tmax":
                if max(values) > 80:
                    warnings.append(
                        f"UNIT TRAP: Max tmax = {max(values):.1f} C. "
                        f"Likely still in Kelvin. Apply -273.15 conversion."
                    )

    result = {"status": "ok" if not errors else "error"}
    if errors:
        result["errors"] = errors
    if warnings:
        result["warnings"] = warnings
    return result


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def detect_format(filepath):
    """Auto-detect input CSV format."""
    with open(filepath) as f:
        header = f.readline().strip().lower()

    if "parameter" in header and "val" in header:
        return "nasa_power"
    elif "tmax" in header or "t_max" in header:
        return "generic"
    elif "date" in header:
        return "generic"
    else:
        return "generic"


def parse_generic_csv(filepath):
    """Parse generic CSV with date, tmax, tmin, precip columns."""
    records = []
    with open(filepath) as f:
        reader = csv.DictReader(f)
        # Normalize column names
        for row in reader:
            normed = {k.strip().lower(): v.strip() for k, v in row.items()}
            date_str = (
                normed.get("date")
                or normed.get("datetime")
                or normed.get("time")
            )
            if date_str is None:
                # Try YYYY, MM, DD columns
                y = normed.get("year") or normed.get("yyyy")
                m = normed.get("month") or normed.get("mm") or normed.get("mon")
                d = normed.get("day") or normed.get("dd")
                if y and m and d:
                    date_str = f"{int(y):04d}-{int(m):02d}-{int(d):02d}"
                else:
                    continue

            tmax = float(
                normed.get("tmax")
                or normed.get("t_max")
                or normed.get("temperature_max")
                or normed.get("tasmax")
                or "nan"
            )
            tmin = float(
                normed.get("tmin")
                or normed.get("t_min")
                or normed.get("temperature_min")
                or normed.get("tasmin")
                or "nan"
            )
            precip = float(
                normed.get("precip")
                or normed.get("rain")
                or normed.get("precipitation")
                or normed.get("pr")
                or normed.get("prcp")
                or "0"
            )

            records.append({
                "date": date_str,
                "tmax": tmax,
                "tmin": tmin,
                "precip": precip,
            })
    return records


def parse_nasa_power(filepath):
    """Parse NASA POWER daily CSV format."""
    records = []
    with open(filepath) as f:
        # Skip metadata lines
        for line in f:
            if line.startswith("YEAR") or line.startswith("-END"):
                break
        reader = csv.DictReader(f) if "YEAR" in line else csv.DictReader(f)
        # Re-read with proper header
    with open(filepath) as f:
        lines = f.readlines()
        header_idx = None
        for i, line in enumerate(lines):
            if line.strip().startswith("YEAR"):
                header_idx = i
                break
        if header_idx is None:
            raise ValueError("Cannot find header in NASA POWER file")

        reader = csv.DictReader(lines[header_idx:])
        for row in reader:
            normed = {k.strip(): v.strip() for k, v in row.items()}
            y = normed.get("YEAR", "")
            doy = normed.get("DOY", "")
            if not y or not doy or not y.isdigit():
                continue
            dt = datetime(int(y), 1, 1) + timedelta(days=int(doy) - 1)
            date_str = dt.strftime("%Y-%m-%d")

            tmax = float(normed.get("T2M_MAX", "nan"))
            tmin = float(normed.get("T2M_MIN", "nan"))
            precip = float(normed.get("PRECTOTCORR", "0"))

            records.append({
                "date": date_str,
                "tmax": tmax,
                "tmin": tmin,
                "precip": precip,
            })
    return records


# ---------------------------------------------------------------------------
# Conversion & Output
# ---------------------------------------------------------------------------

def convert_units(records, precip_unit, temp_unit):
    """Apply unit conversions to records in-place."""
    for rec in records:
        # Precipitation: convert to m/day
        if precip_unit == "mm":
            rec["precip"] = rec["precip"] / 1000.0

        # Temperature: convert to Celsius
        if temp_unit == "K":
            rec["tmax"] = rec["tmax"] - 273.15
            rec["tmin"] = rec["tmin"] - 273.15

    return records


def write_rhessys_clim(records, output_dir, prefix, start_date=None):
    """Write RHESSys ASCII climate files.

    Format per file:
      Line 1: YYYY M D HH (start date header)
      Line 2+: one value per day
    """
    os.makedirs(output_dir, exist_ok=True)

    if start_date is None and records:
        start_date = records[0]["date"]

    # Parse start date
    if isinstance(start_date, str):
        dt = datetime.strptime(start_date.split()[0], "%Y-%m-%d")
    else:
        dt = start_date

    header = f"{dt.year} {dt.month} {dt.day} 01\n"

    for var, ext in [("tmax", ".tmax"), ("tmin", ".tmin"), ("precip", ".rain")]:
        fpath = os.path.join(output_dir, prefix + ext)
        with open(fpath, "w") as f:
            f.write(header)
            for rec in records:
                f.write(f"{rec[var]:.6f}\n")

    return len(records)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Convert meteorological data to RHESSys ASCII forcing format.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--input", required=True, help="Input CSV file path")
    parser.add_argument("--output-dir", required=True, help="Output directory for climate files")
    parser.add_argument("--prefix", required=True, help="Output filename prefix (e.g., site_daily)")
    parser.add_argument("--start-date", default=None, help="Override start date (YYYY-MM-DD)")
    parser.add_argument("--format", default="auto",
                        choices=["auto", "generic", "nasa_power"],
                        help="Input format (default: auto-detect)")
    parser.add_argument("--precip-unit", default="mm",
                        choices=["mm", "m"],
                        help="Input precipitation unit (default: mm, will convert to m)")
    parser.add_argument("--temp-unit", default="C",
                        choices=["C", "K"],
                        help="Input temperature unit (default: C)")
    args = parser.parse_args()

    # Step 1: Validate inputs
    validate_inputs(args)

    # Step 2: Parse input
    fmt = args.format
    if fmt == "auto":
        fmt = detect_format(args.input)
    print(f"Detected format: {fmt}")

    if fmt == "nasa_power":
        records = parse_nasa_power(args.input)
    else:
        records = parse_generic_csv(args.input)

    if not records:
        print(json.dumps({"status": "error", "errors": ["No records parsed from input"]}),
              file=sys.stderr)
        sys.exit(1)

    print(f"Parsed {len(records)} daily records")
    print(f"Date range: {records[0]['date']} to {records[-1]['date']}")

    # Step 3: Convert units
    records = convert_units(records, args.precip_unit, args.temp_unit)

    # Step 4: Write output
    n = write_rhessys_clim(records, args.output_dir, args.prefix, args.start_date)
    print(f"Wrote {n} days to {args.output_dir}/{args.prefix}.[tmax|tmin|rain]")

    # Step 5: Validate output
    result = validate_output(args.output_dir, args.prefix, args.start_date)
    if result.get("warnings"):
        for w in result["warnings"]:
            print(f"WARNING: {w}")
    if result.get("errors"):
        print(json.dumps(result), file=sys.stderr)
        sys.exit(1)

    print(json.dumps({"status": "ok", "records": n, "output_dir": args.output_dir}))


if __name__ == "__main__":
    main()
