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
    # Class 0 in the AVHRR IGBP-DIS product is WATER, not NoData.  True
    # out-of-footprint pixels are carried as the 255 sentinel and filtered
    # before the crosswalk runs, so anything reaching here as 0 is real water.
    16: 16,  # IGBP Water                → USGS Water Bodies
    0: 16,   # IGBP Water                → USGS Water Bodies
}

# IGBP → MODIFIED_IGBP_MODIS_NOAH (MPTABLE.TBL). That table is IGBP-native, so
# the mapping is the identity for 1-16; only water moves, because MPTABLE puts
# ISWATER at 17 while USGS/VEGPARM puts water at 16.
IGBP_TO_MODIS = {i: i for i in range(1, 17)}
IGBP_TO_MODIS[0] = 17    # water -> ISWATER
IGBP_TO_MODIS[16] = 17   # water -> ISWATER
IGBP_TO_MODIS[17] = 17

# Which vegetation-parameter table the caller wants. This MUST agree with
# vegeParTbl in decisions.txt and with s4 --veg_scheme, or the index written
# here selects a different plant in the table SUMMA actually reads.
VEG_SCHEME = "usgs"
VEG_CROSSWALKS = {"usgs": IGBP_TO_USGS, "modis": IGBP_TO_MODIS}
VEG_TABLE_FOR_SCHEME = {"usgs": "USGS", "modis": "MODIFIED_IGBP_MODIS_NOAH"}
VEG_DEFAULT_FOR_SCHEME = {"usgs": 7, "modis": 10}   # grassland in each table

# USDA texture class -> SUMMA STAS soil category (SOILPARM.TBL, 19 classes).
# soilTypeIndex is an INDEX INTO THIS TABLE. dt_030: the previous code wrote
# the raw HWSD MU_GLOBAL id (values in the thousands) into this field.
TEXTURE_TO_STAS = {
    "sand": 1, "loamy_sand": 2, "sandy_loam": 3, "silt_loam": 4,
    "silt": 5, "loam": 6, "sandy_clay_loam": 7, "silty_clay_loam": 8,
    "clay_loam": 9, "sandy_clay": 10, "silty_clay": 11, "clay": 12,
}
STAS_WATER = 14
STAS_DEFAULT = 6  # loam

# GRUs whose DEM extraction failed. dt_031: this used to be swallowed by a bare
# `except Exception: elevation = 0.0`, giving every GRU sea-level elevation,
# which silently warms a 4000 m basin by ~26 K once the s2 lapse correction is
# applied. Collected here and raised as a hard error rather than written out.
DEM_FAILURES = []

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)
LOG = logger  # alias used by the DEM-failure path

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
    parser.add_argument("--veg_scheme", choices=["usgs", "modis"], default="usgs",
                        help="Vegetation parameter table the written vegTypeIndex targets. "
                             "'usgs' = VEGPARM.TBL (27-class USGS); 'modis' = MPTABLE.TBL "
                             "(MODIFIED_IGBP_MODIS_NOAH, IGBP-native, ISWATER=17). MUST match "
                             "vegeParTbl in decisions.txt and s4 --veg_scheme.")
    args = parser.parse_args()
    BASIN_SHP = args.basin_shp
    DEM_FILE = args.dem
    LANDCOVER_FILE = args.landcover
    SOILTYPE_FILE = args.soiltype
    RESOLUTION = args.resolution
    OUTPUT_DIR = args.output_dir
    SINGLE_HRU = not args.multi_hru
    VEG_SCHEME = args.veg_scheme


_HWSD_TABLE = None


def _hwsd_table():
    """Load and cache the HWSD attribute table, indexed by MU_GLOBAL.

    Returns None if the table is unavailable, in which case callers fall back
    to a point lookup.
    """
    global _HWSD_TABLE
    if _HWSD_TABLE is not None:
        return _HWSD_TABLE if _HWSD_TABLE is not False else None
    try:
        import pandas as pd
        from ki_tools_common.soil_utils import HWSD_CSV
        df = pd.read_csv(HWSD_CSV, low_memory=False)
        # A mapping unit can carry several soil components; keep the one with
        # the largest SHARE, which is the unit's dominant soil.
        if "SHARE" in df.columns:
            df = df.sort_values("SHARE", ascending=False)
        _HWSD_TABLE = df.drop_duplicates(subset=["MU_GLOBAL"]).set_index("MU_GLOBAL")
    except Exception as exc:
        logger.warning(f"HWSD attribute table unavailable ({exc}); "
                       "falling back to point lookup for soil texture.")
        _HWSD_TABLE = False
        return None
    return _HWSD_TABLE


def resolve_soil_category(mu_global, lat, lon):
    """Map a HWSD MU_GLOBAL mapping-unit id to a SUMMA STAS category (1-19).

    dt_030: soilTypeIndex is an index into SOILPARM.TBL's 19 STAS classes, but
    the previous code wrote the raw MU_GLOBAL id (typically in the thousands)
    straight into it.

    The id passed in is the MODAL mapping unit of the GRU. Resolving texture
    from that unit's own attribute row -- rather than calling lookup_hwsd() on
    the cell centroid -- keeps the answer consistent with the pixels that
    actually dominate the cell; a centroid can easily land in a minority unit.
    """
    from ki_tools_common.soil_utils import classify_texture

    tbl = _hwsd_table()
    if tbl is not None and mu_global in tbl.index:
        row = tbl.loc[mu_global]
        try:
            # ISSOIL == 0 marks non-soil units (water bodies, glaciers, rock).
            if "ISSOIL" in row and float(row["ISSOIL"]) == 0:
                return STAS_WATER
            sand, silt, clay = (float(row["T_SAND"]), float(row["T_SILT"]),
                                float(row["T_CLAY"]))
            if all(np.isfinite(v) and v >= 0 for v in (sand, silt, clay)) and (sand + clay) > 0:
                return TEXTURE_TO_STAS.get(classify_texture(sand, silt, clay), STAS_DEFAULT)
        except (KeyError, TypeError, ValueError):
            pass

    # Fallback only: the modal unit is not in the table, so ask for this point.
    try:
        from ki_tools_common.soil_utils import lookup_hwsd
        soil = lookup_hwsd(lat, lon)
        return TEXTURE_TO_STAS.get(soil.get("texture"), STAS_DEFAULT)
    except Exception as exc:
        logger.warning(f"Soil texture lookup failed at {lat:.4f},{lon:.4f} "
                       f"(MU_GLOBAL={mu_global}): {exc}; using loam.")
        return STAS_DEFAULT


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

    veg_crosswalk = VEG_CROSSWALKS[VEG_SCHEME]
    veg_default = VEG_DEFAULT_FOR_SCHEME[VEG_SCHEME]
    veg_table_expected = VEG_TABLE_FOR_SCHEME[VEG_SCHEME]
    logger.info(f"Vegetation scheme: {VEG_SCHEME} -> vegeParTbl must be "
                f"{veg_table_expected}")

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
                dem_clip, dem_transform = rio_mask(dem_ds, cell_geom, crop=True, filled=True)
                dem_arr = dem_clip.astype('float64')
                if dem_ds.nodata is not None:
                    dem_arr[dem_clip == dem_ds.nodata] = np.nan
                elevation = float(np.nanmean(dem_arr))
                if not np.isfinite(elevation) or not (-500.0 <= elevation <= 9000.0):
                    raise ValueError('implausible GRU elevation %r' % elevation)
                # Compute slope from DEM
                if dem_clip.shape[1] > 1 and dem_clip.shape[2] > 1:
                    dy, dx = np.gradient(dem_clip[0], dem_transform[4], dem_transform[0])
                    slope = np.sqrt(dx**2 + dy**2)
                    tan_slope = float(np.nanmean(slope))
                else:
                    tan_slope = 0.01  # minimum slope for flat cells
            except Exception as _e:
                LOG.error('DEM extraction FAILED for GRU at %.4f,%.4f: %s', cell_center_lat, cell_center_lon, _e)
                DEM_FAILURES.append((cell_center_lat, cell_center_lon, str(_e)))
                elevation = float('nan')
                tan_slope = 0.01

            # Extract land cover and soil type
            try:
                lc_clip, _ = rio_mask(lc_ds, cell_geom, crop=True, nodata=255)
                lc_values = lc_clip[lc_clip != 255]
                if len(lc_values) == 0:
                    lc_unique = [10]; lc_mode = 10
                else:
                    _v, _c = np.unique(lc_values, return_counts=True)
                    lc_unique = [int(x) for x in _v]
                    lc_mode = int(_v[int(np.argmax(_c))])
            except Exception:
                lc_unique = [10]; lc_mode = 10

            try:
                soil_clip, _ = rio_mask(soil_ds, cell_geom, crop=True, nodata=0)
                soil_values = soil_clip[soil_clip > 0]
                if len(soil_values) == 0:
                    soil_unique = [1]; soil_mode = 1
                else:
                    _v, _c = np.unique(soil_values, return_counts=True)
                    soil_unique = [int(x) for x in _v]
                    soil_mode = int(_v[int(np.argmax(_c))])
            except Exception:
                soil_unique = [1]; soil_mode = 1

            # Compute cell area
            area_m2 = intersection.area * 111320 * 111320 * np.cos(np.radians(cell_center_lat))

            if SINGLE_HRU:
                # 1 HRU per GRU: use dominant (most frequent) soil and veg types
                # This is the standard approach for distributed modeling (like VIC grid cells)
                dom_veg_igbp = int(lc_mode)
                dom_veg = veg_crosswalk.get(dom_veg_igbp, veg_default)
                dom_soil = resolve_soil_category(int(soil_mode), cell_center_lat, cell_center_lon)
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
                    veg_type_usgs = veg_crosswalk.get(int(veg_type_igbp), veg_default)
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
                            # dt_030: STAS category, not the raw MU_GLOBAL id.
                            'soilTypeIndex': resolve_soil_category(
                                int(soil_type), cell_center_lat, cell_center_lon),
                            'contourLength': round(np.sqrt(area_m2 / n_combos), 2),
                            'mHeight': 3.0
                        })

    dem_ds.close()
    lc_ds.close()
    soil_ds.close()

    if not rows:
        logger.error("No GRU/HRU combinations found within basin. Check shapefile overlap with grid.")
        sys.exit(2)

    # dt_031: never write a domain with unresolved elevations. Silently
    # substituting 0.0 here made the s2 lapse correction warm a 4000 m basin by
    # ~26 K, which is invisible downstream but ruins the energy balance.
    if DEM_FAILURES:
        logger.error(f"DEM extraction failed for {len(DEM_FAILURES)} of {gru_id} GRUs; "
                     "refusing to write a domain with unresolved elevations.")
        for flat, flon, msg in DEM_FAILURES[:10]:
            logger.error(f"  GRU at {flat:.4f},{flon:.4f}: {msg}")
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

    # Area-weighted vegetation composition. Surfaced so a domain that is
    # implausibly dominated by one class (e.g. 65% forest on alpine meadow) is
    # visible in the run record instead of having to be reverse-engineered.
    veg_area = {}
    total_area = 0.0
    for r in rows:
        veg_area[r['vegTypeIndex']] = veg_area.get(r['vegTypeIndex'], 0.0) + r['area_m2']
        total_area += r['area_m2']
    veg_area_fraction = {
        str(k): round(v / total_area, 4)
        for k, v in sorted(veg_area.items(), key=lambda kv: -kv[1])
    } if total_area > 0 else {}

    soil_hist = {}
    for r in rows:
        soil_hist[str(r['soilTypeIndex'])] = soil_hist.get(str(r['soilTypeIndex']), 0) + 1

    logger.info(f"Vegetation area fractions ({veg_table_expected}): {veg_area_fraction}")
    logger.info(f"Soil STAS category counts: {soil_hist}")

    # Print JSON summary for agent
    print(json.dumps({
        "status": "success",
        "n_gru": gru_id,
        "n_hru": hru_id,
        "veg_scheme": VEG_SCHEME,
        "veg_table_expected": veg_table_expected,
        "veg_area_fraction": veg_area_fraction,
        "soil_category_counts": soil_hist,
        "elevation_range_m": [round(min(r['elevation'] for r in rows), 1),
                              round(max(r['elevation'] for r in rows), 1)],
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
