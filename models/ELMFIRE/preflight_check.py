#!/usr/bin/env python3
"""Preflight check for the ELMFIRE knowledge infrastructure."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


MODEL_ID = "ELMFIRE"
KI_DIR = Path(__file__).resolve().parent
PYTHON_ENV = Path("KISSPATH_PYTHON_ENV/bin/python")
ELMFIRE_BINARY = Path(
    "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/ELMFIRE/"
    "source/repo/build/linux/bin/elmfire_2025.1002"
)

CHECKS = []


def add_check(kind, subject, critical, passed, fix):
    status = "pass" if passed else "fail"
    CHECKS.append(
        {
            "kind": kind,
            "subject": str(subject),
            "critical": bool(critical),
            "status": status,
            "fix": "" if passed else fix,
        }
    )
    label = "OK" if passed else ("FAIL" if critical else "WARN")
    print(f"  {label:<5} {kind}: {subject}")
    if not passed:
        print(f"        Fix: {fix}")


def check_file(path, label, critical=True, executable=False):
    path = Path(path)
    exists = path.is_file()
    passed = exists and (not executable or os.access(path, os.X_OK))
    subject = path.resolve() if exists else path
    if not exists:
        fix = (
            f"Restore required file: {path}. Check diagnostics/triplets.yaml for "
            "matching recovery steps."
        )
    elif executable:
        fix = f"Make executable: chmod +x {path}"
    else:
        fix = f"Repair inaccessible file: {path}"
    add_check(label, subject, critical, passed, fix)
    return passed, subject


def check_dir(path, label, critical=True, nonempty=False):
    path = Path(path)
    exists = path.is_dir()
    passed = exists and (not nonempty or any(path.iterdir()))
    if not exists:
        fix = (
            f"Restore required directory: {path}. Check diagnostics/triplets.yaml "
            "for matching recovery steps."
        )
    else:
        fix = f"Populate required directory: {path}"
    add_check(label, path.resolve() if exists else path, critical, passed, fix)
    return passed


def check_command(name, critical=True):
    found = shutil.which(name)
    subject = Path(found).resolve() if found else name
    fix = (
        f"Install {name} or add it to PATH. For ELMFIRE, see "
        "diagnostics/triplets.yaml and SKILL.md dependency notes."
    )
    add_check("binary", subject, critical, bool(found), fix)
    return bool(found)


def check_python_import(module, critical=True):
    if not PYTHON_ENV.is_file():
        add_check(
            "import",
            f"{module} via {PYTHON_ENV}",
            critical,
            False,
            f"Restore HydroCraft Python environment at {PYTHON_ENV}.",
        )
        return False
    result = subprocess.run(
        [str(PYTHON_ENV), "-c", f"import {module}"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    passed = result.returncode == 0
    detail = (result.stderr or result.stdout).strip().splitlines()
    reason = f": {detail[-1]}" if detail else ""
    add_check(
        "import",
        f"{module} via {PYTHON_ENV}",
        critical,
        passed,
        f"Install/repair Python package '{module}' in {PYTHON_ENV}{reason}. "
        "Check diagnostics/triplets.yaml before substituting behavior.",
    )
    return passed


def check_binary_starts(binary):
    real_binary = Path(binary).resolve()
    if not real_binary.is_file() or not os.access(real_binary, os.X_OK):
        add_check(
            "run",
            f"{real_binary} --help",
            True,
            False,
            f"Restore executable ELMFIRE binary at {real_binary}.",
        )
        return False

    result = subprocess.run(
        [str(real_binary), "--help"],
        capture_output=True,
        text=True,
        timeout=5,
        cwd=str(KI_DIR),
    )
    output = f"{result.stdout}\n{result.stderr}"
    passed = result.returncode == 0 and "ELMFIRE 2025.1002" in output
    add_check(
        "run",
        f"{real_binary} --help",
        True,
        passed,
        f"ELMFIRE did not start cleanly. Check diagnostics/triplets.yaml. "
        f"Return code: {result.returncode}; output: {output[:300].strip()}",
    )
    return passed


def emit_report():
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": MODEL_ID, "checks": CHECKS}))
    has_failed_critical = any(
        check["critical"] and check["status"] != "pass" for check in CHECKS
    )
    sys.exit(1 if has_failed_critical else 0)


def main():
    print(f"{' PREFLIGHT: ELMFIRE ':=^60}")
    print(f"KI: {KI_DIR}")
    print()

    binary_ok, binary_subject = check_file(
        ELMFIRE_BINARY, "binary", critical=True, executable=True
    )
    if binary_ok:
        print(f"        Verified executable realpath: {binary_subject}")
    check_binary_starts(ELMFIRE_BINARY)

    check_file(PYTHON_ENV, "binary", critical=True, executable=True)
    for module in ("numpy", "osgeo.gdal", "yaml"):
        check_python_import(module, critical=True)

    for command in ("gdalinfo", "gdalwarp", "gdal_translate", "gdal_calc.py"):
        check_command(command, critical=True)
    check_command("mpirun", critical=True)

    check_dir(KI_DIR / "tools", "data", critical=True, nonempty=True)
    for relpath in (
        "tools/convert_landscape_to_elmfire.py",
        "tools/convert_weather_to_elmfire.py",
        "tools/run_elmfire.py",
        "tools/parse_elmfire_output.py",
        "SKILL.md",
        "knowledge_infrastructure.yaml",
        "dag.yaml",
        "docs/format_spec.yaml",
        "diagnostics/triplets.yaml",
    ):
        check_file(KI_DIR / relpath, "data", critical=True)

    print()
    passed = sum(1 for check in CHECKS if check["status"] == "pass")
    failed = len(CHECKS) - passed
    print(f"Results: {passed} passed, {failed} failed")
    if failed:
        print("Blockers found. Start recovery with diagnostics/triplets.yaml.")
    else:
        print("Preflight passed. The real ELMFIRE runtime is available.")
    emit_report()


if __name__ == "__main__":
    main()
