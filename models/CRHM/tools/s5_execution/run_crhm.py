#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
============================================
Tool ID:      run_crhm
Stage:        s5_execution
Description:  Execute CRHM CLI with progress reporting and error capture.

CRHM CLI invocation:
  crhm [options] PROJECT_FILE

Options:
  -h, --help             Show help
  -t TIME_FORMAT         Date format: MS, ISO, YYYYMMDD
  -f OUTPUT_FORMAT       Output format: STD (tab-delimited), OBS
  -o PATH                Output file path (default: CRHM_output_1.txt)
  -d DELIMITER           Column delimiter
  --obs_file_directory   Directory for observation files
  -p UPDATE_FREQUENCY    Print progress every N simulation days

CRITICAL:
  - CRHM reads .obs file paths from the .prj file. If the path is
    relative, it is relative to the WORKING DIRECTORY, not the .prj location.
    Use --obs_file_directory to override, or use absolute paths in .prj.
  - Exit code 0 = success, non-zero = error. But some errors produce
    exit code 0 with error messages on stderr. Always check stderr.
  - CRHM output STD format has 2 header rows: variable names, then units.
    Skip both when parsing data.

Inputs:
  --crhm_exe:      Path to CRHM executable
  --prj_path:      Path to .prj project file
  --output_path:   Output file path
  --obs_dir:       Observation file directory (optional)
  --progress:      Progress update interval in days (default: 100)
  --time_format:   Output time format: ISO, MS, YYYYMMDD (default: YYYYMMDD)

Exit codes:
  0 -- success
  1 -- input error
  2 -- CRHM execution failed
  3 -- output validation failed
"""

import sys
import os
import json
import logging
import argparse
import subprocess
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def parse_args():
    parser = argparse.ArgumentParser(description="Run CRHM simulation")
    parser.add_argument("--crhm_exe", type=str, required=True, help="Path to CRHM executable")
    parser.add_argument("--prj_path", type=str, required=True, help="Path to .prj file")
    parser.add_argument("--output_path", type=str, required=True, help="Output file path")
    parser.add_argument("--obs_dir", type=str, default="", help="Observation file directory")
    parser.add_argument("--progress", type=int, default=100, help="Progress interval (days)")
    parser.add_argument("--time_format", type=str, default="YYYYMMDD",
                        choices=["ISO", "MS", "YYYYMMDD"], help="Output time format")
    return parser.parse_args()


def validate_inputs(crhm_exe, prj_path, output_path):
    errors = []
    if not Path(crhm_exe).exists():
        errors.append(f"CRHM executable not found: {crhm_exe}")
    elif not os.access(crhm_exe, os.X_OK):
        errors.append(f"CRHM executable not executable: {crhm_exe}. Run: chmod +x {crhm_exe}")
    if not Path(prj_path).exists():
        errors.append(f"Project file not found: {prj_path}")
    if not output_path:
        errors.append("Output path not set")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def process(crhm_exe, prj_path, output_path, obs_dir, progress, time_format):
    """Run CRHM and capture output."""
    # Build command
    cmd = [
        str(crhm_exe),
        "-f", "STD",
        "-t", time_format,
        "-o", str(output_path),
        "-p", str(progress),
    ]

    if obs_dir:
        cmd.extend(["--obs_file_directory", str(obs_dir)])

    cmd.append(str(prj_path))

    logger.info(f"Running: {' '.join(cmd)}")

    # Ensure output directory exists
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    # Execute
    start_time = time.time()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=3600,  # 1 hour max
        )
    except subprocess.TimeoutExpired:
        logger.error("CRHM timed out after 1 hour")
        sys.exit(2)
    except FileNotFoundError:
        logger.error(f"CRHM executable not found at runtime: {crhm_exe}")
        sys.exit(2)

    elapsed = time.time() - start_time

    # Log output
    if result.stdout:
        logger.info(f"STDOUT:\n{result.stdout[:2000]}")
    if result.stderr:
        # Check for actual errors vs progress messages
        stderr_lines = result.stderr.strip().split("\n")
        error_lines = [l for l in stderr_lines if "error" in l.lower() or "fatal" in l.lower()]
        if error_lines:
            logger.error(f"STDERR errors:\n" + "\n".join(error_lines))
        else:
            logger.info(f"STDERR (progress/info):\n{result.stderr[:1000]}")

    if result.returncode != 0:
        logger.error(f"CRHM exited with code {result.returncode}")
        logger.error(f"Full stderr: {result.stderr}")
        sys.exit(2)

    logger.info(f"CRHM completed in {elapsed:.1f} seconds")

    return str(output_path)


def validate_outputs(output_path):
    errors = []
    p = Path(output_path)
    if not p.exists():
        errors.append(f"Output file not created: {output_path}")
    elif p.stat().st_size == 0:
        errors.append("Output file is empty -- CRHM may have run but produced no output")
    else:
        # Check first few lines for STD format header
        with open(p) as f:
            first_lines = [f.readline() for _ in range(5)]
        if len(first_lines) < 3:
            errors.append("Output file has fewer than 3 lines")
        # STD format: line 1 = variable names, line 2 = units
        logger.info(f"Output header: {first_lines[0].strip()[:100]}...")

    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(3)
    logger.info("Output validation passed.")


if __name__ == "__main__":
    args = parse_args()
    logger.info(f"Running tool: {os.path.basename(__file__)}")

    validate_inputs(args.crhm_exe, args.prj_path, args.output_path)

    try:
        output_path = process(
            args.crhm_exe, args.prj_path, args.output_path,
            args.obs_dir, args.progress, args.time_format
        )
    except SystemExit:
        raise
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(2)

    validate_outputs(output_path)

    print(json.dumps({
        "status": "success",
        "output": output_path,
        "size_bytes": Path(output_path).stat().st_size,
    }))
    sys.exit(0)
