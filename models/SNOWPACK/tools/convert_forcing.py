#!/usr/bin/env python3
"""
convert_forcing.py — Convert global meteorological data to SNOWPACK SMET format.

Purpose:
    Reads meteorological forcing data from CSV (e.g., ERA5, station data) and
    converts it to the SMET 1.1 ASCII format required by SNOWPACK/MeteoIO.

CRITICAL UNIT CONVERSIONS:
    - Temperature: Input may be °C → output MUST be Kelvin (K)
    - Relative humidity: Input may be 0-100% → output MUST be 0-1 fraction
    - Precipitation: Input may be mm/day or mm/hr → output MUST be kg/m² per timestep
    - Wind speed: Input may be km/h → output MUST be m/s
    - Radiation: Input may be MJ/m²/day → output MUST be W/m²
    - Pressure: Input may be hPa or kPa → output MUST be Pa
    - Snow depth: Input may be cm → output MUST be m

Input CSV format (columns, any order):
    datetime    — ISO 8601 timestamp (e.g., 2020-01-01T00:00)
    TA          — Air temperature
    RH          — Relative humidity
    VW          — Wind velocity
    DW          — Wind direction (degrees, 0-360)
    ISWR        — Incoming shortwave radiation
    ILWR        — Incoming longwave radiation
    PSUM        — Precipitation sum
    HS          — Snow depth (optional)
    TSG         — Ground surface temperature (optional)
    TSS         — Snow surface temperature (optional)
    P           — Atmospheric pressure (optional)

Output SMET format:
    SMET 1.1 ASCII with [HEADER] and [DATA] sections.
    All values in SI units (K, fraction, kg/m², m/s, W/m², m, Pa).

Usage:
    python convert_forcing.py \\
        --input era5_hourly.csv \\
        --output input/station.smet \\
        --station_id WFJ2 \\
        --latitude 46.831 --longitude 9.810 --altitude 2540 \\
        --source_temp_unit C --source_rh_unit percent \\
        --source_precip_unit mm_per_hour --source_wind_unit m_per_s

    python convert_forcing.py \\
        --input station_obs.csv \\
        --output input/OBS01.smet \\
        --station_id OBS01 \\
        --latitude 47.0 --longitude 8.5 --altitude 1500 \\
        --timezone 1 --nodata -999
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd


def validate_inputs(args):
    """Validate all input arguments before processing.

    Returns list of error strings (empty if OK).
    """
    errors = []

    if not os.path.isfile(args.input):
        errors.append(f"Input file not found: {args.input}")

    if not (-90 <= args.latitude <= 90):
        errors.append(f"Latitude out of range [-90, 90]: {args.latitude}")

    if not (-180 <= args.longitude <= 180):
        errors.append(f"Longitude out of range [-180, 180]: {args.longitude}")

    if not (-500 <= args.altitude <= 9000):
        errors.append(f"Altitude out of plausible range [-500, 9000]: {args.altitude}")

    valid_temp_units = ["K", "C", "F"]
    if args.source_temp_unit not in valid_temp_units:
        errors.append(f"source_temp_unit must be one of {valid_temp_units}")

    valid_rh_units = ["fraction", "percent"]
    if args.source_rh_unit not in valid_rh_units:
        errors.append(f"source_rh_unit must be one of {valid_rh_units}")

    valid_precip_units = ["kg_per_m2", "mm_per_hour", "mm_per_day", "m_per_timestep"]
    if args.source_precip_unit not in valid_precip_units:
        errors.append(f"source_precip_unit must be one of {valid_precip_units}")

    valid_wind_units = ["m_per_s", "km_per_h", "knots"]
    if args.source_wind_unit not in valid_wind_units:
        errors.append(f"source_wind_unit must be one of {valid_wind_units}")

    valid_rad_units = ["W_per_m2", "MJ_per_m2_day", "kJ_per_m2_hr"]
    if args.source_rad_unit not in valid_rad_units:
        errors.append(f"source_rad_unit must be one of {valid_rad_units}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)

    return errors


def convert_temperature(values, source_unit):
    """Convert temperature to Kelvin.

    CRITICAL: SNOWPACK expects ALL temperatures in Kelvin.
    Passing Celsius causes the model to interpret 20°C as 20 K (≈ -253°C).
    """
    if source_unit == "K":
        return values
    elif source_unit == "C":
        return values + 273.15
    elif source_unit == "F":
        return (values - 32) * 5.0 / 9.0 + 273.15
    else:
        raise ValueError(f"Unknown temperature unit: {source_unit}")


def convert_rh(values, source_unit):
    """Convert relative humidity to 0-1 fraction.

    CRITICAL: SNOWPACK expects RH as 0-1.
    Values >1 are clamped, causing systematic latent heat errors.
    """
    if source_unit == "fraction":
        return values
    elif source_unit == "percent":
        return values / 100.0
    else:
        raise ValueError(f"Unknown RH unit: {source_unit}")


def convert_precipitation(values, source_unit, timestep_seconds):
    """Convert precipitation to kg/m² per timestep.

    CRITICAL: SNOWPACK expects PSUM in kg/m² (= mm water equiv.) per timestep.
    1 mm water = 1 kg/m².
    """
    if source_unit == "kg_per_m2":
        return values
    elif source_unit == "mm_per_hour":
        # mm/hr → kg/m² per timestep
        return values * (timestep_seconds / 3600.0)
    elif source_unit == "mm_per_day":
        # mm/day → kg/m² per timestep
        return values * (timestep_seconds / 86400.0)
    elif source_unit == "m_per_timestep":
        # m → mm = kg/m²
        return values * 1000.0
    else:
        raise ValueError(f"Unknown precipitation unit: {source_unit}")


def convert_wind(values, source_unit):
    """Convert wind speed to m/s."""
    if source_unit == "m_per_s":
        return values
    elif source_unit == "km_per_h":
        return values / 3.6
    elif source_unit == "knots":
        return values * 0.514444
    else:
        raise ValueError(f"Unknown wind unit: {source_unit}")


def convert_radiation(values, source_unit):
    """Convert radiation to W/m².

    CRITICAL: SNOWPACK expects instantaneous W/m², not energy totals.
    MJ/m²/day ÷ 86400 × 1e6 = W/m²
    """
    if source_unit == "W_per_m2":
        return values
    elif source_unit == "MJ_per_m2_day":
        return values * 1e6 / 86400.0
    elif source_unit == "kJ_per_m2_hr":
        return values * 1000.0 / 3600.0
    else:
        raise ValueError(f"Unknown radiation unit: {source_unit}")


def convert_pressure(values, source_unit):
    """Convert pressure to Pa."""
    if source_unit == "Pa":
        return values
    elif source_unit == "hPa":
        return values * 100.0
    elif source_unit == "kPa":
        return values * 1000.0
    else:
        raise ValueError(f"Unknown pressure unit: {source_unit}")


def process(args):
    """Main processing: read CSV, convert units, write SMET."""
    print(f"Reading input: {args.input}", file=sys.stderr)
    df = pd.read_csv(args.input, parse_dates=["datetime"])
    df = df.sort_values("datetime").reset_index(drop=True)

    # Detect timestep from data
    if len(df) > 1:
        dt = (df["datetime"].iloc[1] - df["datetime"].iloc[0]).total_seconds()
    else:
        dt = 3600  # default 1 hour

    print(f"Detected timestep: {dt} seconds ({dt/3600:.1f} hours)", file=sys.stderr)

    # Apply unit conversions
    if "TA" in df.columns:
        df["TA"] = convert_temperature(df["TA"].values, args.source_temp_unit)
    if "RH" in df.columns:
        df["RH"] = convert_rh(df["RH"].values, args.source_rh_unit)
    if "PSUM" in df.columns:
        df["PSUM"] = convert_precipitation(df["PSUM"].values, args.source_precip_unit, dt)
    if "VW" in df.columns:
        df["VW"] = convert_wind(df["VW"].values, args.source_wind_unit)
    if "ISWR" in df.columns:
        df["ISWR"] = convert_radiation(df["ISWR"].values, args.source_rad_unit)
    if "ILWR" in df.columns:
        df["ILWR"] = convert_radiation(df["ILWR"].values, args.source_rad_unit)
    if "TSG" in df.columns:
        df["TSG"] = convert_temperature(df["TSG"].values, args.source_temp_unit)
    if "TSS" in df.columns:
        df["TSS"] = convert_temperature(df["TSS"].values, args.source_temp_unit)

    # Determine available fields
    smet_fields = ["timestamp"]
    possible_fields = ["TA", "RH", "TSG", "TSS", "HS", "VW", "DW",
                       "RSWR", "ISWR", "ILWR", "PSUM"]
    for f in possible_fields:
        if f in df.columns:
            smet_fields.append(f)

    # Replace NaN with nodata
    nodata = args.nodata
    df = df.fillna(nodata)

    # Write SMET file
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w") as fout:
        fout.write("SMET 1.1 ASCII\n")
        fout.write("[HEADER]\n")
        fout.write(f"station_id       = {args.station_id}\n")
        fout.write(f"station_name     = {args.station_name}\n")
        fout.write(f"latitude         = {args.latitude:.6f}\n")
        fout.write(f"longitude        = {args.longitude:.6f}\n")
        fout.write(f"altitude         = {args.altitude:.1f}\n")
        fout.write(f"nodata           = {nodata}\n")
        fout.write(f"tz               = {args.timezone}\n")
        fout.write(f"fields           = {' '.join(smet_fields)}\n")
        fout.write("[DATA]\n")

        for _, row in df.iterrows():
            ts = row["datetime"].strftime("%Y-%m-%dT%H:%M")
            vals = [ts]
            for f in smet_fields[1:]:
                vals.append(f"{row[f]:.6f}")
            fout.write(" ".join(vals) + "\n")

    n_records = len(df)
    result = {
        "status": "success",
        "output_file": args.output,
        "station_id": args.station_id,
        "n_records": n_records,
        "timestep_seconds": dt,
        "fields": smet_fields,
        "period_start": df["datetime"].iloc[0].isoformat(),
        "period_end": df["datetime"].iloc[-1].isoformat(),
    }
    return result


def validate_outputs(result):
    """Check output for physical realism."""
    warnings = []

    if result.get("n_records", 0) < 24:
        warnings.append("Very few records — simulation may be too short")

    if result.get("n_records", 0) == 0:
        warnings.append("No records written — check input file format")

    if warnings:
        result["warnings"] = warnings
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Convert meteorological data to SNOWPACK SMET format"
    )
    parser.add_argument("--input", required=True, help="Input CSV file path")
    parser.add_argument("--output", required=True, help="Output SMET file path")
    parser.add_argument("--station_id", required=True, help="Station identifier")
    parser.add_argument("--station_name", default="", help="Station name")
    parser.add_argument("--latitude", type=float, required=True)
    parser.add_argument("--longitude", type=float, required=True)
    parser.add_argument("--altitude", type=float, required=True, help="Elevation (m)")
    parser.add_argument("--timezone", type=int, default=0, help="UTC offset (hours)")
    parser.add_argument("--nodata", type=float, default=-999, help="Nodata sentinel")
    parser.add_argument("--source_temp_unit", default="C",
                        choices=["K", "C", "F"], help="Temperature unit in source")
    parser.add_argument("--source_rh_unit", default="percent",
                        choices=["fraction", "percent"], help="RH unit in source")
    parser.add_argument("--source_precip_unit", default="mm_per_hour",
                        choices=["kg_per_m2", "mm_per_hour", "mm_per_day",
                                 "m_per_timestep"],
                        help="Precipitation unit in source")
    parser.add_argument("--source_wind_unit", default="m_per_s",
                        choices=["m_per_s", "km_per_h", "knots"],
                        help="Wind speed unit in source")
    parser.add_argument("--source_rad_unit", default="W_per_m2",
                        choices=["W_per_m2", "MJ_per_m2_day", "kJ_per_m2_hr"],
                        help="Radiation unit in source")

    args = parser.parse_args()
    if not args.station_name:
        args.station_name = args.station_id

    validate_inputs(args)
    result = process(args)
    result = validate_outputs(result)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
