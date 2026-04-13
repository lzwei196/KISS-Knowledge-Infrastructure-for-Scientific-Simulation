#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
==========================================
Tool ID:      load_crop_parameters
Stage:        s1_crop_params
Description:  Load WOFOST crop parameters from YAML via YAMLCropDataProvider,
              validate key parameters, set active crop and variety.

Inputs:
  - CROP_NAME: PCSE crop name (e.g., 'wheat', 'maize') — case sensitive
  - VARIETY_NAME: PCSE variety name (e.g., 'Winter_wheat_101') — case sensitive
  - CROP_DIR: Optional directory with custom YAML crop parameter files

Outputs:
  - JSON on stdout with crop parameter summary and validation status

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
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
CROP_NAME = "wheat"
VARIETY_NAME = "Winter_wheat_101"
CROP_DIR = ""  # empty = use PCSE built-in parameters

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def validate_inputs():
    """Check preconditions."""
    errors = []
    if not CROP_NAME:
        errors.append("CROP_NAME is not set")
    if not VARIETY_NAME:
        errors.append("VARIETY_NAME is not set")
    if CROP_DIR and not Path(CROP_DIR).is_dir():
        errors.append(f"CROP_DIR does not exist: {CROP_DIR}")

    try:
        import pcse
    except ImportError:
        errors.append("pcse package not installed. Run: pip install pcse")

    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)

    logger.info("Input validation passed.")


def validate_outputs(result):
    """Check postconditions."""
    errors = []

    if not result.get("parameters"):
        errors.append("No parameters were loaded")

    required_params = ["TSUM1", "TSUM2", "TDWI", "SPAN"]
    for p in required_params:
        if p not in result.get("parameters", {}):
            errors.append(f"Missing critical parameter: {p}")

    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(3)

    logger.info("Output validation passed.")


# ---------------------------------------------------------------------------
# Core processing
# ---------------------------------------------------------------------------
def process():
    """Load crop parameters via PCSE YAMLCropDataProvider."""
    from pcse.input import YAMLCropDataProvider

    # Load crop data provider
    if CROP_DIR:
        cropdata = YAMLCropDataProvider(fpath=CROP_DIR)
        logger.info(f"Loaded custom crop parameters from: {CROP_DIR}")
    else:
        cropdata = YAMLCropDataProvider()
        logger.info("Loaded built-in PCSE crop parameters")

    # List available crops and varieties
    available_crops = list(cropdata.get_crop_types())
    logger.info(f"Available crops: {available_crops}")

    if CROP_NAME not in available_crops:
        logger.error(f"Crop '{CROP_NAME}' not found. Available: {available_crops}")
        logger.error("NOTE: crop names are CASE SENSITIVE (use lowercase)")
        sys.exit(2)

    available_varieties = list(cropdata.get_variety_names(CROP_NAME))
    logger.info(f"Available varieties for {CROP_NAME}: {available_varieties}")

    if VARIETY_NAME not in available_varieties:
        logger.error(f"Variety '{VARIETY_NAME}' not found. Available: {available_varieties}")
        logger.error("NOTE: variety names are CASE SENSITIVE")
        sys.exit(2)

    # Set active crop and variety
    cropdata.set_active_crop(CROP_NAME, VARIETY_NAME)
    logger.info(f"Active crop: {CROP_NAME} / {VARIETY_NAME}")

    # Extract key parameters for reporting
    key_params = {}
    param_names = [
        "TSUM1", "TSUM2", "TDWI", "SPAN", "TBASEM", "TEFFMX",
        "AMAXTB", "EFFTB", "SLATB", "FOTB", "FLTB", "FSTB", "FRTB",
        "CVL", "CVO", "CVR", "CVS",
        "VERNSAT", "VERNBASE", "VERNDVS",
    ]
    for p in param_names:
        try:
            val = cropdata[p]
            # Convert AFGEN tables to list for JSON serialization
            if hasattr(val, '__iter__') and not isinstance(val, str):
                val = list(val)
            key_params[p] = val
        except (KeyError, AttributeError):
            pass

    # Check if winter crop
    is_winter = "VERNSAT" in key_params and key_params["VERNSAT"] > 0

    result = {
        "status": "success",
        "crop_name": CROP_NAME,
        "variety_name": VARIETY_NAME,
        "is_winter_crop": is_winter,
        "available_crops": available_crops,
        "available_varieties": available_varieties,
        "parameters": key_params,
    }

    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")

    # Allow CLI overrides
    if len(sys.argv) >= 3:
        CROP_NAME = sys.argv[1]
        VARIETY_NAME = sys.argv[2]
    if len(sys.argv) >= 4:
        CROP_DIR = sys.argv[3]

    validate_inputs()

    try:
        result = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        sys.exit(2)

    validate_outputs(result)

    print(json.dumps(result, indent=2, default=str))
    logger.info("Tool completed successfully.")
    sys.exit(0)
