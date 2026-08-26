#!/usr/bin/env python3
"""
Preflight check for the CRHM Knowledge Infrastructure.

Run this before attempting CRHM execution. It verifies the actual CRHM binary,
the canonical HydroCraft Python environment used by the KI tools, required KI
files, tool scripts, and common HydroCraft data locations.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

MODEL_ID = "CRHM"
KI_DIR = Path(__file__).resolve().parent
TRIPLETS = KI_DIR / "diagnostics" / "triplets.yaml"
PYTHON_ENV = Path("KISSPATH_PYTHON_ENV/bin/python")
CRHM_EXE = Path("KISSPATH_BINARIES/crhmcode/crhmcode/build/crhm")

TOOL_FILES = [
    "tools/calib_run.py",
    "tools/s1_basin_setup/create_hru_config.py",
    "tools/s2_observation_data/convert_vic_to_obs.py",
    "tools/s2_observation_data/netcdf_safe.py",
    "tools/s2_observation_data/screen_swe_obs.py",
    "tools/s2_observation_data/validate_obs_file.py",
    "tools/s3_module_selection/select_modules.py",
    "tools/s4_parameter_config/create_prj_file.py",
    "tools/s4_parameter_config/derive_parameters.py",
    "tools/s4_parameter_config/validate_prj.py",
    "tools/s5_execution/check_water_balance.py",
    "tools/s5_execution/parse_crhm_output.py",
    "tools/s5_execution/plot_crhm_results.py",
    "tools/s5_execution/run_crhm.py",
    "tools/s6_vic_coupling/merge_crhm_vic.py",
]

IMPORT_MODULES = [
    "geopandas",
    "ki_tools_common",
    "matplotlib",
    "netCDF4",
    "numpy",
    "pandas",
    "rasterio",
    "xarray",
]

COMMON_DATA_DIRS = [
    ("KISSPATH_OBS", "Observation data"),
    ("KISSPATH_FORCING", "Forcing data"),
    ("KISSPATH_STATIC", "DEM data"),
    ("KISSPATH_STATIC", "Soil data"),
]

REQUIRED_KI_FILES = [
    "SKILL.md",
    "knowledge_infrastructure.yaml",
    "dag.yaml",
    "calibration.yaml",
    "docs/format_spec.yaml",
    "docs/validation_convention.yaml",
]


checks = []


def add_check(kind, subject, critical, ok, fix):
    status = "pass" if ok else "fail"
    checks.append({
        "kind": kind,
        "subject": str(subject),
        "critical": bool(critical),
        "status": status,
        "fix": "" if ok else fix,
    })
    label = "OK" if ok else ("FAIL" if critical else "WARN")
    print(f"  {label:<5} {kind}: {subject}")
    if not ok:
        print(f"        Fix: {fix}")


def check_file(path, label, critical=True, executable=False):
    p = Path(path)
    subject = p.resolve() if p.exists() else Path(os.path.realpath(str(p)))
    if not p.is_file():
        add_check("data", subject, critical, False,
                  f"Restore {label} at {p}; see {TRIPLETS} for recovery hints.")
        return False
    if executable and not os.access(p, os.X_OK):
        add_check("binary" if executable else "data", subject, critical, False,
                  f"Run chmod +x {p}; if still failing, inspect {TRIPLETS}.")
        return False
    add_check("binary" if executable else "data", subject, critical, True, "")
    return True


def check_dir(path, label, critical=False):
    p = Path(path)
    ok = p.is_dir()
    detail = f"{p} ({len(os.listdir(p))} items)" if ok else p
    add_check("data", detail, critical, ok,
              f"Restore or mount {label} at {p}; check {TRIPLETS} for known data-path failures.")
    return ok


def check_python_env():
    if not PYTHON_ENV.is_file():
        add_check("import", PYTHON_ENV, True, False,
                  f"Restore the HydroCraft Python environment at {PYTHON_ENV}; see {TRIPLETS}.")
        return False
    if not os.access(PYTHON_ENV, os.X_OK):
        add_check("import", PYTHON_ENV.resolve(), True, False,
                  f"Run chmod +x {PYTHON_ENV} or repair the python_env interpreter.")
        return False
    add_check("import", PYTHON_ENV, True, True, "")
    return True


def check_import(module):
    cmd = [str(PYTHON_ENV), "-c", f"import {module}"]
    try:
        result = subprocess.run(cmd, cwd=str(KI_DIR), capture_output=True, text=True, timeout=30)
        ok = result.returncode == 0
        stderr = (result.stderr or result.stdout or "").strip().splitlines()
        detail = stderr[-1] if stderr else f"import {module} failed"
    except Exception as exc:
        ok = False
        detail = f"{type(exc).__name__}: {exc}"
    add_check("import", module, True, ok,
              f"Install/repair {module} in {PYTHON_ENV.parent.parent}; details: {detail}; see {TRIPLETS}.")
    return ok


def check_binary_starts():
    subject = Path(os.path.realpath(str(CRHM_EXE)))
    try:
        result = subprocess.run([str(CRHM_EXE), "-h"], cwd=str(KI_DIR),
                                capture_output=True, text=True, timeout=10)
        output = f"{result.stdout}\n{result.stderr}"
        ok = "crhm [options] PROJECT_FILE" in output or "PROJECT_FILE" in output
        detail = f"exit {result.returncode}; usage text not detected"
    except Exception as exc:
        ok = False
        detail = f"{type(exc).__name__}: {exc}"
    add_check("run", subject, True, ok,
              f"Repair CRHM startup at {CRHM_EXE}; details: {detail}; consult {TRIPLETS}.")
    return ok


def check_py_compile():
    cmd = [str(PYTHON_ENV), "-m", "py_compile"] + [str(KI_DIR / p) for p in TOOL_FILES]
    try:
        result = subprocess.run(cmd, cwd=str(KI_DIR), capture_output=True, text=True, timeout=60)
        ok = result.returncode == 0
        detail = (result.stderr or result.stdout or "py_compile failed").strip().splitlines()
        msg = detail[-1] if detail else "py_compile failed"
    except Exception as exc:
        ok = False
        msg = f"{type(exc).__name__}: {exc}"
    add_check("import", "KI tool Python syntax via py_compile", True, ok,
              f"Fix the Python syntax/import-time compile issue in tools; details: {msg}; see {TRIPLETS}.")
    return ok


def emit_report(model_id, report_checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": report_checks}, sort_keys=True))
    ready = all(c["status"] == "pass" or not c.get("critical") for c in report_checks)
    sys.exit(0 if ready else 1)


def main():
    print("=" * 60)
    print("  PREFLIGHT CHECK: CRHM")
    print("=" * 60)
    print()

    check_file(CRHM_EXE, "CRHM executable", critical=True, executable=True)
    check_binary_starts()

    print()
    check_python_env()
    if PYTHON_ENV.is_file() and os.access(PYTHON_ENV, os.X_OK):
        for module in IMPORT_MODULES:
            check_import(module)
        check_py_compile()

    print()
    for rel_path in REQUIRED_KI_FILES:
        check_file(KI_DIR / rel_path, rel_path, critical=True)
    check_file(TRIPLETS, "diagnostic triplets", critical=True)
    for rel_path in TOOL_FILES:
        check_file(KI_DIR / rel_path, rel_path, critical=True)

    print()
    for data_path, label in COMMON_DATA_DIRS:
        check_dir(data_path, label, critical=False)
    check_file("KISSPATH_DATA/elev/elev_CMFD_V0200_B-00_fx_010deg.nc",
               "CMFD elevation grid used by netcdf_safe.py", critical=False)

    failed = [c for c in checks if c["status"] == "fail"]
    critical_failed = [c for c in failed if c["critical"]]
    print()
    print(f"  Results: {len(checks) - len(failed)} passed, {len(failed)} failed")
    if critical_failed:
        print("  STATUS: PREFLIGHT FAILED - fix the critical blockers above before running CRHM.")
        print(f"  Recovery: start with {TRIPLETS}")
    else:
        print("  STATUS: PREFLIGHT PASSED - safe to proceed with CRHM model execution.")

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
