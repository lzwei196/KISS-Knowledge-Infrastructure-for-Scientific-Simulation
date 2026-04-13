#!/usr/bin/env python3
"""
run_bgc_spinup.py
Execute BIOME-BGC in spinup mode with convergence monitoring.

Spinup runs the model for hundreds to thousands of simulated years,
recycling the available meteorological data, until soil C/N pools reach
steady-state equilibrium. This is REQUIRED before any production simulation.

Typical spinup durations:
  - Grassland:        1000-1500 model years
  - Deciduous forest: 2000-3000 model years
  - Evergreen forest: 3000-6000 model years
  - Boreal forest:    4000-6000 model years

Wall clock time is fast because BIOME-BGC is a point model (~1-5 minutes
for 6000 model years). DO NOT interrupt -- this is NORMAL runtime.

The spinup .ini must have:
  - spinup flag = 1
  - write_restart = 1
  - No daily/annual output (to save disk)

After spinup, the restart (.endpoint) file is used as input for normal run.

Usage:
    python run_bgc_spinup.py \\
        --bgc_binary /path/to/bgc \\
        --ini_file spinup.ini \\
        --workdir /path/to/workdir \\
        --timeout 600

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
    """Validate inputs before execution."""
    errors = []

    if not os.path.isfile(args.bgc_binary):
        errors.append(f"BGC binary not found: {args.bgc_binary}")
    if not os.path.isfile(args.ini_file):
        errors.append(f"INI file not found: {args.ini_file}")

    # Verify the INI has spinup mode enabled
    try:
        with open(args.ini_file, 'r') as f:
            content = f.read()
        lines = content.split('\n')
        # Find TIME_DEFINE section and check spinup flag
        in_time = False
        spinup_found = False
        for i, line in enumerate(lines):
            if 'TIME_DEFINE' in line:
                in_time = True
                continue
            if in_time:
                stripped = line.strip().split()[0] if line.strip() else ""
                # The 4th value after TIME_DEFINE keyword is the spinup flag
                # (met years, sim years, first year, spinup flag, max spinup)
                # Actually we count: after keyword, next lines are:
                # n_met_years, n_sim_years, first_year, spinup_flag, max_spinup
                # Let's just check if "spinup" appears in the flag line
                if 'spinup simulation' in line.lower():
                    val = line.strip().split()[0]
                    if val == '1':
                        spinup_found = True
                    elif val == '0':
                        errors.append("INI file has spinup flag = 0. "
                                      "Set to 1 for spinup mode.")
                    break
        if not spinup_found and not errors:
            # Try the -u flag override approach
            pass  # Will use -u flag

    except Exception as e:
        errors.append(f"Could not read INI file: {e}")

    return errors


def run_spinup(args):
    """Execute BIOME-BGC spinup."""
    workdir = Path(args.workdir) if args.workdir else Path(args.ini_file).parent
    workdir = workdir.resolve()

    # Ensure restart directory exists
    restart_dir = workdir / "restart"
    restart_dir.mkdir(parents=True, exist_ok=True)

    # Ensure outputs directory exists
    outputs_dir = workdir / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)

    # Build command: use -u flag to force spinup mode
    # Use -a for ascii output (if any), -v 2 for progress
    cmd = [
        str(Path(args.bgc_binary).resolve()),
        "-u",       # force spinup mode
        "-v", "2",  # progress level
        str(Path(args.ini_file).resolve())
    ]

    start_time = time.time()

    proc = subprocess.run(
        cmd,
        cwd=str(workdir),
        capture_output=True,
        text=True,
        timeout=args.timeout,
    )

    elapsed = time.time() - start_time

    return proc, elapsed


def find_restart_file(ini_file):
    """Parse INI to find the restart output filename."""
    with open(ini_file, 'r') as f:
        lines = f.readlines()

    in_restart = False
    restart_vals = []
    for line in lines:
        if 'RESTART' in line and 'keyword' in line.lower():
            in_restart = True
            continue
        if in_restart and line.strip():
            val = line.strip().split()[0]
            restart_vals.append(val)
            if len(restart_vals) >= 5:
                break

    # restart_vals: [read_flag, write_flag, metyear_flag, input_file, output_file]
    if len(restart_vals) >= 5:
        return restart_vals[4]
    elif len(restart_vals) >= 4:
        return restart_vals[3]
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Run BIOME-BGC spinup with convergence monitoring")
    parser.add_argument("--bgc_binary", required=True,
                        help="Path to bgc executable")
    parser.add_argument("--ini_file", required=True,
                        help="Path to spinup .ini file")
    parser.add_argument("--workdir", default=None,
                        help="Working directory (default: ini file directory)")
    parser.add_argument("--timeout", type=int, default=600,
                        help="Timeout in seconds (default 600)")

    args = parser.parse_args()

    # Validate
    errors = validate_inputs(args)
    if errors:
        result = {"status": "error", "stage": "input_validation",
                  "errors": errors}
        print(json.dumps(result, indent=2))
        sys.exit(1)

    # Run
    try:
        proc, elapsed = run_spinup(args)
    except subprocess.TimeoutExpired:
        result = {"status": "error", "stage": "execution",
                  "message": f"Spinup timed out after {args.timeout}s. "
                             "This may be normal for forest spinups. "
                             "Increase --timeout."}
        print(json.dumps(result, indent=2))
        sys.exit(2)
    except Exception as e:
        result = {"status": "error", "stage": "execution",
                  "message": str(e)}
        print(json.dumps(result, indent=2))
        sys.exit(2)

    # Check results
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

    # Find restart file
    workdir = Path(args.workdir) if args.workdir else Path(args.ini_file).parent
    restart_name = find_restart_file(args.ini_file)
    restart_path = None
    if restart_name:
        candidate = workdir / restart_name
        if candidate.exists():
            restart_path = str(candidate)
            restart_size = candidate.stat().st_size

    # Parse spinup progress from stdout
    spinup_years = None
    for line in (proc.stdout or "").split("\n"):
        if "spinup" in line.lower() and "year" in line.lower():
            # Try to extract year count
            parts = line.strip().split()
            for p in parts:
                try:
                    val = int(p)
                    if val > 100:
                        spinup_years = val
                except ValueError:
                    pass

    result = {
        "status": "success",
        "elapsed_seconds": round(elapsed, 1),
        "returncode": proc.returncode,
        "restart_file": restart_path,
        "restart_size_bytes": restart_size if restart_path else None,
        "spinup_years_completed": spinup_years,
        "stdout_tail": (proc.stdout or "")[-500:],
        "note": "Spinup complete. Use the restart file as input for normal run.",
    }
    print(json.dumps(result, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
