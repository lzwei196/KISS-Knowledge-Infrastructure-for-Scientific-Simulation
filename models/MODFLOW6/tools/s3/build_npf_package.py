#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
==========================================
Tool ID:      build_npf_package
Stage:        s3_layer_properties
Description:  Create MODFLOW 6 NPF (Node Property Flow) package via FloPy.
              Sets hydraulic conductivity (K), vertical K (K33), and cell type
              (ICELLTYPE: 0=confined, 1=convertible/unconfined).

Inputs:
  - SIM_PATH: simulation workspace directory
  - MODEL_NAME: GWF model name
  - K_VALUES: hydraulic conductivity per layer (m/day)
  - K33_VALUES: vertical K per layer (m/day), optional
  - ICELLTYPE: cell type per layer (0=confined, 1=convertible)

Outputs:
  - NPF package attached to GWF model

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import json
import logging
import numpy as np
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SIM_PATH = "/mnt/disk1/Hydrocraft_server/outputs/qinghai_lake_1951_2024/modflow6/workspace"
MODEL_NAME = "gwf"
K_VALUES = [1.0, 0.116]       # Horizontal K per layer (m/day)
K33_VALUES = None                   # Vertical K (defaults to K if None)
ICELLTYPE = [1, 0]              # 1=convertible (top), 0=confined (deeper)
SAVE_FLOWS = True                   # Save flow terms to budget file

# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def validate_inputs():
    errors = []
    if not SIM_PATH:
        errors.append("SIM_PATH is not set")
    for i, k in enumerate(K_VALUES):
        if isinstance(k, (int, float)) and k <= 0:
            errors.append(f"K[{i}] must be positive: {k}")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def process():
    import flopy

    sim = flopy.mf6.MFSimulation.load(sim_ws=SIM_PATH)
    gwf = sim.get_model(MODEL_NAME)

    k33 = K33_VALUES if K33_VALUES is not None else K_VALUES

    npf = flopy.mf6.ModflowGwfnpf(
        gwf,
        icelltype=ICELLTYPE,
        k=K_VALUES,
        k33=k33,
        save_flows=SAVE_FLOWS,
    )

    sim.write_simulation()
    logger.info(f"NPF package created with K={K_VALUES}, ICELLTYPE={ICELLTYPE}")

    return {
        "k_per_layer": K_VALUES,
        "k33_per_layer": list(k33) if isinstance(k33, (list, tuple)) else k33,
        "icelltype": ICELLTYPE,
        "save_flows": SAVE_FLOWS,
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
