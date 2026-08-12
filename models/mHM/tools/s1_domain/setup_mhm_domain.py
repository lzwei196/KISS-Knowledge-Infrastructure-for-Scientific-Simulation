#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
Tool ID:      setup_mhm_domain
Stage:        s1_domain
Description:  Compute L0/L1/L11 domain grids from basin shapefile and write domain header info.

This tool determines the grid extent (xllcorner, yllcorner, ncols, nrows) for each
of the three mHM grids from the basin shapefile bounding box.

CRITICAL: L1 and L11 resolutions must be exact integer multiples of L0 resolution.

Inputs:
  - CONFIG_PATH: path to config.json from s0_config
  - SHP_PATH: path to basin boundary shapefile

Outputs:
  - domain_info.json: grid headers for L0, L1, L11
  - Used by all s2_morphology tools to generate consistent ASCII grids

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import json
import logging
import math
import numpy as np
from pathlib import Path

try:
    import geopandas as gpd
except ImportError:
    print("ERROR: geopandas required. Install: pip install geopandas")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
CONFIG_PATH = ""
SHP_PATH = ""  # override; if empty, read from config.json

# CLI override
if len(sys.argv) > 1:
    import argparse
    parser = argparse.ArgumentParser(description="Setup mHM domain grids")
    parser.add_argument("--config", required=True, help="Path to config.json")
    parser.add_argument("--shp_path", default="", help="Override shapefile path")
    args = parser.parse_args()
    CONFIG_PATH = args.config
    SHP_PATH = args.shp_path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def validate_inputs():
    errors = []
    if not CONFIG_PATH or not Path(CONFIG_PATH).exists():
        errors.append(f"Config file not found: {CONFIG_PATH}")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def compute_grid_extent(bounds, cellsize, buffer_cells=2):
    """
    Compute ESRI ASCII grid extent aligned to cellsize grid.

    Parameters:
        bounds: (minx, miny, maxx, maxy) in the CRS units
        cellsize: grid cell size in CRS units
        buffer_cells: number of buffer cells to add around the basin

    Returns:
        dict with ncols, nrows, xllcorner, yllcorner, cellsize
    """
    minx, miny, maxx, maxy = bounds

    # Align to grid (snap to nearest cellsize)
    xllcorner = math.floor(minx / cellsize) * cellsize - buffer_cells * cellsize
    yllcorner = math.floor(miny / cellsize) * cellsize - buffer_cells * cellsize
    xur = math.ceil(maxx / cellsize) * cellsize + buffer_cells * cellsize
    yur = math.ceil(maxy / cellsize) * cellsize + buffer_cells * cellsize

    ncols = int(round((xur - xllcorner) / cellsize))
    nrows = int(round((yur - yllcorner) / cellsize))

    return {
        "ncols": ncols,
        "nrows": nrows,
        "xllcorner": xllcorner,
        "yllcorner": yllcorner,
        "cellsize": cellsize,
        "NODATA_value": -9999,
    }


def process():
    config = json.load(open(CONFIG_PATH))
    shp_path = SHP_PATH if SHP_PATH else config["shp_path"]

    if not Path(shp_path).exists():
        logger.error(f"Shapefile not found: {shp_path}")
        sys.exit(1)

    gdf = gpd.read_file(shp_path)
    logger.info(f"Shapefile CRS: {gdf.crs}")
    logger.info(f"Basin area: {gdf.geometry.area.sum() / 1e6:.1f} km2 (in CRS units)")

    # For geographic CRS (EPSG:4326), resolutions are in degrees
    # mHM expects meters in the namelist, but ASCII grids use the CRS native units
    is_geographic = gdf.crs is not None and gdf.crs.is_geographic

    # Get resolution from config (in meters)
    res_L0_m = config["resolution_L0_m"]
    res_L1_m = config["resolution_L1_m"]
    res_L11_m = config["resolution_L11_m"]

    if is_geographic:
        # Convert meters to degrees at basin centroid
        centroid = gdf.geometry.unary_union.centroid
        lat_rad = math.radians(centroid.y)
        m_per_deg = 111000 * math.cos(lat_rad)

        res_L0_deg = res_L0_m / m_per_deg
        res_L1_deg = res_L1_m / m_per_deg
        res_L11_deg = res_L11_m / m_per_deg

        # Round L0 to 2 decimal places for clean degree values (0.01, 0.05, etc.)
        # This ensures L1/L0 ratio stays integer after rounding.
        # Using 4 decimals produces ugly values (0.0107) that don't align cleanly.
        res_L0_deg = round(res_L0_deg, 2)
        ratio_L1 = round(res_L1_m / res_L0_m)
        ratio_L11 = round(res_L11_m / res_L0_m)
        res_L1_deg = res_L0_deg * ratio_L1
        res_L11_deg = res_L0_deg * ratio_L11

        logger.info(f"Geographic CRS: L0={res_L0_deg} deg, L1={res_L1_deg} deg, L11={res_L11_deg} deg")
        logger.info(f"Basin centroid: ({centroid.y:.4f}, {centroid.x:.4f})")

        cellsize_L0 = res_L0_deg
        cellsize_L1 = res_L1_deg
        cellsize_L11 = res_L11_deg
    else:
        cellsize_L0 = res_L0_m
        cellsize_L1 = res_L1_m
        cellsize_L11 = res_L11_m

    # Validate integer multiple relationship
    ratio_L1_L0 = cellsize_L1 / cellsize_L0
    ratio_L11_L0 = cellsize_L11 / cellsize_L0
    if abs(ratio_L1_L0 - round(ratio_L1_L0)) > 0.05:
        logger.error(
            f"FATAL: L1 cellsize ({cellsize_L1}) is not integer multiple of "
            f"L0 cellsize ({cellsize_L0}). Ratio={ratio_L1_L0:.4f}"
        )
        sys.exit(2)
    if abs(ratio_L11_L0 - round(ratio_L11_L0)) > 0.05:
        logger.error(
            f"FATAL: L11 cellsize ({cellsize_L11}) is not integer multiple of "
            f"L0 cellsize ({cellsize_L0}). Ratio={ratio_L11_L0:.4f}"
        )
        sys.exit(2)

    bounds = gdf.total_bounds  # (minx, miny, maxx, maxy)
    logger.info(f"Basin bounds: {bounds}")

    # Compute grid headers
    # L0 is computed from basin bounds with buffer
    header_L0 = compute_grid_extent(bounds, cellsize_L0, buffer_cells=2)

    # CRITICAL (dt_r12): L0 MUST BE SQUARE, with the side an exact multiple of the
    # L1/L11 ratio.  mHM's read_header_ascii() declares (header_ncols, header_nrows,
    # ...) but every call site passes (nrows, ncols, ...) positionally, e.g.
    # mo_meteo_handler.f90.  The ASCII `ncols` line therefore lands in mHM's `nrows`,
    # and calculate_grid_properties() derives xllcornerOut from ncolsIn -- mixing the
    # x-origin with the y-extent.  For a NON-square L0 no geographically correct
    # header can satisfy the L2 check and mHM aborts with
    #   "L2_variable_init: size mismatch in grid file for level2".
    # With a square L0 of side N and ratio R,
    #   xllOut = xll0 + N*cs0 - (N/R)*cs1 = xll0  under either reading.
    # mHM's own test domains are square (240x240), so upstream never trips over it.
    _R = max(int(round(cellsize_L1 / cellsize_L0)), int(round(cellsize_L11 / cellsize_L0)))
    side = int(math.ceil(max(header_L0["ncols"], header_L0["nrows"]) / _R) * _R)
    if side != header_L0["ncols"] or side != header_L0["nrows"]:
        pad_c = side - header_L0["ncols"]
        pad_r = side - header_L0["nrows"]
        # centre the basin in the padded square (nodata fills the pad)
        header_L0["xllcorner"] -= (pad_c // 2) * cellsize_L0
        header_L0["yllcorner"] -= (pad_r // 2) * cellsize_L0
        logger.info(
            f"Padding L0 to a square: {header_L0['ncols']}x{header_L0['nrows']} "
            f"-> {side}x{side} (pad {pad_c} cols, {pad_r} rows; multiple of R={_R})"
        )
        header_L0["ncols"] = side
        header_L0["nrows"] = side

    # CRITICAL: L1 and L11 must be derived from L0 grid dimensions, NOT from basin bounds.
    # mHM internally computes L1 as: nrows_L1 = ceil(nrows_L0 / R), ncols_L1 = ceil(ncols_L0 / R)
    # and uses L0's xllcorner/yllcorner as the origin. If we compute L1 independently
    # from bounds, the dimensions won't match what mHM expects → "size mismatch" error.
    R_L1 = int(round(cellsize_L1 / cellsize_L0))
    R_L11 = int(round(cellsize_L11 / cellsize_L0))

    header_L1 = {
        "ncols": -(-header_L0["ncols"] // R_L1),  # ceil division
        "nrows": -(-header_L0["nrows"] // R_L1),
        "xllcorner": header_L0["xllcorner"],
        "yllcorner": header_L0["yllcorner"],
        "cellsize": cellsize_L1,
        "NODATA_value": -9999,
    }
    header_L11 = {
        "ncols": -(-header_L0["ncols"] // R_L11),
        "nrows": -(-header_L0["nrows"] // R_L11),
        "xllcorner": header_L0["xllcorner"],
        "yllcorner": header_L0["yllcorner"],
        "cellsize": cellsize_L11,
        "NODATA_value": -9999,
    }

    logger.info(f"L0 grid: {header_L0['ncols']}x{header_L0['nrows']} cells")
    logger.info(f"L1 grid: {header_L1['ncols']}x{header_L1['nrows']} cells")
    logger.info(f"L11 grid: {header_L11['ncols']}x{header_L11['nrows']} cells")

    domain_info = {
        "basin_name": config["basin_name"],
        "shp_path": str(shp_path),
        "crs": str(gdf.crs),
        "is_geographic": is_geographic,
        "bounds": list(bounds),
        "resolution_L0_m": res_L0_m,
        "resolution_L1_m": res_L1_m,
        "resolution_L11_m": res_L11_m,
        "header_L0": header_L0,
        "header_L1": header_L1,
        "header_L11": header_L11,
    }

    output_dir = Path(config["output_dir"])
    output_path = output_dir / "domain_info.json"
    with open(output_path, "w") as f:
        json.dump(domain_info, f, indent=2)

    print(json.dumps({
        "status": "success",
        "L0_cells": header_L0["ncols"] * header_L0["nrows"],
        "L1_cells": header_L1["ncols"] * header_L1["nrows"],
        "L11_cells": header_L11["ncols"] * header_L11["nrows"],
        "domain_info_path": str(output_path),
    }, indent=2))

    return str(output_path)


def validate_outputs(output_path):
    if not Path(output_path).exists():
        logger.error(f"domain_info.json not created: {output_path}")
        sys.exit(3)

    info = json.load(open(output_path))
    for level in ["header_L0", "header_L1", "header_L11"]:
        h = info[level]
        if h["ncols"] <= 0 or h["nrows"] <= 0:
            logger.error(f"{level} has zero dimensions: ncols={h['ncols']}, nrows={h['nrows']}")
            sys.exit(3)
    logger.info("Output validation passed.")


if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs()
    try:
        output_path = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        import traceback; traceback.print_exc()
        sys.exit(2)
    validate_outputs(output_path)
    sys.exit(0)
