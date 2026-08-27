#!/usr/bin/env python3
"""Contract-compliant preflight check for the SWAN KI."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


MODEL_ID = "SWAN"
KI_DIR = Path(__file__).resolve().parent
HYDRO_PYTHON = Path("KISSPATH_PYTHON_ENV/bin/python")
TRIPLETS = KI_DIR / "diagnostics" / "triplets.yaml"

CHECKS = []


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


def run_cmd(argv, timeout=20, cwd=None):
    try:
        return subprocess.run(
            [str(a) for a in argv],
            cwd=str(cwd or KI_DIR),
            text=True,
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        proc = subprocess.CompletedProcess(argv, 124, exc.stdout or "", exc.stderr or "")
        proc.timed_out = True
        return proc
    except OSError as exc:
        proc = subprocess.CompletedProcess(argv, 127, "", str(exc))
        proc.os_error = True
        return proc


def check_file(path, label, critical=True, executable=False, nonempty=False):
    path = Path(path)
    ok = path.is_file()
    if ok and executable:
        ok = os.access(path, os.X_OK)
    if ok and nonempty:
        ok = path.stat().st_size > 0

    if ok:
        subject = path.resolve()
        fix = ""
    elif executable:
        subject = path
        fix = f"restore executable {path} or update this KI; then check {TRIPLETS}"
    else:
        subject = path
        fix = f"restore required KI file {path}; see {TRIPLETS}"
    add_check("data" if not executable else "binary", subject, critical, ok, fix)
    return ok


def check_dir(path, label, critical=True, nonempty=False):
    path = Path(path)
    ok = path.is_dir() and (not nonempty or any(path.iterdir()))
    fix = f"restore required KI directory {path}; see {TRIPLETS}"
    add_check("data", path.resolve() if path.exists() else path, critical, ok, fix)
    return ok


def check_python_executable():
    if not check_file(HYDRO_PYTHON, "HydroCraft Python", critical=True, executable=True):
        return False

    real = Path(os.path.realpath(HYDRO_PYTHON))
    proc = run_cmd([HYDRO_PYTHON, "-c", "import sys; print(sys.version_info[:2])"], timeout=10)
    ok = proc.returncode == 0
    fix = (
        f"{HYDRO_PYTHON} must start successfully; repair the HydroCraft python_env "
        f"and check {TRIPLETS}"
    )
    add_check("run", real, True, ok, fix)
    return ok


def check_import(module, critical=True):
    code = f"import {module}; print(getattr({module.split('.')[0]}, '__file__', 'built-in'))"
    proc = run_cmd([HYDRO_PYTHON, "-c", code], timeout=15)
    ok = proc.returncode == 0
    fix = (
        f"install or repair Python dependency {module!r} in {HYDRO_PYTHON.parent}; "
        f"see {TRIPLETS}"
    )
    add_check("import", module, critical, ok, fix)
    return ok


def check_tool_import(tool_path):
    module = "tools." + Path(tool_path).stem
    proc = run_cmd(
        [
            HYDRO_PYTHON,
            "-c",
            "import importlib; import sys; "
            f"sys.path.insert(0, {str(KI_DIR)!r}); "
            f"importlib.import_module({module!r})",
        ],
        timeout=20,
    )
    ok = proc.returncode == 0
    fix = f"repair import failure in {tool_path}; see {TRIPLETS}"
    add_check("import", module, True, ok, fix)
    return ok


def check_optional_swan_binary():
    found = shutil.which("swan.exe") or shutil.which("swanrun") or shutil.which("swan")
    if not found:
        add_check(
            "binary",
            "SWAN executable in PATH",
            False,
            False,
            f"install SWAN binary or pass --swan-exe to tools/run_swan.py; see {TRIPLETS}",
        )
        return None

    real = Path(os.path.realpath(found))
    ok = os.access(real, os.X_OK)
    add_check(
        "binary",
        real,
        False,
        ok,
        f"chmod +x {real} or install a working SWAN executable; see {TRIPLETS}",
    )
    if ok:
        proc = run_cmd([real], timeout=5)
        starts = proc.returncode in (0, 1, 2) or bool((proc.stdout or proc.stderr).strip())
        add_check(
            "run",
            real,
            False,
            starts,
            f"{real} did not start cheaply; verify the SWAN installation; see {TRIPLETS}",
        )
    return real


def check_pyswan_smoke():
    with tempfile.TemporaryDirectory(prefix="swan_preflight_") as tmp:
        proc = run_cmd(
            [
                HYDRO_PYTHON,
                "tools/run_swan.py",
                "pyswan",
                "--mode",
                "generate_tpar",
                "--output-dir",
                tmp,
            ],
            timeout=30,
        )
        out_file = Path(tmp) / "boundary.tpar"
        ok = proc.returncode == 0 and out_file.is_file() and out_file.stat().st_size > 0
    fix = (
        "PySWaN smoke run failed; run the same command manually, then check "
        f"{TRIPLETS} for matching import/I/O remedies"
    )
    add_check("run", "tools/run_swan.py pyswan --mode generate_tpar", True, ok, fix)
    return ok


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}, sort_keys=True))
    failed_critical = any(c["status"] != "pass" and c.get("critical") for c in checks)
    sys.exit(1 if failed_critical else 0)


def main():
    print(f"{' PREFLIGHT: SWAN ':=^60}")
    print(f"KI: {KI_DIR}")
    print(f"Diagnostics: {TRIPLETS}")
    print()

    check_python_executable()

    for module in ("numpy", "scipy", "pyswan", "pyswan.swan", "pyswan.oceanwaves"):
        check_import(module, critical=True)

    required_files = [
        "SKILL.md",
        "knowledge_infrastructure.yaml",
        "dag.yaml",
        "docs/format_spec.yaml",
        "diagnostics/triplets.yaml",
        "tools/run_swan.py",
        "tools/convert_bathymetry.py",
        "tools/convert_boundary_spectra.py",
        "tools/convert_wind_forcing.py",
        "tools/fetch_gridded_wind.py",
        "tools/parse_swan_output.py",
        "tools/read_ndbc_buoy.py",
    ]
    for rel in required_files:
        check_file(KI_DIR / rel, rel, critical=True, nonempty=True)

    check_dir(KI_DIR / "tools", "tools", critical=True, nonempty=True)
    check_dir(KI_DIR / "docs", "docs", critical=True, nonempty=True)

    for rel in required_files:
        if rel.startswith("tools/"):
            check_tool_import(rel)

    check_optional_swan_binary()
    check_pyswan_smoke()

    if not any(c.get("critical") for c in CHECKS):
        add_check("run", "preflight critical-check coverage", True, False, f"add at least one critical check; see {TRIPLETS}")

    failures = [c for c in CHECKS if c["status"] != "pass"]
    critical_failures = [c for c in failures if c.get("critical")]
    print()
    print(f"Results: {len(CHECKS) - len(failures)} passed, {len(failures)} failed")
    if critical_failures:
        print("STATUS: PREFLIGHT FAILED")
    else:
        print("STATUS: PREFLIGHT PASSED")
    emit_report(MODEL_ID, CHECKS)


if __name__ == "__main__":
    main()
