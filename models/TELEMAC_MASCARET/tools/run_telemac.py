#!/usr/bin/env python3
"""
run_telemac.py - Execution wrapper for TELEMAC-MASCARET simulations.

Sets up the runtime environment (HOMETEL, PATH, LD_LIBRARY_PATH), validates
the steering file (.cas), and invokes the appropriate module runner script
(telemac2d.py, telemac3d.py, tomawac.py, etc.).

Usage:
    python run_telemac.py --cas simulation.cas --module telemac2d \
        --hometel /path/to/telemac

    python run_telemac.py --cas simulation.cas --module telemac3d \
        --hometel /path/to/telemac --nproc 8

    python run_telemac.py --cas coupled.cas --module telemac2d \
        --hometel /path/to/telemac --options "--ncsize 4"

Follows validate -> process -> validate pattern.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
VALID_MODULES = [
    "telemac2d", "telemac3d", "tomawac", "artemis",
    "gaia", "mascaret", "khione", "waqtel",
    "postel3d", "stbtel",
]

RUNNER_SCRIPTS = {
    "telemac2d": "telemac2d.py",
    "telemac3d": "telemac3d.py",
    "tomawac": "tomawac.py",
    "artemis": "artemis.py",
    "mascaret": "mascaret.py",
    "postel3d": "postel3d.py",
    "stbtel": "stbtel.py",
    "gaia": "telemac2d.py",  # gaia coupled with t2d
    "khione": "telemac2d.py",  # khione coupled with t2d
    "waqtel": "telemac2d.py",  # waqtel coupled with t2d
}


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------
def validate_inputs(args):
    """Check steering file, module, and environment."""
    errors = []

    # Check steering file
    if not os.path.isfile(args.cas):
        errors.append(f"Steering file not found: {args.cas}")

    # Check module
    if args.module not in VALID_MODULES:
        errors.append(f"Unknown module '{args.module}'. Valid: {VALID_MODULES}")

    # Check HOMETEL
    hometel = args.hometel or os.environ.get("HOMETEL", "")
    if not hometel:
        errors.append("HOMETEL not set. Use --hometel or set HOMETEL env var")
    elif not os.path.isdir(hometel):
        errors.append(f"HOMETEL directory does not exist: {hometel}")

    # Check runner script
    if hometel and os.path.isdir(hometel):
        runner = os.path.join(hometel, "scripts", "python3", RUNNER_SCRIPTS.get(args.module, ""))
        if not os.path.isfile(runner):
            errors.append(f"Runner script not found: {runner}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)

    return hometel


def validate_cas_file(cas_path):
    """Parse and validate critical keywords in the steering file."""
    warnings = []
    keywords = {}

    with open(cas_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("/"):
                continue
            if "=" in line or ":" in line:
                sep = "=" if "=" in line else ":"
                parts = line.split(sep, 1)
                key = parts[0].strip().upper()
                val = parts[1].strip().rstrip("/").strip()
                # Remove inline comments
                val = val.split("/")[0].strip()
                keywords[key] = val

    # Check required files
    for required in ["GEOMETRY FILE", "BOUNDARY CONDITIONS FILE"]:
        if required not in keywords:
            warnings.append(f"Missing keyword: {required}")
        else:
            fpath = keywords[required].strip("'\"")
            cas_dir = os.path.dirname(os.path.abspath(cas_path))
            full_path = os.path.join(cas_dir, fpath)
            if not os.path.isfile(full_path):
                warnings.append(f"{required} not found: {full_path}")

    # Check time parameters
    if "TIME STEP" in keywords:
        try:
            dt = float(keywords["TIME STEP"])
            if dt <= 0:
                warnings.append(f"TIME STEP must be positive, got {dt}")
            elif dt > 3600:
                warnings.append(f"TIME STEP = {dt}s seems very large (> 1 hour)")
        except ValueError:
            warnings.append(f"Cannot parse TIME STEP: {keywords['TIME STEP']}")

    # Check friction consistency
    friction_law = keywords.get("LAW OF BOTTOM FRICTION", "")
    friction_coeff = keywords.get("FRICTION COEFFICIENT", "")
    if friction_law and friction_coeff:
        try:
            law = int(friction_law)
            coeff = float(friction_coeff)
            if law == 4 and coeff > 1.0:  # Manning
                warnings.append(
                    f"Manning friction (law=4) with coefficient={coeff}. "
                    f"Manning n is typically 0.01-0.10. Did you mean Strickler (law=3)?")
            if law == 3 and coeff < 1.0:  # Strickler
                warnings.append(
                    f"Strickler friction (law=3) with coefficient={coeff}. "
                    f"Strickler K is typically 10-90. Did you mean Manning (law=4)?")
        except ValueError:
            pass

    return keywords, warnings


def validate_output(cas_path, keywords, run_dir):
    """Check that the results file was produced."""
    results_file = keywords.get("RESULTS FILE", "").strip("'\"")
    if results_file:
        # Results are written to the run directory
        expected = os.path.join(run_dir, results_file)
        if os.path.isfile(expected):
            size_mb = os.path.getsize(expected) / (1024 * 1024)
            return {"status": "success", "results_file": expected,
                    "size_mb": round(size_mb, 2)}
        else:
            # Check in cas directory
            cas_dir = os.path.dirname(os.path.abspath(cas_path))
            alt = os.path.join(cas_dir, results_file)
            if os.path.isfile(alt):
                size_mb = os.path.getsize(alt) / (1024 * 1024)
                return {"status": "success", "results_file": alt,
                        "size_mb": round(size_mb, 2)}
    return {"status": "warning", "message": "Results file not found after run"}


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------
def run_simulation(hometel, module, cas_path, nproc, extra_options):
    """Execute the TELEMAC simulation."""
    scripts_dir = os.path.join(hometel, "scripts", "python3")
    runner = os.path.join(scripts_dir, RUNNER_SCRIPTS[module])

    # Build environment
    env = os.environ.copy()
    env["HOMETEL"] = hometel
    env["PATH"] = scripts_dir + ":" + env.get("PATH", "")

    # Build command
    cmd = [sys.executable, runner, cas_path]
    if nproc and nproc > 1:
        cmd.extend(["--ncsize", str(nproc)])
    if extra_options:
        cmd.extend(extra_options.split())

    print(f"Running: {' '.join(cmd)}", file=sys.stderr)
    print(f"Working directory: {os.path.dirname(os.path.abspath(cas_path))}", file=sys.stderr)

    start_time = time.time()
    result = subprocess.run(
        cmd,
        cwd=os.path.dirname(os.path.abspath(cas_path)),
        env=env,
        capture_output=True,
        text=True,
        timeout=7200,  # 2 hour timeout
    )
    elapsed = time.time() - start_time

    return {
        "returncode": result.returncode,
        "stdout": result.stdout[-2000:] if result.stdout else "",
        "stderr": result.stderr[-2000:] if result.stderr else "",
        "elapsed_s": round(elapsed, 2),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Run TELEMAC-MASCARET simulation")
    parser.add_argument("--cas", required=True, help="Steering file (.cas)")
    parser.add_argument("--module", required=True, choices=VALID_MODULES,
                        help="TELEMAC module to run")
    parser.add_argument("--hometel", default=None, help="TELEMAC root directory")
    parser.add_argument("--nproc", type=int, default=1, help="Number of MPI processes")
    parser.add_argument("--options", default="", help="Extra options for runner script")
    parser.add_argument("--dry-run", action="store_true", help="Validate only, do not run")
    args = parser.parse_args()

    # Step 1: Validate inputs
    hometel = validate_inputs(args)

    # Step 2: Validate steering file
    keywords, warnings = validate_cas_file(args.cas)
    if warnings:
        for w in warnings:
            print(f"WARNING: {w}", file=sys.stderr)

    if args.dry_run:
        print(json.dumps({
            "status": "validated",
            "module": args.module,
            "cas": args.cas,
            "keywords_found": len(keywords),
            "warnings": warnings,
        }))
        return

    # Step 3: Run simulation
    run_result = run_simulation(hometel, args.module, args.cas, args.nproc, args.options)

    if run_result["returncode"] != 0:
        print(json.dumps({
            "status": "error",
            "returncode": run_result["returncode"],
            "elapsed_s": run_result["elapsed_s"],
            "stderr_tail": run_result["stderr"][-500:],
        }))
        sys.exit(1)

    # Step 4: Validate output
    run_dir = os.path.dirname(os.path.abspath(args.cas))
    output_check = validate_output(args.cas, keywords, run_dir)
    output_check["elapsed_s"] = run_result["elapsed_s"]
    output_check["module"] = args.module
    print(json.dumps(output_check))


if __name__ == "__main__":
    main()
