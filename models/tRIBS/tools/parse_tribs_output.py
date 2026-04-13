#!/usr/bin/env python3
"""Parse tRIBS output files (pixel, outlet, MRF) into CSV format.

Supports:
  - Pixel files (.pixel): per-node time series with 50+ variables
  - Outlet files (.qout): discharge time series at outlet
  - Mean response files (.mrf): basin-averaged water balance

Usage:
  python parse_tribs_output.py \\
      --input /path/to/output/ \\
      --output /path/to/results/ \\
      --format pixel \\
      --variables "Rain,TA,Qout,srf,EvapoTranspiration"
"""

import argparse
import csv
import glob
import json
import math
import os
import re
import sys


# ---------------------------------------------------------------------------
# Pixel file column definitions
# ---------------------------------------------------------------------------

# Standard pixel file column order (may vary by tRIBS version)
PIXEL_COLUMNS = [
    "Time_hr", "Rain_mm_hr", "Interception_mm", "NetPrecip_mm_hr",
    "CanStorage_mm", "CumRain_mm", "CumIntercept_mm",
    "EvapWetCanopy_mm_hr", "EvapDryCanopy_mm_hr", "EvapSoil_mm_hr",
    "EvapoTranspiration_mm_hr", "PotEvap_mm_hr", "ActEvap_mm_hr",
    "CumET_mm", "SoilMoist_top", "RootMoist",
    "AirTemp_C", "DewTemp_C", "SurfTemp_C", "SoilTemp_C",
    "AirPress_mb", "RelHumid", "VapPress_mb", "WindSpeed_ms",
    "SkyCover", "ShortRadIn_Wm2", "ShortRadIn_dir", "ShortRadIn_dif",
    "LongRadIn_Wm2", "LongRadOut_Wm2", "NetRad_Wm2",
    "Nwt_mm", "NwtNew_mm", "MuOld", "MuNew", "MiOld", "MiNew",
    "NtOld", "NtNew", "NfOld", "NfNew", "RuOld", "RuNew",
    "Qin_m3s", "Qout_m3s", "Qpin", "Qpout",
    "srf_mm", "hsrf_mm", "esrf_mm", "psrf_mm",
    "satsrf_mm", "rsrf_mm", "sbsrf_mm",
    "UnSatStorage_mm", "SatStorage_mm",
    "CumRunoff_mm", "CumSrf_mm", "CumHsrf_mm",
]

# Snow-related columns (appended when OPTSNOW=1)
SNOW_COLUMNS = [
    "liqWEq_mm", "iceWEq_mm", "snTemperC",
    "cumMelt_mm", "cumSnSub_mm", "cumSnEvap_mm",
    "snLHF_Wm2", "snSHF_Wm2", "snGHF_Wm2", "snPHF_Wm2",
    "snRLin_Wm2", "snRLout_Wm2", "snRSin_Wm2",
]

# Outlet file columns
OUTLET_COLUMNS = ["Time_hr", "Discharge_m3s"]

# MRF columns (basin-averaged)
MRF_COLUMNS = [
    "Time_hr", "MeanRain_mm_hr", "MeanET_mm_hr",
    "MeanRunoff_mm_hr", "MeanInfiltration_mm_hr",
    "MeanSoilMoist", "MeanGW_mm",
]


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def validate_inputs(args):
    """Pre-flight validation."""
    errors = []
    if not os.path.exists(args.input):
        errors.append(f"Input path does not exist: {args.input}")
    if args.format not in ("pixel", "outlet", "mrf", "all"):
        errors.append(f"Unsupported format: {args.format}")
    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)


def validate_outputs(output_files):
    """Post-processing validation."""
    warnings = []
    for fpath in output_files:
        if not os.path.isfile(fpath):
            warnings.append(f"Output file not created: {fpath}")
            continue
        with open(fpath) as f:
            lines = f.readlines()
        if len(lines) < 2:
            warnings.append(f"Output file has < 2 lines: {fpath}")
        # Check for NaN values
        for i, line in enumerate(lines[1:5], start=2):
            if "nan" in line.lower() or "inf" in line.lower():
                warnings.append(
                    f"NaN/Inf detected in {fpath} at line {i}. "
                    "Check input forcing for gaps or unit errors."
                )
                break
    for w in warnings:
        print(f"WARNING: {w}", file=sys.stderr)
    return warnings


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def find_output_files(input_path, pattern):
    """Find output files matching pattern in input path."""
    if os.path.isfile(input_path):
        return [input_path]
    return sorted(glob.glob(os.path.join(input_path, pattern)))


def parse_pixel_file(filepath, variables=None):
    """Parse a tRIBS pixel file into records.

    Pixel files are space-delimited with optional header line.
    Returns list of dicts with named columns.
    """
    records = []
    with open(filepath) as f:
        lines = f.readlines()

    if not lines:
        return records

    # Detect if first line is header
    first_line = lines[0].strip()
    has_header = not first_line[0].isdigit() and not first_line[0] == "-"

    if has_header:
        # Use header columns
        col_names = first_line.split()
        data_lines = lines[1:]
    else:
        # Determine number of columns from first data line
        n_cols = len(first_line.split())
        if n_cols > len(PIXEL_COLUMNS):
            col_names = PIXEL_COLUMNS + SNOW_COLUMNS[:n_cols - len(PIXEL_COLUMNS)]
        else:
            col_names = PIXEL_COLUMNS[:n_cols]
        data_lines = lines

    for line in data_lines:
        vals = line.strip().split()
        if not vals:
            continue
        rec = {}
        for j, val in enumerate(vals):
            if j < len(col_names):
                try:
                    rec[col_names[j]] = float(val)
                except ValueError:
                    rec[col_names[j]] = val
        records.append(rec)

    # Filter to requested variables
    if variables:
        var_list = [v.strip() for v in variables.split(",")]
        # Always include time
        if col_names[0] not in var_list:
            var_list.insert(0, col_names[0])
        filtered = []
        for rec in records:
            f_rec = {k: rec.get(k, None) for k in var_list if k in rec}
            if f_rec:
                filtered.append(f_rec)
        return filtered

    return records


def parse_outlet_file(filepath):
    """Parse tRIBS outlet discharge file.

    Format: space-delimited with Time(hr) and Q(m³/s).
    """
    records = []
    with open(filepath) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) >= 2:
                try:
                    t = float(parts[0])
                    q = float(parts[1])
                    records.append({"Time_hr": t, "Discharge_m3s": q})
                except ValueError:
                    continue
    return records


def parse_mrf_file(filepath):
    """Parse tRIBS mean response file (basin-averaged)."""
    records = []
    with open(filepath) as f:
        lines = f.readlines()

    has_header = lines and not lines[0].strip()[0].isdigit()
    if has_header:
        col_names = lines[0].strip().split()
        data_lines = lines[1:]
    else:
        col_names = MRF_COLUMNS
        data_lines = lines

    for line in data_lines:
        vals = line.strip().split()
        if not vals:
            continue
        rec = {}
        for j, val in enumerate(vals):
            key = col_names[j] if j < len(col_names) else f"Col_{j}"
            try:
                rec[key] = float(val)
            except ValueError:
                rec[key] = val
        records.append(rec)

    return records


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------

def write_csv(records, output_path):
    """Write records to CSV."""
    if not records:
        return
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    keys = list(records[0].keys())
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(records)


def compute_summary_stats(records, var_name):
    """Compute summary statistics for a variable."""
    vals = [r[var_name] for r in records if var_name in r and r[var_name] is not None]
    if not vals:
        return {}
    vals_float = [float(v) for v in vals if not (isinstance(v, float) and math.isnan(v))]
    if not vals_float:
        return {"count": 0, "nan_count": len(vals)}
    return {
        "count": len(vals_float),
        "min": round(min(vals_float), 4),
        "max": round(max(vals_float), 4),
        "mean": round(sum(vals_float) / len(vals_float), 4),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Parse tRIBS output files to CSV."
    )
    parser.add_argument("--input", required=True,
                        help="Input file or directory containing tRIBS output")
    parser.add_argument("--output", required=True,
                        help="Output directory for CSV files")
    parser.add_argument("--format", default="all",
                        choices=["pixel", "outlet", "mrf", "all"],
                        help="Output format to parse (default: all)")
    parser.add_argument("--variables", default=None,
                        help="Comma-separated variable names to extract (pixel only)")
    parser.add_argument("--json-output", type=str, default=None,
                        help="Write result summary to JSON file")

    args = parser.parse_args()

    # --- Validate inputs ---
    validate_inputs(args)
    os.makedirs(args.output, exist_ok=True)

    all_output_files = []
    summary = {"status": "success", "parsed_files": {}}

    # --- Parse pixel files ---
    if args.format in ("pixel", "all"):
        pixel_files = find_output_files(args.input, "*.pixel")
        for pf in pixel_files:
            records = parse_pixel_file(pf, args.variables)
            base = os.path.splitext(os.path.basename(pf))[0]
            out_path = os.path.join(args.output, f"{base}_pixel.csv")
            write_csv(records, out_path)
            all_output_files.append(out_path)
            summary["parsed_files"][base] = {
                "type": "pixel",
                "n_records": len(records),
                "n_columns": len(records[0]) if records else 0,
                "output": out_path,
            }

    # --- Parse outlet files ---
    if args.format in ("outlet", "all"):
        outlet_files = find_output_files(args.input, "*.qout")
        for of in outlet_files:
            records = parse_outlet_file(of)
            base = os.path.splitext(os.path.basename(of))[0]
            out_path = os.path.join(args.output, f"{base}_discharge.csv")
            write_csv(records, out_path)
            all_output_files.append(out_path)

            stats = compute_summary_stats(records, "Discharge_m3s")
            summary["parsed_files"][base] = {
                "type": "outlet",
                "n_records": len(records),
                "discharge_stats": stats,
                "output": out_path,
            }

    # --- Parse MRF files ---
    if args.format in ("mrf", "all"):
        mrf_files = find_output_files(args.input, "*.mrf")
        for mf in mrf_files:
            records = parse_mrf_file(mf)
            base = os.path.splitext(os.path.basename(mf))[0]
            out_path = os.path.join(args.output, f"{base}_mrf.csv")
            write_csv(records, out_path)
            all_output_files.append(out_path)
            summary["parsed_files"][base] = {
                "type": "mrf",
                "n_records": len(records),
                "output": out_path,
            }

    # --- Validate outputs ---
    warnings = validate_outputs(all_output_files)
    summary["warnings"] = warnings
    summary["total_files_parsed"] = len(all_output_files)

    output_json = json.dumps(summary, indent=2)
    if args.json_output:
        with open(args.json_output, "w") as f:
            f.write(output_json)
    print(output_json)


if __name__ == "__main__":
    main()
