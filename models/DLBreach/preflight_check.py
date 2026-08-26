#!/usr/bin/env python3
"""
Preflight check for DLBreach.

Run this before attempting model execution. It verifies the Fortran/Wine
binary, Python environment imports used by the KI tools, required KI files,
and the local DLBreach data/doc layout.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


MODEL_ID = "DLBreach"
KI_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = Path("KISSPATH_ROOT")
MODEL_DIR = PROJECT_ROOT / "model" / "dlbreach"
BINARY_PATH = MODEL_DIR / "bin" / "DLBreach_Barrier.exe"
PYTHON_ENV = PROJECT_ROOT / "python_env" / "bin" / "python"
TRIPLETS = KI_DIR / "diagnostics" / "triplets.yaml"

CHECKS = []
PASS = 0
FAIL = 0


def diagnostics_fix(action):
    return f"{action}; then check {TRIPLETS} for matching recovery triplets."


def add_check(kind, subject, critical, ok, fix):
    global PASS, FAIL
    status = "pass" if ok else "fail"
    CHECKS.append(
        {
            "kind": kind,
            "subject": str(subject),
            "critical": bool(critical),
            "status": status,
            "fix": "" if ok else diagnostics_fix(fix),
        }
    )
    if ok:
        PASS += 1
    else:
        FAIL += 1


def print_result(ok, label, subject, fix=None, warn=False):
    if ok:
        print(f"  OK    {label}: {subject}")
    elif warn:
        print(f"  WARN  {label}: {subject}")
        if fix:
            print(f"         Fix: {fix}")
    else:
        print(f"  FAIL  {label}: {subject}")
        if fix:
            print(f"         Fix: {fix}")


def check_file(path, label, critical=True, executable=False, subject_realpath=False):
    p = Path(path)
    subject = os.path.realpath(p) if subject_realpath and p.exists() else str(p)
    if not p.is_file():
        fix = f"restore required file at {p}"
        print_result(False, label, f"NOT FOUND at {p}", fix, warn=not critical)
        add_check("binary" if executable else "data", subject, critical, False, fix)
        return False
    if executable and not os.access(p, os.X_OK):
        fix = f"chmod +x {p}"
        print_result(False, label, f"exists but is not executable: {p}", fix, warn=not critical)
        add_check("binary", subject, critical, False, fix)
        return False
    print_result(True, label, subject)
    add_check("binary" if executable else "data", subject, critical, True, "")
    return True


def check_dir(path, label, critical=True, nonempty=False):
    p = Path(path)
    if not p.is_dir():
        fix = f"restore required directory at {p}"
        print_result(False, label, f"directory NOT FOUND at {p}", fix, warn=not critical)
        add_check("data", p, critical, False, fix)
        return False
    count = len(list(p.iterdir()))
    if nonempty and count == 0:
        fix = f"populate required directory {p}"
        print_result(False, label, f"{p} is empty", fix, warn=not critical)
        add_check("data", p, critical, False, fix)
        return False
    print_result(True, label, f"{p} ({count} items)")
    add_check("data", p, critical, True, "")
    return True


def check_tool_files():
    expected = [
        "tools/s1_installation/verify_dlbreach.py",
        "tools/s2_dam_properties/create_dam_geometry.py",
        "tools/s3_reservoir_curve/create_reservoir_curve.py",
        "tools/s4_inflow/convert_cama_to_inflow.py",
        "tools/s5_breach_config/set_breach_parameters.py",
        "tools/s5_breach_config/assemble_input_file.py",
        "tools/s6_execution/run_dlbreach.py",
        "tools/s7_output/extract_breach_results.py",
        "tools/s7_output/inject_breach_to_cama.py",
        "tools/s8_visualization/plot_breach_hydrograph.py",
        "tools/s8_visualization/plot_breach_evolution.py",
    ]
    missing = [rel for rel in expected if not (KI_DIR / rel).is_file()]
    if missing:
        fix = "restore missing KI tool scripts: " + ", ".join(missing)
        print_result(False, "KI tool scripts", "missing " + ", ".join(missing), fix)
        add_check("data", "required KI tool scripts", True, False, fix)
        return False
    print_result(True, "KI tool scripts", f"{len(expected)} scripts present")
    add_check("data", "required KI tool scripts", True, True, "")
    return True


def check_import_with_python(module, critical=True):
    label = f"Python import {module}"
    subject = f"{PYTHON_ENV}: import {module}"
    if not PYTHON_ENV.is_file():
        fix = f"restore HydroCraft Python interpreter at {PYTHON_ENV}"
        print_result(False, label, f"interpreter NOT FOUND at {PYTHON_ENV}", fix, warn=not critical)
        add_check("import", subject, critical, False, fix)
        return False
    if not os.access(PYTHON_ENV, os.X_OK):
        fix = f"chmod +x {PYTHON_ENV}"
        print_result(False, label, f"interpreter is not executable: {PYTHON_ENV}", fix, warn=not critical)
        add_check("import", subject, critical, False, fix)
        return False
    proc = subprocess.run(
        [str(PYTHON_ENV), "-c", f"import {module}"],
        cwd=str(KI_DIR),
        capture_output=True,
        text=True,
        timeout=15,
    )
    if proc.returncode == 0:
        print_result(True, label, f"succeeded using {PYTHON_ENV}")
        add_check("import", subject, critical, True, "")
        return True
    detail = (proc.stderr or proc.stdout or "").strip().splitlines()
    message = detail[-1] if detail else f"exit code {proc.returncode}"
    fix = f"install or expose {module.split('.')[0]} in {PYTHON_ENV}"
    print_result(False, label, message, fix, warn=not critical)
    add_check("import", subject, critical, False, fix)
    return False


def check_wine():
    wine = shutil.which("wine")
    if not wine:
        fix = "install Wine or provide a native DLBreach binary"
        print_result(False, "Wine runtime", "wine not found in PATH", fix)
        add_check("binary", "wine", True, False, fix)
        return None
    real_wine = os.path.realpath(wine)
    print_result(True, "Wine runtime", real_wine)
    add_check("binary", real_wine, True, True, "")
    return real_wine


def check_binary_starts(wine_path):
    binary_realpath = os.path.realpath(BINARY_PATH)
    subject = f"{binary_realpath} starts via {wine_path}"
    if not wine_path or not BINARY_PATH.is_file():
        fix = "restore the DLBreach binary and Wine runtime"
        print_result(False, "DLBreach startup", "binary or Wine missing", fix)
        add_check("run", subject, True, False, fix)
        return False

    try:
        proc = subprocess.run(
            [wine_path, str(BINARY_PATH)],
            input="\n",
            cwd=str(BINARY_PATH.parent),
            capture_output=True,
            text=True,
            timeout=8,
        )
    except subprocess.TimeoutExpired:
        fix = f"run {wine_path} {BINARY_PATH} manually and inspect startup hang"
        print_result(False, "DLBreach startup", "timed out during startup probe", fix)
        add_check("run", subject, True, False, fix)
        return False
    except OSError as exc:
        fix = f"repair executable/runtime: {exc}"
        print_result(False, "DLBreach startup", str(exc), fix)
        add_check("run", subject, True, False, fix)
        return False

    combined = f"{proc.stdout}\n{proc.stderr}"
    ok = "The DLBreach model" in combined and "Type the case name" in combined
    if ok:
        print_result(True, "DLBreach startup", "banner and case-name prompt observed")
        add_check("run", subject, True, True, "")
        return True

    snippet = combined.strip().splitlines()
    detail = snippet[-1] if snippet else f"exit code {proc.returncode} with no output"
    fix = f"run {wine_path} {BINARY_PATH} from {BINARY_PATH.parent} and repair startup"
    print_result(False, "DLBreach startup", detail, fix)
    add_check("run", subject, True, False, fix)
    return False


def check_common_data():
    common = [
        (PROJECT_ROOT / "data" / "obs", "Observation data"),
        (Path("KISSPATH_FORCING"), "Forcing data"),
        (PROJECT_ROOT / "data" / "dem", "DEM data"),
        (PROJECT_ROOT / "data" / "soil", "Soil data"),
    ]
    for path, label in common:
        check_dir(
            path,
            label,
            critical=False,
            nonempty=False,
        )


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}))
    critical_failed = any(c["critical"] and c["status"] != "pass" for c in checks)
    sys.exit(1 if critical_failed else 0)


def main():
    print("=" * 60)
    print(f"  PREFLIGHT CHECK: {MODEL_ID}")
    print("=" * 60)
    print()

    check_dir(MODEL_DIR, "DLBreach model directory", critical=True, nonempty=True)
    check_file(BINARY_PATH, "DLBreach Fortran/Wine binary", critical=True, executable=True, subject_realpath=True)
    wine_path = check_wine()
    check_binary_starts(wine_path)

    print()
    check_file(PYTHON_ENV, "HydroCraft Python interpreter", critical=True, executable=True)
    check_import_with_python("numpy", critical=True)
    check_import_with_python("ki_tools_common.units", critical=True)

    print()
    check_tool_files()
    check_file(KI_DIR / "SKILL.md", "KI instructions", critical=True)
    check_file(KI_DIR / "knowledge_infrastructure.yaml", "KI manifest", critical=True)
    check_file(KI_DIR / "dag.yaml", "KI DAG", critical=True)
    check_file(KI_DIR / "docs" / "format_spec.yaml", "DLBreach format spec", critical=True)
    check_file(TRIPLETS, "Diagnostic triplets", critical=True)
    check_dir(MODEL_DIR / "test_cases", "Official DLBreach test cases", critical=True, nonempty=True)
    check_file(KI_DIR / "docs" / "reference" / "DLBreach_Technical_Report_2016.pdf", "DLBreach technical report", critical=True)

    print()
    check_common_data()

    print()
    if TRIPLETS.is_file():
        print(f"  INFO  Diagnostic triplets available at: {TRIPLETS}")
        print("         If the model fails, check triplets FIRST for known fixes.")

    critical_failed = [c for c in CHECKS if c["critical"] and c["status"] != "pass"]
    print()
    print(f"  Results: {PASS} passed, {FAIL} failed")
    if critical_failed:
        print("  STATUS: PREFLIGHT FAILED - fix the critical issues above before running")
        for check in critical_failed:
            print(f"  FIX   {check['subject']}: {check['fix']}")
    else:
        print("  STATUS: PREFLIGHT PASSED - safe to proceed with model execution")

    emit_report(MODEL_ID, CHECKS)


if __name__ == "__main__":
    main()
