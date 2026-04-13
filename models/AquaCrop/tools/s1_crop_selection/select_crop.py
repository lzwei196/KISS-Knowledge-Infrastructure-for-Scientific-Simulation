#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
Tool ID:      select_crop
Stage:        s1_crop_selection
Description:  Creates a Crop object from built-in defaults or custom parameters.
              Validates crop name against available list, checks GDD consistency.

Inputs:
  - crop_name: Built-in crop name or 'custom' (string)
  - planting_date: Planting date in MM/DD format (string)
  - harvest_date: Latest harvest date in MM/DD format (string, optional)
  - overrides: Dict of parameter overrides (dict, optional)

Outputs:
  - crop: Configured Crop instance (in-memory)

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

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
CROP_NAME = "Maize"          # Built-in crop name or 'custom'
PLANTING_DATE = "05/01"      # MM/DD format
HARVEST_DATE = None          # MM/DD format or None
OVERRIDES = {}               # e.g., {'Tbase': 10, 'HI0': 0.50}

# ---------------------------------------------------------------------------
# Built-in crop names (from aquacrop v3.0.12 crop_params.py)
# ---------------------------------------------------------------------------
BUILTIN_CROPS = [
    'Barley', 'BarleyGDD', 'Cotton', 'CottonGDD', 'Default',
    'DryBean', 'DryBeanGDD', 'Maize', 'MaizeGDD', 'PaddyRice',
    'PaddyRiceGDD', 'Potato', 'PotatoGDD', 'PotatoLocalGDD',
    'Quinoa', 'Sorghum', 'SorghumGDD', 'Soybean', 'SoybeanGDD',
    'SugarBeet', 'SugarBeetGDD', 'SugarBeetGDD_UK', 'SugarCane',
    'Sunflower', 'SunflowerGDD', 'Tomato', 'TomatoGDD', 'Wheat',
    'WheatGDD', 'WheatGDD_1dec', 'HydWheatGDD', 'WheatLongGDD',
    'localpaddy', 'MaizeChampionGDD', 'Tef', 'AlfalfaGDD', 'Cassava',
    'custom',
]

# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def validate_inputs():
    errors = []
    if CROP_NAME not in BUILTIN_CROPS:
        errors.append(f"Unknown crop name '{CROP_NAME}'. Must be one of: {BUILTIN_CROPS}")
    if not PLANTING_DATE or '/' not in PLANTING_DATE:
        errors.append(f"Invalid planting_date format: '{PLANTING_DATE}'. Must be MM/DD.")
    try:
        month, day = PLANTING_DATE.split('/')
        if not (1 <= int(month) <= 12 and 1 <= int(day) <= 31):
            errors.append(f"Planting date out of range: month={month}, day={day}")
    except (ValueError, AttributeError):
        errors.append(f"Cannot parse planting_date: '{PLANTING_DATE}'")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def validate_outputs(crop):
    errors = []
    if crop.Tbase >= crop.Tupp:
        errors.append(f"Tbase ({crop.Tbase}) >= Tupp ({crop.Tupp}): GDD will not accumulate")
    if hasattr(crop, 'HI0') and (crop.HI0 <= 0 or crop.HI0 > 1):
        errors.append(f"HI0 ({crop.HI0}) out of range (0, 1]: yield will be wrong")
    if crop.CalendarType == 2:  # GDD mode
        if crop.Emergence >= crop.Maturity:
            errors.append(f"Emergence ({crop.Emergence}) >= Maturity ({crop.Maturity})")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(3)
    logger.info("Output validation passed.")


# ---------------------------------------------------------------------------
# Processing
# ---------------------------------------------------------------------------
def process():
    try:
        from aquacrop import Crop
    except ImportError:
        logger.error("aquacrop package not installed. Run: pip install aquacrop")
        sys.exit(2)

    kwargs = dict(OVERRIDES) if OVERRIDES else {}
    if HARVEST_DATE:
        crop = Crop(CROP_NAME, planting_date=PLANTING_DATE, harvest_date=HARVEST_DATE, **kwargs)
    else:
        crop = Crop(CROP_NAME, planting_date=PLANTING_DATE, **kwargs)

    result = {
        "crop_name": crop.Name,
        "planting_date": crop.planting_date,
        "Tbase": crop.Tbase,
        "Tupp": crop.Tupp,
        "HI0": crop.HI0,
        "WP": crop.WP,
        "CCx": crop.CCx,
        "CalendarType": crop.CalendarType,
        "Emergence_GDD": crop.Emergence,
        "Maturity_GDD": crop.Maturity,
        "Senescence_GDD": crop.Senescence,
    }
    logger.info(f"Crop created: {json.dumps(result, indent=2)}")
    return crop


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs()
    try:
        crop = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        sys.exit(2)
    validate_outputs(crop)
    logger.info("Tool completed successfully.")
    sys.exit(0)
