#!/usr/bin/env python3
"""Preflight check for the ADCIRC Knowledge Infrastructure."""

import json
import os
import subprocess
import sys

MODEL_ID = "ADCIRC"
KI_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.realpath(os.path.join(KI_DIR, ".."))
ADCIRC_BINARY = os.path.realpath(os.path.join(MODEL_DIR, "bin", "adcirc"))
PYTHON_ENV = "KISSPATH_PYTHON_ENV/bin/python"
TRIPLETS = os.path.join(KI_DIR, "diagnostics", "triplets.yaml")


def recovery_fix(message):
    return f"{message}; then check {TRIPLETS} for matching recovery triplets."


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}))
    sys.exit(0 if all(c["status"] == "pass" or not c.get("critical") for c in checks) else 1)


def add_check(checks, kind, subject, critical, passed, fix=""):
    status = "pass" if passed else "fail"
    check = {
        "kind": kind,
        "subject": subject,
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


def check_file(checks, path, label, *, kind="data", critical=True, executable=False):
    path = os.path.realpath(path)
    if not os.path.isfile(path):
        return add_check(
            checks,
            kind,
            path,
            critical,
            False,
            recovery_fix(f"Restore required {label} at {path}"),
        )
    if executable and not os.access(path, os.X_OK):
        return add_check(
            checks,
            kind,
            path,
            critical,
            False,
            recovery_fix(f"Make {label} executable with chmod +x {path}"),
        )
    return add_check(checks, kind, path, critical, True)


def check_dir(checks, path, label, *, critical=True):
    path = os.path.realpath(path)
    if not os.path.isdir(path):
        return add_check(
            checks,
            "data",
            path,
            critical,
            False,
            recovery_fix(f"Restore required {label} directory at {path}"),
        )
    if not os.listdir(path):
        return add_check(
            checks,
            "data",
            path,
            critical,
            False,
            recovery_fix(f"Populate required {label} directory at {path}"),
        )
    return add_check(checks, "data", path, critical, True)


def check_import(checks, module, *, critical=True):
    subject = f"{PYTHON_ENV} import {module}"
    if not os.path.isfile(PYTHON_ENV) or not os.access(PYTHON_ENV, os.X_OK):
        return add_check(
            checks,
            "import",
            subject,
            critical,
            False,
            recovery_fix(f"Restore executable HydroCraft Python interpreter at {PYTHON_ENV}"),
        )

    proc = subprocess.run(
        [PYTHON_ENV, "-c", f"import {module}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=10,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip().splitlines()
        suffix = f" Last error: {detail[-1]}" if detail else ""
        return add_check(
            checks,
            "import",
            subject,
            critical,
            False,
            recovery_fix(f"Install/fix Python dependency '{module}' in {PYTHON_ENV}.{suffix}"),
        )
    return add_check(checks, "import", subject, critical, True)


def check_python_syntax(checks, path, *, critical=True):
    path = os.path.realpath(path)
    subject = f"{PYTHON_ENV} py_compile {path}"
    proc = subprocess.run(
        [PYTHON_ENV, "-m", "py_compile", path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=10,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip().splitlines()
        suffix = f" Last error: {detail[-1]}" if detail else ""
        return add_check(
            checks,
            "import",
            subject,
            critical,
            False,
            recovery_fix(f"Fix syntax/import-time error in {path}.{suffix}"),
        )
    return add_check(checks, "import", subject, critical, True)


def check_binary_starts(checks, binary, *, critical=True):
    binary = os.path.realpath(binary)
    subject = f"{binary} --help"
    try:
        proc = subprocess.run(
            [binary, "--help"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5,
        )
    except Exception as exc:
        return add_check(
            checks,
            "run",
            subject,
            critical,
            False,
            recovery_fix(f"Repair ADCIRC binary startup failure: {exc}"),
        )

    output = f"{proc.stdout}\n{proc.stderr}"
    passed = proc.returncode == 0 and "ADvanced CIRCulation" in output
    if not passed:
        detail = output.strip().splitlines()
        suffix = f" Last output: {detail[-1]}" if detail else ""
        return add_check(
            checks,
            "run",
            subject,
            critical,
            False,
            recovery_fix(f"Rebuild or replace ADCIRC binary; --help did not start cleanly.{suffix}"),
        )
    return add_check(checks, "run", subject, critical, True)


def main():
    checks = []
    print(f"{' PREFLIGHT: ADCIRC ':=^60}")
    print()

    check_file(checks, ADCIRC_BINARY, "ADCIRC binary", kind="binary", critical=True, executable=True)
    if checks[-1]["status"] == "pass":
        check_binary_starts(checks, ADCIRC_BINARY, critical=True)

    check_file(checks, PYTHON_ENV, "HydroCraft Python interpreter", kind="import", critical=True, executable=True)
    for module in ("numpy", "pandas", "netCDF4", "matplotlib", "scipy"):
        check_import(checks, module, critical=True)

    check_dir(checks, os.path.join(KI_DIR, "tools"), "KI tools", critical=True)
    for relpath in (
        "tools/convert_bathymetry_to_fort14.py",
        "tools/convert_forcing_to_adcirc.py",
        "tools/run_adcirc.py",
        "tools/parse_adcirc_output.py",
    ):
        tool_path = os.path.join(KI_DIR, relpath)
        if check_file(checks, tool_path, relpath, kind="data", critical=True):
            check_python_syntax(checks, tool_path, critical=True)

    for relpath in (
        "SKILL.md",
        "knowledge_infrastructure.yaml",
        "dag.yaml",
        "docs/format_spec.yaml",
        "diagnostics/triplets.yaml",
    ):
        check_file(checks, os.path.join(KI_DIR, relpath), relpath, kind="data", critical=True)

    failed = [c for c in checks if c["status"] == "fail"]
    print()
    print(f"  Results: {len(checks) - len(failed)} passed, {len(failed)} failed")
    if failed:
        print(f"  STATUS: PREFLIGHT FAILED - check {TRIPLETS} for known fixes")
    else:
        print("  STATUS: PREFLIGHT PASSED - safe to proceed with ADCIRC execution")

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
