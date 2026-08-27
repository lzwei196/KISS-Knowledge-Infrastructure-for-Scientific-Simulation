#!/usr/bin/env python3
"""Preflight check for the GSFLOW knowledge infrastructure."""

import json
import os
import subprocess
import sys


MODEL_ID = "GSFLOW"
KI_DIR = os.path.dirname(os.path.abspath(__file__))
DIAGNOSTICS = os.path.join(KI_DIR, "diagnostics", "triplets.yaml")
PYTHON_ENV = "KISSPATH_PYTHON_ENV/bin/python"
GSFLOW_BINARY = (
    "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/"
    "GSFLOW/source/repo/autotest/gsflow"
)


def diagnostic_fix(message):
    return f"{message}; see {DIAGNOSTICS} for known recovery triplets"


def emit_report(model_id, checks):
    print(
        "PREFLIGHT_REPORT="
        + json.dumps({"model_id": model_id, "checks": checks}, sort_keys=True)
    )
    critical_failed = any(
        check["critical"] and check["status"] != "pass" for check in checks
    )
    sys.exit(1 if critical_failed else 0)


def add_check(checks, kind, subject, critical, status, fix=""):
    checks.append(
        {
            "kind": kind,
            "subject": subject,
            "critical": bool(critical),
            "status": status,
            "fix": fix,
        }
    )


def check_file(checks, path, label, *, kind="data", critical=True, executable=False):
    subject = os.path.realpath(path) if os.path.exists(path) else path
    if not os.path.isfile(path):
        print(f"FAIL  {label}: missing at {path}")
        add_check(
            checks,
            kind,
            subject,
            critical,
            "fail",
            diagnostic_fix(f"Restore or correct required file path: {path}"),
        )
        return False
    if executable and not os.access(path, os.X_OK):
        print(f"FAIL  {label}: exists but is not executable: {path}")
        add_check(
            checks,
            kind,
            subject,
            critical,
            "fail",
            diagnostic_fix(f"Make executable with: chmod +x {path}"),
        )
        return False
    print(f"OK    {label}: {subject}")
    add_check(checks, kind, subject, critical, "pass")
    return True


def check_python_import(checks, module, label, *, critical=True):
    subject = f"{os.path.realpath(PYTHON_ENV)} -c import {module}"
    if not os.path.isfile(PYTHON_ENV):
        print(f"FAIL  {label}: Python environment missing: {PYTHON_ENV}")
        add_check(
            checks,
            "import",
            subject,
            critical,
            "fail",
            diagnostic_fix(f"Restore HydroCraft Python interpreter at {PYTHON_ENV}"),
        )
        return False

    code = f"import {module}"
    result = subprocess.run(
        [PYTHON_ENV, "-c", code],
        capture_output=True,
        text=True,
        timeout=20,
    )
    if result.returncode == 0:
        print(f"OK    {label}: import {module} using {PYTHON_ENV}")
        add_check(checks, "import", subject, critical, "pass")
        return True

    detail = (result.stderr or result.stdout).strip().splitlines()
    error = detail[-1] if detail else f"return code {result.returncode}"
    print(f"FAIL  {label}: import {module} failed: {error}")
    add_check(
        checks,
        "import",
        subject,
        critical,
        "fail",
        diagnostic_fix(f"Install {module.split('.')[0]} in {PYTHON_ENV} environment"),
    )
    return False


def check_binary_start(checks, binary):
    subject = os.path.realpath(binary) if os.path.exists(binary) else binary
    if not os.path.isfile(binary) or not os.access(binary, os.X_OK):
        print(f"FAIL  GSFLOW startup probe: executable unavailable: {binary}")
        add_check(
            checks,
            "run",
            subject,
            True,
            "fail",
            diagnostic_fix(f"Restore executable before startup probe: {binary}"),
        )
        return False

    try:
        result = subprocess.run(
            [binary],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except subprocess.TimeoutExpired:
        print("FAIL  GSFLOW startup probe: timed out")
        add_check(
            checks,
            "run",
            subject,
            True,
            "fail",
            diagnostic_fix("GSFLOW executable hung during no-control-file startup probe"),
        )
        return False

    output = f"{result.stdout}\n{result.stderr}"
    if "Control File must be specified" in output or "control file" in output.lower():
        print("OK    GSFLOW startup probe: executable starts and reports missing control file")
        add_check(checks, "run", subject, True, "pass")
        return True

    print(f"FAIL  GSFLOW startup probe: unexpected output, return code {result.returncode}")
    add_check(
        checks,
        "run",
        subject,
        True,
        "fail",
        diagnostic_fix("Run the executable manually and compare startup errors"),
    )
    return False


def main():
    checks = []
    print(f"{' PREFLIGHT: GSFLOW ':=^60}")

    check_file(
        checks,
        GSFLOW_BINARY,
        "GSFLOW binary",
        kind="binary",
        critical=True,
        executable=True,
    )
    check_binary_start(checks, GSFLOW_BINARY)

    check_file(checks, os.path.join(KI_DIR, "SKILL.md"), "KI instructions")
    check_file(
        checks,
        os.path.join(KI_DIR, "knowledge_infrastructure.yaml"),
        "KI manifest",
    )
    check_file(checks, os.path.join(KI_DIR, "dag.yaml"), "DAG contract")
    check_file(checks, DIAGNOSTICS, "Diagnostic triplets")

    for tool in (
        "tools/build_control_file.py",
        "tools/convert_forcing_to_gsflow.py",
        "tools/convert_soil_params.py",
        "tools/parse_gsflow_output.py",
        "tools/run_gsflow.py",
    ):
        check_file(checks, os.path.join(KI_DIR, tool), tool)

    check_file(
        checks,
        PYTHON_ENV,
        "HydroCraft Python interpreter",
        kind="data",
        critical=True,
        executable=True,
    )

    for module, label in (
        ("numpy", "array operations for forcing/soil tools"),
        ("pandas", "tabular output parsing"),
        ("netCDF4", "NetCDF forcing conversion"),
        ("geopandas", "basin vector masking"),
        ("shapely", "geometry operations"),
        ("rasterio", "raster soil/land-cover handling"),
    ):
        check_python_import(checks, module, label, critical=True)

    failed = [check for check in checks if check["status"] != "pass"]
    print(f"Results: {len(checks) - len(failed)} passed, {len(failed)} failed")
    if failed:
        print("Fixes:")
        for check in failed:
            print(f"  - {check['subject']}: {check['fix']}")

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
