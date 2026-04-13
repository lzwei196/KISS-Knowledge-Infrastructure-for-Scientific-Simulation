#!/usr/bin/env python3
"""
topography_converter.py — Process global bathymetry data for MOM6 grid.

Converts GEBCO, ETOPO, or SRTM elevation data to MOM6-format topography file
with correct sign convention (positive depth), smoothing, and masking.

Pipeline stage: S1 (Topography / Bathymetry)
Pattern: validate → process → validate
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

# MOM6 topography conventions
# depth > 0 = ocean (positive down)
# depth <= 0 = land
DEPTH_VAR = "depth"
MIN_OCEAN_DEPTH = 10.0      # meters — MOM6 MINIMUM_DEPTH default
MAX_OCEAN_DEPTH = 6500.0    # meters — typical global max
LAND_FILL_VALUE = 0.0

# Common source variable names for bathymetry/elevation
ELEVATION_VARNAMES = ["elevation", "z", "Band1", "topo", "height", "ROSE"]
DEPTH_VARNAMES = ["depth", "Depth", "DEPTH", "bathymetry", "bathy"]


def validate_input(input_path: str, grid_path: str = None) -> dict:
    """Pre-validate: check input bathymetry and optional grid file."""
    import netCDF4

    if not os.path.isfile(input_path):
        log.error(f"Input bathymetry file not found: {input_path}")
        sys.exit(1)

    ds = netCDF4.Dataset(input_path, "r")
    src_vars = list(ds.variables.keys())

    # Find elevation/depth variable
    elev_var = None
    is_elevation = True  # True = data is elevation (positive up); False = depth (positive down)

    for vn in ELEVATION_VARNAMES:
        if vn in src_vars:
            elev_var = vn
            is_elevation = True
            break
    if elev_var is None:
        for vn in DEPTH_VARNAMES:
            if vn in src_vars:
                elev_var = vn
                is_elevation = False
                break

    if elev_var is None:
        log.error(f"Cannot find elevation or depth variable. Available: {src_vars}")
        ds.close()
        sys.exit(1)

    data = ds.variables[elev_var]
    shape = data.shape
    log.info(f"Found variable '{elev_var}' with shape {shape}, is_elevation={is_elevation}")

    # Check for lat/lon
    lat_var = lon_var = None
    for ln in ["lat", "latitude", "y", "LAT"]:
        if ln in src_vars:
            lat_var = ln
            break
    for ln in ["lon", "longitude", "x", "LON"]:
        if ln in src_vars:
            lon_var = ln
            break

    info = {
        "path": input_path,
        "elev_var": elev_var,
        "is_elevation": is_elevation,
        "shape": list(shape),
        "lat_var": lat_var,
        "lon_var": lon_var,
    }

    # Grid file
    if grid_path and os.path.isfile(grid_path):
        ds_grid = netCDF4.Dataset(grid_path, "r")
        grid_vars = list(ds_grid.variables.keys())
        info["grid_path"] = grid_path
        info["grid_vars"] = grid_vars
        # Look for supergrid x/y
        if "x" in grid_vars and "y" in grid_vars:
            gx = ds_grid.variables["x"][:]
            gy = ds_grid.variables["y"][:]
            info["grid_shape"] = [gy.shape[0], gx.shape[-1] if gx.ndim > 1 else len(gx)]
            log.info(f"Grid file: shape={info['grid_shape']}")
        ds_grid.close()
    else:
        info["grid_path"] = None

    ds.close()
    return info


def interpolate_to_grid(src_lat, src_lon, src_data, tgt_lat, tgt_lon):
    """Bilinear interpolation from source grid to target grid."""
    from scipy.interpolate import RegularGridInterpolator

    # Ensure src_lat is ascending
    if src_lat[0] > src_lat[-1]:
        src_lat = src_lat[::-1]
        src_data = src_data[::-1, :]

    interp = RegularGridInterpolator(
        (src_lat, src_lon), src_data,
        method="linear", bounds_error=False, fill_value=np.nan
    )

    if tgt_lat.ndim == 1 and tgt_lon.ndim == 1:
        tgt_lats, tgt_lons = np.meshgrid(tgt_lat, tgt_lon, indexing="ij")
    else:
        tgt_lats, tgt_lons = tgt_lat, tgt_lon

    pts = np.column_stack([tgt_lats.ravel(), tgt_lons.ravel()])
    result = interp(pts).reshape(tgt_lats.shape)
    return result


def smooth_topography(depth: np.ndarray, passes: int = 1) -> np.ndarray:
    """Apply Shapiro filter (1-2-1 smoothing) to reduce grid-scale noise."""
    result = depth.copy()
    for _ in range(passes):
        padded = np.pad(result, 1, mode="edge")
        smoothed = (
            padded[:-2, 1:-1] + padded[2:, 1:-1] +
            padded[1:-1, :-2] + padded[1:-1, 2:] +
            4 * padded[1:-1, 1:-1]
        ) / 8.0
        # Only smooth ocean points
        ocean_mask = result > 0
        result[ocean_mask] = smoothed[ocean_mask]
    return result


def process_topography(info: dict, output_path: str,
                       min_depth: float = MIN_OCEAN_DEPTH,
                       max_depth: float = MAX_OCEAN_DEPTH,
                       smooth_passes: int = 1,
                       lon_range: tuple = None,
                       lat_range: tuple = None) -> str:
    """Convert source bathymetry to MOM6 depth format."""
    import netCDF4

    ds_in = netCDF4.Dataset(info["path"], "r")
    raw = ds_in.variables[info["elev_var"]][:]

    # Get source coordinates
    src_lat = ds_in.variables[info["lat_var"]][:] if info["lat_var"] else None
    src_lon = ds_in.variables[info["lon_var"]][:] if info["lon_var"] else None

    ds_in.close()

    # Subsetting
    if lon_range and src_lon is not None:
        lon_mask = (src_lon >= lon_range[0]) & (src_lon <= lon_range[1])
        src_lon = src_lon[lon_mask]
        if raw.ndim == 2:
            raw = raw[:, lon_mask]

    if lat_range and src_lat is not None:
        lat_mask = (src_lat >= lat_range[0]) & (src_lat <= lat_range[1])
        src_lat = src_lat[lat_mask]
        if raw.ndim == 2:
            raw = raw[lat_mask, :]

    # Convert elevation → depth (TRAP dt_005)
    if info["is_elevation"]:
        log.info("UNIT TRAP dt_005: Converting elevation (positive up) → depth (positive down)")
        depth = -raw.astype(np.float64)
    else:
        depth = raw.astype(np.float64)

    # Handle masked/NaN values
    if hasattr(depth, "filled"):
        depth = depth.filled(LAND_FILL_VALUE)
    depth = np.where(np.isnan(depth), LAND_FILL_VALUE, depth)

    # Enforce land mask (depth <= 0 → land)
    land_mask = depth <= 0
    depth[land_mask] = LAND_FILL_VALUE

    # Enforce min/max ocean depth
    ocean_mask = depth > 0
    shallow = np.sum((depth > 0) & (depth < min_depth))
    if shallow > 0:
        log.info(f"Setting {shallow} shallow points to minimum depth {min_depth} m")
        depth[(depth > 0) & (depth < min_depth)] = min_depth

    deep = np.sum(depth > max_depth)
    if deep > 0:
        log.info(f"Clipping {deep} deep points to maximum depth {max_depth} m")
        depth[depth > max_depth] = max_depth

    # Smoothing
    if smooth_passes > 0:
        log.info(f"Applying {smooth_passes} passes of topographic smoothing")
        depth = smooth_topography(depth, passes=smooth_passes)

    # Interpolate to model grid if provided
    if info.get("grid_path"):
        ds_grid = netCDF4.Dataset(info["grid_path"], "r")
        # Supergrid → model grid (every other point for T-cell centers)
        gx = ds_grid.variables["x"][:]
        gy = ds_grid.variables["y"][:]
        if gx.ndim == 2:
            tgt_lon = gx[1::2, 1::2]  # T-point centers on supergrid
            tgt_lat = gy[1::2, 1::2]
        else:
            tgt_lon = gx[1::2]
            tgt_lat = gy[1::2]
        ds_grid.close()

        if src_lat is not None and src_lon is not None:
            log.info(f"Interpolating from {depth.shape} to target grid")
            depth = interpolate_to_grid(src_lat, src_lon, depth,
                                        tgt_lat if tgt_lat.ndim == 1 else tgt_lat[:, 0],
                                        tgt_lon if tgt_lon.ndim == 1 else tgt_lon[0, :])
            depth = np.where(np.isnan(depth), LAND_FILL_VALUE, depth)
            src_lat = tgt_lat[:, 0] if tgt_lat.ndim == 2 else tgt_lat
            src_lon = tgt_lon[0, :] if tgt_lon.ndim == 2 else tgt_lon

    # Write output
    nlat, nlon = depth.shape
    ds_out = netCDF4.Dataset(output_path, "w", format="NETCDF4")
    ds_out.createDimension("ny", nlat)
    ds_out.createDimension("nx", nlon)

    if src_lat is not None:
        lat_o = ds_out.createVariable("lat", "f8", ("ny",))
        lat_o[:] = src_lat if src_lat.ndim == 1 else src_lat[:, 0]
        lat_o.units = "degrees_north"

    if src_lon is not None:
        lon_o = ds_out.createVariable("lon", "f8", ("nx",))
        lon_o[:] = src_lon if src_lon.ndim == 1 else src_lon[0, :]
        lon_o.units = "degrees_east"

    d_var = ds_out.createVariable(DEPTH_VAR, "f8", ("ny", "nx"), fill_value=0.0)
    d_var[:] = depth
    d_var.units = "m"
    d_var.long_name = "Depth of ocean bottom (positive down)"
    d_var.standard_name = "sea_floor_depth_below_sea_level"

    ds_out.history = f"Created by topography_converter.py on {datetime.utcnow().isoformat()}"
    ds_out.conventions = "CF-1.6"
    ds_out.close()

    log.info(f"Wrote topography: {output_path}")
    n_ocean = int(np.sum(depth > 0))
    n_land = int(np.sum(depth <= 0))
    log.info(f"Ocean cells: {n_ocean}, Land cells: {n_land}, "
             f"Depth range: {np.min(depth[depth > 0]):.1f} – {np.max(depth):.1f} m")
    return output_path


def validate_output(output_path: str) -> dict:
    """Post-validate: check topography file for common issues."""
    import netCDF4

    if not os.path.isfile(output_path):
        return {"valid": False, "error": "Output file not created"}

    ds = netCDF4.Dataset(output_path, "r")
    depth = ds.variables[DEPTH_VAR][:]
    ds.close()

    report = {"valid": True, "warnings": []}
    ocean = depth[depth > 0]

    if ocean.size == 0:
        report["valid"] = False
        report["warnings"].append("No ocean cells found — all depths <= 0")
        return report

    report["stats"] = {
        "n_ocean": int(ocean.size),
        "n_land": int(np.sum(depth <= 0)),
        "min_depth_m": float(np.min(ocean)),
        "max_depth_m": float(np.max(ocean)),
        "mean_depth_m": float(np.mean(ocean)),
        "ocean_fraction": float(ocean.size / depth.size),
    }

    # Check for negative depths in ocean (TRAP dt_005 not applied)
    neg = np.sum(depth < 0)
    if neg > 0:
        report["warnings"].append(
            f"dt_005: {neg} negative depth values found — possible sign convention error"
        )
        report["valid"] = False

    # Check for unrealistically deep values
    if np.max(ocean) > 12000:
        report["warnings"].append(
            f"Max depth {np.max(ocean):.0f} m exceeds Mariana Trench (~11000 m)"
        )

    # Check for isolated single-cell ocean points (numerical instability risk)
    nan_count = int(np.sum(np.isnan(depth)))
    if nan_count > 0:
        report["warnings"].append(f"{nan_count} NaN values in output")
        report["valid"] = False

    for w in report["warnings"]:
        log.warning(w)

    if report["valid"]:
        log.info("Output validation PASSED")

    return report


def main():
    parser = argparse.ArgumentParser(
        description="Convert global bathymetry to MOM6 topography format"
    )
    parser.add_argument("input", help="Input bathymetry NetCDF (GEBCO, ETOPO, etc.)")
    parser.add_argument("-o", "--output", default="topog.nc",
                        help="Output topography file (default: topog.nc)")
    parser.add_argument("--grid", default=None,
                        help="MOM6 supergrid file for interpolation")
    parser.add_argument("--min-depth", type=float, default=MIN_OCEAN_DEPTH,
                        help=f"Minimum ocean depth [m] (default: {MIN_OCEAN_DEPTH})")
    parser.add_argument("--max-depth", type=float, default=MAX_OCEAN_DEPTH,
                        help=f"Maximum ocean depth [m] (default: {MAX_OCEAN_DEPTH})")
    parser.add_argument("--smooth", type=int, default=1,
                        help="Number of smoothing passes (default: 1)")
    parser.add_argument("--lon-range", type=float, nargs=2, metavar=("W", "E"),
                        help="Longitude range for subsetting")
    parser.add_argument("--lat-range", type=float, nargs=2, metavar=("S", "N"),
                        help="Latitude range for subsetting")
    parser.add_argument("--json-report", default=None,
                        help="Write validation report to JSON")
    args = parser.parse_args()

    log.info("=== Step 1: Input validation ===")
    info = validate_input(args.input, args.grid)

    log.info("=== Step 2: Processing ===")
    process_topography(info, args.output,
                       min_depth=args.min_depth,
                       max_depth=args.max_depth,
                       smooth_passes=args.smooth,
                       lon_range=tuple(args.lon_range) if args.lon_range else None,
                       lat_range=tuple(args.lat_range) if args.lat_range else None)

    log.info("=== Step 3: Output validation ===")
    report = validate_output(args.output)

    if args.json_report:
        with open(args.json_report, "w") as f:
            json.dump(report, f, indent=2)

    if not report["valid"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
