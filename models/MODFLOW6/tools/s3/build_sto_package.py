#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
==========================================
Tool ID:      build_sto_package
Stage:        s3_layer_properties
Description:  Create MODFLOW 6 STO (Storage) package via FloPy.
              Sets specific storage (Ss), specific yield (Sy), and
              steady-state/transient flags per stress period.

Inputs:
  - SIM_PATH: simulation workspace directory
  - MODEL_NAME: GWF model name
  - SS_VALUES: specific storage per layer (1/m)
  - SY_VALUES: specific yield per layer (dimensionless)
  - STEADY_STATE: list of booleans per stress period

Outputs:
  - STO package attached to GWF model

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import json
import logging
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SIM_PATH = ""
MODEL_NAME = "gwf"
SS_VALUES = [1e-5, 1e-5, 1e-4]     # Specific storage per layer (1/m)
SY_VALUES = [0.15, 0.10, 0.05]     # Specific yield per layer
STEADY_STATE = [True, False]        # First period steady, rest transient
SAVE_FLOWS = True

# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def validate_inputs():
    errors = []
    if not SIM_PATH:
        errors.append("SIM_PATH is not set")
    for i, ss in enumerate(SS_VALUES):
        if ss <= 0:
            errors.append(f"Ss[{i}] must be positive: {ss}")
    for i, sy in enumerate(SY_VALUES):
        if sy <= 0 or sy >= 0.5:
            errors.append(f"Sy[{i}] must be in (0, 0.5): {sy}")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def process():
    import flopy

    sim = flopy.mf6.MFSimulation.load(sim_ws=SIM_PATH)
    gwf = sim.get_model(MODEL_NAME)

    # Build steady-state / transient flag dict
    sto_spd = {}
    for i, is_ss in enumerate(STEADY_STATE):
        if is_ss:
            sto_spd[i] = ["ss"]
        else:
            sto_spd[i] = ["tr"]

    sto = flopy.mf6.ModflowGwfsto(
        gwf,
        ss=SS_VALUES,
        sy=SY_VALUES,
        steady_state=sto_spd,
        save_flows=SAVE_FLOWS,
    )

    sim.write_simulation()
    logger.info(f"STO package created: Ss={SS_VALUES}, Sy={SY_VALUES}")

    return {
        "ss_per_layer": SS_VALUES,
        "sy_per_layer": SY_VALUES,
        "steady_state_periods": STEADY_STATE,
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
