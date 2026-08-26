#!/usr/bin/env python3
"""Preflight check for the ForeFire knowledge infrastructure."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


MODEL_ID = "ForeFire"
KI_DIR = Path(__file__).resolve().parent
PYTHON_ENV = Path("KISSPATH_PYTHON_ENV/bin/python")
FOREFIRE_BINARY = Path(
    "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/ForeFire/source/repo/bin/forefire"
)
TRIPLETS = KI_DIR / "diagnostics" / "triplets.yaml"
NETCDF_CXX_SONAME = "libnetcdf-cxx4.so.1"

CHECKS = []


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}, sort_keys=True))
    sys.exit(0 if all(c["status"] == "pass" or not c.get("critical") for c in checks) else 1)


def add_check(kind, subject, critical, ok, fix):
    status = "pass" if ok else "fail"
    CHECKS.append(
        {
            "kind": kind,
            "subject": str(subject),
            "critical": bool(critical),
            "status": status,
            "fix": "" if ok else fix,
        }
    )
    label = "OK" if ok else "FAIL"
    print(f"  {label:<5} {kind}: {subject}")
    if not ok:
        print(f"        Fix: {fix}")
    return ok


def check_file(path, label, critical=True, executable=False):
    path = Path(path)
    subject = path.resolve() if path.exists() else path
    if not path.is_file():
        return add_check(
            "data",
            subject,
            critical,
            False,
            f"Restore {label}; consult {TRIPLETS} for recovery.",
        )
    if executable and not os.access(path, os.X_OK):
        return add_check(
            "binary" if "binary" in label.lower() else "data",
            subject,
            critical,
            False,
            f"Make {label} executable with: chmod +x {path}; consult {TRIPLETS}.",
        )
    return add_check("binary" if executable else "data", subject, critical, True, "")


def check_dir(path, label, critical=True, non_empty=True):
    path = Path(path)
    subject = path.resolve() if path.exists() else path
    if not path.is_dir():
        return add_check(
            "data",
            subject,
            critical,
            False,
            f"Restore {label}; consult {TRIPLETS} for recovery.",
        )
    if non_empty and not any(path.iterdir()):
        return add_check(
            "data",
            subject,
            critical,
            False,
            f"Populate {label}; consult {TRIPLETS} for expected inputs.",
        )
    return add_check("data", subject, critical, True, "")


def netcdf_library_dir(binary):
    env = os.environ
    bin_dir = Path(binary).resolve().parent
    candidates = []
    if env.get("NETCDF_HOME"):
        candidates.append(Path(env["NETCDF_HOME"]) / "lib")
    candidates.append(bin_dir.parent / "lib")
    candidates.extend([Path.home() / ".local/lib", Path("/usr/local/lib"), Path("/usr/lib")])
    for directory in candidates:
        if (directory / NETCDF_CXX_SONAME).is_file():
            return directory
    return None


def runtime_env(binary):
    env = dict(os.environ)
    libdir = netcdf_library_dir(binary)
    if libdir:
        existing = [p for p in env.get("LD_LIBRARY_PATH", "").split(os.pathsep) if p]
        if str(libdir) not in existing:
            env["LD_LIBRARY_PATH"] = os.pathsep.join([str(libdir)] + existing)
    return env


def check_netcdf_library(binary):
    libdir = netcdf_library_dir(binary)
    if libdir:
        return add_check("data", (libdir / NETCDF_CXX_SONAME).resolve(), True, True, "")
    return add_check(
        "data",
        NETCDF_CXX_SONAME,
        True,
        False,
        f"Install or expose {NETCDF_CXX_SONAME}; see {TRIPLETS} dt_015 and set LD_LIBRARY_PATH.",
    )


def check_binary_starts(binary):
    binary = Path(binary)
    if not binary.is_file() or not os.access(binary, os.X_OK):
        return
    subject = binary.resolve()
    try:
        result = subprocess.run(
            [str(subject), "-v"],
            cwd=str(KI_DIR),
            env=runtime_env(subject),
            capture_output=True,
            text=True,
            timeout=5,
        )
    except subprocess.TimeoutExpired:
        add_check(
            "run",
            subject,
            True,
            False,
            f"ForeFire -v timed out. Rebuild the binary and check {TRIPLETS}.",
        )
        return
    except OSError as exc:
        add_check(
            "run",
            subject,
            True,
            False,
            f"ForeFire failed to start: {exc}. Check {TRIPLETS}, especially dt_015.",
        )
        return

    output = (result.stdout + result.stderr).strip()
    ok = result.returncode == 0 and bool(output)
    add_check(
        "run",
        subject,
        True,
        ok,
        f"ForeFire -v failed with rc={result.returncode}: {output[-300:]}. Check {TRIPLETS}.",
    )


def check_import(module, critical=True):
    if not PYTHON_ENV.is_file():
        add_check(
            "import",
            f"{module} via {PYTHON_ENV}",
            critical,
            False,
            f"Restore HydroCraft Python interpreter at {PYTHON_ENV}; consult {TRIPLETS}.",
        )
        return
    code = f"import {module}"
    result = subprocess.run(
        [str(PYTHON_ENV), "-c", code],
        cwd=str(KI_DIR),
        capture_output=True,
        text=True,
        timeout=10,
    )
    ok = result.returncode == 0
    detail = (result.stderr or result.stdout).strip()
    add_check(
        "import",
        f"{module} via {PYTHON_ENV}",
        critical,
        ok,
        f"Install/fix Python dependency {module} in {PYTHON_ENV}: {detail}. See {TRIPLETS}.",
    )


def check_import_any(modules, subject, critical=True):
    if not PYTHON_ENV.is_file():
        add_check(
            "import",
            f"{subject} via {PYTHON_ENV}",
            critical,
            False,
            f"Restore HydroCraft Python interpreter at {PYTHON_ENV}; consult {TRIPLETS}.",
        )
        return
    tests = "\n".join(
        [
            "import importlib, sys",
            f"mods = {modules!r}",
            "errors = []",
            "for m in mods:",
            "    try:",
            "        importlib.import_module(m)",
            "        sys.exit(0)",
            "    except Exception as e:",
            "        errors.append(f'{m}: {type(e).__name__}: {e}')",
            "print('; '.join(errors))",
            "sys.exit(1)",
        ]
    )
    result = subprocess.run(
        [str(PYTHON_ENV), "-c", tests],
        cwd=str(KI_DIR),
        capture_output=True,
        text=True,
        timeout=10,
    )
    ok = result.returncode == 0
    detail = (result.stderr or result.stdout).strip()
    add_check(
        "import",
        f"{subject} via {PYTHON_ENV}",
        critical,
        ok,
        f"Install one of {modules} in {PYTHON_ENV}: {detail}. See {TRIPLETS}.",
    )


def main():
    print(f"{' PREFLIGHT: ForeFire ':=^60}")
    print(f"KI directory: {KI_DIR}")
    print()

    check_file(KI_DIR / "SKILL.md", "KI skill document", critical=True)
    check_file(KI_DIR / "knowledge_infrastructure.yaml", "KI manifest", critical=True)
    check_file(KI_DIR / "dag.yaml", "KI DAG", critical=True)
    check_file(TRIPLETS, "diagnostic triplets", critical=True)
    check_dir(KI_DIR / "tools", "KI tools directory", critical=True)

    for tool in [
        "convert_landscape_to_nc.py",
        "convert_fuel_params.py",
        "prepare_fire_case.py",
        "run_forefire.py",
        "parse_forefire_output.py",
        "validate_spread.py",
    ]:
        check_file(KI_DIR / "tools" / tool, f"tool {tool}", critical=True)

    binary = FOREFIRE_BINARY
    if not binary.is_file():
        resolved = shutil.which("forefire")
        if resolved:
            binary = Path(resolved)
    check_file(binary, "ForeFire binary", critical=True, executable=True)
    check_netcdf_library(binary)
    check_binary_starts(binary)

    check_file(PYTHON_ENV, "HydroCraft Python interpreter", critical=True, executable=True)
    for module in [
        "numpy",
        "netCDF4",
        "pyproj",
        "scipy",
        "fiona",
        "shapely",
        "ki_tools_common.load_forcing",
        "lxml",
        "matplotlib",
    ]:
        check_import(module, critical=True)
    check_import_any(["rasterio", "osgeo.gdal"], "raster reader (rasterio or GDAL)", critical=True)

    check_dir("KISSPATH_DATA/MERIT_DEM", "MERIT DEM data directory", critical=True)
    check_dir("KISSPATH_DATA/vegetation/GLCFCS30", "GLC_FCS30 vegetation data directory", critical=True)

    failed = [c for c in CHECKS if c["status"] == "fail"]
    print()
    print(f"Results: {len(CHECKS) - len(failed)} passed, {len(failed)} failed")
    if failed:
        print(f"Blockers found. Start recovery at {TRIPLETS}.")
    else:
        print("Preflight passed.")

    emit_report(MODEL_ID, CHECKS)


if __name__ == "__main__":
    main()
