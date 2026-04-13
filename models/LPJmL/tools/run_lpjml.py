#!/usr/bin/env python3
"""
run_lpjml.py — Execute LPJmL with preflight checks and output validation.

Wraps the LPJmL binary with:
- Pre-flight validation of input files, config, and environment
- Execution with proper environment setup (LPJROOT, LPJINPATH, etc.)
- Post-run validation of output files and balance checks
- Log capture and error code interpretation

Usage:
    python run_lpjml.py --lpjroot /path/to/lpjml \
        --config lpjml_config.cjson \
        --mode spinup \
        --inpath /data/inputs \
        --outpath /data/outputs

Pattern: validate -> process -> validate
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


# LPJmL error code descriptions
ERROR_CODES = {
    1: "Error reading configuration",
    2: "Error initializing input data",
    3: "Error initializing grid",
    4: "Invalid carbon balance",
    5: "Invalid water balance",
    6: "Negative discharge",
    7: "Negative fire probability",
    8: "Negative soil moisture",
    9: "Error allocating memory",
    10: "Negative stand fraction",
    11: "Stand fraction sum error",
    15: "Invalid year in getco2()",
    16: "Crop fraction > 1",
    37: "Invalid nitrogen balance",
    38: "Invalid climate data",
    39: "Invalid FPC value",
}


def validate_inputs(lpjroot, config_path, mode, inpath=None):
    """Pre-flight validation before running LPJmL."""
    errors = []
    warnings = []

    # Check LPJROOT
    if not os.path.isdir(lpjroot):
        errors.append(f"LPJROOT directory not found: {lpjroot}")
        return errors, warnings

    # Check binary
    binary = os.path.join(lpjroot, "bin", "lpjml")
    if not os.path.isfile(binary):
        errors.append(
            f"LPJmL binary not found at {binary}. "
            f"Run 'make' in {lpjroot} first."
        )

    # Check config file
    if not os.path.isfile(config_path):
        errors.append(f"Configuration file not found: {config_path}")

    # Check output/restart directories
    output_dir = os.path.join(lpjroot, "output")
    restart_dir = os.path.join(lpjroot, "restart")

    if not os.path.isdir(output_dir):
        warnings.append(f"Output directory missing, creating: {output_dir}")
        os.makedirs(output_dir, exist_ok=True)

    if not os.path.isdir(restart_dir):
        warnings.append(f"Restart directory missing, creating: {restart_dir}")
        os.makedirs(restart_dir, exist_ok=True)

    # Check input path
    if inpath and not os.path.isdir(inpath):
        errors.append(f"Input path not found: {inpath}")

    # Mode-specific checks
    if mode == "transient":
        # Need restart file from spinup
        restart_files = list(Path(restart_dir).glob("*.lpj"))
        if not restart_files:
            warnings.append(
                "No restart files found. Transient run requires a spinup "
                "restart file. Run spinup first."
            )

    return errors, warnings


def build_command(lpjroot, config_path, mode, inpath=None, outpath=None,
                  restartpath=None, nproc=1, extra_macros=None):
    """Build the LPJmL execution command."""
    binary = os.path.join(lpjroot, "bin", "lpjml")

    cmd = []

    # MPI prefix
    if nproc > 1:
        cmd.extend(["mpirun", "-np", str(nproc)])

    cmd.append(binary)

    # Preprocessor macros
    if mode == "transient":
        cmd.append("-DFROM_RESTART")

    if extra_macros:
        for macro in extra_macros:
            cmd.append(f"-D{macro}")

    # Path options
    if inpath:
        cmd.extend(["-inpath", inpath])
    if outpath:
        cmd.extend(["-outpath", outpath])
    if restartpath:
        cmd.extend(["-restartpath", restartpath])

    # Config file
    cmd.append(config_path)

    return cmd


def validate_outputs(lpjroot, outpath, mode):
    """Post-run validation of LPJmL outputs."""
    warnings = []
    results = {}

    out_dir = outpath or os.path.join(lpjroot, "output")

    # Check that output files were created
    if os.path.isdir(out_dir):
        output_files = list(Path(out_dir).glob("*"))
        results["n_output_files"] = len(output_files)

        if len(output_files) == 0:
            warnings.append("WARNING: No output files generated.")
        else:
            total_size = sum(f.stat().st_size for f in output_files if f.is_file())
            results["total_output_size_mb"] = total_size / (1024 * 1024)
            print(f"Output: {len(output_files)} files, "
                  f"{results['total_output_size_mb']:.1f} MB total")

    # Check globalflux output for basic sanity
    globalflux_files = list(Path(out_dir).glob("globalflux*.csv"))
    if globalflux_files:
        try:
            with open(globalflux_files[0], "r") as f:
                lines = f.readlines()
            if len(lines) > 1:
                results["globalflux_years"] = len(lines) - 1
                print(f"Globalflux: {len(lines)-1} years of output")
        except Exception as e:
            warnings.append(f"Cannot read globalflux: {e}")

    # Check restart file
    restart_dir = os.path.join(lpjroot, "restart")
    restart_files = list(Path(restart_dir).glob("*.lpj"))
    if restart_files:
        newest = max(restart_files, key=lambda p: p.stat().st_mtime)
        results["restart_file"] = str(newest)
        results["restart_size_mb"] = newest.stat().st_size / (1024 * 1024)
        print(f"Restart file: {newest.name} ({results['restart_size_mb']:.1f} MB)")

    return warnings, results


def process(lpjroot, config_path, mode, inpath=None, outpath=None,
            restartpath=None, nproc=1, extra_macros=None, timeout=None):
    """Main execution: preflight -> run -> validate."""

    # Step 1: Validate inputs
    errors, warnings = validate_inputs(lpjroot, config_path, mode, inpath)

    for w in warnings:
        print(f"WARNING: {w}")
    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        return False, {}

    # Step 2: Build and execute command
    cmd = build_command(
        lpjroot, config_path, mode, inpath, outpath,
        restartpath, nproc, extra_macros
    )

    print(f"\nExecuting: {' '.join(cmd)}")
    print(f"Mode: {mode}")
    print(f"Start time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("-" * 60)

    env = os.environ.copy()
    env["LPJROOT"] = lpjroot
    if inpath:
        env["LPJINPATH"] = inpath
    if outpath:
        env["LPJOUTPATH"] = outpath

    start_time = time.time()

    try:
        result = subprocess.run(
            cmd,
            cwd=lpjroot,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        print(f"ERROR: LPJmL timed out after {timeout}s", file=sys.stderr)
        return False, {"error": "timeout"}
    except FileNotFoundError:
        print(f"ERROR: Binary not found: {cmd[0]}", file=sys.stderr)
        return False, {"error": "binary_not_found"}

    elapsed = time.time() - start_time

    # Print output
    if result.stdout:
        # Print first and last 20 lines
        lines = result.stdout.strip().split("\n")
        if len(lines) > 40:
            for line in lines[:20]:
                print(line)
            print(f"... ({len(lines) - 40} lines omitted) ...")
            for line in lines[-20:]:
                print(line)
        else:
            print(result.stdout)

    if result.stderr:
        print("\nSTDERR:", file=sys.stderr)
        print(result.stderr[:2000], file=sys.stderr)

    print("-" * 60)
    print(f"Exit code: {result.returncode}")
    print(f"Elapsed: {elapsed:.1f}s ({elapsed/60:.1f} min)")

    if result.returncode != 0:
        err_desc = ERROR_CODES.get(result.returncode, "Unknown error")
        print(f"ERROR {result.returncode}: {err_desc}", file=sys.stderr)
        return False, {
            "returncode": result.returncode,
            "error": err_desc,
            "elapsed_s": elapsed,
            "stdout_tail": result.stdout[-500:] if result.stdout else "",
        }

    # Step 3: Validate outputs
    out_warnings, out_results = validate_outputs(lpjroot, outpath, mode)
    for w in out_warnings:
        print(w, file=sys.stderr)

    out_results["returncode"] = 0
    out_results["elapsed_s"] = elapsed
    out_results["mode"] = mode

    return True, out_results


def main():
    parser = argparse.ArgumentParser(
        description="Run LPJmL with preflight checks and output validation"
    )
    parser.add_argument("--lpjroot", required=True, help="LPJmL root directory")
    parser.add_argument("--config", required=True, help="Configuration file")
    parser.add_argument("--mode", choices=["spinup", "transient"], default="spinup",
                        help="Run mode: spinup or transient")
    parser.add_argument("--inpath", default=None, help="Input data directory")
    parser.add_argument("--outpath", default=None, help="Output directory")
    parser.add_argument("--restartpath", default=None, help="Restart directory")
    parser.add_argument("--nproc", type=int, default=1, help="Number of MPI processes")
    parser.add_argument("--timeout", type=int, default=None, help="Timeout in seconds")
    parser.add_argument("--macro", action="append", default=[],
                        help="Additional preprocessor macros")

    args = parser.parse_args()

    success, results = process(
        lpjroot=args.lpjroot,
        config_path=args.config,
        mode=args.mode,
        inpath=args.inpath,
        outpath=args.outpath,
        restartpath=args.restartpath,
        nproc=args.nproc,
        extra_macros=args.macro,
        timeout=args.timeout,
    )

    if results:
        print(f"\nResults: {json.dumps(results, indent=2)}")

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
