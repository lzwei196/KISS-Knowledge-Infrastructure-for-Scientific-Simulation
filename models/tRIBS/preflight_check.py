#!/usr/bin/env python3
"""Preflight check for the tRIBS knowledge infrastructure."""

import json
import os
import subprocess
import sys


MODEL_ID = "tRIBS"
KI_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_ROOT = os.path.abspath(os.path.join(KI_DIR, os.pardir))
TRIPLETS = os.path.join(KI_DIR, "diagnostics", "triplets.yaml")
HYDRO_PYTHON = "KISSPATH_PYTHON_ENV/bin/python"
TRIBS_BINARY = os.path.join(MODEL_ROOT, "source", "repo", "build", "tRIBS")


checks = []


def add_check(kind, subject, critical, status, fix=""):
    check = {
        "kind": kind,
        "subject": subject,
        "critical": bool(critical),
        "status": status,
        "fix": fix,
    }
    checks.append(check)
    label = "OK" if status == "pass" else "FAIL"
    print(f"  {label:<5} {kind}: {subject}")
    if status != "pass" and fix:
        print(f"        Fix: {fix}")
    return status == "pass"


def recovery_fix(message):
    return f"{message}; then check {TRIPLETS} for matching recovery triplets."


def check_file(path, label, critical=True, executable=False, kind="data"):
    subject = os.path.realpath(path) if os.path.exists(path) else os.path.abspath(path)
    if not os.path.isfile(path):
        return add_check(
            kind,
            subject,
            critical,
            "fail",
            recovery_fix(f"{label} is missing"),
        )
    if executable and not os.access(path, os.X_OK):
        return add_check(
            kind,
            subject,
            critical,
            "fail",
            recovery_fix(f"Make {label} executable with chmod +x {path}"),
        )
    return add_check(kind, subject, critical, "pass")


def check_dir(path, label, critical=True, nonempty=False):
    subject = os.path.realpath(path) if os.path.exists(path) else os.path.abspath(path)
    if not os.path.isdir(path):
        return add_check(
            "data",
            subject,
            critical,
            "fail",
            recovery_fix(f"{label} directory is missing"),
        )
    if nonempty and not os.listdir(path):
        return add_check(
            "data",
            subject,
            critical,
            "fail",
            recovery_fix(f"{label} directory is empty"),
        )
    return add_check("data", subject, critical, "pass")


def check_import(module, critical=True):
    subject = f"{HYDRO_PYTHON} import {module}"
    if not os.path.isfile(HYDRO_PYTHON):
        return add_check(
            "import",
            subject,
            critical,
            "fail",
            recovery_fix("HydroCraft python_env interpreter is missing"),
        )
    cmd = [
        HYDRO_PYTHON,
        "-c",
        f"import importlib; importlib.import_module({module!r})",
    ]
    result = subprocess.run(cmd, text=True, capture_output=True, timeout=20)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        reason = detail[-1] if detail else f"import {module} failed"
        return add_check(
            "import",
            subject,
            critical,
            "fail",
            recovery_fix(f"Install or repair Python dependency {module}: {reason}"),
        )
    return add_check("import", subject, critical, "pass")


def check_python_compile(path, critical=True):
    subject = os.path.realpath(path) if os.path.exists(path) else os.path.abspath(path)
    if not os.path.isfile(path):
        return add_check(
            "import",
            subject,
            critical,
            "fail",
            recovery_fix("Required KI tool file is missing"),
        )
    cmd = [HYDRO_PYTHON, "-m", "py_compile", path]
    result = subprocess.run(cmd, text=True, capture_output=True, timeout=20)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        reason = detail[-1] if detail else "py_compile failed"
        return add_check(
            "import",
            subject,
            critical,
            "fail",
            recovery_fix(f"Fix Python syntax/importability for {path}: {reason}"),
        )
    return add_check("import", subject, critical, "pass")


def check_binary_starts(path, critical=True):
    subject = os.path.realpath(path) if os.path.exists(path) else os.path.abspath(path)
    if not check_file(path, "tRIBS serial binary", critical, executable=True, kind="binary"):
        return False
    try:
        result = subprocess.run(
            [path],
            text=True,
            capture_output=True,
            timeout=5,
        )
    except subprocess.TimeoutExpired:
        return add_check(
            "run",
            f"{subject} startup probe",
            critical,
            "fail",
            recovery_fix("tRIBS startup probe timed out before printing usage"),
        )
    output = f"{result.stdout}\n{result.stderr}"
    if "tRIBS" in output and ("Usage:" in output or "Provide name of an input file" in output):
        return add_check("run", f"{subject} startup probe", critical, "pass")
    return add_check(
        "run",
        f"{subject} startup probe",
        critical,
        "fail",
        recovery_fix("tRIBS did not print its expected startup banner/usage"),
    )


def emit_report(model_id, report_checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": report_checks}))
    has_critical_failure = any(c["status"] != "pass" and c.get("critical") for c in report_checks)
    sys.exit(1 if has_critical_failure else 0)


def main():
    print("=" * 60)
    print(f"  PREFLIGHT CHECK: {MODEL_ID}")
    print("=" * 60)
    print()

    check_binary_starts(TRIBS_BINARY, critical=True)
    check_file(HYDRO_PYTHON, "HydroCraft Python interpreter", critical=True, executable=True)

    check_dir(os.path.join(KI_DIR, "tools"), "KI tools", critical=True, nonempty=True)
    for relpath in [
        "tools/build_tribs_mesh.py",
        "tools/build_tribs_spatial_maps.py",
        "tools/convert_met_forcing.py",
        "tools/convert_soil_params.py",
        "tools/parse_tribs_output.py",
        "tools/run_tribs.py",
    ]:
        check_python_compile(os.path.join(KI_DIR, relpath), critical=True)

    for module in [
        "pytRIBS",
        "pytRIBS.mesh.mesh",
        "pytRIBS.classes",
        "geopandas",
        "pyproj",
        "rasterio",
        "numpy",
        "pandas",
    ]:
        check_import(module, critical=True)

    check_file(os.path.join(KI_DIR, "SKILL.md"), "KI instructions", critical=True)
    check_file(os.path.join(KI_DIR, "knowledge_infrastructure.yaml"), "KI manifest", critical=True)
    check_file(os.path.join(KI_DIR, "dag.yaml"), "KI DAG", critical=True)
    check_file(TRIPLETS, "diagnostic triplets", critical=True)
    check_file(
        os.path.join(MODEL_ROOT, "source", "repo", "build", "CMakeCache.txt"),
        "tRIBS build metadata",
        critical=False,
    )

    failed = [c for c in checks if c["status"] != "pass"]
    print()
    print(f"  Results: {len(checks) - len(failed)} passed, {len(failed)} failed")
    if failed:
        print(f"  STATUS: PREFLIGHT BLOCKED - check fixes above and {TRIPLETS}")
    else:
        print("  STATUS: PREFLIGHT PASSED - tRIBS is ready for model execution")
    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
