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


# result.blc is a two-column INPUT | OUTPUT table, one block per balance
# period. Each row carries a label in the left-hand margin and its values in
# fixed PLANT / SNOW / POND / SOIL sub-columns, e.g.
#
#   Gross Rainfall     83.72                         |
#                                                    | Interception       5.43
#   SSDI                                        0.00 | Plant Transpiration    76.55
#
# The old split key (a "Water balance" + "components" phrase) appears NOWHERE
# in SWAP 4.2.0 output, so the split matched nothing, parse_blc returned [],
# and water_balance.csv was never written (dt_019). Periods are delimited by
# the `Period             :` line instead.
BLC_INPUT_LABELS = {
    "Gross Rainfall": "rain_cm",
    "Nett Rainfall": "nett_rain_cm",
    "Gross Irrigation": "gross_irrigation_cm",
    "Nett Irrigation": "nett_irrigation_cm",
    "Snowfall": "snowfall_cm",
    "Runon": "runon_cm",
    "Inundation": "inundation_cm",
    "Infiltr. Soil Surf.": "infiltration_cm",
    "Exfiltr. Soil Surf.": "exfiltration_in_cm",
    "Upward seepage": "upward_seepage_cm",
    "Initially Present": "initial_storage_cm",
    "SSDI": "ssdi_cm",
}
BLC_OUTPUT_LABELS = {
    "Interception": "interception_cm",
    "Plant Transpiration": "transpiration_cm",
    "Soil Evaporation": "soil_evaporation_cm",
    "Runoff": "runoff_cm",
    "Sublimation": "sublimation_cm",
    "Downward seepage": "downward_seepage_cm",
    "Finally present": "final_storage_cm",
}
# Rows that carry a value but are neither INPUT nor OUTPUT specific.
BLC_TAIL_LABELS = {
    "Storage Change": "storage_change_cm",
    "Balance Deviation": "balance_deviation_cm",
}


def _blc_numbers(text):
    """Pull the floats out of one half of a .blc row."""
    return [float(v) for v in re.findall(r"-?\d+\.\d+", text)]


def parse_blc(filepath):
    """
    Parse the detailed water balance (.blc) file.

    Returns one dict per balance period with components in cm, including
    `balance_deviation_cm` so a non-closing balance is visible downstream.
    """
    if not os.path.isfile(filepath):
        return []

    with open(filepath, "r", encoding="latin-1") as f:
        content = f.read()

    balances = []
    # Each period block opens with `Period             :  YYYY-MM-DD  until ...`
    blocks = re.split(r"^Period[ \t]*:", content, flags=re.MULTILINE)

    for block in blocks[1:]:
        header, _, body = block.partition("\n")
        balance = {}

        span = re.findall(r"(\d{4}-\d{2}-\d{2})", header)
        if span:
            balance["period_start"] = span[0]
            balance["year"] = int(span[0][:4])
        if len(span) > 1:
            balance["period_end"] = span[1]

        depth = re.search(r"Depth soil profile[ \t]*:[ \t]*([\d.]+)", body)
        if depth:
            balance["profile_depth_cm"] = float(depth.group(1))

        for raw_line in body.splitlines():
            if raw_line.startswith("="):
                continue
            left, sep, right = raw_line.partition("|")

            if sep:
                halves = ((left, BLC_INPUT_LABELS), (right, BLC_OUTPUT_LABELS))
            else:
                halves = ((left, BLC_TAIL_LABELS),)

            for half, label_map in halves:
                stripped = half.strip()
                if not stripped:
                    continue
                for label, key in label_map.items():
                    if not stripped.startswith(label):
                        continue
                    nums = _blc_numbers(stripped[len(label):])
                    if nums:
                        # Sum the PLANT/SNOW/POND/SOIL sub-columns: SWAP only
                        # ever populates one of them per row, except for
                        # Balance Deviation where the worst case is what matters.
                        if key == "balance_deviation_cm":
                            balance[key] = max(nums, key=abs)
                        else:
                            balance[key] = sum(nums)
                    break

            # `Sum` appears once per half of the totals row.
            if sep and left.strip().startswith("Sum"):
                nums_in = _blc_numbers(left)
                nums_out = _blc_numbers(right)
                if nums_in:
                    balance["sum_in_cm"] = round(sum(nums_in), 3)
                if nums_out:
                    balance["sum_out_cm"] = round(sum(nums_out), 3)

            # Drainage systems are numbered: `- system 1     0.00 | ...  22.11`
            m = re.match(r"^-[ \t]*system[ \t]*(\d+)", left.strip())
            if m and sep:
                nums_out = _blc_numbers(right)
                if nums_out:
                    balance["drainage_cm"] = balance.get("drainage_cm", 0.0) \
                        + sum(nums_out)

        if len(balance) > 2:
            balance.setdefault("drainage_cm", 0.0)
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

    with open(filepath, "r", encoding="latin-1") as f:
        for line in f:
            line = line.strip()
            # Skip comment lines
            if line.startswith("*") or line.startswith("!") or not line:
                continue

            # Try to detect header line
            if not header_found and any(kw in line.lower() for kw in
                                         ["date", "daynr", "rain"]):
                headers = [h.strip() for h in line.split(",") if h.strip()]
                header_found = True
                continue

            if header_found:
                # .inc rows are COMMA-separated and blank-padded, e.g.
                #   2001-01-01 ,  1,     1,   0.07300, ... ,          ,   0.01421
                # Splitting on whitespace makes token[1] the bare ',' after the
                # date and shifts every subsequent field by one (dt_019).
                values = [v.strip() for v in line.split(",")]
                if len(values) >= 3:
                    record = {}
                    for i, val in enumerate(values):
                        if i >= len(headers):
                            break
                        if val == "":
                            record[headers[i]] = ""   # e.g. an absent Gwl
                            continue
                        try:
                            record[headers[i]] = float(val)
                        except ValueError:
                            record[headers[i]] = val
                    records.append(record)

    return records


def parse_vap(filepath):
    """
    Parse the soil profiles (.vap) file.

    The file is a flat, comma-separated table whose real column header is

        date, depth, wcontent, phead, hconduc, drainage, rootext,
        waterflux, temp, solute1, solute2, soluteflux, top, bottom, day, dcum

    preceded by a units line. There is no `dd-Mon-yyyy` block marker — the
    old date-marker hunt matched nothing, so every profile was dropped. The
    units line also contains `ºC` (0xBA), which raises UnicodeDecodeError on
    a default UTF-8 open, so the file must be read as latin-1 (dt_019).

    Returns a flat list of row dicts, one per depth per date.
    """
    if not os.path.isfile(filepath):
        return []

    rows = []
    headers = []

    with open(filepath, "r", encoding="latin-1") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("*") or line.startswith("!"):
                continue

            fields = [v.strip() for v in line.split(",")]

            if not headers:
                # The header row is the one naming the date and depth columns;
                # the units line above it holds no column names.
                lowered = [v.lower() for v in fields]
                if "date" in lowered and "depth" in lowered:
                    headers = lowered
                continue

            if len(fields) < 3:
                continue

            record = {}
            for i, val in enumerate(fields):
                if i >= len(headers):
                    break
                if val == "":
                    record[headers[i]] = ""
                    continue
                try:
                    record[headers[i]] = float(val)
                except ValueError:
                    record[headers[i]] = val
            if record:
                rows.append(record)

    return rows


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
        total_rain = sum(b.get("rain_cm", 0) for b in balances)
        # ET follows the dag: transpiration + soil evaporation + interception.
        total_et = sum(
            b.get("transpiration_cm", 0) + b.get("soil_evaporation_cm", 0)
            + b.get("interception_cm", 0)
            for b in balances
        )
        total_irrig = sum(b.get("gross_irrigation_cm", 0) for b in balances)
        total_drain = sum(b.get("drainage_cm", 0) for b in balances)
        worst_dev = max((abs(b.get("balance_deviation_cm", 0.0))
                         for b in balances), default=0.0)
        summary["total_rainfall_cm"] = round(total_rain, 2)
        summary["total_irrigation_cm"] = round(total_irrig, 2)
        summary["total_et_cm"] = round(total_et, 2)
        summary["total_drainage_cm"] = round(total_drain, 2)
        summary["max_abs_balance_deviation_cm"] = round(worst_dev, 4)
        summary["years"] = [b.get("year") for b in balances]
        if worst_dev > 0.01:
            print(f"WARNING: water balance does not close — worst period "
                  f"deviation {worst_dev:.4f} cm")

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
        # Union of keys — SWAP omits rows (e.g. drainage systems) per case.
        fieldnames = []
        for b in balances:
            for k in b:
                if k not in fieldnames:
                    fieldnames.append(k)
        write_summary_csv(
            os.path.join(args.output_dir, "water_balance.csv"),
            balances,
            fieldnames=fieldnames,
        )
        print(f"  Parsed {len(balances)} water balance periods from .blc")
    elif os.path.isfile(blc_path):
        print(f"ERROR: {blc_path} exists but no balance periods were parsed",
              file=sys.stderr)
        sys.exit(1)

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
        write_summary_csv(
            os.path.join(args.output_dir, "soil_profiles.csv"),
            profiles,
        )
        n_dates = len({r.get("date") for r in profiles})
        print(f"  Parsed {len(profiles)} soil profile rows "
              f"({n_dates} snapshots) from .vap")
    elif os.path.isfile(vap_path):
        print(f"ERROR: {vap_path} exists but no profile rows were parsed",
              file=sys.stderr)
        sys.exit(1)

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
