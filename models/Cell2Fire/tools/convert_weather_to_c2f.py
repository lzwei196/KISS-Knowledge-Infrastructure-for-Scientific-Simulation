#!/usr/bin/env python3
"""
Convert meteorological data to Cell2Fire Weather.csv format.

Supports two output formats:
  - Scott & Burgan / Kitral: Instance, datetime, WS, WD, FireScenario
  - Canadian FBP: Scenario, datetime, APCP, TMP, RH, WS, WD, FFMC, DMC, DC, ISI, BUI, FWI

Unit conversions applied:
  - Wind speed: m/s -> km/h  (×3.6)
  - Wind direction: math convention -> meteorological (+180 mod 360)
  - Temperature: K -> °C  (-273.15)
  - Relative humidity: fraction -> percent  (×100)
  - Precipitation: m -> mm  (×1000)

Usage:
  python convert_weather_to_c2f.py --input met_data.csv --output Weather.csv \\
      --model S --scenario-name "MyFire" --fire-scenario 2
"""

import argparse
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd


# ── Validation helpers ──────────────────────────────────────────────────────

def validate_inputs(df: pd.DataFrame, model: str) -> list:
    """Validate input meteorological dataframe. Returns list of warnings."""
    warnings = []

    if df.empty:
        raise ValueError("Input dataframe is empty")

    # Check required columns exist based on model
    if model in ("S", "K"):
        required = ["datetime", "ws", "wd"]
    elif model == "C":
        required = ["datetime", "ws", "wd", "tmp", "rh"]
    else:
        raise ValueError(f"Unknown model: {model}. Use S, C, K, or P.")

    missing = [c for c in required if c not in [col.lower() for col in df.columns]]
    if missing:
        raise ValueError(f"Missing required columns: {missing}. Available: {list(df.columns)}")

    return warnings


def validate_outputs(df: pd.DataFrame, model: str) -> list:
    """Validate output weather CSV. Returns list of warnings."""
    warnings = []

    # Wind speed should be in km/h (typical range 0-200)
    if "WS" in df.columns:
        ws_max = df["WS"].max()
        ws_min = df["WS"].min()
        if ws_max > 200:
            warnings.append(f"WARNING: Max wind speed = {ws_max:.1f} km/h — unusually high, check units")
        if ws_min < 0:
            warnings.append(f"WARNING: Negative wind speed found ({ws_min:.1f}) — invalid")
        if ws_max < 5:
            warnings.append(
                f"WARNING: Max wind speed = {ws_max:.1f} km/h — suspiciously low, "
                f"input may already be in km/h or data is calm"
            )

    # Wind direction should be 0-360
    if "WD" in df.columns:
        wd_max = df["WD"].max()
        wd_min = df["WD"].min()
        if wd_max > 360 or wd_min < 0:
            warnings.append(f"WARNING: Wind direction outside 0-360 range ({wd_min:.1f}-{wd_max:.1f})")

    # FBP-specific checks
    if model == "C":
        if "TMP" in df.columns:
            tmp_max = df["TMP"].max()
            if tmp_max > 60:
                warnings.append(f"WARNING: Max temperature = {tmp_max:.1f}°C — may be in Kelvin, need -273.15")
        if "RH" in df.columns:
            rh_max = df["RH"].max()
            if rh_max <= 1.0:
                warnings.append(f"WARNING: Max RH = {rh_max:.2f} — appears to be fraction, need ×100")
            if rh_max > 100:
                warnings.append(f"WARNING: Max RH = {rh_max:.1f}% — exceeds 100%")
        if "FFMC" in df.columns:
            ffmc_max = df["FFMC"].max()
            if ffmc_max > 101:
                warnings.append(f"WARNING: FFMC > 101 ({ffmc_max:.1f}) — invalid range")

    return warnings


# ── Unit conversion ─────────────────────────────────────────────────────────

def convert_ws_ms_to_kmh(ws: pd.Series) -> pd.Series:
    """Convert wind speed from m/s to km/h."""
    return ws * 3.6


def convert_wd_math_to_met(wd: pd.Series) -> pd.Series:
    """Convert wind direction from math (blowing TO) to met (blowing FROM)."""
    return (wd + 180) % 360


def convert_temp_k_to_c(tmp: pd.Series) -> pd.Series:
    """Convert temperature from Kelvin to Celsius."""
    return tmp - 273.15


def convert_rh_frac_to_pct(rh: pd.Series) -> pd.Series:
    """Convert relative humidity from fraction (0-1) to percent (0-100)."""
    return rh * 100


def convert_precip_m_to_mm(precip: pd.Series) -> pd.Series:
    """Convert precipitation from meters to millimeters."""
    return precip * 1000


# ── Auto-detect units ───────────────────────────────────────────────────────

def auto_detect_and_convert(df: pd.DataFrame, model: str) -> tuple:
    """Auto-detect input units and apply necessary conversions.
    Returns (converted_df, list_of_conversions_applied).
    """
    conversions = []
    df = df.copy()

    # Normalize column names to lowercase for detection
    col_map = {c.lower(): c for c in df.columns}

    # Wind speed: if max < 60, likely m/s; if max > 60, likely km/h
    ws_col = col_map.get("ws")
    if ws_col and df[ws_col].max() < 60:
        df[ws_col] = convert_ws_ms_to_kmh(df[ws_col])
        conversions.append("WS: m/s -> km/h (×3.6)")

    # Temperature: if max > 100, likely Kelvin
    tmp_col = col_map.get("tmp")
    if tmp_col and df[tmp_col].max() > 100:
        df[tmp_col] = convert_temp_k_to_c(df[tmp_col])
        conversions.append("TMP: K -> °C (-273.15)")

    # Relative humidity: if max <= 1.0, likely fraction
    rh_col = col_map.get("rh")
    if rh_col and df[rh_col].max() <= 1.0:
        df[rh_col] = convert_rh_frac_to_pct(df[rh_col])
        conversions.append("RH: fraction -> % (×100)")

    # Precipitation: if max < 0.5, likely meters
    precip_col = col_map.get("apcp") or col_map.get("precip") or col_map.get("precipitation")
    if precip_col and df[precip_col].max() < 0.5 and df[precip_col].max() > 0:
        df[precip_col] = convert_precip_m_to_mm(df[precip_col])
        conversions.append("APCP: m -> mm (×1000)")

    return df, conversions


# ── Main conversion ─────────────────────────────────────────────────────────

def convert_weather(
    input_path: str,
    output_path: str,
    model: str = "S",
    scenario_name: str = "Fire",
    fire_scenario: int = 2,
    auto_units: bool = True,
    ws_conversion: str = "none",
    wd_conversion: str = "none",
) -> dict:
    """
    Convert meteorological data to Cell2Fire Weather.csv.

    Parameters
    ----------
    input_path : str
        Path to input CSV with meteorological data.
    output_path : str
        Path to output Weather.csv.
    model : str
        Fire model: S (Scott&Burgan), C (Canadian FBP), K (Kitral).
    scenario_name : str
        Name for the Instance/Scenario column.
    fire_scenario : int
        Fire weather scenario index (1-3, for S&B).
    auto_units : bool
        Auto-detect and convert units.
    ws_conversion : str
        Wind speed conversion: "none", "ms_to_kmh".
    wd_conversion : str
        Wind direction conversion: "none", "math_to_met".

    Returns
    -------
    dict with keys: n_rows, conversions_applied, warnings
    """
    # Read input
    df = pd.read_csv(input_path)

    # Validate inputs
    input_warnings = validate_inputs(df, model)

    # Apply unit conversions
    conversions = []
    if auto_units:
        df, conversions = auto_detect_and_convert(df, model)
    else:
        col_map = {c.lower(): c for c in df.columns}
        if ws_conversion == "ms_to_kmh":
            ws_col = col_map.get("ws")
            if ws_col:
                df[ws_col] = convert_ws_ms_to_kmh(df[ws_col])
                conversions.append("WS: m/s -> km/h")
        if wd_conversion == "math_to_met":
            wd_col = col_map.get("wd")
            if wd_col:
                df[wd_col] = convert_wd_math_to_met(df[wd_col])
                conversions.append("WD: math -> met convention")

    # Build output DataFrame
    col_map = {c.lower(): c for c in df.columns}

    if model in ("S", "K"):
        out = pd.DataFrame()
        out["Instance"] = [scenario_name] * len(df)
        out["datetime"] = df[col_map.get("datetime", "datetime")]
        out["WS"] = df[col_map.get("ws")].round(1)
        out["WD"] = df[col_map.get("wd")].round(1)
        out["FireScenario"] = fire_scenario

    elif model == "C":
        out = pd.DataFrame()
        out["Scenario"] = [scenario_name] * len(df)
        out["datetime"] = df[col_map.get("datetime", "datetime")]
        out["APCP"] = df.get(col_map.get("apcp"), pd.Series([0.0] * len(df))).round(2)
        out["TMP"] = df[col_map.get("tmp")].round(1)
        out["RH"] = df[col_map.get("rh")].round(0).astype(int)
        out["WS"] = df[col_map.get("ws")].round(0).astype(int)
        out["WD"] = df[col_map.get("wd")].round(0).astype(int)
        out["FFMC"] = df.get(col_map.get("ffmc"), pd.Series([85.0] * len(df))).round(1)
        out["DMC"] = df.get(col_map.get("dmc"), pd.Series([25.0] * len(df))).round(0).astype(int)
        out["DC"] = df.get(col_map.get("dc"), pd.Series([200.0] * len(df))).round(0).astype(int)
        out["ISI"] = df.get(col_map.get("isi"), pd.Series([5.0] * len(df))).round(1)
        out["BUI"] = df.get(col_map.get("bui"), pd.Series([40.0] * len(df))).round(0).astype(int)
        out["FWI"] = df.get(col_map.get("fwi"), pd.Series([10.0] * len(df))).round(1)

    # Validate outputs
    output_warnings = validate_outputs(out, model)

    # Write
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    out.to_csv(output_path, index=False)

    all_warnings = input_warnings + output_warnings
    for w in all_warnings:
        print(w, file=sys.stderr)

    return {
        "n_rows": len(out),
        "conversions_applied": conversions,
        "warnings": all_warnings,
        "output_path": output_path,
    }


# ── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Convert weather data to Cell2Fire format")
    parser.add_argument("--input", required=True, help="Input meteorological CSV")
    parser.add_argument("--output", required=True, help="Output Weather.csv path")
    parser.add_argument("--model", default="S", choices=["S", "C", "K", "P"],
                        help="Fire model (S=Scott&Burgan, C=FBP-Canada, K=Kitral)")
    parser.add_argument("--scenario-name", default="Fire", help="Scenario/Instance name")
    parser.add_argument("--fire-scenario", type=int, default=2,
                        help="Fire weather scenario (1-3, S&B only)")
    parser.add_argument("--auto-units", action="store_true", default=True,
                        help="Auto-detect and convert units")
    parser.add_argument("--ws-conversion", default="none",
                        choices=["none", "ms_to_kmh"],
                        help="Explicit wind speed conversion")
    parser.add_argument("--wd-conversion", default="none",
                        choices=["none", "math_to_met"],
                        help="Explicit wind direction conversion")

    args = parser.parse_args()
    result = convert_weather(
        args.input, args.output, args.model,
        args.scenario_name, args.fire_scenario,
        args.auto_units, args.ws_conversion, args.wd_conversion,
    )
    print(f"Wrote {result['n_rows']} rows to {result['output_path']}")
    if result["conversions_applied"]:
        print(f"Conversions: {', '.join(result['conversions_applied'])}")
    if result["warnings"]:
        print(f"Warnings: {len(result['warnings'])}")


if __name__ == "__main__":
    main()
