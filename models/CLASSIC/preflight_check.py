#!/usr/bin/env python3
"""Preflight check for the CLASSIC Knowledge Infrastructure."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


MODEL_ID = "CLASSIC"
KI_DIR = Path(__file__).resolve().parent
MODELS_DIR = Path("KISSPATH_KI_ROOT")
PY_ENV = Path("KISSPATH_PYTHON_ENV/bin/python")
PYTHON = str(PY_ENV if PY_ENV.exists() else Path(sys.executable))

SOURCE_DIR = Path("KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/CLASSIC/source/repo")
BINARY = SOURCE_DIR / "bin" / "CLASSIC_serial"
TRIPLETS = KI_DIR / "diagnostics" / "triplets.yaml"

checks = []


def add_check(kind, subject, critical, passed, fix):
    checks.append(
        {
            "kind": kind,
            "subject": str(subject),
            "critical": bool(critical),
            "status": "pass" if passed else "fail",
            "fix": "" if passed else fix,
        }
    )
    label = "OK" if passed else ("FAIL" if critical else "WARN")
    print(f"  {label:<5} {kind}: {subject}")
    if not passed:
        print(f"        Fix: {fix}")


def check_dir(path, label, critical=True, non_empty=False):
    path = Path(path)
    ok = path.is_dir() and (not non_empty or any(path.iterdir()))
    detail = f"{label}: {path}"
    fix = f"Restore {path}; check {TRIPLETS} for CLASSIC recovery guidance."
    add_check("data", detail, critical, ok, fix)


def check_file(path, label, critical=True, executable=False, subject_realpath=False):
    path = Path(path)
    exists = path.is_file()
    ok = exists and (not executable or os.access(path, os.X_OK))
    subject = os.path.realpath(path) if subject_realpath else f"{label}: {path}"
    if executable:
        fix = f"Restore/build executable {path} and run chmod +x {path}; check {TRIPLETS}."
    else:
        fix = f"Restore required file {path}; check {TRIPLETS}."
    add_check("binary" if executable else "data", subject, critical, ok, fix)


def check_binary_starts(path):
    path = Path(path)
    subject = os.path.realpath(path)
    if not path.is_file() or not os.access(path, os.X_OK):
        add_check(
            "run",
            subject,
            True,
            False,
            f"Restore/build executable {path} before checking startup; check {TRIPLETS}.",
        )
        return

    try:
        result = subprocess.run(
            [str(path)],
            cwd=str(path.parent.parent),
            capture_output=True,
            text=True,
            timeout=5,
        )
        output = (result.stdout + result.stderr).lower()
        ok = result.returncode == 0 and "usage is as follows" in output
        fix = (
            f"Run {path} manually from {path.parent.parent}; if it fails, inspect linked "
            f"libraries and {TRIPLETS}."
        )
        add_check("run", subject, True, ok, fix)
    except Exception as exc:
        add_check(
            "run",
            subject,
            True,
            False,
            f"Binary did not start cheaply ({exc}); check linked libraries and {TRIPLETS}.",
        )


def check_import(module, critical=True):
    env = os.environ.copy()
    py_path = os.pathsep.join([str(KI_DIR), str(MODELS_DIR), env.get("PYTHONPATH", "")])
    env["PYTHONPATH"] = py_path
    code = "import importlib, sys; importlib.import_module(sys.argv[1])"
    try:
        result = subprocess.run(
            [PYTHON, "-c", code, module],
            capture_output=True,
            text=True,
            timeout=15,
            env=env,
        )
        ok = result.returncode == 0
        detail = f"{module} via {PYTHON}"
        fix = (
            f"Install/import {module} in KISSPATH_PYTHON_ENV "
            f"or restore the HydroCraft Python environment; check {TRIPLETS}."
        )
        add_check("import", detail, critical, ok, fix)
    except Exception as exc:
        add_check(
            "import",
            f"{module} via {PYTHON}",
            critical,
            False,
            f"Import check crashed ({exc}); restore the HydroCraft Python environment and check {TRIPLETS}.",
        )


def check_tool_syntax(tool):
    tool_path = KI_DIR / "tools" / tool
    try:
        result = subprocess.run(
            [PYTHON, "-m", "py_compile", str(tool_path)],
            capture_output=True,
            text=True,
            timeout=15,
        )
        ok = result.returncode == 0
    except Exception:
        ok = False
    add_check(
        "import",
        f"tool syntax: {tool_path}",
        True,
        ok,
        f"Fix Python syntax/import-time errors in {tool_path}; check {TRIPLETS}.",
    )


def emit_report():
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": MODEL_ID, "checks": checks}, sort_keys=True))
    blocking = any(c["critical"] and c["status"] == "fail" for c in checks)
    sys.exit(1 if blocking else 0)


def main():
    print(f"{' PREFLIGHT: CLASSIC ':=^60}")
    print()

    check_dir(KI_DIR / "tools", "KI tools directory", critical=True, non_empty=True)
    check_file(TRIPLETS, "diagnostic triplets", critical=True)

    check_file(BINARY, "CLASSIC serial executable", critical=True, executable=True, subject_realpath=True)
    check_binary_starts(BINARY)

    for required in [
        SOURCE_DIR / "configurationFiles" / "template_job_options_file.txt",
        SOURCE_DIR / "configurationFiles" / "template_run_parameters.txt",
        SOURCE_DIR / "configurationFiles" / "outputVariableDescriptors.xml",
        SOURCE_DIR / "test_met" / "init_file.nc",
        SOURCE_DIR / "test_met" / "dswrf.nc",
        SOURCE_DIR / "test_met" / "dlwrf.nc",
        SOURCE_DIR / "test_met" / "pre.nc",
        SOURCE_DIR / "test_met" / "tmp.nc",
        SOURCE_DIR / "test_met" / "spfh.nc",
        SOURCE_DIR / "test_met" / "wind.nc",
        SOURCE_DIR / "test_met" / "pres.nc",
        SOURCE_DIR / "test_met" / "co2.nc",
        SOURCE_DIR / "test_met" / "ch4.nc",
    ]:
        check_file(required, "CLASSIC support/test data", critical=True)

    for tool in [
        "convert_forcing_to_classic.py",
        "convert_soil_to_classic.py",
        "parse_classic_output.py",
        "run_classic.py",
    ]:
        check_file(KI_DIR / "tools" / tool, "KI tool", critical=True)
        check_tool_syntax(tool)

    for module in ["numpy", "netCDF4", "pandas"]:
        check_import(module, critical=True)
    check_import("ki_tools_common.metrics", critical=False)

    for program in ["make", "gfortran"]:
        add_check(
            "binary",
            f"{program}: {shutil.which(program) or 'not found'}",
            False,
            shutil.which(program) is not None,
            f"Install {program}; check {TRIPLETS}.",
        )
    add_check(
        "binary",
        f"netCDF config: {shutil.which('nf-config') or shutil.which('nc-config') or 'not found'}",
        False,
        shutil.which("nf-config") is not None or shutil.which("nc-config") is not None,
        f"Install netCDF development libraries, e.g. libnetcdff-dev; check {TRIPLETS}.",
    )

    print()
    passed = sum(1 for c in checks if c["status"] == "pass")
    failed = len(checks) - passed
    print(f"  Results: {passed} passed, {failed} failed")
    if failed:
        print(f"  Recovery: inspect {TRIPLETS} for matching CLASSIC diagnostics.")
    emit_report()


if __name__ == "__main__":
    main()
