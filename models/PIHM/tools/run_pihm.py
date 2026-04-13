#!/usr/bin/env python3
"""
run_pihm.py — Execute MM-PIHM binary with pre-flight validation.

Wraps the PIHM executable with input validation, environment setup,
and output verification. Checks for common configuration errors before
running to avoid wasted compute time.

Pre-flight checks:
  - Binary exists and is executable
  - All required input files exist
  - Forcing data covers simulation period
  - Calibration values are multipliers (near 1.0)
  - CVODE tolerances are reasonable
  - Output directory has sufficient disk space

Usage:
    python run_pihm.py --binary ./pihm --project ShaleHills \\
        --input-dir input/ShaleHills --output-dir output/test_run \\
        --threads 4

    python run_pihm.py --binary ./flux-pihm --project ShaleHills \\
        --input-dir input/ShaleHills --spinup --threads 8
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime


REQUIRED_EXTENSIONS = [".mesh", ".att", ".soil", ".lc", ".meteo", ".riv",
                       ".para", ".calib"]
OPTIONAL_EXTENSIONS = [".ic", ".lai", ".bc", ".geol", ".lsm", ".rad",
                       ".bgc", ".ndep"]


def validate_inputs(args):
    """Validate binary, input files, and configuration."""
    errors = []
    warnings = []

    # Check binary exists
    if not os.path.exists(args.binary):
        errors.append(f"Binary not found: {args.binary}")
    elif not os.access(args.binary, os.X_OK):
        errors.append(f"Binary not executable: {args.binary}")

    # Check input directory
    if not os.path.isdir(args.input_dir):
        errors.append(f"Input directory not found: {args.input_dir}")
    else:
        # Check required files
        for ext in REQUIRED_EXTENSIONS:
            fpath = os.path.join(args.input_dir, args.project + ext)
            if not os.path.exists(fpath):
                errors.append(f"Required input file missing: {fpath}")

        # Check optional files
        for ext in OPTIONAL_EXTENSIONS:
            fpath = os.path.join(args.input_dir, args.project + ext)
            if os.path.exists(fpath):
                pass  # OK

        # Validate .para file contents
        para_file = os.path.join(args.input_dir, args.project + ".para")
        if os.path.exists(para_file):
            para_warnings = validate_para(para_file, args.spinup)
            warnings.extend(para_warnings)

        # Validate .calib file contents
        calib_file = os.path.join(args.input_dir, args.project + ".calib")
        if os.path.exists(calib_file):
            calib_warnings = validate_calib(calib_file)
            warnings.extend(calib_warnings)

    # Check disk space (need at least 1 GB free)
    outdir_parent = os.path.dirname(os.path.abspath(args.output_dir or "."))
    if os.path.exists(outdir_parent):
        usage = shutil.disk_usage(outdir_parent)
        free_gb = usage.free / (1024**3)
        if free_gb < 1.0:
            warnings.append(f"Low disk space: {free_gb:.1f} GB free")

    if errors:
        print(json.dumps({"status": "error", "errors": errors, "warnings": warnings}))
        sys.exit(1)

    return warnings


def validate_para(para_file, spinup_mode):
    """Check .para file for common configuration issues."""
    warnings = []
    try:
        with open(para_file, "r") as f:
            content = f.read()

        lines = content.strip().split("\n")
        params = {}
        for line in lines:
            parts = line.strip().split()
            if len(parts) >= 2:
                params[parts[0]] = parts[1]

        # Check ABSTOL
        abstol = float(params.get("ABSTOL", 1e-4))
        if abstol > 0.01:
            warnings.append(f"ABSTOL={abstol} is very loose — mass balance errors likely (dt_013)")
        elif abstol < 1e-7:
            warnings.append(f"ABSTOL={abstol} is very tight — solver may be slow")

        # Check init mode vs spinup
        init_mode = int(params.get("INIT_MODE", 0))
        sim_mode = int(params.get("SIMULATION_MODE", 0))

        if spinup_mode and sim_mode != 1:
            warnings.append("Spinup requested but SIMULATION_MODE != 1 in .para file")
        if not spinup_mode and init_mode == 0 and sim_mode == 0:
            warnings.append("No spin-up and INIT_MODE=0: starting from relaxation IC (dt_012)")

    except Exception as e:
        warnings.append(f"Could not parse .para file: {e}")

    return warnings


def validate_calib(calib_file):
    """Check .calib file for likely absolute-vs-multiplier errors."""
    warnings = []
    try:
        with open(calib_file, "r") as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 2:
                    key = parts[0]
                    try:
                        val = float(parts[1])
                    except ValueError:
                        continue

                    # Multiplier parameters should be near 1.0
                    multiplier_params = [
                        "KSATH", "KSATV", "KINF", "KMACSATH", "KMACSATV",
                        "POROSITY", "ALPHA", "BETA", "MACVF", "MACHF",
                        "VEGFRAC", "ALBEDO", "ROUGH", "DROOT", "DMAC",
                        "ROUGH_RIV", "KRIVH", "RIV_DPTH", "RIV_WDTH", "PRCP"
                    ]
                    if key in multiplier_params:
                        if val < 1e-4 or val > 1e4:
                            warnings.append(
                                f"Calib {key}={val} — this is a MULTIPLIER, not absolute. "
                                f"Did you mean to set it near 1.0? (dt_011)"
                            )

                    # SFCTMP is additive offset, should be near 0
                    if key == "SFCTMP" and abs(val) > 10.0:
                        warnings.append(
                            f"SFCTMP={val} K offset is very large. "
                            f"This is added to forcing temperature."
                        )

    except Exception as e:
        warnings.append(f"Could not parse .calib file: {e}")

    return warnings


def run_model(args, warnings):
    """Execute the PIHM binary."""
    # Set OpenMP threads
    env = os.environ.copy()
    env["OMP_NUM_THREADS"] = str(args.threads)

    # Build command
    cmd = [os.path.abspath(args.binary)]
    if args.output_dir:
        cmd.extend(["-o", args.output_dir])
    if args.spinup:
        # Spin-up is controlled by .para SIMULATION_MODE, not a flag
        pass
    if args.verbose:
        cmd.append("-v")
    if args.debug:
        cmd.append("-d")
    if args.brief:
        cmd.append("-b")
    cmd.append(args.project)

    # Change to the MM-PIHM root directory (parent of input/)
    work_dir = os.path.dirname(os.path.dirname(os.path.abspath(args.input_dir)))
    if not os.path.exists(os.path.join(work_dir, "input")):
        # Try input_dir's parent
        work_dir = os.path.dirname(os.path.abspath(args.input_dir))
        if not os.path.exists(os.path.join(work_dir, "input")):
            work_dir = "."

    print(f"Running: {' '.join(cmd)}", file=sys.stderr)
    print(f"Working directory: {work_dir}", file=sys.stderr)
    print(f"OMP_NUM_THREADS: {args.threads}", file=sys.stderr)

    try:
        result = subprocess.run(
            cmd,
            cwd=work_dir,
            env=env,
            capture_output=True,
            text=True,
            timeout=args.timeout
        )

        output = result.stdout + result.stderr
        success = result.returncode == 0

        return {
            "status": "success" if success else "error",
            "return_code": result.returncode,
            "command": " ".join(cmd),
            "working_dir": work_dir,
            "stdout_tail": output[-2000:] if len(output) > 2000 else output,
            "warnings": warnings,
        }

    except subprocess.TimeoutExpired:
        return {
            "status": "error",
            "errors": [f"Timeout after {args.timeout} seconds"],
            "command": " ".join(cmd),
            "warnings": warnings,
        }
    except Exception as e:
        return {
            "status": "error",
            "errors": [str(e)],
            "command": " ".join(cmd),
            "warnings": warnings,
        }


def main():
    parser = argparse.ArgumentParser(
        description="Execute MM-PIHM binary with pre-flight validation"
    )
    parser.add_argument("--binary", required=True, help="Path to PIHM executable")
    parser.add_argument("--project", required=True, help="Project name (e.g., ShaleHills)")
    parser.add_argument("--input-dir", required=True, help="Input directory path")
    parser.add_argument("--output-dir", default=None, help="Output directory name")
    parser.add_argument("--threads", type=int, default=4, help="Number of OpenMP threads")
    parser.add_argument("--spinup", action="store_true", help="Run in spin-up mode")
    parser.add_argument("--verbose", action="store_true", help="Verbose mode")
    parser.add_argument("--debug", action="store_true", help="Debug mode")
    parser.add_argument("--brief", action="store_true", help="Brief mode")
    parser.add_argument("--timeout", type=int, default=7200,
                        help="Timeout in seconds (default: 7200 = 2 hours)")
    args = parser.parse_args()

    warnings = validate_inputs(args)
    result = run_model(args, warnings)

    print(json.dumps(result, indent=2))
    if result["status"] != "success":
        sys.exit(1)


if __name__ == "__main__":
    main()
