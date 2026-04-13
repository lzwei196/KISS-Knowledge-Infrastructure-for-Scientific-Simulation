#!/usr/bin/env python3
"""
convert_forcing_data.py — Convert meteorological timeseries to WSIMOD input format.

Converts raw CSV data (precipitation, temperature, evapotranspiration) into the
WSIMOD data_input_dict format: a dictionary keyed by (variable, timestamp) tuples.

CRITICAL UNIT CONVERSIONS:
  - Precipitation: mm/day → m/timestep (multiply by MM_TO_M = 1e-3)
  - ET₀: mm/day → m/timestep (multiply by MM_TO_M = 1e-3)
  - Temperature: must be in °C (used for decay calculations at ref=20°C)
  - Flow: m³/s → ML/d (multiply by M3_S_TO_ML_D = 86.4)

Input CSV format:
  site,date,variable,value
  oxford_land,2009-03-03,temperature,7.5
  oxford_land,2009-03-03,precipitation,2.1
  oxford_land,2009-03-03,et0,1.5

Output: JSON file with data_input_dict and date list, or Python dict via API.

Usage:
    python convert_forcing_data.py --input timeseries.csv \\
        --site oxford_land --output forcing.json \\
        [--precip-unit mm] [--et0-unit mm] [--flow-unit m3_s]
"""

import argparse
import json
import sys
from datetime import datetime

# ---------------------------------------------------------------------------
# Constants (mirroring wsimod.core.constants)
# ---------------------------------------------------------------------------
MM_TO_M = 1e-3
M3_S_TO_ML_D = 86.4
KM2_TO_M2 = 1e6
MG_L_TO_KG_M3 = 1e-3

EXPECTED_VARIABLES = {"precipitation", "temperature", "et0"}
OPTIONAL_VARIABLES = {"flow", "phosphate", "ammonia", "nitrate", "bod", "do"}

UNIT_CONVERSIONS = {
    "precipitation": {"mm": MM_TO_M, "m": 1.0},
    "et0": {"mm": MM_TO_M, "m": 1.0},
    "temperature": {"C": 1.0, "K": None},  # K requires offset, handled separately
    "flow": {"m3_s": M3_S_TO_ML_D, "ML_d": 1.0, "m3_d": 1e-3},
}

# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_inputs(args):
    """Validate input arguments and file accessibility."""
    errors = []
    warnings = []

    # Check input file exists
    try:
        with open(args.input, "r") as f:
            header = f.readline().strip()
    except FileNotFoundError:
        errors.append(f"Input file not found: {args.input}")
        _emit_and_exit(errors, warnings)
        return

    # Validate CSV header
    required_cols = {"date", "variable", "value"}
    header_cols = set(col.strip().lower() for col in header.split(","))
    missing = required_cols - header_cols
    if missing:
        errors.append(f"Missing required columns: {missing}. Header: {header}")

    # Validate unit arguments
    if args.precip_unit not in UNIT_CONVERSIONS["precipitation"]:
        errors.append(
            f"Invalid precipitation unit '{args.precip_unit}'. "
            f"Expected one of: {list(UNIT_CONVERSIONS['precipitation'].keys())}"
        )
    if args.et0_unit not in UNIT_CONVERSIONS["et0"]:
        errors.append(
            f"Invalid ET₀ unit '{args.et0_unit}'. "
            f"Expected one of: {list(UNIT_CONVERSIONS['et0'].keys())}"
        )

    if errors:
        _emit_and_exit(errors, warnings)


def validate_outputs(result, args):
    """Validate converted output for physical reasonableness."""
    warnings = []
    data = result.get("data_input_dict", {})

    # Check precipitation range
    precip_values = [v for (var, _), v in data.items() if var == "precipitation"]
    if precip_values:
        max_precip = max(precip_values)
        min_precip = min(precip_values)
        if max_precip > 0.5:
            warnings.append(
                f"Max precipitation = {max_precip:.4f} m/d — exceeds 0.5 m/d. "
                "Check if mm→m conversion was applied (dt_001)."
            )
        if min_precip < 0:
            warnings.append(f"Negative precipitation detected: {min_precip}")

    # Check temperature range
    temp_values = [v for (var, _), v in data.items() if var == "temperature"]
    if temp_values:
        max_temp = max(temp_values)
        min_temp = min(temp_values)
        if max_temp > 60 or min_temp < -50:
            warnings.append(
                f"Temperature range [{min_temp}, {max_temp}] °C seems unrealistic. "
                "Check units (dt_007)."
            )
        if max_temp > 200:
            warnings.append(
                "Temperature > 200 — likely in Kelvin, not Celsius."
            )

    # Check ET₀ range
    et0_values = [v for (var, _), v in data.items() if var == "et0"]
    if et0_values:
        max_et0 = max(et0_values)
        if max_et0 > 0.02:
            warnings.append(
                f"Max ET₀ = {max_et0:.5f} m/d — exceeds 20 mm/d. "
                "Check if mm→m conversion was applied (dt_015)."
            )

    # Check date count
    n_dates = result.get("n_dates", 0)
    if n_dates == 0:
        warnings.append("No dates found in output. Check site filter.")

    return warnings


# ---------------------------------------------------------------------------
# Processing
# ---------------------------------------------------------------------------

def process(args):
    """Convert CSV forcing data to WSIMOD data_input_dict format."""
    import csv

    data_input_dict = {}
    dates_set = set()
    variables_found = set()
    row_count = 0

    precip_factor = UNIT_CONVERSIONS["precipitation"][args.precip_unit]
    et0_factor = UNIT_CONVERSIONS["et0"][args.et0_unit]

    with open(args.input, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Apply site filter if provided
            if args.site and "site" in row:
                if row["site"].strip() != args.site:
                    continue

            variable = row["variable"].strip()
            date_str = row["date"].strip()
            value = float(row["value"])

            # Apply unit conversions
            if variable == "precipitation":
                value *= precip_factor
            elif variable == "et0":
                value *= et0_factor
            elif variable == "temperature" and args.temp_unit == "K":
                value -= 273.15
            elif variable == "flow" and args.flow_unit in UNIT_CONVERSIONS.get(
                "flow", {}
            ):
                value *= UNIT_CONVERSIONS["flow"][args.flow_unit]

            # Store as (variable, date_string) tuple
            # WSIMOD uses pandas Timestamp or to_datetime objects as keys
            key = (variable, date_str)
            data_input_dict[key] = value
            dates_set.add(date_str)
            variables_found.add(variable)
            row_count += 1

    dates_sorted = sorted(dates_set)

    result = {
        "status": "success",
        "data_input_dict": data_input_dict,
        "dates": dates_sorted,
        "n_dates": len(dates_sorted),
        "variables": sorted(variables_found),
        "n_records": row_count,
        "conversions_applied": {
            "precipitation": f"× {precip_factor} ({args.precip_unit} → m)",
            "et0": f"× {et0_factor} ({args.et0_unit} → m)",
            "temperature": "- 273.15" if args.temp_unit == "K" else "none (already °C)",
        },
    }

    # Validate outputs
    warnings = validate_outputs(result, args)
    if warnings:
        result["warnings"] = warnings

    return result


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def serialize_result(result, output_path):
    """Write result to JSON, converting tuple keys to strings."""
    serializable = dict(result)
    if "data_input_dict" in serializable:
        serializable["data_input_dict"] = {
            f"{var}|{date}": val
            for (var, date), val in serializable["data_input_dict"].items()
        }
    with open(output_path, "w") as f:
        json.dump(serializable, f, indent=2, default=str)


def _emit_and_exit(errors, warnings):
    """Print errors/warnings as JSON and exit."""
    print(json.dumps({"status": "error", "errors": errors, "warnings": warnings}))
    sys.exit(1)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Convert meteorological CSV to WSIMOD forcing format"
    )
    parser.add_argument(
        "--input", required=True, help="Path to input CSV file"
    )
    parser.add_argument(
        "--site", default=None,
        help="Filter rows by site name (column 'site')"
    )
    parser.add_argument(
        "--output", required=True, help="Path to output JSON file"
    )
    parser.add_argument(
        "--precip-unit", default="mm", choices=["mm", "m"],
        help="Input precipitation unit (default: mm → converted to m)"
    )
    parser.add_argument(
        "--et0-unit", default="mm", choices=["mm", "m"],
        help="Input ET₀ unit (default: mm → converted to m)"
    )
    parser.add_argument(
        "--temp-unit", default="C", choices=["C", "K"],
        help="Input temperature unit (default: C)"
    )
    parser.add_argument(
        "--flow-unit", default="m3_s", choices=["m3_s", "ML_d", "m3_d"],
        help="Input flow unit (default: m3_s → converted to ML/d)"
    )

    args = parser.parse_args()
    validate_inputs(args)
    result = process(args)
    serialize_result(result, args.output)

    summary = {
        "status": result["status"],
        "n_dates": result["n_dates"],
        "n_records": result["n_records"],
        "variables": result["variables"],
        "output": args.output,
    }
    if "warnings" in result:
        summary["warnings"] = result["warnings"]

    print(json.dumps(summary, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
