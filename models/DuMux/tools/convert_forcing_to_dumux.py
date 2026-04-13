#!/usr/bin/env python3
"""
convert_forcing_to_dumux.py — Convert meteorological/recharge data to DuMux boundary conditions.

Pipeline stage: s2 (Forcing/Recharge)
Pattern: validate → process → validate

Converts global forcing datasets (CMFD, MSWX, ERA5) or custom recharge time series
into DuMux-compatible Neumann boundary condition values.

Key unit conversions:
  - Precipitation mm/day → recharge kg/(m²·s)
  - Evapotranspiration mm/day → extraction kg/(m²·s)
  - Hydraulic head m → pressure Pa

Usage:
    python convert_forcing_to_dumux.py \\
        --input forcing.csv \\
        --output recharge_bc.csv \\
        --recharge_fraction 0.15 \\
        --format dumux
"""

import argparse
import sys
import os
import csv
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

# ─── Constants ────────────────────────────────────────────────────────────────
RHO_WATER = 1000.0        # kg/m³
GRAVITY = 9.81             # m/s²
ATM_PRESSURE = 101325.0    # Pa
SECONDS_PER_DAY = 86400.0  # s/day

# ─── Validation helpers ──────────────────────────────────────────────────────

def validate_inputs(input_path: str, recharge_fraction: float) -> dict:
    """Validate input file exists and parameters are physically reasonable.

    Returns:
        dict with keys: valid (bool), errors (list), warnings (list), metadata (dict)
    """
    result = {"valid": True, "errors": [], "warnings": [], "metadata": {}}

    # Check file exists
    if not os.path.isfile(input_path):
        result["valid"] = False
        result["errors"].append(f"Input file not found: {input_path}")
        return result

    # Check recharge fraction
    if recharge_fraction < 0 or recharge_fraction > 1:
        result["valid"] = False
        result["errors"].append(
            f"Recharge fraction must be 0-1, got {recharge_fraction}"
        )
    if recharge_fraction > 0.5:
        result["warnings"].append(
            f"Recharge fraction {recharge_fraction} is unusually high (>50% of precip). "
            "Typical values: 0.05-0.30 for temperate climates."
        )

    # Read and validate CSV
    try:
        with open(input_path, "r") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            rows = list(reader)

        result["metadata"]["n_rows"] = len(rows)
        result["metadata"]["columns"] = headers

        if len(rows) == 0:
            result["valid"] = False
            result["errors"].append("Input CSV is empty")
            return result

        # Check for required columns (flexible: accept various naming)
        precip_col = None
        date_col = None
        for col in headers:
            cl = col.lower().strip()
            if cl in ("precip", "precipitation", "rain", "rainfall", "p", "pr", "prcp"):
                precip_col = col
            if cl in ("date", "datetime", "time", "timestamp", "day"):
                date_col = col

        if precip_col is None:
            result["valid"] = False
            result["errors"].append(
                f"No precipitation column found in headers: {headers}. "
                "Expected one of: precip, precipitation, rain, rainfall, p, pr, prcp"
            )
        else:
            result["metadata"]["precip_column"] = precip_col

        if date_col is None:
            result["warnings"].append(
                "No date column found. Will generate synthetic daily dates."
            )
        else:
            result["metadata"]["date_column"] = date_col

        # Validate precipitation values
        if precip_col:
            precip_vals = []
            for row in rows:
                try:
                    val = float(row[precip_col])
                    precip_vals.append(val)
                except (ValueError, TypeError):
                    pass

            if len(precip_vals) > 0:
                pmax = max(precip_vals)
                pmin = min(precip_vals)
                pmean = sum(precip_vals) / len(precip_vals)

                result["metadata"]["precip_max"] = pmax
                result["metadata"]["precip_min"] = pmin
                result["metadata"]["precip_mean"] = pmean

                # UNIT TRAP: detect if precip might be in m/day instead of mm/day
                if pmax < 0.5 and pmean < 0.01:
                    result["warnings"].append(
                        f"Max precip = {pmax:.4f}. Values look like m/day, not mm/day. "
                        "If in m/day, set --precip_unit m_per_day to skip mm→m conversion."
                    )

                # UNIT TRAP: detect if precip might be in mm/3hr
                if pmax > 200:
                    result["warnings"].append(
                        f"Max precip = {pmax:.1f} mm/day — extremely high. "
                        "Check if data is sub-daily (mm/3hr). Use --precip_unit mm_per_3hr."
                    )

                if pmin < 0:
                    result["errors"].append(
                        f"Negative precipitation detected (min={pmin}). "
                        "Precipitation cannot be negative."
                    )
                    result["valid"] = False

    except Exception as e:
        result["valid"] = False
        result["errors"].append(f"Failed to read input CSV: {e}")

    return result


def convert_precip_to_recharge(
    precip_mm_per_day: np.ndarray,
    recharge_fraction: float,
    precip_unit: str = "mm_per_day",
) -> np.ndarray:
    """Convert precipitation to DuMux recharge rate.

    Args:
        precip_mm_per_day: Precipitation array (in unit specified by precip_unit)
        recharge_fraction: Fraction of precipitation becoming recharge (0-1)
        precip_unit: One of 'mm_per_day', 'm_per_day', 'mm_per_3hr'

    Returns:
        Recharge rate in kg/(m²·s) — DuMux Neumann BC units
        SIGN: negative = inflow (DuMux convention: positive = outflow)
    """
    # Step 1: Convert to mm/day
    if precip_unit == "mm_per_day":
        p_mm_day = precip_mm_per_day
    elif precip_unit == "m_per_day":
        p_mm_day = precip_mm_per_day * 1000.0
    elif precip_unit == "mm_per_3hr":
        p_mm_day = precip_mm_per_day * 8.0  # 8 intervals per day
    else:
        raise ValueError(f"Unknown precip_unit: {precip_unit}")

    # Step 2: Apply recharge fraction
    recharge_mm_day = p_mm_day * recharge_fraction

    # Step 3: Convert mm/day → kg/(m²·s)
    # 1 mm/day = 1 kg/m² per day = 1/86400 kg/(m²·s)
    recharge_kg_m2_s = recharge_mm_day * RHO_WATER / (SECONDS_PER_DAY * 1000.0)

    # Step 4: Apply DuMux sign convention (negative = inflow)
    return -recharge_kg_m2_s


def head_to_pressure(head_m: float, elevation_m: float = 0.0) -> float:
    """Convert hydraulic head (m above datum) to absolute pressure (Pa).

    Args:
        head_m: Hydraulic head in meters above datum
        elevation_m: Elevation of the point in meters above datum

    Returns:
        Absolute pressure in Pa

    TRAP: Must use absolute pressure, not gauge pressure.
    p = p_atm + ρ·g·(h - z)
    """
    return ATM_PRESSURE + RHO_WATER * GRAVITY * (head_m - elevation_m)


def validate_outputs(recharge_rates: np.ndarray) -> dict:
    """Validate computed recharge rates are physically reasonable.

    Returns:
        dict with keys: valid (bool), errors (list), warnings (list)
    """
    result = {"valid": True, "errors": [], "warnings": []}

    if len(recharge_rates) == 0:
        result["valid"] = False
        result["errors"].append("Empty recharge array")
        return result

    rmax = np.max(np.abs(recharge_rates))
    rmean = np.mean(np.abs(recharge_rates))

    # Physically reasonable bounds for recharge
    # Max plausible recharge: ~50 mm/day = ~5.8e-4 kg/(m²·s)
    if rmax > 1e-3:
        result["warnings"].append(
            f"Max recharge rate |{rmax:.2e}| kg/(m²·s) is very high "
            f"(≈ {rmax * SECONDS_PER_DAY * 1000 / RHO_WATER:.1f} mm/day). "
            "Check unit conversions."
        )

    # Zero recharge is suspicious for long series
    if rmean < 1e-15:
        result["warnings"].append(
            "Mean recharge is effectively zero. Check input data."
        )

    # Check for NaN
    if np.any(np.isnan(recharge_rates)):
        result["valid"] = False
        result["errors"].append("NaN values in computed recharge rates")

    return result


def process(
    input_path: str,
    output_path: str,
    recharge_fraction: float = 0.15,
    precip_unit: str = "mm_per_day",
    start_date: str = "2000-01-01",
) -> dict:
    """Main processing pipeline: validate → process → validate.

    Returns:
        dict with processing summary
    """
    summary = {"status": "failed", "input": input_path, "output": output_path}

    # ── Validate inputs ──
    print("=== Validating inputs ===")
    input_val = validate_inputs(input_path, recharge_fraction)
    for w in input_val["warnings"]:
        print(f"  WARNING: {w}")
    if not input_val["valid"]:
        for e in input_val["errors"]:
            print(f"  ERROR: {e}")
        summary["errors"] = input_val["errors"]
        return summary

    # ── Process ──
    print("=== Processing ===")
    meta = input_val["metadata"]
    precip_col = meta.get("precip_column")
    date_col = meta.get("date_column")

    # Read CSV
    with open(input_path, "r") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    # Extract precipitation
    precip = np.array([float(row[precip_col]) for row in rows])
    precip = np.maximum(precip, 0.0)  # clip negatives

    # Extract or generate dates
    if date_col:
        dates = [row[date_col] for row in rows]
    else:
        base = datetime.strptime(start_date, "%Y-%m-%d")
        dates = [(base + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(len(precip))]

    # Convert to DuMux recharge
    recharge = convert_precip_to_recharge(precip, recharge_fraction, precip_unit)

    # Also compute time in seconds from start for DuMux time axis
    time_seconds = np.arange(len(recharge)) * SECONDS_PER_DAY

    print(f"  Processed {len(recharge)} time steps")
    print(f"  Recharge range: [{np.min(recharge):.2e}, {np.max(recharge):.2e}] kg/(m²·s)")
    print(f"  Mean recharge: {np.mean(recharge):.2e} kg/(m²·s)")
    print(f"  Equivalent mean: {np.mean(np.abs(recharge)) * SECONDS_PER_DAY * 1000 / RHO_WATER:.2f} mm/day")

    # ── Validate outputs ──
    print("=== Validating outputs ===")
    output_val = validate_outputs(recharge)
    for w in output_val["warnings"]:
        print(f"  WARNING: {w}")
    if not output_val["valid"]:
        for e in output_val["errors"]:
            print(f"  ERROR: {e}")
        summary["errors"] = output_val["errors"]
        return summary

    # ── Write output ──
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "time_s", "recharge_kg_m2_s", "precip_mm_day"])
        for i in range(len(recharge)):
            writer.writerow([
                dates[i],
                f"{time_seconds[i]:.0f}",
                f"{recharge[i]:.8e}",
                f"{precip[i]:.2f}",
            ])

    print(f"  Written to: {output_path}")
    summary["status"] = "success"
    summary["n_timesteps"] = len(recharge)
    summary["mean_recharge_kg_m2_s"] = float(np.mean(recharge))
    summary["mean_recharge_mm_day"] = float(
        np.mean(np.abs(recharge)) * SECONDS_PER_DAY * 1000 / RHO_WATER
    )
    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Convert precipitation/met data to DuMux recharge boundary conditions"
    )
    parser.add_argument("--input", required=True, help="Input CSV with precipitation column")
    parser.add_argument("--output", required=True, help="Output CSV for DuMux recharge BC")
    parser.add_argument(
        "--recharge_fraction", type=float, default=0.15,
        help="Fraction of precipitation becoming recharge (0-1). Default: 0.15"
    )
    parser.add_argument(
        "--precip_unit", default="mm_per_day",
        choices=["mm_per_day", "m_per_day", "mm_per_3hr"],
        help="Unit of precipitation in input file"
    )
    parser.add_argument(
        "--start_date", default="2000-01-01",
        help="Start date for time axis if no date column in input"
    )
    args = parser.parse_args()

    result = process(
        input_path=args.input,
        output_path=args.output,
        recharge_fraction=args.recharge_fraction,
        precip_unit=args.precip_unit,
        start_date=args.start_date,
    )

    if result["status"] != "success":
        print(f"\nFAILED: {result.get('errors', ['Unknown error'])}")
        sys.exit(1)
    else:
        print(f"\nSUCCESS: {result['n_timesteps']} time steps processed")
        print(f"  Mean recharge: {result['mean_recharge_mm_day']:.3f} mm/day")


if __name__ == "__main__":
    main()
