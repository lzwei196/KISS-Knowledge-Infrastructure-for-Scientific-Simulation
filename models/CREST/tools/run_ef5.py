#!/usr/bin/env python3
"""
run_ef5.py — Execute the EF5/CREST model with preflight checks.

Wraps the EF5 binary with input validation, environment setup,
execution monitoring, and output verification.

Pipeline stage: s6 (Execution)
Pattern: validate → process → validate

Input:
  - Path to EF5 binary
  - Path to control.txt configuration file
  - (Optional) OpenMP thread count

Output:
  - Model output files in the configured OUTPUT directory
  - Execution log with timing and status
  - Return code and diagnostic messages

Preflight checks:
  - Binary exists and is executable
  - Control file exists and has required sections
  - All referenced grid files exist
  - All referenced forcing directories exist and contain files
  - Output directory exists or can be created
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


# ── Constants ──────────────────────────────────────────────────────────────

REQUIRED_SECTIONS = {"basic", "execute"}
REQUIRED_BASIC_KEYS = {"dem", "ddm", "fam"}
REQUIRED_TASK_KEYS = {"style", "model", "basin", "precip", "pet",
                      "param_set", "timestep", "time_begin", "time_end", "output"}


# ── Config Parser ──────────────────────────────────────────────────────────

def parse_control_file(control_path):
    """Parse EF5 control file into sections."""
    sections = {}
    current_section = None
    current_name = None

    with open(control_path, "r") as f:
        for line in f:
            line = line.strip()

            # Remove comments
            line = re.sub(r"#.*$", "", line)
            line = re.sub(r"//.*$", "", line)
            # Simple /* */ removal (single line only)
            line = re.sub(r"/\*.*?\*/", "", line)

            if not line:
                continue

            # Section header
            match = re.match(r"\[(\w+)(?:\s+(\w+))?\]", line)
            if match:
                current_section = match.group(1).lower()
                current_name = match.group(2) or ""
                key = f"{current_section}:{current_name}".rstrip(":")
                sections[key] = {}
                continue

            # Key=Value pairs (may have multiple on one line)
            if current_section:
                key = f"{current_section}:{current_name}".rstrip(":")
                pairs = re.findall(r"(\w+)\s*=\s*(\S+)", line)
                for k, v in pairs:
                    sections[key][k.lower()] = v

    return sections


# ── Validation ─────────────────────────────────────────────────────────────

def validate_binary(binary_path):
    """Validate EF5 binary exists and is executable."""
    errors = []
    if not os.path.isfile(binary_path):
        errors.append(f"EF5 binary not found: {binary_path}")
    elif not os.access(binary_path, os.X_OK):
        errors.append(f"EF5 binary is not executable: {binary_path}")
    return errors


def validate_control_file(control_path):
    """Validate control file structure and referenced files."""
    errors = []
    warnings = []

    if not os.path.isfile(control_path):
        errors.append(f"Control file not found: {control_path}")
        return errors, warnings

    sections = parse_control_file(control_path)
    section_types = set()
    for key in sections:
        section_types.add(key.split(":")[0])

    # Check required sections
    for req in REQUIRED_SECTIONS:
        if req not in section_types:
            errors.append(f"Missing required section: [{req}]")

    # Check Basic section files
    for key, vals in sections.items():
        if key.startswith("basic"):
            for grid_key in REQUIRED_BASIC_KEYS:
                if grid_key in vals:
                    path = vals[grid_key]
                    if not os.path.isfile(path):
                        errors.append(f"Grid file not found: {grid_key}={path}")
                else:
                    errors.append(f"Missing required key '{grid_key}' in [Basic]")

    # Check forcing directories
    for key, vals in sections.items():
        if "forcing" in key:
            loc = vals.get("loc", "")
            if loc and not os.path.isdir(loc):
                errors.append(f"Forcing directory not found: LOC={loc}")
            elif loc:
                # Check for at least one file
                files = os.listdir(loc)
                if not files:
                    warnings.append(f"Forcing directory is empty: {loc}")

    # Check task output directory
    for key, vals in sections.items():
        if key.startswith("task"):
            output = vals.get("output", "")
            if output and not os.path.isdir(output):
                try:
                    os.makedirs(output, exist_ok=True)
                    warnings.append(f"Created output directory: {output}")
                except OSError as e:
                    errors.append(f"Cannot create output directory: {output} ({e})")

            # Check parameter grid files
            for pk, pv in vals.items():
                if pk.endswith("_grid"):
                    if not os.path.isfile(pv):
                        errors.append(f"Parameter grid not found: {pk}={pv}")

    # Check param set sections for grid references
    for key, vals in sections.items():
        if "paramset" in key:
            for pk, pv in vals.items():
                if pk.endswith("_grid") and not os.path.isfile(pv):
                    errors.append(f"Parameter grid not found: {pk}={pv}")

    return errors, warnings


def validate_outputs(control_path):
    """Validate model outputs after execution."""
    errors = []
    sections = parse_control_file(control_path)

    for key, vals in sections.items():
        if key.startswith("task"):
            output_dir = vals.get("output", "")
            if output_dir and os.path.isdir(output_dir):
                files = os.listdir(output_dir)
                if not files:
                    errors.append(f"No output files in {output_dir}")
                else:
                    # Check for time series files
                    ts_files = [f for f in files if f.endswith(".csv") or f.endswith(".txt")]
                    grid_files = [f for f in files if f.endswith(".tif") or f.endswith(".asc")]
                    if not ts_files and not grid_files:
                        errors.append(f"No recognizable output in {output_dir}")

    return errors


# ── Execution ──────────────────────────────────────────────────────────────

def run_ef5(binary_path, control_path, nthreads=1, timeout=3600, cwd=None):
    """Execute EF5 and capture output."""
    env = os.environ.copy()
    env["OMP_NUM_THREADS"] = str(nthreads)

    if cwd is None:
        cwd = os.path.dirname(os.path.abspath(control_path))

    print(f"  Binary: {binary_path}")
    print(f"  Config: {control_path}")
    print(f"  Threads: {nthreads}")
    print(f"  Working dir: {cwd}")

    start = time.time()

    try:
        result = subprocess.run(
            [binary_path, control_path],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            cwd=cwd,
        )
        elapsed = time.time() - start

        return {
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "elapsed_seconds": round(elapsed, 2),
            "success": result.returncode == 0,
        }
    except subprocess.TimeoutExpired:
        elapsed = time.time() - start
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": f"Process timed out after {timeout}s",
            "elapsed_seconds": round(elapsed, 2),
            "success": False,
        }
    except FileNotFoundError:
        return {
            "returncode": -2,
            "stdout": "",
            "stderr": f"Binary not found: {binary_path}",
            "elapsed_seconds": 0,
            "success": False,
        }


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Execute EF5/CREST model with preflight validation"
    )
    parser.add_argument("--binary", required=True, help="Path to ef5 binary")
    parser.add_argument("--control", required=True, help="Path to control.txt")
    parser.add_argument("--threads", type=int, default=1,
                        help="OpenMP thread count (default: 1)")
    parser.add_argument("--timeout", type=int, default=3600,
                        help="Execution timeout in seconds (default: 3600)")
    parser.add_argument("--log", help="Output JSON log file")
    parser.add_argument("--cwd", help="Working directory for execution")

    args = parser.parse_args()

    log = {"binary": args.binary, "control": args.control,
           "threads": args.threads, "stages": {}}

    # Step 1: Validate binary
    print("=== Step 1: Validating binary ===")
    errors = validate_binary(args.binary)
    if errors:
        for e in errors:
            print(f"ERROR: {e}")
        sys.exit(1)
    print("  Binary validation passed.")

    # Step 2: Validate control file
    print("=== Step 2: Validating control file ===")
    errors, warnings = validate_control_file(args.control)
    for w in warnings:
        print(f"  WARNING: {w}")
    if errors:
        for e in errors:
            print(f"  ERROR: {e}")
        print("\nPreflight checks failed. Fix errors above before running.")
        sys.exit(1)
    print("  Control file validation passed.")
    log["stages"]["preflight"] = {"status": "passed", "warnings": warnings}

    # Step 3: Execute
    print("=== Step 3: Running EF5 ===")
    result = run_ef5(args.binary, args.control, args.threads, args.timeout,
                     args.cwd)

    print(f"\n  Return code: {result['returncode']}")
    print(f"  Elapsed: {result['elapsed_seconds']}s")
    if result["stdout"]:
        print(f"  stdout (last 500 chars):\n{result['stdout'][-500:]}")
    if result["stderr"]:
        print(f"  stderr (last 500 chars):\n{result['stderr'][-500:]}")

    log["stages"]["execution"] = result

    if not result["success"]:
        print("\n  EF5 execution FAILED.")
        if args.log:
            with open(args.log, "w") as f:
                json.dump(log, f, indent=2)
        sys.exit(1)

    # Step 4: Validate outputs
    print("\n=== Step 4: Validating outputs ===")
    errors = validate_outputs(args.control)
    if errors:
        for e in errors:
            print(f"  WARNING: {e}")
    else:
        print("  Output validation passed.")

    log["stages"]["output_validation"] = {
        "status": "passed" if not errors else "warnings",
        "errors": errors,
    }

    if args.log:
        with open(args.log, "w") as f:
            json.dump(log, f, indent=2)
        print(f"\n  Log written to: {args.log}")

    print("\nDone.")


if __name__ == "__main__":
    main()
