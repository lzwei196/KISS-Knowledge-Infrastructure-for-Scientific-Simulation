#!/usr/bin/env python3
"""Preflight check for the MOSART knowledge infrastructure."""

import json
import os
import subprocess
import sys
from pathlib import Path


MODEL_ID = "MOSART"
KI_DIR = Path(__file__).resolve().parent
DIAGNOSTICS = KI_DIR / "diagnostics" / "triplets.yaml"

# Durable MOSART environment documented in SKILL.md. Older _work/MOSART/venv
# paths are dissection scratch space and must not be used by the gate.
MOSART_PYTHON = Path("KISSPATH_KI_ROOT/MOSART/venv/bin/python")

REQUIRED_KI_FILES = [
    KI_DIR / "SKILL.md",
    KI_DIR / "knowledge_infrastructure.yaml",
    KI_DIR / "dag.yaml",
    DIAGNOSTICS,
]

REQUIRED_TOOLS = [
    KI_DIR / "tools" / "build_mosart_grid.py",
    KI_DIR / "tools" / "convert_grid_parameters.py",
    KI_DIR / "tools" / "convert_runoff_forcing.py",
    KI_DIR / "tools" / "delineate_d8_from_merit.py",
    KI_DIR / "tools" / "frac_to_basin_shp.py",
    KI_DIR / "tools" / "parse_mosart_output.py",
    KI_DIR / "tools" / "run_mosartwmpy.py",
]

TOOL_IMPORTS = ["numpy", "xarray", "pandas", "rasterio", "geopandas", "shapely"]


def diagnostic_fix(message):
    return f"{message}; then check {DIAGNOSTICS} for matching recovery triplets"


def add_check(checks, kind, subject, critical, status, fix):
    checks.append(
        {
            "kind": kind,
            "subject": str(subject),
            "critical": bool(critical),
            "status": status,
            "fix": "" if status == "pass" else fix,
        }
    )


def run_command(argv, timeout):
    return subprocess.run(
        [str(a) for a in argv],
        cwd=str(KI_DIR),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )


def check_file(checks, path, label, critical=True, executable=False):
    subject = path.resolve() if path.exists() else path
    if not path.is_file():
        print(f"  FAIL  {label}: not found at {path}")
        add_check(
            checks,
            "data",
            subject,
            critical,
            "fail",
            diagnostic_fix(f"restore required KI file {path}"),
        )
        return
    if executable and not os.access(path, os.X_OK):
        print(f"  FAIL  {label}: exists but is not executable: {path}")
        add_check(
            checks,
            "binary",
            os.path.realpath(path),
            critical,
            "fail",
            diagnostic_fix(f"run chmod +x {path} or repair the MOSART venv"),
        )
        return
    print(f"  OK    {label}: {path}")
    add_check(
        checks,
        "binary" if executable else "data",
        os.path.realpath(path) if executable else subject,
        critical,
        "pass",
        "",
    )


def check_python_starts(checks):
    if not MOSART_PYTHON.is_file():
        print(f"  FAIL  MOSART Python: not found at {MOSART_PYTHON}")
        add_check(
            checks,
            "binary",
            MOSART_PYTHON,
            True,
            "fail",
            diagnostic_fix(
                "restore KISSPATH_KI_ROOT/MOSART/venv or reinstall mosartwmpy"
            ),
        )
        return
    if not os.access(MOSART_PYTHON, os.X_OK):
        print(f"  FAIL  MOSART Python: not executable: {MOSART_PYTHON}")
        add_check(
            checks,
            "binary",
            os.path.realpath(MOSART_PYTHON),
            True,
            "fail",
            diagnostic_fix(f"run chmod +x {MOSART_PYTHON} or rebuild the venv"),
        )
        return

    try:
        proc = run_command(
            [
                MOSART_PYTHON,
                "-c",
                "import os, sys; print(os.path.realpath(sys.executable))",
            ],
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        print(f"  FAIL  MOSART Python: did not start within 10s: {MOSART_PYTHON}")
        add_check(
            checks,
            "binary",
            os.path.realpath(MOSART_PYTHON),
            True,
            "fail",
            diagnostic_fix("repair the MOSART Python environment startup"),
        )
        return

    expected = os.path.realpath(MOSART_PYTHON)
    actual = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
    if proc.returncode == 0 and actual == expected:
        print(f"  OK    MOSART Python starts: {expected}")
        add_check(checks, "binary", expected, True, "pass", "")
    else:
        detail = (proc.stderr or proc.stdout or "no output").strip()
        print(f"  FAIL  MOSART Python start check: {detail}")
        add_check(
            checks,
            "binary",
            expected,
            True,
            "fail",
            diagnostic_fix(f"repair interpreter startup for {MOSART_PYTHON}"),
        )


def check_import_with_python(checks, python_path, module, label, critical=True, timeout=45):
    subject = f"{module} via {python_path}"
    try:
        proc = run_command(
            [
                python_path,
                "-c",
                f"import {module}; print('import-ok')",
            ],
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        print(f"  FAIL  {label}: import {module} timed out after {timeout}s")
        add_check(
            checks,
            "import",
            subject,
            critical,
            "fail",
            diagnostic_fix(
                f"repair or warm up {module} in {python_path}; import exceeded {timeout}s"
            ),
        )
        return

    if proc.returncode == 0:
        print(f"  OK    {label}: import {module}")
        add_check(checks, "import", subject, critical, "pass", "")
    else:
        detail = (proc.stderr or proc.stdout or "no output").strip().splitlines()
        message = detail[-1] if detail else "no output"
        print(f"  FAIL  {label}: import {module} failed: {message}")
        add_check(
            checks,
            "import",
            subject,
            critical,
            "fail",
            diagnostic_fix(f"install/fix {module} in {python_path}"),
        )


def check_tool_imports(checks):
    code = "import " + ", ".join(TOOL_IMPORTS) + "; print('tool-imports-ok')"
    subject = f"{','.join(TOOL_IMPORTS)} via {sys.executable}"
    try:
        proc = run_command([sys.executable, "-c", code], timeout=20)
    except subprocess.TimeoutExpired:
        print("  FAIL  KI tool imports: timed out")
        add_check(
            checks,
            "import",
            subject,
            True,
            "fail",
            diagnostic_fix("repair the Python environment used to run KI tools"),
        )
        return

    if proc.returncode == 0:
        print("  OK    KI tool imports: numpy/xarray/pandas/rasterio/geopandas/shapely")
        add_check(checks, "import", subject, True, "pass", "")
    else:
        detail = (proc.stderr or proc.stdout or "no output").strip().splitlines()
        message = detail[-1] if detail else "no output"
        print(f"  FAIL  KI tool imports: {message}")
        add_check(
            checks,
            "import",
            subject,
            True,
            "fail",
            diagnostic_fix("install missing KI tool dependencies in the active Python environment"),
        )


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}))
    critical_failed = any(
        c.get("critical") and c.get("status") != "pass" for c in checks
    )
    sys.exit(1 if critical_failed else 0)


def main():
    checks = []
    print(f"{' PREFLIGHT: MOSART ':=^60}")
    print()

    check_python_starts(checks)
    check_import_with_python(
        checks,
        MOSART_PYTHON,
        "mosartwmpy",
        "MOSART package",
        critical=True,
        timeout=45,
    )

    for path in REQUIRED_KI_FILES:
        check_file(checks, path, path.relative_to(KI_DIR), critical=True)

    for path in REQUIRED_TOOLS:
        check_file(checks, path, path.relative_to(KI_DIR), critical=True)

    check_tool_imports(checks)

    print()
    if DIAGNOSTICS.is_file():
        print(f"  INFO  Diagnostics available: {DIAGNOSTICS}")
        print("        If a check fails, check diagnostics/triplets.yaml first.")

    failed = [c for c in checks if c["status"] != "pass"]
    print(f"\n  Results: {len(checks) - len(failed)} passed, {len(failed)} failed")
    if failed:
        print("  STATUS: PREFLIGHT FAILED - fix the issues above before running")
    else:
        print("  STATUS: PREFLIGHT PASSED - safe to proceed with model execution")

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
