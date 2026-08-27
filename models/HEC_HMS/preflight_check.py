#!/usr/bin/env python3
"""Preflight check for the HEC-HMS Knowledge Infrastructure."""

import json
import os
import subprocess
import sys
from pathlib import Path


MODEL_ID = "HEC-HMS"
KI_DIR = Path(__file__).resolve().parent
TOOLS_DIR = KI_DIR / "tools"
DIAGNOSTICS = KI_DIR / "diagnostics" / "triplets.yaml"
PYTHON_ENV = Path("KISSPATH_PYTHON_ENV/bin/python")
BINARY = (TOOLS_DIR / "run_hec_hms.py").resolve()


def fix_text(action):
    return f"{action}; then check {DIAGNOSTICS} for matching recovery triplets."


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}, sort_keys=True))
    failed_critical = any(c["status"] == "fail" and c.get("critical") for c in checks)
    sys.exit(1 if failed_critical else 0)


def add_check(checks, kind, subject, critical, ok, fix):
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
    if not ok:
        print(f"        Fix: {fix}")
    return ok


def check_file(checks, path, label, critical=True, executable=False):
    path = Path(path)
    ok = path.is_file()
    if ok and executable:
        ok = os.access(path, os.X_OK)
    if executable:
        action = f"ensure {label} exists and is executable: chmod +x {path}"
    else:
        action = f"restore required file for {label}: {path}"
    return add_check(checks, "data", path.resolve() if path.exists() else path, critical, ok, fix_text(action))


def check_dir(checks, path, label, critical=True, non_empty=True):
    path = Path(path)
    ok = path.is_dir() and (not non_empty or any(path.iterdir()))
    action = f"restore required directory for {label}: {path}"
    return add_check(checks, "data", path.resolve() if path.exists() else path, critical, ok, fix_text(action))


def check_python_import(checks, module, critical=True):
    cmd = [str(PYTHON_ENV), "-c", f"import {module}"]
    try:
        proc = subprocess.run(cmd, cwd=KI_DIR, text=True, capture_output=True, timeout=20)
        ok = proc.returncode == 0
        detail = (proc.stderr or proc.stdout).strip().splitlines()
        extra = f" ({detail[-1]})" if detail and not ok else ""
    except Exception as exc:
        ok = False
        extra = f" ({exc})"
    fix = fix_text(f"install/repair Python dependency '{module}' in {PYTHON_ENV}")
    return add_check(checks, "import", f"{module} via {PYTHON_ENV}{extra}", critical, ok, fix)


def check_command(checks, subject, cmd, critical=True, timeout=20):
    try:
        proc = subprocess.run(cmd, cwd=KI_DIR, text=True, capture_output=True, timeout=timeout)
        ok = proc.returncode == 0
        detail = (proc.stderr or proc.stdout).strip().splitlines()
        extra = f" ({detail[-1][:180]})" if detail and not ok else ""
    except Exception as exc:
        ok = False
        extra = f" ({exc})"
    fix = fix_text(f"make this command start successfully: {' '.join(map(str, cmd))}")
    return add_check(checks, "run", f"{subject}{extra}", critical, ok, fix)


def main():
    checks = []

    print("=" * 60)
    print(f"  PREFLIGHT CHECK: {MODEL_ID}")
    print("=" * 60)

    python_ok = PYTHON_ENV.is_file() and os.access(PYTHON_ENV, os.X_OK)
    add_check(
        checks,
        "data",
        PYTHON_ENV,
        True,
        python_ok,
        fix_text(f"restore executable HydroCraft Python interpreter: {PYTHON_ENV}"),
    )

    # The manifest declares this Python entrypoint as the KI binary. The subject
    # is the executable realpath so the gate can compare it with the models DB.
    check_file(checks, BINARY, "HEC-HMS Python executable", critical=True, executable=True)
    check_command(checks, os.path.realpath(BINARY), [str(PYTHON_ENV), str(BINARY), "--help"], critical=True)

    for module in ("numpy", "pandas"):
        check_python_import(checks, module, critical=True)

    # These are required for the documented HydroCraft data-prep/validation tools.
    for module in ("xarray", "geopandas", "shapely", "rasterio", "matplotlib", "scipy"):
        check_python_import(checks, module, critical=True)

    for rel in (
        "tools/run_hec_hms.py",
        "tools/convert_forcing_to_hms.py",
        "tools/convert_soil_to_hms.py",
        "tools/parse_hms_output.py",
        "tools/validate_hms.py",
        "tools/calibrate_hms.py",
    ):
        check_file(checks, KI_DIR / rel, rel, critical=True)

    check_dir(checks, TOOLS_DIR, "KI tools", critical=True, non_empty=True)
    check_file(checks, KI_DIR / "SKILL.md", "KI instructions", critical=True)
    check_file(checks, KI_DIR / "knowledge_infrastructure.yaml", "KI manifest", critical=True)
    check_file(checks, KI_DIR / "dag.yaml", "KDT DAG", critical=True)
    check_file(checks, KI_DIR / "docs" / "format_spec.yaml", "I/O format specification", critical=True)
    check_file(checks, DIAGNOSTICS, "diagnostic recovery triplets", critical=True)

    check_command(
        checks,
        "compile all HEC-HMS tool scripts",
        [str(PYTHON_ENV), "-m", "py_compile"] + [str(p) for p in sorted(TOOLS_DIR.glob("*.py"))],
        critical=True,
        timeout=30,
    )

    passed = sum(1 for c in checks if c["status"] == "pass")
    failed = len(checks) - passed
    print()
    print(f"  Results: {passed} passed, {failed} failed")
    if failed:
        print(f"  STATUS: PREFLIGHT FAILED - check {DIAGNOSTICS} and fix blockers above")
    else:
        print("  STATUS: PREFLIGHT PASSED - safe to proceed with HEC-HMS execution")

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
