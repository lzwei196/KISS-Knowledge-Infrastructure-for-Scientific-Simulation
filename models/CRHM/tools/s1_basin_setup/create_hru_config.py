#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
============================================
Tool ID:      create_hru_config
Stage:        s1_basin_setup
Description:  Generate HRU definitions from DEM, land cover, and basin shapefile.

CRHM uses Hydrological Response Units (HRUs) -- irregular landscape units
grouped by hydrological similarity (elevation band + land cover + aspect).
Unlike VIC grid cells (regular lat/lon), HRUs capture landscape heterogeneity
relevant to cold regions processes (e.g., wind-exposed prairie vs sheltered
forest, north-facing vs south-facing slopes).

Inputs:
  --dem_path:          DEM raster (GeoTIFF)
  --landcover_path:    Land cover classification raster
  --shapefile_path:    Basin boundary shapefile
  --n_elevation_bands: Number of elevation bands (default: 5)
  --output_dir:        Output directory

Outputs:
  hru_config.json -- HRU definitions with areas, elevations, land cover

Exit codes:
  0 -- success
  1 -- input validation failed
  2 -- processing error
  3 -- output validation failed
"""

import sys
import os
import json
import logging
import argparse
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default configuration
# ---------------------------------------------------------------------------
DEM_PATH = ""
LANDCOVER_PATH = ""
SHAPEFILE_PATH = ""
N_ELEVATION_BANDS = 5
OUTPUT_DIR = ""

# Land cover classes relevant to CRHM cold regions processes
# Direct CRHM class IDs (1-9): used when input raster already uses CRHM scheme
CRHM_LANDCOVER_CLASSES = {
    1: {"name": "open_prairie", "veg_height_m": 0.3, "fetch_m": 1000, "canopy": False},
    2: {"name": "crop_stubble", "veg_height_m": 0.15, "fetch_m": 500, "canopy": False},
    3: {"name": "shrub", "veg_height_m": 1.5, "fetch_m": 100, "canopy": False},
    4: {"name": "deciduous_forest", "veg_height_m": 15.0, "fetch_m": 50, "canopy": True},
    5: {"name": "coniferous_forest", "veg_height_m": 12.0, "fetch_m": 30, "canopy": True},
    6: {"name": "wetland", "veg_height_m": 0.5, "fetch_m": 300, "canopy": False},
    7: {"name": "water", "veg_height_m": 0.0, "fetch_m": 2000, "canopy": False},
    8: {"name": "bare_ground", "veg_height_m": 0.01, "fetch_m": 2000, "canopy": False},
    9: {"name": "alpine_tundra", "veg_height_m": 0.1, "fetch_m": 1500, "canopy": False},
    # AVHRR/UMD global land cover classes (10-16): auto-mapped to CRHM equivalents
    # UMD: 10=Grasslands, 11=Permanent Wetlands, 12=Croplands,
    #       13=Urban, 14=Cropland/NatVeg, 15=Snow/Ice, 16=Barren
    10: {"name": "open_prairie", "veg_height_m": 0.3, "fetch_m": 1000, "canopy": False},
    11: {"name": "wetland", "veg_height_m": 0.5, "fetch_m": 300, "canopy": False},
    12: {"name": "crop_stubble", "veg_height_m": 0.15, "fetch_m": 500, "canopy": False},
    13: {"name": "bare_ground", "veg_height_m": 0.01, "fetch_m": 2000, "canopy": False},
    14: {"name": "crop_stubble", "veg_height_m": 0.15, "fetch_m": 500, "canopy": False},
    15: {"name": "alpine_tundra", "veg_height_m": 0.1, "fetch_m": 1500, "canopy": False},
    16: {"name": "bare_ground", "veg_height_m": 0.01, "fetch_m": 2000, "canopy": False},
}


def parse_args():
    parser = argparse.ArgumentParser(description="Create CRHM HRU configuration")
    parser.add_argument("--dem_path", type=str, help="DEM raster path")
    parser.add_argument("--landcover_path", type=str, help="Land cover raster path")
    parser.add_argument("--shapefile_path", type=str, help="Basin boundary shapefile")
    parser.add_argument("--n_elevation_bands", type=int, default=5, help="Number of elevation bands")
    parser.add_argument("--output_dir", type=str, help="Output directory")
    return parser.parse_args()


def validate_inputs(dem_path, landcover_path, shapefile_path, output_dir):
    """Check that all preconditions are met."""
    errors = []

    if not dem_path or not Path(dem_path).exists():
        errors.append(f"DEM file not found: {dem_path}")

    if not landcover_path or not Path(landcover_path).exists():
        errors.append(f"Land cover file not found: {landcover_path}")

    if not shapefile_path or not Path(shapefile_path).exists():
        errors.append(f"Shapefile not found: {shapefile_path}")

    if not output_dir:
        errors.append("OUTPUT_DIR is not set")

    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)

    logger.info("Input validation passed.")


def process(dem_path, landcover_path, shapefile_path, n_bands, output_dir):
    """
    Generate HRU configuration from DEM and land cover data.

    Algorithm:
    1. Clip DEM and land cover to basin boundary
    2. Compute elevation range, divide into n_bands
    3. Cross-tabulate elevation band x land cover class
    4. Each non-empty combination becomes an HRU
    5. Compute HRU area, mean elevation, dominant aspect
    6. Assign CRHM-relevant parameters (veg height, fetch distance)
    """
    try:
        import numpy as np
        import rasterio
        from rasterio.mask import mask as rio_mask
        import geopandas as gpd
    except ImportError as e:
        logger.error(f"Missing dependency: {e}. Install with: pip install numpy rasterio geopandas")
        sys.exit(2)

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Read basin boundary
    basin = gpd.read_file(shapefile_path)
    basin_geom = basin.geometry.values

    # Clip DEM to basin
    with rasterio.open(dem_path) as dem_src:
        dem_data, dem_transform = rio_mask(dem_src, basin_geom, crop=True, nodata=-9999)
        dem_data = dem_data[0]  # first band
        pixel_area_m2 = abs(dem_transform[0] * dem_transform[4])  # approx
        # For geographic CRS, compute approximate area
        if dem_src.crs and dem_src.crs.is_geographic:
            import math
            center_lat = (dem_data != -9999).nonzero()
            if len(center_lat[0]) > 0:
                mid_row = center_lat[0][len(center_lat[0]) // 2]
                lat_rad = math.radians(dem_transform[5] + mid_row * dem_transform[4])
                pixel_area_m2 = (abs(dem_transform[0]) * 111320 * math.cos(lat_rad)) * \
                                (abs(dem_transform[4]) * 111320)

    # Clip land cover to basin and resample to match DEM shape
    with rasterio.open(landcover_path) as lc_src:
        lc_raw, lc_transform = rio_mask(lc_src, basin_geom, crop=True, nodata=0)
        lc_raw = lc_raw[0]
        lc_crs = lc_src.crs

    # Resample land cover to match DEM grid exactly
    from rasterio.warp import reproject, Resampling as WarpResampling
    lc_data = np.zeros((dem_data.shape[0], dem_data.shape[1]), dtype=np.int16)
    reproject(
        source=lc_raw.astype(np.int16),
        destination=lc_data,
        src_transform=lc_transform,
        src_crs=lc_crs if lc_crs else "EPSG:4326",
        dst_transform=dem_transform,
        dst_crs="EPSG:4326",
        resampling=WarpResampling.nearest,
    )

    valid_mask = (dem_data != -9999) & (dem_data > -500)
    valid_elevations = dem_data[valid_mask]

    if len(valid_elevations) == 0:
        logger.error("No valid elevation data within basin boundary")
        sys.exit(2)

    elev_min = float(np.min(valid_elevations))
    elev_max = float(np.max(valid_elevations))
    elev_range = elev_max - elev_min

    # Define elevation band boundaries
    band_width = elev_range / n_bands if n_bands > 0 else elev_range
    band_edges = [elev_min + i * band_width for i in range(n_bands + 1)]
    band_edges[-1] = elev_max + 1  # inclusive upper bound

    # Classify pixels into elevation bands
    elev_bands = np.full_like(dem_data, -1, dtype=int)
    for i in range(n_bands):
        band_mask = valid_mask & (dem_data >= band_edges[i]) & (dem_data < band_edges[i + 1])
        elev_bands[band_mask] = i

    # Cross-tabulate elevation bands x land cover
    unique_lc = np.unique(lc_data[valid_mask])
    hrus = []
    hru_id = 1

    for band_idx in range(n_bands):
        band_mask = elev_bands == band_idx
        if not np.any(band_mask):
            continue

        for lc_val in unique_lc:
            if lc_val <= 0:
                continue
            hru_mask = band_mask & (lc_data == lc_val)
            pixel_count = int(np.sum(hru_mask))
            if pixel_count == 0:
                continue

            mean_elev = float(np.mean(dem_data[hru_mask]))
            area_km2 = pixel_count * pixel_area_m2 / 1e6

            # Get CRHM land cover properties
            lc_int = int(lc_val)
            lc_props = CRHM_LANDCOVER_CLASSES.get(
                lc_int,
                {"name": f"class_{lc_int}", "veg_height_m": 0.5, "fetch_m": 500, "canopy": False}
            )

            hrus.append({
                "hru_id": hru_id,
                "elevation_band": band_idx,
                "elevation_band_range_m": [
                    round(band_edges[band_idx], 1),
                    round(band_edges[band_idx + 1], 1)
                ],
                "mean_elevation_m": round(mean_elev, 1),
                "land_cover_class": lc_int,
                "land_cover_name": lc_props["name"],
                "area_km2": round(area_km2, 4),
                "veg_height_m": lc_props["veg_height_m"],
                "fetch_m": lc_props["fetch_m"],
                "has_canopy": lc_props["canopy"],
                "pixel_count": pixel_count,
            })
            hru_id += 1

    if len(hrus) == 0:
        logger.error("No HRUs generated -- check DEM/landcover overlap with basin")
        sys.exit(2)

    # Compute basin totals
    total_area_km2 = sum(h["area_km2"] for h in hrus)
    basin_area_km2 = float(basin.geometry.area.sum())
    if basin.crs and basin.crs.is_geographic:
        # Rough conversion for geographic CRS
        basin_area_km2 = basin.to_crs(epsg=3857).geometry.area.sum() / 1e6

    config = {
        "nhru": len(hrus),
        "basin_area_km2": round(total_area_km2, 2),
        "elevation_range_m": [round(elev_min, 1), round(elev_max, 1)],
        "n_elevation_bands": n_bands,
        "hrus": hrus,
        "crhm_dimensions": {
            "nhru": len(hrus),
            "nlay": 1,
            "nobs": 1,
        },
        "crhm_hru_areas_km2": [h["area_km2"] for h in hrus],
        "crhm_hru_elevations_m": [h["mean_elevation_m"] for h in hrus],
    }

    output_file = output_path / "hru_config.json"
    with open(output_file, "w") as f:
        json.dump(config, f, indent=2)

    logger.info(f"Created {len(hrus)} HRUs across {n_bands} elevation bands")
    logger.info(f"Basin area: {total_area_km2:.2f} km2")
    logger.info(f"Elevation range: {elev_min:.0f} - {elev_max:.0f} m")

    return str(output_file)


def validate_outputs(output_path):
    """Check that HRU configuration is valid."""
    errors = []

    if not Path(output_path).exists():
        errors.append(f"Output file not created: {output_path}")
    else:
        with open(output_path) as f:
            config = json.load(f)
        if config.get("nhru", 0) == 0:
            errors.append("No HRUs in output configuration")
        if not config.get("hrus"):
            errors.append("HRU list is empty")
        else:
            total_area = sum(h["area_km2"] for h in config["hrus"])
            if total_area <= 0:
                errors.append("Total HRU area is zero")

    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(3)

    logger.info("Output validation passed.")


if __name__ == "__main__":
    args = parse_args()

    dem_path = args.dem_path or DEM_PATH
    landcover_path = args.landcover_path or LANDCOVER_PATH
    shapefile_path = args.shapefile_path or SHAPEFILE_PATH
    n_bands = args.n_elevation_bands or N_ELEVATION_BANDS
    output_dir = args.output_dir or OUTPUT_DIR

    logger.info(f"Running tool: {os.path.basename(__file__)}")

    validate_inputs(dem_path, landcover_path, shapefile_path, output_dir)

    try:
        output_path = process(dem_path, landcover_path, shapefile_path, n_bands, output_dir)
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(2)

    validate_outputs(output_path)

    # JSON output for agent consumption
    print(json.dumps({"status": "success", "output": output_path}))
    sys.exit(0)
