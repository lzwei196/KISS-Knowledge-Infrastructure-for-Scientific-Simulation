#!/usr/bin/env python3
"""Preflight check for the TRIGRS Knowledge Infrastructure."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


MODEL_ID = "TRIGRS"
KI_DIR = Path(__file__).resolve().parent
MODEL_DIR = KI_DIR.parent
PYTHON_ENV = Path("KISSPATH_PYTHON_ENV/bin/python")
TRIGRS_BINARY = MODEL_DIR / "bin" / "trg"
TRIGRS_SOURCE_DIR = MODEL_DIR / "source" / "repo" / "source" / "trigrs_full" / "src" / "TRIGRS"
TOPOINDEX_BINARY = MODEL_DIR / "source" / "repo" / "source" / "trigrs_full" / "src" / "TopoIndex" / "tpx"
TRIPLETS = KI_DIR / "diagnostics" / "triplets.yaml"


def recovery_hint(detail):
    return f"{detail}; check {TRIPLETS} for matching diagnostics and recovery steps"


def add_check(checks, kind, subject, critical, passed, fix=""):
    check = {
        "kind": kind,
        "subject": str(subject),
        "critical": bool(critical),
        "status": "pass" if passed else "fail",
        "fix": "" if passed else fix,
    }
    checks.append(check)
    label = "OK" if passed else ("FAIL" if critical else "WARN")
    print(f"  {label:<5} {kind}: {subject}")
    if not passed and fix:
        print(f"        Fix: {fix}")
    return passed


def check_file(checks, path, label, critical=True, executable=False):
    path = Path(path)
    subject = path if not executable or not path.exists() else path.resolve()
    if not path.is_file():
        return add_check(
            checks,
            "data",
            subject,
            critical,
            False,
            recovery_hint(f"{label} not found at {path}"),
        )
    if executable and not os.access(path, os.X_OK):
        return add_check(
            checks,
            "binary",
            path.resolve(),
            critical,
            False,
            recovery_hint(f"{label} exists but is not executable; run chmod +x {path}"),
        )
    return add_check(checks, "binary" if executable else "data", subject, critical, True)


def check_dir(checks, path, label, critical=True, require_nonempty=True):
    path = Path(path)
    if not path.is_dir():
        return add_check(
            checks,
            "data",
            path,
            critical,
            False,
            recovery_hint(f"{label} directory not found at {path}"),
        )
    if require_nonempty and not any(path.iterdir()):
        return add_check(
            checks,
            "data",
            path,
            critical,
            False,
            recovery_hint(f"{label} directory is empty at {path}"),
        )
    return add_check(checks, "data", path, critical, True)


def check_import_with_env(checks, module, critical=True):
    python = PYTHON_ENV if PYTHON_ENV.exists() else Path(sys.executable)
    result = subprocess.run(
        [str(python), "-c", f"import {module}"],
        capture_output=True,
        text=True,
        timeout=20,
    )
    return add_check(
        checks,
        "import",
        f"{python}: import {module}",
        critical,
        result.returncode == 0,
        recovery_hint(
            f"install {module.split('.')[0]} in {python}'s environment; stderr: {result.stderr.strip()[:300]}"
        ),
    )


def check_py_compile(checks):
    python = PYTHON_ENV if PYTHON_ENV.exists() else Path(sys.executable)
    tool_files = sorted((KI_DIR / "tools").glob("*.py"))
    if not tool_files:
        return add_check(
            checks,
            "data",
            KI_DIR / "tools",
            True,
            False,
            recovery_hint("no KI tool Python files found"),
        )
    result = subprocess.run(
        [str(python), "-m", "py_compile", *map(str, tool_files)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    return add_check(
        checks,
        "import",
        f"{python}: py_compile tools/*.py",
        True,
        result.returncode == 0,
        recovery_hint(f"fix Python syntax/import-time compile error; stderr: {result.stderr.strip()[:500]}"),
    )


def check_binary_starts(checks, binary):
    binary = Path(binary).resolve()
    try:
        result = subprocess.run(
            [str(binary)],
            cwd=tempfile.gettempdir(),
            input="\n",
            capture_output=True,
            text=True,
            timeout=3,
        )
    except subprocess.TimeoutExpired as exc:
        output = (exc.stdout or "") + (exc.stderr or "")
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="replace")
        passed = "TRIGRS" in output
        return add_check(
            checks,
            "run",
            binary,
            True,
            passed,
            recovery_hint("TRIGRS binary timed out before printing its startup banner"),
        )
    except OSError as exc:
        return add_check(
            checks,
            "run",
            binary,
            True,
            False,
            recovery_hint(f"TRIGRS binary could not be started: {exc}"),
        )

    output = (result.stdout or "") + (result.stderr or "")
    passed = "TRIGRS: Transient Rainfall Infiltration" in output
    fix = recovery_hint(
        f"TRIGRS binary did not print the expected startup banner; returncode={result.returncode}; output={output[:500]!r}"
    )
    return add_check(checks, "run", binary, True, passed, fix)


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}, sort_keys=True))
    sys.exit(0 if all(c["status"] == "pass" or not c.get("critical") for c in checks) else 1)


def main():
    checks = []
    print(f"{' PREFLIGHT: TRIGRS ':=^60}")
    print(f"  KI directory: {KI_DIR}")
    print(f"  Recovery diagnostics: {TRIPLETS}")
    print()

    check_file(checks, KI_DIR / "SKILL.md", "SKILL.md")
    check_file(checks, KI_DIR / "knowledge_infrastructure.yaml", "knowledge_infrastructure.yaml")
    check_file(checks, KI_DIR / "dag.yaml", "dag.yaml")
    check_file(checks, TRIPLETS, "diagnostic triplets")

    check_dir(checks, KI_DIR / "tools", "KI tools")
    for tool in (
        "convert_rainfall_to_trigrs.py",
        "convert_soil_to_trigrs.py",
        "generate_tr_in.py",
        "parse_trigrs_output.py",
        "run_trigrs.py",
    ):
        check_file(checks, KI_DIR / "tools" / tool, f"tool {tool}")

    check_import_with_env(checks, "numpy")
    check_py_compile(checks)

    check_file(checks, TRIGRS_SOURCE_DIR / "Makefile", "TRIGRS source Makefile")
    check_dir(checks, TRIGRS_SOURCE_DIR, "TRIGRS source")
    check_file(checks, TRIGRS_BINARY, "TRIGRS serial binary", executable=True)
    check_binary_starts(checks, TRIGRS_BINARY)
    check_file(checks, TOPOINDEX_BINARY, "TopoIndex companion binary", critical=False, executable=True)

    print()
    passed = sum(1 for c in checks if c["status"] == "pass")
    failed = len(checks) - passed
    critical_failed = sum(1 for c in checks if c["critical"] and c["status"] == "fail")
    print(f"  Results: {passed} passed, {failed} failed, {critical_failed} critical failed")
    if critical_failed:
        print(f"  STATUS: PREFLIGHT FAILED - fix blockers above; start with {TRIPLETS}")
    else:
        print("  STATUS: PREFLIGHT PASSED - ready for model execution")
    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
