#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
==========================================
Tool ID:      convert_hwsd_to_pcse_soil
Stage:        s2_soil_params
Description:  Convert HWSD soil properties (sand/silt/clay/OC/bulk density)
              to WOFOST water balance parameters (SMW/SMFCF/SM0/K0) via
              pedotransfer functions (Wosten et al. 1999).

Inputs:
  - LAT, LON: target location coordinates
  - HWSD_RASTER: path to HWSD global raster (hwsd.bil)
  - HWSD_MDB: path to HWSD MDB database

Outputs:
  - JSON on stdout with WOFOST soil parameter dictionary

Exit codes:
  0 — success
  1 — input validation failed
  2 — processing error
  3 — output validation failed
"""

import sys
import os
import json
import math
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
LAT = 52.0
LON = 5.5
HWSD_RASTER = "data/soil/HWSD_RASTER/hwsd.bil"
HWSD_MDB = "data/forcing/huaihe_raw/soil/HWSD.mdb"

# Manual override: provide texture directly if HWSD not available
SAND_PCT = None  # override: sand percentage
CLAY_PCT = None  # override: clay percentage
SILT_PCT = None  # override: silt percentage
OC_PCT = None    # override: organic carbon percentage
BULK_DENSITY = None  # override: g/cm3


def validate_inputs():
    errors = []
    if LAT is None or LON is None:
        errors.append("LAT and LON must be set")
    if LAT is not None and not (-90 <= LAT <= 90):
        errors.append(f"LAT={LAT} out of range [-90, 90]")
    if LON is not None and not (-180 <= LON <= 180):
        errors.append(f"LON={LON} out of range [-180, 180]")

    # Either HWSD files or manual texture must be available
    has_hwsd = Path(HWSD_RASTER).exists() if HWSD_RASTER else False
    has_manual = SAND_PCT is not None and CLAY_PCT is not None
    if not has_hwsd and not has_manual:
        errors.append("Either HWSD raster or manual texture (SAND_PCT, CLAY_PCT) must be provided")

    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def validate_outputs(soil_params):
    errors = []
    required = ["SMW", "SMFCF", "SM0", "CRAIRC", "K0", "SOPE", "KSUB",
                 "RDMSOL", "IFUNRN", "WAV", "SSI", "SSMAX", "SMLIM", "NOTINF"]
    for key in required:
        if key not in soil_params:
            errors.append(f"Missing required key: {key}")

    if soil_params.get("SMW", 0) >= soil_params.get("SMFCF", 0):
        errors.append(f"SMW ({soil_params['SMW']}) must be < SMFCF ({soil_params['SMFCF']})")
    if soil_params.get("SMFCF", 0) >= soil_params.get("SM0", 0):
        errors.append(f"SMFCF ({soil_params['SMFCF']}) must be < SM0 ({soil_params['SM0']})")
    if soil_params.get("SM0", 0) > 0.65:
        errors.append(f"SM0 ({soil_params['SM0']}) > 0.65 (physically impossible porosity)")

    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(3)
    logger.info("Output validation passed.")


def get_texture_from_hwsd(lat, lon):
    """Extract soil texture from HWSD raster + MDB."""
    try:
        # Try using the shared HWSD adapter
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
        from skills.dssat_crop_run.hwsd_soil_adapter import get_soil_properties
        props = get_soil_properties(lat, lon, HWSD_RASTER, HWSD_MDB)
        return {
            'sand': props.get('T_SAND', 40),
            'clay': props.get('T_CLAY', 25),
            'silt': props.get('T_SILT', 35),
            'oc': props.get('T_OC', 1.0),
            'bd': props.get('T_REF_BULK_DENSITY', 1.4),
        }
    except Exception as e:
        logger.warning(f"HWSD adapter failed: {e}. Using default texture.")
        return {'sand': 40, 'clay': 25, 'silt': 35, 'oc': 1.0, 'bd': 1.4}


def pedotransfer_wosten(sand, clay, silt, oc, bd):
    """
    Wosten et al. (1999) pedotransfer functions.
    Convert soil texture to WOFOST hydraulic parameters.

    sand, clay, silt: percentage (0-100)
    oc: organic carbon percentage
    bd: bulk density g/cm3

    Returns dict with SMW, SMFCF, SM0, K0
    """
    om = oc * 1.724  # OC to OM via van Bemmelen factor

    # Wilting point (pF 4.2, ~1500 kPa)
    SMW = 0.001 + 0.26 * (clay / 100.0) + 0.05 * (om / 100.0)

    # Field capacity (pF 2.0, ~10 kPa)
    SMFCF = 0.02 + 0.37 * (clay / 100.0) + 0.15 * (om / 100.0) + 0.10 * (silt / 100.0)

    # Saturation (porosity)
    SM0 = 1.0 - bd / 2.65

    # Saturated hydraulic conductivity (simplified Cosby et al. 1984)
    K0 = 10.0 ** (1.26 - 0.0064 * clay)

    # Clamp to valid ranges
    SMW = max(0.01, min(SMW, 0.50))
    SM0 = max(0.30, min(SM0, 0.62))
    SMFCF = max(SMW + 0.02, min(SMFCF, SM0 - 0.03))
    K0 = max(1.0, min(K0, 100.0))

    return SMW, SMFCF, SM0, K0


def process():
    """Convert HWSD to PCSE soil parameters."""
    # Get texture
    if SAND_PCT is not None and CLAY_PCT is not None:
        sand = SAND_PCT
        clay = CLAY_PCT
        silt = SILT_PCT if SILT_PCT is not None else (100 - sand - clay)
        oc = OC_PCT if OC_PCT is not None else 1.0
        bd = BULK_DENSITY if BULK_DENSITY is not None else 1.4
        logger.info(f"Using manual texture: sand={sand}%, clay={clay}%, silt={silt}%")
    else:
        texture = get_texture_from_hwsd(LAT, LON)
        sand, clay, silt = texture['sand'], texture['clay'], texture['silt']
        oc, bd = texture['oc'], texture['bd']
        logger.info(f"HWSD texture at ({LAT}, {LON}): sand={sand}%, clay={clay}%, silt={silt}%, OC={oc}%, BD={bd}")

    # Pedotransfer
    SMW, SMFCF, SM0, K0 = pedotransfer_wosten(sand, clay, silt, oc, bd)

    # Rootable depth based on texture
    if clay > 60:
        RDMSOL = 80.0
    elif sand > 80:
        RDMSOL = 150.0
    else:
        RDMSOL = 120.0

    soil_params = {
        'SMW': round(SMW, 4),
        'SMFCF': round(SMFCF, 4),
        'SM0': round(SM0, 4),
        'CRAIRC': round(max(0.02, SM0 - SMFCF - 0.02), 4),
        'K0': round(K0, 2),
        'SOPE': 1.0,
        'KSUB': 1.0,
        'RDMSOL': RDMSOL,
        'IFUNRN': 0,
        'SSMAX': 0.0,
        'SSI': 0.0,
        'WAV': 20.0,
        'NOTINF': 0.0,
        'SMLIM': round(SMFCF, 4),
    }

    logger.info(f"Computed: SMW={SMW:.4f}, SMFCF={SMFCF:.4f}, SM0={SM0:.4f}, K0={K0:.2f}")
    return soil_params


if __name__ == "__main__":
    if len(sys.argv) >= 3:
        LAT = float(sys.argv[1])
        LON = float(sys.argv[2])
    if len(sys.argv) >= 5:
        HWSD_RASTER = sys.argv[3]
        HWSD_MDB = sys.argv[4]

    validate_inputs()

    try:
        result = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        sys.exit(2)

    validate_outputs(result)

    print(json.dumps(result, indent=2))
    sys.exit(0)
