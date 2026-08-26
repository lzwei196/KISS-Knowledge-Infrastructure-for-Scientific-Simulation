#!/usr/bin/env python3
"""
run_glm.py — Execute GLM binary with error handling and output validation.

Performs preflight checks (namelist exists, paths valid, output dir exists),
runs GLM, captures stdout/stderr, and validates output files.

GLM is single-threaded. Typical runtimes:
  - Small lake, 10 years: 1-5 minutes
  - Large lake, 10 years: 5-15 minutes
  - With AED2 water quality: 2-5x longer

Usage:
    python run_glm.py --run_dir /path/to/sim --glm_binary /path/to/glm
    python run_glm.py --run_dir . --timeout 600
"""

import argparse
import json
import os
import subprocess
import sys
import time


GLM_BINARY_DEFAULT = "KISSPATH_BINARIES/glm/bin/glm"


def validate_inputs(args):
    """Preflight checks before running GLM."""
    errors = []
    warnings = []

    # Check GLM binary exists and is executable
    if not os.path.exists(args.glm_binary):
        errors.append(f"GLM binary not found: {args.glm_binary}")
    elif not os.access(args.glm_binary, os.X_OK):
        errors.append(f"GLM binary not executable: {args.glm_binary}")

    # Check run directory
    if not os.path.isdir(args.run_dir):
        errors.append(f"Run directory not found: {args.run_dir}")

    # Check namelist exists
    nml_path = os.path.join(args.run_dir, args.nml_file)
    if not os.path.exists(nml_path):
        errors.append(f"Namelist not found: {nml_path}")
    else:
        # Quick parse to check critical paths in namelist
        with open(nml_path) as f:
            nml_content = f.read()

        # Check met file reference
        import re
        met_match = re.search(r"meteo_fl\s*=\s*'([^']+)'", nml_content)
        if met_match:
            met_path = met_match.group(1)
            met_full = os.path.join(args.run_dir, met_path)
            if not os.path.exists(met_full):
                errors.append(
                    f"Met file referenced in namelist not found: {met_full}")

        # Check output directory
        out_match = re.search(r"out_dir\s*=\s*'([^']+)'", nml_content)
        if out_match:
            out_dir = os.path.join(args.run_dir, out_match.group(1))
            os.makedirs(out_dir, exist_ok=True)

        # Check inflow files
        inflow_matches = re.findall(r"inflow_fl\s*=\s*'([^']+)'", nml_content)
        num_inflows_match = re.search(r"num_inflows\s*=\s*(\d+)", nml_content)
        num_inflows = int(num_inflows_match.group(1)) if num_inflows_match else 0
        if num_inflows > 0:
            for inf_path in inflow_matches:
                inf_full = os.path.join(args.run_dir, inf_path)
                if not os.path.exists(inf_full):
                    errors.append(f"Inflow file not found: {inf_full}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors,
                          "warnings": warnings}))
        sys.exit(1)

    return warnings


def process(args, preflight_warnings):
    """Run GLM and collect results."""
    nml_arg = f"--nml {args.nml_file}" if args.nml_file != "glm3.nml" else ""

    start_time = time.time()
    print(f"Starting GLM in {args.run_dir}...", file=sys.stderr)

    try:
        cmd = [args.glm_binary]
        if nml_arg:
            cmd.extend(["--nml", args.nml_file])

        result = subprocess.run(
            cmd,
            cwd=args.run_dir,
            capture_output=True,
            text=True,
            timeout=args.timeout,
        )
        elapsed = time.time() - start_time

        stdout_lines = result.stdout.strip().split('\n') if result.stdout else []
        stderr_lines = result.stderr.strip().split('\n') if result.stderr else []

        # Check for success
        success = result.returncode == 0
        if success:
            # Also verify "Model Run Complete" in stdout
            if any("Model Run Complete" in line for line in stdout_lines):
                status = "success"
            else:
                status = "completed_with_warnings"
        else:
            status = "failed"

        # Check output files
        output_files = {}
        nml_path = os.path.join(args.run_dir, args.nml_file)
        with open(nml_path) as f:
            nml_content = f.read()
        import re
        out_match = re.search(r"out_dir\s*=\s*'([^']+)'", nml_content)
        out_dir = os.path.join(args.run_dir,
                               out_match.group(1) if out_match else 'output')

        for fname in ['output.nc', 'lake.csv', 'overflow.csv']:
            fpath = os.path.join(out_dir, fname)
            if os.path.exists(fpath):
                output_files[fname] = {
                    "path": fpath,
                    "size_bytes": os.path.getsize(fpath),
                }

        return {
            "status": status,
            "return_code": result.returncode,
            "elapsed_seconds": round(elapsed, 1),
            "elapsed_formatted": f"{int(elapsed//3600):02d}:{int(elapsed%3600//60):02d}:{int(elapsed%60):02d}",
            "output_dir": out_dir,
            "output_files": output_files,
            "stdout_last_lines": stdout_lines[-10:] if stdout_lines else [],
            "stderr_last_lines": stderr_lines[-5:] if stderr_lines else [],
            "warnings": preflight_warnings,
        }

    except subprocess.TimeoutExpired:
        elapsed = time.time() - start_time
        return {
            "status": "timeout",
            "elapsed_seconds": round(elapsed, 1),
            "timeout_seconds": args.timeout,
            "message": f"GLM exceeded timeout of {args.timeout}s. "
                       f"Increase --timeout for longer simulations.",
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
        }


def main():
    parser = argparse.ArgumentParser(
        description="Execute GLM with preflight checks and output validation")
    parser.add_argument("--run_dir", type=str, required=True,
                        help="Directory containing glm3.nml and input files")
    parser.add_argument("--glm_binary", type=str, default=GLM_BINARY_DEFAULT,
                        help=f"Path to GLM executable (default: {GLM_BINARY_DEFAULT})")
    parser.add_argument("--nml_file", type=str, default="glm3.nml",
                        help="Namelist filename (default: glm3.nml)")
    parser.add_argument("--timeout", type=int, default=3600,
                        help="Maximum runtime in seconds (default: 3600)")
    args = parser.parse_args()

    preflight_warnings = validate_inputs(args)
    result = process(args, preflight_warnings)

    print(json.dumps(result, indent=2))

    if result["status"] in ["success", "completed_with_warnings"]:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
