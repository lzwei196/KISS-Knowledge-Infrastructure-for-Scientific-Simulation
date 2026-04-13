#!/usr/bin/env python3
"""
run_fates_case.py — FATES/CTSM Case Creation and Execution Wrapper

Creates, configures, builds, and optionally submits a CTSM single-point case
with FATES enabled. Wraps the CIME case management workflow.

Follows validate → process → validate pattern.

Usage:
    # Create and build a case (dry run)
    python run_fates_case.py --ctsm-root /path/to/CTSM --site-name BCI \
        --lat 9.15 --lon -79.85 --start 2000-01-01 --stop 2005-01-01 \
        --case-dir ~/cases/bci_fates --dry-run

    # Create, build, and submit
    python run_fates_case.py --ctsm-root /path/to/CTSM --site-name TestSite \
        --lat 45.0 --lon -90.0 --start 2000-01-01 --stop 2001-01-01 \
        --case-dir ~/cases/test_fates --compset I2000Clm51FatesRs \
        --submit

    # Modify FATES parameters before submission
    python run_fates_case.py --ctsm-root /path/to/CTSM --site-name BCI \
        --lat 9.15 --lon -79.85 --start 2000-01-01 --stop 2005-01-01 \
        --case-dir ~/cases/bci_custom --fates-params custom_params.json \
        --submit
"""

import argparse
import json
import os
import subprocess
import sys
import shutil
from datetime import datetime
from typing import Dict, List, Any, Optional

# ─── Default configuration ──────────────────────────────────────────────────
DEFAULT_COMPSET = "I2000Clm51FatesRs"
DEFAULT_RES = "f09_g17"
DEFAULT_MACHINE = "container"  # For generic Linux; override for HPC
DEFAULT_FATES_PARAMS = "fates_params_default.json"

# ─── CIME XML variable mappings for FATES ────────────────────────────────────
FATES_XML_SETTINGS = {
    "CLM_BLDNML_OPTS": "-bgc fates",
    "STOP_OPTION": "nyears",
    "RUN_STARTDATE": None,  # Set from --start
    "STOP_N": None,          # Computed from start/stop
    "DATM_CLMNCEP_YR_START": None,
    "DATM_CLMNCEP_YR_END": None,
}

# ─── Common FATES user_nl_clm settings ──────────────────────────────────────
FATES_NL_DEFAULTS = {
    "use_fates": ".true.",
    "use_fates_sp": ".false.",
    "use_fates_logging": ".false.",
    "use_fates_planthydro": ".false.",
    "use_fates_ed_st3": ".false.",
    "fates_spitfire_mode": "0",
    "use_fates_luh": ".false.",
    "use_fates_nocomp": ".false.",
    "use_fates_fixed_biogeog": ".false.",
    "fates_parteh_mode": "1",
}

# ─── History output configuration ───────────────────────────────────────────
FATES_HISTORY_VARS = [
    "FATES_GPP", "FATES_NPP", "FATES_AUTORESP", "FATES_VEGC",
    "FATES_LEAFC", "FATES_SAPWOODC", "FATES_STRUCTC", "FATES_STOREC",
    "FATES_LAI", "FATES_NPLANT", "FATES_MORTALITY",
    "FATES_DISTURBANCE_RATE_FIRE", "FATES_RECRUITMENT",
    "FATES_DDBH_CANOPY_SZPF", "FATES_NPLANT_SZPF",
]


def validate_inputs(args: argparse.Namespace) -> List[str]:
    """Stage 1: Validate inputs for case creation."""
    errors = []

    # Check CTSM root
    if not args.dry_run:
        if not os.path.isdir(args.ctsm_root):
            errors.append(f"CTSM root not found: {args.ctsm_root}")
        else:
            scripts_dir = os.path.join(args.ctsm_root, "cime", "scripts")
            if not os.path.isdir(scripts_dir):
                errors.append(
                    f"CIME scripts not found at {scripts_dir}. "
                    "Run ./manage_externals/checkout_externals first.")

            create_newcase = os.path.join(scripts_dir, "create_newcase")
            if not os.path.isfile(create_newcase):
                errors.append(f"create_newcase not found at {create_newcase}")

    # Validate coordinates
    if args.lat < -90 or args.lat > 90:
        errors.append(f"Latitude must be in [-90, 90], got {args.lat}")
    if args.lon < -180 or args.lon > 360:
        errors.append(f"Longitude out of range: {args.lon}")

    # Validate dates
    try:
        start = datetime.strptime(args.start, "%Y-%m-%d")
        stop = datetime.strptime(args.stop, "%Y-%m-%d")
        if stop <= start:
            errors.append(f"Stop date must be after start date")
    except ValueError as e:
        errors.append(f"Date format error (use YYYY-MM-DD): {e}")

    # Validate FATES params file
    if args.fates_params and not os.path.isfile(args.fates_params):
        errors.append(f"FATES parameter file not found: {args.fates_params}")

    # Check case directory doesn't already exist (unless --overwrite)
    if args.case_dir and os.path.exists(args.case_dir) and not args.overwrite:
        errors.append(
            f"Case directory already exists: {args.case_dir}. "
            "Use --overwrite to replace.")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}, indent=2),
              file=sys.stderr)
        sys.exit(1)

    return errors


def run_command(cmd: List[str], cwd: str = None,
                dry_run: bool = False) -> Dict[str, Any]:
    """Execute a shell command and capture output."""
    cmd_str = " ".join(cmd)

    if dry_run:
        print(f"  [DRY RUN] {cmd_str}", file=sys.stderr)
        return {"returncode": 0, "stdout": "[dry run]", "stderr": ""}

    print(f"  Running: {cmd_str}", file=sys.stderr)
    try:
        result = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=3600)
        return {
            "returncode": result.returncode,
            "stdout": result.stdout[-2000:] if result.stdout else "",
            "stderr": result.stderr[-2000:] if result.stderr else "",
        }
    except subprocess.TimeoutExpired:
        return {"returncode": -1, "stdout": "", "stderr": "Command timed out (1h)"}
    except FileNotFoundError as e:
        return {"returncode": -1, "stdout": "", "stderr": str(e)}


def create_case(args: argparse.Namespace) -> Dict[str, Any]:
    """Create a new CTSM case with FATES."""
    scripts_dir = os.path.join(args.ctsm_root, "cime", "scripts")
    create_newcase = os.path.join(scripts_dir, "create_newcase")

    # Remove existing case if overwrite
    if args.overwrite and os.path.exists(args.case_dir):
        if not args.dry_run:
            shutil.rmtree(args.case_dir)
        print(f"  Removed existing case: {args.case_dir}", file=sys.stderr)

    cmd = [
        create_newcase,
        "--case", args.case_dir,
        "--compset", args.compset,
        "--res", args.res,
        "--run-unsupported",
    ]

    if args.machine:
        cmd.extend(["--machine", args.machine])

    result = run_command(cmd, cwd=scripts_dir, dry_run=args.dry_run)

    if result["returncode"] != 0:
        return {"status": "failed", "stage": "create_newcase",
                "error": result["stderr"]}

    return {"status": "success", "stage": "create_newcase",
            "case_dir": args.case_dir}


def configure_case(args: argparse.Namespace) -> Dict[str, Any]:
    """Configure the case with FATES-specific settings."""
    start = datetime.strptime(args.start, "%Y-%m-%d")
    stop = datetime.strptime(args.stop, "%Y-%m-%d")
    n_years = max(1, (stop - start).days // 365)

    # XML changes
    xml_changes = {
        "RUN_STARTDATE": args.start,
        "STOP_OPTION": "nyears",
        "STOP_N": str(n_years),
        "DATM_CLMNCEP_YR_START": str(start.year),
        "DATM_CLMNCEP_YR_END": str(stop.year),
    }

    results = []
    for key, val in xml_changes.items():
        cmd = [os.path.join(args.case_dir, "xmlchange"), f"{key}={val}"]
        r = run_command(cmd, cwd=args.case_dir, dry_run=args.dry_run)
        results.append({"variable": key, "value": val,
                        "status": "ok" if r["returncode"] == 0 else "failed"})

    # Write user_nl_clm
    nl_path = os.path.join(args.case_dir, "user_nl_clm")
    nl_lines = []
    for key, val in FATES_NL_DEFAULTS.items():
        nl_lines.append(f"{key} = {val}")

    # Add FATES params file if specified
    if args.fates_params:
        abs_params = os.path.abspath(args.fates_params)
        nl_lines.append(f"fates_paramfile = '{abs_params}'")

    # Add custom FATES namelist options
    if args.fates_options:
        for opt in args.fates_options:
            nl_lines.append(opt)

    # Add history output
    hist_vars = ",".join(f"'{v}'" for v in FATES_HISTORY_VARS)
    nl_lines.append(f"hist_fincl1 = {hist_vars}")
    nl_lines.append("hist_mfilt = 12")
    nl_lines.append("hist_nhtfrq = 0")  # Monthly output

    if not args.dry_run:
        with open(nl_path, "w") as f:
            f.write("\n".join(nl_lines) + "\n")
    print(f"  Wrote user_nl_clm ({len(nl_lines)} lines)", file=sys.stderr)

    return {"status": "success", "stage": "configure",
            "xml_changes": results, "nl_lines": len(nl_lines)}


def build_case(args: argparse.Namespace) -> Dict[str, Any]:
    """Setup and build the case."""
    # case.setup
    setup_cmd = [os.path.join(args.case_dir, "case.setup")]
    r1 = run_command(setup_cmd, cwd=args.case_dir, dry_run=args.dry_run)
    if r1["returncode"] != 0:
        return {"status": "failed", "stage": "case.setup",
                "error": r1["stderr"]}

    # case.build
    build_cmd = [os.path.join(args.case_dir, "case.build")]
    r2 = run_command(build_cmd, cwd=args.case_dir, dry_run=args.dry_run)
    if r2["returncode"] != 0:
        return {"status": "failed", "stage": "case.build",
                "error": r2["stderr"]}

    return {"status": "success", "stage": "build"}


def submit_case(args: argparse.Namespace) -> Dict[str, Any]:
    """Submit the case for execution."""
    submit_cmd = [os.path.join(args.case_dir, "case.submit")]
    r = run_command(submit_cmd, cwd=args.case_dir, dry_run=args.dry_run)
    if r["returncode"] != 0:
        return {"status": "failed", "stage": "case.submit",
                "error": r["stderr"]}

    return {"status": "success", "stage": "submit",
            "output": r["stdout"][:500]}


def generate_run_script(args: argparse.Namespace) -> str:
    """Generate a standalone bash script for case creation (for reference)."""
    start = datetime.strptime(args.start, "%Y-%m-%d")
    stop = datetime.strptime(args.stop, "%Y-%m-%d")
    n_years = max(1, (stop - start).days // 365)

    script = f"""#!/bin/bash
# FATES/CTSM Case Creation Script
# Site: {args.site_name} ({args.lat}, {args.lon})
# Period: {args.start} to {args.stop}
# Generated by run_fates_case.py

set -e

CTSM_ROOT="{args.ctsm_root}"
CASE_DIR="{args.case_dir}"

# Create case
cd $CTSM_ROOT/cime/scripts
./create_newcase --case $CASE_DIR \\
    --compset {args.compset} \\
    --res {args.res} \\
    --run-unsupported

cd $CASE_DIR

# Configure
./xmlchange RUN_STARTDATE={args.start}
./xmlchange STOP_OPTION=nyears
./xmlchange STOP_N={n_years}
./xmlchange DATM_CLMNCEP_YR_START={start.year}
./xmlchange DATM_CLMNCEP_YR_END={stop.year}

# Build and submit
./case.setup
./case.build
./case.submit

echo "Case submitted: $CASE_DIR"
"""
    return script


def validate_outputs(results: Dict[str, Any]) -> List[str]:
    """Stage 3: Validate case creation results."""
    warnings = []

    for stage_name, stage_result in results.items():
        if isinstance(stage_result, dict):
            status = stage_result.get("status", "unknown")
            if status == "failed":
                error = stage_result.get("error", "unknown error")
                warnings.append(f"Stage '{stage_name}' failed: {error[:200]}")

    return warnings


def main():
    parser = argparse.ArgumentParser(
        description="Create and run CTSM case with FATES")
    parser.add_argument("--ctsm-root", required=True,
                        help="Path to CTSM source directory")
    parser.add_argument("--site-name", required=True,
                        help="Site name for case identification")
    parser.add_argument("--lat", type=float, required=True,
                        help="Site latitude")
    parser.add_argument("--lon", type=float, required=True,
                        help="Site longitude")
    parser.add_argument("--start", required=True,
                        help="Start date (YYYY-MM-DD)")
    parser.add_argument("--stop", required=True,
                        help="Stop date (YYYY-MM-DD)")
    parser.add_argument("--case-dir",
                        help="Case directory (default: ~/cases/<site_name>_fates)")
    parser.add_argument("--compset", default=DEFAULT_COMPSET,
                        help=f"CTSM compset (default: {DEFAULT_COMPSET})")
    parser.add_argument("--res", default=DEFAULT_RES,
                        help=f"Resolution (default: {DEFAULT_RES})")
    parser.add_argument("--machine", default=None,
                        help="CIME machine name")
    parser.add_argument("--fates-params",
                        help="Custom FATES parameter file (JSON)")
    parser.add_argument("--fates-options", nargs="*",
                        help="Additional user_nl_clm entries")
    parser.add_argument("--submit", action="store_true",
                        help="Submit the case after building")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print commands without executing")
    parser.add_argument("--overwrite", action="store_true",
                        help="Overwrite existing case directory")
    parser.add_argument("--script-only", action="store_true",
                        help="Generate bash script only (no execution)")
    args = parser.parse_args()

    # Default case directory
    if not args.case_dir:
        args.case_dir = os.path.expanduser(
            f"~/cases/{args.site_name}_fates")

    # Stage 1: Validate inputs
    validate_inputs(args)

    # Script-only mode
    if args.script_only:
        script = generate_run_script(args)
        print(script)
        return

    # Stage 2: Process
    results = {}

    print(f"\n=== Creating FATES case: {args.site_name} ===", file=sys.stderr)
    print(f"  Location: ({args.lat}, {args.lon})", file=sys.stderr)
    print(f"  Period: {args.start} to {args.stop}", file=sys.stderr)
    print(f"  Compset: {args.compset}", file=sys.stderr)

    # Step 1: Create case
    results["create"] = create_case(args)
    if results["create"]["status"] == "failed":
        print(json.dumps(results, indent=2))
        sys.exit(1)

    # Step 2: Configure
    results["configure"] = configure_case(args)

    # Step 3: Build
    results["build"] = build_case(args)
    if results["build"]["status"] == "failed":
        print(json.dumps(results, indent=2))
        sys.exit(1)

    # Step 4: Submit (optional)
    if args.submit:
        results["submit"] = submit_case(args)

    # Stage 3: Validate outputs
    warnings = validate_outputs(results)

    summary = {
        "status": "success" if not warnings else "completed_with_warnings",
        "site": args.site_name,
        "location": {"lat": args.lat, "lon": args.lon},
        "period": {"start": args.start, "stop": args.stop},
        "case_dir": args.case_dir,
        "compset": args.compset,
        "stages": results,
        "warnings": warnings,
    }
    print(json.dumps(summary, indent=2))

    if warnings:
        print("\n--- Warnings ---", file=sys.stderr)
        for w in warnings:
            print(f"  WARNING: {w}", file=sys.stderr)


if __name__ == "__main__":
    main()
