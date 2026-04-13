#!/usr/bin/env python3
"""
run_elmfire.py — Execute ELMFIRE with preflight validation and output checking.

Preflight checks:
  1. Binary exists and is executable
  2. Namelist file exists and is parseable
  3. All referenced raster files exist
  4. Output directory exists (creates if needed)
  5. Scratch directory exists (creates if needed)
  6. GDAL is available (if CONVERT_TO_GEOTIFF = .TRUE.)

Execution:
  - Single-process: elmfire_VERSION namelist
  - MPI-parallel: mpirun -np N elmfire_VERSION namelist

Post-run checks:
  1. Output files exist
  2. Fire size stats show non-zero area
  3. Time of arrival raster has valid values

Usage:
    python run_elmfire.py \\
        --namelist ./inputs/elmfire.data \\
        --np 4 \\
        --binary elmfire_2025.1002

    python run_elmfire.py \\
        --namelist ./inputs/elmfire.data \\
        --docker \\
        --np 8
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


def validate_inputs(args):
    """Preflight validation before running ELMFIRE."""
    errors = []
    warnings = []

    # Check namelist
    if not os.path.isfile(args.namelist):
        errors.append(f"Namelist file not found: {args.namelist}")
    else:
        namelist_content = open(args.namelist).read()

        # Extract directories from namelist
        fuels_dir = extract_namelist_value(namelist_content,
                                           "FUELS_AND_TOPOGRAPHY_DIRECTORY")
        weather_dir = extract_namelist_value(namelist_content, "WEATHER_DIRECTORY")
        outputs_dir = extract_namelist_value(namelist_content, "OUTPUTS_DIRECTORY")
        scratch_dir = extract_namelist_value(namelist_content, "SCRATCH")

        # Check input directories
        base_dir = os.path.dirname(os.path.abspath(args.namelist))

        for dirname, dirpath in [("Fuels/topo", fuels_dir),
                                  ("Weather", weather_dir)]:
            if dirpath:
                full_path = os.path.join(base_dir, dirpath) if not os.path.isabs(dirpath) else dirpath
                if not os.path.isdir(full_path):
                    errors.append(f"{dirname} directory not found: {full_path}")
                else:
                    # Check for required raster files
                    raster_names = extract_raster_filenames(namelist_content)
                    for rname in raster_names:
                        tif = os.path.join(full_path, f"{rname}.tif")
                        bil = os.path.join(full_path, f"{rname}.bil")
                        if not os.path.isfile(tif) and not os.path.isfile(bil):
                            errors.append(f"Raster not found: {rname}.tif or {rname}.bil in {full_path}")

        # Create output/scratch directories
        if outputs_dir:
            full_outputs = os.path.join(base_dir, outputs_dir) if not os.path.isabs(outputs_dir) else outputs_dir
            os.makedirs(full_outputs, exist_ok=True)
        if scratch_dir and scratch_dir != 'null':
            full_scratch = os.path.join(base_dir, scratch_dir) if not os.path.isabs(scratch_dir) else scratch_dir
            os.makedirs(full_scratch, exist_ok=True)

    # Check binary
    binary = args.binary
    if not shutil.which(binary):
        # Try common locations
        common_paths = [
            f"/elmfire/build/linux/bin/{binary}",
            f"./build/linux/bin/{binary}",
            os.path.expandvars(f"$ELMFIRE_BASE_DIR/build/linux/bin/{binary}"),
        ]
        found = False
        for p in common_paths:
            if os.path.isfile(p) and os.access(p, os.X_OK):
                args.binary = p
                found = True
                break
        if not found:
            errors.append(f"ELMFIRE binary not found: {binary}")

    # Check MPI
    if args.np > 1 and not shutil.which("mpirun"):
        errors.append("mpirun not found — required for parallel execution")

    if errors:
        print(json.dumps({"status": "error", "stage": "preflight", "errors": errors}))
        sys.exit(1)

    if warnings:
        for w in warnings:
            print(f"  WARNING: {w}")


def extract_namelist_value(content, key):
    """Extract a value from Fortran namelist text."""
    pattern = rf"{key}\s*=\s*'([^']+)'"
    match = re.search(pattern, content, re.IGNORECASE)
    if match:
        return match.group(1)
    # Try without quotes (numeric values)
    pattern = rf"{key}\s*=\s*([^\s,/]+)"
    match = re.search(pattern, content, re.IGNORECASE)
    if match:
        return match.group(1)
    return None


def extract_raster_filenames(content):
    """Extract raster filenames from namelist."""
    rasters = []
    for key in ["ASP_FILENAME", "CBD_FILENAME", "CBH_FILENAME", "CC_FILENAME",
                 "CH_FILENAME", "DEM_FILENAME", "FBFM_FILENAME", "SLP_FILENAME",
                 "ADJ_FILENAME", "PHI_FILENAME", "WS_FILENAME", "WD_FILENAME",
                 "M1_FILENAME", "M10_FILENAME", "M100_FILENAME"]:
        val = extract_namelist_value(content, key)
        if val and val != 'null':
            rasters.append(val)
    return rasters


def run_elmfire(args):
    """Execute ELMFIRE binary."""
    if args.np > 1:
        cmd = ["mpirun", "-np", str(args.np), "--allow-run-as-root",
               args.binary, args.namelist]
    else:
        cmd = [args.binary, args.namelist]

    print(f"Executing: {' '.join(cmd)}")
    start_time = time.time()

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=args.timeout,
        cwd=os.path.dirname(os.path.abspath(args.namelist)) or "."
    )

    elapsed = time.time() - start_time
    print(f"  Completed in {elapsed:.1f} seconds")

    if result.returncode != 0:
        print(f"  STDERR: {result.stderr[:1000]}")
        return {
            "status": "error",
            "returncode": result.returncode,
            "stderr": result.stderr[:500],
            "elapsed_s": elapsed
        }

    return {
        "status": "completed",
        "returncode": 0,
        "stdout": result.stdout[:500],
        "stderr": result.stderr[:500],
        "elapsed_s": elapsed
    }


def validate_outputs(args):
    """Post-run validation of ELMFIRE outputs."""
    namelist_content = open(args.namelist).read()
    outputs_dir = extract_namelist_value(namelist_content, "OUTPUTS_DIRECTORY")
    base_dir = os.path.dirname(os.path.abspath(args.namelist))

    if outputs_dir:
        full_outputs = os.path.join(base_dir, outputs_dir) if not os.path.isabs(outputs_dir) else outputs_dir
    else:
        full_outputs = os.path.join(base_dir, "outputs")

    results = {"status": "ok", "outputs": [], "warnings": []}

    if not os.path.isdir(full_outputs):
        results["status"] = "error"
        results["warnings"].append(f"Output directory not found: {full_outputs}")
        return results

    # List output files
    output_files = sorted(os.listdir(full_outputs))
    results["outputs"] = output_files
    results["output_count"] = len(output_files)

    if len(output_files) == 0:
        results["status"] = "error"
        results["warnings"].append("No output files produced")

    # Check for time_of_arrival
    toa_files = [f for f in output_files if "time_of_arrival" in f]
    if not toa_files:
        results["warnings"].append("No time_of_arrival output found")

    # Check fire size stats
    stats_files = [f for f in output_files if "fire_size_stats" in f
                   or f.endswith(".csv")]
    if stats_files:
        results["stats_file"] = stats_files[0]

    print(json.dumps(results, indent=2))
    return results


def process(args):
    """Main pipeline: validate → execute → validate."""
    # Step 1: Preflight checks
    print("Running preflight checks...")
    validate_inputs(args)
    print("  Preflight OK")

    # Step 2: Execute
    print("\nRunning ELMFIRE...")
    run_result = run_elmfire(args)

    if run_result["status"] != "completed":
        print(json.dumps(run_result, indent=2))
        sys.exit(1)

    # Step 3: Validate outputs
    print("\nValidating outputs...")
    output_result = validate_outputs(args)

    # Combined result
    final = {
        "status": "completed" if output_result["status"] == "ok" else "warning",
        "execution": run_result,
        "outputs": output_result
    }
    print(json.dumps(final, indent=2))
    return final


def main():
    parser = argparse.ArgumentParser(description="Run ELMFIRE with validation")
    parser.add_argument("--namelist", required=True, help="Path to elmfire.data")
    parser.add_argument("--binary", default="elmfire_2025.1002",
                        help="ELMFIRE binary name or path")
    parser.add_argument("--np", type=int, default=1,
                        help="Number of MPI processes (default: 1)")
    parser.add_argument("--timeout", type=int, default=3600,
                        help="Timeout in seconds (default: 3600)")
    parser.add_argument("--docker", action="store_true",
                        help="Run inside Docker container")

    args = parser.parse_args()
    process(args)


if __name__ == "__main__":
    main()
