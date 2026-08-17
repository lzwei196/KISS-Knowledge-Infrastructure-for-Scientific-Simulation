#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
==========================================
Tool ID:      create_grid_from_basin
Stage:        s2_grid_discretization
Description:  Generate a structured MODFLOW grid from a basin boundary shapefile.
              Computes NROW, NCOL from basin extent and cell size.
              Creates IDOMAIN mask from shapefile intersection.

Inputs:
  - SHAPEFILE_PATH: basin boundary .shp
  - CELL_SIZE: grid cell size in meters
  - NLAY: number of model layers
  - LAYER_BOTTOMS: bottom elevations relative to surface (negative values)
  - DEM_PATH: DEM raster for TOP elevation (optional)

Outputs:
  - JSON with nlay, nrow, ncol, delr, delc, top, botm, idomain info

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
import numpy as np
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SHAPEFILE_PATH = "KISSPATH_DATA/shp/qinghai_lake_shp2/qinghai_lake_boundary_shp/qinghai_lake_boundary.shp"       # Basin boundary shapefile
CELL_SIZE = 25000          # Grid cell size in meters
NLAY = 2                  # Number of layers
LAYER_BOTTOMS = [-50, -200]  # Bottom elevations relative to surface (m)
DEM_PATH = ""             # Optional DEM for surface elevation
DEFAULT_TOP = 3194.0       # Default land surface elevation if no DEM

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def validate_inputs():
    """Check preconditions."""
    errors = []
    if not SHAPEFILE_PATH or not Path(SHAPEFILE_PATH).exists():
        errors.append(f"Shapefile not found: {SHAPEFILE_PATH}")
    if CELL_SIZE <= 0:
        errors.append(f"Cell size must be positive: {CELL_SIZE}")
    if NLAY < 1:
        errors.append(f"NLAY must be >= 1: {NLAY}")
    if len(LAYER_BOTTOMS) != NLAY:
        errors.append(f"LAYER_BOTTOMS length ({len(LAYER_BOTTOMS)}) must equal NLAY ({NLAY})")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def process():
    """Create grid from basin shapefile."""
    import geopandas as gpd
    from shapely.geometry import box

    # Read basin shapefile
    basin = gpd.read_file(SHAPEFILE_PATH)
    logger.info(f"Basin CRS: {basin.crs}")

    # Get bounds
    minx, miny, maxx, maxy = basin.total_bounds
    logger.info(f"Basin bounds: ({minx:.2f}, {miny:.2f}) to ({maxx:.2f}, {maxy:.2f})")

    # If geographic CRS, estimate meter-equivalent cell size
    if basin.crs and basin.crs.is_geographic:
        logger.warning("Basin is in geographic CRS (degrees). Converting cell size.")
        # Approximate: 1 degree latitude ~ 111,000 m
        center_lat = (miny + maxy) / 2
        deg_per_m_lat = 1.0 / 111000.0
        deg_per_m_lon = 1.0 / (111000.0 * np.cos(np.radians(center_lat)))
        delr_deg = CELL_SIZE * deg_per_m_lon
        delc_deg = CELL_SIZE * deg_per_m_lat
    else:
        delr_deg = CELL_SIZE
        delc_deg = CELL_SIZE

    # Compute grid dimensions
    ncol = int(np.ceil((maxx - minx) / delr_deg))
    nrow = int(np.ceil((maxy - miny) / delc_deg))
    logger.info(f"Grid: {NLAY} layers x {nrow} rows x {ncol} cols = {NLAY * nrow * ncol} cells")

    # Grid origin (lower-left corner)
    xorigin = minx
    yorigin = miny

    # Create DELR and DELC arrays
    delr = np.full(ncol, delr_deg)
    delc = np.full(nrow, delc_deg)

    # Create TOP array
    if DEM_PATH and Path(DEM_PATH).exists():
        try:
            import rasterio
            from rasterio.transform import from_bounds
            with rasterio.open(DEM_PATH) as src:
                # Resample DEM to grid
                top = np.full((nrow, ncol), DEFAULT_TOP)
                for i in range(nrow):
                    for j in range(ncol):
                        cx = xorigin + (j + 0.5) * delr_deg
                        cy = yorigin + (nrow - i - 0.5) * delc_deg
                        row_dem, col_dem = src.index(cx, cy)
                        if 0 <= row_dem < src.height and 0 <= col_dem < src.width:
                            val = src.read(1)[row_dem, col_dem]
                            if val != src.nodata:
                                top[i, j] = float(val)
            logger.info(f"TOP from DEM: {top.min():.1f} to {top.max():.1f} m")
        except Exception as e:
            logger.warning(f"Could not read DEM: {e}. Using DEFAULT_TOP={DEFAULT_TOP}")
            top = np.full((nrow, ncol), DEFAULT_TOP)
    else:
        top = np.full((nrow, ncol), DEFAULT_TOP)
        logger.info(f"Using uniform TOP = {DEFAULT_TOP} m")

    # Create BOTM array
    botm = np.zeros((NLAY, nrow, ncol))
    for k in range(NLAY):
        botm[k] = top + LAYER_BOTTOMS[k]  # LAYER_BOTTOMS are negative

    # Create IDOMAIN from shapefile intersection
    idomain = np.zeros((NLAY, nrow, ncol), dtype=int)
    basin_geom = basin.geometry.unary_union

    for i in range(nrow):
        for j in range(ncol):
            cx = xorigin + (j + 0.5) * delr_deg
            cy = yorigin + (nrow - i - 0.5) * delc_deg
            cell_box = box(
                cx - delr_deg / 2, cy - delc_deg / 2,
                cx + delr_deg / 2, cy + delc_deg / 2
            )
            if basin_geom.intersects(cell_box):
                overlap = basin_geom.intersection(cell_box).area / cell_box.area
                if overlap > 0.1:  # At least 10% overlap
                    idomain[:, i, j] = 1

    active_cells = (idomain > 0).sum()
    logger.info(f"Active cells: {active_cells} / {NLAY * nrow * ncol}")

    result = {
        "nlay": NLAY,
        "nrow": nrow,
        "ncol": ncol,
        "delr": float(delr_deg),
        "delc": float(delc_deg),
        "xorigin": float(xorigin),
        "yorigin": float(yorigin),
        "top_min": float(top.min()),
        "top_max": float(top.max()),
        "active_cells": int(active_cells),
        "total_cells": int(NLAY * nrow * ncol),
        "layer_bottoms_relative": LAYER_BOTTOMS,
    }

    return result


def validate_outputs(result):
    """Check grid is reasonable."""
    errors = []
    if result["active_cells"] == 0:
        errors.append("No active cells — shapefile may not overlap grid")
    if result["nrow"] > 10000 or result["ncol"] > 10000:
        errors.append(f"Grid too large: {result['nrow']}x{result['ncol']}. Increase cell size.")
    if errors:
        for e in errors:
            logger.error(e)
        print(json.dumps(result, indent=2))
        sys.exit(3)
    logger.info("Output validation passed.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")

    validate_inputs()

    try:
        result = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        import traceback; traceback.print_exc()
        sys.exit(2)

    validate_outputs(result)

    print(json.dumps(result, indent=2))
    logger.info("Grid creation complete.")
    sys.exit(0)
