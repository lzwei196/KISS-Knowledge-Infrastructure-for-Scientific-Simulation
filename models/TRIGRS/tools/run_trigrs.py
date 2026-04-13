#!/usr/bin/env python3
"""
run_trigrs.py
=============
Execution wrapper for TRIGRS: compile source (if needed), run TopoIndex,
run TRIGRS serial or parallel, validate outputs.

This wrapper performs preflight checks, builds the binary from Fortran
source if no binary exists, runs the utility programs and TRIGRS, and
validates that expected output files were created.

Usage:
    python run_trigrs.py \\
        --source_dir /path/to/trigrs/src/TRIGRS \\
        --work_dir /path/to/project/ \\
        --mode serial \\
        [--np 4]

Prerequisites:
    - gfortran installed
    - Input grids in place
    - tr_in.txt and tpx_in.txt configured
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path


def validate_inputs(source_dir: str, work_dir: str, mode: str) -> dict:
    """
    Validate all inputs before execution.

    Checks:
        1. Source directory contains Makefile and .f90/.f95 files
        2. Work directory contains tr_in.txt
        3. Compiler (gfortran) is available
        4. MPI available if parallel mode selected
    """
    errors = []

    # Check source directory
    makefile = os.path.join(source_dir, "Makefile")
    if not os.path.isfile(makefile):
        errors.append(f"Makefile not found in {source_dir}")

    fortran_files = list(Path(source_dir).glob("*.f90")) + \
                    list(Path(source_dir).glob("*.f95")) + \
                    list(Path(source_dir).glob("*.f"))
    if not fortran_files:
        errors.append(f"No Fortran source files in {source_dir}")

    # Check work directory
    tr_in = os.path.join(work_dir, "tr_in.txt")
    if not os.path.isfile(tr_in):
        errors.append(f"Initialization file not found: {tr_in}")

    # Check compiler
    try:
        subprocess.run(["gfortran", "--version"],
                       capture_output=True, check=True, timeout=10)
    except (FileNotFoundError, subprocess.CalledProcessError):
        errors.append("gfortran compiler not found. Install with: "
                       "apt install gfortran")

    # Check MPI if parallel
    if mode == "parallel":
        try:
            subprocess.run(["mpif90", "--version"],
                           capture_output=True, check=True, timeout=10)
        except (FileNotFoundError, subprocess.CalledProcessError):
            errors.append("mpif90 not found. Install with: "
                          "apt install libopenmpi-dev")

    if errors:
        raise ValueError("Preflight check failed:\n  " + "\n  ".join(errors))

    return {
        "source_dir": source_dir,
        "work_dir": work_dir,
        "mode": mode,
        "tr_in": tr_in,
    }


def compile_trigrs(source_dir: str, target: str = "trg",
                   compiler: str = "gfortran") -> str:
    """
    Compile TRIGRS from source.

    Args:
        source_dir: Path to src/TRIGRS directory
        target: 'trg' for serial, 'prg' for parallel, 'tpx' for TopoIndex
        compiler: Fortran compiler name

    Returns:
        Path to compiled binary
    """
    binary_path = os.path.join(source_dir, target)

    # Check if binary already exists and is up to date
    if os.path.isfile(binary_path):
        print(f"  Binary {target} already exists at {binary_path}")
        return binary_path

    print(f"  Compiling {target} from source...")

    # Modify Makefile to use gfortran if needed
    makefile = os.path.join(source_dir, "Makefile")

    result = subprocess.run(
        ["make", target],
        cwd=source_dir,
        capture_output=True,
        text=True,
        timeout=300,
        env={**os.environ, "FC": compiler, "F90": compiler}
    )

    if result.returncode != 0:
        print(f"  Compilation output:\n{result.stdout}")
        print(f"  Compilation errors:\n{result.stderr}")
        raise RuntimeError(f"Compilation of {target} failed. "
                           f"See errors above.")

    if not os.path.isfile(binary_path):
        raise RuntimeError(f"Compilation completed but binary "
                           f"{binary_path} not found")

    print(f"  Successfully compiled {target}")
    return binary_path


def compile_topoindex(source_dir: str, compiler: str = "gfortran") -> str:
    """Compile TopoIndex utility."""
    tpx_src = os.path.join(os.path.dirname(source_dir), "TopoIndex")
    if not os.path.isdir(tpx_src):
        # TopoIndex may be compiled from TRIGRS Makefile
        return compile_trigrs(source_dir, "tpx", compiler)

    # Try building in TopoIndex directory
    tpx_makefile = os.path.join(tpx_src, "Makefile")
    if os.path.isfile(tpx_makefile):
        return compile_trigrs(tpx_src, "tpx", compiler)

    return compile_trigrs(source_dir, "tpx", compiler)


def check_tr_in(tr_in_path: str) -> dict:
    """
    Parse tr_in.txt to extract key parameters for validation.
    """
    info = {}
    with open(tr_in_path, "r") as f:
        lines = f.readlines()

    # Line 4: tx, nmax, mmax, zones
    vals = lines[3].strip().split(",")
    if len(vals) >= 4:
        info["tx"] = int(vals[0].strip())
        info["nmax"] = int(vals[1].strip())
        info["mmax"] = int(vals[2].strip())
        info["zones"] = int(vals[3].strip())

    # Line 6: nzs, zmin, uww, nper, t
    vals = lines[5].strip().replace(",", " ").split()
    if len(vals) >= 5:
        info["nzs"] = int(vals[0])
        info["zmin"] = float(vals[1])
        info["uww"] = float(vals[2])
        info["nper"] = int(vals[3])
        info["t"] = float(vals[4])

    # Line 8: zmax, depth, rizero, slomin, slomax
    vals = lines[7].strip().replace(",", " ").split()
    if len(vals) >= 3:
        info["zmax"] = float(vals[0])
        info["depth"] = float(vals[1])
        info["rizero"] = float(vals[2])

    # Extract output folder
    for i, line in enumerate(lines):
        if "Folder where output" in line and i + 1 < len(lines):
            info["output_folder"] = lines[i + 1].strip()
            break

    # Extract suffix
    for i, line in enumerate(lines):
        if "Identification code" in line and i + 1 < len(lines):
            info["suffix"] = lines[i + 1].strip()
            break

    return info


def run_topoindex(tpx_binary: str, work_dir: str) -> dict:
    """Run TopoIndex to compute grid dimensions and flow routing."""
    tpx_in = os.path.join(work_dir, "tpx_in.txt")
    if not os.path.isfile(tpx_in):
        print("  No tpx_in.txt found, skipping TopoIndex")
        return {"status": "skipped", "reason": "no tpx_in.txt"}

    print("  Running TopoIndex...")
    result = subprocess.run(
        [tpx_binary],
        cwd=work_dir,
        capture_output=True,
        text=True,
        timeout=300,
    )

    return {
        "status": "completed" if result.returncode == 0 else "failed",
        "returncode": result.returncode,
        "stdout": result.stdout[:500],
        "stderr": result.stderr[:500],
    }


def run_trigrs_binary(binary_path: str, work_dir: str,
                      mode: str = "serial", np_procs: int = 1) -> dict:
    """
    Run the TRIGRS binary.

    Args:
        binary_path: Path to trg or prg binary
        work_dir: Working directory containing tr_in.txt
        mode: 'serial' or 'parallel'
        np_procs: Number of MPI processes (parallel mode only)

    Returns:
        dict with status, runtime, output
    """
    start_time = time.time()

    if mode == "parallel" and np_procs > 1:
        cmd = ["mpirun", "-np", str(np_procs), binary_path]
    else:
        cmd = [binary_path]

    print(f"  Running: {' '.join(cmd)}")
    print(f"  Working directory: {work_dir}")

    result = subprocess.run(
        cmd,
        cwd=work_dir,
        capture_output=True,
        text=True,
        timeout=3600,  # 1 hour max
    )

    elapsed = time.time() - start_time

    return {
        "status": "completed" if result.returncode == 0 else "failed",
        "returncode": result.returncode,
        "runtime_seconds": elapsed,
        "stdout": result.stdout[:2000],
        "stderr": result.stderr[:500],
    }


def validate_outputs(work_dir: str, tr_info: dict) -> dict:
    """
    Validate TRIGRS outputs exist and are reasonable.
    """
    results = {"files_found": [], "files_missing": [], "warnings": []}

    output_folder = tr_info.get("output_folder", "")
    suffix = tr_info.get("suffix", "")

    # Check for FS min grid
    output_dir = os.path.join(work_dir, output_folder)
    if os.path.isdir(output_dir):
        for f in os.listdir(output_dir):
            if f.startswith("TR") and (f.endswith(".asc") or
                                        f.endswith(".txt")):
                results["files_found"].append(f)
    else:
        results["warnings"].append(
            f"Output directory not found: {output_dir}")

    # Check log file
    log_file = os.path.join(work_dir, "TrigrsLog.txt")
    if os.path.isfile(log_file):
        results["files_found"].append("TrigrsLog.txt")
        with open(log_file, "r") as f:
            log_content = f.read()
        if "error" in log_content.lower():
            results["warnings"].append(
                "TrigrsLog.txt contains error messages")
        # Extract mass balance info
        for line in log_content.split("\n"):
            if "mass" in line.lower() or "balance" in line.lower():
                results.setdefault("mass_balance", []).append(line.strip())
    else:
        results["files_missing"].append("TrigrsLog.txt")

    return results


def main():
    parser = argparse.ArgumentParser(
        description="TRIGRS execution wrapper"
    )
    parser.add_argument("--source_dir", required=True,
                        help="Path to src/TRIGRS directory")
    parser.add_argument("--work_dir", required=True,
                        help="Working directory with tr_in.txt")
    parser.add_argument("--mode", default="serial",
                        choices=["serial", "parallel"])
    parser.add_argument("--np", type=int, default=1,
                        help="Number of MPI processes")
    parser.add_argument("--compiler", default="gfortran",
                        help="Fortran compiler")
    parser.add_argument("--skip_compile", action="store_true",
                        help="Skip compilation, use existing binary")
    parser.add_argument("--skip_topoindex", action="store_true",
                        help="Skip TopoIndex run")

    args = parser.parse_args()

    # Step 1: Preflight checks
    print("[1/5] Preflight checks...")
    try:
        params = validate_inputs(args.source_dir, args.work_dir, args.mode)
    except ValueError as e:
        print(f"FAILED: {e}")
        return 1

    # Step 2: Compile
    print("[2/5] Compilation...")
    target = "trg" if args.mode == "serial" else "prg"
    if args.skip_compile:
        binary = os.path.join(args.source_dir, target)
        if not os.path.isfile(binary):
            print(f"  Binary {binary} not found!")
            return 1
    else:
        try:
            binary = compile_trigrs(args.source_dir, target, args.compiler)
        except RuntimeError as e:
            print(f"  Compilation failed: {e}")
            return 1

    # Step 3: TopoIndex
    print("[3/5] TopoIndex...")
    if not args.skip_topoindex:
        try:
            tpx = compile_topoindex(args.source_dir, args.compiler)
            tpx_result = run_topoindex(tpx, args.work_dir)
            print(f"  TopoIndex: {tpx_result['status']}")
        except Exception as e:
            print(f"  TopoIndex skipped: {e}")

    # Step 4: Parse tr_in.txt
    print("[4/5] Running TRIGRS...")
    tr_info = check_tr_in(params["tr_in"])
    print(f"  Configuration: {tr_info.get('zones', '?')} zones, "
          f"nper={tr_info.get('nper', '?')}, "
          f"t={tr_info.get('t', '?')} s")

    # Run TRIGRS
    run_result = run_trigrs_binary(binary, args.work_dir, args.mode, args.np)
    print(f"  Status: {run_result['status']}")
    print(f"  Runtime: {run_result['runtime_seconds']:.1f} s")

    if run_result["status"] == "failed":
        print(f"  STDOUT:\n{run_result['stdout']}")
        print(f"  STDERR:\n{run_result['stderr']}")
        return 1

    # Step 5: Validate outputs
    print("[5/5] Validating outputs...")
    validation = validate_outputs(args.work_dir, tr_info)
    print(f"  Files found: {len(validation['files_found'])}")
    for f in validation["files_found"]:
        print(f"    - {f}")
    if validation["files_missing"]:
        print(f"  Files missing: {validation['files_missing']}")
    if validation["warnings"]:
        print("  Warnings:")
        for w in validation["warnings"]:
            print(f"    - {w}")

    # Summary
    summary = {
        "binary": binary,
        "mode": args.mode,
        "runtime_seconds": run_result["runtime_seconds"],
        "output_files": validation["files_found"],
        "warnings": validation["warnings"],
        "tr_info": tr_info,
    }

    print(f"\nDone. TRIGRS completed in {run_result['runtime_seconds']:.1f}s")
    print(f"Output files: {len(validation['files_found'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
