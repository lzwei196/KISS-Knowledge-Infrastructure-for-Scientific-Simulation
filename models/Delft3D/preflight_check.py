#!/usr/bin/env python3
"""Preflight check for the Delft3D Knowledge Infrastructure."""

import json
import os
import subprocess
import sys
from pathlib import Path


MODEL_ID = "Delft3D"
KI_DIR = Path(__file__).resolve().parent
DIAGNOSTICS = KI_DIR / "diagnostics" / "triplets.yaml"
HYDROCRAFT_PYTHON = Path("KISSPATH_PYTHON_ENV/bin/python")
D_HYDRO = Path(
    "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/"
    "Delft3D/build_flow2d3d/d_hydro/d_hydro"
)


checks = []


def add_check(kind, subject, critical, status, fix=""):
    """Record one KDT preflight check and print a concise status line."""
    check = {
        "kind": kind,
        "subject": str(subject),
        "critical": bool(critical),
        "status": status,
        "fix": fix,
    }
    checks.append(check)

    label = "OK" if status == "pass" else "FAIL"
    print(f"  {label:<5} {kind:<7} {subject}")
    if status != "pass" and fix:
        print(f"        Fix: {fix}")


def emit_report(model_id, report_checks):
    print(
        "PREFLIGHT_REPORT="
        + json.dumps({"model_id": model_id, "checks": report_checks}, sort_keys=True)
    )
    sys.exit(
        0
        if all(c["status"] == "pass" or not c.get("critical") for c in report_checks)
        else 1
    )


def fail_fix(detail):
    return f"{detail}; check {DIAGNOSTICS} for matching recovery triplets."


def check_file(path, kind, critical=True, executable=False):
    path = Path(path)
    subject = path.resolve(strict=False)
    if not path.is_file():
        add_check(kind, subject, critical, "fail", fail_fix(f"Create or restore {path}"))
        return False
    if executable and not os.access(path, os.X_OK):
        add_check(kind, subject, critical, "fail", fail_fix(f"Run chmod +x {path}"))
        return False
    add_check(kind, subject, critical, "pass")
    return True


def check_dir(path, critical=True, non_empty=False):
    path = Path(path)
    subject = path.resolve(strict=False)
    if not path.is_dir():
        add_check("data", subject, critical, "fail", fail_fix(f"Create or restore {path}"))
        return False
    if non_empty and not any(path.iterdir()):
        add_check("data", subject, critical, "fail", fail_fix(f"Populate required files in {path}"))
        return False
    add_check("data", subject, critical, "pass")
    return True


def check_python_import(module, critical=True):
    subject = f"{HYDROCRAFT_PYTHON}: import {module}"
    if not HYDROCRAFT_PYTHON.is_file():
        add_check(
            "import",
            subject,
            critical,
            "fail",
            fail_fix(f"Restore HydroCraft Python interpreter at {HYDROCRAFT_PYTHON}"),
        )
        return False

    proc = subprocess.run(
        [str(HYDROCRAFT_PYTHON), "-c", f"import {module}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=20,
    )
    if proc.returncode == 0:
        add_check("import", subject, critical, "pass")
        return True

    detail = (proc.stderr or proc.stdout).strip().splitlines()
    reason = detail[-1] if detail else f"import {module} failed"
    add_check(
        "import",
        subject,
        critical,
        "fail",
        fail_fix(f"Install {module.split('.')[0]} in {HYDROCRAFT_PYTHON}: {reason}"),
    )
    return False


def check_tool_syntax(tool):
    subject = tool.resolve(strict=False)
    if not HYDROCRAFT_PYTHON.is_file():
        add_check(
            "import",
            f"{HYDROCRAFT_PYTHON}: py_compile {tool}",
            True,
            "fail",
            fail_fix(f"Restore HydroCraft Python interpreter at {HYDROCRAFT_PYTHON}"),
        )
        return False

    proc = subprocess.run(
        [str(HYDROCRAFT_PYTHON), "-m", "py_compile", str(tool)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=20,
    )
    if proc.returncode == 0:
        add_check("import", subject, True, "pass")
        return True

    detail = (proc.stderr or proc.stdout).strip().splitlines()
    reason = detail[-1] if detail else "py_compile failed"
    add_check("import", subject, True, "fail", fail_fix(f"Fix Python syntax in {tool}: {reason}"))
    return False


def check_binary_starts(binary):
    real_binary = binary.resolve(strict=False)
    if not (binary.is_file() and os.access(binary, os.X_OK)):
        return False

    try:
        proc = subprocess.run(
            [str(binary), "-v"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=8,
        )
    except subprocess.TimeoutExpired:
        add_check(
            "run",
            f"{real_binary} -v",
            True,
            "fail",
            fail_fix("Delft3D binary timed out during version probe"),
        )
        return False

    output = f"{proc.stdout}\n{proc.stderr}"
    # d_hydro returns 1 for informational probes, but a version banner proves it starts.
    if "D_HYDRO_EXE Version" in output or "Deltares" in output:
        add_check("run", f"{real_binary} -v", True, "pass")
        return True

    reason = output.strip().splitlines()[-1] if output.strip() else f"exit {proc.returncode}"
    add_check(
        "run",
        f"{real_binary} -v",
        True,
        "fail",
        fail_fix(f"Repair Delft3D runtime/linker environment: {reason}"),
    )
    return False


def main():
    print(f"{' PREFLIGHT: Delft3D ':=^60}")
    print()

    check_file(D_HYDRO, "binary", critical=True, executable=True)
    check_binary_starts(D_HYDRO)

    check_file(HYDROCRAFT_PYTHON, "binary", critical=True, executable=True)
    for module in ("numpy", "netCDF4", "pandas", "xarray", "matplotlib", "yaml"):
        check_python_import(module, critical=True)

    check_file(KI_DIR / "SKILL.md", "data", critical=True)
    check_file(KI_DIR / "knowledge_infrastructure.yaml", "data", critical=True)
    check_file(KI_DIR / "dag.yaml", "data", critical=True)
    check_file(DIAGNOSTICS, "data", critical=True)
    check_file(KI_DIR / "docs" / "format_spec.yaml", "data", critical=True)
    check_dir(KI_DIR / "tools", critical=True, non_empty=True)

    for tool_name in (
        "convert_bathymetry.py",
        "convert_boundary_conditions.py",
        "convert_forcing_to_delft3d.py",
        "parse_delft3d_output.py",
        "run_delft3d.py",
    ):
        tool = KI_DIR / "tools" / tool_name
        if check_file(tool, "data", critical=True):
            check_tool_syntax(tool)

    print()
    failed = [c for c in checks if c["status"] != "pass"]
    print(f"  Results: {len(checks) - len(failed)} passed, {len(failed)} failed")
    if failed:
        print(f"  STATUS: PREFLIGHT FAILED - check {DIAGNOSTICS} for recovery triplets")
    else:
        print("  STATUS: PREFLIGHT PASSED - model execution prerequisites are present")

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
