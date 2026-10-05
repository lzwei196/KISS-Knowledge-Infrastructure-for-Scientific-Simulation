#!/usr/bin/env python3
"""
run_hydrotrend.py

Builds (if needed) and executes the HydroTrend model binary.

Pipeline:
  1. Preflight checks (source exists, input files present, build tools available)
  2. Build with CMake if binary not found
  3. Execute hydrotrend with specified input/output directories
  4. Validate output files exist and contain data
  5. Report status as JSON

Usage:
    python run_hydrotrend.py \\
        --source-dir /path/to/hydrotrend/source/repo \\
        --in-dir ./input \\
        --out-dir ./output \\
        --prefix HYDRO \\
        --timeout 3600

    python run_hydrotrend.py \\
        --binary /path/to/hydrotrend \\
        --in-dir ./input \\
        --out-dir ./output \\
        --prefix HYDRO
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time

# Server default binary (same as preflight_check.py).
DEFAULT_HYDROTREND_BIN = "KISSPATH_KI_ROOT/HydroTrend/bin/hydrotrend"

# HydroTrend keeps file paths in fixed C buffers: the input dir goes through
# sprintf(dummystring[100], "%s/%s%d", in_dir, prefix, epoch) in
# hydroreadhypsom.c and hydroreadearthquake.c; the output dir through
# directory[100] and startname[80] (dir + "/" + prefix) in hydrotrend_irf.c.
# Longer paths overflow and crash the model (rc 1 / -11).
_IN_BUF = 100
_STARTNAME_BUF = 80
_LAPSE_LUT = "HYDRO_PROGRAM_FILES/HYDRO_LAPSERATE.LUT"   # opened relative to cwd


def _n_epochs(in_file):
    try:
        with open(in_file, "r", errors="replace") as f:
            return max(1, int(f.readlines()[3].split()[0]))
    except (OSError, IndexError, ValueError):
        return 1


def _first_number(line):
    tok = line.split()
    try:
        return float(tok[0]) if tok else None
    except ValueError:
        return None


def _lapse_lut_use(in_file):
    """Does HYDRO.IN ask for the lapse-rate lookup table (lapse rate -9999)?

    Returns "yes" (epoch 1 lapse rate, line 24, is numerically -9999),
    "maybe" (several epochs and some later line starts with -9999: later
    epoch blocks have no fixed line numbers, and -9999 is also the flag
    value of another field), or "no".
    """
    try:
        with open(in_file, "r", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return "no"
    if len(lines) > 23 and _first_number(lines[23]) == -9999:
        return "yes"
    if _n_epochs(in_file) > 1 and any(_first_number(l) == -9999 for l in lines[24:]):
        return "maybe"
    return "no"


def _avoid_in_file_overrun(in_arg, prefix):
    """Work around an engine heap bug: hydrotrend_irf.c allocates
    strlen(in_dir) + 1 + strlen(prefix) + 3 bytes for "<in_dir>/<prefix>.IN"
    (no room for the NUL).  When that size n is a malloc usable size
    (n % 16 == 8, n >= 24) the NUL lands in the next chunk and glibc aborts
    ("malloc(): invalid next size", rc -6).  Add a harmless "./" (or "/.")
    so the size moves off that value; the directory is the same."""
    n = len(in_arg.encode()) + 1 + len(prefix.encode()) + 3
    if n >= 24 and n % 16 == 8:
        return in_arg + "/." if os.path.isabs(in_arg) else "./" + in_arg
    return in_arg


def resolve_binary(explicit=None):
    """--binary -> $HYDROTREND_BIN -> server default. Invalid explicit/env -> error.
    Returns (path or None, error message or None, source)."""
    for src, val in (("--binary", explicit), ("$HYDROTREND_BIN", os.environ.get("HYDROTREND_BIN"))):
        if val is not None:
            path = (shutil.which(val) if os.sep not in val else val) if val else None
            if path and os.path.isfile(path) and os.access(path, os.X_OK):
                return os.path.abspath(path), None, src
            return None, f"HydroTrend binary from {src} not found or not executable: {val!r}", src
    if os.path.isfile(DEFAULT_HYDROTREND_BIN) and os.access(DEFAULT_HYDROTREND_BIN, os.X_OK):
        return DEFAULT_HYDROTREND_BIN, None, "server default"
    return None, None, None


def plan_paths(in_dir, out_dir, prefix):
    """Short paths for the model: run with cwd=out_dir and --out-dir=., and an
    input dir relative to out_dir (absolute if that is shorter).
    Returns (in_arg, out_arg, cwd) or raises ValueError if no safe form exists."""
    # Physical paths: the model's cwd follows symlinks, so a relative path
    # must be computed between the resolved dirs.
    out_abs = os.path.realpath(out_dir)
    in_abs = os.path.realpath(in_dir)
    in_file = os.path.join(in_abs, f"{prefix}.IN")
    epoch_digits = len(str(_n_epochs(in_file) - 1))
    rel = os.path.relpath(in_abs, out_abs)
    in_arg = min((rel, in_abs), key=lambda p: len(p.encode()))
    in_arg = _avoid_in_file_overrun(in_arg, prefix)
    need_in = (len(in_arg.encode()) + 1 + len(prefix.encode()) + epoch_digits + 1)
    if need_in > _IN_BUF:
        raise ValueError(
            f"input dir path too long for HydroTrend's {_IN_BUF}-byte buffer even as "
            f"{in_arg!r} ({need_in} bytes incl. prefix, epoch and NUL); use a shorter "
            "path or put the inputs in/near the output dir")
    need_start = len("./".encode()) + len(prefix.encode()) + 1
    if need_start > _STARTNAME_BUF:
        raise ValueError(f"prefix too long for HydroTrend's {_STARTNAME_BUF}-byte buffer: {prefix!r}")
    return in_arg, ".", out_abs


# --------------------------------------------------------------------------- #
#  Validation
# --------------------------------------------------------------------------- #
def validate_inputs(args):
    """Preflight checks before build and execution."""
    errors = []
    warnings = []

    # Check input directory
    if not os.path.isdir(args.in_dir):
        errors.append(f"Input directory not found: {args.in_dir}")
    else:
        # Check for required input files
        in_file = os.path.join(args.in_dir, f"{args.prefix}.IN")
        hyps_file = os.path.join(args.in_dir, f"{args.prefix}0.HYPS")

        if not os.path.isfile(in_file):
            errors.append(f"Main input file not found: {in_file}")
        if not os.path.isfile(hyps_file):
            errors.append(f"Hypsometry file not found: {hyps_file}")

        # Check ASCII output flag
        if os.path.isfile(in_file):
            with open(in_file, "r") as f:
                lines = f.readlines()
                if len(lines) >= 2:
                    flag = lines[1].strip().split()[0].upper()
                    if flag != "ON":
                        warnings.append(
                            f"ASCII output flag is '{flag}' (line 2). "
                            "Set to ON for ASCII output files."
                        )

    # Check source (binary selection is checked in main: --binary ->
    # $HYDROTREND_BIN -> --source-dir build -> server default)
    if args.source_dir and not os.path.isdir(args.source_dir):
        errors.append(f"Source directory not found: {args.source_dir}")

    if errors:
        return {"status": "error", "errors": errors, "warnings": warnings}
    return {"status": "ok", "warnings": warnings}


def validate_outputs(out_dir, prefix):
    """Check that output files were created and have content."""
    results = {}
    expected_files = [
        (f"{prefix}ASCII.Q", "discharge"),
        (f"{prefix}ASCII.QS", "suspended_sediment"),
        (f"{prefix}ASCII.QB", "bedload"),
        (f"{prefix}ASCII.CS", "concentration"),
        (f"{prefix}ASCII.VWD", "velocity_width_depth"),
    ]

    for filename, desc in expected_files:
        filepath = os.path.join(out_dir, filename)
        if os.path.isfile(filepath):
            size = os.path.getsize(filepath)
            # Count lines
            with open(filepath, "r") as f:
                n_lines = sum(1 for _ in f)
            results[desc] = {
                "file": filepath,
                "size_bytes": size,
                "n_lines": n_lines,
                "exists": True,
            }
        else:
            results[desc] = {"file": filepath, "exists": False}

    return results


# --------------------------------------------------------------------------- #
#  Build
# --------------------------------------------------------------------------- #
def build_hydrotrend(source_dir, build_dir=None):
    """
    Build HydroTrend using CMake.

    Returns path to built binary or raises on failure.
    """
    if build_dir is None:
        build_dir = os.path.join(source_dir, "_build")

    os.makedirs(build_dir, exist_ok=True)

    # CMake configure
    print("Configuring with CMake...", file=sys.stderr)
    cmake_cmd = [
        "cmake", source_dir,
        "-DCMAKE_BUILD_TYPE=Release",
    ]

    result = subprocess.run(
        cmake_cmd,
        cwd=build_dir,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        return {
            "status": "error",
            "stage": "cmake_configure",
            "stderr": result.stderr[-1000:],
            "returncode": result.returncode,
        }

    # Make
    print("Building...", file=sys.stderr)
    make_cmd = ["make", f"-j{os.cpu_count() or 2}"]
    result = subprocess.run(
        make_cmd,
        cwd=build_dir,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        return {
            "status": "error",
            "stage": "make",
            "stderr": result.stderr[-1000:],
            "returncode": result.returncode,
        }

    # Find binary
    binary = os.path.join(build_dir, "hydrotrend")
    if not os.path.isfile(binary):
        # Try alternate locations
        for candidate in ["hydrotrend", "bin/hydrotrend", "src/hydrotrend"]:
            path = os.path.join(build_dir, candidate)
            if os.path.isfile(path):
                binary = path
                break

    if not os.path.isfile(binary):
        return {
            "status": "error",
            "stage": "find_binary",
            "message": f"Binary not found in {build_dir}",
        }

    return {"status": "success", "binary": binary}


# --------------------------------------------------------------------------- #
#  Execution
# --------------------------------------------------------------------------- #
def run_hydrotrend(binary, in_dir, out_dir, prefix, timeout=3600,
                   verbose=False):
    """
    Execute HydroTrend.

    The model keeps paths in fixed C buffers, so it is run from inside the
    output dir (cwd=out_dir, --out-dir=.) with a short input path (relative to
    the output dir).  Model results do not depend on this.

    Returns execution result with stdout/stderr and timing.
    """
    os.makedirs(out_dir, exist_ok=True)
    binary = os.path.abspath(binary)

    in_file = os.path.join(os.path.abspath(in_dir), f"{prefix}.IN")
    lut = _lapse_lut_use(in_file)
    if lut != "no":
        # The engine opens HYDRO_PROGRAM_FILES/HYDRO_LAPSERATE.LUT relative to
        # its cwd.  Keep the caller's cwd (old behaviour) so the same LUT is
        # used; this needs the given paths to fit the buffers.
        caller_lut = os.path.join(os.getcwd(), _LAPSE_LUT)
        if not os.path.isfile(caller_lut):
            if lut == "yes":
                return {"status": "error",
                        "message": f"{prefix}.IN asks for the lapse-rate table (-9999) but "
                                   f"{caller_lut} does not exist (HydroTrend would exit)"}
            print(f"WARNING: {prefix}.IN may ask for the lapse-rate table (-9999 in a "
                  f"later epoch); {caller_lut} does not exist", file=sys.stderr)
        in_arg, out_arg, cwd = _avoid_in_file_overrun(in_dir, prefix), out_dir, None
        epoch_digits = len(str(_n_epochs(in_file) - 1))
        if (len(out_arg.encode()) + 1 + len(prefix.encode()) + 1 > _STARTNAME_BUF
                or len(out_arg.encode()) + 1 + 1 > 100
                or len(in_arg.encode()) + 1 + len(prefix.encode()) + epoch_digits + 1 > _IN_BUF):
            return {"status": "error",
                    "message": "lapse-rate table run needs the caller's cwd, but the given "
                               "in/out paths are too long for HydroTrend's buffers; use "
                               "shorter (relative) paths"}
    else:
        try:
            in_arg, out_arg, cwd = plan_paths(in_dir, out_dir, prefix)
        except ValueError as e:
            return {"status": "error", "message": str(e)}

    cmd = [
        binary,
        f"--in-dir={in_arg}",
        f"--out-dir={out_arg}",
        f"--prefix={prefix}",
    ]
    if verbose:
        cmd.append("--verbose")

    print(f"Running: {' '.join(cmd)} (cwd={cwd or os.getcwd()})", file=sys.stderr)
    start_time = time.time()

    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        elapsed = time.time() - start_time

        return {
            "status": "success" if result.returncode == 0 else "error",
            "returncode": result.returncode,
            "stdout": result.stdout[-2000:] if result.stdout else "",
            "stderr": result.stderr[-2000:] if result.stderr else "",
            "elapsed_seconds": round(elapsed, 2),
        }
    except subprocess.TimeoutExpired:
        return {
            "status": "error",
            "message": f"Execution timed out after {timeout}s",
        }
    except FileNotFoundError:
        return {
            "status": "error",
            "message": f"Binary not found: {binary}",
        }


# --------------------------------------------------------------------------- #
#  Main
# --------------------------------------------------------------------------- #
def main():
    parser = argparse.ArgumentParser(
        description="Build and run HydroTrend model"
    )
    parser.add_argument("--binary", default=None,
                        help="Path to pre-built hydrotrend binary (default: $HYDROTREND_BIN, "
                             "then --source-dir build, then the server binary)")
    parser.add_argument("--source-dir", default=None,
                        help="Path to HydroTrend source for building")
    parser.add_argument("--build-dir", default=None,
                        help="Build directory (default: source/_build)")
    parser.add_argument("--in-dir", required=True,
                        help="Input directory containing PREFIX.IN")
    parser.add_argument("--out-dir", required=True,
                        help="Output directory for results")
    parser.add_argument("--prefix", default="HYDRO",
                        help="File prefix (default: HYDRO)")
    parser.add_argument("--timeout", type=int, default=3600,
                        help="Execution timeout in seconds")
    parser.add_argument("--verbose", action="store_true",
                        help="Enable verbose output")
    parser.add_argument("--skip-build", action="store_true",
                        help="Skip build step even if binary missing")
    args = parser.parse_args()

    # Step 1: Validate inputs
    check = validate_inputs(args)
    if check["status"] == "error":
        print(json.dumps(check, indent=2))
        sys.exit(1)
    if check.get("warnings"):
        for w in check["warnings"]:
            print(f"WARNING: {w}", file=sys.stderr)

    # Step 2: Determine or build binary:
    # --binary -> $HYDROTREND_BIN (invalid -> error, no fall-through)
    # -> --source-dir build -> server default
    build_result = None
    explicit = args.binary if args.binary is not None else os.environ.get("HYDROTREND_BIN")
    binary, err, src = (resolve_binary(args.binary) if explicit is not None
                        else (None, None, None))
    if err:
        print(json.dumps({"status": "error", "message": err}, indent=2))
        sys.exit(1)
    if binary is None and not (args.source_dir and not args.skip_build):
        binary, err, src = resolve_binary(None)

    if binary:
        print(f"Using existing binary: {binary} ({src})", file=sys.stderr)
    elif args.source_dir and not args.skip_build:
        print("Building HydroTrend from source...", file=sys.stderr)
        build_result = build_hydrotrend(args.source_dir, args.build_dir)
        if build_result["status"] != "success":
            print(json.dumps(build_result, indent=2))
            sys.exit(1)
        binary = build_result["binary"]
        print(f"Built binary: {binary}", file=sys.stderr)
    else:
        print(json.dumps({
            "status": "error",
            "message": "No binary available and build skipped",
        }, indent=2))
        sys.exit(1)

    # Step 3: Run model
    exec_result = run_hydrotrend(
        binary, args.in_dir, args.out_dir, args.prefix,
        args.timeout, args.verbose
    )

    # Step 4: Validate outputs
    output_check = {}
    if exec_result["status"] == "success":
        output_check = validate_outputs(args.out_dir, args.prefix)

    # Final report
    report = {
        "status": exec_result["status"],
        "binary": binary,
        "build": build_result,
        "execution": exec_result,
        "outputs": output_check,
    }
    print(json.dumps(report, indent=2))

    if exec_result["status"] != "success":
        sys.exit(1)


if __name__ == "__main__":
    main()
