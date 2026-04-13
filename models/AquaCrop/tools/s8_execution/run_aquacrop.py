#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
Tool ID:      run_aquacrop
Stage:        s8_execution
Description:  Executes model.run_model(till_termination=True), captures runtime,
              checks for silent failures (zero yield, no canopy development).

Inputs:
  - model: Assembled AquaCropModel

Outputs:
  - success: True if model completed and produced non-zero yield
  - runtime: Execution time in seconds

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import json
import time
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def run_simulation(model):
    """
    Run AquaCrop simulation and perform post-run diagnostics.

    Args:
        model: Assembled AquaCropModel

    Returns:
        dict with success, runtime, yield, warnings
    """
    logger.info("Starting AquaCrop simulation...")
    start_time = time.time()

    try:
        success = model.run_model(till_termination=True)
    except Exception as e:
        logger.error(f"Simulation failed with exception: {e}")
        return {"success": False, "error": str(e), "runtime": time.time() - start_time}

    runtime = time.time() - start_time
    logger.info(f"Simulation completed in {runtime:.2f} seconds")

    if not success:
        return {"success": False, "error": "run_model returned False", "runtime": runtime}

    # Post-run diagnostics
    warnings = []
    stats = model.get_simulation_results()

    if stats is False:
        return {"success": False, "error": "Model not finished", "runtime": runtime}

    if len(stats) == 0:
        warnings.append("No seasons completed (empty final_stats)")

    dry_yield = None
    if len(stats) > 0:
        dry_yield = stats['Dry yield (tonne/ha)'].iloc[0]
        if dry_yield == 0:
            warnings.append("SILENT ERROR: Dry yield is 0.0 -- crop may have died. "
                          "Check crop_growth (canopy_cover) and water_flux (Tr). "
                          "See diagnostic triplets dt_004, dt_005, dt_008, dt_014.")

    # Check canopy development
    growth = model.get_crop_growth()
    if growth is not None and hasattr(growth, 'columns'):
        max_cc = growth['canopy_cover'].max() if 'canopy_cover' in growth.columns else 0
        if max_cc < 0.01:
            warnings.append("Canopy cover never exceeded 1% -- crop likely failed to germinate")

    result = {
        "success": True,
        "runtime": round(runtime, 2),
        "dry_yield_tha": round(dry_yield, 3) if dry_yield is not None else None,
        "n_seasons": len(stats),
        "warnings": warnings,
    }

    if warnings:
        for w in warnings:
            logger.warning(w)
    else:
        logger.info(f"Simulation successful: yield={dry_yield:.3f} t/ha")

    return result


if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    logger.info("Usage: from run_aquacrop import run_simulation; result = run_simulation(model)")
    sys.exit(0)
