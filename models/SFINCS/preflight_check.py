#!/usr/bin/env python3
"""
Preflight check for the SFINCS Knowledge Infrastructure.

This script verifies the executable, Python environment, KI support files, and
locally registered datasets before a run. It always ends with exactly one
PREFLIGHT_REPORT= JSON line, as required by the KDT gate.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


MODEL_ID = "SFINCS"
KI_DIR = Path(__file__).resolve().parent
TRIPLETS = KI_DIR / "diagnostics" / "triplets.yaml"

SFINCS_BINARY = Path("KISSPATH_BINARIES/sfincs/bin/sfincs")
HYDROCRAFT_PYTHON = Path("KISSPATH_PYTHON_ENV/bin/python")
KI_TOOLS_COMMON = Path("KISSPATH_KI_TOOLS_COMMON")


def make_check(kind, subject, critical, status, fix=""):
    check = {
        "kind": kind,
        "subject": str(subject),
        "critical": bool(critical),
        "status": status,
        "fix": fix,
    }
    return check


def add_check(checks, kind, subject, critical, ok, fix):
    status = "pass" if ok else "fail"
    checks.append(make_check(kind, subject, critical, status, "" if ok else fix))
    label = "OK" if ok else ("FAIL" if critical else "WARN")
    print(f"  {label:<5} {kind}: {subject}")
    if not ok:
        print(f"        Fix: {fix}")


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}, sort_keys=True))
    critical_failed = any(c["status"] != "pass" and c.get("critical") for c in checks)
    sys.exit(1 if critical_failed else 0)


def diagnostics_fix(message):
    return f"{message}; then check {TRIPLETS} for matching recovery guidance."


def check_file(checks, path, label, critical=True, executable=False):
    p = Path(path)
    subject = str(p)
    ok = p.is_file() and (not executable or os.access(p, os.X_OK))
    if executable and p.exists():
        subject = os.path.realpath(p)
    if executable and p.is_file() and not os.access(p, os.X_OK):
        fix = diagnostics_fix(f"Make executable: chmod +x {p}")
    else:
        fix = diagnostics_fix(f"Restore required file for {label}: {p}")
    add_check(checks, "binary" if executable else "data", subject, critical, ok, fix)
    return ok


def check_dir(checks, path, label, critical=False, require_nonempty=True):
    p = Path(path)
    ok = p.is_dir() and (not require_nonempty or any(p.iterdir()))
    fix = diagnostics_fix(f"Restore or mount required directory for {label}: {p}")
    add_check(checks, "data", p, critical, ok, fix)
    return ok


def python_env():
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    pieces = [str(KI_TOOLS_COMMON)]
    if existing:
        pieces.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(pieces)
    return env


def check_import(checks, module, label, critical=True):
    if not HYDROCRAFT_PYTHON.is_file():
        add_check(
            checks,
            "import",
            f"{module} via {HYDROCRAFT_PYTHON}",
            critical,
            False,
            diagnostics_fix(f"Restore HydroCraft Python interpreter at {HYDROCRAFT_PYTHON}"),
        )
        return False

    cmd = [str(HYDROCRAFT_PYTHON), "-c", f"import {module}"]
    result = subprocess.run(cmd, cwd=str(KI_DIR), env=python_env(), text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
    ok = result.returncode == 0
    fix = diagnostics_fix(
        f"Install/fix Python dependency '{label}' in KISSPATH_PYTHON_ENV"
    )
    add_check(checks, "import", f"{module} via {HYDROCRAFT_PYTHON}", critical, ok, fix)
    if not ok:
        detail = (result.stderr or result.stdout).strip().splitlines()
        if detail:
            print(f"        Detail: {detail[-1]}")
    return ok


def check_binary_starts(checks):
    if not SFINCS_BINARY.is_file() or not os.access(SFINCS_BINARY, os.X_OK):
        subject = os.path.realpath(SFINCS_BINARY) if SFINCS_BINARY.exists() else str(SFINCS_BINARY)
        add_check(
            checks,
            "run",
            subject,
            True,
            False,
            diagnostics_fix(f"Restore executable SFINCS binary at {SFINCS_BINARY}"),
        )
        return False

    subject = os.path.realpath(SFINCS_BINARY)
    with tempfile.TemporaryDirectory(prefix="sfincs_preflight_") as tmp:
        try:
            result = subprocess.run([str(SFINCS_BINARY)], cwd=tmp, text=True,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=8)
        except subprocess.TimeoutExpired:
            add_check(
                checks,
                "run",
                subject,
                True,
                False,
                diagnostics_fix("SFINCS did not reach startup diagnostics within 8 seconds"),
            )
            return False

    output = result.stdout or ""
    # With no sfincs.inp in the temporary directory, a healthy binary starts, prints
    # the banner/build metadata, and exits with STOP 2 complaining about the missing input.
    ok = ("Welcome to SFINCS" in output and "sfincs.inp" in output
          and result.returncode != 127)
    add_check(
        checks,
        "run",
        subject,
        True,
        ok,
        diagnostics_fix("Run the binary manually and repair shared-library/build problems"),
    )
    if ok:
        for line in output.splitlines():
            if "Build-Revision:" in line or "Build-Date:" in line:
                print(f"        {line.strip()}")
    else:
        tail = "\n".join(output.splitlines()[-5:])
        if tail:
            print(f"        Detail: {tail}")
    return ok


def check_manifest_binary(checks):
    manifest = KI_DIR / "knowledge_infrastructure.yaml"
    ok = manifest.is_file() and str(SFINCS_BINARY) in manifest.read_text(errors="replace")
    add_check(
        checks,
        "data",
        manifest,
        True,
        ok,
        diagnostics_fix(f"Regenerate or repair {manifest} so it records binary.path: {SFINCS_BINARY}"),
    )


def main():
    checks = []
    print("=" * 60)
    print(f"  PREFLIGHT CHECK: {MODEL_ID}")
    print("=" * 60)

    check_file(checks, SFINCS_BINARY, "SFINCS solver", critical=True, executable=True)
    check_binary_starts(checks)
    check_manifest_binary(checks)

    for required in [
        KI_DIR / "SKILL.md",
        KI_DIR / "dag.yaml",
        TRIPLETS,
        KI_DIR / "tools" / "s7_execution" / "run_sfincs.py",
        KI_DIR / "tools" / "s6_config" / "generate_sfincs_inp.py",
        KI_DIR / "tools" / "s2_topobathy" / "build_sfincs_topobathy.py",
    ]:
        check_file(checks, required, required.relative_to(KI_DIR), critical=True)

    check_file(checks, HYDROCRAFT_PYTHON, "HydroCraft Python interpreter", critical=True, executable=True)
    check_dir(checks, KI_TOOLS_COMMON, "ki_tools_common package root", critical=True)

    for module, label in [
        ("numpy", "NumPy"),
        ("pandas", "pandas"),
        ("rasterio", "rasterio/GDAL raster IO"),
        ("xarray", "xarray NetCDF handling"),
        ("geopandas", "GeoPandas vector IO"),
        ("scipy", "SciPy numerical utilities"),
        ("netCDF4", "netCDF4 CaMa/SFINCS readers"),
        ("h5netcdf", "h5netcdf fallback for SFINCS output"),
        ("pyproj", "pyproj CRS transforms"),
        ("matplotlib", "matplotlib postprocessing"),
        ("yaml", "PyYAML dataset registry parsing"),
        ("ki_tools_common.load_forcing", "HydroCraft forcing loader"),
        ("ki_tools_common.metrics", "HydroCraft validation metrics"),
    ]:
        check_import(checks, module, label, critical=True)

    # Local data used by the validated tools when the user does not provide an
    # explicit replacement. Regional datasets are noncritical because a valid run
    # can use user-supplied DEM/forcing instead.
    for path, label in [
        ("KISSPATH_STATIC/china_dem_90m/china_dem_90m.tif", "China DEM 90m"),
        ("KISSPATH_OBS/ice_sheets/bedmachine/BedMachineGreenland-v6.nc",
         "BedMachine Greenland v6"),
        ("KISSPATH_OBS/ice_sheets/bedmachine/NSIDC-0756_BedMachineAntarctica_19700101-20191001_V04.1.nc",
         "BedMachine Antarctica v4.1"),
        ("KISSPATH_DATA/landcover/AVHRR_1km_LANDCOVER_1981_1994.GLOBAL.tif",
         "AVHRR land cover raster"),
        ("KISSPATH_DATA_KI/dataset_index.yaml", "HydroCraft dataset registry"),
    ]:
        check_file(checks, path, label, critical=False)

    for path, label in [
        ("KISSPATH_DATA/forcing/Data_forcing_03hr_010deg", "CMFD forcing directory"),
        ("KISSPATH_FORCING", "MSWX forcing directory"),
        ("KISSPATH_BINARIES/cmf_v420_pkg/out", "CaMa-Flood output directory"),
    ]:
        check_dir(checks, path, label, critical=False)

    passed = sum(1 for c in checks if c["status"] == "pass")
    failed = len(checks) - passed
    critical_failed = sum(1 for c in checks if c["status"] != "pass" and c.get("critical"))
    print()
    print(f"  Results: {passed} passed, {failed} failed, {critical_failed} critical failed")
    if critical_failed:
        print(f"  STATUS: PREFLIGHT FAILED - fix blockers above; start with {TRIPLETS}")
    else:
        print("  STATUS: PREFLIGHT PASSED - SFINCS KI is ready for model execution")

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
