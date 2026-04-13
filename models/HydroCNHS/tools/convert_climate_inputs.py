#!/usr/bin/env python3
"""
convert_climate_inputs.py — Convert global climate data to HydroCNHS input format.

HydroCNHS requires daily climate inputs as Python dictionaries:
  - temp: {outlet_name: [daily_values]} in degrees Celsius (°C)
  - prec: {outlet_name: [daily_values]} in centimeters per day (cm/day)
  - pet:  {outlet_name: [daily_values]} in centimeters per day (cm/day) [optional]

CRITICAL UNIT TRAPS:
  - ERA5 precipitation is in m/day → multiply by 100 to get cm/day
  - CMIP precipitation is in kg/m²/s → multiply by 86400/10 to get cm/day
  - ERA5 temperature is in K → subtract 273.15 to get °C
  - Common station data is in mm/day → divide by 10 to get cm/day
  - If discharge is 10× too high/low, precipitation units are almost certainly wrong

Usage:
    python convert_climate_inputs.py \\
        --input-dir /path/to/climate/csv/ \\
        --outlets "WSLO,DLLO,TRGC" \\
        --start-date "1981/1/1" \\
        --end-date "2013/12/31" \\
        --temp-unit C \\
        --prec-unit mm \\
        --output /path/to/output.json
"""

import argparse
import json
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd


def validate_inputs(args):
    """Validate all inputs before processing. Returns list of errors."""
    errors = []

    if not os.path.isdir(args.input_dir):
        errors.append(f"Input directory does not exist: {args.input_dir}")

    if not args.outlets:
        errors.append("No outlets specified. Use --outlets 'outlet1,outlet2,...'")

    valid_temp_units = ["C", "K", "F"]
    if args.temp_unit not in valid_temp_units:
        errors.append(f"Invalid temp unit '{args.temp_unit}'. Must be one of {valid_temp_units}")

    valid_prec_units = ["cm", "mm", "m", "kg/m2/s"]
    if args.prec_unit not in valid_prec_units:
        errors.append(f"Invalid prec unit '{args.prec_unit}'. Must be one of {valid_prec_units}")

    try:
        datetime.strptime(args.start_date, "%Y/%m/%d")
    except ValueError:
        errors.append(f"Invalid start date format '{args.start_date}'. Use YYYY/M/D")

    try:
        datetime.strptime(args.end_date, "%Y/%m/%d")
    except ValueError:
        errors.append(f"Invalid end date format '{args.end_date}'. Use YYYY/M/D")

    return errors


def convert_temperature(values, from_unit):
    """Convert temperature to degrees Celsius."""
    if from_unit == "C":
        return values
    elif from_unit == "K":
        return values - 273.15
    elif from_unit == "F":
        return (values - 32) * 5.0 / 9.0
    else:
        raise ValueError(f"Unknown temperature unit: {from_unit}")


def convert_precipitation(values, from_unit):
    """Convert precipitation to cm/day.

    CRITICAL: HydroCNHS uses cm/day internally. Getting this wrong causes
    discharge to be off by exactly 10× (mm→cm) or 100× (m→cm).
    """
    if from_unit == "cm":
        return values
    elif from_unit == "mm":
        return values / 10.0
    elif from_unit == "m":
        return values * 100.0
    elif from_unit == "kg/m2/s":
        # kg/m²/s = mm/s → mm/day = ×86400 → cm/day = ÷10
        return values * 86400.0 / 10.0
    else:
        raise ValueError(f"Unknown precipitation unit: {from_unit}")


def validate_output_ranges(temp_dict, prec_dict, log):
    """Check that converted values are physically plausible."""
    warnings = []

    for outlet, values in temp_dict.items():
        arr = np.array(values)
        if np.any(arr < -60):
            warnings.append(f"[WARN] {outlet}: temp min={arr.min():.1f}°C — likely K→C conversion missing")
        if np.any(arr > 60):
            warnings.append(f"[WARN] {outlet}: temp max={arr.max():.1f}°C — likely still in Kelvin or Fahrenheit")
        if np.all(arr > 200):
            warnings.append(f"[CRITICAL] {outlet}: all temp > 200°C — data is almost certainly in Kelvin")

    for outlet, values in prec_dict.items():
        arr = np.array(values)
        if np.any(arr < 0):
            warnings.append(f"[WARN] {outlet}: negative precipitation detected — check data")
        if np.any(arr > 50):
            warnings.append(f"[WARN] {outlet}: prec max={arr.max():.1f} cm/day — verify units (50 cm = 500 mm)")
        mean_prec = arr.mean()
        if mean_prec > 5:
            warnings.append(f"[WARN] {outlet}: mean prec={mean_prec:.2f} cm/day — likely mm/day not converted")
        if mean_prec < 0.001 and mean_prec > 0:
            warnings.append(f"[WARN] {outlet}: mean prec={mean_prec:.4f} cm/day — likely m/day not converted")

    log.extend(warnings)
    return len([w for w in warnings if "CRITICAL" in w]) == 0


def process(args):
    """Main processing: read CSV files, convert units, output JSON."""
    log = []
    outlets = [o.strip() for o in args.outlets.split(",")]

    start = datetime.strptime(args.start_date, "%Y/%m/%d")
    end = datetime.strptime(args.end_date, "%Y/%m/%d")
    n_days = (end - start).days + 1
    log.append(f"Date range: {args.start_date} to {args.end_date} ({n_days} days)")

    temp_dict = {}
    prec_dict = {}
    pet_dict = {}

    for outlet in outlets:
        # Look for CSV files: {outlet}_temp.csv, {outlet}_prec.csv
        temp_file = os.path.join(args.input_dir, f"{outlet}_temp.csv")
        prec_file = os.path.join(args.input_dir, f"{outlet}_prec.csv")
        combined_file = os.path.join(args.input_dir, f"{outlet}.csv")

        if os.path.exists(combined_file):
            df = pd.read_csv(combined_file, parse_dates=["date"])
            temp_raw = df["temp"].values
            prec_raw = df["prec"].values
            log.append(f"{outlet}: loaded combined CSV ({len(df)} rows)")
        elif os.path.exists(temp_file) and os.path.exists(prec_file):
            temp_raw = pd.read_csv(temp_file, header=None).iloc[:, -1].values
            prec_raw = pd.read_csv(prec_file, header=None).iloc[:, -1].values
            log.append(f"{outlet}: loaded separate temp/prec CSVs")
        else:
            return {
                "status": "error",
                "errors": [f"No climate data found for outlet {outlet}. "
                           f"Expected {combined_file} or {temp_file}/{prec_file}"],
                "log": log
            }

        # Validate length
        if len(temp_raw) != n_days:
            log.append(f"[WARN] {outlet}: expected {n_days} days, got {len(temp_raw)} temp values")
        if len(prec_raw) != n_days:
            log.append(f"[WARN] {outlet}: expected {n_days} days, got {len(prec_raw)} prec values")

        # Convert units
        temp_dict[outlet] = convert_temperature(temp_raw, args.temp_unit).tolist()
        prec_dict[outlet] = convert_precipitation(prec_raw, args.prec_unit).tolist()

        # PET is optional
        pet_file = os.path.join(args.input_dir, f"{outlet}_pet.csv")
        if os.path.exists(pet_file):
            pet_raw = pd.read_csv(pet_file, header=None).iloc[:, -1].values
            if args.prec_unit == "mm":
                pet_dict[outlet] = (pet_raw / 10.0).tolist()
            else:
                pet_dict[outlet] = pet_raw.tolist()
            log.append(f"{outlet}: PET data loaded and converted")

    # Validate output ranges
    validate_output_ranges(temp_dict, prec_dict, log)

    result = {
        "status": "success",
        "output": {
            "temp": temp_dict,
            "prec": prec_dict,
            "n_outlets": len(outlets),
            "n_days": n_days,
            "start_date": args.start_date,
            "end_date": args.end_date,
        },
        "log": log
    }
    if pet_dict:
        result["output"]["pet"] = pet_dict

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Convert climate data to HydroCNHS input format"
    )
    parser.add_argument("--input-dir", required=True, help="Directory with climate CSV files")
    parser.add_argument("--outlets", required=True, help="Comma-separated outlet names")
    parser.add_argument("--start-date", required=True, help="Start date YYYY/M/D")
    parser.add_argument("--end-date", required=True, help="End date YYYY/M/D")
    parser.add_argument("--temp-unit", default="C", help="Input temp unit: C, K, F")
    parser.add_argument("--prec-unit", default="mm", help="Input prec unit: cm, mm, m, kg/m2/s")
    parser.add_argument("--output", default=None, help="Output JSON file path")

    args = parser.parse_args()

    # Step 1: Validate inputs
    errors = validate_inputs(args)
    if errors:
        result = {"status": "error", "errors": errors}
        print(json.dumps(result, indent=2))
        sys.exit(1)

    # Step 2: Process
    result = process(args)

    # Step 3: Output
    if args.output:
        with open(args.output, "w") as f:
            json.dump(result, f, indent=2)
        print(f"Output written to {args.output}")
    else:
        print(json.dumps(result, indent=2))

    if result["status"] == "error":
        sys.exit(1)


if __name__ == "__main__":
    main()
