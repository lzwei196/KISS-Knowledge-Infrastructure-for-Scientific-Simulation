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
import subprocess
import sys
import time
from pathlib import Path


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

            # Report continuity errors
            runoff_error = sim.runoff_error
            routing_error = sim.routing_error
            quality_error = sim.quality_error

            print(f"\n  Continuity Errors:")
            print(f"    Runoff:  {runoff_error:.3f}%")
            print(f"    Routing: {routing_error:.3f}%")
            print(f"    Quality: {quality_error:.3f}%")

            if abs(runoff_error) > 10 or abs(routing_error) > 10:
                print(f"\n  WARNING: Large continuity error (>10%)", file=sys.stderr)
                return 1

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
    """Parse .rpt file for key summary statistics."""
    if not os.path.isfile(rpt_path):
        return {}

    summary = {
        "runoff_continuity_error": None,
        "routing_continuity_error": None,
        "n_flooded_nodes": 0,
        "n_surcharging_links": 0,
    }

    with open(rpt_path, "r") as f:
        in_flooding = False
        for line in f:
            line = line.strip()
            if "Runoff Quantity Continuity" in line:
                # Look for error line
                pass
            if "Continuity Error" in line and "%" in line:
                parts = line.split()
                for i, p in enumerate(parts):
                    if "%" in p:
                        try:
                            val = float(p.replace("%", ""))
                            if summary["runoff_continuity_error"] is None:
                                summary["runoff_continuity_error"] = val
                            else:
                                summary["routing_continuity_error"] = val
                        except ValueError:
                            pass
            if "Node Flooding Summary" in line:
                in_flooding = True
            if in_flooding and line and not line.startswith("-") and not line.startswith("*"):
                parts = line.split()
                if parts and parts[0] not in ("No", "Node", "Flooding"):
                    summary["n_flooded_nodes"] += 1

    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Run a SWMM simulation"
    )
    parser.add_argument("--inp", required=True, help="SWMM .inp file")
    parser.add_argument("--rpt", default=None,
                        help="Report output path (default: <inp>.rpt)")
    parser.add_argument("--out", default=None,
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

    # Try pyswmm first, fall back to CLI
    result = run_with_pyswmm(inp_path, rpt_path, out_path)
    if result is None:
        print("pyswmm not available, trying CLI...", file=sys.stderr)
        result = run_with_cli(inp_path, rpt_path, out_path)

    # Parse report for summary
    if os.path.isfile(rpt_path):
        summary = parse_rpt_summary(rpt_path)
        if summary.get("n_flooded_nodes", 0) > 0:
            print(f"\n  Flooded nodes: {summary['n_flooded_nodes']}")

    if result == 0:
        print(f"\nSWMM simulation completed successfully")
        print(f"  Report: {rpt_path}")
        print(f"  Output: {out_path}")
    else:
        print(f"\nSWMM simulation failed (exit code {result})", file=sys.stderr)

    sys.exit(result)


if __name__ == "__main__":
    main()
