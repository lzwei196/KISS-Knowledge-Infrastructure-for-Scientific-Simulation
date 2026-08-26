#!/usr/bin/env python3
"""
run_raven.py — Execute Raven binary with error handling and output collection.

Performs preflight checks on all .rv* files, runs the Raven executable,
parses stdout/stderr for errors, and collects output files.

Usage:
    python run_raven.py \
        --run_dir outputs/chaohe_raven/ \
        --basin_name chaohe \
        --raven_exe KISSPATH_BINARIES/raven/Raven.exe
"""

import argparse
import json
import os
import sys
import subprocess
import time
from datetime import datetime
from pathlib import Path

RAVEN_EXE_DEFAULT = "KISSPATH_BINARIES/raven/Raven.exe"

REQUIRED_FILES = [".rvi", ".rvh", ".rvp", ".rvt"]
OPTIONAL_FILES = [".rvc", ".rve", ".rvm"]

OUTPUT_FILES = [
    "Hydrographs.csv",
    "WatershedStorage.csv",
    "Diagnostics.csv",
    "ForcingFunctions.csv",
    "solution.rvc",
]


def validate_inputs(args):
    """Preflight checks."""
    errors = []
    warnings = []

    # Check Raven binary
    if not os.path.isfile(args.raven_exe):
        errors.append(f"Raven executable not found: {args.raven_exe}")
    elif not os.access(args.raven_exe, os.X_OK):
        errors.append(f"Raven executable not executable: {args.raven_exe}")

    # Check run directory
    if not os.path.isdir(args.run_dir):
        errors.append(f"Run directory not found: {args.run_dir}")
        return {"status": "error", "errors": errors}

    # Check required .rv* files
    for ext in REQUIRED_FILES:
        matches = list(Path(args.run_dir).glob(f"*{ext}"))
        if not matches:
            errors.append(f"Missing required file: *{ext} in {args.run_dir}")

    # Check optional files
    for ext in OPTIONAL_FILES:
        matches = list(Path(args.run_dir).glob(f"*{ext}"))
        if not matches and ext == ".rvc":
            # Raven v4.1 errors if .rvc is missing — create empty one (cold start)
            rvc_path = Path(args.run_dir) / f"{args.basin_name}.rvc"
            rvc_path.touch()
            warnings.append(f"No .rvc file found — created empty {rvc_path.name} (cold start)")

    # Basic .rvi validation
    rvi_files = list(Path(args.run_dir).glob("*.rvi"))
    if rvi_files:
        with open(rvi_files[0]) as f:
            rvi_content = f.read()
        if ":StartDate" not in rvi_content:
            errors.append(".rvi file missing :StartDate")
        if ":EndDate" not in rvi_content:
            errors.append(".rvi file missing :EndDate")
        if ":HydrologicProcesses" not in rvi_content:
            errors.append(".rvi file missing :HydrologicProcesses block")

    # Basic .rvt validation
    rvt_files = list(Path(args.run_dir).glob("*.rvt"))
    if rvt_files:
        with open(rvt_files[0]) as f:
            rvt_content = f.read()
        if ":Gauge" not in rvt_content and ":GriddedForcing" not in rvt_content:
            errors.append(".rvt file has no :Gauge or :GriddedForcing block — no forcing data")
        if ":Data PRECIP" not in rvt_content:
            warnings.append(".rvt has no PRECIP data — Raven will fill with zeros (SILENT ERROR)")

    result = {"status": "ok", "warnings": warnings}
    if errors:
        result = {"status": "error", "errors": errors, "warnings": warnings}
    return result


def run_raven(args):
    """Execute Raven binary."""

    # Raven expects: Raven.exe <basename> [-o output_dir]
    # basename is the file prefix without extension
    # e.g., for chaohe.rvi, chaohe.rvh, etc. -> basename = "chaohe"
    basename = args.basin_name

    # Build command
    cmd = [
        os.path.abspath(args.raven_exe),
        basename,
    ]

    # Output directory
    output_dir = os.path.join(args.run_dir, "output")
    os.makedirs(output_dir, exist_ok=True)
    cmd.extend(["-o", os.path.abspath(output_dir) + "/"])

    print(f"Running: {' '.join(cmd)}", flush=True)
    print(f"Working directory: {os.path.abspath(args.run_dir)}", flush=True)

    t0 = time.time()

    result = subprocess.run(
        cmd,
        cwd=os.path.abspath(args.run_dir),
        capture_output=True,
        text=True,
        timeout=args.timeout,
    )

    elapsed = time.time() - t0

    return {
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "elapsed_seconds": round(elapsed, 1),
        "output_dir": output_dir,
    }


def parse_raven_errors(stdout, stderr):
    """Parse Raven stdout/stderr for known error patterns."""
    errors = []
    warnings = []

    combined = (stdout or "") + "\n" + (stderr or "")

    error_patterns = [
        ("ERROR", "Raven reported an error"),
        ("FATAL", "Fatal error in Raven"),
        ("BAD_DATA", "Bad data encountered"),
        ("cannot find", "Missing input file"),
        ("Segmentation fault", "Segfault — likely memory issue or corrupt input"),
        ("no observation data", "No observed data for diagnostics"),
    ]

    for pattern, desc in error_patterns:
        if pattern.lower() in combined.lower():
            # Extract the line containing the error
            for line in combined.split("\n"):
                if pattern.lower() in line.lower():
                    errors.append(f"{desc}: {line.strip()}")
                    break

    warning_patterns = [
        ("WARNING", "Raven warning"),
        ("using default", "Using default value"),
        ("data gap", "Gap in forcing data"),
    ]

    for pattern, desc in warning_patterns:
        if pattern.lower() in combined.lower():
            for line in combined.split("\n"):
                if pattern.lower() in line.lower():
                    warnings.append(f"{desc}: {line.strip()}")

    return errors, warnings


def collect_outputs(output_dir, basin_name):
    """Collect and validate output files."""
    outputs = {}

    for fname in OUTPUT_FILES:
        # Raven may prefix with RunName_
        possible = [
            os.path.join(output_dir, fname),
            os.path.join(output_dir, f"{basin_name}_{fname}"),
        ]

        for p in possible:
            if os.path.isfile(p):
                size = os.path.getsize(p)
                outputs[fname] = {"path": p, "size_bytes": size}
                break

    # Also check for custom output files
    if os.path.isdir(output_dir):
        for f in os.listdir(output_dir):
            if f.endswith(".csv") and f not in outputs:
                fpath = os.path.join(output_dir, f)
                outputs[f] = {"path": fpath, "size_bytes": os.path.getsize(fpath)}

    return outputs


def extract_diagnostics(output_dir, basin_name):
    """Extract performance diagnostics from Raven's Diagnostics.csv.

    Two defects fixed here (dt_rav_037):
      1. The file is prefixed with the .rvi :RunName, which is
         "<basin>_<template>", NOT the bare basin name — so the fixed-name
         lookup never found it in an ensemble run and diagnostics came back {}.
      2. Diagnostics.csv is a HEADER row plus one DATA row per observation
         series ("observed_data_series,filename,DIAG_NASH_SUTCLIFFE,..."), not
         name,value pairs. Reading it row-wise parsed nothing.
    """
    diag_file = None
    for fname in ["Diagnostics.csv", f"{basin_name}_Diagnostics.csv"]:
        path = os.path.join(output_dir, fname)
        if os.path.isfile(path):
            diag_file = path
            break
    if not diag_file and os.path.isdir(output_dir):
        matches = sorted(f for f in os.listdir(output_dir)
                         if f.lower().endswith("diagnostics.csv"))
        if matches:
            diag_file = os.path.join(output_dir, matches[0])

    if not diag_file:
        return {}

    metrics = {}
    try:
        with open(diag_file) as f:
            rows = [[c.strip() for c in ln.strip().split(",")]
                    for ln in f if ln.strip() and not ln.startswith(("*", "#"))]
        if len(rows) >= 2:
            header, data = rows[0], rows[1]
            for name, value in zip(header, data):
                if not name:
                    continue
                try:
                    metrics[name] = float(value)
                except ValueError:
                    continue
                # Also expose the metric without Raven's DIAG_ prefix
                if name.startswith("DIAG_"):
                    metrics[name[len("DIAG_"):]] = metrics[name]
    except Exception:
        pass

    return metrics


def process(args):
    """Main execution flow."""

    # Preflight
    preflight = validate_inputs(args)
    if preflight["status"] == "error":
        return {"status": "error", "preflight": preflight}

    # Run
    try:
        run_result = run_raven(args)
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": f"Raven timed out after {args.timeout} seconds"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

    # Parse errors
    raven_errors, raven_warnings = parse_raven_errors(
        run_result["stdout"], run_result["stderr"]
    )

    # Collect outputs
    outputs = collect_outputs(run_result["output_dir"], args.basin_name)

    # Extract diagnostics
    diagnostics = extract_diagnostics(run_result["output_dir"], args.basin_name)

    # Determine success
    success = (run_result["returncode"] == 0 and
               "Hydrographs.csv" in outputs or
               any("Hydrographs" in k for k in outputs))

    results = {
        "status": "success" if success else "error",
        "returncode": run_result["returncode"],
        "elapsed_seconds": run_result["elapsed_seconds"],
        "output_dir": run_result["output_dir"],
        "outputs": outputs,
        "diagnostics": diagnostics,
        "raven_errors": raven_errors,
        "raven_warnings": raven_warnings + preflight.get("warnings", []),
        "stdout_tail": run_result["stdout"][-500:] if run_result["stdout"] else "",
        "stderr_tail": run_result["stderr"][-500:] if run_result["stderr"] else "",
    }

    return results


def main():
    parser = argparse.ArgumentParser(description="Run Raven hydrological model")
    parser.add_argument("--run_dir", required=True, help="Directory containing .rv* files")
    parser.add_argument("--basin_name", required=True, help="Basin name (file prefix)")
    parser.add_argument("--raven_exe", default=RAVEN_EXE_DEFAULT, help="Path to Raven executable")
    parser.add_argument("--timeout", type=int, default=3600, help="Timeout in seconds (default: 3600)")

    args = parser.parse_args()

    try:
        results = process(args)
    except Exception as e:
        import traceback
        print(json.dumps({"status": "error", "message": str(e), "traceback": traceback.format_exc()}))
        sys.exit(2)

    print(json.dumps(results, indent=2, default=str))
    sys.exit(0 if results.get("status") == "success" else 1)


if __name__ == "__main__":
    main()
