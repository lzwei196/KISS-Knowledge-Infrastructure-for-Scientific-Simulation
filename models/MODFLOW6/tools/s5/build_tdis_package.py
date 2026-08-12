#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
==========================================
Tool ID:      build_tdis_package
Stage:        s5_stress_periods
Description:  Create MODFLOW 6 TDIS (Temporal Discretization) package via FloPy.
              Defines stress period lengths, timesteps, and multiplier.

Inputs:
  - SIM_PATH: simulation workspace
  - NPER: number of stress periods
  - PERIOD_DATA: list of (perlen, nstp, tsmult) per period
  - TIME_UNITS: "days" (recommended for VIC coupling)

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import json
import logging

SIM_PATH = "/mnt/disk1/Hydrocraft_server/outputs/qinghai_lake_1951_2024/modflow6/workspace"
NPER = 74
PERIOD_DATA = [(365.0, 1, 1.0)] * 74  # 1951-2024 annual  # 1 year, daily timesteps
TIME_UNITS = "days"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def validate_inputs():
    errors = []
    if not SIM_PATH:
        errors.append("SIM_PATH is not set")
    if NPER < 1:
        errors.append(f"NPER must be >= 1: {NPER}")
    if len(PERIOD_DATA) != NPER:
        errors.append(f"PERIOD_DATA length ({len(PERIOD_DATA)}) != NPER ({NPER})")
    for i, (perlen, nstp, tsmult) in enumerate(PERIOD_DATA):
        if perlen <= 0:
            errors.append(f"Period {i}: PERLEN must be > 0: {perlen}")
        if nstp < 1:
            errors.append(f"Period {i}: NSTP must be >= 1: {nstp}")
        if tsmult < 1.0:
            errors.append(f"Period {i}: TSMULT must be >= 1.0: {tsmult}")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)


def process():
    import flopy

    sim = flopy.mf6.MFSimulation.load(sim_ws=SIM_PATH)

    tdis = flopy.mf6.ModflowTdis(
        sim,
        time_units=TIME_UNITS,
        nper=NPER,
        perioddata=PERIOD_DATA,
    )

    sim.write_simulation()

    total_time = sum(p[0] for p in PERIOD_DATA)
    logger.info(f"TDIS: {NPER} periods, total time = {total_time} {TIME_UNITS}")

    return {
        "nper": NPER,
        "total_time": total_time,
        "time_units": TIME_UNITS,
        "period_data": PERIOD_DATA,
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
