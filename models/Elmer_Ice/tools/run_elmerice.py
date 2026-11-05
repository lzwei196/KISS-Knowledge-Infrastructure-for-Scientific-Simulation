#!/usr/bin/env python3
"""
run_elmerice.py — Execute ElmerSolver with preflight checks and output capture.

Runs an Elmer/Ice simulation from a SIF file, performing preflight validation
of the mesh, SIF, and environment before launching the solver.

CRITICAL ISSUES:
  - For MPI runs, the mesh MUST be partitioned first with ElmerGrid.
    Running mpirun without partitioned mesh causes immediate crash (dt_011).
  - ElmerSolver lookup: --solver_binary -> $ELMERSOLVER_BIN -> `which ElmerSolver`
    -> the server's Elmer/Ice build (install_ice, same as preflight_check.py).
    An explicit binary that cannot be found is an error (no other engine is tried).
  - Success needs return code 0 AND ElmerSolver's own "*** Elmer Solver: ALL DONE ***"
    line (ElmerSolver returns 0 even when it stops early, e.g. on a missing library).
  - SIF file must reference the correct mesh directory (relative path).
  - Working directory matters: SIF paths are relative to CWD.

Usage:
    python run_elmerice.py --sif simulation.sif --run_dir ./run --np 1 --timeout 3600

    # Parallel run (mesh must be partitioned first)
    python run_elmerice.py --sif simulation.sif --run_dir ./run --np 4 --timeout 7200
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time

# Server default: the Elmer/Ice build (ships ElmerIceSolvers / ElmerIceUSF), as preflight_check.py
SERVER_ELMERSOLVER = ("KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/"
                      "Elmer_Ice/install_ice/bin/ElmerSolver")
ALL_DONE = "*** Elmer Solver: ALL DONE ***"
ERROR_LINE = re.compile(r"ERROR::|cannot open shared object|Segmentation fault|"
                        r"Program received signal|STOP\s+\d|ABORT", re.IGNORECASE)


def _exe(path):
    return bool(path) and os.path.isfile(path) and os.access(path, os.X_OK)


def resolve_solver(cli_value):
    """--solver_binary -> $ELMERSOLVER_BIN -> which ElmerSolver -> install_ice build.

    Returns (absolute path or None, source, error)."""
    for label, cand in (("--solver_binary", cli_value),
                        ("$ELMERSOLVER_BIN", os.environ.get("ELMERSOLVER_BIN", "").strip())):
        if cand:
            path = shutil.which(cand) if os.sep not in cand else cand
            if _exe(path):
                return os.path.abspath(path), label, None
            return None, label, f"Solver binary from {label} not found or not executable: {cand}"
    on_path = shutil.which("ElmerSolver")
    if on_path:
        return os.path.abspath(on_path), "PATH", None
    if _exe(SERVER_ELMERSOLVER):
        return SERVER_ELMERSOLVER, "server default (Elmer/Ice build)", None
    return None, "default", (f"ElmerSolver not found on PATH nor at {SERVER_ELMERSOLVER}; "
                             "use --solver_binary or set ELMERSOLVER_BIN")


def elmer_ice_libs_missing(solver):
    """Elmer/Ice libraries missing from the solver's install prefix (info only)."""
    prefix = os.path.dirname(os.path.dirname(os.path.realpath(solver)))
    mod_dir = os.path.join(prefix, "share", "elmersolver", "lib")
    return [lib for lib in ("ElmerIceSolvers.so", "ElmerIceUSF.so")
            if not os.path.isfile(os.path.join(mod_dir, lib))]


def mesh_dir_from_sif(sif_path, base_dir):
    try:
        with open(sif_path, "r", errors="replace") as f:
            m = re.search(r'Mesh\s+DB\s+"([^"]+)"\s+"([^"]+)"', f.read())
    except OSError:
        return None
    if not m:
        return None
    return os.path.normpath(os.path.join(base_dir, m.group(1), m.group(2)))


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

    # Check solver binary (resolved once, absolute, before the cwd change)
    solver, source, err = resolve_solver(args.solver_binary)
    if err:
        errors.append(err)
    else:
        args.solver_binary = solver
        print(f"ElmerSolver: {solver} (from {source})", file=sys.stderr)
        missing_libs = elmer_ice_libs_missing(solver)
        if missing_libs:
            warnings.append(f"This ElmerSolver build has no Elmer/Ice libraries "
                            f"({', '.join(missing_libs)}); cases using Elmer/Ice solvers "
                            f"or user functions will not run with it")

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


def finished_normally(run_result):
    return run_result["returncode"] == 0 and ALL_DONE in (
        run_result["stdout"] + run_result["stderr"])


def find_vtu_files(args):
    """VTU files in the run dir, the SIF's mesh dir and its partitioning dirs."""
    base = args.run_dir or os.getcwd()
    dirs = [base]
    mesh_dir = mesh_dir_from_sif(os.path.join(base, args.sif), base)
    if mesh_dir and os.path.isdir(mesh_dir):
        dirs.append(mesh_dir)
        dirs += sorted(os.path.join(mesh_dir, d) for d in os.listdir(mesh_dir)
                       if d.startswith("partitioning.")
                       and os.path.isdir(os.path.join(mesh_dir, d)))
    found = []
    for d in dict.fromkeys(os.path.normpath(x) for x in dirs):
        found += [os.path.join(d, f) for f in sorted(os.listdir(d)) if f.endswith(".vtu")]
    return found


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

    elif not finished_normally(run_result):
        warnings.append(f"Completion not confirmed: return code 0 but '{ALL_DONE}' "
                        "is missing (solver stopped early, or logging settings hide it: "
                        "Max Output Level / Output To File)")
    else:
        vtu_files = find_vtu_files(args)
        if not vtu_files:
            warnings.append("No VTU files found in the run dir or mesh dir — check "
                            "Post File / Output Intervals / output directory in SIF (dt_015)")
        else:
            warnings.append(f"Found {len(vtu_files)} VTU file(s): "
                            + ", ".join(vtu_files[:10]))

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
    parser.add_argument("--solver_binary", type=str, default=None,
                        help="ElmerSolver binary (default: $ELMERSOLVER_BIN, then "
                             "ElmerSolver on PATH, then the server Elmer/Ice build)")
    parser.add_argument("--np", type=int, default=1,
                        help="Number of MPI processes (1 = serial)")
    parser.add_argument("--timeout", type=int, default=3600,
                        help="Timeout in seconds (default 3600)")

    args = parser.parse_args()

    preflight_warnings = validate_inputs(args)
    run_result = process(args)
    output_warnings = validate_outputs(run_result, args)

    ok = finished_normally(run_result)
    combined = run_result["stdout"] + "\n" + run_result["stderr"]
    # Build status report
    status = {
        "status": "success" if ok else "failed",
        "finished_normally": ok,
        "returncode": run_result["returncode"],
        "elapsed_seconds": round(run_result["elapsed_seconds"], 1),
        "command": run_result["command"],
        "timed_out": run_result["timed_out"],
        "stdout_last_20": "\n".join(
            run_result["stdout"].strip().split("\n")[-20:]),
        "stderr_last_10": "\n".join(
            run_result["stderr"].strip().split("\n")[-10:]),
        "stdout_tail": "\n".join(run_result["stdout"].strip().split("\n")[-200:]),
        "stderr_tail": "\n".join(run_result["stderr"].strip().split("\n")[-50:]),
        "error_lines": [l.strip() for l in combined.splitlines()
                        if ERROR_LINE.search(l)][:20],
        "vtu_files": find_vtu_files(args) if ok else [],
        "preflight_warnings": preflight_warnings,
        "output_warnings": output_warnings,
    }

    print(json.dumps(status, indent=2), file=sys.stderr)

    # Exit with the solver's return code; 1 if it returned 0 without finishing
    if run_result["returncode"] != 0:
        sys.exit(run_result["returncode"])
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
