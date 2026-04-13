#!/usr/bin/env python3
"""
convert_forcing_to_amanzi.py — Forcing / Recharge Converter for Amanzi/ATS

Converts global forcing data (ERA5, CMFD, MSWX) or user-specified recharge
rates into Amanzi-compatible XML boundary condition snippets or JSON parameter
files.

Key unit conversions:
  - Precipitation: mm/hr → kg/m²/s  (÷3600, ×ρ_w/1000 ≈ ×0.000278)
  - Recharge: mm/yr → kg/m²/s       (×998.2 / (1000 × 3.156e7))
  - Recharge: cm/yr → kg/m²/s       (×998.2 / (100 × 3.156e7))
  - Temperature: °C → K             (+273.15)
  - Time: years → seconds            (×3.156e7)

Pattern: validate_inputs → process → validate_outputs
"""

import argparse
import json
import sys
import os
import numpy as np

# ============================================================================
# Constants
# ============================================================================
SECONDS_PER_YEAR = 3.15576e7  # 365.25 days
SECONDS_PER_DAY = 86400.0
WATER_DENSITY = 998.2  # kg/m³
GRAVITY = 9.80665  # m/s²


# ============================================================================
# Validation
# ============================================================================
def validate_inputs(args):
    """Validate input arguments before processing."""
    errors = []

    if args.recharge_mm_yr is not None:
        if args.recharge_mm_yr < 0:
            errors.append(f"Recharge cannot be negative: {args.recharge_mm_yr} mm/yr")
        if args.recharge_mm_yr > 5000:
            errors.append(
                f"Recharge {args.recharge_mm_yr} mm/yr is unrealistically high "
                f"(>5000 mm/yr). Check units — did you mean cm/yr?"
            )

    if args.recharge_cm_yr is not None:
        if args.recharge_cm_yr < 0:
            errors.append(f"Recharge cannot be negative: {args.recharge_cm_yr} cm/yr")
        if args.recharge_cm_yr > 500:
            errors.append(
                f"Recharge {args.recharge_cm_yr} cm/yr is unrealistically high "
                f"(>500 cm/yr = 5000 mm/yr)."
            )

    if args.forcing_csv is not None and not os.path.exists(args.forcing_csv):
        errors.append(f"Forcing CSV file not found: {args.forcing_csv}")

    if args.start_year is not None and args.end_year is not None:
        if args.end_year <= args.start_year:
            errors.append(
                f"end_year ({args.end_year}) must be > start_year ({args.start_year})"
            )

    if errors:
        for e in errors:
            print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)

    print("[OK] Input validation passed.")


def validate_outputs(result):
    """Validate output values are physically reasonable."""
    warnings = []

    if "recharge_kg_m2_s" in result:
        val = result["recharge_kg_m2_s"]
        if val < 0:
            warnings.append(f"Negative recharge flux: {val:.2e} kg/m²/s")
        if val > 1e-4:
            warnings.append(
                f"Recharge flux {val:.2e} kg/m²/s seems very high "
                f"(>{1e-4:.0e}). Equivalent to {val * SECONDS_PER_YEAR * 1000 / WATER_DENSITY:.0f} mm/yr"
            )
        if val > 0 and val < 1e-12:
            warnings.append(
                f"Recharge flux {val:.2e} kg/m²/s is extremely small. "
                f"Equivalent to {val * SECONDS_PER_YEAR * 1000 / WATER_DENSITY:.6f} mm/yr"
            )

    if "time_start_s" in result and "time_end_s" in result:
        duration_yr = (result["time_end_s"] - result["time_start_s"]) / SECONDS_PER_YEAR
        if duration_yr > 1000:
            warnings.append(f"Simulation duration is {duration_yr:.0f} years — very long run.")
        if duration_yr < 0.001:
            warnings.append(
                f"Simulation duration is {duration_yr:.6f} years — suspiciously short. "
                f"Check time units."
            )

    for w in warnings:
        print(f"[WARNING] {w}", file=sys.stderr)

    if not warnings:
        print("[OK] Output validation passed.")

    return len(warnings) == 0


# ============================================================================
# Converters
# ============================================================================
def mm_yr_to_kg_m2_s(mm_yr):
    """Convert recharge from mm/yr to kg/m²/s (Amanzi mass flux unit)."""
    # mm/yr → m/yr → m/s → kg/m²/s
    m_per_s = mm_yr / 1000.0 / SECONDS_PER_YEAR
    kg_m2_s = m_per_s * WATER_DENSITY
    return kg_m2_s


def cm_yr_to_kg_m2_s(cm_yr):
    """Convert recharge from cm/yr to kg/m²/s."""
    return mm_yr_to_kg_m2_s(cm_yr * 10.0)


def celsius_to_kelvin(temp_c):
    """Convert temperature from Celsius to Kelvin."""
    return temp_c + 273.15


def head_m_to_pressure_pa(head_m, z_ref=0.0, p_atm=101325.0):
    """Convert hydraulic head (m) to pressure (Pa)."""
    return p_atm + WATER_DENSITY * GRAVITY * (head_m - z_ref)


def years_to_seconds(years):
    """Convert years to seconds."""
    return years * SECONDS_PER_YEAR


def convert_constant_recharge(args):
    """Convert a constant recharge rate to Amanzi parameters."""
    if args.recharge_mm_yr is not None:
        recharge_si = mm_yr_to_kg_m2_s(args.recharge_mm_yr)
        source_val = args.recharge_mm_yr
        source_unit = "mm/yr"
    elif args.recharge_cm_yr is not None:
        recharge_si = cm_yr_to_kg_m2_s(args.recharge_cm_yr)
        source_val = args.recharge_cm_yr
        source_unit = "cm/yr"
    else:
        print("[ERROR] Must specify --recharge_mm_yr or --recharge_cm_yr", file=sys.stderr)
        sys.exit(1)

    time_start_s = years_to_seconds(args.start_year) if args.start_year else 0.0
    time_end_s = years_to_seconds(args.end_year) if args.end_year else years_to_seconds(100)

    result = {
        "type": "constant_recharge",
        "source_value": source_val,
        "source_unit": source_unit,
        "recharge_kg_m2_s": recharge_si,
        "recharge_m_s": recharge_si / WATER_DENSITY,
        "recharge_mm_yr": source_val if source_unit == "mm/yr" else source_val * 10,
        "time_start_s": time_start_s,
        "time_end_s": time_end_s,
        "duration_years": (time_end_s - time_start_s) / SECONDS_PER_YEAR,
        "xml_snippet": {
            "boundary_condition_type": "mass_flux",
            "region": args.region or "Top Surface",
            "value": recharge_si,
            "unit": "kg/m^2/s",
        },
        "unit_conversions_applied": [
            f"{source_val} {source_unit} → {recharge_si:.6e} kg/m²/s",
            f"Equivalent: {recharge_si / WATER_DENSITY:.6e} m/s volumetric flux",
        ],
    }

    return result


def convert_forcing_csv(args):
    """Convert a forcing CSV (ERA5/CMFD format) to Amanzi time-series BCs."""
    try:
        import pandas as pd
    except ImportError:
        print("[ERROR] pandas required for CSV conversion. pip install pandas", file=sys.stderr)
        sys.exit(1)

    df = pd.read_csv(args.forcing_csv)
    print(f"[INFO] Read {len(df)} rows from {args.forcing_csv}")
    print(f"[INFO] Columns: {list(df.columns)}")

    result = {"type": "time_varying_forcing", "source_file": args.forcing_csv}

    # Convert precipitation if present
    precip_cols = [c for c in df.columns if "precip" in c.lower() or "rain" in c.lower() or "prcp" in c.lower()]
    if precip_cols:
        col = precip_cols[0]
        # Assume mm/hr input; convert to kg/m²/s
        df["recharge_kg_m2_s"] = df[col] / 3600.0 * WATER_DENSITY / 1000.0
        result["precip_column"] = col
        result["precip_max_mm_hr"] = float(df[col].max())
        result["recharge_max_kg_m2_s"] = float(df["recharge_kg_m2_s"].max())

    # Convert temperature if present
    temp_cols = [c for c in df.columns if "temp" in c.lower() or "tas" in c.lower()]
    if temp_cols:
        col = temp_cols[0]
        vals = df[col].values
        if np.nanmean(vals) < 100:  # Likely Celsius
            df["temperature_K"] = vals + 273.15
            result["temp_converted"] = "C_to_K"
        else:
            df["temperature_K"] = vals
            result["temp_converted"] = "already_K"

    # Build time array in seconds
    if "time" in df.columns:
        df["time_s"] = df["time"]
    elif "year" in df.columns:
        df["time_s"] = df["year"] * SECONDS_PER_YEAR
    else:
        # Assume daily timestep
        df["time_s"] = np.arange(len(df)) * SECONDS_PER_DAY

    result["n_timesteps"] = len(df)
    result["time_start_s"] = float(df["time_s"].iloc[0])
    result["time_end_s"] = float(df["time_s"].iloc[-1])

    return result


# ============================================================================
# Main
# ============================================================================
def main():
    parser = argparse.ArgumentParser(
        description="Convert forcing/recharge data to Amanzi-compatible format"
    )
    parser.add_argument("--recharge_mm_yr", type=float, help="Constant recharge in mm/yr")
    parser.add_argument("--recharge_cm_yr", type=float, help="Constant recharge in cm/yr")
    parser.add_argument("--forcing_csv", type=str, help="Path to forcing CSV file")
    parser.add_argument("--start_year", type=float, help="Simulation start year")
    parser.add_argument("--end_year", type=float, help="Simulation end year")
    parser.add_argument("--region", type=str, default="Top Surface",
                        help="Boundary region name")
    parser.add_argument("--output", type=str, required=True,
                        help="Output JSON file path")
    args = parser.parse_args()

    # Validate
    validate_inputs(args)

    # Process
    if args.forcing_csv:
        result = convert_forcing_csv(args)
    else:
        result = convert_constant_recharge(args)

    # Validate outputs
    validate_outputs(result)

    # Write
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(result, f, indent=2)

    print(f"[OK] Wrote forcing parameters to {args.output}")


if __name__ == "__main__":
    main()
