#!/usr/bin/env python3
"""
Parse SWAP output files and extract results to structured CSV.

Reads SWAP output files (.blc, .inc, .vap, .wba, .csv) and produces
standardized CSV files suitable for analysis and visualization.

Usage:
    python parse_swap_output.py \\
        --work-dir /path/to/case/ \\
        --outfil result \\
        --output-dir /path/to/parsed/
"""

import argparse
import csv
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import numpy as np


def validate_inputs(work_dir, outfil):
    """Pre-flight validation."""
    errors = []
    if not os.path.isdir(work_dir):
        errors.append(f"Working directory not found: {work_dir}")
    else:
        # Check at least one output file exists
        found_any = False
        for ext in [".blc", ".inc", ".vap", ".wba", ".bal", ".csv"]:
            if os.path.isfile(os.path.join(work_dir, outfil + ext)):
                found_any = True
                break
        if not found_any:
            errors.append(f"No SWAP output files found with prefix '{outfil}'")

    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"[OK] Found SWAP output files in {work_dir}")


def parse_blc(filepath):
    """
    Parse detailed yearly water balance (.blc) file.

    Returns list of dicts, one per balance period, with components in cm.
    """
    if not os.path.isfile(filepath):
        return []

    with open(filepath, "r") as f:
        content = f.read()

    balances = []
    # Split by balance periods (separated by horizontal rules)
    periods = content.split("Water balance components")

    for period_text in periods[1:]:  # Skip header
        balance = {}

        # Extract year/period
        year_match = re.search(r"(\d{4})", period_text)
        if year_match:
            balance["year"] = int(year_match.group(1))

        # Extract components using pattern: "Component name : value"
        patterns = {
            "rain": r"Rain \+ snow\s*:\s*([\d.]+)",
            "irrigation": r"Irrigation\s*:\s*([\d.]+)",
            "runon": r"Runon\s*:\s*([\d.]+)",
            "bottom_flux_in": r"Bottom flux\s*:\s*([\d.]+)",
            "interception": r"Interception\s*:\s*([\d.]+)",
            "runoff": r"Runoff\s*:\s*([\d.]+)",
            "transpiration": r"Transpiration\s*:\s*([\d.]+)",
            "soil_evaporation": r"Soil evaporation\s*:\s*([\d.]+)",
            "crack_flux": r"Crack flux\s*:\s*([\d.]+)",
            "drainage": r"Drainage level \d+\s*:\s*([\d.]+)",
        }

        for key, pattern in patterns.items():
            match = re.search(pattern, period_text)
            if match:
                balance[key] = float(match.group(1))

        # Sum lines
        sum_matches = re.findall(r"Sum\s*:\s*([\d.]+)", period_text)
        if len(sum_matches) >= 2:
            balance["sum_in"] = float(sum_matches[0])
            balance["sum_out"] = float(sum_matches[1])

        if balance:
            balances.append(balance)

    return balances


def parse_inc(filepath):
    """
    Parse water balance increments (.inc) file.

    Returns list of daily records with date and flux components.
    """
    if not os.path.isfile(filepath):
        return []

    records = []
    header_found = False
    headers = []

    with open(filepath, "r") as f:
        for line in f:
            line = line.strip()
            # Skip comment lines
            if line.startswith("*") or line.startswith("!") or not line:
                continue

            # Try to detect header line
            if not header_found and any(kw in line.lower() for kw in
                                         ["date", "daynr", "rain"]):
                # Parse header
                headers = re.split(r"\s{2,}|\t|,", line)
                headers = [h.strip() for h in headers if h.strip()]
                header_found = True
                continue

            if header_found:
                values = line.split()
                if len(values) >= 3:
                    record = {}
                    for i, val in enumerate(values):
                        if i < len(headers):
                            try:
                                record[headers[i]] = float(val)
                            except ValueError:
                                record[headers[i]] = val
                    records.append(record)

    return records


def parse_vap(filepath):
    """
    Parse soil profiles (.vap) file.

    Returns list of profile snapshots, each with depth arrays.
    """
    if not os.path.isfile(filepath):
        return []

    profiles = []
    current_profile = None

    with open(filepath, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("*") or line.startswith("!"):
                # Check for date marker
                date_match = re.search(r"(\d{2})-(\w{3})-(\d{4})", line)
                if date_match:
                    if current_profile and current_profile["data"]:
                        profiles.append(current_profile)
                    current_profile = {
                        "date": line,
                        "data": [],
                    }
                continue

            if current_profile is not None:
                values = line.split()
                if len(values) >= 2:
                    try:
                        row = [float(v) for v in values]
                        current_profile["data"].append(row)
                    except ValueError:
                        # Header line within profile
                        current_profile["headers"] = values

    if current_profile and current_profile["data"]:
        profiles.append(current_profile)

    return profiles


def parse_swap_csv(filepath):
    """
    Parse SWAP native CSV output file.

    Returns header list and list of row dicts.
    """
    if not os.path.isfile(filepath):
        return [], []

    rows = []
    headers = []

    with open(filepath, "r") as f:
        for line in f:
            line = line.strip()
            if line.startswith("*"):
                # Could be units line or comment
                if "(" in line:
                    continue
                continue
            if not headers:
                headers = [h.strip() for h in line.split(",")]
                continue
            values = line.split(",")
            row = {}
            for i, v in enumerate(values):
                if i < len(headers):
                    try:
                        row[headers[i]] = float(v.strip())
                    except ValueError:
                        row[headers[i]] = v.strip()
            rows.append(row)

    return headers, rows


def write_summary_csv(output_path, records, fieldnames=None):
    """Write records to CSV file."""
    if not records:
        print(f"  [SKIP] No records to write to {output_path}")
        return

    if fieldnames is None:
        fieldnames = list(records[0].keys())

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)

    print(f"  [OK] Wrote {len(records)} records to {output_path}")


def generate_summary(work_dir, outfil, balances, inc_records):
    """Generate a JSON summary of simulation results."""
    summary = {
        "model": "SWAP v4.2.0",
        "work_dir": work_dir,
        "output_prefix": outfil,
        "n_balance_periods": len(balances),
        "n_daily_records": len(inc_records),
    }

    if balances:
        total_rain = sum(b.get("rain", 0) for b in balances)
        total_et = sum(
            b.get("transpiration", 0) + b.get("soil_evaporation", 0)
            for b in balances
        )
        total_drain = sum(b.get("drainage", 0) for b in balances)
        summary["total_rainfall_cm"] = round(total_rain, 2)
        summary["total_et_cm"] = round(total_et, 2)
        summary["total_drainage_cm"] = round(total_drain, 2)
        summary["years"] = [b.get("year") for b in balances]

    return summary


def validate_outputs(output_dir):
    """Post-processing validation of parsed outputs."""
    errors = []

    if not os.path.isdir(output_dir):
        errors.append(f"Output directory not created: {output_dir}")
        return False

    files = list(Path(output_dir).glob("*.csv")) + list(Path(output_dir).glob("*.json"))
    if not files:
        errors.append("No output files generated")

    for e in errors:
        print(f"ERROR: {e}", file=sys.stderr)

    if errors:
        print(f"[FAIL] Output validation failed")
        return False

    print(f"[OK] Generated {len(files)} output files in {output_dir}")
    return True


def main():
    parser = argparse.ArgumentParser(description="Parse SWAP output files")
    parser.add_argument("--work-dir", type=str, required=True)
    parser.add_argument("--outfil", type=str, default="result",
                        help="SWAP output file prefix")
    parser.add_argument("--output-dir", type=str, required=True,
                        help="Directory for parsed CSV output")
    args = parser.parse_args()

    validate_inputs(args.work_dir, args.outfil)

    os.makedirs(args.output_dir, exist_ok=True)

    # Parse each output type
    blc_path = os.path.join(args.work_dir, args.outfil + ".blc")
    balances = parse_blc(blc_path)
    if balances:
        write_summary_csv(
            os.path.join(args.output_dir, "water_balance.csv"),
            balances,
        )
        print(f"  Parsed {len(balances)} water balance periods from .blc")

    inc_path = os.path.join(args.work_dir, args.outfil + ".inc")
    inc_records = parse_inc(inc_path)
    if inc_records:
        write_summary_csv(
            os.path.join(args.output_dir, "daily_increments.csv"),
            inc_records,
        )
        print(f"  Parsed {len(inc_records)} daily records from .inc")

    vap_path = os.path.join(args.work_dir, args.outfil + ".vap")
    profiles = parse_vap(vap_path)
    if profiles:
        print(f"  Parsed {len(profiles)} soil profile snapshots from .vap")

    # Check for native CSV output
    csv_path = os.path.join(args.work_dir, args.outfil + ".csv")
    csv_headers, csv_rows = parse_swap_csv(csv_path)
    if csv_rows:
        write_summary_csv(
            os.path.join(args.output_dir, "swap_timeseries.csv"),
            csv_rows,
            fieldnames=csv_headers,
        )
        print(f"  Parsed {len(csv_rows)} rows from .csv")

    # Summary JSON
    summary = generate_summary(args.work_dir, args.outfil, balances, inc_records)
    summary_path = os.path.join(args.output_dir, "summary.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"  [OK] Summary written to {summary_path}")

    validate_outputs(args.output_dir)


if __name__ == "__main__":
    main()
