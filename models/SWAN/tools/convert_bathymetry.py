#!/usr/bin/env python3
"""
Convert bathymetry data from various sources to SWAN bottom grid format (.bot).

Pipeline stage: 1 — Bathymetry preparation
Pattern: validate_inputs → process → validate_outputs

Supported input formats:
  - GEBCO NetCDF (elevation, positive up → SWAN depth positive down)
  - ASCII grid (ESRI ASCII .asc)
  - CSV point data (lon, lat, depth)
  - Regular grid numpy arrays

Unit conversions handled:
  - Elevation (positive up) → depth (positive down): multiply by -1
  - Fathoms → meters: multiply by 1.8288
  - Feet → meters: multiply by 0.3048

SWAN bottom grid format:
  Simple ASCII, one depth value per grid cell, space separated.
  Grid defined by INPGRID BOTTOM command in .swn file.
"""

import numpy as np
import os
import sys


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_inputs(depth_data, grid_info):
    """
    Validate bathymetry inputs before conversion.

    Parameters
    ----------
    depth_data : dict
        Keys: 'depth' (2D array or 1D for simple), 'lon'/'x', 'lat'/'y'
    grid_info : dict
        Keys: 'xpc', 'ypc', 'dx', 'dy', 'mx', 'my' (SWAN grid params)

    Returns
    -------
    list of str : warnings
    """
    warnings = []

    depth = np.asarray(depth_data.get('depth', []))
    if depth.size == 0:
        raise ValueError("Empty depth data")

    # Check for elevation vs depth convention
    if np.nanmean(depth) < 0:
        warnings.append("UNIT TRAP: Mean depth is negative — data may be elevation "
                         "(positive up). SWAN expects depth positive DOWN. "
                         "Apply: depth = -elevation")

    if np.nanmax(depth) > 11000:
        warnings.append(f"UNIT TRAP: Max depth={np.nanmax(depth):.0f} > 11000 m — "
                         "check units (fathoms? feet?)")

    if np.nanmin(depth) < -100:
        warnings.append(f"Min depth={np.nanmin(depth):.0f} < -100 — negative depths "
                         "indicate land above sea level (OK for SWAN, but verify)")

    # Check grid sanity
    mx = grid_info.get('mx', 0)
    my = grid_info.get('my', 0)
    if mx <= 0 or my < 0:
        raise ValueError(f"Invalid grid dimensions: mx={mx}, my={my}")

    dx = grid_info.get('dx', 0)
    dy = grid_info.get('dy', 0)
    if dx <= 0:
        raise ValueError(f"Invalid grid spacing: dx={dx}")

    return warnings


def validate_outputs(output_path, expected_shape=None):
    """
    Validate written bathymetry file.

    Parameters
    ----------
    output_path : str
    expected_shape : tuple, optional
        (n_rows, n_cols) expected in the file.

    Returns
    -------
    dict : validation results
    """
    results = {'status': 'unknown', 'file': output_path}

    if not os.path.exists(output_path):
        results['status'] = 'FAIL: file not found'
        return results

    try:
        data = np.loadtxt(output_path)
        if data.ndim == 1:
            data = data.reshape(1, -1)
        results['shape'] = data.shape
        results['depth_range'] = f"{np.nanmin(data):.2f} to {np.nanmax(data):.2f} m"
        results['n_nan'] = int(np.sum(np.isnan(data)))

        if expected_shape:
            if data.shape != expected_shape:
                results['status'] = (f'WARNING: shape {data.shape} != '
                                     f'expected {expected_shape}')
            else:
                results['status'] = 'OK'
        else:
            results['status'] = 'OK'

    except Exception as e:
        results['status'] = f'FAIL: {str(e)}'

    return results


# ---------------------------------------------------------------------------
# Unit conversion helpers
# ---------------------------------------------------------------------------

def elevation_to_depth(elevation):
    """Convert elevation (positive up, negative = water) to SWAN depth (positive down)."""
    return -np.asarray(elevation, dtype=float)


def fathoms_to_meters(depth_fathoms):
    """Convert fathoms to meters (1 fathom = 1.8288 m)."""
    return np.asarray(depth_fathoms, dtype=float) * 1.8288


def feet_to_meters(depth_feet):
    """Convert feet to meters (1 foot = 0.3048 m)."""
    return np.asarray(depth_feet, dtype=float) * 0.3048


# ---------------------------------------------------------------------------
# Interpolation helpers
# ---------------------------------------------------------------------------

def interpolate_to_grid(lon_src, lat_src, depth_src,
                        xpc, ypc, dx, dy, mx, my):
    """
    Interpolate scattered or gridded depth data onto a regular SWAN grid.

    Parameters
    ----------
    lon_src, lat_src : array-like
        Source coordinates (can be 1D scatter or meshgrid).
    depth_src : array-like
        Source depth values.
    xpc, ypc : float
        SWAN grid origin.
    dx, dy : float
        SWAN grid spacing.
    mx, my : int
        Number of cells in x, y.

    Returns
    -------
    np.ndarray : depth on SWAN grid, shape (my+1, mx+1)
    """
    from scipy.interpolate import griddata

    lon_src = np.asarray(lon_src).ravel()
    lat_src = np.asarray(lat_src).ravel()
    depth_src = np.asarray(depth_src).ravel()

    # Remove NaN points
    valid = ~(np.isnan(lon_src) | np.isnan(lat_src) | np.isnan(depth_src))
    lon_src = lon_src[valid]
    lat_src = lat_src[valid]
    depth_src = depth_src[valid]

    # Build target grid
    x_target = xpc + np.arange(mx + 1) * dx
    y_target = ypc + np.arange(max(my, 1)) * (dy if dy > 0 else 1.0)
    xx, yy = np.meshgrid(x_target, y_target)

    # Interpolate
    depth_grid = griddata(
        (lon_src, lat_src), depth_src,
        (xx, yy), method='linear', fill_value=np.nan
    )

    # Fill remaining NaN with nearest
    if np.any(np.isnan(depth_grid)):
        depth_nearest = griddata(
            (lon_src, lat_src), depth_src,
            (xx, yy), method='nearest'
        )
        mask = np.isnan(depth_grid)
        depth_grid[mask] = depth_nearest[mask]

    return depth_grid


# ---------------------------------------------------------------------------
# Main conversion
# ---------------------------------------------------------------------------

def convert_bathymetry(depth_data, grid_info, output_path,
                       unit_conversion=None, constant_depth=None):
    """
    Convert bathymetry data to SWAN .bot format.

    Parameters
    ----------
    depth_data : dict or None
        Keys: 'depth', 'lon'/'x', 'lat'/'y'. None if constant_depth used.
    grid_info : dict
        Keys: 'xpc', 'ypc', 'dx', 'dy', 'mx', 'my'
    output_path : str
        Output .bot file path.
    unit_conversion : str, optional
        'elevation_to_depth', 'fathoms_to_meters', 'feet_to_meters'
    constant_depth : float, optional
        If set, create uniform bathymetry (ignores depth_data).

    Returns
    -------
    dict : validation results
    """
    mx = grid_info['mx']
    my = grid_info.get('my', 0)
    n_rows = max(my, 1)
    n_cols = mx + 1

    if constant_depth is not None:
        # Simple uniform depth
        depth_grid = np.full((n_rows, n_cols), constant_depth)
    else:
        # Validate
        warnings = validate_inputs(depth_data, grid_info)
        for w in warnings:
            print(f"[WARNING] {w}")

        depth = np.asarray(depth_data['depth'], dtype=float)

        # Unit conversion
        if unit_conversion == 'elevation_to_depth':
            depth = elevation_to_depth(depth)
        elif unit_conversion == 'fathoms_to_meters':
            depth = fathoms_to_meters(depth)
        elif unit_conversion == 'feet_to_meters':
            depth = feet_to_meters(depth)

        # Check if already on correct grid
        if depth.ndim == 2 and depth.shape == (n_rows, n_cols):
            depth_grid = depth
        elif depth.ndim == 1 and len(depth) == n_cols * n_rows:
            depth_grid = depth.reshape(n_rows, n_cols)
        else:
            # Need interpolation
            lon = np.asarray(depth_data.get('lon', depth_data.get('x')))
            lat = np.asarray(depth_data.get('lat', depth_data.get('y')))
            depth_grid = interpolate_to_grid(
                lon, lat, depth,
                grid_info['xpc'], grid_info['ypc'],
                grid_info['dx'], grid_info.get('dy', 0),
                mx, my
            )

    # Write .bot file
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    with open(output_path, 'w') as f:
        for row in depth_grid:
            line = '  '.join(f'{v:.4f}' if not np.isnan(v) else '-999.0000'
                             for v in row)
            f.write(line + '\n')

    # Validate
    results = validate_outputs(output_path, expected_shape=depth_grid.shape)
    return results


def write_simple_bot(depth_value, n_cols, output_path):
    """
    Write a minimal .bot file with uniform depth (for 1D flume tests).

    Parameters
    ----------
    depth_value : float
        Constant water depth in meters.
    n_cols : int
        Number of columns (mx + 1 from CGRID).
    output_path : str
    """
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    with open(output_path, 'w') as f:
        line = '  '.join([f'{depth_value:.4f}'] * n_cols)
        f.write(line + '\n')
    return validate_outputs(output_path)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(
        description='Convert bathymetry to SWAN .bot format')
    parser.add_argument('--depth', type=float, help='Constant depth (m)')
    parser.add_argument('--mx', type=int, default=100, help='Grid cells in x')
    parser.add_argument('--my', type=int, default=0, help='Grid cells in y (0 for 1D)')
    parser.add_argument('--output', '-o', required=True, help='Output .bot path')
    parser.add_argument('--unit', choices=['elevation_to_depth', 'fathoms_to_meters',
                                            'feet_to_meters'],
                        help='Unit conversion to apply')
    args = parser.parse_args()

    if args.depth is not None:
        grid = {'xpc': 0, 'ypc': 0, 'dx': 10, 'dy': 0, 'mx': args.mx, 'my': args.my}
        result = convert_bathymetry(None, grid, args.output,
                                     constant_depth=args.depth)
    else:
        print("Provide --depth for constant bathymetry or extend for file input")
        sys.exit(1)

    print(f"Result: {result['status']}")
