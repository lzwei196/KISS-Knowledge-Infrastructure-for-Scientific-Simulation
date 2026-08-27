#!/usr/bin/env python3
"""Preflight check for the LISFLOOD Knowledge Infrastructure.

This script checks the installed LISFLOOD runtime and KI-local support files
before model execution. It always emits the KDT preflight JSON report as the
last line of output.
"""

import json
import os
import py_compile
import subprocess
import sys
from pathlib import Path


MODEL_ID = "LISFLOOD"
KI_DIR = Path(__file__).resolve().parent
MANIFEST = KI_DIR / "knowledge_infrastructure.yaml"
DIAGNOSTICS = KI_DIR / "diagnostics" / "triplets.yaml"
DEFAULT_BINARY = Path("KISSPATH_HOME/miniconda3/envs/lisflood/bin/lisflood")
IMPORT_MODULES = [
    "lisflood",
    "netCDF4",
    "numpy",
    "numba",
    "pcraster",
    "xarray",
    "pandas",
    "lxml",
    "bs4",
]
KI_FILES = [
    "SKILL.md",
    "knowledge_infrastructure.yaml",
    "dag.yaml",
    "diagnostics/triplets.yaml",
    "tools/run_lisflood.py",
    "tools/convert_forcing.py",
    "tools/convert_soil_params.py",
    "tools/parse_output.py",
]


def diagnostic_fix(message):
    return f"{message}; then check {DIAGNOSTICS} for matching recovery triplets."


def add_check(checks, kind, subject, critical, ok, fix=""):
    checks.append(
        {
            "kind": kind,
            "subject": str(subject),
            "critical": bool(critical),
            "status": "pass" if ok else "fail",
            "fix": "" if ok else fix,
        }
    )


def emit_report(model_id, checks):
    failed = [c for c in checks if c["status"] == "fail"]
    critical_failed = [c for c in failed if c.get("critical")]
    if failed:
        print()
        print("Fixes for failed checks:")
        for c in failed:
            print(f"  - {c['kind']} {c['subject']}: {c['fix']}")
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}))
    sys.exit(1 if critical_failed else 0)


def manifest_binary_path():
    if not MANIFEST.is_file():
        return DEFAULT_BINARY

    in_binary = False
    for raw in MANIFEST.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if stripped == "binary:":
            in_binary = True
            continue
        if in_binary and stripped.startswith("path:"):
            value = stripped.split(":", 1)[1].strip().strip("'\"")
            return Path(value) if value else DEFAULT_BINARY
        if in_binary and raw and not raw.startswith(" "):
            break
    return DEFAULT_BINARY


def check_required_files(checks):
    for relpath in KI_FILES:
        path = KI_DIR / relpath
        add_check(
            checks,
            "data",
            path,
            relpath != "diagnostics/triplets.yaml",
            path.is_file(),
            diagnostic_fix(f"Restore or regenerate required KI file {path}"),
        )


def check_tool_syntax(checks):
    for relpath in KI_FILES:
        if not relpath.endswith(".py"):
            continue
        path = KI_DIR / relpath
        if not path.is_file():
            continue
        try:
            py_compile.compile(str(path), doraise=True)
            add_check(checks, "import", path, False, True)
        except py_compile.PyCompileError as exc:
            add_check(
                checks,
                "import",
                path,
                False,
                False,
                diagnostic_fix(f"Fix Python syntax error in {path}: {exc.msg}"),
            )


def check_binary(checks, binary):
    binary_realpath = Path(os.path.realpath(binary)) if binary.exists() else binary
    ok = binary.is_file() and os.access(binary, os.X_OK)
    add_check(
        checks,
        "binary",
        binary_realpath,
        True,
        ok,
        diagnostic_fix(f"Install LISFLOOD or chmod +x the executable at {binary}"),
    )
    return binary_realpath, ok


def run_env_python(binary):
    if binary.is_file():
        try:
            first = binary.read_text(encoding="utf-8", errors="ignore").splitlines()[0]
            if first.startswith("#!"):
                interpreter = Path(first[2:].strip().split()[0])
                if interpreter.is_file():
                    return interpreter
        except OSError:
            pass
    fallback = binary.parent / "python"
    return fallback if fallback.is_file() else None


def check_runtime_imports(checks, python_exe):
    if not python_exe:
        for module in IMPORT_MODULES:
            add_check(
                checks,
                "import",
                module,
                True,
                False,
                diagnostic_fix("Cannot run LISFLOOD import checks because the environment Python was not found"),
            )
        return

    for module in IMPORT_MODULES:
        snippet = f"import {module}; print(getattr({module}, '__file__', 'built-in'))"
        result = subprocess.run(
            [str(python_exe), "-c", snippet],
            cwd=str(KI_DIR),
            capture_output=True,
            text=True,
            timeout=30,
        )
        ok = result.returncode == 0
        subject = f"{python_exe}:import {module}"
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        last_line = detail[-1] if detail else ""
        fix = diagnostic_fix(
            f"Repair package {module} in {python_exe.parent.parent}; last error: {last_line}"
        )
        add_check(checks, "import", subject, True, ok, fix)


def check_binary_starts(checks, binary):
    if not (binary.is_file() and os.access(binary, os.X_OK)):
        return

    result = subprocess.run(
        [str(binary), "--help"],
        cwd=str(KI_DIR),
        capture_output=True,
        text=True,
        timeout=30,
    )
    output = (result.stderr or result.stdout or "").strip().splitlines()
    last_line = output[-1] if output else f"exit code {result.returncode}"
    ok = result.returncode == 0
    add_check(
        checks,
        "run",
        f"{Path(os.path.realpath(binary))} --help",
        True,
        ok,
        diagnostic_fix(f"Make the LISFLOOD CLI start cleanly; last error: {last_line}"),
    )


def main():
    checks = []
    binary = manifest_binary_path()

    print(f"{' PREFLIGHT: LISFLOOD ':=^60}")
    print(f"KI directory: {KI_DIR}")
    print(f"Diagnostics: {DIAGNOSTICS}")
    print(f"Executable from manifest: {binary}")

    check_required_files(checks)
    check_tool_syntax(checks)
    _, binary_ok = check_binary(checks, binary)

    python_exe = run_env_python(binary) if binary_ok else None
    if python_exe:
        add_check(checks, "binary", python_exe, True, True)
    else:
        add_check(
            checks,
            "binary",
            binary.parent / "python",
            True,
            False,
            diagnostic_fix("Restore the LISFLOOD environment Python next to the executable"),
        )

    check_runtime_imports(checks, python_exe)
    check_binary_starts(checks, binary)

    passed = sum(1 for c in checks if c["status"] == "pass")
    failed = len(checks) - passed
    print(f"Results: {passed} passed, {failed} failed")
    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
