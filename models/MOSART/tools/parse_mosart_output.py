#!/usr/bin/env python3
"""Parse mosartwmpy output NetCDF files and extract results to CSV.

Extracts time series of key variables at specified locations or for
entire basins. Supports spatial averaging, point extraction, and
basin-aggregated statistics.

Usage:
    # Extract discharge at a specific point
    python parse_mosart_output.py \
        --input-dir ./output/tutorial/ \
        --output discharge_timeseries.csv \
        --variable RIVER_DISCHARGE_OVER_LAND_LIQ \
        --lat 45.52 --lon -122.68

    # Extract basin-averaged storage
    python parse_mosart_output.py \
        --input-dir ./output/tutorial/ \
        --output storage_basin.csv \
        --variable STORAGE_LIQ \
        --mode basin-sum

    # Extract all variables at all points to CSV
    python parse_mosart_output.py \
        --input-dir ./output/tutorial/ \
        --output all_output.csv \
        --mode all-variables
"""

import argparse
import glob
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr


# Key output variables and their expected units
OUTPUT_VARIABLES = {
    'QSUR_LIQ': {'units': 'm3/s', 'description': 'Surface runoff'},
    'QSUB_LIQ': {'units': 'm3/s', 'description': 'Subsurface runoff'},
    'STORAGE_LIQ': {'units': 'm3', 'description': 'Total routing storage'},
    'RIVER_DISCHARGE_OVER_LAND_LIQ': {
        'units': 'm3/s', 'description': 'River discharge'},
    'channel_inflow': {'units': 'm3/s', 'description': 'Channel inflow'},
    'channel_outflow': {'units': 'm3/s', 'description': 'Channel outflow'},
    'WRM_STORAGE': {'units': 'm3', 'description': 'Reservoir storage'},
    'WRM_SUPPLY': {'units': 'm3/s', 'description': 'Water supply'},
    'WRM_DEMAND': {'units': 'm3/s', 'description': 'Water demand'},
    'WRM_DEFICIT': {'units': 'm3', 'description': 'Unmet demand'},
}


def validate_input(input_dir: str) -> list:
    """Validate that input directory contains mosartwmpy output files.

    Returns list of errors.
    """
    errors = []

    if not Path(input_dir).is_dir():
        errors.append(f"Input directory not found: {input_dir}")
        return errors

    nc_files = sorted(glob.glob(f"{input_dir}/*.nc"))
    if not nc_files:
        errors.append(f"No NetCDF files found in {input_dir}")
        return errors

    # Check first file for expected structure
    try:
        ds = xr.open_dataset(nc_files[0])
        if 'time' not in ds.dims:
            errors.append(f"First file missing 'time' dimension")
        if 'lat' not in ds.coords:
            errors.append(f"First file missing 'lat' coordinate")
        if 'lon' not in ds.coords:
            errors.append(f"First file missing 'lon' coordinate")
        ds.close()
    except Exception as e:
        errors.append(f"Failed to open first file: {e}")

    return errors


def validate_output(df: pd.DataFrame, variable: str) -> list:
    """Validate extracted data.

    Returns list of warnings.
    """
    warnings = []

    if df.empty:
        warnings.append("Output DataFrame is empty")
        return warnings

    if variable in df.columns:
        data = df[variable].values
        if np.all(np.isnan(data)):
            warnings.append(f"All values for {variable} are NaN")
        elif np.all(data[np.isfinite(data)] == 0):
            warnings.append(f"All finite values for {variable} are zero")

    return warnings


def load_output_files(input_dir: str) -> xr.Dataset:
    """Load all output NetCDF files from a directory.

    Returns merged xarray Dataset.
    """
    nc_files = sorted(glob.glob(f"{input_dir}/*.nc"))
    if not nc_files:
        raise FileNotFoundError(f"No NetCDF files in {input_dir}")

    print(f"[parse_output] Loading {len(nc_files)} output files...")
    ds = xr.open_mfdataset(nc_files, combine='by_coords')
    return ds


def extract_point_timeseries(ds: xr.Dataset, variable: str,
                             lat: float, lon: float) -> pd.DataFrame:
    """Extract time series at the nearest grid point.

    Returns DataFrame with time index and variable column.
    """
    if variable not in ds:
        available = [v for v in ds.data_vars if v in OUTPUT_VARIABLES]
        raise ValueError(f"Variable '{variable}' not found. "
                         f"Available: {available}")

    # Select nearest point
    point = ds[variable].sel(lat=lat, lon=lon, method='nearest')
    actual_lat = float(point.coords['lat'])
    actual_lon = float(point.coords['lon'])
    print(f"[parse_output] Selected point: lat={actual_lat}, lon={actual_lon} "
          f"(requested: {lat}, {lon})")

    df = point.to_dataframe().reset_index()
    df = df[['time', variable]].set_index('time')
    return df


def extract_basin_sum(ds: xr.Dataset, variable: str) -> pd.DataFrame:
    """Extract basin-wide sum of a variable over time.

    Returns DataFrame with time index and summed variable.
    """
    if variable not in ds:
        raise ValueError(f"Variable '{variable}' not found in dataset")

    summed = ds[variable].sum(dim=['lat', 'lon'])
    df = summed.to_dataframe().reset_index()
    df = df[['time', variable]].set_index('time')
    df.columns = [f'{variable}_sum']
    return df


def extract_all_variables(ds: xr.Dataset, lat: float = None,
                          lon: float = None) -> pd.DataFrame:
    """Extract all available output variables.

    If lat/lon provided, extract at that point. Otherwise, spatial sum.
    """
    frames = []
    available = [v for v in ds.data_vars if v in OUTPUT_VARIABLES]

    for var in available:
        try:
            if lat is not None and lon is not None:
                df = extract_point_timeseries(ds, var, lat, lon)
            else:
                df = extract_basin_sum(ds, var)
            frames.append(df)
        except Exception as e:
            print(f"[parse_output] Skipping {var}: {e}")

    if not frames:
        raise ValueError("No variables could be extracted")

    return pd.concat(frames, axis=1)


def compute_summary_stats(df: pd.DataFrame) -> dict:
    """Compute summary statistics for extracted data."""
    stats = {}
    for col in df.columns:
        data = df[col].dropna()
        if len(data) > 0:
            stats[col] = {
                'min': float(data.min()),
                'max': float(data.max()),
                'mean': float(data.mean()),
                'std': float(data.std()),
                'n_timesteps': len(data),
            }
    return stats


def parse_output(input_dir: str, output_path: str,
                 variable: str = None, mode: str = 'point',
                 lat: float = None, lon: float = None) -> dict:
    """Main entry point for parsing mosartwmpy output.

    Args:
        input_dir: Directory containing output .nc files
        output_path: Path for output CSV
        variable: Variable to extract (None for all)
        mode: Extraction mode (point, basin-sum, all-variables)
        lat: Latitude for point extraction
        lon: Longitude for point extraction

    Returns:
        Dictionary with extraction summary
    """
    # Validate input
    errors = validate_input(input_dir)
    if errors:
        raise ValueError("Input validation failed:\n  " +
                         "\n  ".join(errors))

    # Load data
    ds = load_output_files(input_dir)

    # Extract based on mode
    if mode == 'all-variables':
        df = extract_all_variables(ds, lat, lon)
    elif mode == 'basin-sum':
        if variable is None:
            variable = 'RIVER_DISCHARGE_OVER_LAND_LIQ'
        df = extract_basin_sum(ds, variable)
    else:  # point mode
        if lat is None or lon is None:
            raise ValueError("Point mode requires --lat and --lon")
        if variable is None:
            variable = 'RIVER_DISCHARGE_OVER_LAND_LIQ'
        df = extract_point_timeseries(ds, variable, lat, lon)

    # Validate output
    if variable:
        warnings = validate_output(df, variable)
        for w in warnings:
            print(f"[parse_output] WARNING: {w}")

    # Compute stats
    stats = compute_summary_stats(df)

    # Write CSV
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path)
    print(f"[parse_output] Written to {output_path}")
    print(f"[parse_output] {len(df)} timesteps, {len(df.columns)} variables")

    ds.close()
    return {
        'output_path': output_path,
        'n_timesteps': len(df),
        'variables': list(df.columns),
        'stats': stats,
    }


def main():
    parser = argparse.ArgumentParser(
        description='Parse mosartwmpy output to CSV')
    parser.add_argument('--input-dir', required=True,
                        help='Directory with output .nc files')
    parser.add_argument('--output', required=True,
                        help='Output CSV path')
    parser.add_argument('--variable', default=None,
                        help='Variable to extract')
    parser.add_argument('--mode', default='point',
                        choices=['point', 'basin-sum', 'all-variables'],
                        help='Extraction mode')
    parser.add_argument('--lat', type=float, default=None,
                        help='Latitude for point extraction')
    parser.add_argument('--lon', type=float, default=None,
                        help='Longitude for point extraction')

    args = parser.parse_args()

    try:
        result = parse_output(
            args.input_dir, args.output, args.variable,
            args.mode, args.lat, args.lon,
        )
        print("[parse_output] SUCCESS")
        sys.exit(0)
    except Exception as e:
        print(f"[parse_output] FAILED: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
