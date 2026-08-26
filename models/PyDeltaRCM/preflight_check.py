#!/usr/bin/env python3
"""Preflight checks for the PyDeltaRCM Knowledge Infrastructure."""

import json
import os
import subprocess
import sys
from pathlib import Path


MODEL_ID = "PyDeltaRCM"
KI_DIR = Path(__file__).resolve().parent
TRIPLETS = KI_DIR / "diagnostics" / "triplets.yaml"

# This is the executable recorded for PyDeltaRCM in the KI manifest / models table.
# It is a venv wrapper around /usr/bin/python3.12; invoking the wrapper path is
# required so Python activates the venv package context.
MODEL_PYTHON = Path(
    "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/"
    "PyDeltaRCM/venv/bin/python"
)
MODEL_CLI = MODEL_PYTHON.parent / "pyDeltaRCM"


def fix(message):
    return f"{message}; then check {TRIPLETS} for matching recovery triplets."


def add_check(checks, kind, subject, critical, status, fix_text=""):
    check = {
        "kind": kind,
        "subject": str(subject),
        "critical": bool(critical),
        "status": status,
        "fix": fix_text if status == "fail" else "",
    }
    checks.append(check)
    prefix = "OK" if status == "pass" else "FAIL"
    print(f"  {prefix:<4} {kind}: {subject}")
    if status == "fail" and fix_text:
        print(f"       Fix: {fix_text}")
    return status == "pass"


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}))
    ready = checks and all(
        check["status"] == "pass" or not check.get("critical") for check in checks
    )
    sys.exit(0 if ready else 1)


def run_command(args, timeout=15):
    return subprocess.run(
        [str(arg) for arg in args],
        cwd=str(KI_DIR),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )


def check_executable(checks, path, label, critical=True):
    subject = os.path.realpath(path)
    if not path.is_file():
        return add_check(
            checks,
            "binary",
            subject,
            critical,
            "fail",
            fix(f"Install or restore {label} at {path}"),
        )
    if not os.access(path, os.X_OK):
        return add_check(
            checks,
            "binary",
            subject,
            critical,
            "fail",
            fix(f"Make {label} executable with chmod +x {path}"),
        )

    try:
        proc = run_command([path, "-c", "import sys; print(sys.prefix)"], timeout=10)
    except Exception as exc:
        return add_check(
            checks,
            "binary",
            subject,
            critical,
            "fail",
            fix(f"{label} exists but did not start: {exc}"),
        )

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip().splitlines()
        reason = detail[-1] if detail else f"exit code {proc.returncode}"
        return add_check(
            checks,
            "binary",
            subject,
            critical,
            "fail",
            fix(f"{label} exists but failed to start ({reason})"),
        )
    return add_check(checks, "binary", subject, critical, "pass")


def check_import(checks, module, critical=True):
    code = (
        "import importlib; "
        f"mod = importlib.import_module({module!r}); "
        "print(getattr(mod, '__version__', 'imported'))"
    )
    subject = f"{MODEL_PYTHON}: import {module}"
    try:
        proc = run_command([MODEL_PYTHON, "-c", code], timeout=20)
    except Exception as exc:
        return add_check(
            checks,
            "import",
            subject,
            critical,
            "fail",
            fix(f"Import check for {module} could not run: {exc}"),
        )

    if proc.returncode == 0:
        return add_check(checks, "import", subject, critical, "pass")

    detail = (proc.stderr or proc.stdout).strip().splitlines()
    reason = detail[-1] if detail else f"exit code {proc.returncode}"
    return add_check(
        checks,
        "import",
        subject,
        critical,
        "fail",
        fix(f"Install {module.split('.')[0]} into the PyDeltaRCM runtime ({reason})"),
    )


def check_file(checks, path, label, critical=True):
    if path.is_file():
        return add_check(checks, "data", path, critical, "pass")
    return add_check(
        checks,
        "data",
        path,
        critical,
        "fail",
        fix(f"Restore required {label} at {path}"),
    )


def check_cli_starts(checks):
    subject = os.path.realpath(MODEL_CLI)
    if not MODEL_CLI.is_file():
        return add_check(
            checks,
            "run",
            subject,
            True,
            "fail",
            fix(f"Restore pyDeltaRCM console script at {MODEL_CLI}"),
        )
    if not os.access(MODEL_CLI, os.X_OK):
        return add_check(
            checks,
            "run",
            subject,
            True,
            "fail",
            fix(f"Make pyDeltaRCM console script executable with chmod +x {MODEL_CLI}"),
        )

    try:
        proc = run_command([MODEL_CLI, "--help"], timeout=15)
    except Exception as exc:
        return add_check(
            checks,
            "run",
            subject,
            True,
            "fail",
            fix(f"pyDeltaRCM console script did not start: {exc}"),
        )

    if proc.returncode == 0 and "pyDeltaRCM" in proc.stdout:
        return add_check(checks, "run", subject, True, "pass")

    detail = (proc.stderr or proc.stdout).strip().splitlines()
    reason = detail[-1] if detail else f"exit code {proc.returncode}"
    return add_check(
        checks,
        "run",
        subject,
        True,
        "fail",
        fix(f"pyDeltaRCM console script failed its --help smoke test ({reason})"),
    )


def main():
    checks = []

    print(f"{' PREFLIGHT: PyDeltaRCM ':=^60}")
    check_executable(checks, MODEL_PYTHON, "PyDeltaRCM Python runtime", critical=True)

    for module in ("pyDeltaRCM", "numpy", "numba", "scipy", "netCDF4", "yaml"):
        check_import(checks, module, critical=True)
    check_import(checks, "matplotlib", critical=False)

    for relpath, label in (
        ("SKILL.md", "KI skill"),
        ("knowledge_infrastructure.yaml", "KI manifest"),
        ("dag.yaml", "KI DAG"),
        ("diagnostics/triplets.yaml", "diagnostic triplets"),
        ("tools/run_pydeltarcm.py", "execution wrapper"),
        ("tools/generate_yaml_config.py", "configuration generator"),
        ("tools/convert_parameters.py", "unit conversion tool"),
        ("tools/parse_output.py", "output parser"),
    ):
        check_file(checks, KI_DIR / relpath, label, critical=True)

    check_cli_starts(checks)

    passed = sum(1 for check in checks if check["status"] == "pass")
    failed = len(checks) - passed
    print(f"\n  Results: {passed} passed, {failed} failed")
    if failed:
        print(f"  Recovery: inspect {TRIPLETS} before changing model tools.")

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
