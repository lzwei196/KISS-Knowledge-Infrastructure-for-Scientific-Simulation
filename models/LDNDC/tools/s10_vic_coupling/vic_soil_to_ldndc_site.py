#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
Tool ID:      vic_soil_to_ldndc_site
Stage:        s10_vic_coupling
Description:  Convert VIC soil parameter file + HWSD properties to LDNDC site.xml.

              VIC provides: layer depths, Ksat (mm/day)
              HWSD provides: sand%, clay%, bulk density, organic carbon%, pH, gravel%
              Pedotransfer: Saxton-Rawls (2006) for wc_fc and wc_wp

CRITICAL unit conversions (dt_015):
  - HWSD OC is in percentage → divide by 100 for LDNDC corg fraction
  - HWSD bulk density in kg/m³ → divide by 1000 for g/cm³
  - VIC Ksat in mm/day → divide by 86,400,000 for sks in m/s
  - VIC layer depths in metres; LDNDC site.xml depth in mm

VIC soil parameter file columns (0-indexed):
  0:run, 1:id, 2:lat, 3:lon, 4:infilt, 5:Ds, 6:Dsmax, 7:Ws, 8:c,
  9-11:expt(3), 12-14:Ksat_mm_day(3), 15-17:phi_s(3), 18-20:init_moist(3),
  21:elev, 22-24:depth_m(3), 25:avg_T, 26:dp, 27-29:bubble(3), 30-32:quartz(3)

Inputs (set below or pass as CLI args):
  VIC_SOIL_FILE  : path to VIC SOIL_PARAM_COMPLETE.txt
  LAT, LON       : target grid cell coordinates
  OUTPUT_PATH    : output site.xml path
  HWSD_RASTER    : path to HWSD global raster (hwsd.bil)  [optional]
  HWSD_MDB       : path to HWSD MDB database              [optional]

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import json
import logging
import subprocess
import csv
from io import StringIO
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
VIC_SOIL_FILE = ""        # e.g., "outputs/hefei_2000-2001/vic_temp/soil/SOIL_PARAM_COMPLETE.txt"
LAT = 0.0                 # e.g., 31.1250
LON = 0.0                 # e.g., 116.6250
OUTPUT_PATH = ""          # e.g., "outputs/chaohu/ldndc/site.xml"
HWSD_RASTER = "data/soil/HWSD_RASTER/hwsd.bil"
HWSD_MDB    = "data/forcing/huaihe_raw/soil/HWSD.mdb"

# Override from CLI
if len(sys.argv) >= 5:
    VIC_SOIL_FILE = sys.argv[1]
    LAT           = float(sys.argv[2])
    LON           = float(sys.argv[3])
    OUTPUT_PATH   = sys.argv[4]
if len(sys.argv) >= 6:
    HWSD_RASTER = sys.argv[5]
if len(sys.argv) >= 7:
    HWSD_MDB = sys.argv[6]

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pedotransfer functions — Saxton & Rawls (2006)
# ---------------------------------------------------------------------------

def saxton_rawls_fc_wp(sand_frac, clay_frac, oc_pct):
    """
    Compute field capacity and wilting point using Saxton & Rawls (2006).
    sand_frac, clay_frac: 0-1 fractions
    oc_pct: organic carbon % (0-60)
    Returns: (theta_fc, theta_wp) as volumetric fractions (cm3/cm3)
    """
    S   = sand_frac
    C   = clay_frac
    OM  = oc_pct * 1.724  # OC% -> OM%

    # Wilting point (1500 kPa)
    theta_wp = (-0.024 * S + 0.487 * C + 0.006 * OM
                + 0.005 * S * OM - 0.013 * C * OM
                + 0.068 * S * C + 0.031)
    theta_wp = theta_wp + (0.14 * theta_wp - 0.02)

    # Field capacity (33 kPa)
    theta_fc = (-0.251 * S + 0.195 * C + 0.011 * OM
                + 0.006 * S * OM - 0.027 * C * OM
                + 0.452 * S * C + 0.299)
    theta_fc = theta_fc + (1.283 * theta_fc**2 - 0.374 * theta_fc - 0.015)

    theta_wp = min(0.5,  max(0.01, theta_wp))
    theta_fc = min(0.6,  max(theta_wp + 0.01, theta_fc))
    return theta_fc, theta_wp


def texture_class(sand_pct, clay_pct):
    """Return USDA texture class name."""
    silt_pct = 100 - sand_pct - clay_pct
    if clay_pct >= 40:
        return "CLAY"
    elif clay_pct >= 27 and silt_pct <= 40:
        return "CLAY-LOAM" if sand_pct <= 45 else "SANDY-CLAY"
    elif sand_pct >= 70 and clay_pct <= 15:
        return "SANDY-LOAM" if clay_pct > 7 else "SAND"
    elif silt_pct >= 80:
        return "SILT" if clay_pct < 12 else "SILT-LOAM"
    else:
        return "LOAM"


# ---------------------------------------------------------------------------
# HWSD lookup
# ---------------------------------------------------------------------------

def _load_hwsd_mdb(mdb_path):
    """Load HWSD_DATA from MDB via mdb-export (mdbtools)."""
    try:
        result = subprocess.run(
            ["mdb-export", str(mdb_path), "HWSD_DATA"],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            return None
        reader = csv.DictReader(StringIO(result.stdout))
        db = {}
        for row in reader:
            try:
                mu = int(float(row.get("MU_GLOBAL", 0)))
                db[mu] = row
            except (ValueError, TypeError):
                pass
        return db if db else None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def _f(val, default):
    try:
        v = float(val)
        return default if (v != v) else v   # NaN -> default
    except (TypeError, ValueError):
        return default


def lookup_hwsd(lat, lon):
    """Query HWSD raster+MDB. Returns row dict or None."""
    raster_path = Path(HWSD_RASTER)
    mdb_path    = Path(HWSD_MDB)
    if not raster_path.exists() or not mdb_path.exists():
        logger.warning("HWSD raster or MDB not available — using default soil")
        return None
    try:
        import rasterio
        with rasterio.open(str(raster_path)) as src:
            row, col = src.index(lon, lat)
            window = rasterio.windows.Window(col, row, 1, 1)
            mu_global = int(src.read(1, window=window).flat[0])
        logger.info(f"HWSD MU_GLOBAL at ({lat},{lon}): {mu_global}")
    except Exception as e:
        logger.warning(f"HWSD raster read failed: {e}")
        return None

    hwsd_db = _load_hwsd_mdb(mdb_path)
    if hwsd_db is None:
        logger.warning("HWSD MDB load failed — using default soil")
        return None

    row = hwsd_db.get(mu_global)
    if row is None:
        logger.warning(f"MU_GLOBAL {mu_global} not in MDB — using default soil")
        return None
    return row


def _hwsd_layer(row, prefix):
    """Extract sand, clay, OC, bd, pH, gravel from HWSD row."""
    sand = _f(row.get(f"{prefix}_SAND"),            40.0)
    clay = _f(row.get(f"{prefix}_CLAY"),            20.0)
    oc   = _f(row.get(f"{prefix}_OC"),               1.0)
    bd_r = _f(row.get(f"{prefix}_REF_BULK_DENSITY"), 1350.0)
    bd   = bd_r / 1000.0 if bd_r > 10 else bd_r   # kg/m3 -> g/cm3
    ph   = _f(row.get(f"{prefix}_PH_H2O"),           6.8)
    grav = _f(row.get(f"{prefix}_GRAVEL"),            2.0)
    return (min(100, max(0, sand or 40)),
            min(100, max(0, clay or 20)),
            min(60,  max(0, oc   or 1)),
            min(2.2, max(0.5, bd)),
            min(9.5, max(3.0, ph)),
            min(80,  max(0,   grav)))


# ---------------------------------------------------------------------------
# VIC soil param reader
# ---------------------------------------------------------------------------

def read_vic_soil_cell(soil_file, lat, lon, tol=0.15):
    """Find VIC soil parameter row nearest to (lat, lon)."""
    best, best_dist = None, float("inf")
    with open(soil_file) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 33:
                continue
            try:
                clat, clon = float(parts[2]), float(parts[3])
            except (ValueError, IndexError):
                continue
            dist = ((clat - lat)**2 + (clon - lon)**2)**0.5
            if dist < best_dist:
                best_dist, best = dist, parts

    if best is None or best_dist > tol:
        logger.warning(f"No VIC soil cell within {tol}° of ({lat},{lon})")
        return None

    logger.info(f"VIC cell at ({float(best[2]):.4f},{float(best[3]):.4f}), dist={best_dist:.4f}°")
    return {
        "depths_m": [float(best[22]), float(best[23]), float(best[24])],
        "ksat_mmd": [float(best[12]), float(best[13]), float(best[14])],
    }


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_inputs():
    errors = []
    if not VIC_SOIL_FILE or not Path(VIC_SOIL_FILE).exists():
        errors.append(f"VIC_SOIL_FILE not found: {VIC_SOIL_FILE}")
    if not OUTPUT_PATH:
        errors.append("OUTPUT_PATH not set")
    if LAT == 0.0 and LON == 0.0:
        errors.append("LAT and LON must be non-zero")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


# ---------------------------------------------------------------------------
# Core processing
# ---------------------------------------------------------------------------

def process():
    vic = read_vic_soil_cell(VIC_SOIL_FILE, LAT, LON)
    if vic is None:
        vic = {"depths_m": [0.1, 0.3, 1.5], "ksat_mmd": [50.0, 30.0, 20.0]}

    depths_m = vic["depths_m"]
    ksat_mmd = vic["ksat_mmd"]

    hwsd_row = lookup_hwsd(LAT, LON)

    if hwsd_row is not None:
        t_sand, t_clay, t_oc, t_bd, t_ph, t_grav = _hwsd_layer(hwsd_row, "T")
        s_sand, s_clay, s_oc, s_bd, s_ph, s_grav = _hwsd_layer(hwsd_row, "S")
        logger.info(f"HWSD topsoil: sand={t_sand}%, clay={t_clay}%, OC={t_oc}%, "
                    f"bd={t_bd:.2f} g/cm³, pH={t_ph}")
    else:
        # Default: representative East China cropland (Chaohu basin)
        t_sand, t_clay, t_oc, t_bd, t_ph, t_grav = 35.0, 25.0, 1.5, 1.35, 6.5, 2.0
        s_sand, s_clay, s_oc, s_bd, s_ph, s_grav = 30.0, 28.0, 0.6, 1.45, 6.8, 4.0

    # Map VIC 3 layers: layer1=topsoil, layers 2+3=subsoil
    layers_soil = [
        (t_sand, t_clay, t_oc, t_bd, t_ph, t_grav),
        (s_sand, s_clay, s_oc, s_bd, s_ph, s_grav),
        (s_sand, s_clay, s_oc * 0.4, min(2.2, s_bd * 1.02), s_ph + 0.1,
         min(80, s_grav * 1.5)),
    ]

    xml_layers = []
    for depth_m, ksat, (sand, clay, oc, bd, ph, grav) in zip(
            depths_m, ksat_mmd, layers_soil):

        depth_mm = depth_m * 1000.0
        theta_fc, theta_wp = saxton_rawls_fc_wp(sand / 100.0, clay / 100.0, oc)

        wc_fc   = round(theta_fc * 1000.0, 1)      # mm/m
        wc_wp   = round(theta_wp * 1000.0, 1)      # mm/m
        wc_init = round((theta_fc + theta_wp) / 2.0 * 1000.0, 1)

        sks  = ksat / 86_400_000.0                 # mm/day -> m/s
        scel = round(grav / 100.0, 3)
        corg = round(min(0.6, max(0.0001, oc / 100.0)), 5)

        xml_layers.append(
            f'      <layer depth="{depth_mm:.1f}" bd="{bd:.2f}" '
            f'clay="{clay/100:.3f}" corg="{corg}" ph="{ph:.1f}" '
            f'scel="{scel}" sks="{sks:.2e}" '
            f'wc="{wc_init}" wc_fc="{wc_fc}" wc_wp="{wc_wp}" />'
        )

    tex   = texture_class(t_sand, t_clay)
    corg5  = round(t_oc / 100.0, 5)
    corg30 = round(s_oc / 100.0, 5)

    xml = "\n".join([
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<site>",
        "  <description>",
        f"    <dataset>VIC-HWSD-lat{LAT:.4f}-lon{LON:.4f}</dataset>",
        "  </description>",
        "  <soil>",
        f'    <general usehistory="arable" corg5="{corg5}" corg30="{corg30}" '
        f'soil="{tex}" humus="NONE" litterheight="0.0" />',
        "    <layers>",
        *xml_layers,
        "    </layers>",
        "  </soil>",
        "</site>",
    ])

    output_path = Path(OUTPUT_PATH)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(xml, encoding="utf-8")
    logger.info(f"Written site.xml ({len(xml_layers)} layers) → {output_path}")
    return str(output_path)


# ---------------------------------------------------------------------------
# Output validation
# ---------------------------------------------------------------------------

def validate_outputs(output_path):
    import re
    p = Path(output_path)
    if not p.exists():
        logger.error(f"Output not created: {output_path}")
        sys.exit(3)
    content = p.read_text()
    if "<layer" not in content:
        logger.error("site.xml missing <layer> elements")
        sys.exit(3)
    for v in re.findall(r'corg="([^"]+)"', content):
        if float(v) > 0.6:
            logger.error(f"corg={v} > 0.6 — likely percentage not fraction (dt_015)")
            sys.exit(3)
    logger.info("Output validation passed.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs()
    try:
        output_path = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}", exc_info=True)
        sys.exit(2)
    validate_outputs(output_path)
    print(json.dumps({"status": "success", "site_xml": output_path}))
    sys.exit(0)
