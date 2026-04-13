#!/usr/bin/env python3
"""
LISFLOOD Forcing Converter
==========================
Converts global meteorological data (ERA5, CMFD, MSWX) to LISFLOOD NetCDF forcing format.

LISFLOOD requires four forcing variables as NetCDF stacks or PCRaster map sequences:
  - pr  : Precipitation [mm/day]
  - ta  : Average air temperature [°C or K with TemperatureInKelvin=1]
  - et0 : Reference evapotranspiration (potential) [mm/day]
  - e0  : Open water evaporation (potential) [mm/day]

Pattern: validate → process → validate

Usage:
    python convert_forcing.py \
        --source_dir /path/to/era5/daily/ \
        --source_type era5 \
        --output_dir /path/to/lisflood/forcings/ \
        --start_date 2000-01-01 \
        --end_date 2010-12-31 \
        --mask_file /path/to/mask.nc \
        --temp_unit celsius
"""

import argparse
import sys
import os
from pathlib import Path
from datetime import datetime

import numpy as np

try:
    import xarray as xr
    import netCDF4 as nc
    import pandas as pd
except ImportError as e:
    print(f"Missing dependency: {e}. Install with: pip install xarray netCDF4 pandas")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Unit conversion constants
# ---------------------------------------------------------------------------
UNIT_CONVERSIONS = {
    "era5": {
        "precip": {
            "var": "tp",
            "from_unit": "m/timestep",
            "to_unit": "mm/day",
            "factor": 1000.0,  # m -> mm (already daily if daily ERA5)
            "description": "ERA5 total precipitation: m -> mm/day",
        },
        "temperature": {
            "var": "t2m",
            "from_unit": "K",
            "to_unit": "degC",
            "offset": -273.15,
            "description": "ERA5 2m temperature: K -> degC",
        },
    },
    "cmfd": {
        "precip": {
            "var": "prec",
            "from_unit": "mm/3hr",
            "to_unit": "mm/day",
            "factor": 8.0,  # 3hr -> day (8 timesteps per day)
            "description": "CMFD precipitation: mm/3hr -> mm/day (sum 8 steps)",
        },
        "temperature": {
            "var": "temp",
            "from_unit": "K",
            "to_unit": "degC",
            "offset": -273.15,
            "description": "CMFD temperature: K -> degC",
        },
    },
    "mswx": {
        "precip": {
            "var": "precipitation",
            "from_unit": "mm/3hr",
            "to_unit": "mm/day",
            "factor": 8.0,
            "description": "MSWX precipitation: mm/3hr -> mm/day",
        },
        "temperature": {
            "var": "air_temperature",
            "from_unit": "degC",
            "to_unit": "degC",
            "offset": 0.0,
            "description": "MSWX temperature: already in degC",
        },
    },
}


def validate_inputs(source_dir, source_type, mask_file=None):
    """Validate input files exist and source type is supported."""
    errors = []

    if not os.path.isdir(source_dir):
        errors.append(f"Source directory not found: {source_dir}")

    if source_type not in UNIT_CONVERSIONS:
        errors.append(
            f"Unknown source type '{source_type}'. "
            f"Supported: {list(UNIT_CONVERSIONS.keys())}"
        )

    if mask_file and not os.path.isfile(mask_file):
        errors.append(f"Mask file not found: {mask_file}")

    if errors:
        for e in errors:
            print(f"[ERROR] {e}")
        return False

    # Check for forcing files in source directory
    nc_files = list(Path(source_dir).glob("*.nc"))
    if len(nc_files) == 0:
        print(f"[WARNING] No NetCDF files found in {source_dir}")
        return False

    print(f"[OK] Found {len(nc_files)} NetCDF files in source directory")
    print(f"[OK] Source type: {source_type}")
    return True


def convert_precipitation(ds_in, source_type):
    """Convert precipitation to mm/day.

    TRAP dt_001: Precipitation units.
    LISFLOOD expects mm/day. ERA5 gives m/timestep, CMFD gives mm/3hr.
    Wrong conversion causes flooding (too much) or drought (too little).
    """
    conv = UNIT_CONVERSIONS[source_type]["precip"]
    var_name = conv["var"]

    if var_name not in ds_in:
        # Try common alternative names
        for alt in ["tp", "prec", "precip", "precipitation", "pr", "ppt"]:
            if alt in ds_in:
                var_name = alt
                break
        else:
            raise ValueError(
                f"Precipitation variable '{conv['var']}' not found. "
                f"Available: {list(ds_in.data_vars)}"
            )

    precip = ds_in[var_name].values.copy()

    # Apply conversion factor
    factor = conv.get("factor", 1.0)
    precip = precip * factor

    # Clip negative values (can arise from interpolation)
    precip = np.maximum(precip, 0.0)

    # Validation: check for unrealistic values
    max_precip = np.nanmax(precip)
    if max_precip > 500:
        print(
            f"[WARNING] Max precipitation = {max_precip:.1f} mm/day. "
            f"This is extremely high (>500 mm/day). Check units!"
        )
    elif max_precip > 0.5 and max_precip < 1.0:
        print(
            f"[WARNING] Max precipitation = {max_precip:.4f} mm/day. "
            f"Values look like they might be in m/day. Multiply by 1000?"
        )

    print(f"[OK] Precipitation converted: {conv['description']}")
    print(f"     Range: {np.nanmin(precip):.4f} - {max_precip:.2f} mm/day")
    return precip


def convert_temperature(ds_in, source_type, output_unit="celsius"):
    """Convert temperature to °C (or K if TemperatureInKelvin=1).

    TRAP dt_002: Temperature K/C mismatch.
    If TemperatureInKelvin=0 (default), LISFLOOD expects °C.
    If TemperatureInKelvin=1, LISFLOOD expects K.
    Setting the flag wrong shifts snow thresholds by 273.15°C.
    """
    conv = UNIT_CONVERSIONS[source_type]["temperature"]
    var_name = conv["var"]

    if var_name not in ds_in:
        for alt in ["t2m", "temp", "tas", "air_temperature", "ta", "tair"]:
            if alt in ds_in:
                var_name = alt
                break
        else:
            raise ValueError(
                f"Temperature variable '{conv['var']}' not found. "
                f"Available: {list(ds_in.data_vars)}"
            )

    temp = ds_in[var_name].values.copy()
    offset = conv.get("offset", 0.0)

    if output_unit == "celsius":
        temp = temp + offset
    elif output_unit == "kelvin":
        if offset != 0:
            # Source was K, user wants K — no conversion needed
            pass
        else:
            temp = temp + 273.15
    else:
        raise ValueError(f"Unknown output unit: {output_unit}")

    # Validation
    if output_unit == "celsius":
        if np.nanmax(temp) > 200:
            print(
                f"[WARNING] Max temperature = {np.nanmax(temp):.1f} °C. "
                f"Values appear to be in Kelvin. Apply -273.15 offset."
            )
        if np.nanmin(temp) < -90:
            print(
                f"[WARNING] Min temperature = {np.nanmin(temp):.1f} °C. "
                f"Unrealistically cold. Check source data."
            )
    print(f"[OK] Temperature converted: {conv['description']}")
    print(f"     Range: {np.nanmin(temp):.1f} - {np.nanmax(temp):.1f} °{output_unit[0].upper()}")
    return temp


def estimate_et0(temp_celsius, lat_rad, doy):
    """Estimate reference ET (Hargreaves method) when not available in forcing.

    TRAP dt_003: ET0 must be POTENTIAL, not actual.
    Uses Hargreaves equation: ET0 = 0.0023 * Ra * (Tmean + 17.8) * sqrt(Trange)
    where Ra = extraterrestrial radiation [mm/day equivalent].
    """
    # Solar constant
    Gsc = 0.0820  # MJ m-2 min-1

    # Inverse relative distance Earth-Sun
    dr = 1 + 0.033 * np.cos(2 * np.pi * doy / 365)

    # Solar declination
    delta = 0.409 * np.sin(2 * np.pi * doy / 365 - 1.39)

    # Sunset hour angle
    ws = np.arccos(-np.tan(lat_rad) * np.tan(delta))

    # Extraterrestrial radiation [MJ/m2/day]
    Ra = (24 * 60 / np.pi) * Gsc * dr * (
        ws * np.sin(lat_rad) * np.sin(delta)
        + np.cos(lat_rad) * np.cos(delta) * np.sin(ws)
    )

    # Convert MJ/m2/day to mm/day (latent heat of vaporization = 2.45 MJ/kg)
    Ra_mm = Ra / 2.45

    # Hargreaves equation (simplified, assumes Trange ~ 10°C)
    Trange = 10.0  # Default temperature range
    et0 = 0.0023 * Ra_mm * (temp_celsius + 17.8) * np.sqrt(np.maximum(Trange, 0.1))

    return np.maximum(et0, 0.0)


def write_lisflood_netcdf(data, var_name, output_path, times, lats, lons,
                          units, long_name):
    """Write a LISFLOOD-compatible NetCDF forcing file."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    ds = xr.Dataset(
        {
            var_name: (["time", "lat", "lon"], data.astype(np.float32)),
        },
        coords={
            "time": times,
            "lat": lats,
            "lon": lons,
        },
    )
    ds[var_name].attrs["units"] = units
    ds[var_name].attrs["long_name"] = long_name

    ds.to_netcdf(output_path, format="NETCDF4")
    print(f"[OK] Written: {output_path} ({var_name}, shape={data.shape})")


def validate_outputs(output_dir):
    """Validate generated forcing files."""
    errors = []
    warnings = []

    required_vars = ["pr", "ta", "et0", "e0"]
    for var in required_vars:
        nc_path = os.path.join(output_dir, f"{var}.nc")
        if not os.path.exists(nc_path):
            errors.append(f"Missing output file: {nc_path}")
            continue

        ds = xr.open_dataset(nc_path)
        if var not in ds:
            errors.append(f"Variable '{var}' not found in {nc_path}")
            continue

        data = ds[var].values
        if np.all(np.isnan(data)):
            errors.append(f"All NaN values in {var}")
        if var == "pr" and np.nanmax(data) > 500:
            warnings.append(f"Extreme precipitation: max={np.nanmax(data):.1f} mm/day")
        if var == "ta" and np.nanmax(data) > 60:
            warnings.append(f"Extreme temperature: max={np.nanmax(data):.1f} °C (Kelvin?)")
        if var in ("et0", "e0") and np.nanmin(data) < 0:
            warnings.append(f"Negative {var} values found — clipping needed")

        ds.close()

    for e in errors:
        print(f"[ERROR] {e}")
    for w in warnings:
        print(f"[WARNING] {w}")

    if not errors:
        print(f"[OK] All forcing files validated successfully")
    return len(errors) == 0


def main():
    parser = argparse.ArgumentParser(
        description="Convert global forcing data to LISFLOOD NetCDF format"
    )
    parser.add_argument("--source_dir", required=True, help="Input forcing directory")
    parser.add_argument(
        "--source_type",
        required=True,
        choices=["era5", "cmfd", "mswx"],
        help="Source data type",
    )
    parser.add_argument("--output_dir", required=True, help="Output directory")
    parser.add_argument("--start_date", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end_date", required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument("--mask_file", default=None, help="Domain mask (NetCDF)")
    parser.add_argument(
        "--temp_unit",
        default="celsius",
        choices=["celsius", "kelvin"],
        help="Output temperature unit (default: celsius)",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("LISFLOOD Forcing Converter")
    print("=" * 60)

    # Step 1: Validate inputs
    if not validate_inputs(args.source_dir, args.source_type, args.mask_file):
        sys.exit(1)

    # Step 2: Open source data
    nc_files = sorted(Path(args.source_dir).glob("*.nc"))
    print(f"\nOpening {len(nc_files)} source files...")
    ds_in = xr.open_mfdataset(nc_files, combine="by_coords")

    # Filter time range
    start = pd.Timestamp(args.start_date)
    end = pd.Timestamp(args.end_date)
    ds_in = ds_in.sel(time=slice(start, end))
    print(f"Time range: {ds_in.time.values[0]} to {ds_in.time.values[-1]}")
    print(f"Steps: {len(ds_in.time)}")

    times = ds_in.time.values
    lats = ds_in.lat.values if "lat" in ds_in.coords else ds_in.latitude.values
    lons = ds_in.lon.values if "lon" in ds_in.coords else ds_in.longitude.values

    # Step 3: Convert precipitation
    precip = convert_precipitation(ds_in, args.source_type)
    write_lisflood_netcdf(
        precip, "pr", os.path.join(args.output_dir, "pr.nc"),
        times, lats, lons, "mm/day", "Precipitation"
    )

    # Step 4: Convert temperature
    temp = convert_temperature(ds_in, args.source_type, args.temp_unit)
    write_lisflood_netcdf(
        temp, "ta", os.path.join(args.output_dir, "ta.nc"),
        times, lats, lons, f"deg{args.temp_unit[0].upper()}", "Average air temperature"
    )

    # Step 5: ET0 and E0 — use from source if available, otherwise estimate
    try:
        et0_data = ds_in["et0"].values if "et0" in ds_in else ds_in["pet"].values
        print("[OK] ET0 found in source data")
    except KeyError:
        print("[INFO] ET0 not in source — estimating via Hargreaves method")
        lat_rad = np.deg2rad(np.mean(lats))
        doys = pd.DatetimeIndex(times).dayofyear.values
        et0_data = np.zeros_like(precip)
        for i, doy in enumerate(doys):
            et0_data[i] = estimate_et0(temp[i], lat_rad, doy)

    write_lisflood_netcdf(
        et0_data, "et0", os.path.join(args.output_dir, "et0.nc"),
        times, lats, lons, "mm/day", "Reference evapotranspiration (potential)"
    )

    # E0 ≈ 1.05 * ET0 for open water (Penman factor)
    e0_data = et0_data * 1.05
    write_lisflood_netcdf(
        e0_data, "e0", os.path.join(args.output_dir, "e0.nc"),
        times, lats, lons, "mm/day", "Open water evaporation (potential)"
    )

    ds_in.close()

    # Step 6: Validate outputs
    print("\n--- Output validation ---")
    success = validate_outputs(args.output_dir)
    if not success:
        print("[FAIL] Output validation failed")
        sys.exit(1)

    print("\n[DONE] Forcing conversion complete")


if __name__ == "__main__":
    main()
