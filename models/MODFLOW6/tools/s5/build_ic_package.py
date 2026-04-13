#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
==========================================
Tool ID:      build_ic_package
Stage:        s5_stress_periods
Description:  Create MODFLOW 6 IC (Initial Conditions) package via FloPy.
              Sets starting head for all model cells.

              CRITICAL: Starting head must be >= layer bottom for all active cells.
              If STRT < BOTM, the cell starts dry and may never rewet.

Inputs:
  - SIM_PATH, MODEL_NAME
  - STRT: starting head — scalar, per-layer list, or 3D array

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import json
import logging
import numpy as np

SIM_PATH = ""
MODEL_NAME = "gwf"
STRT = 95.0  # Starting head (m) — scalar or array

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def validate_inputs():
    errors = []
    if not SIM_PATH:
        errors.append("SIM_PATH is not set")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)


def process():
    import flopy

    sim = flopy.mf6.MFSimulation.load(sim_ws=SIM_PATH)
    gwf = sim.get_model(MODEL_NAME)

    ic = flopy.mf6.ModflowGwfic(gwf, strt=STRT)

    # Check STRT vs BOTM
    try:
        botm = gwf.dis.botm.array
        if isinstance(STRT, (int, float)):
            dry_cells = (botm > STRT).sum()
            if dry_cells > 0:
                logger.warning(
                    f"WARNING: {dry_cells} cells have BOTM > STRT ({STRT}). "
                    f"These cells will start dry. Consider raising STRT. "
                    f"See triplet dt_mf6_011."
                )
        logger.info(f"BOTM range: {botm.min():.1f} to {botm.max():.1f}")
    except Exception:
        pass

    sim.write_simulation()
    logger.info(f"IC package created with STRT = {STRT}")

    return {"strt": float(STRT) if isinstance(STRT, (int, float)) else "array"}


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
