#!/usr/bin/env python3
"""Convert grid/parameter data to mosartwmpy domain file format.

Builds or validates a mosartwmpy-compatible grid domain NetCDF file from
various upstream sources (MERIT-Hydro, HydroSHEDS, manually prepared data).
Ensures all required fields are present with correct units.

Usage:
    python convert_grid_parameters.py \
        --input /path/to/source_grid.nc \
        --output /path/to/mosart_grid.nc \
        --validate-only

    python convert_grid_parameters.py \
        --input /path/to/merit_hydro_data/ \
        --output /path/to/mosart_grid.nc \
        --source-type merit
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import xarray as xr


# Required grid variables for mosartwmpy
REQUIRED_VARIABLES = {
    'ID': {'units': '-', 'description': 'Grid cell unique identifier'},
    'dnID': {'units': '-', 'description': 'Downstream cell ID (-1 for outlet)'},
    'fdir': {'units': '-', 'description': 'D8 flow direction'},
    'area': {'units': 'm2', 'description': 'Local drainage area'},
    'areaTotal': {'units': 'm2', 'description': 'Total upstream area (multi-flow)'},
    'areaTotal2': {'units': 'm2', 'description': 'Total upstream area (single-flow)'},
    'frac': {'units': '0-1', 'description': 'Drainage/land fraction'},
    'gxr': {'units': 'm-1', 'description': 'Drainage density'},
    'hslp': {'units': 'm/m', 'description': 'Hillslope topographic slope'},
    'nh': {'units': 's/m^(1/3)', 'description': 'Hillslope Manning roughness'},
    'tslp': {'units': 'm/m', 'description': 'Subnetwork (tributary) slope'},
    'twid': {'units': 'm', 'description': 'Subnetwork bankfull width'},
    'nt': {'units': 's/m^(1/3)', 'description': 'Subnetwork Manning roughness'},
    'rlen': {'units': 'm', 'description': 'Main channel length'},
    'rslp': {'units': 'm/m', 'description': 'Main channel slope'},
    'rwid': {'units': 'm', 'description': 'Main channel bankfull width'},
    'rwid0': {'units': 'm', 'description': 'Floodplain width'},
    'rdep': {'units': 'm', 'description': 'Main channel bankfull depth'},
    'nr': {'units': 's/m^(1/3)', 'description': 'Main channel Manning roughness'},
}

# Typical Manning's n values for reference
MANNING_DEFAULTS = {
    'hillslope': 0.075,       # overland flow
    'subnetwork': 0.035,      # tributaries
    'channel': 0.030,         # main channel
}


def validate_grid(ds: xr.Dataset) -> list:
    """Validate grid dataset for mosartwmpy compatibility.

    Returns list of errors/warnings (empty if valid).
    """
    issues = []

    # Check coordinates
    if 'lat' not in ds.coords and 'lat' not in ds.dims:
        issues.append("ERROR: Missing 'lat' coordinate")
    if 'lon' not in ds.coords and 'lon' not in ds.dims:
        issues.append("ERROR: Missing 'lon' coordinate")

    # Check required variables
    for var, info in REQUIRED_VARIABLES.items():
        if var not in ds:
            issues.append(f"ERROR: Missing required variable '{var}' "
                          f"({info['description']})")
            continue

        data = ds[var].values.flatten()
        finite = data[np.isfinite(data)]

        if len(finite) == 0:
            issues.append(f"ERROR: Variable '{var}' is entirely NaN/Inf")
            continue

        # Check for suspicious values
        if var in ('hslp', 'tslp', 'rslp'):
            if np.any(finite < 0):
                issues.append(f"WARNING: '{var}' has negative slopes")
            if np.any(finite > 1.0):
                issues.append(f"WARNING: '{var}' has slopes > 1.0 m/m "
                              f"(max={np.max(finite):.4f})")
        elif var in ('nh', 'nt', 'nr'):
            if np.any(finite < 0):
                issues.append(f"ERROR: '{var}' has negative Manning's n")
            if np.any(finite > 1.0):
                issues.append(f"WARNING: '{var}' has Manning's n > 1.0 "
                              f"(max={np.max(finite):.4f})")
        elif var == 'area':
            if np.any(finite < 0):
                issues.append(f"ERROR: '{var}' has negative areas")
            if np.max(finite) < 1e4:
                issues.append(f"WARNING: '{var}' max={np.max(finite):.1f}. "
                              f"Expected m^2 (>1e6 for 1km grid)")
        elif var == 'frac':
            if np.any(finite < 0) or np.any(finite > 1):
                issues.append(f"WARNING: '{var}' has values outside [0, 1]")

    # Check grid regularity
    if 'lat' in ds.coords:
        lats = ds.coords['lat'].values
        if len(lats) > 1:
            spacing = np.diff(lats)
            if not np.allclose(spacing, spacing[0], rtol=1e-3):
                issues.append("WARNING: Latitude spacing is not uniform")

    if 'lon' in ds.coords:
        lons = ds.coords['lon'].values
        if len(lons) > 1:
            spacing = np.diff(lons)
            if not np.allclose(spacing, spacing[0], rtol=1e-3):
                issues.append("WARNING: Longitude spacing is not uniform")

    # Check downstream connectivity
    if 'ID' in ds and 'dnID' in ds:
        ids = set(ds['ID'].values.flatten().astype(int))
        dn_ids = ds['dnID'].values.flatten()
        dn_ids = dn_ids[np.isfinite(dn_ids)].astype(int)
        orphans = sum(1 for d in dn_ids if d >= 0 and d not in ids)
        if orphans > 0:
            issues.append(f"WARNING: {orphans} cells have downstream IDs "
                          f"not present in the grid")

    return issues


def fill_missing_parameters(ds: xr.Dataset) -> xr.Dataset:
    """Fill missing or zero grid parameters with reasonable defaults.

    This matches the behavior in mosartwmpy's Grid.__init__:
    - Zero slopes replaced with minimum values
    - Zero areas recomputed from lat/lon
    """
    ds = ds.copy()

    # Replace zero/negative slopes
    slope_mins = {
        'hslp': 0.005,    # hillslope_minimum
        'tslp': 0.0001,   # subnetwork_slope_minimum
        'rslp': 0.0001,   # channel_slope_minimum
    }
    for var, min_val in slope_mins.items():
        if var in ds:
            ds[var] = xr.where(ds[var] <= 0, min_val, ds[var])

    # Fill missing Manning's n with defaults
    manning_map = {
        'nh': MANNING_DEFAULTS['hillslope'],
        'nt': MANNING_DEFAULTS['subnetwork'],
        'nr': MANNING_DEFAULTS['channel'],
    }
    for var, default in manning_map.items():
        if var in ds:
            ds[var] = xr.where(
                (ds[var] <= 0) | ~np.isfinite(ds[var]),
                default,
                ds[var]
            )

    return ds


def convert_grid(input_path: str, output_path: str,
                 source_type: str = 'generic',
                 fill_defaults: bool = True,
                 validate_only: bool = False) -> dict:
    """Convert or validate grid file for mosartwmpy.

    Args:
        input_path: Path to source grid NetCDF
        output_path: Path for output grid NetCDF
        source_type: Source type (generic, merit, hydrosheds)
        fill_defaults: Whether to fill missing values with defaults
        validate_only: If True, only validate without writing

    Returns:
        Dictionary with validation results and statistics
    """
    ds = xr.open_dataset(input_path)

    # Validate input
    issues = validate_grid(ds)
    errors = [i for i in issues if i.startswith('ERROR')]
    warnings = [i for i in issues if i.startswith('WARNING')]

    print(f"[convert_grid] Validation: {len(errors)} errors, "
          f"{len(warnings)} warnings")
    for issue in issues:
        print(f"  {issue}")

    if validate_only:
        ds.close()
        return {
            'valid': len(errors) == 0,
            'errors': errors,
            'warnings': warnings,
        }

    if errors:
        ds.close()
        raise ValueError(f"Input has {len(errors)} errors. Fix before converting.")

    # Fill defaults if requested
    if fill_defaults:
        ds = fill_missing_parameters(ds)
        print("[convert_grid] Applied default parameter fills")

    # Write output
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    ds.attrs['source_file'] = str(input_path)
    ds.attrs['source_type'] = source_type
    ds.attrs['created_by'] = 'mosartwmpy KI convert_grid_parameters'
    ds.to_netcdf(output_path)

    # Compute statistics
    stats = {}
    for var in REQUIRED_VARIABLES:
        if var in ds:
            data = ds[var].values.flatten()
            finite = data[np.isfinite(data)]
            if len(finite) > 0:
                stats[var] = {
                    'min': float(np.min(finite)),
                    'max': float(np.max(finite)),
                    'mean': float(np.mean(finite)),
                    'n_valid': int(len(finite)),
                }

    ds.close()
    print(f"[convert_grid] Output written to {output_path}")
    return {'valid': True, 'stats': stats}


def main():
    parser = argparse.ArgumentParser(
        description='Convert/validate grid parameters for mosartwmpy')
    parser.add_argument('--input', required=True, help='Input grid NetCDF path')
    parser.add_argument('--output', default=None, help='Output grid NetCDF path')
    parser.add_argument('--source-type', default='generic',
                        choices=['generic', 'merit', 'hydrosheds'])
    parser.add_argument('--validate-only', action='store_true',
                        help='Only validate, do not write output')
    parser.add_argument('--no-fill-defaults', action='store_true',
                        help='Do not fill missing values with defaults')

    args = parser.parse_args()

    output_path = args.output or args.input.replace('.nc', '_mosart.nc')

    try:
        result = convert_grid(
            args.input, output_path, args.source_type,
            fill_defaults=not args.no_fill_defaults,
            validate_only=args.validate_only,
        )
        if result.get('valid', False):
            print("[convert_grid] SUCCESS")
        else:
            print("[convert_grid] VALIDATION FAILED")
            sys.exit(1)
    except Exception as e:
        print(f"[convert_grid] FAILED: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
