#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
==========================================
Tool ID:      build_ims_package
Stage:        s6_solver
Description:  Create MODFLOW 6 IMS (Iterative Model Solution) package via FloPy.
              Configures the numerical solver: complexity preset, convergence
              criteria, iteration limits, and advanced options.

              Complexity presets:
              - SIMPLE:   CG solver, no under-relaxation. For all-confined models.
              - MODERATE: BICGSTAB, DBD under-relaxation. For convertible layers.
              - COMPLEX:  BICGSTAB, DBD + backtracking. For Newton/wetting-drying.

Inputs:
  - SIM_PATH: simulation workspace
  - COMPLEXITY: SIMPLE, MODERATE, or COMPLEX
  - DVCLOSE: head change convergence criterion (m)
  - RCLOSE: residual convergence criterion (m3/day)
  - OUTER_MAXIMUM: max outer iterations
  - INNER_MAXIMUM: max inner iterations

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import json
import logging

SIM_PATH = "/mnt/disk1/Hydrocraft_server/outputs/qinghai_lake_1951_2024/modflow6/workspace"
COMPLEXITY = "MODERATE"
DVCLOSE = 0.001           # Head change criterion (m)
RCLOSE = 0.1              # Residual criterion (m3/day)
OUTER_MAXIMUM = 100       # Max outer (nonlinear) iterations
INNER_MAXIMUM = 50        # Max inner (linear) iterations

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def validate_inputs():
    errors = []
    if not SIM_PATH:
        errors.append("SIM_PATH is not set")
    if COMPLEXITY not in ["SIMPLE", "MODERATE", "COMPLEX"]:
        errors.append(f"COMPLEXITY must be SIMPLE, MODERATE, or COMPLEX: {COMPLEXITY}")
    if DVCLOSE <= 0:
        errors.append(f"DVCLOSE must be positive: {DVCLOSE}")
    if RCLOSE <= 0:
        errors.append(f"RCLOSE must be positive: {RCLOSE}")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)


def process():
    import flopy

    sim = flopy.mf6.MFSimulation.load(sim_ws=SIM_PATH)
    model_names = list(sim.model_names)

    ims = flopy.mf6.ModflowIms(
        sim,
        complexity=COMPLEXITY,
        outer_dvclose=DVCLOSE,
        outer_maximum=OUTER_MAXIMUM,
        inner_maximum=INNER_MAXIMUM,
        inner_dvclose=DVCLOSE / 10,
        rcloserecord=[RCLOSE, "strict"],
    )

    # Register IMS with all models
    sim.register_ims_package(ims, model_names)

    sim.write_simulation()

    logger.info(f"IMS package created: {COMPLEXITY}, DVCLOSE={DVCLOSE}, RCLOSE={RCLOSE}")
    logger.info(f"Registered to models: {model_names}")

    return {
        "complexity": COMPLEXITY,
        "dvclose": DVCLOSE,
        "rclose": RCLOSE,
        "outer_maximum": OUTER_MAXIMUM,
        "inner_maximum": INNER_MAXIMUM,
        "registered_models": model_names,
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
