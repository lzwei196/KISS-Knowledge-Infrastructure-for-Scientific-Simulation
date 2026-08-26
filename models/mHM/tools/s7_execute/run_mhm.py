#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
Tool ID:      run_mhm
Stage:        s7_execute
Description:  Execute mHM with progress monitoring and error handling.

CRITICAL:
  - mHM must be run FROM the directory containing mhm.nml (all paths relative)
  - The binary reads mhm.nml, mhm_parameter.nml, mhm_outputs.nml, mrm_outputs.nml
  - Output goes to output_b1/ (as specified in mhm.nml)
  - Exit code 0 = success, non-zero = error
  - Check for "mHM: Finished!" in stdout to confirm completion

Inputs:
  - RUN_DIR: directory containing mhm.nml and all input data
  - MHM_BINARY: path to mHM executable
  - TIMEOUT: max runtime in seconds (default 3600)

Outputs:
  - output_b1/mHM_Fluxes_States.nc: hydrological outputs
  - output_b1/mRM_Fluxes_States.nc: routing outputs
  - output_b1/discharge.nc: simulated discharge at gauges
  - output_b1/daily_discharge.out: ASCII discharge

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import json
import logging
import subprocess
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
RUN_DIR = ""
MHM_BINARY = os.path.join(os.environ.get("HYDROCRAFT_ROOT", "KISSPATH_ROOT"), "model/mhm/mhm")
TIMEOUT = 3600  # seconds

if len(sys.argv) > 1:
    import argparse
    parser = argparse.ArgumentParser(description="Run mHM")
    parser.add_argument("--run_dir", required=True)
    parser.add_argument("--mhm_binary", default=MHM_BINARY)
    parser.add_argument("--timeout", type=int, default=3600)
    args = parser.parse_args()
    RUN_DIR = args.run_dir
    MHM_BINARY = args.mhm_binary
    TIMEOUT = args.timeout

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def validate_inputs():
    errors = []
    if not RUN_DIR or not Path(RUN_DIR).exists():
        errors.append(f"Run directory not found: {RUN_DIR}")
    else:
        run_dir = Path(RUN_DIR)
        if not (run_dir / "mhm.nml").exists():
            errors.append(f"mhm.nml not found in {RUN_DIR}")
        if not (run_dir / "mhm_parameter.nml").exists():
            errors.append(f"mhm_parameter.nml not found in {RUN_DIR}")
        if not (run_dir / "input" / "morph" / "dem.asc").exists():
            errors.append(f"input/morph/dem.asc not found in {RUN_DIR}")
    if not Path(MHM_BINARY).exists():
        errors.append(f"mHM binary not found: {MHM_BINARY}")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def process():
    run_dir = Path(RUN_DIR)
    output_dir = run_dir / "output_b1"
    output_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "restart").mkdir(parents=True, exist_ok=True)

    logger.info(f"Running mHM in {run_dir}...")
    logger.info(f"Binary: {MHM_BINARY}")
    logger.info(f"Timeout: {TIMEOUT}s")

    start_time = time.time()

    try:
        result = subprocess.run(
            [MHM_BINARY],
            cwd=str(run_dir),
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        logger.error(f"mHM timed out after {TIMEOUT}s")
        sys.exit(2)

    elapsed = time.time() - start_time
    logger.info(f"mHM completed in {elapsed:.1f}s with exit code {result.returncode}")

    # Log stdout (last 30 lines)
    stdout_lines = result.stdout.strip().split('\n')
    for line in stdout_lines[-30:]:
        logger.info(f"  {line}")

    if result.stderr:
        logger.warning(f"STDERR: {result.stderr[:500]}")

    # Check for success
    success = result.returncode == 0 and "mHM: Finished!" in result.stdout

    if not success:
        logger.error("mHM did not complete successfully")
        # Look for error messages
        for line in stdout_lines:
            if "ERROR" in line.upper() or "STOP" in line:
                logger.error(f"  >> {line}")
        sys.exit(2)

    # Extract performance metrics from output
    metrics = {}
    for line in stdout_lines:
        if "KGE" in line:
            try:
                parts = line.split(":")
                metrics["KGE"] = float(parts[-1].strip())
            except (ValueError, IndexError):
                pass
        if "NSE" in line:
            try:
                parts = line.split(":")
                metrics["NSE"] = float(parts[-1].strip())
            except (ValueError, IndexError):
                pass

    # Check output files
    output_files = list(output_dir.glob("*.nc")) + list(output_dir.glob("*.out"))

    output = {
        "status": "success",
        "run_dir": str(run_dir),
        "elapsed_seconds": round(elapsed, 1),
        "exit_code": result.returncode,
        "metrics": metrics,
        "output_files": [str(f.relative_to(run_dir)) for f in output_files],
    }
    print(json.dumps(output, indent=2))
    return str(output_dir)


def validate_outputs(output_path):
    out_dir = Path(output_path)
    # Check for at least discharge output
    if not (out_dir / "discharge.nc").exists() and not (out_dir / "daily_discharge.out").exists():
        logger.error("No discharge output found")
        sys.exit(3)
    logger.info("Output validation passed.")


if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs()
    try:
        output_path = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        import traceback; traceback.print_exc()
        sys.exit(2)
    validate_outputs(output_path)
    sys.exit(0)
