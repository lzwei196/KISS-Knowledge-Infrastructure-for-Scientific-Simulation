#!/usr/bin/env python3
"""Preflight check for CISM v2.1."""

import json
import os
import subprocess
import sys


MODEL_ID = "CISM"
KI_DIR = os.path.dirname(os.path.abspath(__file__))
PYTHON_ENV = "KISSPATH_PYTHON_ENV/bin/python"
CISM_BINARY = (
    "KISSPATH_KI_ROOT/CISM/source/repo/builds/mpi/"
    "cism_driver/cism_driver"
)
TRIPLETS = os.path.join(KI_DIR, "diagnostics", "triplets.yaml")

CHECKS = []
PASS = 0
FAIL = 0


def add_check(kind, subject, critical, status, fix=""):
    """Record one gate-visible check and mirror it to the text log."""
    global PASS, FAIL
    check = {
        "kind": kind,
        "subject": subject,
        "critical": bool(critical),
        "status": status,
        "fix": fix,
    }
    CHECKS.append(check)
    if status == "pass":
        PASS += 1
        print(f"  OK    {kind}: {subject}")
    else:
        FAIL += 1
        print(f"  FAIL  {kind}: {subject}")
        print(f"         Fix: {fix}")
    return check


def check_file(path, label, executable=False, critical=True):
    """Check that a required file exists, and is executable when requested."""
    subject = os.path.realpath(path) if os.path.exists(path) else path
    if not os.path.isfile(path):
        fix = f"Restore {label} at {path}; consult {TRIPLETS} for recovery."
        return add_check("binary" if executable else "data", subject, critical, "fail", fix)
    if executable and not os.access(path, os.X_OK):
        fix = f"Run chmod +x {path}; consult {TRIPLETS} if the build is damaged."
        return add_check("binary", subject, critical, "fail", fix)
    return add_check("binary" if executable else "data", subject, critical, "pass", "")


def check_dir(path, label, critical=True):
    """Check that a required directory exists and is non-empty."""
    subject = os.path.realpath(path) if os.path.exists(path) else path
    if not os.path.isdir(path):
        fix = f"Restore {label} at {path}; consult {TRIPLETS} for recovery."
        return add_check("data", subject, critical, "fail", fix)
    if not os.listdir(path):
        fix = f"Populate {label} at {path}; consult {TRIPLETS} for recovery."
        return add_check("data", subject, critical, "fail", fix)
    return add_check("data", subject, critical, "pass", "")


def check_import(module, label, critical=True):
    """Check imports using the HydroCraft Python environment."""
    subject = f"{PYTHON_ENV} import {module}"
    if not os.path.isfile(PYTHON_ENV):
        fix = (
            f"Restore HydroCraft Python environment at {PYTHON_ENV}; "
            f"then check {TRIPLETS}."
        )
        return add_check("import", subject, critical, "fail", fix)

    code = f"import {module}"
    result = subprocess.run(
        [PYTHON_ENV, "-c", code],
        cwd=KI_DIR,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        reason = f": {detail[-1]}" if detail else ""
        fix = (
            f"Install/repair {module.split('.')[0]} in {PYTHON_ENV}{reason}; "
            f"consult {TRIPLETS}."
        )
        return add_check("import", subject, critical, "fail", fix)
    return add_check("import", subject, critical, "pass", "")


def check_binary_starts(path, critical=True):
    """Run the CISM driver without config; this cheap path prints usage."""
    subject = os.path.realpath(path) if os.path.exists(path) else path
    if not os.path.isfile(path) or not os.access(path, os.X_OK):
        fix = f"Fix the CISM executable at {path}; consult {TRIPLETS}."
        return add_check("run", subject, critical, "fail", fix)

    try:
        result = subprocess.run(
            [path],
            cwd=KI_DIR,
            capture_output=True,
            text=True,
            timeout=8,
        )
    except subprocess.TimeoutExpired:
        fix = f"CISM driver did not reach its usage path within 8s; consult {TRIPLETS}."
        return add_check("run", subject, critical, "fail", fix)
    except OSError as exc:
        fix = f"CISM driver failed to start: {exc}; consult {TRIPLETS}."
        return add_check("run", subject, critical, "fail", fix)

    output = f"{result.stdout}\n{result.stderr}"
    if "Call cism_driver" in output or "cism_driver ice_sheet.config" in output:
        return add_check("run", subject, critical, "pass", "")

    if result.returncode == 0:
        return add_check("run", subject, critical, "pass", "")

    fix = (
        f"CISM driver exited {result.returncode} before printing expected usage; "
        f"consult {TRIPLETS}."
    )
    return add_check("run", subject, critical, "fail", fix)


def emit_report(model_id, checks):
    """Emit the KDT gate report as the final output line and exit."""
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}))
    failed_critical = any(c["status"] != "pass" and c.get("critical") for c in checks)
    sys.exit(1 if failed_critical else 0)


def main():
    print(f"{' PREFLIGHT: CISM ':=^60}")
    print()

    check_dir(os.path.join(KI_DIR, "tools"), "KI tools directory", critical=True)
    for relpath in [
        "tools/generate_input_nc.py",
        "tools/convert_forcing_to_cism.py",
        "tools/generate_cism_config.py",
        "tools/run_cism.py",
        "tools/parse_cism_output.py",
    ]:
        check_file(os.path.join(KI_DIR, relpath), relpath, critical=True)

    check_file(TRIPLETS, "diagnostic triplets", critical=True)

    check_file(CISM_BINARY, "CISM binary", executable=True, critical=True)
    check_binary_starts(CISM_BINARY, critical=True)

    check_import("numpy", "NumPy", critical=True)
    check_import("netCDF4", "netCDF4", critical=True)
    check_import("pandas", "pandas CSV forcing support", critical=False)

    print()
    print(f"  Results: {PASS} passed, {FAIL} failed")
    if FAIL:
        print(f"  Recovery: check {TRIPLETS} first for known CISM fixes.")

    emit_report(MODEL_ID, CHECKS)


if __name__ == "__main__":
    main()
