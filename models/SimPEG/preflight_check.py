#!/usr/bin/env python3
"""Preflight check for the SimPEG Knowledge Infrastructure."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


MODEL_ID = "SimPEG"
KI_DIR = Path(__file__).resolve().parent
PYTHON_ENV = Path("KISSPATH_PYTHON_ENV/bin/python")
TRIPLETS = KI_DIR / "diagnostics" / "triplets.yaml"


checks: list[dict[str, object]] = []


def add_check(
    kind: str,
    subject: str | Path,
    critical: bool,
    passed: bool,
    fix: str = "",
) -> bool:
    """Record and print one preflight check result."""
    status = "pass" if passed else "fail"
    subject_str = str(subject)
    checks.append(
        {
            "kind": kind,
            "subject": subject_str,
            "critical": critical,
            "status": status,
            "fix": "" if passed else fix,
        }
    )

    label = "OK" if passed else "FAIL"
    print(f"  {label:<5} {kind}: {subject_str}")
    if not passed and fix:
        print(f"        Fix: {fix}")
    return passed


def emit_report() -> None:
    print(
        "PREFLIGHT_REPORT="
        + json.dumps({"model_id": MODEL_ID, "checks": checks}, sort_keys=True)
    )
    has_critical_failure = any(
        c["status"] == "fail" and bool(c.get("critical")) for c in checks
    )
    sys.exit(1 if has_critical_failure else 0)


def check_python_executable() -> bool:
    realpath = os.path.realpath(PYTHON_ENV)
    if not PYTHON_ENV.is_file():
        return add_check(
            "binary",
            realpath,
            True,
            False,
            (
                f"Restore the HydroCraft Python environment at {PYTHON_ENV}; "
                f"then check {TRIPLETS} for matching recovery steps."
            ),
        )
    if not os.access(PYTHON_ENV, os.X_OK):
        return add_check(
            "binary",
            realpath,
            True,
            False,
            (
                f"Make {PYTHON_ENV} executable, e.g. chmod +x {PYTHON_ENV}; "
                f"then check {TRIPLETS}."
            ),
        )
    return add_check("binary", realpath, True, True)


def run_with_python(args: list[str], timeout: int = 20) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(PYTHON_ENV), *args],
        cwd=str(KI_DIR),
        text=True,
        capture_output=True,
        timeout=timeout,
    )


def check_python_starts() -> None:
    try:
        proc = run_with_python(
            [
                "-c",
                (
                    "import os, sys; "
                    "print(sys.executable); "
                    "print(os.path.realpath(sys.executable))"
                ),
            ],
            timeout=10,
        )
        passed = proc.returncode == 0
        detail = (proc.stderr or proc.stdout).strip().splitlines()[-1] if not passed else ""
        add_check(
            "run",
            f"{PYTHON_ENV} starts",
            True,
            passed,
            (
                f"HydroCraft Python did not start cleanly ({detail}); "
                f"repair {PYTHON_ENV} and consult {TRIPLETS}."
            ),
        )
    except Exception as exc:
        add_check(
            "run",
            f"{PYTHON_ENV} starts",
            True,
            False,
            f"HydroCraft Python startup failed: {exc}. Check {TRIPLETS}.",
        )


def check_import(module: str, critical: bool = True) -> None:
    try:
        proc = run_with_python(["-c", f"import {module}"], timeout=20)
        passed = proc.returncode == 0
        detail = (proc.stderr or proc.stdout).strip().splitlines()
        tail = detail[-1] if detail else "unknown import error"
        add_check(
            "import",
            module,
            critical,
            passed,
            (
                f"Install or repair '{module}' in {PYTHON_ENV}; last error: {tail}. "
                f"Check {TRIPLETS} before changing tools."
            ),
        )
    except Exception as exc:
        add_check(
            "import",
            module,
            critical,
            False,
            f"Could not import-check '{module}' with {PYTHON_ENV}: {exc}. Check {TRIPLETS}.",
        )


def check_file(path: Path, kind: str, critical: bool = True) -> None:
    add_check(
        kind,
        path,
        critical,
        path.is_file(),
        f"Restore required KI file {path}; check {TRIPLETS} for recovery guidance.",
    )


def check_tool_compiles(path: Path) -> None:
    if not path.is_file():
        add_check(
            "run",
            f"py_compile {path}",
            True,
            False,
            f"Restore missing tool {path}; check {TRIPLETS}.",
        )
        return

    try:
        proc = run_with_python(["-m", "py_compile", str(path)], timeout=20)
        passed = proc.returncode == 0
        detail = (proc.stderr or proc.stdout).strip().splitlines()
        tail = detail[-1] if detail else "syntax or import-time compile error"
        add_check(
            "run",
            f"py_compile {path}",
            True,
            passed,
            f"Fix syntax in {path}; last error: {tail}. Check {TRIPLETS}.",
        )
    except Exception as exc:
        add_check(
            "run",
            f"py_compile {path}",
            True,
            False,
            f"Could not compile-check {path}: {exc}. Check {TRIPLETS}.",
        )


def main() -> None:
    print(f"{' PREFLIGHT: SimPEG ':=^60}")
    print(f"KI directory: {KI_DIR}")
    print(f"Diagnostics: {TRIPLETS}")
    print()

    check_python_executable()
    check_python_starts()

    for module in [
        "simpeg",
        "simpeg.potential_fields.gravity",
        "simpeg.potential_fields.magnetics",
        "simpeg.electromagnetics.static.resistivity",
        "discretize",
        "pymatsolver",
        "geoana",
        "numpy",
    ]:
        check_import(module, critical=True)
    check_import("matplotlib", critical=False)

    for rel in [
        "SKILL.md",
        "knowledge_infrastructure.yaml",
        "dag.yaml",
        "docs/format_spec.yaml",
        "diagnostics/triplets.yaml",
    ]:
        check_file(KI_DIR / rel, "data", critical=True)

    for rel in [
        "tools/build_mesh.py",
        "tools/initialize_model.py",
        "tools/run_simpeg.py",
        "tools/parse_results.py",
    ]:
        path = KI_DIR / rel
        check_file(path, "data", critical=True)
        check_tool_compiles(path)

    passed = sum(1 for c in checks if c["status"] == "pass")
    failed = len(checks) - passed
    print()
    print(f"  Results: {passed} passed, {failed} failed")
    if failed:
        print(f"  STATUS: PREFLIGHT FAILED. Check {TRIPLETS} before recovery.")
    else:
        print("  STATUS: PREFLIGHT PASSED. SimPEG KI is ready for model execution.")
    emit_report()


if __name__ == "__main__":
    main()
