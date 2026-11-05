#!/usr/bin/env python3
"""
Run a SWMM simulation.

Executes a SWMM model using pyswmm (Python wrapper for EPA SWMM 5.1+).
Reports runtime, continuity errors, and warnings. Generates the standard
SWMM output files (.rpt report and .out binary results).

If pyswmm is not available, falls back to calling the swmm5 CLI executable
directly.

Inputs:
  - SWMM .inp file

Outputs:
  - .rpt report file
  - .out binary output file
  - Console summary (runtime, errors, warnings)
"""

import argparse
import os
import math
import subprocess
import sys
import time
from pathlib import Path

try:
    from .check_continuity_errors import parse_rpt_file
except ImportError:  # direct CLI invocation
    from check_continuity_errors import parse_rpt_file


def run_with_pyswmm(inp_path, rpt_path, out_path):
    """Run SWMM using pyswmm library."""
    try:
        from pyswmm import Simulation
    except ImportError:
        return None  # signal to try fallback

    print(f"Running SWMM via pyswmm...")
    print(f"  Input:  {inp_path}")
    print(f"  Report: {rpt_path}")
    print(f"  Output: {out_path}")

    start_time = time.time()

    try:
        with Simulation(str(inp_path), str(rpt_path), str(out_path)) as sim:
            # Print simulation info
            print(f"  Flow units: {sim.flow_units}")
            print(f"  System units: {sim.system_units}")

            step_count = 0
            for step in sim:
                step_count += 1
                # Print progress every 1000 steps
                if step_count % 1000 == 0:
                    pct = sim.percent_complete * 100
                    print(f"  Progress: {pct:.1f}%", end="\r")

            elapsed = time.time() - start_time
            print(f"\n  Completed in {elapsed:.1f} seconds ({step_count} steps)")

        # swmm_end (called by __exit__) finalizes the continuity balances.
        # The main function validates the completed report after this context.

    except Exception as e:
        elapsed = time.time() - start_time
        print(f"\n  SWMM ERROR after {elapsed:.1f}s: {e}", file=sys.stderr)
        return 2

    return 0


def run_with_cli(inp_path, rpt_path, out_path):
    """Run SWMM using command-line executable."""
    # Search for swmm5 executable
    exe_names = ["swmm5", "runswmm", "epaswmm5"]
    exe_path = None

    for name in exe_names:
        # Check common locations
        for directory in ["/usr/local/bin", "/usr/bin", os.path.expanduser("~/.local/bin")]:
            candidate = os.path.join(directory, name)
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                exe_path = candidate
                break
        if exe_path:
            break

    if not exe_path:
        # Try using 'which'
        for name in exe_names:
            try:
                result = subprocess.run(["which", name], capture_output=True, text=True)
                if result.returncode == 0:
                    exe_path = result.stdout.strip()
                    break
            except FileNotFoundError:
                continue

    if not exe_path:
        print("ERROR: SWMM executable not found. Install pyswmm or EPA SWMM CLI.",
              file=sys.stderr)
        print("  pip install pyswmm", file=sys.stderr)
        return 3

    print(f"Running SWMM via CLI: {exe_path}")
    print(f"  Input:  {inp_path}")
    print(f"  Report: {rpt_path}")
    print(f"  Output: {out_path}")

    start_time = time.time()
    try:
        result = subprocess.run(
            [exe_path, str(inp_path), str(rpt_path), str(out_path)],
            capture_output=True, text=True, timeout=3600,
        )
        elapsed = time.time() - start_time
        print(f"  Completed in {elapsed:.1f} seconds")

        if result.stdout:
            print(result.stdout)
        if result.returncode != 0:
            print(f"  SWMM returned exit code {result.returncode}", file=sys.stderr)
            if result.stderr:
                print(result.stderr, file=sys.stderr)
            return result.returncode

    except subprocess.TimeoutExpired:
        print("ERROR: SWMM timed out after 3600 seconds", file=sys.stderr)
        return 4
    except Exception as e:
        print(f"ERROR: Failed to run SWMM: {e}", file=sys.stderr)
        return 5

    return 0


def parse_rpt_summary(rpt_path):
    """Read finalized EPA report syntax using the shared continuity parser."""
    result = parse_rpt_file(rpt_path)
    return {
        "runoff_continuity_error": result["runoff_error_pct"],
        "routing_continuity_error": result["routing_error_pct"],
        "n_flooded_nodes": len(result["flooded_nodes"]),
        "n_surcharging_links": len(result["surcharging_links"]),
        "report": result,
    }


def required_balances(inp_path):
    """Mirror the engine's massbal_report conditions for water balances."""
    sections = set()
    options = {}
    uses_runoff_file = False
    subcatch_area = 0.0
    section = None
    for line in Path(inp_path).read_text(encoding="latin-1").splitlines():
        line = line.split(";", 1)[0].strip()
        if line.startswith("["):
            section = line.upper()
        elif line:
            sections.add(section)
            if section == "[OPTIONS]":
                fields = line.upper().split()
                if len(fields) >= 2:
                    options[fields[0]] = fields[1]
            elif section == "[SUBCATCHMENTS]":
                # Name RainGage Outlet Area ...; an unreadable area counts as
                # contributing so the runoff balance stays required.
                fields = line.split()
                try:
                    area = float(fields[3])
                    subcatch_area += area if math.isfinite(area) else float("inf")
                except (IndexError, ValueError):
                    subcatch_area = float("inf")
            elif section == "[FILES]":
                fields = line.upper().split()
                if fields[:2] == ["USE", "RUNOFF"]:
                    uses_runoff_file = True
    required = []
    # With [FILES] USE RUNOFF, report_writeRunoffError prints "Runoff supplied
    # by interface file" and no runoff balance (EPA report.c), so none is required.
    # massbal_report/report_writeRunoffError skip the runoff table when the
    # total subcatchment area is zero (EPA massbal.c, report.c).
    if "[SUBCATCHMENTS]" in sections and not uses_runoff_file and subcatch_area > 0:
        required.append("runoff_error_pct")
    if (sections & {"[JUNCTIONS]", "[OUTFALLS]", "[STORAGE]", "[DIVIDERS]"}
            and options.get("IGNORE_ROUTING") != "YES"):
        required.append("routing_error_pct")
    return required


def continuity_report_off(inp_path):
    """True when [REPORT] CONTINUITY NO is set (balances then print only above 10%)."""
    section = None
    for line in Path(inp_path).read_text(encoding="latin-1").splitlines():
        line = line.split(";", 1)[0].strip()
        if line.startswith("["):
            section = line.upper()
        elif section == "[REPORT]" and line.upper().split()[:2] == ["CONTINUITY", "NO"]:
            return True
    return False


def validate_completed_report(inp_path, rpt_path, threshold=10.0):
    """Fail closed on missing/non-finite balances or engine errors."""
    if not Path(rpt_path).is_file():
        print("ERROR: SWMM did not write a report", file=sys.stderr)
        return 2
    report = parse_rpt_file(rpt_path)
    required = set(required_balances(inp_path))
    required.update(report["continuity_sections"])
    if (not required or report["continuity_errors"] or report["simulation_errors"]
            or report["table_errors"]
            or any(report.get(k) is None or not math.isfinite(report[k]) for k in required)):
        print("ERROR: Missing/non-finite continuity balance, unreadable report table "
              "or simulation error; see the report", file=sys.stderr)
        for problem in report["continuity_errors"] + report["table_errors"]:
            print(f"  {problem}", file=sys.stderr)
        if continuity_report_off(inp_path):
            print("  [REPORT] CONTINUITY NO hides balances below 10%; set CONTINUITY YES "
                  "so they can be checked", file=sys.stderr)
        return 2
    print("\n  Final continuity errors:")
    for key in sorted(required):
        print(f"    {key}: {report[key]:.3f}%")
    if any(abs(report[k]) > threshold for k in required):
        print(f"ERROR: Continuity error exceeds {threshold:g}%", file=sys.stderr)
        return 1
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Run a SWMM simulation"
    )
    parser.add_argument("--inp", "--inp_file", required=True, help="SWMM .inp file")
    parser.add_argument("--rpt", "--rpt_file", default=None,
                        help="Report output path (default: <inp>.rpt)")
    parser.add_argument("--out", "--out_file", default=None,
                        help="Binary output path (default: <inp>.out)")
    args = parser.parse_args()

    if not os.path.isfile(args.inp):
        print(f"ERROR: Input file not found: {args.inp}", file=sys.stderr)
        sys.exit(1)

    inp_path = Path(args.inp)
    rpt_path = Path(args.rpt) if args.rpt else inp_path.with_suffix(".rpt")
    out_path = Path(args.out) if args.out else inp_path.with_suffix(".out")

    # Ensure output directory exists
    rpt_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Refuse to certify a stale report if a backend returns success without writing.
    previous_report = rpt_path.stat() if rpt_path.exists() else None
    # Try pyswmm first, fall back to CLI
    result = run_with_pyswmm(inp_path, rpt_path, out_path)
    if result is None:
        print("pyswmm not available, trying CLI...", file=sys.stderr)
        result = run_with_cli(inp_path, rpt_path, out_path)

    if result == 0:
        current_report = rpt_path.stat() if rpt_path.exists() else None
        def write_signature(stat):
            return None if stat is None else (stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
        if previous_report is not None and write_signature(current_report) == write_signature(previous_report):
            print("ERROR: SWMM did not replace the previous report", file=sys.stderr)
            result = 2
        else:
            result = validate_completed_report(inp_path, rpt_path)

    if result == 0:
        print(f"\nSWMM simulation completed successfully")
        print(f"  Report: {rpt_path}")
        print(f"  Output: {out_path}")
    else:
        print(f"\nSWMM simulation failed (exit code {result})", file=sys.stderr)

    sys.exit(result)


if __name__ == "__main__":
    main()
