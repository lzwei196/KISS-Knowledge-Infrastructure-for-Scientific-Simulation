#!/usr/bin/env python3
"""
Preflight check for CaMa-Flood v4.20.

Run this before attempting model setup or execution. It checks the real
CaMa-Flood binary, required map/setup data, KI tools, and Python imports.
The final line is the KDT gate contract:
PREFLIGHT_REPORT=<json>
"""

import json
import os
import subprocess
import sys

MODEL_ID = "CaMa_Flood"
KI_DIR = os.path.dirname(os.path.abspath(__file__))
DIAGNOSTICS = os.path.join(KI_DIR, "diagnostics", "triplets.yaml")

CAMA_ROOT = "KISSPATH_BINARIES/cmf_v420_pkg"
BINARY = os.path.join(CAMA_ROOT, "src", "MAIN_cmf")
GLB_MAP = os.path.join(CAMA_ROOT, "map", "glb_15min")
GPCC_CLIM = os.path.join(
    CAMA_ROOT, "map", "data", "ELSE_GPCC_coastmod_dayclm-1981-2010.one"
)
PYTHON_ENV = "KISSPATH_PYTHON_ENV/bin/python"

GLOBAL_MAP_FILES = [
    "nextxy.bin",
    "ctmare.bin",
    "elevtn.bin",
    "nxtdst.bin",
    "rivlen.bin",
    "fldhgt.bin",
    "rivwth.bin",
    "rivhgt.bin",
    "rivman.bin",
    "mapdim.txt",
]

SETUP_BINARIES = [
    os.path.join(GLB_MAP, "src_region", "cut_domain"),
    os.path.join(GLB_MAP, "src_region", "cut_bifway"),
    os.path.join(GLB_MAP, "src_region", "set_map"),
    os.path.join(GLB_MAP, "src_region", "combine_hires"),
    os.path.join(GLB_MAP, "src_param", "generate_inpmat"),
    os.path.join(GLB_MAP, "src_param", "calc_outclm"),
    os.path.join(GLB_MAP, "src_param", "calc_rivwth"),
]

KI_TOOL_FILES = [
    "tools/prepare_runoff_input.py",
    "tools/configure_simulation.py",
    "tools/run_cama.py",
    "tools/parse_cama_output.py",
    "tools/calib_run.py",
]

PYTHON_IMPORTS = ["numpy", "netCDF4", "pandas", "xarray"]

OPTIONAL_DATA_DIRS = [
    ("KISSPATH_OBS", "Observation data"),
    ("KISSPATH_FORCING", "Forcing data"),
    ("KISSPATH_STATIC", "DEM data"),
    ("KISSPATH_STATIC", "Soil data"),
]


def add_check(checks, kind, subject, critical, status, fix=""):
    checks.append(
        {
            "kind": kind,
            "subject": subject,
            "critical": bool(critical),
            "status": status,
            "fix": fix,
        }
    )


def print_check(label, status, subject, fix=""):
    tag = "OK" if status == "pass" else "FAIL"
    print(f"  {tag:<5} {label}: {subject}")
    if status == "fail" and fix:
        print(f"        Fix: {fix}")


def check_file(checks, path, label, kind="data", critical=True, executable=False):
    subject = os.path.realpath(path) if os.path.exists(path) else path
    if not os.path.isfile(path):
        fix = f"Restore missing file. See {DIAGNOSTICS} for known recovery steps."
        add_check(checks, kind, subject, critical, "fail", fix)
        print_check(label, "fail", subject, fix)
        return False
    if executable and not os.access(path, os.X_OK):
        fix = f"chmod +x {path}; if that is not enough, rebuild CaMa-Flood from {CAMA_ROOT}/src."
        add_check(checks, kind, os.path.realpath(path), critical, "fail", fix)
        print_check(label, "fail", os.path.realpath(path), fix)
        return False
    add_check(checks, kind, os.path.realpath(path), critical, "pass")
    print_check(label, "pass", os.path.realpath(path))
    return True


def check_dir(checks, path, label, critical=True, non_empty=True):
    subject = os.path.realpath(path) if os.path.exists(path) else path
    if not os.path.isdir(path):
        fix = f"Restore missing directory. See {DIAGNOSTICS} for known recovery steps."
        add_check(checks, "data", subject, critical, "fail", fix)
        print_check(label, "fail", subject, fix)
        return False
    if non_empty and not os.listdir(path):
        fix = f"Populate {path}; see {DIAGNOSTICS} for expected CaMa-Flood data layout."
        add_check(checks, "data", os.path.realpath(path), critical, "fail", fix)
        print_check(label, "fail", os.path.realpath(path), fix)
        return False
    add_check(checks, "data", os.path.realpath(path), critical, "pass")
    print_check(label, "pass", os.path.realpath(path))
    return True


def check_binary_start(checks):
    subject = os.path.realpath(BINARY) if os.path.exists(BINARY) else BINARY
    if not os.path.isfile(BINARY) or not os.access(BINARY, os.X_OK):
        fix = f"Restore executable binary first: {BINARY}. See {DIAGNOSTICS}."
        add_check(checks, "run", subject, True, "fail", fix)
        print_check("CaMa-Flood binary startup", "fail", subject, fix)
        return

    try:
        result = subprocess.run(
            [BINARY],
            cwd="/tmp",
            capture_output=True,
            text=True,
            timeout=3,
        )
    except subprocess.TimeoutExpired:
        fix = f"Binary did not return from a no-input startup probe within 3s. Check {DIAGNOSTICS}."
        add_check(checks, "run", subject, True, "fail", fix)
        print_check("CaMa-Flood binary startup", "fail", subject, fix)
        return
    except OSError as exc:
        fix = f"Cannot execute binary ({exc}). Rebuild or repair dependencies; see {DIAGNOSTICS}."
        add_check(checks, "run", subject, True, "fail", fix)
        print_check("CaMa-Flood binary startup", "fail", subject, fix)
        return

    output = (result.stdout or "") + (result.stderr or "")
    loader_failures = [
        "error while loading shared libraries",
        "exec format error",
        "permission denied",
        "not found",
    ]
    if any(token in output.lower() for token in loader_failures):
        fix = f"Binary starts with loader/runtime failure. Rebuild CaMa-Flood or repair shared libraries; see {DIAGNOSTICS}."
        add_check(checks, "run", subject, True, "fail", fix)
        print_check("CaMa-Flood binary startup", "fail", subject, fix)
        return

    # With no input_cmf.nam in /tmp, this binary normally exits nonzero after the
    # Fortran runtime opens. That is enough to prove the executable starts.
    add_check(checks, "run", subject, True, "pass")
    print_check("CaMa-Flood binary startup", "pass", f"{subject} (returned {result.returncode})")


def check_import(checks, module):
    subject = f"{PYTHON_ENV} import {module}"
    if not os.path.isfile(PYTHON_ENV):
        fix = f"Restore HydroCraft Python interpreter at {PYTHON_ENV}; then install {module}."
        add_check(checks, "import", subject, True, "fail", fix)
        print_check(f"Python import {module}", "fail", subject, fix)
        return

    code = f"import {module}"
    result = subprocess.run(
        [PYTHON_ENV, "-c", code],
        cwd=KI_DIR,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode == 0:
        add_check(checks, "import", subject, True, "pass")
        print_check(f"Python import {module}", "pass", subject)
        return

    detail = (result.stderr or result.stdout or "").strip().splitlines()
    reason = detail[-1] if detail else f"exit code {result.returncode}"
    fix = f"Install/repair {module} in {PYTHON_ENV}. See {DIAGNOSTICS}. Last error: {reason}"
    add_check(checks, "import", subject, True, "fail", fix)
    print_check(f"Python import {module}", "fail", subject, fix)


def check_netcdf_read(checks):
    """Actually OPEN a NetCDF4 file with xarray -- importing xarray is not enough (dt_cama_014).

    Verified 2026-08-20 on this server: `import xarray` succeeds while xarray's DEFAULT
    'netcdf4' backend raises `OSError: [Errno -101] NetCDF: HDF error` on EVERY NETCDF4/HDF5
    file, including CaMa's own shipped e2o test forcing and CaMa's own o_*.nc output.
    `netCDF4.Dataset(path)` opens the same files fine, so nothing is corrupt -- the xarray
    backend is. Every KI tool that reads NetCDF (prepare_runoff_input.py, parse_cama_output.py,
    configure_simulation.py --grid_nc) therefore failed at stage 1 or 4 while this preflight
    reported all-green. The tools now fall back to 'h5netcdf'; this check reports WHICH engine
    works so a future breakage is visible at stage 0.
    """
    subject = f"{PYTHON_ENV} xarray open_dataset"
    probe = os.path.join(CAMA_ROOT, "inp", "test_15min_nc",
                         "e2o_ecmwf_wrr2_glob15_day_Runoff_2000.nc")
    if not os.path.isfile(probe):
        add_check(checks, "import", subject, False, "fail",
                  f"probe file missing: {probe}")
        print(f"  WARN  xarray NetCDF read: probe file {probe} not found (check skipped)")
        return

    code = (
        "import xarray as xr, json, sys\n"
        f"p = {probe!r}\n"
        "ok = []\n"
        "for e in (None, 'h5netcdf', 'netcdf4'):\n"
        "    try:\n"
        "        d = xr.open_dataset(p, engine=e); d.close(); ok.append(e or 'default')\n"
        "    except Exception:\n"
        "        pass\n"
        "print(json.dumps(ok))\n"
    )
    result = subprocess.run([PYTHON_ENV, "-c", code], cwd=KI_DIR,
                            capture_output=True, text=True, timeout=120)
    working = []
    if result.returncode == 0:
        try:
            working = json.loads((result.stdout or "[]").strip().splitlines()[-1])
        except Exception:                              # noqa: BLE001
            working = []

    if not working:
        fix = ("No xarray engine can open a NetCDF4 file. Install/repair h5netcdf in "
               f"{PYTHON_ENV} (`pip install h5netcdf`) -- see dt_cama_014 in {DIAGNOSTICS}.")
        add_check(checks, "import", subject, True, "fail", fix)
        print_check("xarray NetCDF read", "fail", subject, fix)
        return

    add_check(checks, "import", subject, True, "pass")
    print_check("xarray NetCDF read", "pass", f"working engines: {', '.join(working)}")
    if "default" not in working:
        print("  WARN  xarray's DEFAULT engine cannot open NetCDF4 here (dt_cama_014). KI tools fall "
              "back to h5netcdf via their open_nc() helper -- any NEW code must do the same.")


def check_optional_dir(checks, path, label):
    subject = os.path.realpath(path) if os.path.exists(path) else path
    if os.path.isdir(path):
        add_check(checks, "data", subject, False, "pass")
        print_check(label, "pass", subject)
        return
    fix = f"Only needed for workflows using {label.lower()}; create or mount {path} if required."
    add_check(checks, "data", subject, False, "fail", fix)
    print(f"  WARN  {label}: {subject} not found (may not be needed)")


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}, sort_keys=True))
    critical_failed = any(c["critical"] and c["status"] != "pass" for c in checks)
    sys.exit(1 if critical_failed else 0)


def main():
    checks = []

    print("=" * 60)
    print("  PREFLIGHT CHECK: CaMa-Flood v4.20")
    print("=" * 60)
    print()

    check_file(checks, BINARY, "CaMa-Flood binary", kind="binary", critical=True, executable=True)
    check_binary_start(checks)
    print()

    check_dir(checks, GLB_MAP, "CaMa global river map", critical=True)
    for filename in GLOBAL_MAP_FILES:
        check_file(
            checks,
            os.path.join(GLB_MAP, filename),
            f"Global map file {filename}",
            kind="data",
            critical=True,
        )
    check_file(checks, GPCC_CLIM, "Runoff climatology", kind="data", critical=True)
    print()

    for path in SETUP_BINARIES:
        check_file(
            checks,
            path,
            f"Map setup binary {os.path.basename(path)}",
            kind="binary",
            critical=True,
            executable=True,
        )
    print()

    for relpath in KI_TOOL_FILES:
        check_file(
            checks,
            os.path.join(KI_DIR, relpath),
            f"KI tool {relpath}",
            kind="data",
            critical=True,
            executable=False,
        )
    print()

    check_file(checks, PYTHON_ENV, "HydroCraft Python interpreter", kind="binary", critical=True, executable=True)
    for module in PYTHON_IMPORTS:
        check_import(checks, module)
    check_netcdf_read(checks)
    print()

    check_file(checks, DIAGNOSTICS, "Diagnostic triplets", kind="data", critical=True)
    print(f"  INFO  On failure, check diagnostics first: {DIAGNOSTICS}")
    print()

    for path, label in OPTIONAL_DATA_DIRS:
        check_optional_dir(checks, path, label)
    print()

    passed = sum(1 for check in checks if check["status"] == "pass")
    failed = len(checks) - passed
    critical_failed = [check for check in checks if check["critical"] and check["status"] != "pass"]
    print(f"  Results: {passed} passed, {failed} failed")
    if critical_failed:
        print("  STATUS: PREFLIGHT FAILED - fix critical issues before running")
        for check in critical_failed:
            print(f"  BLOCKER: {check['subject']}")
            print(f"           Fix: {check['fix']}")
    else:
        print("  STATUS: PREFLIGHT PASSED - safe to proceed with model execution")

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
