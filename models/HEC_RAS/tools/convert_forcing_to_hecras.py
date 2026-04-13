#!/usr/bin/env python3
"""
Convert CMFD forcing data to HEC-RAS (GR4J surrogate) input format.

Reads NetCDF forcing files (precipitation, temperature) from the CMFD dataset,
applies unit conversions and basin-averaging using a shapefile mask, and writes
a daily CSV suitable for the GR4J rainfall-runoff engine.

Unit conversions applied:
  - Precipitation: CMFD kg/m2/s -> mm/day (multiply by 86400.0)
  - Temperature: CMFD Kelvin -> Celsius (subtract 273.15)

The conversion constants are defined explicitly so that unit errors are visible
in code review and traceable in diagnostic triplets.

Usage:
  python3 convert_forcing_to_hecras.py \\
    --forcing_dir /path/to/cmfd/ \\
    --basin_shp /path/to/basin.shp \\
    --start_year 1980 --end_year 1990 \\
    --output_csv ./forcing.csv

References:
  - CMFD: China Meteorological Forcing Dataset (He et al., 2020)
  - dt_201: Precipitation kg/m2/s -> mm/day requires *86400
  - dt_202: Temperature K -> C requires -273.15
  - dt_206: Basin mask point-in-polygon can yield zero cells for small basins
  - dt_207: Negative sentinel values must be replaced before averaging
"""

import argparse
import os
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# ===========================================================================
# UNIT CONVERSION CONSTANTS (explicit for auditability)
# ===========================================================================
# CMFD precipitation is in kg/m2/s. Since 1 kg/m2 = 1 mm water depth,
# multiplying by seconds-per-day converts to mm/day.
CMFD_PRECIP_TO_MMDAY = 86400.0  # seconds/day

# CMFD temperature is in Kelvin. Subtract to get Celsius.
KELVIN_TO_CELSIUS = -273.15  # additive offset


# ===========================================================================
# Validate inputs
# ===========================================================================
def validate_inputs(args):
    """Check all input paths and parameters exist and are valid.

    Follows the validate-process-validate pattern. This function runs before
    any data processing to catch configuration errors early.

    Args:
        args: Parsed argparse namespace with forcing_dir, basin_shp,
              start_year, end_year, output_csv.

    Raises:
        SystemExit: If any validation check fails.
    """
    errors = []

    if not os.path.isdir(args.forcing_dir):
        errors.append(f"Forcing directory not found: {args.forcing_dir}")

    if not os.path.isfile(args.basin_shp):
        errors.append(f"Basin shapefile not found: {args.basin_shp}")

    if args.start_year > args.end_year:
        errors.append(
            f"start_year ({args.start_year}) must be <= end_year ({args.end_year})"
        )

    if args.start_year < 1900 or args.end_year > 2100:
        errors.append(
            f"Year range [{args.start_year}, {args.end_year}] outside plausible bounds"
        )

    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    print("[validate_inputs] All inputs valid.")
    print(f"  Forcing dir: {args.forcing_dir}")
    print(f"  Basin shp:   {args.basin_shp}")
    print(f"  Period:       {args.start_year} to {args.end_year}")


# ===========================================================================
# Basin mask computation
# ===========================================================================
def compute_basin_mask(shp_path, x_coords, y_coords):
    """Create a boolean mask of grid cells whose centers fall within the basin.

    Uses point-in-polygon test for each grid cell center against the basin
    boundary polygon(s) from the shapefile.

    Args:
        shp_path: Path to basin boundary shapefile.
        x_coords: 1D array of longitude coordinates (cell centers).
        y_coords: 1D array of latitude coordinates (cell centers).

    Returns:
        mask: 2D boolean array of shape (len(y_coords), len(x_coords)).

    Warns:
        If the mask contains zero True cells (dt_206).
    """
    import geopandas as gpd
    from shapely.geometry import Point

    basin = gpd.read_file(shp_path)
    geom = basin.geometry.unary_union

    mask = np.zeros((len(y_coords), len(x_coords)), dtype=bool)
    for j, yy in enumerate(y_coords):
        for i, xx in enumerate(x_coords):
            if geom.contains(Point(xx, yy)):
                mask[j, i] = True

    n_cells = mask.sum()
    print(f"[basin_mask] {n_cells} of {mask.size} grid cells inside basin")

    if n_cells == 0:
        print(
            "  WARNING (dt_206): Basin mask is empty! No grid cells fall within "
            "the basin polygon. Check CRS alignment and basin size vs grid resolution.",
            file=sys.stderr,
        )

    return mask


# ===========================================================================
# Read and convert forcing for one year
# ===========================================================================
def read_year_forcing(forcing_dir, year, mask):
    """Read CMFD precipitation and temperature for one year and compute basin averages.

    Applies unit conversions:
      - Precipitation: kg/m2/s -> mm/day (dt_201)
      - Temperature: K -> C (dt_202)

    Also handles:
      - Masked arrays from NetCDF fill values
      - Negative sentinel replacement (dt_207)

    Args:
        forcing_dir: Directory containing CMFD NetCDF files.
        year: Integer year to load.
        mask: 2D boolean basin mask from compute_basin_mask().

    Returns:
        dates: list of pd.Timestamp for each day.
        prec_daily: list of float, basin-averaged precipitation (mm/day).
        temp_daily: list of float, basin-averaged temperature (deg C).
    """
    import netCDF4 as nc

    prec_file = os.path.join(
        forcing_dir,
        f"prec_CMFD_V0200_B-01_01dy_025deg_{year}01-{year}12_huai.nc",
    )
    temp_file = os.path.join(
        forcing_dir,
        f"temp_CMFD_V0200_B-01_01dy_025deg_{year}01-{year}12_huai.nc",
    )

    if not os.path.isfile(prec_file):
        print(f"  WARNING: Precipitation file not found for {year}: {prec_file}")
        return [], [], []
    if not os.path.isfile(temp_file):
        print(f"  WARNING: Temperature file not found for {year}: {temp_file}")
        return [], [], []

    # Read precipitation
    ds_prec = nc.Dataset(prec_file)
    prec_raw = ds_prec.variables["prec"][:]  # shape: (time, y, x)
    ndays = prec_raw.shape[0]
    ds_prec.close()

    # Read temperature
    ds_temp = nc.Dataset(temp_file)
    temp_raw = ds_temp.variables["temp"][:]  # shape: (time, y, x) in Kelvin
    ds_temp.close()

    dates = pd.date_range(f"{year}-01-01", periods=ndays, freq="D")
    prec_daily = []
    temp_daily = []

    for t in range(ndays):
        # Extract spatial slices, handle masked arrays
        p_slice = np.ma.filled(prec_raw[t, :, :], np.nan)
        t_slice = np.ma.filled(temp_raw[t, :, :], np.nan)

        # Replace negative sentinels with NaN (dt_207)
        p_slice[p_slice < 0] = np.nan
        t_slice[t_slice < 0] = np.nan

        # Basin average with unit conversion
        # Precipitation: kg/m2/s -> mm/day (dt_201)
        basin_prec = np.nanmean(p_slice[mask]) * CMFD_PRECIP_TO_MMDAY

        # Temperature: K -> deg C (dt_202)
        basin_temp = np.nanmean(t_slice[mask]) + KELVIN_TO_CELSIUS

        prec_daily.append(basin_prec)
        temp_daily.append(basin_temp)

    return list(dates), prec_daily, temp_daily


# ===========================================================================
# Process: main conversion workflow
# ===========================================================================
def process(args):
    """Main forcing conversion workflow.

    Steps:
      1. Read grid coordinates from first NetCDF file
      2. Compute basin mask from shapefile
      3. Loop over years, reading and converting forcing data
      4. Build output DataFrame and write CSV

    Args:
        args: Parsed argparse namespace.

    Returns:
        df: pandas DataFrame with columns [prec_mm, temp_c], indexed by date.
    """
    import netCDF4 as nc

    print("=" * 60)
    print("HEC-RAS Forcing Converter (CMFD -> basin-averaged CSV)")
    print("=" * 60)

    years = list(range(args.start_year, args.end_year + 1))

    # Get grid coordinates from first available file
    first_prec = os.path.join(
        args.forcing_dir,
        f"prec_CMFD_V0200_B-01_01dy_025deg_{years[0]}01-{years[0]}12_huai.nc",
    )
    if not os.path.isfile(first_prec):
        print(f"ERROR: Cannot find first forcing file: {first_prec}", file=sys.stderr)
        sys.exit(1)

    ds0 = nc.Dataset(first_prec)
    x = ds0.variables["x"][:]
    y = ds0.variables["y"][:]
    ds0.close()

    # Compute basin mask
    print("\n[1/3] Computing basin mask...")
    mask = compute_basin_mask(args.basin_shp, x, y)

    # Load all years
    print("\n[2/3] Loading and converting forcing data...")
    all_dates = []
    all_prec = []
    all_temp = []

    for yr in years:
        print(f"  Loading {yr}...")
        dates, prec, temp = read_year_forcing(args.forcing_dir, yr, mask)
        all_dates.extend(dates)
        all_prec.extend(prec)
        all_temp.extend(temp)

    if len(all_dates) == 0:
        print("ERROR: No forcing data loaded!", file=sys.stderr)
        sys.exit(1)

    # Build output DataFrame
    print(f"\n[3/3] Building output CSV...")
    df = pd.DataFrame(
        {"prec_mm": all_prec, "temp_c": all_temp},
        index=pd.DatetimeIndex(all_dates, name="date"),
    )

    # Write output
    out_dir = os.path.dirname(args.output_csv)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    df.to_csv(args.output_csv)
    print(f"  Output: {args.output_csv}")
    print(f"  Rows: {len(df)}, Period: {df.index[0]} to {df.index[-1]}")

    return df


# ===========================================================================
# Validate outputs
# ===========================================================================
def validate_outputs(df):
    """Post-conversion validation checks on the output DataFrame.

    Checks for common silent errors in unit conversion and data quality.

    Args:
        df: pandas DataFrame with columns [prec_mm, temp_c].

    Returns:
        warnings_list: List of warning strings.
    """
    warnings_list = []

    # --- Precipitation checks ---
    mean_prec = df["prec_mm"].mean()
    annual_prec = mean_prec * 365.25
    max_prec = df["prec_mm"].max()

    print(f"\n[validate_outputs] Precipitation diagnostics:")
    print(f"  Mean daily:  {mean_prec:.2f} mm/day")
    print(f"  Annual est:  {annual_prec:.0f} mm/yr")
    print(f"  Max daily:   {max_prec:.1f} mm")

    if annual_prec < 50:
        warnings_list.append(
            f"Annual precipitation = {annual_prec:.0f} mm/yr is extremely low. "
            f"Did you forget CMFD_PRECIP_TO_MMDAY (*86400)? (dt_201)"
        )

    if annual_prec > 5000:
        warnings_list.append(
            f"Annual precipitation = {annual_prec:.0f} mm/yr is very high. "
            f"Check for double unit conversion."
        )

    if max_prec > 500:
        warnings_list.append(
            f"Max daily precip = {max_prec:.0f} mm is extreme (>500 mm/day)."
        )

    if (df["prec_mm"] < 0).any():
        n_neg = (df["prec_mm"] < 0).sum()
        warnings_list.append(
            f"{n_neg} negative precipitation values detected. "
            f"Sentinel values may not have been replaced (dt_207)."
        )

    # --- Temperature checks ---
    mean_temp = df["temp_c"].mean()

    print(f"\n[validate_outputs] Temperature diagnostics:")
    print(f"  Mean:  {mean_temp:.1f} deg C")

    if mean_temp > 100:
        warnings_list.append(
            f"Mean temperature = {mean_temp:.1f} deg C is unrealistic. "
            f"Data appears to still be in Kelvin. Apply KELVIN_TO_CELSIUS (-273.15). (dt_202)"
        )

    if mean_temp < -50:
        warnings_list.append(
            f"Mean temperature = {mean_temp:.1f} deg C is extremely cold. "
            f"Check data source and conversion."
        )

    # --- NaN checks ---
    n_nan_prec = df["prec_mm"].isna().sum()
    n_nan_temp = df["temp_c"].isna().sum()
    if n_nan_prec > 0:
        warnings_list.append(
            f"{n_nan_prec} NaN values in precipitation. "
            f"Basin mask may be empty (dt_206)."
        )
    if n_nan_temp > 0:
        warnings_list.append(
            f"{n_nan_temp} NaN values in temperature. "
            f"Basin mask may be empty (dt_206)."
        )

    # Print warnings
    for w in warnings_list:
        print(f"  WARNING: {w}")

    if not warnings_list:
        print("  All output checks passed.")

    return warnings_list


# ===========================================================================
# Main
# ===========================================================================
def main():
    parser = argparse.ArgumentParser(
        description="Convert CMFD forcing data to HEC-RAS (GR4J) input CSV"
    )
    parser.add_argument(
        "--forcing_dir",
        required=True,
        help="Directory containing CMFD NetCDF files",
    )
    parser.add_argument(
        "--basin_shp",
        required=True,
        help="Path to basin boundary shapefile",
    )
    parser.add_argument(
        "--start_year",
        type=int,
        required=True,
        help="Start year (inclusive)",
    )
    parser.add_argument(
        "--end_year",
        type=int,
        required=True,
        help="End year (inclusive)",
    )
    parser.add_argument(
        "--output_csv",
        required=True,
        help="Output CSV path for basin-averaged forcing",
    )
    args = parser.parse_args()

    # Validate-process-validate pattern
    validate_inputs(args)
    df = process(args)
    validate_outputs(df)


if __name__ == "__main__":
    main()
