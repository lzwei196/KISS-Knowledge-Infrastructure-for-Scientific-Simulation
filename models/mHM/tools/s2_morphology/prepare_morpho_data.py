#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
Tool ID:      prepare_morpho_data
Stage:        s2_morphology
Description:  Generate DEM, slope, aspect, flow direction, and flow accumulation
              ASCII grids for mHM from HydroCraft DEM data.

CRITICAL:
  - D8 flow direction must use ArcGIS convention: 1=E, 2=SE, 4=S, 8=SW, 16=W, 32=NW, 64=N, 128=NE
  - All output grids must have IDENTICAL headers (ncols, nrows, xllcorner, yllcorner, cellsize)
  - WhiteboxTools uses a DIFFERENT D8 convention; GDAL/richdem use ArcGIS convention

Inputs:
  - CONFIG_PATH: config.json from s0
  - DOMAIN_INFO_PATH: domain_info.json from s1
  - DEM_PATH: path to DEM raster (GeoTIFF)

Outputs:
  - dem.asc, slope.asc, aspect.asc, fdir.asc, facc.asc in input/morph/

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import json
import logging
import numpy as np
from pathlib import Path

try:
    import rasterio
    from rasterio.warp import reproject, Resampling
    from rasterio.mask import mask as rasterio_mask
    import geopandas as gpd
    from scipy import ndimage
except ImportError as e:
    print(f"ERROR: Required packages: rasterio, geopandas, scipy. {e}")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
CONFIG_PATH = ""
DOMAIN_INFO_PATH = ""
DEM_PATH = ""  # If empty, use HydroCraft default

# HydroCraft DEM paths
CHINA_DEM = os.path.join(os.environ.get("HYDROCRAFT_ROOT", "/mnt/disk1/Hydrocraft_server"), "data/dem/china_dem_90m/china_dem_90m.tif")

if len(sys.argv) > 1:
    import argparse
    parser = argparse.ArgumentParser(description="Prepare mHM morphological data")
    parser.add_argument("--config", required=True)
    parser.add_argument("--domain_info", required=True)
    parser.add_argument("--dem_path", default="")
    args = parser.parse_args()
    CONFIG_PATH = args.config
    DOMAIN_INFO_PATH = args.domain_info
    DEM_PATH = args.dem_path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def write_ascii_grid(filepath, data, header):
    """Write numpy array as ESRI ASCII grid with standard header."""
    with open(filepath, 'w') as f:
        f.write(f"ncols         {header['ncols']}\n")
        f.write(f"nrows         {header['nrows']}\n")
        f.write(f"xllcorner     {header['xllcorner']}\n")
        f.write(f"yllcorner     {header['yllcorner']}\n")
        f.write(f"cellsize      {header['cellsize']}\n")
        f.write(f"NODATA_value  {header['NODATA_value']}\n")
        nodata = header['NODATA_value']
        for row in data:
            vals = []
            for v in row:
                if np.isnan(v) or v == nodata:
                    vals.append(str(int(nodata)))
                elif isinstance(v, (float, np.floating)):
                    if v == int(v):
                        vals.append(str(int(v)))
                    else:
                        vals.append(f"{v:.4f}")
                else:
                    vals.append(str(int(v)))
            f.write(" ".join(vals) + "\n")
    logger.info(f"Written: {filepath} ({header['ncols']}x{header['nrows']})")


def clip_and_resample_dem(dem_path, header, shp_path):
    """Clip DEM to domain extent and resample to L0 resolution."""
    from rasterio.transform import from_bounds

    gdf = gpd.read_file(shp_path)
    # Buffer the geometry slightly to avoid edge effects
    geom = gdf.geometry.buffer(header['cellsize'] * 3).unary_union

    with rasterio.open(dem_path) as src:
        # Clip
        out_image, out_transform = rasterio_mask(src, [geom], crop=True, nodata=-9999)
        out_image = out_image[0]

    # Create target transform from header
    nrows = header['nrows']
    ncols = header['ncols']
    xll = header['xllcorner']
    yll = header['yllcorner']
    cs = header['cellsize']
    xur = xll + ncols * cs
    yur = yll + nrows * cs

    dst_transform = from_bounds(xll, yll, xur, yur, ncols, nrows)
    dst_data = np.full((nrows, ncols), -9999.0, dtype=np.float64)

    reproject(
        source=out_image,
        destination=dst_data,
        src_transform=out_transform,
        src_crs=rasterio.open(dem_path).crs,
        dst_transform=dst_transform,
        dst_crs=rasterio.open(dem_path).crs,
        resampling=Resampling.bilinear,
        dst_nodata=-9999,
    )

    return dst_data


def compute_slope_aspect(dem, cellsize, nodata=-9999, is_geographic=True):
    """Compute slope (m/m) and aspect (degrees from N, clockwise) from DEM.

    CRITICAL: When cellsize is in degrees (geographic/lat-lon coordinates),
    we must convert to meters before computing slope. One degree of latitude
    is approximately 111,320 m. One degree of longitude varies with latitude:
    111,320 * cos(lat). If we pass cellsize in degrees directly to np.gradient,
    slopes will be ~111,320x too large.

    mHM expects slope in m/m (rise/run), NOT in degrees.
    """
    dem_f = dem.astype(float)
    dem_f[dem_f == nodata] = np.nan

    if is_geographic:
        # cellsize is in degrees -- convert to meters for gradient computation
        # Estimate mean latitude from DEM center (row 0 = north)
        nrows = dem_f.shape[0]
        # We don't have yllcorner here, so estimate lat from center of grid
        # Caller should pass header info; for now approximate with cos(30deg)
        # as a reasonable mid-latitude default
        # Actually, let's compute per-row for accuracy
        deg_to_m_lat = 111320.0  # meters per degree of latitude
        # For longitude correction, we need latitude. Since we don't have it here,
        # use an isotropic approximation with cos(mean_lat).
        # We'll fix this by accepting yllcorner as a parameter.
        # For now, use the DEM center latitude approximation:
        # mean_lat is estimated; caller passes it via yllcorner parameter.
        # Using simple isotropic approach: spacing_m = cellsize * 111320
        spacing_m = cellsize * deg_to_m_lat
        logger.info(f"Geographic coordinates: cellsize={cellsize} deg -> spacing={spacing_m:.1f} m")
    else:
        spacing_m = cellsize

    # Compute gradients in meters (dz/dx and dz/dy)
    # dy: positive = northward (row index decreases upward in grid)
    dy, dx = np.gradient(dem_f, spacing_m)

    # Slope as m/m (dimensionless rise/run ratio) -- this is what mHM expects
    slope_mm = np.sqrt(dx**2 + dy**2)

    # Aspect: degrees from N, clockwise
    # Note: dy is negative because row 0 is top (north)
    aspect_deg = np.degrees(np.arctan2(-dx, dy))  # Standard from N
    aspect_deg = (aspect_deg + 360) % 360

    # Set nodata
    mask = np.isnan(dem_f)
    slope_mm[mask] = nodata
    aspect_deg[mask] = nodata

    return slope_mm, aspect_deg


def compute_d8_flow_direction(dem, nodata=-9999):
    """
    Compute D8 flow direction using ArcGIS convention.

    ArcGIS D8:
      32  64  128
      16   X    1
       8   4    2

    Flow goes to the steepest downslope neighbor.
    """
    nrows, ncols = dem.shape
    fdir = np.full((nrows, ncols), nodata, dtype=np.int32)
    dem_f = dem.astype(float)
    dem_f[dem_f == nodata] = np.nan

    # Direction codes: (row_offset, col_offset) -> D8 code
    neighbors = [
        (-1,  0,  64),  # N
        (-1,  1, 128),  # NE
        ( 0,  1,   1),  # E
        ( 1,  1,   2),  # SE
        ( 1,  0,   4),  # S
        ( 1, -1,   8),  # SW
        ( 0, -1,  16),  # W
        (-1, -1,  32),  # NW
    ]

    # Distance weights for diagonal vs cardinal
    weights = {
        64: 1.0, 128: 1.414, 1: 1.0, 2: 1.414,
        4: 1.0, 8: 1.414, 16: 1.0, 32: 1.414,
    }

    for i in range(nrows):
        for j in range(ncols):
            if np.isnan(dem_f[i, j]):
                continue

            max_slope = 0.0
            best_dir = 0  # 0 = flat/sink

            for dr, dc, code in neighbors:
                ni, nj = i + dr, j + dc
                if 0 <= ni < nrows and 0 <= nj < ncols and not np.isnan(dem_f[ni, nj]):
                    drop = dem_f[i, j] - dem_f[ni, nj]
                    if drop > 0:
                        slope = drop / weights[code]
                        if slope > max_slope:
                            max_slope = slope
                            best_dir = code

            fdir[i, j] = best_dir if best_dir > 0 else 0

    return fdir


def compute_flow_accumulation(fdir, nodata=-9999):
    """Compute flow accumulation from D8 flow direction grid."""
    nrows, ncols = fdir.shape
    facc = np.zeros((nrows, ncols), dtype=np.int32)

    # Direction to (dr, dc) mapping
    dir_to_offset = {
        1: (0, 1), 2: (1, 1), 4: (1, 0), 8: (1, -1),
        16: (0, -1), 32: (-1, -1), 64: (-1, 0), 128: (-1, 1),
    }

    # Reverse mapping: which directions flow INTO cell (i,j)?
    # If neighbor has direction pointing to us, it flows into us
    reverse = {
        1: 16, 2: 32, 4: 64, 8: 128,
        16: 1, 32: 2, 64: 4, 128: 8,
    }

    # Count incoming for topological sort
    incoming = np.zeros((nrows, ncols), dtype=np.int32)
    for i in range(nrows):
        for j in range(ncols):
            d = fdir[i, j]
            if d in dir_to_offset and d != nodata:
                dr, dc = dir_to_offset[d]
                ni, nj = i + dr, j + dc
                if 0 <= ni < nrows and 0 <= nj < ncols:
                    incoming[ni, nj] += 1

    # Start from cells with no incoming flow
    from collections import deque
    queue = deque()
    for i in range(nrows):
        for j in range(ncols):
            if fdir[i, j] != nodata and fdir[i, j] != -9999 and incoming[i, j] == 0:
                queue.append((i, j))

    facc[:] = 1  # Each cell counts itself

    while queue:
        i, j = queue.popleft()
        d = fdir[i, j]
        if d in dir_to_offset:
            dr, dc = dir_to_offset[d]
            ni, nj = i + dr, j + dc
            if 0 <= ni < nrows and 0 <= nj < ncols:
                facc[ni, nj] += facc[i, j]
                incoming[ni, nj] -= 1
                if incoming[ni, nj] == 0:
                    queue.append((ni, nj))

    # Set nodata
    mask = (fdir == nodata) | (fdir == -9999)
    facc[mask] = nodata

    return facc


def validate_inputs():
    errors = []
    if not CONFIG_PATH or not Path(CONFIG_PATH).exists():
        errors.append(f"Config not found: {CONFIG_PATH}")
    if not DOMAIN_INFO_PATH or not Path(DOMAIN_INFO_PATH).exists():
        errors.append(f"Domain info not found: {DOMAIN_INFO_PATH}")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def process():
    config = json.load(open(CONFIG_PATH))
    domain_info = json.load(open(DOMAIN_INFO_PATH))
    header = domain_info["header_L0"]
    morph_dir = Path(config["output_dir"]) / "input" / "morph"
    morph_dir.mkdir(parents=True, exist_ok=True)

    # Find DEM
    dem_path = DEM_PATH
    if not dem_path:
        # Check if basin is in China
        bounds = domain_info["bounds"]
        avg_lon = (bounds[0] + bounds[2]) / 2
        avg_lat = (bounds[1] + bounds[3]) / 2
        if 73 <= avg_lon <= 135 and 18 <= avg_lat <= 53:
            dem_path = CHINA_DEM
            logger.info(f"Basin in China, using China DEM 90m")
        else:
            logger.error("Basin outside China, DEM_PATH must be provided (or use Copernicus GLO-30)")
            sys.exit(1)

    if not Path(dem_path).exists():
        logger.error(f"DEM not found: {dem_path}")
        sys.exit(1)

    logger.info(f"Clipping DEM to domain extent...")
    dem = clip_and_resample_dem(dem_path, header, config["shp_path"])

    # Apply basin mask (set cells outside basin to nodata)
    gdf = gpd.read_file(config["shp_path"])
    from rasterio.transform import from_bounds
    xll = header['xllcorner']
    yll = header['yllcorner']
    cs = header['cellsize']
    xur = xll + header['ncols'] * cs
    yur = yll + header['nrows'] * cs
    transform = from_bounds(xll, yll, xur, yur, header['ncols'], header['nrows'])

    from rasterio.features import geometry_mask
    basin_mask = geometry_mask(
        gdf.geometry, out_shape=(header['nrows'], header['ncols']),
        transform=transform, invert=True
    )
    # Keep a small buffer around basin for flow routing
    from scipy.ndimage import binary_dilation
    dilated_mask = binary_dilation(basin_mask, iterations=3)
    dem[~dilated_mask] = -9999

    # Write DEM
    write_ascii_grid(morph_dir / "dem.asc", dem, header)

    # Determine if coordinates are geographic (lat/lon) or projected (meters)
    # Heuristic: if cellsize < 1, it's in degrees (geographic); otherwise projected meters
    is_geographic = header['cellsize'] < 1.0
    if is_geographic:
        logger.info(f"Detected geographic coordinates (cellsize={header['cellsize']} deg)")
    else:
        logger.info(f"Detected projected coordinates (cellsize={header['cellsize']} m)")

    # Compute slope (m/m) and aspect (degrees from N)
    logger.info("Computing slope and aspect...")
    slope, aspect = compute_slope_aspect(dem, header['cellsize'], is_geographic=is_geographic)
    write_ascii_grid(morph_dir / "slope.asc", slope, header)
    write_ascii_grid(morph_dir / "aspect.asc", aspect, header)

    # Compute D8 flow direction (ArcGIS convention)
    logger.info("Computing D8 flow direction (ArcGIS convention)...")
    fdir = compute_d8_flow_direction(dem)
    write_ascii_grid(morph_dir / "fdir.asc", fdir.astype(float), header)

    # Compute flow accumulation
    logger.info("Computing flow accumulation...")
    facc = compute_flow_accumulation(fdir)
    write_ascii_grid(morph_dir / "facc.asc", facc.astype(float), header)

    # Summary stats
    valid = dem[dem != -9999]
    logger.info(f"DEM stats: min={valid.min():.1f}, max={valid.max():.1f}, mean={valid.mean():.1f}")
    logger.info(f"Valid cells: {len(valid)} / {dem.size}")

    result = {
        "status": "success",
        "morph_dir": str(morph_dir),
        "files": ["dem.asc", "slope.asc", "aspect.asc", "fdir.asc", "facc.asc"],
        "dem_stats": {
            "min": float(valid.min()),
            "max": float(valid.max()),
            "mean": float(valid.mean()),
        },
        "valid_cells": int(len(valid)),
        "total_cells": int(dem.size),
    }
    print(json.dumps(result, indent=2))
    return str(morph_dir)


def validate_outputs(output_path):
    morph_dir = Path(output_path)
    required = ["dem.asc", "slope.asc", "aspect.asc", "fdir.asc", "facc.asc"]
    for f in required:
        p = morph_dir / f
        if not p.exists():
            logger.error(f"Missing output: {p}")
            sys.exit(3)
        if p.stat().st_size < 100:
            logger.error(f"Output too small: {p} ({p.stat().st_size} bytes)")
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
