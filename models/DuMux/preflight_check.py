#!/usr/bin/env python3
"""Preflight check for the DuMux Knowledge Infrastructure."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


MODEL_ID = "DuMux"
KI_DIR = Path(__file__).resolve().parent
TRIPLETS = KI_DIR / "diagnostics" / "triplets.yaml"
PYTHON_ENV = Path("KISSPATH_PYTHON_ENV/bin/python3")
PYTHON = str(PYTHON_ENV if PYTHON_ENV.exists() else Path(sys.executable))

BINARY_PATH = Path(
    "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/DuMux/"
    "dumux_real_run/example_1ptracer"
)
RUN_DIR = BINARY_PATH.parent
PARAMS_INPUT = RUN_DIR / "params.input"


checks = []


def triplets_fix(action):
    return f"{action}; then check {TRIPLETS} for matching recovery triplets."


def add_check(kind, subject, critical, passed, fix=""):
    status = "pass" if passed else "fail"
    check = {
        "kind": kind,
        "subject": str(subject),
        "critical": bool(critical),
        "status": status,
        "fix": "" if passed else fix,
    }
    checks.append(check)
    label = "OK" if passed else "FAIL"
    print(f"  {label:<5} {kind}: {subject}")
    if not passed and fix:
        print(f"        Fix: {fix}")
    return passed


def check_file(path, label, critical=True, executable=False, subject=None):
    path = Path(path)
    subject = subject or path
    exists = path.is_file()
    executable_ok = (not executable) or os.access(path, os.X_OK)
    passed = exists and executable_ok
    if not exists:
        fix = triplets_fix(f"Restore or rebuild missing {label}: {path}")
    elif not executable_ok:
        fix = triplets_fix(f"Make {label} executable: chmod +x {path}")
    else:
        fix = ""
    return add_check("binary" if executable else "data", subject, critical, passed, fix)


def check_dir(path, label, critical=True, non_empty=True):
    path = Path(path)
    passed = path.is_dir() and ((not non_empty) or any(path.iterdir()))
    fix = triplets_fix(f"Restore required {label}: {path}")
    return add_check("data", path, critical, passed, fix)


def check_import(module, label, critical=True):
    code = f"import {module}"
    proc = subprocess.run(
        [PYTHON, "-c", code],
        cwd=str(KI_DIR),
        text=True,
        capture_output=True,
        timeout=20,
    )
    fix = triplets_fix(
        f"Install {label} for {PYTHON}: {PYTHON} -m pip install {module.split('.')[0]}"
    )
    return add_check("import", f"{module} via {PYTHON}", critical, proc.returncode == 0, fix)


def check_script_import(script, critical=True):
    script_path = KI_DIR / script
    module = script.replace("/", ".").removesuffix(".py")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(KI_DIR) + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [PYTHON, "-m", "py_compile", str(script_path)],
        cwd=str(KI_DIR),
        env=env,
        text=True,
        capture_output=True,
        timeout=20,
    )
    fix = triplets_fix(f"Repair syntax/import readiness for KI tool {script}")
    return add_check("import", module, critical, proc.returncode == 0, fix)


def check_command(name, critical=False):
    found = shutil.which(name)
    fix = triplets_fix(f"Install required build command '{name}' or load the DuMux build environment")
    return add_check("run", name, critical, bool(found), fix)


def check_binary_starts(binary, critical=True):
    real_binary = os.path.realpath(binary)
    try:
        proc = subprocess.run(
            [str(binary), "--help"],
            cwd=str(RUN_DIR),
            text=True,
            capture_output=True,
            timeout=10,
        )
        passed = proc.returncode == 0
    except Exception:
        passed = False
    fix = triplets_fix(f"Rebuild DuMux example binary and verify it starts: {real_binary}")
    return add_check("run", real_binary, critical, passed, fix)


def emit_report(model_id, report_checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": report_checks}))
    has_failed_critical = any(c["critical"] and c["status"] != "pass" for c in report_checks)
    sys.exit(1 if has_failed_critical else 0)


def main():
    print(f"{' PREFLIGHT: DuMux ':=^60}")
    print(f"  KI root: {KI_DIR}")
    print(f"  Python for import checks: {PYTHON}")
    print()

    real_binary = os.path.realpath(BINARY_PATH)

    check_dir(KI_DIR / "tools", "KI tools directory", critical=True)
    check_file(BINARY_PATH, "DuMux binary", critical=True, executable=True, subject=real_binary)
    check_binary_starts(BINARY_PATH, critical=True)
    check_file(PARAMS_INPUT, "DuMux smoke-run params.input", critical=True)
    check_file(TRIPLETS, "diagnostic triplets", critical=False)

    for script in [
        "tools/convert_forcing_to_dumux.py",
        "tools/convert_soil_to_dumux.py",
        "tools/parse_dumux_output.py",
        "tools/run_dumux.py",
    ]:
        check_file(KI_DIR / script, f"KI tool {script}", critical=True)
        check_script_import(script, critical=True)

    check_import("numpy", "numpy", critical=True)
    check_command("cmake", critical=False)
    check_command("make", critical=False)

    print()
    passed = sum(1 for c in checks if c["status"] == "pass")
    failed = len(checks) - passed
    print(f"  Results: {passed} passed, {failed} failed")
    if any(c["critical"] and c["status"] != "pass" for c in checks):
        print(f"  STATUS: PREFLIGHT FAILED - fix blockers above; start with {TRIPLETS}")
    else:
        print("  STATUS: PREFLIGHT PASSED - safe to proceed with DuMux execution")

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
