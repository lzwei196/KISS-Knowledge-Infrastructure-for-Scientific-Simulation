#!/usr/bin/env python3
"""
convert_forcing_to_ogs.py — Convert external forcing/boundary condition data to OGS format.

Converts time-series data from common hydrological sources (CSV, NetCDF) to
OpenGeoSys-compatible boundary condition files. Handles critical unit conversions:
  - Precipitation: mm/day → m/s (÷ 86,400,000)
  - Temperature: °C → K (+ 273.15)
  - Hydraulic head: m → Pa (× ρ × g)
  - Recharge: mm/day → m/s (÷ 86,400,000)
  - Flux: L/s → m³/s (÷ 1000)

CRITICAL CONSTRAINTS:
  - OGS uses SI units exclusively: Pa, K, m, s, kg
  - Time column MUST be in seconds from simulation start
  - All spatial coordinates in meters
  - Output format matches OGS curve/parameter input expectations

Usage:
    python convert_forcing_to_ogs.py --source recharge.csv --variable recharge \\
        --source_unit mm/day --target_unit m/s --output recharge_ogs.csv
    python convert_forcing_to_ogs.py --source temperature.csv --variable temperature \\
        --source_unit degC --target_unit K --output temp_ogs.csv
"""

import argparse
import json
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd


# ============================================================================
# Unit conversion factors: multiply source value by factor to get target unit
# ============================================================================
UNIT_CONVERSIONS = {
    # Precipitation / Recharge
    ("mm/day", "m/s"): 1.0 / (1000.0 * 86400.0),
    ("mm/hr", "m/s"): 1.0 / (1000.0 * 3600.0),
    ("mm/day", "m/day"): 1.0 / 1000.0,
    ("m/day", "m/s"): 1.0 / 86400.0,
    # Temperature
    ("degC", "K"): None,  # special: additive, not multiplicative
    ("celsius", "K"): None,
    # Pressure / Head
    ("m_head", "Pa"): 9810.0,  # ρ*g ≈ 998.2 * 9.81
    ("kPa", "Pa"): 1000.0,
    ("bar", "Pa"): 100000.0,
    ("atm", "Pa"): 101325.0,
    # Flow rate
    ("L/s", "m3/s"): 0.001,
    ("m3/day", "m3/s"): 1.0 / 86400.0,
    ("m3/hr", "m3/s"): 1.0 / 3600.0,
    # Permeability
    ("darcy", "m2"): 9.869233e-13,
    ("mdarcy", "m2"): 9.869233e-16,
    # Time
    ("days", "seconds"): 86400.0,
    ("hours", "seconds"): 3600.0,
    ("years", "seconds"): 365.25 * 86400.0,
    # Identity
    ("Pa", "Pa"): 1.0,
    ("K", "K"): 1.0,
    ("m/s", "m/s"): 1.0,
    ("m2", "m2"): 1.0,
    ("m3/s", "m3/s"): 1.0,
}


def validate_inputs(args):
    """Validate input arguments before processing."""
    errors = []

    if not os.path.isfile(args.source):
        errors.append(f"Source file not found: {args.source}")

    conv_key = (args.source_unit, args.target_unit)
    if conv_key not in UNIT_CONVERSIONS:
        errors.append(
            f"Unknown unit conversion: {args.source_unit} → {args.target_unit}. "
            f"Supported: {list(UNIT_CONVERSIONS.keys())}"
        )

    if args.start_date and args.end_date:
        try:
            sd = datetime.strptime(args.start_date, "%Y-%m-%d")
            ed = datetime.strptime(args.end_date, "%Y-%m-%d")
            if ed <= sd:
                errors.append("end_date must be after start_date")
        except ValueError as e:
            errors.append(f"Date parse error: {e}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stdout)
        sys.exit(1)


def convert_units(values, source_unit, target_unit):
    """Apply unit conversion. Returns converted numpy array."""
    conv_key = (source_unit, target_unit)
    factor = UNIT_CONVERSIONS.get(conv_key)

    if factor is None:
        # Additive conversion (temperature)
        if source_unit in ("degC", "celsius") and target_unit == "K":
            return values + 273.15
        raise ValueError(f"No conversion defined for {source_unit} → {target_unit}")

    return values * factor


def read_source_csv(filepath, variable, time_col="date"):
    """Read CSV source file with flexible column detection."""
    df = pd.read_csv(filepath)

    # Find time column
    time_candidates = ["date", "datetime", "time", "Date", "DateTime", "Time", "TIMESTAMP"]
    found_time = None
    for tc in time_candidates:
        if tc in df.columns:
            found_time = tc
            break
    if found_time is None and len(df.columns) >= 2:
        found_time = df.columns[0]  # Assume first column is time

    # Find value column
    var_candidates = [variable, variable.lower(), variable.upper(), variable.capitalize()]
    found_var = None
    for vc in var_candidates:
        if vc in df.columns:
            found_var = vc
            break
    if found_var is None and len(df.columns) >= 2:
        found_var = df.columns[1]  # Assume second column is value

    return df, found_time, found_var


def dates_to_seconds(dates, reference_date=None):
    """Convert datetime series to seconds from reference date."""
    dt_series = pd.to_datetime(dates)
    if reference_date is None:
        reference_date = dt_series.iloc[0]
    else:
        reference_date = pd.to_datetime(reference_date)

    delta = dt_series - reference_date
    return delta.dt.total_seconds().values


def process(args):
    """Main processing: read source, convert units, write OGS format."""
    warnings = []

    # Read source data
    df, time_col, var_col = read_source_csv(args.source, args.variable)

    if time_col is None or var_col is None:
        return {"status": "error", "errors": [f"Could not identify time/value columns in {args.source}"]}

    # Extract values
    raw_values = df[var_col].values.astype(float)

    # Convert time to seconds
    ref_date = args.start_date if args.start_date else None
    try:
        time_seconds = dates_to_seconds(df[time_col], ref_date)
    except Exception:
        # If not datetime, assume already numeric (seconds or days)
        time_seconds = df[time_col].values.astype(float)
        if args.source_unit != "seconds" and max(time_seconds) < 1e6:
            warnings.append("Time values appear to be in days, not seconds — applying ×86400")
            time_seconds = time_seconds * 86400.0

    # Filter date range
    if args.start_date and args.end_date:
        try:
            dt_series = pd.to_datetime(df[time_col])
            mask = (dt_series >= args.start_date) & (dt_series <= args.end_date)
            time_seconds = time_seconds[mask]
            raw_values = raw_values[mask]
        except Exception:
            pass  # If time is numeric, skip date filtering

    # Convert units
    converted_values = convert_units(raw_values, args.source_unit, args.target_unit)

    # Validate converted values
    if np.any(np.isnan(converted_values)):
        warnings.append(f"NaN values detected after conversion ({np.sum(np.isnan(converted_values))} NaNs)")
    if np.any(np.isinf(converted_values)):
        warnings.append(f"Inf values detected after conversion")

    # Variable-specific sanity checks
    if args.variable in ("temperature", "temp", "T"):
        if args.target_unit == "K":
            if np.any(converted_values < 200) or np.any(converted_values > 400):
                warnings.append(f"Temperature outside 200-400 K range — check conversion")
            if np.mean(converted_values) < 100:
                warnings.append("Mean temperature < 100 K — likely still in °C, not K")

    if args.variable in ("recharge", "precipitation", "rain"):
        if args.target_unit == "m/s":
            if np.any(converted_values > 1e-4):
                warnings.append("Recharge > 1e-4 m/s (>8.6 mm/day) — unusually high")
            if np.any(converted_values < 0):
                warnings.append("Negative recharge values — clipping to 0")
                converted_values = np.maximum(converted_values, 0.0)

    if args.variable in ("pressure", "head"):
        if args.target_unit == "Pa":
            if np.any(converted_values < -1e7):
                warnings.append("Pressure < -10 MPa — check conversion from head")

    # Build output dataframe
    out_df = pd.DataFrame({
        "time_s": time_seconds,
        args.variable: converted_values
    })

    # Write output
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    out_df.to_csv(args.output, index=False)

    result = {
        "status": "success",
        "source": args.source,
        "output": args.output,
        "variable": args.variable,
        "conversion": f"{args.source_unit} → {args.target_unit}",
        "n_records": len(out_df),
        "time_range_s": [float(time_seconds[0]), float(time_seconds[-1])],
        "value_range": [float(np.nanmin(converted_values)), float(np.nanmax(converted_values))],
        "value_mean": float(np.nanmean(converted_values)),
        "warnings": warnings,
    }

    return result


def validate_outputs(result):
    """Validate output result and add warnings."""
    if result["status"] != "success":
        return result

    warnings = result.get("warnings", [])

    if result["n_records"] == 0:
        warnings.append("Output has 0 records — check date range or column names")
        result["status"] = "error"

    if result["n_records"] < 10:
        warnings.append(f"Only {result['n_records']} records — is date range correct?")

    result["warnings"] = warnings
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Convert external forcing data to OGS-compatible format with unit conversions"
    )
    parser.add_argument("--source", type=str, required=True, help="Input CSV file path")
    parser.add_argument("--source_format", type=str, default="csv", help="Input format (csv, netcdf)")
    parser.add_argument("--variable", type=str, required=True, help="Variable name (recharge, temperature, pressure, head)")
    parser.add_argument("--source_unit", type=str, required=True, help="Source unit (mm/day, degC, m_head, kPa, etc.)")
    parser.add_argument("--target_unit", type=str, required=True, help="Target OGS unit (m/s, K, Pa, etc.)")
    parser.add_argument("--start_date", type=str, default=None, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end_date", type=str, default=None, help="End date (YYYY-MM-DD)")
    parser.add_argument("--output", type=str, required=True, help="Output CSV file path")

    args = parser.parse_args()

    validate_inputs(args)
    result = process(args)
    result = validate_outputs(result)

    output_json = json.dumps(result, indent=2)
    if args.output:
        summary_path = args.output.replace(".csv", "_summary.json")
        os.makedirs(os.path.dirname(summary_path) or ".", exist_ok=True)
        with open(summary_path, "w") as f:
            f.write(output_json)
        print(f"Output written to {args.output}", file=sys.stderr)
        print(f"Summary written to {summary_path}", file=sys.stderr)
    print(output_json)


if __name__ == "__main__":
    main()
