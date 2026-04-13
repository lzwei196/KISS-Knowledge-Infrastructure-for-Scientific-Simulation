#!/usr/bin/env python3
"""
convert_grid.py — COAWST Grid / Bathymetry Converter
=====================================================

Creates ROMS-compatible grid NetCDF files from bathymetry data (GEBCO, ETOPO)
and coastline data (GSHHS). Computes derived fields: Coriolis, grid metrics
(pm, pn), angles, and land/sea masks.

CRITICAL CONVENTIONS:
  - Bathymetry h MUST be positive (depth below MSL). GEBCO/ETOPO use
    negative-for-ocean convention — you MUST negate: h = -z_gebco.
    See dt_007 in diagnostics/triplets.yaml.
  - ROMS uses Arakawa C-grid: rho (Lm+2 × Mm+2), u (Lm+1 × Mm+2),
    v (Lm+2 × Mm+1), psi (Lm+1 × Mm+1).
  - Grid angle must be in radians (angle between xi-axis and east).
  - Coriolis parameter f = 2 * Omega * sin(lat), Omega = 7.2921e-5 rad/s.

Usage:
  python3 convert_grid.py \\
    --bathymetry gebco_2023.nc --bathy-format gebco \\
    --lon-range -77 -69 --lat-range 35 43 \\
    --resolution 0.01 \\
    --output sandy_grid.nc \\
    --smooth-factor 0.2

See diagnostics/triplets.yaml dt_007, dt_009 for grid-related traps.
"""

import argparse
import json
import os
import sys
from datetime import datetime

import numpy as np

try:
    import netCDF4 as nc
    HAS_NETCDF = True
except ImportError:
    HAS_NETCDF = False

try:
    import xarray as xr
    HAS_XARRAY = True
except ImportError:
    HAS_XARRAY = False


# Constants
EARTH_RADIUS = 6371000.0  # meters
OMEGA = 7.2921e-5         # rad/s (Earth rotation rate)
DEG2RAD = np.pi / 180.0


def validate_inputs(args):
    """Validate inputs before processing."""
    errors = []
    warnings = []

    if not os.path.exists(args.bathymetry):
        errors.append(f"Bathymetry file not found: {args.bathymetry}")

    if args.lon_range[0] >= args.lon_range[1]:
        errors.append(f"Invalid longitude range: {args.lon_range}")

    if args.lat_range[0] >= args.lat_range[1]:
        errors.append(f"Invalid latitude range: {args.lat_range}")

    if args.resolution <= 0 or args.resolution > 1.0:
        errors.append(f"Resolution must be 0 < res <= 1.0 degrees, got {args.resolution}")

    if args.smooth_factor < 0 or args.smooth_factor > 1.0:
        warnings.append(f"Smooth factor {args.smooth_factor} outside typical range [0, 0.4]")

    if args.min_depth is not None and args.min_depth < 0:
        errors.append("min_depth must be positive (ROMS convention: depth = positive)")

    if not HAS_NETCDF:
        errors.append("netCDF4 is required. pip install netCDF4")

    if errors:
        print(json.dumps({"status": "error", "errors": errors, "warnings": warnings}, indent=2))
        sys.exit(1)

    return warnings


def read_bathymetry(bathy_path, bathy_format, lon_range, lat_range):
    """Read bathymetry from GEBCO, ETOPO, or custom NetCDF."""
    print(f"  Reading bathymetry: {bathy_path} ({bathy_format})", file=sys.stderr)

    if HAS_XARRAY:
        ds = xr.open_dataset(bathy_path)
    else:
        ds_nc = nc.Dataset(bathy_path)

    # Variable name mapping
    var_maps = {
        "gebco": {"z": "elevation", "lon": "lon", "lat": "lat"},
        "etopo": {"z": "z", "lon": "x", "lat": "y"},
        "custom": {"z": "z", "lon": "lon", "lat": "lat"},
    }
    vmap = var_maps.get(bathy_format, var_maps["custom"])

    if HAS_XARRAY:
        lon = ds[vmap["lon"]].values
        lat = ds[vmap["lat"]].values
        z = ds[vmap["z"]].values
        ds.close()
    else:
        lon = ds_nc.variables[vmap["lon"]][:]
        lat = ds_nc.variables[vmap["lat"]][:]
        z = ds_nc.variables[vmap["z"]][:]
        ds_nc.close()

    # Subset to region
    lon_mask = (lon >= lon_range[0] - 0.1) & (lon <= lon_range[1] + 0.1)
    lat_mask = (lat >= lat_range[0] - 0.1) & (lat <= lat_range[1] + 0.1)

    lon_sub = lon[lon_mask]
    lat_sub = lat[lat_mask]
    z_sub = z[np.ix_(lat_mask, lon_mask)]

    return lon_sub, lat_sub, z_sub


def create_roms_grid(lon_range, lat_range, resolution):
    """Create ROMS grid coordinates on rho, u, v, psi points."""
    lon_rho_1d = np.arange(lon_range[0], lon_range[1] + resolution, resolution)
    lat_rho_1d = np.arange(lat_range[0], lat_range[1] + resolution, resolution)

    lon_rho, lat_rho = np.meshgrid(lon_rho_1d, lat_rho_1d)

    # U-points (halfway in xi)
    lon_u = 0.5 * (lon_rho[:, :-1] + lon_rho[:, 1:])
    lat_u = 0.5 * (lat_rho[:, :-1] + lat_rho[:, 1:])

    # V-points (halfway in eta)
    lon_v = 0.5 * (lon_rho[:-1, :] + lon_rho[1:, :])
    lat_v = 0.5 * (lat_rho[:-1, :] + lat_rho[1:, :])

    # Psi-points (corners)
    lon_psi = 0.5 * (lon_u[:-1, :] + lon_u[1:, :])
    lat_psi = 0.5 * (lat_u[:-1, :] + lat_u[1:, :])

    return {
        "lon_rho": lon_rho, "lat_rho": lat_rho,
        "lon_u": lon_u, "lat_u": lat_u,
        "lon_v": lon_v, "lat_v": lat_v,
        "lon_psi": lon_psi, "lat_psi": lat_psi,
    }


def compute_grid_metrics(lon_rho, lat_rho):
    """Compute ROMS grid metrics: pm, pn (inverse grid spacing), angle, f."""
    # Grid spacing in meters
    dx = np.zeros_like(lon_rho)
    dy = np.zeros_like(lon_rho)

    # dx: spacing in xi-direction (along rows)
    dlon = np.gradient(lon_rho, axis=1)
    dlat_xi = np.gradient(lat_rho, axis=1)
    dx = EARTH_RADIUS * np.sqrt((dlon * DEG2RAD * np.cos(lat_rho * DEG2RAD))**2 +
                                  (dlat_xi * DEG2RAD)**2)

    # dy: spacing in eta-direction (along columns)
    dlon_eta = np.gradient(lon_rho, axis=0)
    dlat = np.gradient(lat_rho, axis=0)
    dy = EARTH_RADIUS * np.sqrt((dlon_eta * DEG2RAD * np.cos(lat_rho * DEG2RAD))**2 +
                                  (dlat * DEG2RAD)**2)

    # Inverse spacing (1/m)
    pm = 1.0 / np.maximum(dx, 1.0)
    pn = 1.0 / np.maximum(dy, 1.0)

    # Grid angle (radians) — angle between xi-axis and east
    angle = np.arctan2(dlat_xi * DEG2RAD,
                        dlon * DEG2RAD * np.cos(lat_rho * DEG2RAD))

    # Coriolis parameter
    f = 2.0 * OMEGA * np.sin(lat_rho * DEG2RAD)

    return pm, pn, angle, f, dx, dy


def smooth_bathymetry(h, mask, rx0_max=0.2):
    """Smooth bathymetry to satisfy the rx0 Beckmann-Haidvogel number constraint.

    rx0 = |h(i+1) - h(i)| / (h(i+1) + h(i)) < rx0_max

    Excessive rx0 causes pressure gradient errors in sigma coordinates.
    """
    max_iter = 500
    for iteration in range(max_iter):
        rx0 = np.zeros_like(h)

        # xi-direction
        dh_xi = np.abs(np.diff(h, axis=1))
        sh_xi = h[:, :-1] + h[:, 1:]
        sh_xi = np.maximum(sh_xi, 1e-10)
        rx0_xi = dh_xi / sh_xi

        # eta-direction
        dh_eta = np.abs(np.diff(h, axis=0))
        sh_eta = h[:-1, :] + h[1:, :]
        sh_eta = np.maximum(sh_eta, 1e-10)
        rx0_eta = dh_eta / sh_eta

        max_rx0 = max(np.max(rx0_xi[mask[:, :-1] * mask[:, 1:] > 0]) if np.any(mask[:, :-1] * mask[:, 1:]) else 0,
                      np.max(rx0_eta[mask[:-1, :] * mask[1:, :] > 0]) if np.any(mask[:-1, :] * mask[1:, :]) else 0)

        if max_rx0 <= rx0_max:
            print(f"  Smoothing converged at iteration {iteration}: rx0 = {max_rx0:.4f}", file=sys.stderr)
            return h

        # Apply Shapiro filter where rx0 is too large
        h_new = h.copy()
        for j in range(1, h.shape[0] - 1):
            for i in range(1, h.shape[1] - 1):
                if mask[j, i] > 0:
                    neighbors = []
                    if mask[j, i-1] > 0: neighbors.append(h[j, i-1])
                    if mask[j, i+1] > 0: neighbors.append(h[j, i+1])
                    if mask[j-1, i] > 0: neighbors.append(h[j-1, i])
                    if mask[j+1, i] > 0: neighbors.append(h[j+1, i])
                    if neighbors:
                        h_new[j, i] = 0.5 * h[j, i] + 0.5 * np.mean(neighbors)
        h = h_new

    print(f"  Warning: smoothing did not converge after {max_iter} iterations (rx0={max_rx0:.4f})", file=sys.stderr)
    return h


def interpolate_bathy_to_grid(src_lon, src_lat, z, dst_lon, dst_lat):
    """Interpolate bathymetry to ROMS grid points."""
    from scipy.interpolate import RegularGridInterpolator

    interp = RegularGridInterpolator(
        (src_lat, src_lon), z,
        method="linear", bounds_error=False, fill_value=np.nan
    )
    points = np.stack([dst_lat.ravel(), dst_lon.ravel()], axis=-1)
    return interp(points).reshape(dst_lat.shape)


def process(args, warnings):
    """Main grid generation process."""
    print("Creating ROMS grid...", file=sys.stderr)

    # Read bathymetry
    src_lon, src_lat, z_raw = read_bathymetry(
        args.bathymetry, args.bathy_format, args.lon_range, args.lat_range
    )

    # Create grid coordinates
    grid = create_roms_grid(args.lon_range, args.lat_range, args.resolution)
    Mm, Lm = grid["lon_rho"].shape[0] - 2, grid["lon_rho"].shape[1] - 2

    print(f"  Grid dimensions: Lm={Lm}, Mm={Mm} (rho: {Lm+2}×{Mm+2})", file=sys.stderr)

    # Interpolate bathymetry to rho-points
    h = interpolate_bathy_to_grid(src_lon, src_lat, z_raw,
                                   grid["lon_rho"], grid["lat_rho"])

    # CRITICAL: GEBCO/ETOPO use negative-for-ocean convention
    # ROMS requires h > 0 (positive depth below MSL)
    if args.bathy_format in ("gebco", "etopo"):
        h = -h  # Negate! See dt_007
        warnings.append("Bathymetry negated (GEBCO/ETOPO negative-ocean → ROMS positive-depth)")

    # Apply minimum depth
    min_depth = args.min_depth if args.min_depth else 5.0
    h = np.maximum(h, min_depth)

    # Create land/sea mask (1 = water, 0 = land)
    mask_rho = np.ones_like(h)
    mask_rho[np.isnan(h)] = 0
    mask_rho[h <= 0] = 0
    h[mask_rho == 0] = min_depth  # fill land with min depth

    # Smooth bathymetry for sigma-coordinate stability
    h = smooth_bathymetry(h, mask_rho, rx0_max=args.smooth_factor)

    # Compute grid metrics
    pm, pn, angle, f, dx, dy = compute_grid_metrics(grid["lon_rho"], grid["lat_rho"])

    # U/V masks
    mask_u = mask_rho[:, :-1] * mask_rho[:, 1:]
    mask_v = mask_rho[:-1, :] * mask_rho[1:, :]
    mask_psi = mask_rho[:-1, :-1] * mask_rho[:-1, 1:] * mask_rho[1:, :-1] * mask_rho[1:, 1:]

    # Write NetCDF
    write_grid_netcdf(args.output, grid, h, mask_rho, mask_u, mask_v, mask_psi,
                       pm, pn, angle, f)

    print(f"  Grid written: {args.output}", file=sys.stderr)
    print(f"  Depth range: {np.min(h[mask_rho > 0]):.1f} – {np.max(h[mask_rho > 0]):.1f} m", file=sys.stderr)

    return {
        "status": "success",
        "output": args.output,
        "grid_dims": {"Lm": int(Lm), "Mm": int(Mm)},
        "depth_range": [float(np.min(h[mask_rho > 0])), float(np.max(h[mask_rho > 0]))],
        "water_cells": int(np.sum(mask_rho > 0)),
        "land_cells": int(np.sum(mask_rho == 0)),
        "warnings": warnings,
    }


def write_grid_netcdf(output_path, grid, h, mask_rho, mask_u, mask_v, mask_psi,
                       pm, pn, angle, f):
    """Write ROMS grid file in NetCDF format."""
    eta_rho, xi_rho = grid["lon_rho"].shape

    ds = nc.Dataset(output_path, "w", format="NETCDF4")
    ds.title = "ROMS grid (generated by convert_grid.py)"
    ds.history = f"Created {datetime.now().isoformat()}"
    ds.Conventions = "CF-1.6"
    ds.type = "ROMS grid file"

    # Dimensions
    ds.createDimension("xi_rho", xi_rho)
    ds.createDimension("eta_rho", eta_rho)
    ds.createDimension("xi_u", xi_rho - 1)
    ds.createDimension("eta_u", eta_rho)
    ds.createDimension("xi_v", xi_rho)
    ds.createDimension("eta_v", eta_rho - 1)
    ds.createDimension("xi_psi", xi_rho - 1)
    ds.createDimension("eta_psi", eta_rho - 1)

    # Scalar variables
    for name in ["spherical"]:
        v = ds.createVariable(name, "i4")
        v[:] = 1

    # rho-point variables
    for name, data, long_name, units in [
        ("lon_rho", grid["lon_rho"], "longitude of rho-points", "degrees_east"),
        ("lat_rho", grid["lat_rho"], "latitude of rho-points", "degrees_north"),
        ("h", h, "bathymetry at rho-points", "meter"),
        ("mask_rho", mask_rho, "mask on rho-points", ""),
        ("pm", pm, "curvilinear coordinate metric in XI", "meter-1"),
        ("pn", pn, "curvilinear coordinate metric in ETA", "meter-1"),
        ("angle", angle, "angle between XI-axis and EAST", "radians"),
        ("f", f, "Coriolis parameter at rho-points", "second-1"),
    ]:
        v = ds.createVariable(name, "f8", ("eta_rho", "xi_rho"))
        v[:] = data
        v.long_name = long_name
        if units:
            v.units = units

    # u-point variables
    for name, data, long_name, units in [
        ("lon_u", grid["lon_u"], "longitude of u-points", "degrees_east"),
        ("lat_u", grid["lat_u"], "latitude of u-points", "degrees_north"),
        ("mask_u", mask_u, "mask on u-points", ""),
    ]:
        v = ds.createVariable(name, "f8", ("eta_u", "xi_u"))
        v[:] = data
        v.long_name = long_name
        if units:
            v.units = units

    # v-point variables
    for name, data, long_name, units in [
        ("lon_v", grid["lon_v"], "longitude of v-points", "degrees_east"),
        ("lat_v", grid["lat_v"], "latitude of v-points", "degrees_north"),
        ("mask_v", mask_v, "mask on v-points", ""),
    ]:
        v = ds.createVariable(name, "f8", ("eta_v", "xi_v"))
        v[:] = data
        v.long_name = long_name
        if units:
            v.units = units

    # psi-point variables
    for name, data, long_name, units in [
        ("lon_psi", grid["lon_psi"], "longitude of psi-points", "degrees_east"),
        ("lat_psi", grid["lat_psi"], "latitude of psi-points", "degrees_north"),
        ("mask_psi", mask_psi, "mask on psi-points", ""),
    ]:
        v = ds.createVariable(name, "f8", ("eta_psi", "xi_psi"))
        v[:] = data
        v.long_name = long_name
        if units:
            v.units = units

    ds.close()


def validate_outputs(result):
    """Post-processing validation."""
    if result["status"] != "success":
        return result

    output = result.get("output")
    if output and os.path.exists(output):
        size_mb = os.path.getsize(output) / (1024 * 1024)
        result["file_size_mb"] = round(size_mb, 2)

        # Verify grid file is readable
        try:
            ds = nc.Dataset(output)
            required_vars = ["lon_rho", "lat_rho", "h", "mask_rho", "pm", "pn", "f", "angle"]
            missing = [v for v in required_vars if v not in ds.variables]
            if missing:
                result["warnings"].append(f"Missing variables in grid file: {missing}")
            ds.close()
        except Exception as e:
            result["warnings"].append(f"Cannot verify grid file: {e}")
    else:
        result["status"] = "error"
        result["errors"] = [f"Output not created: {output}"]

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Create ROMS grid NetCDF from bathymetry data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--bathymetry", required=True, help="Path to bathymetry NetCDF (GEBCO, ETOPO)")
    parser.add_argument("--bathy-format", required=True, choices=["gebco", "etopo", "custom"],
                        help="Bathymetry data format")
    parser.add_argument("--lon-range", nargs=2, type=float, required=True, help="Longitude range (min max)")
    parser.add_argument("--lat-range", nargs=2, type=float, required=True, help="Latitude range (min max)")
    parser.add_argument("--resolution", type=float, required=True, help="Grid resolution in degrees")
    parser.add_argument("--output", required=True, help="Output grid NetCDF path")
    parser.add_argument("--smooth-factor", type=float, default=0.2,
                        help="rx0 Beckmann-Haidvogel smoothing factor (default: 0.2)")
    parser.add_argument("--min-depth", type=float, default=5.0,
                        help="Minimum depth in meters (default: 5.0)")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing output")

    args = parser.parse_args()
    warnings = validate_inputs(args)
    result = process(args, warnings)
    result = validate_outputs(result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
