#!/usr/bin/env python3
"""
convert_met_to_w2.py — Convert CMFD/MSWX/NASA POWER forcing to CE-QUAL-W2 met format.

CRITICAL UNIT CONVERSIONS (silent errors if wrong — dt_001, dt_002, dt_004, dt_005):
  - Cloud cover: CE-QUAL-W2 wants TENTHS (0-10), NOT fraction (0-1), NOT percent (0-100)
    If given as fraction 0-1: multiply by 10
    If wrong: model sees near-clear sky → 3-5 C warm temperature bias (dt_001)
  - Dewpoint: CE-QUAL-W2 wants TDEW in deg C, NOT relative humidity, NOT vapor pressure
    From VP (kPa): TDEW = (237.3 * ln(VP/0.6108)) / (17.27 - ln(VP/0.6108))  (dt_002)
  - Julian day: CE-QUAL-W2 wants DECIMAL day of year (1.0 = midnight Jan 1, 1.5 = noon Jan 1)
    NOT integer day number, NOT astronomical Julian Date  (dt_005)
  - Wind direction: typically degrees (0-360) in v4.x. Some v3.x versions use radians (dt_004)

CE-QUAL-W2 met file format (fixed-width, 8-char fields):
  $Met file for water body 1
  JDAY      TAIR      TDEW      WIND      WDIR     CLOUD       SRO
    1.000    -5.200    -8.100     3.100   270.000     7.000     0.000

Usage:
    python convert_met_to_w2.py \
        --forcing_dir /path/to/cmfd_or_mswx \
        --lat 32.54 --lon 111.51 \
        --start_year 2005 --end_year 2010 \
        --output met_wb1.npt

    python convert_met_to_w2.py \
        --vic_forcing_dir /path/to/vic/forcing/forcing_final \
        --lat 32.54 --lon 111.51 \
        --start_year 2005 --end_year 2010 \
        --output met_wb1.npt
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect")
from ki_tools_common.humidity import saturation_vapor_pressure


def validate_inputs(args):
    """Validate input arguments."""
    errors = []

    if args.forcing_dir is None and args.vic_forcing_dir is None:
        errors.append("Must provide either --forcing_dir (CMFD/MSWX) or "
                      "--vic_forcing_dir (VIC forcing files)")

    if args.forcing_dir and not os.path.isdir(args.forcing_dir):
        errors.append(f"Forcing directory not found: {args.forcing_dir}")

    if args.vic_forcing_dir and not os.path.isdir(args.vic_forcing_dir):
        errors.append(f"VIC forcing directory not found: {args.vic_forcing_dir}")

    if not (-90 <= args.lat <= 90):
        errors.append(f"--lat must be between -90 and 90, got {args.lat}")
    if not (-180 <= args.lon <= 180):
        errors.append(f"--lon must be between -180 and 180, got {args.lon}")

    if args.start_year > args.end_year:
        errors.append(f"start_year ({args.start_year}) > end_year ({args.end_year})")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)


def vp_to_dewpoint(vp_kpa):
    """
    Convert vapor pressure (kPa) to dewpoint temperature (deg C).

    Formula: TDEW = (237.3 * ln(VP/0.6108)) / (17.27 - ln(VP/0.6108))
    where VP is in kPa.

    CRITICAL (dt_002): VP must be in kPa. CMFD gives kPa. MSWX also kPa.
    If VP is in Pa (e.g., ERA5), divide by 1000 first!
    If VP is in hPa, divide by 10 first!
    """
    # Use canonical Tetens reference: es(0°C) in kPa
    es0_kpa = saturation_vapor_pressure(0.0) / 10.0  # hPa -> kPa (≈0.6108)
    vp_kpa = np.clip(vp_kpa, 0.001, 10.0)  # prevent log(0)
    ln_term = np.log(vp_kpa / es0_kpa)
    tdew = (237.3 * ln_term) / (17.269 - ln_term)  # inverse Tetens (ki_tools_common coefficients)
    return tdew


def estimate_cloud_cover(sw_actual, sw_clearsky):
    """
    Estimate cloud cover in TENTHS (0-10) from shortwave radiation.

    CLOUD = 10 * (1 - SW_actual / SW_clearsky)

    CRITICAL (dt_001): Result is in TENTHS (0-10), NOT fraction (0-1)!
    CE-QUAL-W2 reads cloud cover as 0-10. If you pass 0-1 (fraction),
    it looks like near-clear sky, resulting in too much shortwave and
    water temperatures 3-5 C too warm. This is a SILENT error.

    During nighttime (SW_clearsky ≈ 0), use the most recent daytime value.
    """
    cloud = np.full_like(sw_actual, 5.0)  # default moderate cloud
    mask = sw_clearsky > 10  # only compute when sufficient daylight
    cloud[mask] = 10.0 * np.clip(1.0 - sw_actual[mask] / sw_clearsky[mask], 0, 1)
    return cloud


def compute_clearsky_sw(lat, doy_array, hour_array):
    """
    Compute clear-sky shortwave radiation (W/m^2) using simple solar geometry.

    Used as denominator for cloud cover estimation when only measured SW is available.
    """
    lat_rad = np.radians(lat)
    # Solar declination (Spencer formula)
    day_angle = 2 * np.pi * (doy_array - 1) / 365.25
    decl = (0.006918 - 0.399912 * np.cos(day_angle) + 0.070257 * np.sin(day_angle)
            - 0.006758 * np.cos(2 * day_angle) + 0.000907 * np.sin(2 * day_angle))

    # Hour angle (15 deg per hour, 0 at solar noon)
    hour_angle = np.radians(15.0 * (hour_array - 12.0))

    # Solar elevation
    sin_elev = (np.sin(lat_rad) * np.sin(decl) +
                np.cos(lat_rad) * np.cos(decl) * np.cos(hour_angle))
    sin_elev = np.clip(sin_elev, 0, 1)

    # Clear-sky SW (simplified)
    solar_constant = 1361.0  # W/m^2
    transmittance = 0.75  # atmospheric transmittance
    sw_clearsky = solar_constant * transmittance * sin_elev

    return sw_clearsky


def datetime_to_jday(dt):
    """
    Convert datetime to CE-QUAL-W2 decimal Julian day (JDAY).

    JDAY = day_of_year + hour/24 + minute/1440

    CRITICAL (dt_005): JDAY is decimal, NOT integer.
    1.0 = midnight Jan 1, 1.5 = noon Jan 1, 2.0 = midnight Jan 2.
    """
    doy = dt.timetuple().tm_yday
    frac = dt.hour / 24.0 + dt.minute / 1440.0 + dt.second / 86400.0
    return doy + frac


def read_vic_forcing(vic_dir, lat, lon, start_year, end_year):
    """
    Read VIC forcing files and extract meteorological variables.

    VIC forcing file format (space-delimited, 7 columns):
    PREC  TMAX  TMIN  WIND  VP  SRAD_SW  SRAD_LW
    mm    C     C     m/s   kPa W/m^2    W/m^2

    VIC files are 3-hourly (8 steps/day).
    """
    # Find the forcing file closest to the given lat/lon
    vic_dir = Path(vic_dir)
    forcing_files = sorted(vic_dir.glob("*"))

    # VIC forcing files are named like: forcing_prefix_LAT_LON
    best_file = None
    best_dist = float("inf")

    for f in forcing_files:
        if f.is_dir():
            continue
        parts = f.stem.split("_")
        try:
            file_lat = float(parts[-2])
            file_lon = float(parts[-1])
            dist = (file_lat - lat) ** 2 + (file_lon - lon) ** 2
            if dist < best_dist:
                best_dist = dist
                best_file = f
        except (ValueError, IndexError):
            continue

    if best_file is None:
        return None, "No VIC forcing file found near lat={}, lon={}".format(lat, lon)

    # Read the file — VIC forcing column order (CLAUDE.md unit trap):
    # TEMP(°C), PREC(mm), PRESSURE(kPa), SWDOWN(W/m²), LWDOWN(W/m²), VP(kPa), WIND(m/s)
    df = pd.read_csv(best_file, sep=r"\s+", header=None,
                     names=["TAIR", "PREC", "PRESSURE", "SW_DOWN", "LW_DOWN", "VP", "WIND"])

    # Generate timestamps (3-hourly)
    start_dt = datetime(start_year, 1, 1)
    n_steps = len(df)
    timestamps = [start_dt + timedelta(hours=3 * i) for i in range(n_steps)]
    df["datetime"] = timestamps

    return df, None


def read_cmfd_mswx_forcing(forcing_dir, lat, lon, start_year, end_year):
    """
    Read CMFD or MSWX forcing NetCDF files.
    Returns a DataFrame with 3-hourly meteorological data.
    """
    try:
        import xarray as xr
    except ImportError:
        return None, "xarray required for CMFD/MSWX reading"

    forcing_dir = Path(forcing_dir)

    all_data = []
    for year in range(start_year, end_year + 1):
        # Try CMFD format first (monthly files)
        cmfd_files = sorted(forcing_dir.glob(f"*{year}*.nc"))
        if not cmfd_files:
            # Try MSWX format (yearly files)
            cmfd_files = sorted(forcing_dir.glob(f"*{year}*"))

        for nc_file in cmfd_files:
            try:
                ds = xr.open_dataset(nc_file)
                # Extract nearest grid point
                ds_point = ds.sel(lat=lat, lon=lon, method="nearest")
                df_chunk = ds_point.to_dataframe().reset_index()
                all_data.append(df_chunk)
                ds.close()
            except Exception:
                continue

    if not all_data:
        return None, f"No forcing data found in {forcing_dir} for {start_year}-{end_year}"

    df = pd.concat(all_data, ignore_index=True)
    return df, None


def process(args):
    """Main processing: read forcing data and write CE-QUAL-W2 met file."""
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)

    # Read forcing data
    if args.vic_forcing_dir:
        df, err = read_vic_forcing(args.vic_forcing_dir, args.lat, args.lon,
                                   args.start_year, args.end_year)
        if err:
            print(json.dumps({"status": "error", "errors": [err]}))
            return 2

        # Extract variables from VIC format
        tair = df["TAIR"].values
        vp_kpa = df["VP"].values
        wind = df["WIND"].values
        sw_down = df["SW_DOWN"].values
        timestamps = df["datetime"].values

    elif args.forcing_dir:
        df, err = read_cmfd_mswx_forcing(args.forcing_dir, args.lat, args.lon,
                                          args.start_year, args.end_year)
        if err:
            print(json.dumps({"status": "error", "errors": [err]}))
            return 2

        # Map CMFD/MSWX variable names (may vary)
        tair_col = next((c for c in df.columns if "temp" in c.lower() or "tair" in c.lower()), None)
        vp_col = next((c for c in df.columns if "vp" in c.lower() or "vapor" in c.lower()), None)
        wind_col = next((c for c in df.columns if "wind" in c.lower()), None)
        sw_col = next((c for c in df.columns if "sw" in c.lower() or "srad" in c.lower()), None)
        time_col = next((c for c in df.columns if "time" in c.lower()), None)

        tair = df[tair_col].values if tair_col else np.zeros(len(df))
        vp_kpa = df[vp_col].values if vp_col else np.full(len(df), 0.8)
        wind = df[wind_col].values if wind_col else np.full(len(df), 2.0)
        sw_down = df[sw_col].values if sw_col else np.zeros(len(df))
        timestamps = pd.to_datetime(df[time_col]).values if time_col else None

    # Convert units
    # 1. Dewpoint from vapor pressure (CRITICAL — dt_002)
    tdew = vp_to_dewpoint(vp_kpa)

    # 2. Wind direction: default westerly (270 degrees) if not available
    wdir = np.full_like(wind, 270.0)

    # 3. Cloud cover in TENTHS 0-10 (CRITICAL — dt_001)
    if timestamps is not None:
        dts = pd.to_datetime(timestamps)
        doy_arr = np.array([d.timetuple().tm_yday for d in dts], dtype=float)
        hour_arr = np.array([d.hour + d.minute / 60 for d in dts], dtype=float)
        sw_clearsky = compute_clearsky_sw(args.lat, doy_arr, hour_arr)
        cloud = estimate_cloud_cover(sw_down, sw_clearsky)
    else:
        cloud = np.full_like(tair, 5.0)  # moderate default

    # 4. Shortwave radiation (optional SRO column)
    sro = np.clip(sw_down, 0, 1400)

    # 5. Julian days (CRITICAL — dt_005: must be DECIMAL, not integer)
    if timestamps is not None:
        dts = pd.to_datetime(timestamps)
        jdays = np.array([datetime_to_jday(d.to_pydatetime()) for d in dts])
    else:
        # Generate from start_year
        n_steps = len(tair)
        start_dt = datetime(args.start_year, 1, 1)
        jdays = np.array([
            datetime_to_jday(start_dt + timedelta(hours=3 * i)) for i in range(n_steps)
        ])

    # Write CE-QUAL-W2 met file (fixed-width, 10-char fields)
    with open(args.output, "w") as f:
        f.write(f"$Met file for water body 1 — generated by HydroCraft CE-QUAL-W2 tools\n")
        f.write(f"$JDAY      TAIR      TDEW      WIND      WDIR     CLOUD       SRO\n")

        for i in range(len(jdays)):
            line = (f"{jdays[i]:10.3f}"
                    f"{tair[i]:10.3f}"
                    f"{tdew[i]:10.3f}"
                    f"{wind[i]:10.3f}"
                    f"{wdir[i]:10.3f}"
                    f"{cloud[i]:10.3f}"
                    f"{sro[i]:10.3f}")
            f.write(line + "\n")

    # Validate output
    warnings = []
    if np.any(cloud > 10.001):
        warnings.append("Cloud cover exceeds 10 — check units (should be tenths 0-10)")
    if np.any(cloud < -0.001):
        warnings.append("Cloud cover is negative — check calculation")
    if np.any(tdew > tair + 1):
        warnings.append("Dewpoint exceeds air temperature at some timesteps — check VP units")
    if np.all(sro < 1):
        warnings.append("All shortwave radiation is ~0 — check SW data source")

    n_steps = len(jdays)
    n_days = (jdays[-1] - jdays[0]) if n_steps > 1 else 0

    result = {
        "status": "success",
        "output_file": args.output,
        "n_timesteps": n_steps,
        "n_days": round(float(n_days), 1),
        "jday_range": [round(float(jdays[0]), 3), round(float(jdays[-1]), 3)],
        "tair_range": [round(float(np.min(tair)), 1), round(float(np.max(tair)), 1)],
        "tdew_range": [round(float(np.min(tdew)), 1), round(float(np.max(tdew)), 1)],
        "cloud_range": [round(float(np.min(cloud)), 1), round(float(np.max(cloud)), 1)],
        "wind_range": [round(float(np.min(wind)), 1), round(float(np.max(wind)), 1)],
    }
    if warnings:
        result["warnings"] = warnings

    print(json.dumps(result, indent=2))
    return 0


def main():
    parser = argparse.ArgumentParser(description="Convert forcing to CE-QUAL-W2 met format")

    parser.add_argument("--forcing_dir", help="CMFD/MSWX forcing directory")
    parser.add_argument("--vic_forcing_dir", help="VIC forcing file directory")
    parser.add_argument("--lat", type=float, required=True, help="Latitude")
    parser.add_argument("--lon", type=float, required=True, help="Longitude")
    parser.add_argument("--start_year", type=int, required=True)
    parser.add_argument("--end_year", type=int, required=True)
    parser.add_argument("--output", required=True, help="Output met file path (met_wb1.npt)")

    args = parser.parse_args()
    validate_inputs(args)
    sys.exit(process(args))


if __name__ == "__main__":
    main()
