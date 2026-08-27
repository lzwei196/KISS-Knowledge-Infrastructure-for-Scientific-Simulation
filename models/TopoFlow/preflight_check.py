#!/usr/bin/env python3
"""Preflight check for the TopoFlow Knowledge Infrastructure."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path


MODEL_ID = "TopoFlow"
KI_DIR = Path(__file__).resolve().parent
MANIFEST = KI_DIR / "knowledge_infrastructure.yaml"
TRIPLETS = KI_DIR / "diagnostics" / "triplets.yaml"
DEFAULT_MODEL_PYTHON = (
    "KISSPATH_INTERNAL_NOT_SHIPPED/"
    "auto_dissect/_work/TopoFlow/venv/bin/python"
)


def diagnostics_fix(extra: str) -> str:
    return f"{extra} Check {TRIPLETS} for matching recovery triplets."


def emit_report(model_id: str, checks: list[dict]) -> None:
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}))
    sys.exit(0 if all(c["status"] == "pass" or not c.get("critical") for c in checks) else 1)


def add_check(
    checks: list[dict],
    *,
    kind: str,
    subject: str,
    critical: bool,
    ok: bool,
    fix: str = "",
    detail: str = "",
) -> None:
    status = "pass" if ok else "fail"
    checks.append(
        {
            "kind": kind,
            "subject": subject,
            "critical": critical,
            "status": status,
            "fix": "" if ok else fix,
        }
    )
    label = "OK" if ok else "FAIL"
    print(f"  {label:<5} {kind}: {subject}")
    if detail:
        print(f"        {detail}")
    if not ok and fix:
        print(f"        Fix: {fix}")


def manifest_binary_path() -> str:
    if not MANIFEST.is_file():
        return DEFAULT_MODEL_PYTHON

    try:
        import yaml

        with MANIFEST.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        path = (
            data.get("package", {})
            .get("binary", {})
            .get("path")
        )
        if path:
            return str(path)
    except Exception:
        pass

    in_binary_block = False
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped == "binary:":
            in_binary_block = True
            continue
        if in_binary_block:
            if stripped.startswith("path:"):
                return re.sub(r"^path:\s*", "", stripped).strip().strip("'\"")
            if stripped and not line.startswith(" "):
                break
    return DEFAULT_MODEL_PYTHON


def run_with_python(executable: str, code: str, timeout: int = 10) -> subprocess.CompletedProcess:
    return subprocess.run(
        [executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def check_python_binary(checks: list[dict], executable: str) -> str:
    real_executable = os.path.realpath(executable) if os.path.exists(executable) else executable
    exists_and_exec = os.path.isfile(executable) and os.access(executable, os.X_OK)
    add_check(
        checks,
        kind="binary",
        subject=real_executable,
        critical=True,
        ok=exists_and_exec,
        fix=diagnostics_fix(
            f"Restore or install the TopoFlow Python executable recorded in {MANIFEST}: {executable}."
        ),
        detail=f"manifest path: {executable}",
    )
    if not exists_and_exec:
        return real_executable

    try:
        proc = run_with_python(executable, "import sys; print(sys.version.split()[0])")
        ok = proc.returncode == 0
        detail = (proc.stdout or proc.stderr).strip().splitlines()[-1] if (proc.stdout or proc.stderr).strip() else ""
    except Exception as exc:
        ok = False
        detail = str(exc)
    add_check(
        checks,
        kind="run",
        subject=real_executable,
        critical=True,
        ok=ok,
        fix=diagnostics_fix(f"Make sure {executable} starts without errors."),
        detail=detail,
    )
    return real_executable


def check_import_with_python(
    checks: list[dict],
    executable: str,
    real_executable: str,
    module: str,
    *,
    critical: bool = True,
) -> None:
    subject = f"{module} via {real_executable}"
    code = (
        "import importlib; "
        f"m = importlib.import_module({module!r}); "
        "print(getattr(m, '__file__', 'built-in'))"
    )
    try:
        proc = run_with_python(executable, code)
        ok = proc.returncode == 0
        output = (proc.stdout or proc.stderr).strip()
        detail = output.splitlines()[-1] if output else ""
    except Exception as exc:
        ok = False
        detail = str(exc)
    add_check(
        checks,
        kind="import",
        subject=subject,
        critical=critical,
        ok=ok,
        fix=diagnostics_fix(
            f"Install TopoFlow/dependency '{module}' into the environment used by {executable}."
        ),
        detail=detail,
    )


def check_file(
    checks: list[dict],
    path: Path,
    *,
    kind: str = "data",
    critical: bool = True,
    executable: bool = False,
) -> None:
    ok = path.is_file() and (not executable or os.access(path, os.X_OK))
    add_check(
        checks,
        kind=kind,
        subject=str(path),
        critical=critical,
        ok=ok,
        fix=diagnostics_fix(f"Restore required KI file {path}."),
    )


def main() -> None:
    checks: list[dict] = []

    print(f"{' PREFLIGHT: TopoFlow ':=^60}")
    print(f"KI directory: {KI_DIR}")
    print()

    model_python = manifest_binary_path()
    real_model_python = check_python_binary(checks, model_python)

    for module in [
        "topoflow",
        "topoflow.framework.emeli",
        "numpy",
        "scipy",
        "netCDF4",
        "cfunits",
    ]:
        check_import_with_python(checks, model_python, real_model_python, module, critical=True)

    for rel_path in [
        "SKILL.md",
        "knowledge_infrastructure.yaml",
        "dag.yaml",
        "tools/run_topoflow.py",
        "tools/convert_forcing.py",
        "tools/convert_soil_params.py",
        "tools/parse_output.py",
    ]:
        check_file(checks, KI_DIR / rel_path, critical=True)

    check_file(checks, TRIPLETS, critical=True)
    print()
    passed = sum(1 for c in checks if c["status"] == "pass")
    failed = len(checks) - passed
    print(f"  Results: {passed} passed, {failed} failed")
    if failed:
        print(f"  Recovery: inspect {TRIPLETS} before changing model setup or inputs.")

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        emergency_checks = [
            {
                "kind": "run",
                "subject": str(Path(__file__).resolve()),
                "critical": True,
                "status": "fail",
                "fix": diagnostics_fix(f"preflight_check.py crashed with {type(exc).__name__}: {exc}."),
            }
        ]
        print(f"  FAIL  preflight crashed: {type(exc).__name__}: {exc}")
        emit_report(MODEL_ID, emergency_checks)
