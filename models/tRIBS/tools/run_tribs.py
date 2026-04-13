#!/usr/bin/env python3
"""Execute tRIBS binary with preflight checks and output validation.

Performs:
  1. Pre-flight validation (binary exists, input file parseable, paths valid)
  2. Execute tRIBS with timeout and capture stdout/stderr
  3. Post-flight validation (output files created, no NaN in results)

Usage:
  python run_tribs.py \\
      --binary ./build/tRIBS \\
      --input my_basin.in \\
      --timeout 3600 \\
      --flags "-V"
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time


# ---------------------------------------------------------------------------
# Pre-flight validation
# ---------------------------------------------------------------------------

def parse_control_file(infile_path):
    """Parse tRIBS .in control file and return keyword-value dict.

    The control file uses a keyword-on-one-line, value-on-next-line format.
    Lines starting with # are comments.
    """
    params = {}
    with open(infile_path) as f:
        lines = [l.strip() for l in f.readlines()]

    i = 0
    while i < len(lines) - 1:
        line = lines[i]
        if line.startswith("#") or not line:
            i += 1
            continue
        # Check if this looks like a keyword (all uppercase with underscores)
        if re.match(r'^[A-Z][A-Z0-9_]*$', line):
            value = lines[i + 1].strip()
            params[line] = value
            i += 2
        else:
            i += 1

    return params


def validate_preflight(binary, infile, flags):
    """Validate that execution can proceed."""
    errors = []
    warnings = []

    # Check binary
    if not os.path.isfile(binary):
        errors.append(f"Binary not found: {binary}")
    elif not os.access(binary, os.X_OK):
        errors.append(f"Binary is not executable: {binary}")

    # Check input file
    if not os.path.isfile(infile):
        errors.append(f"Input file not found: {infile}")
    else:
        try:
            params = parse_control_file(infile)
        except Exception as e:
            errors.append(f"Cannot parse input file: {e}")
            params = {}

        # Validate critical paths referenced in control file
        path_keys = [
            "INPUTDATAFILE", "SOILTABLENAME", "LANDTABLENAME",
            "HYDROMETFILE", "RAINFILE", "RAINGAUGEFILE",
            "OUTFILENAME", "HYDRONODELIST",
        ]
        for key in path_keys:
            if key in params:
                val = params[key]
                if val and val != "0" and val != "NO_DATA":
                    # Check if it's a directory prefix or file
                    parent = os.path.dirname(val)
                    if parent and not os.path.isdir(parent):
                        warnings.append(
                            f"Directory for {key} does not exist: {parent}"
                        )

        # Validate timing
        metstep = params.get("METSTEP")
        if metstep:
            try:
                ms = float(metstep)
                if ms > 24:
                    warnings.append(
                        f"METSTEP={ms} hours is very large. "
                        "Did you provide minutes instead of hours? "
                        "tRIBS expects METSTEP in hours."
                    )
            except ValueError:
                pass

        # Check mesh option
        opt_mesh = params.get("OPTMESHINPUT")
        if opt_mesh:
            try:
                om = int(opt_mesh)
                if om not in range(10):
                    warnings.append(
                        f"OPTMESHINPUT={om} is not a recognized option (0–9)."
                    )
            except ValueError:
                pass

    return errors, warnings, params


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def run_tribs(binary, infile, flags, timeout, work_dir=None):
    """Execute tRIBS and capture output.

    Returns dict with: returncode, stdout, stderr, elapsed_s.
    """
    cmd = [binary, infile]
    if flags:
        cmd.extend(flags.split())

    start = time.time()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=work_dir,
        )
        elapsed = time.time() - start
        return {
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "elapsed_s": round(elapsed, 2),
        }
    except subprocess.TimeoutExpired:
        elapsed = time.time() - start
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": f"Process timed out after {timeout} seconds",
            "elapsed_s": round(elapsed, 2),
        }
    except Exception as e:
        return {
            "returncode": -2,
            "stdout": "",
            "stderr": str(e),
            "elapsed_s": 0,
        }


# ---------------------------------------------------------------------------
# Post-flight validation
# ---------------------------------------------------------------------------

def validate_postflight(params, run_result):
    """Validate that the run produced expected outputs."""
    warnings = []
    findings = []

    if run_result["returncode"] != 0:
        warnings.append(
            f"Non-zero exit code: {run_result['returncode']}"
        )
        # Check for common error patterns in stderr
        stderr = run_result["stderr"]
        if "Segmentation fault" in stderr or "SIGSEGV" in stderr:
            warnings.append("Segmentation fault — check mesh input files.")
        if "Cannot open" in stderr or "No such file" in stderr:
            warnings.append("File-not-found error — check all paths in .in file.")
        if "nan" in stderr.lower() or "NaN" in stderr:
            warnings.append("NaN detected — check forcing data for gaps.")

    # Check for output files
    outbase = params.get("OUTFILENAME", "")
    if outbase:
        out_dir = os.path.dirname(outbase) or "."
        if os.path.isdir(out_dir):
            out_files = os.listdir(out_dir)
            if not out_files:
                warnings.append(f"Output directory {out_dir} is empty.")
            else:
                findings.append(f"Output directory has {len(out_files)} files.")

    # Check stdout for simulation completion
    stdout = run_result["stdout"]
    if "Part 9: Deleting Objects" in stdout:
        findings.append("Simulation completed successfully (Part 9 reached).")
    elif "Part 8: Hydrologic Simulation Loop" in stdout:
        findings.append("Simulation started but may not have completed.")
    else:
        warnings.append("Could not confirm simulation completion from stdout.")

    for w in warnings:
        print(f"WARNING: {w}", file=sys.stderr)

    return warnings, findings


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Execute tRIBS binary with preflight checks."
    )
    parser.add_argument("--binary", required=True,
                        help="Path to tRIBS binary")
    parser.add_argument("--input", required=True,
                        help="Path to .in control file")
    parser.add_argument("--flags", default="",
                        help="Additional CLI flags (e.g., '-V 100')")
    parser.add_argument("--timeout", type=int, default=3600,
                        help="Timeout in seconds (default: 3600)")
    parser.add_argument("--work-dir", default=None,
                        help="Working directory for execution")
    parser.add_argument("--json-output", type=str, default=None,
                        help="Write result summary to JSON file")

    args = parser.parse_args()

    # --- Pre-flight ---
    errors, pre_warnings, params = validate_preflight(
        args.binary, args.input, args.flags
    )

    if errors:
        result = {
            "status": "preflight_error",
            "errors": errors,
            "warnings": pre_warnings,
        }
        print(json.dumps(result, indent=2))
        sys.exit(1)

    # --- Execute ---
    print(f"Running: {args.binary} {args.input} {args.flags}", file=sys.stderr)
    run_result = run_tribs(
        args.binary, args.input, args.flags,
        args.timeout, args.work_dir
    )

    # --- Post-flight ---
    post_warnings, findings = validate_postflight(params, run_result)

    result = {
        "status": "success" if run_result["returncode"] == 0 else "failed",
        "returncode": run_result["returncode"],
        "elapsed_s": run_result["elapsed_s"],
        "stdout_last_500": run_result["stdout"][-500:] if run_result["stdout"] else "",
        "stderr_last_500": run_result["stderr"][-500:] if run_result["stderr"] else "",
        "preflight_warnings": pre_warnings,
        "postflight_warnings": post_warnings,
        "findings": findings,
    }

    output_json = json.dumps(result, indent=2)
    if args.json_output:
        with open(args.json_output, "w") as f:
            f.write(output_json)
    print(output_json)


if __name__ == "__main__":
    main()
