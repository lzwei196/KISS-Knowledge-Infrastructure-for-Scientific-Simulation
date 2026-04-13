#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
Tool ID:      create_field_management
Stage:        s6_field_management
Description:  Creates FieldMngt object for mulches, bunds, CN adjustment,
              and surface runoff inhibition.

CRITICAL: z_bund is specified in METERS but internally converted to mm.
          Passing 150 (thinking mm) creates a 150-meter bund (wrong).
          Pass 0.15 for a 150mm bund.

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MULCHES = False
MULCH_PCT = 50
F_MULCH = 0.5
BUNDS = False
Z_BUND = 0.0        # METERS (not mm!)
BUND_WATER = 0.0     # mm
CURVE_NUMBER_ADJ = False
CURVE_NUMBER_ADJ_PCT = 0
SR_INHB = False


def validate_inputs():
    errors = []
    if Z_BUND > 1.0:
        errors.append(f"z_bund={Z_BUND}m seems too large. Did you pass mm instead of meters? "
                      f"A 150mm bund should be z_bund=0.15")
    if not (0 <= MULCH_PCT <= 100):
        errors.append(f"mulch_pct={MULCH_PCT} out of range 0-100")
    if not (0 <= F_MULCH <= 1):
        errors.append(f"f_mulch={F_MULCH} out of range 0-1")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def process():
    try:
        from aquacrop import FieldMngt
    except ImportError:
        logger.error("aquacrop not installed. Run: pip install aquacrop")
        sys.exit(2)

    field = FieldMngt(
        mulches=MULCHES,
        bunds=BUNDS,
        curve_number_adj=CURVE_NUMBER_ADJ,
        sr_inhb=SR_INHB,
        mulch_pct=MULCH_PCT,
        f_mulch=F_MULCH,
        z_bund=Z_BUND,
        bund_water=BUND_WATER,
        curve_number_adj_pct=CURVE_NUMBER_ADJ_PCT,
    )

    logger.info(f"FieldMngt created: mulches={MULCHES}, bunds={BUNDS}, "
                f"z_bund={Z_BUND}m (stored as {field.z_bund}mm)")
    return field


if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs()
    try:
        field = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        sys.exit(2)
    logger.info("Tool completed successfully.")
    sys.exit(0)
