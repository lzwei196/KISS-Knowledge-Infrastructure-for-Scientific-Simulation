#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
Tool ID:      parse_npc_output
Stage:        s9_water_quality
Description:  Parse HYPE nutrient output (N/P loads and concentrations) from
              time series output files. Computes annual/monthly TN, TP loads
              and yields per unit area.

HYPE nutrient output variables:
    reIN   - Inorganic N load at outlet (kg/timestep)
    reON   - Organic N load at outlet (kg/timestep)
    reTN   - Total N load at outlet (kg/timestep)
    reSP   - Soluble P load at outlet (kg/timestep)
    rePP   - Particulate P load at outlet (kg/timestep)
    reTP   - Total P load at outlet (kg/timestep)
    ccIN   - Inorganic N concentration (ug/L)
    ccON   - Organic N concentration (ug/L)
    ccSP   - Soluble P concentration (ug/L)
    ccPP   - Particulate P concentration (ug/L)

Usage:
    python parse_npc_output.py \
        --result_dir <path> \
        --subbasin_id <int> \
        --basin_area_km2 <float> \
        --output_csv <path>

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import argparse
import sys
import os
import json
import csv
import logging
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def parse_args():
    parser = argparse.ArgumentParser(description="Parse HYPE nutrient output")
    parser.add_argument("--result_dir", required=True,
                        help="Path to HYPE result directory")
    parser.add_argument("--subbasin_id", type=int, required=True,
                        help="Subbasin ID for outlet")
    parser.add_argument("--basin_area_km2", type=float, required=True,
                        help="Basin area in km2")
    parser.add_argument("--output_csv", required=True,
                        help="Output CSV path")
    return parser.parse_args()


def read_hype_timeseries(result_dir, var_name, subbasin_id):
    """Read a HYPE time series file (timeCOUT.txt format).

    HYPE time output format:
    - Filename: time{VAR}.txt (e.g., timereTN.txt)
    - Header: DATE  subid1  subid2  ...
    - Data: YYYY-MM-DD  value1  value2  ...
    """
    result_path = Path(result_dir)
    fname = f"time{var_name}.txt"
    fpath = result_path / fname

    if not fpath.exists():
        logger.warning(f"File not found: {fpath}")
        return None

    records = []
    with open(fpath) as f:
        lines = f.readlines()

    if len(lines) < 3:
        return None

    # Find the header line with subbasin IDs (skip !! comment lines)
    header_idx = 0
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped and not stripped.startswith('!!'):
            header_idx = idx
            break

    # Parse header to find subbasin column
    header = lines[header_idx].strip().split()
    sub_col = None
    for i, h in enumerate(header):
        try:
            if int(h) == subbasin_id:
                sub_col = i
                break
        except ValueError:
            continue

    if sub_col is None:
        logger.warning(f"Subbasin {subbasin_id} not found in {fname}")
        return None

    for line in lines[header_idx + 1:]:
        parts = line.strip().split()
        if len(parts) <= sub_col:
            continue
        try:
            date = datetime.strptime(parts[0], "%Y-%m-%d")
            value = float(parts[sub_col])
            records.append({"date": date, "value": value})
        except (ValueError, IndexError):
            continue

    logger.info(f"Read {len(records)} records from {fname}")
    return records


def process(args):
    result_dir = args.result_dir
    subid = args.subbasin_id
    basin_area_ha = args.basin_area_km2 * 100.0

    # Read available nutrient variables
    # Use c1* variables (computed main flow concentrations)
    # NOT re* variables (which require observed nutrient data)
    nutrient_vars = {
        "C1TN": "Total N concentration (ug/L)",
        "C1IN": "Inorganic N concentration (ug/L)",
        "C1ON": "Organic N concentration (ug/L)",
        "C1TP": "Total P concentration (ug/L)",
        "C1SP": "Soluble P concentration (ug/L)",
        "C1PP": "Particulate P concentration (ug/L)",
    }

    all_data = {}
    for var in nutrient_vars:
        data = read_hype_timeseries(result_dir, var, subid)
        if data:
            all_data[var] = {r["date"]: r["value"] for r in data}

    if not all_data:
        logger.error("No nutrient output files found. Check that NPC is enabled in info.txt.")
        sys.exit(2)

    # Get date range from first available variable
    first_var = next(iter(all_data.values()))
    dates = sorted(first_var.keys())
    logger.info(f"Date range: {dates[0].strftime('%Y-%m-%d')} to {dates[-1].strftime('%Y-%m-%d')}")

    # Build daily records
    daily_records = []
    annual_loads = defaultdict(lambda: defaultdict(float))

    for date in dates:
        record = {
            "date": date.strftime("%Y-%m-%d"),
            "year": date.year,
            "month": date.month,
        }
        for var in all_data:
            record[var] = all_data[var].get(date, 0.0)
            if var.startswith("re"):  # load variables
                annual_loads[date.year][var] += record[var]

        daily_records.append(record)

    # Write daily CSV
    output_csv = Path(args.output_csv)
    output_csv.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = ["date", "year", "month"] + sorted(all_data.keys())
    with open(output_csv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(daily_records)

    # Annual summary with yields
    annual_summary = []
    for yr in sorted(annual_loads.keys()):
        loads = annual_loads[yr]
        summary = {"year": yr}

        for var in ["reTN", "reIN", "reON", "reTP", "reSP", "rePP"]:
            if var in loads:
                summary[f"{var}_kg_yr"] = round(loads[var], 1)
                summary[f"{var}_kg_ha_yr"] = round(loads[var] / basin_area_ha, 3)

        annual_summary.append(summary)
        tn = summary.get("reTN_kg_ha_yr", 0)
        tp = summary.get("reTP_kg_ha_yr", 0)
        logger.info(f"  {yr}: TN={tn:.2f} kgN/ha/yr, TP={tp:.3f} kgP/ha/yr")

    # Write annual CSV
    annual_csv = output_csv.parent / (output_csv.stem + "_annual.csv")
    if annual_summary:
        with open(annual_csv, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=annual_summary[0].keys())
            writer.writeheader()
            writer.writerows(annual_summary)

    n_years = len(annual_summary)
    avg_tn = sum(a.get("reTN_kg_ha_yr", 0) for a in annual_summary) / n_years if n_years else 0
    avg_tp = sum(a.get("reTP_kg_ha_yr", 0) for a in annual_summary) / n_years if n_years else 0

    return {
        "status": "success",
        "output_csv": str(output_csv),
        "annual_csv": str(annual_csv),
        "n_daily_records": len(daily_records),
        "n_years": n_years,
        "variables_found": list(all_data.keys()),
        "basin_area_km2": args.basin_area_km2,
        "average_annual_yield": {
            "TN_kg_ha_yr": round(avg_tn, 3),
            "TP_kg_ha_yr": round(avg_tp, 4),
        },
        "annual_summary": annual_summary,
        "reference_ranges": {
            "TN_kg_ha_yr": "5-20 (agricultural), 1-5 (forested)",
            "TP_kg_ha_yr": "0.3-3 (agricultural), 0.05-0.5 (forested)",
        },
    }


def main():
    args = parse_args()

    if not Path(args.result_dir).exists():
        logger.error(f"Result directory not found: {args.result_dir}")
        sys.exit(1)
    if args.basin_area_km2 <= 0:
        logger.error(f"Invalid basin area: {args.basin_area_km2}")
        sys.exit(1)

    try:
        result = process(args)
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        sys.exit(2)

    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
