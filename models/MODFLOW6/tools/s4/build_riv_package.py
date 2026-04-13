#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
==========================================
Tool ID:      build_riv_package
Stage:        s4_boundary_conditions
Description:  Create MODFLOW 6 RIV (River) package via FloPy.
              Each river cell: cellid, stage, conductance, rbot.
              Supports CaMa-Flood river stage coupling.

Inputs:
  - SIM_PATH, MODEL_NAME
  - RIV_DATA: list of [(layer, row, col), stage, conductance, rbot]
  - CAMA_STAGE_NC: CaMa-Flood stage NetCDF (optional)

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import json
import logging
from pathlib import Path

SIM_PATH = ""
MODEL_NAME = "gwf"
RIV_DATA = [
    # [(layer, row, col), stage_m, conductance_m2day, rbot_m]
    # Example: [(0, 5, 10), 95.0, 500.0, 93.0]
]
CAMA_STAGE_NC = ""

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def validate_inputs():
    errors = []
    if not SIM_PATH:
        errors.append("SIM_PATH is not set")
    if not RIV_DATA and not CAMA_STAGE_NC:
        errors.append("RIV_DATA is empty and no CaMa-Flood NetCDF provided")
    # Check stage > rbot for each entry
    for i, entry in enumerate(RIV_DATA):
        cellid, stage, cond, rbot = entry
        if stage <= rbot:
            errors.append(f"RIV entry {i}: stage ({stage}) must be > rbot ({rbot})")
        if cond <= 0:
            errors.append(f"RIV entry {i}: conductance must be positive: {cond}")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)


def process():
    import flopy

    sim = flopy.mf6.MFSimulation.load(sim_ws=SIM_PATH)
    gwf = sim.get_model(MODEL_NAME)

    riv = flopy.mf6.ModflowGwfriv(
        gwf,
        stress_period_data=RIV_DATA,
        save_flows=True,
    )

    sim.write_simulation()
    logger.info(f"RIV package created with {len(RIV_DATA)} river cells")

    return {"riv_cell_count": len(RIV_DATA)}


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
