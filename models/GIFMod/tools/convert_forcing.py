#!/usr/bin/env python3
"""
convert_forcing.py - Convert meteorological forcing data to GIFMod time series format.

GIFMod requires forcing data as CSV time series with:
  - Time in days from simulation start
  - Precipitation in m/day
  - Temperature in Celsius
  - Relative humidity as fraction (0-1)
  - Wind speed in m/s

CRITICAL UNIT CONVERSIONS (see SKILL.md dt_002, dt_008):
  - Precipitation: mm/hr -> m/day (* 0.024), mm/day -> m/day (* 0.001)
  - Temperature: Fahrenheit -> Celsius ((F-32)*5/9)
  - Humidity: percent -> fraction (* 0.01)

Input:  CSV with columns [datetime, precip, temperature, humidity, wind_speed]
Output: GIFMod-format CSV with columns [Time, Precipitation, Temperature, Humidity, WindSpeed]

Usage:
    python convert_forcing.py --input met_data.csv --output gifmod_forcing.csv \\
        --precip-unit mm/hr --temp-unit celsius --start-date 2020-01-01
"""

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timedelta


# ---------- Unit conversion factors ----------

PRECIP_CONVERSIONS = {
    "m/day":  1.0,
    "mm/day": 0.001,
    "mm/hr":  0.024,
    "mm/h":   0.024,
    "in/day": 0.0254,
    "in/hr":  0.6096,
    "cm/day": 0.01,
    "cm/hr":  0.24,
}

TEMP_CONVERSIONS = {
    "celsius": lambda t: t,
    "c":       lambda t: t,
    "fahrenheit": lambda t: (t - 32.0) * 5.0 / 9.0,
    "f":          lambda t: (t - 32.0) * 5.0 / 9.0,
    "kelvin":     lambda t: t - 273.15,
    "k":          lambda t: t - 273.15,
}

HUMIDITY_CONVERSIONS = {
    "fraction": 1.0,
    "decimal":  1.0,
    "percent":  0.01,
    "%":        0.01,
}

WIND_CONVERSIONS = {
    "m/s":   1.0,
    "km/hr": 1.0 / 3.6,
    "km/h":  1.0 / 3.6,
    "mph":   0.44704,
    "knots": 0.51444,
}


def validate_inputs(args):
    """Validate input file exists and unit specifications are recognized."""
    errors = []

    if not os.path.isfile(args.input):
        errors.append(f"Input file not found: {args.input}")

    if args.precip_unit.lower() not in PRECIP_CONVERSIONS:
        errors.append(
            f"Unknown precip unit '{args.precip_unit}'. "
            f"Valid: {list(PRECIP_CONVERSIONS.keys())}"
        )

    if args.temp_unit.lower() not in TEMP_CONVERSIONS:
        errors.append(
            f"Unknown temp unit '{args.temp_unit}'. "
            f"Valid: {list(TEMP_CONVERSIONS.keys())}"
        )

    if args.humidity_unit.lower() not in HUMIDITY_CONVERSIONS:
        errors.append(
            f"Unknown humidity unit '{args.humidity_unit}'. "
            f"Valid: {list(HUMIDITY_CONVERSIONS.keys())}"
        )

    if args.wind_unit.lower() not in WIND_CONVERSIONS:
        errors.append(
            f"Unknown wind unit '{args.wind_unit}'. "
            f"Valid: {list(WIND_CONVERSIONS.keys())}"
        )

    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)

    return {"status": "ok"}


def process(args):
    """Read input CSV, apply unit conversions, write GIFMod-format output."""
    precip_factor = PRECIP_CONVERSIONS[args.precip_unit.lower()]
    temp_func = TEMP_CONVERSIONS[args.temp_unit.lower()]
    hum_factor = HUMIDITY_CONVERSIONS[args.humidity_unit.lower()]
    wind_factor = WIND_CONVERSIONS[args.wind_unit.lower()]

    start_date = datetime.strptime(args.start_date, "%Y-%m-%d")

    rows_in = 0
    rows_out = 0
    warnings = []
    output_rows = []

    with open(args.input, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows_in += 1

            # Parse datetime
            dt_str = row.get("datetime") or row.get("date") or row.get("time")
            if dt_str is None:
                warnings.append(f"Row {rows_in}: no datetime column found")
                continue

            try:
                dt = datetime.strptime(dt_str.strip(), "%Y-%m-%d %H:%M:%S")
            except ValueError:
                try:
                    dt = datetime.strptime(dt_str.strip(), "%Y-%m-%d")
                except ValueError:
                    warnings.append(f"Row {rows_in}: cannot parse datetime '{dt_str}'")
                    continue

            # Time in days from start
            time_days = (dt - start_date).total_seconds() / 86400.0

            # Convert precipitation
            precip_raw = float(row.get("precip", row.get("precipitation", 0.0)))
            precip_m_day = precip_raw * precip_factor

            # Convert temperature
            temp_raw = float(row.get("temperature", row.get("temp", 20.0)))
            temp_c = temp_func(temp_raw)

            # Convert humidity
            hum_raw = float(row.get("humidity", row.get("rh", 0.5)))
            hum_frac = hum_raw * hum_factor

            # Convert wind speed
            wind_raw = float(row.get("wind_speed", row.get("wind", 2.0)))
            wind_ms = wind_raw * wind_factor

            # Range checks (warnings, not errors)
            if precip_m_day < 0:
                warnings.append(f"Row {rows_in}: negative precipitation {precip_m_day}")
            if precip_m_day > 1.0:
                warnings.append(
                    f"Row {rows_in}: precip {precip_m_day:.4f} m/day > 1.0 — "
                    f"possible unit error (dt_002)"
                )
            if temp_c < -60 or temp_c > 60:
                warnings.append(f"Row {rows_in}: temperature {temp_c:.1f}C out of range")
            if hum_frac < 0 or hum_frac > 1.0:
                warnings.append(
                    f"Row {rows_in}: humidity {hum_frac:.3f} outside [0,1] — "
                    f"check unit (dt_012 analog)"
                )

            output_rows.append({
                "Time": f"{time_days:.6f}",
                "Precipitation": f"{precip_m_day:.8f}",
                "Temperature": f"{temp_c:.2f}",
                "Humidity": f"{hum_frac:.4f}",
                "WindSpeed": f"{wind_ms:.2f}",
            })
            rows_out += 1

    # Write output
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["Time", "Precipitation", "Temperature", "Humidity", "WindSpeed"]
        )
        writer.writeheader()
        writer.writerows(output_rows)

    return {
        "status": "success",
        "rows_in": rows_in,
        "rows_out": rows_out,
        "warnings": warnings[:20],
        "output_file": args.output,
        "conversions_applied": {
            "precip": f"{args.precip_unit} -> m/day (x{precip_factor})",
            "temp": f"{args.temp_unit} -> Celsius",
            "humidity": f"{args.humidity_unit} -> fraction (x{hum_factor})",
            "wind": f"{args.wind_unit} -> m/s (x{wind_factor})",
        },
    }


def validate_outputs(result):
    """Verify output file was created and has reasonable content."""
    errors = []

    if result["rows_out"] == 0:
        errors.append("No output rows produced — check input format")

    if not os.path.isfile(result["output_file"]):
        errors.append(f"Output file not created: {result['output_file']}")

    if errors:
        result["status"] = "error"
        result["errors"] = errors
        print(json.dumps(result, indent=2))
        sys.exit(1)

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Convert meteorological forcing to GIFMod format"
    )
    parser.add_argument("--input", required=True, help="Input CSV file path")
    parser.add_argument("--output", required=True, help="Output GIFMod CSV file path")
    parser.add_argument("--precip-unit", default="mm/hr",
                        help="Precipitation unit in input (default: mm/hr)")
    parser.add_argument("--temp-unit", default="celsius",
                        help="Temperature unit in input (default: celsius)")
    parser.add_argument("--humidity-unit", default="fraction",
                        help="Humidity unit in input (default: fraction)")
    parser.add_argument("--wind-unit", default="m/s",
                        help="Wind speed unit in input (default: m/s)")
    parser.add_argument("--start-date", required=True,
                        help="Simulation start date (YYYY-MM-DD)")

    args = parser.parse_args()

    validate_inputs(args)
    result = process(args)
    result = validate_outputs(result)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
