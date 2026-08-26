#!/usr/bin/env python3
"""Preflight check for the PorePy Knowledge Infrastructure."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any


MODEL_ID = "PorePy"
KI_DIR = Path(__file__).resolve().parent
DIAGNOSTICS = KI_DIR / "diagnostics" / "triplets.yaml"
HYDROCRAFT_PYTHON = Path("KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/PorePy/venv/bin/python")


def emit_report(model_id: str, checks: list[dict[str, Any]]) -> None:
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}))
    ready = checks and all(
        check["status"] == "pass" or not check.get("critical") for check in checks
    )
    sys.exit(0 if ready else 1)


def fix_text(message: str) -> str:
    return f"{message}; then consult {DIAGNOSTICS} for known PorePy recovery steps."


def add_check(
    checks: list[dict[str, Any]],
    *,
    kind: str,
    subject: str,
    critical: bool,
    status: str,
    fix: str = "",
) -> None:
    checks.append(
        {
            "kind": kind,
            "subject": subject,
            "critical": critical,
            "status": status,
            "fix": fix,
        }
    )


def check_python_executable(checks: list[dict[str, Any]]) -> bool:
    subject = str(HYDROCRAFT_PYTHON.resolve(strict=False))
    if not HYDROCRAFT_PYTHON.is_file():
        print(f"FAIL Python executable: not found at {HYDROCRAFT_PYTHON}")
        add_check(
            checks,
            kind="binary",
            subject=subject,
            critical=True,
            status="fail",
            fix=fix_text(
                f"restore/create the HydroCraft Python environment at {HYDROCRAFT_PYTHON}"
            ),
        )
        return False
    if not os.access(HYDROCRAFT_PYTHON, os.X_OK):
        print(f"FAIL Python executable: not executable at {HYDROCRAFT_PYTHON}")
        add_check(
            checks,
            kind="binary",
            subject=subject,
            critical=True,
            status="fail",
            fix=fix_text(f"chmod +x {HYDROCRAFT_PYTHON}"),
        )
        return False

    try:
        result = subprocess.run(
            [
                str(HYDROCRAFT_PYTHON),
                "-c",
                "import os, sys; print(os.path.realpath(sys.executable)); "
                "print(sys.version.split()[0])",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception as exc:
        print(f"FAIL Python executable: failed to start: {exc}")
        add_check(
            checks,
            kind="binary",
            subject=subject,
            critical=True,
            status="fail",
            fix=fix_text(f"repair the Python executable {HYDROCRAFT_PYTHON}"),
        )
        return False

    if result.returncode != 0:
        print(f"FAIL Python executable: start failed: {result.stderr.strip()}")
        add_check(
            checks,
            kind="binary",
            subject=subject,
            critical=True,
            status="fail",
            fix=fix_text(f"repair the Python executable {HYDROCRAFT_PYTHON}"),
        )
        return False

    started_realpath = result.stdout.splitlines()[0].strip() if result.stdout else subject
    print(f"OK Python executable: {started_realpath}")
    add_check(
        checks,
        kind="binary",
        subject=started_realpath,
        critical=True,
        status="pass",
    )
    return True


def check_import(
    checks: list[dict[str, Any]], module: str, *, critical: bool = True
) -> None:
    try:
        result = subprocess.run(
            [
                str(HYDROCRAFT_PYTHON),
                "-c",
                (
                    "import importlib; "
                    f"m = importlib.import_module({module!r}); "
                    "print(getattr(m, '__version__', 'unknown'))"
                ),
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
    except Exception as exc:
        print(f"FAIL import {module}: import check crashed: {exc}")
        add_check(
            checks,
            kind="import",
            subject=module,
            critical=critical,
            status="fail",
            fix=fix_text(
                f"repair {HYDROCRAFT_PYTHON} so it can import {module} without crashing"
            ),
        )
        return

    if result.returncode == 0:
        version = result.stdout.strip() or "unknown"
        print(f"OK import {module}: {version}")
        add_check(
            checks,
            kind="import",
            subject=module,
            critical=critical,
            status="pass",
        )
        return

    error = (result.stderr or result.stdout).strip()
    print(f"FAIL import {module}: {error}")
    add_check(
        checks,
        kind="import",
        subject=module,
        critical=critical,
        status="fail",
        fix=fix_text(
            f"install {module.split('.')[0]} into {HYDROCRAFT_PYTHON.parent.parent}"
        ),
    )


def check_file(
    checks: list[dict[str, Any]],
    relative_path: str,
    *,
    label: str,
    critical: bool = True,
) -> None:
    path = KI_DIR / relative_path
    if path.is_file():
        print(f"OK {label}: {path}")
        add_check(
            checks,
            kind="data",
            subject=str(path),
            critical=critical,
            status="pass",
        )
        return

    print(f"FAIL {label}: missing {path}")
    add_check(
        checks,
        kind="data",
        subject=str(path),
        critical=critical,
        status="fail",
        fix=fix_text(f"restore required KI file {relative_path}"),
    )


def check_tool_syntax(checks: list[dict[str, Any]], relative_path: str) -> None:
    path = KI_DIR / relative_path
    if not path.is_file():
        add_check(
            checks,
            kind="data",
            subject=str(path),
            critical=True,
            status="fail",
            fix=fix_text(f"restore required KI tool {relative_path}"),
        )
        print(f"FAIL tool syntax {relative_path}: missing file")
        return

    result = subprocess.run(
        [str(HYDROCRAFT_PYTHON), "-m", "py_compile", str(path)],
        capture_output=True,
        text=True,
        timeout=20,
    )
    if result.returncode == 0:
        print(f"OK tool syntax: {relative_path}")
        add_check(
            checks,
            kind="data",
            subject=str(path),
            critical=True,
            status="pass",
        )
        return

    error = (result.stderr or result.stdout).strip()
    print(f"FAIL tool syntax {relative_path}: {error}")
    add_check(
        checks,
        kind="data",
        subject=str(path),
        critical=True,
        status="fail",
        fix=fix_text(f"fix Python syntax in {relative_path}"),
    )


def main() -> None:
    checks: list[dict[str, Any]] = []
    print(f"{' PREFLIGHT: PorePy ':=^60}")

    python_ready = check_python_executable(checks)

    check_file(checks, "SKILL.md", label="KI instructions")
    check_file(checks, "knowledge_infrastructure.yaml", label="KI manifest")
    check_file(checks, "dag.yaml", label="DAG")
    check_file(checks, "diagnostics/triplets.yaml", label="diagnostic triplets")

    for tool in (
        "tools/convert_forcing_data.py",
        "tools/convert_material_params.py",
        "tools/parse_porepy_output.py",
        "tools/run_porepy.py",
    ):
        check_tool_syntax(checks, tool)

    if python_ready:
        for module in (
            "porepy",
            "gmsh",
            "numpy",
            "scipy",
            "meshio",
            "numba",
            "networkx",
            "shapely",
            "matplotlib",
            "sympy",
        ):
            check_import(checks, module, critical=True)
        check_import(checks, "pypardiso", critical=False)
    else:
        print("Skipping import checks because the configured Python executable is unavailable.")

    failed = [check for check in checks if check["status"] == "fail"]
    print(f"Results: {len(checks) - len(failed)} passed, {len(failed)} failed")
    if failed:
        print("Fixes:")
        for check in failed:
            print(f"- {check['subject']}: {check['fix']}")

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
