#!/usr/bin/env python3
"""
Preflight check for the OGGM Knowledge Infrastructure.

This script verifies the real HydroCraft OGGM runner, Python environment,
required imports, KI tools, diagnostics, and cached reference inputs before a
model run. It always ends with a single PREFLIGHT_REPORT= JSON line.
"""

import csv
import json
import os
import subprocess
import sys
from pathlib import Path


MODEL_ID = "OGGM"
ROOT = Path(__file__).resolve().parent
MODEL_ROOT = ROOT.parent
PYTHON = Path("KISSPATH_PYTHON_ENV/bin/python")
SITE_PACKAGES = Path("KISSPATH_PYTHON_ENV/lib/python3.12/site-packages")
RUNNER = Path("KISSPATH_KI_ROOT/OGGM/run_and_score.py")
TRIPLETS = ROOT / "diagnostics" / "triplets.yaml"

REQUIRED_TOOLS = [
    ROOT / "tools/s1_glacier_inventory/download_rgi_region.py",
    ROOT / "tools/s1_glacier_inventory/find_glaciers_in_basin.py",
    ROOT / "tools/s1_glacier_inventory/validate_glacier_selection.py",
    ROOT / "tools/s2_preprocessing/configure_oggm.py",
    ROOT / "tools/s2_preprocessing/init_glacier_directories.py",
    ROOT / "tools/s2_preprocessing/validate_preprocessing.py",
    ROOT / "tools/s3_climate_input/process_climate_baseline.py",
    ROOT / "tools/s3_climate_input/process_cmip6_projections.py",
    ROOT / "tools/s3_climate_input/process_custom_climate.py",
    ROOT / "tools/s4_calibration/calibrate_mass_balance.py",
    ROOT / "tools/s4_calibration/validate_calibration.py",
    ROOT / "tools/s5_simulation/compile_glacier_output.py",
    ROOT / "tools/s5_simulation/run_glacier_projections.py",
    ROOT / "tools/s5_simulation/run_glacier_simulation.py",
    ROOT / "tools/s5_simulation/validate_wgms_reference_mb.py",
    ROOT / "tools/s6_vic_coupling/glacier_contribution_analysis.py",
    ROOT / "tools/s6_vic_coupling/oggm_to_vic_runoff.py",
    ROOT / "tools/s6_vic_coupling/plot_glacier_hydro.py",
]

HELP_TOOLS = [
    ROOT / "tools/s2_preprocessing/init_glacier_directories.py",
    ROOT / "tools/s5_simulation/run_glacier_simulation.py",
    ROOT / "tools/s5_simulation/compile_glacier_output.py",
]

REQUIRED_DATA_FILES = [
    MODEL_ROOT / "yajiang_glaciers.csv",
    Path("KISSPATH_HOME/OGGM/yajiang_test/run_output_hist.nc"),
]

CACHED_OUTPUTS = [
    MODEL_ROOT / "yajiang_run/working_dir/run_output_historical.nc",
    MODEL_ROOT / "yajiang_run/compiled/compiled_output_historical.nc",
]


def recovery_fix(message):
    return f"{message}; check {TRIPLETS} for known recovery steps"


def check(kind, subject, critical, status, fix=""):
    item = {
        "kind": kind,
        "subject": str(subject),
        "critical": bool(critical),
        "status": status,
        "fix": fix or "",
    }
    label = "OK" if status == "pass" else ("FAIL" if critical else "WARN")
    print(f"  {label:<5} {kind}: {subject}")
    if status != "pass" and fix:
        print(f"        Fix: {fix}")
    return item


def check_file(path, label, critical=True, executable=False):
    path = Path(path)
    subject = path.resolve() if path.exists() else path
    if not path.is_file():
        return check("data", subject, critical, "fail", recovery_fix(f"{label} not found"))
    if executable and not os.access(path, os.X_OK):
        return check("data", subject, critical, "fail", recovery_fix(f"make {label} executable with chmod +x {path}"))
    return check("data", subject, critical, "pass")


def check_dir(path, label, critical=False):
    path = Path(path)
    subject = path.resolve() if path.exists() else path
    if not path.is_dir():
        return check("data", subject, critical, "fail", recovery_fix(f"{label} directory not found"))
    if not any(path.iterdir()):
        return check("data", subject, critical, "fail", recovery_fix(f"{label} directory is empty"))
    return check("data", subject, critical, "pass")


def check_python():
    subject = PYTHON.resolve() if PYTHON.exists() else PYTHON
    if not PYTHON.is_file():
        return check("binary", subject, True, "fail", recovery_fix("HydroCraft Python interpreter is missing"))
    if not os.access(PYTHON, os.X_OK):
        return check("binary", subject, True, "fail", recovery_fix(f"make interpreter executable with chmod +x {PYTHON}"))
    return check("binary", subject, True, "pass")


def check_runner():
    subject = RUNNER.resolve() if RUNNER.exists() else RUNNER
    if not RUNNER.is_file():
        return check("binary", subject, True, "fail", recovery_fix("OGGM runner from knowledge_infrastructure.yaml is missing"))
    proc = subprocess.run(
        [str(PYTHON), "-m", "py_compile", str(RUNNER)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout).strip().splitlines()[-1:]
        detail = err[0] if err else "py_compile failed"
        return check("binary", subject, True, "fail", recovery_fix(f"runner does not compile under {PYTHON}: {detail}"))
    return check("binary", subject, True, "pass")


def check_import(module, label, critical=True):
    code = (
        "import importlib; "
        f"m = importlib.import_module({module!r}); "
        "print(getattr(m, '__version__', ''))"
    )
    proc = subprocess.run(
        [str(PYTHON), "-c", code],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip().splitlines()[-1:] or ["import failed"]
        return check("import", module, critical, "fail", recovery_fix(f"{label} import failed under {PYTHON}: {detail[0]}"))
    version = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
    subject = f"{module} {version}".strip()
    return check("import", subject, critical, "pass")


def check_tool_help(tool):
    proc = subprocess.run(
        [str(PYTHON), str(tool), "--help"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    subject = tool.resolve() if tool.exists() else tool
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip().splitlines()[-1:] or ["--help failed"]
        return check("run", subject, True, "fail", recovery_fix(f"{tool.name} does not start: {detail[0]}"))
    return check("run", subject, True, "pass")


def check_tools_present():
    missing = [str(p.relative_to(ROOT)) for p in REQUIRED_TOOLS if not p.is_file()]
    subject = ROOT / "tools"
    if missing:
        return check("data", subject, True, "fail", recovery_fix("missing KI tools: " + ", ".join(missing)))
    return check("data", subject.resolve(), True, "pass")


def check_rgi_csv(path):
    path = Path(path)
    subject = path.resolve() if path.exists() else path
    if not path.is_file():
        return check("data", subject, True, "fail", recovery_fix("Yajiang RGI ID CSV is missing"))
    try:
        with path.open(newline="") as handle:
            rows = list(csv.DictReader(handle))
    except Exception as exc:
        return check("data", subject, True, "fail", recovery_fix(f"cannot read Yajiang RGI ID CSV: {exc}"))
    ids = [row.get("rgi_id") or row.get("RGIId") for row in rows]
    ids = [value for value in ids if value]
    if not ids:
        return check("data", subject, True, "fail", recovery_fix("Yajiang RGI ID CSV has no rgi_id/RGIId values"))
    return check("data", subject, True, "pass")


def check_netcdf(path, required_vars, critical=True):
    subject = path.resolve() if path.exists() else path
    if not path.is_file():
        return check("data", subject, critical, "fail", recovery_fix(f"NetCDF file is missing: {path}"))
    try:
        if str(SITE_PACKAGES) not in sys.path:
            sys.path.insert(0, str(SITE_PACKAGES))
        import netCDF4

        with netCDF4.Dataset(str(path)) as dataset:
            missing = [name for name in required_vars if name not in dataset.variables]
    except Exception as exc:
        return check("data", subject, critical, "fail", recovery_fix(f"cannot open NetCDF file {path}: {exc}"))
    if missing:
        return check("data", subject, critical, "fail", recovery_fix(f"NetCDF file {path} missing variables: {', '.join(missing)}"))
    return check("data", subject, critical, "pass")


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}, sort_keys=True))
    failed_critical = [item for item in checks if item["critical"] and item["status"] != "pass"]
    sys.exit(1 if failed_critical else 0)


def main():
    print("=" * 60)
    print("  PREFLIGHT CHECK: OGGM")
    print("=" * 60)
    print()

    checks = []
    checks.append(check_python())
    checks.append(check_runner())

    print()
    checks.extend(
        [
            check_import("oggm", "OGGM 1.6.x"),
            check_import("oggm.core", "OGGM core"),
            check_import("netCDF4", "netCDF4"),
            check_import("numpy", "numpy"),
            check_import("ki_tools_common.metrics", "ki_tools_common metrics"),
        ]
    )

    print()
    checks.append(check_tools_present())
    for tool in HELP_TOOLS:
        checks.append(check_tool_help(tool))

    print()
    checks.append(check_rgi_csv(REQUIRED_DATA_FILES[0]))
    checks.append(check_netcdf(REQUIRED_DATA_FILES[1], ["volume", "area", "calendar_year", "rgi_id"], critical=True))
    checks.append(check_netcdf(CACHED_OUTPUTS[0], ["volume", "area", "calendar_year", "rgi_id"], critical=False))
    checks.append(check_netcdf(CACHED_OUTPUTS[1], ["volume", "area", "time", "rgi_id"], critical=False))

    print()
    checks.append(check_file(ROOT / "knowledge_infrastructure.yaml", "KI manifest", critical=True))
    checks.append(check_file(ROOT / "dag.yaml", "DAG", critical=True))
    checks.append(check_file(ROOT / "SKILL.md", "KI skill instructions", critical=True))
    checks.append(check_file(TRIPLETS, "diagnostic triplets", critical=False))
    checks.append(check_file(ROOT / "docs/format_spec.yaml", "format specification", critical=False))
    checks.append(check_dir(MODEL_ROOT / "yajiang_run/working_dir/per_glacier", "cached OGGM glacier directories", critical=False))

    print()
    passed = sum(1 for item in checks if item["status"] == "pass")
    failed = len(checks) - passed
    print(f"  Results: {passed} passed, {failed} failed")
    if any(item["critical"] and item["status"] != "pass" for item in checks):
        print("  STATUS: PREFLIGHT FAILED - fix critical issues above before running")
    else:
        print("  STATUS: PREFLIGHT PASSED - safe to proceed with model execution")

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        checks = [
            check(
                "run",
                "preflight_check.py",
                True,
                "fail",
                recovery_fix(f"preflight crashed: {type(exc).__name__}: {exc}"),
            )
        ]
        emit_report(MODEL_ID, checks)
