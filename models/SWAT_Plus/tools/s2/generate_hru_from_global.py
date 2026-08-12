#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
====================================================
Tool ID:      generate_hru_from_global
Stage:        s2_hru_definition
Description:  Generate a complete, runnable SWAT+ TxtInOut project from global
              datasets (AVHRR land cover, HWSD soil, DEM). Replaces the QSWAT+
              GUI entirely for automated basin setup.

Inputs:
  --basin_shp       : Basin boundary shapefile
  --dem_path        : DEM raster path (or "auto" to select based on location)
  --landcover_path  : Land cover raster (default: AVHRR 1km global)
  --hwsd_raster     : HWSD soil raster (default: data/soil/HWSD_RASTER/hwsd.bil)
  --hwsd_mdb        : HWSD MDB database (default: data/forcing/huaihe_raw/soil/HWSD.mdb)
  --output_dir      : Output TxtInOut directory
  --template_dir    : SWAT+ template project for auxiliary files
  --basin_name      : Basin name for file headers
  --n_subbasins     : Target number of subbasins (default: auto based on area)
  --slope_classes   : Slope class breaks in percent (default: "0-5,5-15,15-30,30-9999")
  --hru_threshold   : Minimum HRU area fraction to keep (default: 0.05 = 5%)
  --start_year      : Simulation start year
  --end_year        : Simulation end year
  --grid_nc         : Optional VIC grid NC; if provided, each VIC cell = one subbasin

Outputs:
  - Complete runnable TxtInOut directory with:
    hru.con, hru-data.hru, rout_unit.con, rout_unit.def, rout_unit.ele,
    rout_unit.rtu, topography.hyd, hydrology.hyd, soils.sol, landuse.lum,
    object.cnt, file.cio, time.sim, codes.bsn, print.prt, etc.
  - JSON summary to stdout

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
import shutil
import math
import subprocess
import csv
import io
from pathlib import Path
from collections import Counter, defaultdict

import numpy as np

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path("/mnt/disk1/Hydrocraft_server")
DEFAULT_LANDCOVER = PROJECT_ROOT / "data/landcover/AVHRR_1km_LANDCOVER_1981_1994.GLOBAL.tif"
DEFAULT_HWSD_RASTER = PROJECT_ROOT / "data/soil/HWSD_RASTER/hwsd.bil"
DEFAULT_HWSD_MDB = PROJECT_ROOT / "data/forcing/huaihe_raw/soil/HWSD.mdb"
DEFAULT_DEM_CHINA = PROJECT_ROOT / "data/dem/china_dem_90m/china_dem_90m.tif"
DEFAULT_TEMPLATE = PROJECT_ROOT / "models/SWAT_Plus/run_lrew/swatplus_rev59_demo"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


# ===========================================================================
# UMD AVHRR land cover -> SWAT+ plant mapping
# ===========================================================================
UMD_TO_SWAT = {
    0:  {"plant": "watr", "lum": "watr_lum",  "desc": "Water"},
    1:  {"plant": "pine", "lum": "frse_lum",  "desc": "Evergreen Needleleaf"},
    2:  {"plant": "frse", "lum": "frse_lum",  "desc": "Evergreen Broadleaf"},
    3:  {"plant": "frsd", "lum": "frsd_lum",  "desc": "Deciduous Needleleaf"},
    4:  {"plant": "frsd", "lum": "frsd_lum",  "desc": "Deciduous Broadleaf"},
    5:  {"plant": "frst", "lum": "frst_lum",  "desc": "Mixed Forest"},
    6:  {"plant": "rngb", "lum": "rngb_lum",  "desc": "Woodland"},
    7:  {"plant": "rnge", "lum": "rnge_lum",  "desc": "Wooded Grassland"},
    8:  {"plant": "rngb", "lum": "rngb_lum",  "desc": "Closed Shrubland"},
    9:  {"plant": "rnge", "lum": "rnge_lum",  "desc": "Open Shrubland"},
    10: {"plant": "rnge", "lum": "rnge_lum",  "desc": "Grassland"},
    11: {"plant": "agrl", "lum": "agrl_lum",  "desc": "Cropland"},
    12: {"plant": "barr", "lum": "barr_lum",  "desc": "Bare Ground"},
    13: {"plant": "urld", "lum": "urld_lum",  "desc": "Urban"},
    14: {"plant": "watr", "lum": "watr_lum",  "desc": "Snow/Ice"},
}

# Manning's n for overland flow per land use
OVN_TABLE = {
    "watr_lum": "fallow_nores",
    "frse_lum": "forest_heavy",
    "frsd_lum": "forest_med",
    "frst_lum": "forest_med",
    "rngb_lum": "range_20cover",
    "rnge_lum": "densegrass",
    "agrl_lum": "convtill_res",
    "barr_lum": "fallow_nores",
    "urld_lum": "urban_asphalt",
    "past_lum": "densegrass",
    "wetf_lum": "forest_med",
}

# CN table name per land use
CN_TABLE = {
    "watr_lum": "water",
    "frse_lum": "wood_f",
    "frsd_lum": "wood_f",
    "frst_lum": "wood_f",
    "rngb_lum": "wood_f",
    "rnge_lum": "pastg_f",
    "agrl_lum": "rc_strow_g",
    "barr_lum": "fal_bare",
    "urld_lum": "urban",
    "past_lum": "pastg_f",
    "wetf_lum": "wood_p",
}

# Conservation practice per land use
CONS_PRACTICE = {
    "watr_lum": "up_down_slope",
    "frse_lum": "up_down_slope",
    "frsd_lum": "up_down_slope",
    "frst_lum": "up_down_slope",
    "rngb_lum": "up_down_slope",
    "rnge_lum": "up_down_slope",
    "agrl_lum": "cross_slope",
    "barr_lum": "up_down_slope",
    "urld_lum": "up_down_slope",
    "past_lum": "up_down_slope",
    "wetf_lum": "up_down_slope",
}


# ===========================================================================
# Soil (reuse HWSD tool functions)
# ===========================================================================
def _safe_float(val, default=0.0):
    try:
        return float(val) if val and str(val).strip() else default
    except (ValueError, TypeError):
        return default


def load_hwsd_mdb(mdb_path):
    """Load HWSD_DATA table from MDB into dict keyed by MU_GLOBAL."""
    logger.info(f"Loading HWSD MDB: {mdb_path}")
    result = subprocess.run(
        ['mdb-export', str(mdb_path), 'HWSD_DATA'],
        capture_output=True, text=True, timeout=120
    )
    if result.returncode != 0:
        raise RuntimeError(f"mdb-export failed: {result.stderr[:200]}")
    reader = csv.DictReader(io.StringIO(result.stdout))
    mu_data = {}
    for row in reader:
        try:
            mu = int(row['MU_GLOBAL'])
        except (ValueError, KeyError):
            continue
        share = _safe_float(row.get('SHARE', 0))
        has_texture = bool(row.get('T_SAND') and str(row['T_SAND']).strip())
        if mu not in mu_data or (has_texture and share > mu_data[mu].get('_share', 0)):
            row['_share'] = share
            mu_data[mu] = row
    logger.info(f"HWSD MDB loaded: {len(mu_data)} mapping units")
    return mu_data


def classify_texture(sand, silt, clay):
    total = sand + silt + clay
    if total <= 0:
        return "L"
    sand, silt, clay = sand * 100 / total, silt * 100 / total, clay * 100 / total
    if clay >= 40 and sand <= 45 and silt < 40:
        return "C"
    elif clay >= 40 and silt >= 40:
        return "SIC"
    elif clay >= 35 and sand > 45:
        return "SC"
    elif clay >= 27 and clay < 40 and sand > 20 and sand <= 45:
        return "CL"
    elif clay >= 27 and clay < 40 and sand <= 20:
        return "SICL"
    elif clay >= 20 and clay < 35 and silt < 28 and sand > 45:
        return "SCL"
    elif silt >= 80:
        return "SI"
    elif silt >= 50 and clay >= 12 and clay < 27:
        return "SIL"
    elif silt >= 50 and clay < 12:
        return "SIL"
    elif clay >= 7 and clay < 27 and silt >= 28 and silt < 50 and sand <= 52:
        return "L"
    elif clay < 7 and silt < 50 and sand > 52 and sand <= 90:
        return "SL"
    elif (sand > 85 and clay < 10) or (sand >= 70 and silt <= 15 and clay < 10):
        return "S" if sand > 90 else "LS"
    elif sand > 52 and clay >= 7 and clay < 20:
        return "SL"
    elif sand > 90:
        return "S"
    else:
        return "L"


def hydrologic_group(ksat_mm_hr):
    if ksat_mm_hr >= 36.0:
        return "A"
    elif ksat_mm_hr >= 3.6:
        return "B"
    elif ksat_mm_hr >= 0.36:
        return "C"
    else:
        return "D"


def saxton_rawls_awc(sand, clay, om):
    s, c = sand / 100.0, clay / 100.0
    wp1500t = -0.024*s + 0.487*c + 0.006*om + 0.005*s*om - 0.013*c*om + 0.068*s*c + 0.031
    wp1500 = wp1500t + 0.14 * wp1500t - 0.02
    fc33t = -0.251*s + 0.195*c + 0.011*om + 0.006*s*om - 0.027*c*om + 0.452*s*c + 0.299
    fc33 = fc33t + 1.283 * fc33t * fc33t - 0.374 * fc33t - 0.015
    return max(0.01, min(0.50, fc33 - wp1500))


def cosby_ksat(sand, clay):
    log_ksat = -0.6 + 0.0126 * sand - 0.0064 * clay
    return max(0.01, 10.0 ** log_ksat * 25.4)


def williams_usle_k(sand, silt, clay, om):
    sn1 = max(0.001, 1.0 - sand / 100.0)
    fom = max(0.0001, om / 100.0)
    k_forg = 1.0 - 0.25 * fom / (fom + math.exp(3.72 - 2.95 * fom))
    k_fhi_sand = 1.0 - 0.7 * sn1 / (sn1 + math.exp(-5.51 + 22.9 * sn1))
    k = 0.2 + 0.3 * math.exp(-0.0256 * sand * (1.0 - silt / 100.0))
    m_silt = silt / (clay + silt) if (clay + silt) > 0 else 0.5
    k *= (m_silt ** 0.3)
    k *= k_forg * k_fhi_sand
    return max(0.01, min(0.65, k))


def estimate_albedo(sand, clay, om):
    alb = 0.10 + 0.15 * (sand / 100.0) - 0.02 * min(om, 5.0)
    return max(0.05, min(0.35, round(alb, 2)))


def normalize_texture(sand, silt, clay):
    total = sand + silt + clay
    if total <= 0:
        return 33.3, 33.3, 33.4
    if abs(total - 100.0) < 0.1:
        return sand, silt, clay
    f = 100.0 / total
    return round(sand * f, 1), round(silt * f, 1), round(clay * f, 1)


# ===========================================================================
# CLI argument parsing
# ===========================================================================
def parse_args():
    p = argparse.ArgumentParser(
        description="Generate complete SWAT+ TxtInOut from global datasets"
    )
    p.add_argument("--basin_shp", required=True,
                    help="Basin boundary shapefile")
    p.add_argument("--dem_path", default="auto",
                    help="DEM raster path, or 'auto' (default)")
    p.add_argument("--landcover_path", default=str(DEFAULT_LANDCOVER),
                    help="Land cover raster (default: AVHRR 1km global)")
    p.add_argument("--hwsd_raster", default=str(DEFAULT_HWSD_RASTER),
                    help="HWSD soil raster")
    p.add_argument("--hwsd_mdb", default=str(DEFAULT_HWSD_MDB),
                    help="HWSD MDB database")
    p.add_argument("--output_dir", required=True,
                    help="Output TxtInOut directory")
    p.add_argument("--template_dir", default=str(DEFAULT_TEMPLATE),
                    help="SWAT+ template project dir")
    p.add_argument("--basin_name", default="basin",
                    help="Basin name for file headers")
    p.add_argument("--n_subbasins", type=int, default=0,
                    help="Target subbasins (0=auto from area, default: 0)")
    p.add_argument("--slope_classes", default="0-5,5-15,15-30,30-9999",
                    help="Slope class breaks in %% (default: '0-5,5-15,15-30,30-9999')")
    p.add_argument("--hru_threshold", type=float, default=0.05,
                    help="Min HRU area fraction (default: 0.05=5%%)")
    p.add_argument("--start_year", type=int, required=True)
    p.add_argument("--end_year", type=int, required=True)
    p.add_argument("--grid_nc", default=None,
                    help="Optional VIC grid NC: each VIC cell = one subbasin")
    p.add_argument("--channel_topology", default="",
                    help="channel_topology.json from tools/s1/build_channel_topology.py. "
                         "Supplies the real downstream id, network-accumulated upstream "
                         "area, Strahler order, reach length and slope per channel. "
                         "WITHOUT it the deck falls back to a one-hop STAR topology, "
                         "which is a lumped water-yield proxy and NOT a routed hydrograph.")
    p.add_argument("--esco", type=float, default=0.15,
                    help="hydrology.hyd soil-evap comp. 0.15=max ET (over-predicting humid e.g. Bengbu); 0.85=restrict ET (under-predicting e.g. Xixian)")
    p.add_argument("--cn3_swf", type=float, default=0.0,
                    help="hydrology.hyd wet-season CN3 adj. 0.0 over-predicting; ~0.5 amplifies wet-season quickflow for under-predicting basins")
    p.add_argument("--perco", type=float, default=0.75,
                    help="hydrology.hyd percolation coef. 0.75 routes to slow baseflow (over-predicting); ~0.30 keeps quickflow (under-predicting). NOT in cal_parms.cal -> can ONLY be set here, never via calibration.cal")
    return p.parse_args()


def parse_slope_classes(spec):
    """Parse '0-5,5-15,15-30,30-9999' into list of (lo, hi) tuples."""
    classes = []
    for part in spec.split(","):
        lo, hi = part.strip().split("-")
        classes.append((float(lo), float(hi)))
    return classes


# ===========================================================================
# Step 1: Subbasin delineation
# ===========================================================================
def create_subbasins_from_grid_nc(grid_nc_path, basin_shp):
    """Create subbasins from a VIC grid NC -- each cell = one subbasin."""
    import xarray as xr
    import geopandas as gpd
    from shapely.geometry import box

    logger.info(f"Creating subbasins from VIC grid: {grid_nc_path}")
    ds = xr.open_dataset(grid_nc_path)

    if 'mask' in ds:
        valid = ds['mask'].stack(cell=('y', 'x')).dropna('cell')
        lats = valid.coords['y'].values.astype(float)
        lons = valid.coords['x'].values.astype(float)
    elif 'lat' in ds and 'lon' in ds:
        lats = ds['lat'].values.astype(float)
        lons = ds['lon'].values.astype(float)
    else:
        raise ValueError("Grid NC must have (mask, y, x) or (lat, lon)")

    if 'y' in ds.coords and len(ds.coords['y']) > 1:
        resolution = abs(float(ds.coords['y'].values[1] - ds.coords['y'].values[0]))
    else:
        resolution = 0.25
    ds.close()

    half = resolution / 2.0
    geoms = []
    sub_data = []
    for i, (lat, lon) in enumerate(zip(lats, lons)):
        geom = box(lon - half, lat - half, lon + half, lat + half)
        geoms.append(geom)
        sub_data.append({
            'sub_id': i + 1,
            'lat': float(lat),
            'lon': float(lon),
        })

    gdf = gpd.GeoDataFrame(sub_data, geometry=geoms, crs="EPSG:4326")

    # Clip to basin boundary
    basin_gdf = gpd.read_file(basin_shp).to_crs("EPSG:4326")
    basin_union = basin_gdf.geometry.unary_union
    gdf['geometry'] = gdf.geometry.intersection(basin_union)
    gdf = gdf[~gdf.geometry.is_empty].copy()

    # Compute area in ha using equal-area projection
    gdf_ea = gdf.to_crs(epsg=6933)
    gdf['area_ha'] = gdf_ea.geometry.area / 10000.0

    logger.info(f"  Created {len(gdf)} subbasins from grid cells "
                f"(resolution={resolution}deg)")
    return gdf


def warn_rectangular_subbasins():
    """The rectangular fallback is not a hydrologic partition. Say so."""
    logger.warning("=" * 78)
    logger.warning("WARNING: no --subbasin_shp supplied -- subbasins will be cut "
                   "as a RECTANGULAR LAT/LON GRID clipped to the basin outline.")
    logger.warning("WARNING: those are grid cells, not hydrologic subbasins. Each "
                   "one's 'channel' is not a real reach, so even a correct "
                   "flow-network cascade built over them is a cell-to-cell "
                   "routing graph rather than the dag's distributed STREAM "
                   "network.")
    logger.warning("WARNING: delineate real subbasins first with "
                   "tools/s1/delineate_watershed.py (it runs wbt.subbasins() on "
                   "the flow network and writes subbasins.shp) and pass them via "
                   "--subbasin_shp.")
    logger.warning("=" * 78)


def load_subbasins_from_shapefile(subbasin_shp):
    """Load REAL flow-network subbasins (e.g. subbasins.shp from
    tools/s1/delineate_watershed.py, produced by wbt.subbasins()).

    Returns the same schema the rest of this tool expects: sub_id / lat / lon /
    area_ha in EPSG:4326, sorted by sub_id so that channel ids stay positional
    (cha{idx+1} <-> sub_ids[idx]) and therefore consistent with
    build_channel_topology.py and define_subbasins.py.
    """
    import geopandas as gpd

    logger.info(f"Loading flow-network subbasins from: {subbasin_shp}")
    gdf = gpd.read_file(subbasin_shp)
    if gdf.empty:
        raise RuntimeError(f"Subbasin shapefile is empty: {subbasin_shp}")
    gdf = gdf.to_crs("EPSG:4326")

    # whitebox raster_to_vector_polygons names the id column VALUE/FID; accept
    # the common spellings rather than silently renumbering, because the ids
    # must agree with whatever build_channel_topology.py read.
    id_col = next((c for c in ("sub_id", "SUB_ID", "VALUE", "value", "FID", "DN")
                   if c in gdf.columns), None)
    if id_col is None:
        logger.warning("No id column (sub_id/VALUE/FID/DN) in %s -- assigning "
                       "1..N in file order. build_channel_topology.py must be "
                       "run against this SAME file or the two will "
                       "desynchronize.", subbasin_shp)
        gdf["sub_id"] = range(1, len(gdf) + 1)
    else:
        gdf["sub_id"] = gdf[id_col].astype(int)
        if id_col != "sub_id":
            logger.info("  Using '%s' as sub_id", id_col)

    if gdf["sub_id"].duplicated().any():
        dups = sorted(gdf.loc[gdf["sub_id"].duplicated(), "sub_id"].unique())
        raise RuntimeError(
            f"Duplicate sub_id values in {subbasin_shp}: {dups[:10]}. Each "
            "subbasin must be a single dissolved polygon; a multipart subbasin "
            "split into several rows would create duplicate channels.")

    gdf = gdf.sort_values("sub_id").reset_index(drop=True)

    gdf_ea = gdf.to_crs(epsg=6933)
    gdf["area_ha"] = gdf_ea.geometry.area / 10000.0
    centroids = gdf.geometry.centroid
    gdf["lat"] = centroids.y
    gdf["lon"] = centroids.x

    total_km2 = gdf["area_ha"].sum() / 100.0
    logger.info(f"  Loaded {len(gdf)} flow-network subbasins, "
                f"{total_km2:.0f} km2 total "
                f"(min {gdf['area_ha'].min()/100:.1f} / "
                f"max {gdf['area_ha'].max()/100:.1f} km2)")
    return gdf[["sub_id", "lat", "lon", "area_ha", "geometry"]]


def create_subbasins_from_basin(basin_shp, dem_path, n_subbasins):
    """Create subbasins by subdividing the basin using a regular grid.

    NOT a hydrologic partition -- see warn_rectangular_subbasins(). Retained as
    a last-resort fallback for when no delineation is available.
    """
    import geopandas as gpd
    from shapely.geometry import box

    logger.info(f"Creating subbasins from basin shapefile: {basin_shp}")
    basin_gdf = gpd.read_file(basin_shp).to_crs("EPSG:4326")
    basin_union = basin_gdf.geometry.unary_union
    bounds = basin_union.bounds  # (minx, miny, maxx, maxy)

    # Compute area in km2
    basin_ea = basin_gdf.to_crs(epsg=6933)
    area_km2 = basin_ea.geometry.area.sum() / 1e6

    # Auto-determine n_subbasins from area if not specified
    if n_subbasins <= 0:
        # Target ~100-500 km2 per subbasin
        n_subbasins = max(3, min(50, int(area_km2 / 200)))
    logger.info(f"  Basin area: {area_km2:.0f} km2, target subbasins: {n_subbasins}")

    # Determine grid dimensions
    dx = bounds[2] - bounds[0]
    dy = bounds[3] - bounds[1]
    aspect = dx / dy if dy > 0 else 1.0
    n_cols = max(1, int(math.sqrt(n_subbasins * aspect)))
    n_rows = max(1, int(n_subbasins / n_cols))
    cell_w = dx / n_cols
    cell_h = dy / n_rows

    geoms = []
    sub_data = []
    sub_id = 1
    for row in range(n_rows):
        for col in range(n_cols):
            x0 = bounds[0] + col * cell_w
            y0 = bounds[1] + row * cell_h
            cell_geom = box(x0, y0, x0 + cell_w, y0 + cell_h)
            clipped = cell_geom.intersection(basin_union)
            if clipped.is_empty or clipped.area < 1e-10:
                continue
            lat_c = (y0 + y0 + cell_h) / 2
            lon_c = (x0 + x0 + cell_w) / 2
            geoms.append(clipped)
            sub_data.append({
                'sub_id': sub_id,
                'lat': lat_c,
                'lon': lon_c,
            })
            sub_id += 1

    gdf = gpd.GeoDataFrame(sub_data, geometry=geoms, crs="EPSG:4326")
    gdf_ea = gdf.to_crs(epsg=6933)
    gdf['area_ha'] = gdf_ea.geometry.area / 10000.0

    logger.info(f"  Created {len(gdf)} subbasins ({n_rows}x{n_cols} grid)")
    return gdf


# ===========================================================================
# Step 2: Land cover classification
# ===========================================================================
def classify_landcover(subbasins_gdf, landcover_path):
    """Extract dominant UMD land cover class per subbasin."""
    import rasterio
    from rasterstats import zonal_stats

    logger.info(f"Classifying land cover from: {landcover_path}")
    with rasterio.open(landcover_path) as src:
        nodata = src.nodata if src.nodata is not None else 255

    stats = zonal_stats(
        subbasins_gdf.to_crs("EPSG:4326"),
        str(landcover_path),
        band=1, stats="majority", nodata=nodata,
        all_touched=True,
    )

    lc_classes = []
    for s in stats:
        majority = s.get("majority")
        if majority is None or int(majority) not in UMD_TO_SWAT:
            majority = 10  # Default to grassland
        lc_classes.append(int(majority))

    # Distribution summary
    dist = Counter(lc_classes)
    for cls, cnt in sorted(dist.items()):
        desc = UMD_TO_SWAT.get(cls, {}).get("desc", "Unknown")
        logger.info(f"  Land cover {cls} ({desc}): {cnt} subbasins")

    return lc_classes


def classify_landcover_fractions(subbasins_gdf, landcover_path):
    """Extract fractional land cover per subbasin for multi-HRU generation."""
    import rasterio
    from rasterstats import zonal_stats

    logger.info(f"Extracting land cover fractions from: {landcover_path}")
    with rasterio.open(landcover_path) as src:
        nodata = src.nodata if src.nodata is not None else 255

    stats = zonal_stats(
        subbasins_gdf.to_crs("EPSG:4326"),
        str(landcover_path),
        band=1,
        categorical=True,
        nodata=nodata,
        all_touched=True,
    )

    lc_fractions = []
    for s in stats:
        total = sum(s.values()) if s else 1
        if total == 0:
            total = 1
        fracs = {}
        for cls_val, count in s.items():
            cls_int = int(cls_val)
            if cls_int in UMD_TO_SWAT:
                fracs[cls_int] = count / total
        if not fracs:
            fracs = {10: 1.0}  # Default grassland
        lc_fractions.append(fracs)

    return lc_fractions


# ===========================================================================
# Step 3: Soil classification
# ===========================================================================
def extract_soil_per_subbasin(subbasins_gdf, hwsd_raster, hwsd_db):
    """Extract dominant HWSD MU_GLOBAL per subbasin and build soil profiles."""
    import rasterio
    from rasterstats import zonal_stats

    logger.info(f"Extracting soil from HWSD: {hwsd_raster}")
    with rasterio.open(str(hwsd_raster)) as src:
        nodata = src.nodata if src.nodata is not None else 0
        raster_crs = src.crs

    gdf_proj = subbasins_gdf.to_crs("EPSG:4326")
    if raster_crs and str(raster_crs) != "EPSG:4326":
        gdf_proj = gdf_proj.to_crs(raster_crs)

    stats = zonal_stats(
        gdf_proj, str(hwsd_raster),
        band=1, stats="majority", nodata=nodata,
        all_touched=True,
    )

    mu_codes = []
    for s in stats:
        mu = int(s["majority"]) if s.get("majority") is not None else 0
        mu_codes.append(mu)

    # Build soil profiles
    soil_profiles = {}
    soil_names_per_sub = []
    for i, mu in enumerate(mu_codes):
        if mu > 0 and mu in hwsd_db:
            row = hwsd_db[mu]
            t_sand = _safe_float(row.get('T_SAND'))
            t_silt = _safe_float(row.get('T_SILT'))
            t_clay = _safe_float(row.get('T_CLAY'))
            if t_sand + t_silt + t_clay < 1.0:
                soil_name = f"dflt_{i+1:04d}"
                if soil_name not in soil_profiles:
                    soil_profiles[soil_name] = _build_default_soil(soil_name)
            else:
                soil_name = f"hw_{mu:05d}"
                if soil_name not in soil_profiles:
                    soil_profiles[soil_name] = _build_hwsd_soil(soil_name, row)
        else:
            soil_name = f"dflt_{i+1:04d}"
            if soil_name not in soil_profiles:
                soil_profiles[soil_name] = _build_default_soil(soil_name)
        soil_names_per_sub.append(soil_name)

    logger.info(f"  Extracted {len(soil_profiles)} unique soil profiles "
                f"for {len(subbasins_gdf)} subbasins")
    return soil_names_per_sub, soil_profiles


def _build_hwsd_soil(name, row):
    """Build a soil profile dict from HWSD row."""
    t_sand, t_silt, t_clay = normalize_texture(
        _safe_float(row.get('T_SAND')),
        _safe_float(row.get('T_SILT')),
        _safe_float(row.get('T_CLAY'))
    )
    t_oc = _safe_float(row.get('T_OC'), 1.0)
    t_bd = max(0.90, min(2.50, _safe_float(row.get('T_REF_BULK_DENSITY'), 1.4)))
    t_om = t_oc * 1.724
    t_gravel = min(80.0, max(0.0, _safe_float(row.get('T_GRAVEL'), 0.0)))
    t_caco3 = min(50.0, max(0.0, _safe_float(row.get('T_CACO3'), 0.0)))
    t_ph = max(3.5, min(10.0, _safe_float(row.get('T_PH_H2O'), 6.5)))

    s_sand_raw = _safe_float(row.get('S_SAND'))
    s_silt_raw = _safe_float(row.get('S_SILT'))
    s_clay_raw = _safe_float(row.get('S_CLAY'))
    if s_sand_raw + s_silt_raw + s_clay_raw < 1.0:
        s_sand, s_silt, s_clay = t_sand, t_silt, t_clay
        s_oc = max(0.1, t_oc * 0.5)
        s_bd = t_bd + 0.05
        s_gravel = t_gravel
        s_caco3 = t_caco3
        s_ph = t_ph
    else:
        s_sand, s_silt, s_clay = normalize_texture(s_sand_raw, s_silt_raw, s_clay_raw)
        s_oc = _safe_float(row.get('S_OC'), max(0.1, t_oc * 0.5))
        s_bd = max(0.90, min(2.50, _safe_float(row.get('S_REF_BULK_DENSITY'), 1.45)))
        s_gravel = min(80.0, max(0.0, _safe_float(row.get('S_GRAVEL'), 0.0)))
        s_caco3 = min(50.0, max(0.0, _safe_float(row.get('S_CACO3'), 0.0)))
        s_ph = max(3.5, min(10.0, _safe_float(row.get('S_PH_H2O'), t_ph)))

    s_om = s_oc * 1.724

    t_ksat = cosby_ksat(t_sand, t_clay)
    s_ksat = cosby_ksat(s_sand, s_clay)
    hyd_grp = hydrologic_group(min(t_ksat, s_ksat))

    t_tex = classify_texture(t_sand, t_silt, t_clay)
    s_tex = classify_texture(s_sand, s_silt, s_clay)

    return {
        'name': name,
        'nly': 2,
        'hyd_grp': hyd_grp,
        'dp_tot': 1000.0,
        'anion_excl': 0.50,
        'perc_crk': 0.50,
        'texture': f"{t_tex}-{s_tex}",
        'layers': [
            {
                'dp': 300.0, 'bd': t_bd,
                'awc': saxton_rawls_awc(t_sand, t_clay, t_om),
                'soil_k': t_ksat, 'carbon': t_oc,
                'clay': t_clay, 'silt': t_silt, 'sand': t_sand,
                'rock': t_gravel,
                'alb': estimate_albedo(t_sand, t_clay, t_om),
                'usle_k': williams_usle_k(t_sand, t_silt, t_clay, t_om),
                'ec': 0.0, 'caco3': t_caco3, 'ph': t_ph,
            },
            {
                'dp': 1000.0, 'bd': s_bd,
                'awc': saxton_rawls_awc(s_sand, s_clay, s_om),
                'soil_k': s_ksat, 'carbon': s_oc,
                'clay': s_clay, 'silt': s_silt, 'sand': s_sand,
                'rock': s_gravel,
                'alb': estimate_albedo(s_sand, s_clay, s_om),
                'usle_k': williams_usle_k(s_sand, s_silt, s_clay, s_om),
                'ec': 0.0, 'caco3': s_caco3, 'ph': s_ph,
            },
        ],
    }


def _build_default_soil(name):
    """Build a default loam soil profile."""
    return {
        'name': name,
        'nly': 2,
        'hyd_grp': 'B',
        'dp_tot': 1000.0,
        'anion_excl': 0.50,
        'perc_crk': 0.50,
        'texture': 'L-L',
        'layers': [
            {
                'dp': 300.0, 'bd': 1.40, 'awc': 0.15, 'soil_k': 6.5,
                'carbon': 1.0, 'clay': 18.0, 'silt': 42.0, 'sand': 40.0,
                'rock': 0.0, 'alb': 0.13, 'usle_k': 0.30,
                'ec': 0.0, 'caco3': 0.0, 'ph': 6.5,
            },
            {
                'dp': 1000.0, 'bd': 1.50, 'awc': 0.12, 'soil_k': 3.5,
                'carbon': 0.5, 'clay': 22.0, 'silt': 40.0, 'sand': 38.0,
                'rock': 0.0, 'alb': 0.15, 'usle_k': 0.32,
                'ec': 0.0, 'caco3': 0.0, 'ph': 6.5,
            },
        ],
    }


# ===========================================================================
# Step 4: Slope classification
# ===========================================================================
def compute_slope_per_subbasin(subbasins_gdf, dem_path):
    """Compute mean slope (m/m) and elevation (m) per subbasin from DEM."""
    import rasterio
    from rasterstats import zonal_stats

    logger.info(f"Computing slope and elevation from DEM: {dem_path}")

    # Compute slope from DEM using numpy gradient
    with rasterio.open(dem_path) as src:
        dem_data = src.read(1).astype(float)
        nodata = src.nodata
        transform = src.transform
        cellsize_x = abs(transform.a)
        cellsize_y = abs(transform.e)

        if nodata is not None:
            dem_data[dem_data == nodata] = np.nan

        # Gradient in y and x directions
        # Convert cell size from degrees to approximate meters at mean latitude
        bounds = src.bounds
        mean_lat = (bounds.bottom + bounds.top) / 2.0
        m_per_deg_lat = 111320.0
        m_per_deg_lon = 111320.0 * math.cos(math.radians(mean_lat))
        dy = cellsize_y * m_per_deg_lat
        dx = cellsize_x * m_per_deg_lon

        grad_y, grad_x = np.gradient(dem_data, dy, dx)
        slope_array = np.sqrt(grad_x**2 + grad_y**2)

        # Write temporary slope raster
        import tempfile
        slope_tif = tempfile.NamedTemporaryFile(suffix='_slope.tif', delete=False)
        slope_tif_path = slope_tif.name
        slope_tif.close()

        profile = src.profile.copy()
        profile.update(dtype='float32', nodata=-9999.0)
        with rasterio.open(slope_tif_path, 'w', **profile) as dst:
            slope_out = slope_array.astype(np.float32)
            if nodata is not None:
                slope_out[np.isnan(dem_data)] = -9999.0
            dst.write(slope_out, 1)

    gdf_proj = subbasins_gdf.to_crs("EPSG:4326")

    # Mean slope per subbasin
    slope_stats = zonal_stats(
        gdf_proj, slope_tif_path,
        band=1, stats="mean", nodata=-9999.0,
        all_touched=True,
    )

    # Mean elevation per subbasin
    elev_stats = zonal_stats(
        gdf_proj, dem_path,
        band=1, stats="mean", nodata=nodata,
        all_touched=True,
    )

    slopes = []
    elevations = []
    for ss, es in zip(slope_stats, elev_stats):
        slp = ss.get("mean", 0.05)
        if slp is None or np.isnan(slp):
            slp = 0.05
        slp = max(0.001, min(1.0, slp))
        slopes.append(slp)

        elev = es.get("mean", 100.0)
        if elev is None or np.isnan(elev):
            elev = 100.0
        elevations.append(elev)

    # Clean up temp file
    try:
        os.unlink(slope_tif_path)
    except OSError:
        pass

    logger.info(f"  Slope range: {min(slopes):.4f} - {max(slopes):.4f} m/m")
    logger.info(f"  Elevation range: {min(elevations):.0f} - {max(elevations):.0f} m")
    return slopes, elevations


def classify_slope(slope_m_m, slope_classes):
    """Classify a slope value (m/m) into a slope class index."""
    slope_pct = slope_m_m * 100.0
    for i, (lo, hi) in enumerate(slope_classes):
        if lo <= slope_pct < hi:
            return i
    return len(slope_classes) - 1


# ===========================================================================
# Step 5: Generate HRUs
# ===========================================================================
def generate_hrus(subbasins_gdf, lc_fractions, soil_names, slopes, elevations,
                  slope_classes, hru_threshold):
    """Generate HRU list from subbasin x landuse x soil x slope overlay.

    Returns list of HRU dicts and updated subbasins_gdf with HRU counts.
    """
    logger.info("Generating HRUs from overlay...")
    hrus = []
    hru_id = 1

    for sub_idx in range(len(subbasins_gdf)):
        sub_row = subbasins_gdf.iloc[sub_idx]
        sub_id = sub_row['sub_id']
        sub_area = sub_row['area_ha']
        sub_lat = sub_row['lat']
        sub_lon = sub_row['lon']
        sub_elev = elevations[sub_idx]
        sub_slope = slopes[sub_idx]
        sub_soil = soil_names[sub_idx]
        lc_frac = lc_fractions[sub_idx]

        # Slope class for entire subbasin (single value from DEM mean)
        slope_cls = classify_slope(sub_slope, slope_classes)
        slope_name = f"slp{slope_classes[slope_cls][0]:.0f}_{slope_classes[slope_cls][1]:.0f}"

        # Build candidate HRUs: one per land-use class that exceeds threshold
        candidates = []
        for lc_code, frac in sorted(lc_frac.items(), key=lambda x: -x[1]):
            if frac < hru_threshold and candidates:
                continue  # Skip small fractions (redistribute below)
            swat_info = UMD_TO_SWAT.get(lc_code, UMD_TO_SWAT[10])
            candidates.append({
                'lc_code': lc_code,
                'plant': swat_info['plant'],
                'lum': swat_info['lum'],
                'frac': frac,
            })

        if not candidates:
            # Fallback: use dominant
            dominant = max(lc_frac.items(), key=lambda x: x[1])
            swat_info = UMD_TO_SWAT.get(dominant[0], UMD_TO_SWAT[10])
            candidates = [{
                'lc_code': dominant[0],
                'plant': swat_info['plant'],
                'lum': swat_info['lum'],
                'frac': 1.0,
            }]

        # Normalize fractions to sum to 1.0
        total_frac = sum(c['frac'] for c in candidates)
        if total_frac > 0:
            for c in candidates:
                c['frac'] /= total_frac

        # Create HRU for each candidate
        for cand in candidates:
            hru_area = sub_area * cand['frac']
            if hru_area < 0.01:
                continue  # Skip tiny HRUs

            hrus.append({
                'id': hru_id,
                'name': f"hru{hru_id:06d}",
                'sub_id': sub_id,
                'area_ha': hru_area,
                'lat': sub_lat,
                'lon': sub_lon,
                'elev': sub_elev,
                'slope': sub_slope,
                'slope_cls': slope_cls,
                'slope_name': slope_name,
                'soil_name': sub_soil,
                'lc_code': cand['lc_code'],
                'plant': cand['plant'],
                'lum': cand['lum'],
                'frac_of_sub': cand['frac'],
            })
            hru_id += 1

    logger.info(f"  Generated {len(hrus)} HRUs across {len(subbasins_gdf)} subbasins")

    # Land use distribution
    lu_dist = Counter(h['plant'] for h in hrus)
    for plant, cnt in sorted(lu_dist.items(), key=lambda x: -x[1]):
        logger.info(f"    {plant}: {cnt} HRUs")

    return hrus


# ===========================================================================
# Step 6: Write SWAT+ TxtInOut files
# ===========================================================================
def resolve_dem_path(dem_path, basin_shp):
    """Resolve 'auto' DEM path based on basin location."""
    if dem_path != "auto":
        return dem_path

    import geopandas as gpd
    basin_gdf = gpd.read_file(basin_shp).to_crs("EPSG:4326")
    centroid = basin_gdf.geometry.unary_union.centroid
    lat, lon = centroid.y, centroid.x

    # Check if in China (rough bounds)
    if 18 <= lat <= 54 and 73 <= lon <= 135:
        if DEFAULT_DEM_CHINA.exists():
            logger.info(f"  Auto-selected China DEM (basin centroid at {lat:.1f}N, {lon:.1f}E)")
            return str(DEFAULT_DEM_CHINA)

    # Try to find SRTM tiles
    srtm_dir = Path("/mnt/disk4/SRTMGL1")
    if srtm_dir.exists():
        logger.info(f"  Auto-selected SRTM DEM (basin centroid at {lat:.1f}N, {lon:.1f}E)")
        return str(srtm_dir)

    # Fallback: use China DEM even if outside (will have nodata -- user should provide)
    if DEFAULT_DEM_CHINA.exists():
        logger.warning("  No suitable DEM found for location, falling back to China DEM")
        return str(DEFAULT_DEM_CHINA)

    raise FileNotFoundError("No DEM available. Please specify --dem_path explicitly.")


def clip_dem_to_basin(dem_path, basin_shp, output_dir):
    """Clip DEM to basin extent + buffer for slope computation."""
    import rasterio
    from rasterio.mask import mask as rio_mask
    import geopandas as gpd

    logger.info("Clipping DEM to basin extent...")
    basin_gdf = gpd.read_file(basin_shp).to_crs("EPSG:4326")
    # Buffer by ~0.1 degrees for edge effects
    buffered = basin_gdf.geometry.buffer(0.1).unary_union

    with rasterio.open(dem_path) as src:
        # Check if DEM covers the basin
        from shapely.geometry import box as shp_box
        dem_bounds = shp_box(*src.bounds)
        if not dem_bounds.intersects(buffered):
            raise ValueError(
                f"DEM does not cover basin. DEM bounds: {src.bounds}, "
                f"Basin bounds: {basin_gdf.total_bounds}"
            )

        out_image, out_transform = rio_mask(
            src, [buffered.__geo_interface__],
            crop=True, all_touched=True, nodata=src.nodata
        )
        out_meta = src.meta.copy()
        out_meta.update({
            "driver": "GTiff",
            "height": out_image.shape[1],
            "width": out_image.shape[2],
            "transform": out_transform,
        })

    clipped_path = Path(output_dir) / "dem_clipped.tif"
    with rasterio.open(str(clipped_path), "w", **out_meta) as dst:
        dst.write(out_image)

    logger.info(f"  Clipped DEM: {out_image.shape[2]}x{out_image.shape[1]} pixels")
    return str(clipped_path)


# ---------------------------------------------------------------------------
# Write soils.sol
# ---------------------------------------------------------------------------
def write_soils_sol(soil_profiles, output_path):
    """Write soils.sol in SWAT+ editor format."""
    PNW = 32   # profile name width
    NW = 14    # numeric width
    HW = 18    # hyd_grp width
    INDENT = 98
    FW = 14

    with open(output_path, 'w') as f:
        f.write("soils.sol: written by SWAT+ HRU generator (HydroCraft)\n")

        hdr = (f"{'name':<{PNW}}"
               f"{'nly':>{NW}}"
               f"{'hyd_grp':>{HW}}"
               f"{'dp_tot':>{NW}}"
               f"{'anion_excl':>{NW}}"
               f"{'perc_crk':>{NW}}")
        pad = max(2, INDENT - len(hdr))
        lcols = ['dp', 'bd', 'awc', 'soil_k', 'carbon',
                 'clay', 'silt', 'sand', 'rock', 'alb', 'usle_k',
                 'ec', 'caco3', 'ph']
        f.write(hdr + " " * pad + "texture" + " " * 25
                + "".join(f"{c:>{FW}}" for c in lcols) + "  \n")

        for prof in soil_profiles.values():
            line = (f"{prof['name']:<{PNW}}"
                    f"{prof['nly']:>{NW}d}"
                    f"{prof['hyd_grp']:>{HW}}"
                    f"{prof['dp_tot']:>{NW}.5f}"
                    f"{prof['anion_excl']:>{NW}.5f}"
                    f"{prof['perc_crk']:>{NW}.5f}"
                    f"  {prof['texture']:<27}")
            f.write(line + "\n")

            for layer in prof['layers']:
                vals = [layer['dp'], layer['bd'], layer['awc'], layer['soil_k'],
                        layer['carbon'], layer['clay'], layer['silt'], layer['sand'],
                        layer['rock'], layer['alb'], layer['usle_k'],
                        layer['ec'], layer['caco3'], layer['ph']]
                f.write(" " * INDENT + "".join(f"{v:>{FW}.5f}" for v in vals) + "  \n")

    logger.info(f"Wrote soils.sol: {len(soil_profiles)} profiles")


# ---------------------------------------------------------------------------
# Write hru.con
# ---------------------------------------------------------------------------
def write_hru_con(hrus, n_subbasins, output_path):
    """Write hru.con -- HRU connectivity file."""
    CW = 12  # column width for numbers
    NW = 20  # name width

    with open(output_path, 'w') as f:
        f.write("hru.con: written by SWAT+ HRU generator (HydroCraft)\n")
        f.write(f"{'id':>{CW-6}}  {'name':<{NW}}"
                f"{'gis_id':>{CW}}"
                f"{'area':>{CW}}"
                f"{'lat':>{CW}}"
                f"{'lon':>{CW}}"
                f"{'elev':>{CW}}"
                f"{'hru':>{CW-3}}"
                f"{'wst':>{CW+4}}"
                f"{'cst':>{CW-3}}"
                f"{'ovfl':>{CW-3}}"
                f"{'rule':>{CW-3}}"
                f"{'out_tot':>{CW-2}}  \n")

        for h in hrus:
            sta_name = f"sta{((h['sub_id']-1) % n_subbasins) + 1:02d}"
            f.write(f"{h['id']:>8}  {h['name']:<{NW}}"
                    f"{h['id']:>{CW}}"
                    f"{h['area_ha']:>{CW}.2f}"
                    f"{h['lat']:>{CW}.5f}"
                    f"{h['lon']:>{CW}.5f}"
                    f"{h['elev']:>{CW}.3f}"
                    f"{h['id']:>{CW-3}}"
                    f"{sta_name:>{CW+4}}"
                    f"{'0':>{CW-3}}"
                    f"{'0':>{CW-3}}"
                    f"{'0':>{CW-3}}"
                    f"{'0':>{CW-2}}  \n")

    logger.info(f"Wrote hru.con: {len(hrus)} HRUs")


# ---------------------------------------------------------------------------
# Write hru-data.hru
# ---------------------------------------------------------------------------
def write_hru_data(hrus, output_path):
    """Write hru-data.hru -- HRU property references."""
    NW = 20

    with open(output_path, 'w') as f:
        f.write("hru-data.hru: written by SWAT+ HRU generator (HydroCraft)\n")
        f.write(f"{'id':>8}  {'name':<{NW}}"
                f"{'topo':>{NW}}"
                f"{'hydro':>{NW}}"
                f"{'soil':>{NW}}"
                f"{'lu_mgt':>{NW}}"
                f"{'soil_plant_init':>{NW}}"
                f"{'surf_stor':>{NW}}"
                f"{'snow':>{NW}}"
                f"{'field':>{NW}}  \n")

        for h in hrus:
            topo_name = f"topo{h['id']:06d}"
            soil_name = h['soil_name']
            lum_name = h['lum']
            f.write(f"{h['id']:>8}  {h['name']:<{NW}}"
                    f"{topo_name:>{NW}}"
                    f"{'hyd1':>{NW}}"
                    f"{soil_name:>{NW}}"
                    f"{lum_name:>{NW}}"
                    f"{'soilnut1':>{NW}}"
                    f"{'null':>{NW}}"
                    f"{'snow001':>{NW}}"
                    f"{'null':>{NW}}  \n")

    logger.info(f"Wrote hru-data.hru: {len(hrus)} entries")


# ---------------------------------------------------------------------------
# Write topography.hyd
# ---------------------------------------------------------------------------
def write_topography_hyd(hrus, output_path):
    """Write topography.hyd -- slope and slope length per HRU."""
    NW = 20

    with open(output_path, 'w') as f:
        f.write("topography.hyd: written by SWAT+ HRU generator (HydroCraft)\n")
        f.write(f"{'name':<{NW}}"
                f"{'slp':>{14}}"
                f"{'slp_len':>{14}}"
                f"{'lat_len':>{14}}"
                f"{'dist_cha':>{14}}"
                f"{'depos':>{14}}  \n")

        for h in hrus:
            topo_name = f"topo{h['id']:06d}"
            slp = h['slope']
            # Slope length estimation from slope (USLE formula)
            slp_len = max(10.0, min(150.0, 50.0 / (slp + 0.01)))
            f.write(f"{topo_name:<{NW}}"
                    f"{slp:>14.5f}"
                    f"{slp_len:>14.5f}"
                    f"{slp_len:>14.5f}"
                    f"{100.0:>14.5f}"
                    f"{1.0:>14.5f}  \n")

    logger.info(f"Wrote topography.hyd: {len(hrus)} entries")


# ---------------------------------------------------------------------------
# Write rout_unit.con, rout_unit.def, rout_unit.ele, rout_unit.rtu
# ---------------------------------------------------------------------------
def write_routing_units(subbasins_gdf, hrus, n_subbasins, output_dir):
    """Write all routing unit files."""
    # Group HRUs by subbasin
    hrus_by_sub = defaultdict(list)
    for h in hrus:
        hrus_by_sub[h['sub_id']].append(h)

    sub_ids = sorted(hrus_by_sub.keys())
    n_subs = len(sub_ids)

    # ---- rout_unit.con ----
    CW = 12
    with open(Path(output_dir) / "rout_unit.con", 'w') as f:
        f.write("rout_unit.con: written by SWAT+ HRU generator (HydroCraft)\n")
        f.write(f"{'id':>8}  {'name':<20}"
                f"{'gis_id':>{CW}}"
                f"{'area':>{CW}}"
                f"{'lat':>{CW}}"
                f"{'lon':>{CW}}"
                f"{'elev':>{CW}}"
                f"{'rtu':>8}"
                f"{'wst':>16}"
                f"{'cst':>8}"
                f"{'ovfl':>8}"
                f"{'rule':>8}"
                f"{'out_tot':>10}"
                f"{'obj_typ':>12}"
                f"{'obj_id':>10}"
                f"{'hyd_typ':>12}"
                f"{'frac':>14}"
                f"{'obj_typ':>12}"
                f"{'obj_id':>10}"
                f"{'hyd_typ':>12}"
                f"{'frac':>14}  \n")

        for idx, sub_id in enumerate(sub_ids):
            sub_hrus = hrus_by_sub[sub_id]
            sub_area = sum(h['area_ha'] for h in sub_hrus)
            sub_lat = sub_hrus[0]['lat']
            sub_lon = sub_hrus[0]['lon']
            sub_elev = sub_hrus[0]['elev']
            rtu_name = f"rtu{sub_id:04d}"
            sta_name = f"sta{((sub_id-1) % n_subbasins) + 1:02d}"

            # Routing (SWAT+ Editor convention, verified against the test_lrew
            # and test_osu decks written by SWAT+ Editor v2.1.0 / v2.2.0):
            #   cha <id> tot 1.00000   -> the FULL surface+lateral hydrograph
            #   aqu <id> rhg 1.00000   -> the RECHARGE (percolation) hydrograph
            # Surface-water outflow fractions must sum to 1.0. Sending `tot` to
            # the aquifer makes it re-release the same surq+latq the channel
            # already received (mass creation, ~1.7x at the outlet) and orphans
            # soil percolation, which then never recharges any aquifer.
            # The rev59-era demo uses cha 0.70 only because a reservoir takes
            # the other 0.30; this tool emits no reservoir.
            # Last subbasin is outlet (channel 1), others chain
            out_cha_id = min(idx + 1, n_subs)

            f.write(f"{idx+1:>8}  {rtu_name:<20}"
                    f"{sub_id:>{CW}}"
                    f"{sub_area:>{CW}.2f}"
                    f"{sub_lat:>{CW}.5f}"
                    f"{sub_lon:>{CW}.5f}"
                    f"{sub_elev:>{CW}.3f}"
                    f"{idx+1:>8}"
                    f"{sta_name:>16}"
                    f"{'0':>8}"
                    f"{'0':>8}"
                    f"{'0':>8}"
                    f"{'2':>10}"
                    f"{'cha':>12}"
                    f"{out_cha_id:>10}"
                    f"{'tot':>12}"
                    f"{1.0:>14.5f}"
                    f"{'aqu':>12}"
                    f"{idx+1:>10}"
                    f"{'rhg':>12}"
                    f"{1.0:>14.5f}  \n")

    # ---- rout_unit.def ----
    with open(Path(output_dir) / "rout_unit.def", 'w') as f:
        f.write("rout_unit.def: written by SWAT+ HRU generator (HydroCraft)\n")
        f.write(f"{'id':>8}{'name':>16}{'elem_tot':>10}{'elem1':>10}{'elem2':>10}  \n")

        for idx, sub_id in enumerate(sub_ids):
            sub_hrus = hrus_by_sub[sub_id]
            rtu_name = f"rtu{sub_id:04d}"
            first_hru = sub_hrus[0]['id']
            last_hru = sub_hrus[-1]['id']
            f.write(f"{idx+1:>8}"
                    f"{rtu_name:>16}"
                    f"{2:>10}"
                    f"{first_hru:>10}"
                    f"{-last_hru:>10}  \n")

    # ---- rout_unit.ele ----
    total_area = sum(h['area_ha'] for h in hrus)
    with open(Path(output_dir) / "rout_unit.ele", 'w') as f:
        f.write("rout_unit.ele: written by SWAT+ HRU generator (HydroCraft)\n")
        f.write(f"{'id':>8}  {'name':<20}{'obj_typ':>10}"
                f"{'obj_id':>10}{'frac':>16}{'dlr':>18}  \n")

        for h in hrus:
            sub_id = h['sub_id']
            sub_area = sum(hh['area_ha'] for hh in hrus_by_sub[sub_id])
            frac = h['area_ha'] / sub_area if sub_area > 0 else 0.0
            f.write(f"{h['id']:>8}  {h['name']:<20}{'hru':>10}"
                    f"{h['id']:>10}"
                    f"{frac:>16.5f}"
                    f"{0:>18}  \n")

    # ---- rout_unit.rtu ----
    with open(Path(output_dir) / "rout_unit.rtu", 'w') as f:
        f.write("rout_unit.rtu: written by SWAT+ HRU generator (HydroCraft)\n")
        f.write(f"{'id':>8}{'name':>16}{'define':>18}{'dlr':>18}"
                f"{'topo':>18}{'field':>18}  \n")

        for idx, sub_id in enumerate(sub_ids):
            rtu_name = f"rtu{sub_id:04d}"
            topo_name = f"topo_rtu{sub_id:04d}"
            fld_name = f"fld{sub_id:04d}"
            f.write(f"{idx+1:>8}"
                    f"{rtu_name:>16}"
                    f"{rtu_name:>18}"
                    f"{'null':>18}"
                    f"{topo_name:>18}"
                    f"{fld_name:>18}  \n")

    logger.info(f"Wrote routing unit files: {n_subs} RTUs")


# ---------------------------------------------------------------------------
# Channel topology (from tools/s1/build_channel_topology.py)
# ---------------------------------------------------------------------------
def load_channel_topology(topology_path, sub_ids):
    """Load the flow-network-derived channel cascade.

    FALLBACK DISCIPLINE (do not loosen): the legacy star is permitted for exactly
    ONE case -- no topology was requested at all (--channel_topology empty). In
    that case this returns None and the caller emits warn_star_fallback().

    If a topology WAS supplied but is missing, unparseable, mismatched or
    otherwise invalid, this is a hard failure (sys.exit(2)). Silently degrading a
    broken-but-supplied topology to the star is how a run that the operator
    believed was routed gets scored as a lumped water-yield proxy -- exactly the
    failure this whole tool exists to prevent. An explicit request for a routed
    deck must never be answered with an unrouted one.
    """
    if not topology_path:
        return None

    def fatal(msg, *fmt):
        logger.error(msg, *fmt)
        logger.error("A channel topology WAS supplied (%s), so this is fatal: "
                     "refusing to silently fall back to the legacy star. Rebuild "
                     "it with tools/s1/build_channel_topology.py from the SAME "
                     "subbasin partition, or omit --channel_topology if you "
                     "knowingly want an unrouted lumped-proxy deck.", topology_path)
        sys.exit(2)

    p = Path(topology_path)
    if not p.exists():
        fatal("Channel topology file not found: %s", p)
    try:
        raw = json.loads(p.read_text())
    except Exception as e:
        fatal("Could not parse channel topology %s: %s", p, e)

    meta = raw.pop("_meta", {})
    topo = {}
    for k, v in raw.items():
        try:
            topo[int(k)] = v
        except (TypeError, ValueError):
            continue

    n_ch = len(sub_ids)
    if len(topo) != n_ch:
        fatal("Channel topology has %d channels but the HRU set has %d subbasins.",
              len(topo), n_ch)

    expected = set(range(1, n_ch + 1))
    if set(topo.keys()) != expected:
        fatal("Channel topology keys are not exactly 1..%d (got %s).",
              n_ch, sorted(topo.keys()))

    # ---- sub_id alignment ------------------------------------------------
    # Channel ids are POSITIONAL: this writer emits cha{idx+1} for sub_ids[idx].
    # A topology with the right channel COUNT but a different sub_id ordering
    # would bind each channel's connectivity and accumulated area to the wrong
    # subbasin's HRUs -- silently, since every count check still passes. Verify
    # the actual identity, not just the cardinality.
    misaligned = []
    for idx, sid in enumerate(sub_ids):
        topo_sid = topo[idx + 1].get("sub_id")
        if topo_sid is None:
            fatal("Channel topology entry cha%d has no 'sub_id' field; cannot "
                  "verify alignment with the HRU subbasin ordering.", idx + 1)
        if int(topo_sid) != int(sid):
            misaligned.append((idx + 1, int(topo_sid), int(sid)))
    if misaligned:
        preview = ", ".join(f"cha{c}: topology sub_id={t} vs HRU sub_id={h}"
                            for c, t, h in misaligned[:5])
        fatal("Channel topology sub_id ordering does not match the HRU subbasin "
              "ordering for %d of %d channels (%s%s). The topology was built from "
              "a DIFFERENT subbasin partition or a different sort order; using it "
              "would bind channels to the wrong HRUs.",
              len(misaligned), n_ch, preview,
              ", ..." if len(misaligned) > 5 else "")

    terminals = [cid for cid, v in topo.items() if v.get("downstream_id") is None]
    if len(terminals) != 1:
        fatal("Channel topology has %d terminal channels (%s); exactly one is "
              "required (s9/extract_discharge auto-detects the scored outlet as "
              "the channel with out_tot==0).", len(terminals), terminals)

    logger.info("Loaded channel topology: %d channels, outlet=cha%d, "
                "max Strahler order=%s, sub_id alignment verified for all %d "
                "channels", len(topo), terminals[0],
                meta.get("max_strahler_order", "?"), n_ch)
    return topo


def warn_star_fallback(context):
    """Loud, unmissable warning that the deck is NOT a routed network."""
    logger.warning("=" * 78)
    logger.warning("WARNING: no channel topology supplied -- falling back to the "
                   "LEGACY STAR for %s.", context)
    logger.warning("WARNING: every channel will discharge directly into cha1. "
                   "SWAT+ ChannelRouting will NOT execute as a cascade: there is "
                   "no travel-time lag and no floodplain attenuation.")
    logger.warning("WARNING: the resulting outlet series is a LUMPED BASIN WATER "
                   "YIELD PROXY, not a routed hydrograph. Any NSE/KGE computed "
                   "from it is NOT a model verdict.")
    logger.warning("WARNING: build a real cascade with "
                   "tools/s1/build_channel_topology.py and pass "
                   "--channel_topology.")
    logger.warning("=" * 78)


# ---------------------------------------------------------------------------
# Write channel files
# ---------------------------------------------------------------------------
def write_channel_files(subbasins_gdf, hrus, output_dir, channel_topology=None):
    """Write channel.con, channel.cha, hydrology.cha, sediment.cha, nutrients.cha."""
    hrus_by_sub = defaultdict(list)
    for h in hrus:
        hrus_by_sub[h['sub_id']].append(h)

    sub_ids = sorted(hrus_by_sub.keys())
    n_ch = len(sub_ids)

    topo = load_channel_topology(channel_topology, sub_ids)
    if topo is None:
        warn_star_fallback("channel.con connectivity and hydrology.cha geometry")

    # ---- channel.con ----
    CW = 12
    with open(Path(output_dir) / "channel.con", 'w') as f:
        f.write("channel.con: written by SWAT+ HRU generator (HydroCraft)\n")
        f.write(f"{'id':>8}  {'name':<20}"
                f"{'gis_id':>{CW}}{'area':>{CW}}{'lat':>{CW}}{'lon':>{CW}}"
                f"{'elev':>{CW}}{'cha':>8}{'wst':>16}"
                f"{'cst':>8}{'ovfl':>8}{'rule':>8}{'out_tot':>10}"
                f"{'obj_typ':>12}{'obj_id':>10}{'hyd_typ':>12}{'frac':>14}  \n")

        for idx, sub_id in enumerate(sub_ids):
            sub_hrus = hrus_by_sub[sub_id]
            total_area = sum(h['area_ha'] for h in hrus)
            sub_area_tot = sum(h['area_ha'] for h in sub_hrus)
            # Upstream area accumulated along the FLOW NETWORK. The legacy
            # fallback below sums in sorted-subbasin-id order, which is not a
            # network accumulation at all and hands the terminal channel the
            # smallest area in the basin.
            if topo is not None:
                cum_area = topo[idx + 1]['upstream_accumulated_area_ha']
            else:
                cum_area = sum(
                    sum(h2['area_ha'] for h2 in hrus_by_sub[sid])
                    for sid in sub_ids[:idx+1]
                )
            cha_name = f"cha{idx+1}"
            sub_lat = sub_hrus[0]['lat']
            sub_lon = sub_hrus[0]['lon']
            sta_name = f"sta{((sub_id-1) % n_ch) + 1:02d}"

            # Downstream target from the flow network. Exactly one channel (the
            # true terminal) carries out_tot=0; every other channel routes to its
            # network-derived downstream neighbour, NOT to a hardcoded cha1.
            if topo is not None:
                ds_id = topo[idx + 1]['downstream_id']
                if ds_id is None:
                    out_tot = 0
                    obj_typ, obj_id, hyd_typ, frac = "null", 0, "null", 0.0
                else:
                    out_tot = 1
                    obj_typ, obj_id, hyd_typ, frac = "cha", int(ds_id), "tot", 1.0
            else:
                # LEGACY STAR FALLBACK -- lumped water-yield proxy. See
                # warn_star_fallback() above.
                if idx == 0:
                    out_tot = 0
                    obj_typ, obj_id, hyd_typ, frac = "null", 0, "null", 0.0
                else:
                    out_tot = 1
                    obj_typ, obj_id, hyd_typ, frac = "cha", 1, "tot", 1.0

            f.write(f"{idx+1:>8}  {cha_name:<20}"
                    f"{idx+1:>{CW}}"
                    f"{cum_area:>{CW}.2f}"
                    f"{sub_lat:>{CW}.5f}"
                    f"{sub_lon:>{CW}.5f}"
                    f"{0:>{CW}}"
                    f"{idx+1:>8}"
                    f"{sta_name:>16}"
                    f"{'0':>8}{'0':>8}{'0':>8}"
                    f"{out_tot:>10}"
                    f"{obj_typ:>12}"
                    f"{obj_id:>10}"
                    f"{hyd_typ:>12}"
                    f"{frac:>14.5f}  \n")

    # ---- channel.cha ----
    with open(Path(output_dir) / "channel.cha", 'w') as f:
        f.write("channel.cha: written by SWAT+ HRU generator (HydroCraft)\n")
        f.write(f"{'id':>8}  {'name':<20}"
                f"{'cha_ini':>16}{'cha_hyd':>16}{'cha_sed':>16}"
                f"{'cha_nut':>16}{'cha_pst':>16}"
                f"{'cha_ls_lnk':>16}{'cha_aqu_lnk':>16}  \n")
        for idx in range(n_ch):
            # Bind each channel to its OWN hydrology.cha row. Pointing every
            # channel at 'hydcha1' would make the per-channel hydraulic geometry
            # written below completely inert.
            f.write(f"{idx+1:>8}  {f'cha{idx+1}':<20}"
                    f"{'initcha1':>16}{f'hydcha{idx+1}':>16}{'sedcha1':>16}"
                    f"{'nutcha1':>16}{'pestcha1':>16}"
                    f"{0:>16}{0:>16}  \n")

    # ---- hydrology.cha ----
    with open(Path(output_dir) / "hydrology.cha", 'w') as f:
        f.write("hydrology.cha: written by SWAT+ HRU generator (HydroCraft)\n")
        f.write(f"{'name':<20}{'wd':>14}{'dp':>14}{'slp':>14}"
                f"{'len':>14}{'mann':>14}{'k':>14}"
                f"{'wdr':>14}{'alpha_bnk':>14}{'side_slp':>14}  description\n")
        for idx, sub_id in enumerate(sub_ids):
            sub_hrus = hrus_by_sub[sub_id]
            # Channel hydraulic geometry must be sized from the area the channel
            # actually CONVEYS (network-accumulated), not from the local subbasin
            # area -- otherwise no channel can ever be sized as a mainstem and the
            # outlet is a rivulet asked to carry the whole basin.
            if topo is not None:
                geom_area_km2 = topo[idx + 1]['upstream_accumulated_area_ha'] / 100.0
            else:
                geom_area_km2 = sum(h['area_ha'] for h in sub_hrus) / 100.0
            sub_area_km2 = geom_area_km2
            # Empirical channel geometry from drainage area
            wd = max(1.0, 2.71 * (sub_area_km2 ** 0.557))
            dp = max(0.1, 0.349 * (sub_area_km2 ** 0.341))
            mean_slp = np.mean([h['slope'] for h in sub_hrus])
            if topo is not None:
                ch_len = max(0.5, float(topo[idx + 1]['length_km']))
                ch_slp = max(0.0001, float(topo[idx + 1]['slope']))
            else:
                ch_len = max(0.5, math.sqrt(sub_area_km2) * 1.3)  # km
                ch_slp = max(0.0001, mean_slp * 0.5)
            wdr = max(3.0, wd / dp if dp > 0 else 10.0)

            f.write(f"{f'hydcha{idx+1}':<20}"
                    f"{wd:>14.5f}{dp:>14.5f}{ch_slp:>14.5f}"
                    f"{ch_len:>14.5f}{0.05:>14.5f}{0.0:>14.5f}"
                    f"{wdr:>14.5f}{0.0:>14.5f}{0.0:>14.5f}  \n")

    # ---- sediment.cha ----
    with open(Path(output_dir) / "sediment.cha", 'w') as f:
        f.write("sediment.cha: written by SWAT+ HRU generator (HydroCraft)\n")
        f.write(f"{'name':<20}{'sed_eqn':>10}{'erod_fact':>14}{'cov_fact':>14}"
                f"{'bd_bnk':>14}{'bd_bed':>14}{'kd_bnk':>14}{'kd_bed':>14}"
                f"{'d50_bnk':>14}{'d50_bed':>14}{'css_bnk':>14}{'css_bed':>14}"
                + "".join(f"{'erod'+str(i):>14}" for i in range(1, 13))
                + "  description\n")
        f.write(f"{'sedcha1':<20}"
                f"{0:>10}{0.0:>14.5f}{0.0:>14.5f}"
                f"{1.4:>14.5f}{1.5:>14.5f}{0.001:>14.5f}{0.001:>14.5f}"
                f"{50.0:>14.5f}{500.0:>14.5f}{0.0:>14.5f}{0.0:>14.5f}"
                + "".join(f"{0.0:>14.5f}" for _ in range(12))
                + "\n")

    # ---- nutrients.cha ----
    with open(Path(output_dir) / "nutrients.cha", 'w') as f:
        f.write("nutrients.cha: written by SWAT+ HRU generator (HydroCraft)\n")
        cols = ['plt_n', 'ptl_p', 'alg_stl', 'ben_disp', 'ben_nh3n',
                'ptln_stl', 'ptlp_stl', 'cst_stl', 'ben_cst', 'cbn_bod_co',
                'air_rt', 'cbn_bod_stl', 'ben_bod', 'bact_die', 'cst_decay',
                'nh3n_no2n', 'no2n_no3n', 'ptln_nh3n', 'ptlp_solp',
                'q2e_lt', 'q2e_alg', 'chla_alg', 'alg_n', 'alg_p',
                'alg_o2_prod', 'alg_o2_resp', 'o2_nh3n', 'o2_no2n',
                'alg_grow', 'alg_resp', 'slr_act', 'lt_co', 'const_n',
                'const_p', 'lt_nonalg', 'alg_shd_l', 'alg_shd_nl',
                'nh3_pref']
        f.write(f"{'name':<20}" + "".join(f"{c:>14}" for c in cols) + "  description\n")
        vals = [0, 0, 1, 0.05, 0.5, 0.05, 0.05, 2.5, 2.5, 1.71,
                50, 0.36, 2, 2, 1.71, 0.55, 1.1, 0.21, 0.35,
                2, 2, 50, 0.08, 0.015, 1.6, 2.0, 3.5, 1.07,
                2.0, 2.5, 0.3, 0.75, 0.02, 0.025, 1.0, 0.03, 0.054, 0.5]
        f.write(f"{'nutcha1':<20}" + "".join(f"{v:>14.5f}" for v in vals) + "\n")

    logger.info(f"Wrote channel files: {n_ch} channels")


# ---------------------------------------------------------------------------
# Write aquifer files
# ---------------------------------------------------------------------------
def write_aquifer_files(subbasins_gdf, hrus, output_dir):
    """Write aquifer.con and aquifer.aqu."""
    hrus_by_sub = defaultdict(list)
    for h in hrus:
        hrus_by_sub[h['sub_id']].append(h)
    sub_ids = sorted(hrus_by_sub.keys())
    n_aqu = len(sub_ids)

    # ---- aquifer.con ----
    CW = 12
    with open(Path(output_dir) / "aquifer.con", 'w') as f:
        f.write("aquifer.con: written by SWAT+ HRU generator (HydroCraft)\n")
        f.write(f"{'id':>8}  {'name':<20}"
                f"{'gis_id':>{CW}}{'area':>{CW}}{'lat':>{CW}}{'lon':>{CW}}"
                f"{'elev':>{CW}}{'aqu':>8}{'wst':>16}"
                f"{'cst':>8}{'ovfl':>8}{'rule':>8}{'out_tot':>10}"
                f"{'obj_typ':>12}{'obj_id':>10}{'hyd_typ':>12}{'frac':>14}  \n")

        for idx, sub_id in enumerate(sub_ids):
            sub_hrus = hrus_by_sub[sub_id]
            sub_area = sum(h['area_ha'] for h in sub_hrus)
            sub_lat = sub_hrus[0]['lat']
            sub_lon = sub_hrus[0]['lon']
            sub_elev = sub_hrus[0]['elev'] * 0.9  # aquifer slightly below surface
            sta_name = f"sta{((sub_id-1) % n_aqu) + 1:02d}"

            f.write(f"{idx+1:>8}  {f'aqu{idx+1}':<20}"
                    f"{idx+1:>{CW}}"
                    f"{sub_area:>{CW}.2f}"
                    f"{sub_lat:>{CW}.5f}"
                    f"{sub_lon:>{CW}.5f}"
                    f"{sub_elev:>{CW}.3f}"
                    f"{idx+1:>8}"
                    f"{sta_name:>16}"
                    f"{'0':>8}{'0':>8}{'0':>8}"
                    f"{'1':>10}"
                    f"{'cha':>12}"
                    f"{idx+1:>10}"
                    f"{'tot':>12}"
                    f"{1.0:>14.5f}  \n")

    # ---- aquifer.aqu ----
    with open(Path(output_dir) / "aquifer.aqu", 'w') as f:
        f.write("aquifer.aqu: written by SWAT+ HRU generator (HydroCraft)\n")
        f.write(f"{'id':>8}  {'name':<12}{'aqu_init':>12}"
                f"{'gw_flo':>14}{'gw_dp':>14}{'gw_ht':>14}"
                f"{'no3_n':>14}{'sol_p':>14}{'ptl_n':>14}{'ptl_p':>14}"
                f"{'bf_max':>14}{'alpha_bf':>14}{'revap_co':>14}"
                f"{'rchg_dp':>14}{'spec_yld':>14}{'hl_no3n':>14}"
                f"{'flo_min':>14}{'revap_min':>14}  \n")

        for idx in range(n_aqu):
            f.write(f"{idx+1:>8}  {f'aqu{idx+1}':<12}{'low_init':>12}"
                    f"{2500.0:>14.5f}{1000.0:>14.5f}{1.0:>14.5f}"
                    f"{0.0:>14.5f}{0.0:>14.5f}{0.0:>14.5f}{0.0:>14.5f}"
                    f"{1.0:>14.5f}{0.05:>14.5f}{0.02:>14.5f}"
                    f"{0.05:>14.5f}{0.05:>14.5f}{0.0:>14.5f}"
                    f"{1000.0:>14.5f}{750.0:>14.5f}  \n")

    logger.info(f"Wrote aquifer files: {n_aqu} aquifers")


# ---------------------------------------------------------------------------
# Write landuse.lum
# ---------------------------------------------------------------------------
def write_landuse_lum(hrus, output_dir):
    """Write landuse.lum -- land use management lookup."""
    # Collect unique land use types
    lum_types = set()
    for h in hrus:
        lum_types.add(h['lum'])

    NW = 28

    with open(Path(output_dir) / "landuse.lum", 'w') as f:
        f.write("landuse.lum: written by SWAT+ HRU generator (HydroCraft)\n")
        cols = ['name', 'cal_group', 'plnt_com', 'mgt', 'cn2',
                'cons_prac', 'urban', 'urb_ro', 'ov_mann',
                'tile', 'sep', 'vfs', 'grww', 'bmp']
        f.write("".join(f"{c:<{NW}}" for c in cols).rstrip() + "  \n")

        for lum in sorted(lum_types):
            # Determine plant community, management, CN, conservation practice
            plant = lum.replace('_lum', '')

            # Plant community name
            plnt_com = f"{plant}_comm" if plant not in ('watr', 'barr', 'urld') else "null"

            # Management schedule
            # NOTE: generic_ag and generic_past cause segfaults in SWAT+ rev59
            # due to incompatible operation format. Use no_mgt as safe default.
            # For proper management, use pySWATPlus to set up decision-table
            # management after project generation. See dt_v004.
            mgt = "no_mgt"

            cn2 = CN_TABLE.get(lum, "rc_strow_g")
            cons = CONS_PRACTICE.get(lum, "up_down_slope")
            ovn = OVN_TABLE.get(lum, "densegrass")

            urban = "urld" if plant == 'urld' else "null"
            urb_ro = "buildup_washoff" if plant == 'urld' else "null"

            row = [lum, "all_lum", plnt_com, mgt, cn2,
                   cons, urban, urb_ro, ovn,
                   "null", "null", "null", "null", "null"]
            f.write("".join(f"{v:<{NW}}" for v in row).rstrip() + "  \n")

    logger.info(f"Wrote landuse.lum: {len(lum_types)} entries")


# ---------------------------------------------------------------------------
# Write object.cnt
# ---------------------------------------------------------------------------
def write_object_cnt(hrus, n_subbasins, basin_name, total_area_ha, output_dir):
    """Write object.cnt -- object counts for the basin."""
    hrus_by_sub = defaultdict(list)
    for h in hrus:
        hrus_by_sub[h['sub_id']].append(h)
    n_subs = len(hrus_by_sub)
    n_hrus = len(hrus)
    n_cha = n_subs
    n_aqu = n_subs

    # Total objects = hru + rtu + aqu + cha (no reservoirs in auto-gen)
    total_obj = n_hrus + n_subs + n_aqu + n_cha

    with open(Path(output_dir) / "object.cnt", 'w') as f:
        f.write("object.cnt: written by SWAT+ HRU generator (HydroCraft)\n")
        cols = ['name', 'ls_area', 'tot_area', 'obj', 'hru', 'lhru',
                'rtu', 'mfl', 'aqu', 'cha', 'res', 'rec', 'exco',
                'dlr', 'can', 'pmp', 'out', 'lcha', 'aqu2d', 'hrd', 'wro']
        # NOTE: prepend a space to every field (" {v:>12}" not "{v:>12}") so
        # there is ALWAYS >=1 whitespace separator between tokens. SWAT+ reads
        # object.cnt list-directed; a value that exactly fills its 12-char field
        # (e.g. a basin-scale ls_area like "151683475.87" = 12 chars, i.e.
        # >~1e6 km2) would otherwise touch its neighbour, merging name+ls_area+
        # tot_area into ONE token. That shifts every count left by two fields ->
        # 'obj' misread as 0 -> SWAT+ crashes in hyd_read_connect.f90 with
        # "Attempting to allocate already allocated variable 'ob'" (dt_048).
        f.write("".join(f" {c:>12}" for c in cols) + "  \n")

        vals = [basin_name[:12], f"{total_area_ha:.2f}", f"{total_area_ha:.2f}",
                str(total_obj), str(n_hrus), '0',
                str(n_subs), '0', str(n_aqu), str(n_cha), '0', '0', '0',
                '0', '0', '0', '0', '0', '0', '0', '0']
        f.write("".join(f" {v:>12}" for v in vals) + "  \n")

    logger.info(f"Wrote object.cnt: {total_obj} objects "
                f"({n_hrus} HRUs, {n_subs} RTUs, {n_cha} channels, {n_aqu} aquifers)")


# ---------------------------------------------------------------------------
# Write time.sim, print.prt, file.cio, hydrology.hyd, codes.bsn
# ---------------------------------------------------------------------------
def write_time_sim(output_dir, start_year, end_year):
    with open(Path(output_dir) / "time.sim", 'w') as f:
        f.write("time.sim: written by SWAT+ HRU generator (HydroCraft)\n")
        f.write("day_start  yrc_start   day_end   yrc_end      step  \n")
        f.write(f"       1      {start_year}         365      {end_year}         0  \n")


def write_print_prt(output_dir, warmup=2):
    """Write print.prt by copying from LREW template and modifying.

    NOTE: SWAT+ print.prt format is sensitive to exact whitespace.
    Our generated version doesn't produce channel output, but the LREW
    template format does. Copy LREW's and modify warmup + enable flags.
    See diagnostic triplet dt_v007.
    """
    # Try to copy from LREW template (known working format)
    template = Path(os.path.join(os.environ.get("HYDROCRAFT_ROOT", "/mnt/disk1/Hydrocraft_server"), "models/SWAT_Plus/run_lrew/swatplus_rev59_demo/print.prt"))
    if template.exists():
        import shutil
        dst = Path(output_dir) / "print.prt"
        shutil.copy2(template, dst)
        content = dst.read_text()
        # Update warmup years
        import re
        content = re.sub(r'nyskip.*\n\s*\d+',
                         f'nyskip      day_start  yrc_start  day_end   yrc_end   interval\n     {warmup}',
                         content)
        # Enable channel daily + yearly output
        content = re.sub(r'^(channel\s+)\w(\s+\w\s+)\w(\s+\w)',
                         r'\g<1>y\g<2>y\g<3>', content, flags=re.MULTILINE)
        dst.write_text(content)
        logger.info(f"Copied print.prt from LREW template (warmup={warmup}, channel output enabled)")
        return

    # Fallback: generate from scratch (channel output may not work — dt_v007)
    logger.warning("LREW template not found, generating print.prt from scratch "
                    "(channel output may not work — see dt_v007)")
    with open(Path(output_dir) / "print.prt", 'w') as f:
        f.write("print.prt: written by SWAT+ HRU generator (HydroCraft)\n")
        f.write("nyskip      day_start  yrc_start  day_end   yrc_end   interval\n")
        f.write(f"     {warmup}              0          0        0         0          1\n")
        f.write("aa_int_cnt\n")
        f.write("         0\n")
        f.write("csvout        dbout         cdfout\n")
        f.write("     n            n              n\n")
        f.write("soilout       mgtout        hydcon        fdcout\n")
        f.write("      n            n             n             n\n")
        f.write("objects                  daily       monthly        yearly         avann\n")
        # Enable yearly output for key objects; daily channel for discharge comparison
        enable_yearly = {'basin_wb', 'channel', 'channel_sd', 'aquifer'}
        enable_daily = {'channel'}
        for obj in ['basin_wb', 'basin_nb', 'basin_ls', 'basin_pw',
                     'basin_aqu', 'basin_res', 'basin_cha', 'basin_sd_cha',
                     'basin_psc', 'region_wb', 'region_nb', 'region_ls',
                     'region_pw', 'region_aqu', 'region_res', 'region_cha',
                     'region_sd_cha', 'region_psc', 'lsunit_wb', 'lsunit_nb',
                     'lsunit_ls', 'lsunit_pw', 'hru_wb', 'hru_nb',
                     'hru_ls', 'hru_pw', 'channel', 'channel_sd',
                     'aquifer', 'reservoir']:
            daily = 'y' if obj in enable_daily else 'n'
            yearly = 'y' if obj in enable_yearly else 'n'
            f.write(f"{obj:<25}{daily:>5}{'n':>12}{yearly:>13}{'n':>14}\n")


def write_hydrology_hyd(output_dir, esco=0.15, cn3_swf=0.0, perco=0.75):
    """Write hydrology.hyd with humid-basin defaults.

    The previous defaults (esco=0.95, cn3_swf=0.5, perco=0.0) were hostile to
    humid monsoon basins: esco=0.95 suppresses soil evaporation, cn3_swf=0.5
    amplifies the wet-season curve number, and perco=0.0 blocks ALL percolation
    to the aquifer — forcing nearly every mm of rain to leave as surface runoff
    (Wangjiaba quickstart: surq=591, latq=0, perc=0, wateryld=592 mm/yr vs
    obs 215 mm/yr, PBIAS +315%).

    These three fields are NOT in cal_parms.cal, so the SKILL's
    "humid_subtropical" calibration preset (esco 0.15, cn3_swf 0.0, perco 0.75)
    could never take effect through calibration.cal — they MUST be set here at
    generation time. The new defaults match the validated Bengbu setup
    (NSE 0.751, wateryld 134 mm/yr) and the SKILL preset exactly.
    """
    with open(Path(output_dir) / "hydrology.hyd", 'w') as f:
        f.write("hydrology.hyd: written by SWAT+ HRU generator (HydroCraft)\n")
        cols = ['name', 'lat_ttime', 'lat_sed', 'can_max', 'esco',
                'epco', 'orgn_enrich', 'orgp_enrich', 'cn3_swf',
                'bio_mix', 'perco', 'lat_orgn', 'lat_orgp',
                'harg_pet', 'cn_plntet']
        f.write("".join(f"{c:>{16}}" for c in cols) + "  \n")
        vals = [0.0, 0.0, 1.0, esco, 1.0, 0.0, 0.0, cn3_swf, 0.2, perco,
                0.0, 0.0, 0.0, 1.0]
        f.write(f"{'hyd1':<16}" + "".join(f"{v:>16.5f}" for v in vals) + "  \n")


def write_field_fld(subbasins_gdf, hrus, output_dir):
    """Write field.fld with default field dimensions per subbasin."""
    hrus_by_sub = defaultdict(list)
    for h in hrus:
        hrus_by_sub[h['sub_id']].append(h)
    sub_ids = sorted(hrus_by_sub.keys())

    with open(Path(output_dir) / "field.fld", 'w') as f:
        f.write("field.fld: written by SWAT+ HRU generator (HydroCraft)\n")
        f.write(f"{'name':<20}{'len':>14}{'wd':>14}{'ang':>14}  \n")
        for sub_id in sub_ids:
            fld_name = f"fld{sub_id:04d}"
            f.write(f"{fld_name:<20}{500.0:>14.5f}{100.0:>14.5f}{30.0:>14.5f}  \n")


def write_topography_rtu(subbasins_gdf, hrus, slopes, output_dir):
    """Write topography records for RTUs."""
    hrus_by_sub = defaultdict(list)
    for h in hrus:
        hrus_by_sub[h['sub_id']].append(h)
    sub_ids = sorted(hrus_by_sub.keys())

    # Append RTU topo records to topography.hyd file
    topo_path = Path(output_dir) / "topography.hyd"
    with open(topo_path, 'a') as f:
        for sub_id in sub_ids:
            sub_hrus = hrus_by_sub[sub_id]
            mean_slp = np.mean([h['slope'] for h in sub_hrus])
            topo_name = f"topo_rtu{sub_id:04d}"
            slp_len = max(10.0, min(150.0, 50.0 / (mean_slp + 0.01)))
            f.write(f"{topo_name:<20}"
                    f"{mean_slp:>14.5f}"
                    f"{slp_len:>14.5f}"
                    f"{slp_len:>14.5f}"
                    f"{100.0:>14.5f}"
                    f"{1.0:>14.5f}  \n")


# ---------------------------------------------------------------------------
# Write plant community init files
# ---------------------------------------------------------------------------
def write_plant_ini(hrus, output_dir):
    """Write plant.ini for plant community initialization."""
    # Collect unique plant communities
    communities = set()
    for h in hrus:
        plant = h['plant']
        lum = h['lum']
        comm_name = f"{plant}_comm"
        if plant not in ('watr', 'barr', 'urld'):
            communities.add((comm_name, plant))

    with open(Path(output_dir) / "plant.ini", 'w') as f:
        f.write("plant.ini: written by SWAT+ HRU generator (HydroCraft)\n")
        f.write(f"{'pcom_name':<20}{'plt_cnt':>10}{'rot_yr_ini':>12}"
                f"{'plt_name':>16}{'lc_status':>12}{'lai_init':>12}"
                f"{'bm_init':>12}{'phu_init':>12}{'plnt_pop':>12}"
                f"{'yrs_init':>12}{'rsd_init':>12}  \n")

        for comm_name, plant in sorted(communities):
            # Perennial or annual
            is_perennial = plant in ('frse', 'frsd', 'frst', 'pine', 'rnge',
                                     'rngb', 'past', 'wetf', 'wetn', 'wetl')
            lc_status = 'y' if is_perennial else 'n'
            lai_init = 2.0 if is_perennial else 0.0
            bm_init = 2000.0 if plant in ('frse', 'frsd', 'frst', 'pine') else (
                500.0 if is_perennial else 0.0)
            yrs_init = 30.0 if plant in ('frse', 'frsd', 'frst', 'pine') else 0.0
            rsd_init = 10000.0 if plant in ('frse', 'frsd', 'frst', 'pine') else (
                3000.0 if is_perennial else 1000.0)

            f.write(f"{comm_name:<20}{1:>10}{1:>12}\n")
            f.write(f"{'':>42}{plant:>16}{lc_status:>12}{lai_init:>12.5f}"
                    f"{bm_init:>12.5f}{0.0:>12.5f}{0.0:>12.5f}"
                    f"{yrs_init:>12.5f}{rsd_init:>12.5f}  \n")


def write_soil_plant_ini(output_dir):
    """Write soil_plant.ini."""
    with open(Path(output_dir) / "soil_plant.ini", 'w') as f:
        f.write("Nutrient and Constituent initial amounts on plant and soil\n")
        f.write("  name\t\t   sw_frac\tnutrient\t pesticides"
                "\t pathogens\theavy_metals\tsalts\n")
        f.write(" soilnut1         0.80\tsoilnut1           null"
                "\t\t  null\t\t    null\t null\n")
        f.write(" soilnut2         0.20\tsoilnut1           null"
                "\t\t  null\t\t    null\t null\n")


def write_snow_sno(output_dir):
    """Write snow.sno with default parameters."""
    with open(Path(output_dir) / "snow.sno", 'w') as f:
        f.write("snow.sno: written by SWAT+ HRU generator (HydroCraft)\n")
        f.write(f"{'name':<20}{'fall_tmp':>14}{'melt_tmp':>14}"
                f"{'melt_max':>14}{'melt_min':>14}{'tmp_lag':>14}"
                f"{'snow_h2o':>14}{'cov50':>14}{'snow_init':>14}  \n")
        f.write(f"{'snow001':<20}{1.0:>14.5f}{0.5:>14.5f}"
                f"{4.5:>14.5f}{4.5:>14.5f}{1.0:>14.5f}"
                f"{1.0:>14.5f}{0.5:>14.5f}{0.0:>14.5f}  \n")


def write_nutrients_sol(output_dir):
    """Write nutrients.sol."""
    with open(Path(output_dir) / "nutrients.sol", 'w') as f:
        f.write("nutrients.sol: written by SWAT+ HRU generator (HydroCraft)\n")
        f.write(f"{'id':>8}  {'name':<20}{'dp_co':>14}{'tot_n':>14}"
                f"{'min_n':>14}{'org_n':>14}{'tot_p':>14}{'min_p':>14}"
                f"{'org_p':>14}{'sol_p':>14}{'h3a_p':>14}{'mehl_p':>14}"
                f"{'bray_p':>14}  description\n")
        f.write(f"{1:>8}  {'soilnut1':<20}{13.0:>14.5f}{6.0:>14.5f}"
                f"{3.0:>14.5f}{3.0:>14.5f}{3.5:>14.5f}{0.4:>14.5f}"
                f"{0.15:>14.5f}{0.25:>14.5f}{1.2:>14.5f}{0.85:>14.5f}"
                f"{0.85:>14.5f}\n")


def write_om_water_ini(output_dir):
    """Write om_water.ini."""
    with open(Path(output_dir) / "om_water.ini", 'w') as f:
        f.write("om_water.ini\tinitial water organic/mineral "
                "for channels and reservoirs\n")
        f.write("            flo        sed     orgn    sedp      no3"
                "     solp    chla    nh3     no2     cbod    dox"
                "     san     sil     cla     sag     lag     grv     temp \n")
        f.write("low_init    0.8        100      90      80      70"
                "      60      30      20      10       9       8"
                "       2       1     1000      90      80      70      20\n")
        f.write("high_init   0.9        110      99      88      77"
                "      66      33      22      11      19      28"
                "      82      91     1900      98      87      76      25\n")


def write_initial_files(output_dir):
    """Write initial.cha, initial.aqu."""
    # initial.cha
    with open(Path(output_dir) / "initial.cha", 'w') as f:
        f.write("initial.cha: written by SWAT+ HRU generator (HydroCraft)\n")
        f.write("       name\t\t org-min    pesticides    pathogens"
                "    heavy_metals    salts\n")
        f.write("   initcha1\t    low_init          null         null"
                "\t\t       null     null\n")
        f.write("   initcha2\t   high_init          null         null"
                "\t\t       null     null\n")

    # initial.aqu
    with open(Path(output_dir) / "initial.aqu", 'w') as f:
        f.write("initial.aqu Nutrient and Constituent initial amounts"
                " in water bodies - aquifers\n")
        f.write("  NAME\t\tORG-MIN\t\tPESTICIDES\tPATHOGENS"
                "\tHEAVY_METALS\tSALTS\n")
        f.write(" low_init\t  low_init      no_ini\t\tno_ini"
                "\t\tnull\t\tnull\n")
        f.write(" high_init\t  high_init     low_ini\t\tlow_ini"
                "\t\tnull\t\tnull\n")


def write_ls_unit_files(subbasins_gdf, hrus, output_dir):
    """Write ls_unit.ele and ls_unit.def."""
    hrus_by_sub = defaultdict(list)
    for h in hrus:
        hrus_by_sub[h['sub_id']].append(h)
    sub_ids = sorted(hrus_by_sub.keys())
    total_area = sum(h['area_ha'] for h in hrus)

    # ls_unit.ele
    with open(Path(output_dir) / "ls_unit.ele", 'w') as f:
        f.write("ls_unit.ele: written by SWAT+ HRU generator (HydroCraft)\n")
        f.write(f"{'id':>8}  {'name':<20}{'obj_typ':>10}"
                f"{'obj_typ_no':>12}{'bsn_frac':>14}"
                f"{'sub_frac':>14}{'reg_frac':>14}  \n")
        for h in hrus:
            sub_area = sum(hh['area_ha'] for hh in hrus_by_sub[h['sub_id']])
            bsn_frac = h['area_ha'] / total_area if total_area > 0 else 0
            sub_frac = h['area_ha'] / sub_area if sub_area > 0 else 0
            f.write(f"{h['id']:>8}  {h['name']:<20}{'hru':>10}"
                    f"{h['id']:>12}{bsn_frac:>14.5f}"
                    f"{sub_frac:>14.5f}{0.0:>14.5f}  \n")

    # ls_unit.def
    with open(Path(output_dir) / "ls_unit.def", 'w') as f:
        f.write("ls_unit.def: written by SWAT+ HRU generator (HydroCraft)\n")
        f.write(f"{len(sub_ids)}\n")
        f.write(f"{'id':>8}{'name':>16}{'area':>16}{'elem_tot':>10}"
                f"{'elem1':>10}{'elem2':>10}  \n")
        for idx, sub_id in enumerate(sub_ids):
            sub_hrus = hrus_by_sub[sub_id]
            sub_area = sum(h['area_ha'] for h in sub_hrus)
            rtu_name = f"rtu{sub_id:04d}"
            first_hru = sub_hrus[0]['id']
            last_hru = sub_hrus[-1]['id']
            f.write(f"{idx+1:>8}"
                    f"{rtu_name:>16}"
                    f"{sub_area:>16.5f}"
                    f"{2:>10}"
                    f"{first_hru:>10}"
                    f"{-last_hru:>10}  \n")


# ---------------------------------------------------------------------------
# Write management.sch
# ---------------------------------------------------------------------------
def write_management_sch(hrus, output_dir):
    """Write simplified management schedules."""
    with open(Path(output_dir) / "management.sch", 'w') as f:
        f.write("management.sch: written by SWAT+ HRU generator (HydroCraft)\n")
        f.write(f"{'name':<16}{'numb_ops':>10}{'numb_auto':>10}"
                f"{'op_typ':>20}{'mon':>6}{'day':>6}{'hu_sch':>10}"
                f"{'op_data1':>13}{'op_data2':>13}{'op_data3':>12}  \n")

        # Generic agricultural management
        f.write(f"{'generic_ag':<16}{5:>10}{0:>10}"
                f"{'':>20}{'':>6}{'':>6}{'':>10}{'':>13}{'':>13}{'':>12}\n")
        ops = [
            ('till',  3, 15, 'fldcult',  'null',     0),
            ('plnt',  4,  1, 'agrl',     'null',     0),
            ('fert',  4,  2, 'elem_n',   'broadcast', 100),
            ('harv', 10,  1, 'agrl',     'grain',    0),
            ('skip',  0,  0, 'null',     'null',     0),
        ]
        for op_typ, mon, day, d1, d2, d3 in ops:
            f.write(f"{'':>36}{op_typ:>20}{mon:>6}{day:>6}{0.0:>10.3f}"
                    f"{d1:>13}{d2:>13}{d3:>12.3f}\n")

        # Pasture management
        f.write(f"{'generic_past':<16}{3:>10}{0:>10}"
                f"{'':>20}{'':>6}{'':>6}{'':>10}{'':>13}{'':>13}{'':>12}\n")
        ops_past = [
            ('plnt',  3,  1, 'past', 'null',        0),
            ('harv', 11,  1, 'past', 'hay_cut_low', 0),
            ('skip',  0,  0, 'null', 'null',        0),
        ]
        for op_typ, mon, day, d1, d2, d3 in ops_past:
            f.write(f"{'':>36}{op_typ:>20}{mon:>6}{day:>6}{0.0:>10.3f}"
                    f"{d1:>13}{d2:>13}{d3:>12.3f}\n")

        # Forest -- skip (perennial, no management needed)
        f.write(f"{'forest':<16}{1:>10}{0:>10}"
                f"{'':>20}{'':>6}{'':>6}{'':>10}{'':>13}{'':>13}{'':>12}\n")
        f.write(f"{'':>36}{'skip':>20}{0:>6}{0:>6}{0.0:>10.3f}"
                f"{'null':>13}{'null':>13}{0.0:>12.3f}\n")

        # Wetland -- skip
        f.write(f"{'wetland':<16}{1:>10}{0:>10}"
                f"{'':>20}{'':>6}{'':>6}{'':>10}{'':>13}{'':>13}{'':>12}\n")
        f.write(f"{'':>36}{'skip':>20}{0:>6}{0:>6}{0.0:>10.3f}"
                f"{'null':>13}{'null':>13}{0.0:>12.3f}\n")

        # No management
        f.write(f"{'no_mgt':<16}{0:>10}{0:>10}\n")


# ---------------------------------------------------------------------------
# Copy template files that we don't regenerate
# ---------------------------------------------------------------------------
def copy_template_auxiliary(template_dir, output_dir):
    """Copy auxiliary files from template that we don't regenerate."""
    template_dir = Path(template_dir)
    output_dir = Path(output_dir)

    # Files we generate ourselves -- do NOT copy from template
    generated = {
        'hru.con', 'hru-data.hru', 'rout_unit.con', 'rout_unit.def',
        'rout_unit.ele', 'rout_unit.rtu', 'topography.hyd', 'hydrology.hyd',
        'soils.sol', 'landuse.lum', 'object.cnt', 'file.cio', 'time.sim',
        'print.prt', 'codes.bsn', 'parameters.bsn', 'channel.con',
        'channel.cha', 'hydrology.cha', 'sediment.cha', 'nutrients.cha',
        'aquifer.con', 'aquifer.aqu', 'initial.cha', 'initial.aqu',
        'field.fld', 'plant.ini', 'soil_plant.ini', 'om_water.ini',
        'snow.sno', 'nutrients.sol', 'management.sch', 'ls_unit.ele',
        'ls_unit.def', 'weather-sta.cli', 'reservoir.con',
    }

    # Files to copy from template (database files, decision tables, etc.)
    copy_patterns = [
        'plants.plt', 'fertilizer.frt', 'tillage.til', 'pesticide.pst',
        'urban.urb', 'septic.sep',
        'cntable.lum', 'cons_practice.lum', 'ovn_table.lum',
        'cal_parms.cal', 'calibration.cal',
        'lum.dtl', 'res_rel.dtl', 'scen_lu.dtl', 'flo_con.dtl', 'd_table.dtl',
        'weather-wgn.cli',
        'harv.ops', 'graze.ops', 'irr.ops', 'chem_app.ops', 'fire.ops', 'sweep.ops',
        'pest_hru.ini', 'pest_water.ini', 'path_hru.ini', 'path_water.ini',
        'hmet_hru.ini', 'hmet_water.ini', 'salt_hru.ini', 'salt_water.ini',
        'channel-lte.cha', 'hyd-sed-lte.cha',
        'tiledrain.str', 'septic.str', 'filterstrip.str', 'grassedww.str', 'bmpuser.str',
        'weir.res', 'reservoir.res', 'hydrology.res', 'sediment.res', 'nutrients.res',
        'initial.res',
    ]

    copied = 0
    for pattern in copy_patterns:
        src = template_dir / pattern
        if src.exists() and pattern not in generated:
            dst = output_dir / pattern
            if not dst.exists():
                shutil.copy2(src, dst)
                copied += 1

    logger.info(f"Copied {copied} auxiliary files from template")
    return copied


# ---------------------------------------------------------------------------
# Write file.cio
# ---------------------------------------------------------------------------
def write_file_cio(output_dir, basin_name):
    """Write file.cio master control file."""
    with open(Path(output_dir) / "file.cio", 'w') as f:
        f.write(f"file.cio: generated for {basin_name} by SWAT+ HRU generator (HydroCraft)\n")
        lines = [
            "simulation        time.sim          print.prt         null              object.cnt        null",
            "basin             codes.bsn         parameters.bsn",
            "climate           weather-sta.cli   weather-wgn.cli   null              pcp.cli           tmp.cli           slr.cli           hmd.cli           wnd.cli           null",
            "connect           hru.con           null              rout_unit.con     null              aquifer.con       null              channel.con       null              null              null              null              null              null",
            "channel           initial.cha       channel.cha       hydrology.cha     sediment.cha      nutrients.cha     channel-lte.cha   hyd-sed-lte.cha   null",
            "reservoir         initial.res       reservoir.res     hydrology.res     sediment.res      nutrients.res     weir.res          null              null",
            "routing_unit      rout_unit.def     rout_unit.ele     rout_unit.rtu     null",
            "hru               hru-data.hru      null",
            "exco              null              null              null              null              null              null",
            "recall            null",
            "dr                null              null              null              null              null              null",
            "aquifer           initial.aqu       aquifer.aqu",
            "herd              null              null              null",
            "water_rights      null              null              null",
            "link              null              null",
            "hydrology         hydrology.hyd     topography.hyd    field.fld",
            "structural        tiledrain.str     septic.str        filterstrip.str   grassedww.str     bmpuser.str",
            "hru_parm_db       plants.plt        fertilizer.frt    tillage.til       pesticide.pst     null              null              null              urban.urb         septic.sep        snow.sno",
            "ops               harv.ops          graze.ops         irr.ops           chem_app.ops      fire.ops          sweep.ops",
            "lum               landuse.lum       management.sch    cntable.lum       cons_practice.lum ovn_table.lum",
            "chg               cal_parms.cal     calibration.cal   null           null                 null              null              null              null              null",
            "init              plant.ini         soil_plant.ini    om_water.ini      pest_hru.ini      pest_water.ini    path_hru.ini      path_water.ini    hmet_hru.ini      hmet_water.ini    salt_hru.ini     salt_water.ini",
            "soils             soils.sol         nutrients.sol     soils-lte.sol",
            "decision_table    lum.dtl           res_rel.dtl       scen_lu.dtl       flo_con.dtl",
            "regions           ls_unit.ele       ls_unit.def       null              null              null              null              null              null              null              null              null              null              null              null              null              null              null",
            "pcp_path          null",
            "tmp_path          null",
            "slr_path          null",
            "hmd_path          null",
            "wnd_path          null",
        ]
        for line in lines:
            f.write(line + "\n")


def write_codes_bsn(output_dir):
    """Write codes.bsn with default settings."""
    with open(Path(output_dir) / "codes.bsn", 'w') as f:
        f.write("codes.bsn: written by SWAT+ HRU generator (HydroCraft)\n")
        cols = ['pet_file', 'wq_file', 'pet', 'event', 'crack',
                'rtu_wq', 'sed_det', 'rte_cha', 'deg_cha', 'wq_cha',
                'rte_pest', 'cn', 'c_fact', 'carbon', 'baseflo',
                'uhyd', 'sed_cha', 'tiledrain', 'wtable', 'soil_p',
                'abstr_init', 'atmo_dep', 'stor_max', 'headwater']
        f.write("".join(f"{c:>{14}}" for c in cols) + "  \n")
        vals = ['null', 'null', 0, 0, 0, 0, 0, 1, 0, 0,
                0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0]
        f.write("".join(f"{str(v):>{14}}" for v in vals) + "  \n")


def write_parameters_bsn(output_dir):
    """Write parameters.bsn with SWAT+ defaults."""
    with open(Path(output_dir) / "parameters.bsn", 'w') as f:
        f.write("parameters.bsn: written by SWAT+ HRU generator (HydroCraft)\n")
        cols = ['lai_noevap', 'sw_init', 'surq_lag', 'adj_pkrt',
                'adj_pkrt_sed', 'lin_sed', 'exp_sed', 'orgn_min',
                'n_uptake', 'p_uptake', 'n_perc', 'p_perc', 'p_soil',
                'p_avail', 'rsd_decomp', 'pest_perc', 'msk_co1', 'msk_co2',
                'msk_x', 'trans_loss', 'evap_adj', 'cn_co', 'denit_exp',
                'denit_frac', 'man_bact', 'adj_uhyd', 'cn_froz', 'dorm_hr',
                's_max', 'n_fix', 'n_fix_max', 'rsd_decay', 'rsd_cover',
                'vel_crit', 'res_sed', 'uhyd_alpha', 'splash', 'rill',
                'surq_exp', 'cov_mgt', 'cha_d50', 'cha_part_sd', 'adj_cn',
                'igen']
        f.write("".join(f"{c:>{14}}" for c in cols) + "  \n")
        vals = [3.0, 0.0, 4.0, 1.0, 1.0, 0.0, 1.0, 0.0,
                20.0, 20.0, 20.0, 10.0, 175.0, 0.4, 0.05, 0.5,
                0.75, 0.25, 0.2, 0.0, 0.6, 1.0, 1.4, 1.3,
                0.15, 0.0, 0.0, 0.0, 1.0, 0.5, 20.0, 0.01,
                0.3, 5.0, 0.18, 5.0, 1.0, 0.7, 1.2, 0.03,
                50.0, 1.57, 1.0, 0]
        f.write("".join(
            f"{v:>14.5f}" if isinstance(v, float) else f"{v:>14}"
            for v in vals
        ) + "  \n")


def write_weather_sta_cli(subbasins_gdf, hrus, output_dir, basin_name):
    """Write a minimal weather-sta.cli with one station per subbasin."""
    hrus_by_sub = defaultdict(list)
    for h in hrus:
        hrus_by_sub[h['sub_id']].append(h)
    n_subs = len(hrus_by_sub)

    # Check if template wgn exists
    wgn_name = "sim"
    wgn_path = Path(output_dir) / "weather-wgn.cli"
    if wgn_path.exists():
        try:
            lines = wgn_path.read_text().strip().split('\n')
            if len(lines) >= 2:
                wgn_name = lines[1].split()[0]
        except Exception:
            pass

    CW = 27
    with open(Path(output_dir) / "weather-sta.cli", 'w') as f:
        f.write(f"weather-sta.cli: written for {basin_name} by SWAT+ HRU generator\n")
        cols = ['name', 'wgn', 'pcp', 'tmp', 'slr', 'hmd', 'wnd',
                'wnd_dir', 'atmo_dep']
        f.write("".join(c.ljust(CW) for c in cols).rstrip() + "\n")

        for i in range(n_subs):
            sta_name = f"sta{i+1:02d}"
            row = [sta_name, wgn_name, "null", "null", "null",
                   "null", "null", "null", "null"]
            f.write("".join(c.ljust(CW) for c in row).rstrip() + "\n")

    logger.info(f"Wrote weather-sta.cli: {n_subs} stations")


def write_reservoir_con(output_dir):
    """Write an empty reservoir.con (no reservoirs in auto-generated project)."""
    with open(Path(output_dir) / "reservoir.con", 'w') as f:
        f.write("reservoir.con: written by SWAT+ HRU generator (HydroCraft)\n")
        f.write(f"{'id':>8}  {'name':<20}"
                f"{'gis_id':>12}{'area':>12}{'lat':>12}{'lon':>12}"
                f"{'elev':>12}{'res':>8}{'wst':>16}"
                f"{'cst':>8}{'ovfl':>8}{'rule':>8}{'out_tot':>10}"
                f"{'obj_typ':>12}{'obj_id':>10}{'hyd_typ':>12}{'frac':>14}  \n")


def write_empty_cli_files(output_dir):
    """Write empty .cli weather index files (user adds data later)."""
    for fname, desc in [('pcp.cli', 'Precipitation'),
                        ('tmp.cli', 'Temperature'),
                        ('slr.cli', 'Solar radiation'),
                        ('hmd.cli', 'Relative humidity'),
                        ('wnd.cli', 'Wind speed')]:
        with open(Path(output_dir) / fname, 'w') as f:
            f.write(f"{fname}: {desc} - file written by SWAT+ HRU generator\n")
            f.write("filename\n")


def fix_cal_parms_cal(output_dir):
    """Fix cal_parms.cal for pySWATPlus compatibility."""
    cal_path = Path(output_dir) / "cal_parms.cal"
    if not cal_path.exists():
        return

    content = cal_path.read_text()
    original = content
    content = content.replace('\r', '')

    lines = content.split('\n')
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.upper().startswith('NAME') and 'OBJ_TYP' in stripped.upper():
            lines[i] = line.lower()
            break

    content = '\n'.join(lines)
    replacements = {
        'kg P': 'kg_P', 'kg N': 'kg_N', 'kg C': 'kg_C',
        'kg p': 'kg_p', 'kg n': 'kg_n', 'kg c': 'kg_c',
        'm**3': 'm3', 'julian day': 'julian_day', 'Julian day': 'julian_day',
        'deg c': 'deg_c', 'deg C': 'deg_C', 'Deg C': 'deg_C',
        'mg N': 'mg_N', 'mg P': 'mg_P',
    }
    for old, new in replacements.items():
        content = content.replace(old, new)

    if content != original:
        cal_path.write_text(content)
        logger.info("Fixed cal_parms.cal for pySWATPlus compatibility")


# ===========================================================================
# Validation
# ===========================================================================
def validate_inputs(args):
    errors = []
    if not Path(args.basin_shp).exists():
        errors.append(f"Basin shapefile not found: {args.basin_shp}")
    if args.dem_path != "auto" and not Path(args.dem_path).exists():
        errors.append(f"DEM not found: {args.dem_path}")
    if not Path(args.landcover_path).exists():
        errors.append(f"Land cover raster not found: {args.landcover_path}")
    if not Path(args.hwsd_raster).exists():
        errors.append(f"HWSD raster not found: {args.hwsd_raster}")
    if not Path(args.hwsd_mdb).exists():
        errors.append(f"HWSD MDB not found: {args.hwsd_mdb}")
    if not Path(args.template_dir).is_dir():
        errors.append(f"Template directory not found: {args.template_dir}")
    if args.start_year >= args.end_year:
        errors.append(f"start_year ({args.start_year}) must be < end_year ({args.end_year})")
    if args.grid_nc and not Path(args.grid_nc).exists():
        errors.append(f"Grid NC not found: {args.grid_nc}")

    try:
        subprocess.run(['mdb-export', '--version'],
                       capture_output=True, timeout=5)
    except FileNotFoundError:
        errors.append("mdb-tools not installed (apt install mdbtools)")
    except subprocess.TimeoutExpired:
        pass

    if errors:
        for e in errors:
            logger.error(e)
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)

    logger.info("Input validation passed.")


def validate_outputs(output_dir):
    output_path = Path(output_dir)
    essential = ['file.cio', 'time.sim', 'print.prt', 'hru.con',
                 'hru-data.hru', 'rout_unit.con', 'soils.sol',
                 'object.cnt', 'codes.bsn', 'landuse.lum',
                 'topography.hyd', 'hydrology.hyd']
    errors = []
    for ef in essential:
        if not (output_path / ef).exists():
            errors.append(f"Essential file missing: {ef}")
        elif (output_path / ef).stat().st_size == 0:
            errors.append(f"Essential file is empty: {ef}")

    total_files = len(list(output_path.iterdir()))
    if total_files < 20:
        errors.append(f"Only {total_files} files in output, expected >= 20")

    if errors:
        for e in errors:
            logger.error(e)
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(3)

    logger.info(f"Output validation passed: {total_files} files in {output_dir}")
    return total_files


# ===========================================================================
# Main processing pipeline
# ===========================================================================
def process(args):
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    slope_classes = parse_slope_classes(args.slope_classes)

    # Step 0: Resolve DEM path
    dem_path = resolve_dem_path(args.dem_path, args.basin_shp)
    logger.info(f"Using DEM: {dem_path}")

    # Step 1: Create subbasins.
    # Priority: real flow-network subbasins > VIC grid > rectangular fallback.
    if args.subbasin_shp:
        subbasins_gdf = load_subbasins_from_shapefile(args.subbasin_shp)
    elif args.grid_nc:
        subbasins_gdf = create_subbasins_from_grid_nc(args.grid_nc, args.basin_shp)
    else:
        warn_rectangular_subbasins()
        subbasins_gdf = create_subbasins_from_basin(
            args.basin_shp, dem_path, args.n_subbasins)

    n_subbasins = len(subbasins_gdf)
    total_area_ha = subbasins_gdf['area_ha'].sum()
    logger.info(f"Basin: {n_subbasins} subbasins, {total_area_ha:.0f} ha "
                f"({total_area_ha/100:.0f} km2)")

    # Step 2: Land cover classification (fractional for multi-HRU)
    lc_fractions = classify_landcover_fractions(subbasins_gdf, args.landcover_path)

    # Step 3: Soil classification
    hwsd_db = load_hwsd_mdb(args.hwsd_mdb)
    soil_names, soil_profiles = extract_soil_per_subbasin(
        subbasins_gdf, args.hwsd_raster, hwsd_db)

    # Step 4: Slope classification
    clipped_dem = clip_dem_to_basin(dem_path, args.basin_shp, str(output_dir))
    slopes, elevations = compute_slope_per_subbasin(subbasins_gdf, clipped_dem)

    # Step 5: Generate HRUs
    hrus = generate_hrus(
        subbasins_gdf, lc_fractions, soil_names, slopes, elevations,
        slope_classes, args.hru_threshold)

    # Step 6: Write all SWAT+ TxtInOut files
    logger.info("Writing SWAT+ TxtInOut files...")

    # Copy template auxiliary files first
    copy_template_auxiliary(args.template_dir, str(output_dir))

    # Write generated files
    write_soils_sol(soil_profiles, str(output_dir / "soils.sol"))
    write_hru_con(hrus, n_subbasins, str(output_dir / "hru.con"))
    write_hru_data(hrus, str(output_dir / "hru-data.hru"))
    write_topography_hyd(hrus, str(output_dir / "topography.hyd"))
    write_topography_rtu(subbasins_gdf, hrus, slopes, str(output_dir))
    write_hydrology_hyd(str(output_dir), esco=args.esco, cn3_swf=args.cn3_swf, perco=args.perco)
    write_routing_units(subbasins_gdf, hrus, n_subbasins, str(output_dir))
    write_channel_files(subbasins_gdf, hrus, str(output_dir),
                        channel_topology=args.channel_topology)
    write_aquifer_files(subbasins_gdf, hrus, str(output_dir))
    write_landuse_lum(hrus, str(output_dir))
    write_object_cnt(hrus, n_subbasins, args.basin_name, total_area_ha,
                     str(output_dir))
    write_field_fld(subbasins_gdf, hrus, str(output_dir))
    write_plant_ini(hrus, str(output_dir))
    write_soil_plant_ini(str(output_dir))
    write_snow_sno(str(output_dir))
    write_nutrients_sol(str(output_dir))
    write_om_water_ini(str(output_dir))
    write_initial_files(str(output_dir))
    write_ls_unit_files(subbasins_gdf, hrus, str(output_dir))
    write_management_sch(hrus, str(output_dir))
    write_weather_sta_cli(subbasins_gdf, hrus, str(output_dir), args.basin_name)
    write_reservoir_con(str(output_dir))
    write_empty_cli_files(str(output_dir))
    write_time_sim(str(output_dir), args.start_year, args.end_year)
    write_print_prt(str(output_dir), warmup=min(2, args.end_year - args.start_year))
    write_file_cio(str(output_dir), args.basin_name)
    write_codes_bsn(str(output_dir))
    write_parameters_bsn(str(output_dir))

    # Step 7: Fix cal_parms.cal
    fix_cal_parms_cal(str(output_dir))

    # Step 8: Create empty soils_lte.sol (required by SWAT+ for basin-level output)
    (output_dir / "soils_lte.sol").touch()
    logger.info("Created empty soils_lte.sol (required for basin_wb output)")

    # Clean up clipped DEM
    clipped_dem_path = Path(clipped_dem)
    if clipped_dem_path.exists():
        clipped_dem_path.unlink()

    # Build result summary
    lu_dist = Counter(h['plant'] for h in hrus)
    soil_types = list(soil_profiles.keys())

    slope_dist = Counter()
    for h in hrus:
        sc = slope_classes[h['slope_cls']]
        slope_dist[f"{sc[0]:.0f}-{sc[1]:.0f}%"] += 1

    result = {
        "status": "success",
        "output_dir": str(output_dir.resolve()),
        "basin_name": args.basin_name,
        "period": f"{args.start_year}-{args.end_year}",
        "n_subbasins": n_subbasins,
        "n_hrus": len(hrus),
        "total_area_ha": round(total_area_ha, 1),
        "total_area_km2": round(total_area_ha / 100, 1),
        "land_use_distribution": dict(lu_dist.most_common()),
        "n_soil_types": len(soil_types),
        "soil_types": soil_types[:10] + (["..."] if len(soil_types) > 10 else []),
        "slope_distribution": dict(slope_dist),
        "data_sources": {
            "landcover": str(args.landcover_path),
            "soil": "HWSD v1.2 (FAO/IIASA/ISRIC/ISS-CAS/JRC)",
            "dem": dem_path,
        },
    }
    return result


# ===========================================================================
# Entry point
# ===========================================================================
if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")

    args = parse_args()
    validate_inputs(args)

    try:
        result = process(args)
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        import traceback
        traceback.print_exc()
        print(json.dumps({"status": "error", "message": str(e)}))
        sys.exit(2)

    validate_outputs(args.output_dir)

    logger.info(f"Tool completed successfully. Output: {result['output_dir']}")
    print(json.dumps(result, indent=2))
    sys.exit(0)
