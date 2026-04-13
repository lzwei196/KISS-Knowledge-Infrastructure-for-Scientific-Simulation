#!/usr/bin/env python3
"""
Convert generic meteorological forcing data to FSM2 input format.

Supports: ERA5, MSWX, generic CSV with standard column names.
Target format: FSM2 DRIV1D=1 (year month day hour SW LW Sf Rf Ta RH Ua Ps)

Unit conversions applied:
  - Temperature: °C → K (add 273.15)
  - Pressure: hPa → Pa (multiply 100), kPa → Pa (multiply 1000)
  - Precipitation: mm/h → kg/m²/s (divide 3600), mm/day → kg/m²/s (divide 86400)
  - Relative humidity: fraction 0-1 → percent 0-100 (multiply 100)
  - Wind speed: enforced minimum 0.1 m/s
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def validate_input(df: pd.DataFrame, required_cols: list[str]) -> list[str]:
    """Check that all required columns exist. Return list of missing ones."""
    missing = [c for c in required_cols if c not in df.columns]
    return missing


def validate_output(df: pd.DataFrame) -> list[str]:
    """Run physical-range checks on the output dataframe."""
    issues = []
    if (df["Ta"] < 180).any() or (df["Ta"] > 340).any():
        issues.append(f"Ta out of range [180, 340] K: min={df['Ta'].min():.1f}, max={df['Ta'].max():.1f}")
    if (df["Ps"] < 30000).any() or (df["Ps"] > 110000).any():
        issues.append(f"Ps out of range [30000, 110000] Pa: min={df['Ps'].min():.0f}, max={df['Ps'].max():.0f}")
    if (df["RH"] < 0).any() or (df["RH"] > 100.5).any():
        issues.append(f"RH out of range [0, 100] %: min={df['RH'].min():.1f}, max={df['RH'].max():.1f}")
    if (df["SW"] < 0).any():
        issues.append(f"SW has negative values: min={df['SW'].min():.1f}")
    if (df["LW"] < 50).any() or (df["LW"] > 600).any():
        issues.append(f"LW out of range [50, 600] W/m²: min={df['LW'].min():.1f}, max={df['LW'].max():.1f}")
    if (df["Sf"] < 0).any() or (df["Rf"] < 0).any():
        issues.append("Negative precipitation detected")
    if (df["Sf"].max() > 0.01) or (df["Rf"].max() > 0.05):
        issues.append(f"Precipitation suspiciously large (Sf max={df['Sf'].max():.4e}, Rf max={df['Rf'].max():.4e} kg/m²/s). Check units.")
    if (df["Ua"] < 0).any():
        issues.append("Negative wind speed detected")
    return issues


# ---------------------------------------------------------------------------
# Unit conversion functions
# ---------------------------------------------------------------------------

def convert_temperature(series: pd.Series, unit: str) -> pd.Series:
    """Convert temperature to Kelvin."""
    if unit == "C":
        return series + 273.15
    elif unit == "K":
        return series.copy()
    else:
        raise ValueError(f"Unknown temperature unit: {unit}")


def convert_pressure(series: pd.Series, unit: str) -> pd.Series:
    """Convert pressure to Pa."""
    if unit == "hPa":
        return series * 100.0
    elif unit == "kPa":
        return series * 1000.0
    elif unit == "Pa":
        return series.copy()
    else:
        raise ValueError(f"Unknown pressure unit: {unit}")


def convert_precip(series: pd.Series, unit: str) -> pd.Series:
    """Convert precipitation to kg/m²/s."""
    if unit == "mm/h":
        return series / 3600.0
    elif unit == "mm/day":
        return series / 86400.0
    elif unit == "kg/m2/s":
        return series.copy()
    elif unit == "mm/s":
        return series.copy()  # 1 mm/s water = 1 kg/m²/s
    else:
        raise ValueError(f"Unknown precipitation unit: {unit}")


def convert_humidity(series: pd.Series, unit: str) -> pd.Series:
    """Convert relative humidity to percent 0-100."""
    if unit == "fraction":
        return series * 100.0
    elif unit == "percent":
        return series.copy()
    else:
        raise ValueError(f"Unknown humidity unit: {unit}")


# ---------------------------------------------------------------------------
# Auto-detect units from data ranges
# ---------------------------------------------------------------------------

def auto_detect_units(df: pd.DataFrame, col_map: dict) -> dict:
    """Heuristically detect units from data ranges."""
    units = {}

    # Temperature
    ta = df[col_map["Ta"]]
    if ta.median() < 100:
        units["Ta"] = "C"
        print("  Auto-detected Ta unit: °C (median < 100)")
    else:
        units["Ta"] = "K"
        print("  Auto-detected Ta unit: K (median >= 100)")

    # Pressure
    ps = df[col_map["Ps"]]
    if ps.median() < 200:
        units["Ps"] = "kPa"
        print("  Auto-detected Ps unit: kPa (median < 200)")
    elif ps.median() < 2000:
        units["Ps"] = "hPa"
        print("  Auto-detected Ps unit: hPa (median < 2000)")
    else:
        units["Ps"] = "Pa"
        print("  Auto-detected Ps unit: Pa (median >= 2000)")

    # Relative humidity
    rh = df[col_map["RH"]]
    if rh.max() <= 1.1:
        units["RH"] = "fraction"
        print("  Auto-detected RH unit: fraction (max <= 1.1)")
    else:
        units["RH"] = "percent"
        print("  Auto-detected RH unit: percent (max > 1.1)")

    # Precipitation — check if already in kg/m²/s (very small) or mm/h
    for var in ["Sf", "Rf"]:
        p = df[col_map[var]]
        pmax = p.max()
        if pmax < 0.1:
            units[var] = "kg/m2/s"
            print(f"  Auto-detected {var} unit: kg/m²/s (max < 0.1)")
        elif pmax < 50:
            units[var] = "mm/h"
            print(f"  Auto-detected {var} unit: mm/h (max < 50)")
        else:
            units[var] = "mm/day"
            print(f"  Auto-detected {var} unit: mm/day (max >= 50)")

    return units


# ---------------------------------------------------------------------------
# Main conversion
# ---------------------------------------------------------------------------

def convert_forcing(
    input_file: str,
    output_file: str,
    col_map: dict | None = None,
    units: dict | None = None,
    auto_detect: bool = True,
    dt_hours: float = 1.0,
) -> dict:
    """
    Convert a CSV meteorological file to FSM2 format.

    Parameters
    ----------
    input_file : str
        Path to input CSV (comma, space, or tab delimited).
    output_file : str
        Path for output FSM2 met file.
    col_map : dict, optional
        Mapping from FSM2 names to input column names.
        Keys: year, month, day, hour, SW, LW, Sf, Rf, Ta, RH, Ua, Ps
    units : dict, optional
        Units for each variable. If None and auto_detect=True, units are guessed.
    auto_detect : bool
        Whether to auto-detect units from data ranges.
    dt_hours : float
        Timestep in hours for the output file.

    Returns
    -------
    dict with keys: n_rows, issues, output_file
    """
    # Read input
    input_path = Path(input_file)
    if input_path.suffix == ".csv":
        df = pd.read_csv(input_file)
    else:
        df = pd.read_csv(input_file, sep=r"\s+", header=None)

    # Default column mapping (assume FSM2-like order if no headers)
    default_map = {
        "year": "year", "month": "month", "day": "day", "hour": "hour",
        "SW": "SW", "LW": "LW", "Sf": "Sf", "Rf": "Rf",
        "Ta": "Ta", "RH": "RH", "Ua": "Ua", "Ps": "Ps",
    }
    if col_map is None:
        if df.columns.dtype == np.int64:
            # No headers — assign positional names
            names = ["year", "month", "day", "hour", "SW", "LW", "Sf", "Rf", "Ta", "RH", "Ua", "Ps"]
            if len(df.columns) >= len(names):
                df.columns = names + [f"extra_{i}" for i in range(len(df.columns) - len(names))]
            else:
                raise ValueError(f"Input has {len(df.columns)} columns, need at least {len(names)}")
        col_map = default_map

    # Validate input columns
    required = list(col_map.values())
    missing = validate_input(df, required)
    if missing:
        raise ValueError(f"Missing columns in input: {missing}")

    # Rename to standard names
    inv_map = {v: k for k, v in col_map.items()}
    df = df.rename(columns=inv_map)

    # Auto-detect or apply units
    if units is None and auto_detect:
        print("Auto-detecting units...")
        units = auto_detect_units(df, {k: k for k in default_map})
    elif units is None:
        units = {"Ta": "K", "Ps": "Pa", "RH": "percent", "Sf": "kg/m2/s", "Rf": "kg/m2/s"}

    # Apply conversions
    df["Ta"] = convert_temperature(df["Ta"], units.get("Ta", "K"))
    df["Ps"] = convert_pressure(df["Ps"], units.get("Ps", "Pa"))
    df["RH"] = convert_humidity(df["RH"], units.get("RH", "percent"))
    df["Sf"] = convert_precip(df["Sf"], units.get("Sf", "kg/m2/s"))
    df["Rf"] = convert_precip(df["Rf"], units.get("Rf", "kg/m2/s"))

    # Enforce physical limits
    df["Ua"] = df["Ua"].clip(lower=0.1)
    df["SW"] = df["SW"].clip(lower=0.0)
    df["RH"] = df["RH"].clip(lower=0.0, upper=100.0)
    df["Sf"] = df["Sf"].clip(lower=0.0)
    df["Rf"] = df["Rf"].clip(lower=0.0)

    # Validate output
    issues = validate_output(df)
    if issues:
        print("WARNING: Output validation issues:")
        for iss in issues:
            print(f"  - {iss}")

    # Write FSM2 format
    out_cols = ["year", "month", "day", "hour", "SW", "LW", "Sf", "Rf", "Ta", "RH", "Ua", "Ps"]
    with open(output_file, "w") as f:
        for _, row in df[out_cols].iterrows():
            f.write(
                f"{int(row['year']):4d}  {int(row['month']):2d}  "
                f"{int(row['day']):2d}  {row['hour']:2.0f}  "
                f"{row['SW']:8.1f}  {row['LW']:8.1f}  "
                f"{row['Sf']:.3e}  {row['Rf']:.3e}  "
                f"{row['Ta']:8.1f}  {row['RH']:8.1f}  "
                f"{row['Ua']:5.1f}  {row['Ps']:.0f}\n"
            )

    result = {
        "n_rows": len(df),
        "issues": issues,
        "output_file": output_file,
        "period": f"{int(df['year'].iloc[0])}-{int(df['month'].iloc[0]):02d} to "
                  f"{int(df['year'].iloc[-1])}-{int(df['month'].iloc[-1]):02d}",
    }
    print(f"Wrote {len(df)} timesteps to {output_file}")
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Convert met forcing to FSM2 format")
    parser.add_argument("input", help="Input CSV file")
    parser.add_argument("output", help="Output FSM2 met file")
    parser.add_argument("--ta-unit", default=None, choices=["C", "K"], help="Temperature unit")
    parser.add_argument("--ps-unit", default=None, choices=["Pa", "hPa", "kPa"], help="Pressure unit")
    parser.add_argument("--rh-unit", default=None, choices=["percent", "fraction"], help="RH unit")
    parser.add_argument("--precip-unit", default=None, choices=["kg/m2/s", "mm/h", "mm/day"], help="Precip unit")
    args = parser.parse_args()

    units = {}
    if args.ta_unit:
        units["Ta"] = args.ta_unit
    if args.ps_unit:
        units["Ps"] = args.ps_unit
    if args.rh_unit:
        units["RH"] = args.rh_unit
    if args.precip_unit:
        units["Sf"] = args.precip_unit
        units["Rf"] = args.precip_unit

    convert_forcing(
        args.input, args.output,
        units=units if units else None,
        auto_detect=not bool(units),
    )


if __name__ == "__main__":
    main()
