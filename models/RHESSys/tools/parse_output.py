#!/usr/bin/env python3
"""
parse_output.py — Parse RHESSys output files to clean CSV format.

RHESSys produces space-delimited output files (legacy mode) or CSV (filter mode).
This tool handles both formats, normalizes headers, applies unit conversions,
and produces analysis-ready CSV.

Key conversions:
  - Streamflow: mm/day -> m^3/s (requires basin area). Legacy <prefix>_basin.daily
    writes water fluxes x1000 = mm/day (output_basin.c:446). Output-filter CSV writes
    raw model values (m/day): pass --streamflow-unit m/day for that file.
  - Dates: day/month/year columns -> ISO date string

Usage:
    python parse_output.py --input out/test_basin.daily --output basin_daily.csv --level basin
    python parse_output.py --input out/test_basin.daily --output basin_daily.csv --level basin --basin-area 1e6
    python parse_output.py --input out/test_basin_daily.csv --output basin_clean.csv --level basin --csv-input
"""

import argparse
import csv
import json
import os
import sys
from datetime import datetime


# ---------------------------------------------------------------------------
# Column definitions per output level
# ---------------------------------------------------------------------------

# Legacy (space-delimited) column order for basin daily output
BASIN_DAILY_COLUMNS = [
    "day", "month", "year", "basinID",
    "rain_thr", "snow_thr", "rain", "snow_melt",
    "trans_sat", "trans_unsat",
    "Qout", "Qout_sub",
    "evap", "evap_surf",
    "sat_deficit", "sat_deficit_z", "unsat_storage", "unsat_drain",
    "cap_rise", "return_flow",
    "snow_stored", "litter_store",
    "canopy_store", "streamflow",
    "psn", "lai",
    "gw_Qout", "gw_storage",
    "detention_store",
    "base_flow",
    "streamflow_NO3", "streamflow_NH4", "streamflow_DON", "streamflow_DOC",
    "denitrif", "nitrif",
    "mineralized", "uptake", "theta",
    "snow_depth", "snow_water_equiv",
    "gw_NO3", "gw_DON",
]

PATCH_DAILY_COLUMNS = [
    "day", "month", "year", "patchID",
    "rain_thr", "snow_thr", "rain", "snow_melt",
    "trans_sat", "trans_unsat",
    "Qout", "Qout_sub",
    "evap", "evap_surf",
    "sat_deficit", "sat_deficit_z", "unsat_storage", "unsat_drain",
    "cap_rise", "return_flow",
    "snow_stored", "litter_store",
    "canopy_store", "streamflow",
    "psn", "lai",
]

STRATUM_DAILY_COLUMNS = [
    "day", "month", "year", "patchID", "stratumID",
    "lai", "evap", "Kstar_direct", "Kstar_diffuse",
    "Lstar", "trans_sat", "trans_unsat",
    "ga", "gsurf", "gs",
    "psn", "resp",
    "leafc", "stemc", "rootc",
]


COLUMN_MAP = {
    "basin": BASIN_DAILY_COLUMNS,
    "patch": PATCH_DAILY_COLUMNS,
    "stratum": STRATUM_DAILY_COLUMNS,
}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_inputs(args):
    """Validate command-line arguments."""
    errors = []

    if not os.path.isfile(args.input):
        errors.append(f"Input file not found: {args.input}")

    if args.level not in COLUMN_MAP and not args.csv_input:
        errors.append(f"Unknown output level: {args.level}. Use: basin, patch, stratum")

    if args.basin_area is not None and args.basin_area <= 0:
        errors.append(f"Basin area must be positive, got: {args.basin_area}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)


def validate_output(output_path, expected_min_rows=1):
    """Validate the output CSV."""
    errors = []
    warnings = []

    if not os.path.isfile(output_path):
        errors.append(f"Output file not created: {output_path}")
        return {"status": "error", "errors": errors}

    with open(output_path) as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if len(rows) < expected_min_rows:
        warnings.append(f"Output has only {len(rows)} rows (expected >= {expected_min_rows})")

    if rows:
        # Check for date column
        if "date" not in reader.fieldnames:
            warnings.append("No 'date' column in output")

        # Check for streamflow
        if "streamflow" in reader.fieldnames:
            sf_vals = [float(r["streamflow"]) for r in rows if r.get("streamflow")]
            if sf_vals:
                if max(sf_vals) == 0:
                    warnings.append("All streamflow values are zero — check TEC events (dt_014)")
                if max(sf_vals) > 100:
                    warnings.append(
                        f"Max streamflow = {max(sf_vals):.2f}, seems very high. "
                        f"Check precipitation units (dt_001)."
                    )

    result = {"status": "ok" if not errors else "error", "rows": len(rows)}
    if errors:
        result["errors"] = errors
    if warnings:
        result["warnings"] = warnings
    return result


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_legacy_output(filepath, level):
    """Parse space-delimited RHESSys legacy output."""
    columns = COLUMN_MAP.get(level, BASIN_DAILY_COLUMNS)
    records = []
    header_found = False

    with open(filepath) as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue

            parts = line.split()

            # Header line (non-numeric first token). RHESSys legacy output always writes
            # one (main.c:433 add_headers): read columns BY NAME from it; the fixed
            # lists above do not match the file (streamflow is column 19, not 24).
            if not parts[0].replace("-", "").replace(".", "").isdigit():
                if not records:
                    columns = parts
                    header_found = True
                continue

            row = {}
            for i, col in enumerate(columns):
                if i < len(parts):
                    row[col] = parts[i]
                else:
                    row[col] = ""

            records.append(row)

    if records and not header_found:
        print(f"WARNING: no header line in {filepath}; using the old fixed column list, "
              "which does not match real RHESSys files (e.g. 'streamflow' there is gw.storage). "
              "Check the columns before using the numbers.", file=sys.stderr)

    return records


def parse_csv_output(filepath):
    """Parse RHESSys CSV output (from output filter)."""
    records = []
    with open(filepath) as f:
        reader = csv.DictReader(f)
        for row in reader:
            records.append(dict(row))
    return records


# ---------------------------------------------------------------------------
# Processing
# ---------------------------------------------------------------------------

def add_date_column(records):
    """Add ISO date string from day/month/year columns."""
    for rec in records:
        try:
            d = int(float(rec.get("day", 0)))
            m = int(float(rec.get("month", 0)))
            y = int(float(rec.get("year", 0)))
            if y > 0 and m > 0 and d > 0:
                rec["date"] = f"{y:04d}-{m:02d}-{d:02d}"
            else:
                rec["date"] = ""
        except (ValueError, TypeError):
            rec["date"] = ""
    return records


def convert_streamflow(records, basin_area_m2, depth_unit="mm/day"):
    """Convert streamflow depth (mm/day or m/day over the basin) to m^3/s.

    Formula: Q_m3s = streamflow_mm_day / 1000 * basin_area_m2 / 86400
    """
    to_m = 0.001 if depth_unit == "mm/day" else 1.0
    for rec in records:
        sf_key = None
        for k in ["streamflow", "Qout"]:
            if k in rec:
                sf_key = k
                break
        if sf_key and basin_area_m2:
            try:
                sf_m_day = float(rec[sf_key]) * to_m
                rec["streamflow_m3s"] = sf_m_day * basin_area_m2 / 86400.0
            except (ValueError, TypeError):
                rec["streamflow_m3s"] = ""
    return records


def compute_water_balance(records):
    """Add water balance check column: P - ET - Q.

    There is no storage-change (dS) term here, so a large residual can be water stored
    in the basin (snow, soil, surface detention), not a parser error.
    """
    for rec in records:
        try:
            # basin.daily header names (add_headers.c): precip = rain+snow, trans = sat+unsat
            precip = float(rec.get("precip", 0) or 0)
            evap = float(rec.get("evap", 0) or 0)
            trans = float(rec.get("trans", 0) or 0)
            sf = float(rec.get("streamflow", 0) or 0)
            total_in = precip
            total_out = evap + trans + sf
            rec["water_balance_residual"] = total_in - total_out
        except (ValueError, TypeError):
            rec["water_balance_residual"] = ""
    return records


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def write_csv(records, output_path, columns=None):
    """Write records to CSV."""
    if not records:
        print("WARNING: No records to write", file=sys.stderr)
        return

    if columns is None:
        # Use all columns, with date first
        all_cols = set()
        for rec in records:
            all_cols.update(rec.keys())
        # Order: date first, then sorted
        priority = ["date", "day", "month", "year"]
        columns = [c for c in priority if c in all_cols]
        columns += sorted(c for c in all_cols if c not in priority)

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)

    return len(records)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Parse RHESSys output to clean CSV.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--input", required=True, help="Input RHESSys output file")
    parser.add_argument("--output", required=True, help="Output CSV path")
    parser.add_argument("--level", default="basin",
                        choices=["basin", "patch", "stratum"],
                        help="Output level (default: basin)")
    parser.add_argument("--timestep", default="daily",
                        choices=["daily", "monthly", "yearly", "hourly"],
                        help="Timestep (for metadata only)")
    parser.add_argument("--csv-input", action="store_true",
                        help="Input is already CSV (output filter format)")
    parser.add_argument("--basin-area", type=float, default=None,
                        help="Basin area in m^2 (for streamflow conversion to m^3/s)")
    parser.add_argument("--streamflow-unit", default=None, choices=["mm/day", "m/day"],
                        help="Unit of the streamflow column. Legacy basin.daily is mm/day (default). "
                             "Required with --csv-input --basin-area (output-filter CSV is m/day).")
    parser.add_argument("--water-balance", action="store_true",
                        help="Add water balance residual column")
    args = parser.parse_args()

    # Step 1: Validate inputs
    validate_inputs(args)

    # Step 2: Parse
    if args.csv_input:
        records = parse_csv_output(args.input)
        print(f"Parsed {len(records)} rows from CSV")
    else:
        records = parse_legacy_output(args.input, args.level)
        print(f"Parsed {len(records)} rows from legacy output")

    if not records:
        print(json.dumps({"status": "error", "errors": ["No records parsed"]}),
              file=sys.stderr)
        sys.exit(1)

    # Step 3: Process
    records = add_date_column(records)

    if args.basin_area:
        if args.csv_input and args.streamflow_unit is None:
            print(json.dumps({"status": "error", "errors": [
                "--csv-input with --basin-area needs --streamflow-unit (mm/day or m/day)"]}),
                file=sys.stderr)
            sys.exit(1)
        records = convert_streamflow(records, args.basin_area, args.streamflow_unit or "mm/day")
        print(f"Converted streamflow to m^3/s (basin area = {args.basin_area} m^2)")

    if args.water_balance:
        records = compute_water_balance(records)

    # Step 4: Write output
    n = write_csv(records, args.output)
    print(f"Wrote {n} rows to {args.output}")

    # Step 5: Validate output
    result = validate_output(args.output)
    if result.get("warnings"):
        for w in result["warnings"]:
            print(f"WARNING: {w}")
    if result.get("errors"):
        print(json.dumps(result), file=sys.stderr)
        sys.exit(1)

    print(json.dumps({
        "status": "ok",
        "rows": n,
        "output": args.output,
        "level": args.level,
        "timestep": args.timestep,
    }))


if __name__ == "__main__":
    main()
