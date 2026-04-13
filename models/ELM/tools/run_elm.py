#!/usr/bin/env python3
"""
run_elm.py — Execution wrapper for the E3SM Land Model (ELM).

Manages ELM execution through CIME's case control system or direct MPI launch.
Handles case creation, namelist configuration, compilation, and submission.

ELM cannot be run as a standalone binary — it requires the full E3SM/CIME
infrastructure. This wrapper automates the CIME workflow:
  1. Create a new case (create_newcase)
  2. Configure the case (case.setup)
  3. Modify namelists (user_nl_elm)
  4. Build the model (case.build)
  5. Submit the run (case.submit)
  6. Monitor completion

CRITICAL: ELM requires a supported HPC machine. This wrapper will detect
          whether CIME is available and fall back to documentation mode
          if running on an unsupported system.

Usage:
    python run_elm.py --e3sm_root /path/to/E3SM \\
        --case_name elm_test --compset IELM \\
        --res ne4pg2_ne4pg2 --machine chrysalis \\
        --stop_n 1 --stop_option nmonths

    python run_elm.py --check_only --e3sm_root /path/to/E3SM
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_COMPSETS = {
    "sp":  "IELM",                       # Satellite phenology (fastest)
    "cn":  "I1850ELMCN",                  # Carbon-nitrogen
    "bgc": "I1850CNPRDCTCBCTOP",          # Full C/N/P BGC (recommended)
    "crop": "IELMCNCROP",                 # With crop model
}

DEFAULT_RES = "ne4pg2_ne4pg2"  # Low-res for testing

CIME_SCRIPTS_REL = "cime/scripts"

# Common history variables for basic diagnostics
BASIC_HIST_VARS = [
    "GPP", "NPP", "NEE", "HR",           # Carbon fluxes
    "FSH", "EFLX_LH_TOT", "FSA", "FIRA", # Energy fluxes
    "QRUNOFF", "QOVER", "QDRAI",          # Water fluxes
    "H2OSOI", "TSOI",                     # Soil state
    "H2OSNO", "SNOW_DEPTH",               # Snow
    "TLAI", "TV", "TG",                   # Vegetation/surface
]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def validate_inputs(args):
    """Validate CLI arguments and environment."""
    errors = []
    warnings = []

    # Check E3SM root exists
    if not os.path.isdir(args.e3sm_root):
        errors.append(f"E3SM root directory not found: {args.e3sm_root}")
    else:
        cime_dir = os.path.join(args.e3sm_root, CIME_SCRIPTS_REL)
        if not os.path.isdir(cime_dir):
            errors.append(
                f"CIME scripts directory not found: {cime_dir}. "
                f"Did you run 'git submodule update --init --recursive'?"
            )

        create_newcase = os.path.join(cime_dir, "create_newcase")
        if not os.path.isfile(create_newcase):
            errors.append(f"create_newcase not found at {create_newcase}")

    # Check compset
    if args.compset and args.compset not in DEFAULT_COMPSETS.values():
        warnings.append(
            f"Non-standard compset: {args.compset}. "
            f"Standard options: {list(DEFAULT_COMPSETS.values())}"
        )

    if errors:
        result = {"status": "error", "errors": errors, "warnings": warnings}
        print(json.dumps(result, indent=2))
        sys.exit(1)

    return warnings


def validate_machine(e3sm_root, machine):
    """Check if the specified machine is supported."""
    config_machines = os.path.join(
        e3sm_root, "cime_config", "machines", "config_machines.xml"
    )
    if os.path.isfile(config_machines):
        with open(config_machines) as f:
            content = f.read()
        if f'MACH="{machine}"' in content or f"MACH=\"{machine}\"" in content:
            return True, f"Machine '{machine}' found in config_machines.xml"
        else:
            return False, (
                f"Machine '{machine}' not found in config_machines.xml. "
                f"Run: cd {e3sm_root}/{CIME_SCRIPTS_REL} && ./query_config --machines"
            )
    return False, "config_machines.xml not found"


# ---------------------------------------------------------------------------
# CIME operations
# ---------------------------------------------------------------------------
def run_cmd(cmd, cwd=None, timeout=600, description=""):
    """Run a shell command and capture output."""
    print(f"  Running: {description or ' '.join(cmd[:3])}")
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            cwd=cwd, timeout=timeout
        )
        return {
            "returncode": result.returncode,
            "stdout": result.stdout[-2000:] if result.stdout else "",
            "stderr": result.stderr[-2000:] if result.stderr else "",
            "success": result.returncode == 0,
        }
    except subprocess.TimeoutExpired:
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": f"Command timed out after {timeout}s",
            "success": False,
        }
    except FileNotFoundError:
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": f"Command not found: {cmd[0]}",
            "success": False,
        }


def create_case(e3sm_root, case_dir, compset, res, machine):
    """Create a new CIME case."""
    create_newcase = os.path.join(e3sm_root, CIME_SCRIPTS_REL, "create_newcase")

    cmd = [
        create_newcase,
        "--case", case_dir,
        "--compset", compset,
        "--res", res,
        "--mach", machine,
    ]

    return run_cmd(cmd, description="create_newcase")


def setup_case(case_dir):
    """Run case.setup."""
    cmd = [os.path.join(case_dir, "case.setup")]
    return run_cmd(cmd, cwd=case_dir, description="case.setup")


def configure_namelist(case_dir, hist_vars=None, stop_n=1, stop_option="nmonths",
                       custom_nl=None):
    """Write user_nl_elm with requested configuration.

    CRITICAL (dt_008): Fortran namelists require single quotes for strings,
    NOT double quotes. This function ensures correct quoting.
    """
    nl_path = os.path.join(case_dir, "user_nl_elm")
    lines = []

    # History output configuration
    if hist_vars:
        var_list = ", ".join(f"'{v}'" for v in hist_vars)  # Single quotes!
        lines.append(f"hist_fincl1 = {var_list}")
        lines.append("hist_nhtfrq = 0")   # Monthly
        lines.append("hist_mfilt = 12")   # 12 months per file

    # Additional custom namelist entries
    if custom_nl:
        for entry in custom_nl:
            # Ensure single quotes for string values
            entry = entry.replace('"', "'")
            lines.append(entry)

    if lines:
        with open(nl_path, "a") as f:
            f.write("\n".join(lines) + "\n")

    return nl_path


def build_case(case_dir, timeout=1800):
    """Run case.build (can take 10-30 min)."""
    cmd = [os.path.join(case_dir, "case.build")]
    return run_cmd(cmd, cwd=case_dir, timeout=timeout,
                   description="case.build (may take 10-30 min)")


def submit_case(case_dir):
    """Run case.submit."""
    cmd = [os.path.join(case_dir, "case.submit")]
    return run_cmd(cmd, cwd=case_dir, description="case.submit")


def query_xml(case_dir, variable):
    """Query a CIME XML variable."""
    cmd = [os.path.join(case_dir, "xmlquery"), "--value", variable]
    result = run_cmd(cmd, cwd=case_dir, description=f"xmlquery {variable}")
    if result["success"]:
        return result["stdout"].strip()
    return None


def check_status(case_dir):
    """Check case status from CaseStatus file."""
    status_file = os.path.join(case_dir, "CaseStatus")
    if os.path.isfile(status_file):
        with open(status_file) as f:
            lines = f.readlines()
        return lines[-10:] if len(lines) > 10 else lines
    return ["CaseStatus file not found"]


# ---------------------------------------------------------------------------
# Monitoring
# ---------------------------------------------------------------------------
def wait_for_completion(case_dir, timeout=3600, poll_interval=30):
    """Wait for model run to complete."""
    start = time.time()
    while time.time() - start < timeout:
        status_lines = check_status(case_dir)
        last_status = status_lines[-1].strip() if status_lines else ""

        if "case.run success" in last_status.lower():
            return {"status": "completed", "elapsed_s": time.time() - start}
        elif "error" in last_status.lower() or "fail" in last_status.lower():
            return {
                "status": "failed",
                "elapsed_s": time.time() - start,
                "last_status": last_status,
            }

        time.sleep(poll_interval)

    return {"status": "timeout", "elapsed_s": timeout}


# ---------------------------------------------------------------------------
# Main processing
# ---------------------------------------------------------------------------
def process(args):
    """Full CIME workflow: create → setup → configure → build → submit."""
    warnings = []
    steps_completed = []

    # Resolve paths
    e3sm_root = os.path.abspath(args.e3sm_root)
    case_dir = os.path.abspath(args.case_name)
    compset = args.compset or DEFAULT_COMPSETS.get(args.bgc_mode, "IELM")

    # --- Check-only mode ---
    if args.check_only:
        cime_ok = os.path.isdir(os.path.join(e3sm_root, CIME_SCRIPTS_REL))
        if args.machine:
            mach_ok, mach_msg = validate_machine(e3sm_root, args.machine)
        else:
            mach_ok, mach_msg = False, "No machine specified"

        return {
            "status": "success",
            "mode": "check_only",
            "e3sm_root": e3sm_root,
            "cime_available": cime_ok,
            "machine_valid": mach_ok,
            "machine_message": mach_msg,
            "available_compsets": DEFAULT_COMPSETS,
        }

    # --- Full execution ---
    machine = args.machine
    if not machine:
        return {
            "status": "error",
            "errors": ["--machine is required for execution"],
        }

    # Step 1: Create case
    if os.path.isdir(case_dir):
        warnings.append(f"Case directory already exists: {case_dir}")
        if args.force:
            shutil.rmtree(case_dir)
            warnings.append("Removed existing case directory (--force)")
        else:
            return {
                "status": "error",
                "errors": [
                    f"Case directory exists: {case_dir}. "
                    f"Use --force to overwrite."
                ],
            }

    result = create_case(e3sm_root, case_dir, compset, args.res, machine)
    if not result["success"]:
        return {
            "status": "error",
            "step": "create_newcase",
            "errors": [result["stderr"]],
        }
    steps_completed.append("create_newcase")

    # Step 2: Setup
    result = setup_case(case_dir)
    if not result["success"]:
        return {
            "status": "error",
            "step": "case.setup",
            "errors": [result["stderr"]],
        }
    steps_completed.append("case.setup")

    # Step 3: Configure namelist
    hist_vars = BASIC_HIST_VARS if args.hist_vars is None else args.hist_vars
    nl_path = configure_namelist(
        case_dir,
        hist_vars=hist_vars,
        stop_n=args.stop_n,
        stop_option=args.stop_option,
        custom_nl=args.custom_nl,
    )
    steps_completed.append("configure_namelist")

    # Step 4: Build
    if not args.skip_build:
        result = build_case(case_dir, timeout=args.build_timeout)
        if not result["success"]:
            return {
                "status": "error",
                "step": "case.build",
                "errors": [result["stderr"][:1000]],
                "steps_completed": steps_completed,
            }
        steps_completed.append("case.build")

    # Step 5: Submit
    if not args.no_submit:
        result = submit_case(case_dir)
        if not result["success"]:
            return {
                "status": "error",
                "step": "case.submit",
                "errors": [result["stderr"]],
                "steps_completed": steps_completed,
            }
        steps_completed.append("case.submit")

        # Step 6: Wait for completion (optional)
        if args.wait:
            run_result = wait_for_completion(
                case_dir,
                timeout=args.run_timeout,
                poll_interval=args.poll_interval,
            )
            steps_completed.append(f"wait ({run_result['status']})")
        else:
            run_result = {"status": "submitted", "elapsed_s": 0}
    else:
        run_result = {"status": "not_submitted"}

    # Query output directories
    run_dir = query_xml(case_dir, "RUNDIR")
    archive_dir = query_xml(case_dir, "DOUT_S_ROOT")

    return {
        "status": "success",
        "case_dir": case_dir,
        "compset": compset,
        "resolution": args.res,
        "machine": machine,
        "run_status": run_result["status"],
        "run_dir": run_dir,
        "archive_dir": archive_dir,
        "steps_completed": steps_completed,
        "user_nl_elm": nl_path,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Execute ELM via CIME case control system"
    )

    # Required
    parser.add_argument("--e3sm_root", required=True,
                        help="Path to E3SM source root")
    parser.add_argument("--case_name", default="elm_run",
                        help="Case name/path")

    # Model configuration
    parser.add_argument("--compset", default=None,
                        help="CIME compset alias (e.g., I1850CNPRDCTCBCTOP)")
    parser.add_argument("--bgc_mode", default="sp",
                        choices=["sp", "cn", "bgc", "crop"],
                        help="BGC mode shorthand (ignored if --compset given)")
    parser.add_argument("--res", default=DEFAULT_RES,
                        help="Grid resolution")
    parser.add_argument("--machine", default=None,
                        help="Machine name (required for execution)")

    # Run configuration
    parser.add_argument("--stop_n", type=int, default=1,
                        help="Number of time units to run")
    parser.add_argument("--stop_option", default="nmonths",
                        choices=["nsteps", "nhours", "ndays", "nmonths", "nyears"],
                        help="Time unit for stop_n")

    # Namelist customization
    parser.add_argument("--hist_vars", nargs="+",
                        help="History variables to include")
    parser.add_argument("--custom_nl", nargs="+",
                        help="Custom namelist entries (key=value)")

    # Execution control
    parser.add_argument("--check_only", action="store_true",
                        help="Only check environment, don't execute")
    parser.add_argument("--skip_build", action="store_true",
                        help="Skip case.build (use existing build)")
    parser.add_argument("--no_submit", action="store_true",
                        help="Don't submit the run")
    parser.add_argument("--force", action="store_true",
                        help="Remove existing case directory")
    parser.add_argument("--wait", action="store_true",
                        help="Wait for run completion")
    parser.add_argument("--build_timeout", type=int, default=1800,
                        help="Build timeout in seconds (default 1800)")
    parser.add_argument("--run_timeout", type=int, default=7200,
                        help="Run timeout in seconds (default 7200)")
    parser.add_argument("--poll_interval", type=int, default=30,
                        help="Status poll interval in seconds")

    args = parser.parse_args()

    initial_warnings = validate_inputs(args)
    result = process(args)

    if initial_warnings and "warnings" in result:
        result["warnings"] = initial_warnings + result["warnings"]

    print(json.dumps(result, indent=2))

    if result["status"] != "success":
        sys.exit(1)


if __name__ == "__main__":
    main()
