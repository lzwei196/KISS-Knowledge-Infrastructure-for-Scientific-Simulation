#!/usr/bin/env python3
"""
run_forefire.py — Execute ForeFire simulation with preflight/postflight checks.

Wraps the `forefire` binary, handling:
  1. Preflight validation (binary exists, data files present, fuels.csv valid)
  2. Execution with timeout and output capture
  3. Postflight validation (output files created, not empty, reasonable size)

Usage:
    python run_forefire.py \\
        --binary /path/to/forefire/bin/forefire \\
        --script real_case.ff \\
        --workdir /path/to/tests/runff \\
        --timeout 300

    python run_forefire.py \\
        --binary forefire \\
        --script run.ff \\
        --workdir . \\
        --expected_outputs ForeFire.0.nc real_case.kml
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


def validate_inputs(args):
    """Preflight checks before running ForeFire."""
    errors = []
    warnings = []

    # Check binary
    binary = args.binary
    if not os.path.isfile(binary):
        resolved = shutil.which(binary)
        if resolved:
            binary = resolved
        else:
            errors.append(f"ForeFire binary not found: {args.binary}")

    # Check script file
    script_path = os.path.join(args.workdir, args.script)
    if not os.path.isfile(script_path):
        errors.append(f"Script file not found: {script_path}")

    # Check working directory
    if not os.path.isdir(args.workdir):
        errors.append(f"Working directory not found: {args.workdir}")
    else:
        # Check for common required files
        fuels_path = os.path.join(args.workdir, "fuels.csv")
        if not os.path.isfile(fuels_path):
            # Check if script references fuels
            if os.path.isfile(script_path):
                with open(script_path) as f:
                    content = f.read()
                if "fuelsTableFile" in content or "fuels.csv" in content:
                    warnings.append("fuels.csv not found but referenced in script")

        # Check for data files
        data_nc = os.path.join(args.workdir, "data.nc")
        if os.path.isfile(data_nc):
            size = os.path.getsize(data_nc)
            if size < 100:
                errors.append(f"data.nc is too small ({size} bytes) — likely a Git LFS pointer. "
                              "Run 'git lfs pull' to download actual data.")

    for w in warnings:
        print(f"PREFLIGHT WARNING: {w}", file=sys.stderr)
    if errors:
        for e in errors:
            print(f"PREFLIGHT ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    print("Preflight checks passed.")
    return binary


def process(args, binary):
    """Run the ForeFire simulation."""
    cmd = [binary, "-i", args.script]
    print(f"Running: {' '.join(cmd)}")
    print(f"Working directory: {args.workdir}")

    start = time.time()
    try:
        result = subprocess.run(
            cmd,
            cwd=args.workdir,
            capture_output=True,
            text=True,
            timeout=args.timeout,
        )
    except subprocess.TimeoutExpired:
        print(f"ERROR: ForeFire timed out after {args.timeout} seconds", file=sys.stderr)
        return {
            "status": "timeout",
            "duration_s": args.timeout,
            "command": " ".join(cmd),
        }
    except FileNotFoundError:
        print(f"ERROR: Binary not found: {binary}", file=sys.stderr)
        return {"status": "error", "error": f"Binary not found: {binary}"}

    duration = time.time() - start
    stdout = result.stdout
    stderr = result.stderr

    print(f"Exit code: {result.returncode}")
    print(f"Duration: {duration:.1f}s")
    if stdout:
        print(f"STDOUT (first 1000 chars):\n{stdout[:1000]}")
    if stderr:
        print(f"STDERR (first 500 chars):\n{stderr[:500]}", file=sys.stderr)

    return {
        "status": "completed" if result.returncode == 0 else "failed",
        "returncode": result.returncode,
        "duration_s": round(duration, 2),
        "command": " ".join(cmd),
        "stdout": stdout[:2000],
        "stderr": stderr[:1000],
    }


def validate_outputs(args, run_result):
    """Postflight checks after running ForeFire."""
    if run_result["status"] != "completed":
        print(f"Skipping postflight: run status={run_result['status']}")
        return run_result

    errors = []
    created_files = []

    # Check expected outputs
    if args.expected_outputs:
        for fname in args.expected_outputs:
            fpath = os.path.join(args.workdir, fname)
            if os.path.isfile(fpath):
                size = os.path.getsize(fpath)
                created_files.append({"file": fname, "size_bytes": size})
                if size == 0:
                    errors.append(f"Output file is empty: {fname}")
            else:
                errors.append(f"Expected output not created: {fname}")

    # Check for common output files
    for pattern in ["ForeFire.0.nc", "*.kml", "*.geojson"]:
        import glob
        matches = glob.glob(os.path.join(args.workdir, pattern))
        for m in matches:
            name = os.path.basename(m)
            if not any(f["file"] == name for f in created_files):
                created_files.append({"file": name, "size_bytes": os.path.getsize(m)})

    run_result["output_files"] = created_files

    if errors:
        for e in errors:
            print(f"POSTFLIGHT WARNING: {e}", file=sys.stderr)
        run_result["postflight_warnings"] = errors
    else:
        print(f"Postflight passed. {len(created_files)} output files found.")

    return run_result


def main():
    parser = argparse.ArgumentParser(description="Run ForeFire simulation with checks")
    parser.add_argument("--binary", required=True, help="Path to forefire binary")
    parser.add_argument("--script", required=True, help="ForeFire script (.ff) to execute")
    parser.add_argument("--workdir", default=".", help="Working directory for simulation")
    parser.add_argument("--timeout", type=int, default=300, help="Timeout in seconds")
    parser.add_argument("--expected_outputs", nargs="*", default=None, help="Expected output files")
    parser.add_argument("--output_json", default=None, help="Path to write run result JSON")
    args = parser.parse_args()

    binary = validate_inputs(args)
    run_result = process(args, binary)
    run_result = validate_outputs(args, run_result)

    # Write result JSON
    if args.output_json:
        with open(args.output_json, 'w') as f:
            json.dump(run_result, f, indent=2)
        print(f"Run result written to: {args.output_json}")

    # Print summary
    print(f"\n=== Run Summary ===")
    print(f"Status: {run_result['status']}")
    print(f"Duration: {run_result.get('duration_s', 'N/A')}s")
    if run_result.get("output_files"):
        for finfo in run_result["output_files"]:
            print(f"  Output: {finfo['file']} ({finfo['size_bytes']} bytes)")

    sys.exit(0 if run_result["status"] == "completed" else 1)


if __name__ == "__main__":
    main()
