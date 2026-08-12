#!/usr/bin/env python3
"""
run_snowpack.py — Execute SNOWPACK binary and capture output.

Purpose:
    Wrapper for running the SNOWPACK point simulation binary. Handles:
    - Locating/verifying the binary
    - Creating output directories
    - Running the simulation with proper arguments
    - Capturing stdout/stderr and exit codes
    - Timeout handling for runaway simulations

SNOWPACK CLI usage:
    snowpack -c <config.ini> -e <end_date>

    The config file specifies all input paths, parameters, and output settings.
    SNOWPACK reads the .sno profile (start date embedded) and .smet forcing,
    then simulates until end_date.

CRITICAL NOTES:
    - The binary must be compiled with MeteoIO support (always the case if
      built from source with cmake).
    - Output directory specified in .ini must exist before running.
    - SNOWPACK writes .met (time series) and .pro (profiles) to output dir.
    - Spinup runs should use a separate config that recycles the end profile
      as the new start profile.

Usage:
    # Standard run
    python run_snowpack.py \\
        --binary ./build/bin/snowpack \\
        --config io.ini \\
        --end_date "1996-06-30T23:00"

    # Spinup mode
    python run_snowpack.py \\
        --binary ./build/bin/snowpack \\
        --config spinup.ini \\
        --end_date "1995-10-30T00:00" \\
        --mode spinup

    # Test with bundled example
    python run_snowpack.py \\
        --binary ./build/bin/snowpack \\
        --config tests/cfgfiles/io.ini \\
        --end_date "1996-06-15T00:00"
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def validate_inputs(args):
    """Validate binary and config existence."""
    errors = []

    if not os.path.isfile(args.binary):
        errors.append(f"Binary not found: {args.binary}")
    elif not os.access(args.binary, os.X_OK):
        errors.append(f"Binary not executable: {args.binary}")

    if not os.path.isfile(args.config):
        errors.append(f"Config file not found: {args.config}")

    if not args.end_date:
        errors.append("end_date is required (ISO 8601 format)")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)
    return errors


def ensure_output_dir(config_path):
    """Read config to find output METEOPATH and ensure it exists."""
    output_path = None
    try:
        with open(config_path, "r") as f:
            in_output = False
            for line in f:
                line = line.strip()
                if line == "[Output]":
                    in_output = True
                    continue
                if line.startswith("[") and line != "[Output]":
                    in_output = False
                    continue
                if in_output and "METEOPATH" in line and "=" in line:
                    output_path = line.split("=", 1)[1].strip()
                    break
    except Exception:
        pass

    if output_path:
        os.makedirs(output_path, exist_ok=True)
        return output_path
    return None


def process(args):
    """Run the SNOWPACK binary."""
    # Ensure output directory exists
    output_dir = ensure_output_dir(args.config)

    # Build command. The subprocess runs with cwd set to the config's directory
    # (below), so the config path passed to the binary must be absolute -- a
    # relative path like "config/io.ini" would otherwise be re-resolved against
    # the new cwd and MeteoIO would fail with "Path expansion ... failed".
    cmd = [args.binary, "-c", os.path.abspath(args.config), "-e", args.end_date]

    print(f"Running: {' '.join(cmd)}", file=sys.stderr)
    print(f"Mode: {args.mode}", file=sys.stderr)

    start_time = time.time()

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=args.timeout,
            cwd=os.path.dirname(os.path.abspath(args.config)) or ".",
        )
        elapsed = time.time() - start_time

        result = {
            "status": "success" if proc.returncode == 0 else "error",
            "return_code": proc.returncode,
            "elapsed_seconds": round(elapsed, 2),
            "command": " ".join(cmd),
            "mode": args.mode,
            "stdout_head": proc.stdout[:2000] if proc.stdout else "",
            "stderr_head": proc.stderr[:2000] if proc.stderr else "",
            "output_dir": output_dir,
        }

        if proc.returncode != 0:
            result["error_message"] = (
                f"SNOWPACK exited with code {proc.returncode}. "
                f"Check stderr for details."
            )

    except subprocess.TimeoutExpired:
        elapsed = time.time() - start_time
        result = {
            "status": "error",
            "error_message": f"Simulation timed out after {args.timeout}s",
            "elapsed_seconds": round(elapsed, 2),
            "command": " ".join(cmd),
            "mode": args.mode,
        }
    except FileNotFoundError:
        result = {
            "status": "error",
            "error_message": f"Binary not found at: {args.binary}",
            "command": " ".join(cmd),
        }

    return result


def validate_outputs(result):
    """Check simulation result for common issues."""
    warnings = []

    stderr = result.get("stderr_head", "")
    if "segmentation fault" in stderr.lower() or "segfault" in stderr.lower():
        warnings.append("SEGFAULT detected — check .sno file for zero-thickness layers")

    if "nan" in stderr.lower():
        warnings.append("NaN detected in output — possible numerical instability")

    if "meteoio" in stderr.lower() and "error" in stderr.lower():
        warnings.append("MeteoIO error — check input file paths and SMET format")

    elapsed = result.get("elapsed_seconds", 0)
    if elapsed < 0.1 and result.get("status") == "success":
        warnings.append("Very fast execution — may have done nothing (check end_date)")

    if warnings:
        result["warnings"] = warnings
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Run SNOWPACK simulation"
    )
    parser.add_argument("--binary", required=True,
                        help="Path to snowpack binary")
    parser.add_argument("--config", required=True,
                        help="Path to .ini config file")
    parser.add_argument("--end_date", required=True,
                        help="Simulation end date (ISO 8601)")
    parser.add_argument("--mode", default="production",
                        choices=["production", "spinup", "test"],
                        help="Run mode (for logging)")
    parser.add_argument("--timeout", type=int, default=3600,
                        help="Timeout in seconds (default: 3600)")

    args = parser.parse_args()

    validate_inputs(args)
    result = process(args)
    result = validate_outputs(result)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
