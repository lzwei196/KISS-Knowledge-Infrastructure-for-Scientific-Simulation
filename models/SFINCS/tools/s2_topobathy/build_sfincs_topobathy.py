#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
==========================================
Tool ID:      build_sfincs_topobathy
Stage:        s2_topobathy
Description:  Build SFINCS topography/bathymetry from DEM. Generates sfincs.dep (bed level)
              and sfincs.msk (active cell mask). Optionally builds subgrid tables.

Inputs:
  --grid_info:    Path to grid_info.json from s1_domain
  --dem_path:     Path to DEM raster (GeoTIFF). Auto-selects China DEM 90m or Copernicus GLO-30.
  --shp_path:     Path to basin shapefile (for masking active cells)
  --output_dir:   Output directory
  --nodata_fill:  Value for cells outside DEM coverage (default: -9999)

Outputs:
  - sfincs.dep:   Bed level / topography file (binary float32, row-major)
  - sfincs.msk:   Active cell mask (binary uint8: 0=inactive, 1=boundary inflow, 2=outflow, 3=active)
  - sfincs.ind:   Index file for subgrid (binary int32)
  - topobathy_summary.json: Statistics

Exit codes:
  0 — success, 1 — input error, 2 — processing error, 3 — output error
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

# --- Default DEM paths ---
CHINA_DEM = "/mnt/disk1/Hydrocraft_server/data/dem/china_dem_90m/china_dem_90m.tif"


def validate_inputs(args):
    errors = []
    if not Path(args.grid_info).exists():
        errors.append(f"Grid info not found: {args.grid_info}")
    if args.dem_path and not Path(args.dem_path).exists():
        errors.append(f"DEM not found: {args.dem_path}")
    if args.shp_path and not Path(args.shp_path).exists():
        errors.append(f"Shapefile not found: {args.shp_path}")
    if not args.output_dir:
        errors.append("--output_dir is required")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def auto_select_dem(center_lon, center_lat):
    """Auto-select DEM based on location."""
    # China bounding box (rough)
    if 73 <= center_lon <= 135 and 18 <= center_lat <= 54:
        if Path(CHINA_DEM).exists():
            logger.info("Auto-selected China DEM 90m")
            return CHINA_DEM
    logger.info("Location outside China or China DEM unavailable — need Copernicus GLO-30 or user DEM")
    return None


def process(args):
    import rasterio
    from rasterio.warp import reproject, Resampling, calculate_default_transform
    from rasterio.mask import mask as rio_mask
    from pyproj import CRS
    import geopandas as gpd

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # --- Load grid info ---
    with open(args.grid_info) as f:
        grid = json.load(f)

    x0 = grid["x0"]
    y0 = grid["y0"]
    dx = grid["dx"]
    dy = grid["dy"]
    mmax = grid["mmax"]
    nmax = grid["nmax"]
    epsg = grid["epsg"]
    target_crs = CRS.from_epsg(epsg)

    logger.info(f"Grid: {mmax}x{nmax}, dx={dx}m, origin=({x0},{y0}), EPSG:{epsg}")

    # --- Select DEM ---
    dem_path = args.dem_path
    if not dem_path:
        dem_path = auto_select_dem(grid.get("center_lon", 0), grid.get("center_lat", 0))
    if not dem_path or not Path(dem_path).exists():
        logger.error("No DEM available. Provide --dem_path or ensure China DEM exists.")
        sys.exit(2)

    # --- Resample DEM to SFINCS grid ---
    logger.info(f"Reading DEM: {dem_path}")
    with rasterio.open(dem_path) as src:
        # Define target transform
        from rasterio.transform import from_origin
        # SFINCS uses top-left origin convention for raster output
        # But grid y0 is bottom-left. Need y0 + nmax*dy for top
        y_top = y0 + nmax * dy
        target_transform = from_origin(x0, y_top, dx, dy)

        # Reproject DEM to target grid
        dem_data = np.zeros((nmax, mmax), dtype=np.float32)
        reproject(
            source=rasterio.band(src, 1),
            destination=dem_data,
            src_transform=src.transform,
            src_crs=src.crs,
            dst_transform=target_transform,
            dst_crs=target_crs,
            resampling=Resampling.bilinear,
            dst_nodata=args.nodata_fill,
        )

    logger.info(f"DEM resampled to grid. Shape: {dem_data.shape}")
    logger.info(f"Elevation range: {np.nanmin(dem_data[dem_data > -9000]):.1f} to "
                f"{np.nanmax(dem_data[dem_data > -9000]):.1f} m")

    # --- Build mask ---
    # SFINCS mask convention: 0=inactive, 1=active (computed), 2=outflow, 3=water level BC
    # Interior cells MUST be 1, NOT 3. Using 3 makes SFINCS expect prescribed water
    # levels instead of computing them. Bug found 2026-04-11 Wangjiaba test.
    msk = np.zeros((nmax, mmax), dtype=np.uint8)

    if args.shp_path:
        gdf = gpd.read_file(args.shp_path).to_crs(f"EPSG:{epsg}")
        # Rasterize shapefile to grid
        from rasterio.features import rasterize
        shapes = [(geom, 1) for geom in gdf.geometry]
        basin_mask = rasterize(
            shapes,
            out_shape=(nmax, mmax),
            transform=target_transform,
            fill=0,
            dtype=np.uint8,
        )
        # Active cells inside basin = 1 (NOT 3)
        msk[basin_mask == 1] = 1
    else:
        # All cells with valid DEM data are active
        msk[dem_data > -9000] = 1

    # Set boundary cells (edges of active domain) to outflow (2)
    active = (msk == 1)
    # Find edge cells using convolution
    from scipy.ndimage import binary_erosion
    interior = binary_erosion(active, structure=np.ones((3, 3)))
    edge = active & ~interior
    msk[edge] = 2  # outflow boundary

    active_count = int(np.sum(msk > 0))
    outflow_count = int(np.sum(msk == 2))
    logger.info(f"Active cells: {active_count}, Outflow boundary: {outflow_count}")

    if active_count == 0:
        logger.error("No active cells! Check shapefile alignment with DEM and CRS.")
        sys.exit(2)

    # --- Replace nodata with reasonable value in inactive cells ---
    dem_data[msk == 0] = args.nodata_fill

    # --- Build index file in SFINCS v2 format ---
    # Format: [n_active (int32)] [flat_index_1 (int32)] ... [flat_index_n (int32)]
    # Flat indices are 1-based, row-major (C order)
    active_flat = np.where(msk.flatten(order='C') > 0)[0]
    n_active = len(active_flat)
    active_1based = (active_flat + 1).astype(np.int32)  # 1-based indexing

    # --- Write binary files ---
    dep_path = output_dir / "sfincs.dep"
    msk_path = output_dir / "sfincs.msk"
    ind_path = output_dir / "sfincs.ind"

    dem_data.astype(np.float32).tofile(str(dep_path))
    msk.astype(np.uint8).tofile(str(msk_path))
    # Write index: header (n_active) + body (flat indices)
    with open(str(ind_path), 'wb') as f_ind:
        np.array([n_active], dtype=np.int32).tofile(f_ind)
        active_1based.tofile(f_ind)

    logger.info(f"Wrote: {dep_path} ({dep_path.stat().st_size} bytes)")
    logger.info(f"Wrote: {msk_path} ({msk_path.stat().st_size} bytes)")
    logger.info(f"Wrote: {ind_path} ({ind_path.stat().st_size} bytes)")

    # --- Summary ---
    valid_dem = dem_data[msk > 0]
    summary = {
        "status": "success",
        "dep_file": str(dep_path),
        "msk_file": str(msk_path),
        "ind_file": str(ind_path),
        "grid_shape": [nmax, mmax],
        "total_cells": mmax * nmax,
        "active_cells": active_count,
        "outflow_cells": outflow_count,
        "elevation_min": float(np.nanmin(valid_dem)) if len(valid_dem) > 0 else None,
        "elevation_max": float(np.nanmax(valid_dem)) if len(valid_dem) > 0 else None,
        "elevation_mean": float(np.nanmean(valid_dem)) if len(valid_dem) > 0 else None,
        "dem_source": str(dem_path),
    }

    summary_path = output_dir / "topobathy_summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    print(json.dumps(summary, indent=2))
    return str(summary_path)


def validate_outputs(output_path):
    if not Path(output_path).exists():
        logger.error(f"Summary not created: {output_path}")
        sys.exit(3)

    parent = Path(output_path).parent
    for fname in ["sfincs.dep", "sfincs.msk", "sfincs.ind"]:
        fpath = parent / fname
        if not fpath.exists() or fpath.stat().st_size == 0:
            logger.error(f"Output file missing or empty: {fpath}")
            sys.exit(3)

    logger.info("Output validation passed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build SFINCS topography/bathymetry")
    parser.add_argument("--grid_info", required=True, help="Path to grid_info.json")
    parser.add_argument("--dem_path", default=None, help="Path to DEM raster (auto-selects if omitted)")
    parser.add_argument("--shp_path", default=None, help="Basin shapefile for masking")
    parser.add_argument("--output_dir", required=True, help="Output directory")
    parser.add_argument("--nodata_fill", type=float, default=-9999, help="Fill value for nodata")
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
