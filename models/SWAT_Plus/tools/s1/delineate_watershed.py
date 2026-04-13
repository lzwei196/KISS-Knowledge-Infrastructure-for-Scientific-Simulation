#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
Tool ID:      delineate_watershed
Stage:        s1_watershed_delineation
Description:  Process DEM to generate subbasins, stream network, and watershed boundary.

Inputs:
  - dem_path: Path to DEM raster (GeoTIFF)
  - outlet_lat: Basin outlet latitude (decimal degrees)
  - outlet_lon: Basin outlet longitude (decimal degrees)
  - stream_threshold: Minimum upstream area (km2) to define streams (default 25)
  - output_dir: Output directory for shapefiles and rasters

Outputs:
  - subbasins.shp: Subbasin boundary shapefile
  - streams.shp: Stream network shapefile
  - watershed.shp: Watershed boundary shapefile

Exit codes:
  0 — success
  1 — input validation failed
  2 — processing error
  3 — output validation failed
"""

import sys
import os
import logging
import json
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DEM_PATH = ""
OUTLET_LAT = 0.0
OUTLET_LON = 0.0
STREAM_THRESHOLD_KM2 = 25.0
OUTPUT_DIR = ""

# CLI override
if len(sys.argv) >= 5:
    DEM_PATH = sys.argv[1]
    OUTLET_LAT = float(sys.argv[2])
    OUTLET_LON = float(sys.argv[3])
    OUTPUT_DIR = sys.argv[4]
if len(sys.argv) >= 6:
    STREAM_THRESHOLD_KM2 = float(sys.argv[5])

# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def validate_inputs():
    """Check that all preconditions are met."""
    errors = []
    if not DEM_PATH or not Path(DEM_PATH).exists():
        errors.append(f"DEM file not found: {DEM_PATH}")
    if not (-90 <= OUTLET_LAT <= 90):
        errors.append(f"Invalid latitude: {OUTLET_LAT}")
    if not (-180 <= OUTLET_LON <= 180):
        errors.append(f"Invalid longitude: {OUTLET_LON}")
    if STREAM_THRESHOLD_KM2 <= 0:
        errors.append(f"Stream threshold must be positive: {STREAM_THRESHOLD_KM2}")
    if not OUTPUT_DIR:
        errors.append("OUTPUT_DIR is not set")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def process():
    """
    Main processing: DEM -> pit-fill -> flow direction -> flow accumulation ->
    stream network -> snap outlet -> watershed -> subbasins.

    Uses WhiteboxTools (preferred) or pysheds as fallback.
    """
    output_dir = Path(OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        import whitebox
        wbt = whitebox.WhiteboxTools()
        wbt.set_verbose_mode(True)

        dem = str(Path(DEM_PATH).resolve())
        filled = str(output_dir / "dem_filled.tif")
        fdir = str(output_dir / "flow_direction.tif")
        facc = str(output_dir / "flow_accumulation.tif")
        streams_raster = str(output_dir / "streams.tif")

        logger.info("Step 1: Breach depressions")
        wbt.breach_depressions(dem, filled)

        logger.info("Step 2: D8 flow direction")
        wbt.d8_pointer(filled, fdir)

        logger.info("Step 3: D8 flow accumulation")
        wbt.d8_flow_accumulation(filled, facc, out_type="cells")

        logger.info("Step 4: Extract streams")
        # Convert km2 threshold to cell count (approximate)
        import rasterio
        with rasterio.open(dem) as src:
            cell_size_m = abs(src.transform[0])
            if cell_size_m < 1:  # degrees
                cell_size_m = cell_size_m * 111000  # approximate
            cell_area_km2 = (cell_size_m ** 2) / 1e6
        threshold_cells = max(1, int(STREAM_THRESHOLD_KM2 / cell_area_km2))
        wbt.extract_streams(facc, streams_raster, threshold=threshold_cells)

        logger.info("Step 5: Snap outlet and delineate watershed")
        # Create outlet point shapefile
        import geopandas as gpd
        from shapely.geometry import Point
        outlet_gdf = gpd.GeoDataFrame(
            {"id": [1]},
            geometry=[Point(OUTLET_LON, OUTLET_LAT)],
            crs="EPSG:4326"
        )
        outlet_path = str(output_dir / "outlet.shp")
        outlet_gdf.to_file(outlet_path)

        # Snap pour point
        snapped = str(output_dir / "outlet_snapped.shp")
        wbt.snap_pour_points(outlet_path, facc, snapped, snap_dist=0.15)

        # Watershed delineation
        watershed_raster = str(output_dir / "watershed.tif")
        wbt.watershed(fdir, snapped, watershed_raster)

        logger.info("Step 6: Vectorize outputs")
        # Convert rasters to shapefiles
        watershed_shp = str(output_dir / "watershed.shp")
        wbt.raster_to_vector_polygons(watershed_raster, watershed_shp)

        logger.info("Step 7: Define subbasins")
        subbasins_raster = str(output_dir / "subbasins.tif")
        wbt.subbasins(fdir, streams_raster, subbasins_raster)
        subbasins_shp = str(output_dir / "subbasins.shp")
        wbt.raster_to_vector_polygons(subbasins_raster, subbasins_shp)

        streams_shp = str(output_dir / "streams.shp")
        wbt.raster_to_vector_lines(streams_raster, streams_shp)

    except ImportError:
        logger.warning("WhiteboxTools not available. Using pysheds fallback.")
        # Pysheds fallback would go here
        raise NotImplementedError("pysheds fallback not yet implemented")

    result = {
        "status": "success",
        "watershed_shp": str(output_dir / "watershed.shp"),
        "subbasins_shp": str(output_dir / "subbasins.shp"),
        "streams_shp": str(output_dir / "streams.shp"),
        "outlet_lat": OUTLET_LAT,
        "outlet_lon": OUTLET_LON,
        "stream_threshold_km2": STREAM_THRESHOLD_KM2
    }
    return result


def validate_outputs(result):
    """Check that postconditions are met."""
    errors = []
    for key in ["watershed_shp", "subbasins_shp", "streams_shp"]:
        if not Path(result[key]).exists():
            errors.append(f"Expected output not created: {result[key]}")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(3)
    logger.info("Output validation passed.")


if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs()
    try:
        result = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        sys.exit(2)
    validate_outputs(result)
    print(json.dumps(result, indent=2))
    sys.exit(0)
