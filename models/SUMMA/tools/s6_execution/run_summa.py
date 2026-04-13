#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
============================================
Tool ID:      run_summa
Stage:        s6_execution
Description:  Execute SUMMA with progress monitoring. Captures stdout/stderr,
              monitors for Fortran STOP codes, convergence failures, and
              checks output file creation.

              SUMMA Fortran STOP codes:
                STOP 10 = file I/O error (missing file, wrong path)
                STOP 20 = NetCDF dimension mismatch
                STOP 30 = invalid decision option
                STOP 40 = convergence failure (reduce time step)

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
SUMMA_EXE = ""
FILE_MANAGER = ""
OUTPUT_SUFFIX = ""
GRU_START = None   # optional: run subset of GRUs (for debugging)
GRU_COUNT = None
LOG_FILE = ""      # optional: redirect output to file

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

if len(sys.argv) > 1:
    import argparse
    parser = argparse.ArgumentParser(description="Run SUMMA")
    parser.add_argument("--summa_exe", required=True, help="Path to summa.exe")
    parser.add_argument("--file_manager", required=True, help="Path to fileManager.txt")
    parser.add_argument("--output_suffix", default="", help="Output file suffix")
    parser.add_argument("--gru_start", type=int, default=None)
    parser.add_argument("--gru_count", type=int, default=None)
    parser.add_argument("--log_file", default="", help="Redirect output to log file")
    args = parser.parse_args()
    SUMMA_EXE = args.summa_exe
    FILE_MANAGER = args.file_manager
    OUTPUT_SUFFIX = args.output_suffix
    GRU_START = args.gru_start
    GRU_COUNT = args.gru_count
    LOG_FILE = args.log_file


def validate_inputs():
    errors = []
    if not SUMMA_EXE or not Path(SUMMA_EXE).exists():
        errors.append(f"SUMMA executable not found: {SUMMA_EXE}")
    elif not os.access(SUMMA_EXE, os.X_OK):
        errors.append(f"SUMMA executable is not executable: {SUMMA_EXE}")
    if not FILE_MANAGER or not Path(FILE_MANAGER).exists():
        errors.append(f"fileManager.txt not found: {FILE_MANAGER}")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def validate_outputs(output_dir):
    """Check that SUMMA produced output files."""
    errors = []
    if not output_dir or not Path(output_dir).exists():
        errors.append(f"Output directory not found: {output_dir}")
    else:
        nc_files = list(Path(output_dir).glob("*.nc"))
        if not nc_files:
            errors.append(f"No output NetCDF files found in {output_dir}")
        else:
            for nc in nc_files:
                if nc.stat().st_size == 0:
                    errors.append(f"Output file is empty: {nc}")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(3)
    logger.info("Output validation passed.")


def get_output_path():
    """Extract output path from fileManager.txt."""
    import re
    with open(FILE_MANAGER) as f:
        for line in f:
            line_clean = line.split('!')[0].strip()
            if line_clean.startswith('outputPath'):
                match = re.search(r"'([^']*)'", line)
                if match:
                    return match.group(1)
    return None


def process():
    """Run SUMMA executable."""
    # Build command
    cmd = [SUMMA_EXE, '-m', FILE_MANAGER]
    if OUTPUT_SUFFIX:
        cmd.extend(['-s', OUTPUT_SUFFIX])
    if GRU_START is not None:
        cmd.extend(['-g', str(GRU_START)])
    if GRU_COUNT is not None:
        cmd.extend(['-c', str(GRU_COUNT)])

    logger.info(f"Running SUMMA: {' '.join(cmd)}")
    start_time = time.time()

    if LOG_FILE:
        with open(LOG_FILE, 'w') as lf:
            result = subprocess.run(cmd, stdout=lf, stderr=subprocess.STDOUT,
                                    timeout=7200)  # 2 hour timeout
    else:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                timeout=7200)

    elapsed = time.time() - start_time
    logger.info(f"SUMMA finished in {elapsed:.1f} seconds")

    # Check for errors
    if not LOG_FILE:
        stdout = result.stdout or ""
        stderr = result.stderr or ""

        # Check for STOP codes in output
        stop_patterns = {
            'STOP 10': 'File I/O error -- check that all paths in fileManager.txt exist',
            'STOP 20': 'NetCDF dimension mismatch -- check hru dimensions across files',
            'STOP 30': 'Invalid decision option -- check decisions file',
            'STOP 40': 'Convergence failure -- try reducing initial time step (dt_init)',
        }
        for pattern, explanation in stop_patterns.items():
            if pattern in stdout or pattern in stderr:
                logger.error(f"SUMMA {pattern}: {explanation}")
                logger.error(f"STDOUT: {stdout[-500:]}")
                logger.error(f"STDERR: {stderr[-500:]}")
                sys.exit(2)

        if result.returncode != 0:
            logger.error(f"SUMMA exit code: {result.returncode}")
            logger.error(f"STDOUT: {stdout[-1000:]}")
            logger.error(f"STDERR: {stderr[-1000:]}")
            sys.exit(2)

        # Print last few lines of output for progress
        if stdout:
            for line in stdout.strip().split('\n')[-5:]:
                logger.info(f"  SUMMA: {line}")

    elif result.returncode != 0:
        logger.error(f"SUMMA exit code: {result.returncode}. Check log: {LOG_FILE}")
        sys.exit(2)

    # Get output directory
    output_dir = get_output_path()
    if output_dir:
        nc_files = list(Path(output_dir).glob("*.nc"))
        logger.info(f"Output files: {len(nc_files)} NetCDF files in {output_dir}")

    print(json.dumps({
        "status": "success",
        "exit_code": result.returncode,
        "elapsed_seconds": round(elapsed, 1),
        "output_dir": output_dir,
        "n_output_files": len(nc_files) if output_dir else 0
    }))

    return output_dir


if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs()
    try:
        output_dir = process()
    except subprocess.TimeoutExpired:
        logger.error("SUMMA timed out after 2 hours")
        sys.exit(2)
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        sys.exit(2)
    validate_outputs(output_dir)
    sys.exit(0)
