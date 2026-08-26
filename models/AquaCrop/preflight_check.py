#!/usr/bin/env python3
"""
Preflight check for the AquaCrop knowledge infrastructure.

This script is executed before model runs. It verifies the recorded model
entry script, the HydroCraft Python environment, required imports, KI tools,
and local diagnostics/docs needed for recovery.
"""

import json
import os
import subprocess
import sys
from pathlib import Path


MODEL_ID = "AquaCrop"
KI_DIR = Path(__file__).resolve().parent
TRIPLETS = KI_DIR / "diagnostics" / "triplets.yaml"
PYTHON_ENV = Path("KISSPATH_PYTHON_ENV/bin/python")
MODEL_ENTRY = Path("KISSPATH_KI_ROOT/AquaCrop/run_and_score.py")
KI_COMMON = Path("KISSPATH_KI_TOOLS_COMMON")

TOOL_FILES = [
    "tools/s10_water_productivity/compare_irrigation_scenarios.py",
    "tools/s10_water_productivity/compute_water_productivity.py",
    "tools/s1_crop_selection/select_crop.py",
    "tools/s1_crop_selection/validate_crop_params.py",
    "tools/s2_soil_profile/create_soil_profile.py",
    "tools/s2_soil_profile/validate_soil_hydraulics.py",
    "tools/s3_weather_prep/compute_eto_penman_monteith.py",
    "tools/s3_weather_prep/prepare_weather_df.py",
    "tools/s3_weather_prep/validate_weather_df.py",
    "tools/s4_initial_conditions/create_initial_water_content.py",
    "tools/s5_irrigation/create_irrigation_management.py",
    "tools/s5_irrigation/optimize_deficit_irrigation.py",
    "tools/s6_field_management/apply_cama_flood.py",
    "tools/s6_field_management/create_field_management.py",
    "tools/s7_model_assembly/assemble_model.py",
    "tools/s7_model_assembly/validate_model_config.py",
    "tools/s8_execution/run_aquacrop.py",
    "tools/s9_output_analysis/compare_sim_obs.py",
    "tools/s9_output_analysis/extract_results.py",
    "tools/s9_output_analysis/validate_national_yield_series.py",
]

REQUIRED_LOCAL_FILES = [
    "SKILL.md",
    "knowledge_infrastructure.yaml",
    "dag.yaml",
    "docs/format_spec.yaml",
    "diagnostics/triplets.yaml",
]


def recovery_hint(fix):
    return f"{fix} See {TRIPLETS} for known AquaCrop recovery triplets."


def add_check(checks, kind, subject, critical, status, fix=""):
    checks.append(
        {
            "kind": kind,
            "subject": str(subject),
            "critical": bool(critical),
            "status": status,
            "fix": fix,
        }
    )


def print_check(label, status, subject, fix=""):
    prefix = "OK" if status == "pass" else "FAIL"
    print(f"  {prefix:<5} {label}: {subject}")
    if status == "fail" and fix:
        print(f"        Fix: {fix}")


def run_subprocess(args, timeout=20):
    try:
        return subprocess.run(
            [str(a) for a in args],
            cwd=str(KI_DIR),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        return exc


def check_python_env(checks):
    subject = os.path.realpath(PYTHON_ENV)
    fix = recovery_hint(
        f"Restore executable HydroCraft Python at {PYTHON_ENV} with AquaCrop dependencies installed."
    )
    if not PYTHON_ENV.exists():
        status = "fail"
    elif not os.access(PYTHON_ENV, os.X_OK):
        status = "fail"
        fix = recovery_hint(f"Make the HydroCraft Python interpreter executable: chmod +x {PYTHON_ENV}.")
    else:
        result = run_subprocess([PYTHON_ENV, "-c", "import sys; print(sys.executable)"])
        status = "pass" if getattr(result, "returncode", 1) == 0 else "fail"
        if status == "fail":
            details = getattr(result, "stderr", "") or getattr(result, "stdout", "")
            fix = recovery_hint(f"Repair {PYTHON_ENV}; it did not start cleanly. Details: {details.strip()}")
    add_check(checks, "binary", subject, True, status, "" if status == "pass" else fix)
    print_check("HydroCraft python_env", status, subject, "" if status == "pass" else fix)


def check_model_entry(checks):
    subject = os.path.realpath(MODEL_ENTRY)
    fix = recovery_hint(
        f"Restore executable AquaCrop entry script at {MODEL_ENTRY} and verify the models DB path."
    )
    if not MODEL_ENTRY.is_file():
        status = "fail"
    elif not os.access(MODEL_ENTRY, os.X_OK):
        status = "fail"
        fix = recovery_hint(f"Make the AquaCrop entry script executable: chmod +x {MODEL_ENTRY}.")
    else:
        result = run_subprocess([PYTHON_ENV, "-m", "py_compile", MODEL_ENTRY])
        status = "pass" if getattr(result, "returncode", 1) == 0 else "fail"
        if status == "fail":
            details = getattr(result, "stderr", "") or getattr(result, "stdout", "")
            fix = recovery_hint(f"Fix syntax/import-time blockers in {MODEL_ENTRY}. Details: {details.strip()}")
    add_check(checks, "binary", subject, True, status, "" if status == "pass" else fix)
    print_check("Model entry script realpath", status, subject, "" if status == "pass" else fix)


def check_import(checks, module, label, critical=True):
    subject = module
    code = (
        "import importlib, sys; "
        f"sys.path.insert(0, {str(KI_DIR)!r}); "
        f"sys.path.insert(0, {str(KI_COMMON)!r}); "
        f"importlib.import_module({module!r})"
    )
    result = run_subprocess([PYTHON_ENV, "-c", code])
    status = "pass" if getattr(result, "returncode", 1) == 0 else "fail"
    fix = ""
    if status == "fail":
        details = getattr(result, "stderr", "") or getattr(result, "stdout", "")
        fix = recovery_hint(
            f"Install or repair import {module!r} in {PYTHON_ENV}: {details.strip()}"
        )
    add_check(checks, "import", subject, critical, status, fix)
    print_check(label, status, subject, fix)


def check_aquacrop_smoke(checks):
    subject = "AquaCrop package smoke: Crop/Soil/InitialWaterContent"
    code = (
        "from aquacrop import Crop, Soil, InitialWaterContent; "
        "Crop('Maize', planting_date='05/01'); "
        "Soil('SiltLoam'); "
        "InitialWaterContent(wc_type='Prop', value=['FC'])"
    )
    result = run_subprocess([PYTHON_ENV, "-c", code])
    status = "pass" if getattr(result, "returncode", 1) == 0 else "fail"
    fix = ""
    if status == "fail":
        details = getattr(result, "stderr", "") or getattr(result, "stdout", "")
        fix = recovery_hint(f"Repair AquaCrop-OSPy runtime objects in {PYTHON_ENV}. Details: {details.strip()}")
    add_check(checks, "run", subject, True, status, fix)
    print_check("AquaCrop object smoke test", status, subject, fix)


def check_local_file(checks, relpath, critical=True):
    path = KI_DIR / relpath
    subject = str(path)
    status = "pass" if path.is_file() else "fail"
    fix = "" if status == "pass" else recovery_hint(f"Restore required KI file {relpath}.")
    add_check(checks, "data", subject, critical, status, fix)
    print_check("Required KI file", status, subject, fix)


def check_tool_inventory(checks):
    missing = [relpath for relpath in TOOL_FILES if not (KI_DIR / relpath).is_file()]
    subject = f"{KI_DIR}/tools ({len(TOOL_FILES)} manifest tools)"
    status = "pass" if not missing else "fail"
    fix = "" if status == "pass" else recovery_hint(f"Restore missing tool files: {', '.join(missing)}.")
    add_check(checks, "data", subject, True, status, fix)
    print_check("Tool inventory", status, subject, fix)


def check_tool_syntax(checks):
    paths = [KI_DIR / relpath for relpath in TOOL_FILES if (KI_DIR / relpath).is_file()]
    subject = "AquaCrop KI tools py_compile"
    result = run_subprocess([PYTHON_ENV, "-m", "py_compile", *paths], timeout=30)
    status = "pass" if getattr(result, "returncode", 1) == 0 else "fail"
    fix = ""
    if status == "fail":
        details = getattr(result, "stderr", "") or getattr(result, "stdout", "")
        fix = recovery_hint(f"Fix Python syntax in KI tools. Details: {details.strip()}")
    add_check(checks, "run", subject, True, status, fix)
    print_check("Tool syntax", status, subject, fix)


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}, sort_keys=True))
    sys.exit(0 if all(c["status"] == "pass" or not c.get("critical") for c in checks) else 1)


def main():
    checks = []

    print("=" * 60)
    print("  PREFLIGHT CHECK: AquaCrop-OSPy")
    print("=" * 60)
    print()

    check_python_env(checks)
    check_model_entry(checks)

    print()
    check_import(checks, "aquacrop", "AquaCrop-OSPy")
    check_import(checks, "aquacrop.core", "AquaCrop core module")
    check_import(checks, "ki_tools_common.load_forcing", "HydroCraft forcing helper")
    check_import(checks, "ki_tools_common.crop_obs", "HydroCraft crop observation helper")
    check_aquacrop_smoke(checks)

    print()
    for relpath in REQUIRED_LOCAL_FILES:
        check_local_file(checks, relpath)
    check_tool_inventory(checks)
    check_tool_syntax(checks)

    print()
    passed = sum(1 for c in checks if c["status"] == "pass")
    failed = len(checks) - passed
    print(f"  Results: {passed} passed, {failed} failed")
    if failed:
        print(f"  STATUS: PREFLIGHT FAILED - fix blockers above before running {MODEL_ID}")
    else:
        print("  STATUS: PREFLIGHT PASSED - safe to proceed with model execution")

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
