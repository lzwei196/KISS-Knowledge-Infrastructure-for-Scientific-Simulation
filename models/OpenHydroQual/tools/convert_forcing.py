#!/usr/bin/env python3
"""
convert_forcing.py - Convert meteorological forcing data to OpenHydroQual format.

Reads common climate data formats (CSV with headers) and converts to OHQ-compatible
time series files. Handles unit conversions for temperature, wind speed, solar
radiation, and relative humidity.

CRITICAL: OHQ time is in DAYS. All time columns must be in day units.
CRITICAL: Relative humidity must be 0-1 fraction, NOT 0-100 percentage.
CRITICAL: Solar radiation must be in W/m^2 for Penman ET calculation.
CRITICAL: Wind speed must be in m/s.
CRITICAL: Temperature must be in Celsius.

Usage:
  python convert_forcing.py --input-dir ./data/ --output-dir ./forcing/ \\
    --temp-file Temp.csv --wind-file Wind.csv --solar-file Solar.csv \\
    --humidity-file Humidity.csv

  python convert_forcing.py --input-dir ./data/ --output-dir ./forcing/ \\
    --temp-file Temp.csv --temp-unit kelvin \\
    --wind-file Wind.csv --wind-unit km/h \\
    --solar-file Solar.csv --solar-unit MJ/m2/day \\
    --humidity-file Humidity.csv --rh-unit percent

  python convert_forcing.py --input-dir ./data/ --output-dir ./forcing/ \\
    --precip-file Precip.csv --precip-unit mm/hr \\
    --start-date 2010-01-01 --time-unit date
"""

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timedelta


def validate_inputs(args):
    """Validate input arguments and paths."""
    errors = []
    warnings = []

    if not os.path.isdir(args.input_dir):
        errors.append(f"Input directory not found: {args.input_dir}")

    if not os.path.isdir(args.output_dir):
        try:
            os.makedirs(args.output_dir, exist_ok=True)
        except OSError as e:
            errors.append(f"Cannot create output directory: {e}")

    forcing_files = [
        ("temp_file", "Temperature"),
        ("wind_file", "Wind speed"),
        ("solar_file", "Solar radiation"),
        ("humidity_file", "Relative humidity"),
    ]

    found_any = False
    for attr, label in forcing_files:
        fname = getattr(args, attr, None)
        if fname:
            fpath = os.path.join(args.input_dir, fname)
            if not os.path.isfile(fpath):
                errors.append(f"{label} file not found: {fpath}")
            else:
                found_any = True

    if not found_any:
        errors.append("No forcing files specified. Provide at least one of: "
                       "--temp-file, --wind-file, --solar-file, --humidity-file")

    if args.rh_unit == "percent":
        warnings.append("Relative humidity will be converted from % (0-100) to fraction (0-1)")

    if args.temp_unit == "kelvin":
        warnings.append("Temperature will be converted from Kelvin to Celsius")

    if args.wind_unit == "km/h":
        warnings.append("Wind speed will be converted from km/h to m/s")

    if args.solar_unit == "MJ/m2/day":
        warnings.append("Solar radiation will be converted from MJ/m^2/day to W/m^2")

    if errors:
        print(json.dumps({"status": "error", "errors": errors, "warnings": warnings}))
        sys.exit(1)

    if warnings:
        for w in warnings:
            print(f"WARNING: {w}", file=sys.stderr)

    return True


def read_csv_timeseries(filepath):
    """Read a CSV time series file. Returns list of (time, value) tuples.

    Handles multiple formats:
    - Two columns: time, value
    - With headers or without
    - Date strings or numeric time
    """
    rows = []
    with open(filepath, "r") as f:
        reader = csv.reader(f)
        for i, row in enumerate(reader):
            if len(row) < 2:
                continue
            try:
                t = float(row[0])
                v = float(row[1])
                rows.append((t, v))
            except ValueError:
                if i == 0:
                    continue  # skip header
                # Try date parsing
                try:
                    dt = datetime.strptime(row[0].strip(), "%Y-%m-%d")
                    v = float(row[1])
                    rows.append((None, v, dt))
                except (ValueError, IndexError):
                    continue
    return rows


def convert_time_to_days(rows, start_date=None, time_unit="days"):
    """Convert time column to days from simulation start.

    Args:
        rows: list of tuples from read_csv_timeseries
        start_date: reference date for date-based time series
        time_unit: 'days', 'hours', 'seconds', 'date'
    """
    result = []

    if time_unit == "date" or (rows and len(rows[0]) == 3):
        # Date-based time series
        if start_date is None:
            ref = rows[0][2] if len(rows[0]) == 3 else datetime(2000, 1, 1)
        else:
            ref = datetime.strptime(start_date, "%Y-%m-%d")

        for row in rows:
            if len(row) == 3:
                dt = row[2]
                val = row[1]
            else:
                continue
            days = (dt - ref).total_seconds() / 86400.0
            result.append((days, val))
    else:
        for row in rows:
            t, v = row[0], row[1]
            if time_unit == "hours":
                t = t / 24.0
            elif time_unit == "seconds":
                t = t / 86400.0
            result.append((t, v))

    return result


def convert_temperature(value, from_unit):
    """Convert temperature to Celsius."""
    if from_unit == "kelvin":
        return value - 273.15
    elif from_unit == "fahrenheit":
        return (value - 32.0) * 5.0 / 9.0
    return value  # already celsius


def convert_wind(value, from_unit):
    """Convert wind speed to m/s."""
    if from_unit == "km/h":
        return value / 3.6
    elif from_unit == "mph":
        return value * 0.44704
    elif from_unit == "knots":
        return value * 0.51444
    return value  # already m/s


def convert_solar(value, from_unit):
    """Convert solar radiation to W/m^2."""
    if from_unit == "MJ/m2/day":
        return value * 1e6 / 86400.0  # MJ/day -> W
    elif from_unit == "cal/cm2/day":
        return value * 4.184e4 / 86400.0
    elif from_unit == "kW/m2":
        return value * 1000.0
    return value  # already W/m^2


def convert_humidity(value, from_unit):
    """Convert relative humidity to fraction (0-1)."""
    if from_unit == "percent":
        return value / 100.0
    return value  # already fraction


def convert_precip(value, from_unit):
    """Convert precipitation to m/day."""
    if from_unit == "mm/hr":
        return value * 24.0 / 1000.0
    elif from_unit == "mm/day":
        return value / 1000.0
    elif from_unit == "in/hr":
        return value * 24.0 * 0.0254
    return value  # already m/day


def write_ohq_csv(filepath, data, header=None):
    """Write time series in OHQ-compatible CSV format.

    Format: time,value (no header by default, consistent with OHQ examples)
    """
    with open(filepath, "w", newline="") as f:
        writer = csv.writer(f)
        if header:
            writer.writerow(header)
        for t, v in data:
            writer.writerow([f"{t:.6f}", f"{v:.6f}"])


def process(args):
    """Process all forcing files and write converted output."""
    results = {"status": "success", "files_written": [], "warnings": []}

    conversions = [
        ("temp_file", "Temperature", args.temp_unit, convert_temperature),
        ("wind_file", "Wind", args.wind_unit, convert_wind),
        ("solar_file", "Solar", args.solar_unit, convert_solar),
        ("humidity_file", "Humidity", args.rh_unit, convert_humidity),
    ]

    if hasattr(args, "precip_file") and args.precip_file:
        conversions.append(
            ("precip_file", "Precipitation", args.precip_unit, convert_precip)
        )

    for attr, label, unit, conv_func in conversions:
        fname = getattr(args, attr, None)
        if not fname:
            continue

        fpath = os.path.join(args.input_dir, fname)
        if not os.path.isfile(fpath):
            continue

        rows = read_csv_timeseries(fpath)
        if not rows:
            results["warnings"].append(f"No data read from {fpath}")
            continue

        # Convert time to days
        data = convert_time_to_days(rows, args.start_date, args.time_unit)

        # Apply unit conversion
        converted = []
        for t, v in data:
            converted.append((t, conv_func(v, unit)))

        # Validate converted values
        values = [v for _, v in converted]
        if label == "Temperature":
            if min(values) < -60 or max(values) > 60:
                results["warnings"].append(
                    f"Temperature range [{min(values):.1f}, {max(values):.1f}] C "
                    f"seems unreasonable. Check input units.")
        elif label == "Humidity":
            if max(values) > 1.0:
                results["warnings"].append(
                    f"Humidity max={max(values):.2f} > 1.0. "
                    f"Did you forget --rh-unit percent?")
        elif label == "Solar":
            if max(values) > 1500:
                results["warnings"].append(
                    f"Solar max={max(values):.1f} W/m^2 seems high. "
                    f"Check input units.")
        elif label == "Wind":
            if max(values) > 50:
                results["warnings"].append(
                    f"Wind max={max(values):.1f} m/s seems high. "
                    f"Check input units (should be m/s).")

        outname = f"{label}_ohq.csv"
        outpath = os.path.join(args.output_dir, outname)
        write_ohq_csv(outpath, converted)
        results["files_written"].append(outpath)
        results[f"{label.lower()}_stats"] = {
            "n_records": len(converted),
            "min": min(values),
            "max": max(values),
            "mean": sum(values) / len(values),
        }

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Convert meteorological forcing data to OpenHydroQual format"
    )
    parser.add_argument("--input-dir", required=True, help="Input data directory")
    parser.add_argument("--output-dir", required=True, help="Output directory for converted files")
    parser.add_argument("--temp-file", default=None, help="Temperature CSV filename")
    parser.add_argument("--temp-unit", default="celsius",
                        choices=["celsius", "kelvin", "fahrenheit"],
                        help="Input temperature unit (default: celsius)")
    parser.add_argument("--wind-file", default=None, help="Wind speed CSV filename")
    parser.add_argument("--wind-unit", default="m/s",
                        choices=["m/s", "km/h", "mph", "knots"],
                        help="Input wind speed unit (default: m/s)")
    parser.add_argument("--solar-file", default=None, help="Solar radiation CSV filename")
    parser.add_argument("--solar-unit", default="W/m2",
                        choices=["W/m2", "MJ/m2/day", "cal/cm2/day", "kW/m2"],
                        help="Input solar radiation unit (default: W/m^2)")
    parser.add_argument("--humidity-file", default=None, help="Relative humidity CSV filename")
    parser.add_argument("--rh-unit", default="fraction",
                        choices=["fraction", "percent"],
                        help="Input RH unit (default: fraction 0-1)")
    parser.add_argument("--precip-file", default=None, help="Precipitation CSV filename")
    parser.add_argument("--precip-unit", default="m/day",
                        choices=["m/day", "mm/day", "mm/hr", "in/hr"],
                        help="Input precipitation unit (default: m/day)")
    parser.add_argument("--start-date", default=None,
                        help="Reference start date for date-based time (YYYY-MM-DD)")
    parser.add_argument("--time-unit", default="days",
                        choices=["days", "hours", "seconds", "date"],
                        help="Input time column unit (default: days)")

    args = parser.parse_args()
    validate_inputs(args)
    result = process(args)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
