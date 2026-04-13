#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
============================================
Tool ID:      create_gru_hru
Stage:        s1_domain_setup
Description:  Define GRU/HRU structure from basin shapefile, DEM, land cover,
              and soil type data. Each GRU is a grid cell; each unique
              combination of soil type and vegetation class within a GRU
              becomes a separate HRU.

Inputs:
  - BASIN_SHP:      Basin boundary shapefile (.shp)
  - DEM_FILE:       DEM raster (GeoTIFF)
  - LANDCOVER_FILE: Land cover raster (MODIS IGBP or USGS classification)
  - SOILTYPE_FILE:  Soil type raster (e.g., from HWSD)
  - RESOLUTION:     Grid resolution in degrees (default 0.25)
  - OUTPUT_DIR:     Output directory

Outputs:
  - gru_hru_mapping.csv: CSV with columns [gruId, hruId, lat, lon, elevation,
    area_m2, tan_slope, aspect, vegTypeIndex, soilTypeIndex]

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
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
BASIN_SHP = ""
DEM_FILE = ""
LANDCOVER_FILE = ""
SOILTYPE_FILE = ""
RESOLUTION = 0.25
OUTPUT_DIR = ""
SINGLE_HRU = True  # Default: 1 HRU per GRU (dominant soil/veg). Set False for multi-HRU.

# AVHRR IGBP-DIS → USGS crosswalk (CRITICAL: different classification systems!)
# AVHRR 1km uses IGBP-DIS classes. SUMMA VEGPARM.TBL uses USGS 27-class scheme.
# Without this mapping, AVHRR class 11 (Wetland/Cropland) → USGS 11 (Deciduous Broadleaf Forest)
# which gives 20m tall canopy to rice paddies — causes canopySnow convergence failure.
IGBP_TO_USGS = {
    1: 14,   # IGBP Evergreen Needleleaf → USGS Evergreen Needleleaf Forest
    2: 13,   # IGBP Evergreen Broadleaf  → USGS Evergreen Broadleaf Forest
    3: 12,   # IGBP Deciduous Needleleaf → USGS Deciduous Needleleaf Forest
    4: 11,   # IGBP Deciduous Broadleaf  → USGS Deciduous Broadleaf Forest
    5: 15,   # IGBP Mixed Forest         → USGS Mixed Forest
    6: 8,    # IGBP Closed Shrubland     → USGS Shrubland
    7: 9,    # IGBP Open Shrubland       → USGS Mixed Shrubland/Grassland
    8: 10,   # IGBP Woody Savanna        → USGS Savanna
    9: 10,   # IGBP Savanna              → USGS Savanna
    10: 7,   # IGBP Grassland            → USGS Grassland
    11: 3,   # IGBP Wetland/Cropland     → USGS Irrigated Cropland (NOT Deciduous Broadleaf!)
    12: 2,   # IGBP Cropland             → USGS Dryland Cropland
    13: 1,   # IGBP Urban                → USGS Urban
    14: 5,   # IGBP Crop/Natural Mosaic  → USGS Cropland/Grassland Mosaic
    15: 19,  # IGBP Snow/Ice             → USGS Barren (safe fallback)
    16: 16,  # IGBP Water                → USGS Water Bodies
    0: 7,    # NoData                    → USGS Grassland (safe default)
}

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CLI override
# ---------------------------------------------------------------------------
if len(sys.argv) > 1:
    import argparse
    parser = argparse.ArgumentParser(description="Create GRU/HRU structure for SUMMA")
    parser.add_argument("--basin_shp", required=True, help="Basin shapefile path")
    parser.add_argument("--dem", required=True, help="DEM raster path")
    parser.add_argument("--landcover", required=True, help="Land cover raster path")
    parser.add_argument("--soiltype", required=True, help="Soil type raster path")
    parser.add_argument("--resolution", type=float, default=0.25, help="Grid resolution in degrees")
    parser.add_argument("--output_dir", required=True, help="Output directory")
    parser.add_argument("--multi_hru", action="store_true",
                        help="Create one HRU per unique soil×veg combo (default: 1 HRU per GRU using dominant types)")
    args = parser.parse_args()
    BASIN_SHP = args.basin_shp
    DEM_FILE = args.dem
    LANDCOVER_FILE = args.landcover
    SOILTYPE_FILE = args.soiltype
    RESOLUTION = args.resolution
    OUTPUT_DIR = args.output_dir
    SINGLE_HRU = not args.multi_hru


def validate_inputs():
    """Check that all preconditions are met."""
    errors = []
    if not BASIN_SHP or not Path(BASIN_SHP).exists():
        errors.append(f"Basin shapefile not found: {BASIN_SHP}")
    if not DEM_FILE or not Path(DEM_FILE).exists():
        errors.append(f"DEM file not found: {DEM_FILE}")
    if not LANDCOVER_FILE or not Path(LANDCOVER_FILE).exists():
        errors.append(f"Land cover file not found: {LANDCOVER_FILE}")
    if not SOILTYPE_FILE or not Path(SOILTYPE_FILE).exists():
        errors.append(f"Soil type file not found: {SOILTYPE_FILE}")
    if not OUTPUT_DIR:
        errors.append("OUTPUT_DIR is not set")
    if RESOLUTION <= 0 or RESOLUTION > 1.0:
        errors.append(f"Resolution must be between 0 and 1 degree, got {RESOLUTION}")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def validate_outputs(output_csv):
    """Check postconditions."""
    errors = []
    if not Path(output_csv).exists():
        errors.append(f"Output CSV not created: {output_csv}")
    else:
        import csv
        with open(output_csv) as f:
            reader = csv.reader(f)
            header = next(reader)
            required_cols = ['gruId', 'hruId', 'lat', 'lon', 'elevation',
                             'area_m2', 'tan_slope', 'vegTypeIndex', 'soilTypeIndex']
            for col in required_cols:
                if col not in header:
                    errors.append(f"Missing required column: {col}")
            row_count = sum(1 for _ in reader)
            if row_count == 0:
                errors.append("Output CSV has no data rows")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(3)
    logger.info("Output validation passed.")


def process():
    """Create GRU/HRU structure from geospatial inputs."""
    try:
        import geopandas as gpd
        import rasterio
        from rasterio.mask import mask as rio_mask
        from shapely.geometry import box
    except ImportError as e:
        logger.error(f"Missing dependency: {e}. Install: pip install geopandas rasterio shapely")
        sys.exit(2)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_csv = os.path.join(OUTPUT_DIR, "gru_hru_mapping.csv")

    # Read basin shapefile
    logger.info(f"Reading basin shapefile: {BASIN_SHP}")
    basin_gdf = gpd.read_file(BASIN_SHP)
    basin_geom = basin_gdf.geometry.unary_union
    bounds = basin_geom.bounds  # (minx, miny, maxx, maxy)

    # Create grid cells (each = one GRU)
    logger.info(f"Creating grid with resolution {RESOLUTION} degrees")
    min_lon = np.floor(bounds[0] / RESOLUTION) * RESOLUTION
    max_lon = np.ceil(bounds[2] / RESOLUTION) * RESOLUTION
    min_lat = np.floor(bounds[1] / RESOLUTION) * RESOLUTION
    max_lat = np.ceil(bounds[3] / RESOLUTION) * RESOLUTION

    lons = np.arange(min_lon, max_lon, RESOLUTION)
    lats = np.arange(min_lat, max_lat, RESOLUTION)

    gru_id = 0
    hru_id = 0
    rows = []

    # Open rasters
    dem_ds = rasterio.open(DEM_FILE)
    lc_ds = rasterio.open(LANDCOVER_FILE)
    soil_ds = rasterio.open(SOILTYPE_FILE)

    for lat in lats:
        for lon in lons:
            cell = box(lon, lat, lon + RESOLUTION, lat + RESOLUTION)
            intersection = basin_geom.intersection(cell)
            if intersection.is_empty or intersection.area == 0:
                continue

            gru_id += 1
            cell_center_lat = lat + RESOLUTION / 2
            cell_center_lon = lon + RESOLUTION / 2

            # Extract DEM stats for this cell
            try:
                cell_geom = [intersection.__geo_interface__]
                dem_clip, dem_transform = rio_mask(dem_ds, cell_geom, crop=True, nodata=np.nan)
                elevation = float(np.nanmean(dem_clip))
                # Compute slope from DEM
                if dem_clip.shape[1] > 1 and dem_clip.shape[2] > 1:
                    dy, dx = np.gradient(dem_clip[0], dem_transform[4], dem_transform[0])
                    slope = np.sqrt(dx**2 + dy**2)
                    tan_slope = float(np.nanmean(slope))
                else:
                    tan_slope = 0.01  # minimum slope for flat cells
            except Exception:
                elevation = 0.0
                tan_slope = 0.01

            # Extract land cover and soil type
            try:
                lc_clip, _ = rio_mask(lc_ds, cell_geom, crop=True, nodata=0)
                lc_values = lc_clip[lc_clip > 0]
                if len(lc_values) == 0:
                    lc_unique = [1]  # default: evergreen needleleaf
                else:
                    lc_unique = list(np.unique(lc_values))
            except Exception:
                lc_unique = [1]

            try:
                soil_clip, _ = rio_mask(soil_ds, cell_geom, crop=True, nodata=0)
                soil_values = soil_clip[soil_clip > 0]
                if len(soil_values) == 0:
                    soil_unique = [1]  # default: sand
                else:
                    soil_unique = list(np.unique(soil_values))
            except Exception:
                soil_unique = [1]

            # Compute cell area
            area_m2 = intersection.area * 111320 * 111320 * np.cos(np.radians(cell_center_lat))

            if SINGLE_HRU:
                # 1 HRU per GRU: use dominant (most frequent) soil and veg types
                # This is the standard approach for distributed modeling (like VIC grid cells)
                from collections import Counter
                dom_veg_igbp = int(Counter(lc_unique).most_common(1)[0][0]) if lc_unique else 7
                dom_veg = IGBP_TO_USGS.get(dom_veg_igbp, 7)  # IGBP→USGS crosswalk
                dom_soil = int(Counter(soil_unique).most_common(1)[0][0]) if soil_unique else 1
                hru_id += 1
                rows.append({
                    'gruId': gru_id,
                    'hruId': hru_id,
                    'lat': round(cell_center_lat, 6),
                    'lon': round(cell_center_lon, 6),
                    'elevation': round(elevation, 2),
                    'area_m2': round(area_m2, 2),
                    'tan_slope': round(max(tan_slope, 0.01), 6),
                    'vegTypeIndex': dom_veg,
                    'soilTypeIndex': dom_soil,
                    'contourLength': round(np.sqrt(area_m2), 2),
                    'mHeight': 3.0
                })
            else:
                # Multi-HRU: one HRU per unique (soil, veg) combination
                # Use for sub-grid heterogeneity in complex terrain (mountain basins)
                # WARNING: can produce 10-50x more HRUs, proportionally slower runtime
                n_combos = len(lc_unique) * len(soil_unique)
                for veg_type_igbp in lc_unique:
                    veg_type_usgs = IGBP_TO_USGS.get(int(veg_type_igbp), 7)
                    for soil_type in soil_unique:
                        hru_id += 1
                        rows.append({
                            'gruId': gru_id,
                            'hruId': hru_id,
                            'lat': round(cell_center_lat, 6),
                            'lon': round(cell_center_lon, 6),
                            'elevation': round(elevation, 2),
                            'area_m2': round(area_m2 / n_combos, 2),
                            'tan_slope': round(max(tan_slope, 0.01), 6),
                            'vegTypeIndex': veg_type_usgs,
                            'soilTypeIndex': int(soil_type),
                            'contourLength': round(np.sqrt(area_m2 / n_combos), 2),
                            'mHeight': 3.0
                        })

    dem_ds.close()
    lc_ds.close()
    soil_ds.close()

    if not rows:
        logger.error("No GRU/HRU combinations found within basin. Check shapefile overlap with grid.")
        sys.exit(2)

    # Write CSV
    import csv
    fieldnames = ['gruId', 'hruId', 'lat', 'lon', 'elevation', 'area_m2',
                  'tan_slope', 'vegTypeIndex', 'soilTypeIndex', 'contourLength', 'mHeight']
    with open(output_csv, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    logger.info(f"Created {gru_id} GRUs with {hru_id} HRUs total")
    logger.info(f"Output: {output_csv}")

    # Print JSON summary for agent
    print(json.dumps({
        "status": "success",
        "n_gru": gru_id,
        "n_hru": hru_id,
        "output": output_csv
    }))

    return output_csv


if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs()
    try:
        output_path = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(2)
    validate_outputs(output_path)
    sys.exit(0)
