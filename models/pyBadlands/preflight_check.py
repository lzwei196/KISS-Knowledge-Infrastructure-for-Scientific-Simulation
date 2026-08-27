#!/usr/bin/env python3
"""Preflight check for the pyBadlands Knowledge Infrastructure."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


MODEL_ID = "pyBadlands"
KI_DIR = Path(__file__).resolve().parent
PYTHON = Path("KISSPATH_PYTHON_ENV/bin/python")
TRIPLETS = KI_DIR / "diagnostics" / "triplets.yaml"


def diagnostic_fix(message: str) -> str:
    return f"{message}; see {TRIPLETS} for matching diagnostics and recovery steps."


def emit_report(model_id: str, checks: list[dict]) -> None:
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}))
    ready = all(c["status"] == "pass" or not c.get("critical") for c in checks)
    sys.exit(0 if ready else 1)


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
        "critical": critical,
        "status": status,
        "fix": fix,
    }
    checks.append(check)
    label = "OK" if status == "pass" else "FAIL"
    print(f"  {label:<5} {kind}: {subject}")
    if status != "pass" and fix:
        print(f"        Fix: {fix}")


def run_python(code: str, timeout: int = 15) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONNOUSERSITE"] = "1"
    return subprocess.run(
        [str(PYTHON), "-c", code],
        cwd=str(KI_DIR),
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout,
    )


def check_python_executable(checks: list[dict]) -> bool:
    subject = str(PYTHON.resolve()) if PYTHON.exists() else str(PYTHON)
    if not PYTHON.is_file():
        add_check(
            checks,
            kind="binary",
            subject=subject,
            critical=True,
            status="fail",
            fix=diagnostic_fix(f"Restore or recreate the HydroCraft Python environment at {PYTHON}"),
        )
        return False
    if not os.access(PYTHON, os.X_OK):
        add_check(
            checks,
            kind="binary",
            subject=subject,
            critical=True,
            status="fail",
            fix=diagnostic_fix(f"Make the interpreter executable: chmod +x {PYTHON}"),
        )
        return False

    try:
        proc = subprocess.run(
            [str(PYTHON), "--version"],
            text=True,
            capture_output=True,
            timeout=10,
        )
    except Exception as exc:
        add_check(
            checks,
            kind="binary",
            subject=subject,
            critical=True,
            status="fail",
            fix=diagnostic_fix(f"Interpreter did not start: {exc}"),
        )
        return False

    if proc.returncode == 0:
        version = (proc.stdout or proc.stderr).strip()
        add_check(checks, kind="binary", subject=subject, critical=True, status="pass")
        print(f"        Version: {version}")
        return True

    add_check(
        checks,
        kind="binary",
        subject=subject,
        critical=True,
        status="fail",
        fix=diagnostic_fix((proc.stderr or proc.stdout or "python --version failed").strip()),
    )
    return False


def check_import(checks: list[dict], module: str, *, critical: bool = True, fix: str | None = None) -> None:
    proc = run_python(
        "import importlib, json; "
        f"m=importlib.import_module({module!r}); "
        "print(json.dumps({'module': m.__name__, 'file': getattr(m, '__file__', '')}))"
    )
    if proc.returncode == 0:
        add_check(checks, kind="import", subject=module, critical=critical, status="pass")
        detail = proc.stdout.strip()
        if detail:
            print(f"        {detail}")
        return

    stderr = (proc.stderr or proc.stdout).strip().splitlines()
    message = stderr[-1] if stderr else f"import {module} failed"
    add_check(
        checks,
        kind="import",
        subject=module,
        critical=critical,
        status="fail",
        fix=fix or diagnostic_fix(f"Install/repair Python dependency in {PYTHON.parent}: {message}"),
    )


def check_numpy_contract(checks: list[dict]) -> None:
    proc = run_python("import numpy as np; print(np.__version__)")
    if proc.returncode != 0:
        add_check(
            checks,
            kind="import",
            subject="numpy<2",
            critical=True,
            status="fail",
            fix=diagnostic_fix("Install NumPy < 2 in KISSPATH_PYTHON_ENV"),
        )
        return

    version = proc.stdout.strip()
    major = int(version.split(".", 1)[0])
    if major < 2:
        add_check(checks, kind="import", subject=f"numpy<2 ({version})", critical=True, status="pass")
    else:
        add_check(
            checks,
            kind="import",
            subject=f"numpy<2 ({version})",
            critical=True,
            status="fail",
            fix=diagnostic_fix(
                "pyBadlands requires NumPy < 2; install a compatible NumPy in "
                "KISSPATH_PYTHON_ENV before running the model"
            ),
        )


def check_tool_file(checks: list[dict], relative_path: str, *, python_ready: bool) -> None:
    path = KI_DIR / relative_path
    status = "pass" if path.is_file() else "fail"
    add_check(
        checks,
        kind="data",
        subject=str(path),
        critical=True,
        status=status,
        fix="" if status == "pass" else diagnostic_fix(f"Restore required KI tool file {relative_path}"),
    )
    if status == "pass" and path.suffix == ".py" and python_ready:
        proc = run_python(
            "import py_compile, sys; "
            f"py_compile.compile({str(path)!r}, doraise=True); "
            "print('compiled')"
        )
        if proc.returncode == 0:
            add_check(
                checks,
                kind="import",
                subject=f"syntax-check tool module {relative_path}",
                critical=True,
                status="pass",
            )
        else:
            message = (proc.stderr or proc.stdout).strip().splitlines()
            add_check(
                checks,
                kind="import",
                subject=f"syntax-check tool module {relative_path}",
                critical=True,
                status="fail",
                fix=diagnostic_fix(
                    f"Fix Python syntax in {relative_path}: {message[-1] if message else 'py_compile failed'}"
                ),
            )


def main() -> None:
    print(f"{' PREFLIGHT: pyBadlands ':=^60}")
    print(f"KI directory: {KI_DIR}")
    print(f"Recovery diagnostics: {TRIPLETS}")
    print()

    checks: list[dict] = []
    python_ready = check_python_executable(checks)

    add_check(
        checks,
        kind="data",
        subject=str(TRIPLETS),
        critical=False,
        status="pass" if TRIPLETS.is_file() else "fail",
        fix="" if TRIPLETS.is_file() else f"Restore diagnostics/triplets.yaml under {KI_DIR}.",
    )

    for relative_path in (
        "SKILL.md",
        "knowledge_infrastructure.yaml",
        "dag.yaml",
        "tools/s3_forcing/convert_forcing_to_badlands.py",
        "tools/s4_parameters/convert_soil_params.py",
        "tools/s5_run/run_badlands.py",
        "tools/s6_output/parse_badlands_output.py",
    ):
        check_tool_file(checks, relative_path, python_ready=python_ready)

    if python_ready:
        check_numpy_contract(checks)
        for module in ("scipy", "h5py", "pandas", "matplotlib", "skimage", "six"):
            check_import(checks, module, critical=True)
        check_import(
            checks,
            "triangle",
            critical=True,
            fix=diagnostic_fix(
                "Install the pyBadlands triangulation dependency in "
                "KISSPATH_PYTHON_ENV (for example: python -m pip install triangle)"
            ),
        )
        check_import(
            checks,
            "badlands",
            critical=True,
            fix=diagnostic_fix(
                "Install/build pyBadlands into KISSPATH_PYTHON_ENV; "
                "do not use the stale auto_dissect/_work venv path"
            ),
        )
        check_import(
            checks,
            "badlands.model",
            critical=True,
            fix=diagnostic_fix(
                "Repair the pyBadlands package installation so from badlands.model import Model works"
            ),
        )

    passed = sum(1 for c in checks if c["status"] == "pass")
    failed = sum(1 for c in checks if c["status"] != "pass")
    print()
    print(f"Results: {passed} passed, {failed} failed")
    if failed:
        print(f"STATUS: PREFLIGHT FAILED. Check {TRIPLETS} first for known recovery steps.")
    else:
        print("STATUS: PREFLIGHT PASSED. The model package and KI files are ready.")
    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
