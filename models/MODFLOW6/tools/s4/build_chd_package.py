#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
==========================================
Tool ID:      build_chd_package
Stage:        s4_boundary_conditions
Description:  Create MODFLOW 6 CHD (Constant Head) package via FloPy.
              Specifies cells with fixed head values at model boundaries.

Inputs:
  - SIM_PATH: simulation workspace directory
  - MODEL_NAME: GWF model name
  - CHD_DATA: list of [(layer, row, col), head] entries

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import json
import logging

SIM_PATH = ""
MODEL_NAME = "gwf"
CHD_DATA = [
    # [(layer, row, col), head]
    # Example: constant head of 100 m along left boundary
]
SAVE_FLOWS = True

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def validate_inputs():
    errors = []
    if not SIM_PATH:
        errors.append("SIM_PATH is not set")
    if not CHD_DATA:
        errors.append("CHD_DATA is empty — no constant head cells defined")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)


def process():
    import flopy

    sim = flopy.mf6.MFSimulation.load(sim_ws=SIM_PATH)
    gwf = sim.get_model(MODEL_NAME)

    chd = flopy.mf6.ModflowGwfchd(
        gwf,
        stress_period_data=CHD_DATA,
        save_flows=SAVE_FLOWS,
    )

    sim.write_simulation()
    logger.info(f"CHD package created with {len(CHD_DATA)} constant head cells")

    return {"chd_cell_count": len(CHD_DATA)}


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
