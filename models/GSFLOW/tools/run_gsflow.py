#!/usr/bin/env python3
"""
Execute the GSFLOW model binary with pre/post validation.

Usage:
    python run_gsflow.py \
        --executable /path/to/gsflow \
        --control-file /path/to/gsflow.control \
        --timeout 7200

Pipeline Stage: s6 (Model Execution)
Follows: validate → process → validate pattern

Checks:
    Pre-run:  control file exists, all referenced files exist, binary is executable
    Run:      executes gsflow with control file, captures stdout/stderr
    Post-run: checks listing file for convergence, verifies output files created
"""

import os
import sys
import argparse
import subprocess
import time
import re


def validate_inputs(executable, control_file):
    """Validate executable and control file before running."""
    errors = []

    if not os.path.isfile(executable):
        errors.append(f"GSFLOW executable not found: {executable}")
    elif not os.access(executable, os.X_OK):
        errors.append(f"GSFLOW binary not executable: {executable} (run: chmod +x)")

    if not os.path.isfile(control_file):
        errors.append(f"Control file not found: {control_file}")
        if errors:
            for e in errors:
                print(f"ERROR: {e}", file=sys.stderr)
            return False
        return True

    # Parse control file to check referenced files
    control_dir = os.path.dirname(os.path.abspath(control_file))
    referenced_files = parse_control_file_paths(control_file, control_dir)

    for fpath, param_name in referenced_files:
        if not os.path.isfile(fpath):
            errors.append(f"Referenced file missing: {fpath} (param: {param_name})")

    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        return False

    print(f"  Pre-run validation PASSED ({len(referenced_files)} referenced files verified)")
    return True


def parse_control_file_paths(control_file, base_dir):
    """
    Parse control file to extract all referenced file paths.
    Returns list of (absolute_path, parameter_name) tuples.
    """
    referenced = []
    file_params = [
        "data_file", "param_file", "modflow_name",
        "tmax_day", "tmin_day", "precip_day", "potet_day", "swrad_day",
        "model_output_file", "gsflow_output_file", "csv_output_file",
        "var_init_file", "var_save_file", "stat_var_file"
    ]

    with open(control_file) as f:
        lines = f.readlines()

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line in file_params:
            param_name = line
            # Next lines: n_values, data_type, then values
            if i + 2 < len(lines):
                try:
                    n_values = int(lines[i + 1].strip())
                    data_type = int(lines[i + 2].strip())
                    if data_type == 4:  # string type
                        for j in range(n_values):
                            if i + 3 + j < len(lines):
                                fpath = lines[i + 3 + j].strip()
                                if fpath and fpath != "####":
                                    # Only check input files, not output files
                                    if "output" not in param_name.lower():
                                        abs_path = os.path.join(base_dir, fpath) if not os.path.isabs(fpath) else fpath
                                        referenced.append((abs_path, param_name))
                except (ValueError, IndexError):
                    pass
        i += 1

    return referenced


def run_model(executable, control_file, timeout=7200, working_dir=None):
    """
    Execute GSFLOW binary.

    Args:
        executable: path to gsflow binary
        control_file: path to control file
        timeout: max runtime in seconds (default 2 hours)
        working_dir: directory to run from (default: control file's directory)

    Returns:
        (return_code, stdout, stderr, elapsed_seconds)
    """
    if working_dir is None:
        working_dir = os.path.dirname(os.path.abspath(control_file))

    cmd = [os.path.abspath(executable), os.path.abspath(control_file)]
    print(f"  Running: {' '.join(cmd)}")
    print(f"  Working dir: {working_dir}")
    print(f"  Timeout: {timeout}s")

    start_time = time.time()
    try:
        result = subprocess.run(
            cmd,
            cwd=working_dir,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        elapsed = time.time() - start_time
        return result.returncode, result.stdout, result.stderr, elapsed
    except subprocess.TimeoutExpired:
        elapsed = time.time() - start_time
        return -1, "", f"TIMEOUT after {timeout}s", elapsed
    except Exception as e:
        elapsed = time.time() - start_time
        return -2, "", str(e), elapsed


def validate_outputs(control_file, stdout, stderr, return_code):
    """
    Validate model run by checking:
    1. Return code
    2. Listing file for errors/convergence
    3. Expected output files exist
    """
    errors = []
    warnings = []

    # Check return code
    if return_code != 0:
        if return_code == -1:
            errors.append("Model run TIMED OUT")
        elif return_code == -2:
            errors.append(f"Model run FAILED: {stderr}")
        else:
            errors.append(f"Non-zero return code: {return_code}")

    # Check stderr for fatal errors
    if stderr:
        for line in stderr.split("\n"):
            if "error" in line.lower() or "fatal" in line.lower():
                errors.append(f"STDERR: {line.strip()}")

    # Check stdout for common issues
    if stdout:
        if "FAILED TO MEET SOLVER CONVERGENCE" in stdout:
            warnings.append("MODFLOW solver failed to converge in some stress periods")
        if "ERROR" in stdout.upper():
            error_lines = [l for l in stdout.split("\n") if "ERROR" in l.upper()]
            for el in error_lines[:5]:
                errors.append(f"STDOUT error: {el.strip()}")

    # Check for output files
    control_dir = os.path.dirname(os.path.abspath(control_file))
    with open(control_file) as f:
        content = f.read()

    # Look for model_output_file and csv_output_file
    output_params = ["model_output_file", "gsflow_output_file", "csv_output_file"]
    for param in output_params:
        if param in content:
            # Extract path (simplified parsing)
            idx = content.index(param)
            remaining = content[idx:].split("####")[0]
            lines = remaining.strip().split("\n")
            if len(lines) >= 4:
                fpath = lines[3].strip()
                abs_path = os.path.join(control_dir, fpath) if not os.path.isabs(fpath) else fpath
                if os.path.isfile(abs_path):
                    size = os.path.getsize(abs_path)
                    print(f"  Output file: {fpath} ({size} bytes)")
                else:
                    warnings.append(f"Expected output not found: {fpath}")

    # Report
    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        return False

    if warnings:
        for w in warnings:
            print(f"WARNING: {w}", file=sys.stderr)

    print("  Post-run validation PASSED")
    return True


def main():
    parser = argparse.ArgumentParser(description="Run GSFLOW model with validation")
    parser.add_argument("--executable", required=True, help="Path to gsflow binary")
    parser.add_argument("--control-file", required=True, help="Path to control file")
    parser.add_argument("--timeout", type=int, default=7200, help="Max runtime seconds")
    parser.add_argument("--working-dir", default=None, help="Working directory")
    args = parser.parse_args()

    print("=" * 60)
    print("GSFLOW Execution Wrapper")
    print("=" * 60)

    # ── Step 1: Pre-run validation ──
    print(f"\n[1/3] Validating inputs")
    if not validate_inputs(args.executable, args.control_file):
        sys.exit(1)

    # ── Step 2: Run model ──
    print(f"\n[2/3] Running GSFLOW")
    rc, stdout, stderr, elapsed = run_model(
        args.executable, args.control_file, args.timeout, args.working_dir
    )
    print(f"  Completed in {elapsed:.1f}s (return code: {rc})")

    if stdout:
        # Print last 20 lines of stdout
        last_lines = stdout.strip().split("\n")[-20:]
        print("\n  --- Last 20 lines of stdout ---")
        for line in last_lines:
            print(f"  {line}")

    if stderr and rc != 0:
        print(f"\n  --- stderr ---")
        print(f"  {stderr[:500]}")

    # ── Step 3: Post-run validation ──
    print(f"\n[3/3] Validating outputs")
    success = validate_outputs(args.control_file, stdout, stderr, rc)

    if success:
        print(f"\nGSFLOW run completed successfully in {elapsed:.1f}s")
    else:
        print(f"\nGSFLOW run completed with errors (elapsed: {elapsed:.1f}s)")
        sys.exit(1)


if __name__ == "__main__":
    main()
