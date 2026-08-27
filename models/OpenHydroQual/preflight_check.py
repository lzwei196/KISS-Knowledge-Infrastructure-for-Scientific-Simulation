#!/usr/bin/env python3
"""Preflight check for the OpenHydroQual KI."""

import json
import os
import py_compile
import shutil
import subprocess
import sys
from pathlib import Path


MODEL_ID = "OpenHydroQual"
KI_DIR = Path(__file__).resolve().parent
TRIPLETS = KI_DIR / "diagnostics" / "triplets.yaml"
DIAGNOSTIC_FIX = f"See {TRIPLETS} for matching recovery triplets."

OHQ_BINARY = Path(
    "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/"
    "OpenHydroQual/source/repo/OHQLibTest/OHQLibTest"
)
OHQ_RESOURCES = (OHQ_BINARY.parent / "../../../resources").resolve()

TOOL_FILES = [
    KI_DIR / "tools" / "convert_forcing.py",
    KI_DIR / "tools" / "convert_parameters.py",
    KI_DIR / "tools" / "run_ohq.py",
    KI_DIR / "tools" / "parse_output.py",
]


def make_check(kind, subject, critical, status, fix=""):
    check = {
        "kind": kind,
        "subject": str(subject),
        "critical": bool(critical),
        "status": status,
        "fix": fix if status == "fail" else "",
    }
    print(f"  {'OK' if status == 'pass' else 'FAIL':<5} {kind}: {subject}")
    if status == "fail" and fix:
        print(f"        Fix: {fix}")
    return check


def check_file(path, label, critical=True, executable=False):
    path = Path(path)
    subject = str(path.resolve()) if path.exists() else str(path)
    if not path.is_file():
        return make_check(
            "binary" if executable else "data",
            subject,
            critical,
            "fail",
            f"{label} is missing. Restore the KI dependency or rebuild it. {DIAGNOSTIC_FIX}",
        )
    if executable and not os.access(path, os.X_OK):
        return make_check(
            "binary",
            subject,
            critical,
            "fail",
            f"{label} is not executable; run chmod +x {subject}. {DIAGNOSTIC_FIX}",
        )
    return make_check("binary" if executable else "data", subject, critical, "pass")


def check_dir(path, label, critical=True):
    path = Path(path)
    subject = str(path.resolve()) if path.exists() else str(path)
    if not path.is_dir():
        return make_check(
            "data",
            subject,
            critical,
            "fail",
            f"{label} is missing. Restore the KI layout. {DIAGNOSTIC_FIX}",
        )
    if not any(path.iterdir()):
        return make_check(
            "data",
            subject,
            critical,
            "fail",
            f"{label} is empty. Restore required files. {DIAGNOSTIC_FIX}",
        )
    return make_check("data", subject, critical, "pass")


def check_ldd(binary):
    subject = str(binary.resolve()) if binary.exists() else str(binary)
    ldd = shutil.which("ldd")
    if not ldd:
        return make_check(
            "run",
            f"ldd for {subject}",
            False,
            "fail",
            f"Install ldd or verify shared libraries manually. {DIAGNOSTIC_FIX}",
        )
    if not binary.is_file():
        return make_check(
            "run",
            f"ldd for {subject}",
            True,
            "fail",
            f"Cannot inspect shared libraries because the binary is missing. {DIAGNOSTIC_FIX}",
        )
    try:
        proc = subprocess.run(
            [ldd, str(binary)],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return make_check(
            "run",
            f"ldd for {subject}",
            True,
            "fail",
            f"ldd timed out. Check shared library configuration. {DIAGNOSTIC_FIX}",
        )

    output = proc.stdout + proc.stderr
    missing = [line.strip() for line in output.splitlines() if "not found" in line]
    if proc.returncode != 0 or missing:
        detail = "; ".join(missing) if missing else output.strip()[:500]
        return make_check(
            "run",
            f"ldd for {subject}",
            True,
            "fail",
            f"Resolve missing shared libraries ({detail}). {DIAGNOSTIC_FIX}",
        )
    return make_check("run", f"ldd for {subject}", True, "pass")


def check_binary_starts(binary):
    subject = str(binary.resolve()) if binary.exists() else str(binary)
    if not binary.is_file():
        return make_check(
            "run",
            subject,
            True,
            "fail",
            f"Cannot start OpenHydroQual because the binary is missing. {DIAGNOSTIC_FIX}",
        )
    try:
        proc = subprocess.run(
            [str(binary)],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return make_check(
            "run",
            subject,
            True,
            "fail",
            f"OpenHydroQual did not return from its no-input startup check within 5 seconds. {DIAGNOSTIC_FIX}",
        )

    output = f"{proc.stdout}\n{proc.stderr}"
    # OHQLibTest starts correctly without an input file by printing usage and
    # returning 1. That is a cheap startup check, not a model run.
    if "Usage: OHQLibTest <input_file>" in output:
        return make_check("run", subject, True, "pass")
    return make_check(
        "run",
        subject,
        True,
        "fail",
        f"OpenHydroQual started but did not print the expected usage banner. Exit={proc.returncode}. {DIAGNOSTIC_FIX}",
    )


def check_tool_compile(path):
    path = Path(path)
    subject = str(path.resolve()) if path.exists() else str(path)
    if not path.is_file():
        return make_check(
            "import",
            subject,
            True,
            "fail",
            f"Required KI tool is missing. Restore {path.name}. {DIAGNOSTIC_FIX}",
        )
    try:
        py_compile.compile(str(path), doraise=True)
    except py_compile.PyCompileError as exc:
        return make_check(
            "import",
            subject,
            True,
            "fail",
            f"Required KI tool does not compile with {sys.executable}: {exc.msg}. {DIAGNOSTIC_FIX}",
        )
    return make_check("import", subject, True, "pass")


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}))
    failed_critical = any(
        check["status"] == "fail" and check.get("critical") for check in checks
    )
    sys.exit(1 if failed_critical else 0)


def main():
    checks = []
    print(f"{' PREFLIGHT: OpenHydroQual ':=^60}")

    checks.append(check_dir(KI_DIR / "tools", "KI tools directory", critical=True))
    for tool in TOOL_FILES:
        checks.append(check_tool_compile(tool))

    checks.append(check_file(OHQ_BINARY, "OpenHydroQual OHQLibTest binary", critical=True, executable=True))
    checks.append(check_ldd(OHQ_BINARY))
    checks.append(check_binary_starts(OHQ_BINARY))

    checks.append(check_dir(OHQ_RESOURCES, "OpenHydroQual runtime resources", critical=True))
    checks.append(check_file(OHQ_RESOURCES / "main_components.json", "main component template", critical=True))
    checks.append(check_file(OHQ_RESOURCES / "settings.json", "solver settings template", critical=True))

    checks.append(check_file(TRIPLETS, "diagnostic triplets", critical=False))

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
