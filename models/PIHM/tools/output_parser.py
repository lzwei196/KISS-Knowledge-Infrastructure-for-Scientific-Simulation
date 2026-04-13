#!/usr/bin/env python3
"""
output_parser.py — Parse MM-PIHM binary output files to CSV.

Reads PIHM binary .dat output files and converts to CSV with timestamps
and element/river IDs as headers. Supports all standard PIHM output
variables (surface water, groundwater, river stage, fluxes, etc.).

Output format:
  - First column: timestamp (YYYY-MM-DD HH:MM)
  - Subsequent columns: one per element/river segment
  - Values in original PIHM units (see SKILL.md §8)

Usage:
    python output_parser.py --input output/test_run/ --project ShaleHills \\
        --variables gw,surf,rivflx1 --output results.csv

    python output_parser.py --input output/test_run/ --project ShaleHills \\
        --variables gw --output gw.csv --start 2009-03-01 --end 2009-09-30

    python output_parser.py --list-variables --input output/test_run/ \\
        --project ShaleHills
"""

import argparse
import csv
import glob
import json
import os
import struct
import sys
from datetime import datetime, timedelta


# Map variable names to file suffixes and types
VARIABLE_MAP = {
    # Element-based state variables
    "surf":     {"suffix": ".surf.dat",     "type": "elem", "unit": "m",    "desc": "Surface water depth"},
    "unsat":    {"suffix": ".unsat.dat",     "type": "elem", "unit": "m",    "desc": "Unsaturated zone storage"},
    "gw":       {"suffix": ".gw.dat",        "type": "elem", "unit": "m",    "desc": "Groundwater head"},
    "snow":     {"suffix": ".snow.dat",      "type": "elem", "unit": "m",    "desc": "Snow water equivalent"},
    "cmc":      {"suffix": ".cmc.dat",       "type": "elem", "unit": "m",    "desc": "Canopy moisture content"},
    "soilm":    {"suffix": ".soilm.dat",     "type": "elem", "unit": "m",    "desc": "Total soil moisture"},
    # Element-based flux variables
    "infil":    {"suffix": ".infil.dat",     "type": "elem", "unit": "m/s",  "desc": "Infiltration rate"},
    "recharge": {"suffix": ".recharge.dat",  "type": "elem", "unit": "m/s",  "desc": "GW recharge rate"},
    "ec":       {"suffix": ".ec.dat",        "type": "elem", "unit": "m/s",  "desc": "Canopy evaporation"},
    "ett":      {"suffix": ".ett.dat",       "type": "elem", "unit": "m/s",  "desc": "Transpiration"},
    "edir":     {"suffix": ".edir.dat",      "type": "elem", "unit": "m/s",  "desc": "Direct soil evaporation"},
    # River-based variables
    "stage":    {"suffix": ".stage.dat",     "type": "river","unit": "m",    "desc": "River water stage"},
    "rivflx0":  {"suffix": ".rivflx0.dat",  "type": "river","unit": "m3/s", "desc": "Upstream river flux"},
    "rivflx1":  {"suffix": ".rivflx1.dat",  "type": "river","unit": "m3/s", "desc": "Downstream river flux"},
    "rivflx2":  {"suffix": ".rivflx2.dat",  "type": "river","unit": "m3/s", "desc": "Left bank surface flux"},
    "rivflx3":  {"suffix": ".rivflx3.dat",  "type": "river","unit": "m3/s", "desc": "Right bank surface flux"},
    "rivflx4":  {"suffix": ".rivflx4.dat",  "type": "river","unit": "m3/s", "desc": "Left bank aquifer flux"},
    "rivflx5":  {"suffix": ".rivflx5.dat",  "type": "river","unit": "m3/s", "desc": "Right bank aquifer flux"},
    # Subsurface fluxes
    "subflx":   {"suffix": ".subflx.dat",   "type": "elem", "unit": "m3/s", "desc": "Subsurface lateral flux"},
    "surfflx":  {"suffix": ".surfflx.dat",  "type": "elem", "unit": "m3/s", "desc": "Surface overland flux"},
}


def validate_inputs(args):
    """Validate input arguments."""
    errors = []
    if not os.path.isdir(args.input):
        errors.append(f"Output directory not found: {args.input}")

    if not args.list_variables:
        if not args.variables:
            errors.append("No variables specified. Use --variables or --list-variables.")
        else:
            for v in args.variables.split(","):
                v = v.strip().lower()
                if v not in VARIABLE_MAP:
                    errors.append(f"Unknown variable '{v}'. Use --list-variables to see available.")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)


def detect_dimensions(input_dir, project):
    """Detect number of elements and river segments from output file sizes."""
    # Try reading a known element file to detect nelem
    nelem = 0
    nriver = 0

    for suffix, vtype in [(".gw.dat", "elem"), (".surf.dat", "elem"),
                           (".stage.dat", "river"), (".rivflx1.dat", "river")]:
        fpath = os.path.join(input_dir, project + suffix)
        if os.path.exists(fpath):
            fsize = os.path.getsize(fpath)
            if fsize == 0:
                continue

            # Read first record to determine n
            with open(fpath, "rb") as f:
                # First 4 bytes: timestamp (int32)
                ts_bytes = f.read(4)
                if len(ts_bytes) < 4:
                    continue
                ts = struct.unpack("i", ts_bytes)[0]

                # Read remaining doubles until next timestamp marker
                # Record size = 4 (int) + n * 8 (doubles)
                # Try to figure out n from file size and assuming uniform records
                # Total records * (4 + n*8) = fsize
                # Try n from 1 to 10000
                remaining = fsize - 4
                # Read all remaining bytes of first record
                # We need to find n such that fsize % (4 + n*8) == 0
                for n in range(1, 10001):
                    record_size = 4 + n * 8
                    if fsize % record_size == 0:
                        if vtype == "elem" and nelem == 0:
                            nelem = n
                        elif vtype == "river" and nriver == 0:
                            nriver = n
                        break

    return nelem, nriver


def read_binary_output(filepath, n_columns):
    """Read a PIHM binary output file.

    Format: [int32 timestamp] [float64 val1] [float64 val2] ... [float64 valN]
    Repeated for each output timestep.
    """
    records = []
    record_size = 4 + n_columns * 8  # int32 + n * float64

    fsize = os.path.getsize(filepath)
    if fsize == 0:
        return records

    n_records = fsize // record_size
    if fsize % record_size != 0:
        # Try with different n_columns
        return records

    with open(filepath, "rb") as f:
        for _ in range(n_records):
            data = f.read(record_size)
            if len(data) < record_size:
                break

            ts = struct.unpack("i", data[:4])[0]
            values = struct.unpack(f"{n_columns}d", data[4:])

            # Convert Unix timestamp to datetime
            try:
                dt = datetime.utcfromtimestamp(ts)
                dt_str = dt.strftime("%Y-%m-%d %H:%M")
            except (OSError, ValueError):
                dt_str = str(ts)

            records.append({"time": dt_str, "timestamp": ts, "values": list(values)})

    return records


def filter_by_time(records, start_str, end_str):
    """Filter records by time range."""
    if not start_str and not end_str:
        return records

    filtered = []
    for rec in records:
        try:
            dt = datetime.strptime(rec["time"], "%Y-%m-%d %H:%M")
            if start_str:
                start_dt = datetime.strptime(start_str, "%Y-%m-%d")
                if dt < start_dt:
                    continue
            if end_str:
                end_dt = datetime.strptime(end_str, "%Y-%m-%d")
                if dt > end_dt:
                    continue
            filtered.append(rec)
        except ValueError:
            filtered.append(rec)  # Keep if can't parse

    return filtered


def process(args):
    """Parse binary output and write CSV."""
    nelem, nriver = detect_dimensions(args.input, args.project)

    if args.list_variables:
        # List available variables with file existence check
        available = []
        for var, info in VARIABLE_MAP.items():
            fpath = os.path.join(args.input, args.project + info["suffix"])
            exists = os.path.exists(fpath)
            fsize = os.path.getsize(fpath) if exists else 0
            available.append({
                "variable": var,
                "suffix": info["suffix"],
                "type": info["type"],
                "unit": info["unit"],
                "description": info["desc"],
                "exists": exists,
                "size_mb": round(fsize / 1e6, 2) if exists else 0,
            })
        return {"status": "success", "variables": available,
                "nelem": nelem, "nriver": nriver}

    variables = [v.strip().lower() for v in args.variables.split(",")]
    all_data = {}

    for var in variables:
        info = VARIABLE_MAP[var]
        fpath = os.path.join(args.input, args.project + info["suffix"])

        if not os.path.exists(fpath):
            print(f"Warning: File not found for {var}: {fpath}", file=sys.stderr)
            continue

        n_cols = nelem if info["type"] == "elem" else nriver
        if n_cols == 0:
            print(f"Warning: Cannot determine dimensions for {var}", file=sys.stderr)
            continue

        records = read_binary_output(fpath, n_cols)
        records = filter_by_time(records, args.start, args.end)
        all_data[var] = {"records": records, "n_cols": n_cols, "info": info}

    # Write combined CSV
    if args.output and all_data:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)

        # Use the first variable's timestamps as reference
        first_var = list(all_data.keys())[0]
        ref_records = all_data[first_var]["records"]

        with open(args.output, "w", newline="") as f:
            writer = csv.writer(f)

            # Header
            header = ["time"]
            for var in all_data:
                info = all_data[var]["info"]
                n_cols = all_data[var]["n_cols"]
                prefix = "elem" if info["type"] == "elem" else "riv"
                for i in range(n_cols):
                    header.append(f"{var}_{prefix}{i+1}_{info['unit']}")
            writer.writerow(header)

            # Data rows
            for idx, ref_rec in enumerate(ref_records):
                row = [ref_rec["time"]]
                for var in all_data:
                    recs = all_data[var]["records"]
                    if idx < len(recs):
                        row.extend(recs[idx]["values"])
                    else:
                        row.extend([""] * all_data[var]["n_cols"])
                writer.writerow(row)

    n_records = len(ref_records) if all_data else 0
    return {
        "status": "success",
        "output": args.output,
        "variables_parsed": list(all_data.keys()),
        "n_records": n_records,
        "nelem": nelem,
        "nriver": nriver,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Parse MM-PIHM binary output files to CSV"
    )
    parser.add_argument("--input", required=True, help="PIHM output directory")
    parser.add_argument("--project", required=True, help="Project name")
    parser.add_argument("--variables", default=None,
                        help="Comma-separated variable names (e.g., gw,surf,rivflx1)")
    parser.add_argument("--output", default=None, help="Output CSV file path")
    parser.add_argument("--start", default=None, help="Start date filter (YYYY-MM-DD)")
    parser.add_argument("--end", default=None, help="End date filter (YYYY-MM-DD)")
    parser.add_argument("--list-variables", action="store_true",
                        help="List available output variables and exit")
    args = parser.parse_args()

    validate_inputs(args)
    result = process(args)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
