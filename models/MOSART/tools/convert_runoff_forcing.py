#!/usr/bin/env python3
"""Convert generic runoff forcing data to mosartwmpy input format.

Converts VIC, CLM, or generic gridded runoff data to the NetCDF format
expected by mosartwmpy. Handles unit conversion from various source formats
(mm/day, mm/hr, m3/s, kg/m2/s) to the required mm/s.

Usage:
    python convert_runoff_forcing.py \
        --input /path/to/source_runoff.nc \
        --output /path/to/mosart_runoff.nc \
        --source-type vic \
        --surface-var RUNOFF \
        --subsurface-var BASEFLOW \
        --source-units mm/day
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import xarray as xr


# Unit conversion factors to mm/s
UNIT_CONVERSIONS = {
    'mm/s': 1.0,
    'mm/day': 1.0 / 86400.0,
    'mm/hr': 1.0 / 3600.0,
    'mm/h': 1.0 / 3600.0,
    'm/s': 1000.0,
    'm/day': 1000.0 / 86400.0,
    'kg/m2/s': 1.0,         # 1 kg/m2/s = 1 mm/s for water
    'kg/m2/day': 1.0 / 86400.0,
}


def validate_input(ds: xr.Dataset, surface_var: str, subsurface_var: str,
                   time_var: str, lat_var: str, lon_var: str) -> list:
    """Validate that input dataset has required variables and dimensions.

    Returns list of validation errors (empty if valid).
    """
    errors = []

    if surface_var not in ds:
        errors.append(f"Surface runoff variable '{surface_var}' not found. "
                      f"Available: {list(ds.data_vars)}")
    if subsurface_var not in ds:
        errors.append(f"Subsurface runoff variable '{subsurface_var}' not found. "
                      f"Available: {list(ds.data_vars)}")
    if time_var not in ds.dims and time_var not in ds.coords:
        errors.append(f"Time coordinate '{time_var}' not found. "
                      f"Available dims: {list(ds.dims)}, coords: {list(ds.coords)}")
    if lat_var not in ds.dims and lat_var not in ds.coords:
        errors.append(f"Latitude coordinate '{lat_var}' not found.")
    if lon_var not in ds.dims and lon_var not in ds.coords:
        errors.append(f"Longitude coordinate '{lon_var}' not found.")

    return errors


def validate_output(ds: xr.Dataset) -> list:
    """Validate that output dataset meets mosartwmpy requirements.

    Returns list of validation errors.
    """
    errors = []

    required_vars = ['QOVER', 'QDRAI']
    for var in required_vars:
        if var not in ds:
            errors.append(f"Output missing required variable: {var}")
            continue
        data = ds[var].values
        if np.all(np.isnan(data)):
            errors.append(f"Output variable {var} is entirely NaN")
        if np.any(data[np.isfinite(data)] < 0):
            neg_count = np.sum(data[np.isfinite(data)] < 0)
            errors.append(f"Output variable {var} has {neg_count} negative values "
                          f"(min={np.nanmin(data):.6e})")

    for coord in ['time', 'lat', 'lon']:
        if coord not in ds.coords:
            errors.append(f"Output missing required coordinate: {coord}")

    # Check units are mm/s (reasonable range check)
    for var in required_vars:
        if var in ds:
            max_val = float(np.nanmax(ds[var].values))
            if max_val > 1.0:
                errors.append(
                    f"WARNING: {var} max={max_val:.4f} mm/s seems high. "
                    f"Verify units are mm/s (not mm/day or m/s)."
                )

    return errors


def convert_runoff(input_path: str, output_path: str, source_type: str,
                   surface_var: str, subsurface_var: str,
                   source_units: str, wetland_var: str = None,
                   time_var: str = 'time', lat_var: str = 'lat',
                   lon_var: str = 'lon') -> dict:
    """Convert runoff data to mosartwmpy format.

    Args:
        input_path: Path to source NetCDF file
        output_path: Path for output NetCDF file
        source_type: Source model type (vic, clm, generic)
        surface_var: Name of surface runoff variable in source
        subsurface_var: Name of subsurface runoff variable in source
        source_units: Units of source data (mm/s, mm/day, etc.)
        wetland_var: Optional name of wetland runoff variable
        time_var: Name of time dimension
        lat_var: Name of latitude dimension
        lon_var: Name of longitude dimension

    Returns:
        Dictionary with conversion statistics
    """
    # Validate unit conversion factor exists
    if source_units not in UNIT_CONVERSIONS:
        raise ValueError(
            f"Unknown source units: {source_units}. "
            f"Supported: {list(UNIT_CONVERSIONS.keys())}"
        )

    conversion_factor = UNIT_CONVERSIONS[source_units]
    print(f"[convert_runoff] Unit conversion: {source_units} -> mm/s "
          f"(factor={conversion_factor})")

    # Open source dataset
    ds = xr.open_dataset(input_path)

    # Validate input
    input_errors = validate_input(ds, surface_var, subsurface_var,
                                  time_var, lat_var, lon_var)
    if input_errors:
        ds.close()
        raise ValueError("Input validation failed:\n  " +
                         "\n  ".join(input_errors))

    # Apply unit conversion
    surface = ds[surface_var].values * conversion_factor
    subsurface = ds[subsurface_var].values * conversion_factor

    # Replace NaN with 0 (mosartwmpy expects finite values)
    surface = np.where(np.isfinite(surface), surface, 0.0)
    subsurface = np.where(np.isfinite(subsurface), subsurface, 0.0)

    # Clip negative values to 0
    surface = np.maximum(surface, 0.0)
    subsurface = np.maximum(subsurface, 0.0)

    # Build output dataset
    coords = {
        'time': ds[time_var].values,
        'lat': ds[lat_var].values if lat_var in ds.dims else ds.coords[lat_var].values,
        'lon': ds[lon_var].values if lon_var in ds.dims else ds.coords[lon_var].values,
    }

    out_vars = {
        'QOVER': (['time', 'lat', 'lon'], surface, {
            'units': 'mm/s',
            'long_name': 'Surface runoff',
            'source_variable': surface_var,
            'source_units': source_units,
        }),
        'QDRAI': (['time', 'lat', 'lon'], subsurface, {
            'units': 'mm/s',
            'long_name': 'Subsurface runoff',
            'source_variable': subsurface_var,
            'source_units': source_units,
        }),
    }

    if wetland_var and wetland_var in ds:
        wetland = ds[wetland_var].values * conversion_factor
        wetland = np.where(np.isfinite(wetland), wetland, 0.0)
        out_vars['QGWL'] = (['time', 'lat', 'lon'], wetland, {
            'units': 'mm/s',
            'long_name': 'Wetland/glacier/lake runoff',
            'source_variable': wetland_var,
            'source_units': source_units,
        })

    out_ds = xr.Dataset(out_vars, coords=coords)
    out_ds.attrs['source_type'] = source_type
    out_ds.attrs['source_file'] = str(input_path)
    out_ds.attrs['conversion_factor'] = conversion_factor
    out_ds.attrs['created_by'] = 'mosartwmpy KI convert_runoff_forcing'

    # Validate output
    output_errors = validate_output(out_ds)
    warnings = [e for e in output_errors if e.startswith('WARNING')]
    errors = [e for e in output_errors if not e.startswith('WARNING')]
    if errors:
        ds.close()
        raise ValueError("Output validation failed:\n  " + "\n  ".join(errors))
    for w in warnings:
        print(f"[convert_runoff] {w}")

    # Write output
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    out_ds.to_netcdf(output_path)

    stats = {
        'surface_max_mm_s': float(np.nanmax(surface)),
        'surface_mean_mm_s': float(np.nanmean(surface)),
        'subsurface_max_mm_s': float(np.nanmax(subsurface)),
        'subsurface_mean_mm_s': float(np.nanmean(subsurface)),
        'time_steps': len(coords['time']),
        'grid_cells': len(coords['lat']) * len(coords['lon']),
        'conversion_factor': conversion_factor,
    }

    ds.close()
    out_ds.close()

    print(f"[convert_runoff] Output written to {output_path}")
    print(f"[convert_runoff] Stats: {stats}")
    return stats


def main():
    parser = argparse.ArgumentParser(
        description='Convert runoff forcing to mosartwmpy format')
    parser.add_argument('--input', required=True, help='Input NetCDF path')
    parser.add_argument('--output', required=True, help='Output NetCDF path')
    parser.add_argument('--source-type', default='generic',
                        choices=['vic', 'clm', 'generic'],
                        help='Source model type')
    parser.add_argument('--surface-var', default='QOVER',
                        help='Surface runoff variable name')
    parser.add_argument('--subsurface-var', default='QDRAI',
                        help='Subsurface runoff variable name')
    parser.add_argument('--source-units', default='mm/s',
                        help=f'Source units: {list(UNIT_CONVERSIONS.keys())}')
    parser.add_argument('--wetland-var', default=None,
                        help='Optional wetland runoff variable name')
    parser.add_argument('--time-var', default='time')
    parser.add_argument('--lat-var', default='lat')
    parser.add_argument('--lon-var', default='lon')

    args = parser.parse_args()

    try:
        stats = convert_runoff(
            args.input, args.output, args.source_type,
            args.surface_var, args.subsurface_var,
            args.source_units, args.wetland_var,
            args.time_var, args.lat_var, args.lon_var,
        )
        print("[convert_runoff] SUCCESS")
        sys.exit(0)
    except Exception as e:
        print(f"[convert_runoff] FAILED: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
