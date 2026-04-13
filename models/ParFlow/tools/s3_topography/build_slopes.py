#!/usr/bin/env python3
"""
Compute slope fields (slope_x, slope_y) from DEM for ParFlow overland flow.

ParFlow overland flow routing uses x-direction and y-direction slopes
(dz/dx, dz/dy) to determine surface water flow direction and speed.

CRITICAL: Unfilled DEM sinks create extreme pressure gradients -> solver crash.
CRITICAL: Minimum slope ~0.0001 to prevent zero-velocity ponding.
CRITICAL: Slope sign convention: positive slope in positive coordinate direction.

Usage:
    python build_slopes.py \
        --domain_json outputs/parflow_run/domain/domain_definition.json \
        --dem_path data/dem/china_dem_90m/china_dem_90m.tif \
        --surface_mask_npy outputs/parflow_run/domain/surface_mask.npy \
        --output_dir outputs/parflow_run/topography/

Author: Jianyun Zhang Research Group, Hohai University
"""

import argparse
import json
import os
import sys

import numpy as np

try:
    import rasterio
    from rasterio.warp import reproject, Resampling
    from rasterio.transform import from_bounds
    from pyproj import CRS, Transformer
    from scipy.ndimage import uniform_filter
except ImportError as e:
    print(json.dumps({"status": "error", "message": f"Missing dependency: {e}"}))
    sys.exit(1)


HYDROCRAFT_ROOT = "/mnt/disk1/Hydrocraft_server"
CHINA_DEM = os.path.join(HYDROCRAFT_ROOT, "data/dem/china_dem_90m/china_dem_90m.tif")


def fill_sinks_simple(elevation, mask, max_iterations=1000):
    """
    Simple depression filling algorithm (priority-flood simplified).
    Fills sinks so that all cells drain to domain edges.
    """
    filled = elevation.copy()
    ny, nx = filled.shape

    for iteration in range(max_iterations):
        changed = False
        for j in range(1, ny - 1):
            for i in range(1, nx - 1):
                if mask[j, i] == 0:
                    continue
                neighbors = []
                for dj, di in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    nj, ni = j + dj, i + di
                    if 0 <= nj < ny and 0 <= ni < nx and mask[nj, ni] > 0:
                        neighbors.append(filled[nj, ni])
                if neighbors:
                    min_neighbor = min(neighbors)
                    if filled[j, i] < min_neighbor:
                        # Check if this cell is a local minimum (sink)
                        if all(filled[j, i] <= n for n in neighbors):
                            filled[j, i] = min_neighbor + 0.001
                            changed = True
        if not changed:
            break

    return filled


def validate_inputs(domain_json, dem_path, surface_mask_npy):
    errors = []
    if not os.path.exists(domain_json):
        errors.append(f"Domain definition not found: {domain_json}")
    if not os.path.exists(dem_path):
        errors.append(f"DEM not found: {dem_path}")
    if not os.path.exists(surface_mask_npy):
        errors.append(f"Surface mask not found: {surface_mask_npy}")
    return errors


def process(domain_json, dem_path, surface_mask_npy, output_dir,
            min_slope=0.0001, smooth_sigma=0, fill_sinks=True):
    """
    Compute slope fields from DEM on ParFlow grid.

    Parameters
    ----------
    domain_json : str
        Path to domain definition JSON.
    dem_path : str
        Path to DEM raster.
    surface_mask_npy : str
        Path to 2D surface mask.
    output_dir : str
        Output directory.
    min_slope : float
        Minimum absolute slope to prevent ponding (default 0.0001).
    smooth_sigma : int
        Smoothing kernel size (0 = no smoothing).
    fill_sinks : bool
        Whether to fill DEM sinks before slope computation.
    """
    os.makedirs(output_dir, exist_ok=True)

    with open(domain_json) as f:
        domain = json.load(f)

    mask_2d = np.load(surface_mask_npy)
    grid = domain["grid"]
    nx, ny = grid["nx"], grid["ny"]
    dx, dy = grid["dx"], grid["dy"]
    origin_x = domain["origin"]["x"]
    origin_y = domain["origin"]["y"]
    utm_epsg = domain["crs"]["epsg"]

    # Resample DEM to ParFlow grid
    dst_crs = CRS.from_epsg(utm_epsg)
    dst_transform = from_bounds(origin_x, origin_y,
                                origin_x + nx * dx, origin_y + ny * dy,
                                nx, ny)
    elevation = np.zeros((ny, nx), dtype=np.float64)

    with rasterio.open(dem_path) as src:
        reproject(
            source=rasterio.band(src, 1),
            destination=elevation,
            src_transform=src.transform,
            src_crs=src.crs,
            dst_transform=dst_transform,
            dst_crs=dst_crs,
            resampling=Resampling.bilinear,
        )

    # Handle nodata
    nodata_mask = (elevation < -9990) | np.isnan(elevation)
    if np.any(nodata_mask & (mask_2d > 0)):
        # Fill nodata in active cells with nearest valid value
        from scipy.ndimage import distance_transform_edt
        valid = ~nodata_mask
        if np.any(valid):
            _, indices = distance_transform_edt(nodata_mask, return_indices=True)
            elevation[nodata_mask] = elevation[indices[0, nodata_mask], indices[1, nodata_mask]]

    # Fill sinks
    sinks_filled = 0
    if fill_sinks:
        elev_before = elevation.copy()
        elevation = fill_sinks_simple(elevation, mask_2d)
        sinks_filled = int(np.sum(elevation != elev_before))

    # Smooth if requested
    if smooth_sigma > 0:
        elevation_smooth = uniform_filter(elevation, size=smooth_sigma)
        elevation = np.where(mask_2d > 0, elevation_smooth, elevation)

    # Compute slopes using central differences
    # slope_x[j, i] = (elev[j, i+1] - elev[j, i]) / dx
    # slope_y[j, i] = (elev[j+1, i] - elev[j, i]) / dy
    slope_x = np.zeros((ny, nx), dtype=np.float64)
    slope_y = np.zeros((ny, nx), dtype=np.float64)

    # X-direction slopes
    for j in range(ny):
        for i in range(nx - 1):
            slope_x[j, i] = (elevation[j, i + 1] - elevation[j, i]) / dx
        slope_x[j, nx - 1] = slope_x[j, max(0, nx - 2)]

    # Y-direction slopes
    for j in range(ny - 1):
        for i in range(nx):
            slope_y[j, i] = (elevation[j + 1, i] - elevation[j, i]) / dy
    slope_y[ny - 1, :] = slope_y[max(0, ny - 2), :]

    # Apply minimum slope for active cells
    flat_cells = 0
    for j in range(ny):
        for i in range(nx):
            if mask_2d[j, i] == 0:
                slope_x[j, i] = 0.0
                slope_y[j, i] = 0.0
                continue
            mag = np.sqrt(slope_x[j, i]**2 + slope_y[j, i]**2)
            if mag < min_slope:
                # Apply minimum slope in direction of steepest descent
                # Default: toward lower x (arbitrary but consistent)
                slope_x[j, i] = -min_slope
                flat_cells += 1

    # Save outputs
    outputs = {}
    for name, arr in [("slope_x", slope_x), ("slope_y", slope_y),
                       ("elevation", elevation)]:
        npy_path = os.path.join(output_dir, f"{name}.npy")
        np.save(npy_path, arr)
        outputs[f"{name}_npy"] = npy_path

        try:
            from parflow.tools.io import write_pfb
            pfb_path = os.path.join(output_dir, f"{name}.pfb")
            write_pfb(pfb_path, arr[np.newaxis, :, :].astype(np.float64),
                      dx=dx, dy=dy, dz=1.0, x=origin_x, y=origin_y, z=0.0)
            outputs[f"{name}_pfb"] = pfb_path
        except ImportError:
            pass

    active = mask_2d > 0
    result = {
        "status": "success",
        "output_files": outputs,
        "elevation_stats": {
            "min": float(np.min(elevation[active])) if np.any(active) else 0,
            "max": float(np.max(elevation[active])) if np.any(active) else 0,
            "mean": float(np.mean(elevation[active])) if np.any(active) else 0,
            "range": float(np.ptp(elevation[active])) if np.any(active) else 0,
        },
        "slope_x_stats": {
            "min": float(np.min(slope_x[active])) if np.any(active) else 0,
            "max": float(np.max(slope_x[active])) if np.any(active) else 0,
            "mean": float(np.mean(np.abs(slope_x[active]))) if np.any(active) else 0,
        },
        "slope_y_stats": {
            "min": float(np.min(slope_y[active])) if np.any(active) else 0,
            "max": float(np.max(slope_y[active])) if np.any(active) else 0,
            "mean": float(np.mean(np.abs(slope_y[active]))) if np.any(active) else 0,
        },
        "sinks_filled": sinks_filled,
        "flat_cells_adjusted": flat_cells,
        "min_slope_threshold": min_slope,
    }
    return result


def main():
    parser = argparse.ArgumentParser(description="Build ParFlow slope fields from DEM")
    parser.add_argument("--domain_json", required=True)
    parser.add_argument("--dem_path", required=True)
    parser.add_argument("--surface_mask_npy", required=True)
    parser.add_argument("--output_dir", required=True)
    parser.add_argument("--min_slope", type=float, default=0.0001)
    parser.add_argument("--smooth", type=int, default=0, help="Smoothing kernel size")
    parser.add_argument("--no_fill_sinks", action="store_true")
    args = parser.parse_args()

    errs = validate_inputs(args.domain_json, args.dem_path, args.surface_mask_npy)
    if errs:
        print(json.dumps({"status": "error", "errors": errs}))
        sys.exit(1)

    result = process(
        args.domain_json, args.dem_path, args.surface_mask_npy,
        args.output_dir, args.min_slope, args.smooth, not args.no_fill_sinks,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
