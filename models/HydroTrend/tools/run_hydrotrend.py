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

    # Check binary or source
    if args.binary and not os.path.isfile(args.binary):
        if not args.source_dir:
            errors.append(
                f"Binary not found: {args.binary}. "
                "Provide --source-dir to build."
            )

    if args.source_dir and not os.path.isdir(args.source_dir):
        errors.append(f"Source directory not found: {args.source_dir}")

    if not args.binary and not args.source_dir:
        errors.append("Provide either --binary or --source-dir")

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

    Returns execution result with stdout/stderr and timing.
    """
    os.makedirs(out_dir, exist_ok=True)

    cmd = [
        binary,
        f"--in-dir={in_dir}",
        f"--out-dir={out_dir}",
        f"--prefix={prefix}",
    ]
    if verbose:
        cmd.append("--verbose")

    print(f"Running: {' '.join(cmd)}", file=sys.stderr)
    start_time = time.time()

    try:
        result = subprocess.run(
            cmd,
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
                        help="Path to pre-built hydrotrend binary")
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

    # Step 2: Determine or build binary
    binary = args.binary
    build_result = None

    if binary and os.path.isfile(binary):
        print(f"Using existing binary: {binary}", file=sys.stderr)
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
