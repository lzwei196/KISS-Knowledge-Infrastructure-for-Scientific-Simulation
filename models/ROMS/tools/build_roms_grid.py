#!/usr/bin/env python3
"""
Build ROMS Grid NetCDF File
============================
Creates a ROMS-compatible grid file from bathymetry data and domain specification.

Inputs:
  --bathymetry   : Path to bathymetry source (NetCDF with lon, lat, depth variables)
  --lon-range    : Longitude extent [west, east] in degrees
  --lat-range    : Latitude extent [south, north] in degrees
  --resolution   : Grid resolution in degrees (e.g., 0.01)
  --output       : Output grid file path (NetCDF)
  --hmin         : Minimum depth (m, positive), default 5.0
  --hmax         : Maximum depth clamp (m, positive), default 6000.0
  --spherical    : 1 for spherical (lon/lat), 0 for Cartesian (default 1)

Outputs:
  NetCDF grid file with: h, pm, pn, lon_rho, lat_rho, mask_rho, angle, f, xl, el

CRITICAL:
  - Bathymetry h must be POSITIVE (depth below sea surface)
  - pm and pn are 1/dx and 1/dy in 1/meters (NOT meters)
  - mask_rho: 0 = land, 1 = water
  - Coriolis f is computed as 2*omega*sin(lat)

Usage:
  python build_roms_grid.py \\
    --bathymetry etopo1.nc \\
    --lon-range -76.0 -70.0 \\
    --lat-range 35.0 42.0 \\
    --resolution 0.05 \\
    --output roms_grid.nc \\
    --hmin 5.0
"""

import argparse
import json
import sys
import os

import numpy as np

try:
    from netCDF4 import Dataset
    HAS_NETCDF4 = True
except ImportError:
    HAS_NETCDF4 = False

# Earth constants
EARTH_RADIUS = 6371000.0  # meters
OMEGA = 7.2921e-5  # rad/s


def validate_inputs(args):
    """Validate all inputs before processing."""
    errors = []

    if args.bathymetry and not os.path.isfile(args.bathymetry):
        errors.append(f"Bathymetry file not found: {args.bathymetry}")

    if not HAS_NETCDF4:
        errors.append("netCDF4 Python package is required but not installed")

    if len(args.lon_range) != 2:
        errors.append("--lon-range must have exactly 2 values [west, east]")
    elif args.lon_range[0] >= args.lon_range[1]:
        errors.append(f"lon_range west ({args.lon_range[0]}) must be < east ({args.lon_range[1]})")

    if len(args.lat_range) != 2:
        errors.append("--lat-range must have exactly 2 values [south, north]")
    elif args.lat_range[0] >= args.lat_range[1]:
        errors.append(f"lat_range south ({args.lat_range[0]}) must be < north ({args.lat_range[1]})")

    if args.resolution <= 0:
        errors.append(f"Resolution must be positive, got {args.resolution}")

    if args.hmin <= 0:
        errors.append(f"hmin must be positive, got {args.hmin}")

    if args.hmax <= args.hmin:
        errors.append(f"hmax ({args.hmax}) must be > hmin ({args.hmin})")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)

    return True


def compute_grid_metrics(lon_rho, lat_rho, spherical=True):
    """Compute pm, pn (inverse grid spacing) and angle."""
    Mm, Lm = lon_rho.shape

    if spherical:
        # dx = R * cos(lat) * dlon (in radians)
        dlon = np.gradient(lon_rho, axis=1) * np.pi / 180.0
        dlat = np.gradient(lat_rho, axis=0) * np.pi / 180.0
        lat_rad = lat_rho * np.pi / 180.0

        dx = EARTH_RADIUS * np.cos(lat_rad) * np.abs(dlon)
        dy = EARTH_RADIUS * np.abs(dlat)
    else:
        dx = np.gradient(lon_rho, axis=1)
        dy = np.gradient(lat_rho, axis=0)

    # Prevent division by zero
    dx = np.maximum(dx, 1.0)
    dy = np.maximum(dy, 1.0)

    pm = 1.0 / dx  # 1/meters
    pn = 1.0 / dy  # 1/meters

    # Grid angle (0 for regular lon/lat grids)
    angle = np.zeros_like(lon_rho)

    return pm, pn, angle


def compute_coriolis(lat_rho):
    """Compute Coriolis parameter f = 2*omega*sin(lat)."""
    return 2.0 * OMEGA * np.sin(lat_rho * np.pi / 180.0)


def interpolate_bathymetry(bathy_file, lon_rho, lat_rho, hmin, hmax):
    """Interpolate source bathymetry onto ROMS grid."""
    from scipy.interpolate import RegularGridInterpolator

    ds = Dataset(bathy_file, 'r')

    # Try common variable names
    for lon_name in ['lon', 'longitude', 'x']:
        if lon_name in ds.variables:
            blon = ds.variables[lon_name][:]
            break
    else:
        ds.close()
        raise ValueError("Cannot find longitude variable in bathymetry file")

    for lat_name in ['lat', 'latitude', 'y']:
        if lat_name in ds.variables:
            blat = ds.variables[lat_name][:]
            break
    else:
        ds.close()
        raise ValueError("Cannot find latitude variable in bathymetry file")

    for dep_name in ['depth', 'z', 'elevation', 'Band1', 'topo']:
        if dep_name in ds.variables:
            bdep = ds.variables[dep_name][:]
            break
    else:
        ds.close()
        raise ValueError("Cannot find depth variable in bathymetry file")

    ds.close()

    interp = RegularGridInterpolator(
        (blat, blon), bdep,
        method='linear', bounds_error=False, fill_value=None
    )

    points = np.column_stack([lat_rho.ravel(), lon_rho.ravel()])
    h = interp(points).reshape(lon_rho.shape)

    # Ensure positive (ROMS convention: h > 0 is depth below surface)
    h = np.abs(h)

    # Clamp
    h = np.clip(h, hmin, hmax)

    return h


def create_uniform_bathymetry(lon_rho, lat_rho, depth=100.0):
    """Create a flat-bottom bathymetry for testing."""
    return np.full_like(lon_rho, depth)


def build_mask(h, hmin):
    """Build land/sea mask: 1=water, 0=land."""
    mask = np.ones_like(h)
    mask[h <= 0] = 0
    return mask


def write_grid_netcdf(output_path, lon_rho, lat_rho, h, pm, pn, angle, f,
                      mask_rho, spherical=1):
    """Write ROMS grid file in NetCDF format."""
    Mm, Lm = lon_rho.shape

    ds = Dataset(output_path, 'w', format='NETCDF4')

    # Global attributes
    ds.type = 'ROMS Grid File'
    ds.title = 'ROMS grid generated by build_roms_grid.py'

    # Dimensions
    ds.createDimension('xi_rho', Lm)
    ds.createDimension('eta_rho', Mm)
    ds.createDimension('xi_u', Lm - 1)
    ds.createDimension('eta_u', Mm)
    ds.createDimension('xi_v', Lm)
    ds.createDimension('eta_v', Mm - 1)
    ds.createDimension('xi_psi', Lm - 1)
    ds.createDimension('eta_psi', Mm - 1)

    # Spherical flag
    var = ds.createVariable('spherical', 'i4')
    var[:] = spherical

    # Domain lengths
    dx_mean = 1.0 / np.mean(pm)
    dy_mean = 1.0 / np.mean(pn)
    var = ds.createVariable('xl', 'f8')
    var[:] = dx_mean * Lm
    var = ds.createVariable('el', 'f8')
    var[:] = dy_mean * Mm

    # Coordinates
    var = ds.createVariable('lon_rho', 'f8', ('eta_rho', 'xi_rho'))
    var.long_name = 'longitude of rho-points'
    var.units = 'degrees_east'
    var[:] = lon_rho

    var = ds.createVariable('lat_rho', 'f8', ('eta_rho', 'xi_rho'))
    var.long_name = 'latitude of rho-points'
    var.units = 'degrees_north'
    var[:] = lat_rho

    # Bathymetry
    var = ds.createVariable('h', 'f8', ('eta_rho', 'xi_rho'))
    var.long_name = 'bathymetry at rho-points'
    var.units = 'meter'
    var[:] = h

    # Grid metrics
    var = ds.createVariable('pm', 'f8', ('eta_rho', 'xi_rho'))
    var.long_name = 'curvilinear coordinate metric in XI'
    var.units = 'meter-1'
    var[:] = pm

    var = ds.createVariable('pn', 'f8', ('eta_rho', 'xi_rho'))
    var.long_name = 'curvilinear coordinate metric in ETA'
    var.units = 'meter-1'
    var[:] = pn

    # Angle
    var = ds.createVariable('angle', 'f8', ('eta_rho', 'xi_rho'))
    var.long_name = 'angle between XI-axis and EAST'
    var.units = 'radians'
    var[:] = angle

    # Coriolis
    var = ds.createVariable('f', 'f8', ('eta_rho', 'xi_rho'))
    var.long_name = 'Coriolis parameter at rho-points'
    var.units = 'second-1'
    var[:] = f

    # Mask
    var = ds.createVariable('mask_rho', 'f8', ('eta_rho', 'xi_rho'))
    var.long_name = 'mask on rho-points (0=land, 1=water)'
    var[:] = mask_rho

    # U/V point masks (derived)
    mask_u = mask_rho[:, :-1] * mask_rho[:, 1:]
    mask_v = mask_rho[:-1, :] * mask_rho[1:, :]

    var = ds.createVariable('mask_u', 'f8', ('eta_u', 'xi_u'))
    var.long_name = 'mask on u-points'
    var[:] = mask_u

    var = ds.createVariable('mask_v', 'f8', ('eta_v', 'xi_v'))
    var.long_name = 'mask on v-points'
    var[:] = mask_v

    ds.close()


def validate_output(output_path):
    """Validate the generated grid file."""
    errors = []
    ds = Dataset(output_path, 'r')

    required_vars = ['h', 'pm', 'pn', 'lon_rho', 'lat_rho', 'mask_rho', 'angle', 'f']
    for v in required_vars:
        if v not in ds.variables:
            errors.append(f"Missing required variable: {v}")

    if 'h' in ds.variables:
        h = ds.variables['h'][:]
        if np.any(h < 0):
            errors.append("Bathymetry h has negative values (must be positive in ROMS)")
        if np.any(np.isnan(h)):
            errors.append("Bathymetry h contains NaN values")

    if 'pm' in ds.variables:
        pm = ds.variables['pm'][:]
        if np.any(pm <= 0):
            errors.append("Grid metric pm has non-positive values")

    if 'pn' in ds.variables:
        pn = ds.variables['pn'][:]
        if np.any(pn <= 0):
            errors.append("Grid metric pn has non-positive values")

    if 'mask_rho' in ds.variables:
        mask = ds.variables['mask_rho'][:]
        unique = np.unique(mask)
        if not all(v in [0, 1] for v in unique):
            errors.append(f"mask_rho has values other than 0,1: {unique}")

    ds.close()

    return errors


def main():
    parser = argparse.ArgumentParser(
        description='Build ROMS grid NetCDF file from bathymetry and domain spec'
    )
    parser.add_argument('--bathymetry', type=str, default=None,
                        help='Path to bathymetry NetCDF (omit for flat bottom test)')
    parser.add_argument('--lon-range', type=float, nargs=2, required=True,
                        help='Longitude range [west, east]')
    parser.add_argument('--lat-range', type=float, nargs=2, required=True,
                        help='Latitude range [south, north]')
    parser.add_argument('--resolution', type=float, default=0.05,
                        help='Grid resolution in degrees')
    parser.add_argument('--output', type=str, required=True,
                        help='Output grid file path')
    parser.add_argument('--hmin', type=float, default=5.0,
                        help='Minimum depth (m, positive)')
    parser.add_argument('--hmax', type=float, default=6000.0,
                        help='Maximum depth (m, positive)')
    parser.add_argument('--spherical', type=int, default=1,
                        help='1 for spherical, 0 for Cartesian')
    parser.add_argument('--flat-depth', type=float, default=None,
                        help='Create flat-bottom bathymetry at this depth (testing)')

    args = parser.parse_args()
    validate_inputs(args)

    # Build coordinate arrays
    lon_1d = np.arange(args.lon_range[0], args.lon_range[1] + args.resolution / 2,
                       args.resolution)
    lat_1d = np.arange(args.lat_range[0], args.lat_range[1] + args.resolution / 2,
                       args.resolution)
    lon_rho, lat_rho = np.meshgrid(lon_1d, lat_1d)

    print(f"Grid dimensions: {lon_rho.shape[1]} x {lon_rho.shape[0]} (xi x eta)")

    # Bathymetry
    if args.flat_depth is not None:
        h = create_uniform_bathymetry(lon_rho, lat_rho, depth=args.flat_depth)
        print(f"Using flat-bottom bathymetry at {args.flat_depth} m")
    elif args.bathymetry:
        h = interpolate_bathymetry(args.bathymetry, lon_rho, lat_rho,
                                   args.hmin, args.hmax)
        print(f"Interpolated bathymetry: depth range [{h.min():.1f}, {h.max():.1f}] m")
    else:
        h = create_uniform_bathymetry(lon_rho, lat_rho, depth=100.0)
        print("No bathymetry source; using 100 m flat bottom")

    # Grid metrics
    pm, pn, angle = compute_grid_metrics(lon_rho, lat_rho,
                                         spherical=bool(args.spherical))
    dx_min = 1.0 / pm.max()
    dx_max = 1.0 / pm.min()
    print(f"Grid spacing: dx=[{dx_min:.0f}, {dx_max:.0f}] m")

    # Coriolis
    f = compute_coriolis(lat_rho)

    # Mask
    mask_rho = build_mask(h, args.hmin)
    water_frac = mask_rho.sum() / mask_rho.size * 100
    print(f"Water fraction: {water_frac:.1f}%")

    # Write
    write_grid_netcdf(args.output, lon_rho, lat_rho, h, pm, pn, angle, f,
                      mask_rho, spherical=args.spherical)

    # Validate output
    errors = validate_output(args.output)
    if errors:
        result = {"status": "error", "errors": errors, "output": args.output}
    else:
        result = {
            "status": "success",
            "output": args.output,
            "grid_size": [int(lon_rho.shape[1]), int(lon_rho.shape[0])],
            "depth_range": [float(h.min()), float(h.max())],
            "dx_range_m": [float(dx_min), float(dx_max)],
            "water_fraction_pct": float(water_frac)
        }

    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
