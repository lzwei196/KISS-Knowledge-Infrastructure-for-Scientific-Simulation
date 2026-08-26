#!/usr/bin/env python3
"""Preflight check for the CREST KI under the KDT report contract."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


MODEL_ID = "CREST"
KI_ROOT = Path(__file__).resolve().parent
HYDROCRAFT_PYTHON = Path("KISSPATH_PYTHON_ENV/bin/python")
DIAGNOSTICS = KI_ROOT / "diagnostics" / "triplets.yaml"


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}, sort_keys=True))
    sys.exit(0 if all(c["status"] == "pass" or not c.get("critical") for c in checks) else 1)


def add_check(checks, kind, subject, critical, status, fix=""):
    check = {
        "kind": kind,
        "subject": str(subject),
        "critical": bool(critical),
        "status": status,
        "fix": fix if status == "fail" else "",
    }
    checks.append(check)
    label = "OK" if status == "pass" else ("FAIL" if critical else "WARN")
    print(f"  {label:<5} {kind}: {subject}")
    if status == "fail" and fix:
        print(f"        Fix: {fix}")
    return status == "pass"


def check_file(checks, path, label, *, critical=True, executable=False, kind="data"):
    path = Path(path)
    subject = path
    if path.exists():
        try:
            subject = path.resolve(strict=True)
        except OSError:
            subject = path.absolute()
    if not path.is_file():
        return add_check(
            checks,
            kind,
            subject,
            critical,
            "fail",
            f"Restore {label} at {path}. Check {DIAGNOSTICS} for recovery steps.",
        )
    if executable and not os.access(path, os.X_OK):
        return add_check(
            checks,
            kind,
            subject,
            critical,
            "fail",
            f"Run chmod +x {path}, or rebuild EF5. Check {DIAGNOSTICS}.",
        )
    return add_check(checks, kind, subject, critical, "pass")


def check_dir(checks, path, label, *, critical=True):
    path = Path(path)
    if path.is_dir() and any(path.iterdir()):
        return add_check(checks, "data", path.resolve(), critical, "pass")
    if path.is_dir():
        return add_check(
            checks,
            "data",
            path.resolve(),
            critical,
            "fail",
            f"Populate {label} at {path}. Check {DIAGNOSTICS}.",
        )
    return add_check(
        checks,
        "data",
        path,
        critical,
        "fail",
        f"Restore {label} at {path}. Check {DIAGNOSTICS}.",
    )


def run_python_snippet(code, timeout=10):
    if not HYDROCRAFT_PYTHON.is_file():
        return None, "", f"HydroCraft Python not found: {HYDROCRAFT_PYTHON}"
    try:
        result = subprocess.run(
            [str(HYDROCRAFT_PYTHON), "-c", code],
            cwd=str(KI_ROOT),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"timed out after {timeout}s"


def check_import(checks, module, *, critical=True):
    rc, stdout, stderr = run_python_snippet(f"import {module}; print('ok')")
    subject = f"{HYDROCRAFT_PYTHON}:import:{module}"
    if rc == 0:
        return add_check(checks, "import", subject, critical, "pass")
    err = (stderr or stdout or "import failed").strip().splitlines()[-1]
    return add_check(
        checks,
        "import",
        subject,
        critical,
        "fail",
        f"Install or repair Python module {module} in {HYDROCRAFT_PYTHON}; last error: {err}. Check {DIAGNOSTICS}.",
    )


def check_py_compile(checks, paths):
    quoted = ", ".join(repr(str(p)) for p in paths)
    code = "import py_compile; [py_compile.compile(p, doraise=True) for p in [" + quoted + "]]"
    rc, stdout, stderr = run_python_snippet(code, timeout=20)
    subject = f"{HYDROCRAFT_PYTHON}:py_compile:tools"
    if rc == 0:
        return add_check(checks, "run", subject, True, "pass")
    err = (stderr or stdout or "py_compile failed").strip().splitlines()[-1]
    return add_check(
        checks,
        "run",
        subject,
        True,
        "fail",
        f"Fix Python syntax/import-time compile error in KI tools; last error: {err}. Check {DIAGNOSTICS}.",
    )


def binary_candidates():
    env_value = os.environ.get("CREST_EF5_BINARY") or os.environ.get("EF5_BINARY")
    if env_value:
        yield Path(env_value)
    yield KI_ROOT / "bin" / "ef5"
    yield KI_ROOT / "source" / "repo" / "bin" / "ef5"
    yield KI_ROOT / "source" / "repo" / "build" / "ef5"
    yield Path("KISSPATH_BINARIES/EF5/bin/ef5")
    yield Path("KISSPATH_BINARIES/ef5/bin/ef5")
    yield Path("KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/CREST/source/repo/build/ef5")


def find_ef5_binary():
    seen = set()
    for candidate in binary_candidates():
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        if candidate.is_file():
            return candidate
    return None


def check_binary_start(checks, binary):
    real_binary = Path(binary).resolve(strict=True)
    try:
        result = subprocess.run(
            [str(real_binary), "--help"],
            cwd=str(KI_ROOT),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5,
        )
    except subprocess.TimeoutExpired:
        return add_check(
            checks,
            "run",
            real_binary,
            True,
            "fail",
            f"EF5 did not finish a cheap startup check within 5s. Check {DIAGNOSTICS}.",
        )
    except OSError as exc:
        return add_check(
            checks,
            "run",
            real_binary,
            True,
            "fail",
            f"EF5 could not be started: {exc}. Rebuild or relink the executable; check {DIAGNOSTICS}.",
        )

    output = (result.stdout or "") + (result.stderr or "")
    started = "Ensemble Framework For Flash Flood Forecasting" in output or "Version 1.2.3" in output
    if started:
        return add_check(checks, "run", real_binary, True, "pass")
    return add_check(
        checks,
        "run",
        real_binary,
        True,
        "fail",
        f"EF5 executed but did not print its startup banner; rc={result.returncode}. Check {DIAGNOSTICS}.",
    )


def main():
    checks = []
    print("=" * 60)
    print("  PREFLIGHT CHECK: CREST / EF5")
    print("=" * 60)

    check_file(checks, HYDROCRAFT_PYTHON, "HydroCraft Python interpreter", critical=True, executable=True, kind="binary")

    ef5_binary = find_ef5_binary()
    if ef5_binary is None:
        add_check(
            checks,
            "binary",
            KI_ROOT / "bin" / "ef5",
            True,
            "fail",
            f"Build EF5 and expose it as {KI_ROOT / 'bin' / 'ef5'} or set EF5_BINARY. Check {DIAGNOSTICS}.",
        )
    else:
        check_file(checks, ef5_binary, "CREST/EF5 executable", critical=True, executable=True, kind="binary")
        check_binary_start(checks, ef5_binary)

    check_dir(checks, KI_ROOT / "tools", "KI tools directory", critical=True)
    tool_files = [
        KI_ROOT / "tools" / "prepare_basic_grids.py",
        KI_ROOT / "tools" / "convert_forcing_to_ef5.py",
        KI_ROOT / "tools" / "convert_params_to_ef5.py",
        KI_ROOT / "tools" / "run_ef5.py",
        KI_ROOT / "tools" / "parse_ef5_output.py",
    ]
    for tool in tool_files:
        check_file(checks, tool, tool.name, critical=True)
    check_py_compile(checks, tool_files)

    for module in ("numpy", "rasterio", "whitebox", "netCDF4"):
        check_import(checks, module, critical=True)
    check_import(checks, "matplotlib", critical=False)
    check_import(checks, "osgeo", critical=False)

    check_file(checks, KI_ROOT / "SKILL.md", "SKILL.md", critical=True)
    check_file(checks, KI_ROOT / "knowledge_infrastructure.yaml", "KI manifest", critical=True)
    check_file(checks, KI_ROOT / "dag.yaml", "DAG", critical=True)
    check_file(checks, DIAGNOSTICS, "diagnostic triplets", critical=True)
    check_file(checks, KI_ROOT / "docs" / "format_spec.yaml", "format specification", critical=False)

    passed = sum(1 for c in checks if c["status"] == "pass")
    failed = len(checks) - passed
    print(f"  Results: {passed} passed, {failed} failed")
    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
