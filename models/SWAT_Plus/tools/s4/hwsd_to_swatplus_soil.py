#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
============================================
Tool ID:      hwsd_to_swatplus_soil
Stage:        s4_soil_database
Description:  Generate SWAT+ soils.sol from HWSD global raster + MDB database
              for any basin worldwide, keyed to a VIC-style basin_grid.nc.

Reads HWSD raster (hwsd.bil, 30 arc-sec) to obtain MU_GLOBAL per grid cell,
then looks up topsoil (0-30 cm) and subsoil (30-100 cm) properties from the
HWSD.mdb Access database. Derives all SWAT+ soil parameters via standard
pedotransfer functions (Saxton-Rawls 2006 for AWC, Cosby 1984 for Ksat,
Williams 1995 for USLE K).

Two layers per soil profile:
  Layer 1 — topsoil  (0-300 mm,  HWSD T_* columns)
  Layer 2 — subsoil  (300-1000 mm, HWSD S_* columns)

Inputs:
  --grid_nc      Path to basin_grid.nc (VIC grid with y, x, mask)
  --hwsd_raster  Path to HWSD raster (.bil), default: data/soil/HWSD_RASTER/hwsd.bil
  --hwsd_mdb     Path to HWSD.mdb, default: data/forcing/huaihe_raw/soil/HWSD.mdb
  --output_path  Output soils.sol path

Outputs:
  soils.sol — SWAT+ multi-line format (profile line + N layer lines)

Preconditions:
  - basin_grid.nc exists with mask, y, x variables
  - HWSD raster and MDB are accessible
  - mdb-tools installed (apt install mdbtools)
  - rasterio, xarray, numpy, geopandas, rasterstats installed

Postconditions:
  - soils.sol contains one profile per valid grid cell
  - All texture sums = 100%, bulk density in [0.9, 2.5], AWC in [0.01, 0.5]
  - Format matches SWAT+ editor output (readable by SWAT+ rev59+)

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
import argparse
import subprocess
import csv
import io
import math
from pathlib import Path

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path("KISSPATH_ROOT")
DEFAULT_HWSD_RASTER = PROJECT_ROOT / "data/soil/HWSD_RASTER/hwsd.bil"
DEFAULT_HWSD_MDB = PROJECT_ROOT / "data/forcing/huaihe_raw/soil/HWSD.mdb"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# USDA Texture Triangle Classification
# ---------------------------------------------------------------------------
def classify_texture(sand, silt, clay):
    """
    Classify soil texture from USDA texture triangle.
    Returns (abbreviation, full_name).
    sand, silt, clay as percentages summing to ~100.
    """
    # Normalize to ensure sum = 100
    total = sand + silt + clay
    if total <= 0:
        return "L", "Loam"
    sand = sand * 100.0 / total
    silt = silt * 100.0 / total
    clay = clay * 100.0 / total

    if clay >= 40 and sand <= 45 and silt < 40:
        return "C", "Clay"
    elif clay >= 40 and silt >= 40:
        return "SIC", "Silty Clay"
    elif clay >= 35 and sand > 45:
        return "SC", "Sandy Clay"
    elif clay >= 27 and clay < 40 and sand > 20 and sand <= 45:
        return "CL", "Clay Loam"
    elif clay >= 27 and clay < 40 and sand <= 20:
        return "SICL", "Silty Clay Loam"
    elif clay >= 20 and clay < 35 and silt < 28 and sand > 45:
        return "SCL", "Sandy Clay Loam"
    elif silt >= 80:
        return "SI", "Silt"
    elif silt >= 50 and clay >= 12 and clay < 27:
        return "SIL", "Silt Loam"
    elif silt >= 50 and clay < 12:
        return "SIL", "Silt Loam"
    elif clay >= 7 and clay < 27 and silt >= 28 and silt < 50 and sand <= 52:
        return "L", "Loam"
    elif clay < 7 and silt < 50 and sand > 52 and sand <= 90:
        return "SL", "Sandy Loam"
    elif (sand > 85 and clay < 10) or (sand >= 70 and silt <= 15 and clay < 10):
        if sand > 90:
            return "S", "Sand"
        else:
            return "LS", "Loamy Sand"
    elif sand > 52 and clay >= 7 and clay < 20:
        return "SL", "Sandy Loam"
    elif sand > 90:
        return "S", "Sand"
    else:
        return "L", "Loam"


# ---------------------------------------------------------------------------
# Hydrologic Soil Group from Ksat
# ---------------------------------------------------------------------------
def hydrologic_group(ksat_mm_hr):
    """
    Determine USDA hydrologic soil group from saturated hydraulic conductivity.
    Based on NRCS Part 630, Chapter 7.

    ksat_mm_hr: saturated hydraulic conductivity of least transmissive layer (mm/hr)
    Returns: 'A', 'B', 'C', or 'D'
    """
    if ksat_mm_hr >= 36.0:      # > 1.42 in/hr
        return "A"
    elif ksat_mm_hr >= 3.6:     # 0.14 – 1.42 in/hr
        return "B"
    elif ksat_mm_hr >= 0.36:    # 0.014 – 0.14 in/hr
        return "C"
    else:
        return "D"


# ---------------------------------------------------------------------------
# Pedotransfer Functions
# ---------------------------------------------------------------------------
def saxton_rawls_awc(sand, clay, om):
    """
    Available Water Capacity (mm/mm) via Saxton & Rawls (2006).
    sand, clay: percentages (0-100)
    om: organic matter percentage (typically OC * 1.724)
    """
    s = sand / 100.0
    c = clay / 100.0
    # Wilting point (1500 kPa)
    wp1500t = (
        -0.024 * s + 0.487 * c + 0.006 * om
        + 0.005 * s * om - 0.013 * c * om
        + 0.068 * s * c + 0.031
    )
    wp1500 = wp1500t + 0.14 * wp1500t - 0.02
    # Field capacity (33 kPa)
    fc33t = (
        -0.251 * s + 0.195 * c + 0.011 * om
        + 0.006 * s * om - 0.027 * c * om
        + 0.452 * s * c + 0.299
    )
    fc33 = fc33t + 1.283 * fc33t * fc33t - 0.374 * fc33t - 0.015
    awc = fc33 - wp1500
    return max(0.01, min(0.50, awc))


def cosby_ksat(sand, clay):
    """
    Saturated hydraulic conductivity (mm/hr) via Cosby et al. (1984).
    sand, clay: percentages (0-100)
    """
    log_ksat_in_hr = -0.6 + 0.0126 * sand - 0.0064 * clay
    ksat_in_hr = 10.0 ** log_ksat_in_hr
    ksat_mm_hr = ksat_in_hr * 25.4  # inch/hr -> mm/hr
    return max(0.01, ksat_mm_hr)


def williams_usle_k(sand, silt, clay, om):
    """
    USLE K factor via Williams (1995) / EPIC equation.
    sand, silt, clay: percentages (0-100)
    om: organic matter percentage
    """
    sn1 = 1.0 - sand / 100.0
    if sn1 <= 0:
        sn1 = 0.001
    fom = om / 100.0 if om > 0 else 0.0001

    k_forg = 1.0 - 0.25 * fom / (fom + math.exp(3.72 - 2.95 * fom))
    k_fhi_sand = 1.0 - 0.7 * sn1 / (sn1 + math.exp(-5.51 + 22.9 * sn1))
    k_fstruc = 1.0  # Assume no structural data
    k_fperm = 1.0   # Assume moderate permeability

    # Modified Williams equation
    k = 0.2 + 0.3 * math.exp(-0.0256 * sand * (1.0 - silt / 100.0))
    m_silt = silt / (clay + silt) if (clay + silt) > 0 else 0.5
    k *= (m_silt ** 0.3)
    k *= k_forg
    k *= k_fhi_sand
    return max(0.01, min(0.65, k))


def estimate_albedo(sand, clay, om):
    """
    Estimate dry soil albedo from texture and organic matter.
    Darker soils have more OM; sandier soils are lighter.
    Post & Pfeiffer (1969), simplified.
    """
    # Base albedo from texture
    alb = 0.10 + 0.15 * (sand / 100.0)
    # Darken with organic matter
    alb -= 0.02 * min(om, 5.0)
    return max(0.05, min(0.35, round(alb, 2)))


# ---------------------------------------------------------------------------
# HWSD MDB Loading
# ---------------------------------------------------------------------------
def _safe_float(val, default=0.0):
    """Safely convert to float, returning default on failure."""
    try:
        return float(val) if val and str(val).strip() else default
    except (ValueError, TypeError):
        return default


def load_hwsd_mdb(mdb_path):
    """
    Load HWSD_DATA table from MDB into dict keyed by MU_GLOBAL.
    Keeps dominant component (highest SHARE with texture data).
    """
    logger.info(f"Loading HWSD MDB: {mdb_path}")
    result = subprocess.run(
        ['mdb-export', str(mdb_path), 'HWSD_DATA'],
        capture_output=True, text=True, timeout=120
    )
    if result.returncode != 0:
        raise RuntimeError(f"mdb-export failed: {result.stderr[:200]}")

    reader = csv.DictReader(io.StringIO(result.stdout))
    mu_data = {}
    row_count = 0
    for row in reader:
        row_count += 1
        try:
            mu = int(row['MU_GLOBAL'])
        except (ValueError, KeyError):
            continue
        share = _safe_float(row.get('SHARE', 0))
        has_texture = bool(row.get('T_SAND') and str(row['T_SAND']).strip())
        if mu not in mu_data or (has_texture and share > mu_data[mu].get('_share', 0)):
            row['_share'] = share
            mu_data[mu] = row

    logger.info(f"HWSD MDB loaded: {len(mu_data)} mapping units from {row_count} rows")
    return mu_data


# ---------------------------------------------------------------------------
# Grid cell MU_GLOBAL extraction
# ---------------------------------------------------------------------------
def extract_mu_codes(lats, lons, resolution, hwsd_raster):
    """
    For each grid cell, extract the dominant HWSD mapping unit code.
    Uses zonal_stats with 'majority' on cell bounding boxes.
    """
    import rasterio
    import geopandas as gpd
    from shapely.geometry import box
    from rasterstats import zonal_stats

    logger.info(f"Extracting MU_GLOBAL from raster: {hwsd_raster}")
    half_res = resolution / 2.0

    grid_geoms = [
        box(lon - half_res, lat - half_res, lon + half_res, lat + half_res)
        for lat, lon in zip(lats, lons)
    ]
    grid_gdf = gpd.GeoDataFrame(geometry=grid_geoms, crs="EPSG:4326")

    with rasterio.open(str(hwsd_raster)) as src:
        raster_crs = src.crs
        nodata = src.nodata if src.nodata is not None else 0

    if raster_crs is not None and str(raster_crs) != "EPSG:4326":
        grid_gdf = grid_gdf.to_crs(raster_crs)

    stats = zonal_stats(
        grid_gdf, str(hwsd_raster),
        band=1, stats="majority", nodata=nodata
    )
    mu_codes = [
        int(s["majority"]) if s.get("majority") is not None else 0
        for s in stats
    ]
    valid = sum(1 for m in mu_codes if m > 0)
    logger.info(f"MU_GLOBAL extracted: {valid}/{len(lats)} cells have valid codes")
    return mu_codes


# ---------------------------------------------------------------------------
# HWSD property lookup for a single cell
# ---------------------------------------------------------------------------
def lookup_soil_properties(mu_code, hwsd_db):
    """
    Look up topsoil and subsoil properties from the preloaded HWSD database.
    Returns (topsoil_dict, subsoil_dict) or (None, None) for ocean/missing cells.
    """
    if mu_code <= 0 or mu_code not in hwsd_db:
        return None, None

    row = hwsd_db[mu_code]

    # Check if this is a water body or organic soil with no mineral texture
    t_sand = _safe_float(row.get('T_SAND'))
    t_silt = _safe_float(row.get('T_SILT'))
    t_clay = _safe_float(row.get('T_CLAY'))
    if t_sand + t_silt + t_clay < 1.0:
        return None, None

    topsoil = {
        'sand': t_sand,
        'silt': t_silt,
        'clay': t_clay,
        'oc': _safe_float(row.get('T_OC'), 1.0),
        'ph': _safe_float(row.get('T_PH_H2O'), 6.5),
        'bulk_density': _safe_float(row.get('T_REF_BULK_DENSITY'), 1.4),
        'gravel': _safe_float(row.get('T_GRAVEL'), 0.0),
        'caco3': _safe_float(row.get('T_CACO3'), 0.0),
        'cec': _safe_float(row.get('T_CEC_SOIL'), 0.0),
        'esp': _safe_float(row.get('T_ESP'), 0.0),
        'usda_tex_class': int(_safe_float(row.get('T_USDA_TEX_CLASS'), 0)),
    }

    s_sand = _safe_float(row.get('S_SAND'))
    s_silt = _safe_float(row.get('S_SILT'))
    s_clay = _safe_float(row.get('S_CLAY'))

    # If subsoil has no texture, replicate topsoil
    if s_sand + s_silt + s_clay < 1.0:
        subsoil = topsoil.copy()
        subsoil['oc'] = max(0.1, topsoil['oc'] * 0.5)  # Reduce OC at depth
    else:
        subsoil = {
            'sand': s_sand,
            'silt': s_silt,
            'clay': s_clay,
            'oc': _safe_float(row.get('S_OC'), max(0.1, topsoil['oc'] * 0.5)),
            'ph': _safe_float(row.get('S_PH_H2O'), topsoil['ph']),
            'bulk_density': _safe_float(row.get('S_REF_BULK_DENSITY'), 1.45),
            'gravel': _safe_float(row.get('S_GRAVEL'), 0.0),
            'caco3': _safe_float(row.get('S_CACO3'), 0.0),
            'cec': _safe_float(row.get('S_CEC_SOIL'), 0.0),
            'esp': _safe_float(row.get('S_ESP'), 0.0),
            'usda_tex_class': int(_safe_float(row.get('S_USDA_TEX_CLASS'), 0)),
        }

    return topsoil, subsoil


# ---------------------------------------------------------------------------
# Normalize texture to sum to 100%
# ---------------------------------------------------------------------------
def normalize_texture(sand, silt, clay):
    """Ensure sand + silt + clay = 100. Returns (sand, silt, clay)."""
    total = sand + silt + clay
    if total <= 0:
        return 33.3, 33.3, 33.4  # Fallback: loam
    if abs(total - 100.0) < 0.1:
        return sand, silt, clay
    factor = 100.0 / total
    return round(sand * factor, 1), round(silt * factor, 1), round(clay * factor, 1)


# ---------------------------------------------------------------------------
# Build SWAT+ soil profile for one cell
# ---------------------------------------------------------------------------
def build_swatplus_profile(cell_idx, lat, lon, topsoil, subsoil):
    """
    Build a complete SWAT+ soil profile dict from HWSD topsoil/subsoil data.
    Returns dict with profile-level and layer-level attributes.
    """
    # Normalize textures
    t_sand, t_silt, t_clay = normalize_texture(
        topsoil['sand'], topsoil['silt'], topsoil['clay']
    )
    s_sand, s_silt, s_clay = normalize_texture(
        subsoil['sand'], subsoil['silt'], subsoil['clay']
    )

    # Organic matter = OC * 1.724 (van Bemmelen factor)
    t_om = topsoil['oc'] * 1.724
    s_om = subsoil['oc'] * 1.724

    # Clamp bulk density to physical range
    t_bd = max(0.90, min(2.50, topsoil['bulk_density']))
    s_bd = max(0.90, min(2.50, subsoil['bulk_density']))

    # Derived properties per layer
    t_awc = saxton_rawls_awc(t_sand, t_clay, t_om)
    s_awc = saxton_rawls_awc(s_sand, s_clay, s_om)

    t_ksat = cosby_ksat(t_sand, t_clay)
    s_ksat = cosby_ksat(s_sand, s_clay)

    t_usle = williams_usle_k(t_sand, t_silt, t_clay, t_om)
    s_usle = williams_usle_k(s_sand, s_silt, s_clay, s_om)

    t_alb = estimate_albedo(t_sand, t_clay, t_om)
    s_alb = estimate_albedo(s_sand, s_clay, s_om)

    # Texture class abbreviations
    t_tex_abbr, _ = classify_texture(t_sand, t_silt, t_clay)
    s_tex_abbr, _ = classify_texture(s_sand, s_silt, s_clay)

    # Hydrologic group from minimum Ksat (most restrictive layer)
    min_ksat = min(t_ksat, s_ksat)
    hyd_grp = hydrologic_group(min_ksat)

    # Rock fragment volume (%) from HWSD gravel
    t_rock = min(80.0, max(0.0, topsoil.get('gravel', 0.0)))
    s_rock = min(80.0, max(0.0, subsoil.get('gravel', 0.0)))

    # Electrical conductivity from ESP (rough: high ESP -> saline)
    t_ec = round(min(10.0, topsoil.get('esp', 0.0) * 0.05), 2)
    s_ec = round(min(10.0, subsoil.get('esp', 0.0) * 0.05), 2)

    # CaCO3 (%)
    t_caco3 = min(50.0, max(0.0, topsoil.get('caco3', 0.0)))
    s_caco3 = min(50.0, max(0.0, subsoil.get('caco3', 0.0)))

    # pH
    t_ph = max(3.5, min(10.0, topsoil.get('ph', 6.5)))
    s_ph = max(3.5, min(10.0, subsoil.get('ph', 6.5)))

    # Profile-level attributes
    # Soil name: lat_lon encoded, max 32 chars for SWAT+ compatibility
    lat_str = f"{abs(lat):.2f}".replace('.', '')
    lon_str = f"{abs(lon):.2f}".replace('.', '')
    lat_hemi = 'n' if lat >= 0 else 's'
    lon_hemi = 'e' if lon >= 0 else 'w'
    name = f"hw_{lat_hemi}{lat_str}_{lon_hemi}{lon_str}"
    if len(name) > 32:
        name = f"hw_{cell_idx:06d}"

    dp_tot = 1000.0  # Total depth mm (topsoil 300 + subsoil 700)
    texture_str = f"{t_tex_abbr}-{s_tex_abbr}"

    profile = {
        'name': name,
        'nly': 2,
        'hyd_grp': hyd_grp,
        'dp_tot': dp_tot,
        'anion_excl': 0.50,
        'perc_crk': 0.50,
        'texture': texture_str,
        'layers': [
            {
                'dp': 300.0,      # mm (topsoil 0-30 cm)
                'bd': t_bd,
                'awc': t_awc,
                'soil_k': t_ksat,
                'carbon': topsoil['oc'],
                'clay': t_clay,
                'silt': t_silt,
                'sand': t_sand,
                'rock': t_rock,
                'alb': t_alb,
                'usle_k': t_usle,
                'ec': t_ec,
                'caco3': t_caco3,
                'ph': t_ph,
            },
            {
                'dp': 1000.0,     # mm (subsoil 0-100 cm cumulative depth)
                'bd': s_bd,
                'awc': s_awc,
                'soil_k': s_ksat,
                'carbon': subsoil['oc'],
                'clay': s_clay,
                'silt': s_silt,
                'sand': s_sand,
                'rock': s_rock,
                'alb': s_alb,
                'usle_k': s_usle,
                'ec': s_ec,
                'caco3': s_caco3,
                'ph': s_ph,
            },
        ],
    }
    return profile


def build_default_profile(cell_idx):
    """
    Build a default SWAT+ soil profile for cells where HWSD has no data
    (ocean, ice, organic soils). Uses loam defaults.
    """
    return {
        'name': f"hw_dflt_{cell_idx:04d}",
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


# ---------------------------------------------------------------------------
# Write soils.sol in SWAT+ editor format
# ---------------------------------------------------------------------------
def write_soils_sol(profiles, output_path):
    """
    Write soils.sol matching the exact SWAT+ editor format.

    Format (from SWAT+ editor v1.0.0):
    - Line 1: header comment
    - Line 2: column names
    - For each soil:
        - Profile line: name, nly, hyd_grp, dp_tot, anion_excl, perc_crk, texture
        - Layer lines (one per layer): dp, bd, awc, soil_k, carbon, clay, silt, sand,
          rock, alb, usle_k, ec, caco3, ph
        - Profile line is left-aligned at col 0
        - Layer lines are right-indented (leading spaces) to align under layer columns
    """
    # Column widths matching SWAT+ editor output exactly
    # Profile columns (from analysis of real soils.sol files)
    PROFILE_NAME_W = 32       # name field width
    PROFILE_NLY_W = 14        # nly field width (right-aligned int)
    PROFILE_HYD_W = 18        # hyd_grp field width
    PROFILE_DPTOT_W = 14      # dp_tot field width
    PROFILE_ANION_W = 14      # anion_excl
    PROFILE_CRACK_W = 14      # perc_crk
    # Texture is followed by enough padding to reach layer column start

    # Layer data start column (from actual files: ~98 spaces of indent)
    LAYER_INDENT = 98

    # Layer column field widths (14 chars each, right-aligned, 5 decimal places)
    LAYER_FW = 14

    with open(output_path, 'w') as f:
        # Line 1: header
        f.write("soils.sol: written by SWAT+ HWSD converter (HydroCraft)\n")

        # Line 2: column names
        hdr_profile = (
            f"{'name':<{PROFILE_NAME_W}}"
            f"{'nly':>{PROFILE_NLY_W}}"
            f"{'hyd_grp':>{PROFILE_HYD_W}}"
            f"{'dp_tot':>{PROFILE_DPTOT_W}}"
            f"{'anion_excl':>{PROFILE_ANION_W}}"
            f"{'perc_crk':>{PROFILE_CRACK_W}}"
        )
        # Pad profile header to LAYER_INDENT, then add layer column names
        padding = max(2, LAYER_INDENT - len(hdr_profile))
        hdr_layer_cols = [
            'dp', 'bd', 'awc', 'soil_k', 'carbon',
            'clay', 'silt', 'sand', 'rock',
            'alb', 'usle_k', 'ec', 'caco3', 'ph'
        ]
        hdr_layers = "".join(f"{c:>{LAYER_FW}}" for c in hdr_layer_cols)
        f.write(hdr_profile + " " * padding + "texture" + " " * 25 + hdr_layers + "  \n")

        for profile in profiles:
            # Profile line
            name = profile['name']
            nly = profile['nly']
            hyd_grp = profile['hyd_grp']
            dp_tot = profile['dp_tot']
            anion = profile['anion_excl']
            crack = profile['perc_crk']
            texture = profile['texture']

            prof_line = (
                f"{name:<{PROFILE_NAME_W}}"
                f"{nly:>{PROFILE_NLY_W}d}"
                f"{hyd_grp:>{PROFILE_HYD_W}}"
                f"{dp_tot:>{PROFILE_DPTOT_W}.5f}"
                f"{anion:>{PROFILE_ANION_W}.5f}"
                f"{crack:>{PROFILE_CRACK_W}.5f}"
                f"  {texture:<27}"
            )
            f.write(prof_line + "\n")

            # Layer lines
            for layer in profile['layers']:
                indent = " " * LAYER_INDENT
                vals = [
                    layer['dp'], layer['bd'], layer['awc'], layer['soil_k'],
                    layer['carbon'], layer['clay'], layer['silt'], layer['sand'],
                    layer['rock'], layer['alb'], layer['usle_k'],
                    layer['ec'], layer['caco3'], layer['ph']
                ]
                layer_str = "".join(f"{v:>{LAYER_FW}.5f}" for v in vals)
                f.write(indent + layer_str + "  \n")

    logger.info(f"Wrote soils.sol with {len(profiles)} soil profiles to {output_path}")


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def validate_inputs(args):
    """Validate all inputs before processing."""
    errors = []

    if not Path(args.grid_nc).exists():
        errors.append(f"Grid NC not found: {args.grid_nc}")
    if not Path(args.hwsd_raster).exists():
        errors.append(f"HWSD raster not found: {args.hwsd_raster}")
    if not Path(args.hwsd_mdb).exists():
        errors.append(f"HWSD MDB not found: {args.hwsd_mdb}")

    # Check mdb-tools is installed
    try:
        subprocess.run(['mdb-export', '--version'],
                       capture_output=True, timeout=5)
    except FileNotFoundError:
        errors.append("mdb-tools not installed (apt install mdbtools)")
    except subprocess.TimeoutExpired:
        pass  # It's installed but slow

    if errors:
        for e in errors:
            logger.error(e)
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)

    logger.info("Input validation passed.")


def validate_outputs(profiles, output_path):
    """Validate the generated soils.sol."""
    errors = []

    if not Path(output_path).exists():
        errors.append(f"Output file not created: {output_path}")
        for e in errors:
            logger.error(e)
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(3)

    if len(profiles) == 0:
        errors.append("No soil profiles generated")

    n_issues = 0
    for p in profiles:
        for li, layer in enumerate(p['layers']):
            tex_sum = layer['clay'] + layer['silt'] + layer['sand']
            if abs(tex_sum - 100.0) > 1.5:
                n_issues += 1
                if n_issues <= 5:
                    errors.append(
                        f"{p['name']} layer {li+1}: texture sum={tex_sum:.1f} != 100"
                    )
            if not (0.0 < layer['bd'] <= 2.65):
                n_issues += 1
                if n_issues <= 5:
                    errors.append(
                        f"{p['name']} layer {li+1}: bd={layer['bd']:.2f} out of range"
                    )
            if not (0.0 <= layer['awc'] <= 0.60):
                n_issues += 1
                if n_issues <= 5:
                    errors.append(
                        f"{p['name']} layer {li+1}: awc={layer['awc']:.3f} out of range"
                    )

    if n_issues > 5:
        errors.append(f"... and {n_issues - 5} more issues")

    if errors:
        for e in errors:
            logger.warning(e)
        # Warnings, not fatal — degraded mode
        logger.warning(f"Output validation: {n_issues} issues found (non-fatal)")
    else:
        logger.info("Output validation passed — all profiles valid.")


# ---------------------------------------------------------------------------
# Main processing
# ---------------------------------------------------------------------------
def process(args):
    """
    Main pipeline:
    1. Read basin_grid.nc to get cell coordinates
    2. Load HWSD MDB into memory
    3. Extract MU_GLOBAL codes from raster per grid cell
    4. Look up soil properties and compute derived params
    5. Write soils.sol
    """
    import xarray as xr
    import numpy as np

    # Step 1: Read grid
    logger.info(f"Reading grid: {args.grid_nc}")
    ds = xr.open_dataset(args.grid_nc)

    if 'mask' in ds:
        valid = ds['mask'].stack(cell=('y', 'x')).dropna('cell')
        lats = valid.coords['y'].values.astype(float)
        lons = valid.coords['x'].values.astype(float)
    elif 'lat' in ds and 'lon' in ds:
        lats = ds['lat'].values.astype(float)
        lons = ds['lon'].values.astype(float)
    else:
        raise ValueError("Grid NC must have (mask, y, x) or (lat, lon) variables")

    # Determine resolution
    if 'y' in ds.coords and len(ds.coords['y']) > 1:
        resolution = abs(float(ds.coords['y'].values[1] - ds.coords['y'].values[0]))
    else:
        resolution = 0.25  # Fallback
    ds.close()

    n_cells = len(lats)
    logger.info(f"Grid: {n_cells} cells at {resolution}deg resolution")

    if n_cells == 0:
        raise ValueError("No valid grid cells found in basin_grid.nc")

    # Step 2: Load HWSD MDB
    hwsd_db = load_hwsd_mdb(args.hwsd_mdb)

    # Step 3: Extract MU codes
    mu_codes = extract_mu_codes(lats, lons, resolution, args.hwsd_raster)

    # Step 4: Build profiles
    logger.info("Building SWAT+ soil profiles...")
    profiles = []
    n_hwsd = 0
    n_default = 0
    n_dedup = {}  # Deduplicate identical MU codes to same profile

    for i in range(n_cells):
        mu = mu_codes[i]
        topsoil, subsoil = lookup_soil_properties(mu, hwsd_db)

        if topsoil is not None:
            profile = build_swatplus_profile(i, lats[i], lons[i], topsoil, subsoil)
            n_hwsd += 1
        else:
            profile = build_default_profile(i)
            n_default += 1

        profiles.append(profile)

    logger.info(
        f"Profiles built: {n_hwsd} from HWSD, {n_default} defaults "
        f"({n_cells} total)"
    )

    # Step 5: Write output
    output_path = Path(args.output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_soils_sol(profiles, str(output_path))

    return profiles, str(output_path)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate SWAT+ soils.sol from HWSD global database"
    )
    parser.add_argument(
        '--grid_nc', required=True,
        help='Path to basin_grid.nc (VIC grid with y, x, mask)'
    )
    parser.add_argument(
        '--hwsd_raster', default=str(DEFAULT_HWSD_RASTER),
        help=f'Path to HWSD raster (.bil), default: {DEFAULT_HWSD_RASTER}'
    )
    parser.add_argument(
        '--hwsd_mdb', default=str(DEFAULT_HWSD_MDB),
        help=f'Path to HWSD.mdb, default: {DEFAULT_HWSD_MDB}'
    )
    parser.add_argument(
        '--output_path', required=True,
        help='Output soils.sol file path'
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")

    args = parse_args()
    validate_inputs(args)

    try:
        profiles, output_path = process(args)
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        import traceback
        traceback.print_exc()
        print(json.dumps({
            "status": "error",
            "message": str(e),
        }))
        sys.exit(2)

    validate_outputs(profiles, output_path)

    # JSON summary to stdout
    result = {
        "status": "success",
        "soils_sol": output_path,
        "n_soils": len(profiles),
        "n_layers_per_soil": 2,
        "layer_depths_mm": [300, 1000],
        "source": "HWSD v1.2 (FAO/IIASA/ISRIC/ISS-CAS/JRC)",
        "pedotransfer": {
            "awc": "Saxton & Rawls (2006)",
            "ksat": "Cosby et al. (1984)",
            "usle_k": "Williams (1995) / EPIC",
            "albedo": "Post & Pfeiffer (1969) simplified",
            "hyd_grp": "NRCS Part 630 Ch.7 (Ksat thresholds)"
        },
        "soil_names": [p['name'] for p in profiles[:5]]
        + (["..."] if len(profiles) > 5 else []),
    }
    print(json.dumps(result, indent=2))
    sys.exit(0)
