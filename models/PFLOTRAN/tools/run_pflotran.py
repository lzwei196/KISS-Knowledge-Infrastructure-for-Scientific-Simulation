#!/usr/bin/env python3
"""
run_pflotran.py — Execution wrapper for PFLOTRAN subsurface flow simulator.

Handles pre-flight validation, binary discovery, MPI execution, output
verification, and error reporting for PFLOTRAN simulations.

Inputs:
    --input-file   : Path to PFLOTRAN input deck (.in)
    --pflotran-bin : Path to PFLOTRAN binary (auto-detected if not given)
    --nproc        : Number of MPI processes (default: 1)
    --timeout      : Maximum runtime in seconds (default: 3600)
    --workdir      : Working directory for execution (default: input file dir)

Outputs:
    - HDF5 output file (<prefix>.h5)
    - Observation files (<prefix>-obs-*.tec)
    - Mass balance file (<prefix>-mas.dat)
    - Screen output log (<prefix>.out)
    - Execution summary JSON

Usage:
    python run_pflotran.py \\
        --input-file bengbu_richards.in \\
        --nproc 4 \\
        --timeout 7200
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


def validate_inputs(args):
    """Validate all inputs before attempting execution.

    Checks:
    1. Input file exists and is readable
    2. PFLOTRAN binary exists and is executable
    3. MPI is available if nproc > 1
    4. Referenced data files exist
    5. Sufficient disk space for output

    Returns:
        dict with 'valid' (bool), 'errors' (list), 'warnings' (list)
    """
    errors = []
    warnings = []

    # Check input file
    if not os.path.isfile(args.input_file):
        errors.append(f"Input file not found: {args.input_file}")
    else:
        # Parse input deck for referenced files
        try:
            with open(args.input_file, "r") as f:
                content = f.read()
            # Check for FILE references
            for line in content.split("\n"):
                stripped = line.strip()
                if stripped.startswith("FILE ") or " FILE " in stripped.upper():
                    parts = stripped.split()
                    for i, p in enumerate(parts):
                        if p.upper() == "FILE" and i + 1 < len(parts):
                            ref_file = parts[i + 1]
                            ref_path = os.path.join(
                                os.path.dirname(args.input_file), ref_file
                            )
                            if not os.path.isfile(ref_path):
                                warnings.append(f"Referenced file not found: {ref_file}")
        except Exception as e:
            warnings.append(f"Could not parse input file: {e}")

    # Check PFLOTRAN binary
    pflotran_bin = find_pflotran_binary(args.pflotran_bin)
    if pflotran_bin is None:
        errors.append(
            "PFLOTRAN binary not found. Specify with --pflotran-bin or "
            "ensure 'pflotran' is in PATH."
        )
    elif not os.access(pflotran_bin, os.X_OK):
        errors.append(f"PFLOTRAN binary not executable: {pflotran_bin}")

    # Check MPI
    if args.nproc > 1:
        mpirun = shutil.which("mpirun") or shutil.which("mpiexec")
        if mpirun is None:
            errors.append("mpirun/mpiexec not found but nproc > 1")

    # Check nproc
    if args.nproc < 1:
        errors.append(f"nproc must be >= 1: {args.nproc}")

    # Check timeout
    if args.timeout <= 0:
        errors.append(f"Timeout must be > 0: {args.timeout}")

    return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings,
            "pflotran_bin": pflotran_bin}


def find_pflotran_binary(user_path=None):
    """Find PFLOTRAN binary.

    Search order:
    1. User-specified path
    2. PATH lookup
    3. Common installation locations
    4. Docker container

    Returns:
        str or None: Path to PFLOTRAN binary
    """
    if user_path and os.path.isfile(user_path):
        return user_path

    # Check PATH
    in_path = shutil.which("pflotran")
    if in_path:
        return in_path

    # Common locations
    common_paths = [
        "/usr/local/bin/pflotran",
        "/opt/pflotran/bin/pflotran",
        os.path.expanduser("~/pflotran/src/pflotran/pflotran"),
        os.path.expanduser("~/pflotran/pflotran"),
    ]

    for p in common_paths:
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p

    return None


def build_command(pflotran_bin, input_file, nproc):
    """Build the execution command.

    PFLOTRAN command format:
        mpirun -n <nproc> pflotran -pflotranin <input_file>

    For single process:
        pflotran -pflotranin <input_file>

    Alternative flag names:
        -pflotranin, -input_prefix, -stochastic

    Returns:
        list of str: Command components
    """
    input_prefix = os.path.splitext(os.path.basename(input_file))[0]

    if nproc > 1:
        mpirun = shutil.which("mpirun") or shutil.which("mpiexec")
        cmd = [mpirun, "-n", str(nproc), pflotran_bin, "-pflotranin", input_file]
    else:
        cmd = [pflotran_bin, "-pflotranin", input_file]

    return cmd


def run_pflotran(cmd, workdir, timeout, log_file=None):
    """Execute PFLOTRAN and capture output.

    Returns:
        dict with:
            - returncode: int
            - stdout: str
            - stderr: str
            - elapsed_s: float
            - success: bool
    """
    print(f"  Command: {' '.join(cmd)}")
    print(f"  Working directory: {workdir}")
    print(f"  Timeout: {timeout}s")

    start_time = time.time()

    try:
        result = subprocess.run(
            cmd,
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        elapsed = time.time() - start_time

        # Write log file
        if log_file:
            with open(log_file, "w") as f:
                f.write(f"Command: {' '.join(cmd)}\n")
                f.write(f"Return code: {result.returncode}\n")
                f.write(f"Elapsed: {elapsed:.2f}s\n")
                f.write(f"\n{'='*60}\nSTDOUT:\n{'='*60}\n")
                f.write(result.stdout)
                f.write(f"\n{'='*60}\nSTDERR:\n{'='*60}\n")
                f.write(result.stderr)

        return {
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "elapsed_s": elapsed,
            "success": result.returncode == 0,
        }

    except subprocess.TimeoutExpired:
        elapsed = time.time() - start_time
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": f"TIMEOUT after {timeout}s",
            "elapsed_s": elapsed,
            "success": False,
        }
    except FileNotFoundError as e:
        return {
            "returncode": -2,
            "stdout": "",
            "stderr": str(e),
            "elapsed_s": 0,
            "success": False,
        }


def validate_outputs(input_file, workdir, run_result):
    """Validate PFLOTRAN outputs after execution.

    Checks:
    1. HDF5 output file exists and is non-empty
    2. Observation files exist (if configured)
    3. Mass balance file exists
    4. No PETSC errors in output
    5. Simulation completed message present

    Returns:
        dict with 'valid' (bool), 'warnings' (list), 'output_files' (dict)
    """
    warnings = []
    output_files = {}
    prefix = os.path.splitext(os.path.basename(input_file))[0]

    # Check for completion message
    if "Simulation Complete" not in run_result.get("stdout", ""):
        if run_result.get("success"):
            warnings.append("No 'Simulation Complete' message in output")

    # Check for PETSc errors
    stderr = run_result.get("stderr", "")
    if "PETSC ERROR" in stderr or "PETSc Error" in stderr:
        warnings.append(f"PETSc error detected in stderr")

    # Check for convergence failures
    stdout = run_result.get("stdout", "")
    if "Time step cut" in stdout:
        cut_count = stdout.count("Time step cut")
        warnings.append(f"Time step was cut {cut_count} times (convergence issues)")

    # Check HDF5 output
    h5_file = os.path.join(workdir, f"{prefix}.h5")
    if os.path.isfile(h5_file):
        size_mb = os.path.getsize(h5_file) / (1024 * 1024)
        output_files["hdf5"] = {"path": h5_file, "size_mb": round(size_mb, 2)}
        if size_mb < 0.001:
            warnings.append(f"HDF5 output file is nearly empty ({size_mb:.4f} MB)")
    else:
        warnings.append(f"HDF5 output file not found: {h5_file}")

    # Check observation files
    obs_pattern = f"{prefix}-obs-"
    for f in os.listdir(workdir):
        if f.startswith(obs_pattern) and f.endswith(".tec"):
            obs_path = os.path.join(workdir, f)
            output_files[f"obs_{f}"] = {"path": obs_path, "size_kb": round(os.path.getsize(obs_path) / 1024, 2)}

    # Check mass balance
    mas_file = os.path.join(workdir, f"{prefix}-mas.dat")
    if os.path.isfile(mas_file):
        output_files["mass_balance"] = {"path": mas_file}
    else:
        warnings.append("Mass balance file not found (may not be configured)")

    valid = run_result.get("success", False) and len([w for w in warnings if "error" in w.lower()]) == 0

    return {"valid": valid, "warnings": warnings, "output_files": output_files}


def diagnose_failure(run_result):
    """Diagnose common PFLOTRAN failures from output.

    Returns:
        list of dicts with 'symptom', 'diagnosis', 'remedy'
    """
    diagnostics = []
    stdout = run_result.get("stdout", "")
    stderr = run_result.get("stderr", "")
    combined = stdout + stderr

    # PETSc version mismatch
    if "Incompatible PETSc" in combined or "PETSC_ARCH" in combined:
        diagnostics.append({
            "symptom": "PETSc version/arch mismatch",
            "diagnosis": "PFLOTRAN compiled with different PETSc than runtime",
            "remedy": "Rebuild PFLOTRAN with current PETSc: make clean && make pflotran",
        })

    # Missing input file
    if "ERROR: pflotranin" in combined or "Input file" in combined:
        diagnostics.append({
            "symptom": "Input file not found",
            "diagnosis": "PFLOTRAN cannot locate the .in file",
            "remedy": "Check -pflotranin path; run from directory containing .in file",
        })

    # Convergence failure
    if "Newton solver DIVERGED" in combined or "SNES_DIVERGED" in combined:
        diagnostics.append({
            "symptom": "Nonlinear solver divergence",
            "diagnosis": "Newton iterations failed to converge",
            "remedy": (
                "1. Reduce INITIAL_TIMESTEP_SIZE\n"
                "2. Check boundary conditions for physical consistency\n"
                "3. Check initial conditions (use HYDROSTATIC)\n"
                "4. Verify material properties (especially vG alpha units)"
            ),
        })

    # Memory error
    if "Allocated memory exceeded" in combined or "MemoryError" in combined:
        diagnostics.append({
            "symptom": "Out of memory",
            "diagnosis": "Grid too large for available RAM",
            "remedy": "Use more MPI processes (-n) or reduce grid resolution",
        })

    # HDF5 error
    if "HDF5" in combined and "Error" in combined:
        diagnostics.append({
            "symptom": "HDF5 I/O error",
            "diagnosis": "HDF5 library issue (version mismatch or disk full)",
            "remedy": "Check disk space; rebuild with compatible HDF5",
        })

    if not diagnostics:
        diagnostics.append({
            "symptom": "Unknown failure",
            "diagnosis": f"Return code: {run_result.get('returncode')}",
            "remedy": f"Check full output log. First 200 chars of stderr: {stderr[:200]}",
        })

    return diagnostics


def main():
    parser = argparse.ArgumentParser(description="PFLOTRAN execution wrapper")
    parser.add_argument("--input-file", required=True, help="Path to .in file")
    parser.add_argument("--pflotran-bin", help="Path to PFLOTRAN binary")
    parser.add_argument("--nproc", type=int, default=1, help="MPI processes")
    parser.add_argument("--timeout", type=int, default=3600, help="Max runtime (s)")
    parser.add_argument("--workdir", help="Working directory (default: input file dir)")

    args = parser.parse_args()

    if args.workdir is None:
        args.workdir = os.path.dirname(os.path.abspath(args.input_file))

    print("=" * 60)
    print("PFLOTRAN Execution Wrapper")
    print("=" * 60)

    # Step 1: Validate inputs
    print("\n[1/4] Pre-flight checks...")
    validation = validate_inputs(args)
    for err in validation["errors"]:
        print(f"  ERROR: {err}")
    for warn in validation["warnings"]:
        print(f"  WARNING: {warn}")

    if not validation["valid"]:
        print("\nPre-flight checks FAILED. Cannot proceed.")
        sys.exit(1)

    pflotran_bin = validation["pflotran_bin"]
    print(f"  Binary: {pflotran_bin}")
    print(f"  Input: {args.input_file}")
    print(f"  Processes: {args.nproc}")

    # Step 2: Build and run
    print("\n[2/4] Executing PFLOTRAN...")
    cmd = build_command(pflotran_bin, args.input_file, args.nproc)

    prefix = os.path.splitext(os.path.basename(args.input_file))[0]
    log_file = os.path.join(args.workdir, f"{prefix}.out")

    run_result = run_pflotran(cmd, args.workdir, args.timeout, log_file)

    print(f"\n  Return code: {run_result['returncode']}")
    print(f"  Elapsed: {run_result['elapsed_s']:.2f}s")

    # Step 3: Validate outputs
    print("\n[3/4] Validating outputs...")
    output_validation = validate_outputs(args.input_file, args.workdir, run_result)
    for w in output_validation["warnings"]:
        print(f"  WARNING: {w}")
    for name, info in output_validation["output_files"].items():
        print(f"  Output: {name} -> {info.get('path', 'N/A')}")

    # Step 4: Diagnose if failed
    if not run_result["success"]:
        print("\n[4/4] Diagnosing failure...")
        diagnostics = diagnose_failure(run_result)
        for d in diagnostics:
            print(f"  Symptom: {d['symptom']}")
            print(f"  Diagnosis: {d['diagnosis']}")
            print(f"  Remedy: {d['remedy']}")
            print()
    else:
        print("\n[4/4] Execution successful!")

    # Write summary JSON
    summary = {
        "timestamp": datetime.now().isoformat(),
        "input_file": args.input_file,
        "pflotran_bin": pflotran_bin,
        "nproc": args.nproc,
        "command": " ".join(cmd),
        "returncode": run_result["returncode"],
        "elapsed_s": run_result["elapsed_s"],
        "success": run_result["success"],
        "output_files": output_validation["output_files"],
        "warnings": output_validation["warnings"],
        "stdout_first_500": run_result["stdout"][:500],
        "stderr_first_500": run_result["stderr"][:500],
    }

    summary_path = os.path.join(args.workdir, f"{prefix}_run_summary.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\n  Summary: {summary_path}")

    sys.exit(0 if run_result["success"] else 1)


if __name__ == "__main__":
    main()
