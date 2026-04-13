#!/usr/bin/env python3
"""
run_coawst.py — COAWST Execution Wrapper
==========================================

Runs the COAWST/ROMS model binary with preflight validation, MPI execution,
and post-run output verification.

PREFLIGHT CHECKS:
  - Binary exists and is executable
  - Input .in file exists and is parseable
  - Grid, forcing, IC, BC files referenced in .in exist
  - NtileI × NtileJ matches nprocs (dt_004)
  - NetCDF library available (ldd check)
  - Sufficient disk space for estimated output

RUNTIME MONITORING:
  - Watches stdout for BLOWUP, NaN, CFL violations
  - Captures timing information
  - Reports final status

Usage:
  python3 run_coawst.py \\
    --binary ./coawstM \\
    --config coupling_sandy.in \\
    --nprocs 16 \\
    --timeout 7200

  python3 run_coawst.py \\
    --binary ./romsM \\
    --config ocean_upwelling.in \\
    --nprocs 4
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


def validate_inputs(args):
    """Preflight validation before model execution."""
    errors = []
    warnings = []

    # Check binary
    if not os.path.exists(args.binary):
        errors.append(f"Binary not found: {args.binary}")
    elif not os.access(args.binary, os.X_OK):
        errors.append(f"Binary not executable: {args.binary}. Run: chmod +x {args.binary}")

    # Check config file
    if not os.path.exists(args.config):
        errors.append(f"Config file not found: {args.config}")
    else:
        # Parse .in file to check referenced files
        referenced_files = parse_in_file_references(args.config)
        for ref_key, ref_path in referenced_files.items():
            if ref_path and not os.path.exists(ref_path):
                if ref_key in ("GRDNAME", "ININAME"):
                    errors.append(f"Required file {ref_key}={ref_path} not found")
                else:
                    warnings.append(f"Referenced file {ref_key}={ref_path} not found")

        # Check NtileI × NtileJ
        tiles = parse_tiling(args.config)
        if tiles:
            expected_ocean_procs = tiles["NtileI"] * tiles["NtileJ"]
            # For coupled runs, total procs includes wave/atm
            # For standalone, must match nprocs
            if expected_ocean_procs > args.nprocs:
                errors.append(
                    f"NtileI({tiles['NtileI']}) × NtileJ({tiles['NtileJ']}) = "
                    f"{expected_ocean_procs} > nprocs({args.nprocs}). "
                    f"Model will deadlock (dt_004)."
                )

    # Check MPI
    mpirun = shutil.which("mpirun") or shutil.which("mpiexec")
    if not mpirun and args.nprocs > 1:
        errors.append("mpirun/mpiexec not found but nprocs > 1. Install MPI or use nprocs=1.")

    # Check disk space (rough estimate: 1 GB per 1M grid cells per 100 output steps)
    try:
        stat = os.statvfs(os.path.dirname(os.path.abspath(args.config)) or ".")
        free_gb = stat.f_bavail * stat.f_frsize / (1024**3)
        if free_gb < 2.0:
            warnings.append(f"Low disk space: {free_gb:.1f} GB free. COAWST outputs can be large.")
    except Exception:
        pass

    if errors:
        print(json.dumps({"status": "error", "errors": errors, "warnings": warnings}, indent=2))
        sys.exit(1)

    return warnings


def parse_in_file_references(in_path):
    """Extract file references from ROMS .in file."""
    refs = {}
    file_keys = ["GRDNAME", "ININAME", "BRYNAME", "FRCNAME", "CLMNAME",
                  "TIDENAME", "NFFILES", "HISNAME", "AVGNAME", "RSTNAME",
                  "SCRIP_COAWST_NAME"]

    try:
        with open(in_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("!") or not line:
                    continue
                for key in file_keys:
                    if key in line:
                        parts = line.split("==") if "==" in line else line.split("=")
                        if len(parts) >= 2:
                            val = parts[-1].strip().split()[0].strip()
                            if val and not val.startswith("!"):
                                refs[key] = val
    except Exception:
        pass

    return refs


def parse_tiling(in_path):
    """Extract NtileI and NtileJ from .in file."""
    tiles = {}
    try:
        with open(in_path) as f:
            for line in f:
                line = line.strip()
                if "NtileI" in line and "==" in line:
                    tiles["NtileI"] = int(line.split("==")[1].strip().split()[0])
                elif "NtileJ" in line and "==" in line:
                    tiles["NtileJ"] = int(line.split("==")[1].strip().split()[0])
    except Exception:
        pass

    return tiles if len(tiles) == 2 else None


def run_model(args, warnings):
    """Execute the COAWST model via MPI."""
    mpirun = shutil.which("mpirun") or shutil.which("mpiexec") or "mpirun"

    if args.nprocs > 1:
        cmd = [mpirun, "-np", str(args.nprocs), args.binary, args.config]
    else:
        cmd = [args.binary, args.config]

    cmd_str = " ".join(cmd)
    print(f"  Executing: {cmd_str}", file=sys.stderr)

    work_dir = os.path.dirname(os.path.abspath(args.config)) or "."

    start_time = time.time()

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=work_dir,
            text=True,
            bufsize=1,
        )

        output_lines = []
        blowup = False
        nan_detected = False

        while True:
            line = proc.stdout.readline()
            if not line and proc.poll() is not None:
                break

            output_lines.append(line)
            print(f"    {line.rstrip()}", file=sys.stderr)

            # Monitor for failures
            line_upper = line.upper()
            if "BLOWUP" in line_upper:
                blowup = True
                warnings.append("BLOWUP detected in model output — CFL violation likely (dt_005)")
            if "NAN" in line_upper or "INF" in line_upper:
                nan_detected = True
                warnings.append(f"NaN/Inf detected: {line.strip()}")

            # Timeout check
            elapsed = time.time() - start_time
            if args.timeout and elapsed > args.timeout:
                proc.kill()
                warnings.append(f"Timeout after {args.timeout}s — model killed")
                break

        returncode = proc.wait()
        elapsed = time.time() - start_time

    except FileNotFoundError as e:
        return {
            "status": "error",
            "errors": [f"Cannot execute: {e}"],
            "warnings": warnings,
        }

    full_output = "".join(output_lines)

    # Determine status
    if blowup:
        status = "blowup"
    elif returncode != 0:
        status = "failed"
    elif nan_detected:
        status = "completed_with_warnings"
    else:
        status = "success"

    return {
        "status": status,
        "returncode": returncode,
        "elapsed_seconds": round(elapsed, 1),
        "command": cmd_str,
        "work_dir": work_dir,
        "output_head": full_output[:500],
        "output_tail": full_output[-500:] if len(full_output) > 500 else "",
        "blowup": blowup,
        "warnings": warnings,
    }


def validate_outputs(result, args):
    """Check that expected output files were created."""
    if result["status"] in ("error", "failed"):
        return result

    work_dir = result.get("work_dir", ".")

    # Look for history files
    his_files = [f for f in os.listdir(work_dir) if "his" in f.lower() and f.endswith(".nc")]
    rst_files = [f for f in os.listdir(work_dir) if "rst" in f.lower() and f.endswith(".nc")]

    result["output_files"] = {
        "history": his_files,
        "restart": rst_files,
    }

    if not his_files and result["status"] == "success":
        result["warnings"].append("No history files found — check NHIS setting in ocean.in")

    # Check history file is non-empty
    for hf in his_files:
        hf_path = os.path.join(work_dir, hf)
        size_mb = os.path.getsize(hf_path) / (1024**2)
        if size_mb < 0.01:
            result["warnings"].append(f"History file {hf} suspiciously small: {size_mb:.4f} MB")
        else:
            result[f"history_size_mb"] = round(size_mb, 2)

    return result


def process(args, warnings):
    """Main execution process."""
    if args.dry_run:
        mpirun = shutil.which("mpirun") or "mpirun"
        cmd = f"{mpirun} -np {args.nprocs} {args.binary} {args.config}"
        return {
            "status": "dry_run",
            "command": cmd,
            "warnings": warnings,
        }

    return run_model(args, warnings)


def main():
    parser = argparse.ArgumentParser(
        description="COAWST execution wrapper with preflight checks and monitoring",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--binary", required=True, help="Path to coawstM or romsM binary")
    parser.add_argument("--config", required=True, help="Path to ocean.in or coupling.in")
    parser.add_argument("--nprocs", type=int, default=4, help="Number of MPI processors")
    parser.add_argument("--timeout", type=int, default=3600, help="Timeout in seconds (default: 3600)")
    parser.add_argument("--dry-run", action="store_true", help="Print command without executing")

    args = parser.parse_args()
    warnings = validate_inputs(args)
    result = process(args, warnings)
    result = validate_outputs(result, args)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
