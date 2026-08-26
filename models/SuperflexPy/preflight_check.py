#!/usr/bin/env python3
"""Contract-compliant preflight check for the SuperflexPy KI."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


MODEL_ID = "SuperflexPy"
KI_DIR = Path(__file__).resolve().parent
DIAGNOSTICS = KI_DIR / "diagnostics" / "triplets.yaml"
DIAGNOSTIC_FIX = f"Check {DIAGNOSTICS} for known recovery steps."

HYDROCRAFT_PYTHON = Path("KISSPATH_PYTHON_ENV/bin/python")
WORK_PYTHON = Path(
    "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/SuperflexPy/venv/bin/python"
)

CHECKS = []


def add_check(kind, subject, critical, status, fix=""):
    check = {
        "kind": kind,
        "subject": str(subject),
        "critical": bool(critical),
        "status": status,
        "fix": "" if status == "pass" else fix,
    }
    CHECKS.append(check)
    label = "OK" if status == "pass" else "FAIL"
    print(f"  {label:<5} {kind}: {subject}")
    if status != "pass" and fix:
        print(f"        Fix: {fix}")
    return status == "pass"


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}))
    ready = checks and all(c["status"] == "pass" or not c.get("critical") for c in checks)
    sys.exit(0 if ready else 1)


def run_command(argv, timeout=10, cwd=KI_DIR):
    return subprocess.run(
        [str(a) for a in argv],
        cwd=str(cwd),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )


def python_imports_superflexpy(python_exe):
    if not python_exe.is_file() or not os.access(python_exe, os.X_OK):
        return False
    try:
        result = run_command(
            [python_exe, "-c", "import superflexpy; print(superflexpy.__file__)"],
            timeout=8,
        )
    except Exception:
        return False
    return result.returncode == 0


def select_python():
    # Per KI policy, prefer the HydroCraft shared env when it actually contains
    # SuperflexPy. Current KI state uses the SuperflexPy work venv.
    for candidate in (HYDROCRAFT_PYTHON, WORK_PYTHON):
        if python_imports_superflexpy(candidate):
            return candidate
    return HYDROCRAFT_PYTHON if HYDROCRAFT_PYTHON.exists() else WORK_PYTHON


def check_python_binary(python_exe):
    subject = Path(os.path.realpath(python_exe))
    if not python_exe.is_file():
        return add_check(
            "binary",
            subject,
            True,
            "fail",
            f"Restore or install the Python environment for SuperflexPy. {DIAGNOSTIC_FIX}",
        )
    if not os.access(python_exe, os.X_OK):
        return add_check(
            "binary",
            subject,
            True,
            "fail",
            f"Make the interpreter executable: chmod +x {python_exe}. {DIAGNOSTIC_FIX}",
        )
    try:
        result = run_command([python_exe, "-c", "import sys; print(sys.executable)"], timeout=5)
    except Exception as exc:
        return add_check(
            "binary",
            subject,
            True,
            "fail",
            f"Interpreter did not start: {exc}. {DIAGNOSTIC_FIX}",
        )
    return add_check(
        "binary",
        subject,
        True,
        "pass" if result.returncode == 0 else "fail",
        f"Interpreter failed to start: {result.stderr.strip() or result.stdout.strip()}. {DIAGNOSTIC_FIX}",
    )


def check_import(python_exe, module, critical=True):
    code = f"import {module}; print(getattr({module.split('.')[0]}, '__file__', 'builtin'))"
    try:
        result = run_command([python_exe, "-c", code], timeout=10)
    except Exception as exc:
        result = None
        detail = str(exc)
    else:
        detail = result.stderr.strip() or result.stdout.strip()
    status = "pass" if result is not None and result.returncode == 0 else "fail"
    return add_check(
        "import",
        module,
        critical,
        status,
        f"Install/import {module} in {python_exe}: {detail}. {DIAGNOSTIC_FIX}",
    )


def check_superflexpy_api(python_exe):
    code = """
from superflexpy.framework.unit import Unit
from superflexpy.implementation.elements.gr4j import (
    FluxAggregator, InterceptionFilter, ProductionStore, RoutingStore,
    UnitHydrograph1, UnitHydrograph2,
)
from superflexpy.implementation.elements.structure_elements import Junction, Splitter, Transparent
from superflexpy.implementation.numerical_approximators.implicit_euler import ImplicitEulerPython
from superflexpy.implementation.root_finders.pegasus import PegasusPython
print("superflexpy gr4j api ok")
"""
    try:
        result = run_command([python_exe, "-c", code], timeout=12)
    except Exception as exc:
        result = None
        detail = str(exc)
    else:
        detail = result.stderr.strip() or result.stdout.strip()
    status = "pass" if result is not None and result.returncode == 0 else "fail"
    return add_check(
        "import",
        "superflexpy GR4J framework/API modules",
        True,
        status,
        f"Repair the SuperflexPy install used by {python_exe}: {detail}. {DIAGNOSTIC_FIX}",
    )


def check_file(path, critical=True, executable=False, kind="data"):
    path = Path(path)
    if not path.is_file():
        return add_check(kind, path, critical, "fail", f"Restore required file {path}. {DIAGNOSTIC_FIX}")
    if executable and not os.access(path, os.X_OK):
        return add_check(kind, path, critical, "fail", f"Make {path} executable. {DIAGNOSTIC_FIX}")
    return add_check(kind, path, critical, "pass")


def check_tool_help(python_exe, tool):
    tool_path = KI_DIR / tool
    if not check_file(tool_path, critical=True, kind="data"):
        return False
    try:
        result = run_command([python_exe, tool_path, "--help"], timeout=8)
    except Exception as exc:
        result = None
        detail = str(exc)
    else:
        detail = result.stderr.strip() or result.stdout.strip()
    status = "pass" if result is not None and result.returncode == 0 else "fail"
    return add_check(
        "run",
        tool_path,
        True,
        status,
        f"Tool does not start with {python_exe}: {detail[:500]}. {DIAGNOSTIC_FIX}",
    )


def check_tiny_model_run(python_exe):
    tool_path = KI_DIR / "tools" / "run_superflexpy.py"
    with tempfile.TemporaryDirectory(prefix="superflexpy_preflight_") as tmp:
        tmp_path = Path(tmp)
        forcing = tmp_path / "forcing.json"
        output = tmp_path / "output.json"
        forcing.write_text(
            json.dumps(
                {
                    "status": "success",
                    "P": [1.0, 0.0, 2.0, 0.0, 1.0],
                    "PET": [0.2, 0.3, 0.2, 0.4, 0.3],
                }
            ),
            encoding="utf-8",
        )
        try:
            result = run_command(
                [
                    python_exe,
                    tool_path,
                    "--model",
                    "gr4j",
                    "--forcing",
                    forcing,
                    "--output",
                    output,
                ],
                timeout=20,
            )
        except Exception as exc:
            result = None
            detail = str(exc)
        else:
            detail = (result.stderr + "\n" + result.stdout).strip()
        ok = False
        if result is not None and result.returncode == 0 and output.is_file():
            try:
                data = json.loads(output.read_text(encoding="utf-8"))
            except Exception as exc:
                detail = f"{detail}\nOutput JSON parse failed: {exc}"
            else:
                ok = data.get("status") == "success" and len(data.get("Q_sim", [])) == 5
                if not ok:
                    detail = f"{detail}\nUnexpected output: {data}"
        return add_check(
            "run",
            "tools/run_superflexpy.py gr4j smoke run",
            True,
            "pass" if ok else "fail",
            f"Fix SuperflexPy execution through {tool_path}: {detail[:700]}. {DIAGNOSTIC_FIX}",
        )


def main():
    print("=" * 60)
    print(f"  PREFLIGHT CHECK: {MODEL_ID}")
    print("=" * 60)

    python_exe = select_python()
    check_python_binary(python_exe)

    check_import(python_exe, "superflexpy", critical=True)
    check_import(python_exe, "numpy", critical=True)
    check_import(python_exe, "numba", critical=False)
    check_superflexpy_api(python_exe)

    for required in (
        "SKILL.md",
        "knowledge_infrastructure.yaml",
        "dag.yaml",
        "docs/format_spec.yaml",
        "diagnostics/triplets.yaml",
    ):
        check_file(KI_DIR / required, critical=True, kind="data")

    for tool in (
        "tools/convert_forcing.py",
        "tools/convert_parameters.py",
        "tools/parse_output.py",
        "tools/run_superflexpy.py",
    ):
        check_tool_help(python_exe, tool)

    check_tiny_model_run(python_exe)

    failed = [c for c in CHECKS if c["status"] != "pass"]
    print()
    print(f"  Results: {len(CHECKS) - len(failed)} passed, {len(failed)} failed")
    if failed:
        print(f"  STATUS: PREFLIGHT FAILED. {DIAGNOSTIC_FIX}")
    else:
        print("  STATUS: PREFLIGHT PASSED")
    emit_report(MODEL_ID, CHECKS)


if __name__ == "__main__":
    main()
