#!/usr/bin/env python3
"""
convert_forcing_to_kineros2.py -- Convert global gridded climate data to
KINEROS2 daily forcing format.

Reads CMFD (or ERA5) NetCDF files containing precipitation and temperature,
masks them to a basin using a shapefile, computes basin-average daily values,
and writes output as JSON with the converted time series.

KINEROS2 expects:
  - Precipitation: mm/d  (daily total)
  - Temperature:   deg C (daily mean)

CRITICAL UNIT TRAPS:
  - CMFD precipitation is in kg/m2/s (= mm/s). Multiply by 86400 for mm/d.
    Forgetting this produces ~0.03 mm/d instead of ~2.7 mm/d (dt_001).
  - CMFD temperature is in K. Subtract 273.15 for deg C (dt_004).
    Without this, Hamon PET receives ~280 deg C and produces absurd values.
  - ERA5 precipitation may be in m/d. Multiply by 1000 for mm/d (dt_003).
  - If mean precip > 50 mm/d, likely units are wrong (mm/3h not mm/d).
  - If mean precip < 0.1 mm/d, likely units are wrong (kg/m2/s not mm/d).

Usage:
    python convert_forcing_to_kineros2.py \\
        --forcing-dir /path/to/CMFD/Data_forcing_01dy_025deg \\
        --shapefile /path/to/basin.shp \\
        --years 1980-1990 \\
        --prec-var prec --temp-var temp \\
        --prec-unit kg/m2/s --temp-unit K \\
        --output forcing.json
"""

import argparse
import json
import os
import sys
from datetime import datetime

import numpy as np

try:
    import pandas as pd
except ImportError:
    pd = None

try:
    import xarray as xr
except ImportError:
    xr = None

try:
    import geopandas as gpd
    from shapely.geometry import Point
except ImportError:
    gpd = None


# ---- Unit conversion constants ------------------------------------------------
# Each constant converts FROM the source unit TO the model's expected unit.
# The variable name encodes the conversion: SOURCE_TO_TARGET.

KG_M2_S_TO_MM_D = 86400.0      # kg/m2/s -> mm/d  (1 kg/m2/s = 1 mm/s * 86400 s/d)
M_D_TO_MM_D = 1000.0           # m/d -> mm/d
MM_3H_TO_MM_D = 1.0            # mm/3h values must be SUMMED (8 per day), not scaled
K_TO_C = -273.15               # K -> deg C  (add this offset)
F_TO_C_SCALE = 5.0 / 9.0       # (F - 32) * 5/9 = C
F_TO_C_OFFSET = -32.0          # subtract 32 before scaling


def validate_inputs(args):
    """Validate all inputs before processing. Returns list of errors."""
    errors = []

    if not os.path.isdir(args.forcing_dir):
        errors.append(f"Forcing directory does not exist: {args.forcing_dir}")

    if not os.path.isfile(args.shapefile):
        errors.append(f"Shapefile does not exist: {args.shapefile}")

    # Parse year range
    try:
        parts = args.years.split("-")
        y_start, y_end = int(parts[0]), int(parts[1])
        if y_start > y_end:
            errors.append(f"Start year {y_start} > end year {y_end}")
        if y_start < 1900 or y_end > 2100:
            errors.append(f"Year range {y_start}-{y_end} looks implausible")
    except (ValueError, IndexError):
        errors.append(f"Cannot parse year range '{args.years}'. Use YYYY-YYYY format.")

    valid_prec_units = ["kg/m2/s", "mm/d", "m/d", "mm/3h"]
    if args.prec_unit not in valid_prec_units:
        errors.append(
            f"Invalid prec unit '{args.prec_unit}'. Must be one of {valid_prec_units}")

    valid_temp_units = ["K", "C", "F"]
    if args.temp_unit not in valid_temp_units:
        errors.append(
            f"Invalid temp unit '{args.temp_unit}'. Must be one of {valid_temp_units}")

    if xr is None:
        errors.append("xarray is required but not installed. Run: pip install xarray")

    if gpd is None:
        errors.append("geopandas is required but not installed. Run: pip install geopandas")

    if pd is None:
        errors.append("pandas is required but not installed. Run: pip install pandas")

    return errors


def convert_precipitation(values, from_unit):
    """Convert precipitation to mm/d.

    CRITICAL: Getting this wrong causes discharge to be off by orders of
    magnitude. The model runs without error -- only the results are wrong.

    Conversion factors:
      kg/m2/s -> mm/d:  multiply by 86400   (1 kg/m2 = 1 mm water depth)
      m/d     -> mm/d:  multiply by 1000
      mm/d    -> mm/d:  no conversion
      mm/3h   -> mm/d:  values should already be daily sums; pass through
    """
    if from_unit == "mm/d":
        return values
    elif from_unit == "kg/m2/s":
        return values * KG_M2_S_TO_MM_D
    elif from_unit == "m/d":
        return values * M_D_TO_MM_D
    elif from_unit == "mm/3h":
        # Assumes input is already daily sum of 8 x 3-hourly values
        return values
    else:
        raise ValueError(f"Unknown precipitation unit: {from_unit}")


def convert_temperature(values, from_unit):
    """Convert temperature to deg C.

    CRITICAL: Kelvin values (~280) fed to Hamon PET produce absurd
    evapotranspiration. The model does NOT warn about this.
    """
    if from_unit == "C":
        return values
    elif from_unit == "K":
        return values + K_TO_C   # i.e., values - 273.15
    elif from_unit == "F":
        return (values + F_TO_C_OFFSET) * F_TO_C_SCALE
    else:
        raise ValueError(f"Unknown temperature unit: {from_unit}")


def load_and_mask_cmfd(forcing_dir, shapefile, years, prec_var, temp_var,
                       file_pattern, log):
    """Load CMFD NetCDF files, mask to basin, return basin-average daily series.

    Parameters
    ----------
    forcing_dir : str
        Directory containing NetCDF files.
    shapefile : str
        Path to basin boundary shapefile.
    years : list of int
        Years to load.
    prec_var, temp_var : str
        Variable names for precipitation and temperature in filenames.
    file_pattern : str
        Filename pattern with {var} and {year} placeholders.
    log : list
        Accumulates log messages.

    Returns
    -------
    prec_raw : pd.Series
        Basin-average precipitation in source units, indexed by date.
    temp_raw : pd.Series
        Basin-average temperature in source units, indexed by date.
    """
    gdf = gpd.read_file(shapefile)
    basin_bounds = gdf.total_bounds  # [minx, miny, maxx, maxy]
    log.append(f"Basin bounds: lon [{basin_bounds[0]:.2f}, {basin_bounds[2]:.2f}], "
               f"lat [{basin_bounds[1]:.2f}, {basin_bounds[3]:.2f}]")

    basin_geom = gdf.geometry.iloc[0]
    mask_2d_cache = {}

    def load_var(var_name, years_list):
        """Load a single variable across years, mask, return basin-avg series."""
        datasets = []
        for yr in years_list:
            fn = file_pattern.format(var=var_name, year=yr)
            full_path = os.path.join(forcing_dir, fn)
            if not os.path.isfile(full_path):
                log.append(f"[WARN] File not found: {full_path}")
                continue
            ds = xr.open_dataset(full_path)
            datasets.append(ds)

        if not datasets:
            raise FileNotFoundError(
                f"No files found for variable '{var_name}' in {forcing_dir}")

        combined = xr.concat(datasets, dim="time")

        # Determine coordinate names (CMFD uses 'x' and 'y')
        lon_name = "x" if "x" in combined.dims else "longitude"
        lat_name = "y" if "y" in combined.dims else "latitude"

        # Crop to basin bounding box with buffer
        buf = 0.125
        lon_vals = combined[lon_name].values
        lat_vals = combined[lat_name].values
        mask_x = (lon_vals >= basin_bounds[0] - buf) & (lon_vals <= basin_bounds[2] + buf)
        mask_y = (lat_vals >= basin_bounds[1] - buf) & (lat_vals <= basin_bounds[3] + buf)
        cropped = combined.isel(
            **{lon_name: mask_x, lat_name: mask_y})

        # Build 2D mask from shapefile geometry (cached)
        cache_key = (cropped[lon_name].shape, cropped[lat_name].shape)
        if cache_key not in mask_2d_cache:
            lons, lats = np.meshgrid(
                cropped[lon_name].values, cropped[lat_name].values)
            mask_arr = np.zeros(lons.shape, dtype=bool)
            for i in range(lons.shape[0]):
                for j in range(lons.shape[1]):
                    mask_arr[i, j] = basin_geom.contains(
                        Point(lons[i, j], lats[i, j]))
            mask_2d_cache[cache_key] = mask_arr
            log.append(f"  {var_name}: {mask_arr.sum()} grid cells inside basin")

        mask_arr = mask_2d_cache[cache_key]

        # Compute basin-average
        data_var = list(cropped.data_vars)[0]
        vals = cropped[data_var].values  # shape: (time, lat, lon)
        basin_avg = np.nanmean(vals[:, mask_arr], axis=1)

        times = pd.DatetimeIndex(cropped.time.values).normalize()

        for ds in datasets:
            ds.close()

        return pd.Series(basin_avg, index=times, name=var_name)

    prec_raw = load_var(prec_var, years)
    temp_raw = load_var(temp_var, years)

    return prec_raw, temp_raw


def validate_outputs(prec_mmd, temp_c, log):
    """Check converted values for physical plausibility.

    Returns True if no critical errors found, False otherwise.
    """
    warnings = []
    critical = False

    # -- Precipitation checks --
    mean_p = float(np.nanmean(prec_mmd))
    max_p = float(np.nanmax(prec_mmd))
    min_p = float(np.nanmin(prec_mmd))

    if mean_p > 50.0:
        warnings.append(
            f"[CRITICAL] Mean precip = {mean_p:.2f} mm/d -- possible unit error. "
            "If source is mm/3h, values may not have been summed to daily (dt_002).")
        critical = True
    elif mean_p > 20.0:
        warnings.append(
            f"[WARN] Mean precip = {mean_p:.2f} mm/d -- unusually high, verify units.")

    if 0 < mean_p < 0.1:
        warnings.append(
            f"[CRITICAL] Mean precip = {mean_p:.4f} mm/d -- likely still in kg/m2/s "
            "(multiply by 86400) (dt_001).")
        critical = True

    if min_p < 0:
        warnings.append(
            f"[WARN] Negative precipitation detected (min = {min_p:.4f} mm/d).")

    if max_p > 500:
        warnings.append(
            f"[WARN] Max precip = {max_p:.1f} mm/d -- physically unlikely for daily total.")

    # -- Temperature checks --
    mean_t = float(np.nanmean(temp_c))
    max_t = float(np.nanmax(temp_c))
    min_t = float(np.nanmin(temp_c))

    if mean_t > 100:
        warnings.append(
            f"[CRITICAL] Mean temp = {mean_t:.1f} deg C -- data almost certainly "
            "still in Kelvin (subtract 273.15) (dt_004).")
        critical = True

    if min_t < -80:
        warnings.append(
            f"[WARN] Min temp = {min_t:.1f} deg C -- implausibly cold, check data.")

    if max_t > 60:
        warnings.append(
            f"[WARN] Max temp = {max_t:.1f} deg C -- implausibly hot, check conversion.")

    log.extend(warnings)
    return not critical


def process(args):
    """Main processing: load NetCDF, mask to basin, convert units, output JSON."""
    log = []

    # Parse year range
    parts = args.years.split("-")
    y_start, y_end = int(parts[0]), int(parts[1])
    years = list(range(y_start, y_end + 1))
    log.append(f"Processing years {y_start}-{y_end} ({len(years)} years)")

    # File naming pattern for CMFD
    # Default: {var}_CMFD_V0200_B-01_01dy_025deg_{year}01-{year}12_huai.nc
    file_pattern = args.file_pattern
    log.append(f"File pattern: {file_pattern}")

    # Load and mask
    try:
        prec_raw, temp_raw = load_and_mask_cmfd(
            args.forcing_dir, args.shapefile, years,
            args.prec_var, args.temp_var, file_pattern, log)
    except FileNotFoundError as e:
        return {"status": "error", "errors": [str(e)], "log": log}
    except Exception as e:
        return {"status": "error", "errors": [f"Failed to load forcing: {e}"], "log": log}

    # Convert units
    prec_mmd = convert_precipitation(prec_raw.values, args.prec_unit)
    temp_c = convert_temperature(temp_raw.values, args.temp_unit)

    log.append(f"Precipitation converted from {args.prec_unit} to mm/d")
    log.append(f"Temperature converted from {args.temp_unit} to deg C")
    log.append(f"Forcing period: {prec_raw.index[0].date()} to {prec_raw.index[-1].date()}")
    log.append(f"  Mean daily precip: {np.nanmean(prec_mmd):.2f} mm/d")
    log.append(f"  Mean daily temp:   {np.nanmean(temp_c):.1f} deg C")
    log.append(f"  Total timesteps:   {len(prec_mmd)}")

    # Validate outputs
    outputs_ok = validate_outputs(prec_mmd, temp_c, log)

    # Build output
    dates = [d.strftime("%Y-%m-%d") for d in prec_raw.index]
    result = {
        "status": "success" if outputs_ok else "warning",
        "output": {
            "dates": dates,
            "prec_mm_d": [round(float(v), 4) for v in prec_mmd],
            "temp_deg_c": [round(float(v), 4) for v in temp_c],
            "n_timesteps": len(dates),
            "start_date": dates[0],
            "end_date": dates[-1],
            "prec_unit": "mm/d",
            "temp_unit": "deg_C",
            "source_prec_unit": args.prec_unit,
            "source_temp_unit": args.temp_unit,
            "stats": {
                "prec_mean_mm_d": round(float(np.nanmean(prec_mmd)), 4),
                "prec_max_mm_d": round(float(np.nanmax(prec_mmd)), 4),
                "prec_total_mm": round(float(np.nansum(prec_mmd)), 2),
                "temp_mean_c": round(float(np.nanmean(temp_c)), 2),
                "temp_min_c": round(float(np.nanmin(temp_c)), 2),
                "temp_max_c": round(float(np.nanmax(temp_c)), 2),
            },
        },
        "log": log,
    }

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Convert CMFD/ERA5 forcing data to KINEROS2 daily format")
    parser.add_argument("--forcing-dir", required=True,
                        help="Directory containing NetCDF forcing files")
    parser.add_argument("--shapefile", required=True,
                        help="Basin boundary shapefile for spatial masking")
    parser.add_argument("--years", required=True,
                        help="Year range to process (e.g., 1980-1990)")
    parser.add_argument("--prec-var", default="prec",
                        help="Precipitation variable name in filenames (default: prec)")
    parser.add_argument("--temp-var", default="temp",
                        help="Temperature variable name in filenames (default: temp)")
    parser.add_argument("--prec-unit", default="kg/m2/s",
                        choices=["kg/m2/s", "mm/d", "m/d", "mm/3h"],
                        help="Source precipitation unit (default: kg/m2/s)")
    parser.add_argument("--temp-unit", default="K",
                        choices=["K", "C", "F"],
                        help="Source temperature unit (default: K)")
    parser.add_argument("--file-pattern",
                        default="{var}_CMFD_V0200_B-01_01dy_025deg_{year}01-{year}12_huai.nc",
                        help="NetCDF filename pattern with {var} and {year} placeholders")
    parser.add_argument("--output", required=True,
                        help="Output JSON file path")

    args = parser.parse_args()

    # Step 1: validate inputs
    errors = validate_inputs(args)
    if errors:
        result = {"status": "error", "errors": errors}
        print(json.dumps(result, indent=2))
        sys.exit(1)

    # Step 2: process
    result = process(args)

    # Step 3: write output
    out_dir = os.path.dirname(args.output)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    with open(args.output, "w") as f:
        json.dump(result, f, indent=2)

    # Print summary to stdout
    if result["status"] == "error":
        print(json.dumps(result, indent=2))
        sys.exit(1)
    else:
        for line in result.get("log", []):
            print(line)
        print(f"\nOutput written to {args.output}")


if __name__ == "__main__":
    main()
