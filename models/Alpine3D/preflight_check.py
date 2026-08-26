#!/usr/bin/env python3
"""Preflight check for the Alpine3D Knowledge Infrastructure."""

import json
import os
import subprocess
import sys


MODEL_ID = "Alpine3D"
KI_DIR = os.path.dirname(os.path.abspath(__file__))
HYDROCRAFT_PYTHON = "KISSPATH_PYTHON_ENV/bin/python"
MANIFEST_BINARY = (
    "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/Alpine3D/"
    "source/repo/Source/alpine3d/bin/alpine3d"
)


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}))
    sys.exit(0 if all(c["status"] == "pass" or not c.get("critical") for c in checks) else 1)


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
    label = "OK" if status == "pass" else "FAIL"
    print(f"  {label:<5} {kind}: {subject}")
    if status != "pass" and fix:
        print(f"        Fix: {fix}")


def check_file(checks, path, label, critical=True, executable=False):
    subject = os.path.realpath(path) if os.path.exists(path) else path
    if not os.path.isfile(path):
        add_check(
            checks,
            "data",
            subject,
            critical,
            "fail",
            f"Restore {label}; check diagnostics/triplets.yaml for recovery.",
        )
        return False
    if executable and not os.access(path, os.X_OK):
        add_check(
            checks,
            "binary",
            subject,
            critical,
            "fail",
            f"chmod +x {path}; check diagnostics/triplets.yaml if execution still fails.",
        )
        return False
    add_check(checks, "binary" if executable else "data", subject, critical, "pass")
    return True


def check_python_import(checks, module, critical=True):
    subject = f"{os.path.realpath(HYDROCRAFT_PYTHON)} -c import {module}"
    if not os.path.exists(HYDROCRAFT_PYTHON):
        add_check(
            checks,
            "import",
            subject,
            critical,
            "fail",
            "Restore KISSPATH_PYTHON_ENV/bin/python; check diagnostics/triplets.yaml.",
        )
        return False
    proc = subprocess.run(
        [HYDROCRAFT_PYTHON, "-c", f"import {module}"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if proc.returncode == 0:
        add_check(checks, "import", subject, critical, "pass")
        return True
    add_check(
        checks,
        "import",
        subject,
        critical,
        "fail",
        f"Install {module} into KISSPATH_PYTHON_ENV; see diagnostics/triplets.yaml.",
    )
    return False


def check_tool_compiles(checks, relpath, critical=True):
    path = os.path.join(KI_DIR, relpath)
    subject = os.path.realpath(path) if os.path.exists(path) else path
    if not os.path.isfile(path):
        add_check(
            checks,
            "data",
            subject,
            critical,
            "fail",
            f"Restore KI tool {relpath}; check diagnostics/triplets.yaml.",
        )
        return False
    proc = subprocess.run(
        [HYDROCRAFT_PYTHON, "-m", "py_compile", path],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode == 0:
        add_check(checks, "import", subject, critical, "pass")
        return True
    add_check(
        checks,
        "import",
        subject,
        critical,
        "fail",
        f"Fix Python syntax/import issue in {relpath}; check diagnostics/triplets.yaml. {proc.stderr[-300:]}",
    )
    return False


def check_binary_starts(checks, binary):
    subject = os.path.realpath(binary) if os.path.exists(binary) else binary
    if not check_file(checks, binary, "Alpine3D binary", critical=True, executable=True):
        return False
    try:
        proc = subprocess.run(
            [binary, "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        add_check(
            checks,
            "run",
            subject,
            True,
            "fail",
            "Alpine3D --help timed out; rebuild or repair the binary, then check diagnostics/triplets.yaml.",
        )
        return False
    except OSError as exc:
        add_check(
            checks,
            "run",
            subject,
            True,
            "fail",
            f"Alpine3D could not start: {exc}; check diagnostics/triplets.yaml.",
        )
        return False

    output = f"{proc.stdout}\n{proc.stderr}"
    if "Usage:" in output and ("Alpine3D" in output or "alpine3d" in output):
        add_check(checks, "run", subject, True, "pass")
        return True
    add_check(
        checks,
        "run",
        subject,
        True,
        "fail",
        "Alpine3D started but did not print expected help/version text; check diagnostics/triplets.yaml.",
    )
    return False


def main():
    checks = []
    print(f"{' PREFLIGHT: Alpine3D ':=^60}")
    print()

    check_binary_starts(checks, MANIFEST_BINARY)

    check_file(checks, HYDROCRAFT_PYTHON, "HydroCraft Python interpreter", critical=True, executable=True)
    for module in ("yaml", "numpy", "netCDF4"):
        check_python_import(checks, module, critical=True)

    for relpath in (
        "SKILL.md",
        "knowledge_infrastructure.yaml",
        "dag.yaml",
        "diagnostics/triplets.yaml",
        "docs/format_spec.yaml",
    ):
        check_file(checks, os.path.join(KI_DIR, relpath), relpath, critical=True)

    for relpath in (
        "tools/convert_forcing_to_smet.py",
        "tools/generate_sno_files.py",
        "tools/run_alpine3d.py",
        "tools/parse_alpine3d_output.py",
    ):
        check_tool_compiles(checks, relpath, critical=True)

    print()
    passed = sum(1 for c in checks if c["status"] == "pass")
    failed = len(checks) - passed
    print(f"  Results: {passed} passed, {failed} failed")
    if failed:
        print("  STATUS: PREFLIGHT FAILED - fix blockers above; start with diagnostics/triplets.yaml.")
    else:
        print("  STATUS: PREFLIGHT PASSED - Alpine3D KI is ready for model execution.")
    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
