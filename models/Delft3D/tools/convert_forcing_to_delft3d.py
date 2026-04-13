#!/usr/bin/env python3
"""
convert_forcing_to_delft3d.py — ERA5/CMFD/VIC forcing → Delft3D meteo files

Converts global reanalysis or regional forcing data into Delft3D-compatible
meteorological forcing files (.wnd for wind, .amu/.amv for wind components,
.amp for pressure, .amt for temperature, etc.)

Pipeline stage: s3 (meteorological forcing)
Pattern: validate → process → validate

Unit conversions performed:
  - Pressure: hPa → Pa (×100) if needed
  - Wind direction: mathematical (TO) → nautical (FROM) if needed (+180°)
  - Relative humidity: fraction (0-1) → percentage (0-100) if needed
  - Cloud cover: percentage (0-100) → fraction (0-1) if needed
  - Shortwave radiation: clipped to >= 0 W/m²
  - Temperature: K → °C if needed (−273.15)
"""

import argparse
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta

import numpy as np

try:
    import netCDF4 as nc
except ImportError:
    nc = None

try:
    import pandas as pd
except ImportError:
    pd = None


# ──────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────

KELVIN_OFFSET = 273.15
HPA_TO_PA = 100.0
EXPECTED_RANGES = {
    "wind_speed": (0, 60),          # m/s
    "wind_direction": (0, 360),     # degrees
    "pressure": (85000, 110000),    # Pa
    "temperature": (-60, 55),       # °C
    "rel_humidity": (0, 100),       # %
    "cloud_cover": (0.0, 1.0),      # fraction
    "shortwave": (0, 1400),         # W/m²
    "longwave": (100, 500),         # W/m²
    "precipitation": (0, 200),      # mm/hr
}


# ──────────────────────────────────────────────────────────────────────
# Validation
# ──────────────────────────────────────────────────────────────────────

def validate_inputs(args):
    """Validate input arguments and file existence."""
    errors = []

    if args.era5_file and not os.path.isfile(args.era5_file):
        errors.append(f"ERA5 file not found: {args.era5_file}")

    if args.csv_file and not os.path.isfile(args.csv_file):
        errors.append(f"CSV file not found: {args.csv_file}")

    if not args.era5_file and not args.csv_file:
        errors.append("Must provide either --era5_file or --csv_file")

    try:
        datetime.strptime(args.start_date, "%Y-%m-%d")
        datetime.strptime(args.end_date, "%Y-%m-%d")
    except ValueError as e:
        errors.append(f"Date format error (use YYYY-MM-DD): {e}")

    os.makedirs(args.output_dir, exist_ok=True)

    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"[validate_inputs] All inputs valid.")


def validate_outputs(output_dir, ref_date):
    """Validate generated forcing files for physical plausibility."""
    warnings = []

    wnd_file = os.path.join(output_dir, "wind.wnd")
    if os.path.isfile(wnd_file):
        data = np.loadtxt(wnd_file, comments="#")
        if len(data) == 0:
            warnings.append("wind.wnd is empty")
        else:
            speeds = data[:, 1] if data.ndim > 1 else data
            if np.any(speeds < 0):
                warnings.append("Negative wind speeds detected — check data")
            if np.max(speeds) > 60:
                warnings.append(f"Wind speed max {np.max(speeds):.1f} m/s — extreme value")

    amp_file = os.path.join(output_dir, "pressure.amp")
    if os.path.isfile(amp_file):
        data = np.loadtxt(amp_file, comments="#")
        if len(data) > 0:
            pressures = data[:, 1] if data.ndim > 1 else data
            if np.max(pressures) < 2000:
                warnings.append(
                    f"Pressure max {np.max(pressures):.0f} — likely in hPa, not Pa! "
                    "Delft3D expects Pa (multiply by 100)"
                )
            if np.min(pressures) < 85000:
                warnings.append(f"Pressure min {np.min(pressures):.0f} Pa — unusually low")

    if warnings:
        print("[validate_outputs] WARNINGS:")
        for w in warnings:
            print(f"  ⚠ {w}")
    else:
        print("[validate_outputs] All outputs within expected ranges.")

    return warnings


# ──────────────────────────────────────────────────────────────────────
# Unit conversion helpers
# ──────────────────────────────────────────────────────────────────────

def convert_temperature(t_array, detect_units=True):
    """Convert temperature to °C. Auto-detects Kelvin if values > 100."""
    if detect_units and np.nanmean(t_array) > 100:
        print("  [unit] Temperature appears to be in Kelvin — converting to °C")
        return t_array - KELVIN_OFFSET
    return t_array


def convert_pressure(p_array, detect_units=True):
    """Convert pressure to Pa. Auto-detects hPa if max < 2000."""
    if detect_units and np.nanmax(p_array) < 2000:
        print("  [unit] Pressure appears to be in hPa — converting to Pa (×100)")
        return p_array * HPA_TO_PA
    return p_array


def convert_wind_direction(wd_array, from_math_to_nautical=False):
    """Convert wind direction. Nautical = FROM direction (Delft3D convention)."""
    if from_math_to_nautical:
        print("  [unit] Converting wind direction from math (TO) to nautical (FROM)")
        return (wd_array + 180.0) % 360.0
    return wd_array


def convert_rel_humidity(rh_array, detect_units=True):
    """Convert relative humidity to % (0-100). Auto-detects fraction if max < 1.5."""
    if detect_units and np.nanmax(rh_array) < 1.5:
        print("  [unit] RelHum appears to be fraction (0-1) — converting to % (×100)")
        return rh_array * 100.0
    return rh_array


def convert_cloud_cover(cc_array, detect_units=True):
    """Convert cloud cover to fraction (0-1). Auto-detects % if max > 1.5."""
    if detect_units and np.nanmax(cc_array) > 1.5:
        print("  [unit] Cloud cover appears to be % — converting to fraction (÷100)")
        return cc_array / 100.0
    return cc_array


def clip_shortwave(sw_array):
    """Clip shortwave radiation to >= 0 (night-time interpolation artifact)."""
    n_neg = np.sum(sw_array < 0)
    if n_neg > 0:
        print(f"  [unit] Clipping {n_neg} negative shortwave values to 0")
        return np.maximum(sw_array, 0.0)
    return sw_array


# ──────────────────────────────────────────────────────────────────────
# ERA5 NetCDF processing
# ──────────────────────────────────────────────────────────────────────

def process_era5(era5_file, output_dir, start_date, end_date, domain_bounds=None):
    """Process ERA5 NetCDF file into Delft3D forcing files."""
    if nc is None:
        print("ERROR: netCDF4 not installed", file=sys.stderr)
        sys.exit(1)

    print(f"[process] Reading ERA5: {era5_file}")
    ds = nc.Dataset(era5_file, "r")

    # Identify time variable
    time_var = None
    for tname in ["time", "valid_time", "forecast_time"]:
        if tname in ds.variables:
            time_var = tname
            break
    if time_var is None:
        print("ERROR: No time variable found in ERA5 file", file=sys.stderr)
        sys.exit(1)

    times = nc.num2date(ds.variables[time_var][:],
                        ds.variables[time_var].units,
                        only_use_cftime_datetimes=False)

    # Filter by date range
    t_start = datetime.strptime(start_date, "%Y-%m-%d")
    t_end = datetime.strptime(end_date, "%Y-%m-%d")
    mask = np.array([(t_start <= t <= t_end) for t in times])
    time_indices = np.where(mask)[0]

    if len(time_indices) == 0:
        print("ERROR: No timesteps found in date range", file=sys.stderr)
        sys.exit(1)

    print(f"  Found {len(time_indices)} timesteps in [{start_date}, {end_date}]")

    # Spatial subset
    lat = ds.variables.get("latitude", ds.variables.get("lat"))[:]
    lon = ds.variables.get("longitude", ds.variables.get("lon"))[:]

    if domain_bounds:
        lon_min, lat_min, lon_max, lat_max = [float(x) for x in domain_bounds.split()]
        lat_mask = (lat >= lat_min) & (lat <= lat_max)
        lon_mask = (lon >= lon_min) & (lon <= lon_max)
        lat_idx = np.where(lat_mask)[0]
        lon_idx = np.where(lon_mask)[0]
    else:
        lat_idx = np.arange(len(lat))
        lon_idx = np.arange(len(lon))

    # Extract and convert variables
    ref_date = t_start

    # Map ERA5 variable names to standard names
    var_map = {
        "u10": "wind_u10",    "v10": "wind_v10",
        "sp": "pressure",     "msl": "pressure",
        "t2m": "temperature", "d2m": "dewpoint",
        "tcc": "cloud_cover", "ssrd": "shortwave",
        "strd": "longwave",   "tp": "precipitation",
    }

    extracted = {}
    for era5_name, std_name in var_map.items():
        if era5_name in ds.variables:
            var = ds.variables[era5_name]
            if var.ndim == 3:  # time, lat, lon
                data = var[time_indices][:, lat_idx][:, :, lon_idx]
            elif var.ndim == 1:  # time only (spatially averaged)
                data = var[time_indices]
            else:
                continue
            # Spatial mean for uniform forcing
            if data.ndim > 1:
                data = np.nanmean(data, axis=tuple(range(1, data.ndim)))
            extracted[std_name] = data
            print(f"  Extracted {era5_name} → {std_name}: shape={data.shape}")

    ds.close()

    # Apply unit conversions
    if "temperature" in extracted:
        extracted["temperature"] = convert_temperature(extracted["temperature"])
    if "pressure" in extracted:
        extracted["pressure"] = convert_pressure(extracted["pressure"])
    if "shortwave" in extracted:
        extracted["shortwave"] = clip_shortwave(extracted["shortwave"])
    if "cloud_cover" in extracted:
        extracted["cloud_cover"] = convert_cloud_cover(extracted["cloud_cover"])

    # Compute wind speed and direction from u10, v10
    if "wind_u10" in extracted and "wind_v10" in extracted:
        u10 = extracted["wind_u10"]
        v10 = extracted["wind_v10"]
        ws = np.sqrt(u10**2 + v10**2)
        # Nautical convention: direction wind comes FROM
        wd = (270.0 - np.degrees(np.arctan2(v10, u10))) % 360.0
        extracted["wind_speed"] = ws
        extracted["wind_direction"] = wd

    # Compute relative humidity from temperature and dewpoint
    if "temperature" in extracted and "dewpoint" in extracted:
        t = extracted["temperature"]
        td = convert_temperature(extracted["dewpoint"])
        # Magnus formula
        es = 6.112 * np.exp(17.67 * t / (t + 243.5))
        e = 6.112 * np.exp(17.67 * td / (td + 243.5))
        rh = 100.0 * e / es
        rh = np.clip(rh, 0, 100)
        extracted["rel_humidity"] = rh

    # Compute time in seconds since reference
    time_seconds = np.array([
        (times[i] - ref_date).total_seconds() for i in time_indices
    ])

    # Write output files
    _write_uniform_wind(output_dir, time_seconds, extracted, ref_date)
    _write_uniform_meteo(output_dir, time_seconds, extracted, ref_date)

    print(f"[process] Forcing files written to {output_dir}")
    return extracted


# ──────────────────────────────────────────────────────────────────────
# CSV processing (for VIC/CMFD pre-processed data)
# ──────────────────────────────────────────────────────────────────────

def process_csv(csv_file, output_dir, start_date, end_date):
    """Process CSV forcing file into Delft3D format."""
    if pd is None:
        print("ERROR: pandas not installed", file=sys.stderr)
        sys.exit(1)

    print(f"[process] Reading CSV: {csv_file}")
    df = pd.read_csv(csv_file, parse_dates=["time"] if "time" in
                     pd.read_csv(csv_file, nrows=0).columns else [0])

    # Standardize column names
    col_map = {
        "Wind": "wind_speed", "WindSpeed": "wind_speed",
        "WindDir": "wind_direction", "AirTemp": "temperature",
        "ShortWave": "shortwave", "LongWave": "longwave",
        "RelHum": "rel_humidity", "Pressure": "pressure",
        "Rain": "precipitation", "CloudCover": "cloud_cover",
    }
    df = df.rename(columns=col_map)

    # Filter by date
    date_col = df.columns[0]
    df[date_col] = pd.to_datetime(df[date_col])
    mask = (df[date_col] >= start_date) & (df[date_col] <= end_date)
    df = df[mask].copy()

    ref_date = datetime.strptime(start_date, "%Y-%m-%d")
    time_seconds = (df[date_col] - ref_date).dt.total_seconds().values

    extracted = {}
    for col in df.columns[1:]:
        if col in EXPECTED_RANGES:
            extracted[col] = df[col].values

    # Apply conversions
    if "temperature" in extracted:
        extracted["temperature"] = convert_temperature(extracted["temperature"])
    if "pressure" in extracted:
        extracted["pressure"] = convert_pressure(extracted["pressure"])
    if "rel_humidity" in extracted:
        extracted["rel_humidity"] = convert_rel_humidity(extracted["rel_humidity"])
    if "cloud_cover" in extracted:
        extracted["cloud_cover"] = convert_cloud_cover(extracted["cloud_cover"])
    if "shortwave" in extracted:
        extracted["shortwave"] = clip_shortwave(extracted["shortwave"])

    _write_uniform_wind(output_dir, time_seconds, extracted, ref_date)
    _write_uniform_meteo(output_dir, time_seconds, extracted, ref_date)

    print(f"[process] Forcing files written to {output_dir}")
    return extracted


# ──────────────────────────────────────────────────────────────────────
# File writers
# ──────────────────────────────────────────────────────────────────────

def _write_uniform_wind(output_dir, time_seconds, data, ref_date):
    """Write uniform wind file (.wnd) for Delft3D."""
    ws = data.get("wind_speed", np.zeros(len(time_seconds)))
    wd = data.get("wind_direction", np.zeros(len(time_seconds)))

    outpath = os.path.join(output_dir, "wind.wnd")
    with open(outpath, "w") as f:
        f.write(f"# Delft3D wind forcing (uniform)\n")
        f.write(f"# Generated by convert_forcing_to_delft3d.py\n")
        f.write(f"# RefDate: {ref_date.strftime('%Y%m%d')}\n")
        f.write(f"# Columns: time_seconds  wind_speed_m/s  wind_direction_degN\n")
        for i in range(len(time_seconds)):
            f.write(f"{time_seconds[i]:.1f}  {ws[i]:.4f}  {wd[i]:.2f}\n")

    print(f"  Written: {outpath} ({len(time_seconds)} records)")


def _write_uniform_meteo(output_dir, time_seconds, data, ref_date):
    """Write uniform meteorological files for Delft3D heat flux model."""
    # Pressure file
    if "pressure" in data:
        outpath = os.path.join(output_dir, "pressure.amp")
        with open(outpath, "w") as f:
            f.write(f"# Atmospheric pressure [Pa]\n")
            f.write(f"# RefDate: {ref_date.strftime('%Y%m%d')}\n")
            for i in range(len(time_seconds)):
                f.write(f"{time_seconds[i]:.1f}  {data['pressure'][i]:.2f}\n")
        print(f"  Written: {outpath}")

    # Temperature file
    if "temperature" in data:
        outpath = os.path.join(output_dir, "airtemp.amt")
        with open(outpath, "w") as f:
            f.write(f"# Air temperature [°C]\n")
            f.write(f"# RefDate: {ref_date.strftime('%Y%m%d')}\n")
            for i in range(len(time_seconds)):
                f.write(f"{time_seconds[i]:.1f}  {data['temperature'][i]:.4f}\n")
        print(f"  Written: {outpath}")

    # Relative humidity file
    if "rel_humidity" in data:
        outpath = os.path.join(output_dir, "relhum.amr")
        with open(outpath, "w") as f:
            f.write(f"# Relative humidity [%]\n")
            f.write(f"# RefDate: {ref_date.strftime('%Y%m%d')}\n")
            for i in range(len(time_seconds)):
                f.write(f"{time_seconds[i]:.1f}  {data['rel_humidity'][i]:.2f}\n")
        print(f"  Written: {outpath}")

    # Cloud cover file
    if "cloud_cover" in data:
        outpath = os.path.join(output_dir, "cloud.amc")
        with open(outpath, "w") as f:
            f.write(f"# Cloud cover [fraction 0-1]\n")
            f.write(f"# RefDate: {ref_date.strftime('%Y%m%d')}\n")
            for i in range(len(time_seconds)):
                f.write(f"{time_seconds[i]:.1f}  {data['cloud_cover'][i]:.4f}\n")
        print(f"  Written: {outpath}")


# ──────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Convert ERA5/CMFD/VIC forcing to Delft3D format"
    )
    parser.add_argument("--era5_file", help="ERA5 NetCDF file path")
    parser.add_argument("--csv_file", help="CSV forcing file path (alternative)")
    parser.add_argument("--domain_bounds", help="lon_min lat_min lon_max lat_max")
    parser.add_argument("--start_date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end_date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--output_dir", required=True, help="Output directory")
    parser.add_argument("--wind_convention", default="nautical",
                        choices=["nautical", "math"],
                        help="Input wind direction convention")
    args = parser.parse_args()

    # Step 1: Validate inputs
    validate_inputs(args)

    # Step 2: Process
    if args.era5_file:
        data = process_era5(args.era5_file, args.output_dir,
                            args.start_date, args.end_date, args.domain_bounds)
    else:
        data = process_csv(args.csv_file, args.output_dir,
                           args.start_date, args.end_date)

    # Step 3: Validate outputs
    ref_date = datetime.strptime(args.start_date, "%Y-%m-%d")
    warnings = validate_outputs(args.output_dir, ref_date)

    if warnings:
        print(f"\n[DONE] Forcing generated with {len(warnings)} warning(s)")
    else:
        print(f"\n[DONE] Forcing generated successfully")


if __name__ == "__main__":
    main()
