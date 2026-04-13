#!/usr/bin/env python3
"""
run_dumux.py — Build and execute a DuMux simulation.

Pipeline stage: s4 (Build & Execute)
Pattern: validate → process → validate

Handles:
  1. Building the DuMux executable with CMake/Make
  2. Running the simulation with parameter file
  3. Monitoring output and capturing results
  4. Post-run validation of output files

Usage:
    python run_dumux.py \\
        --source_dir /path/to/dumux/source \\
        --build_dir /path/to/build \\
        --target example_1ptracer \\
        --params params.input \\
        --overrides "Problem.Name=myrun TimeLoop.TEnd=10000"
"""

import argparse
import json
import os
import subprocess
import sys
import time
import glob
from pathlib import Path

# ─── Constants ────────────────────────────────────────────────────────────────
DEFAULT_BUILD_TYPE = "Release"
DEFAULT_CXX_FLAGS = "-O3 -DNDEBUG"
DEFAULT_TIMEOUT = 600  # seconds (10 minutes)

# ─── Validation ──────────────────────────────────────────────────────────────

def validate_inputs(
    source_dir: str,
    build_dir: str,
    target: str,
    params_file: str,
) -> dict:
    """Validate build environment and input files.

    Returns:
        dict with valid, errors, warnings, metadata
    """
    result = {"valid": True, "errors": [], "warnings": [], "metadata": {}}

    # Check source directory
    if not os.path.isdir(source_dir):
        result["valid"] = False
        result["errors"].append(f"Source directory not found: {source_dir}")
        return result

    # Check for CMakeLists.txt
    cmake_file = os.path.join(source_dir, "CMakeLists.txt")
    if not os.path.isfile(cmake_file):
        result["valid"] = False
        result["errors"].append(f"CMakeLists.txt not found in {source_dir}")

    # Check for dune.module (DuMux-specific)
    dune_module = os.path.join(source_dir, "dune.module")
    if os.path.isfile(dune_module):
        result["metadata"]["has_dune_module"] = True
        with open(dune_module) as f:
            for line in f:
                if line.startswith("Version:"):
                    result["metadata"]["version"] = line.split(":")[1].strip()
                if line.startswith("Module:"):
                    result["metadata"]["module"] = line.split(":")[1].strip()
    else:
        result["warnings"].append("No dune.module found — may not be a DUNE/DuMux project")

    # Check parameter file
    if params_file and not os.path.isfile(params_file):
        # Params file might be relative to build target directory
        result["warnings"].append(
            f"Parameter file '{params_file}' not found at current path. "
            "Will search in build/example directories."
        )

    # Check for required tools
    for tool in ["cmake", "make"]:
        try:
            subprocess.run([tool, "--version"], capture_output=True, timeout=10)
        except FileNotFoundError:
            result["valid"] = False
            result["errors"].append(f"Required tool '{tool}' not found in PATH")
        except Exception:
            pass

    return result


def validate_build(build_dir: str, target: str) -> dict:
    """Validate build succeeded."""
    result = {"valid": True, "errors": [], "warnings": []}

    # Check build directory exists
    if not os.path.isdir(build_dir):
        result["valid"] = False
        result["errors"].append(f"Build directory not found: {build_dir}")
        return result

    # Search for the built binary
    binary_paths = []
    for root, dirs, files in os.walk(build_dir):
        for f in files:
            if f == target and os.access(os.path.join(root, f), os.X_OK):
                binary_paths.append(os.path.join(root, f))

    if not binary_paths:
        result["valid"] = False
        result["errors"].append(
            f"Binary '{target}' not found in {build_dir}. Build may have failed."
        )
    else:
        result["binary_path"] = binary_paths[0]
        if len(binary_paths) > 1:
            result["warnings"].append(
                f"Multiple binaries found: {binary_paths}. Using first."
            )

    return result


def validate_output(work_dir: str, problem_name: str) -> dict:
    """Validate simulation produced expected output files."""
    result = {"valid": True, "errors": [], "warnings": [], "metadata": {}}

    # Check for VTK output files
    vtu_files = glob.glob(os.path.join(work_dir, f"{problem_name}*.vtu"))
    vtk_files = glob.glob(os.path.join(work_dir, f"{problem_name}*.vtk"))
    pvd_files = glob.glob(os.path.join(work_dir, f"{problem_name}*.pvd"))

    all_vtk = vtu_files + vtk_files + pvd_files
    result["metadata"]["vtk_files"] = len(all_vtk)
    result["metadata"]["vtu_files"] = vtu_files[:5]  # first 5

    if len(all_vtk) == 0:
        result["warnings"].append(
            f"No VTK output files found matching '{problem_name}*' in {work_dir}. "
            "Check Problem.Name parameter and output directory."
        )
    else:
        # Check file sizes
        total_size = sum(os.path.getsize(f) for f in all_vtk)
        result["metadata"]["total_output_size_bytes"] = total_size

        if total_size == 0:
            result["valid"] = False
            result["errors"].append("VTK output files are empty (0 bytes)")
        elif total_size < 100:
            result["warnings"].append(
                f"VTK output very small ({total_size} bytes). May contain no data."
            )

    return result


# ─── Build Functions ─────────────────────────────────────────────────────────

def configure_cmake(
    source_dir: str,
    build_dir: str,
    build_type: str = DEFAULT_BUILD_TYPE,
    extra_cmake_args: list = None,
) -> dict:
    """Run cmake configuration step."""
    os.makedirs(build_dir, exist_ok=True)

    cmd = [
        "cmake",
        source_dir,
        f"-DCMAKE_BUILD_TYPE={build_type}",
    ]
    if extra_cmake_args:
        cmd.extend(extra_cmake_args)

    print(f"  CMake command: {' '.join(cmd)}")
    print(f"  Build directory: {build_dir}")

    try:
        proc = subprocess.run(
            cmd,
            cwd=build_dir,
            capture_output=True,
            text=True,
            timeout=300,
        )
        return {
            "success": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": proc.stdout[-2000:] if proc.stdout else "",
            "stderr": proc.stderr[-2000:] if proc.stderr else "",
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "returncode": -1, "stderr": "CMake timed out (300s)"}
    except Exception as e:
        return {"success": False, "returncode": -1, "stderr": str(e)}


def build_target(build_dir: str, target: str, n_jobs: int = 4) -> dict:
    """Build a specific target with make."""
    cmd = ["make", "-j", str(n_jobs), target]
    print(f"  Make command: {' '.join(cmd)}")

    try:
        proc = subprocess.run(
            cmd,
            cwd=build_dir,
            capture_output=True,
            text=True,
            timeout=600,
        )
        return {
            "success": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": proc.stdout[-2000:] if proc.stdout else "",
            "stderr": proc.stderr[-2000:] if proc.stderr else "",
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "returncode": -1, "stderr": "Build timed out (600s)"}
    except Exception as e:
        return {"success": False, "returncode": -1, "stderr": str(e)}


# ─── Run Functions ───────────────────────────────────────────────────────────

def run_simulation(
    binary_path: str,
    params_file: str,
    work_dir: str,
    overrides: dict = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict:
    """Run DuMux simulation.

    Args:
        binary_path: Path to compiled executable
        params_file: Path to .input parameter file
        work_dir: Working directory for execution
        overrides: Dict of param overrides {Section.Key: value}
        timeout: Maximum runtime in seconds

    Returns:
        dict with success, returncode, stdout, stderr, runtime_s
    """
    cmd = [binary_path]
    if params_file:
        cmd.append(params_file)

    # Add parameter overrides
    if overrides:
        for key, value in overrides.items():
            cmd.extend([f"-{key}", str(value)])

    print(f"  Run command: {' '.join(cmd)}")
    print(f"  Work dir: {work_dir}")

    start_time = time.time()
    try:
        proc = subprocess.run(
            cmd,
            cwd=work_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        elapsed = time.time() - start_time

        return {
            "success": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": proc.stdout[-3000:] if proc.stdout else "",
            "stderr": proc.stderr[-2000:] if proc.stderr else "",
            "runtime_s": elapsed,
        }
    except subprocess.TimeoutExpired:
        elapsed = time.time() - start_time
        return {
            "success": False,
            "returncode": -1,
            "stderr": f"Simulation timed out after {timeout}s",
            "runtime_s": elapsed,
        }
    except Exception as e:
        elapsed = time.time() - start_time
        return {
            "success": False,
            "returncode": -1,
            "stderr": str(e),
            "runtime_s": elapsed,
        }


def parse_newton_output(stdout: str) -> dict:
    """Parse DuMux Newton solver output for convergence info."""
    info = {
        "time_steps": 0,
        "newton_iterations_total": 0,
        "convergence_failures": 0,
        "final_time": None,
    }

    for line in stdout.split("\n"):
        line_stripped = line.strip()
        if "Time step" in line_stripped:
            info["time_steps"] += 1
        if "Newton iteration" in line_stripped:
            info["newton_iterations_total"] += 1
        if "convergence" in line_stripped.lower() and "fail" in line_stripped.lower():
            info["convergence_failures"] += 1

    return info


# ─── Main Pipeline ───────────────────────────────────────────────────────────

def process(
    source_dir: str,
    build_dir: str,
    target: str,
    params_file: str,
    overrides_str: str = "",
    build_type: str = DEFAULT_BUILD_TYPE,
    skip_build: bool = False,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict:
    """Full build-and-run pipeline: validate → build → run → validate."""
    summary = {
        "status": "failed",
        "source_dir": source_dir,
        "build_dir": build_dir,
        "target": target,
    }

    # ── Validate inputs ──
    print("=== Validating inputs ===")
    input_val = validate_inputs(source_dir, build_dir, target, params_file)
    for w in input_val["warnings"]:
        print(f"  WARNING: {w}")
    if not input_val["valid"]:
        for e in input_val["errors"]:
            print(f"  ERROR: {e}")
        summary["errors"] = input_val["errors"]
        return summary
    summary["metadata"] = input_val["metadata"]

    if not skip_build:
        # ── Configure ──
        print("\n=== Configuring with CMake ===")
        cmake_result = configure_cmake(source_dir, build_dir, build_type)
        if not cmake_result["success"]:
            print(f"  CMake FAILED (rc={cmake_result['returncode']})")
            print(f"  stderr: {cmake_result['stderr'][:500]}")
            summary["cmake_error"] = cmake_result["stderr"][:1000]
            summary["status"] = "cmake_failed"
            return summary
        print("  CMake configuration: OK")

        # ── Build ──
        print("\n=== Building target ===")
        build_result = build_target(build_dir, target)
        if not build_result["success"]:
            print(f"  Build FAILED (rc={build_result['returncode']})")
            print(f"  stderr: {build_result['stderr'][:500]}")
            summary["build_error"] = build_result["stderr"][:1000]
            summary["status"] = "build_failed"
            return summary
        print("  Build: OK")

    # ── Locate binary ──
    build_val = validate_build(build_dir, target)
    if not build_val["valid"]:
        for e in build_val["errors"]:
            print(f"  ERROR: {e}")
        summary["errors"] = build_val["errors"]
        summary["status"] = "binary_not_found"
        return summary

    binary_path = build_val["binary_path"]
    summary["binary_path"] = binary_path
    print(f"  Binary found: {binary_path}")

    # Resolve params file path
    binary_dir = os.path.dirname(binary_path)
    if params_file and not os.path.isfile(params_file):
        alt_path = os.path.join(binary_dir, params_file)
        if os.path.isfile(alt_path):
            params_file = alt_path
        else:
            # Search in source examples
            for root, dirs, files in os.walk(source_dir):
                if os.path.basename(params_file) in files:
                    params_file = os.path.join(root, os.path.basename(params_file))
                    break

    # Parse overrides
    overrides = {}
    if overrides_str:
        for pair in overrides_str.split():
            if "=" in pair:
                k, v = pair.split("=", 1)
                overrides[k] = v

    # ── Run simulation ──
    print("\n=== Running simulation ===")
    work_dir = binary_dir
    run_result = run_simulation(
        binary_path, params_file, work_dir, overrides, timeout
    )

    summary["runtime_s"] = run_result["runtime_s"]
    summary["test_command"] = f"{binary_path} {params_file}"

    if not run_result["success"]:
        print(f"  Simulation FAILED (rc={run_result['returncode']})")
        print(f"  stderr: {run_result['stderr'][:500]}")
        summary["run_error"] = run_result["stderr"][:1000]
        summary["test_output"] = run_result["stderr"][:500]
        summary["status"] = "run_failed"
        return summary

    print(f"  Simulation completed in {run_result['runtime_s']:.1f}s")
    summary["test_output"] = run_result["stdout"][:500]

    # Parse Newton info
    newton_info = parse_newton_output(run_result["stdout"])
    summary["newton_info"] = newton_info
    print(f"  Time steps: {newton_info['time_steps']}")
    print(f"  Newton iterations: {newton_info['newton_iterations_total']}")

    # ── Validate output ──
    print("\n=== Validating output ===")
    problem_name = overrides.get("Problem.Name", "")
    if not problem_name and params_file:
        # Try to extract from params file
        try:
            with open(params_file) as f:
                for line in f:
                    if "Name" in line and "=" in line and not line.strip().startswith("#"):
                        problem_name = line.split("=")[1].strip()
                        break
        except Exception:
            problem_name = target

    output_val = validate_output(work_dir, problem_name)
    for w in output_val["warnings"]:
        print(f"  WARNING: {w}")
    summary["output_metadata"] = output_val["metadata"]

    if output_val["valid"]:
        summary["status"] = "completed"
        print("  Output validation: OK")
    else:
        for e in output_val["errors"]:
            print(f"  ERROR: {e}")
        summary["status"] = "output_invalid"

    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Build and run a DuMux simulation"
    )
    parser.add_argument("--source_dir", required=True, help="DuMux source directory")
    parser.add_argument("--build_dir", required=True, help="Build directory")
    parser.add_argument("--target", required=True, help="Build target name")
    parser.add_argument("--params", default="", help="Parameter .input file")
    parser.add_argument("--overrides", default="", help="Parameter overrides: Key=val ...")
    parser.add_argument("--build_type", default=DEFAULT_BUILD_TYPE)
    parser.add_argument("--skip_build", action="store_true", help="Skip build step")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    args = parser.parse_args()

    result = process(
        source_dir=args.source_dir,
        build_dir=args.build_dir,
        target=args.target,
        params_file=args.params,
        overrides_str=args.overrides,
        build_type=args.build_type,
        skip_build=args.skip_build,
        timeout=args.timeout,
    )

    print(f"\n{'='*60}")
    print(f"Status: {result['status']}")
    if result.get("binary_path"):
        print(f"Binary: {result['binary_path']}")
    if result.get("runtime_s"):
        print(f"Runtime: {result['runtime_s']:.1f}s")

    if result["status"] != "completed":
        sys.exit(1)


if __name__ == "__main__":
    main()
