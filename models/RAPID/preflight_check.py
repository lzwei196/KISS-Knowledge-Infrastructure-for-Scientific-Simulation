#!/usr/bin/env python3
"""Preflight check for the RAPID knowledge infrastructure."""

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path


MODEL_ID = "RAPID"
KI_DIR = Path(__file__).resolve().parent
TRIPLETS = KI_DIR / "diagnostics" / "triplets.yaml"
RAPID_BINARY = Path(
    "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/RAPID/source/repo/src/rapid"
)

REQUIRED_KI_FILES = [
    "SKILL.md",
    "knowledge_infrastructure.yaml",
    "dag.yaml",
    "diagnostics/triplets.yaml",
    "docs/format_spec.yaml",
    "tools/build_connectivity.py",
    "tools/convert_lsm_to_vlat.py",
    "tools/generate_muskingum_params.py",
    "tools/generate_namelist.py",
    "tools/parse_rapid_output.py",
    "tools/run_rapid.py",
]

REQUIRED_IMPORTS = [
    ("numpy", "pip install numpy"),
    ("netCDF4", "pip install netCDF4"),
    ("networkx", "pip install networkx"),
]


def fix_text(remedy):
    return f"{remedy}; then check {TRIPLETS} for RAPID-specific recovery guidance."


def check(kind, subject, critical, status, fix=""):
    item = {
        "kind": kind,
        "subject": str(subject),
        "critical": bool(critical),
        "status": status,
        "fix": fix if status == "fail" else "",
    }
    label = "OK" if status == "pass" else "FAIL"
    print(f"  {label:<4} {kind:<6} {subject}")
    if status == "fail" and fix:
        print(f"       Fix: {fix}")
    return item


def check_file(path, label, critical=True, executable=False):
    path = Path(path)
    subject = path.resolve() if path.exists() else path
    if not path.is_file():
        return check(
            "data",
            f"{label}: {subject}",
            critical,
            "fail",
            fix_text(f"Restore or regenerate required file {path}"),
        )
    if executable and not os.access(path, os.X_OK):
        return check(
            "binary",
            path.resolve(),
            critical,
            "fail",
            fix_text(f"Make executable with chmod +x {path}"),
        )
    return check("binary" if executable else "data", subject, critical, "pass")


def check_binary_start(binary):
    subject = binary.resolve()
    try:
        result = subprocess.run(
            [str(subject), "--help"],
            cwd=str(KI_DIR),
            capture_output=True,
            text=True,
            timeout=5,
        )
    except subprocess.TimeoutExpired:
        return check(
            "run",
            f"{subject} --help",
            True,
            "fail",
            fix_text("RAPID executable did not return from --help within 5 seconds"),
        )
    except OSError as exc:
        return check(
            "run",
            f"{subject} --help",
            True,
            "fail",
            fix_text(f"RAPID executable could not start: {exc}"),
        )

    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        suffix = f": {detail[-1]}" if detail else ""
        return check(
            "run",
            f"{subject} --help",
            True,
            "fail",
            fix_text(f"RAPID executable started but exited {result.returncode}{suffix}"),
        )
    return check("run", f"{subject} --help", True, "pass")


def check_import(module, remedy):
    try:
        importlib.import_module(module)
    except Exception as exc:
        return check(
            "import",
            f"{sys.executable}: import {module}",
            True,
            "fail",
            fix_text(f"{remedy} for interpreter {sys.executable} ({exc})"),
        )
    return check("import", f"{sys.executable}: import {module}", True, "pass")


def check_py_compile():
    tools = [str(KI_DIR / item) for item in REQUIRED_KI_FILES if item.startswith("tools/")]
    result = subprocess.run(
        [sys.executable, "-m", "py_compile", *tools],
        cwd=str(KI_DIR),
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        suffix = f": {detail[-1]}" if detail else ""
        return check(
            "run",
            f"{sys.executable} -m py_compile tools/*.py",
            True,
            "fail",
            fix_text(f"Fix syntax/import-time errors in RAPID tools{suffix}"),
        )
    return check("run", f"{sys.executable} -m py_compile tools/*.py", True, "pass")


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}))
    sys.exit(0 if all(c["status"] == "pass" or not c.get("critical") for c in checks) else 1)


def main():
    print(f"{' PREFLIGHT: RAPID ':=^60}")
    print(f"KI directory: {KI_DIR}")
    print()

    checks = []

    binary_check = check_file(RAPID_BINARY, "RAPID executable", critical=True, executable=True)
    checks.append(binary_check)
    if binary_check["status"] == "pass":
        checks.append(check_binary_start(RAPID_BINARY))

    for module, remedy in REQUIRED_IMPORTS:
        checks.append(check_import(module, remedy))

    for relpath in REQUIRED_KI_FILES:
        checks.append(check_file(KI_DIR / relpath, relpath, critical=True))

    checks.append(check_py_compile())

    print()
    passed = sum(1 for item in checks if item["status"] == "pass")
    failed = len(checks) - passed
    print(f"  Results: {passed} passed, {failed} failed")
    if failed:
        print(f"  STATUS: PREFLIGHT FAILED; check {TRIPLETS} before recovery work.")
    else:
        print("  STATUS: PREFLIGHT PASSED; RAPID is ready for model execution.")

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
