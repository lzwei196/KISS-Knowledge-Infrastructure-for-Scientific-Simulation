#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
==========================================
Tool ID:      run_sfincs
Stage:        s7_execution
Description:  Execute SFINCS binary with preflight checks, log monitoring, and output validation.

CRITICAL:
  - SFINCS reads sfincs.inp from the CURRENT WORKING DIRECTORY. Must cd to run_dir.
  - All file paths in sfincs.inp must be relative to run_dir (or absolute).
  - Binary must be executable: chmod +x sfincs
  - Set OMP_NUM_THREADS for parallel execution.

Inputs:
  --run_dir:          Directory containing sfincs.inp and all input files
  --sfincs_binary:    Path to SFINCS executable (default: model/sfincs/bin/sfincs)
  --omp_threads:      Number of OpenMP threads (default: 4)
  --timeout:          Timeout in seconds (default: 7200 = 2 hours)

Outputs:
  - sfincs_map.nc:    Gridded flood output
  - sfincs_his.nc:    Time series at observation points
  - sfincs.log:       Runtime log
  - run_summary.json: Execution summary

Exit codes:
  0 — success, 1 — input error, 2 — processing error, 3 — output error
"""

import sys
import os
import json
import logging
import argparse
import subprocess
import time
import shutil
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_SFINCS = "/mnt/disk1/Hydrocraft_server/model/sfincs/bin/sfincs"


def validate_inputs(args):
    errors = []

    run_dir = Path(args.run_dir)
    if not run_dir.exists():
        errors.append(f"Run directory not found: {run_dir}")
    elif not (run_dir / "sfincs.inp").exists():
        errors.append(f"sfincs.inp not found in {run_dir}")

    # Check binary
    sfincs_bin = Path(args.sfincs_binary)
    if not sfincs_bin.exists():
        errors.append(f"SFINCS binary not found: {sfincs_bin}. "
                      "Download from Deltares or compile from source.")

    # Check required input files referenced in sfincs.inp
    if (run_dir / "sfincs.inp").exists():
        inp = (run_dir / "sfincs.inp").read_text()
        for key in ["depfile", "mskfile", "indexfile"]:
            for line in inp.splitlines():
                if line.strip().startswith(key):
                    fname = line.split("=")[1].strip()
                    if not (run_dir / fname).exists():
                        errors.append(f"Referenced file not found: {run_dir / fname} (from {key})")

    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)

    logger.info("Input validation passed.")


def preflight_check(run_dir):
    """Run additional checks before execution."""
    warnings = []

    inp_path = run_dir / "sfincs.inp"
    inp = inp_path.read_text()

    # Check for outputformat = net
    if "outputformat" not in inp:
        warnings.append("outputformat not set in sfincs.inp — default may produce binary "
                        "instead of NetCDF. Add 'outputformat = net'")

    # Check mask file has active cells
    msk_path = run_dir / "sfincs.msk"
    if msk_path.exists():
        import numpy as np
        # Read grid dimensions from inp
        mmax = nmax = 0
        for line in inp.splitlines():
            line = line.strip()
            if line.startswith("mmax"):
                mmax = int(line.split("=")[1].strip())
            elif line.startswith("nmax"):
                nmax = int(line.split("=")[1].strip())

        if mmax > 0 and nmax > 0:
            msk = np.fromfile(str(msk_path), dtype=np.uint8)
            if len(msk) >= mmax * nmax:
                msk = msk[:mmax * nmax].reshape(nmax, mmax)
                active = int(np.sum(msk > 0))
                if active == 0:
                    warnings.append("CRITICAL: Mask file has NO active cells — output will be all zeros! (dt_020)")

    # Check CFL condition
    dt = dx = None
    for line in inp.splitlines():
        line = line.strip()
        if line.startswith("dt ") or line.startswith("dt="):
            dt = float(line.split("=")[1].strip())
        elif line.startswith("dx ") or line.startswith("dx="):
            dx = float(line.split("=")[1].strip())

    if dt and dx:
        import math
        dt_max = dx / math.sqrt(9.81 * 10.0)
        if dt > dt_max:
            warnings.append(f"dt={dt}s may violate CFL (dt_max={dt_max:.1f}s for 10m depth). "
                            f"Model may crash with NaN. Reduce dt. (dt_009)")

    for w in warnings:
        logger.warning(f"PREFLIGHT: {w}")

    return warnings


def process(args):
    run_dir = Path(args.run_dir).resolve()
    sfincs_bin = Path(args.sfincs_binary).resolve()

    # Preflight checks
    warnings = preflight_check(run_dir)

    # Set environment
    env = os.environ.copy()
    env["OMP_NUM_THREADS"] = str(args.omp_threads)
    logger.info(f"OMP_NUM_THREADS = {args.omp_threads}")

    # Run SFINCS
    logger.info(f"Starting SFINCS in {run_dir}...")
    start_time = time.time()

    try:
        result = subprocess.run(
            [str(sfincs_bin)],
            cwd=str(run_dir),
            env=env,
            capture_output=True,
            text=True,
            timeout=args.timeout,
        )
    except subprocess.TimeoutExpired:
        elapsed = time.time() - start_time
        logger.error(f"SFINCS timed out after {elapsed:.0f}s (limit: {args.timeout}s)")
        sys.exit(2)

    elapsed = time.time() - start_time
    logger.info(f"SFINCS finished in {elapsed:.1f}s with exit code {result.returncode}")

    # Save stdout/stderr
    if result.stdout:
        (run_dir / "sfincs_stdout.log").write_text(result.stdout)
    if result.stderr:
        (run_dir / "sfincs_stderr.log").write_text(result.stderr)

    # Check for errors
    # KNOWN ISSUE: gfortran 13 + NetCDF causes SIGABRT (-6) at cleanup
    # even when the simulation completes successfully. Check log for
    # "Simulation finished" to determine true success.
    simulation_finished = False
    log_file = run_dir / "sfincs.log"
    if log_file.exists():
        log_text = log_file.read_text()
        simulation_finished = "Simulation finished" in log_text

    if result.returncode != 0 and not simulation_finished:
        logger.error(f"SFINCS failed with exit code {result.returncode}")
        if result.stderr:
            logger.error(f"stderr: {result.stderr[:2000]}")
        if result.stdout:
            logger.error(f"stdout (last 500 chars): {result.stdout[-500:]}")
        sys.exit(2)
    elif result.returncode != 0 and simulation_finished:
        logger.warning(f"SFINCS exit code {result.returncode} but simulation finished successfully "
                       "(known gfortran cleanup crash — output is valid)")

    # Check for output files
    map_nc = run_dir / "sfincs_map.nc"
    his_nc = run_dir / "sfincs_his.nc"

    outputs_found = {}
    for nc_file in [map_nc, his_nc]:
        if nc_file.exists():
            outputs_found[nc_file.name] = nc_file.stat().st_size
            logger.info(f"Output: {nc_file.name} ({nc_file.stat().st_size} bytes)")

    if not map_nc.exists():
        logger.warning("sfincs_map.nc not found — check outputformat in sfincs.inp (dt_019)")

    # --- Summary ---
    effective_success = (result.returncode == 0) or simulation_finished
    summary = {
        "status": "success" if effective_success else "failed",
        "exit_code": result.returncode,
        "elapsed_seconds": round(elapsed, 1),
        "omp_threads": args.omp_threads,
        "run_dir": str(run_dir),
        "binary": str(sfincs_bin),
        "outputs": outputs_found,
        "preflight_warnings": warnings,
    }

    summary_path = run_dir / "run_summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    print(json.dumps(summary, indent=2))
    return str(summary_path)


def validate_outputs(output_path):
    if not Path(output_path).exists():
        logger.error(f"Run summary not created: {output_path}")
        sys.exit(3)
    with open(output_path) as f:
        data = json.load(f)
    if data.get("status") != "success":
        logger.error("SFINCS did not complete successfully")
        sys.exit(3)
    logger.info("Output validation passed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run SFINCS flood model")
    parser.add_argument("--run_dir", required=True, help="Directory with sfincs.inp")
    parser.add_argument("--sfincs_binary", default=DEFAULT_SFINCS, help="Path to SFINCS binary")
    parser.add_argument("--omp_threads", type=int, default=4, help="OpenMP threads")
    parser.add_argument("--timeout", type=int, default=7200, help="Timeout in seconds")
    args = parser.parse_args()

    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs(args)

    try:
        output_path = process(args)
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(2)

    validate_outputs(output_path)
    sys.exit(0)
