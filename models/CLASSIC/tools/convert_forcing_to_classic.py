#!/usr/bin/env python3
"""
convert_forcing_to_classic.py — Convert global reanalysis forcing to CLASSIC netCDF format.

CRITICAL UNIT CONVERSIONS (silent errors if wrong):
  - Temperature: Source often in K, CLASSIC driver expects deg C.
    Conversion: T_C = T_K - 273.15
  - Precipitation: Source often in mm/hr or mm/day. CLASSIC expects kg m-2 s-1.
    Conversion: mm/hr / 3600 = kg/m2/s, mm/day / 86400 = kg/m2/s
  - Specific humidity: Source may be g/kg. CLASSIC expects kg/kg.
    Conversion: g/kg / 1000
  - Pressure: Source may be hPa or kPa. CLASSIC expects Pa.
    Conversion: hPa * 100, kPa * 1000
  - Time: CLASSIC uses "day as %Y%m%d.%f" encoding, NOT CF "days since" convention.

CLASSIC netCDF format (one variable per file):
  Dimensions: time (UNLIMITED), lat, lon
  Time units: "day as %Y%m%d.%f" (e.g., 19010101.0 = midnight Jan 1 1901)
  Calendar: proleptic_gregorian (or standard)

Supported sources: CRU-JRA, ERA5, CMFD, generic CSV (site-level)

Usage:
    python convert_forcing_to_classic.py \\
        --source_type crujra \\
        --source_dir /path/to/crujra/ \\
        --lat 40.48 --lon 116.97 \\
        --start_year 1991 --end_year 2017 \\
        --output_dir /path/to/classic/met/ \\
        --timestep_minutes 30

    python convert_forcing_to_classic.py \\
        --source_type csv \\
        --csv_file /path/to/site_met.csv \\
        --lat 40.48 --lon 116.97 \\
        --start_year 2010 --end_year 2015 \\
        --output_dir /path/to/classic/met/ \\
        --timestep_minutes 30
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

try:
    import netCDF4 as nc
except ImportError:
    print(json.dumps({"status": "error", "errors": ["netCDF4 not installed. pip install netCDF4"]}))
    sys.exit(1)

try:
    import pandas as pd
except ImportError:
    pd = None


# ============================================================================
# CLASSIC meteorological variable definitions
# ============================================================================
CLASSIC_MET_VARS = {
    "dswrf": {
        "long_name": "Downwelling shortwave radiation",
        "units": "W/m2",
        "classic_name": "FSS",
        "min_valid": 0.0,
        "max_valid": 1400.0,
    },
    "dlwrf": {
        "long_name": "Downwelling longwave radiation",
        "units": "W/m2",
        "classic_name": "FDL",
        "min_valid": 50.0,
        "max_valid": 600.0,
    },
    "pre": {
        "long_name": "Precipitation rate",
        "units": "kg m-2 s-1",
        "classic_name": "PRE",
        "min_valid": 0.0,
        "max_valid": 0.1,  # ~360 mm/hr extreme
    },
    "tmp": {
        "long_name": "Air temperature",
        "units": "deg C",
        "classic_name": "TA",
        "min_valid": -90.0,
        "max_valid": 60.0,
    },
    "spfh": {
        "long_name": "Specific humidity",
        "units": "kg/kg",
        "classic_name": "QA",
        "min_valid": 0.0,
        "max_valid": 0.06,
    },
    "wind": {
        "long_name": "Wind speed",
        "units": "m/s",
        "classic_name": "VMOD",
        "min_valid": 0.0,
        "max_valid": 75.0,
    },
    "pres": {
        "long_name": "Surface air pressure",
        "units": "Pa",
        "classic_name": "PRES",
        "min_valid": 30000.0,
        "max_valid": 110000.0,
    },
}


def validate_inputs(args):
    """Validate input arguments before processing."""
    errors = []

    if args.source_type == "csv":
        if args.csv_file is None:
            errors.append("--csv_file required for source_type=csv")
        elif not os.path.isfile(args.csv_file):
            errors.append(f"CSV file not found: {args.csv_file}")
    else:
        if args.source_dir is None:
            errors.append("--source_dir required for non-CSV source types")
        elif not os.path.isdir(args.source_dir):
            errors.append(f"Source directory not found: {args.source_dir}")

    if args.lat < -90 or args.lat > 90:
        errors.append(f"--lat must be between -90 and 90, got {args.lat}")
    if args.lon < -180 or args.lon > 360:
        errors.append(f"--lon must be between -180 and 360, got {args.lon}")
    if args.start_year > args.end_year:
        errors.append(f"start_year ({args.start_year}) must be <= end_year ({args.end_year})")
    if args.timestep_minutes not in [15, 30, 60]:
        errors.append(f"timestep_minutes must be 15, 30, or 60, got {args.timestep_minutes}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)


def datetime_to_classic_time(dt):
    """
    Convert a datetime to CLASSIC's time encoding: "day as %Y%m%d.%f"

    Examples:
        2001-01-01 00:00 -> 20010101.0
        2001-01-01 12:00 -> 20010101.5
        2001-01-01 06:00 -> 20010101.25
        2001-01-01 00:30 -> 20010101.020833...
    """
    base = float(dt.strftime("%Y%m%d"))
    frac = (dt.hour * 3600 + dt.minute * 60 + dt.second) / 86400.0
    return base + frac


def create_classic_met_nc(output_path, var_name, data, times_dt, lat, lon):
    """
    Create a single-variable CLASSIC meteorological netCDF file.

    Parameters
    ----------
    output_path : str
        Path to output netCDF file
    var_name : str
        Variable name (e.g., 'dswrf', 'tmp', 'pre')
    data : np.ndarray
        1D array of data values, shape (ntimes,)
    times_dt : list of datetime
        List of datetime objects for each timestep
    lat : float
        Latitude in degrees north
    lon : float
        Longitude in degrees east
    """
    meta = CLASSIC_MET_VARS[var_name]
    time_values = np.array([datetime_to_classic_time(dt) for dt in times_dt])

    ds = nc.Dataset(output_path, "w", format="NETCDF4")

    # Dimensions
    ds.createDimension("time", None)  # UNLIMITED
    ds.createDimension("lat", 1)
    ds.createDimension("lon", 1)

    # Coordinate variables
    time_var = ds.createVariable("time", "f8", ("time",))
    time_var.standard_name = "time"
    time_var.units = "day as %Y%m%d.%f"
    time_var.calendar = "proleptic_gregorian"
    time_var.axis = "T"
    time_var[:] = time_values

    lat_var = ds.createVariable("lat", "f4", ("lat",))
    lat_var.standard_name = "latitude"
    lat_var.long_name = "latitude"
    lat_var.units = "degrees_north"
    lat_var.axis = "Y"
    lat_var[:] = [lat]

    lon_var = ds.createVariable("lon", "f4", ("lon",))
    lon_var.standard_name = "longitude"
    lon_var.long_name = "longitude"
    lon_var.units = "degrees_east"
    lon_var.axis = "X"
    lon_var[:] = [lon]

    # Data variable
    data_var = ds.createVariable(var_name, "f4", ("time", "lat", "lon"),
                                  fill_value=9.96921e+36)
    data_var.long_name = meta["long_name"]
    data_var.units = meta["units"]
    data_var[:, 0, 0] = data.astype(np.float32)

    ds.close()
    return output_path


def convert_temperature(values, source_unit):
    """Convert temperature to deg C (CLASSIC driver expects Celsius)."""
    if source_unit.lower() in ["k", "kelvin"]:
        return values - 273.15
    elif source_unit.lower() in ["c", "celsius", "degc", "deg c", "deg_c"]:
        return values
    elif source_unit.lower() in ["f", "fahrenheit"]:
        return (values - 32.0) * 5.0 / 9.0
    else:
        print(f"WARNING: Unknown temperature unit '{source_unit}', assuming Kelvin")
        return values - 273.15


def convert_precipitation(values, source_unit, timestep_seconds):
    """Convert precipitation to kg m-2 s-1."""
    if source_unit.lower() in ["kg m-2 s-1", "kg/m2/s", "mm/s"]:
        return values
    elif source_unit.lower() in ["mm/hr", "mm/h", "mm hr-1"]:
        return values / 3600.0
    elif source_unit.lower() in ["mm/day", "mm/d", "mm d-1"]:
        return values / 86400.0
    elif source_unit.lower() in ["mm/3hr", "mm/3h"]:
        return values / 10800.0
    elif source_unit.lower() in ["mm/timestep", "mm"]:
        return values / timestep_seconds
    else:
        print(f"WARNING: Unknown precip unit '{source_unit}', assuming mm/timestep")
        return values / timestep_seconds


def convert_pressure(values, source_unit):
    """Convert pressure to Pa."""
    if source_unit.lower() in ["pa"]:
        return values
    elif source_unit.lower() in ["hpa", "mbar", "mb"]:
        return values * 100.0
    elif source_unit.lower() in ["kpa"]:
        return values * 1000.0
    else:
        print(f"WARNING: Unknown pressure unit '{source_unit}', assuming Pa")
        return values


def convert_humidity(values, source_unit):
    """Convert specific humidity to kg/kg."""
    if source_unit.lower() in ["kg/kg", "kg kg-1"]:
        return values
    elif source_unit.lower() in ["g/kg", "g kg-1"]:
        return values / 1000.0
    else:
        print(f"WARNING: Unknown humidity unit '{source_unit}', assuming kg/kg")
        return values


def validate_outputs(var_name, data):
    """Validate converted data is within physical bounds."""
    meta = CLASSIC_MET_VARS[var_name]
    warnings = []

    n_nan = np.sum(np.isnan(data))
    if n_nan > 0:
        warnings.append(f"{var_name}: {n_nan} NaN values detected")

    valid = data[~np.isnan(data)]
    if len(valid) > 0:
        vmin, vmax = np.min(valid), np.max(valid)
        if vmin < meta["min_valid"]:
            warnings.append(
                f"{var_name}: min value {vmin:.4f} below expected minimum {meta['min_valid']}"
            )
        if vmax > meta["max_valid"]:
            warnings.append(
                f"{var_name}: max value {vmax:.4f} above expected maximum {meta['max_valid']}"
            )

    # Specific traps
    if var_name == "tmp":
        if len(valid) > 0 and np.min(valid) > 100:
            warnings.append(
                "CRITICAL: Temperature values > 100, likely in Kelvin — must convert to Celsius!"
            )
    if var_name == "spfh":
        if len(valid) > 0 and np.max(valid) > 1.0:
            warnings.append(
                "CRITICAL: Specific humidity > 1.0, likely in g/kg — must convert to kg/kg!"
            )
    if var_name == "pres":
        if len(valid) > 0 and np.max(valid) < 2000:
            warnings.append(
                "CRITICAL: Pressure < 2000, likely in hPa or kPa — must convert to Pa!"
            )
    if var_name == "dswrf":
        n_neg = np.sum(valid < 0)
        if n_neg > 0:
            warnings.append(f"Shortwave has {n_neg} negative values — will be clipped to 0")

    return warnings


def convert_csv_to_classic(csv_file, lat, lon, start_year, end_year,
                           output_dir, timestep_minutes):
    """
    Convert site-level CSV meteorological data to CLASSIC netCDF files.

    Expected CSV columns (same order as legacy .MET format):
        Minutes, Hour, Day, Year, Shortwave(W/m2), Longwave(W/m2),
        Precipitation(kg/m2/s), Temperature(degC), Humidity(kg/kg),
        Wind(m/s), Pressure(Pa)

    Or with header row with column names.
    """
    if pd is None:
        print(json.dumps({"status": "error",
                           "errors": ["pandas required for CSV conversion"]}))
        sys.exit(1)

    # Try reading with header first
    try:
        df = pd.read_csv(csv_file)
        if df.shape[1] < 11:
            raise ValueError("Need at least 11 columns")
    except Exception:
        # Legacy format without header
        df = pd.read_csv(csv_file, header=None, sep=r"\s+|,", engine="python")

    # Assume columns in CLASSIC MET order
    cols = df.columns.tolist()
    if len(cols) >= 11:
        minute_col = cols[0]
        hour_col = cols[1]
        day_col = cols[2]
        year_col = cols[3]

        # Build datetime
        times = []
        for _, row in df.iterrows():
            yr = int(row[year_col])
            dy = int(row[day_col])
            hr = int(row[hour_col])
            mn = int(row[minute_col])
            dt = datetime(yr, 1, 1) + timedelta(days=dy - 1, hours=hr, minutes=mn)
            times.append(dt)

        # Extract variables (columns 4-10 in MET order)
        var_data = {
            "dswrf": np.array(df.iloc[:, 4], dtype=float),
            "dlwrf": np.array(df.iloc[:, 5], dtype=float),
            "pre": np.array(df.iloc[:, 6], dtype=float),
            "tmp": np.array(df.iloc[:, 7], dtype=float),
            "spfh": np.array(df.iloc[:, 8], dtype=float),
            "wind": np.array(df.iloc[:, 9], dtype=float),
            "pres": np.array(df.iloc[:, 10], dtype=float),
        }

        # Clip shortwave to >= 0
        var_data["dswrf"] = np.maximum(var_data["dswrf"], 0.0)

        # Filter by year range
        mask = np.array([(start_year <= t.year <= end_year) for t in times])
        times = [t for t, m in zip(times, mask) if m]
        for k in var_data:
            var_data[k] = var_data[k][mask]

        # Validate and write
        os.makedirs(output_dir, exist_ok=True)
        results = {"status": "success", "files": [], "warnings": []}

        for var_name, data in var_data.items():
            warns = validate_outputs(var_name, data)
            results["warnings"].extend(warns)

            out_path = os.path.join(output_dir, f"{var_name}.nc")
            create_classic_met_nc(out_path, var_name, data, times, lat, lon)
            results["files"].append(out_path)

        print(json.dumps(results, indent=2))
        return results
    else:
        print(json.dumps({"status": "error",
                           "errors": [f"CSV has {len(cols)} columns, need >= 11"]}))
        sys.exit(1)


def convert_netcdf_to_classic(source_dir, source_type, lat, lon,
                               start_year, end_year, output_dir,
                               timestep_minutes):
    """
    Convert gridded reanalysis netCDF to CLASSIC single-point netCDF files.

    Extracts the nearest grid cell to (lat, lon) from source files.
    """
    os.makedirs(output_dir, exist_ok=True)
    results = {"status": "success", "files": [], "warnings": []}

    # Source variable name mapping
    source_var_map = {
        "crujra": {
            "dswrf": ("dswrf", "W/m2"),
            "dlwrf": ("dlwrf", "W/m2"),
            "pre": ("pre", "kg m-2 s-1"),
            "tmp": ("tmp", "K"),
            "spfh": ("spfh", "kg/kg"),
            "wind": ("wind", "m/s"),
            "pres": ("pres", "Pa"),
        },
        "era5": {
            "dswrf": ("ssrd", "J/m2"),
            "dlwrf": ("strd", "J/m2"),
            "pre": ("tp", "mm/hr"),
            "tmp": ("t2m", "K"),
            "spfh": ("q", "kg/kg"),
            "wind": ("wind", "m/s"),
            "pres": ("sp", "Pa"),
        },
    }

    if source_type not in source_var_map:
        results["status"] = "error"
        results["errors"] = [f"Unknown source_type: {source_type}. "
                             f"Supported: {list(source_var_map.keys())}"]
        print(json.dumps(results, indent=2))
        sys.exit(1)

    var_map = source_var_map[source_type]
    ts_seconds = timestep_minutes * 60

    for classic_var, (src_var, src_unit) in var_map.items():
        # Find source file
        src_files = list(Path(source_dir).glob(f"*{src_var}*"))
        if not src_files:
            src_files = list(Path(source_dir).glob(f"*{classic_var}*"))
        if not src_files:
            results["warnings"].append(f"No source file found for {classic_var}")
            continue

        src_file = str(sorted(src_files)[0])

        try:
            ds = nc.Dataset(src_file, "r")

            # Find nearest grid cell
            lats = ds.variables["lat"][:]
            lons = ds.variables["lon"][:]
            lat_idx = np.argmin(np.abs(lats - lat))
            lon_idx = np.argmin(np.abs(lons - lon))

            # Read time and data
            time_var = ds.variables["time"]
            # Detect data variable (not lat, lon, time)
            data_var_name = None
            for vn in ds.variables:
                if vn not in ["lat", "lon", "time", "latitude", "longitude"]:
                    if len(ds.variables[vn].dimensions) >= 2:
                        data_var_name = vn
                        break

            if data_var_name is None:
                results["warnings"].append(f"No data variable found in {src_file}")
                ds.close()
                continue

            raw_data = ds.variables[data_var_name][:, lat_idx, lon_idx]
            raw_times = time_var[:]
            ds.close()

            # Convert time from CLASSIC format to datetime
            times_dt = []
            for t in raw_times:
                date_part = int(t)
                frac_part = t - date_part
                yr = date_part // 10000
                mo = (date_part % 10000) // 100
                dy = date_part % 100
                if mo < 1: mo = 1
                if dy < 1: dy = 1
                secs = frac_part * 86400
                try:
                    dt = datetime(yr, mo, dy) + timedelta(seconds=secs)
                    times_dt.append(dt)
                except ValueError:
                    continue

            # Filter by year
            mask = np.array([(start_year <= dt.year <= end_year) for dt in times_dt])
            times_dt = [dt for dt, m in zip(times_dt, mask) if m]
            data = raw_data[mask]

            # Unit conversions
            if classic_var == "tmp":
                data = convert_temperature(data, src_unit)
            elif classic_var == "pre":
                data = convert_precipitation(data, src_unit, ts_seconds)
            elif classic_var == "pres":
                data = convert_pressure(data, src_unit)
            elif classic_var == "spfh":
                data = convert_humidity(data, src_unit)
            elif classic_var == "dswrf":
                data = np.maximum(data, 0.0)

            # Validate
            warns = validate_outputs(classic_var, data)
            results["warnings"].extend(warns)

            # Write
            out_path = os.path.join(output_dir, f"{classic_var}.nc")
            create_classic_met_nc(out_path, classic_var, data, times_dt, lat, lon)
            results["files"].append(out_path)

        except Exception as e:
            results["warnings"].append(f"Error processing {classic_var}: {str(e)}")

    print(json.dumps(results, indent=2))
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Convert forcing data to CLASSIC netCDF format"
    )
    parser.add_argument("--source_type", required=True,
                        choices=["crujra", "era5", "csv"],
                        help="Source dataset type")
    parser.add_argument("--source_dir", default=None,
                        help="Directory with source netCDF files")
    parser.add_argument("--csv_file", default=None,
                        help="Path to CSV met file (for source_type=csv)")
    parser.add_argument("--lat", type=float, required=True,
                        help="Latitude (degrees north)")
    parser.add_argument("--lon", type=float, required=True,
                        help="Longitude (degrees east)")
    parser.add_argument("--start_year", type=int, required=True,
                        help="First year to extract")
    parser.add_argument("--end_year", type=int, required=True,
                        help="Last year to extract")
    parser.add_argument("--output_dir", required=True,
                        help="Directory for output CLASSIC met netCDF files")
    parser.add_argument("--timestep_minutes", type=int, default=30,
                        help="Forcing timestep in minutes (default: 30)")

    args = parser.parse_args()
    validate_inputs(args)

    if args.source_type == "csv":
        convert_csv_to_classic(args.csv_file, args.lat, args.lon,
                               args.start_year, args.end_year,
                               args.output_dir, args.timestep_minutes)
    else:
        convert_netcdf_to_classic(args.source_dir, args.source_type,
                                   args.lat, args.lon,
                                   args.start_year, args.end_year,
                                   args.output_dir, args.timestep_minutes)


if __name__ == "__main__":
    main()
