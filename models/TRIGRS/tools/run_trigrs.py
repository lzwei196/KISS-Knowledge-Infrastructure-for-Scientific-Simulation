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

    # with built binaries (no source tree, no compiler needed):
    python run_trigrs.py --work_dir /path/to/project/ \\
        [--trg_binary /path/to/trg] [--tpx_binary /path/to/tpx]

Binary lookup (no silent switch to another engine):
    TRIGRS:    --trg_binary -> $TRIGRS_BIN -> <source_dir>/trg|prg (compiled if
               missing, unless --skip_compile) -> server default bin/trg (serial,
               only when no --source_dir is given)
    TopoIndex: --tpx_binary -> $TOPOINDEX_BIN -> built <source_dir>/../TopoIndex/tpx
               or <source_dir>/tpx (compiled if missing, unless --skip_compile) ->
               server default src/TopoIndex/tpx (only when no --source_dir)
    An explicit binary that is not an executable file is an error.

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

# Server defaults (same as preflight_check.py)
MODEL_DIR = Path(__file__).resolve().parents[2]
SERVER_TRG = MODEL_DIR / "bin" / "trg"
SERVER_TPX = (MODEL_DIR / "source" / "repo" / "source" / "trigrs_full" / "src"
              / "TopoIndex" / "tpx")

# Log lines that contain "error" but are information only
INFO_LOG_LINES = (
    "early-time errors in unsaturated infiltration model",
    "if errors occur in runoff routing",
)


def is_error_line(line: str) -> bool:
    low = line.lower()
    return "error" in low and not any(s in low for s in INFO_LOG_LINES)


def _is_exe(path) -> bool:
    return bool(path) and os.path.isfile(path) and os.access(path, os.X_OK)


def pick_explicit(cli_value, env_name, what):
    """CLI option, then env var. Returns (path or None, error or None)."""
    for label, cand in ((f"--{what}", cli_value), (f"${env_name}", os.environ.get(env_name))):
        if cand:
            if _is_exe(cand):
                return os.path.abspath(cand), None
            return None, f"{what} from {label} is not an executable file: {cand}"
    return None, None


def fresh_log(path: str) -> None:
    """Move an old log aside so a new run cannot pass on an old log's lines."""
    if os.path.exists(path):
        os.replace(path, path + ".prev")


def read_text(path: str) -> str:
    try:
        with open(path, "r", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def validate_inputs(source_dir: str, work_dir: str, mode: str,
                    need_compile: bool = True) -> dict:
    """
    Validate all inputs before execution.

    Checks:
        1. Work directory contains tr_in.txt
        2. Only when a compile is needed: source directory contains Makefile and
           Fortran files, compiler (gfortran) and, for parallel, mpif90 available
    """
    errors = []

    # Check work directory
    tr_in = os.path.join(work_dir, "tr_in.txt")
    if not os.path.isfile(tr_in):
        errors.append(f"Initialization file not found: {tr_in}")

    if not need_compile:
        if errors:
            raise ValueError("Preflight check failed:\n  " + "\n  ".join(errors))
        return {"source_dir": source_dir, "work_dir": work_dir, "mode": mode,
                "tr_in": tr_in}

    # Check source directory
    makefile = os.path.join(source_dir, "Makefile")
    if not os.path.isfile(makefile):
        errors.append(f"Makefile not found in {source_dir}")

    fortran_files = list(Path(source_dir).glob("*.f90")) + \
                    list(Path(source_dir).glob("*.f95")) + \
                    list(Path(source_dir).glob("*.f"))
    if not fortran_files:
        errors.append(f"No Fortran source files in {source_dir}")

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


def built_topoindex(source_dir: str):
    """Already-built TopoIndex in the source tree (src/TopoIndex/tpx or src/TRIGRS/tpx)."""
    for cand in (os.path.join(os.path.dirname(source_dir), "TopoIndex", "tpx"),
                 os.path.join(source_dir, "tpx")):
        if _is_exe(cand):
            return os.path.abspath(cand)
    return None


def compile_topoindex(source_dir: str, compiler: str = "gfortran") -> str:
    """Compile TopoIndex utility."""
    built = built_topoindex(source_dir)
    if built:
        print(f"  Binary tpx already exists at {built}")
        return built
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

    print(f"  Running TopoIndex: {tpx_binary}")
    log_path = os.path.join(work_dir, "TopoIndexLog.txt")
    fresh_log(log_path)
    try:
        result = subprocess.run(
            [tpx_binary],
            cwd=work_dir,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"status": "failed", "returncode": None, "stdout": "",
                "stderr": f"TopoIndex could not run: {e}"}

    finished = "TopoIndex finished normally" in read_text(log_path)
    return {
        "status": "completed" if result.returncode == 0 and finished else "failed",
        "returncode": result.returncode,
        "finished_normally": finished,
        "stdout": result.stdout[-2000:],
        "stderr": result.stderr[-2000:],
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

    log_path = os.path.join(work_dir, "TrigrsLog.txt")
    fresh_log(log_path)
    try:
        result = subprocess.run(
            cmd,
            cwd=work_dir,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=3600,  # 1 hour max
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"status": "failed", "returncode": None,
                "runtime_seconds": time.time() - start_time,
                "stdout": "", "stderr": f"TRIGRS could not run: {e}"}

    elapsed = time.time() - start_time
    finished = "TRIGRS finished normally" in read_text(log_path)

    return {
        "status": "completed" if result.returncode == 0 and finished else "failed",
        "returncode": result.returncode,
        "finished_normally": finished,
        "runtime_seconds": elapsed,
        "stdout": result.stdout[-2000:],
        "stderr": result.stderr[-2000:],
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
        if any(is_error_line(l) for l in log_content.splitlines()):
            results["warnings"].append(
                "TrigrsLog.txt contains error messages")
        if "Skipped runoff-routing computations" in log_content:
            results["warnings"].append(
                "TRIGRS skipped runoff routing (routing input data did not exist); "
                "check the TopoIndex output names in tr_in.txt")
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
    parser.add_argument("--source_dir", default=None,
                        help="Path to src/TRIGRS directory (optional when a built "
                             "binary is given or the server default is used)")
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
    parser.add_argument("--trg_binary", default=None,
                        help="Built TRIGRS binary (trg, or prg for --mode parallel); "
                             "default: $TRIGRS_BIN, then <source_dir>, then server bin/trg")
    parser.add_argument("--tpx_binary", default=None,
                        help="Built TopoIndex binary; default: $TOPOINDEX_BIN, then "
                             "<source_dir>/../TopoIndex/tpx, then the server build")

    args = parser.parse_args()
    target = "trg" if args.mode == "serial" else "prg"
    work_dir = os.path.abspath(args.work_dir)
    source_dir = os.path.abspath(args.source_dir) if args.source_dir else None

    # Step 0: resolve the TRIGRS binary (no silent switch to another engine)
    binary, err = pick_explicit(args.trg_binary, "TRIGRS_BIN", "trg_binary")
    if err:
        print(f"FAILED: {err}")
        return 1
    need_compile = False
    if not binary and source_dir:
        cand = os.path.join(source_dir, target)
        if _is_exe(cand):
            binary = cand
        elif args.skip_compile:
            print(f"FAILED: Binary {cand} not found (--skip_compile given)")
            return 1
        else:
            need_compile = True
    elif not binary:
        if args.mode != "serial":
            print("FAILED: --mode parallel needs --trg_binary/$TRIGRS_BIN or a "
                  "--source_dir with prg (the server default is the serial trg)")
            return 1
        if not _is_exe(str(SERVER_TRG)):
            print(f"FAILED: TRIGRS binary not found (server default {SERVER_TRG}); "
                  "use --trg_binary, $TRIGRS_BIN or --source_dir")
            return 1
        binary = str(SERVER_TRG)

    # Step 1: Preflight checks
    print("[1/5] Preflight checks...")
    try:
        params = validate_inputs(source_dir, work_dir, args.mode,
                                 need_compile=need_compile)
    except ValueError as e:
        print(f"FAILED: {e}")
        return 1
    if args.mode == "parallel" and args.np > 1 and not shutil.which("mpirun"):
        print("FAILED: mpirun not found for --mode parallel")
        return 1

    # Step 2: Compile
    print("[2/5] Compilation...")
    if need_compile:
        try:
            binary = compile_trigrs(source_dir, target, args.compiler)
        except RuntimeError as e:
            print(f"  Compilation failed: {e}")
            return 1
    else:
        print(f"  Using built binary {binary}")

    # Step 3: TopoIndex
    print("[3/5] TopoIndex...")
    if args.skip_topoindex:
        print("  TopoIndex skipped (--skip_topoindex)")
    elif not os.path.isfile(os.path.join(work_dir, "tpx_in.txt")):
        print("  No tpx_in.txt found, skipping TopoIndex")
    else:
        tpx, err = pick_explicit(args.tpx_binary, "TOPOINDEX_BIN", "tpx_binary")
        if err:
            print(f"FAILED: {err}")
            return 1
        if not tpx and source_dir:
            tpx = built_topoindex(source_dir)
            if not tpx and args.skip_compile:
                print(f"FAILED: no built TopoIndex (tpx) next to {source_dir} "
                      "(--skip_compile given); use --tpx_binary or --skip_topoindex")
                return 1
            if not tpx:
                try:
                    tpx = compile_topoindex(source_dir, args.compiler)
                except Exception as e:
                    print(f"FAILED: TopoIndex could not be built: {e}")
                    return 1
        elif not tpx:
            if not _is_exe(str(SERVER_TPX)):
                print(f"FAILED: TopoIndex binary not found (server default {SERVER_TPX}); "
                      "use --tpx_binary, $TOPOINDEX_BIN or --skip_topoindex")
                return 1
            tpx = str(SERVER_TPX)
        tpx_result = run_topoindex(tpx, work_dir)
        print(f"  TopoIndex: {tpx_result['status']}")
        if tpx_result["status"] != "completed":
            print(f"FAILED: TopoIndex did not finish normally "
                  f"(rc={tpx_result.get('returncode')}, "
                  f"'TopoIndex finished normally' in TopoIndexLog.txt: "
                  f"{tpx_result.get('finished_normally')})")
            print(f"  STDOUT:\n{tpx_result['stdout']}")
            print(f"  STDERR:\n{tpx_result['stderr']}")
            return 1

    # Step 4: Parse tr_in.txt
    print("[4/5] Running TRIGRS...")
    tr_info = check_tr_in(params["tr_in"])
    print(f"  Configuration: {tr_info.get('zones', '?')} zones, "
          f"nper={tr_info.get('nper', '?')}, "
          f"t={tr_info.get('t', '?')} s")

    # Run TRIGRS
    run_result = run_trigrs_binary(binary, work_dir, args.mode, args.np)
    print(f"  Status: {run_result['status']}")
    print(f"  Runtime: {run_result['runtime_seconds']:.1f} s")

    if run_result["status"] == "failed":
        print(f"  Return code: {run_result.get('returncode')}; "
              f"'TRIGRS finished normally' in TrigrsLog.txt: "
              f"{run_result.get('finished_normally')}")
        print(f"  STDOUT:\n{run_result['stdout']}")
        print(f"  STDERR:\n{run_result['stderr']}")
        log_tail = read_text(os.path.join(work_dir, "TrigrsLog.txt")).splitlines()[-20:]
        if log_tail:
            print("  TrigrsLog.txt (last lines):")
            for line in log_tail:
                print(f"    {line}")
        return 1

    # Step 5: Validate outputs
    print("[5/5] Validating outputs...")
    validation = validate_outputs(work_dir, tr_info)
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
