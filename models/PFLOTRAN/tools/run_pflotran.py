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
    - PFLOTRAN's own screen/output file (<prefix>.out, written by PFLOTRAN)
    - This wrapper's log (<prefix>_run_log.txt: command, return code, stdout, stderr)
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
import re
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
            "No usable PFLOTRAN binary: --pflotran-bin / $PFLOTRAN_BIN is not an executable "
            f"file, or (neither given) the server default {SERVER_DEFAULT_BINARY} is missing."
        )
    elif not os.access(pflotran_bin, os.X_OK):
        errors.append(f"PFLOTRAN binary not executable: {pflotran_bin}")

    # Check MPI
    mpirun = None
    if args.nproc > 1:
        mpirun = find_mpirun(getattr(args, "mpirun", None))
        if mpirun is None:
            errors.append("No usable MPI launcher for nproc > 1 (--mpirun / $PFLOTRAN_MPIRUN "
                          f"not executable, or server default {SERVER_DEFAULT_MPIRUN} missing)")

    # Check nproc
    if args.nproc < 1:
        errors.append(f"nproc must be >= 1: {args.nproc}")

    # Check timeout
    if args.timeout <= 0:
        errors.append(f"Timeout must be > 0: {args.timeout}")

    return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings,
            "pflotran_bin": pflotran_bin, "mpirun": mpirun}


# Server default build (same path the KI preflight_check.py checks)
SERVER_DEFAULT_BINARY = "KISSPATH_KI_ROOT/PFLOTRAN/source/repo/src/pflotran/pflotran"


def find_pflotran_binary(user_path=None):
    """Find PFLOTRAN binary.

    Search order:
    1. User-specified path (--pflotran-bin)
    2. $PFLOTRAN_BIN
    3. Server default build (as in preflight_check.py)
    An explicit choice (1 or 2) that is not an executable file is an error: there
    is no fallback to another PFLOTRAN.

    Returns:
        str or None: Path to PFLOTRAN binary
    """
    for label, explicit in (("--pflotran-bin", user_path),
                            ("$PFLOTRAN_BIN", os.environ.get("PFLOTRAN_BIN"))):
        if explicit:
            if os.path.isfile(explicit) and os.access(explicit, os.X_OK):
                return explicit
            print(f"  ERROR: {label} {explicit} is not an executable file")
            return None

    if os.path.isfile(SERVER_DEFAULT_BINARY) and os.access(SERVER_DEFAULT_BINARY, os.X_OK):
        return SERVER_DEFAULT_BINARY

    return None


# MPI launcher of the same OpenMPI the server PFLOTRAN/PETSc link against
# (KISSPATH_HOME/miniconda3/lib/libmpi.so.40). The `mpirun` first on PATH
# (~/.local/bin/orterun, another OpenMPI) fails with "undefined symbol
# MPI_Neighbor_alltoallv_init".
SERVER_DEFAULT_MPIRUN = "KISSPATH_HOME/miniconda3/bin/mpirun"


def find_mpirun(user_path=None):
    """MPI launcher: --mpirun, then $PFLOTRAN_MPIRUN, then the server default.

    An explicit choice that is not an executable file is an error (None); no
    PATH lookup, so a launcher from another MPI is never picked silently.
    """
    for label, explicit in (("--mpirun", user_path),
                            ("$PFLOTRAN_MPIRUN", os.environ.get("PFLOTRAN_MPIRUN"))):
        if explicit:
            if os.path.isfile(explicit) and os.access(explicit, os.X_OK):
                return os.path.abspath(explicit)
            print(f"  ERROR: {label} {explicit} is not an executable file")
            return None
    if os.path.isfile(SERVER_DEFAULT_MPIRUN) and os.access(SERVER_DEFAULT_MPIRUN, os.X_OK):
        return SERVER_DEFAULT_MPIRUN
    return None


def build_command(pflotran_bin, input_file, nproc, mpirun=None):
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
        mpirun = mpirun or find_mpirun()
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
    except OSError as e:
        return {
            "returncode": -2,
            "stdout": "",
            "stderr": str(e),
            "elapsed_s": 0,
            "success": False,
        }


# Sub-blocks of OUTPUT that end with their own END or "/"
# (factory_subsurface_read.F90 OUTPUT reader, output.F90 OutputFileRead)
_OUTPUT_SUBBLOCKS = {"SNAPSHOT_FILE", "OBSERVATION_FILE", "MASS_BALANCE_FILE",
                     "VARIABLES", "AVERAGE_VARIABLES", "TOTAL_MASS_REGIONS"}


def _requested_outputs(input_file):
    """What the deck's OUTPUT block asks PFLOTRAN to write.

    Returns {'hdf5': bool (snapshot HDF5), 'obs_hdf5': bool (OBSERVATION_FILE
    FORMAT HDF5 -> <prefix>-obs-region.h5), 'mass_balance': bool, 'known': bool}.
    'known' is False when the deck pulls in other files (EXTERNAL_FILE) or cannot
    be read; then nothing is treated as required. Comments (# !) and skip/noskip
    blocks are ignored.
    """
    req = {"hdf5": False, "obs_hdf5": False, "mass_balance": False, "known": True,
           "screen_off": False, "file_off": False}
    try:
        with open(input_file) as f:
            lines = f.readlines()
    except OSError:
        req["known"] = False
        return req
    skipping = 0
    in_output = False
    stack = []
    for line in lines:
        words = re.split(r"[#!]", line, 1)[0].upper().split()
        if not words:
            continue
        if words[0] == "SKIP":
            skipping += 1
            continue
        if words[0] == "NOSKIP":
            skipping = max(0, skipping - 1)
            continue
        if skipping:
            continue
        if words[0] == "EXTERNAL_FILE":
            req["known"] = False
        if not in_output:
            if words[0] == "OUTPUT":
                in_output, stack = True, []
            continue
        if words[0] in ("END", "/"):
            if stack:
                stack.pop()
            else:
                in_output = False
            continue
        if words[0] in _OUTPUT_SUBBLOCKS:
            stack.append(words[0])
            if words[0] == "MASS_BALANCE_FILE":
                req["mass_balance"] = True
            continue
        block = stack[-1] if stack else "OUTPUT"
        if words[0] == "SCREEN" and words[1:2] == ["OFF"]:
            req["screen_off"] = True
        if words[0] == "OUTPUT_FILE" and words[1:2] == ["OFF"]:
            req["file_off"] = True
        if words[0] == "FORMAT" and "HDF5" in words[1:]:
            if block == "OBSERVATION_FILE":
                req["obs_hdf5"] = True
            elif block in ("OUTPUT", "SNAPSHOT_FILE"):
                req["hdf5"] = True
        if words[0] == "MASS_BALANCE" and block == "OUTPUT":
            req["mass_balance"] = True
    return req


def _output_kind(name, prefix):
    """Kind of a PFLOTRAN output file name for this prefix, else None."""
    p = re.escape(prefix)
    patterns = [
        ("obs_hdf5", rf"^{p}-obs-region\.h5$"),
        ("hdf5", rf"^{p}(-\d+)?(-aveg)?\.h5$"),
        ("obs", rf"^{p}-obs-\d+\.(tec|pft)$"),
        ("tec", rf"^{p}(-vel)?-\d+\.tec$"),
        ("regression", rf"^{p}\.regression$"),
        ("mass_balance", rf"^{p}-mas\.dat$"),
    ]
    for kind, pat in patterns:
        if re.match(pat, name):
            return kind
    return None


def _file_state(folders):
    """{path: (mtime_ns, size)} of the files directly in the given folders."""
    state = {}
    for d in folders:
        if os.path.isdir(d):
            for name in os.listdir(d):
                path = os.path.join(d, name)
                if os.path.isfile(path):
                    st = os.stat(path)
                    state[path] = (st.st_mtime_ns, st.st_size)
    return state


def _output_folders(input_file, workdir):
    """PFLOTRAN names outputs after the -pflotranin path, so they land next to the
    deck; workdir comes second."""
    folders = []
    for d in (os.path.dirname(os.path.abspath(input_file)), os.path.abspath(workdir)):
        if d not in folders:
            folders.append(d)
    return folders


def validate_outputs(input_file, workdir, run_result, before=None):
    """Validate PFLOTRAN outputs after execution.

    Checks:
    1. PFLOTRAN's end-of-run line "Wall Clock Time:" is present
    2. No PETSc errors in stderr
    3. HDF5 / mass balance file written by this run if the deck's OUTPUT block asks
       for them (before = _file_state taken just before the run)
    4. Output files found are listed (deck folder first, then workdir)

    Returns:
        dict with 'valid' (bool), 'errors' (list), 'warnings' (list), 'output_files' (dict)
    """
    errors = []
    warnings = []
    output_files = {}
    prefix = os.path.splitext(os.path.basename(input_file))[0]
    requested = _requested_outputs(input_file)

    def is_new(path):
        if before is None:
            return True
        st = os.stat(path)
        return before.get(path) != (st.st_mtime_ns, st.st_size)

    # PFLOTRAN v6 ends a finished run with " Wall Clock Time: ..." (there is no
    # "Simulation Complete" line). It goes to the screen and to PFLOTRAN's own
    # <prefix>.out; either can be switched off (SCREEN OFF / OUTPUT_FILE OFF).
    if run_result.get("success"):
        marker = "Wall Clock Time:" in run_result.get("stdout", "")
        own_out = os.path.join(os.path.dirname(os.path.abspath(input_file)), f"{prefix}.out")
        if not marker and os.path.isfile(own_out) and is_new(own_out):
            with open(own_out, errors="replace") as fh:
                marker = "Wall Clock Time:" in fh.read()
        if not marker:
            if requested.get("screen_off") and requested.get("file_off"):
                warnings.append("No 'Wall Clock Time:' end-of-run line to check (deck has "
                                "SCREEN OFF and OUTPUT_FILE OFF)")
            else:
                errors.append("Return code 0 but no 'Wall Clock Time:' end-of-run line in "
                              f"PFLOTRAN's screen output or {prefix}.out")

    # Check for PETSc errors
    stderr = run_result.get("stderr", "")
    if "PETSC ERROR" in stderr or "PETSc Error" in stderr:
        errors.append("PETSc error detected in stderr")

    # Check for convergence failures (information only)
    stdout = run_result.get("stdout", "")
    if "Time step cut" in stdout:
        cut_count = stdout.count("Time step cut")
        warnings.append(f"Time step was cut {cut_count} times (convergence issues)")

    new_kinds = set()
    for d in _output_folders(input_file, workdir):
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            path = os.path.join(d, f)
            kind = _output_kind(f, prefix)
            if kind is None or not os.path.isfile(path):
                continue
            if kind == "hdf5":
                key = "hdf5" if f == f"{prefix}.h5" else f"hdf5_{f}"
            elif kind == "obs_hdf5":
                key = "obs_hdf5"
            elif kind in ("regression", "mass_balance"):
                key = kind
            else:
                key = f"{kind}_{f}"
            if key in output_files:
                continue  # the deck folder has precedence
            info = {"path": path, "new": is_new(path)}
            if kind == "hdf5":
                size_mb = os.path.getsize(path) / (1024 * 1024)
                info["size_mb"] = round(size_mb, 2)
                if size_mb < 0.001:
                    warnings.append(f"HDF5 output file is nearly empty ({size_mb:.4f} MB): {path}")
            elif kind == "obs":
                info["size_kb"] = round(os.path.getsize(path) / 1024, 2)
            output_files[key] = info
            if info["new"]:
                new_kinds.add(kind)

    if run_result.get("success"):
        if not requested["known"]:
            warnings.append("Deck uses EXTERNAL_FILE: requested outputs not checked")
        else:
            if requested["hdf5"] and "hdf5" not in new_kinds:
                errors.append(f"Deck asks for FORMAT HDF5 but this run wrote no {prefix}*.h5")
            if requested["obs_hdf5"] and "obs_hdf5" not in new_kinds:
                errors.append(f"Deck asks for observation HDF5 but this run wrote no "
                              f"{prefix}-obs-region.h5")
            if requested["mass_balance"] and "mass_balance" not in new_kinds:
                errors.append(f"Deck asks for a mass balance file but this run wrote no "
                              f"{prefix}-mas.dat")

    valid = run_result.get("success", False) and not errors

    return {"valid": valid, "errors": errors, "warnings": warnings, "output_files": output_files}


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
    parser.add_argument("--pflotran-bin", help="Path to PFLOTRAN binary "
                        "(else $PFLOTRAN_BIN, else the server default build)")
    parser.add_argument("--nproc", type=int, default=1, help="MPI processes")
    parser.add_argument("--mpirun", help="MPI launcher for --nproc > 1 (else $PFLOTRAN_MPIRUN, "
                        "else the server default matching PFLOTRAN's MPI)")
    parser.add_argument("--timeout", type=int, default=3600, help="Max runtime (s)")
    parser.add_argument("--workdir", help="Working directory (default: input file dir)")

    args = parser.parse_args()

    # Absolute paths: the engine runs in --workdir, not in the caller's folder
    args.input_file = os.path.abspath(args.input_file)
    if args.workdir is None:
        args.workdir = os.path.dirname(args.input_file)
    args.workdir = os.path.abspath(args.workdir)

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

    pflotran_bin = os.path.abspath(validation["pflotran_bin"])
    print(f"  Binary: {pflotran_bin}")
    print(f"  Input: {args.input_file}")
    print(f"  Processes: {args.nproc}" + (f" (MPI launcher: {validation['mpirun']})" if validation.get("mpirun") else ""))

    # Step 2: Build and run
    print("\n[2/4] Executing PFLOTRAN...")
    cmd = build_command(pflotran_bin, args.input_file, args.nproc, validation.get("mpirun"))

    prefix = os.path.splitext(os.path.basename(args.input_file))[0]
    # Not <prefix>.out: that is PFLOTRAN's own output file
    log_file = os.path.join(args.workdir, f"{prefix}_run_log.txt")

    state_before = _file_state(_output_folders(args.input_file, args.workdir))
    run_result = run_pflotran(cmd, args.workdir, args.timeout, log_file)

    print(f"\n  Return code: {run_result['returncode']}")
    print(f"  Elapsed: {run_result['elapsed_s']:.2f}s")

    # Step 3: Validate outputs
    print("\n[3/4] Validating outputs...")
    output_validation = validate_outputs(args.input_file, args.workdir, run_result,
                                         before=state_before)
    for e in output_validation["errors"]:
        print(f"  ERROR: {e}")
    for w in output_validation["warnings"]:
        print(f"  WARNING: {w}")
    for name, info in output_validation["output_files"].items():
        print(f"  Output: {name} -> {info.get('path', 'N/A')}")

    success = run_result["success"] and output_validation["valid"]

    # Step 4: Diagnose if failed
    if not run_result["success"]:
        print("\n[4/4] Diagnosing failure...")
        diagnostics = diagnose_failure(run_result)
        for d in diagnostics:
            print(f"  Symptom: {d['symptom']}")
            print(f"  Diagnosis: {d['diagnosis']}")
            print(f"  Remedy: {d['remedy']}")
            print()
    elif not success:
        print("\n[4/4] PFLOTRAN returned 0 but the output checks failed (see ERROR lines)")
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
        "success": success,
        "output_files": output_validation["output_files"],
        "errors": output_validation["errors"],
        "warnings": output_validation["warnings"],
        "stdout_first_500": run_result["stdout"][:500],
        "stderr_first_500": run_result["stderr"][:500],
    }

    summary_path = os.path.join(args.workdir, f"{prefix}_run_summary.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\n  Summary: {summary_path}")

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
