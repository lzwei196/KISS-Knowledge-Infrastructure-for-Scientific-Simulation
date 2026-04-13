#!/usr/bin/env python3
"""
build_geo_em.py  --  WRF-Hydro Phase 1, Tool 2
================================================
Build a geo_em.d01.nc file from raw geospatial data, replicating the exact
structure that WRF/WPS geogrid produces (39 variables, 46+ global attributes,
8 dimensions).

Requires the domain JSON produced by define_lambert_domain.py (Tool 1).

Data sources
------------
- DEM:  China 90 m or SRTM 30 m (GeoTIFF, EPSG:4326)
- Land cover:  UMD AVHRR 1 km (GeoTIFF, EPSG:4326, 0-14 classes)
- Soil:  HWSD raster (.bil, uint16 MU_GLOBAL) + MDB for sand/silt/clay

Usage
-----
    python build_geo_em.py \
        --domain_json domain_def.json \
        --dem_path  data/dem/china_dem_90m/china_dem_90m.tif \
        --landcover_path data/landcover/AVHRR_1km_LANDCOVER_1981_1994.GLOBAL.tif \
        --hwsd_raster data/soil/HWSD_RASTER/hwsd.bil \
        --hwsd_mdb   data/forcing/huaihe_raw/soil/HWSD.mdb \
        --output     outputs/test/DOMAIN/geo_em.d01.nc
"""

import argparse
import csv
import io
import json
import subprocess
import sys
from pathlib import Path

import geopandas as gpd
import netCDF4 as nc
import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling
from rasterio.transform import from_bounds
from pyproj import Transformer
sys.path.insert(0, "/home/server/knowledge-dissection-toolkit/auto_dissect")
from ki_tools_common.units import celsius_to_kelvin, kelvin_to_celsius

# ===================================================================
# Constants
# ===================================================================
WRF_EARTH_RADIUS = 6370000.0
OMEGA = 7.2921e-5  # Earth angular velocity (rad/s)

# UMD class (0-14) --> USGS 24-category land use
UMD_TO_USGS = {
    0:  16,  # Water
    1:  14,  # Evergreen Needleleaf Forest
    2:  13,  # Evergreen Broadleaf Forest
    3:  12,  # Deciduous Needleleaf Forest
    4:  11,  # Deciduous Broadleaf Forest
    5:  15,  # Mixed Forest
    6:   6,  # Cropland/Woodland Mosaic
    7:  10,  # Savanna  (mapped to Savanna in USGS)
    8:   8,  # Closed Shrubland
    9:   9,  # Open Shrubland / Mixed Shrub-Grass
    10:  7,  # Grassland
    11:  2,  # Cropland (Dryland)
    12: 19,  # Barren / Sparsely Vegetated
    13:  1,  # Urban
    14: 24,  # Snow and Ice
}

ISWATER = 16
ISICE = 24
ISURBAN = 1
ISLAKE = -1
ISOILWATER = 14
NUM_LAND_CAT = 24
NUM_SOIL_CAT = 16

# USDA texture triangle classification thresholds
# Returns STATSGO/FAO 16-category soil type index.
# 1=Sand, 2=Loamy Sand, 3=Sandy Loam, 4=Silt Loam, 5=Silt,
# 6=Loam, 7=Sandy Clay Loam, 8=Silty Clay Loam, 9=Clay Loam,
# 10=Sandy Clay, 11=Silty Clay, 12=Clay, 13=Organic, 14=Water,
# 15=Bedrock, 16=Other
def classify_usda_soil(sand, silt, clay):
    """Classify soil by USDA texture triangle. Inputs in percent (0-100)."""
    if sand + silt + clay < 1:
        return ISOILWATER  # Water / no data
    # Normalise to 100%
    total = sand + silt + clay
    if total > 0:
        sand = sand * 100.0 / total
        silt = silt * 100.0 / total
        clay = clay * 100.0 / total
    if clay >= 40:
        if silt >= 40:
            return 11  # Silty Clay
        if sand >= 45:
            return 10  # Sandy Clay
        return 12  # Clay
    if clay >= 27:
        if sand >= 20 and sand < 45:
            return 9  # Clay Loam
        if sand < 20:
            return 8  # Silty Clay Loam
        return 7  # Sandy Clay Loam
    if clay >= 7 and clay < 27:
        if silt >= 28 and silt < 50 and sand <= 52:
            return 6  # Loam
        if silt >= 50 and clay >= 12:
            return 4  # Silt Loam
        if silt >= 50 and clay < 12:
            return 4  # Silt Loam
        if silt >= 80 and clay < 12:
            return 5  # Silt
        if sand > 52:
            return 3  # Sandy Loam
        return 4  # Silt Loam
    if clay < 7:
        if silt >= 50:
            return 4  # Silt Loam (or Silt)
        if sand >= 85:
            return 1  # Sand
        if sand >= 70:
            return 2  # Loamy Sand
        return 3  # Sandy Loam
    return 6  # Loam (fallback)


# Climatological GREENFRAC and LAI12M by USGS land use class
# 12 monthly values. Sources: NLDAS/WRF default vegetation tables.
# Indexed 1-24 (USGS). 0 = fill.
_GF = {
    0:  [0.0]*12,
    1:  [0.10, 0.10, 0.10, 0.12, 0.15, 0.18, 0.18, 0.17, 0.15, 0.12, 0.10, 0.10],  # Urban
    2:  [0.10, 0.10, 0.15, 0.30, 0.50, 0.70, 0.80, 0.78, 0.60, 0.35, 0.15, 0.10],  # Dryland Crop
    3:  [0.20, 0.20, 0.25, 0.40, 0.60, 0.80, 0.85, 0.83, 0.65, 0.40, 0.25, 0.20],  # Irrigated Crop
    4:  [0.15, 0.15, 0.20, 0.35, 0.55, 0.75, 0.82, 0.80, 0.62, 0.38, 0.20, 0.15],  # Mixed Crop
    5:  [0.30, 0.30, 0.35, 0.50, 0.65, 0.78, 0.82, 0.80, 0.68, 0.50, 0.35, 0.30],  # Crop/Grass
    6:  [0.35, 0.35, 0.40, 0.52, 0.65, 0.75, 0.80, 0.78, 0.68, 0.52, 0.40, 0.35],  # Crop/Wood
    7:  [0.20, 0.20, 0.25, 0.40, 0.55, 0.70, 0.72, 0.68, 0.55, 0.35, 0.25, 0.20],  # Grassland
    8:  [0.20, 0.20, 0.22, 0.30, 0.40, 0.48, 0.50, 0.48, 0.42, 0.32, 0.22, 0.20],  # Shrubland
    9:  [0.15, 0.15, 0.18, 0.28, 0.38, 0.45, 0.48, 0.45, 0.38, 0.28, 0.18, 0.15],  # Mixed Shrub/Grass
    10: [0.30, 0.30, 0.35, 0.45, 0.55, 0.65, 0.68, 0.65, 0.55, 0.42, 0.35, 0.30],  # Savanna
    11: [0.40, 0.40, 0.50, 0.65, 0.80, 0.88, 0.90, 0.88, 0.80, 0.65, 0.50, 0.40],  # Deciduous Broadleaf
    12: [0.40, 0.40, 0.45, 0.55, 0.75, 0.85, 0.88, 0.85, 0.75, 0.55, 0.45, 0.40],  # Deciduous Needleleaf
    13: [0.70, 0.70, 0.72, 0.75, 0.80, 0.85, 0.88, 0.85, 0.82, 0.78, 0.72, 0.70],  # Evergreen Broadleaf
    14: [0.50, 0.50, 0.55, 0.60, 0.70, 0.80, 0.85, 0.82, 0.75, 0.65, 0.55, 0.50],  # Evergreen Needleleaf
    15: [0.45, 0.45, 0.52, 0.62, 0.75, 0.85, 0.88, 0.85, 0.78, 0.62, 0.52, 0.45],  # Mixed Forest
    16: [0.00]*12,  # Water
    17: [0.20, 0.20, 0.22, 0.28, 0.35, 0.42, 0.45, 0.42, 0.35, 0.28, 0.22, 0.20],  # Herb Wetland
    18: [0.30, 0.30, 0.35, 0.45, 0.55, 0.65, 0.68, 0.65, 0.55, 0.45, 0.35, 0.30],  # Wooded Wetland
    19: [0.01, 0.01, 0.01, 0.02, 0.03, 0.04, 0.05, 0.04, 0.03, 0.02, 0.01, 0.01],  # Barren
    20: [0.10, 0.10, 0.12, 0.15, 0.20, 0.25, 0.28, 0.25, 0.20, 0.15, 0.12, 0.10],  # Herb Tundra
    21: [0.15, 0.15, 0.18, 0.25, 0.35, 0.42, 0.45, 0.42, 0.35, 0.25, 0.18, 0.15],  # Wooded Tundra
    22: [0.12, 0.12, 0.15, 0.20, 0.28, 0.35, 0.38, 0.35, 0.28, 0.20, 0.15, 0.12],  # Mixed Tundra
    23: [0.05, 0.05, 0.06, 0.08, 0.12, 0.15, 0.18, 0.15, 0.12, 0.08, 0.06, 0.05],  # Bare Tundra
    24: [0.00]*12,  # Snow/Ice
}

_LAI = {
    0:  [0.0]*12,
    1:  [0.5, 0.5, 0.5, 0.6, 0.8, 1.0, 1.0, 0.9, 0.8, 0.6, 0.5, 0.5],  # Urban
    2:  [0.3, 0.3, 0.5, 1.2, 2.5, 3.5, 4.0, 3.8, 2.5, 1.2, 0.5, 0.3],  # Dryland Crop
    3:  [0.5, 0.5, 0.8, 1.5, 3.0, 4.0, 4.5, 4.2, 3.0, 1.5, 0.8, 0.5],  # Irrigated Crop
    4:  [0.4, 0.4, 0.6, 1.3, 2.8, 3.8, 4.2, 4.0, 2.8, 1.3, 0.6, 0.4],  # Mixed Crop
    5:  [0.8, 0.8, 1.0, 1.8, 3.0, 3.8, 4.0, 3.8, 3.0, 1.8, 1.0, 0.8],  # Crop/Grass
    6:  [1.0, 1.0, 1.2, 2.0, 3.2, 3.8, 4.0, 3.8, 3.2, 2.0, 1.2, 1.0],  # Crop/Wood
    7:  [0.5, 0.5, 0.8, 1.5, 2.0, 2.5, 2.5, 2.3, 2.0, 1.2, 0.8, 0.5],  # Grassland
    8:  [0.5, 0.5, 0.6, 0.8, 1.0, 1.3, 1.5, 1.3, 1.0, 0.8, 0.6, 0.5],  # Shrubland
    9:  [0.3, 0.3, 0.4, 0.6, 0.8, 1.0, 1.2, 1.0, 0.8, 0.6, 0.4, 0.3],  # Mixed Shrub/Grass
    10: [1.0, 1.0, 1.2, 1.8, 2.5, 3.0, 3.2, 3.0, 2.5, 1.8, 1.2, 1.0],  # Savanna
    11: [1.0, 1.0, 1.5, 2.5, 4.0, 5.0, 5.5, 5.2, 4.0, 2.5, 1.5, 1.0],  # Deciduous Broadleaf
    12: [1.0, 1.0, 1.3, 2.0, 3.5, 4.5, 5.0, 4.5, 3.5, 2.0, 1.3, 1.0],  # Deciduous Needleleaf
    13: [4.0, 4.0, 4.2, 4.5, 5.0, 5.5, 6.0, 5.5, 5.2, 4.8, 4.2, 4.0],  # Evergreen Broadleaf
    14: [2.0, 2.0, 2.2, 2.5, 3.5, 4.5, 5.0, 4.5, 3.8, 3.0, 2.2, 2.0],  # Evergreen Needleleaf
    15: [1.5, 1.5, 1.8, 2.5, 3.8, 4.8, 5.2, 5.0, 4.0, 2.8, 1.8, 1.5],  # Mixed Forest
    16: [0.0]*12,  # Water
    17: [0.5, 0.5, 0.6, 1.0, 1.5, 2.0, 2.2, 2.0, 1.5, 1.0, 0.6, 0.5],  # Herb Wetland
    18: [1.0, 1.0, 1.2, 1.8, 2.5, 3.2, 3.5, 3.2, 2.5, 1.8, 1.2, 1.0],  # Wooded Wetland
    19: [0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1],  # Barren
    20: [0.3, 0.3, 0.4, 0.5, 0.8, 1.0, 1.2, 1.0, 0.8, 0.5, 0.4, 0.3],  # Herb Tundra
    21: [0.5, 0.5, 0.6, 0.8, 1.2, 1.5, 1.8, 1.5, 1.2, 0.8, 0.6, 0.5],  # Wooded Tundra
    22: [0.4, 0.4, 0.5, 0.7, 1.0, 1.3, 1.5, 1.3, 1.0, 0.7, 0.5, 0.4],  # Mixed Tundra
    23: [0.2, 0.2, 0.2, 0.3, 0.5, 0.6, 0.7, 0.6, 0.5, 0.3, 0.2, 0.2],  # Bare Tundra
    24: [0.0]*12,  # Snow/Ice
}


# ===================================================================
# Helper functions
# ===================================================================

def _safe_float(val, default=0.0):
    try:
        return float(val) if val else default
    except (ValueError, TypeError):
        return default


def load_hwsd_mdb(mdb_path):
    """Load HWSD_DATA table from MDB, keyed by MU_GLOBAL."""
    result = subprocess.run(
        ['mdb-export', str(mdb_path), 'HWSD_DATA'],
        capture_output=True, text=True, timeout=120
    )
    if result.returncode != 0:
        print(f"  WARNING: mdb-export failed: {result.stderr[:200]}")
        return None
    reader = csv.DictReader(io.StringIO(result.stdout))
    mu_data = {}
    for row in reader:
        try:
            mu = int(row['MU_GLOBAL'])
        except (ValueError, KeyError):
            continue
        share = _safe_float(row.get('SHARE', 0))
        has_data = bool(row.get('T_SAND'))
        if mu not in mu_data or (has_data and share > mu_data[mu].get('_share', 0)):
            row['_share'] = share
            mu_data[mu] = row
    return mu_data


def resample_raster_to_lcc(raster_path, proj4, x_sw, y_sw, nx, ny, dx, dy,
                           resampling=Resampling.bilinear, nodata=None,
                           dst_dtype=None):
    """
    Read a raster (assumed EPSG:4326 or with CRS) and reproject it onto the
    WRF Lambert grid.  Returns a 2D numpy array of shape (ny, nx).
    """
    with rasterio.open(raster_path) as src:
        src_crs = src.crs if src.crs else rasterio.crs.CRS.from_epsg(4326)
        if nodata is None:
            nodata = src.nodata
        src_data = src.read(1)
        src_transform = src.transform
        src_height, src_width = src.shape
        out_dtype = dst_dtype if dst_dtype else src_data.dtype

    # Destination transform: top-left = (x_sw, y_sw + ny*dy)
    dst_transform = from_bounds(x_sw, y_sw, x_sw + nx * dx,
                                y_sw + ny * dy, nx, ny)
    dst_crs = rasterio.crs.CRS.from_proj4(proj4)
    # Use -9999 sentinel for float types (DEM, soil) so uncovered cells are
    # distinguishable from real 0-elevation; keep 0 for integer types (land cover).
    is_float = out_dtype in [np.float32, np.float64, float]
    if is_float:
        dst = np.full((ny, nx), -9999.0, dtype=np.float32)
        _dst_nodata = -9999.0 if nodata is not None else None
    else:
        dst = np.zeros((ny, nx), dtype=out_dtype)
        _dst_nodata = 0 if nodata is not None else None

    reproject(
        source=src_data,
        destination=dst,
        src_transform=src_transform,
        src_crs=src_crs,
        dst_transform=dst_transform,
        dst_crs=dst_crs,
        resampling=resampling,
        src_nodata=nodata,
        dst_nodata=_dst_nodata,
    )

    return dst


def fill_nodata_cells(data, nodata_val=-9999.0):
    """Fill nodata cells with nearest valid neighbor using distance transform."""
    from scipy.ndimage import distance_transform_edt
    nodata_mask = data <= nodata_val + 1  # within 1 of sentinel
    if not nodata_mask.any():
        return data  # nothing to fill
    valid_mask = ~nodata_mask
    if not valid_mask.any():
        return data  # all nodata, can't fill
    # Find nearest valid cell for each nodata cell
    _, nearest_idx = distance_transform_edt(nodata_mask, return_distances=True,
                                            return_indices=True)
    filled = data.copy()
    filled[nodata_mask] = data[nearest_idx[0][nodata_mask],
                               nearest_idx[1][nodata_mask]]
    return filled


def compute_srtm_tiles(lat_min, lat_max, lon_min, lon_max):
    """Return list of SRTM tile names needed to cover the given extent."""
    import math
    tiles = []
    for lat in range(math.floor(lat_min), math.ceil(lat_max)):
        for lon in range(math.floor(lon_min), math.ceil(lon_max)):
            ns = f"N{lat:02d}" if lat >= 0 else f"S{abs(lat):02d}"
            ew = f"E{lon:03d}" if lon >= 0 else f"W{abs(lon):03d}"
            tiles.append(f"{ns}{ew}")
    return tiles


def validate_dem_coverage(hgt_m, lat_mass=None, lon_mass=None):
    """Validate DEM coverage after nodata filling. Warn if suspicious."""
    total = hgt_m.size
    # After fill, check if many cells still have near-zero values
    suspicious = (hgt_m <= 0.1).sum()
    if suspicious > total * 0.5:
        print(f"  [WARN] {suspicious}/{total} cells ({100*suspicious/total:.1f}%) "
              f"have elevation <= 0.1m -- check DEM coverage")
    # Report needed SRTM tiles if lat/lon are available
    if lat_mass is not None and lon_mass is not None:
        lat_min, lat_max = float(lat_mass.min()), float(lat_mass.max())
        lon_min, lon_max = float(lon_mass.min()), float(lon_mass.max())
        tiles = compute_srtm_tiles(lat_min, lat_max, lon_min, lon_max)
        print(f"  [INFO] Domain lat [{lat_min:.2f}, {lat_max:.2f}], "
              f"lon [{lon_min:.2f}, {lon_max:.2f}] "
              f"needs {len(tiles)} SRTM tiles")


def compute_mapfac_lambert(lat_deg, truelat1, truelat2):
    """
    Compute Lambert Conformal map scale factor at given latitude(s).

    The map-scale factor m for a secant Lambert cone is:
        m = cos(phi1) * t(phi)^n / (cos(phi) * t(phi1)^n)
    where t(phi) = tan(pi/4 - phi/2) and
        n = ln(cos(phi1)/cos(phi2)) / ln(t(phi2)/t(phi1))
    At the true latitudes, m = 1 by definition.
    """
    lat = np.deg2rad(np.asarray(lat_deg, dtype=np.float64))
    phi1 = np.deg2rad(truelat1)
    phi2 = np.deg2rad(truelat2)

    t_phi  = np.tan(np.pi / 4 - lat / 2)
    t_phi1 = np.tan(np.pi / 4 - phi1 / 2)
    t_phi2 = np.tan(np.pi / 4 - phi2 / 2)

    if abs(truelat1 - truelat2) < 1e-6:
        n = np.sin(phi1)
    else:
        n = (np.log(np.cos(phi1)) - np.log(np.cos(phi2))) / \
            (np.log(t_phi2) - np.log(t_phi1))

    mapfac = np.cos(phi1) * (t_phi1 ** n) / (np.cos(lat) * (t_phi ** n))

    return np.float32(mapfac)


def compute_rotation_angle(lon_deg, stand_lon, truelat1, truelat2):
    """
    Compute grid rotation angle (angle between grid-north and true-north).
    For Lambert Conformal:
        alpha = n * (lon - stand_lon)
    where n is the cone constant.
    Returns sin(alpha), cos(alpha).
    """
    phi1 = np.deg2rad(truelat1)
    phi2 = np.deg2rad(truelat2)

    if abs(truelat1 - truelat2) < 1e-6:
        n = np.sin(phi1)
    else:
        n = (np.log(np.cos(phi1)) - np.log(np.cos(phi2))) / \
            (np.log(np.tan(np.pi / 4 + phi2 / 2)) -
             np.log(np.tan(np.pi / 4 + phi1 / 2)))

    diff_lon = np.deg2rad(np.asarray(lon_deg, dtype=np.float64) - stand_lon)
    # Wrap to [-pi, pi]
    diff_lon = (diff_lon + np.pi) % (2 * np.pi) - np.pi
    # WRF convention: alpha = -n * (lon - stand_lon)
    # See WRF source module_llxy.F: the negative sign accounts for the
    # direction of convergence of meridians on a Lambert cone.
    alpha = -n * diff_lon
    return np.float32(np.sin(alpha)), np.float32(np.cos(alpha))


# ===================================================================
# Main
# ===================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Build geo_em.d01.nc for WRF-Hydro")
    parser.add_argument("--domain_json", required=True,
                        help="Domain definition JSON from define_lambert_domain.py")
    parser.add_argument("--dem_path", required=True,
                        help="DEM GeoTIFF path")
    parser.add_argument("--landcover_path", required=True,
                        help="UMD AVHRR land cover GeoTIFF")
    parser.add_argument("--hwsd_raster", required=True,
                        help="HWSD global raster (.bil)")
    parser.add_argument("--hwsd_mdb", required=True,
                        help="HWSD MDB database for soil properties")
    parser.add_argument("--output", default="geo_em.d01.nc",
                        help="Output NetCDF path")
    parser.add_argument("--basin_shp", default=None,
                        help="Basin shapefile (optional, for checking)")
    args = parser.parse_args()

    # ------------------------------------------------------------------
    # 0. Load domain definition
    # ------------------------------------------------------------------
    dom_path = Path(args.domain_json)
    if not dom_path.exists():
        sys.exit(f"ERROR: domain JSON not found: {dom_path}")
    with open(dom_path) as f:
        dom = json.load(f)

    cen_lat   = dom["cen_lat"]
    cen_lon   = dom["cen_lon"]
    truelat1  = dom["truelat1"]
    truelat2  = dom["truelat2"]
    stand_lon = dom["stand_lon"]
    dx        = dom["dx"]
    dy        = dom["dy"]
    e_we      = dom["e_we"]
    e_sn      = dom["e_sn"]
    x_sw      = dom["x_sw"]
    y_sw      = dom["y_sw"]
    proj4     = dom["proj4"]

    print(f"Domain: {e_we} x {e_sn} cells, dx={dx:.0f} m")
    print(f"  CEN_LAT={cen_lat:.6f}, CEN_LON={cen_lon:.6f}")
    print(f"  TRUELAT1={truelat1}, TRUELAT2={truelat2}, STAND_LON={stand_lon}")

    # Transformers
    to_lcc = Transformer.from_proj("EPSG:4326", proj4, always_xy=True)
    from_lcc = Transformer.from_proj(proj4, "EPSG:4326", always_xy=True)

    # ------------------------------------------------------------------
    # 1. Compute coordinate arrays for all stagger types
    # ------------------------------------------------------------------
    print("Computing coordinate grids...")

    # Mass grid centres: cell (i,j) has centre at
    #   x = x_sw + (i + 0.5) * dx,  y = y_sw + (j + 0.5) * dy
    # where i = 0..e_we-1 (west_east), j = 0..e_sn-1 (south_north)
    i_mass = np.arange(e_we, dtype=np.float64)
    j_mass = np.arange(e_sn, dtype=np.float64)
    x_mass = x_sw + (i_mass + 0.5) * dx  # shape (e_we,)
    y_mass = y_sw + (j_mass + 0.5) * dy  # shape (e_sn,)
    xx_mass, yy_mass = np.meshgrid(x_mass, y_mass)  # (e_sn, e_we)

    # U-stagger: half-cell offset in x (west_east_stag = e_we+1)
    i_u = np.arange(e_we + 1, dtype=np.float64)
    x_u = x_sw + i_u * dx
    xx_u, yy_u = np.meshgrid(x_u, y_mass)  # (e_sn, e_we+1)

    # V-stagger: half-cell offset in y (south_north_stag = e_sn+1)
    j_v = np.arange(e_sn + 1, dtype=np.float64)
    y_v = y_sw + j_v * dy
    xx_v, yy_v = np.meshgrid(x_mass, y_v)  # (e_sn+1, e_we)

    # Corner: stagger in both x and y
    xx_c, yy_c = np.meshgrid(x_u, y_v)  # (e_sn+1, e_we+1)

    # Inverse-project all to geographic (lon, lat)
    lon_mass, lat_mass = from_lcc.transform(xx_mass.ravel(), yy_mass.ravel())
    lon_mass = np.float32(np.array(lon_mass).reshape(e_sn, e_we))
    lat_mass = np.float32(np.array(lat_mass).reshape(e_sn, e_we))

    lon_u, lat_u = from_lcc.transform(xx_u.ravel(), yy_u.ravel())
    lon_u = np.float32(np.array(lon_u).reshape(e_sn, e_we + 1))
    lat_u = np.float32(np.array(lat_u).reshape(e_sn, e_we + 1))

    lon_v, lat_v = from_lcc.transform(xx_v.ravel(), yy_v.ravel())
    lon_v = np.float32(np.array(lon_v).reshape(e_sn + 1, e_we))
    lat_v = np.float32(np.array(lat_v).reshape(e_sn + 1, e_we))

    lon_c, lat_c = from_lcc.transform(xx_c.ravel(), yy_c.ravel())
    lon_c = np.float32(np.array(lon_c).reshape(e_sn + 1, e_we + 1))
    lat_c = np.float32(np.array(lat_c).reshape(e_sn + 1, e_we + 1))

    # ------------------------------------------------------------------
    # 2. Map scale factors
    # ------------------------------------------------------------------
    print("Computing map scale factors...")
    mf_mass = compute_mapfac_lambert(lat_mass, truelat1, truelat2)
    mf_u    = compute_mapfac_lambert(lat_u, truelat1, truelat2)
    mf_v    = compute_mapfac_lambert(lat_v, truelat1, truelat2)

    # ------------------------------------------------------------------
    # 3. Coriolis parameters
    # ------------------------------------------------------------------
    print("Computing Coriolis parameters...")
    lat_rad_mass = np.deg2rad(lat_mass)
    e_cor = np.float32(2.0 * OMEGA * np.cos(lat_rad_mass))
    f_cor = np.float32(2.0 * OMEGA * np.sin(lat_rad_mass))

    # ------------------------------------------------------------------
    # 4. Rotation angles
    # ------------------------------------------------------------------
    print("Computing rotation angles...")
    sin_alpha_m, cos_alpha_m = compute_rotation_angle(
        lon_mass, stand_lon, truelat1, truelat2)
    sin_alpha_u, cos_alpha_u = compute_rotation_angle(
        lon_u, stand_lon, truelat1, truelat2)
    sin_alpha_v, cos_alpha_v = compute_rotation_angle(
        lon_v, stand_lon, truelat1, truelat2)

    # ------------------------------------------------------------------
    # 5. Extract DEM --> HGT_M
    # ------------------------------------------------------------------
    print("Extracting DEM (HGT_M)...")
    dem_path = Path(args.dem_path)
    if not dem_path.exists():
        sys.exit(f"ERROR: DEM not found: {dem_path}")
    hgt_m = resample_raster_to_lcc(
        str(dem_path), proj4, x_sw, y_sw, e_we, e_sn, dx, dy,
        resampling=Resampling.bilinear, dst_dtype=np.float32)
    # Flip: rasterio puts row 0 at top, but WRF puts j=0 at south
    hgt_m = np.flipud(hgt_m)
    # Fill DEM nodata cells (-9999 sentinel) with nearest valid neighbor
    n_nodata = (hgt_m <= -9990).sum()
    if n_nodata > 0:
        print(f"  [WARN] DEM has {n_nodata} uncovered cells "
              f"({100*n_nodata/hgt_m.size:.1f}%), filling with nearest neighbor")
        hgt_m = fill_nodata_cells(hgt_m, nodata_val=-9999.0)
    # Clip negative elevations to 0
    hgt_m = np.maximum(hgt_m, 0.0).astype(np.float32)
    print(f"  HGT_M range: {hgt_m.min():.1f} - {hgt_m.max():.1f} m")
    validate_dem_coverage(hgt_m, lat_mass=lat_mass, lon_mass=lon_mass)

    # ------------------------------------------------------------------
    # 6. Extract land cover --> LU_INDEX + LANDUSEF
    # ------------------------------------------------------------------
    print("Extracting land cover (LU_INDEX, LANDUSEF)...")
    lc_path = Path(args.landcover_path)
    if not lc_path.exists():
        sys.exit(f"ERROR: Land cover not found: {lc_path}")

    # Resample using nearest-neighbour (categorical data)
    umd_raw = resample_raster_to_lcc(
        str(lc_path), proj4, x_sw, y_sw, e_we, e_sn, dx, dy,
        resampling=Resampling.nearest, dst_dtype=np.uint8)
    umd_raw = np.flipud(umd_raw)

    # Convert UMD -> USGS
    lu_index = np.zeros((e_sn, e_we), dtype=np.float32)
    for j in range(e_sn):
        for i in range(e_we):
            umd_val = int(umd_raw[j, i])
            lu_index[j, i] = UMD_TO_USGS.get(umd_val, ISWATER)

    # Compute fractional LANDUSEF: for single-source raster at native
    # resolution each cell gets 100% in the dominant category.
    # A more sophisticated approach would use sub-grid sampling.
    landusef = np.zeros((NUM_LAND_CAT, e_sn, e_we), dtype=np.float32)
    for j in range(e_sn):
        for i in range(e_we):
            cat = int(lu_index[j, i])
            if 1 <= cat <= NUM_LAND_CAT:
                landusef[cat - 1, j, i] = 1.0
            else:
                landusef[ISWATER - 1, j, i] = 1.0  # default to water

    # Validate fractional sums
    frac_sum = landusef.sum(axis=0)
    bad = np.abs(frac_sum - 1.0) > 0.01
    if bad.any():
        print(f"  WARNING: {bad.sum()} cells have LANDUSEF sum != 1.0, fixing...")
        # Assign to water where sum is 0
        zero_mask = frac_sum < 0.01
        landusef[ISWATER - 1][zero_mask] = 1.0
        lu_index[zero_mask] = ISWATER

    unique_lu, counts = np.unique(lu_index, return_counts=True)
    print(f"  LU_INDEX classes: {dict(zip(unique_lu.astype(int), counts))}")

    # ------------------------------------------------------------------
    # 7. LANDMASK
    # ------------------------------------------------------------------
    landmask = np.where(lu_index == ISWATER, 0.0, 1.0).astype(np.float32)
    print(f"  LANDMASK: {landmask.sum():.0f}/{landmask.size} land cells "
          f"({100*landmask.mean():.1f}%)")

    # ------------------------------------------------------------------
    # 8. Soil type --> SCT_DOM, SCB_DOM, SOILCTOP, SOILCBOT
    # ------------------------------------------------------------------
    print("Extracting soil type (SOILCTOP, SOILCBOT)...")
    hwsd_raster_path = Path(args.hwsd_raster)
    hwsd_mdb_path = Path(args.hwsd_mdb)

    if not hwsd_raster_path.exists():
        sys.exit(f"ERROR: HWSD raster not found: {hwsd_raster_path}")
    if not hwsd_mdb_path.exists():
        sys.exit(f"ERROR: HWSD MDB not found: {hwsd_mdb_path}")

    # Load HWSD MDB
    print("  Loading HWSD MDB database...")
    hwsd_db = load_hwsd_mdb(str(hwsd_mdb_path))
    if hwsd_db is None:
        print("  WARNING: Could not load HWSD MDB. Using default soil class 6 (Loam).")
        hwsd_db = {}
    else:
        print(f"  HWSD MDB loaded: {len(hwsd_db)} mapping units")

    # Resample HWSD MU_GLOBAL raster to LCC grid (nearest neighbour)
    mu_grid = resample_raster_to_lcc(
        str(hwsd_raster_path), proj4, x_sw, y_sw, e_we, e_sn, dx, dy,
        resampling=Resampling.nearest, dst_dtype=np.uint16)
    mu_grid = np.flipud(mu_grid)

    # Classify each cell
    sct_dom = np.full((e_sn, e_we), 6.0, dtype=np.float32)  # default Loam
    scb_dom = np.full((e_sn, e_we), 6.0, dtype=np.float32)
    soilctop = np.zeros((NUM_SOIL_CAT, e_sn, e_we), dtype=np.float32)
    soilcbot = np.zeros((NUM_SOIL_CAT, e_sn, e_we), dtype=np.float32)

    mdb_hits = 0
    for j in range(e_sn):
        for i in range(e_we):
            mu = int(mu_grid[j, i])
            if mu == 0 or lu_index[j, i] == ISWATER:
                # Water cell
                sct_dom[j, i] = ISOILWATER
                scb_dom[j, i] = ISOILWATER
                soilctop[ISOILWATER - 1, j, i] = 1.0
                soilcbot[ISOILWATER - 1, j, i] = 1.0
                continue

            row = hwsd_db.get(mu)
            if row:
                t_sand = _safe_float(row.get('T_SAND'))
                t_silt = _safe_float(row.get('T_SILT'))
                t_clay = _safe_float(row.get('T_CLAY'))
                s_sand = _safe_float(row.get('S_SAND'))
                s_silt = _safe_float(row.get('S_SILT'))
                s_clay = _safe_float(row.get('S_CLAY'))

                top_class = classify_usda_soil(t_sand, t_silt, t_clay)
                bot_class = classify_usda_soil(s_sand, s_silt, s_clay)

                # Validate range
                top_class = max(1, min(NUM_SOIL_CAT, top_class))
                bot_class = max(1, min(NUM_SOIL_CAT, bot_class))

                sct_dom[j, i] = top_class
                scb_dom[j, i] = bot_class
                soilctop[top_class - 1, j, i] = 1.0
                soilcbot[bot_class - 1, j, i] = 1.0
                mdb_hits += 1
            else:
                # Default: Loam (class 6)
                sct_dom[j, i] = 6
                scb_dom[j, i] = 6
                soilctop[5, j, i] = 1.0
                soilcbot[5, j, i] = 1.0

    # Validate: ensure fractional sum = 1
    for arr in [soilctop, soilcbot]:
        frac_sum = arr.sum(axis=0)
        zero_mask = frac_sum < 0.01
        if zero_mask.any():
            # Set to Loam where no data
            arr[5][zero_mask] = 1.0

    print(f"  HWSD MDB lookup: {mdb_hits}/{e_sn * e_we} cells have real soil properties")
    unique_sct, sct_counts = np.unique(sct_dom, return_counts=True)
    print(f"  SCT_DOM classes: {dict(zip(unique_sct.astype(int), sct_counts))}")

    # ------------------------------------------------------------------
    # 9. SOILTEMP (annual mean deep soil temperature in K)
    # ------------------------------------------------------------------
    print("Computing SOILTEMP...")
    # Empirical: T_soil ~ 288 - 6.5*(elev/1000) - 0.5*(|lat|-30)
    # Convert to Kelvin (add 273.15)
    soiltemp_c = 15.0 - 6.5 * (hgt_m / 1000.0) - 0.3 * np.abs(lat_mass - 30.0)
    soiltemp = np.float32(celsius_to_kelvin(soiltemp_c))
    # Water cells get 0
    soiltemp[landmask < 0.5] = 0.0
    print(f"  SOILTEMP range: {soiltemp[landmask > 0.5].min():.1f} - "
          f"{soiltemp[landmask > 0.5].max():.1f} K")

    # ------------------------------------------------------------------
    # 10. GREENFRAC + LAI12M from LUT
    # ------------------------------------------------------------------
    print("Computing GREENFRAC and LAI12M from LUT...")
    greenfrac = np.zeros((12, e_sn, e_we), dtype=np.float32)
    lai12m    = np.zeros((12, e_sn, e_we), dtype=np.float32)

    for j in range(e_sn):
        for i in range(e_we):
            cat = int(lu_index[j, i])
            gf_vals = _GF.get(cat, _GF[0])
            la_vals = _LAI.get(cat, _LAI[0])
            for m in range(12):
                greenfrac[m, j, i] = gf_vals[m]
                lai12m[m, j, i]    = la_vals[m]

    print(f"  GREENFRAC range: {greenfrac.min():.3f} - {greenfrac.max():.3f}")
    print(f"  LAI12M range: {lai12m.min():.3f} - {lai12m.max():.3f}")

    # ------------------------------------------------------------------
    # 11. Compute corner_lats / corner_lons global attributes
    #     16 values: 4 corners x 4 stagger types (mass, U, V, corner)
    # ------------------------------------------------------------------
    print("Computing corner_lats/corner_lons attributes...")

    def _grid_corners(lat_arr, lon_arr):
        """Return (SW, NW, NE, SE) lat/lon for a 2D grid."""
        return (
            [float(lat_arr[0, 0]), float(lat_arr[-1, 0]),
             float(lat_arr[-1, -1]), float(lat_arr[0, -1])],
            [float(lon_arr[0, 0]), float(lon_arr[-1, 0]),
             float(lon_arr[-1, -1]), float(lon_arr[0, -1])]
        )

    cl_mass, cn_mass = _grid_corners(lat_mass, lon_mass)
    cl_u, cn_u       = _grid_corners(lat_u, lon_u)
    cl_v, cn_v       = _grid_corners(lat_v, lon_v)
    cl_c, cn_c       = _grid_corners(lat_c, lon_c)

    corner_lats = np.float32(cl_mass + cl_u + cl_v + cl_c)
    corner_lons = np.float32(cn_mass + cn_u + cn_v + cn_c)

    # ------------------------------------------------------------------
    # 12. Write NetCDF
    # ------------------------------------------------------------------
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"\nWriting {out_path}...")

    ds = nc.Dataset(str(out_path), "w", format="NETCDF4_CLASSIC")

    # --- Dimensions ---
    ds.createDimension("Time", None)  # unlimited
    ds.createDimension("DateStrLen", 19)
    ds.createDimension("west_east", e_we)
    ds.createDimension("south_north", e_sn)
    ds.createDimension("south_north_stag", e_sn + 1)
    ds.createDimension("west_east_stag", e_we + 1)
    ds.createDimension("land_cat", NUM_LAND_CAT)
    ds.createDimension("soil_cat", NUM_SOIL_CAT)
    ds.createDimension("month", 12)

    # --- Global attributes (order matching reference) ---
    ds.TITLE = "OUTPUT FROM GEOGRID V4.2"
    ds.SIMULATION_START_DATE = "0000-00-00_00:00:00"
    ds.setncattr("WEST-EAST_GRID_DIMENSION", np.int32(e_we + 1))
    ds.setncattr("SOUTH-NORTH_GRID_DIMENSION", np.int32(e_sn + 1))
    ds.setncattr("BOTTOM-TOP_GRID_DIMENSION", np.int32(0))
    ds.setncattr("WEST-EAST_PATCH_START_UNSTAG", np.int32(1))
    ds.setncattr("WEST-EAST_PATCH_END_UNSTAG", np.int32(e_we))
    ds.setncattr("WEST-EAST_PATCH_START_STAG", np.int32(1))
    ds.setncattr("WEST-EAST_PATCH_END_STAG", np.int32(e_we + 1))
    ds.setncattr("SOUTH-NORTH_PATCH_START_UNSTAG", np.int32(1))
    ds.setncattr("SOUTH-NORTH_PATCH_END_UNSTAG", np.int32(e_sn))
    ds.setncattr("SOUTH-NORTH_PATCH_START_STAG", np.int32(1))
    ds.setncattr("SOUTH-NORTH_PATCH_END_STAG", np.int32(e_sn + 1))
    ds.GRIDTYPE = "C"
    ds.DX = np.float32(dx)
    ds.DY = np.float32(dy)
    ds.DYN_OPT = np.int32(2)
    ds.CEN_LAT = np.float32(cen_lat)
    ds.CEN_LON = np.float32(cen_lon)
    ds.TRUELAT1 = np.float32(truelat1)
    ds.TRUELAT2 = np.float32(truelat2)
    ds.MOAD_CEN_LAT = np.float32(cen_lat)
    ds.STAND_LON = np.float32(stand_lon)
    ds.POLE_LAT = np.float32(90.0)
    ds.POLE_LON = np.float32(0.0)
    ds.setncattr("corner_lats", corner_lats)
    ds.setncattr("corner_lons", corner_lons)
    ds.MAP_PROJ = np.int32(1)
    ds.MMINLU = "USGS"
    ds.NUM_LAND_CAT = np.int32(NUM_LAND_CAT)
    ds.ISWATER = np.int32(ISWATER)
    ds.ISLAKE = np.int32(ISLAKE)
    ds.ISICE = np.int32(ISICE)
    ds.ISURBAN = np.int32(ISURBAN)
    ds.ISOILWATER = np.int32(ISOILWATER)
    ds.setncattr("grid_id", np.int32(1))
    ds.setncattr("parent_id", np.int32(1))
    ds.setncattr("i_parent_start", np.int32(1))
    ds.setncattr("j_parent_start", np.int32(1))
    ds.setncattr("i_parent_end", np.int32(e_we + 1))
    ds.setncattr("j_parent_end", np.int32(e_sn + 1))
    ds.setncattr("parent_grid_ratio", np.int32(1))
    ds.setncattr("sr_x", np.int32(1))
    ds.setncattr("sr_y", np.int32(1))
    ds.setncattr("FLAG_MF_XY", np.int32(1))
    ds.setncattr("FLAG_LAI12M", np.int32(1))

    # --- Helper to create a variable with standard WRF attributes ---
    def _create_var(name, dims, data, units, description, stagger="M",
                    memory_order="XY "):
        v = ds.createVariable(name, "f4", dims, zlib=False)
        v.FieldType = np.int32(104)
        v.MemoryOrder = memory_order
        v.units = units
        v.description = description
        v.stagger = stagger
        v.sr_x = np.int32(1)
        v.sr_y = np.int32(1)
        v[:] = data
        return v

    # --- Times ---
    times_var = ds.createVariable("Times", "S1", ("Time", "DateStrLen"))
    time_str = "0000-00-00_00:00:00"
    for ci, ch in enumerate(time_str):
        times_var[0, ci] = ch

    # --- Coordinate variables ---
    _create_var("XLAT_M", ("Time", "south_north", "west_east"),
                lat_mass[np.newaxis, :, :],
                "degrees latitude", "Latitude on mass grid", "M")
    _create_var("XLONG_M", ("Time", "south_north", "west_east"),
                lon_mass[np.newaxis, :, :],
                "degrees longitude", "Longitude on mass grid", "M")

    _create_var("XLAT_V", ("Time", "south_north_stag", "west_east"),
                lat_v[np.newaxis, :, :],
                "degrees latitude", "Latitude on V grid", "V")
    _create_var("XLONG_V", ("Time", "south_north_stag", "west_east"),
                lon_v[np.newaxis, :, :],
                "degrees longitude", "Longitude on V grid", "V")

    _create_var("XLAT_U", ("Time", "south_north", "west_east_stag"),
                lat_u[np.newaxis, :, :],
                "degrees latitude", "Latitude on U grid", "U")
    _create_var("XLONG_U", ("Time", "south_north", "west_east_stag"),
                lon_u[np.newaxis, :, :],
                "degrees longitude", "Longitude on U grid", "U")

    # CLAT, CLONG = computational lat/lon on mass grid (same as XLAT_M, XLONG_M)
    _create_var("CLAT", ("Time", "south_north", "west_east"),
                lat_mass[np.newaxis, :, :],
                "degrees latitude", "Computational latitude on mass grid", "M")
    _create_var("CLONG", ("Time", "south_north", "west_east"),
                lon_mass[np.newaxis, :, :],
                "degrees longitude", "Computational longitude on mass grid", "M")

    # --- Map factors ---
    _create_var("MAPFAC_M", ("Time", "south_north", "west_east"),
                mf_mass[np.newaxis, :, :],
                "none", "Mapfactor on mass grid", "M")
    _create_var("MAPFAC_V", ("Time", "south_north_stag", "west_east"),
                mf_v[np.newaxis, :, :],
                "none", "Mapfactor on V grid", "V")
    _create_var("MAPFAC_U", ("Time", "south_north", "west_east_stag"),
                mf_u[np.newaxis, :, :],
                "none", "Mapfactor on U grid", "U")

    # MX, MY = directional map factors (isotropic for Lambert, same as M)
    _create_var("MAPFAC_MX", ("Time", "south_north", "west_east"),
                mf_mass[np.newaxis, :, :],
                "none", "Mapfactor (x-dir) on mass grid", "M")
    _create_var("MAPFAC_VX", ("Time", "south_north_stag", "west_east"),
                mf_v[np.newaxis, :, :],
                "none", "Mapfactor (x-dir) on V grid", "V")
    _create_var("MAPFAC_UX", ("Time", "south_north", "west_east_stag"),
                mf_u[np.newaxis, :, :],
                "none", "Mapfactor (x-dir) on U grid", "U")
    _create_var("MAPFAC_MY", ("Time", "south_north", "west_east"),
                mf_mass[np.newaxis, :, :],
                "none", "Mapfactor (y-dir) on mass grid", "M")
    _create_var("MAPFAC_VY", ("Time", "south_north_stag", "west_east"),
                mf_v[np.newaxis, :, :],
                "none", "Mapfactor (y-dir) on V grid", "V")
    _create_var("MAPFAC_UY", ("Time", "south_north", "west_east_stag"),
                mf_u[np.newaxis, :, :],
                "none", "Mapfactor (y-dir) on U grid", "U")

    # --- Coriolis ---
    _create_var("E", ("Time", "south_north", "west_east"),
                e_cor[np.newaxis, :, :],
                "-", "Coriolis E parameter", "M")
    _create_var("F", ("Time", "south_north", "west_east"),
                f_cor[np.newaxis, :, :],
                "-", "Coriolis F parameter", "M")

    # --- Rotation angles ---
    _create_var("SINALPHA", ("Time", "south_north", "west_east"),
                sin_alpha_m[np.newaxis, :, :],
                "none", "Sine of rotation angle", "M")
    _create_var("COSALPHA", ("Time", "south_north", "west_east"),
                cos_alpha_m[np.newaxis, :, :],
                "none", "Cosine of rotation angle", "M")

    # --- LANDMASK ---
    _create_var("LANDMASK", ("Time", "south_north", "west_east"),
                landmask[np.newaxis, :, :],
                "none", "Landmask : 1=land, 0=water", "M")

    # --- Corner coordinates ---
    _create_var("XLAT_C", ("Time", "south_north_stag", "west_east_stag"),
                lat_c[np.newaxis, :, :],
                "degrees latitude", "Latitude at grid cell corners", "CORNER")
    _create_var("XLONG_C", ("Time", "south_north_stag", "west_east_stag"),
                lon_c[np.newaxis, :, :],
                "degrees longitude", "Longitude at grid cell corners", "CORNER")

    # --- Rotation angles on U and V grids ---
    _create_var("SINALPHA_U", ("Time", "south_north", "west_east_stag"),
                sin_alpha_u[np.newaxis, :, :],
                "none", "Sine of rotation angle on U grid", "U")
    _create_var("COSALPHA_U", ("Time", "south_north", "west_east_stag"),
                cos_alpha_u[np.newaxis, :, :],
                "none", "Cosine of rotation angle on U grid", "U")
    _create_var("SINALPHA_V", ("Time", "south_north_stag", "west_east"),
                sin_alpha_v[np.newaxis, :, :],
                "none", "Sine of rotation angle on V grid", "V")
    _create_var("COSALPHA_V", ("Time", "south_north_stag", "west_east"),
                cos_alpha_v[np.newaxis, :, :],
                "none", "Cosine of rotation angle on V grid", "V")

    # --- LANDUSEF (fractional) ---
    _create_var("LANDUSEF", ("Time", "land_cat", "south_north", "west_east"),
                landusef[np.newaxis, :, :, :],
                "category", "2011 30 meter, USGS reclass", "M", "XYZ")

    # --- LU_INDEX (dominant) ---
    _create_var("LU_INDEX", ("Time", "south_north", "west_east"),
                lu_index[np.newaxis, :, :],
                "category", "Dominant category", "M")

    # --- HGT_M ---
    _create_var("HGT_M", ("Time", "south_north", "west_east"),
                hgt_m[np.newaxis, :, :],
                "meters MSL", "Topography height", "M")

    # --- SOILTEMP ---
    _create_var("SOILTEMP", ("Time", "south_north", "west_east"),
                soiltemp[np.newaxis, :, :],
                "Kelvin", "Annual mean deep soil temperature", "M")

    # --- SOILCTOP (fractional, 16 categories) ---
    _create_var("SOILCTOP", ("Time", "soil_cat", "south_north", "west_east"),
                soilctop[np.newaxis, :, :, :],
                "category", "16-category top-layer soil type", "M", "XYZ")

    # --- SCT_DOM ---
    _create_var("SCT_DOM", ("Time", "south_north", "west_east"),
                sct_dom[np.newaxis, :, :],
                "category", "Dominant category", "M")

    # --- SOILCBOT (fractional, 16 categories) ---
    _create_var("SOILCBOT", ("Time", "soil_cat", "south_north", "west_east"),
                soilcbot[np.newaxis, :, :, :],
                "category", "16-category bottom-layer soil type", "M", "XYZ")

    # --- SCB_DOM ---
    _create_var("SCB_DOM", ("Time", "south_north", "west_east"),
                scb_dom[np.newaxis, :, :],
                "category", "Dominant category", "M")

    # --- GREENFRAC (12 months) ---
    _create_var("GREENFRAC", ("Time", "month", "south_north", "west_east"),
                greenfrac[np.newaxis, :, :, :],
                "fraction", "MODIS FPAR", "M", "XYZ")

    # --- LAI12M (12 months) ---
    _create_var("LAI12M", ("Time", "month", "south_north", "west_east"),
                lai12m[np.newaxis, :, :, :],
                "m^2/m^2", "MODIS LAI", "M", "XYZ")

    ds.close()
    print(f"\ngeo_em.d01.nc written: {out_path}")
    print(f"  Dimensions: Time=1, south_north={e_sn}, west_east={e_we}")
    print(f"  Variables: {39} (matching WRF geogrid reference)")

    # ------------------------------------------------------------------
    # 13. Validate output
    # ------------------------------------------------------------------
    print("\n=== Validation ===")
    ds = nc.Dataset(str(out_path), "r")

    # Check dimensions
    expected_dims = {
        "Time": 1, "DateStrLen": 19,
        "west_east": e_we, "south_north": e_sn,
        "south_north_stag": e_sn + 1, "west_east_stag": e_we + 1,
        "land_cat": NUM_LAND_CAT, "soil_cat": NUM_SOIL_CAT, "month": 12
    }
    for dname, dsize in expected_dims.items():
        actual = len(ds.dimensions[dname])
        status = "OK" if actual == dsize else "FAIL"
        if status == "FAIL":
            print(f"  [{status}] dim {dname}: expected {dsize}, got {actual}")
        # Only print failures

    # Check critical attributes
    for attr in ["MAP_PROJ", "DX", "DY", "CEN_LAT", "CEN_LON",
                 "TRUELAT1", "TRUELAT2", "STAND_LON", "MMINLU",
                 "NUM_LAND_CAT", "ISWATER", "GRIDTYPE"]:
        if attr not in ds.ncattrs():
            print(f"  [FAIL] Missing global attribute: {attr}")

    # Check all 39 variables exist
    expected_vars = [
        "Times", "XLAT_M", "XLONG_M", "XLAT_V", "XLONG_V", "XLAT_U",
        "XLONG_U", "CLAT", "CLONG", "MAPFAC_M", "MAPFAC_V", "MAPFAC_U",
        "MAPFAC_MX", "MAPFAC_VX", "MAPFAC_UX", "MAPFAC_MY", "MAPFAC_VY",
        "MAPFAC_UY", "E", "F", "SINALPHA", "COSALPHA", "LANDMASK",
        "XLAT_C", "XLONG_C", "SINALPHA_U", "COSALPHA_U", "SINALPHA_V",
        "COSALPHA_V", "LANDUSEF", "LU_INDEX", "HGT_M", "SOILTEMP",
        "SOILCTOP", "SCT_DOM", "SOILCBOT", "SCB_DOM", "GREENFRAC", "LAI12M"
    ]
    missing_vars = [v for v in expected_vars if v not in ds.variables]
    if missing_vars:
        print(f"  [FAIL] Missing variables: {missing_vars}")
    else:
        print(f"  [OK] All {len(expected_vars)} variables present")

    # Check LANDUSEF and SOILCTOP fractional sums
    luf = ds.variables["LANDUSEF"][0]
    luf_sum = luf.sum(axis=0)
    if np.abs(luf_sum - 1.0).max() > 0.02:
        print(f"  [WARN] LANDUSEF fractional sum deviation: max={np.abs(luf_sum - 1.0).max():.4f}")
    else:
        print("  [OK] LANDUSEF fractions sum to 1.0")

    sct = ds.variables["SOILCTOP"][0]
    sct_sum = sct.sum(axis=0)
    if np.abs(sct_sum - 1.0).max() > 0.02:
        print(f"  [WARN] SOILCTOP fractional sum deviation: max={np.abs(sct_sum - 1.0).max():.4f}")
    else:
        print("  [OK] SOILCTOP fractions sum to 1.0")

    # Check mapfac range (should be ~0.9-1.1 for most domains)
    mf = ds.variables["MAPFAC_M"][0]
    if mf.min() < 0.5 or mf.max() > 2.0:
        print(f"  [WARN] MAPFAC_M range suspect: {mf.min():.4f} - {mf.max():.4f}")
    else:
        print(f"  [OK] MAPFAC_M range: {mf.min():.4f} - {mf.max():.4f}")

    # Check COSALPHA range (should be -1 to 1)
    ca = ds.variables["COSALPHA"][0]
    if ca.min() < -1.01 or ca.max() > 1.01:
        print(f"  [WARN] COSALPHA range: {ca.min():.4f} - {ca.max():.4f}")
    else:
        print(f"  [OK] COSALPHA range: {ca.min():.4f} - {ca.max():.4f}")

    # Check HGT_M has reasonable values
    hgt = ds.variables["HGT_M"][0]
    print(f"  [INFO] HGT_M range: {hgt.min():.1f} - {hgt.max():.1f} m")

    # Check SOILTEMP in Kelvin
    st = ds.variables["SOILTEMP"][0]
    land = ds.variables["LANDMASK"][0]
    st_land = st[land > 0.5]
    if len(st_land) > 0:
        if st_land.min() < 230 or st_land.max() > 310:
            print(f"  [WARN] SOILTEMP (land) range: {st_land.min():.1f} - {st_land.max():.1f} K")
        else:
            print(f"  [OK] SOILTEMP (land) range: {st_land.min():.1f} - {st_land.max():.1f} K")

    ds.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
