#!/usr/bin/env python3
"""Preflight check for the PyAEZ knowledge infrastructure."""

import json
import os
import subprocess
import sys
from pathlib import Path


MODEL_ID = "PyAEZ"
KI_DIR = Path(__file__).resolve().parent
MODEL_SCRIPT = KI_DIR / "tools" / "run_pyaez.py"
PYTHON = Path("KISSPATH_PYTHON_ENV/bin/python")
PYTHON_WITH_GDAL = Path("KISSPATH_PYTHON_ENV/bin/python_with_gdal")
SOURCE_REPO = KI_DIR.parent / "source" / "repo"
DIAGNOSTICS = KI_DIR / "diagnostics" / "triplets.yaml"


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}, sort_keys=True))
    failed_critical = [c for c in checks if c["status"] == "fail" and c.get("critical")]
    sys.exit(1 if failed_critical else 0)


def add_check(checks, kind, subject, critical, passed, fix="", detail=""):
    status = "pass" if passed else "fail"
    checks.append(
        {
            "kind": kind,
            "subject": str(subject),
            "critical": bool(critical),
            "status": status,
            "fix": "" if passed else fix,
            "detail": detail,
        }
    )
    label = "OK" if passed else ("FAIL" if critical else "WARN")
    print(f"  {label:<5} {kind}: {subject}")
    if detail:
        print(f"        {detail}")
    if not passed and fix:
        print(f"        Fix: {fix}")


def run_command(args, timeout=15, env=None):
    try:
        return subprocess.run(
            [str(a) for a in args],
            cwd=str(KI_DIR),
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
    except Exception as exc:
        class Result:
            returncode = 1
            stdout = ""
            stderr = repr(exc)

        return Result()


def runtime_env():
    env = os.environ.copy()
    source = str(SOURCE_REPO)
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = source if not existing else source + os.pathsep + existing
    return env


def check_executable_file(checks, path, label, critical=True):
    subject = Path(path).resolve(strict=False)
    if not Path(path).is_file():
        add_check(
            checks,
            "binary",
            subject,
            critical,
            False,
            f"Restore {path}; check {DIAGNOSTICS} for recovery.",
            label,
        )
        return False
    if not os.access(path, os.X_OK):
        add_check(
            checks,
            "binary",
            subject,
            critical,
            False,
            f"chmod +x {path}; then re-run preflight. See {DIAGNOSTICS}.",
            label,
        )
        return False
    add_check(checks, "binary", subject, critical, True, detail=label)
    return True


def check_file(checks, path, label, critical):
    subject = Path(path).resolve(strict=False)
    passed = Path(path).is_file()
    add_check(
        checks,
        "data",
        subject,
        critical,
        passed,
        f"Restore {path}; check {DIAGNOSTICS} for recovery.",
        label,
    )
    return passed


def check_dir(checks, path, label, critical):
    subject = Path(path).resolve(strict=False)
    passed = Path(path).is_dir()
    detail = label
    if passed:
        detail = f"{label}; {len(list(Path(path).iterdir()))} entries"
    add_check(
        checks,
        "data",
        subject,
        critical,
        passed,
        f"Restore {path}; check {DIAGNOSTICS} for recovery.",
        detail,
    )
    return passed


def check_python_import(checks, module, label, critical=True, use_gdal_wrapper=False):
    python = PYTHON_WITH_GDAL if use_gdal_wrapper else PYTHON
    code = f"import {module}; print('ok')"
    proc = run_command([python, "-c", code], env=runtime_env())
    stderr_tail = proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else ""
    passed = proc.returncode == 0
    fix = (
        f"Install/repair {module.split('.')[0]} for {python} with PYTHONPATH={SOURCE_REPO}; "
        f"check {DIAGNOSTICS} first for known remedies."
    )
    add_check(
        checks,
        "import",
        f"{python} imports {module}",
        critical,
        passed,
        fix,
        label if passed else f"{label}: {stderr_tail}",
    )
    return passed


def check_python_code(checks, code, subject, label, critical=True, use_gdal_wrapper=False):
    python = PYTHON_WITH_GDAL if use_gdal_wrapper else PYTHON
    proc = run_command([python, "-c", code], env=runtime_env())
    stderr_tail = proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else ""
    passed = proc.returncode == 0
    fix = f"Repair runtime dependencies for {python}; check {DIAGNOSTICS} for matching remedies."
    add_check(
        checks,
        "import",
        subject,
        critical,
        passed,
        fix,
        label if passed else f"{label}: {stderr_tail}",
    )
    return passed


def check_tool_help(checks):
    proc = run_command(
        [
            PYTHON_WITH_GDAL,
            MODEL_SCRIPT,
            "--help",
        ],
        env=runtime_env(),
    )
    output = (proc.stdout + proc.stderr).strip()
    passed = proc.returncode == 0 and "Run PyAEZ pipeline" in output
    add_check(
        checks,
        "run",
        f"{PYTHON_WITH_GDAL} {MODEL_SCRIPT} --help",
        True,
        passed,
        f"Make {MODEL_SCRIPT} start under {PYTHON_WITH_GDAL}; check {DIAGNOSTICS}.",
        "cheap startup/help invocation",
    )
    return passed


def main():
    checks = []
    print("=" * 60)
    print("PREFLIGHT: PyAEZ")
    print("=" * 60)
    print(f"KI directory: {KI_DIR}")
    print(f"Runtime PYTHONPATH prefix: {SOURCE_REPO}")
    print()

    check_executable_file(checks, PYTHON, "HydroCraft Python interpreter", critical=True)
    check_executable_file(checks, PYTHON_WITH_GDAL, "HydroCraft Python wrapper for GDAL TLS", critical=True)
    check_executable_file(checks, MODEL_SCRIPT, "manifest binary: PyAEZ pipeline driver", critical=True)

    for relpath in [
        "SKILL.md",
        "knowledge_infrastructure.yaml",
        "dag.yaml",
        "tools/convert_forcing.py",
        "tools/convert_soil.py",
        "tools/parse_output.py",
    ]:
        check_file(checks, KI_DIR / relpath, relpath, critical=True)

    check_file(checks, DIAGNOSTICS, "diagnostics/triplets.yaml for recovery", critical=False)
    check_dir(checks, SOURCE_REPO / "pyaez", "PyAEZ source package", critical=True)

    check_python_import(checks, "numpy", "NumPy array runtime", critical=True)
    check_python_import(checks, "pandas", "Pandas Excel/table runtime", critical=True)
    check_python_import(checks, "scipy", "SciPy interpolation/runtime", critical=True)
    check_python_import(checks, "numba", "Numba JIT runtime", critical=True)
    check_python_import(checks, "pyaez", "PyAEZ package from current source layout", critical=True, use_gdal_wrapper=True)
    check_python_code(
        checks,
        "from osgeo import gdal; print(gdal.VersionInfo())",
        f"{PYTHON_WITH_GDAL} imports osgeo.gdal",
        "GDAL raster runtime",
        critical=True,
        use_gdal_wrapper=True,
    )
    check_python_code(
        checks,
        "from pyaez import ClimateRegime, CropSimulation, UtilitiesCalc; print('ok')",
        f"{PYTHON_WITH_GDAL} imports core PyAEZ modules",
        "core PyAEZ modules",
        critical=True,
        use_gdal_wrapper=True,
    )

    check_tool_help(checks)

    print()
    passed = sum(1 for c in checks if c["status"] == "pass")
    failed = sum(1 for c in checks if c["status"] == "fail")
    print(f"Results: {passed} passed, {failed} failed")
    if failed:
        print(f"Blockers found. Check {DIAGNOSTICS} before attempting workarounds.")
    else:
        print("Preflight passed.")
    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
