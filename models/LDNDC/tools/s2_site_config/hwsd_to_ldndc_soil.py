#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
Tool ID:      hwsd_to_ldndc_soil
Stage:        s2_site_config
Description:  Query HWSD global soil database and return LDNDC-format soil horizons.
              Reads HWSD raster (hwsd.bil) for mapping unit, then MDB for properties.
              CRITICAL: Converts OC from percentage to mass fraction (divide by 100).

Inputs:
  - lat: Latitude in decimal degrees
  - lon: Longitude in decimal degrees
  - hwsd_raster: Path to HWSD raster (default: data/soil/HWSD_RASTER/hwsd.bil)
  - hwsd_mdb: Path to HWSD MDB database (default: data/forcing/huaihe_raw/soil/HWSD.mdb)

Outputs:
  - JSON with LDNDC-format soil horizon data + pedotransfer hydraulic properties

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import csv
import io
import json
import math
import logging
import subprocess
from pathlib import Path

LAT = 0.0
LON = 0.0
HWSD_RASTER = "/mnt/disk1/Hydrocraft_server/data/soil/HWSD_RASTER/hwsd.bil"
HWSD_MDB = "/media/server/hc_ssd/forcing/huaihe_raw/soil/HWSD.mdb"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def validate_inputs():
    errors = []
    if not (-90 <= LAT <= 90):
        errors.append(f"LAT out of range: {LAT}")
    if not (-180 <= LON <= 180):
        errors.append(f"LON out of range: {LON}")
    if not Path(HWSD_RASTER).exists():
        errors.append(f"HWSD raster not found: {HWSD_RASTER}")
    if not Path(HWSD_MDB).exists():
        errors.append(f"HWSD MDB not found: {HWSD_MDB}")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def _safe_float(val, default=0.0):
    try:
        v = float(val) if val and str(val).strip() else default
        return default if math.isnan(v) else v
    except (ValueError, TypeError):
        return default


def _pedotransfer_sks(sand_pct, clay_pct):
    """Estimate Ksat in cm/min using Cosby et al. (1984)."""
    log10_ksat_cm_hr = -0.6 + 0.012 * sand_pct - 0.0064 * clay_pct
    ksat_cm_min = (10.0 ** log10_ksat_cm_hr) / 60.0
    return max(0.001, min(1.0, ksat_cm_min))


def _pedotransfer_wc(sand_pct, clay_pct, oc_pct):
    """Estimate field capacity and wilting point (L/m3) using Rawls et al. (1982)."""
    OM = oc_pct * 1.724
    theta_fc = 0.2576 - 0.0020 * sand_pct + 0.0036 * clay_pct + 0.0299 * OM
    theta_wp = 0.0260 + 0.0050 * clay_pct + 0.0158 * OM
    theta_fc = max(0.10, min(0.55, theta_fc))
    theta_wp = max(0.02, min(0.35, theta_wp))
    if theta_wp >= theta_fc:
        theta_wp = theta_fc * 0.5
    return theta_fc * 1000.0, theta_wp * 1000.0


def _usda_texture(sand, clay):
    """Return LDNDC soil type mnemonic from sand/clay percentages."""
    silt = 100.0 - sand - clay
    if sand >= 85 and clay < 10: return "SAND"
    elif sand >= 70 and clay < 15: return "LOSA"
    elif sand >= 43 and clay < 7 and silt < 50: return "SALO"
    elif clay >= 7 and clay < 20 and sand > 52: return "SALO"
    elif clay >= 7 and clay < 27 and silt >= 28 and silt < 50 and sand <= 52: return "LOAM"
    elif silt >= 50 and clay >= 12 and clay < 27: return "SILO"
    elif silt >= 50 and silt < 80 and clay < 12: return "SILO"
    elif silt >= 80 and clay < 12: return "SILT"
    elif clay >= 20 and clay < 35 and silt < 28 and sand >= 45: return "SACL"
    elif clay >= 20 and clay < 35 and silt >= 28: return "SLCL"
    elif clay >= 27 and clay < 40 and sand >= 20 and sand <= 45: return "CLLO"
    elif clay >= 35 and sand >= 45: return "SNCL"
    elif clay >= 35 and clay < 60 and silt >= 40: return "SICL"
    elif clay >= 40: return "CLAY"
    else: return "LOAM"


def process():
    """Query HWSD raster + MDB for soil properties at lat/lon."""
    import rasterio

    # Step 1: Read MU_GLOBAL from raster
    with rasterio.open(HWSD_RASTER) as src:
        row, col = src.index(LON, LAT)
        mu_global = int(src.read(1)[row, col])

    logger.info(f"HWSD MU_GLOBAL at ({LAT:.2f}, {LON:.2f}): {mu_global}")
    if mu_global <= 0:
        raise ValueError(f"No valid HWSD soil unit at ({LAT}, {LON}). MU_GLOBAL={mu_global}")

    # Step 2: Query MDB
    result = subprocess.run(
        ["mdb-export", HWSD_MDB, "HWSD_DATA"],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"mdb-export failed: {result.stderr}")

    reader = csv.DictReader(io.StringIO(result.stdout))
    soil_row = None
    for r in reader:
        if r.get("MU_GLOBAL") == str(mu_global) and r.get("SEQ") == "1":
            soil_row = r
            break

    if soil_row is None:
        raise ValueError(f"MU_GLOBAL {mu_global} not found in HWSD_DATA")

    # Extract topsoil (T_) and subsoil (S_) properties
    t_sand = _safe_float(soil_row.get("T_SAND"), 40)
    t_silt = _safe_float(soil_row.get("T_SILT"), 40)
    t_clay = _safe_float(soil_row.get("T_CLAY"), 20)
    t_oc = _safe_float(soil_row.get("T_OC"), 1.0)
    t_ph = _safe_float(soil_row.get("T_PH_H2O"), 7.0)
    t_bd = _safe_float(soil_row.get("T_REF_BULK_DENSITY"), 1.35)
    t_gravel = _safe_float(soil_row.get("T_GRAVEL"), 0)

    s_sand = _safe_float(soil_row.get("S_SAND"), t_sand)
    s_clay = _safe_float(soil_row.get("S_CLAY"), t_clay)
    s_oc = _safe_float(soil_row.get("S_OC"), t_oc * 0.5)
    s_ph = _safe_float(soil_row.get("S_PH_H2O"), t_ph)
    s_bd = _safe_float(soil_row.get("S_REF_BULK_DENSITY"), t_bd + 0.05)
    s_gravel = _safe_float(soil_row.get("S_GRAVEL"), t_gravel)

    if t_bd <= 0: t_bd = 1.35
    if s_bd <= 0: s_bd = 1.40

    logger.info(
        f"HWSD soil: clay={t_clay}%, sand={t_sand}%, silt={t_silt}%, "
        f"BD={t_bd} g/cm3, OC={t_oc}%, pH={t_ph}"
    )

    # Pedotransfer functions
    t_sks = _pedotransfer_sks(t_sand, t_clay)
    s_sks = _pedotransfer_sks(s_sand, s_clay)
    t_wc_fc, t_wc_wp = _pedotransfer_wc(t_sand, t_clay, t_oc)
    s_wc_fc, s_wc_wp = _pedotransfer_wc(s_sand, s_clay, s_oc)
    soil_type = _usda_texture(t_sand, t_clay)

    # Build LDNDC soil data
    # CRITICAL: OC percentage → fraction (÷100)
    t_corg = t_oc / 100.0
    s_corg = s_oc / 100.0
    t_scel = t_gravel / 100.0
    s_scel = s_gravel / 100.0

    soil_data = {
        "mu_global": mu_global,
        "soil_type": soil_type,
        "corg5": t_corg,
        "corg30": t_corg * 0.9,
        "topsoil": {
            "clay_pct": t_clay, "sand_pct": t_sand, "silt_pct": t_silt,
            "bd_gcm3": t_bd, "corg_frac": t_corg, "ph": t_ph,
            "sks_cmmin": t_sks, "scel": t_scel,
            "wc_fc": t_wc_fc, "wc_wp": t_wc_wp,
        },
        "subsoil": {
            "clay_pct": s_clay, "sand_pct": s_sand,
            "bd_gcm3": s_bd, "corg_frac": s_corg, "ph": s_ph,
            "sks_cmmin": s_sks, "scel": s_scel,
            "wc_fc": s_wc_fc, "wc_wp": s_wc_wp,
        },
        # Layer structure matching proven Bengbu format (9 layers, depths in mm)
        "layers": [],
    }

    # Topsoil: 3 layers of 100 mm (0-30 cm)
    for i in range(3):
        depth_factor = 1.0 - 0.05 * i
        soil_data["layers"].append({
            "depth_mm": 100, "bd": t_bd, "clay": t_clay / 100,
            "corg": t_corg * depth_factor, "ph": t_ph,
            "scel": t_scel, "sks": t_sks,
            "wc_fc": t_wc_fc, "wc_wp": t_wc_wp,
        })
    # Subsoil: 4 layers of 175 mm (30-100 cm)
    for i in range(4):
        depth_factor = 1.0 - 0.1 * i
        soil_data["layers"].append({
            "depth_mm": 175, "bd": s_bd, "clay": s_clay / 100,
            "corg": s_corg * depth_factor, "ph": s_ph,
            "scel": s_scel, "sks": s_sks,
            "wc_fc": s_wc_fc, "wc_wp": s_wc_wp,
        })
    # Deep subsoil: 2 layers of 200 mm (100-140 cm)
    d_corg = s_corg * 0.5
    d_sks = s_sks * 0.8
    for i in range(2):
        soil_data["layers"].append({
            "depth_mm": 200, "bd": s_bd + 0.05, "clay": s_clay / 100,
            "corg": d_corg, "ph": s_ph + 0.2,
            "scel": s_scel, "sks": d_sks,
            "wc_fc": s_wc_fc - 10, "wc_wp": s_wc_wp,
        })

    return soil_data


def validate_outputs(soil_data):
    layers = soil_data.get("layers", [])
    if len(layers) < 3:
        logger.error(f"Output has only {len(layers)} layers — expected at least 3")
        sys.exit(3)
    for i, layer in enumerate(layers):
        if layer["bd"] <= 0 or layer["bd"] > 2.65:
            logger.error(f"Layer {i}: bd={layer['bd']} out of range (0, 2.65]")
            sys.exit(3)
        if layer["corg"] > 0.60:
            logger.error(f"Layer {i}: corg={layer['corg']} > 0.60 — likely percentage, not fraction!")
            sys.exit(3)
    logger.info(f"Output validation passed ({len(layers)} layers).")


if __name__ == "__main__":
    if len(sys.argv) >= 3:
        LAT = float(sys.argv[1])
        LON = float(sys.argv[2])
    if len(sys.argv) >= 4:
        HWSD_RASTER = sys.argv[3]
    if len(sys.argv) >= 5:
        HWSD_MDB = sys.argv[4]
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs()
    try:
        result = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        sys.exit(2)
    validate_outputs(result)
    print(json.dumps({"status": "success", "soil_data": result}))
    sys.exit(0)
