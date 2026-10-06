#!/usr/bin/env python3
"""Preflight check for the icepack knowledge infrastructure."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


MODEL_ID = "icepack"
KI_DIR = Path(__file__).resolve().parent
PYTHON_ENV = Path("KISSPATH_PYTHON_ENV/bin/python")
TRIPLETS = KI_DIR / "diagnostics" / "triplets.yaml"
# icepack needs Firedrake, which python_env does not have. The model runtime is the
# Firedrake 2026.10 venv with upstream icepack master c9a29780 (built 2026-10-06).
# $ICEPACK_PYTHON overrides it; an explicit value is used as-is, with no fallback.
DEFAULT_MODEL_PYTHON = Path("KISSPATH_HOME/engine_builds_20261006/firedrake/venv/bin/python")
IMPORT_TIMEOUT = 180


def model_python() -> tuple[Path, str]:
    explicit = os.environ.get("ICEPACK_PYTHON", "").strip()
    if explicit:
        return Path(os.path.abspath(explicit)), "ICEPACK_PYTHON"
    return DEFAULT_MODEL_PYTHON, "server default"


def make_check(kind: str, subject: str, critical: bool, status: str, fix: str = "") -> dict:
    check = {
        "kind": kind,
        "subject": subject,
        "critical": critical,
        "status": status,
        "fix": fix,
    }
    return check


def emit_report(checks: list[dict]) -> None:
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": MODEL_ID, "checks": checks}, sort_keys=True))
    ready = all(c["status"] == "pass" or not c.get("critical") for c in checks)
    sys.exit(0 if ready else 1)


def diagnostics_fix(detail: str) -> str:
    return f"{detail}; check {TRIPLETS} for known recovery steps."


def check_python_executable(path: Path) -> dict:
    if not path.exists():
        return make_check(
            "binary",
            str(path),
            True,
            "fail",
            diagnostics_fix("HydroCraft Python environment is missing"),
        )
    if not path.is_file():
        return make_check(
            "binary",
            str(path),
            True,
            "fail",
            diagnostics_fix("HydroCraft Python path is not a file"),
        )
    if not os.access(path, os.X_OK):
        return make_check(
            "binary",
            str(path.resolve()),
            True,
            "fail",
            diagnostics_fix(f"Make the interpreter executable: chmod +x {path}"),
        )

    # Report the path itself: a venv python and python_env share one realpath.
    realpath = f"{path} (realpath {path.resolve()})"
    try:
        proc = subprocess.run(
            [str(path), "-c", "import sys; print(sys.executable)"],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=15,
        )
    except Exception as exc:  # pragma: no cover - defensive runtime guard
        return make_check(
            "binary",
            realpath,
            True,
            "fail",
            diagnostics_fix(f"Interpreter did not start: {exc}"),
        )

    if proc.returncode != 0:
        return make_check(
            "binary",
            realpath,
            True,
            "fail",
            diagnostics_fix(f"Interpreter start failed: {proc.stderr.strip() or proc.stdout.strip()}"),
        )
    return make_check("binary", realpath, True, "pass")


def check_import(module: str, critical: bool = True, python: Path = PYTHON_ENV,
                 source: str = "python_env") -> dict:
    subject = f"{python}:{module} ({source})"
    try:
        proc = subprocess.run(
            [
                str(python),
                "-c",
                f"import importlib; importlib.import_module({module!r}); print('ok')",
            ],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=IMPORT_TIMEOUT,
            cwd=str(KI_DIR),
        )
    except Exception as exc:  # pragma: no cover - defensive runtime guard
        return make_check(
            "import",
            subject,
            critical,
            "fail",
            diagnostics_fix(f"Import check could not run: {exc}"),
        )

    if proc.returncode == 0:
        return make_check("import", subject, critical, "pass")

    detail = (proc.stderr or proc.stdout).strip().splitlines()
    message = detail[-1] if detail else f"import {module} failed"
    return make_check(
        "import",
        subject,
        critical,
        "fail",
        diagnostics_fix(
            f"{python} ({source}) cannot import {module!r}: {message}. Use the Firedrake venv "
            f"{DEFAULT_MODEL_PYTHON}, or set ICEPACK_PYTHON to a Python with firedrake + icepack"
        ),
    )


def report_versions(python: Path) -> None:
    """Print which icepack/firedrake the model runtime really uses (information only)."""
    code = ("import icepack, firedrake, importlib.metadata as m; "
            "print('icepack', m.version('icepack'), icepack.__file__); "
            "print('firedrake', m.version('firedrake'))")
    try:
        proc = subprocess.run([str(python), "-c", code], check=False, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              timeout=IMPORT_TIMEOUT, cwd=str(KI_DIR))
    except Exception:  # pragma: no cover - information only
        return
    if proc.returncode == 0:
        for line in proc.stdout.strip().splitlines():
            print(f"        Detail: {line}")


def check_py_compile(path: Path, critical: bool = True) -> dict:
    subject = str(path.resolve())
    try:
        proc = subprocess.run(
            [str(PYTHON_ENV), "-m", "py_compile", str(path)],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            cwd=str(KI_DIR),
        )
    except Exception as exc:  # pragma: no cover - defensive runtime guard
        return make_check("run", subject, critical, "fail", diagnostics_fix(f"py_compile failed to run: {exc}"))

    if proc.returncode == 0:
        return make_check("run", subject, critical, "pass")
    return make_check(
        "run",
        subject,
        critical,
        "fail",
        diagnostics_fix(f"Fix syntax/import-time compile issue: {(proc.stderr or proc.stdout).strip()}"),
    )


def check_file(path: Path, label: str, critical: bool = True) -> dict:
    subject = str(path.resolve())
    if path.is_file():
        return make_check("data", subject, critical, "pass")
    return make_check(
        "data",
        subject,
        critical,
        "fail",
        diagnostics_fix(f"Required KI file is missing: {label}"),
    )


def main() -> None:
    print(f"{' PREFLIGHT: icepack ':=^60}")

    checks: list[dict] = []
    checks.append(check_python_executable(PYTHON_ENV))
    # python_env still runs the convert tools, which need numpy.
    checks.append(check_import("numpy", critical=True))

    # The model runtime (icepack + Firedrake) is the Firedrake venv, not python_env.
    py, source = model_python()
    runtime_checks = [check_python_executable(py)]
    for module in ("numpy", "icepack", "firedrake"):
        runtime_checks.append(check_import(module, critical=True, python=py, source=source))
    checks.extend(runtime_checks)

    for path, label in (
        (KI_DIR / "SKILL.md", "model skill"),
        (KI_DIR / "knowledge_infrastructure.yaml", "KI manifest"),
        (KI_DIR / "dag.yaml", "model DAG"),
        (TRIPLETS, "diagnostic triplets"),
        (KI_DIR / "docs" / "format_spec.yaml", "I/O format specification"),
    ):
        checks.append(check_file(path, label, critical=True))

    for tool in sorted((KI_DIR / "tools").glob("*.py")):
        checks.append(check_py_compile(tool, critical=True))

    failures = [c for c in checks if c["status"] != "pass"]
    for check in checks:
        marker = "OK" if check["status"] == "pass" else "FAIL"
        print(f"  {marker:<5} {check['kind']}: {check['subject']}")
        if check["status"] != "pass":
            print(f"        Fix: {check['fix']}")
    if all(c["status"] == "pass" for c in runtime_checks):
        report_versions(py)

    print(f"\n  Results: {len(checks) - len(failures)} passed, {len(failures)} failed")
    emit_report(checks)


if __name__ == "__main__":
    main()
