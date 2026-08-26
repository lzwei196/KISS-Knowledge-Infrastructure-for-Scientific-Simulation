#!/usr/bin/env python3
"""
Preflight check for the LDNDC Knowledge Infrastructure.

This script verifies the real model binary, its runtime resources, KI tool
imports, and required local data before any model execution. It always ends
with a single PREFLIGHT_REPORT= JSON line for the KDT gate.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


MODEL_ID = "LDNDC"
KI_DIR = Path(__file__).resolve().parent
HYDROCRAFT_ROOT = Path("KISSPATH_ROOT")
PYTHON_ENV = HYDROCRAFT_ROOT / "python_env" / "bin" / "python"
LDNDC_BASE = HYDROCRAFT_ROOT / "model" / "ldndc" / "ldndc-1.37.linux64"
LDNDC_BINARY = LDNDC_BASE / "bin" / "ldndc"
TRIPLETS = KI_DIR / "diagnostics" / "triplets.yaml"

COMMON_DATA_DIRS = [
    (HYDROCRAFT_ROOT / "data" / "obs", "Observation data"),
    (Path("KISSPATH_FORCING"), "Forcing data"),
    (HYDROCRAFT_ROOT / "data" / "dem", "DEM data"),
    (HYDROCRAFT_ROOT / "data" / "soil", "Soil data"),
]


def recovery_fix(text):
    return f"{text}. Then check {TRIPLETS} for matching diagnostics."


def report_check(checks, kind, subject, critical, status, fix):
    checks.append(
        {
            "kind": kind,
            "subject": str(subject),
            "critical": bool(critical),
            "status": status,
            "fix": fix,
        }
    )


def print_check(label, status, subject, fix=""):
    if status == "pass":
        print(f"  OK    {label}: {subject}")
    else:
        prefix = "FAIL" if fix else "WARN"
        print(f"  {prefix:<5} {label}: {subject}")
        if fix:
            print(f"         Fix: {fix}")


def check_file(checks, path, label, critical=True, executable=False):
    path = Path(path)
    subject = path.resolve() if path.exists() else path
    if not path.is_file():
        fix = recovery_fix(f"Restore or correct the path for {label}: {path}")
        report_check(checks, "binary" if executable else "data", subject, critical, "fail", fix)
        print_check(label, "fail", f"NOT FOUND at {path}", fix if critical else "")
        return False
    if executable and not os.access(path, os.X_OK):
        fix = recovery_fix(f"Run chmod +x {path} or install the executable LDNDC binary")
        report_check(checks, "binary", path.resolve(), critical, "fail", fix)
        print_check(label, "fail", f"exists but is not executable: {path}", fix)
        return False
    report_check(checks, "binary" if executable else "data", path.resolve(), critical, "pass", "")
    print_check(label, "pass", path.resolve())
    return True


def check_dir(checks, path, label, critical=False):
    path = Path(path)
    subject = path.resolve() if path.exists() else path
    if path.is_dir():
        count = len(list(path.iterdir()))
        report_check(checks, "data", subject, critical, "pass", "")
        print_check(label, "pass", f"{subject} ({count} items)")
        return True
    fix = recovery_fix(f"Restore or mount {label}: {path}")
    report_check(checks, "data", subject, critical, "fail", fix)
    print_check(label, "fail", f"directory NOT FOUND at {path}", fix if critical else "")
    return False


def check_command(checks, command, label, critical=True, cwd=None, timeout=10, expect=None):
    subject = " ".join(str(part) for part in command)
    try:
        result = subprocess.run(
            [str(part) for part in command],
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        fix = recovery_fix(f"Install or correct command path: {command[0]}")
        report_check(checks, "run", subject, critical, "fail", fix)
        print_check(label, "fail", "command not found", fix)
        return False
    except subprocess.TimeoutExpired:
        fix = recovery_fix(f"Investigate why {subject} does not return within {timeout}s")
        report_check(checks, "run", subject, critical, "fail", fix)
        print_check(label, "fail", f"timed out after {timeout}s", fix)
        return False

    combined = (result.stdout or "") + (result.stderr or "")
    if result.returncode != 0 or (expect and expect not in combined):
        fix = recovery_fix(f"Run {subject} manually and repair the LDNDC installation")
        report_check(checks, "run", subject, critical, "fail", fix)
        detail = f"exit={result.returncode}; output={combined.strip()[:200]}"
        print_check(label, "fail", detail, fix)
        return False

    first_line = combined.strip().splitlines()[0] if combined.strip() else f"exit={result.returncode}"
    report_check(checks, "run", subject, critical, "pass", "")
    print_check(label, "pass", first_line)
    return True


def check_import(checks, module, label, critical=True):
    subject = f"{PYTHON_ENV} -c import {module}"
    if not PYTHON_ENV.is_file():
        fix = recovery_fix(f"Restore HydroCraft Python interpreter at {PYTHON_ENV}")
        report_check(checks, "import", subject, critical, "fail", fix)
        print_check(label, "fail", f"Python interpreter not found: {PYTHON_ENV}", fix)
        return False

    code = f"import importlib; importlib.import_module({module!r})"
    result = subprocess.run(
        [str(PYTHON_ENV), "-c", code],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode != 0:
        output = ((result.stderr or "") + (result.stdout or "")).strip()
        fix = recovery_fix(f"Install {module.split('.')[0]} into {PYTHON_ENV}")
        report_check(checks, "import", subject, critical, "fail", fix)
        print_check(label, "fail", output[:200], fix)
        return False
    report_check(checks, "import", subject, critical, "pass", "")
    print_check(label, "pass", f"import {module} via {PYTHON_ENV}")
    return True


def check_binary_in_path(checks, name, label, critical=True):
    found = shutil.which(name)
    if found:
        report_check(checks, "binary", Path(found).resolve(), critical, "pass", "")
        print_check(label, "pass", Path(found).resolve())
        return True
    fix = recovery_fix(f"Install {name} and ensure it is on PATH")
    report_check(checks, "binary", name, critical, "fail", fix)
    print_check(label, "fail", f"binary '{name}' not found on PATH", fix)
    return False


def check_ldd(checks):
    subject = f"ldd {LDNDC_BINARY.resolve() if LDNDC_BINARY.exists() else LDNDC_BINARY}"
    if not LDNDC_BINARY.is_file():
        fix = recovery_fix(f"Restore LDNDC binary before running ldd: {LDNDC_BINARY}")
        report_check(checks, "binary", subject, True, "fail", fix)
        print_check("LDNDC shared libraries", "fail", "binary missing", fix)
        return False

    result = subprocess.run(["ldd", str(LDNDC_BINARY)], capture_output=True, text=True, timeout=10)
    combined = (result.stdout or "") + (result.stderr or "")
    if result.returncode != 0 or "not found" in combined:
        fix = recovery_fix("Install missing shared libraries reported by ldd")
        report_check(checks, "binary", subject, True, "fail", fix)
        print_check("LDNDC shared libraries", "fail", combined.strip()[:300], fix)
        return False

    report_check(checks, "binary", subject, True, "pass", "")
    print_check("LDNDC shared libraries", "pass", "ldd reports no missing libraries")
    return True


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}, sort_keys=True))
    critical_failed = any(c["critical"] and c["status"] != "pass" for c in checks)
    sys.exit(1 if critical_failed else 0)


def main():
    checks = []

    print("=" * 60)
    print(f"  PREFLIGHT CHECK: {MODEL_ID}")
    print("=" * 60)
    print()

    print("Model binary and runtime")
    check_file(checks, LDNDC_BINARY, "LDNDC 1.37 binary", critical=True, executable=True)
    check_command(
        checks,
        [LDNDC_BINARY.resolve() if LDNDC_BINARY.exists() else LDNDC_BINARY, "--version"],
        "LDNDC starts",
        critical=True,
        cwd=LDNDC_BASE if LDNDC_BASE.is_dir() else None,
        expect="LandscapeDNDC",
    )
    check_ldd(checks)
    check_file(checks, LDNDC_BASE / "ldndc.conf", "LDNDC config", critical=True)
    check_file(checks, LDNDC_BASE / "Lresources", "LDNDC resource database", critical=True)
    check_file(checks, LDNDC_BASE / "parameters" / "species.xml", "LDNDC species parameters", critical=True)
    check_file(checks, LDNDC_BASE / "parameters" / "site.xml", "LDNDC site parameters", critical=True)
    check_file(checks, LDNDC_BASE / "parameters" / "soil.xml", "LDNDC soil parameters", critical=True)
    check_file(checks, Path.home() / ".ldndc" / "udunits2" / "udunits2.xml", "LDNDC udunits install", critical=True)

    print()
    print("KI tooling")
    check_file(checks, PYTHON_ENV, "HydroCraft Python interpreter", critical=True, executable=True)
    for module in [
        "numpy",
        "pandas",
        "rasterio",
        "ki_tools_common.humidity",
        "ki_tools_common.netcdf_utils",
        "ki_tools_common.load_forcing",
    ]:
        check_import(checks, module, f"Python import {module}", critical=True)
    check_binary_in_path(checks, "mdb-export", "mdbtools mdb-export", critical=True)

    print()
    print("KI files and data")
    check_file(checks, KI_DIR / "SKILL.md", "KI SKILL.md", critical=True)
    check_file(checks, KI_DIR / "knowledge_infrastructure.yaml", "KI manifest", critical=True)
    check_file(checks, KI_DIR / "dag.yaml", "KI DAG", critical=True)
    check_file(checks, TRIPLETS, "Diagnostic triplets", critical=True)
    check_file(checks, HYDROCRAFT_ROOT / "data" / "soil" / "HWSD_RASTER" / "hwsd.bil", "HWSD raster", critical=True)
    check_file(checks, HYDROCRAFT_ROOT / "data" / "forcing" / "huaihe_raw" / "soil" / "HWSD.mdb", "HWSD MDB", critical=True)
    for path, label in COMMON_DATA_DIRS:
        check_dir(checks, path, label, critical=False)

    print()
    passed = sum(1 for c in checks if c["status"] == "pass")
    failed = len(checks) - passed
    critical_failed = sum(1 for c in checks if c["critical"] and c["status"] != "pass")
    print(f"  Results: {passed} passed, {failed} failed, {critical_failed} critical failed")
    if critical_failed:
        print(f"  STATUS: PREFLIGHT FAILED - check fixes above, then consult {TRIPLETS}")
    else:
        print("  STATUS: PREFLIGHT PASSED - safe to proceed with LDNDC execution")

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
