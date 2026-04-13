#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
Tool ID:      create_irrigation_management
Stage:        s5_irrigation
Description:  Creates IrrigationManagement object for rainfed, SMT-based, interval,
              schedule, net irrigation, or constant depth strategies. Validates
              method-specific parameters.

Inputs:
  - irrigation_method: 0=rainfed, 1=SMT, 2=interval, 3=schedule, 4=net, 5=constant
  - kwargs: Method-specific parameters (SMT, IrrInterval, Schedule, etc.)

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
IRRIGATION_METHOD = 0    # 0=rainfed, 1=SMT, 2=interval, 3=schedule, 4=net, 5=constant
SMT = [100, 100, 100, 100]  # Soil moisture targets (% TAW) for method=1
IRR_INTERVAL = 3         # Days between events for method=2
NET_IRR_SMT = 80.0       # Net irrigation threshold (% TAW) for method=4
DEPTH = 0.0              # Constant depth (mm) for method=5
WET_SURF = 100.0         # % soil surface wetted
APP_EFF = 100.0           # Application efficiency (%)
MAX_IRR = 25.0            # Max daily application (mm)
MAX_IRR_SEASON = 10000.0  # Max seasonal application (mm)


def validate_inputs():
    errors = []
    if IRRIGATION_METHOD not in [0, 1, 2, 3, 4, 5]:
        errors.append(f"irrigation_method {IRRIGATION_METHOD} not in [0,1,2,3,4,5]")
    if IRRIGATION_METHOD == 1:
        if len(SMT) != 4:
            errors.append(f"SMT must have 4 values, got {len(SMT)}")
        for s in SMT:
            if not (0 <= s <= 100):
                errors.append(f"SMT value {s} out of range 0-100")
    if not (0 < APP_EFF <= 100):
        errors.append(f"AppEff {APP_EFF} out of range (0, 100]")
    if MAX_IRR <= 0:
        errors.append(f"MaxIrr {MAX_IRR} must be > 0")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def process():
    try:
        from aquacrop import IrrigationManagement
    except ImportError:
        logger.error("aquacrop not installed. Run: pip install aquacrop")
        sys.exit(2)

    kwargs = {
        'WetSurf': WET_SURF,
        'AppEff': APP_EFF,
        'MaxIrr': MAX_IRR,
        'MaxIrrSeason': MAX_IRR_SEASON,
    }

    if IRRIGATION_METHOD == 1:
        kwargs['SMT'] = SMT
    elif IRRIGATION_METHOD == 2:
        kwargs['IrrInterval'] = IRR_INTERVAL
    elif IRRIGATION_METHOD == 4:
        kwargs['NetIrrSMT'] = NET_IRR_SMT
    elif IRRIGATION_METHOD == 5:
        kwargs['depth'] = DEPTH

    irr = IrrigationManagement(irrigation_method=IRRIGATION_METHOD, **kwargs)

    method_names = {0: 'rainfed', 1: 'SMT', 2: 'interval', 3: 'schedule', 4: 'net', 5: 'constant'}
    logger.info(f"IrrigationManagement created: method={method_names.get(IRRIGATION_METHOD, '?')}")
    return irr


if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs()
    try:
        irr = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        sys.exit(2)
    logger.info("Tool completed successfully.")
    sys.exit(0)
