#!/usr/bin/env python3
"""
convert_meteo_forcing.py — Convert global reanalysis/station data to openAMUNDSEN format.

Supports two input sources:
  - ERA5/MSWX/CMFD gridded reanalysis (NetCDF) → per-station CSV files
  - Raw station CSV (arbitrary units) → openAMUNDSEN-compliant CSV files

CRITICAL unit conversions:
  - Temperature: °C → K  (add 273.15)
  - Precipitation: mm/day → kg m⁻² per timestep (divide by steps_per_day)
  - Precipitation: kg m⁻² s⁻¹ → kg m⁻² per timestep (multiply by dt_seconds)
  - Relative humidity: fraction (0-1) → percent (0-100) (multiply by 100)
  - Shortwave radiation: MJ m⁻² day⁻¹ → W m⁻² (divide by 0.0864)
  - Wind speed: km/h → m/s (divide by 3.6)

Usage:
  python convert_meteo_forcing.py \\
    --input-dir ./raw_meteo/ \\
    --output-dir ./input/meteo/ \\
    --source era5 \\
    --timestep 3h \\
    --temp-unit celsius \\
    --precip-unit mm_per_day \\
    --rh-unit fraction \\
    --sw-unit wm2 \\
    --wind-unit ms

  python convert_meteo_forcing.py \\
    --input-dir ./raw_stations/ \\
    --output-dir ./input/meteo/ \\
    --source station_csv \\
    --timestep h \\
    --temp-unit kelvin
"""

import argparse
import json
import os
import sys

import numpy as np
import pandas as pd


# openAMUNDSEN expected units and valid ranges
EXPECTED_UNITS = {
    "temp": {"unit": "K", "min": 200.0, "max": 330.0},
    "precip": {"unit": "kg m-2", "min": 0.0, "max": 200.0},
    "rel_hum": {"unit": "%", "min": 1.0, "max": 100.0},
    "sw_in": {"unit": "W m-2", "min": 0.0, "max": 1500.0},
    "wind_speed": {"unit": "m s-1", "min": 0.0, "max": 50.0},
}

REQUIRED_VARS = ["temp", "precip", "rel_hum", "sw_in", "wind_speed"]


def validate_inputs(args):
    """Validate input arguments and files exist."""
    errors = []

    if not os.path.isdir(args.input_dir):
        errors.append(f"Input directory not found: {args.input_dir}")

    if args.source not in ("era5", "mswx", "cmfd", "station_csv"):
        errors.append(f"Unknown source: {args.source}. Use: era5, mswx, cmfd, station_csv")

    if args.temp_unit not in ("kelvin", "celsius"):
        errors.append(f"Unknown temp unit: {args.temp_unit}. Use: kelvin, celsius")

    if args.precip_unit not in ("mm_per_day", "mm_per_timestep", "kg_m2_s", "kg_m2"):
        errors.append(f"Unknown precip unit: {args.precip_unit}")

    if args.rh_unit not in ("percent", "fraction"):
        errors.append(f"Unknown RH unit: {args.rh_unit}. Use: percent, fraction")

    if args.sw_unit not in ("wm2", "mj_m2_day", "kj_m2_h"):
        errors.append(f"Unknown SW unit: {args.sw_unit}")

    if args.wind_unit not in ("ms", "kmh"):
        errors.append(f"Unknown wind unit: {args.wind_unit}. Use: ms, kmh")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)

    return True


def get_timestep_seconds(timestep_str):
    """Convert pandas frequency string to seconds."""
    td = pd.tseries.frequencies.to_offset(timestep_str)
    return int(pd.Timedelta(td).total_seconds())


def convert_temperature(values, from_unit):
    """Convert temperature to Kelvin."""
    if from_unit == "celsius":
        return values + 273.15
    return values  # already Kelvin


def convert_precipitation(values, from_unit, timestep_seconds):
    """Convert precipitation to kg m⁻² per timestep."""
    steps_per_day = 86400.0 / timestep_seconds
    if from_unit == "mm_per_day":
        return values / steps_per_day
    elif from_unit == "kg_m2_s":
        return values * timestep_seconds
    elif from_unit == "mm_per_timestep":
        return values  # mm per timestep == kg m⁻² per timestep
    return values  # already kg_m2 per timestep


def convert_relative_humidity(values, from_unit):
    """Convert relative humidity to percent (0-100)."""
    if from_unit == "fraction":
        return values * 100.0
    return values  # already percent


def convert_shortwave(values, from_unit, timestep_seconds):
    """Convert shortwave radiation to W m⁻²."""
    if from_unit == "mj_m2_day":
        return values / 0.0864  # MJ m⁻² day⁻¹ → W m⁻²
    elif from_unit == "kj_m2_h":
        return values / 3.6  # kJ m⁻² h⁻¹ → W m⁻²
    return values  # already W m⁻²


def convert_wind_speed(values, from_unit):
    """Convert wind speed to m s⁻¹."""
    if from_unit == "kmh":
        return values / 3.6
    return values  # already m/s


def process_station_csv(input_file, args, timestep_seconds):
    """Process a single station CSV file and apply unit conversions."""
    df = pd.read_csv(input_file, parse_dates=["date"], index_col="date")

    # Rename columns if needed (common aliases)
    column_map = {
        "temperature": "temp",
        "air_temperature": "temp",
        "tas": "temp",
        "precipitation": "precip",
        "pr": "precip",
        "relative_humidity": "rel_hum",
        "hurs": "rel_hum",
        "shortwave": "sw_in",
        "rsds": "sw_in",
        "global_radiation": "sw_in",
        "wind": "wind_speed",
        "wss": "wind_speed",
    }
    df = df.rename(columns={k: v for k, v in column_map.items() if k in df.columns})

    # Check required variables
    missing = [v for v in REQUIRED_VARS if v not in df.columns]
    if missing:
        print(f"WARNING: Missing variables in {input_file}: {missing}", file=sys.stderr)

    # Apply unit conversions
    if "temp" in df.columns:
        df["temp"] = convert_temperature(df["temp"].values, args.temp_unit)

    if "precip" in df.columns:
        df["precip"] = convert_precipitation(df["precip"].values, args.precip_unit, timestep_seconds)

    if "rel_hum" in df.columns:
        df["rel_hum"] = convert_relative_humidity(df["rel_hum"].values, args.rh_unit)

    if "sw_in" in df.columns:
        df["sw_in"] = convert_shortwave(df["sw_in"].values, args.sw_unit, timestep_seconds)

    if "wind_speed" in df.columns:
        df["wind_speed"] = convert_wind_speed(df["wind_speed"].values, args.wind_unit)

    return df


def process_era5_netcdf(input_file, station_id, args, timestep_seconds):
    """Extract station time series from ERA5/MSWX/CMFD gridded NetCDF."""
    try:
        import xarray as xr
    except ImportError:
        print(json.dumps({"status": "error", "errors": ["xarray required for NetCDF processing"]}),
              file=sys.stderr)
        sys.exit(1)

    ds = xr.open_dataset(input_file)

    # Common ERA5/CMFD variable name mappings
    era5_map = {
        "t2m": "temp", "2m_temperature": "temp", "tas": "temp",
        "tp": "precip", "total_precipitation": "precip", "pr": "precip",
        "r": "rel_hum", "relative_humidity": "rel_hum", "hurs": "rel_hum",
        "ssrd": "sw_in", "surface_solar_radiation_downwards": "sw_in", "rsds": "sw_in",
        "u10": "wind_u", "v10": "wind_v", "wss": "wind_speed",
    }

    df = pd.DataFrame(index=pd.DatetimeIndex(ds.time.values, name="date"))

    for src_name, tgt_name in era5_map.items():
        if src_name in ds:
            df[tgt_name] = ds[src_name].values.flatten()[:len(df)]

    # Compute wind speed from components if needed
    if "wind_speed" not in df.columns and "wind_u" in df.columns and "wind_v" in df.columns:
        df["wind_speed"] = np.sqrt(df["wind_u"] ** 2 + df["wind_v"] ** 2)
        df = df.drop(columns=["wind_u", "wind_v"])

    # Apply conversions
    if "temp" in df.columns:
        df["temp"] = convert_temperature(df["temp"].values, args.temp_unit)
    if "precip" in df.columns:
        df["precip"] = convert_precipitation(df["precip"].values, args.precip_unit, timestep_seconds)
    if "rel_hum" in df.columns:
        df["rel_hum"] = convert_relative_humidity(df["rel_hum"].values, args.rh_unit)
    if "sw_in" in df.columns:
        df["sw_in"] = convert_shortwave(df["sw_in"].values, args.sw_unit, timestep_seconds)
    if "wind_speed" in df.columns:
        df["wind_speed"] = convert_wind_speed(df["wind_speed"].values, args.wind_unit)

    ds.close()
    return df


def validate_outputs(output_dir, stations):
    """Validate converted output files against expected ranges."""
    warnings = []
    errors = []

    for station_id in stations:
        csv_path = os.path.join(output_dir, f"{station_id}.csv")
        if not os.path.exists(csv_path):
            errors.append(f"Output file missing: {csv_path}")
            continue

        df = pd.read_csv(csv_path, parse_dates=["date"])

        for var, spec in EXPECTED_UNITS.items():
            if var not in df.columns:
                continue

            vals = df[var].dropna()
            if len(vals) == 0:
                warnings.append(f"{station_id}: {var} is all NaN")
                continue

            vmin, vmax = vals.min(), vals.max()

            if vmin < spec["min"]:
                warnings.append(
                    f"{station_id}: {var} min={vmin:.2f} below expected {spec['min']} {spec['unit']}"
                )

            if spec["max"] is not None and vmax > spec["max"]:
                warnings.append(
                    f"{station_id}: {var} max={vmax:.2f} above expected {spec['max']} {spec['unit']}"
                )

            # Specific heuristic checks
            if var == "temp" and vmax < 200:
                errors.append(
                    f"{station_id}: temp max={vmax:.1f} — likely Celsius, not Kelvin! Add 273.15"
                )
            if var == "rel_hum" and vmax <= 1.0:
                errors.append(
                    f"{station_id}: rel_hum max={vmax:.2f} — likely fraction, not percent! Multiply by 100"
                )

    result = {
        "status": "error" if errors else ("warning" if warnings else "success"),
        "stations_processed": len(stations),
        "errors": errors,
        "warnings": warnings,
    }
    return result


def process(args):
    """Main processing: convert all input data to openAMUNDSEN format."""
    os.makedirs(args.output_dir, exist_ok=True)

    timestep_seconds = get_timestep_seconds(args.timestep)
    print(f"Timestep: {args.timestep} = {timestep_seconds} seconds", file=sys.stderr)

    stations = []

    if args.source == "station_csv":
        # Process individual station CSV files
        csv_files = sorted([f for f in os.listdir(args.input_dir)
                           if f.endswith(".csv") and f != "stations.csv"])

        for csv_file in csv_files:
            station_id = os.path.splitext(csv_file)[0]
            stations.append(station_id)

            input_path = os.path.join(args.input_dir, csv_file)
            print(f"Processing station: {station_id}", file=sys.stderr)

            df = process_station_csv(input_path, args, timestep_seconds)

            output_path = os.path.join(args.output_dir, f"{station_id}.csv")
            df.to_csv(output_path, index=True, date_format="%Y-%m-%d %H:%M")
            print(f"  Written: {output_path}", file=sys.stderr)

        # Copy or create stations.csv metadata
        stations_src = os.path.join(args.input_dir, "stations.csv")
        stations_dst = os.path.join(args.output_dir, "stations.csv")
        if os.path.exists(stations_src):
            import shutil
            shutil.copy2(stations_src, stations_dst)

    else:
        # Process gridded reanalysis NetCDF
        nc_files = sorted([f for f in os.listdir(args.input_dir)
                          if f.endswith(".nc") or f.endswith(".nc4")])

        for nc_file in nc_files:
            station_id = os.path.splitext(nc_file)[0]
            stations.append(station_id)

            input_path = os.path.join(args.input_dir, nc_file)
            print(f"Processing: {nc_file}", file=sys.stderr)

            df = process_era5_netcdf(input_path, station_id, args, timestep_seconds)

            output_path = os.path.join(args.output_dir, f"{station_id}.csv")
            df.to_csv(output_path, index=True, date_format="%Y-%m-%d %H:%M")

    # Validate outputs
    result = validate_outputs(args.output_dir, stations)
    print(json.dumps(result, indent=2))
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Convert meteorological data to openAMUNDSEN format"
    )
    parser.add_argument("--input-dir", required=True, help="Input data directory")
    parser.add_argument("--output-dir", required=True, help="Output directory for converted files")
    parser.add_argument("--source", required=True,
                        choices=["era5", "mswx", "cmfd", "station_csv"],
                        help="Data source type")
    parser.add_argument("--timestep", default="h", help="Model timestep (pandas freq, e.g. 'h', '3h')")
    parser.add_argument("--temp-unit", default="celsius",
                        choices=["kelvin", "celsius"],
                        help="Input temperature unit")
    parser.add_argument("--precip-unit", default="mm_per_day",
                        choices=["mm_per_day", "mm_per_timestep", "kg_m2_s", "kg_m2"],
                        help="Input precipitation unit")
    parser.add_argument("--rh-unit", default="percent",
                        choices=["percent", "fraction"],
                        help="Input relative humidity unit")
    parser.add_argument("--sw-unit", default="wm2",
                        choices=["wm2", "mj_m2_day", "kj_m2_h"],
                        help="Input shortwave radiation unit")
    parser.add_argument("--wind-unit", default="ms",
                        choices=["ms", "kmh"],
                        help="Input wind speed unit")

    args = parser.parse_args()
    validate_inputs(args)
    process(args)


if __name__ == "__main__":
    main()
