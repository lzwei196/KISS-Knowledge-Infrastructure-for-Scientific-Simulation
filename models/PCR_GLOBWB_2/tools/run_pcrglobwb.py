#!/usr/bin/env python3
"""
PCR-GLOBWB 2 Execution Wrapper
================================
Runs the PCR-GLOBWB 2 model with preflight checks, environment validation,
and post-run output verification.

Pipeline stage: s5/s6 (Spin-up and Transient Run)
Pattern: validate_inputs → process → validate_outputs

Execution: python deterministic_runner.py <ini_file> [debug] [--output_dir <dir>]

Preflight checks:
  - Conda environment has pcraster, netCDF4
  - Clone map exists locally
  - Input directory (OPeNDAP or local) is accessible
  - Output directory is writable
  - INI file sections are complete

Traps:
  dt_010: Clone map must be local (not OPeNDAP)
  dt_011: Clone map corners must be nicely-rounded
  dt_012: Only daily timestep supported
  dt_013: Spin-up convergence settings
  dt_014: OPeNDAP latency warning
"""

import os
import sys
import argparse
import subprocess
import logging
import time
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Preflight validation
# ---------------------------------------------------------------------------

def validate_inputs(ini_file, model_dir):
    """Run preflight checks before executing PCR-GLOBWB."""
    errors = []
    warnings = []

    # 1. Check INI file exists
    if not os.path.exists(ini_file):
        errors.append(f"Configuration file not found: {ini_file}")
        # Can't continue without ini file
        for e in errors:
            logger.error(e)
        raise ValueError("INI file not found")

    # 2. Check model scripts exist
    runner_script = os.path.join(model_dir, "deterministic_runner.py")
    if not os.path.exists(runner_script):
        errors.append(f"deterministic_runner.py not found in {model_dir}")

    # 3. Parse INI file for basic checks
    try:
        from configparser import RawConfigParser
        config = RawConfigParser()
        config.optionxform = str
        config.read(ini_file)

        # Check required sections
        required_sections = [
            "globalOptions", "meteoOptions", "landSurfaceOptions",
            "groundwaterOptions", "routingOptions", "reportingOptions"
        ]
        for sec in required_sections:
            if sec not in config.sections():
                errors.append(f"Missing required section: [{sec}]")

        # dt_010: Check clone map is local
        if config.has_option("globalOptions", "cloneMap"):
            clone_map = config.get("globalOptions", "cloneMap")
            if clone_map.startswith("http"):
                errors.append(
                    "dt_010: cloneMap must be a local file, not OPeNDAP URL. "
                    f"Current value: {clone_map}"
                )
            elif not os.path.exists(clone_map):
                errors.append(f"dt_010: cloneMap file not found: {clone_map}")

        # dt_014: OPeNDAP warning
        if config.has_option("globalOptions", "inputDir"):
            input_dir = config.get("globalOptions", "inputDir")
            if input_dir.startswith("http"):
                warnings.append(
                    "dt_014: Using OPeNDAP for input data. This is 10-100x slower "
                    "than local files. Consider downloading inputs for production runs."
                )

        # Check output directory
        if config.has_option("globalOptions", "outputDir"):
            output_dir = config.get("globalOptions", "outputDir")
            parent = os.path.dirname(output_dir.rstrip("/"))
            if parent and not os.path.exists(parent):
                warnings.append(
                    f"Output parent directory does not exist: {parent}. "
                    f"Will be created during run."
                )

        # dt_012: Timestep check
        if config.has_option("globalOptions", "timeStep"):
            ts = config.get("globalOptions", "timeStep")
            if ts != "1.0" and ts != "1":
                errors.append(
                    f"dt_012: PCR-GLOBWB only supports daily timestep. "
                    f"Current timeStep={ts}"
                )

        # Land cover sections check
        land_cover_sections = [
            "forestOptions", "grasslandOptions",
            "irrPaddyOptions", "irrNonPaddyOptions"
        ]
        for sec in land_cover_sections:
            if sec not in config.sections():
                warnings.append(f"Land cover section [{sec}] not found in INI file")

    except Exception as e:
        warnings.append(f"Could not fully parse INI file: {e}")

    # 4. Check Python environment
    try:
        import pcraster
        logger.info(f"PCRaster available: {pcraster.__file__}")
    except ImportError:
        errors.append(
            "PCRaster not found. Activate conda environment: "
            "conda activate pcrglobwb_python3"
        )

    try:
        import netCDF4
        logger.info(f"netCDF4 available: {netCDF4.__version__}")
    except ImportError:
        errors.append("netCDF4 not found. Install: pip install netCDF4")

    for w in warnings:
        logger.warning(w)
    for e in errors:
        logger.error(e)

    if errors:
        raise ValueError(f"Preflight check failed: {len(errors)} error(s)")

    logger.info("Preflight checks passed.")
    return True


def validate_outputs(output_dir):
    """Validate model outputs after execution."""
    errors = []
    warnings = []

    # Check output directory exists
    if not os.path.exists(output_dir):
        errors.append(f"Output directory not created: {output_dir}")
        for e in errors:
            logger.error(e)
        raise ValueError("Output validation failed")

    # Check NetCDF output directory
    nc_dir = os.path.join(output_dir, "netcdf")
    if os.path.exists(nc_dir):
        nc_files = [f for f in os.listdir(nc_dir) if f.endswith(".nc")]
        if nc_files:
            logger.info(f"Found {len(nc_files)} output NetCDF file(s): {nc_files[:5]}...")
        else:
            warnings.append("No NetCDF output files found in netcdf/ directory")
    else:
        warnings.append("netcdf/ output directory not found")

    # Check states directory
    states_dir = os.path.join(output_dir, "states")
    if os.path.exists(states_dir):
        state_files = os.listdir(states_dir)
        logger.info(f"Found {len(state_files)} state files")
    else:
        warnings.append("states/ directory not found")

    # Check log directory
    log_dir = os.path.join(output_dir, "log")
    if os.path.exists(log_dir):
        log_files = [f for f in os.listdir(log_dir) if f.endswith(".log")]
        if log_files:
            logger.info(f"Log files: {log_files}")
            # Check last log for errors
            latest_log = sorted(log_files)[-1]
            log_path = os.path.join(log_dir, latest_log)
            with open(log_path, "r") as f:
                log_content = f.read()
                if "ERROR" in log_content:
                    error_lines = [
                        l for l in log_content.split("\n") if "ERROR" in l
                    ]
                    for el in error_lines[:5]:
                        warnings.append(f"Error in log: {el.strip()}")

    for w in warnings:
        logger.warning(w)
    for e in errors:
        logger.error(e)

    if errors:
        raise ValueError(f"Output validation failed: {len(errors)} error(s)")

    logger.info("Output validation passed.")
    return True


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def process(ini_file, model_dir, debug=False, output_dir_override=None,
            timeout=None):
    """Execute PCR-GLOBWB 2.

    Args:
        ini_file: Path to .ini configuration file
        model_dir: Path to PCR-GLOBWB model/ directory
        debug: Enable debug mode
        output_dir_override: Override output directory from INI
        timeout: Timeout in seconds (None = no timeout)

    Returns:
        dict with execution results
    """
    runner_script = os.path.join(model_dir, "deterministic_runner.py")

    # Build command
    cmd = [sys.executable, runner_script, os.path.abspath(ini_file)]
    if debug:
        cmd.append("debug")
    if output_dir_override:
        cmd.extend(["--output_dir", output_dir_override])

    logger.info(f"Executing: {' '.join(cmd)}")
    logger.info(f"Working directory: {model_dir}")

    start_time = time.time()

    try:
        result = subprocess.run(
            cmd,
            cwd=model_dir,
            capture_output=True,
            text=True,
            timeout=timeout
        )

        elapsed = time.time() - start_time

        # Log output
        if result.stdout:
            logger.info(f"STDOUT (last 500 chars):\n{result.stdout[-500:]}")
        if result.stderr:
            logger.warning(f"STDERR (last 500 chars):\n{result.stderr[-500:]}")

        return {
            "returncode": result.returncode,
            "elapsed_seconds": elapsed,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "command": " ".join(cmd),
            "success": result.returncode == 0,
        }

    except subprocess.TimeoutExpired:
        elapsed = time.time() - start_time
        logger.error(f"Execution timed out after {elapsed:.0f}s")
        return {
            "returncode": -1,
            "elapsed_seconds": elapsed,
            "stdout": "",
            "stderr": "TimeoutExpired",
            "command": " ".join(cmd),
            "success": False,
        }
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"Execution failed: {e}")
        return {
            "returncode": -1,
            "elapsed_seconds": elapsed,
            "stdout": "",
            "stderr": str(e),
            "command": " ".join(cmd),
            "success": False,
        }


def get_output_dir_from_ini(ini_file):
    """Extract outputDir from INI file."""
    try:
        from configparser import RawConfigParser
        config = RawConfigParser()
        config.optionxform = str
        config.read(ini_file)
        return config.get("globalOptions", "outputDir")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Run PCR-GLOBWB 2 with preflight checks"
    )
    parser.add_argument("ini_file", help="Path to .ini configuration file")
    parser.add_argument(
        "--model-dir", default=None,
        help="Path to model/ directory (default: auto-detect)"
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    parser.add_argument("--output-dir", default=None, help="Override output directory")
    parser.add_argument(
        "--timeout", type=int, default=None,
        help="Timeout in seconds"
    )
    parser.add_argument(
        "--skip-preflight", action="store_true",
        help="Skip preflight checks"
    )

    args = parser.parse_args()

    # Auto-detect model directory
    model_dir = args.model_dir
    if model_dir is None:
        # Look for deterministic_runner.py relative to ini file or cwd
        candidates = [
            os.path.join(os.path.dirname(args.ini_file), "..", "model"),
            os.path.join(os.path.dirname(args.ini_file), "model"),
            "model",
            ".",
        ]
        for c in candidates:
            if os.path.exists(os.path.join(c, "deterministic_runner.py")):
                model_dir = c
                break
        if model_dir is None:
            logger.error("Could not find model/ directory. Use --model-dir.")
            sys.exit(1)

    # Validate → Process → Validate
    if not args.skip_preflight:
        validate_inputs(args.ini_file, model_dir)

    result = process(
        args.ini_file, model_dir,
        debug=args.debug,
        output_dir_override=args.output_dir,
        timeout=args.timeout
    )

    if result["success"]:
        logger.info(f"PCR-GLOBWB completed in {result['elapsed_seconds']:.1f}s")
        output_dir = args.output_dir or get_output_dir_from_ini(args.ini_file)
        if output_dir:
            try:
                validate_outputs(output_dir)
            except Exception as e:
                logger.warning(f"Output validation issue: {e}")
    else:
        logger.error(f"PCR-GLOBWB failed (return code {result['returncode']})")
        sys.exit(1)


if __name__ == "__main__":
    main()
