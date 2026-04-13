#!/usr/bin/env python3
"""
convert_met_to_glm.py — Convert CMFD/MSWX/NASA POWER forcing to GLM meteorological CSV.

CRITICAL UNIT CONVERSIONS (silent errors if wrong):
  - Rain: CMFD/MSWX give mm/3hr. GLM wants m/day. Conversion: mm/3hr * 8 / 1000
  - RelHum: CMFD/MSWX give VP in kPa. GLM wants RH in % (0-100).
    Formula: RH = 100 * VP / (0.6108 * exp(17.27*T/(T+237.3)))  # TODO: consider ki_tools_common.humidity.saturation_vapor_pressure
  - ShortWave: Clip to >= 0 (interpolation can produce negative at night)
  - Snow: Partition from rain when T < snow_threshold (default 0 degC)

GLM CSV format:
  time,ShortWave,LongWave,AirTemp,RelHum,WindSpeed,Rain,Snow
  YYYY-MM-DD HH:MM:SS,W/m2,W/m2,degC,%,m/s,m/day,m/day

Usage:
    python convert_met_to_glm.py \
        --forcing_dir /path/to/cmfd_or_mswx \
        --lat 40.48 --lon 116.97 \
        --start_date 2000-01-01 --end_date 2010-12-31 \
        --output bcs/met_hourly.csv

    python convert_met_to_glm.py \
        --vic_forcing_dir /path/to/vic/forcing/forcing_final \
        --lat 40.48 --lon 116.97 \
        --start_date 2000-01-01 --end_date 2010-12-31 \
        --output bcs/met_hourly.csv
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
sys.path.insert(0, "/home/server/knowledge-dissection-toolkit/auto_dissect")
from ki_tools_common.units import celsius_to_kelvin, kelvin_to_celsius
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

    if args.lat < -90 or args.lat > 90:
        errors.append(f"--lat must be between -90 and 90, got {args.lat}")
    if args.lon < -180 or args.lon > 180:
        errors.append(f"--lon must be between -180 and 180, got {args.lon}")

    try:
        datetime.strptime(args.start_date, "%Y-%m-%d")
        datetime.strptime(args.end_date, "%Y-%m-%d")
    except ValueError as e:
        errors.append(f"Invalid date format: {e}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)


def vp_to_rh(vp_kpa, temp_c):
    """
    Convert vapor pressure (kPa) to relative humidity (%).

    Uses the Tetens formula for saturation vapor pressure:
    VP_sat = 0.6108 * exp(17.27 * T / (T + 237.3))  # TODO: consider ki_tools_common.humidity.saturation_vapor_pressure
    RH = 100 * VP / VP_sat

    CRITICAL: Result must be 0-100 (percentage), NOT 0-1 (fraction).
    """
    vp_sat = 0.6108 * np.exp(17.27 * temp_c / (temp_c + 237.3))  # TODO: consider ki_tools_common.humidity.saturation_vapor_pressure
    rh = 100.0 * vp_kpa / vp_sat
    # Clip to physical range
    rh = np.clip(rh, 0.0, 100.0)
    return rh


def precip_mm_3hr_to_m_day(precip_mm_3hr):
    """
    Convert precipitation from mm/3hr to m/day.

    CMFD/MSWX: mm per 3-hour timestep
    GLM: meters per day

    Conversion: mm/3hr * (24/3) / 1000 = mm/3hr * 8 / 1000
    i.e., multiply rate by 8 (to get mm/day) then divide by 1000 (to get m/day)

    CRITICAL: Using mm/day instead of m/day causes lake to flood (1000x too much rain).
    """
    return precip_mm_3hr * 8.0 / 1000.0


def partition_rain_snow(precip_m_day, temp_c, snow_threshold=0.0):
    """
    Partition total precipitation into rain and snow based on air temperature.

    Below snow_threshold: all snow
    Above snow_threshold + 2: all rain
    Between: linear interpolation
    """
    rain = np.where(temp_c > snow_threshold + 2.0, precip_m_day,
                    np.where(temp_c < snow_threshold, 0.0,
                             precip_m_day * (temp_c - snow_threshold) / 2.0))
    snow = precip_m_day - rain
    return np.maximum(rain, 0.0), np.maximum(snow, 0.0)


def read_vic_forcing(vic_forcing_dir, lat, lon, start_date, end_date):
    """
    Read VIC ASCII forcing files and convert to GLM format.

    VIC forcing file columns (7 variables):
    0: PRECIP (mm/timestep, typically 3hr)
    1: AIR_TEMP (degC)
    2: SHORTWAVE (W/m2)
    3: LONGWAVE (W/m2)
    4: PRESSURE (kPa)
    5: VP (kPa)
    6: WIND (m/s)
    """
    # Find the closest VIC forcing file
    import glob
    pattern = os.path.join(vic_forcing_dir, f"*_{lat:.4f}_{lon:.4f}")
    files = glob.glob(pattern)
    if not files:
        # Try with different precision
        pattern = os.path.join(vic_forcing_dir, f"*_{lat:.2f}*_{lon:.2f}*")
        files = glob.glob(pattern)
    if not files:
        # Search all files and find closest
        all_files = glob.glob(os.path.join(vic_forcing_dir, "*"))
        best_dist = float('inf')
        best_file = None
        for f in all_files:
            basename = os.path.basename(f)
            parts = basename.split('_')
            try:
                flat = float(parts[-2])
                flon = float(parts[-1])
                dist = (flat - lat) ** 2 + (flon - lon) ** 2
                if dist < best_dist:
                    best_dist = dist
                    best_file = f
            except (ValueError, IndexError):
                continue
        if best_file:
            files = [best_file]

    if not files:
        print(json.dumps({"status": "error",
                          "errors": [f"No VIC forcing file found near {lat}, {lon}"]}))
        sys.exit(1)

    forcing_file = files[0]
    print(f"Reading VIC forcing from {forcing_file}", file=sys.stderr)

    data = np.loadtxt(forcing_file)
    n_cols = data.shape[1]

    # Determine timestep from file length and date range
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    n_days = (end_dt - start_dt).days + 1

    if data.shape[0] >= n_days * 8:
        steps_per_day = 8  # 3-hourly
    elif data.shape[0] >= n_days * 24:
        steps_per_day = 24  # hourly
    elif data.shape[0] >= n_days * 4:
        steps_per_day = 4  # 6-hourly
    else:
        steps_per_day = 1  # daily

    dt_hours = 24 / steps_per_day

    # Build time index
    times = [start_dt + timedelta(hours=i * dt_hours)
             for i in range(data.shape[0])]

    # Extract variables (VIC 7-column format: AIR_TEMP, PREC, PRESSURE, SWDOWN, LWDOWN, VP, WIND)
    # Verified empirically: col3=SWDOWN (0 at night, >100 daytime), col4=LWDOWN (~230 constant)
    temp_c = data[:, 0]      # degC
    precip_mm = data[:, 1]   # mm/timestep
    pressure = data[:, 2]    # kPa
    sw = data[:, 3]          # W/m2 (SWDOWN - zero at night)
    lw = data[:, 4]          # W/m2 (LWDOWN - ~200-400 constant)
    vp = data[:, 5]          # kPa
    wind = data[:, 6]        # m/s

    # Convert units
    # Precip: mm/timestep -> m/day
    precip_m_day = precip_mm * (24.0 / dt_hours) / 1000.0
    rh = vp_to_rh(vp, temp_c)
    sw = np.maximum(sw, 0.0)  # CRITICAL: clip negative SW
    rain, snow = partition_rain_snow(precip_m_day, temp_c)

    df = pd.DataFrame({
        'time': times,
        'ShortWave': sw,
        'LongWave': lw,
        'AirTemp': temp_c,
        'RelHum': rh,
        'WindSpeed': wind,
        'Rain': rain,
        'Snow': snow,
    })

    return df


def read_cmfd_mswx_at_point(forcing_dir, lat, lon, start_date, end_date):
    """
    Read CMFD or MSWX forcing data at a single lat/lon point.

    CMFD structure: {forcing_dir}/{variable}/{variable}_YYYY{MM}.nc
    MSWX structure: {forcing_dir}/{variable}/{variable}_YYYY.nc

    Variables: temp, sp, prec, lwd, swd, shum/vp, wind
    """
    import xarray as xr

    forcing_path = Path(forcing_dir)
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")

    # Detect forcing type (CMFD vs MSWX)
    is_mswx = "msxw" in str(forcing_path).lower() or "mswx" in str(forcing_path).lower()

    # Variable name mapping
    if is_mswx:
        var_map = {
            'temp': ('Temp', 'air_temperature'),
            'swd': ('SWd', 'surface_downwelling_shortwave_flux_in_air'),
            'lwd': ('LWd', 'surface_downwelling_longwave_flux_in_air'),
            'prec': ('P', 'precipitation_amount'),
            'wind': ('Wind', 'wind_speed'),
            'sp': ('Pres', 'surface_air_pressure'),
            'shum': ('SpHum', 'specific_humidity'),
        }
    else:
        var_map = {
            'temp': ('Temp', 'temp'),
            'swd': ('SRad', 'srad'),
            'lwd': ('LRad', 'lrad'),
            'prec': ('Prec', 'prec'),
            'wind': ('Wind', 'wind'),
            'sp': ('Pres', 'pres'),
            'shum': ('SHum', 'shum'),
        }

    all_data = {}
    for var_key, (dir_name, var_name) in var_map.items():
        var_dir = forcing_path / dir_name
        if not var_dir.exists():
            # Try alternative names
            for alt in [dir_name.lower(), dir_name.upper(), var_key]:
                var_dir = forcing_path / alt
                if var_dir.exists():
                    break

        if not var_dir.exists():
            print(f"WARNING: Variable directory {dir_name} not found, skipping",
                  file=sys.stderr)
            continue

        # Find files for the period
        import glob
        nc_files = sorted(glob.glob(str(var_dir / "*.nc")))
        if not nc_files:
            print(f"WARNING: No NetCDF files in {var_dir}", file=sys.stderr)
            continue

        datasets = []
        for nc_file in nc_files:
            try:
                ds = xr.open_dataset(nc_file)
                # Select nearest point
                ds_point = ds.sel(lat=lat, lon=lon, method='nearest')
                # Filter time
                ds_point = ds_point.sel(
                    time=slice(start_date, end_date))
                if len(ds_point.time) > 0:
                    datasets.append(ds_point)
                ds.close()
            except Exception as e:
                print(f"WARNING: Error reading {nc_file}: {e}", file=sys.stderr)
                continue

        if datasets:
            combined = xr.concat(datasets, dim='time')
            # Get the first data variable
            data_var = list(combined.data_vars)[0]
            all_data[var_key] = combined[data_var].values
            if 'time_index' not in all_data:
                all_data['time_index'] = pd.DatetimeIndex(combined.time.values)

    if not all_data or 'time_index' not in all_data:
        print(json.dumps({"status": "error",
                          "errors": ["Could not read any forcing data"]}))
        sys.exit(1)

    times = all_data['time_index']
    n = len(times)

    # Build dataframe with unit conversions
    temp_c = all_data.get('temp', np.zeros(n))
    if is_mswx and np.nanmean(temp_c) > 200:
        temp_c = kelvin_to_celsius(temp_c)  # K to C

    sw = np.maximum(all_data.get('swd', np.zeros(n)), 0.0)
    lw = all_data.get('lwd', np.zeros(n))

    precip = all_data.get('prec', np.zeros(n))
    # CMFD precip is mm/3hr; MSWX depends on convention
    precip_m_day = precip * 8.0 / 1000.0  # mm/3hr -> m/day

    wind = all_data.get('wind', np.ones(n) * 2.0)

    # Humidity conversion
    if 'shum' in all_data:
        shum = all_data['shum']
        sp = all_data.get('sp', np.ones(n) * 101.325)  # kPa default
        if np.nanmean(sp) > 10000:
            sp = sp / 1000.0  # Pa to kPa
        # Specific humidity to VP: VP = q * P / (0.622 + 0.378 * q)
        vp = shum * sp / (0.622 + 0.378 * shum)
        rh = vp_to_rh(vp, temp_c)
    else:
        rh = np.ones(n) * 70.0  # default if no humidity data

    rain, snow = partition_rain_snow(precip_m_day, temp_c)

    df = pd.DataFrame({
        'time': times,
        'ShortWave': sw,
        'LongWave': lw,
        'AirTemp': temp_c,
        'RelHum': rh,
        'WindSpeed': wind,
        'Rain': rain,
        'Snow': snow,
    })

    return df


def process(args):
    """Read forcing data and convert to GLM format."""
    if args.vic_forcing_dir:
        df = read_vic_forcing(args.vic_forcing_dir, args.lat, args.lon,
                              args.start_date, args.end_date)
    else:
        df = read_cmfd_mswx_at_point(args.forcing_dir, args.lat, args.lon,
                                     args.start_date, args.end_date)

    # Apply wind height correction if needed
    if args.wind_height != 10.0:
        # Log-law correction: U_10 = U_z * ln(10/z0) / ln(z/z0)
        z0 = 0.001  # roughness for water surface
        correction = np.log(10.0 / z0) / np.log(args.wind_height / z0)
        df['WindSpeed'] = df['WindSpeed'] * correction
        print(f"Wind height correction: {args.wind_height}m -> 10m, "
              f"factor={correction:.3f}", file=sys.stderr)

    # Format time column
    df['time'] = pd.to_datetime(df['time']).dt.strftime('%Y-%m-%d %H:%M:%S')

    return df


def validate_outputs(df, args):
    """Validate the output meteorological data."""
    warnings = []

    # Check for NaN
    nan_counts = df.isna().sum()
    for col in nan_counts.index:
        if nan_counts[col] > 0:
            warnings.append(f"Column {col} has {nan_counts[col]} NaN values")

    # Check ranges
    sw_max = df['ShortWave'].max()
    if sw_max > 1361:
        warnings.append(
            f"ShortWave max={sw_max:.1f} exceeds solar constant (1361 W/m2)")
    if df['ShortWave'].min() < 0:
        warnings.append(f"ShortWave has negative values (min={df['ShortWave'].min():.1f})")

    rh_max = df['RelHum'].max()
    rh_min = df['RelHum'].min()
    if rh_max <= 1.0:
        warnings.append(
            f"CRITICAL: RelHum max={rh_max:.3f} — appears to be fraction (0-1) "
            f"instead of percentage (0-100). GLM will compute near-zero evaporation!")
    if rh_min < 0:
        warnings.append(f"RelHum has negative values (min={rh_min:.1f})")

    rain_max = df['Rain'].max()
    if rain_max > 0.5:
        warnings.append(
            f"Rain max={rain_max:.4f} m/day ({rain_max*1000:.1f} mm/day) — "
            f"very high, check units")
    if rain_max > 1.0:
        warnings.append(
            f"CRITICAL: Rain max={rain_max:.1f} m/day — likely in mm/day instead of m/day!")

    temp_range = df['AirTemp'].max() - df['AirTemp'].min()
    if temp_range < 5:
        warnings.append(f"Temperature range only {temp_range:.1f} degC — check data")

    for w in warnings:
        print(f"WARNING: {w}", file=sys.stderr)

    return warnings


def main():
    parser = argparse.ArgumentParser(
        description="Convert forcing data to GLM meteorological CSV format")
    parser.add_argument("--forcing_dir", type=str,
                        help="CMFD or MSWX forcing directory")
    parser.add_argument("--vic_forcing_dir", type=str,
                        help="VIC ASCII forcing files directory")
    parser.add_argument("--lat", type=float, required=True,
                        help="Lake latitude")
    parser.add_argument("--lon", type=float, required=True,
                        help="Lake longitude")
    parser.add_argument("--start_date", type=str, required=True,
                        help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end_date", type=str, required=True,
                        help="End date (YYYY-MM-DD)")
    parser.add_argument("--wind_height", type=float, default=10.0,
                        help="Measurement height for wind speed (m, default: 10)")
    parser.add_argument("--snow_threshold", type=float, default=0.0,
                        help="Temperature threshold for rain/snow partition (degC)")
    parser.add_argument("--output", type=str, required=True,
                        help="Output CSV file path")
    args = parser.parse_args()

    validate_inputs(args)
    df = process(args)
    warnings = validate_outputs(df, args)

    # Write output
    os.makedirs(os.path.dirname(args.output) or '.', exist_ok=True)
    df.to_csv(args.output, index=False, float_format='%.4f')

    n_records = len(df)
    date_range = f"{df['time'].iloc[0]} to {df['time'].iloc[-1]}"

    result = {
        "status": "success",
        "output_file": args.output,
        "num_records": n_records,
        "date_range": date_range,
        "columns": list(df.columns),
        "warnings": warnings,
        "unit_summary": {
            "ShortWave": "W/m2",
            "LongWave": "W/m2",
            "AirTemp": "degC",
            "RelHum": "% (0-100)",
            "WindSpeed": "m/s (10m height)",
            "Rain": "m/day",
            "Snow": "m/day",
        }
    }

    print(json.dumps(result, indent=2), file=sys.stderr)
    print(f"GLM meteorological forcing written to {args.output} "
          f"({n_records} records)", file=sys.stderr)


if __name__ == "__main__":
    main()
