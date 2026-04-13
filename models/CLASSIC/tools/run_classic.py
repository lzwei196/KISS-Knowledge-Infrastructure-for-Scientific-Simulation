#!/usr/bin/env python3
"""
run_classic.py — Compile and execute the CLASSIC model with preflight checks.

This tool:
  1. Validates that all required input files exist
  2. Compiles CLASSIC (if binary not found)
  3. Runs CLASSIC for a specified location
  4. Validates that output files were created
  5. Reports success/failure with diagnostics

Usage:
    python run_classic.py \\
        --source_dir /path/to/classic/source \\
        --job_options configurationFiles/template_job_options_file.txt \\
        --coords "105.23/40.91" \\
        --mode serial

    python run_classic.py \\
        --source_dir /path/to/classic/source \\
        --job_options configurationFiles/template_job_options_file.txt \\
        --coords "0/0/0/0" \\
        --mode parallel --nprocs 4
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path


def validate_inputs(args):
    """Validate input arguments and check prerequisites."""
    errors = []

    if not os.path.isdir(args.source_dir):
        errors.append(f"Source directory not found: {args.source_dir}")

    job_opts_path = os.path.join(args.source_dir, args.job_options)
    if not os.path.isfile(job_opts_path):
        errors.append(f"Job options file not found: {job_opts_path}")

    if args.mode not in ["serial", "parallel"]:
        errors.append(f"--mode must be 'serial' or 'parallel', got {args.mode}")

    if args.mode == "parallel" and args.nprocs < 2:
        errors.append(f"--nprocs must be >= 2 for parallel mode, got {args.nprocs}")

    # Validate coords format
    coords = args.coords.split("/")
    if len(coords) not in [2, 4]:
        errors.append(f"--coords must be lon/lat or Wlon/Elon/Slat/Nlat, got {args.coords}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)


def check_dependencies():
    """Check that required system dependencies are installed."""
    warnings = []

    # Check gfortran
    try:
        result = subprocess.run(["gfortran", "--version"],
                                capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            warnings.append("gfortran not found or not working")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        warnings.append("gfortran not found. Install: apt install gfortran")

    # Check netCDF library
    try:
        result = subprocess.run(["nf-config", "--all"],
                                capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            # Try alternative
            result = subprocess.run(["nc-config", "--all"],
                                    capture_output=True, text=True, timeout=10)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        warnings.append("netCDF Fortran library not found. "
                        "Install: apt install libnetcdff-dev")

    # Check make
    try:
        subprocess.run(["make", "--version"],
                       capture_output=True, text=True, timeout=10)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        warnings.append("make not found. Install: apt install make")

    return warnings


def parse_job_options(job_opts_path):
    """Parse the job options file to extract file paths for validation."""
    file_keys = [
        "metFileFss", "metFileFdl", "metFilePre", "metFileTa",
        "metFileQa", "metFileUv", "metFilePres",
        "init_file", "rs_file_to_overwrite",
        "runparams_file", "CO2File", "CH4File",
        "POPDFile", "LGHTFile", "LUCFile", "OBSWETFFile",
    ]

    paths = {}
    try:
        with open(job_opts_path, "r") as f:
            content = f.read()
        for key in file_keys:
            # Match: key = 'path' or key = "path"
            pattern = rf"{key}\s*=\s*['\"]([^'\"]+)['\"]"
            match = re.search(pattern, content)
            if match:
                paths[key] = match.group(1)
    except Exception as e:
        pass

    return paths


def validate_input_files(source_dir, job_opts_path):
    """Check that input files referenced in job options exist."""
    warnings = []
    paths = parse_job_options(job_opts_path)

    critical_keys = ["init_file", "runparams_file"]
    met_keys = ["metFileFss", "metFileFdl", "metFilePre", "metFileTa",
                "metFileQa", "metFileUv", "metFilePres"]

    for key in critical_keys:
        if key in paths:
            fpath = paths[key]
            if not os.path.isabs(fpath):
                fpath = os.path.join(source_dir, fpath)
            if not os.path.isfile(fpath):
                warnings.append(f"CRITICAL: {key} file not found: {fpath}")

    for key in met_keys:
        if key in paths:
            fpath = paths[key]
            if not os.path.isabs(fpath):
                fpath = os.path.join(source_dir, fpath)
            if not os.path.isfile(fpath):
                warnings.append(f"Met file not found: {key} = {fpath}")

    return warnings, paths


def compile_classic(source_dir, mode="serial"):
    """Compile CLASSIC using make."""
    binary_name = f"CLASSIC_{mode}"
    binary_path = os.path.join(source_dir, "bin", binary_name)

    if os.path.isfile(binary_path):
        return {"status": "exists", "binary": binary_path}

    # Clean and compile
    try:
        result = subprocess.run(
            ["make", f"mode={mode}"],
            cwd=source_dir,
            capture_output=True,
            text=True,
            timeout=600,
        )

        if result.returncode == 0 and os.path.isfile(binary_path):
            return {
                "status": "compiled",
                "binary": binary_path,
                "stdout": result.stdout[-500:] if len(result.stdout) > 500 else result.stdout,
            }
        else:
            return {
                "status": "failed",
                "returncode": result.returncode,
                "stderr": result.stderr[-1000:] if len(result.stderr) > 1000 else result.stderr,
                "stdout": result.stdout[-500:] if len(result.stdout) > 500 else result.stdout,
            }
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "message": "Compilation timed out after 600s"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def run_classic(source_dir, binary_path, job_options, coords, mode, nprocs):
    """Execute the CLASSIC binary."""
    if mode == "parallel":
        cmd = ["mpirun", "-np", str(nprocs), binary_path, job_options, coords]
    else:
        cmd = [binary_path, job_options, coords]

    start_time = time.time()
    try:
        result = subprocess.run(
            cmd,
            cwd=source_dir,
            capture_output=True,
            text=True,
            timeout=3600,
        )
        elapsed = time.time() - start_time

        return {
            "status": "completed" if result.returncode == 0 else "failed",
            "returncode": result.returncode,
            "elapsed_seconds": round(elapsed, 1),
            "command": " ".join(cmd),
            "stdout": result.stdout[-1000:] if len(result.stdout) > 1000 else result.stdout,
            "stderr": result.stderr[-1000:] if len(result.stderr) > 1000 else result.stderr,
        }
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "message": "Run timed out after 3600s",
                "command": " ".join(cmd)}
    except Exception as e:
        return {"status": "error", "message": str(e), "command": " ".join(cmd)}


def validate_outputs(source_dir, job_opts_path):
    """Check that expected output files were created."""
    paths = parse_job_options(job_opts_path)
    output_dir = paths.get("output_directory", "outputFiles")
    if not os.path.isabs(output_dir):
        output_dir = os.path.join(source_dir, output_dir)

    results = {"output_dir": output_dir, "files": []}
    if os.path.isdir(output_dir):
        for f in sorted(os.listdir(output_dir)):
            if f.endswith(".nc"):
                fpath = os.path.join(output_dir, f)
                size = os.path.getsize(fpath)
                results["files"].append({"name": f, "size_bytes": size})

    return results


def main():
    parser = argparse.ArgumentParser(description="Compile and run CLASSIC")
    parser.add_argument("--source_dir", required=True,
                        help="Path to CLASSIC source directory")
    parser.add_argument("--job_options", required=True,
                        help="Path to job options file (relative to source_dir)")
    parser.add_argument("--coords", required=True,
                        help="Coordinates: lon/lat or Wlon/Elon/Slat/Nlat")
    parser.add_argument("--mode", default="serial",
                        choices=["serial", "parallel"],
                        help="Compilation/execution mode")
    parser.add_argument("--nprocs", type=int, default=2,
                        help="Number of MPI processes (parallel mode)")
    parser.add_argument("--skip_compile", action="store_true",
                        help="Skip compilation step")

    args = parser.parse_args()
    validate_inputs(args)

    report = {
        "status": "starting",
        "dependencies": [],
        "input_validation": [],
        "compilation": {},
        "execution": {},
        "output_validation": {},
    }

    # 1. Check dependencies
    dep_warnings = check_dependencies()
    report["dependencies"] = dep_warnings

    # 2. Validate input files
    job_opts_path = os.path.join(args.source_dir, args.job_options)
    input_warnings, _ = validate_input_files(args.source_dir, job_opts_path)
    report["input_validation"] = input_warnings

    # 3. Compile
    if not args.skip_compile:
        compile_result = compile_classic(args.source_dir, args.mode)
        report["compilation"] = compile_result
        if compile_result["status"] == "failed":
            report["status"] = "compile_failed"
            print(json.dumps(report, indent=2))
            sys.exit(1)
        binary_path = compile_result.get("binary",
                                          os.path.join(args.source_dir, "bin",
                                                       f"CLASSIC_{args.mode}"))
    else:
        binary_path = os.path.join(args.source_dir, "bin",
                                    f"CLASSIC_{args.mode}")
        report["compilation"] = {"status": "skipped"}

    # 4. Run
    run_result = run_classic(args.source_dir, binary_path, args.job_options,
                              args.coords, args.mode, args.nprocs)
    report["execution"] = run_result

    # 5. Validate outputs
    output_result = validate_outputs(args.source_dir, job_opts_path)
    report["output_validation"] = output_result

    if run_result["status"] == "completed" and len(output_result["files"]) > 0:
        report["status"] = "success"
    elif run_result["status"] == "completed":
        report["status"] = "completed_no_output"
    else:
        report["status"] = run_result["status"]

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
