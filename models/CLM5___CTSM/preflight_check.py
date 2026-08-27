#!/usr/bin/env python3
"""Preflight check for the CLM5 / CTSM Knowledge Infrastructure.

This script is executed by the KDT gate before model execution. It performs
real environment checks and always ends with a PREFLIGHT_REPORT= JSON line.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


MODEL_ID = "CLM5_CTSM"
KI_DIR = Path(__file__).resolve().parent
DIAGNOSTICS = KI_DIR / "diagnostics" / "triplets.yaml"
HYDROCRAFT_PYTHON = Path("KISSPATH_PYTHON_ENV/bin/python")

# This is the executable path projected into knowledge_infrastructure.yaml from
# the models DB. Keep a report subject with its realpath for gate drift checks.
MANIFEST_BINARY = Path("KISSPATH_HOME/cesm/scratch/test_clm5/bld/cesm.exe")

# SKILL.md section 14b documents this as the validated execution route.
CESM_ROOT = Path("KISSPATH_HOME/cesm/src/cesm-2.2.2")
CREATE_NEWCASE = CESM_ROOT / "cime" / "scripts" / "create_newcase"
DIN_LOC_ROOT = Path("KISSPATH_HOME/cesm/inputdata")
DIN_LOC_ROOT_CLMFORC = Path("KISSPATH_HOME/cesm/inputdata/atm/datm7")


def fix_hint(message):
    return f"{message}; consult {DIAGNOSTICS}"


def add_check(checks, kind, subject, critical, ok, fix=""):
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
    if not ok and fix:
        print(f"        Fix: {fix}")


def command_result(cmd, timeout=10, cwd=None):
    try:
        return subprocess.run(
            [str(part) for part in cmd],
            cwd=str(cwd) if cwd else None,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        return exc
    except OSError as exc:
        return exc


def check_file(checks, path, label, critical=True, executable=False):
    path = Path(path)
    ok = path.is_file() and (not executable or os.access(path, os.X_OK))
    fix = f"restore {label} at {path}"
    if executable:
        fix = f"restore executable {label} at {path} or run chmod +x {path}"
    add_check(checks, "data" if not executable else "binary", path, critical, ok, fix_hint(fix))
    return ok


def check_dir(checks, path, label, critical=True, non_empty=False):
    path = Path(path)
    ok = path.is_dir() and (not non_empty or any(path.iterdir()))
    requirement = "non-empty directory" if non_empty else "directory"
    add_check(
        checks,
        "data",
        path,
        critical,
        ok,
        fix_hint(f"restore {label} {requirement} at {path}"),
    )
    return ok


def check_program_on_path(checks, names, label, critical=True):
    found = next((shutil.which(name) for name in names if shutil.which(name)), None)
    subject = found or "/".join(names)
    add_check(
        checks,
        "binary",
        subject,
        critical,
        bool(found),
        fix_hint(f"install {label} or make one of {', '.join(names)} visible on PATH"),
    )
    return bool(found)


def check_python_import(checks, module, critical=True):
    if not HYDROCRAFT_PYTHON.is_file():
        add_check(
            checks,
            "import",
            f"{HYDROCRAFT_PYTHON} import {module}",
            critical,
            False,
            fix_hint(f"restore HydroCraft Python interpreter at {HYDROCRAFT_PYTHON}"),
        )
        return False

    result = command_result(
        [HYDROCRAFT_PYTHON, "-c", f"import {module}"],
        timeout=20,
        cwd=KI_DIR,
    )
    ok = isinstance(result, subprocess.CompletedProcess) and result.returncode == 0
    add_check(
        checks,
        "import",
        f"{HYDROCRAFT_PYTHON} import {module}",
        critical,
        ok,
        fix_hint(f"install Python package '{module.split('.')[0]}' in {HYDROCRAFT_PYTHON}"),
    )
    return ok


def check_py_compile(checks, script, critical=True):
    result = command_result([HYDROCRAFT_PYTHON, "-m", "py_compile", script], timeout=20, cwd=KI_DIR)
    ok = isinstance(result, subprocess.CompletedProcess) and result.returncode == 0
    add_check(
        checks,
        "import",
        Path(script),
        critical,
        ok,
        fix_hint(f"repair Python syntax/import-time dependencies for {script}"),
    )
    return ok


def check_ldd(checks, binary, critical=True):
    result = command_result(["ldd", binary], timeout=20, cwd=KI_DIR)
    ok = (
        isinstance(result, subprocess.CompletedProcess)
        and result.returncode == 0
        and "not found" not in (result.stdout + result.stderr)
    )
    add_check(
        checks,
        "binary",
        f"ldd {Path(binary).resolve()}",
        critical,
        ok,
        fix_hint(f"restore shared-library dependencies for {binary}"),
    )
    return ok


def check_binary_starts(checks, binary, critical=True):
    real_binary = Path(binary).resolve()
    result = command_result([real_binary, "--help"], timeout=5, cwd=KI_DIR)
    output = ""
    if isinstance(result, subprocess.CompletedProcess):
        output = (result.stdout or "") + (result.stderr or "")
        # A CLM/CESM executable has no CLI help. Reaching the Fortran driver and
        # failing on missing drv_in proves that the executable starts and links.
        ok = result.returncode == 0 or "Cannot open file 'drv_in'" in output
    elif isinstance(result, subprocess.TimeoutExpired):
        ok = False
    else:
        ok = False
    add_check(
        checks,
        "run",
        real_binary,
        critical,
        ok,
        fix_hint("rebuild the model executable; if it aborts during real CIME initialization, see dt_022"),
    )
    return ok


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}, sort_keys=True))
    critical_failed = any(c["critical"] and c["status"] != "pass" for c in checks)
    sys.exit(1 if critical_failed else 0)


def main():
    checks = []
    print("=" * 60)
    print(f"  PREFLIGHT CHECK: {MODEL_ID}")
    print("=" * 60)

    check_file(checks, KI_DIR / "SKILL.md", "KI skill")
    check_file(checks, KI_DIR / "knowledge_infrastructure.yaml", "KI manifest")
    check_file(checks, KI_DIR / "dag.yaml", "DAG")
    check_file(checks, DIAGNOSTICS, "diagnostic triplets")
    check_file(checks, KI_DIR / "docs" / "format_spec.yaml", "I/O format spec")

    check_dir(checks, KI_DIR / "tools", "KI tools", non_empty=True)
    for script in [
        "tools/convert_forcing_to_clm.py",
        "tools/convert_soil_params.py",
        "tools/make_site_dataset.py",
        "tools/parse_clm_output.py",
        "tools/run_clm.py",
    ]:
        check_file(checks, KI_DIR / script, script)
        check_py_compile(checks, script)

    manifest_realpath = MANIFEST_BINARY.resolve()
    check_file(checks, manifest_realpath, "manifest-pinned CLM5/CTSM executable", executable=True)
    if manifest_realpath.is_file() and os.access(manifest_realpath, os.X_OK):
        check_ldd(checks, manifest_realpath)
        check_binary_starts(checks, manifest_realpath)

    check_dir(checks, CESM_ROOT, "validated CESM 2.2.2 root")
    check_file(checks, CREATE_NEWCASE, "CIME create_newcase", executable=True)
    check_dir(checks, DIN_LOC_ROOT, "CESM inputdata", non_empty=True)
    check_dir(checks, DIN_LOC_ROOT_CLMFORC, "DATM forcing inputdata", non_empty=True)

    check_program_on_path(checks, ["gfortran", "ifort", "nvfortran"], "Fortran compiler")
    check_program_on_path(checks, ["mpirun", "mpiexec"], "MPI launcher")
    check_program_on_path(checks, ["nf-config", "nc-config"], "NetCDF config")

    for module in ["numpy", "pandas", "xarray", "netCDF4", "matplotlib", "yaml", "ki_tools_common"]:
        check_python_import(checks, module)

    failures = [c for c in checks if c["status"] != "pass"]
    print()
    print(f"  Results: {len(checks) - len(failures)} passed, {len(failures)} failed")
    if failures:
        print(f"  STATUS: PREFLIGHT FAILED - fixes above point to {DIAGNOSTICS}")
    else:
        print("  STATUS: PREFLIGHT PASSED - safe to proceed with the documented CIME route")

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
