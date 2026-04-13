#!/usr/bin/env python3
"""convert_weather_to_dwf.py — Convert global meteorological data to Daisy .dwf format.

Converts CSV forcing data (e.g., from CMFD, ERA5, MSWX, or custom stations) into the
Daisy Weather File (.dwf) format. Handles unit conversions for radiation, temperature,
precipitation, and humidity.

Usage:
    python convert_weather_to_dwf.py \\
        --input forcing.csv \\
        --output my-site.dwf \\
        --station "MySite" \\
        --lat 55.67 --lon 12.30 --elev 30 \\
        --rad-unit "MJ/m2/d" \\
        --temp-unit "degC" \\
        --precip-unit "mm/d"
"""

import argparse
import csv
import sys
import os
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def validate_inputs(df, config):
    """Validate input CSV structure and value ranges."""
    errors = []

    required_cols = config.get("required_columns", ["date", "temp", "rad", "precip"])
    for col in required_cols:
        mapped = config.get("col_map", {}).get(col, col)
        if mapped not in df.columns:
            errors.append(f"Missing required column: '{mapped}' (expected for '{col}')")

    if errors:
        raise ValueError("Input validation failed:\n  " + "\n  ".join(errors))

    # Check for NaN in critical columns
    for col in required_cols:
        mapped = config.get("col_map", {}).get(col, col)
        if mapped in df.columns:
            nan_count = df[mapped].isna().sum()
            if nan_count > 0:
                print(f"WARNING: {nan_count} NaN values in column '{mapped}'")

    return True


def validate_outputs(station_meta, data):
    """Validate converted DWF data for physical plausibility."""
    warnings = []

    # Temperature checks
    if "AirTemp" in data.columns:
        tmin, tmax = data["AirTemp"].min(), data["AirTemp"].max()
        if tmin < -60:
            warnings.append(f"AirTemp min={tmin:.1f} °C — suspiciously low, check K→°C conversion")
        if tmax > 60:
            warnings.append(f"AirTemp max={tmax:.1f} °C — suspiciously high, check K→°C conversion")
        if tmin > 100:
            warnings.append(f"AirTemp min={tmin:.1f} °C — likely still in Kelvin!")

    # Radiation checks
    if "GlobRad" in data.columns:
        rmin, rmax = data["GlobRad"].min(), data["GlobRad"].max()
        if rmin < 0:
            warnings.append(f"GlobRad min={rmin:.1f} W/m² — negative values clipped to 0")
            data["GlobRad"] = data["GlobRad"].clip(lower=0)
        if rmax > 500:
            warnings.append(f"GlobRad max={rmax:.1f} W/m² — unusually high for daily mean")
        if rmax > 1500:
            warnings.append(f"GlobRad max={rmax:.1f} W/m² — likely in MJ/m²/d, not W/m²!")

    # Precipitation checks
    if "Precip" in data.columns:
        pmin, pmax = data["Precip"].min(), data["Precip"].max()
        if pmin < 0:
            warnings.append(f"Precip min={pmin:.1f} mm/d — negative values clipped to 0")
            data["Precip"] = data["Precip"].clip(lower=0)
        if pmax > 500:
            warnings.append(f"Precip max={pmax:.1f} mm/d — extreme; check units")

    for w in warnings:
        print(f"WARNING: {w}")

    return len([w for w in warnings if "likely" in w.lower()]) == 0


# ---------------------------------------------------------------------------
# Unit conversion functions
# ---------------------------------------------------------------------------

def convert_radiation(values, from_unit):
    """Convert radiation to W/m^2 (daily mean).

    Daisy expects GlobRad in W/m^2 as daily average.
    Common source units:
      - MJ/m2/d: divide by 0.0864 (= multiply by 11.574)
      - kJ/m2/d: divide by 86.4
      - W/m2:    identity
    """
    from_unit = from_unit.lower().replace(" ", "")
    if from_unit in ("w/m2", "w/m^2", "wm-2"):
        return values
    elif from_unit in ("mj/m2/d", "mj/m^2/d", "mjm-2d-1"):
        return values / 0.0864
    elif from_unit in ("kj/m2/d", "kj/m^2/d", "kjm-2d-1"):
        return values / 86.4
    elif from_unit in ("j/m2/d", "j/m^2/d"):
        return values / 86400.0
    else:
        raise ValueError(f"Unknown radiation unit: {from_unit}. "
                         f"Expected: W/m2, MJ/m2/d, kJ/m2/d, J/m2/d")


def convert_temperature(values, from_unit):
    """Convert temperature to degrees Celsius.

    Daisy expects AirTemp in dgC (°C).
    """
    from_unit = from_unit.lower().replace(" ", "")
    if from_unit in ("degc", "dgc", "°c", "celsius", "c"):
        return values
    elif from_unit in ("k", "kelvin"):
        return values - 273.15
    elif from_unit in ("degf", "°f", "fahrenheit", "f"):
        return (values - 32.0) * 5.0 / 9.0
    else:
        raise ValueError(f"Unknown temperature unit: {from_unit}. "
                         f"Expected: degC, K, degF")


def convert_precipitation(values, from_unit):
    """Convert precipitation to mm/d.

    Daisy expects Precip in mm/d.
    Common source units:
      - mm/d:     identity
      - mm/3h:    multiply by 8 (CMFD 3-hourly accumulated)
      - mm/h:     multiply by 24
      - kg/m2/s:  multiply by 86400
      - m/d:      multiply by 1000
    """
    from_unit = from_unit.lower().replace(" ", "")
    if from_unit in ("mm/d", "mm/day", "mmday-1", "mmd-1"):
        return values
    elif from_unit in ("mm/3h", "mm/3hr"):
        return values * 8.0
    elif from_unit in ("mm/h", "mm/hr", "mmh-1"):
        return values * 24.0
    elif from_unit in ("kg/m2/s", "kgm-2s-1"):
        return values * 86400.0
    elif from_unit in ("m/d", "m/day"):
        return values * 1000.0
    else:
        raise ValueError(f"Unknown precipitation unit: {from_unit}. "
                         f"Expected: mm/d, mm/3h, mm/h, kg/m2/s, m/d")


def convert_humidity(values, from_unit):
    """Convert humidity to % (0-100).

    Daisy expects RelHum as percentage (0-100).
    """
    from_unit = from_unit.lower().replace(" ", "")
    if from_unit in ("%", "percent"):
        return values
    elif from_unit in ("fraction", "0-1"):
        return values * 100.0
    else:
        raise ValueError(f"Unknown humidity unit: {from_unit}. Expected: %, fraction")


# ---------------------------------------------------------------------------
# DWF writer
# ---------------------------------------------------------------------------

def write_dwf(filepath, station_meta, data, columns_config):
    """Write a Daisy Weather File (.dwf).

    Parameters
    ----------
    filepath : str
        Output .dwf file path.
    station_meta : dict
        Station metadata: Station, Elevation, Longitude, Latitude, TimeZone, etc.
    data : pd.DataFrame
        Must have Year, Month, Day columns plus weather variables.
    columns_config : list of dict
        Each entry: {"name": "GlobRad", "unit": "W/m^2"}
    """
    with open(filepath, "w") as f:
        # Header
        f.write(f"dwf-0.0 -- Weather data for {station_meta.get('Station', 'Unknown')}.\n\n")

        # Station metadata
        for key in ["Station", "Elevation", "Longitude", "Latitude", "TimeZone",
                     "Surface", "ScreenHeight"]:
            if key in station_meta:
                f.write(f"{key}: {station_meta[key]}\n")

        f.write("\n")

        # Date range
        f.write(f"Begin: {data['Year'].iloc[0]}-{data['Month'].iloc[0]:02d}-{data['Day'].iloc[0]:02d}\n")
        f.write(f"End:   {data['Year'].iloc[-1]}-{data['Month'].iloc[-1]:02d}-{data['Day'].iloc[-1]:02d}\n")
        f.write(f"Timestep: {station_meta.get('Timestep', '24 hours')}\n\n")

        # Deposition values (defaults)
        for key in ["NH4WetDep", "NH4DryDep", "NO3WetDep", "NO3DryDep"]:
            if key in station_meta:
                f.write(f"{key}: {station_meta[key]}\n")

        # Temperature averages
        for key in ["TAverage", "TAmplitude", "MaxTDay"]:
            if key in station_meta:
                f.write(f"{key}: {station_meta[key]}\n")

        f.write("\n")

        # Data separator
        f.write("-" * 78 + "\n")

        # Column names
        col_names = ["Year", "Month", "Day"]
        col_units = ["year", "month", "mday"]
        for cc in columns_config:
            col_names.append(cc["name"])
            col_units.append(cc["unit"])

        f.write("\t".join(col_names) + "\n")
        f.write("\t".join(col_units) + "\n")

        # Data rows
        for _, row in data.iterrows():
            parts = [f"{int(row['Year'])}", f"{int(row['Month']):3d}",
                     f"{int(row['Day']):3d}"]
            for cc in columns_config:
                val = row[cc["name"]]
                parts.append(f"{val:8.1f}")
            f.write("  ".join(parts) + "\n")

    print(f"Wrote {len(data)} records to {filepath}")


# ---------------------------------------------------------------------------
# Main conversion pipeline
# ---------------------------------------------------------------------------

def process(input_path, output_path, config):
    """Main conversion: CSV → DWF.

    Parameters
    ----------
    input_path : str
        Path to input CSV.
    output_path : str
        Path to output .dwf file.
    config : dict
        Configuration with column mappings, unit specifications, station metadata.
    """
    # Step 1: Read input
    df = pd.read_csv(input_path, parse_dates=config.get("date_parse", False))

    # Step 2: Validate inputs
    validate_inputs(df, config)

    # Step 3: Map columns and apply unit conversions
    col_map = config.get("col_map", {})

    # Parse dates
    date_col = col_map.get("date", "date")
    if date_col in df.columns:
        dates = pd.to_datetime(df[date_col])
        df["Year"] = dates.dt.year
        df["Month"] = dates.dt.month
        df["Day"] = dates.dt.day
    else:
        # Assume Year, Month, Day columns already exist
        for c in ["Year", "Month", "Day"]:
            mc = col_map.get(c.lower(), c)
            if mc != c and mc in df.columns:
                df[c] = df[mc]

    # Convert radiation
    rad_col = col_map.get("rad", "rad")
    if rad_col in df.columns:
        df["GlobRad"] = convert_radiation(
            df[rad_col].values, config.get("rad_unit", "W/m2"))

    # Convert temperature
    temp_col = col_map.get("temp", "temp")
    if temp_col in df.columns:
        df["AirTemp"] = convert_temperature(
            df[temp_col].values, config.get("temp_unit", "degC"))

    # Convert precipitation
    precip_col = col_map.get("precip", "precip")
    if precip_col in df.columns:
        df["Precip"] = convert_precipitation(
            df[precip_col].values, config.get("precip_unit", "mm/d"))

    # Convert reference evapotranspiration (optional, already mm/d typically)
    refevap_col = col_map.get("refevap", "refevap")
    if refevap_col in df.columns:
        df["RefEvap"] = df[refevap_col].values

    # Step 4: Build station metadata
    station_meta = {
        "Station": config.get("station", "Unknown"),
        "Elevation": f"{config.get('elev', 0)} m",
        "Longitude": f"{config.get('lon', 0)} dgEast",
        "Latitude": f"{config.get('lat', 0)} dgNorth",
        "TimeZone": f"{int(config.get('lon', 0) // 15) * 15} dgEast",
        "Surface": "reference",
        "ScreenHeight": "2.0 m",
        "Timestep": "24 hours",
    }

    # Compute temperature statistics if available
    if "AirTemp" in df.columns:
        monthly_means = df.groupby("Month")["AirTemp"].mean()
        station_meta["TAverage"] = f"{df['AirTemp'].mean():.1f} dgC"
        station_meta["TAmplitude"] = f"{(monthly_means.max() - monthly_means.min()) / 2:.1f} dgC"
        warmest_doy = df.loc[df.groupby(
            df["Year"])["AirTemp"].transform("max") == df["AirTemp"]].index
        station_meta["MaxTDay"] = f"209 yday"  # default Northern Hemisphere

    # Default N deposition (typical temperate values)
    station_meta.setdefault("NH4WetDep", "0.9 ppm")
    station_meta.setdefault("NH4DryDep", "2.2 kgN/ha/year")
    station_meta.setdefault("NO3WetDep", "0.6 ppm")
    station_meta.setdefault("NO3DryDep", "1.1 kgN/ha/year")

    # Step 5: Define output columns
    output_columns = []
    if "GlobRad" in df.columns:
        output_columns.append({"name": "GlobRad", "unit": "W/m^2"})
    if "AirTemp" in df.columns:
        output_columns.append({"name": "AirTemp", "unit": "dgC"})
    if "Precip" in df.columns:
        output_columns.append({"name": "Precip", "unit": "mm/d"})
    if "RefEvap" in df.columns:
        output_columns.append({"name": "RefEvap", "unit": "mm/d"})

    # Step 6: Validate outputs
    validate_outputs(station_meta, df)

    # Step 7: Write DWF
    write_dwf(output_path, station_meta, df, output_columns)

    return output_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Convert meteorological CSV to Daisy .dwf weather file")
    parser.add_argument("--input", required=True, help="Input CSV file path")
    parser.add_argument("--output", required=True, help="Output .dwf file path")
    parser.add_argument("--station", default="Unknown", help="Station name")
    parser.add_argument("--lat", type=float, required=True, help="Latitude (degrees N)")
    parser.add_argument("--lon", type=float, required=True, help="Longitude (degrees E)")
    parser.add_argument("--elev", type=float, default=0, help="Elevation (m)")
    parser.add_argument("--rad-unit", default="W/m2",
                        help="Input radiation unit: W/m2, MJ/m2/d, kJ/m2/d")
    parser.add_argument("--temp-unit", default="degC",
                        help="Input temperature unit: degC, K, degF")
    parser.add_argument("--precip-unit", default="mm/d",
                        help="Input precipitation unit: mm/d, mm/3h, mm/h, kg/m2/s")
    parser.add_argument("--date-col", default="date", help="Date column name in CSV")
    parser.add_argument("--rad-col", default="rad", help="Radiation column name")
    parser.add_argument("--temp-col", default="temp", help="Temperature column name")
    parser.add_argument("--precip-col", default="precip", help="Precipitation column name")

    args = parser.parse_args()

    config = {
        "station": args.station,
        "lat": args.lat,
        "lon": args.lon,
        "elev": args.elev,
        "rad_unit": args.rad_unit,
        "temp_unit": args.temp_unit,
        "precip_unit": args.precip_unit,
        "col_map": {
            "date": args.date_col,
            "rad": args.rad_col,
            "temp": args.temp_col,
            "precip": args.precip_col,
        },
        "required_columns": ["date", "temp", "rad", "precip"],
    }

    process(args.input, args.output, config)


if __name__ == "__main__":
    main()
