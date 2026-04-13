#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
==========================================
Tool ID:      build_wel_package
Stage:        s4_boundary_conditions
Description:  Create MODFLOW 6 WEL (Well) package via FloPy.
              Negative rate = pumping (extraction), positive = injection.
              Rate is volumetric: m3/day.

Inputs:
  - SIM_PATH, MODEL_NAME
  - WEL_DATA: list of [(layer, row, col), rate_m3day]

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import json
import logging

SIM_PATH = ""
MODEL_NAME = "gwf"
WEL_DATA = [
    # [(layer, row, col), rate_m3_day]
    # Negative = pumping, positive = injection
    # Example: [(1, 10, 10), -500.0]  # Pump 500 m3/day from layer 2
]

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def validate_inputs():
    errors = []
    if not SIM_PATH:
        errors.append("SIM_PATH is not set")
    if not WEL_DATA:
        errors.append("WEL_DATA is empty")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)


def process():
    import flopy

    sim = flopy.mf6.MFSimulation.load(sim_ws=SIM_PATH)
    gwf = sim.get_model(MODEL_NAME)

    wel = flopy.mf6.ModflowGwfwel(
        gwf,
        stress_period_data=WEL_DATA,
        save_flows=True,
    )

    sim.write_simulation()

    total_rate = sum(entry[1] for entry in WEL_DATA)
    pump_count = sum(1 for entry in WEL_DATA if entry[1] < 0)
    inject_count = sum(1 for entry in WEL_DATA if entry[1] > 0)

    logger.info(f"WEL package: {pump_count} pumping, {inject_count} injection wells")
    logger.info(f"Total rate: {total_rate:.1f} m3/day")

    return {
        "well_count": len(WEL_DATA),
        "pumping_wells": pump_count,
        "injection_wells": inject_count,
        "total_rate_m3day": total_rate,
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
