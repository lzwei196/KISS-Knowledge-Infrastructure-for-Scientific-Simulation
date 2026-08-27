#!/usr/bin/env python3
"""
Preflight check for Raven v4.1 Knowledge Infrastructure.

This script verifies the real Raven executable, the HydroCraft Python runtime
used by the KI tools, required KI files, and common optional data locations
before any model execution is attempted.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

MODEL_ID = "Raven"
KI_DIR = Path(__file__).resolve().parent
RAVEN_EXE = Path("KISSPATH_BINARIES/raven/Raven.exe")
HYDROCRAFT_PYTHON = Path("KISSPATH_PYTHON_ENV/bin/python")
TRIPLETS = KI_DIR / "diagnostics" / "triplets.yaml"

CHECKS = []
PASS = 0
FAIL = 0


def fix_message(action):
    return f"{action}; then check {TRIPLETS} for matching recovery triplets."


def record(kind, subject, critical, passed, fix=""):
    global PASS, FAIL
    status = "pass" if passed else "fail"
    check = {
        "kind": kind,
        "subject": str(subject),
        "critical": bool(critical),
        "status": status,
        "fix": "" if passed else fix,
    }
    CHECKS.append(check)
    if passed:
        PASS += 1
        print(f"  OK    {kind}: {subject}")
    else:
        FAIL += 1
        prefix = "FAIL" if critical else "WARN"
        print(f"  {prefix:<5} {kind}: {subject}")
        if fix:
            print(f"         Fix: {fix}")
    return passed


def check_file(path, label, *, executable=False, critical=True, kind="data"):
    path = Path(path)
    subject = path
    exists = path.is_file()
    if exists and executable:
        subject = os.path.realpath(path)
    if not exists:
        return record(
            kind,
            subject,
            critical,
            False,
            fix_message(f"Restore or correct {label} at {path}"),
        )
    if executable and not os.access(path, os.X_OK):
        return record(
            kind,
            subject,
            critical,
            False,
            fix_message(f"Make {label} executable: chmod +x {path}"),
        )
    return record(kind, subject, critical, True)


def check_dir(path, label, *, critical=True):
    path = Path(path)
    if not path.is_dir():
        return record(
            "data",
            path,
            critical,
            False,
            fix_message(f"Restore or correct {label} directory at {path}"),
        )
    n_items = len(list(path.iterdir()))
    return record("data", f"{path} ({n_items} items)", critical, True)


def check_python_imports(modules):
    if not check_file(HYDROCRAFT_PYTHON, "HydroCraft Python interpreter", executable=True, critical=True, kind="binary"):
        for module in modules:
            record(
                "import",
                f"{module} via {HYDROCRAFT_PYTHON}",
                True,
                False,
                fix_message(f"Restore HydroCraft Python before checking import {module}"),
            )
        return

    code = (
        "import importlib, json\n"
        f"mods = {modules!r}\n"
        "out = []\n"
        "for mod in mods:\n"
        "    try:\n"
        "        importlib.import_module(mod)\n"
        "        out.append({'module': mod, 'ok': True, 'error': ''})\n"
        "    except Exception as exc:\n"
        "        out.append({'module': mod, 'ok': False, 'error': repr(exc)})\n"
        "print(json.dumps(out))\n"
    )
    try:
        proc = subprocess.run(
            [str(HYDROCRAFT_PYTHON), "-c", code],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception as exc:
        for module in modules:
            record(
                "import",
                f"{module} via {HYDROCRAFT_PYTHON}",
                True,
                False,
                fix_message(f"Run import check with HydroCraft Python failed: {exc}"),
            )
        return

    try:
        results = json.loads(proc.stdout.strip())
    except json.JSONDecodeError:
        results = [
            {
                "module": module,
                "ok": False,
                "error": f"import probe returned rc={proc.returncode}, stdout={proc.stdout!r}, stderr={proc.stderr!r}",
            }
            for module in modules
        ]

    for result in results:
        module = result["module"]
        record(
            "import",
            f"{module} via {HYDROCRAFT_PYTHON}",
            True,
            bool(result["ok"]),
            fix_message(f"Install or repair Python dependency {module}: {result.get('error', '')}"),
        )


def check_raven_starts():
    exe_realpath = os.path.realpath(RAVEN_EXE)
    if not (RAVEN_EXE.is_file() and os.access(RAVEN_EXE, os.X_OK)):
        record(
            "run",
            exe_realpath,
            True,
            False,
            fix_message(f"Raven executable cannot be started until {RAVEN_EXE} exists and is executable"),
        )
        return
    try:
        proc = subprocess.run(
            [str(RAVEN_EXE)],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(KI_DIR),
        )
    except Exception as exc:
        record(
            "run",
            exe_realpath,
            True,
            False,
            fix_message(f"Start Raven executable failed: {exc}"),
        )
        return

    output = f"{proc.stdout}\n{proc.stderr}"
    started = "RAVEN" in output and "Version 4.1" in output
    record(
        "run",
        exe_realpath,
        True,
        started,
        fix_message(
            f"Raven did not print the expected v4.1 startup banner "
            f"(returncode={proc.returncode})"
        ),
    )


def check_ki_tools():
    required_tools = [
        "tools/common/validate_raven_inputs.py",
        "tools/s0_config/select_model_template.py",
        "tools/s1_basin_setup/build_rvh_from_shapefile.py",
        "tools/s2_parameters/build_rvp_parameters.py",
        "tools/s3_forcing/convert_forcing_to_rvt.py",
        "tools/s5_initial_conditions/generate_rvc_initial.py",
        "tools/s6_execution/run_raven.py",
        "tools/s7_output/parse_raven_output.py",
        "tools/s8_ensemble/run_ensemble_comparison.py",
        "tools/s9_calibration/calibrate_raven_dds.py",
        "tools/s10_coupling/raven_vic_comparison.py",
    ]
    for relpath in required_tools:
        check_file(KI_DIR / relpath, relpath, critical=True, kind="data")


def check_common_data():
    common = [
        ("KISSPATH_OBS", "Observation data"),
        ("KISSPATH_FORCING", "Forcing data"),
        ("KISSPATH_STATIC", "DEM data"),
        ("KISSPATH_STATIC", "Soil data"),
    ]
    for path, label in common:
        check_dir(path, label, critical=False)


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}, sort_keys=True))
    sys.exit(0 if all(c["status"] == "pass" or not c.get("critical") for c in checks) else 1)


def main():
    print("=" * 60)
    print("  PREFLIGHT CHECK: Raven")
    print("=" * 60)
    print()

    print("Model binary")
    check_file(RAVEN_EXE, "Raven v4.1 executable", executable=True, critical=True, kind="binary")
    check_raven_starts()
    print()

    print("HydroCraft Python imports")
    check_python_imports([
        "numpy",
        "pandas",
        "geopandas",
        "rasterio",
        "shapely",
        "netCDF4",
        "xarray",
        "ki_tools_common",
    ])
    print()

    print("KI files")
    check_file(KI_DIR / "SKILL.md", "SKILL.md", critical=True, kind="data")
    check_file(KI_DIR / "knowledge_infrastructure.yaml", "knowledge_infrastructure.yaml", critical=True, kind="data")
    check_file(KI_DIR / "dag.yaml", "dag.yaml", critical=True, kind="data")
    check_file(TRIPLETS, "diagnostics/triplets.yaml", critical=True, kind="data")
    check_ki_tools()
    print()

    print("Common data locations")
    check_common_data()
    print()

    critical_failures = [c for c in CHECKS if c["critical"] and c["status"] == "fail"]
    print(f"  Results: {PASS} passed, {FAIL} failed")
    if critical_failures:
        print("  STATUS: PREFLIGHT FAILED - fix blockers before running Raven.")
    else:
        print("  STATUS: PREFLIGHT PASSED - safe to proceed with Raven execution.")
    print()

    emit_report(MODEL_ID, CHECKS)


if __name__ == "__main__":
    main()
