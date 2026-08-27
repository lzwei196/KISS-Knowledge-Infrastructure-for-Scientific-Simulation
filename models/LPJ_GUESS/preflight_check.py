#!/usr/bin/env python3
"""Preflight check for the LPJ-GUESS knowledge infrastructure."""

from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


MODEL_ID = "LPJ-GUESS"
KI_DIR = Path(__file__).resolve().parent
PYTHON_ENV = Path("KISSPATH_PYTHON_ENV/bin/python")
TOOLS_DIR = KI_DIR / "tools"
RUNNER = TOOLS_DIR / "run_lpjguess.py"
TRIPLETS = KI_DIR / "diagnostics" / "triplets.yaml"
REQUIRED_TOOLS = [
    TOOLS_DIR / "convert_forcing_to_lpjguess.py",
    TOOLS_DIR / "convert_parameters_to_lpjguess.py",
    TOOLS_DIR / "parse_output_lpjguess.py",
    RUNNER,
]
REQUIRED_OUTPUT_COLUMNS = ["date", "GPP", "Ra", "Rh", "Reco", "NEE", "NPP"]


def fix_text(action: str) -> str:
    return f"{action}; then check {TRIPLETS} for matching diagnostics."


def record(checks, kind, subject, critical, ok, fix):
    status = "pass" if ok else "fail"
    checks.append(
        {
            "kind": kind,
            "subject": str(subject),
            "critical": bool(critical),
            "status": status,
            "fix": "" if ok else fix,
        }
    )
    print(f"  {'OK' if ok else 'FAIL':<5} {kind}: {subject}")
    if not ok:
        print(f"        Fix: {fix}")
    return ok


def run_command(cmd, *, cwd=KI_DIR, timeout=15):
    return subprocess.run(
        [str(part) for part in cmd],
        cwd=str(cwd),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )


def check_python_interpreter(checks):
    ok = PYTHON_ENV.is_file() and os.access(PYTHON_ENV, os.X_OK)
    record(
        checks,
        "binary",
        PYTHON_ENV,
        True,
        ok,
        fix_text(f"Restore executable HydroCraft Python interpreter at {PYTHON_ENV}"),
    )
    return ok


def check_file(checks, path, label, *, executable=False, critical=True):
    ok = path.is_file()
    if ok and executable:
        ok = os.access(path, os.X_OK)
    action = f"Restore {label} at {path}"
    if executable:
        action += f" and run chmod +x {path}"
    return record(checks, "binary" if executable else "data", path, critical, ok, fix_text(action))


def check_directory(checks, path, label, *, critical=True):
    ok = path.is_dir() and any(path.iterdir())
    return record(
        checks,
        "data",
        path,
        critical,
        ok,
        fix_text(f"Restore non-empty {label} directory at {path}"),
    )


def check_import(checks, module, *, critical=True):
    if not PYTHON_ENV.is_file():
        return record(
            checks,
            "import",
            module,
            critical,
            False,
            fix_text(f"Cannot test import {module}; restore {PYTHON_ENV}"),
        )

    proc = run_command([PYTHON_ENV, "-c", f"import {module}"])
    ok = proc.returncode == 0
    fix = fix_text(f"Install {module.split('.')[0]} into {PYTHON_ENV.parent.parent}")
    return record(checks, "import", module, critical, ok, fix)


def check_tool_import(checks, path):
    proc = run_command([PYTHON_ENV, "-m", "py_compile", path])
    ok = proc.returncode == 0
    fix = fix_text(f"Fix syntax/import-time errors in {path}: {(proc.stderr or proc.stdout).strip()}")
    return record(checks, "import", path, True, ok, fix)


def check_runner_starts(checks):
    proc = run_command([PYTHON_ENV, RUNNER, "--help"], timeout=10)
    ok = proc.returncode == 0 and "--forcing" in proc.stdout and "--params" in proc.stdout
    fix = fix_text(
        f"Make {RUNNER} start under {PYTHON_ENV}; stderr was {(proc.stderr or proc.stdout).strip()[:500]}"
    )
    return record(checks, "run", os.path.realpath(RUNNER), True, ok, fix)


def check_smoke_run(checks):
    with tempfile.TemporaryDirectory(prefix="lpjguess_preflight_") as tmp:
        tmpdir = Path(tmp)
        forcing = tmpdir / "forcing.csv"
        params = tmpdir / "params.json"
        output = tmpdir / "model_output.csv"

        forcing.write_text(
            "date,SW_IN,TA,VPD,P\n"
            "2001-06-01,220,18,9,1.0\n"
            "2001-06-02,260,20,12,0.0\n",
            encoding="utf-8",
        )
        params.write_text(
            json.dumps(
                {
                    "LUE_max": 1.5,
                    "T_opt": 20.0,
                    "T_min": -2.0,
                    "T_max": 38.0,
                    "VPD_0": 10.0,
                    "VPD_1": 35.0,
                    "Ra_base": 0.5,
                    "Ra_Q10": 2.0,
                    "Rh_base": 2.0,
                    "Rh_Q10": 2.0,
                }
            ),
            encoding="utf-8",
        )

        proc = run_command(
            [PYTHON_ENV, RUNNER, "--forcing", forcing, "--params", params, "--output", output],
            timeout=20,
        )
        ok = proc.returncode == 0 and output.is_file() and output.stat().st_size > 0
        if ok:
            with output.open(newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                ok = reader.fieldnames is not None and all(
                    column in reader.fieldnames for column in REQUIRED_OUTPUT_COLUMNS
                )

    fix = fix_text(
        "Run the LPJ-GUESS wrapper manually with a minimal forcing/parameter file and fix the reported error"
        f"; stderr was {(proc.stderr or proc.stdout).strip()[:500]}"
    )
    return record(checks, "run", f"{os.path.realpath(RUNNER)} minimal smoke run", True, ok, fix)


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}, sort_keys=True))
    failed_critical = [check for check in checks if check["critical"] and check["status"] != "pass"]
    sys.exit(1 if failed_critical else 0)


def main():
    checks = []
    print("=" * 60)
    print(f"  PREFLIGHT CHECK: {MODEL_ID}")
    print("=" * 60)

    check_directory(checks, TOOLS_DIR, "KI tools")
    check_file(checks, TRIPLETS, "diagnostic triplets", critical=True)
    python_ok = check_python_interpreter(checks)
    for tool in REQUIRED_TOOLS:
        check_file(checks, tool, tool.name, executable=(tool == RUNNER), critical=True)

    if python_ok:
        check_import(checks, "numpy", critical=True)
        check_import(checks, "pandas", critical=False)
        for tool in REQUIRED_TOOLS:
            if tool.is_file():
                check_tool_import(checks, tool)
        if RUNNER.is_file() and os.access(RUNNER, os.X_OK):
            check_runner_starts(checks)
            check_smoke_run(checks)

    passed = sum(1 for check in checks if check["status"] == "pass")
    failed = len(checks) - passed
    print(f"\n  Results: {passed} passed, {failed} failed")
    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
