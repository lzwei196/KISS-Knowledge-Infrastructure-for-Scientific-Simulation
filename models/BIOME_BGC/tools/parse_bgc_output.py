#!/usr/bin/env python3
"""
parse_bgc_output.py
Parse BIOME-BGC ASCII output files and extract key carbon/water fluxes.

Reads the .dayout.ascii and .annout.ascii files produced by BIOME-BGC
with the -a flag. Computes summary statistics, annual budgets, and
performs physical reasonableness checks.

Output columns in .dayout.ascii correspond to the DAILY_OUTPUT variables
specified in the .ini file, tab-separated, one row per day.

Output columns in .annout.ascii correspond to ANNUAL_OUTPUT variables,
one row per year.

Usage:
    python parse_bgc_output.py \\
        --daily_file outputs/test.dayout.ascii \\
        --annual_file outputs/test.annout.ascii \\
        --start_year 2000 --n_years 10 \\
        --output_csv outputs/test_summary.csv

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import json
import argparse
import csv
from pathlib import Path
from collections import defaultdict


# Standard daily output column order (must match .ini DAILY_OUTPUT)
# This is the default set from generate_site_ini.py STANDARD_DAILY_OUTPUT
DAILY_COLUMNS = [
    "soilw",        # ws.soilw (kgH2O/m2)
    "snoww",        # ws.snoww (kgH2O/m2)
    "proj_lai",     # epv.proj_lai (m2/m2)
    "net_nmin",     # epv.daily_net_nmin (kgN/m2/d)
    "daily_npp",    # summary.daily_npp (kgC/m2/d)
    "daily_nep",    # summary.daily_nep (kgC/m2/d)
    "daily_nee",    # summary.daily_nee (kgC/m2/d)
    "daily_gpp",    # summary.daily_gpp (kgC/m2/d)
    "daily_mr",     # summary.daily_mr (kgC/m2/d)
    "daily_gr",     # summary.daily_gr (kgC/m2/d)
    "daily_hr",     # summary.daily_hr (kgC/m2/d)
    "daily_fire",   # summary.daily_fire (kgC/m2/d)
    "vegc",         # summary.vegc (kgC/m2)
    "litrc",        # summary.litrc (kgC/m2)
    "soilc",        # summary.soilc (kgC/m2)
    "totalc",       # summary.totalc (kgC/m2)
    "daily_et",     # summary.daily_et (kgH2O/m2/d = mm/d)
    "daily_outflow", # summary.daily_outflow (kgH2O/m2/d)
    "daily_trans",  # summary.daily_trans (kgH2O/m2/d)
    "daily_soilw",  # summary.daily_soilw (kgH2O/m2)
    "daily_snoww",  # summary.daily_snoww (kgH2O/m2)
    "psn_sun_A",    # psn_sun.A (umol/m2/s)
    "outflow",      # wf.soilw_outflow (kgH2O/m2/d)
]

ANNUAL_COLUMNS = [
    "max_lai",    # epv.ytd_maxplai (m2/m2)
    "vegc",       # summary.vegc (kgC/m2)
    "litrc",      # summary.litrc (kgC/m2)
    "soilc",      # summary.soilc (kgC/m2)
    "totalc",     # summary.totalc (kgC/m2)
    "sminn",      # ns.sminn (kgN/m2)
]


def read_ascii_output(filepath, column_names, start_year, n_years):
    """Read tab-separated ASCII output file."""
    records = []
    with open(filepath, 'r') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            vals = line.split('\t')
            if len(vals) == 0:
                vals = line.split()
            if len(vals) < len(column_names):
                # Pad with None
                vals.extend([None] * (len(column_names) - len(vals)))
            record = {}
            for i, col in enumerate(column_names):
                try:
                    record[col] = float(vals[i]) if vals[i] is not None else None
                except (ValueError, IndexError):
                    record[col] = None
            records.append(record)
    return records


def compute_annual_summary(daily_records, start_year):
    """Compute annual summaries from daily records."""
    annual = defaultdict(lambda: defaultdict(float))
    year = start_year
    day_in_year = 0

    for rec in daily_records:
        day_in_year += 1
        if day_in_year > 365:
            year += 1
            day_in_year = 1

        for var in ["daily_gpp", "daily_npp", "daily_nep", "daily_nee",
                     "daily_mr", "daily_gr", "daily_hr", "daily_fire",
                     "daily_et", "daily_outflow", "daily_trans"]:
            if rec.get(var) is not None:
                annual[year][var + "_sum"] += rec[var]

        # Track last-day C stocks
        for var in ["vegc", "litrc", "soilc", "totalc"]:
            if rec.get(var) is not None:
                annual[year][var] = rec[var]

        # Track max LAI
        if rec.get("proj_lai") is not None:
            cur = annual[year].get("max_lai", 0)
            annual[year]["max_lai"] = max(cur, rec["proj_lai"])

    return dict(annual)


def physical_checks(annual_summaries):
    """Check physical reasonableness of results."""
    warnings = []

    for year, data in sorted(annual_summaries.items()):
        # Convert daily sums to annual (kgC/m2/yr -> gC/m2/yr)
        gpp = data.get("daily_gpp_sum", 0) * 1000  # kgC -> gC
        npp = data.get("daily_npp_sum", 0) * 1000
        nee = data.get("daily_nee_sum", 0) * 1000
        et = data.get("daily_et_sum", 0)  # mm/yr
        soilc = data.get("soilc", 0) * 1000  # gC/m2

        if gpp < 0:
            warnings.append(f"Year {year}: GPP = {gpp:.0f} gC/m2/yr (negative!)")
        if gpp > 3000:
            warnings.append(f"Year {year}: GPP = {gpp:.0f} gC/m2/yr "
                            "(>3000, unrealistically high)")
        if gpp > 0 and npp > gpp:
            warnings.append(f"Year {year}: NPP ({npp:.0f}) > GPP ({gpp:.0f})")

        cue = npp / gpp if gpp > 0 else 0
        if gpp > 0 and (cue < 0.2 or cue > 0.8):
            warnings.append(f"Year {year}: CUE = {cue:.2f} "
                            "(expected 0.3-0.6 for forests)")

        if et < 0:
            warnings.append(f"Year {year}: ET = {et:.0f} mm/yr (negative!)")
        if et > 2000:
            warnings.append(f"Year {year}: ET = {et:.0f} mm/yr (very high)")

    return warnings


def main():
    parser = argparse.ArgumentParser(
        description="Parse BIOME-BGC output files")
    parser.add_argument("--daily_file", default=None,
                        help="Daily output .dayout.ascii file")
    parser.add_argument("--annual_file", default=None,
                        help="Annual output .annout.ascii file")
    parser.add_argument("--start_year", type=int, required=True)
    parser.add_argument("--n_years", type=int, required=True)
    parser.add_argument("--output_csv", default=None,
                        help="Output CSV with annual summaries")
    parser.add_argument("--daily_columns", default=None,
                        help="Comma-separated column names for daily file")
    parser.add_argument("--annual_columns", default=None,
                        help="Comma-separated column names for annual file")

    args = parser.parse_args()

    if not args.daily_file and not args.annual_file:
        result = {"status": "error", "stage": "input_validation",
                  "message": "Provide at least one of --daily_file or --annual_file"}
        print(json.dumps(result, indent=2))
        sys.exit(1)

    daily_cols = args.daily_columns.split(",") if args.daily_columns else DAILY_COLUMNS
    annual_cols = args.annual_columns.split(",") if args.annual_columns else ANNUAL_COLUMNS

    # Parse daily output
    daily_records = []
    annual_summaries = {}
    if args.daily_file and os.path.isfile(args.daily_file):
        try:
            daily_records = read_ascii_output(
                args.daily_file, daily_cols, args.start_year, args.n_years)
            annual_summaries = compute_annual_summary(
                daily_records, args.start_year)
        except Exception as e:
            result = {"status": "error", "stage": "processing",
                      "message": f"Failed to parse daily output: {e}"}
            print(json.dumps(result, indent=2))
            sys.exit(2)

    # Parse annual output
    annual_records = []
    if args.annual_file and os.path.isfile(args.annual_file):
        try:
            annual_records = read_ascii_output(
                args.annual_file, annual_cols, args.start_year, args.n_years)
        except Exception as e:
            result = {"status": "error", "stage": "processing",
                      "message": f"Failed to parse annual output: {e}"}
            print(json.dumps(result, indent=2))
            sys.exit(2)

    # Physical checks
    warnings = physical_checks(annual_summaries) if annual_summaries else []

    # Write CSV if requested
    if args.output_csv and annual_summaries:
        try:
            out_path = Path(args.output_csv)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with open(out_path, 'w', newline='') as f:
                writer = csv.writer(f)
                cols = ["year", "gpp_gCm2yr", "npp_gCm2yr", "nee_gCm2yr",
                        "et_mmyr", "max_lai", "vegc_kgCm2", "soilc_kgCm2",
                        "totalc_kgCm2"]
                writer.writerow(cols)
                for year in sorted(annual_summaries.keys()):
                    d = annual_summaries[year]
                    writer.writerow([
                        year,
                        round(d.get("daily_gpp_sum", 0) * 1000, 1),
                        round(d.get("daily_npp_sum", 0) * 1000, 1),
                        round(d.get("daily_nee_sum", 0) * 1000, 1),
                        round(d.get("daily_et_sum", 0), 1),
                        round(d.get("max_lai", 0), 2),
                        round(d.get("vegc", 0), 3),
                        round(d.get("soilc", 0), 3),
                        round(d.get("totalc", 0), 3),
                    ])
        except Exception as e:
            result = {"status": "error", "stage": "output",
                      "message": f"Failed to write CSV: {e}"}
            print(json.dumps(result, indent=2))
            sys.exit(3)

    # Build summary
    summary = {}
    if annual_summaries:
        years = sorted(annual_summaries.keys())
        last = annual_summaries[years[-1]]
        mean_gpp = sum(annual_summaries[y].get("daily_gpp_sum", 0)
                       for y in years) / len(years) * 1000
        mean_npp = sum(annual_summaries[y].get("daily_npp_sum", 0)
                       for y in years) / len(years) * 1000
        mean_nee = sum(annual_summaries[y].get("daily_nee_sum", 0)
                       for y in years) / len(years) * 1000
        mean_et = sum(annual_summaries[y].get("daily_et_sum", 0)
                      for y in years) / len(years)

        summary = {
            "mean_annual_gpp_gCm2yr": round(mean_gpp, 1),
            "mean_annual_npp_gCm2yr": round(mean_npp, 1),
            "mean_annual_nee_gCm2yr": round(mean_nee, 1),
            "mean_annual_et_mmyr": round(mean_et, 1),
            "final_vegc_kgCm2": round(last.get("vegc", 0), 3),
            "final_soilc_kgCm2": round(last.get("soilc", 0), 3),
            "final_totalc_kgCm2": round(last.get("totalc", 0), 3),
            "cue": round(mean_npp / mean_gpp, 3) if mean_gpp > 0 else None,
            "nee_sign": "sink" if mean_nee < 0 else "source",
        }

    result = {
        "status": "success",
        "n_daily_records": len(daily_records),
        "n_annual_records": len(annual_records),
        "n_years_analyzed": len(annual_summaries),
        "summary": summary,
        "warnings": warnings,
        "output_csv": args.output_csv,
    }
    print(json.dumps(result, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
