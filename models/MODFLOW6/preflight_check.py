#!/usr/bin/env python3
"""
Preflight check for the MODFLOW 6 Knowledge Infrastructure.

This script verifies the executable, Python interface, KI metadata, tools, and
data inputs needed before a MODFLOW 6 run. It always ends with one
PREFLIGHT_REPORT= JSON line as required by the KDT gate.
"""

import json
import os
import subprocess
import sys
from pathlib import Path


MODEL_ID = "MODFLOW6"
KI_DIR = Path(__file__).resolve().parent
MF6_EXE = Path("KISSPATH_BINARIES/modflow6/mf6.6.1_linux/bin/mf6")
HYDROCRAFT_PYTHON = Path("KISSPATH_PYTHON_ENV/bin/python")
TRIPLETS = KI_DIR / "diagnostics" / "triplets.yaml"

CHECKS = []


def add_check(kind, subject, critical, status, fix):
    CHECKS.append(
        {
            "kind": kind,
            "subject": str(subject),
            "critical": bool(critical),
            "status": status,
            "fix": fix,
        }
    )


def print_result(status, label, subject, fix=""):
    tag = "OK" if status == "pass" else "FAIL"
    print(f"  {tag:<5} {label}: {subject}")
    if status == "fail" and fix:
        print(f"        Fix: {fix}")


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}, sort_keys=True))
    has_failed_critical = any(c["status"] == "fail" and c.get("critical") for c in checks)
    sys.exit(1 if has_failed_critical else 0)


def check_file(path, label, *, kind="data", executable=False, critical=True, fix=None):
    path = Path(path)
    subject = os.path.realpath(path) if kind == "binary" and path.exists() else str(path)
    if not path.is_file():
        status = "fail"
        fix = fix or f"Restore required file; see {TRIPLETS} for recovery guidance."
    elif executable and not os.access(path, os.X_OK):
        status = "fail"
        fix = fix or f"Run chmod +x {path}; see {TRIPLETS} for recovery guidance."
    else:
        status = "pass"
        fix = ""

    print_result(status, label, subject, fix)
    add_check(kind, subject, critical, status, fix)
    return status == "pass"


def check_dir(path, label, *, critical=False, fix=None):
    path = Path(path)
    subject = os.path.realpath(path) if path.exists() else str(path)
    if path.is_dir():
        try:
            count = len(os.listdir(path))
        except OSError:
            count = "unreadable"
        status = "pass"
        fix = ""
        print_result(status, label, f"{subject} ({count} items)")
    else:
        status = "fail"
        fix = fix or f"Restore or mount data directory; see {TRIPLETS} for recovery guidance."
        print_result(status, label, subject, fix)

    add_check("data", subject, critical, status, fix)
    return status == "pass"


def check_binary_starts(path):
    path = Path(path)
    subject = os.path.realpath(path) if path.exists() else str(path)
    fix = f"Repair MODFLOW 6 executable or update knowledge_infrastructure.yaml; see {TRIPLETS}."
    if not path.is_file() or not os.access(path, os.X_OK):
        status = "fail"
        print_result(status, "MODFLOW 6 starts", subject, fix)
        add_check("run", subject, True, status, fix)
        return False

    try:
        proc = subprocess.run(
            [str(path), "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception as exc:
        status = "fail"
        fix = f"{fix} Startup error: {exc}"
        print_result(status, "MODFLOW 6 starts", subject, fix)
        add_check("run", subject, True, status, fix)
        return False

    output = "\n".join(x for x in [proc.stdout.strip(), proc.stderr.strip()] if x)
    if proc.returncode == 0 and "mf6:" in output.lower():
        status = "pass"
        fix = ""
        print_result(status, "MODFLOW 6 starts", f"{subject} ({output.splitlines()[0]})")
    else:
        status = "fail"
        fix = f"{fix} '--version' returned {proc.returncode}: {output[:300]}"
        print_result(status, "MODFLOW 6 starts", subject, fix)

    add_check("run", subject, True, status, fix)
    return status == "pass"


def check_import(module, label, *, python_exe=HYDROCRAFT_PYTHON, critical=True):
    subject = f"{python_exe}: import {module}"
    fix = (
        f"Install {module.split('.')[0]} in KISSPATH_PYTHON_ENV "
        f"and check {TRIPLETS}."
    )
    if not Path(python_exe).is_file():
        status = "fail"
        fix = f"Restore HydroCraft Python interpreter at {python_exe}; see {TRIPLETS}."
        print_result(status, label, subject, fix)
        add_check("import", subject, critical, status, fix)
        return False

    code = f"import {module}; print(getattr({module.split('.')[0]}, '__version__', 'ok'))"
    proc = subprocess.run(
        [str(python_exe), "-c", code],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    if proc.returncode == 0:
        version = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else "ok"
        status = "pass"
        fix = ""
        print_result(status, label, f"{subject} ({version})")
    else:
        status = "fail"
        detail = (proc.stderr or proc.stdout).strip().splitlines()[-1:] or ["unknown import error"]
        fix = f"{fix} Import error: {detail[0]}"
        print_result(status, label, subject, fix)

    add_check("import", subject, critical, status, fix)
    return status == "pass"


def check_tools():
    required_tools = [
        "tools/calib_run.py",
        "tools/s1/verify_mf6_installation.py",
        "tools/s2/create_grid_from_basin.py",
        "tools/s2/build_dis_package.py",
        "tools/s2/build_layers_from_global.py",
        "tools/s3/build_npf_package.py",
        "tools/s3/build_sto_package.py",
        "tools/s3/assign_k_from_glhymps.py",
        "tools/s4/build_chd_package.py",
        "tools/s4/build_rch_package.py",
        "tools/s4/build_riv_package.py",
        "tools/s4/build_drn_package.py",
        "tools/s4/build_wel_package.py",
        "tools/s4/build_riv_from_cama.py",
        "tools/s5/build_tdis_package.py",
        "tools/s5/build_ic_package.py",
        "tools/s5/assign_transient_stress.py",
        "tools/s6/build_ims_package.py",
        "tools/s7/write_and_run_simulation.py",
        "tools/s8/extract_heads.py",
        "tools/s8/extract_budget.py",
        "tools/s9/export_to_netcdf.py",
        "tools/s9/plot_head_map.py",
        "tools/s9/plot_water_budget.py",
        "tools/s10_transport/configure_gwt.py",
        "tools/s10_transport/parse_gwt_output.py",
        "tools/s11_sfr/configure_sfr.py",
        "tools/s11_sfr/parse_sfr_output.py",
    ]
    for rel in required_tools:
        check_file(
            KI_DIR / rel,
            f"KI tool {rel}",
            critical=True,
            fix=f"Restore {rel} from the KI source or regenerate the KI; see {TRIPLETS}.",
        )


def check_required_data():
    required_data_files = [
        (
            "KISSPATH_DATA/groundwater/glhymps/GLHYMPS.shp",
            "GLHYMPS hydrogeology shapefile",
        ),
        (
            "KISSPATH_DATA/groundwater/fan_wtd/MeanWaterTableDepth_meter.tif",
            "Fan/Reinecke water table depth raster",
        ),
        (
            "KISSPATH_DATA/groundwater/glim/glim_wgs84_0point5deg.txt.asc",
            "GLiM lithology grid",
        ),
        (
            "KISSPATH_STATIC/china_dem_90m/china_dem_90m.tif",
            "China DEM 90m raster",
        ),
        (
            "KISSPATH_STATIC/HWSD_China_Geo.img",
            "HWSD China soil raster",
        ),
    ]
    for path, label in required_data_files:
        check_file(path, label, critical=True)

    # Preserve the legacy common HydroCraft data probes as noncritical checks.
    check_dir("KISSPATH_OBS", "Observation data", critical=False)
    check_dir("KISSPATH_FORCING", "Forcing data", critical=False)
    check_dir("KISSPATH_STATIC", "DEM data directory", critical=False)
    check_dir("KISSPATH_STATIC", "Soil data directory", critical=False)


def main():
    print("=" * 60)
    print("  PREFLIGHT CHECK: MODFLOW 6")
    print("=" * 60)
    print()

    check_file(MF6_EXE, "MODFLOW 6.6.1 executable", kind="binary", executable=True, critical=True)
    check_binary_starts(MF6_EXE)
    check_file(HYDROCRAFT_PYTHON, "HydroCraft Python interpreter", executable=True, critical=True)
    check_import("flopy", "FloPy Python interface", critical=True)

    print()
    check_file(KI_DIR / "SKILL.md", "KI SKILL.md", critical=True)
    check_file(KI_DIR / "knowledge_infrastructure.yaml", "KI manifest", critical=True)
    check_file(KI_DIR / "dag.yaml", "KI DAG", critical=True)
    check_file(TRIPLETS, "Diagnostic triplets", critical=True)

    print()
    check_tools()

    print()
    check_required_data()

    print()
    passed = sum(1 for c in CHECKS if c["status"] == "pass")
    failed = sum(1 for c in CHECKS if c["status"] == "fail")
    critical_failed = sum(1 for c in CHECKS if c["status"] == "fail" and c["critical"])
    print(f"  Results: {passed} passed, {failed} failed ({critical_failed} critical failed)")
    if critical_failed:
        print(f"  STATUS: PREFLIGHT FAILED - check {TRIPLETS} for recovery guidance.")
    else:
        print("  STATUS: PREFLIGHT PASSED - safe to proceed with model execution.")

    emit_report(MODEL_ID, CHECKS)


if __name__ == "__main__":
    main()
