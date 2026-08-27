#!/usr/bin/env python3
"""
run_bgc.py
Execute BIOME-BGC in normal (production) simulation mode.

Runs the model with:
  - Read restart file from spinup (recommended) or cold start
  - Actual meteorological forcing for the target period
  - Daily and annual output enabled
  - ASCII output format (-a flag)

The .ini file MUST have mode=normal (spinup flag = 0), read_restart = 1
(unless cold-starting), and output variables configured.

Usage:
    python run_bgc.py \\
        --bgc_binary /path/to/bgc \\
        --ini_file normal.ini \\
        --workdir /path/to/workdir \\
        --timeout 300

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import json
import argparse
import subprocess
import time
from pathlib import Path


def validate_inputs(args):
    """Validate inputs."""
    errors = []

    if not os.path.isfile(args.bgc_binary):
        errors.append(f"BGC binary not found: {args.bgc_binary}")
    if not os.path.isfile(args.ini_file):
        errors.append(f"INI file not found: {args.ini_file}")

    return errors


def find_output_prefix(ini_file):
    """Parse INI to find output file prefix."""
    with open(ini_file, 'r') as f:
        lines = f.readlines()

    in_output = False
    for line in lines:
        if 'OUTPUT_CONTROL' in line and 'keyword' in line.lower():
            in_output = True
            continue
        if in_output and line.strip():
            return line.strip().split()[0]
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Run BIOME-BGC normal simulation")
    parser.add_argument("--bgc_binary", required=True,
                        help="Path to bgc executable")
    parser.add_argument("--ini_file", required=True,
                        help="Path to normal-mode .ini file")
    parser.add_argument("--workdir", default=None,
                        help="Working directory")
    parser.add_argument("--timeout", type=int, default=300,
                        help="Timeout in seconds")
    parser.add_argument("--ascii", action="store_true", default=True,
                        help="Output ASCII files (default True)")

    args = parser.parse_args()

    # Validate
    errors = validate_inputs(args)
    if errors:
        result = {"status": "error", "stage": "input_validation",
                  "errors": errors}
        print(json.dumps(result, indent=2))
        sys.exit(1)

    workdir = Path(args.workdir) if args.workdir else Path(args.ini_file).parent
    workdir = workdir.resolve()

    # Build command
    cmd = [
        str(Path(args.bgc_binary).resolve()),
        "-m",       # force model (normal) mode
        "-v", "2",  # progress output
    ]
    if args.ascii:
        cmd.append("-a")  # ASCII output

    cmd.append(str(Path(args.ini_file).resolve()))

    # Ensure output directories exist
    output_prefix = find_output_prefix(args.ini_file)
    if output_prefix:
        out_dir = workdir / Path(output_prefix).parent
        out_dir.mkdir(parents=True, exist_ok=True)

    start_time = time.time()

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(workdir),
            capture_output=True,
            text=True,
            timeout=args.timeout,
        )
    except subprocess.TimeoutExpired:
        result = {"status": "error", "stage": "execution",
                  "message": f"Timed out after {args.timeout}s"}
        print(json.dumps(result, indent=2))
        sys.exit(2)

    elapsed = time.time() - start_time

    if proc.returncode != 0:
        result = {
            "status": "error",
            "stage": "execution",
            "returncode": proc.returncode,
            "stdout": proc.stdout[-2000:] if proc.stdout else "",
            "stderr": proc.stderr[-2000:] if proc.stderr else "",
        }
        print(json.dumps(result, indent=2))
        sys.exit(2)

    # Find output files
    output_files = {}
    if output_prefix:
        base = workdir / output_prefix
        for suffix in [".dayout.ascii", ".annout.ascii", ".monavgout.ascii",
                       ".annavgout.ascii", ".endpoint",
                       ".dayout", ".annout", ".monavgout", ".annavgout"]:
            candidate = Path(str(base) + suffix)
            if candidate.exists():
                output_files[suffix.lstrip(".")] = {
                    "path": str(candidate),
                    "size_bytes": candidate.stat().st_size,
                }

    # A normal run that produces no output file is a FAILURE even at rc 0:
    # BIOME-BGC copies the output prefix into char outprefix[100] with no
    # bounds check, so an over-long prefix makes the model exit 0, print
    # "Opened binary daily output file in write mode", and write nothing.
    if not output_files or all(v["size_bytes"] == 0 for v in output_files.values()):
        result = {
            "status": "error",
            "stage": "execution",
            "returncode": proc.returncode,
            "message": ("BIOME-BGC exited 0 but wrote no output files under prefix "
                        f"'{output_prefix}' ({len(output_prefix or '')} chars). "
                        "Prefixes longer than 99 chars overflow the model's "
                        "outprefix[100] buffer silently; use a short prefix relative "
                        "to --workdir (e.g. 'outputs/normal') and check the ini's "
                        "OUTPUT_CONTROL flags request daily/annual output."),
            "output_prefix": output_prefix,
            "stdout": proc.stdout[-2000:] if proc.stdout else "",
            "stderr": proc.stderr[-2000:] if proc.stderr else "",
        }
        print(json.dumps(result, indent=2))
        sys.exit(2)

    result = {
        "status": "success",
        "elapsed_seconds": round(elapsed, 1),
        "returncode": proc.returncode,
        "output_prefix": output_prefix,
        "output_files": output_files,
        "stdout_tail": (proc.stdout or "")[-500:],
    }
    print(json.dumps(result, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
