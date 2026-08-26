#!/usr/bin/env python3
"""
run_rapid.py — Execute the RAPID binary with preflight checks and validation.

Wraps the RAPID executable with:
  1. Preflight validation of namelist and input files
  2. MPI execution with configurable process count
  3. Runtime monitoring (timeout, output capture)
  4. Post-run output validation

Usage:
  python run_rapid.py \\
    --rapid_bin /path/to/rapid \\
    --namelist /path/to/rapid_namelist \\
    --np 4 \\
    --timeout 3600 \\
    --work_dir /path/to/run_dir
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_inputs(args):
    """Preflight checks before executing RAPID."""
    errors = []
    warnings = []

    # Binary
    if not os.path.isfile(args.rapid_bin):
        errors.append(f"RAPID binary not found: {args.rapid_bin}")
    elif not os.access(args.rapid_bin, os.X_OK):
        errors.append(f"RAPID binary not executable: {args.rapid_bin}")

    # Namelist
    if not os.path.isfile(args.namelist):
        errors.append(f"Namelist not found: {args.namelist}")
    else:
        # Parse namelist for file references
        with open(args.namelist) as f:
            content = f.read()

        # Extract file paths from namelist
        file_refs = re.findall(r"(\w+_file)\s*=\s*'([^']+)'", content)
        for var, path in file_refs:
            if not os.path.isfile(path):
                if "Qout" in var or "Qfinal" in var or "V_file" in var:
                    # Output files don't need to exist yet
                    pass
                else:
                    errors.append(f"Input file referenced by {var} not found: {path}")

        # Check temporal consistency
        tau_m = re.search(r"ZS_TauM\s*=\s*(\d+)", content)
        tau_r = re.search(r"ZS_TauR\s*=\s*(\d+)", content)
        dt_r = re.search(r"ZS_dtR\s*=\s*(\d+)", content)

        if tau_m and tau_r:
            if int(tau_m.group(1)) % int(tau_r.group(1)) != 0:
                errors.append("ZS_TauM not divisible by ZS_TauR")

        if tau_r and dt_r:
            if int(tau_r.group(1)) % int(dt_r.group(1)) != 0:
                errors.append("ZS_TauR not divisible by ZS_dtR")

    # MPI
    if args.np < 1:
        errors.append(f"Number of processes must be >= 1, got {args.np}")
    if args.np > 1:
        mpiexec = args.mpiexec or "mpiexec"
        result = subprocess.run([mpiexec, "--version"], capture_output=True, text=True)
        if result.returncode != 0:
            warnings.append(f"mpiexec not found or failed — will try single-process run")

    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    for w in warnings:
        print(f"WARNING: {w}", file=sys.stderr)

    return warnings


def validate_outputs(work_dir, namelist_path):
    """Check RAPID produced expected output files."""
    warnings = []
    outputs = {}

    with open(namelist_path) as f:
        content = f.read()

    # Check Qout file
    qout_match = re.search(r"Qout_file\s*=\s*'([^']+)'", content)
    if qout_match:
        qout_path = qout_match.group(1)
        if os.path.isfile(qout_path):
            size = os.path.getsize(qout_path)
            outputs["Qout_file"] = {"path": qout_path, "size_bytes": size}
            if size < 1000:
                warnings.append(f"Qout file is only {size} bytes — may be empty or corrupt")
        else:
            warnings.append(f"Qout file not created: {qout_path}")

    # Check V file
    v_match = re.search(r"V_file\s*=\s*'([^']+)'", content)
    if v_match:
        v_path = v_match.group(1)
        if os.path.isfile(v_path):
            size = os.path.getsize(v_path)
            outputs["V_file"] = {"path": v_path, "size_bytes": size}

    # Check Qfinal file
    qfinal_match = re.search(r"Qfinal_file\s*=\s*'([^']+)'", content)
    if qfinal_match:
        qfinal_path = qfinal_match.group(1)
        if os.path.isfile(qfinal_path):
            outputs["Qfinal_file"] = {"path": qfinal_path,
                                       "size_bytes": os.path.getsize(qfinal_path)}

    for w in warnings:
        print(f"WARNING: {w}", file=sys.stderr)

    return outputs, warnings


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def build_command(args):
    """Build the RAPID execution command."""
    cmd = []

    if args.np > 1:
        mpiexec = args.mpiexec or "mpiexec"
        cmd.extend([mpiexec, "-n", str(args.np)])

    cmd.append(os.path.abspath(args.rapid_bin))

    # RAPID's CLI stores the namelist argument in a Fortran character(len=50)
    # variable (src/rapid_cli.F90 / rapid_var.f90). An absolute path longer than
    # 50 chars is silently TRUNCATED, producing
    #   "Cannot open file 'KISSPATH_KI_ROOT/RAPID/source/r'".
    # Pass the namelist as a path relative to the working directory (the binary
    # is launched with cwd=work_dir), which keeps it well under 50 chars.
    work_dir = args.work_dir or os.path.dirname(os.path.abspath(args.namelist))
    nl_rel = os.path.relpath(os.path.abspath(args.namelist), os.path.abspath(work_dir))
    nl_arg = nl_rel if len(nl_rel) <= 49 else os.path.abspath(args.namelist)
    cmd.extend(["--namelist", nl_arg])

    return cmd


def run_rapid(args):
    """Execute RAPID and capture output."""
    cmd = build_command(args)
    print(f"Executing: {' '.join(cmd)}")

    work_dir = args.work_dir or os.path.dirname(os.path.abspath(args.namelist))

    start_time = time.time()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=args.timeout,
            cwd=work_dir,
        )
        elapsed = time.time() - start_time
        status = "success" if result.returncode == 0 else "failed"

    except subprocess.TimeoutExpired:
        elapsed = args.timeout
        return {
            "status": "timeout",
            "elapsed_seconds": elapsed,
            "command": " ".join(cmd),
            "timeout": args.timeout,
        }

    report = {
        "status": status,
        "return_code": result.returncode,
        "elapsed_seconds": round(elapsed, 2),
        "command": " ".join(cmd),
        "stdout_last_lines": result.stdout.strip().split("\n")[-20:],
        "stderr_last_lines": result.stderr.strip().split("\n")[-20:],
    }

    return report


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def process(args):
    """Main pipeline: preflight → execute → validate outputs."""
    preflight_warnings = validate_inputs(args)

    exec_report = run_rapid(args)
    print(f"\nExecution: {exec_report['status']} in {exec_report.get('elapsed_seconds', '?')}s")

    if exec_report["status"] == "success":
        outputs, post_warnings = validate_outputs(
            args.work_dir or os.path.dirname(args.namelist),
            args.namelist
        )
        exec_report["output_files"] = outputs
        exec_report["post_warnings"] = post_warnings
    elif exec_report["status"] == "failed":
        print("\nSTDERR:", file=sys.stderr)
        for line in exec_report.get("stderr_last_lines", []):
            print(f"  {line}", file=sys.stderr)

    exec_report["preflight_warnings"] = preflight_warnings
    print(json.dumps(exec_report, indent=2))
    return exec_report


def main():
    parser = argparse.ArgumentParser(
        description="Execute RAPID binary with preflight checks and output validation")
    parser.add_argument("--rapid_bin", required=True, help="Path to RAPID executable")
    parser.add_argument("--namelist", required=True, help="Path to RAPID namelist file")
    parser.add_argument("--np", type=int, default=1, help="Number of MPI processes (default: 1)")
    parser.add_argument("--mpiexec", default=None, help="Path to mpiexec (default: system mpiexec)")
    parser.add_argument("--timeout", type=int, default=3600, help="Timeout in seconds (default: 3600)")
    parser.add_argument("--work_dir", default=None, help="Working directory for execution")
    args = parser.parse_args()

    process(args)


if __name__ == "__main__":
    main()
