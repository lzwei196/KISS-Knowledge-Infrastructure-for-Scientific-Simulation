#!/usr/bin/env python3
"""
run_dart.py — Execute DART programs with pre/post validation.

CRITICAL:
  - DART programs read input.nml from the CURRENT WORKING DIRECTORY.
    You must cd to the work/ directory before running.
  - perfect_model_obs must run BEFORE filter (it generates obs_seq.out).
  - filter requires ensemble input files. For single_file_in=.true.,
    the file must contain all ensemble members.
  - NetCDF library must match the compiler used to build DART.
  - MPI programs (filter, perfect_model_obs) need mpirun if built with MPI.

Usage:
  python run_dart.py \\
      --program perfect_model_obs \\
      --work_dir /path/to/models/lorenz_63/work

  python run_dart.py \\
      --program filter \\
      --work_dir /path/to/models/lorenz_63/work

  python run_dart.py \\
      --program filter \\
      --work_dir /path/to/models/cam-fv/work \\
      --mpi --np 16
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


# Programs and their required input files
PROGRAM_REQUIREMENTS = {
    "preprocess": {
        "inputs": [],
        "outputs": ["obs_def_mod.f90", "obs_kind_mod.f90"],
        "description": "Generate observation type/quantity modules",
        "mpi_capable": False,
    },
    "create_obs_sequence": {
        "inputs": ["input.nml"],
        "outputs": ["set_def.out"],
        "description": "Define observation types and locations interactively",
        "mpi_capable": False,
    },
    "create_fixed_network_seq": {
        "inputs": ["input.nml", "set_def.out"],
        "outputs": ["obs_seq.in"],
        "description": "Replicate observation template across time",
        "mpi_capable": False,
    },
    "perfect_model_obs": {
        "inputs": ["input.nml", "obs_seq.in"],
        "outputs": ["obs_seq.out"],
        "description": "Generate synthetic observations from truth run",
        "mpi_capable": True,
    },
    "filter": {
        "inputs": ["input.nml", "obs_seq.out"],
        "outputs": ["obs_seq.final"],
        "description": "Run ensemble data assimilation",
        "mpi_capable": True,
    },
    "obs_diag": {
        "inputs": ["input.nml", "obs_seq.final"],
        "outputs": ["obs_diag_output.nc"],
        "description": "Compute observation-space diagnostics",
        "mpi_capable": False,
    },
    "obs_sequence_tool": {
        "inputs": ["input.nml"],
        "outputs": [],
        "description": "Manipulate observation sequence files",
        "mpi_capable": False,
    },
}


def validate_inputs(args):
    """Pre-execution validation."""
    errors = []

    if not os.path.isdir(args.work_dir):
        errors.append(f"Work directory not found: {args.work_dir}")
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)

    exe_path = os.path.join(args.work_dir, args.program)
    if not os.path.isfile(exe_path):
        errors.append(
            f"Executable not found: {exe_path}. "
            f"Did you run quickbuild.sh first?"
        )

    if args.program in PROGRAM_REQUIREMENTS:
        reqs = PROGRAM_REQUIREMENTS[args.program]
        for inp in reqs["inputs"]:
            inp_path = os.path.join(args.work_dir, inp)
            if not os.path.isfile(inp_path):
                errors.append(f"Required input file not found: {inp_path}")

    if args.mpi and args.program in PROGRAM_REQUIREMENTS:
        if not PROGRAM_REQUIREMENTS[args.program]["mpi_capable"]:
            errors.append(
                f"Program '{args.program}' is not MPI-capable. "
                f"Remove --mpi flag."
            )

    nml_path = os.path.join(args.work_dir, "input.nml")
    if os.path.isfile(nml_path):
        with open(nml_path) as f:
            content = f.read()
        if "&filter_nml" not in content and args.program == "filter":
            errors.append(
                "input.nml does not contain &filter_nml. "
                "Generate it with generate_input_nml.py."
            )

    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)


def run_program(args):
    """Execute the DART program and capture output."""
    exe_path = os.path.join(args.work_dir, args.program)

    if args.mpi:
        cmd = ["mpirun", "-np", str(args.np), exe_path]
    else:
        cmd = [exe_path]

    env = os.environ.copy()
    # Ensure NetCDF is findable
    if args.netcdf_path:
        env["NETCDF"] = args.netcdf_path
        env["LD_LIBRARY_PATH"] = (
            f"{args.netcdf_path}/lib:" + env.get("LD_LIBRARY_PATH", "")
        )

    print(f"Running: {' '.join(cmd)}", file=sys.stderr)
    print(f"Working directory: {args.work_dir}", file=sys.stderr)

    start_time = time.time()

    result = subprocess.run(
        cmd,
        cwd=args.work_dir,
        capture_output=True,
        text=True,
        timeout=args.timeout,
        env=env,
    )

    elapsed = time.time() - start_time

    return {
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "elapsed_seconds": round(elapsed, 2),
        "command": " ".join(cmd),
    }


def validate_outputs(run_result, args):
    """Post-execution validation."""
    warnings = []

    if run_result["returncode"] != 0:
        warnings.append(
            f"CRITICAL: {args.program} exited with code {run_result['returncode']}"
        )
        # Check for common errors
        combined = run_result["stdout"] + run_result["stderr"]
        if "STOP" in combined:
            warnings.append("Program hit Fortran STOP statement")
        if "NetCDF" in combined or "netcdf" in combined:
            warnings.append("NetCDF error — check library paths and file format")
        if "namelist" in combined.lower():
            warnings.append("Namelist read error — check input.nml format")
        if "inflation" in combined.lower():
            warnings.append("Inflation error — check inf_* parameters")
        return warnings

    # Check expected outputs exist
    if args.program in PROGRAM_REQUIREMENTS:
        reqs = PROGRAM_REQUIREMENTS[args.program]
        for out in reqs["outputs"]:
            out_path = os.path.join(args.work_dir, out)
            if not os.path.isfile(out_path):
                warnings.append(f"Expected output not found: {out_path}")

    # Check for filter-specific diagnostics
    if args.program == "filter":
        # Check obs_seq.final exists and has content
        final_path = os.path.join(args.work_dir, "obs_seq.final")
        if os.path.isfile(final_path):
            size = os.path.getsize(final_path)
            if size < 100:
                warnings.append(
                    f"obs_seq.final is very small ({size} bytes) — "
                    f"possibly no observations were assimilated"
                )
        # Check for analysis output
        analysis_mean = os.path.join(args.work_dir, "analysis_mean.nc")
        if not os.path.isfile(analysis_mean):
            warnings.append(
                "analysis_mean.nc not found — check stages_to_write in filter_nml"
            )

    # Check dart_log.out for warnings
    log_path = os.path.join(args.work_dir, "dart_log.out")
    if os.path.isfile(log_path):
        with open(log_path) as f:
            log_content = f.read()
        if "WARNING" in log_content:
            warning_lines = [l for l in log_content.split("\n") if "WARNING" in l]
            for wl in warning_lines[:5]:
                warnings.append(f"DART warning: {wl.strip()}")

    for w in warnings:
        print(f"WARNING: {w}", file=sys.stderr)

    return warnings


def main():
    parser = argparse.ArgumentParser(
        description="Execute DART programs with pre/post validation"
    )
    parser.add_argument("--program", required=True,
                        help="DART program to run (e.g., filter, perfect_model_obs)")
    parser.add_argument("--work_dir", required=True,
                        help="Path to DART model work/ directory")
    parser.add_argument("--mpi", action="store_true",
                        help="Run with MPI (mpirun)")
    parser.add_argument("--np", type=int, default=4,
                        help="Number of MPI processes (default: 4)")
    parser.add_argument("--netcdf_path", default=None,
                        help="Path to NetCDF installation (overrides NETCDF env var)")
    parser.add_argument("--timeout", type=int, default=3600,
                        help="Timeout in seconds (default: 3600)")

    args = parser.parse_args()

    # Step 1: validate
    validate_inputs(args)

    # Step 2: run
    run_result = run_program(args)

    # Step 3: validate outputs
    warnings = validate_outputs(run_result, args)

    # Step 4: report
    result = {
        "status": "success" if run_result["returncode"] == 0 else "failed",
        "program": args.program,
        "work_dir": args.work_dir,
        "returncode": run_result["returncode"],
        "elapsed_seconds": run_result["elapsed_seconds"],
        "command": run_result["command"],
        "stdout_first_500": run_result["stdout"][:500],
        "stderr_first_500": run_result["stderr"][:500],
        "warnings": warnings,
    }
    print(json.dumps(result, indent=2), file=sys.stderr)

    if run_result["returncode"] == 0:
        print(
            f"{args.program} completed successfully in "
            f"{run_result['elapsed_seconds']:.1f}s",
            file=sys.stderr
        )
    else:
        print(
            f"{args.program} FAILED with exit code {run_result['returncode']}",
            file=sys.stderr
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
