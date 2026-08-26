#!/usr/bin/env python3
"""
Preflight check for the HydroCraft mHM KI.

Run this before model setup or execution. It verifies the actual mHM binary,
the HydroCraft Python environment used by the KI tools, required KI metadata,
tool syntax/import dependencies, and the current shared data roots referenced
by the tools.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


MODEL_ID = "mHM"
KI_DIR = Path(__file__).resolve().parent
TRIPLETS = KI_DIR / "diagnostics" / "triplets.yaml"
HYDROCRAFT_ROOT = Path(os.environ.get("HYDROCRAFT_ROOT", "KISSPATH_ROOT"))
PYTHON_ENV = HYDROCRAFT_ROOT / "python_env" / "bin" / "python"
MHM_BINARY = HYDROCRAFT_ROOT / "model" / "mhm" / "mhm"

TOOL_FILES = [
    "tools/s0_config/configure_mhm_basin.py",
    "tools/s1_domain/delineate_basin_merit.py",
    "tools/s1_domain/setup_mhm_domain.py",
    "tools/s1_domain/generate_latlon_files.py",
    "tools/s2_morphology/prepare_morpho_data.py",
    "tools/s2_morphology/hwsd_to_mhm_soil.py",
    "tools/s2_morphology/glim_to_mhm_geology.py",
    "tools/s2_morphology/landcover_to_mhm_luse.py",
    "tools/s2_morphology/generate_gauge_grid.py",
    "tools/s2_morphology/validate_morph_grids.py",
    "tools/s3_mpr/generate_mhm_parameters.py",
    "tools/s4_forcing/convert_forcing_to_mhm.py",
    "tools/s5_gauge/prepare_mhm_gauge.py",
    "tools/s6_namelist/generate_mhm_namelists.py",
    "tools/s7_execute/run_mhm.py",
    "tools/s8_postprocess/parse_mhm_output.py",
    "tools/s8_postprocess/compare_mhm_vic.py",
    "tools/s9_calibration/setup_mhm_calibration.py",
    "tools/s10_regionalize/transfer_mpr_params.py",
]

PYTHON_IMPORTS = [
    "numpy",
    "pandas",
    "xarray",
    "netCDF4",
    "geopandas",
    "rasterio",
    "shapely",
    "scipy",
    "yaml",
    "ki_tools_common.load_forcing",
    "ki_tools_common.units",
]

REQUIRED_KI_FILES = [
    "SKILL.md",
    "knowledge_infrastructure.yaml",
    "dag.yaml",
    "docs/format_spec.yaml",
    "diagnostics/triplets.yaml",
]

DATA_PATHS = [
    (HYDROCRAFT_ROOT / "data" / "obs", "Observation data root", False),
    (Path("KISSPATH_FORCING"), "CMFD forcing data root", False),
    (HYDROCRAFT_ROOT / "data" / "dem" / "china_dem_90m" / "china_dem_90m.tif", "China DEM 90m raster", False),
    (HYDROCRAFT_ROOT / "data" / "merit_hydro", "MERIT-Hydro tile root", False),
    (HYDROCRAFT_ROOT / "data" / "soil" / "HWSD_RASTER" / "hwsd.bil", "HWSD raster", False),
    (HYDROCRAFT_ROOT / "data" / "forcing" / "huaihe_raw" / "soil" / "HWSD.mdb", "HWSD properties database", False),
    (HYDROCRAFT_ROOT / "data" / "groundwater" / "glim" / "glim_wgs84_0point5deg.txt.asc", "GLiM geology raster", False),
    (
        HYDROCRAFT_ROOT / "data" / "landcover" / "AVHRR_1km_LANDCOVER_1981_1994.GLOBAL.tif",
        "AVHRR land-cover raster",
        False,
    ),
]


checks = []


def diagnostics_fix(action):
    return f"{action}; then check {TRIPLETS} for known recovery steps."


def add_check(kind, subject, critical, passed, fix=""):
    status = "pass" if passed else "fail"
    checks.append(
        {
            "kind": kind,
            "subject": str(subject),
            "critical": bool(critical),
            "status": status,
            "fix": "" if passed else fix,
        }
    )
    label = "OK" if passed else ("FAIL" if critical else "WARN")
    print(f"  {label:<5} {kind}: {subject}")
    if not passed and fix:
        print(f"        Fix: {fix}")
    return passed


def check_file(path, label, critical=True, executable=False):
    path = Path(path)
    subject = path.resolve(strict=False)
    if not path.is_file():
        return add_check("data", subject, critical, False, diagnostics_fix(f"Restore missing {label}: {path}"))
    if executable and not os.access(path, os.X_OK):
        return add_check("binary", subject, critical, False, diagnostics_fix(f"Make {label} executable: chmod +x {path}"))
    kind = "binary" if executable else "data"
    return add_check(kind, subject, critical, True)


def check_dir(path, label, critical=True):
    path = Path(path)
    subject = path.resolve(strict=False)
    if not path.is_dir():
        return add_check("data", subject, critical, False, diagnostics_fix(f"Restore missing {label}: {path}"))
    try:
        has_items = any(path.iterdir())
    except OSError as exc:
        return add_check("data", subject, critical, False, diagnostics_fix(f"Fix unreadable {label}: {exc}"))
    return add_check("data", subject, critical, has_items, diagnostics_fix(f"Populate empty {label}: {path}"))


def check_binary_search(name, label):
    found = shutil.which(name)
    if found:
        return add_check("binary", Path(found).resolve(strict=False), True, True)

    for root in [HYDROCRAFT_ROOT / "model", Path("KISSPATH_HOME"), Path("/usr/local/bin")]:
        if not root.is_dir():
            continue
        for current, dirs, files in os.walk(root):
            current_path = Path(current)
            for filename in files:
                candidate = current_path / filename
                if name.lower() in filename.lower() and os.access(candidate, os.X_OK):
                    return add_check("binary", candidate.resolve(strict=False), True, True)
            if len(current_path.relative_to(root).parts) > 3:
                dirs.clear()

    return add_check(
        "binary",
        name,
        True,
        False,
        diagnostics_fix(f"Install {label} or update knowledge_infrastructure.yaml with its real executable path"),
    )


def check_python_import(module):
    if not PYTHON_ENV.is_file():
        return add_check(
            "import",
            f"{module} via {PYTHON_ENV}",
            True,
            False,
            diagnostics_fix(f"Restore HydroCraft Python interpreter at {PYTHON_ENV}"),
        )
    code = "import importlib, sys; importlib.import_module(sys.argv[1])"
    proc = subprocess.run(
        [str(PYTHON_ENV), "-c", code, module],
        cwd=str(KI_DIR),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
    )
    return add_check(
        "import",
        f"{module} via {PYTHON_ENV}",
        True,
        proc.returncode == 0,
        diagnostics_fix(f"Install/fix Python module '{module}' in {PYTHON_ENV}: {proc.stderr.strip() or proc.stdout.strip()}"),
    )


def check_tool_syntax():
    if not PYTHON_ENV.is_file():
        return add_check(
            "import",
            f"py_compile KI tools via {PYTHON_ENV}",
            True,
            False,
            diagnostics_fix(f"Restore HydroCraft Python interpreter at {PYTHON_ENV}"),
        )
    files = [str(KI_DIR / rel) for rel in TOOL_FILES]
    proc = subprocess.run(
        [str(PYTHON_ENV), "-m", "py_compile", *files],
        cwd=str(KI_DIR),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
    )
    return add_check(
        "import",
        f"py_compile {len(TOOL_FILES)} KI tools via {PYTHON_ENV}",
        True,
        proc.returncode == 0,
        diagnostics_fix(f"Fix KI tool syntax/import-time error: {proc.stderr.strip() or proc.stdout.strip()}"),
    )


def check_binary_starts():
    binary_realpath = MHM_BINARY.resolve(strict=False)
    if not MHM_BINARY.is_file() or not os.access(MHM_BINARY, os.X_OK):
        return add_check(
            "run",
            f"{binary_realpath} --version",
            True,
            False,
            diagnostics_fix(f"Restore executable mHM binary at {MHM_BINARY}"),
        )
    proc = subprocess.run(
        [str(MHM_BINARY), "--version"],
        cwd=str(KI_DIR),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=5,
    )
    output = (proc.stdout + proc.stderr).strip()
    passed = proc.returncode == 0 and "5.13" in output
    return add_check(
        "run",
        f"{binary_realpath} --version",
        True,
        passed,
        diagnostics_fix(f"mHM binary did not start cleanly or did not report v5.13.x: {output or 'no output'}"),
    )


def emit_report(model_id, report_checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": report_checks}, sort_keys=True))
    sys.exit(0 if all(c["status"] == "pass" or not c.get("critical") for c in report_checks) else 1)


def main():
    print("=" * 60)
    print(f"  PREFLIGHT CHECK: {MODEL_ID}")
    print("=" * 60)
    print()

    # The contract requires this realpath subject for compiled-model drift checks.
    check_file(MHM_BINARY, "mHM binary", critical=True, executable=True)
    check_binary_starts()

    # Preserve the legacy PATH/common-location binary search as an additional real check.
    check_binary_search("mhm", "mHM binary")

    check_file(PYTHON_ENV, "HydroCraft Python interpreter", critical=True, executable=True)
    for module in PYTHON_IMPORTS:
        check_python_import(module)

    for rel_path in REQUIRED_KI_FILES:
        check_file(KI_DIR / rel_path, rel_path, critical=True)

    for rel_path in TOOL_FILES:
        check_file(KI_DIR / rel_path, rel_path, critical=True)
    check_tool_syntax()

    for path, label, critical in DATA_PATHS:
        if Path(path).is_dir() or not Path(path).suffix:
            check_dir(path, label, critical=critical)
        else:
            check_file(path, label, critical=critical)

    failed_critical = [c for c in checks if c["critical"] and c["status"] == "fail"]
    failed_noncritical = [c for c in checks if not c["critical"] and c["status"] == "fail"]

    print()
    print(f"  Results: {sum(c['status'] == 'pass' for c in checks)} passed, {len(failed_critical)} critical failed, {len(failed_noncritical)} warnings")
    if failed_critical:
        print("  STATUS: PREFLIGHT FAILED - fix the critical issues above before running mHM.")
        print(f"  Recovery: start with {TRIPLETS}")
    else:
        print("  STATUS: PREFLIGHT PASSED - safe to proceed with mHM execution.")
        if failed_noncritical:
            print(f"  Note: non-critical data warnings may matter for basin setup; see {TRIPLETS}")

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
