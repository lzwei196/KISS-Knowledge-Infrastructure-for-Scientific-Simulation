#!/usr/bin/env python3
"""
run_monica.py — Execute the MONICA model binary with preflight checks

Wraps the monica-run CLI executable, performing:
  1. Preflight validation (binary, input files, MONICA_PARAMETERS)
  2. Model execution with timeout
  3. Post-run validation (output file existence, non-empty)

Usage:
    python run_monica.py --binary ./monica-run --sim-json sim.json \
        --output out.csv --parameters-dir /path/to/monica-parameters

    python run_monica.py --binary ./monica-run --sim-json sim.json \
        --output out.csv --timeout 600
"""

import argparse
import json
import os
import subprocess
import sys
import time


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_inputs(args):
    """Preflight checks before running MONICA."""
    errors = []
    warnings = []

    # Check binary
    if not os.path.isfile(args.binary):
        errors.append(f"MONICA binary not found: {args.binary}")
    elif not os.access(args.binary, os.X_OK):
        errors.append(f"MONICA binary not executable: {args.binary}")

    # Check sim.json
    if not os.path.isfile(args.sim_json):
        errors.append(f"sim.json not found: {args.sim_json}")
    else:
        try:
            with open(args.sim_json, "r") as f:
                sim = json.load(f)
            # Check referenced files
            sim_dir = os.path.dirname(os.path.abspath(args.sim_json))
            for key in ["crop.json", "site.json", "climate.csv"]:
                ref = sim.get(key, "")
                if ref:
                    ref_path = os.path.join(sim_dir, ref) if not os.path.isabs(ref) else ref
                    if not os.path.isfile(ref_path):
                        warnings.append(f"Referenced file not found: {key} → {ref_path}")
        except json.JSONDecodeError as e:
            errors.append(f"sim.json is not valid JSON: {e}")

    # Check MONICA_PARAMETERS
    params_dir = args.parameters_dir or os.environ.get("MONICA_PARAMETERS", "")
    if not params_dir:
        errors.append("MONICA_PARAMETERS not set. Use --parameters-dir or set env variable.")
    elif not os.path.isdir(params_dir):
        errors.append(f"MONICA_PARAMETERS directory not found: {params_dir}")
    else:
        # Check for critical subdirectories
        for subdir in ["crops", "mineral-fertilisers"]:
            check = os.path.join(params_dir, subdir)
            if not os.path.isdir(check):
                warnings.append(f"Expected subdirectory not found: {check}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors, "warnings": warnings}),
              file=sys.stderr)
        sys.exit(1)

    return warnings


def validate_outputs(output_path, stdout_text, stderr_text):
    """Post-run checks on MONICA output."""
    warnings = []

    if not os.path.isfile(output_path):
        warnings.append(f"Output file not created: {output_path}")
        return warnings

    size_bytes = os.path.getsize(output_path)
    if size_bytes == 0:
        warnings.append("Output file is empty (0 bytes)")
        return warnings

    # Count data rows (subtract header rows)
    with open(output_path, "r") as f:
        lines = f.readlines()
    n_total = len(lines)
    # MONICA outputs 3+ header rows
    n_data = max(0, n_total - 4)
    if n_data == 0:
        warnings.append("Output file has header rows but no data")

    warnings.append(f"Output: {n_data} data rows, {size_bytes / 1024:.1f} KB")

    # Check stderr for warnings
    if stderr_text:
        for line in stderr_text.strip().split("\n"):
            if "error" in line.lower() or "warning" in line.lower():
                warnings.append(f"MONICA stderr: {line.strip()[:200]}")

    return warnings


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def run_monica(args):
    """Execute the MONICA binary."""
    cmd = [os.path.abspath(args.binary)]

    # Build command-line arguments
    if args.output:
        cmd.extend(["-o", args.output])
    if args.start_date:
        cmd.extend(["--start-date", args.start_date])
    if args.end_date:
        cmd.extend(["--end-date", args.end_date])
    if args.debug:
        cmd.append("--debug")

    cmd.append(args.sim_json)

    # Set environment
    env = os.environ.copy()
    if args.parameters_dir:
        env["MONICA_PARAMETERS"] = os.path.abspath(args.parameters_dir)

    # Run
    run_dir = os.path.dirname(os.path.abspath(args.sim_json))

    print(f"Running: {' '.join(cmd)}", file=sys.stderr)
    print(f"Working dir: {run_dir}", file=sys.stderr)
    print(f"MONICA_PARAMETERS: {env.get('MONICA_PARAMETERS', 'NOT SET')}", file=sys.stderr)

    t0 = time.time()
    try:
        proc = subprocess.run(
            cmd,
            cwd=run_dir,
            env=env,
            capture_output=True,
            text=True,
            timeout=args.timeout,
        )
    except subprocess.TimeoutExpired:
        elapsed = time.time() - t0
        return {
            "status": "timeout",
            "elapsed_s": round(elapsed, 1),
            "timeout_s": args.timeout,
            "command": " ".join(cmd),
        }

    elapsed = time.time() - t0

    return {
        "returncode": proc.returncode,
        "elapsed_s": round(elapsed, 1),
        "stdout": proc.stdout[:2000] if proc.stdout else "",
        "stderr": proc.stderr[:2000] if proc.stderr else "",
        "command": " ".join(cmd),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Execute MONICA model with preflight and post-run validation")
    parser.add_argument("--binary", required=True, help="Path to monica-run binary")
    parser.add_argument("--sim-json", required=True, help="Path to sim.json")
    parser.add_argument("--output", default="out.csv", help="Output CSV path")
    parser.add_argument("--parameters-dir", help="Path to monica-parameters directory")
    parser.add_argument("--start-date", help="Override start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", help="Override end date (YYYY-MM-DD)")
    parser.add_argument("--debug", action="store_true", help="Enable debug output")
    parser.add_argument("--timeout", type=int, default=300, help="Timeout in seconds")

    args = parser.parse_args()
    preflight_warnings = validate_inputs(args)

    result = run_monica(args)

    if result.get("status") == "timeout":
        result["preflight_warnings"] = preflight_warnings
        print(json.dumps(result, indent=2))
        sys.exit(1)

    # Determine output path
    output_path = args.output
    if not os.path.isabs(output_path):
        sim_dir = os.path.dirname(os.path.abspath(args.sim_json))
        output_path = os.path.join(sim_dir, output_path)

    postrun_warnings = validate_outputs(
        output_path,
        result.get("stdout", ""),
        result.get("stderr", ""),
    )

    final = {
        "status": "success" if result["returncode"] == 0 else "failed",
        "returncode": result["returncode"],
        "elapsed_s": result["elapsed_s"],
        "output_file": output_path,
        "command": result["command"],
        "preflight_warnings": preflight_warnings,
        "postrun_warnings": postrun_warnings,
        "stdout_head": result.get("stdout", "")[:500],
        "stderr_head": result.get("stderr", "")[:500],
    }
    print(json.dumps(final, indent=2))

    if result["returncode"] != 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
