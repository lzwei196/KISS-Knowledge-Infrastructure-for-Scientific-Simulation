#!/usr/bin/env python3
"""Preflight check for the FATES Knowledge Infrastructure."""

import json
import os
import subprocess
import sys
from pathlib import Path


MODEL_ID = "FATES"
KI_DIR = Path(__file__).resolve().parent
TRIPLETS = KI_DIR / "diagnostics" / "triplets.yaml"
PYTHON_ENV = Path("KISSPATH_PYTHON_ENV/bin/python")
FATES_BINARY = Path("KISSPATH_HOME/cesm/scratch/test_fates/bld/cesm.exe")

REQUIRED_TOOLS = [
    KI_DIR / "tools" / "convert_fates_params.py",
    KI_DIR / "tools" / "convert_surface_data.py",
    KI_DIR / "tools" / "convert_forcing_data.py",
    KI_DIR / "tools" / "run_fates_case.py",
    KI_DIR / "tools" / "parse_fates_output.py",
]

REQUIRED_KI_FILES = [
    KI_DIR / "SKILL.md",
    KI_DIR / "knowledge_infrastructure.yaml",
    KI_DIR / "dag.yaml",
    KI_DIR / "docs" / "format_spec.yaml",
    TRIPLETS,
]

REQUIRED_IMPORTS = [
    "numpy",
    "pandas",
    "xarray",
    "netCDF4",
    "matplotlib",
    "scipy",
    "yaml",
]


def fix_text(message):
    return f"{message}; then check {TRIPLETS} for known FATES/CTSM recovery triplets."


def add_check(checks, kind, subject, critical, ok, fix="", detail=None):
    check = {
        "kind": kind,
        "subject": str(subject),
        "critical": bool(critical),
        "status": "pass" if ok else "fail",
        "fix": "" if ok else fix_text(fix or f"Fix {subject}"),
    }
    if detail:
        check["detail"] = detail
    checks.append(check)
    prefix = "OK" if ok else "FAIL"
    print(f"  {prefix:<5} {kind}: {subject}")
    if detail:
        print(f"        {detail}")
    if not ok:
        print(f"        Fix: {check['fix']}")
    return ok


def check_file(checks, path, label, critical=True, executable=False):
    exists = path.is_file()
    executable_ok = True if not executable else os.access(path, os.X_OK)
    ok = exists and executable_ok
    if exists and executable:
        subject = os.path.realpath(path)
    else:
        subject = path
    if not exists:
        fix = f"Restore or rebuild required file: {path}"
    elif not executable_ok:
        fix = f"Make executable with: chmod +x {path}"
    else:
        fix = ""
    detail = label
    return add_check(checks, "binary" if executable else "data", subject,
                     critical, ok, fix, detail)


def check_directory(checks, path, label, critical=True):
    ok = path.is_dir() and any(path.iterdir())
    detail = label
    if path.is_dir():
        detail = f"{label}; {len(list(path.iterdir()))} entries"
    return add_check(
        checks, "data", path, critical, ok,
        f"Restore required non-empty directory: {path}", detail)


def run_command(cmd, timeout=10, cwd=None):
    try:
        return subprocess.run(
            cmd, cwd=cwd, text=True, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        return exc
    except OSError as exc:
        return exc


def check_ldd(checks, binary):
    if not binary.is_file():
        return add_check(
            checks, "binary", binary, True, False,
            f"Cannot inspect libraries until binary exists: {binary}",
            "shared-library resolution")

    result = run_command(["ldd", str(binary)], timeout=10)
    if isinstance(result, subprocess.CompletedProcess):
        output = (result.stdout or "") + (result.stderr or "")
        missing = [line.strip() for line in output.splitlines()
                   if "not found" in line]
        ok = result.returncode == 0 and not missing
        detail = "all shared libraries resolved"
        if missing:
            detail = "; ".join(missing[:3])
        return add_check(
            checks, "binary", os.path.realpath(binary), True, ok,
            "Install or expose the missing CESM/FATES shared libraries in LD_LIBRARY_PATH",
            detail)

    return add_check(
        checks, "binary", os.path.realpath(binary), True, False,
        f"Unable to run ldd for {binary}: {result}",
        "shared-library resolution")


def check_binary_starts(checks, binary):
    if not binary.is_file() or not os.access(binary, os.X_OK):
        return add_check(
            checks, "run", binary, True, False,
            f"Rebuild executable before probing startup: {binary}",
            "cheap startup probe")

    result = run_command([str(binary), "--help"], timeout=5, cwd=KI_DIR)
    subject = os.path.realpath(binary)
    if isinstance(result, subprocess.TimeoutExpired):
        return add_check(
            checks, "run", subject, True, False,
            "The executable did not reach startup within 5s; verify it runs in its CTSM case directory",
            "cheap startup probe timed out")
    if isinstance(result, OSError):
        return add_check(
            checks, "run", subject, True, False,
            f"Executable could not be started: {result}",
            "cheap startup probe")

    output = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
    expected_case_error = "Cannot open file 'drv_in'" in output
    ok = result.returncode == 0 or expected_case_error
    detail = "started and reached CESM runtime input handling"
    if not ok:
        detail = f"exit {result.returncode}; {(output[:240] or 'no output')}"
    return add_check(
        checks, "run", subject, True, ok,
        "Run from a prepared CTSM/CIME case directory and inspect diagnostics/triplets.yaml",
        detail)


def check_imports(checks):
    if not PYTHON_ENV.is_file():
        return add_check(
            checks, "import", PYTHON_ENV, True, False,
            f"Restore HydroCraft Python interpreter: {PYTHON_ENV}",
            "required interpreter for KI tools")

    add_check(
        checks, "import", PYTHON_ENV, True,
        os.access(PYTHON_ENV, os.X_OK),
        f"Make HydroCraft Python executable: chmod +x {PYTHON_ENV}",
        "required interpreter for KI tools")

    code = (
        "import importlib, json\n"
        f"mods = {REQUIRED_IMPORTS!r}\n"
        "out = {}\n"
        "for mod in mods:\n"
        "    try:\n"
        "        importlib.import_module(mod)\n"
        "        out[mod] = 'pass'\n"
        "    except Exception as exc:\n"
        "        out[mod] = type(exc).__name__ + ': ' + str(exc)\n"
        "print(json.dumps(out, sort_keys=True))\n"
    )
    result = run_command([str(PYTHON_ENV), "-c", code], timeout=20, cwd=KI_DIR)
    if not isinstance(result, subprocess.CompletedProcess) or result.returncode != 0:
        detail = result if not isinstance(result, subprocess.CompletedProcess) else (result.stderr or result.stdout)
        return add_check(
            checks, "import", PYTHON_ENV, True, False,
            "Repair KISSPATH_PYTHON_ENV and install KI dependencies",
            f"import probe failed: {str(detail)[:240]}")

    statuses = json.loads(result.stdout)
    for module, status in statuses.items():
        ok = status == "pass"
        add_check(
            checks, "import", f"{PYTHON_ENV}:{module}", True, ok,
            f"Install {module} into {PYTHON_ENV}: {PYTHON_ENV} -m pip install {module}",
            "HydroCraft Python dependency" if ok else status)


def check_tool_compilation(checks):
    for tool in REQUIRED_TOOLS:
        if not tool.is_file():
            add_check(
                checks, "data", tool, True, False,
                f"Restore required KI tool: {tool}", "tool script")
            continue
        result = run_command(
            [str(PYTHON_ENV), "-m", "py_compile", str(tool)],
            timeout=20, cwd=KI_DIR)
        ok = isinstance(result, subprocess.CompletedProcess) and result.returncode == 0
        detail = "py_compile passed"
        if not ok:
            if isinstance(result, subprocess.CompletedProcess):
                detail = (result.stderr or result.stdout or "compile failed")[:240]
            else:
                detail = str(result)[:240]
        add_check(
            checks, "import", tool, True, ok,
            f"Fix syntax/import-time issue in KI tool: {tool}",
            detail)


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}, sort_keys=True))
    sys.exit(0 if all(c["status"] == "pass" or not c.get("critical") for c in checks) else 1)


def main():
    checks = []
    print(f"{' PREFLIGHT: FATES ':=^60}")
    print("  Recovery reference: diagnostics/triplets.yaml")
    print()

    check_directory(checks, KI_DIR / "tools", "KI tools directory", critical=True)
    for path in REQUIRED_KI_FILES:
        check_file(checks, path, f"required KI file: {path.relative_to(KI_DIR)}", critical=True)

    check_file(checks, FATES_BINARY, "FATES/CTSM host executable", critical=True, executable=True)
    check_ldd(checks, FATES_BINARY)
    check_binary_starts(checks, FATES_BINARY)
    check_imports(checks)
    check_tool_compilation(checks)

    failed = [c for c in checks if c["status"] == "fail"]
    print()
    print(f"  Results: {len(checks) - len(failed)} passed, {len(failed)} failed")
    if failed:
        print(f"  STATUS: PREFLIGHT FAILED - check {TRIPLETS} for recovery guidance")
    else:
        print("  STATUS: PREFLIGHT PASSED - FATES/CTSM executable and KI tools are available")
    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
