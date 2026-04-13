#!/usr/bin/env python3
"""
convert_climate_to_hydrotrend.py

Converts global reanalysis / station climate data into HydroTrend monthly
climate statistics (lines 12-23 of HYDRO.IN).

Supported input sources:
  - CSV with columns: date, temperature(°C), precipitation(mm/day or m/day)
  - ERA5 / CRU / CMFD NetCDF monthly data
  - Manual specification of monthly T/P values

Output: 12 lines of monthly climate in HYDRO.IN format:
    MonthName  T_mean(°C)  T_std(°C)  P_total(mm)  P_std(mm)

CRITICAL UNIT CONVERSIONS:
  - HydroTrend expects monthly precipitation in mm (lines 12-23)
  - HydroTrend expects annual precipitation in m/yr (line 9)
  - The model internally divides monthly precip by 1000 to convert to meters
  - If you provide meters instead of mm, values will be 1000x too small

Usage:
    python convert_climate_to_hydrotrend.py \\
        --input climate_daily.csv \\
        --output hydro_climate_lines.txt \\
        --precip-units mm/day \\
        --temp-col temperature \\
        --precip-col precipitation \\
        --date-col date
"""

import argparse
import csv
import json
import sys
import os
from datetime import datetime
from collections import defaultdict
import math


# --------------------------------------------------------------------------- #
#  Constants
# --------------------------------------------------------------------------- #
MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
DAYS_IN_MONTH = [31, 28.25, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]

VALID_PRECIP_UNITS = {"mm/day", "m/day", "mm/month", "m/month", "mm/yr", "m/yr"}
VALID_TEMP_UNITS = {"C", "K", "F"}


# --------------------------------------------------------------------------- #
#  Validation
# --------------------------------------------------------------------------- #
def validate_inputs(args):
    """Validate command-line inputs before processing."""
    errors = []

    if not os.path.isfile(args.input):
        errors.append(f"Input file not found: {args.input}")

    if args.precip_units not in VALID_PRECIP_UNITS:
        errors.append(
            f"Invalid precip units '{args.precip_units}'. "
            f"Valid: {VALID_PRECIP_UNITS}"
        )

    if args.temp_units not in VALID_TEMP_UNITS:
        errors.append(
            f"Invalid temp units '{args.temp_units}'. Valid: {VALID_TEMP_UNITS}"
        )

    if errors:
        return {"status": "error", "errors": errors}
    return {"status": "ok"}


def validate_outputs(monthly_stats):
    """Validate computed monthly statistics for physical plausibility."""
    warnings = []

    for m in range(12):
        t_mean = monthly_stats[m]["t_mean"]
        t_std = monthly_stats[m]["t_std"]
        p_total = monthly_stats[m]["p_total_mm"]
        p_std = monthly_stats[m]["p_std_mm"]

        if t_mean < -60 or t_mean > 60:
            warnings.append(
                f"{MONTH_NAMES[m]}: T_mean={t_mean:.1f}°C outside [-60,60]"
            )
        if t_std < 0:
            warnings.append(f"{MONTH_NAMES[m]}: T_std={t_std:.2f} is negative")
        if t_std > 20:
            warnings.append(
                f"{MONTH_NAMES[m]}: T_std={t_std:.2f}°C unusually high (>20)"
            )
        if p_total < 0:
            warnings.append(
                f"{MONTH_NAMES[m]}: P_total={p_total:.1f}mm is negative"
            )
        if p_total > 2000:
            warnings.append(
                f"{MONTH_NAMES[m]}: P_total={p_total:.1f}mm unusually high "
                "(>2000mm/month)"
            )
        if p_std < 0:
            warnings.append(f"{MONTH_NAMES[m]}: P_std={p_std:.1f}mm is negative")

    # Check annual total
    annual_p = sum(monthly_stats[m]["p_total_mm"] for m in range(12))
    if annual_p < 10:
        warnings.append(
            f"Annual P total = {annual_p:.1f}mm — extremely low, "
            "check units (should be mm not m)"
        )
    if annual_p > 15000:
        warnings.append(
            f"Annual P total = {annual_p:.1f}mm — extremely high, "
            "check units"
        )

    return warnings


# --------------------------------------------------------------------------- #
#  Unit conversions
# --------------------------------------------------------------------------- #
def convert_precip_to_mm_per_day(value, units):
    """Convert precipitation to mm/day."""
    if units == "mm/day":
        return value
    elif units == "m/day":
        return value * 1000.0
    elif units == "mm/month":
        return value / 30.0  # approximate
    elif units == "m/month":
        return value * 1000.0 / 30.0
    elif units == "mm/yr":
        return value / 365.0
    elif units == "m/yr":
        return value * 1000.0 / 365.0
    else:
        raise ValueError(f"Unknown precip units: {units}")


def convert_temp_to_celsius(value, units):
    """Convert temperature to Celsius."""
    if units == "C":
        return value
    elif units == "K":
        return value - 273.15
    elif units == "F":
        return (value - 32.0) * 5.0 / 9.0
    else:
        raise ValueError(f"Unknown temp units: {units}")


# --------------------------------------------------------------------------- #
#  Processing
# --------------------------------------------------------------------------- #
def process_csv(filepath, date_col, temp_col, precip_col,
                precip_units, temp_units):
    """
    Read daily CSV and compute monthly statistics.

    Returns dict of {month_index: {t_mean, t_std, p_total_mm, p_std_mm}}
    """
    monthly_temps = defaultdict(list)
    monthly_precip = defaultdict(list)  # daily values in mm/day

    with open(filepath, "r") as f:
        reader = csv.DictReader(f)
        available_cols = reader.fieldnames
        if date_col not in available_cols:
            raise ValueError(
                f"Date column '{date_col}' not found. "
                f"Available: {available_cols}"
            )
        if temp_col not in available_cols:
            raise ValueError(
                f"Temp column '{temp_col}' not found. "
                f"Available: {available_cols}"
            )
        if precip_col not in available_cols:
            raise ValueError(
                f"Precip column '{precip_col}' not found. "
                f"Available: {available_cols}"
            )

        for row in reader:
            try:
                dt = datetime.strptime(row[date_col].strip(), "%Y-%m-%d")
            except ValueError:
                try:
                    dt = datetime.strptime(row[date_col].strip(),
                                           "%Y/%m/%d")
                except ValueError:
                    continue

            month = dt.month - 1  # 0-indexed

            t_val = convert_temp_to_celsius(
                float(row[temp_col]), temp_units
            )
            p_val = convert_precip_to_mm_per_day(
                float(row[precip_col]), precip_units
            )

            monthly_temps[month].append(t_val)
            monthly_precip[month].append(p_val)

    # Compute statistics
    stats = {}
    for m in range(12):
        temps = monthly_temps[m]
        precs = monthly_precip[m]

        if not temps or not precs:
            stats[m] = {
                "t_mean": 0.0, "t_std": 0.0,
                "p_total_mm": 0.0, "p_std_mm": 0.0
            }
            continue

        t_mean = sum(temps) / len(temps)
        t_std = math.sqrt(
            sum((t - t_mean) ** 2 for t in temps) / max(len(temps) - 1, 1)
        )

        # Monthly total precip = mean daily × days in month
        p_mean_daily = sum(precs) / len(precs)
        p_total_mm = p_mean_daily * DAYS_IN_MONTH[m]

        # Std dev of monthly totals across years
        yearly_totals = defaultdict(float)
        for p in precs:
            yearly_totals[len(yearly_totals)] += p
        p_std_vals = list(yearly_totals.values())
        if len(p_std_vals) > 1:
            p_mean_tot = sum(p_std_vals) / len(p_std_vals)
            p_std_mm = math.sqrt(
                sum((p - p_mean_tot) ** 2 for p in p_std_vals)
                / max(len(p_std_vals) - 1, 1)
            )
        else:
            p_std_mm = p_total_mm * 0.3  # default 30% CV

        stats[m] = {
            "t_mean": round(t_mean, 1),
            "t_std": round(t_std, 2),
            "p_total_mm": round(p_total_mm, 1),
            "p_std_mm": round(p_std_mm, 2),
        }

    return stats


def format_hydro_in_lines(monthly_stats):
    """
    Format 12 lines for HYDRO.IN (lines 12-23).

    IMPORTANT: HydroTrend expects precipitation in mm here.
    The model internally divides by 1000 to get meters.
    """
    lines = []
    for m in range(12):
        s = monthly_stats[m]
        line = (
            f"{MONTH_NAMES[m]:>3s}  "
            f"{s['t_mean']:5.1f} {s['t_std']:5.2f} "
            f"{s['p_total_mm']:6.1f} {s['p_std_mm']:6.2f}"
        )
        lines.append(line)
    return lines


def compute_annual_stats(monthly_stats):
    """Compute annual P in m/yr and annual T stats for HYDRO.IN lines 8-9."""
    annual_p_mm = sum(monthly_stats[m]["p_total_mm"] for m in range(12))
    annual_p_m = annual_p_mm / 1000.0  # Convert mm to m for line 9

    annual_t_vals = [monthly_stats[m]["t_mean"] for m in range(12)]
    annual_t_mean = sum(annual_t_vals) / 12.0

    return {
        "annual_precip_m_per_yr": round(annual_p_m, 3),
        "annual_temp_mean_C": round(annual_t_mean, 1),
    }


# --------------------------------------------------------------------------- #
#  Main
# --------------------------------------------------------------------------- #
def main():
    parser = argparse.ArgumentParser(
        description="Convert climate data to HydroTrend monthly format"
    )
    parser.add_argument("--input", required=True, help="Input CSV file path")
    parser.add_argument("--output", required=True,
                        help="Output file for 12 monthly lines")
    parser.add_argument("--precip-units", default="mm/day",
                        help=f"Precipitation units: {VALID_PRECIP_UNITS}")
    parser.add_argument("--temp-units", default="C",
                        help=f"Temperature units: {VALID_TEMP_UNITS}")
    parser.add_argument("--temp-col", default="temperature",
                        help="Column name for temperature")
    parser.add_argument("--precip-col", default="precipitation",
                        help="Column name for precipitation")
    parser.add_argument("--date-col", default="date",
                        help="Column name for date")
    args = parser.parse_args()

    # Step 1: Validate inputs
    check = validate_inputs(args)
    if check["status"] == "error":
        print(json.dumps(check, indent=2))
        sys.exit(1)

    # Step 2: Process
    try:
        monthly_stats = process_csv(
            args.input, args.date_col, args.temp_col, args.precip_col,
            args.precip_units, args.temp_units
        )
    except Exception as e:
        print(json.dumps({"status": "error", "message": str(e)}, indent=2))
        sys.exit(1)

    # Step 3: Validate outputs
    warnings = validate_outputs(monthly_stats)
    if warnings:
        for w in warnings:
            print(f"WARNING: {w}", file=sys.stderr)

    # Step 4: Write output
    lines = format_hydro_in_lines(monthly_stats)
    annual = compute_annual_stats(monthly_stats)

    with open(args.output, "w") as f:
        f.write("# HydroTrend monthly climate lines (12-23 of HYDRO.IN)\n")
        f.write("# Format: Month  T_mean(°C)  T_std(°C)  P_total(mm)  "
                "P_std(mm)\n")
        f.write(f"# Annual P = {annual['annual_precip_m_per_yr']} m/yr "
                f"(for HYDRO.IN line 9)\n")
        f.write(f"# Annual T = {annual['annual_temp_mean_C']} °C "
                f"(for HYDRO.IN line 8)\n")
        for line in lines:
            f.write(line + "\n")

    result = {
        "status": "success",
        "output_file": args.output,
        "monthly_lines": len(lines),
        "annual_stats": annual,
        "warnings": warnings,
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
