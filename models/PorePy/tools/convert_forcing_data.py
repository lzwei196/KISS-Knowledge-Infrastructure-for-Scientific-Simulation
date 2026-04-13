#!/usr/bin/env python3
"""Convert forcing / boundary condition data to PorePy-compatible format.

This tool converts external forcing data (pressure heads, recharge rates,
temperature time series) into PorePy boundary condition arrays and
TimeManager schedules.

CRITICAL UNIT CONVERSIONS:
- Pressure: Must be in Pa (not MPa, bar, or psi)
- Recharge: Must be in m/s (not mm/day or mm/year)
- Temperature: Must be in Kelvin (not Celsius or Fahrenheit)
- Time: Must be in seconds (not hours, days, or years)

Usage:
    python convert_forcing_data.py --input forcing.csv --output porepy_forcing.json
    python convert_forcing_data.py --input forcing.csv --output porepy_forcing.json \\
        --pressure-unit MPa --time-unit days --temp-unit celsius
"""

import argparse
import csv
import json
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional


# ─────────────────────────────────────────────────────────────
# Unit conversion factors → SI
# ─────────────────────────────────────────────────────────────
PRESSURE_TO_PA = {
    "Pa": 1.0,
    "kPa": 1e3,
    "MPa": 1e6,
    "GPa": 1e9,
    "bar": 1e5,
    "atm": 101325.0,
    "psi": 6894.76,
    "mH2O": 9806.65,  # meters of water column
}

TIME_TO_S = {
    "s": 1.0,
    "seconds": 1.0,
    "min": 60.0,
    "minutes": 60.0,
    "h": 3600.0,
    "hours": 3600.0,
    "days": 86400.0,
    "d": 86400.0,
    "years": 3.15576e7,
    "yr": 3.15576e7,
}

TEMP_OFFSETS = {
    "K": (1.0, 0.0),         # T_K = T * 1 + 0
    "kelvin": (1.0, 0.0),
    "C": (1.0, 273.15),      # T_K = T_C + 273.15
    "celsius": (1.0, 273.15),
    "F": (5.0 / 9.0, 255.372),  # T_K = (T_F - 32) * 5/9 + 273.15
    "fahrenheit": (5.0 / 9.0, 255.372),
}

RECHARGE_TO_MS = {
    "m/s": 1.0,
    "mm/day": 1.0 / (1000.0 * 86400.0),
    "mm/year": 1.0 / (1000.0 * 3.15576e7),
    "mm/hr": 1.0 / (1000.0 * 3600.0),
    "m/day": 1.0 / 86400.0,
    "m/year": 1.0 / 3.15576e7,
}


def validate_inputs(args: argparse.Namespace) -> List[str]:
    """Validate input arguments before processing.

    Returns:
        List of error messages (empty if valid).
    """
    errors = []

    if not os.path.isfile(args.input):
        errors.append(f"Input file not found: {args.input}")

    if args.pressure_unit not in PRESSURE_TO_PA:
        errors.append(
            f"Unknown pressure unit '{args.pressure_unit}'. "
            f"Valid: {list(PRESSURE_TO_PA.keys())}"
        )

    if args.time_unit not in TIME_TO_S:
        errors.append(
            f"Unknown time unit '{args.time_unit}'. "
            f"Valid: {list(TIME_TO_S.keys())}"
        )

    if args.temp_unit not in TEMP_OFFSETS:
        errors.append(
            f"Unknown temperature unit '{args.temp_unit}'. "
            f"Valid: {list(TEMP_OFFSETS.keys())}"
        )

    if args.recharge_unit not in RECHARGE_TO_MS:
        errors.append(
            f"Unknown recharge unit '{args.recharge_unit}'. "
            f"Valid: {list(RECHARGE_TO_MS.keys())}"
        )

    return errors


def read_csv_forcing(filepath: str) -> List[Dict[str, Any]]:
    """Read forcing data from CSV.

    Expected columns (flexible): time, pressure, temperature, recharge
    At minimum, 'time' column must be present.
    """
    rows = []
    with open(filepath, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            parsed = {}
            for key, val in row.items():
                key_lower = key.strip().lower()
                try:
                    parsed[key_lower] = float(val)
                except (ValueError, TypeError):
                    parsed[key_lower] = val
            rows.append(parsed)
    return rows


def convert_pressure(value: float, from_unit: str) -> float:
    """Convert pressure to Pa.

    CRITICAL: PorePy expects Pa internally. Using MPa without conversion
    will make all pressures 1e6 too small, causing wrong displacement fields.
    """
    return value * PRESSURE_TO_PA[from_unit]


def convert_time(value: float, from_unit: str) -> float:
    """Convert time to seconds.

    CRITICAL: PorePy Units class requires s=1 (time scaling not implemented).
    All time values MUST be in seconds.
    """
    return value * TIME_TO_S[from_unit]


def convert_temperature(value: float, from_unit: str) -> float:
    """Convert temperature to Kelvin.

    CRITICAL: PorePy uses Kelvin internally. Using Celsius directly
    will give temperatures near 0 K instead of ~293 K.
    """
    scale, offset = TEMP_OFFSETS[from_unit]
    if from_unit.lower() in ("f", "fahrenheit"):
        return (value - 32.0) * scale + 273.15
    return value * scale + offset


def convert_recharge(value: float, from_unit: str) -> float:
    """Convert recharge rate to m/s.

    CRITICAL: Using mm/day without conversion gives recharge 86.4 million
    times too large. This causes immediate flooding/overflow in models.
    """
    return value * RECHARGE_TO_MS[from_unit]


def process(
    rows: List[Dict[str, Any]],
    pressure_unit: str,
    time_unit: str,
    temp_unit: str,
    recharge_unit: str,
) -> Dict[str, Any]:
    """Convert all forcing data to SI units for PorePy.

    Returns:
        Dictionary with converted arrays and metadata.
    """
    result = {
        "times_s": [],
        "pressure_pa": [],
        "temperature_k": [],
        "recharge_ms": [],
        "conversions_applied": {
            "pressure": f"{pressure_unit} → Pa (×{PRESSURE_TO_PA[pressure_unit]})",
            "time": f"{time_unit} → s (×{TIME_TO_S[time_unit]})",
            "temperature": f"{temp_unit} → K",
            "recharge": f"{recharge_unit} → m/s (×{RECHARGE_TO_MS[recharge_unit]})",
        },
    }

    for row in rows:
        if "time" in row:
            result["times_s"].append(convert_time(float(row["time"]), time_unit))
        if "pressure" in row:
            result["pressure_pa"].append(
                convert_pressure(float(row["pressure"]), pressure_unit)
            )
        if "temperature" in row:
            result["temperature_k"].append(
                convert_temperature(float(row["temperature"]), temp_unit)
            )
        if "recharge" in row:
            result["recharge_ms"].append(
                convert_recharge(float(row["recharge"]), recharge_unit)
            )

    return result


def validate_outputs(result: Dict[str, Any]) -> List[str]:
    """Validate converted outputs for physically reasonable ranges.

    Returns:
        List of warning messages.
    """
    warnings = []

    # Check pressure range
    if result["pressure_pa"]:
        p_max = max(result["pressure_pa"])
        p_min = min(result["pressure_pa"])
        if p_max > 1e12:
            warnings.append(
                f"CRITICAL: Max pressure {p_max:.2e} Pa is extremely high. "
                f"Check if input is already in Pa and being double-converted."
            )
        if p_min < 0:
            warnings.append(
                f"WARNING: Negative pressure {p_min:.2e} Pa detected. "
                f"May indicate vacuum or unit error."
            )

    # Check temperature range
    if result["temperature_k"]:
        t_max = max(result["temperature_k"])
        t_min = min(result["temperature_k"])
        if t_min < 200:
            warnings.append(
                f"CRITICAL: Min temperature {t_min:.1f} K is very low. "
                f"Check if Celsius values were not converted to Kelvin."
            )
        if t_max > 1000:
            warnings.append(
                f"WARNING: Max temperature {t_max:.1f} K is very high "
                f"for typical groundwater applications."
            )

    # Check recharge range
    if result["recharge_ms"]:
        r_max = max(result["recharge_ms"])
        if r_max > 1e-3:
            warnings.append(
                f"CRITICAL: Max recharge {r_max:.2e} m/s is extremely high "
                f"(>{r_max * 86400 * 1000:.0f} mm/day). Likely wrong units."
            )

    # Check time monotonicity
    if result["times_s"]:
        for i in range(1, len(result["times_s"])):
            if result["times_s"][i] <= result["times_s"][i - 1]:
                warnings.append(
                    f"WARNING: Time is not monotonically increasing at index {i}."
                )
                break

    return warnings


def main():
    parser = argparse.ArgumentParser(
        description="Convert forcing data to PorePy SI format.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--input", required=True, help="Input CSV file path")
    parser.add_argument("--output", required=True, help="Output JSON file path")
    parser.add_argument(
        "--pressure-unit", default="Pa", help=f"Input pressure unit {list(PRESSURE_TO_PA.keys())}"
    )
    parser.add_argument(
        "--time-unit", default="s", help=f"Input time unit {list(TIME_TO_S.keys())}"
    )
    parser.add_argument(
        "--temp-unit", default="K", help=f"Input temperature unit {list(TEMP_OFFSETS.keys())}"
    )
    parser.add_argument(
        "--recharge-unit", default="m/s", help=f"Input recharge unit {list(RECHARGE_TO_MS.keys())}"
    )
    args = parser.parse_args()

    # Step 1: Validate inputs
    errors = validate_inputs(args)
    if errors:
        print(json.dumps({"status": "error", "errors": errors}, indent=2))
        sys.exit(1)

    # Step 2: Read and convert
    rows = read_csv_forcing(args.input)
    result = process(
        rows, args.pressure_unit, args.time_unit, args.temp_unit, args.recharge_unit
    )

    # Step 3: Validate outputs
    warnings = validate_outputs(result)
    result["warnings"] = warnings
    result["status"] = "success" if not any("CRITICAL" in w for w in warnings) else "warning"

    # Write output
    with open(args.output, "w") as f:
        json.dump(result, f, indent=2)

    print(json.dumps({"status": result["status"], "output_file": args.output,
                       "n_records": len(result["times_s"]),
                       "warnings": warnings}, indent=2))


if __name__ == "__main__":
    main()
