#!/usr/bin/env python3
"""
run_elmerice.py — Execute ElmerSolver with preflight checks and output capture.

Runs an Elmer/Ice simulation from a SIF file, performing preflight validation
of the mesh, SIF, and environment before launching the solver.

CRITICAL ISSUES:
  - For MPI runs, the mesh MUST be partitioned first with ElmerGrid.
    Running mpirun without partitioned mesh causes immediate crash (dt_011).
  - ElmerSolver binary must be in PATH or specified explicitly.
  - SIF file must reference the correct mesh directory (relative path).
  - Working directory matters: SIF paths are relative to CWD.

Usage:
    python run_elmerice.py --sif simulation.sif --run_dir ./run \
        --solver_binary ElmerSolver --np 1 --timeout 3600

    # Parallel run (mesh must be partitioned first)
    python run_elmerice.py --sif simulation.sif --run_dir ./run \
        --solver_binary ElmerSolver --np 4 --timeout 7200
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time


def validate_inputs(args):
    """Preflight checks before running ElmerSolver."""
    errors = []
    warnings = []

    # Check SIF file exists
    sif_path = os.path.join(args.run_dir, args.sif) if args.run_dir else args.sif
    if not os.path.isfile(sif_path):
        errors.append(f"SIF file not found: {sif_path}")

    # Check run directory
    if args.run_dir and not os.path.isdir(args.run_dir):
        errors.append(f"Run directory not found: {args.run_dir}")

    # Check solver binary
    solver = shutil.which(args.solver_binary)
    if solver is None:
        errors.append(f"Solver binary not found: {args.solver_binary}. "
                      "Is Elmer installed and in PATH?")

    # Check MPI for parallel runs
    if args.np > 1:
        mpirun = shutil.which("mpirun") or shutil.which("mpiexec")
        if mpirun is None:
            errors.append("mpirun/mpiexec not found for parallel run")

    # Parse SIF to check mesh directory reference
    if os.path.isfile(sif_path if not args.run_dir
                      else os.path.join(args.run_dir, args.sif)):
        actual_sif = (os.path.join(args.run_dir, args.sif) if args.run_dir
                      else args.sif)
        try:
            with open(actual_sif, "r") as f:
                sif_content = f.read()

            # Extract mesh directory
            mesh_match = re.search(r'Mesh\s+DB\s+"([^"]+)"\s+"([^"]+)"',
                                   sif_content)
            if mesh_match:
                mesh_base = mesh_match.group(1)
                mesh_name = mesh_match.group(2)
                if args.run_dir:
                    mesh_dir = os.path.join(args.run_dir, mesh_base, mesh_name)
                else:
                    mesh_dir = os.path.join(mesh_base, mesh_name)

                if not os.path.isdir(mesh_dir):
                    errors.append(f"Mesh directory not found: {mesh_dir}")
                else:
                    # Check mesh files exist
                    for mf in ["mesh.header", "mesh.nodes", "mesh.elements",
                               "mesh.boundary"]:
                        if not os.path.isfile(os.path.join(mesh_dir, mf)):
                            errors.append(f"Missing mesh file: {mf} in {mesh_dir}")

                    # Check partitioning for parallel runs
                    if args.np > 1:
                        part_dir = os.path.join(mesh_dir, "partitioning." +
                                                str(args.np))
                        if not os.path.isdir(part_dir):
                            errors.append(
                                f"Mesh not partitioned for {args.np} procs. "
                                f"Run: ElmerGrid 2 2 {mesh_name} "
                                f"-partdual -metis {args.np} (dt_011)")
        except (IOError, OSError) as e:
            warnings.append(f"Could not parse SIF: {e}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors,
                          "warnings": warnings}), file=sys.stderr)
        sys.exit(1)

    if warnings:
        for w in warnings:
            print(f"WARNING: {w}", file=sys.stderr)

    return warnings


def process(args):
    """Run ElmerSolver and capture output."""
    # Build command
    if args.np > 1:
        mpirun = shutil.which("mpirun") or shutil.which("mpiexec")
        cmd = [mpirun, "-np", str(args.np), args.solver_binary, args.sif]
    else:
        cmd = [args.solver_binary, args.sif]

    print(f"Running: {' '.join(cmd)}", file=sys.stderr)
    print(f"Working directory: {args.run_dir or os.getcwd()}", file=sys.stderr)

    start_time = time.time()

    try:
        result = subprocess.run(
            cmd,
            cwd=args.run_dir or None,
            capture_output=True,
            text=True,
            timeout=args.timeout,
        )
        elapsed = time.time() - start_time

        return {
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "elapsed_seconds": elapsed,
            "command": " ".join(cmd),
            "timed_out": False,
        }

    except subprocess.TimeoutExpired:
        elapsed = time.time() - start_time
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": f"Process timed out after {args.timeout}s",
            "elapsed_seconds": elapsed,
            "command": " ".join(cmd),
            "timed_out": True,
        }

    except FileNotFoundError as e:
        return {
            "returncode": -2,
            "stdout": "",
            "stderr": str(e),
            "elapsed_seconds": 0,
            "command": " ".join(cmd),
            "timed_out": False,
        }


def validate_outputs(run_result, args):
    """Check solver execution results."""
    warnings = []

    if run_result["timed_out"]:
        warnings.append(f"Solver timed out after {args.timeout}s. "
                        "Consider increasing --timeout or using iterative solver")
        return warnings

    if run_result["returncode"] != 0:
        warnings.append(f"Solver exited with code {run_result['returncode']}")

        # Parse common error patterns
        stderr = run_result["stderr"]
        stdout = run_result["stdout"]
        combined = stdout + stderr

        if "MUMPS" in combined and ("not enough memory" in combined.lower()
                                     or "error" in combined.lower()):
            warnings.append("MUMPS out-of-memory — switch to iterative solver "
                            "or use fewer mesh elements (dt_017)")

        if "mesh" in combined.lower() and "not found" in combined.lower():
            warnings.append("Mesh directory not found — check SIF Header block")

        if "nan" in combined.lower() or "NaN" in combined:
            warnings.append("NaN detected — check Critical Shear Rate > 0 (dt_013) "
                            "and initial conditions")

    else:
        # Check for VTU output
        if args.run_dir:
            vtu_files = [f for f in os.listdir(args.run_dir)
                         if f.endswith(".vtu")]
        else:
            vtu_files = [f for f in os.listdir(".")
                         if f.endswith(".vtu")]

        if not vtu_files:
            warnings.append("No VTU files produced — check Output Intervals "
                            "in SIF (dt_015)")
        else:
            warnings.append(f"Found {len(vtu_files)} VTU output file(s)")

    for w in warnings:
        print(f"INFO: {w}", file=sys.stderr)
    return warnings


def main():
    parser = argparse.ArgumentParser(
        description="Run Elmer/Ice simulation with preflight checks")
    parser.add_argument("--sif", type=str, required=True,
                        help="SIF filename (relative to run_dir)")
    parser.add_argument("--run_dir", type=str, default=None,
                        help="Working directory for the simulation")
    parser.add_argument("--solver_binary", type=str, default="ElmerSolver",
                        help="Path to ElmerSolver binary")
    parser.add_argument("--np", type=int, default=1,
                        help="Number of MPI processes (1 = serial)")
    parser.add_argument("--timeout", type=int, default=3600,
                        help="Timeout in seconds (default 3600)")

    args = parser.parse_args()

    preflight_warnings = validate_inputs(args)
    run_result = process(args)
    output_warnings = validate_outputs(run_result, args)

    # Build status report
    status = {
        "status": "success" if run_result["returncode"] == 0 else "failed",
        "returncode": run_result["returncode"],
        "elapsed_seconds": round(run_result["elapsed_seconds"], 1),
        "command": run_result["command"],
        "timed_out": run_result["timed_out"],
        "stdout_last_20": "\n".join(
            run_result["stdout"].strip().split("\n")[-20:]),
        "stderr_last_10": "\n".join(
            run_result["stderr"].strip().split("\n")[-10:]),
        "preflight_warnings": preflight_warnings,
        "output_warnings": output_warnings,
    }

    print(json.dumps(status, indent=2), file=sys.stderr)

    # Exit with solver's return code
    sys.exit(run_result["returncode"])


if __name__ == "__main__":
    main()
