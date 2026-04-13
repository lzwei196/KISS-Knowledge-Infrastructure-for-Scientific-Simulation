#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
Tool ID:      create_initial_water_content
Stage:        s4_initial_conditions
Description:  Creates InitialWaterContent object with proper wc_type, method,
              and layer/depth specification. Validates against soil profile.

Inputs:
  - wc_type: 'Prop' (WP/FC/SAT), 'Num' (m3/m3), 'Pct' (% TAW)
  - method: 'Layer' or 'Depth'
  - depth_layer: Layer numbers or depth values
  - value: Water content values at each location

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
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
WC_TYPE = "Prop"         # 'Prop', 'Num', 'Pct'
METHOD = "Layer"         # 'Layer', 'Depth'
DEPTH_LAYER = [1]        # Layer numbers or depth values
VALUE = ["FC"]           # Values (string for Prop, float for Num/Pct)

VALID_WC_TYPES = ['Prop', 'Num', 'Pct']
VALID_METHODS = ['Layer', 'Depth']
VALID_PROPS = ['WP', 'FC', 'SAT']


def validate_inputs():
    errors = []
    if WC_TYPE not in VALID_WC_TYPES:
        errors.append(f"wc_type '{WC_TYPE}' not in {VALID_WC_TYPES}")
    if METHOD not in VALID_METHODS:
        errors.append(f"method '{METHOD}' not in {VALID_METHODS}")
    if not DEPTH_LAYER or not VALUE:
        errors.append("depth_layer and value must be non-empty lists")
    if len(DEPTH_LAYER) != len(VALUE):
        errors.append(f"depth_layer length ({len(DEPTH_LAYER)}) != value length ({len(VALUE)})")
    if WC_TYPE == 'Prop':
        for v in VALUE:
            if v not in VALID_PROPS:
                errors.append(f"For wc_type='Prop', value '{v}' must be one of {VALID_PROPS}")
    if WC_TYPE == 'Pct':
        for v in VALUE:
            if not (0 <= float(v) <= 100):
                errors.append(f"For wc_type='Pct', value {v} must be 0-100")
    if WC_TYPE == 'Num':
        for v in VALUE:
            if not (0 <= float(v) <= 0.7):
                errors.append(f"For wc_type='Num', value {v} must be 0-0.7 m3/m3")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def process():
    try:
        from aquacrop import InitialWaterContent
    except ImportError:
        logger.error("aquacrop not installed. Run: pip install aquacrop")
        sys.exit(2)

    iwc = InitialWaterContent(
        wc_type=WC_TYPE,
        method=METHOD,
        depth_layer=DEPTH_LAYER,
        value=VALUE
    )

    logger.info(f"InitialWaterContent created: type={iwc.wc_type}, method={iwc.method}, "
                f"layers={iwc.depth_layer}, values={iwc.value}")
    return iwc


if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs()
    try:
        iwc = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        sys.exit(2)
    logger.info("Tool completed successfully.")
    sys.exit(0)
