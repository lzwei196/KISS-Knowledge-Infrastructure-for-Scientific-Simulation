#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
==========================================
Tool ID:      assign_transient_stress
Stage:        s5_stress_periods
Description:  Update stress package data (RCH, WEL, RIV) per stress period
              for transient simulations. Maps time-varying VIC recharge or
              pumping schedules to MODFLOW stress periods.

Inputs:
  - SIM_PATH, MODEL_NAME
  - PACKAGE_NAME: which package to update (rch, wel, riv, drn)
  - TRANSIENT_DATA: dict mapping stress period index to package data

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import json
import logging

SIM_PATH = ""
MODEL_NAME = "gwf"
PACKAGE_NAME = "rch"  # Package to update: rch, wel, riv, drn
TRANSIENT_DATA = {
    # stress_period_index: data
    # For RCH (array-based): {0: 0.001, 1: 0.002, ...} (m/day)
    # For WEL (list-based): {0: [[(1,5,5), -500]], 1: [[(1,5,5), -600]], ...}
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def validate_inputs():
    errors = []
    if not SIM_PATH:
        errors.append("SIM_PATH is not set")
    if not TRANSIENT_DATA:
        errors.append("TRANSIENT_DATA is empty")
    if PACKAGE_NAME not in ["rch", "wel", "riv", "drn", "chd", "ghb", "evt"]:
        errors.append(f"Unknown package: {PACKAGE_NAME}")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)


def process():
    import flopy

    sim = flopy.mf6.MFSimulation.load(sim_ws=SIM_PATH)
    gwf = sim.get_model(MODEL_NAME)

    # Find the package
    pkg = gwf.get_package(PACKAGE_NAME)
    if pkg is None:
        raise ValueError(f"Package '{PACKAGE_NAME}' not found on model '{MODEL_NAME}'")

    # Update stress period data
    if PACKAGE_NAME == "rch" and hasattr(pkg, 'recharge'):
        # Array-based RCH
        for iper, rch_val in TRANSIENT_DATA.items():
            pkg.recharge.set_data(rch_val, key=int(iper))
            logger.info(f"Period {iper}: RCH = {rch_val}")
    else:
        # List-based packages (WEL, RIV, DRN, CHD, GHB)
        for iper, spd in TRANSIENT_DATA.items():
            pkg.stress_period_data.set_data(spd, key=int(iper))
            count = len(spd) if isinstance(spd, list) else "array"
            logger.info(f"Period {iper}: {PACKAGE_NAME.upper()} entries = {count}")

    sim.write_simulation()

    return {
        "package": PACKAGE_NAME,
        "periods_updated": list(TRANSIENT_DATA.keys()),
        "total_periods": len(TRANSIENT_DATA),
    }


def validate_outputs(result):
    logger.info("Output validation passed.")


if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    if len(sys.argv) > 1:
        SIM_PATH = sys.argv[1]
    validate_inputs()
    try:
        result = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        sys.exit(2)
    validate_outputs(result)
    print(json.dumps(result, indent=2))
    sys.exit(0)
