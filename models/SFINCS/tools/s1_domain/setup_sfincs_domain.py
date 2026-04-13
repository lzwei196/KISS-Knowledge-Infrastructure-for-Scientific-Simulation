#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
==========================================
Tool ID:      setup_sfincs_domain
Stage:        s1_domain
Description:  Define SFINCS computational grid from basin shapefile or bounding box.

Inputs:
  --shp_path:     Path to basin boundary shapefile (or use --bbox)
  --bbox:         Bounding box as "xmin,ymin,xmax,ymax" (alternative to --shp_path)
  --resolution:   Computational grid resolution in meters (default: 100)
  --epsg:         Target EPSG code (default: auto-detect UTM zone)
  --buffer_m:     Buffer around basin boundary in meters (default: 500)
  --output_dir:   Output directory for sfincs.ind, sfincs.msk, grid_info.json

Outputs:
  - grid_info.json: Grid metadata (origin, size, CRS, cell count)
  - sfincs domain parameters for sfincs.inp

Exit codes:
  0 — success
  1 — input validation failed
  2 — processing error
  3 — output validation failed
"""

import sys
import os
import json
import logging
import argparse
import numpy as np
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def get_utm_epsg(lon, lat):
    """Auto-detect UTM zone EPSG code from lon/lat."""
    zone = int((lon + 180) / 6) + 1
    if lat >= 0:
        return 32600 + zone  # Northern hemisphere
    else:
        return 32700 + zone  # Southern hemisphere


def validate_inputs(args):
    """Check that all preconditions are met."""
    errors = []

    if not args.shp_path and not args.bbox:
        errors.append("Either --shp_path or --bbox must be provided")

    if args.shp_path and not Path(args.shp_path).exists():
        errors.append(f"Shapefile not found: {args.shp_path}")

    if args.resolution <= 0:
        errors.append(f"Resolution must be positive, got {args.resolution}")

    if args.resolution < 5:
        errors.append(f"Resolution {args.resolution}m is extremely fine — minimum recommended is 10m")

    if args.resolution > 1000:
        errors.append(f"Resolution {args.resolution}m is very coarse — maximum recommended is 500m")

    if args.buffer_m < 0:
        errors.append(f"Buffer must be non-negative, got {args.buffer_m}")

    if not args.output_dir:
        errors.append("--output_dir is required")

    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)

    logger.info("Input validation passed.")


def process(args):
    """Define SFINCS computational grid."""
    import geopandas as gpd
    from pyproj import Transformer, CRS

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # --- Get basin extent ---
    if args.shp_path:
        gdf = gpd.read_file(args.shp_path)
        logger.info(f"Loaded shapefile with CRS: {gdf.crs}")

        # Get centroid for UTM detection
        centroid = gdf.to_crs("EPSG:4326").geometry.centroid.iloc[0]
        center_lon, center_lat = centroid.x, centroid.y
    else:
        bbox_parts = [float(x) for x in args.bbox.split(",")]
        if len(bbox_parts) != 4:
            logger.error("--bbox must have 4 values: xmin,ymin,xmax,ymax")
            sys.exit(1)
        xmin, ymin, xmax, ymax = bbox_parts
        center_lon = (xmin + xmax) / 2
        center_lat = (ymin + ymax) / 2

    # --- Determine target CRS ---
    if args.epsg:
        target_epsg = args.epsg
    else:
        target_epsg = get_utm_epsg(center_lon, center_lat)
    logger.info(f"Target CRS: EPSG:{target_epsg}")

    target_crs = CRS.from_epsg(target_epsg)

    # --- Get bounding box in target CRS ---
    if args.shp_path:
        gdf_proj = gdf.to_crs(f"EPSG:{target_epsg}")
        bounds = gdf_proj.total_bounds  # xmin, ymin, xmax, ymax
    else:
        transformer = Transformer.from_crs("EPSG:4326", f"EPSG:{target_epsg}", always_xy=True)
        x1, y1 = transformer.transform(xmin, ymin)
        x2, y2 = transformer.transform(xmax, ymax)
        bounds = np.array([min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)])

    # --- Apply buffer ---
    buf = args.buffer_m
    xmin_m = bounds[0] - buf
    ymin_m = bounds[1] - buf
    xmax_m = bounds[2] + buf
    ymax_m = bounds[3] + buf

    # --- Snap to grid ---
    dx = args.resolution
    dy = args.resolution
    x0 = np.floor(xmin_m / dx) * dx
    y0 = np.floor(ymin_m / dy) * dy
    x1 = np.ceil(xmax_m / dx) * dx
    y1 = np.ceil(ymax_m / dy) * dy

    mmax = int((x1 - x0) / dx)
    nmax = int((y1 - y0) / dy)

    total_cells = mmax * nmax
    logger.info(f"Grid: {mmax} x {nmax} = {total_cells} cells at {dx}m resolution")
    logger.info(f"Origin: ({x0}, {y0}), Extent: ({x1 - x0}m x {y1 - y0}m)")

    # --- Estimate active cells (cells inside basin) ---
    if args.shp_path:
        basin_area_m2 = gdf_proj.geometry.area.sum()
        active_cells_est = int(basin_area_m2 / (dx * dy))
    else:
        active_cells_est = total_cells
    logger.info(f"Estimated active cells: {active_cells_est}")

    # --- CFL stability check ---
    # dt_max = dx / sqrt(g * h_max)
    # For 10m flood depth: dt_max = dx / sqrt(9.81 * 10) ~ dx / 9.9
    g = 9.81
    h_max_assumed = 10.0  # meters
    dt_max_cfl = dx / np.sqrt(g * h_max_assumed)
    dt_recommended = max(0.5, min(dt_max_cfl * 0.8, 30.0))  # safety factor 0.8
    logger.info(f"CFL dt_max = {dt_max_cfl:.1f}s (for h_max={h_max_assumed}m), recommended dt = {dt_recommended:.1f}s")

    # --- Build grid_info.json ---
    grid_info = {
        "x0": x0,
        "y0": y0,
        "dx": dx,
        "dy": dy,
        "mmax": mmax,
        "nmax": nmax,
        "rotation": 0.0,
        "epsg": target_epsg,
        "total_cells": total_cells,
        "active_cells_est": active_cells_est,
        "dt_max_cfl": round(dt_max_cfl, 2),
        "dt_recommended": round(dt_recommended, 2),
        "center_lon": center_lon,
        "center_lat": center_lat,
        "bounds_m": [x0, y0, x1, y1],
        "buffer_m": buf,
    }

    # --- Recommend subgrid resolution ---
    subgrid_ratio = max(1, min(int(dx / 10), 20))  # Ratio of 1-20x
    subgrid_res = dx / subgrid_ratio
    grid_info["subgrid_resolution"] = subgrid_res
    grid_info["subgrid_ratio"] = subgrid_ratio
    logger.info(f"Recommended subgrid: {subgrid_res}m ({subgrid_ratio}x ratio)")

    # --- Warn about large domains ---
    if total_cells > 5_000_000:
        logger.warning(f"Very large domain ({total_cells:,} cells). Consider coarsening resolution or reducing extent.")
    elif total_cells > 1_000_000:
        logger.warning(f"Large domain ({total_cells:,} cells). Runtime may be significant.")

    # --- Save ---
    output_path = output_dir / "grid_info.json"
    with open(output_path, "w") as f:
        json.dump(grid_info, f, indent=2)

    logger.info(f"Grid info saved to: {output_path}")

    # --- Print sfincs.inp snippet ---
    inp_snippet = f"""! === Grid definition (paste into sfincs.inp) ===
mmax           = {mmax}
nmax           = {nmax}
dx             = {dx:.1f}
dy             = {dy:.1f}
x0             = {x0:.1f}
y0             = {y0:.1f}
rotation       = 0.0
epsg           = {target_epsg}
"""
    snippet_path = output_dir / "grid_snippet.inp"
    with open(snippet_path, "w") as f:
        f.write(inp_snippet)
    logger.info(f"Grid snippet for sfincs.inp saved to: {snippet_path}")

    # --- JSON result ---
    result = {
        "status": "success",
        "grid_info": str(output_path),
        "grid_snippet": str(snippet_path),
        "mmax": mmax,
        "nmax": nmax,
        "dx": dx,
        "dy": dy,
        "epsg": target_epsg,
        "total_cells": total_cells,
        "active_cells_est": active_cells_est,
        "dt_recommended": dt_recommended,
    }
    print(json.dumps(result, indent=2))
    return str(output_path)


def validate_outputs(output_path):
    """Check outputs."""
    if not Path(output_path).exists():
        logger.error(f"Expected output not created: {output_path}")
        sys.exit(3)

    with open(output_path) as f:
        data = json.load(f)

    if data.get("mmax", 0) <= 0 or data.get("nmax", 0) <= 0:
        logger.error("Grid dimensions are zero or negative")
        sys.exit(3)

    logger.info("Output validation passed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Setup SFINCS computational grid domain")
    parser.add_argument("--shp_path", help="Path to basin boundary shapefile")
    parser.add_argument("--bbox", help="Bounding box: xmin,ymin,xmax,ymax (WGS84)")
    parser.add_argument("--resolution", type=float, default=100.0, help="Grid resolution in meters (default: 100)")
    parser.add_argument("--epsg", type=int, default=None, help="Target EPSG code (default: auto UTM)")
    parser.add_argument("--buffer_m", type=float, default=500.0, help="Buffer around basin in meters (default: 500)")
    parser.add_argument("--output_dir", required=True, help="Output directory")
    args = parser.parse_args()

    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs(args)

    try:
        output_path = process(args)
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(2)

    validate_outputs(output_path)
    sys.exit(0)
