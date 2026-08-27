#!/usr/bin/env python3
"""Preflight check for the FloPy knowledge infrastructure."""

from __future__ import annotations

import json
import os
import py_compile
import subprocess
import sys
from pathlib import Path


MODEL_ID = "FloPy"
KI_DIR = Path(__file__).resolve().parent
PYTHON_ENV = Path("KISSPATH_PYTHON_ENV/bin/python")
MF6_BINARY = Path("KISSPATH_HOME/.local/share/flopy/bin/mf6")
TRIPLETS = KI_DIR / "diagnostics" / "triplets.yaml"


def emit_report(model_id: str, checks: list[dict]) -> None:
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}))
    failed_critical = any(c["status"] != "pass" and c.get("critical") for c in checks)
    sys.exit(1 if failed_critical else 0)


def add_check(
    checks: list[dict],
    kind: str,
    subject: str,
    critical: bool,
    passed: bool,
    fix: str = "",
) -> None:
    check = {
        "kind": kind,
        "subject": subject,
        "critical": critical,
        "status": "pass" if passed else "fail",
        "fix": "" if passed else fix,
    }
    checks.append(check)
    label = "OK" if passed else "FAIL"
    critical_label = "critical" if critical else "optional"
    print(f"  {label:<5} {kind:<7} {critical_label:<8} {subject}")
    if not passed and fix:
        print(f"        Fix: {fix}")


def check_file(
    checks: list[dict],
    path: Path,
    label: str,
    *,
    critical: bool = True,
    executable: bool = False,
) -> bool:
    path = path.resolve() if path.exists() else path
    exists = path.is_file()
    executable_ok = (not executable) or os.access(path, os.X_OK)
    passed = exists and executable_ok
    if not exists:
        fix = f"Restore {label} at {path}; see {TRIPLETS} for recovery."
    elif not executable_ok:
        fix = f"Run chmod +x {path}; see {TRIPLETS} if execution still fails."
    else:
        fix = ""
    add_check(checks, "binary" if executable else "data", str(path), critical, passed, fix)
    return passed


def check_directory(checks: list[dict], path: Path, label: str, *, critical: bool = True) -> bool:
    path = path.resolve() if path.exists() else path
    passed = path.is_dir() and any(path.iterdir())
    fix = f"Restore non-empty {label} directory at {path}; see {TRIPLETS} for recovery."
    add_check(checks, "data", str(path), critical, passed, fix)
    return passed


def check_python(checks: list[dict]) -> Path:
    python = PYTHON_ENV if PYTHON_ENV.is_file() and os.access(PYTHON_ENV, os.X_OK) else Path(sys.executable)
    subject = str(python)
    passed = python.is_file() and os.access(python, os.X_OK)
    fix = (
        f"Restore executable HydroCraft Python at {PYTHON_ENV}; "
        f"then rerun this preflight. See {TRIPLETS}."
    )
    add_check(checks, "run", subject, True, passed, fix)
    return python


def check_import(
    checks: list[dict],
    python: Path,
    module: str,
    *,
    critical: bool = True,
) -> bool:
    try:
        result = subprocess.run(
            [str(python), "-c", f"import {module}; print(getattr({module.split('.')[0]}, '__version__', 'ok'))"],
            cwd=str(KI_DIR),
            capture_output=True,
            text=True,
            timeout=10,
        )
        passed = result.returncode == 0
        detail = (result.stderr or result.stdout).strip().splitlines()[:1]
        reason = detail[0] if detail else "import failed"
    except Exception as exc:
        passed = False
        reason = str(exc)
    fix = (
        f"Install/repair Python dependency '{module}' in {python}; "
        f"check {TRIPLETS} for known import remedies. Last error: {reason}"
    )
    add_check(checks, "import", f"{module} via {python}", critical, passed, fix)
    return passed


def check_binary_starts(checks: list[dict], binary: Path) -> bool:
    real_binary = binary.resolve() if binary.exists() else binary
    if not binary.is_file() or not os.access(binary, os.X_OK):
        return False
    try:
        result = subprocess.run(
            [str(real_binary), "--version"],
            cwd=str(KI_DIR),
            capture_output=True,
            text=True,
            timeout=10,
        )
        output = (result.stdout + result.stderr).strip()
        passed = result.returncode == 0 and "mf6" in output.lower()
        reason = output.splitlines()[0] if output else f"exit code {result.returncode}"
    except Exception as exc:
        passed = False
        reason = str(exc)
    fix = (
        f"Reinstall MODFLOW 6 with 'get-modflow :' or repair {real_binary}; "
        f"check {TRIPLETS}. Last error: {reason}"
    )
    add_check(checks, "run", str(real_binary), True, passed, fix)
    return passed


def check_tool_syntax(checks: list[dict], tool: Path) -> bool:
    subject = str(tool.resolve() if tool.exists() else tool)
    try:
        py_compile.compile(str(tool), doraise=True)
        passed = True
        reason = ""
    except Exception as exc:
        passed = False
        reason = str(exc)
    fix = f"Fix syntax/import-time errors in {tool}; see {TRIPLETS}. Last error: {reason}"
    add_check(checks, "import", subject, True, passed, fix)
    return passed


def main() -> None:
    checks: list[dict] = []

    print("=" * 60)
    print(f"  PREFLIGHT CHECK: {MODEL_ID}")
    print("=" * 60)

    python = check_python(checks)

    check_file(checks, MF6_BINARY, "MODFLOW 6 executable", critical=True, executable=True)
    check_binary_starts(checks, MF6_BINARY)

    for module in ("flopy", "numpy", "pandas", "matplotlib"):
        check_import(checks, python, module, critical=True)

    for module in ("scipy", "rasterio"):
        check_import(checks, python, module, critical=False)

    required_files = [
        KI_DIR / "SKILL.md",
        KI_DIR / "knowledge_infrastructure.yaml",
        KI_DIR / "dag.yaml",
        TRIPLETS,
        KI_DIR / "docs" / "format_spec.yaml",
    ]
    for path in required_files:
        check_file(checks, path, path.name, critical=True)

    check_directory(checks, KI_DIR / "tools", "tools", critical=True)
    for tool in sorted((KI_DIR / "tools").glob("*.py")):
        check_tool_syntax(checks, tool)

    passed = sum(1 for check in checks if check["status"] == "pass")
    failed = len(checks) - passed
    print()
    print(f"  Results: {passed} passed, {failed} failed")
    if failed:
        print(f"  STATUS: PREFLIGHT FAILED - fix issues above; start with {TRIPLETS}")
    else:
        print("  STATUS: PREFLIGHT PASSED - model execution prerequisites are available")

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
