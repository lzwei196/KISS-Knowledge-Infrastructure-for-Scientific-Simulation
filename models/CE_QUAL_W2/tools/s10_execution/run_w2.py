#!/usr/bin/env python3
"""
run_w2.py — Execute CE-QUAL-W2 with preflight checks and output validation.

CE-QUAL-W2 reads its control file from the CURRENT WORKING DIRECTORY:
w2_con.csv for the v5 binary on this server (the DeGray example), w2_con.npt
for the v4.x fixed-width form. The binary must be run from the directory
containing all input files.

Preflight checks:
  1. w2_con.npt exists in run_dir
  2. All referenced input files exist (bth_wb*.npt, met_wb*.npt, qin_br*.npt, etc.)
  3. Binary exists and is executable
  4. File paths < 72 chars (dt_008)

Post-run checks:
  1. Exit code = 0
  2. w2l.opt exists and has no STOP errors
  3. Output files (snp, tsr, spr) exist and are non-empty (dt_025)

Usage:
    python run_w2.py --run_dir /path/to/run \
        --binary /path/to/w2_v5 \
        --timeout 7200
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path


W2_BINARY_DEFAULT = "KISSPATH_BINARIES/ce_qual_w2/bin/w2_v5"


def preflight_checks(run_dir, binary):
    """Run preflight checks before execution."""
    errors = []
    warnings = []

    # Check binary
    if not os.path.isfile(binary):
        errors.append(f"CE-QUAL-W2 binary not found: {binary}")
    elif not os.access(binary, os.X_OK):
        warnings.append(f"Binary may not be executable: {binary}")

    # Check the control file: v5 reads w2_con.csv, v4.x reads w2_con.npt
    w2_con_csv = os.path.join(run_dir, "w2_con.csv")
    w2_con = os.path.join(run_dir, "w2_con.npt")
    if os.path.isfile(w2_con_csv):
        # v5 CSV control file: a file-name row holds the name in its first field
        with open(w2_con_csv, errors="replace") as f:
            for line in f:
                first = line.split(",")[0].strip().strip('"')
                if re.fullmatch(r"[\w\-]+\.(npt|csv)", first) and \
                        re.match(r"(met|bth|qin|tin|cin|qot|qtr|ttr|ctr|qdt|tdt|pre|tpr|wsc|vpr|lpr|shade)",
                                 first, re.I):
                    # a warning, not an error: the control file also names the files of
                    # options that are switched off (the DeGray example has no lpr.npt,
                    # pre_br1.npt, ...); the binary stops with w2.err if it needs one
                    if not os.path.isfile(os.path.join(run_dir, first)):
                        warnings.append(f"Named in w2_con.csv but not in the run directory: {first}")
    elif not os.path.isfile(w2_con):
        errors.append(f"No control file (w2_con.csv for v5, w2_con.npt for v4.x) in run directory: {run_dir}")
    else:
        # Parse w2_con.npt for referenced files
        with open(w2_con) as f:
            content = f.read()

        # Check for file references
        for pattern in [r"bth_wb\d+\.npt", r"met_wb\d+\.npt", r"qin_br\d+\.npt",
                       r"tin_br\d+\.npt", r"qot_br\d+\.npt"]:
            for match in re.findall(pattern, content):
                fpath = os.path.join(run_dir, match)
                if not os.path.isfile(fpath):
                    errors.append(f"Referenced file not found: {fpath}")

        # Check path lengths (dt_008)
        for line in content.split("\n"):
            line = line.strip()
            if len(line) > 80 and ("FILE" in line or ".npt" in line):
                warnings.append(f"Possible path >72 chars in w2_con.npt: {line[:60]}...")

    # Check bathymetry file
    for wb in range(1, 10):
        bth = os.path.join(run_dir, f"bth_wb{wb}.npt")
        if os.path.isfile(bth):
            size = os.path.getsize(bth)
            if size < 50:
                errors.append(f"Bathymetry file too small ({size} bytes): {bth}")
            break

    return errors, warnings


def postrun_checks(run_dir):
    """Check output files after CE-QUAL-W2 run."""
    errors = []
    warnings = []

    # Check log file
    w2l = os.path.join(run_dir, "w2l.opt")
    if os.path.isfile(w2l):
        with open(w2l) as f:
            log_content = f.read()
        if "STOP" in log_content.upper() or "ERROR" in log_content.upper():
            # Extract error lines
            error_lines = [l for l in log_content.split("\n")
                          if "STOP" in l.upper() or "ERROR" in l.upper()]
            errors.append(f"w2l.opt contains errors: {'; '.join(error_lines[:3])}")
        if "NaN" in log_content or "Infinity" in log_content:
            warnings.append("w2l.opt contains NaN/Infinity — possible numerical instability (dt_023)")
    elif not os.path.isfile(os.path.join(run_dir, "w2_con.csv")):
        warnings.append("w2l.opt not found — model may not have run")

    # v5 writes its stop reasons to w2.err (the .w2l file of v5 is binary, not a log)
    w2err = os.path.join(run_dir, "w2.err")
    if os.path.isfile(w2err) and os.path.getsize(w2err) > 0:
        with open(w2err, errors="replace") as f:
            errors.append(f"w2.err: {f.read(600).strip()}")

    # Check output files exist and are non-empty (dt_025)
    output_found = False
    for pattern in ["snp_*.opt", "tsr_*.opt", "spr_*.opt", "snp.opt", "tsr_*.csv", "spr*.csv"]:
        for f in Path(run_dir).glob(pattern):
            if f.stat().st_size > 0:
                output_found = True
            else:
                warnings.append(f"Output file is empty: {f.name} (dt_025)")

    if not output_found:
        warnings.append("No output files found — check OUT FILE cards in w2_con.npt (dt_025)")

    return errors, warnings


def process(args):
    """Main processing."""
    run_dir = os.path.abspath(args.run_dir)
    binary = os.path.abspath(args.binary)

    # Preflight
    pre_errors, pre_warnings = preflight_checks(run_dir, binary)
    if pre_errors:
        result = {"status": "error", "phase": "preflight", "errors": pre_errors}
        if pre_warnings:
            result["warnings"] = pre_warnings
        print(json.dumps(result, indent=2))
        return 1

    # A stop reason left by an earlier run must not be read as this run's
    stale = os.path.join(run_dir, "w2.err")
    if os.path.isfile(stale):
        os.remove(stale)

    # Run CE-QUAL-W2
    print(f"Running CE-QUAL-W2 in {run_dir}...", file=sys.stderr)

    try:
        proc = subprocess.run(
            [binary],
            cwd=run_dir,
            capture_output=True,
            text=True,
            timeout=args.timeout
        )
        exit_code = proc.returncode
        stdout = proc.stdout
        stderr = proc.stderr
    except subprocess.TimeoutExpired:
        result = {"status": "error", "phase": "execution",
                  "errors": [f"Timeout after {args.timeout} seconds"]}
        print(json.dumps(result, indent=2))
        return 2
    except Exception as e:
        result = {"status": "error", "phase": "execution",
                  "errors": [f"Execution failed: {str(e)}"]}
        print(json.dumps(result, indent=2))
        return 2

    # Post-run checks
    post_errors, post_warnings = postrun_checks(run_dir)

    all_warnings = pre_warnings + post_warnings
    all_errors = post_errors

    if exit_code != 0:
        all_errors.insert(0, f"CE-QUAL-W2 exited with code {exit_code}")

    # Collect output files
    output_files = []
    for pattern in ["snp_*.opt", "tsr_*.opt", "spr_*.opt", "snp.opt", "tsr_*.csv", "spr*.csv", "*.nc"]:
        for f in Path(run_dir).glob(pattern):
            if f.stat().st_size > 0:
                output_files.append(str(f))

    result = {
        "status": "error" if all_errors else "success",
        "exit_code": exit_code,
        "run_dir": run_dir,
        "output_files": output_files,
        "n_output_files": len(output_files),
    }
    if all_errors:
        result["errors"] = all_errors
    if all_warnings:
        result["warnings"] = all_warnings
    if stdout.strip():
        result["stdout"] = stdout[:2000]
    if stderr.strip():
        result["stderr"] = stderr[:2000]

    print(json.dumps(result, indent=2))
    return 0 if not all_errors else 2


def main():
    parser = argparse.ArgumentParser(description="Run CE-QUAL-W2")
    parser.add_argument("--run_dir", required=True, help="Directory with the control file (w2_con.csv for v5, w2_con.npt for v4.x) and all input files")
    parser.add_argument("--binary", default=W2_BINARY_DEFAULT, help="Path to w2_v5")
    parser.add_argument("--timeout", type=int, default=7200, help="Timeout in seconds (default: 7200)")
    args = parser.parse_args()
    sys.exit(process(args))


if __name__ == "__main__":
    main()
