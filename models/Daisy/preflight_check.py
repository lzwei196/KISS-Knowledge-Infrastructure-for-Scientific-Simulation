#!/usr/bin/env python3
"""Preflight check for Daisy knowledge infrastructure.

This script verifies the real Daisy executable, KI tool dependencies, required
KI files, calibration assets, and Daisy library files before any model run.
It always ends with a PREFLIGHT_REPORT= JSON line for the KDT gate.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


MODEL_ID = "Daisy"
KI_DIR = Path(__file__).resolve().parent
TOOLS_DIR = KI_DIR / "tools"
DIAGNOSTICS = KI_DIR / "diagnostics" / "triplets.yaml"

PYTHON_ENV = Path("KISSPATH_PYTHON_ENV/bin/python")
DAISY_BIN = Path("KISSPATH_KI_ROOT/Daisy/bin/daisy")
DAISY_REPO = Path("KISSPATH_KI_ROOT/Daisy/source/repo")
DAISY_LIB = DAISY_REPO / "lib"


def recovery_fix(detail: str) -> str:
    return f"{detail}; check diagnostics/triplets.yaml for known Daisy recovery steps"


def add_check(checks, kind, subject, critical, passed, fix=""):
    subject = str(subject)
    status = "pass" if passed else "fail"
    checks.append(
        {
            "kind": kind,
            "subject": subject,
            "critical": bool(critical),
            "status": status,
            "fix": "" if passed else fix,
        }
    )
    label = "OK" if passed else ("FAIL" if critical else "WARN")
    print(f"  {label:<5} {kind}: {subject}")
    if not passed and fix:
        print(f"        Fix: {fix}")


def check_file(checks, path, label, critical=True, executable=False, kind=None):
    path = Path(path)
    exists = path.is_file()
    executable_ok = (not executable) or os.access(path, os.X_OK)
    passed = exists and executable_ok
    subject = path.resolve(strict=False)
    if not exists:
        fix = recovery_fix(f"restore required file for {label}: {path}")
    elif executable and not executable_ok:
        fix = recovery_fix(f"make {label} executable: chmod +x {path}")
    else:
        fix = ""
    add_check(checks, kind or ("binary" if executable else "data"), subject, critical, passed, fix)
    return passed


def check_python_interpreter(checks):
    exists = PYTHON_ENV.is_file()
    executable_ok = exists and os.access(PYTHON_ENV, os.X_OK)
    if not exists:
        fix = recovery_fix(f"restore HydroCraft Python interpreter at {PYTHON_ENV}")
    elif not executable_ok:
        fix = recovery_fix(f"make HydroCraft Python interpreter executable: chmod +x {PYTHON_ENV}")
    else:
        fix = ""
    add_check(checks, "run", PYTHON_ENV, True, executable_ok, fix)
    return executable_ok


def check_dir(checks, path, label, critical=True, min_items=1):
    path = Path(path)
    exists = path.is_dir()
    item_count = len(list(path.iterdir())) if exists else 0
    passed = exists and item_count >= min_items
    subject = path.resolve(strict=False)
    if not exists:
        fix = recovery_fix(f"restore required directory for {label}: {path}")
    else:
        fix = recovery_fix(f"populate {label}: {path} has {item_count} items, expected at least {min_items}")
    add_check(checks, "data", subject, critical, passed, fix)
    return passed


def check_python_import(checks, module, critical=True):
    if not PYTHON_ENV.is_file():
        add_check(
            checks,
            "import",
            f"{PYTHON_ENV}:import {module}",
            critical,
            False,
            recovery_fix(f"restore HydroCraft Python interpreter at {PYTHON_ENV}"),
        )
        return False

    cmd = [str(PYTHON_ENV), "-c", f"import importlib; importlib.import_module({module!r})"]
    proc = subprocess.run(cmd, text=True, capture_output=True, timeout=20)
    passed = proc.returncode == 0
    stderr = (proc.stderr or proc.stdout or "").strip().splitlines()
    detail = stderr[-1] if stderr else f"install Python package for import {module}"
    add_check(
        checks,
        "import",
        f"{PYTHON_ENV}:import {module}",
        critical,
        passed,
        recovery_fix(detail),
    )
    return passed


def check_py_compile(checks, path, critical=True):
    path = Path(path)
    if not path.is_file():
        add_check(
            checks,
            "import",
            path.resolve(strict=False),
            critical,
            False,
            recovery_fix(f"restore KI tool file: {path}"),
        )
        return False

    cmd = [str(PYTHON_ENV if PYTHON_ENV.is_file() else sys.executable), "-m", "py_compile", str(path)]
    proc = subprocess.run(cmd, text=True, capture_output=True, timeout=20, cwd=str(KI_DIR))
    passed = proc.returncode == 0
    stderr = (proc.stderr or proc.stdout or "").strip().splitlines()
    detail = stderr[-1] if stderr else f"fix Python syntax/import-time compile issue in {path}"
    add_check(
        checks,
        "import",
        path.resolve(strict=False),
        critical,
        passed,
        recovery_fix(detail),
    )
    return passed


def check_daisy_starts(checks, binary):
    binary = Path(binary)
    subject = binary.resolve(strict=False)
    if not binary.is_file() or not os.access(binary, os.X_OK):
        add_check(
            checks,
            "run",
            subject,
            True,
            False,
            recovery_fix(f"restore executable Daisy binary at {binary} before testing startup"),
        )
        return False

    with tempfile.TemporaryDirectory(prefix="daisy-preflight-") as td:
        proc = subprocess.run(
            [str(binary), "-v"],
            cwd=td,
            text=True,
            capture_output=True,
            timeout=20,
        )
    output = "\n".join(part for part in [proc.stdout, proc.stderr] if part).strip()
    passed = proc.returncode == 0 and "Daisy" in output and "7.1.4" in output
    fix = recovery_fix(
        "Daisy binary did not start with '-v' as v7.1.4; rebuild/reinstall the real model binary"
    )
    add_check(checks, "run", subject, True, passed, fix)
    return passed


def emit_report(model_id, checks):
    if not checks:
        checks.append(
            {
                "kind": "run",
                "subject": "preflight_check.py",
                "critical": True,
                "status": "fail",
                "fix": recovery_fix("preflight produced zero checks"),
            }
        )
    if not any(c.get("critical") for c in checks):
        checks.append(
            {
                "kind": "run",
                "subject": "preflight_check.py",
                "critical": True,
                "status": "fail",
                "fix": recovery_fix("add at least one critical preflight check"),
            }
        )

    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}, sort_keys=True))
    critical_failed = any(c["status"] != "pass" and c.get("critical") for c in checks)
    sys.exit(1 if critical_failed else 0)


def main():
    checks = []

    print(f"{' PREFLIGHT: Daisy ':=^60}")
    print()

    real_binary = DAISY_BIN.resolve(strict=False)
    check_file(checks, real_binary, "Daisy binary", critical=True, executable=True)
    check_daisy_starts(checks, real_binary)

    check_python_interpreter(checks)
    for module in ("numpy", "pandas", "yaml", "ki_tools_common.metrics"):
        check_python_import(checks, module, critical=True)

    check_dir(checks, TOOLS_DIR, "KI tools directory", critical=True, min_items=5)
    for name in (
        "calib_run.py",
        "convert_soil_to_dai.py",
        "convert_weather_to_dwf.py",
        "parse_daisy_output.py",
        "run_daisy.py",
    ):
        check_py_compile(checks, TOOLS_DIR / name, critical=True)

    check_file(checks, KI_DIR / "SKILL.md", "KI skill instructions", critical=True)
    check_file(checks, KI_DIR / "knowledge_infrastructure.yaml", "KI manifest", critical=True)
    check_file(checks, KI_DIR / "dag.yaml", "KI DAG", critical=True)
    check_file(checks, DIAGNOSTICS, "diagnostic triplets", critical=True)

    for name in (
        "main_template.dai",
        "crop_params.dai",
        "usne3.dwf",
        "usne3_soil.dai",
        "usne3_obs_et.csv",
        "usne3_met_2002_2008.csv",
    ):
        check_file(checks, KI_DIR / "calibration_assets" / name, f"calibration asset {name}", critical=True)

    check_dir(checks, DAISY_LIB, "Daisy library directory", critical=True, min_items=10)
    for name in ("crop.dai", "maize.dai", "tillage.dai", "log.dai", "fertilizer.dai"):
        check_file(checks, DAISY_LIB / name, f"Daisy library {name}", critical=True)

    failed = [c for c in checks if c["status"] != "pass"]
    print()
    print(f"  Results: {len(checks) - len(failed)} passed, {len(failed)} failed")
    if failed:
        print("  STATUS: PREFLIGHT FAILED - fix blockers above before running Daisy")
    else:
        print("  STATUS: PREFLIGHT PASSED - real Daisy binary and KI runtime are ready")

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
