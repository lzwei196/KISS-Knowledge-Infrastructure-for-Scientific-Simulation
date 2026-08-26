#!/usr/bin/env python3
"""Preflight check for the GemPy KI."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


MODEL_ID = "GemPy"
KI_DIR = Path(__file__).resolve().parent
TRIPLETS = KI_DIR / "diagnostics" / "triplets.yaml"
DIAGNOSTIC_FIX = f"Check {TRIPLETS} for the matching symptom and remedy."

HYDROCRAFT_PYTHON = Path("KISSPATH_PYTHON_ENV/bin/python")
MANIFEST_PYTHON = Path(
    "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/GemPy/venv/bin/python"
)

TOOL_FILES = [
    KI_DIR / "tools" / "build_structural_params.py",
    KI_DIR / "tools" / "convert_geological_data.py",
    KI_DIR / "tools" / "parse_gempy_output.py",
    KI_DIR / "tools" / "run_gempy_model.py",
]

METADATA_FILES = [
    KI_DIR / "SKILL.md",
    KI_DIR / "knowledge_infrastructure.yaml",
    KI_DIR / "dag.yaml",
]


def emit_report(model_id: str, checks: list[dict]) -> None:
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}))
    sys.exit(0 if all(c["status"] == "pass" or not c.get("critical") for c in checks) else 1)


def add_check(
    checks: list[dict],
    *,
    kind: str,
    subject: str,
    critical: bool,
    status: str,
    fix: str = "",
) -> None:
    check = {
        "kind": kind,
        "subject": subject,
        "critical": bool(critical),
        "status": status,
        "fix": fix if status == "fail" else "",
    }
    checks.append(check)

    label = "OK" if status == "pass" else "FAIL"
    crit = "critical" if critical else "noncritical"
    print(f"  {label:<5} {kind:<7} {subject} ({crit})")
    if status == "fail" and fix:
        print(f"        Fix: {fix}")


def run_cmd(args: list[str], timeout: int = 15) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        cwd=str(KI_DIR),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )


def python_can_import(python_path: Path, module: str) -> tuple[bool, str]:
    if not python_path.is_file():
        return False, f"interpreter not found: {python_path}"
    try:
        result = run_cmd(
            [
                str(python_path),
                "-c",
                (
                    "import importlib, sys; "
                    f"m = importlib.import_module({module!r}); "
                    "print(getattr(m, '__version__', 'no_version'))"
                ),
            ]
        )
    except Exception as exc:
        return False, str(exc)
    output = (result.stdout + result.stderr).strip()
    return result.returncode == 0, output


def select_model_python(checks: list[dict]) -> Path:
    """Use HydroCraft python_env when it actually contains GemPy, else the manifest runtime."""
    hydro_ok, hydro_detail = python_can_import(HYDROCRAFT_PYTHON, "gempy_engine")
    add_check(
        checks,
        kind="import",
        subject=f"{HYDROCRAFT_PYTHON}:gempy_engine",
        critical=False,
        status="pass" if hydro_ok else "fail",
        fix=(
            "Install compatible GemPy packages in KISSPATH_PYTHON_ENV "
            f"or keep using the manifest runtime. {DIAGNOSTIC_FIX}"
        ),
    )
    if hydro_ok:
        print(f"        Detail: {hydro_detail}")
        return HYDROCRAFT_PYTHON

    manifest_ok, manifest_detail = python_can_import(MANIFEST_PYTHON, "gempy_engine")
    if manifest_ok:
        print(f"        Detail: selected manifest runtime; {manifest_detail}")
    return MANIFEST_PYTHON


def check_python_executable(checks: list[dict], python_path: Path) -> None:
    real = os.path.realpath(python_path)
    executable = python_path.is_file() and os.access(python_path, os.X_OK)
    add_check(
        checks,
        kind="binary",
        subject=real,
        critical=True,
        status="pass" if executable else "fail",
        fix=f"Restore executable Python runtime at {python_path}; {DIAGNOSTIC_FIX}",
    )
    if not executable:
        return

    try:
        result = run_cmd([str(python_path), "-c", "import sys; print(sys.version.split()[0])"])
        ok = result.returncode == 0 and result.stdout.strip()
        detail = (result.stdout or result.stderr).strip()
    except Exception as exc:
        ok = False
        detail = str(exc)
    add_check(
        checks,
        kind="run",
        subject=f"{real}: starts Python",
        critical=True,
        status="pass" if ok else "fail",
        fix=f"Fix the Python runtime at {python_path}. {detail} {DIAGNOSTIC_FIX}",
    )
    if ok:
        print(f"        Detail: Python {detail}")


def check_import(checks: list[dict], python_path: Path, module: str, critical: bool = True) -> None:
    ok, detail = python_can_import(python_path, module)
    add_check(
        checks,
        kind="import",
        subject=f"{python_path}:{module}",
        critical=critical,
        status="pass" if ok else "fail",
        fix=(
            f"Install a GemPy-compatible dependency set for {python_path}: "
            "pip install 'gempy[base]'. "
            f"{detail} {DIAGNOSTIC_FIX}"
        ),
    )
    if ok:
        print(f"        Detail: {module} {detail}")


def check_file(checks: list[dict], path: Path, kind: str, critical: bool = True) -> None:
    add_check(
        checks,
        kind=kind,
        subject=str(path),
        critical=critical,
        status="pass" if path.is_file() else "fail",
        fix=f"Restore required KI file {path}. {DIAGNOSTIC_FIX}",
    )


def check_tool_syntax(checks: list[dict], python_path: Path, path: Path) -> None:
    if not path.is_file():
        return
    try:
        result = run_cmd([str(python_path), "-m", "py_compile", str(path)], timeout=20)
        ok = result.returncode == 0
        detail = (result.stderr or result.stdout).strip()
    except Exception as exc:
        ok = False
        detail = str(exc)
    add_check(
        checks,
        kind="run",
        subject=f"{python_path}:py_compile:{path.relative_to(KI_DIR)}",
        critical=True,
        status="pass" if ok else "fail",
        fix=f"Fix Python syntax/import-time compilation for {path}. {detail} {DIAGNOSTIC_FIX}",
    )


def check_tool_help(checks: list[dict], python_path: Path) -> None:
    tool = KI_DIR / "tools" / "run_gempy_model.py"
    if not tool.is_file():
        return
    try:
        result = run_cmd([str(python_path), str(tool), "--help"], timeout=20)
        ok = result.returncode == 0 and "Execute a GemPy geological model" in result.stdout
        detail = (result.stderr or result.stdout).strip().splitlines()[:1]
    except Exception as exc:
        ok = False
        detail = [str(exc)]
    add_check(
        checks,
        kind="run",
        subject=f"{python_path}:tools/run_gempy_model.py --help",
        critical=True,
        status="pass" if ok else "fail",
        fix=f"Fix the GemPy execution wrapper CLI startup. {' '.join(detail)} {DIAGNOSTIC_FIX}",
    )


def check_triplets_yaml(checks: list[dict]) -> None:
    if not TRIPLETS.is_file():
        add_check(
            checks,
            kind="data",
            subject=str(TRIPLETS),
            critical=True,
            status="fail",
            fix=f"Restore diagnostics/triplets.yaml so failures have recovery guidance. {DIAGNOSTIC_FIX}",
        )
        return

    try:
        import yaml

        loaded = yaml.safe_load(TRIPLETS.read_text())
        ok = isinstance(loaded, list) and len(loaded) > 0
        detail = f"{len(loaded) if isinstance(loaded, list) else 0} triplets"
    except Exception as exc:
        ok = False
        detail = str(exc)

    add_check(
        checks,
        kind="data",
        subject=str(TRIPLETS),
        critical=True,
        status="pass" if ok else "fail",
        fix=f"Repair diagnostics/triplets.yaml; it must parse and contain recovery triplets. {detail}",
    )
    if ok:
        print(f"        Detail: {detail}")


def main() -> None:
    checks: list[dict] = []
    print("=" * 60)
    print(f"  PREFLIGHT CHECK: {MODEL_ID}")
    print("=" * 60)

    model_python = select_model_python(checks)
    check_python_executable(checks, model_python)

    for module in ("gempy", "gempy_engine", "numpy", "pandas"):
        check_import(checks, model_python, module, critical=True)
    check_import(checks, model_python, "gempy_viewer", critical=False)

    for path in METADATA_FILES:
        check_file(checks, path, kind="data", critical=True)
    for path in TOOL_FILES:
        check_file(checks, path, kind="data", critical=True)
        check_tool_syntax(checks, model_python, path)

    check_tool_help(checks, model_python)
    check_triplets_yaml(checks)

    passed = sum(1 for c in checks if c["status"] == "pass")
    failed = len(checks) - passed
    print(f"\n  Results: {passed} passed, {failed} failed")
    if any(c["status"] == "fail" and c.get("critical") for c in checks):
        print(f"  STATUS: PREFLIGHT FAILED. {DIAGNOSTIC_FIX}")
    else:
        print("  STATUS: PREFLIGHT PASSED")
    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
