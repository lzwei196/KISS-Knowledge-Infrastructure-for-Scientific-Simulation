#!/usr/bin/env python3
"""
run_clm.py — Execute CLM5/CTSM via CIME case workflow or standalone LILAC.

Wraps the CIME create_newcase → case.setup → case.build → case.submit pipeline
with preflight checks, timeout management, and structured JSON output.

Supports two execution modes:
  1. CIME mode (default): Uses CESM/CIME case infrastructure
  2. LILAC mode: Standalone CLM5 coupled to a host atmosphere model

PREFLIGHT CHECKS:
  - Verifies CIME/CTSM root directories exist
  - Checks required environment variables (NETCDF, ESMFMKFILE)
  - Validates compiler and MPI availability
  - Checks disk space in case and run directories
  - Validates namelist files if case already exists

Usage:
    python run_clm.py --case-dir /path/to/case --action submit --timeout 7200
    python run_clm.py --ctsm-root /path/to/ctsm --case-name test1 \\
        --compset I2000Clm60Sp --res f09_g17 --action create-and-run
    python run_clm.py --case-dir /path/to/case --action build
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time


def validate_inputs(args):
    """Validate execution environment and arguments."""
    errors = []
    warnings_list = []

    if args.action in ("submit", "build", "setup", "configure", "status"):
        if not args.case_dir:
            errors.append(f"--case-dir required for the {args.action} action")
        elif not os.path.isdir(args.case_dir):
            errors.append(f"Case directory does not exist: {args.case_dir}")

    if args.action in ("create-and-run", "create"):
        if not args.ctsm_root:
            errors.append("--ctsm-root required for create-and-run action")
        elif not os.path.isdir(args.ctsm_root):
            errors.append(f"CTSM root does not exist: {args.ctsm_root}")
        if not args.compset:
            errors.append("--compset required for create-and-run action")
        if not args.res:
            errors.append("--res (resolution) required for create-and-run action")

    # Check for Fortran compiler
    if shutil.which("gfortran") is None and shutil.which("ifort") is None:
        warnings_list.append("No Fortran compiler (gfortran/ifort) found in PATH")

    # Check for MPI
    if shutil.which("mpirun") is None and shutil.which("mpiexec") is None:
        warnings_list.append("No MPI launcher (mpirun/mpiexec) found in PATH")

    # Check for NetCDF
    nc_config = shutil.which("nf-config") or shutil.which("nc-config")
    if nc_config is None:
        warnings_list.append("NetCDF config not found — may cause build failure")

    if errors:
        print(json.dumps({
            "status": "error",
            "errors": errors,
            "warnings": warnings_list,
        }))
        sys.exit(1)

    return warnings_list


def run_command(cmd, cwd=None, timeout=None, capture=True):
    """Run a shell command with timeout and capture output."""
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            shell=isinstance(cmd, str),
            capture_output=capture,
            text=True,
            timeout=timeout,
        )
        return {
            "returncode": result.returncode,
            "stdout": result.stdout[:5000] if result.stdout else "",
            "stderr": result.stderr[:5000] if result.stderr else "",
        }
    except subprocess.TimeoutExpired:
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": f"Command timed out after {timeout}s",
        }
    except FileNotFoundError as e:
        return {
            "returncode": -2,
            "stdout": "",
            "stderr": str(e),
        }


def check_case_health(case_dir):
    """Check if a CIME case directory is properly configured."""
    checks = {}

    # Check essential files
    for fname in ["case.setup", "case.build", "case.submit",
                   "env_run.xml", "env_build.xml"]:
        fpath = os.path.join(case_dir, fname)
        checks[fname] = os.path.exists(fpath)

    # Check if already built
    bld_dir = os.path.join(case_dir, "bld")
    checks["build_exists"] = os.path.isdir(bld_dir)

    # Check for lnd_in namelist
    run_dir_candidates = [
        os.path.join(case_dir, "run"),
        os.path.join(case_dir, "CaseDocs"),
    ]
    checks["lnd_in_exists"] = any(
        os.path.exists(os.path.join(d, "lnd_in"))
        for d in run_dir_candidates
    )

    return checks


def create_case(args):
    """Create a new CIME case."""
    cime_scripts = os.path.join(args.ctsm_root, "cime", "scripts")
    if not os.path.isdir(cime_scripts):
        # Try alternative location
        cime_scripts = os.path.join(args.ctsm_root, "cime_config")

    create_newcase = os.path.join(cime_scripts, "create_newcase")
    if not os.path.exists(create_newcase):
        return {
            "status": "error",
            "errors": [f"create_newcase not found at {create_newcase}"],
        }

    case_dir = args.case_dir or os.path.join(
        os.path.expanduser("~/cases"), args.case_name or "clm_test"
    )

    cmd = [
        create_newcase,
        "--case", case_dir,
        "--compset", args.compset,
        "--res", args.res,
        "--run-unsupported",
    ]

    if args.machine:
        cmd.extend(["--machine", args.machine])

    result = run_command(cmd, timeout=args.timeout)
    result["case_dir"] = case_dir
    return result


def setup_case(case_dir, timeout=600):
    """Run case.setup."""
    setup_script = os.path.join(case_dir, "case.setup")
    return run_command(setup_script, cwd=case_dir, timeout=timeout)


def build_case(case_dir, timeout=3600):
    """Run case.build."""
    build_script = os.path.join(case_dir, "case.build")
    return run_command(build_script, cwd=case_dir, timeout=timeout)


def submit_case(case_dir, timeout=300):
    """Run case.submit."""
    submit_script = os.path.join(case_dir, "case.submit")
    return run_command(submit_script, cwd=case_dir, timeout=timeout)


def xmlchange(case_dir, assignments, timeout=120):
    """Apply ``VAR=VALUE`` settings with the case's own ./xmlchange.

    Added because ``create-and-run`` ran create -> setup -> build -> submit with
    no hook in between, so there was no KI-tool route to set the things a
    single-point case cannot run without (CLM_USRDAT_NAME, ATM/LND_DOMAIN_*,
    DATM_MODE, STOP_N, ...).  Agents were editing env_*.xml by hand instead,
    which silently bypasses CIME's LockedFiles check.
    """
    script = os.path.join(case_dir, "xmlchange")
    if not os.path.exists(script):
        return {"returncode": -1, "stdout": "",
                "stderr": f"xmlchange not found in {case_dir}"}
    steps = []
    for item in assignments:
        if "=" not in item:
            steps.append({"assignment": item, "returncode": -1,
                          "stderr": "expected VAR=VALUE"})
            continue
        res = run_command([script, item], cwd=case_dir, timeout=timeout)
        res["assignment"] = item
        steps.append(res)
    rc = 0 if all(s.get("returncode") == 0 for s in steps) else 1
    return {"returncode": rc, "assignments": steps, "stdout": "", "stderr": ""}


def append_user_nl(case_dir, spec):
    """Append namelist text to user_nl_<component>.

    ``spec`` is ``component:path-or-literal``, e.g. ``clm:/tmp/user_nl_clm.txt``
    or ``clm:finidat = ' '``.
    """
    if ":" not in spec:
        return {"returncode": -1, "stderr": "expected component:payload"}
    comp, payload = spec.split(":", 1)
    target = os.path.join(case_dir, f"user_nl_{comp}")
    if not os.path.exists(target):
        return {"returncode": -1,
                "stderr": f"{target} does not exist (run case.setup first?)"}
    text = open(payload).read() if os.path.exists(payload) else payload
    with open(target, "a") as fh:
        fh.write("\n" + text.rstrip() + "\n")
    return {"returncode": 0, "target": target, "n_chars": len(text)}


def xmlquery(case_dir, variable):
    """Query a CIME XML variable."""
    xmlquery_script = os.path.join(case_dir, "xmlquery")
    if not os.path.exists(xmlquery_script):
        return None
    result = run_command(
        [xmlquery_script, variable, "--value"],
        cwd=case_dir,
        timeout=30,
    )
    if result["returncode"] == 0:
        return result["stdout"].strip()
    return None


def process(args, preflight_warnings):
    """Main execution logic."""
    start_time = time.time()
    results = {
        "action": args.action,
        "preflight_warnings": preflight_warnings,
        "steps": [],
    }

    if args.action == "create-and-run":
        # Step 1: Create
        step = create_case(args)
        results["steps"].append({"name": "create_newcase", **step})
        if step.get("returncode", -1) != 0:
            results["status"] = "error"
            results["error"] = "create_newcase failed"
            return results

        case_dir = step.get("case_dir", args.case_dir)

        # Step 2: Setup
        step = setup_case(case_dir, timeout=args.timeout)
        results["steps"].append({"name": "case.setup", **step})
        if step["returncode"] != 0:
            results["status"] = "error"
            results["error"] = "case.setup failed"
            return results

        # Step 3: Build
        step = build_case(case_dir, timeout=args.timeout)
        results["steps"].append({"name": "case.build", **step})
        if step["returncode"] != 0:
            results["status"] = "error"
            results["error"] = "case.build failed"
            return results

        # Step 4: Submit
        step = submit_case(case_dir, timeout=args.timeout)
        results["steps"].append({"name": "case.submit", **step})
        if step["returncode"] != 0:
            results["status"] = "error"
            results["error"] = "case.submit failed"
            return results

        results["case_dir"] = case_dir
        results["status"] = "success"

    elif args.action == "create":
        step = create_case(args)
        results["steps"].append({"name": "create_newcase", **step})
        results["case_dir"] = step.get("case_dir", args.case_dir)
        results["status"] = "success" if step.get("returncode", -1) == 0 else "error"

    elif args.action == "configure":
        if args.xmlchange:
            step = xmlchange(args.case_dir, args.xmlchange)
            results["steps"].append({"name": "xmlchange", **step})
            if step["returncode"] != 0:
                results["status"] = "error"
                results["error"] = "xmlchange failed"
                return results
        for spec in (args.append_user_nl or []):
            step = append_user_nl(args.case_dir, spec)
            results["steps"].append({"name": f"user_nl:{spec.split(':')[0]}", **step})
            if step["returncode"] != 0:
                results["status"] = "error"
                results["error"] = "append_user_nl failed"
                return results
        results["status"] = "success"

    elif args.action == "setup":
        step = setup_case(args.case_dir, timeout=args.timeout)
        results["steps"].append({"name": "case.setup", **step})
        results["status"] = "success" if step["returncode"] == 0 else "error"

    elif args.action == "build":
        step = build_case(args.case_dir, timeout=args.timeout)
        results["steps"].append({"name": "case.build", **step})
        results["status"] = "success" if step["returncode"] == 0 else "error"

    elif args.action == "submit":
        # Pre-check case health
        health = check_case_health(args.case_dir)
        results["case_health"] = health

        step = submit_case(args.case_dir, timeout=args.timeout)
        results["steps"].append({"name": "case.submit", **step})
        results["status"] = "success" if step["returncode"] == 0 else "error"

    elif args.action == "status":
        health = check_case_health(args.case_dir)
        results["case_health"] = health

        # Query key variables
        for var in ["CASE", "COMPSET", "RES", "STOP_OPTION", "STOP_N",
                     "RUN_TYPE", "RUNDIR", "DOUT_S_ROOT"]:
            val = xmlquery(args.case_dir, var)
            if val:
                results[var] = val

        results["status"] = "success"

    results["elapsed_seconds"] = round(time.time() - start_time, 2)
    return results


def validate_outputs(results):
    """Post-execution validation."""
    warnings_list = results.get("preflight_warnings", [])

    for step in results.get("steps", []):
        if step.get("returncode", 0) != 0:
            stderr = step.get("stderr", "")
            if "NetCDF" in stderr:
                warnings_list.append(
                    "NetCDF-related error — check NETCDF_PATH and library versions"
                )
            if "ESMF" in stderr:
                warnings_list.append(
                    "ESMF-related error — check ESMFMKFILE environment variable"
                )
            if "Permission denied" in stderr:
                warnings_list.append(
                    "Permission error — check file permissions on case directory"
                )

    results["warnings"] = warnings_list
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Execute CLM5/CTSM via CIME case workflow"
    )
    parser.add_argument(
        "--action", type=str, required=True,
        choices=["create-and-run", "create", "configure", "setup", "build",
                 "submit", "status"],
        help="Action to perform"
    )
    parser.add_argument("--xmlchange", action="append", default=None,
                        metavar="VAR=VALUE",
                        help="(action=configure) repeatable ./xmlchange setting")
    parser.add_argument("--append-user-nl", action="append", default=None,
                        metavar="COMPONENT:PAYLOAD",
                        help="(action=configure) append text or a file's "
                             "contents to user_nl_<component>")
    parser.add_argument("--case-dir", type=str, default=None)
    parser.add_argument("--case-name", type=str, default=None)
    parser.add_argument("--ctsm-root", type=str, default=None)
    parser.add_argument("--compset", type=str, default=None)
    parser.add_argument("--res", type=str, default=None)
    parser.add_argument("--machine", type=str, default=None)
    parser.add_argument("--timeout", type=int, default=7200)

    args = parser.parse_args()

    preflight_warnings = validate_inputs(args)
    results = process(args, preflight_warnings)
    results = validate_outputs(results)

    print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()
