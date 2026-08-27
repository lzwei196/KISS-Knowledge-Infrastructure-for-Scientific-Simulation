#!/usr/bin/env python3
"""Contract preflight check for the GEOPHIRES knowledge infrastructure."""

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path


MODEL_ID = "GEOPHIRES"
KI_DIR = Path(__file__).resolve().parent
DIAGNOSTICS = KI_DIR / "diagnostics" / "triplets.yaml"
HYDROCRAFT_DB = Path("KISSPATH_ROOT/hydrocraft.db")
HYDROCRAFT_PYTHON = Path("KISSPATH_PYTHON_ENV/bin/python")
REQUIRED_PACKAGE = "geophires_x"

REQUIRED_FILES = [
    KI_DIR / "SKILL.md",
    KI_DIR / "knowledge_infrastructure.yaml",
    KI_DIR / "dag.yaml",
    DIAGNOSTICS,
    KI_DIR / "docs" / "format_spec.yaml",
]

REQUIRED_TOOLS = [
    KI_DIR / "tools" / "convert_reservoir_params.py",
    KI_DIR / "tools" / "convert_site_economics.py",
    KI_DIR / "tools" / "generate_input_file.py",
    KI_DIR / "tools" / "run_geophires.py",
    KI_DIR / "tools" / "parse_geophires_output.py",
    KI_DIR / "tools" / "validate_geophires_results.py",
]


def diagnostic_fix(action):
    return f"{action}; then check {DIAGNOSTICS} for matching recovery triplets."


def add_check(checks, kind, subject, critical, status, fix=""):
    checks.append(
        {
            "kind": kind,
            "subject": str(subject),
            "critical": bool(critical),
            "status": status,
            "fix": fix,
        }
    )


def absolute_path(path):
    return Path(os.path.abspath(path))


def is_executable_file(path):
    return path.is_file() and os.access(path, os.X_OK)


def db_binary_path(model_id):
    if not HYDROCRAFT_DB.is_file():
        return None

    try:
        conn = sqlite3.connect(f"file:{HYDROCRAFT_DB}?mode=ro", uri=True, timeout=5)
        try:
            row = conn.execute(
                """
                SELECT binary_path
                FROM models
                WHERE lower(id) = lower(?) OR lower(name) = lower(?)
                LIMIT 1
                """,
                (model_id, model_id),
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return None

    if not row or not row[0]:
        return None
    return Path(row[0])


def python_candidates_from_binary_path(binary_path):
    """Prefer the venv attached to the DB model binary/work path."""
    candidates = []
    path = Path(binary_path)

    if path.name.startswith("python"):
        candidates.append(path)

    if path.suffix == "" or path.is_dir():
        candidates.append(path / "venv" / "bin" / "python")

    cursor = path if path.is_dir() else path.parent
    for parent in (cursor, *cursor.parents):
        candidates.append(parent / "venv" / "bin" / "python")
        if parent.name == "_work":
            break

    seen = set()
    unique = []
    for candidate in candidates:
        key = str(candidate)
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def module_installed(python_path, module):
    if not is_executable_file(python_path):
        return False

    try:
        result = subprocess.run(
            [
                str(python_path),
                "-c",
                (
                    "import importlib.util, sys; "
                    f"sys.exit(0 if importlib.util.find_spec({module!r}) else 1)"
                ),
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except Exception:
        return False
    return result.returncode == 0


def select_model_python(model_id, module):
    candidates = []

    binary_path = db_binary_path(model_id)
    if binary_path:
        candidates.extend(python_candidates_from_binary_path(binary_path))
        for candidate in candidates:
            if is_executable_file(candidate):
                return absolute_path(candidate)

    ki_python = KI_DIR / "venv" / "bin" / "python"
    if is_executable_file(ki_python):
        return absolute_path(ki_python)

    if module_installed(HYDROCRAFT_PYTHON, module):
        return absolute_path(HYDROCRAFT_PYTHON)

    if candidates:
        return absolute_path(candidates[0])
    return absolute_path(ki_python)


def check_file(checks, path, label, critical=True):
    if path.is_file():
        print(f"  OK    {label}: {path}")
        add_check(checks, "data", path, critical, "pass")
        return True

    fix = diagnostic_fix(f"Restore required KI file {path}")
    print(f"  FAIL  {label}: NOT FOUND at {path}")
    print(f"         Fix: {fix}")
    add_check(checks, "data", path, critical, "fail", fix)
    return False


def check_python_binary(checks, python_path):
    subject = absolute_path(python_path)

    if not python_path.exists():
        fix = diagnostic_fix(
            f"Create or repair model runtime Python environment at {python_path}"
        )
        print(f"  FAIL  Model runtime Python: NOT FOUND at {python_path}")
        print(f"         Fix: {fix}")
        add_check(checks, "binary", subject, True, "fail", fix)
        return False

    if not os.access(python_path, os.X_OK):
        fix = diagnostic_fix(f"Make Python executable: chmod +x {python_path}")
        print(f"  FAIL  Model runtime Python: exists but is not executable: {python_path}")
        print(f"         Fix: {fix}")
        add_check(checks, "binary", subject, True, "fail", fix)
        return False

    try:
        result = subprocess.run(
            [str(python_path), "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception as exc:
        fix = diagnostic_fix(f"Repair Python executable {python_path}: {exc}")
        print(f"  FAIL  Model runtime Python: could not start {python_path}: {exc}")
        print(f"         Fix: {fix}")
        add_check(checks, "binary", subject, True, "fail", fix)
        return False

    version = (result.stdout or result.stderr).strip()
    if result.returncode == 0 and version:
        print(f"  OK    Model runtime Python: {python_path} ({version})")
        add_check(checks, "binary", subject, True, "pass")
        return True

    fix = diagnostic_fix(
        f"Repair Python executable {python_path}; --version exited {result.returncode}"
    )
    print(f"  FAIL  Model runtime Python: --version failed for {python_path}")
    print(f"         Fix: {fix}")
    add_check(checks, "binary", subject, True, "fail", fix)
    return False


def check_import(checks, python_path, module, label, critical=True):
    subject = f"{module} via {absolute_path(python_path)}"
    if not python_path.is_file() or not os.access(python_path, os.X_OK):
        fix = diagnostic_fix(
            f"Repair model runtime Python executable at {python_path} before checking {module}"
        )
        print(f"  FAIL  {label}: cannot import because Python is unavailable: {python_path}")
        print(f"         Fix: {fix}")
        add_check(checks, "import", subject, critical, "fail", fix)
        return False

    try:
        result = subprocess.run(
            [
                str(python_path),
                "-c",
                (
                    "import importlib, json; "
                    f"m = importlib.import_module({module!r}); "
                    "print(json.dumps({'file': getattr(m, '__file__', ''), "
                    "'version': getattr(m, '__version__', '')}))"
                ),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception as exc:
        fix = diagnostic_fix(f"Repair {label} import under {python_path}: {exc}")
        print(f"  FAIL  {label}: import check could not run: {exc}")
        print(f"         Fix: {fix}")
        add_check(checks, "import", subject, critical, "fail", fix)
        return False

    if result.returncode == 0:
        detail = result.stdout.strip()
        print(f"  OK    {label}: import {module} succeeded ({detail})")
        add_check(checks, "import", subject, critical, "pass")
        return True

    stderr = result.stderr.strip() or result.stdout.strip()
    fix = diagnostic_fix(
        f"Restore the approved GEOPHIRES-X runtime so {module} imports under {python_path}"
    )
    print(f"  FAIL  {label}: import {module} failed under {python_path}")
    if stderr:
        print(f"         stderr: {stderr[:500]}")
    print(f"         Fix: {fix}")
    add_check(checks, "import", subject, critical, "fail", fix)
    return False


def check_package_start(checks, python_path, module, label, critical=True):
    subject = f"{absolute_path(python_path)} -m {module} --help"
    if not python_path.is_file() or not os.access(python_path, os.X_OK):
        fix = diagnostic_fix(
            f"Repair model runtime Python executable at {python_path} before starting {module}"
        )
        print(f"  FAIL  {label}: cannot start because Python is unavailable: {python_path}")
        print(f"         Fix: {fix}")
        add_check(checks, "run", subject, critical, "fail", fix)
        return False

    try:
        result = subprocess.run(
            [str(python_path), "-m", module, "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception as exc:
        fix = diagnostic_fix(f"Repair {label} start check under {python_path}: {exc}")
        print(f"  FAIL  {label}: start check could not run: {exc}")
        print(f"         Fix: {fix}")
        add_check(checks, "run", subject, critical, "fail", fix)
        return False

    if result.returncode == 0:
        output_lines = (result.stdout or result.stderr).strip().splitlines()
        first_line = output_lines[0] if output_lines else "started successfully"
        print(f"  OK    {label}: {first_line}")
        add_check(checks, "run", subject, critical, "pass")
        return True

    stderr = result.stderr.strip() or result.stdout.strip()
    fix = diagnostic_fix(f"Repair GEOPHIRES-X CLI entrypoint for `{python_path} -m {module}`")
    print(f"  FAIL  {label}: `{python_path} -m {module} --help` exited {result.returncode}")
    if stderr:
        print(f"         stderr: {stderr[:1200]}")
    print(f"         Fix: {fix}")
    add_check(checks, "run", subject, critical, "fail", fix)
    return False


def check_tool_syntax(checks, python_path, tools):
    python_ready = python_path.is_file() and os.access(python_path, os.X_OK)

    for tool in tools:
        if not check_file(checks, tool, f"Tool file {tool.name}", critical=True):
            continue

        subject = tool.relative_to(KI_DIR)

        if not python_ready:
            fix = diagnostic_fix(
                f"Repair model runtime Python executable at {python_path}; then rerun py_compile for {tool}"
            )
            print(f"  FAIL  Tool syntax: {subject} (Python unavailable)")
            print(f"         Fix: {fix}")
            add_check(checks, "run", subject, True, "fail", fix)
            continue

        try:
            result = subprocess.run(
                [str(python_path), "-m", "py_compile", str(tool)],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except Exception as exc:
            fix = diagnostic_fix(f"Repair py_compile execution for {tool}: {exc}")
            print(f"  FAIL  Tool syntax: {subject}")
            print(f"         Fix: {fix}")
            add_check(checks, "run", subject, True, "fail", fix)
            continue

        if result.returncode == 0:
            print(f"  OK    Tool syntax: {subject}")
            add_check(checks, "run", subject, True, "pass")
        else:
            stderr = result.stderr.strip() or result.stdout.strip()
            fix = diagnostic_fix(f"Fix Python syntax/import-time error in {tool}")
            print(f"  FAIL  Tool syntax: {subject}")
            if stderr:
                print(f"         stderr: {stderr[:500]}")
            print(f"         Fix: {fix}")
            add_check(checks, "run", subject, True, "fail", fix)


def emit_report(model_id, checks):
    if not checks:
        checks.append(
            {
                "kind": "run",
                "subject": "preflight_check.py",
                "critical": True,
                "status": "fail",
                "fix": diagnostic_fix("Restore model-specific preflight checks"),
            }
        )

    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}))
    failed_critical = any(
        check["status"] != "pass" and check.get("critical") for check in checks
    )
    sys.exit(1 if failed_critical else 0)


def main():
    checks = []
    model_python = select_model_python(MODEL_ID, REQUIRED_PACKAGE)

    print(f"{' PREFLIGHT: GEOPHIRES ':=^60}")
    print()

    check_python_binary(checks, model_python)
    check_import(checks, model_python, REQUIRED_PACKAGE, "GEOPHIRES-X package")
    check_package_start(
        checks, model_python, REQUIRED_PACKAGE, "GEOPHIRES-X CLI start"
    )

    for required in REQUIRED_FILES:
        check_file(checks, required, f"Required file {required.relative_to(KI_DIR)}")

    check_tool_syntax(checks, model_python, REQUIRED_TOOLS)

    print()
    passed = sum(1 for check in checks if check["status"] == "pass")
    failed = len(checks) - passed
    print(f"  Results: {passed} passed, {failed} failed")
    if failed:
        print(f"  STATUS: PREFLIGHT FAILED - check fixes above and {DIAGNOSTICS}")
    else:
        print("  STATUS: PREFLIGHT PASSED - safe to proceed with model execution")

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
