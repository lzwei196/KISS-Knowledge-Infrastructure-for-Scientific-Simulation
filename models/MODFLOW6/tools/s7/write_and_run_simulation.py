#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
==========================================
Tool ID:      write_and_run_simulation
Stage:        s7_execution
Description:  Write all FloPy packages to MODFLOW 6 input files and execute mf6.
              Checks listing file for convergence failures, budget errors, and
              dry cell warnings after completion.

Inputs:
  - SIM_PATH: simulation workspace directory
  - MF6_PATH: path to mf6 executable (optional, auto-detected)
  - SILENT: suppress mf6 stdout (default False)

Outputs:
  - JSON with success, runtime, convergence_failures, budget_error, dry_cells

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import json
import logging
import time
import re
from pathlib import Path

SIM_PATH = ""
MF6_PATH = ""         # Optional: path to mf6 binary
SILENT = False

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def validate_inputs():
    errors = []
    if not SIM_PATH:
        errors.append("SIM_PATH is not set")
    elif not Path(SIM_PATH).exists():
        errors.append(f"SIM_PATH does not exist: {SIM_PATH}")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)


def check_listing_file(sim_ws, model_name="gwf"):
    """Parse listing file for diagnostics."""
    diagnostics = {
        "normal_termination": False,
        "convergence_failures": 0,
        "max_budget_error_pct": 0.0,
        "dry_cell_count": 0,
        "warnings": [],
    }

    # Check simulation listing
    sim_lst = Path(sim_ws) / "mfsim.lst"
    if sim_lst.exists():
        content = sim_lst.read_text()
        if "Normal termination" in content:
            diagnostics["normal_termination"] = True

    # Check model listing
    model_lst = Path(sim_ws) / f"{model_name}.lst"
    if model_lst.exists():
        content = model_lst.read_text()

        # Count convergence failures
        diagnostics["convergence_failures"] = content.count("FAILED TO CONVERGE")

        # Find max budget error
        pct_matches = re.findall(r"PERCENT DISCREPANCY\s*=\s*([-\d.]+)", content)
        if pct_matches:
            errors = [abs(float(p)) for p in pct_matches]
            diagnostics["max_budget_error_pct"] = max(errors)

        # Count dry cells
        diagnostics["dry_cell_count"] = content.count("DRY")

    return diagnostics


def process():
    import flopy

    sim_ws = Path(SIM_PATH)

    # Load simulation
    sim = flopy.mf6.MFSimulation.load(sim_ws=str(sim_ws))

    # Write input files
    logger.info("Writing simulation files...")
    sim.write_simulation()

    # Get model name for listing file check
    model_names = list(sim.model_names)
    model_name = model_names[0] if model_names else "gwf"

    # Run mf6
    logger.info("Running MODFLOW 6...")
    t0 = time.time()

    exe_name = MF6_PATH if MF6_PATH else "mf6"
    success, buff = sim.run_simulation(silent=SILENT, exe_name=exe_name)

    runtime = time.time() - t0
    logger.info(f"Runtime: {runtime:.1f} seconds")

    # Check results
    diagnostics = check_listing_file(sim_ws, model_name)

    result = {
        "success": success,
        "runtime_seconds": round(runtime, 1),
        "normal_termination": diagnostics["normal_termination"],
        "convergence_failures": diagnostics["convergence_failures"],
        "max_budget_error_pct": diagnostics["max_budget_error_pct"],
        "dry_cell_warnings": diagnostics["dry_cell_count"],
        "model_name": model_name,
        "sim_ws": str(sim_ws),
    }

    # Check output files
    hds_file = sim_ws / f"{model_name}.hds"
    cbc_file = sim_ws / f"{model_name}.cbc"
    result["hds_exists"] = hds_file.exists()
    result["cbc_exists"] = cbc_file.exists()

    if not success:
        logger.error("MODFLOW 6 run FAILED. Check listing file for details.")
        logger.error(f"Convergence failures: {diagnostics['convergence_failures']}")
    else:
        logger.info("MODFLOW 6 completed successfully.")

    if diagnostics["convergence_failures"] > 0:
        logger.warning(
            f"{diagnostics['convergence_failures']} convergence failures detected. "
            f"See triplet dt_mf6_001."
        )

    if diagnostics["max_budget_error_pct"] > 0.1:
        logger.warning(
            f"Budget error {diagnostics['max_budget_error_pct']:.4f}% exceeds 0.1%. "
            f"See triplet dt_mf6_003."
        )

    return result


def validate_outputs(result):
    if not result["success"]:
        logger.error("Simulation failed")
        print(json.dumps(result, indent=2))
        sys.exit(3)
    if not result["hds_exists"]:
        logger.error("Head file not created — check OC package")
    logger.info("Output validation passed.")


if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    if len(sys.argv) > 1:
        SIM_PATH = sys.argv[1]
    if len(sys.argv) > 2:
        MF6_PATH = sys.argv[2]
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
