#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
==========================================
Tool ID:      build_rch_package
Stage:        s4_boundary_conditions
Description:  Create MODFLOW 6 RCH (Recharge) package via FloPy.
              Applies areal recharge to the highest active cell in each column.
              Supports VIC deep percolation coupling via NetCDF input.

              CRITICAL UNIT CONVERSION:
              VIC OUT_BASEFLOW is in mm/day.
              MODFLOW RCH expects m/day (if LENGTH_UNITS=meters).
              This tool divides by 1000 when reading VIC data.

Inputs:
  - SIM_PATH: simulation workspace directory
  - MODEL_NAME: GWF model name
  - RECHARGE_RATE: uniform recharge rate (m/day) OR
  - VIC_RECHARGE_NC: NetCDF with VIC deep percolation (mm/day)

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import json
import logging
import numpy as np
from pathlib import Path

SIM_PATH = ""
MODEL_NAME = "gwf"
RECHARGE_RATE = 0.001     # m/day (= 1 mm/day). Typical: 0.0001 to 0.01
VIC_RECHARGE_NC = ""      # Optional: NetCDF with VIC deep percolation

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def validate_inputs():
    errors = []
    if not SIM_PATH:
        errors.append("SIM_PATH is not set")
    if RECHARGE_RATE <= 0 and not VIC_RECHARGE_NC:
        errors.append(f"RECHARGE_RATE must be positive: {RECHARGE_RATE}")
    if RECHARGE_RATE > 0.1:
        logger.warning(
            f"RECHARGE_RATE = {RECHARGE_RATE} m/day seems high (>100 mm/day). "
            f"Did you forget to convert from mm/day? Divide by 1000."
        )
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)


def process():
    import flopy

    sim = flopy.mf6.MFSimulation.load(sim_ws=SIM_PATH)
    gwf = sim.get_model(MODEL_NAME)

    if VIC_RECHARGE_NC and Path(VIC_RECHARGE_NC).exists():
        # Read VIC deep percolation and convert mm/day -> m/day
        import xarray as xr
        ds = xr.open_dataset(VIC_RECHARGE_NC)
        # Expect variable named 'baseflow' or 'deep_percolation'
        for varname in ['baseflow', 'deep_percolation', 'OUT_BASEFLOW']:
            if varname in ds:
                rch_mm_day = ds[varname].values
                break
        else:
            raise ValueError(f"No recharge variable found in {VIC_RECHARGE_NC}")

        # CRITICAL: Convert mm/day to m/day
        rch_m_day = rch_mm_day / 1000.0
        logger.info(f"VIC recharge loaded: mean={rch_mm_day.mean():.3f} mm/day "
                     f"= {rch_m_day.mean():.6f} m/day")
        recharge = rch_m_day
    else:
        recharge = RECHARGE_RATE
        logger.info(f"Uniform recharge: {RECHARGE_RATE} m/day ({RECHARGE_RATE*1000:.1f} mm/day)")

    # Use array-based RCH (applies to highest active cell automatically)
    rch = flopy.mf6.ModflowGwfrcha(
        gwf,
        recharge=recharge,
        save_flows=True,
    )

    sim.write_simulation()

    mean_rch = float(np.mean(recharge)) if isinstance(recharge, np.ndarray) else float(recharge)
    return {
        "mean_recharge_m_day": mean_rch,
        "mean_recharge_mm_day": mean_rch * 1000,
        "source": "VIC NetCDF" if VIC_RECHARGE_NC else "uniform",
    }


def validate_outputs(result):
    if result["mean_recharge_m_day"] > 0.1:
        logger.warning(
            f"Mean recharge is {result['mean_recharge_mm_day']:.1f} mm/day — "
            f"this is very high. Verify units. See triplet dt_mf6_004."
        )
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
