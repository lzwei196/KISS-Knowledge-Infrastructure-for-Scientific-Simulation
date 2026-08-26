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
  --shapefile_path:    Basin boundary shapefile (OR --bbox for a regional domain)
  --bbox:              minlon,minlat,maxlon,maxlat -- build a RECTANGULAR REGION
                       domain instead of a delineated basin. Required for a
                       regional-aggregate validation (e.g. gridded SWE clipped to
                       a box) where there is no gauge and therefore no catchment.
                       The rectangle is written to <output_dir>/region.geojson so
                       the observation clip uses the IDENTICAL polygon.
  --landcover_scheme:  Which legend the land-cover raster uses (see
                       LANDCOVER_SCHEMES). Getting this wrong is SILENT: the
                       classes still resolve, they just resolve to the wrong
                       surface, and `fetch_m` (the master PBSM blowing-snow
                       parameter) and `veg_height_m` come out wrong.
  --min_hru_area_frac: Fold land-cover classes smaller than this fraction of the
                       domain into the band's dominant class (default 0.0 = off).
  --n_elevation_bands: Number of elevation bands (default: 5). Use 1 on flat
                       terrain so HRUs are pure land-cover units.
  --output_dir:        Output directory

Outputs:
  hru_config.json -- HRU definitions with areas, elevations, land cover.
                     Each HRU carries TWO fetch fields:
                       fetch_m       -- landscape descriptor (a 30 m fetch under
                                        closed conifer canopy is physically
                                        right and is what the shelter ranking in
                                        derive_parameters.py sorts on)
                       pbsm_fetch_m  -- the SAME quantity forced into the range
                                        Classpbsm.cpp declares for the `fetch`
                                        parameter, <300 to 10000> m. This is the
                                        only one that may be written to a .prj.

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

# ---------------------------------------------------------------------------
# Land-cover legends for the real global/China products on this server.
#
# WHY THIS EXISTS: the table above is a private CRHM scheme with an AVHRR/UMD
# block bolted onto codes 10-16. Feeding it a raster that uses a DIFFERENT
# legend still "works" -- every code resolves to something -- so the error is
# SILENT. On the Hulunbuir steppe (Chinese analog of the Canadian Prairies) the
# CLCD grassland code 4 landed on `deciduous_forest` (veg 15 m, fetch 50 m) and
# GLCFCS30 grassland 130 fell through to the unknown-class default (fetch 500 m).
# `fetch_m` is the master PBSM blowing-snow fetch and `veg_height_m` sets the
# snow-holding capacity, so a mislabelled open steppe silently loses its
# wind-redistribution and sublimation physics -- the exact process the domain
# was chosen to test. Pass --landcover_scheme to say which legend you have.
#
# Each entry maps a PRODUCT class code -> one of the CRHM surface property sets.
# ---------------------------------------------------------------------------
_OPEN_STEPPE = {"name": "open_prairie", "veg_height_m": 0.3, "fetch_m": 1500, "canopy": False}
_CROP = {"name": "crop_stubble", "veg_height_m": 0.15, "fetch_m": 1000, "canopy": False}
_SHRUB = {"name": "shrub", "veg_height_m": 1.5, "fetch_m": 100, "canopy": False}
_DECID = {"name": "deciduous_forest", "veg_height_m": 15.0, "fetch_m": 50, "canopy": True}
_CONIF = {"name": "coniferous_forest", "veg_height_m": 12.0, "fetch_m": 30, "canopy": True}
_MIXED_F = {"name": "deciduous_forest", "veg_height_m": 13.0, "fetch_m": 40, "canopy": True}
_WETLAND = {"name": "wetland", "veg_height_m": 0.5, "fetch_m": 300, "canopy": False}
_WATER = {"name": "water", "veg_height_m": 0.0, "fetch_m": 2000, "canopy": False}
_BARE = {"name": "bare_ground", "veg_height_m": 0.01, "fetch_m": 2000, "canopy": False}
_TUNDRA = {"name": "alpine_tundra", "veg_height_m": 0.1, "fetch_m": 1500, "canopy": False}
_URBAN = {"name": "bare_ground", "veg_height_m": 0.05, "fetch_m": 500, "canopy": False}
_SNOWICE = {"name": "bare_ground", "veg_height_m": 0.01, "fetch_m": 2000, "canopy": False}

LANDCOVER_SCHEMES = {
    # native CRHM / AVHRR-UMD table above (legacy default)
    "crhm": CRHM_LANDCOVER_CLASSES,
    "avhrr_umd": CRHM_LANDCOVER_CLASSES,
    # CLCD v01 China 30 m annual (Yang & Huang) -- KISSPATH_DATA/vegetation/CLCD_raw
    "clcd": {
        1: _CROP, 2: _MIXED_F, 3: _SHRUB, 4: _OPEN_STEPPE, 5: _WATER,
        6: _SNOWICE, 7: _BARE, 8: _URBAN, 9: _WETLAND,
    },
    # GLCFCS30 30 m global fine classification (RADI/CAS), and ESA-CCI-LC, which
    # share the LCCS code space -- KISSPATH_DATA/vegetation/{GLCFCS30,ESA_CCI_LC*}
    "glcfcs30": {
        10: _CROP, 11: _CROP, 12: _CROP, 20: _CROP,
        51: _DECID, 52: _DECID, 61: _DECID, 62: _DECID,
        71: _CONIF, 72: _CONIF, 81: _CONIF, 82: _CONIF,
        91: _MIXED_F, 92: _MIXED_F,
        50: _DECID, 60: _DECID, 70: _CONIF, 80: _CONIF, 90: _MIXED_F, 100: _MIXED_F,
        110: _SHRUB, 120: _SHRUB, 121: _SHRUB, 122: _SHRUB,
        130: _OPEN_STEPPE, 140: _TUNDRA,
        150: _BARE, 152: _BARE, 153: _BARE,
        160: _WETLAND, 170: _WETLAND, 180: _WETLAND,
        190: _URBAN, 200: _BARE, 201: _BARE, 202: _BARE,
        210: _WATER, 220: _SNOWICE,
    },
}
LANDCOVER_SCHEMES["esa_cci"] = LANDCOVER_SCHEMES["glcfcs30"]

# ---------------------------------------------------------------------------
# PBSM fetch range, transcribed from Classpbsm.cpp declparam:
#   fetch  "fetch distance"  [1000.0]  <300.0 to 10000.0>
#
# The fetch_m values in the tables above are LANDSCAPE fetches: 30 m under
# closed conifer canopy, 50 m under deciduous, 100 m in shrub. Those are the
# physically right descriptors and the drift-cascade shelter ranking sorts on
# them -- but they are BELOW the range CRHM declares, and CRHM clamps an
# out-of-range parameter SILENTLY (triplet dt_006): the .prj says 30, the run
# uses 300, and nothing in the log says so. So every HRU also carries
# `pbsm_fetch_m`, the same value forced into the declared range HERE, where the
# adjustment can be reported. create_prj_file.py writes that field.
PBSM_FETCH_MIN = 300
PBSM_FETCH_MAX = 10000


def pbsm_fetch(fetch_m):
    """Landscape fetch -> a value valid for the PBSM `fetch` parameter."""
    v = min(float(PBSM_FETCH_MAX), max(float(PBSM_FETCH_MIN), float(fetch_m)))
    return int(v) if float(v).is_integer() else round(v, 2)


def parse_args():
    parser = argparse.ArgumentParser(description="Create CRHM HRU configuration")
    parser.add_argument("--dem_path", type=str, help="DEM raster path")
    parser.add_argument("--landcover_path", type=str, help="Land cover raster path")
    parser.add_argument("--shapefile_path", type=str, help="Basin boundary shapefile")
    parser.add_argument("--bbox", type=str,
                        help="minlon,minlat,maxlon,maxlat -- build a RECTANGULAR REGION "
                             "domain instead of a delineated basin (for a regional-"
                             "aggregate validation with no gauge). Writes region.geojson.")
    parser.add_argument("--landcover_scheme", type=str, default="crhm",
                        choices=sorted(LANDCOVER_SCHEMES),
                        help="Legend the land-cover raster uses. WRONG VALUE FAILS "
                             "SILENTLY (classes resolve to the wrong surface, so fetch_m "
                             "and veg_height_m -- the PBSM blowing-snow controls -- are "
                             "wrong). Default 'crhm' = the legacy CRHM/AVHRR-UMD table.")
    parser.add_argument("--order_by_veg_height", action="store_true",
                        help="Emit HRUs sorted by ASCENDING vegetation height. REQUIRED "
                             "for a blowing-snow (pbsm) domain: Classpbsm.cpp cascades "
                             "drift in HRU order and raises 'vegetation heights not in "
                             "ascending order' when they are not, so the open source "
                             "HRUs must precede the sheltered sink HRUs.")
    parser.add_argument("--min_hru_area_frac", type=float, default=0.0,
                        help="Fold land-cover classes covering less than this fraction of "
                             "the domain into their band's dominant class (default 0 = off). "
                             "Prevents sliver HRUs when using a 30 m fine-class product.")
    parser.add_argument("--n_elevation_bands", type=int, default=5, help="Number of elevation bands")
    parser.add_argument("--output_dir", type=str, help="Output directory")
    parser.add_argument("--equal_area_bands", action="store_true",
                        help="Place elevation-band edges at AREA quantiles (hypsometric "
                             "terciles for 3 bands) instead of equal elevation width. "
                             "This is what every validated CRHM mountain basin uses.")
    parser.add_argument("--consolidate_by_band", action="store_true",
                        help="Emit ONE HRU per elevation band (dominant land cover, "
                             "area-weighted mean elevation) instead of the "
                             "band x land-cover cross-tab. Gives the validated "
                             "Alpine/Forest/Valley 3-HRU structure.")
    return parser.parse_args()


def validate_inputs(dem_path, landcover_path, shapefile_path, output_dir):
    """Check that all preconditions are met."""
    errors = []

    if not dem_path or not Path(dem_path).exists():
        errors.append(f"DEM file not found: {dem_path}")

    if not landcover_path or not Path(landcover_path).exists():
        errors.append(f"Land cover file not found: {landcover_path}")

    if not shapefile_path or not Path(shapefile_path).exists():
        errors.append(f"Shapefile not found: {shapefile_path} "
                      f"(pass --bbox instead for a regional domain)")

    if not output_dir:
        errors.append("OUTPUT_DIR is not set")

    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)

    logger.info("Input validation passed.")


def write_region_geojson(bbox, output_dir):
    """Materialise a --bbox rectangle as a polygon file usable as the domain.

    Written BEFORE clipping so the observation clip (e.g. gridded SWE) can use
    the byte-identical polygon; a region domain and its regional-aggregate
    observation MUST share one boundary or the comparison is off-domain.
    """
    minlon, minlat, maxlon, maxlat = bbox
    if not (minlon < maxlon and minlat < maxlat):
        raise ValueError(f"--bbox must be minlon,minlat,maxlon,maxlat; got {bbox}")
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "region.geojson"
    ring = [[minlon, minlat], [maxlon, minlat], [maxlon, maxlat],
            [minlon, maxlat], [minlon, minlat]]
    gj = {"type": "FeatureCollection", "features": [{
        "type": "Feature",
        "properties": {"name": "crhm_region_domain",
                       "bbox": [minlon, minlat, maxlon, maxlat]},
        "geometry": {"type": "Polygon", "coordinates": [ring]}}]}
    with open(path, "w") as f:
        json.dump(gj, f)
    logger.info("Region domain %s -> %s", bbox, path)
    return str(path)


def process(dem_path, landcover_path, shapefile_path, n_bands, output_dir,
            equal_area_bands=False, consolidate_by_band=False,
            landcover_scheme="crhm", min_hru_area_frac=0.0, region_bbox=None,
            order_by_veg_height=False):
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
    #
    # Two schemes:
    #   equal-WIDTH (default, legacy): edges evenly spaced in elevation. In a
    #     high-relief mountain basin this puts almost no area in the top band
    #     (hypsometry is not uniform), so the "alpine" HRU ends up a sliver and
    #     the melt signal it carries is negligible.
    #   equal-AREA (--equal_area_bands): edges at area quantiles of the
    #     elevation distribution, i.e. hypsometric terciles for n_bands=3.
    #     EVERY validated CRHM mountain basin in SKILL.md (Gold, Blaeberry,
    #     Blue, Canoe, Kootenay, Crowsnest, Dore) uses area-equal terciles --
    #     until now they were hand-built because this tool could not emit them.
    if equal_area_bands and n_bands > 0:
        qs = [100.0 * i / n_bands for i in range(1, n_bands)]
        inner = [float(np.percentile(valid_elevations, q)) for q in qs]
        band_edges = [elev_min] + inner + [elev_max + 1]
    else:
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
    unmapped_classes = set()

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
            lc_table = LANDCOVER_SCHEMES.get(landcover_scheme, CRHM_LANDCOVER_CLASSES)
            if lc_int not in lc_table:
                unmapped_classes.add(lc_int)
            lc_props = lc_table.get(
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

    if unmapped_classes:
        logger.warning(
            "land-cover codes %s are NOT in the '%s' legend -- they fell through to the "
            "generic default (fetch 500 m, veg 0.5 m). If most of the domain is unmapped "
            "you are almost certainly using the WRONG --landcover_scheme.",
            sorted(unmapped_classes), landcover_scheme)

    # Fold sliver land-cover classes into the band's dominant class. A 30 m
    # fine-class product (GLCFCS30/CLCD) otherwise emits a long tail of <1%
    # classes, each becoming a full HRU with its own parameter slot -- nhru
    # explodes and the per-HRU tuning recipes become unusable.
    if min_hru_area_frac and min_hru_area_frac > 0:
        domain_area = sum(h["area_km2"] for h in hrus)
        kept = []
        for band_idx in sorted({h["elevation_band"] for h in hrus}):
            members = [h for h in hrus if h["elevation_band"] == band_idx]
            big = [m for m in members
                   if m["area_km2"] / domain_area >= min_hru_area_frac]
            small = [m for m in members if m not in big]
            if not big:                       # whole band is slivers -> keep its largest
                big = [max(members, key=lambda m: m["area_km2"])]
                small = [m for m in members if m not in big]
            if small:
                host = max(big, key=lambda m: m["area_km2"])
                add_area = sum(m["area_km2"] for m in small)
                add_pix = sum(m["pixel_count"] for m in small)
                # area-weighted elevation so folding does not shift the band's mean
                host["mean_elevation_m"] = round(
                    (host["mean_elevation_m"] * host["area_km2"]
                     + sum(m["mean_elevation_m"] * m["area_km2"] for m in small))
                    / (host["area_km2"] + add_area), 1)
                host["area_km2"] = round(host["area_km2"] + add_area, 4)
                host["pixel_count"] += add_pix
                host["folded_classes"] = sorted(m["land_cover_class"] for m in small)
                logger.info("band %d: folded %d sliver class(es) %s (%.1f km2) into '%s'",
                            band_idx, len(small), host["folded_classes"], add_area,
                            host["land_cover_name"])
            kept.extend(big)
        for i, h in enumerate(kept, start=1):
            h["hru_id"] = i
        hrus = kept

    # Optional consolidation: ONE HRU per elevation band (the validated
    # Alpine/Forest/Valley structure used by every validated CRHM mountain
    # basin). The band x land-cover cross-tab can otherwise emit 10-30 slivers,
    # which blows up nhru and makes the documented per-HRU tuning recipes
    # (gw_max / Kstorage triplets in SKILL.md) inapplicable.
    if consolidate_by_band:
        merged = []
        for band_idx in sorted({h["elevation_band"] for h in hrus}, reverse=True):
            members = [h for h in hrus if h["elevation_band"] == band_idx]
            area = sum(m["area_km2"] for m in members)
            pix = sum(m["pixel_count"] for m in members)
            # area-weighted mean elevation; dominant land cover by area
            mean_elev = sum(m["mean_elevation_m"] * m["area_km2"] for m in members) / area
            dom = max(members, key=lambda m: m["area_km2"])
            merged.append({
                "hru_id": len(merged) + 1,
                "elevation_band": band_idx,
                "elevation_band_range_m": dom["elevation_band_range_m"],
                "mean_elevation_m": round(mean_elev, 1),
                "land_cover_class": dom["land_cover_class"],
                "land_cover_name": dom["land_cover_name"],
                "area_km2": round(area, 4),
                "veg_height_m": dom["veg_height_m"],
                "fetch_m": dom["fetch_m"],
                "has_canopy": dom["has_canopy"],
                "pixel_count": pix,
                "merged_from": len(members),
            })
        hrus = merged
        logger.info("Consolidated to %d HRUs (one per elevation band, high->low)", len(hrus))

    # Blowing-snow HRU ordering. Classpbsm.cpp walks the HRU list to cascade
    # drift from exposed to sheltered units and logs "vegetation heights not in
    # ascending order" when the list is not sorted that way; the cascade then
    # deposits drift on the wrong units. Land-cover HRUs come out of the
    # cross-tab in raster-class order (here stubble 0.15 m, forest 15 m,
    # grassland 0.3 m), which violates it.
    if order_by_veg_height:
        hrus.sort(key=lambda h: (float(h.get("veg_height_m", 0.3)),
                                 -float(h.get("area_km2", 0.0))))
        for i, h in enumerate(hrus, start=1):
            h["hru_id"] = i
        logger.info("HRUs ordered by ascending vegetation height (pbsm drift "
                    "cascade): %s",
                    [(h["land_cover_name"], h["veg_height_m"]) for h in hrus])

    # Stamp the PBSM-valid fetch on every HRU (see PBSM_FETCH_MIN). Done after
    # folding/consolidation/ordering so it is derived from the fetch_m each HRU
    # actually ends up with, and reported per land-cover class: a forest-heavy
    # domain legitimately sits on the 300 m floor, but seeing that in the log is
    # the difference between a known limit and a silent one.
    raised = {}
    for h in hrus:
        h["pbsm_fetch_m"] = pbsm_fetch(h.get("fetch_m", PBSM_FETCH_MIN))
        if h["pbsm_fetch_m"] != h.get("fetch_m"):
            raised[h["land_cover_name"]] = (h.get("fetch_m"), h["pbsm_fetch_m"])
    if raised:
        logger.warning(
            "pbsm_fetch_m differs from the landscape fetch_m for %d class(es) %s "
            "-- CRHM declares fetch <%d to %d> m and clamps silently, so the .prj "
            "carries the adjusted value.",
            len(raised),
            {k: f"{v[0]} -> {v[1]} m" for k, v in sorted(raised.items())},
            PBSM_FETCH_MIN, PBSM_FETCH_MAX)

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
        "band_scheme": "equal_area" if equal_area_bands else "equal_width",
        "landcover_scheme": landcover_scheme,
        "domain_kind": "region_bbox" if region_bbox else "basin",
    }
    if region_bbox:
        config["region_bbox"] = list(region_bbox)
        config["region_polygon"] = str(Path(output_dir) / "region.geojson")

    # Basin centroid -- REQUIRED downstream: create_prj_file writes `basin hru_lat`
    # and calcsun computes solar geometry from it. Without this the .prj falls back
    # to the 51 deg N default, which is silently right for Canadian basins and
    # silently WRONG everywhere else (e.g. 38.8 N on the Tibetan Plateau).
    try:
        cen = basin.to_crs("EPSG:4326").geometry.union_all().centroid
        config["latitude"] = round(float(cen.y), 4)
        config["longitude"] = round(float(cen.x), 4)
    except Exception as exc:  # geometry backends differ across geopandas versions
        logger.warning("Could not compute basin centroid (%s); hru_lat will fall back", exc)

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
            # pbsm_fetch_m is what create_prj_file.py writes for the PBSM
            # `fetch` parameter; if it is missing or out of the declared range
            # the .prj is out of range too, and CRHM will not say so.
            for h in config["hrus"]:
                f = h.get("pbsm_fetch_m")
                if f is None:
                    errors.append(f"HRU {h.get('hru_id')} has no pbsm_fetch_m")
                elif not (PBSM_FETCH_MIN <= float(f) <= PBSM_FETCH_MAX):
                    errors.append(
                        f"HRU {h.get('hru_id')} pbsm_fetch_m={f} outside the "
                        f"declared PBSM range <{PBSM_FETCH_MIN} to {PBSM_FETCH_MAX}>")

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

    # A REGION domain (--bbox) has no catchment polygon; synthesise the
    # rectangle and use it as the clip boundary for every downstream step.
    region_bbox = None
    if args.bbox:
        try:
            region_bbox = tuple(float(v) for v in args.bbox.split(","))
        except ValueError:
            logger.error("--bbox must be four comma-separated numbers: "
                         "minlon,minlat,maxlon,maxlat")
            sys.exit(1)
        if len(region_bbox) != 4:
            logger.error("--bbox needs exactly 4 values, got %d", len(region_bbox))
            sys.exit(1)
        if not output_dir:
            logger.error("--bbox requires --output_dir")
            sys.exit(1)
        shapefile_path = write_region_geojson(region_bbox, output_dir)

    validate_inputs(dem_path, landcover_path, shapefile_path, output_dir)

    try:
        output_path = process(dem_path, landcover_path, shapefile_path, n_bands, output_dir,
                              equal_area_bands=args.equal_area_bands,
                              consolidate_by_band=args.consolidate_by_band,
                              landcover_scheme=args.landcover_scheme,
                              min_hru_area_frac=args.min_hru_area_frac,
                              region_bbox=region_bbox,
                              order_by_veg_height=args.order_by_veg_height)
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(2)

    validate_outputs(output_path)

    # JSON output for agent consumption
    print(json.dumps({"status": "success", "output": output_path}))
    sys.exit(0)
