#!/usr/bin/env python3
"""
run_gifmod.py - Build and execute GIFMod model.

GIFMod is a Qt5 GUI application. This wrapper handles:
  1. Preflight validation of source tree and dependencies
  2. Building GIFMod from source using qmake + make
  3. Verifying the binary was created
  4. (Optional) Running GIFMod with a project file via xvfb for headless execution

CRITICAL NOTES:
  - GIFMod requires Qt5 development libraries
  - LAPACK and BLAS must be installed (liblapack-dev, libblas-dev)
  - OpenMP support (-fopenmp) is required
  - The model is GUI-only; headless execution requires xvfb-run
  - Build produces binary in builds/release/ or builds/debug/

Usage:
    python run_gifmod.py --source-dir /path/to/GIFMod/source/repo --mode build
    python run_gifmod.py --source-dir /path/to/GIFMod/source/repo --mode run \\
        --project model.GIFMod --timeout 3600
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time


def validate_inputs(args):
    """Validate source directory structure and dependencies."""
    errors = []
    warnings = []

    # Check source directory
    if not os.path.isdir(args.source_dir):
        errors.append(f"Source directory not found: {args.source_dir}")
    else:
        pro_file = os.path.join(args.source_dir, "GIFMod.pro")
        if not os.path.isfile(pro_file):
            errors.append(f"GIFMod.pro not found in {args.source_dir}")

        src_dir = os.path.join(args.source_dir, "src", "GUI")
        if not os.path.isdir(src_dir):
            errors.append(f"src/GUI/ directory not found in {args.source_dir}")

    # Check dependencies
    if shutil.which("qmake") is None and shutil.which("qmake-qt5") is None:
        errors.append(
            "qmake not found. Install Qt5 development tools: "
            "sudo apt-get install qt5-default qtbase5-dev"
        )

    if shutil.which("make") is None:
        errors.append("make not found. Install build-essential.")

    # Check LAPACK/BLAS
    lapack_paths = [
        "/usr/lib/liblapack.so",
        "/usr/lib/x86_64-linux-gnu/liblapack.so",
        "/usr/lib/aarch64-linux-gnu/liblapack.so",
    ]
    if not any(os.path.exists(p) for p in lapack_paths):
        try:
            result = subprocess.run(
                ["ldconfig", "-p"], capture_output=True, text=True, timeout=10
            )
            if "liblapack" not in result.stdout:
                warnings.append(
                    "LAPACK library not found. Install: sudo apt-get install liblapack-dev"
                )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            warnings.append("Could not verify LAPACK installation")

    # Check for run mode requirements
    if args.mode == "run":
        if not args.project:
            errors.append("--project required in run mode")
        elif not os.path.isfile(args.project):
            errors.append(f"Project file not found: {args.project}")

        if shutil.which("xvfb-run") is None:
            warnings.append(
                "xvfb-run not found. Headless execution may fail. "
                "Install: sudo apt-get install xvfb"
            )

    if errors:
        print(json.dumps({"status": "error", "errors": errors, "warnings": warnings}))
        sys.exit(1)

    return {"status": "ok", "warnings": warnings}


def build_gifmod(args):
    """Build GIFMod from source."""
    source_dir = args.source_dir
    build_dir = os.path.join(source_dir, "build")

    os.makedirs(build_dir, exist_ok=True)

    # Determine qmake binary
    qmake = "qmake-qt5" if shutil.which("qmake-qt5") else "qmake"

    # Run qmake
    pro_file = os.path.join(source_dir, "GIFMod.pro")
    qmake_cmd = [qmake, pro_file, "CONFIG+=release"]

    print(f"Running: {' '.join(qmake_cmd)}")
    result = subprocess.run(
        qmake_cmd,
        cwd=build_dir,
        capture_output=True,
        text=True,
        timeout=120,
    )

    if result.returncode != 0:
        return {
            "status": "error",
            "stage": "qmake",
            "returncode": result.returncode,
            "stdout": result.stdout[:500],
            "stderr": result.stderr[:500],
        }

    # Run make
    n_jobs = os.cpu_count() or 2
    make_cmd = ["make", f"-j{n_jobs}"]

    print(f"Running: {' '.join(make_cmd)}")
    t0 = time.time()
    result = subprocess.run(
        make_cmd,
        cwd=build_dir,
        capture_output=True,
        text=True,
        timeout=args.timeout,
    )
    build_time = time.time() - t0

    if result.returncode != 0:
        return {
            "status": "error",
            "stage": "make",
            "returncode": result.returncode,
            "stdout": result.stdout[-500:],
            "stderr": result.stderr[-500:],
            "build_time_s": round(build_time, 1),
        }

    # Find binary
    binary_candidates = [
        os.path.join(build_dir, "GIFMod"),
        os.path.join(build_dir, "release", "GIFMod"),
        os.path.join(source_dir, "builds", "release", "GIFMod"),
        os.path.join(build_dir, "GIFMod.exe"),
    ]
    binary_path = None
    for p in binary_candidates:
        if os.path.isfile(p):
            binary_path = p
            break

    if binary_path is None:
        return {
            "status": "error",
            "stage": "binary_search",
            "message": "Build completed but binary not found",
            "searched": binary_candidates,
            "build_time_s": round(build_time, 1),
        }

    return {
        "status": "success",
        "binary_path": binary_path,
        "build_time_s": round(build_time, 1),
        "build_dir": build_dir,
    }


def run_gifmod(args, binary_path):
    """Run GIFMod with a project file (headless via xvfb)."""
    cmd = []

    # Use xvfb-run for headless if available
    if shutil.which("xvfb-run"):
        cmd = ["xvfb-run", "-a", binary_path, args.project]
    else:
        cmd = [binary_path, args.project]

    print(f"Running: {' '.join(cmd)}")
    t0 = time.time()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=args.timeout,
        )
        run_time = time.time() - t0

        return {
            "status": "success" if result.returncode == 0 else "error",
            "returncode": result.returncode,
            "stdout": result.stdout[:500],
            "stderr": result.stderr[:500],
            "run_time_s": round(run_time, 1),
        }
    except subprocess.TimeoutExpired:
        return {
            "status": "error",
            "message": f"Execution timed out after {args.timeout}s",
        }


def validate_outputs(result):
    """Validate build/run results."""
    if result["status"] == "error":
        print(json.dumps(result, indent=2))
        sys.exit(1)
    return result


def main():
    parser = argparse.ArgumentParser(description="Build and run GIFMod")
    parser.add_argument("--source-dir", required=True,
                        help="Path to GIFMod source repository")
    parser.add_argument("--mode", choices=["build", "run", "build-and-run"],
                        default="build", help="Operation mode")
    parser.add_argument("--project", default=None,
                        help="GIFMod project file for run mode")
    parser.add_argument("--timeout", type=int, default=600,
                        help="Timeout in seconds (default: 600)")

    args = parser.parse_args()

    preflight = validate_inputs(args)

    if args.mode in ("build", "build-and-run"):
        result = build_gifmod(args)
        result = validate_outputs(result)

        if args.mode == "build-and-run" and result["status"] == "success":
            run_result = run_gifmod(args, result["binary_path"])
            result["run"] = run_result
            result = validate_outputs(result)
    elif args.mode == "run":
        # Find existing binary
        binary_candidates = [
            os.path.join(args.source_dir, "build", "GIFMod"),
            os.path.join(args.source_dir, "builds", "release", "GIFMod"),
        ]
        binary_path = None
        for p in binary_candidates:
            if os.path.isfile(p):
                binary_path = p
                break

        if binary_path is None:
            print(json.dumps({
                "status": "error",
                "message": "Binary not found. Run with --mode build first.",
            }))
            sys.exit(1)

        result = run_gifmod(args, binary_path)
        result = validate_outputs(result)

    if preflight.get("warnings"):
        result["preflight_warnings"] = preflight["warnings"]

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
