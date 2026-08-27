#!/usr/bin/env python3
"""
Preflight check for the WOFOST/PCSE knowledge infrastructure.

This script verifies the model entrypoint, required Python environment,
imports, KI tool files, diagnostics, and common data locations before model
execution. It always finishes with a single PREFLIGHT_REPORT= JSON line.
"""

import json
import os
import subprocess
import sys


MODEL_ID = "WOFOST"
KI_DIR = os.path.dirname(os.path.abspath(__file__))
HYDROCRAFT_ROOT = "KISSPATH_ROOT"
PYTHON = os.path.join(HYDROCRAFT_ROOT, "python_env", "bin", "python")
MODEL_ENTRYPOINT = os.path.join(HYDROCRAFT_ROOT, "models", "WOFOST", "run_and_score.py")
KI_TOOLS_COMMON = os.path.join(HYDROCRAFT_ROOT, "models", "ki_tools_common")
TRIPLETS = os.path.join(KI_DIR, "diagnostics", "triplets.yaml")

TOOL_FILES = [
    "tools/calib_run.py",
    "tools/s1_crop_params/load_crop_parameters.py",
    "tools/s1_crop_params/validate_crop_params.py",
    "tools/s2_soil_params/convert_hwsd_to_pcse_soil.py",
    "tools/s2_soil_params/validate_soil_params.py",
    "tools/s3_weather_prep/convert_vic_to_pcse_weather.py",
    "tools/s3_weather_prep/create_csv_weather_file.py",
    "tools/s3_weather_prep/validate_weather_data.py",
    "tools/s4_agromanagement/generate_agromanagement_yaml.py",
    "tools/s4_agromanagement/validate_agromanagement.py",
    "tools/s5_engine_config/configure_pcse_engine.py",
    "tools/s5_engine_config/validate_engine_config.py",
    "tools/s6_execution/check_simulation_status.py",
    "tools/s6_execution/run_wofost_simulation.py",
    "tools/s7_output_parsing/export_output_csv.py",
    "tools/s7_output_parsing/parse_wofost_output.py",
    "tools/s8_yield_analysis/compare_wofost_dssat.py",
    "tools/s8_yield_analysis/compute_gridded_yield.py",
    "tools/s8_yield_analysis/generate_yield_map.py",
    "tools/s8_yield_analysis/validate_against_faostat.py",
]

IMPORT_CHECKS = [
    "pcse",
    "pcse.models",
    "pcse.input",
    "pcse.base",
    "pandas",
    "numpy",
    "yaml",
    "xarray",
]

KI_TOOLS_COMMON_IMPORTS = [
    "ki_tools_common.load_forcing",
    "ki_tools_common.crop_obs",
    "ki_tools_common.metrics",
    "ki_tools_common.soil_utils",
]

COMMON_DATA_PATHS = [
    ("KISSPATH_OBS", "Observation data", False),
    ("KISSPATH_FORCING", "Forcing data", False),
    ("KISSPATH_DATA/elev", "Elevation/DEM data", False),
    ("KISSPATH_STATIC", "Soil data", False),
]


def diag_fix(message):
    return f"{message}. Check {os.path.relpath(TRIPLETS, KI_DIR)} for recovery."


def run_cmd(args, timeout=20, env=None):
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
        env=merged_env,
    )


def add_check(checks, kind, subject, critical, ok, fix="", ok_message=None, fail_message=None):
    status = "pass" if ok else "fail"
    check = {
        "kind": kind,
        "subject": subject,
        "critical": bool(critical),
        "status": status,
        "fix": "" if ok else fix,
    }
    checks.append(check)

    label = "OK" if ok else ("FAIL" if critical else "WARN")
    message = ok_message if ok else fail_message
    if message:
        print(f"  {label:<5} {message}")
    else:
        print(f"  {label:<5} {subject}")
    if not ok and fix:
        print(f"        Fix: {fix}")
    return ok


def check_python(checks):
    subject = os.path.realpath(PYTHON)
    if not os.path.isfile(PYTHON):
        return add_check(
            checks,
            "binary",
            subject,
            True,
            False,
            diag_fix(f"Restore the HydroCraft Python interpreter at {PYTHON}"),
            fail_message=f"HydroCraft Python missing: {PYTHON}",
        )
    if not os.access(PYTHON, os.X_OK):
        return add_check(
            checks,
            "binary",
            subject,
            True,
            False,
            diag_fix(f"Make the HydroCraft Python interpreter executable: chmod +x {PYTHON}"),
            fail_message=f"HydroCraft Python is not executable: {PYTHON}",
        )
    try:
        proc = run_cmd(
            [PYTHON, "-c", "import sys; print(sys.executable); print(sys.version_info[:2])"],
            timeout=10,
        )
        ok = proc.returncode == 0 and "(3, 12)" in proc.stdout
        detail = proc.stdout.strip().replace("\n", " ")
        return add_check(
            checks,
            "binary",
            subject,
            True,
            ok,
            diag_fix(f"Use the Python 3.12 HydroCraft environment at {PYTHON}"),
            ok_message=f"HydroCraft Python starts: {detail}",
            fail_message=f"HydroCraft Python did not start as Python 3.12: {proc.stderr.strip()}",
        )
    except Exception as exc:
        return add_check(
            checks,
            "binary",
            subject,
            True,
            False,
            diag_fix(f"Repair the HydroCraft Python environment at {PYTHON}"),
            fail_message=f"HydroCraft Python startup failed: {exc}",
        )


def check_entrypoint(checks):
    subject = os.path.realpath(MODEL_ENTRYPOINT)
    if not os.path.isfile(MODEL_ENTRYPOINT):
        return add_check(
            checks,
            "binary",
            subject,
            True,
            False,
            diag_fix(f"Restore the WOFOST model entrypoint at {MODEL_ENTRYPOINT}"),
            fail_message=f"WOFOST entrypoint missing: {MODEL_ENTRYPOINT}",
        )
    if not os.access(MODEL_ENTRYPOINT, os.R_OK):
        return add_check(
            checks,
            "binary",
            subject,
            True,
            False,
            diag_fix(f"Make the WOFOST entrypoint readable: chmod +r {MODEL_ENTRYPOINT}"),
            fail_message=f"WOFOST entrypoint is not readable: {MODEL_ENTRYPOINT}",
        )

    try:
        proc = run_cmd([PYTHON, MODEL_ENTRYPOINT, "--help"], timeout=20)
        ok = proc.returncode == 0 and "usage:" in proc.stdout
        return add_check(
            checks,
            "binary",
            subject,
            True,
            ok,
            diag_fix(f"Run `{PYTHON} {MODEL_ENTRYPOINT} --help` and fix the first traceback"),
            ok_message=f"WOFOST entrypoint starts via HydroCraft Python: {subject}",
            fail_message=(
                "WOFOST entrypoint failed cheap startup check: "
                + (proc.stderr.strip() or proc.stdout.strip())
            ),
        )
    except Exception as exc:
        return add_check(
            checks,
            "binary",
            subject,
            True,
            False,
            diag_fix(f"Run `{PYTHON} {MODEL_ENTRYPOINT} --help` and fix the startup failure"),
            fail_message=f"WOFOST entrypoint startup check crashed: {exc}",
        )


def check_import(checks, module, critical=True, extra_path=None):
    subject = module
    code = "import importlib; importlib.import_module(%r); print('ok')" % module
    env = None
    if extra_path:
        env = {"PYTHONPATH": extra_path + os.pathsep + os.environ.get("PYTHONPATH", "")}
    try:
        proc = run_cmd([PYTHON, "-c", code], timeout=20, env=env)
        ok = proc.returncode == 0
        return add_check(
            checks,
            "import",
            subject,
            critical,
            ok,
            diag_fix(f"Install or repair import `{module}` in {PYTHON}"),
            ok_message=f"import {module} succeeded under {PYTHON}",
            fail_message=f"import {module} failed under {PYTHON}: {proc.stderr.strip()}",
        )
    except Exception as exc:
        return add_check(
            checks,
            "import",
            subject,
            critical,
            False,
            diag_fix(f"Install or repair import `{module}` in {PYTHON}"),
            fail_message=f"import {module} check crashed: {exc}",
        )


def check_file(checks, path, label, critical=True):
    subject = os.path.realpath(path)
    ok = os.path.isfile(path)
    return add_check(
        checks,
        "data",
        subject,
        critical,
        ok,
        diag_fix(f"Restore required file for {label}: {path}"),
        ok_message=f"{label}: {path}",
        fail_message=f"{label} missing: {path}",
    )


def check_dir(checks, path, label, critical=False):
    subject = os.path.realpath(path)
    ok = os.path.isdir(path)
    count = len(os.listdir(path)) if ok else 0
    return add_check(
        checks,
        "data",
        subject,
        critical,
        ok,
        diag_fix(f"Restore or configure {label} at {path} if this run needs it"),
        ok_message=f"{label}: {path} ({count} items)",
        fail_message=f"{label} not found: {path}",
    )


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}, sort_keys=True))
    critical_failed = any(c["critical"] and c["status"] != "pass" for c in checks)
    sys.exit(1 if critical_failed else 0)


def main():
    checks = []

    print("=" * 60)
    print("  PREFLIGHT CHECK: WOFOST/PCSE")
    print("=" * 60)
    print()

    check_python(checks)
    check_entrypoint(checks)
    print()

    for module in IMPORT_CHECKS:
        check_import(checks, module, critical=True)
    for module in KI_TOOLS_COMMON_IMPORTS:
        check_import(checks, module, critical=True, extra_path=KI_TOOLS_COMMON)
    print()

    for relpath in TOOL_FILES:
        check_file(checks, os.path.join(KI_DIR, relpath), relpath, critical=True)
    check_file(checks, os.path.join(KI_DIR, "knowledge_infrastructure.yaml"), "KI manifest", critical=True)
    check_file(checks, os.path.join(KI_DIR, "dag.yaml"), "DAG", critical=True)
    check_file(checks, os.path.join(KI_DIR, "SKILL.md"), "agent skill instructions", critical=True)
    check_file(checks, TRIPLETS, "diagnostic triplets", critical=True)
    print()

    for path, label, critical in COMMON_DATA_PATHS:
        check_dir(checks, path, label, critical=critical)
    print()

    passed = sum(1 for c in checks if c["status"] == "pass")
    failed = len(checks) - passed
    critical_failed = [c for c in checks if c["critical"] and c["status"] != "pass"]
    print(f"  Results: {passed} passed, {failed} failed")
    if critical_failed:
        print("  STATUS: PREFLIGHT FAILED - fix critical issues before running")
    else:
        print("  STATUS: PREFLIGHT PASSED - safe to proceed with model execution")
    print()

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
