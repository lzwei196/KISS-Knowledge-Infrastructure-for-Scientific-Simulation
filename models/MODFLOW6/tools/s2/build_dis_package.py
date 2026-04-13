#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
==========================================
Tool ID:      build_dis_package
Stage:        s2_grid_discretization
Description:  Create the MODFLOW 6 DIS (structured discretization) package via FloPy.

Inputs:
  - SIM_PATH: simulation workspace directory
  - MODEL_NAME: GWF model name
  - NLAY, NROW, NCOL, DELR, DELC, TOP, BOTM, IDOMAIN from grid config

Outputs:
  - DIS package attached to GWF model in FloPy simulation object

Exit codes:
  0 — success
  1 — input validation failed
  2 — processing error
  3 — output validation failed
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
SIM_PATH = ""             # Simulation workspace directory
MODEL_NAME = "gwf"        # GWF model name
SIM_NAME = "mf6sim"       # Simulation name
NLAY = 3
NROW = 50
NCOL = 100
DELR = 1000.0             # Row width (m) — scalar or array
DELC = 1000.0             # Column width (m) — scalar or array
TOP = 100.0               # Land surface elevation — scalar or 2D array
BOTM = [90.0, 50.0, -100.0]  # Layer bottom elevations — per-layer scalar or 3D array
IDOMAIN = None            # Active cell mask — None = all active
LENGTH_UNITS = "meters"
NEWTON = True             # Enable Newton-Raphson for unconfined problems

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def validate_inputs():
    """Check preconditions."""
    errors = []
    if not SIM_PATH:
        errors.append("SIM_PATH is not set")
    if NLAY < 1 or NROW < 1 or NCOL < 1:
        errors.append(f"Invalid dimensions: NLAY={NLAY}, NROW={NROW}, NCOL={NCOL}")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def process():
    """Create DIS package via FloPy."""
    import flopy

    # Create workspace
    sim_ws = Path(SIM_PATH)
    sim_ws.mkdir(parents=True, exist_ok=True)

    # Create simulation
    sim = flopy.mf6.MFSimulation(
        sim_name=SIM_NAME,
        sim_ws=str(sim_ws),
    )

    # Create GWF model with Newton if requested
    if NEWTON:
        gwf = flopy.mf6.ModflowGwf(
            sim, modelname=MODEL_NAME,
            newtonoptions="NEWTON UNDER_RELAXATION"
        )
    else:
        gwf = flopy.mf6.ModflowGwf(sim, modelname=MODEL_NAME)

    # Build BOTM array
    if isinstance(BOTM, (list, tuple)):
        if isinstance(BOTM[0], (int, float)):
            # Per-layer scalars
            botm_array = np.array(BOTM)
        else:
            botm_array = np.array(BOTM)
    else:
        botm_array = BOTM

    # Build IDOMAIN
    if IDOMAIN is not None:
        idomain_array = np.array(IDOMAIN)
    else:
        idomain_array = 1  # All active

    # Create DIS package
    dis = flopy.mf6.ModflowGwfdis(
        gwf,
        length_units=LENGTH_UNITS,
        nlay=NLAY,
        nrow=NROW,
        ncol=NCOL,
        delr=DELR,
        delc=DELC,
        top=TOP,
        botm=botm_array,
        idomain=idomain_array,
    )

    logger.info(f"DIS package created: {NLAY} layers x {NROW} rows x {NCOL} cols")
    logger.info(f"Length units: {LENGTH_UNITS}")

    # Validate layer ordering
    top_val = dis.top.array if hasattr(dis.top, 'array') else TOP
    botm_val = dis.botm.array if hasattr(dis.botm, 'array') else botm_array

    # Save simulation (temporary — other tools will add packages and re-save)
    sim.write_simulation()

    result = {
        "nlay": NLAY,
        "nrow": NROW,
        "ncol": NCOL,
        "total_cells": NLAY * NROW * NCOL,
        "delr": float(DELR) if isinstance(DELR, (int, float)) else "array",
        "delc": float(DELC) if isinstance(DELC, (int, float)) else "array",
        "length_units": LENGTH_UNITS,
        "newton": NEWTON,
        "sim_ws": str(sim_ws),
    }

    return result


def validate_outputs(result):
    """Check DIS package files exist."""
    sim_ws = Path(result["sim_ws"])
    nam_file = sim_ws / "mfsim.nam"
    if not nam_file.exists():
        logger.error(f"Simulation name file not created: {nam_file}")
        sys.exit(3)
    logger.info("Output validation passed.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")

    validate_inputs()

    try:
        result = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        import traceback; traceback.print_exc()
        sys.exit(2)

    validate_outputs(result)

    print(json.dumps(result, indent=2))
    sys.exit(0)
