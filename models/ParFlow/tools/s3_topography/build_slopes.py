#!/usr/bin/env python3
"""
Compute slope fields (slope_x, slope_y) from DEM for ParFlow overland flow.

ParFlow overland flow routing uses x-direction and y-direction slopes
(dz/dx, dz/dy) to determine surface water flow direction and speed.

CRITICAL: Unfilled DEM sinks create extreme pressure gradients -> solver crash.
CRITICAL: Minimum slope ~0.0001 to prevent zero-velocity ponding.
CRITICAL: Slope sign convention: positive slope in positive coordinate direction.

Every cell of the rectangular grid gets its own DEM slope, inside AND outside
the basin mask: the s7 run script uses Box geometry (no SolidFile), so ParFlow
routes overland flow over every cell of the rectangle. (Zero slopes outside the
mask made those simulated cells flat ponds.) A cell with no DEM value stops the
tool; DEM voids are never filled with a neighbour's value. The basin mask is
only used to report basin statistics.

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


HYDROCRAFT_ROOT = "KISSPATH_ROOT"
CHINA_DEM = os.path.join(HYDROCRAFT_ROOT, "data/dem/china_dem_90m/china_dem_90m.tif")


def fill_sinks_simple(elevation, mask, max_iterations=None, epsilon=0.001):
    """
    Priority-flood depression filling (Barnes et al. 2014, epsilon variant).
    Seeds are the grid's edge cells (water leaves the Box there); cells are
    taken lowest-first and every neighbour is raised to at least
    (current + epsilon), so every cell, including multi-cell and flat-floored
    depressions, ends with a strictly downhill 4-neighbour path to the edge.
    Cells with mask == 0 are left unchanged and act as outlets (callers in
    this KI pass an all-ones mask: the whole Box is simulated).
    max_iterations is ignored (kept for call compatibility).
    """
    import heapq
    filled = np.array(elevation, dtype=np.float64, copy=True)
    ny, nx = filled.shape
    done = np.zeros((ny, nx), dtype=bool)
    heap = []
    for j in range(ny):
        for i in range(nx):
            if j in (0, ny - 1) or i in (0, nx - 1) or mask[j, i] == 0:
                done[j, i] = True
                heapq.heappush(heap, (filled[j, i], j, i))
    while heap:
        z, j, i = heapq.heappop(heap)
        for dj, di in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nj, ni = j + dj, i + di
            if 0 <= nj < ny and 0 <= ni < nx and not done[nj, ni]:
                done[nj, ni] = True
                if filled[nj, ni] < z + epsilon:
                    filled[nj, ni] = z + epsilon
                heapq.heappush(heap, (filled[nj, ni], nj, ni))
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
    with open(domain_json) as f:
        domain = json.load(f)

    mask_2d = np.load(surface_mask_npy)
    grid = domain["grid"]
    nx, ny = grid["nx"], grid["ny"]
    dx, dy = grid["dx"], grid["dy"]
    origin_x = domain["origin"]["x"]
    origin_y = domain["origin"]["y"]
    utm_epsg = domain["crs"]["epsg"]
    if mask_2d.shape != (ny, nx):
        raise ValueError(f"surface mask shape {mask_2d.shape} does not match grid ({ny}, {nx})")

    # Resample DEM to ParFlow grid
    dst_crs = CRS.from_epsg(utm_epsg)
    dst_transform = from_bounds(origin_x, origin_y,
                                origin_x + nx * dx, origin_y + ny * dy,
                                nx, ny)
    # Start as NaN so grid cells the DEM does not cover stay NaN (a zero
    # start would turn them into sea-level ground).
    elevation = np.full((ny, nx), np.nan, dtype=np.float64)

    with rasterio.open(dem_path) as src:
        reproject(
            source=rasterio.band(src, 1),
            destination=elevation,
            src_transform=src.transform,
            src_crs=src.crs,
            src_nodata=src.nodata,
            dst_transform=dst_transform,
            dst_crs=dst_crs,
            dst_nodata=np.nan,
            resampling=Resampling.bilinear,
        )

    # from_bounds gives a north-up raster (row 0 = NORTH edge). Every other
    # KI tool, and ParFlow's PFB layout, index j = 0 as the SOUTH row (cell
    # centre y = origin_y + (j + 0.5) * dy). Flip so row j matches them;
    # without it the elevation map was mirrored north-south against the mask,
    # soil and CLM maps, and slope_y = (z[j+1] - z[j]) / dy had the wrong sign.
    elevation = elevation[::-1, :].copy()

    # Missing DEM anywhere in the Box stops the tool (no neighbour fill)
    nodata_mask = ~np.isfinite(elevation) | (elevation < -9990)
    if np.any(nodata_mask):
        jj, ii = np.nonzero(nodata_mask)
        n_out = int(np.sum(nodata_mask & (mask_2d == 0)))
        cells = [f"(i={i}, j={j}, {'inside' if mask_2d[j, i] else 'OUTSIDE'} basin mask)"
                 for j, i in list(zip(jj, ii))[:10]]
        raise ValueError(
            f"DEM {dem_path} has no value for {int(nodata_mask.sum())} grid cell(s) "
            f"({n_out} outside the basin mask); no fill value is used. The run script uses "
            f"Box geometry, so every cell of the rectangle needs a real elevation: use a DEM "
            f"that covers the whole domain rectangle, or shrink/move it. First "
            f"{len(cells)}: " + ", ".join(cells))

    # Fill sinks over the whole Box (every cell is simulated)
    every_cell = np.ones((ny, nx), dtype=np.int32)
    sinks_filled = 0
    if fill_sinks:
        elev_before = elevation.copy()
        elevation = fill_sinks_simple(elevation, every_cell)
        sinks_filled = int(np.sum(elevation != elev_before))

    # Smooth if requested (whole Box)
    if smooth_sigma > 0:
        elevation = uniform_filter(elevation, size=smooth_sigma)

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

    # Apply minimum slope in every cell (outside-mask cells are simulated too)
    flat_cells = 0
    for j in range(ny):
        for i in range(nx):
            mag = np.sqrt(slope_x[j, i]**2 + slope_y[j, i]**2)
            if mag < min_slope:
                # Apply minimum slope in direction of steepest descent
                # Default: toward lower x (arbitrary but consistent)
                slope_x[j, i] = -min_slope
                flat_cells += 1

    # Save outputs
    os.makedirs(output_dir, exist_ok=True)
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

    def _stats(sel):
        return {
            "elevation": {"min": float(np.min(elevation[sel])), "max": float(np.max(elevation[sel])),
                          "mean": float(np.mean(elevation[sel]))},
            "mean_abs_slope_x": float(np.mean(np.abs(slope_x[sel]))),
            "mean_abs_slope_y": float(np.mean(np.abs(slope_y[sel]))),
        } if np.any(sel) else None

    # Headline stats are over every simulated cell (the whole Box)
    active = np.ones((ny, nx), dtype=bool)
    result = {
        "status": "success",
        "output_files": outputs,
        "slope_cells": ("every cell of the rectangular grid (s7 uses Box geometry, so "
                        "cells outside the basin mask are simulated with their own DEM slope)"),
        "cells_outside_mask": int(np.sum(mask_2d == 0)),
        "inside_basin_mask": _stats(mask_2d > 0),
        "outside_basin_mask": _stats(mask_2d == 0),
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

    try:
        result = process(
            args.domain_json, args.dem_path, args.surface_mask_npy,
            args.output_dir, args.min_slope, args.smooth, not args.no_fill_sinks,
        )
    except (ValueError, OSError, KeyError) as exc:
        print(json.dumps({"status": "error", "errors": [str(exc)]}))
        sys.exit(1)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
