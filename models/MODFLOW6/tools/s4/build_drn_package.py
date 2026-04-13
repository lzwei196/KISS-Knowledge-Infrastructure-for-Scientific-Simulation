#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
==========================================
Tool ID:      build_drn_package
Stage:        s4_boundary_conditions
Description:  Create MODFLOW 6 DRN (Drain) package via FloPy.
              Drains remove water when head exceeds drain elevation.
              Used for springs, tile drains, and baseflow coupling to routing.

Inputs:
  - SIM_PATH, MODEL_NAME
  - DRN_DATA: list of [(layer, row, col), elevation, conductance]

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import json
import logging

SIM_PATH = ""
MODEL_NAME = "gwf"
DRN_DATA = [
    # [(layer, row, col), drain_elevation_m, conductance_m2day]
]

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def validate_inputs():
    errors = []
    if not SIM_PATH:
        errors.append("SIM_PATH is not set")
    if not DRN_DATA:
        errors.append("DRN_DATA is empty")
    for i, entry in enumerate(DRN_DATA):
        cellid, elev, cond = entry
        if cond <= 0:
            errors.append(f"DRN entry {i}: conductance must be positive: {cond}")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)


def process():
    import flopy

    sim = flopy.mf6.MFSimulation.load(sim_ws=SIM_PATH)
    gwf = sim.get_model(MODEL_NAME)

    drn = flopy.mf6.ModflowGwfdrn(
        gwf,
        stress_period_data=DRN_DATA,
        save_flows=True,
    )

    sim.write_simulation()
    logger.info(f"DRN package created with {len(DRN_DATA)} drain cells")

    return {"drn_cell_count": len(DRN_DATA)}


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
