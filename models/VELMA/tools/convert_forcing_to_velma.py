#!/usr/bin/env python3
"""
convert_forcing_to_velma.py -- Convert global gridded climate data to VELMA
daily forcing format.

Reads CMFD (or ERA5) NetCDF files containing precipitation, temperature, and
solar radiation, masks them to a basin using a shapefile, computes basin-average
daily values, and writes output as JSON with the converted time series.

VELMA expects:
  - Precipitation:    mm/d     (daily total)
  - Temperature:      K        (Kelvin -- model converts to C internally)
  - Solar radiation:  W/m2     (daily mean, for Hargreaves PET)
  - Wind speed:       m/s      (optional, not used in current PET)
  - Surface pressure: Pa       (optional)
  - Specific humidity:kg/kg    (optional)

CRITICAL UNIT TRAPS:
  - CMFD precipitation is in kg/m2/s (= mm/s). Multiply by 86400 for mm/d.
    Forgetting this produces ~0.03 mm/d instead of ~2.7 mm/d (dt_001).
  - CMFD temperature is in K.  VELMA expects Kelvin -- do NOT subtract 273.15.
    The model converts to Celsius internally at line 454 of run_validation.py.
    Pre-converting to Celsius causes T_C = C - 273.15 = negative hundreds,
    yielding zero PET and zero ET (dt_004).
  - CMFD solar radiation is in W/m2. If source is MJ/m2/d, divide by 0.0864.
    Wrong srad units make PET off by an order of magnitude (dt_006).
  - ERA5 precipitation may be in m/d. Multiply by 1000 for mm/d (dt_003).
  - If mean precip > 50 mm/d, likely units are wrong (mm/3h not mm/d).
  - If mean precip < 0.1 mm/d, likely units are wrong (kg/m2/s not mm/d).

Usage:
    python convert_forcing_to_velma.py \\
        --forcing-dir /path/to/CMFD/Data_forcing_01dy_025deg \\
        --shapefile /path/to/basin.shp \\
        --years 1980-1990 \\
        --prec-var prec --temp-var temp --srad-var srad \\
        --prec-unit kg/m2/s --temp-unit K --srad-unit W/m2 \\
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
# Variable names encode the conversion: SOURCE_TO_TARGET.

# Precipitation: CMFD is kg/m2/s = mm/s.  Model needs mm/d.
CMFD_PRECIP_KGM2S_TO_MMDAY = 86400.0   # kg/m2/s -> mm/d  (1 kg/m2/s = 1 mm/s * 86400 s/d)
M_D_TO_MM_D = 1000.0                    # m/d -> mm/d
MM_3H_TO_MM_D = 1.0                     # mm/3h values must be SUMMED (8 per day), not scaled

# Temperature: VELMA expects Kelvin internally.
# If source is Celsius, ADD 273.15.  If source is already K, no conversion.
C_TO_K = 273.15                          # deg C -> K  (add this offset)
F_TO_C_SCALE = 5.0 / 9.0                # (F - 32) * 5/9 = C, then + 273.15 = K
F_TO_C_OFFSET = -32.0

# Solar radiation: VELMA expects W/m2.
MJ_M2_D_TO_W_M2 = 1.0 / 0.0864         # MJ/m2/d -> W/m2  (~11.574)
KJ_M2_D_TO_W_M2 = 1.0 / 86.4           # kJ/m2/d -> W/m2  (~0.01157)


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

    valid_srad_units = ["W/m2", "MJ/m2/d", "kJ/m2/d"]
    if args.srad_unit not in valid_srad_units:
        errors.append(
            f"Invalid srad unit '{args.srad_unit}'. Must be one of {valid_srad_units}")

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
      kg/m2/s -> mm/d:  multiply by CMFD_PRECIP_KGM2S_TO_MMDAY (86400)
      m/d     -> mm/d:  multiply by 1000
      mm/d    -> mm/d:  no conversion
      mm/3h   -> mm/d:  values should already be daily sums; pass through
    """
    if from_unit == "mm/d":
        return values
    elif from_unit == "kg/m2/s":
        return values * CMFD_PRECIP_KGM2S_TO_MMDAY
    elif from_unit == "m/d":
        return values * M_D_TO_MM_D
    elif from_unit == "mm/3h":
        # Assumes input is already daily sum of 8 x 3-hourly values
        return values
    else:
        raise ValueError(f"Unknown precipitation unit: {from_unit}")


def convert_temperature(values, from_unit):
    """Convert temperature to Kelvin.

    CRITICAL: VELMA expects Kelvin. The model subtracts 273.15 internally.
    Pre-converting to Celsius causes the model to compute T_C = C - 273.15,
    giving values like -258 C, which makes PET = 0 and ET = 0 (dt_004).
    """
    if from_unit == "K":
        return values
    elif from_unit == "C":
        return values + C_TO_K   # i.e., values + 273.15
    elif from_unit == "F":
        t_c = (values + F_TO_C_OFFSET) * F_TO_C_SCALE
        return t_c + C_TO_K
    else:
        raise ValueError(f"Unknown temperature unit: {from_unit}")


def convert_solar_radiation(values, from_unit):
    """Convert solar radiation to W/m2.

    CRITICAL: Wrong srad units make PET off by ~10x (dt_006, dt_007).
    CMFD srad is already in W/m2. Other sources may be in MJ/m2/d or kJ/m2/d.
    """
    if from_unit == "W/m2":
        return values
    elif from_unit == "MJ/m2/d":
        return values * MJ_M2_D_TO_W_M2
    elif from_unit == "kJ/m2/d":
        return values * KJ_M2_D_TO_W_M2
    else:
        raise ValueError(f"Unknown solar radiation unit: {from_unit}")


def load_and_mask_cmfd(forcing_dir, shapefile, years, prec_var, temp_var,
                       srad_var, file_pattern, log):
    """Load CMFD NetCDF files, mask to basin, return basin-average daily series.

    Parameters
    ----------
    forcing_dir : str
        Directory containing NetCDF files.
    shapefile : str
        Path to basin boundary shapefile.
    years : list of int
        Years to load.
    prec_var, temp_var, srad_var : str
        Variable names for precipitation, temperature, solar radiation in filenames.
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
    srad_raw : pd.Series
        Basin-average solar radiation in source units, indexed by date.
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
            log.append(f"Basin mask for {var_name}: {mask_arr.sum()} / "
                       f"{mask_arr.size} cells inside polygon")

        mask_2d = mask_2d_cache[cache_key]
        if mask_2d.sum() == 0:
            log.append("[WARN] Zero cells in polygon -- falling back to bounding box")
            mask_2d = np.ones_like(mask_2d, dtype=bool)

        # Compute basin-average time series
        data_vars = [v for v in cropped.data_vars]
        if len(data_vars) != 1:
            log.append(f"[WARN] Expected 1 data var for {var_name}, "
                       f"found {data_vars}; using first")
        vname = data_vars[0]
        data = cropped[vname].values  # (time, lat, lon)

        n_times = data.shape[0]
        basin_avg = np.zeros(n_times)
        for t in range(n_times):
            vals = data[t][mask_2d]
            vals = vals[np.isfinite(vals)]
            basin_avg[t] = np.mean(vals) if len(vals) > 0 else np.nan

        dates = pd.DatetimeIndex(cropped.time.values)
        series = pd.Series(basin_avg, index=dates, name=var_name)
        series = series[~series.index.duplicated(keep='first')]
        return series

    results = {}
    for var_name in [prec_var, temp_var, srad_var]:
        try:
            results[var_name] = load_var(var_name, years)
            log.append(f"Loaded {var_name}: {len(results[var_name])} days")
        except FileNotFoundError as e:
            log.append(f"[WARN] {e}")

    prec_raw = results.get(prec_var)
    temp_raw = results.get(temp_var)
    srad_raw = results.get(srad_var)

    return prec_raw, temp_raw, srad_raw


def validate_outputs(prec_mm_d, temp_K, srad_Wm2, log):
    """Validate converted output values for physical plausibility.

    Returns True if outputs pass basic sanity checks, False if critical
    issues are detected.
    """
    ok = True

    # --- Precipitation checks ---
    if prec_mm_d is not None:
        mean_p = np.nanmean(prec_mm_d)
        max_p = np.nanmax(prec_mm_d)

        if mean_p < 0.1:
            log.append(
                f"[CRITICAL] Mean precip = {mean_p:.4f} mm/d -- likely still in "
                "kg/m2/s (forgot x 86400). dt_001")
            ok = False
        elif mean_p > 50:
            log.append(
                f"[CRITICAL] Mean precip = {mean_p:.1f} mm/d -- likely in mm/3h "
                "not mm/d, or source units wrong. dt_002")
            ok = False

        if max_p > 500:
            log.append(
                f"[WARN] Max precip = {max_p:.1f} mm/d -- plausible for extreme "
                "events but verify units")
        if np.any(prec_mm_d < 0):
            log.append("[CRITICAL] Negative precipitation values detected")
            ok = False

    # --- Temperature checks (should be in Kelvin) ---
    if temp_K is not None:
        mean_t = np.nanmean(temp_K)
        min_t = np.nanmin(temp_K)
        max_t = np.nanmax(temp_K)

        if mean_t < 200:
            log.append(
                f"[CRITICAL] Mean temp = {mean_t:.1f} K -- this is < -73 C, "
                "likely Celsius values that weren't converted to K. dt_004")
            ok = False
        elif mean_t > 340:
            log.append(
                f"[CRITICAL] Mean temp = {mean_t:.1f} K -- this is > 67 C, "
                "likely double conversion or wrong source unit")
            ok = False
        elif 230 < mean_t < 320:
            log.append(f"Temperature range OK: [{min_t:.1f}, {max_t:.1f}] K "
                       f"= [{min_t-273.15:.1f}, {max_t-273.15:.1f}] C")
        else:
            log.append(f"[WARN] Mean temp = {mean_t:.1f} K -- unusual, verify units")

    # --- Solar radiation checks (should be in W/m2) ---
    if srad_Wm2 is not None:
        mean_r = np.nanmean(srad_Wm2)
        max_r = np.nanmax(srad_Wm2)

        if mean_r < 10:
            log.append(
                f"[CRITICAL] Mean srad = {mean_r:.1f} W/m2 -- suspiciously low, "
                "likely in MJ/m2/d (need / 0.0864). dt_006")
            ok = False
        elif mean_r > 500:
            log.append(
                f"[WARN] Mean srad = {mean_r:.1f} W/m2 -- unusually high, "
                "verify source units")

    return ok


def process(args, log):
    """Main processing pipeline: load -> convert -> validate -> write.

    Returns the result dictionary.
    """
    # Parse years
    parts = args.years.split("-")
    y_start, y_end = int(parts[0]), int(parts[1])
    years = list(range(y_start, y_end + 1))

    log.append(f"Processing VELMA forcing for {y_start}-{y_end} ({len(years)} years)")
    log.append(f"Forcing dir: {args.forcing_dir}")
    log.append(f"Shapefile: {args.shapefile}")

    # Load and mask
    prec_raw, temp_raw, srad_raw = load_and_mask_cmfd(
        args.forcing_dir, args.shapefile, years,
        args.prec_var, args.temp_var, args.srad_var,
        args.file_pattern, log)

    if prec_raw is None:
        return {"status": "error", "errors": ["No precipitation data loaded"], "log": log}
    if temp_raw is None:
        return {"status": "error", "errors": ["No temperature data loaded"], "log": log}

    # Convert units
    prec_mm_d = convert_precipitation(prec_raw.values, args.prec_unit)
    temp_K = convert_temperature(temp_raw.values, args.temp_unit)

    srad_Wm2 = None
    if srad_raw is not None:
        srad_Wm2 = convert_solar_radiation(srad_raw.values, args.srad_unit)
    else:
        log.append("[WARN] No solar radiation data. Using default 200 W/m2.")
        srad_Wm2 = np.full(len(prec_mm_d), 200.0)

    # Log conversion summary
    log.append(f"Precipitation: {args.prec_unit} -> mm/d | "
               f"mean={np.nanmean(prec_mm_d):.2f}, "
               f"max={np.nanmax(prec_mm_d):.1f} mm/d")
    log.append(f"Temperature: {args.temp_unit} -> K | "
               f"mean={np.nanmean(temp_K):.1f}, "
               f"range=[{np.nanmin(temp_K):.1f}, {np.nanmax(temp_K):.1f}] K")
    log.append(f"Solar radiation: {args.srad_unit} -> W/m2 | "
               f"mean={np.nanmean(srad_Wm2):.1f} W/m2")

    # Validate outputs
    outputs_ok = validate_outputs(prec_mm_d, temp_K, srad_Wm2, log)
    if not outputs_ok:
        log.append("[CRITICAL] Output validation failed -- check unit conversions")

    # Align dates
    dates = prec_raw.index
    if temp_raw is not None:
        dates = dates.intersection(temp_raw.index)

    n = min(len(prec_mm_d), len(temp_K), len(srad_Wm2), len(dates))
    prec_mm_d = prec_mm_d[:n]
    temp_K = temp_K[:n]
    srad_Wm2 = srad_Wm2[:n]
    dates = dates[:n]

    # Handle NaN
    nan_prec = np.isnan(prec_mm_d).sum()
    nan_temp = np.isnan(temp_K).sum()
    nan_srad = np.isnan(srad_Wm2).sum()
    if nan_prec > 0:
        log.append(f"[WARN] {nan_prec} NaN in precipitation -- filled with 0")
        prec_mm_d = np.nan_to_num(prec_mm_d, nan=0.0)
    if nan_temp > 0:
        log.append(f"[WARN] {nan_temp} NaN in temperature -- interpolated")
        temp_K = pd.Series(temp_K).interpolate().bfill().ffill().values
    if nan_srad > 0:
        log.append(f"[WARN] {nan_srad} NaN in solar radiation -- filled with 200")
        srad_Wm2 = np.nan_to_num(srad_Wm2, nan=200.0)

    # Build output
    output = {
        "dates": [d.strftime("%Y-%m-%d") for d in dates],
        "prec_mm_d": [round(float(v), 4) for v in prec_mm_d],
        "temp_K": [round(float(v), 2) for v in temp_K],
        "srad_Wm2": [round(float(v), 2) for v in srad_Wm2],
        "n_days": n,
        "year_range": f"{y_start}-{y_end}",
        "source_units": {
            "prec": args.prec_unit,
            "temp": args.temp_unit,
            "srad": args.srad_unit,
        },
        "target_units": {
            "prec": "mm/d",
            "temp": "K",
            "srad": "W/m2",
        },
        "conversion_constants": {
            "CMFD_PRECIP_KGM2S_TO_MMDAY": CMFD_PRECIP_KGM2S_TO_MMDAY,
            "C_TO_K": C_TO_K,
            "MJ_M2_D_TO_W_M2": MJ_M2_D_TO_W_M2,
        },
        "statistics": {
            "prec_mean_mm_d": round(float(np.mean(prec_mm_d)), 2),
            "prec_max_mm_d": round(float(np.max(prec_mm_d)), 1),
            "prec_annual_mm": round(float(np.mean(prec_mm_d) * 365.25), 0),
            "temp_mean_K": round(float(np.mean(temp_K)), 2),
            "temp_min_K": round(float(np.min(temp_K)), 2),
            "temp_max_K": round(float(np.max(temp_K)), 2),
            "srad_mean_Wm2": round(float(np.mean(srad_Wm2)), 1),
        },
    }

    return {"status": "success", "output": output, "log": log}


def main():
    parser = argparse.ArgumentParser(
        description="Convert CMFD/ERA5 NetCDF forcing to VELMA daily format.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
CRITICAL UNIT TRAPS:
  dt_001: CMFD precip is kg/m2/s. Multiply by 86400 for mm/d.
  dt_004: VELMA expects temperature in Kelvin. Do NOT pre-convert to Celsius.
  dt_006: Solar radiation must be in W/m2 (CMFD default). If MJ/m2/d, divide by 0.0864.
""")
    parser.add_argument("--forcing-dir", required=True,
                        help="Directory containing CMFD/ERA5 NetCDF files")
    parser.add_argument("--shapefile", required=True,
                        help="Path to basin boundary shapefile")
    parser.add_argument("--years", required=True,
                        help="Year range YYYY-YYYY (e.g. 1980-1990)")
    parser.add_argument("--prec-var", default="prec",
                        help="Precipitation variable name in filenames (default: prec)")
    parser.add_argument("--temp-var", default="temp",
                        help="Temperature variable name in filenames (default: temp)")
    parser.add_argument("--srad-var", default="srad",
                        help="Solar radiation variable name in filenames (default: srad)")
    parser.add_argument("--prec-unit", default="kg/m2/s",
                        choices=["kg/m2/s", "mm/d", "m/d", "mm/3h"],
                        help="Precipitation unit in source data (default: kg/m2/s)")
    parser.add_argument("--temp-unit", default="K",
                        choices=["K", "C", "F"],
                        help="Temperature unit in source data (default: K)")
    parser.add_argument("--srad-unit", default="W/m2",
                        choices=["W/m2", "MJ/m2/d", "kJ/m2/d"],
                        help="Solar radiation unit in source data (default: W/m2)")
    parser.add_argument("--file-pattern", default="{var}_ITPCAS-CMFD_V0200_B-01_01dy_025deg_{year}01-{year}12.nc",
                        help="Filename pattern with {var} and {year} placeholders")
    parser.add_argument("--output", required=True,
                        help="Output JSON file path")

    args = parser.parse_args()

    # Validate inputs
    errors = validate_inputs(args)
    if errors:
        result = {"status": "error", "errors": errors, "log": []}
        json.dump(result, sys.stdout, indent=2)
        sys.exit(1)

    # Process
    log = []
    result = process(args, log)

    # Write output
    output_dir = os.path.dirname(args.output)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    with open(args.output, "w") as f:
        json.dump(result, f, indent=2)

    status = result["status"]
    print(f"\n[convert_forcing_to_velma] Status: {status}")
    print(f"  Output: {args.output}")
    if status == "success":
        n = result["output"]["n_days"]
        stats = result["output"]["statistics"]
        print(f"  Days: {n}")
        print(f"  Mean precip: {stats['prec_mean_mm_d']} mm/d "
              f"({stats['prec_annual_mm']} mm/yr)")
        print(f"  Mean temp: {stats['temp_mean_K']} K "
              f"({stats['temp_mean_K'] - 273.15:.1f} C)")
        print(f"  Mean srad: {stats['srad_mean_Wm2']} W/m2")
    for entry in log:
        if "[CRITICAL]" in entry or "[WARN]" in entry:
            print(f"  {entry}")


if __name__ == "__main__":
    main()
