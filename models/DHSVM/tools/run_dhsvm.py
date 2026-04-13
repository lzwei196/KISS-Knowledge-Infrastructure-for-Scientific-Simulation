#!/usr/bin/env python3
"""
run_dhsvm.py — Execution wrapper for DHSVM model binary.

Validates inputs, runs DHSVM, captures stdout/stderr, checks for
common failure modes, and reports results as JSON.

Usage:
  python run_dhsvm.py --binary build/DHSVM/sourcecode/DHSVM \\
      --config INPUT.MyBasin --output-dir output/

  python run_dhsvm.py --binary ./DHSVM --config INPUT.test \\
      --timeout 3600 --output run_report.json
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
    """Validate inputs before running DHSVM."""
    errors = []

    if not os.path.isfile(args.binary):
        errors.append(f"DHSVM binary not found: {args.binary}")
    elif not os.access(args.binary, os.X_OK):
        errors.append(f"DHSVM binary not executable: {args.binary}")

    if not os.path.isfile(args.config):
        errors.append(f"Configuration file not found: {args.config}")

    # Parse config to check for referenced files
    if os.path.isfile(args.config):
        config_dir = os.path.dirname(os.path.abspath(args.config))
        try:
            with open(args.config, "r") as f:
                config_text = f.read()

            # Check for DEM file
            dem_match = re.search(r"DEM\s+File\s*=\s*(.+)", config_text)
            if dem_match:
                dem_path = dem_match.group(1).strip()
                if not os.path.isabs(dem_path):
                    dem_path = os.path.join(config_dir, dem_path)
                if not os.path.isfile(dem_path):
                    errors.append(f"DEM file not found: {dem_path}")

            # Check for mask file
            mask_match = re.search(r"Basin\s+Mask\s+File\s*=\s*(.+)",
                                   config_text)
            if mask_match:
                mask_path = mask_match.group(1).strip()
                if not os.path.isabs(mask_path):
                    mask_path = os.path.join(config_dir, mask_path)
                if not os.path.isfile(mask_path):
                    errors.append(f"Mask file not found: {mask_path}")

            # Check output directory
            outdir_match = re.search(r"Output\s+Directory\s*=\s*(.+)",
                                     config_text)
            if outdir_match:
                out_path = outdir_match.group(1).strip()
                if not os.path.isabs(out_path):
                    out_path = os.path.join(config_dir, out_path)
                os.makedirs(out_path, exist_ok=True)

        except Exception as e:
            errors.append(f"Could not parse config file: {e}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}, indent=2))
        sys.exit(1)


def process(args):
    """Run DHSVM and capture output."""
    binary = os.path.abspath(args.binary)
    config = os.path.abspath(args.config)
    work_dir = os.path.dirname(config)

    cmd = [binary, config]

    print(f"Running: {' '.join(cmd)}", file=sys.stderr)
    print(f"Working directory: {work_dir}", file=sys.stderr)

    start_time = time.time()

    try:
        proc = subprocess.run(
            cmd,
            cwd=work_dir,
            capture_output=True,
            text=True,
            timeout=args.timeout,
        )
        elapsed = time.time() - start_time

        result = {
            "status": "success" if proc.returncode == 0 else "failed",
            "returncode": proc.returncode,
            "elapsed_seconds": round(elapsed, 2),
            "command": " ".join(cmd),
            "working_directory": work_dir,
            "stdout_lines": len(proc.stdout.splitlines()),
            "stderr_lines": len(proc.stderr.splitlines()),
            "stdout_head": proc.stdout[:2000],
            "stderr_head": proc.stderr[:2000],
            "stdout_tail": proc.stdout[-2000:] if len(proc.stdout) > 2000 else "",
            "stderr_tail": proc.stderr[-2000:] if len(proc.stderr) > 2000 else "",
        }

        # Extract mass balance from stderr
        mass_balance = extract_mass_balance(proc.stderr)
        if mass_balance:
            result["mass_balance"] = mass_balance

        # Check for common error patterns
        error_patterns = detect_errors(proc.stdout + proc.stderr)
        if error_patterns:
            result["detected_errors"] = error_patterns

    except subprocess.TimeoutExpired:
        elapsed = time.time() - start_time
        result = {
            "status": "timeout",
            "elapsed_seconds": round(elapsed, 2),
            "timeout_limit": args.timeout,
            "command": " ".join(cmd),
        }

    except Exception as e:
        result = {
            "status": "error",
            "errors": [str(e)],
            "command": " ".join(cmd),
        }

    return result


def extract_mass_balance(stderr_text):
    """Extract final mass balance information from DHSVM stderr."""
    balance = {}

    patterns = {
        "total_inflow_mm": r"Total Inflow\s*\.+\s*([\d.e+-]+)",
        "precip_mm": r"Precip/Inflow\s*\.+\s*([\d.e+-]+)",
        "total_outflow_mm": r"Total Outflow\s*\.+\s*([\d.e+-]+)",
        "et_mm": r"ET\s*\.+\s*([\d.e+-]+)",
        "channel_int_mm": r"ChannelInt\s*\.+\s*([\d.e+-]+)",
        "storage_change_mm": r"Storage Change\s*\.+\s*([\d.e+-]+)",
    }

    for key, pattern in patterns.items():
        match = re.search(pattern, stderr_text)
        if match:
            try:
                balance[key] = float(match.group(1))
            except ValueError:
                pass

    return balance if balance else None


def detect_errors(output_text):
    """Detect common DHSVM error patterns."""
    errors = []

    error_checks = [
        (r"Segmentation fault", "Segmentation fault - likely binary map "
         "size mismatch or corrupt input"),
        (r"NaN|nan|inf|-inf", "NaN or Inf detected - check reference "
         "height vs vegetation height"),
        (r"unable to open|cannot open|No such file",
         "File not found - check paths in config"),
        (r"Error.*reading", "Error reading input file - check format"),
        (r"GetInitString.*not found",
         "Missing config parameter - check section completeness"),
        (r"Assertion.*failed", "Assertion failure - internal consistency "
         "check violated"),
    ]

    for pattern, message in error_checks:
        if re.search(pattern, output_text, re.IGNORECASE):
            errors.append(message)

    return errors


def validate_outputs(result):
    """Validate run outputs."""
    if result.get("status") != "success":
        return result

    warnings = []

    # Check mass balance closure
    mb = result.get("mass_balance", {})
    if mb:
        inflow = mb.get("total_inflow_mm", 0)
        outflow = mb.get("total_outflow_mm", 0)
        storage = mb.get("storage_change_mm", 0)
        if inflow > 0:
            closure = abs(inflow - outflow - storage) / inflow * 100
            result["mass_balance_closure_pct"] = round(closure, 4)
            if closure > 1.0:
                warnings.append(f"Mass balance closure error: {closure:.2f}%")

    # Check for very short runtime (may indicate early exit)
    if result.get("elapsed_seconds", 0) < 1.0:
        warnings.append("Run completed in < 1 second. "
                        "May have exited early without error.")

    # Check for detected errors
    if result.get("detected_errors"):
        warnings.append(f"Detected {len(result['detected_errors'])} "
                        "potential errors in output")

    result["warnings"] = warnings
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Run DHSVM with input validation and output capture")
    parser.add_argument("--binary", required=True,
                        help="Path to DHSVM executable")
    parser.add_argument("--config", required=True,
                        help="Path to DHSVM input configuration file")
    parser.add_argument("--output-dir",
                        help="Override output directory in config")
    parser.add_argument("--timeout", type=int, default=7200,
                        help="Timeout in seconds (default: 7200)")
    parser.add_argument("--output", help="Output JSON report file")
    args = parser.parse_args()

    validate_inputs(args)
    result = process(args)
    result = validate_outputs(result)

    output_json = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            f.write(output_json)
        print(f"Report written to {args.output}", file=sys.stderr)
    else:
        print(output_json)


if __name__ == "__main__":
    main()
