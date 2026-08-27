#!/usr/bin/env python3
"""Preflight check for the Cell2Fire knowledge infrastructure."""

import json
import os
import subprocess
import sys
from pathlib import Path


MODEL_ID = "Cell2Fire"
KI_DIR = Path(__file__).resolve().parent
DIAGNOSTICS = KI_DIR / "diagnostics" / "triplets.yaml"
PYTHON_ENV = Path("KISSPATH_PYTHON_ENV/bin/python")
CELL2FIRE_BINARY = Path(
    "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/"
    "Cell2Fire/source/repo/Cell2Fire/Cell2Fire"
)
REQUIRED_TOOLS = [
    KI_DIR / "tools" / "convert_fuel_params.py",
    KI_DIR / "tools" / "convert_weather_to_c2f.py",
    KI_DIR / "tools" / "parse_cell2fire_output.py",
    KI_DIR / "tools" / "run_cell2fire.py",
]
REQUIRED_DATA_FILES = [
    KI_DIR / "SKILL.md",
    KI_DIR / "knowledge_infrastructure.yaml",
    KI_DIR / "dag.yaml",
    KI_DIR / "docs" / "format_spec.yaml",
    DIAGNOSTICS,
]
REQUIRED_IMPORTS = ["numpy", "pandas", "yaml"]


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}))
    sys.exit(0 if all(c["status"] == "pass" or not c.get("critical") for c in checks) else 1)


def add_check(checks, kind, subject, critical, status, fix=""):
    check = {
        "kind": kind,
        "subject": str(subject),
        "critical": bool(critical),
        "status": status,
        "fix": fix,
    }
    checks.append(check)
    label = "OK" if status == "pass" else "FAIL"
    print(f"  {label:<4} {kind}: {subject}")
    if status != "pass" and fix:
        print(f"       Fix: {fix}")
    return check


def check_file(checks, path, label, kind="data", critical=True, executable=False):
    path = Path(path)
    subject = path.resolve() if path.exists() else path
    if not path.is_file():
        return add_check(
            checks,
            kind,
            subject,
            critical,
            "fail",
            f"Restore {label}; see {DIAGNOSTICS} for recovery.",
        )
    if executable and not os.access(path, os.X_OK):
        return add_check(
            checks,
            kind,
            path.resolve(),
            critical,
            "fail",
            f"Run chmod +x {path}; see {DIAGNOSTICS} for recovery.",
        )
    return add_check(checks, kind, path.resolve(), critical, "pass")


def check_dir(checks, path, label, critical=True):
    path = Path(path)
    subject = path.resolve() if path.exists() else path
    if not path.is_dir():
        return add_check(
            checks,
            "data",
            subject,
            critical,
            "fail",
            f"Restore {label}; see {DIAGNOSTICS} for recovery.",
        )
    if not any(path.iterdir()):
        return add_check(
            checks,
            "data",
            path.resolve(),
            critical,
            "fail",
            f"Populate {label}; see {DIAGNOSTICS} for recovery.",
        )
    return add_check(checks, "data", path.resolve(), critical, "pass")


def check_imports(checks):
    if not PYTHON_ENV.is_file():
        add_check(
            checks,
            "import",
            PYTHON_ENV,
            True,
            "fail",
            f"Restore HydroCraft Python environment at {PYTHON_ENV}; see {DIAGNOSTICS}.",
        )
        return

    for module in REQUIRED_IMPORTS:
        code = f"import {module}"
        result = subprocess.run(
            [str(PYTHON_ENV), "-c", code],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0:
            add_check(checks, "import", f"{PYTHON_ENV}: import {module}", True, "pass")
        else:
            detail = (result.stderr or result.stdout).strip().splitlines()
            error = detail[-1] if detail else f"return code {result.returncode}"
            add_check(
                checks,
                "import",
                f"{PYTHON_ENV}: import {module}",
                True,
                "fail",
                f"Install {module.split('.')[0]} in {PYTHON_ENV}: {error}; see {DIAGNOSTICS}.",
            )


def check_tool_syntax(checks):
    result = subprocess.run(
        [str(PYTHON_ENV), "-m", "py_compile", *[str(tool) for tool in REQUIRED_TOOLS]],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode == 0:
        add_check(checks, "import", f"{PYTHON_ENV}: py_compile KI tools", True, "pass")
    else:
        detail = (result.stderr or result.stdout).strip()
        add_check(
            checks,
            "import",
            f"{PYTHON_ENV}: py_compile KI tools",
            True,
            "fail",
            f"Fix Python syntax/import-time errors in tools/: {detail}; see {DIAGNOSTICS}.",
        )


def check_binary_starts(checks):
    if not CELL2FIRE_BINARY.is_file() or not os.access(CELL2FIRE_BINARY, os.X_OK):
        return

    realpath = CELL2FIRE_BINARY.resolve()
    result = subprocess.run(
        [str(realpath), "--help"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    output = (result.stdout or "") + (result.stderr or "")
    if "version:" in output or "Command line values" in output:
        add_check(checks, "run", realpath, True, "pass")
    else:
        detail = output.strip().splitlines()
        error = detail[-1] if detail else f"return code {result.returncode}"
        add_check(
            checks,
            "run",
            realpath,
            True,
            "fail",
            f"Cell2Fire executable did not start cleanly enough to emit version output: {error}; see {DIAGNOSTICS}.",
        )


def main():
    checks = []
    print(f"{' PREFLIGHT: Cell2Fire ':=^60}")

    check_dir(checks, KI_DIR / "tools", "KI tools directory", critical=True)
    for tool in REQUIRED_TOOLS:
        check_file(checks, tool, tool.name, kind="data", critical=True)
    for data_file in REQUIRED_DATA_FILES:
        check_file(checks, data_file, data_file.name, kind="data", critical=True)

    check_file(
        checks,
        CELL2FIRE_BINARY,
        "Cell2Fire binary",
        kind="binary",
        critical=True,
        executable=True,
    )
    check_binary_starts(checks)
    check_imports(checks)
    check_tool_syntax(checks)

    failed = [c for c in checks if c["status"] != "pass"]
    print(f"\n  Results: {len(checks) - len(failed)} passed, {len(failed)} failed")
    if failed:
        print(f"  Recovery: check {DIAGNOSTICS} for matching fixes.")
    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        emit_report(
            MODEL_ID,
            [
                {
                    "kind": "run",
                    "subject": "preflight_check.py",
                    "critical": True,
                    "status": "fail",
                    "fix": f"Preflight crashed: {exc}; see {DIAGNOSTICS} for recovery.",
                }
            ],
        )
