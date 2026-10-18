#!/usr/bin/env python3
"""Preflight check for the EF5 Knowledge Infrastructure.

This script verifies the real EF5 executable, runtime loader environment,
HydroCraft Python imports, KI tool files, and recovery diagnostics before a run.
It always finishes with a PREFLIGHT_REPORT= JSON line for the KDT gate.
"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


MODEL_ID = "EF5"
KI_DIR = Path(__file__).resolve().parent
TRIPLETS = KI_DIR / "diagnostics" / "triplets.yaml"
# Interpreter whose imports are checked: KI_PYTHON if set, else the interpreter running this
# preflight (no host path pinned here; a missing interpreter is still a critical FAIL below).
# Relative paths are made absolute here (os.path.abspath keeps venv symlinks) because the import
# check below runs the interpreter with cwd=KI_DIR.
_KI_PYTHON = os.environ.get("KI_PYTHON")
_PY_PICK = (shutil.which(_KI_PYTHON) if _KI_PYTHON else None) or _KI_PYTHON or sys.executable or "python3"
PYTHON_ENV = Path(os.path.abspath(_PY_PICK) if (os.sep in _PY_PICK or os.path.exists(_PY_PICK)) else _PY_PICK)
# EF5 binary, looked for in this order (same list as tools/run_ef5.py BINARY_CANDIDATES):
#  1. managed engine install (server): bin/ef5 + lib/ with every non-system shared library it needs;
#     RUNPATH is $ORIGIN/../lib (libs: $ORIGIN), so no LD_LIBRARY_PATH is set here. Same path as
#     knowledge_infrastructure.yaml package.binary.path.
#  2. source build in the same engine folder (desktop: KISS builds EF5 from source to source/repo/bin/ef5).
# main() checks the first one that exists; if neither exists the binary check FAILS naming both.
EF5_BINARY = Path("KISSPATH_BINARIES/EF5/bin/ef5")
EF5_SOURCE_BUILD_BINARY = Path("KISSPATH_BINARIES/EF5/source/repo/bin/ef5")
EF5_BINARY_CANDIDATES = (EF5_BINARY, EF5_SOURCE_BUILD_BINARY)

REQUIRED_KI_FILES = [
    KI_DIR / "SKILL.md",
    KI_DIR / "knowledge_infrastructure.yaml",
    KI_DIR / "dag.yaml",
    KI_DIR / "docs" / "format_spec.yaml",
    TRIPLETS,
]

REQUIRED_TOOLS = [
    KI_DIR / "tools" / "prepare_basic_grids.py",
    KI_DIR / "tools" / "convert_forcing_to_ef5.py",
    KI_DIR / "tools" / "convert_params_to_ef5.py",
    KI_DIR / "tools" / "run_ef5.py",
    KI_DIR / "tools" / "parse_ef5_output.py",
]

REQUIRED_IMPORTS = [
    "numpy",
    "pandas",
    "rasterio",
    "yaml",
    "whitebox",
    "ki_tools_common.load_forcing",
    "ki_tools_common.metrics",
    "ki_tools_common.soil_utils",
    "ki_tools_common.cross_platform",
    "ki_tools_common.debug_framework",
]

def diagnostic_fix(message):
    return f"{message}; check {TRIPLETS} for known recovery triplets"


def add_check(checks, kind, subject, critical, status, fix=""):
    check = {
        "kind": kind,
        "subject": str(subject),
        "critical": bool(critical),
        "status": status,
        "fix": fix if status == "fail" else "",
    }
    checks.append(check)
    level = "OK" if status == "pass" else ("FAIL" if critical else "WARN")
    print(f"  {level:<5} {kind}: {subject}")
    if status == "fail" and fix:
        print(f"        Fix: {fix}")
    return status == "pass"


def emit_report(model_id, checks):
    report = {"model_id": model_id, "checks": checks}
    print("PREFLIGHT_REPORT=" + json.dumps(report, sort_keys=True))
    critical_failed = any(c["critical"] and c["status"] != "pass" for c in checks)
    sys.exit(1 if critical_failed else 0)


def check_file(checks, path, label, critical=True, executable=False, kind="data"):
    p = Path(path)
    subject = p.resolve() if p.exists() else p
    if not p.is_file():
        return add_check(
            checks,
            kind,
            subject,
            critical,
            "fail",
            diagnostic_fix(f"{label} is missing; restore or regenerate {p}"),
        )
    if executable and not os.access(p, os.X_OK):
        return add_check(
            checks,
            kind,
            p.resolve(),
            critical,
            "fail",
            diagnostic_fix(f"{label} exists but is not executable; run chmod +x {p}"),
        )
    return add_check(checks, kind, p.resolve(), critical, "pass")


def binary_check_file(path, checks):
    """check_file for the EF5 binary, path first.

    The path is the first argument so that the managed install path can be written as a literal
    string at the call site in main(); KISS (kiss_cli.runnable.declared) reads the binary a KI
    declares from calls whose first argument is such a literal string.
    """
    return check_file(checks, path, "EF5 binary", critical=True, executable=True, kind="binary")


def pick_binary():
    """First EF5_BINARY_CANDIDATES entry that exists, else None."""
    for c in EF5_BINARY_CANDIDATES:
        if c.is_file():
            return c
    return None


def check_dir(checks, path, label, critical=True):
    p = Path(path)
    if p.is_dir() and any(p.iterdir()):
        return add_check(checks, "data", p.resolve(), critical, "pass")
    state = "missing" if not p.is_dir() else "empty"
    return add_check(
        checks,
        "data",
        p.resolve() if p.exists() else p,
        critical,
        "fail",
        diagnostic_fix(f"{label} directory is {state}; restore the KI layout"),
    )


def run_command(cmd, timeout=20, env=None, cwd=None):
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            cwd=cwd,
        )
    except subprocess.TimeoutExpired as exc:
        completed = subprocess.CompletedProcess(cmd, -1, exc.stdout or "", exc.stderr or "")
        completed.timeout = True
        return completed
    except OSError as exc:
        return subprocess.CompletedProcess(cmd, -2, "", str(exc))


def check_import(checks, module):
    if not PYTHON_ENV.is_file():
        return add_check(
            checks,
            "import",
            f"{PYTHON_ENV} import {module}",
            True,
            "fail",
            diagnostic_fix(f"HydroCraft Python interpreter is missing at {PYTHON_ENV}"),
        )

    code = f"import {module}; print('ok')"
    result = run_command([str(PYTHON_ENV), "-c", code], timeout=20, cwd=str(KI_DIR))
    if result.returncode == 0:
        return add_check(checks, "import", f"{PYTHON_ENV} import {module}", True, "pass")
    detail = (result.stderr or result.stdout or "").strip().splitlines()
    reason = detail[-1] if detail else f"exit code {result.returncode}"
    return add_check(
        checks,
        "import",
        f"{PYTHON_ENV} import {module}",
        True,
        "fail",
        diagnostic_fix(f"install or repair Python dependency '{module}' in {PYTHON_ENV} ({reason})"),
    )


def parse_ldd_missing(output):
    missing = []
    for line in output.splitlines():
        if "=> not found" in line:
            missing.append(line.split("=>", 1)[0].strip())
    return missing


def check_shared_libs(checks, binary_realpath):
    # Check the loader exactly as tools/run_ef5.py runs the managed binary: the caller's
    # environment, no extra library folders added (the binary's RUNPATH finds its own lib/).
    env = os.environ.copy()
    result = run_command(["ldd", binary_realpath], timeout=20, env=env)
    output = result.stdout + result.stderr
    missing = parse_ldd_missing(output)
    if result.returncode == 0 and not missing:
        return add_check(checks, "binary", f"{binary_realpath} shared libraries", True, "pass"), env
    fix = diagnostic_fix(
        f"repair the EF5 install: ldd {binary_realpath} failed "
        f"(the managed install keeps its libraries in {EF5_BINARY.parent.parent / 'lib'})"
    )
    if missing:
        fix = diagnostic_fix(f"missing EF5 shared libraries: {', '.join(missing)} (the managed install keeps them in {EF5_BINARY.parent.parent / 'lib'})")
    return add_check(checks, "binary", f"{binary_realpath} shared libraries", True, "fail", fix), env


def check_binary_starts(checks, binary_realpath, env):
    result = run_command([binary_realpath], timeout=10, env=env, cwd=str(KI_DIR))
    output = (result.stdout or "") + (result.stderr or "")
    started = "Ensemble Framework For Flash Flood Forecasting" in output
    expected_no_control = "Failed to open configuration file control.txt" in output
    if started and expected_no_control:
        return add_check(checks, "run", binary_realpath, True, "pass")
    if getattr(result, "timeout", False):
        fix = diagnostic_fix("EF5 did not reach its startup banner within 10 seconds")
    else:
        detail = output.strip().splitlines()[-1] if output.strip() else f"exit code {result.returncode}"
        fix = diagnostic_fix(f"EF5 binary did not start cleanly ({detail})")
    return add_check(checks, "run", binary_realpath, True, "fail", fix)


def main():
    checks = []
    print("=" * 60)
    print("PREFLIGHT CHECK: EF5")
    print("=" * 60)

    check_dir(checks, KI_DIR / "tools", "KI tools", critical=True)
    for path in REQUIRED_KI_FILES:
        check_file(checks, path, path.name, critical=True)
    for path in REQUIRED_TOOLS:
        check_file(checks, path, path.name, critical=True)

    binary = pick_binary()
    if binary is None:
        binary_ok = add_check(
            checks, "binary", EF5_BINARY, True, "fail",
            diagnostic_fix("EF5 binary is missing; looked for (in order) "
                           + "; ".join(str(c) for c in EF5_BINARY_CANDIDATES)),
        )
    elif binary == EF5_BINARY:
        # Literal on purpose (KISS reads it, see binary_check_file); test_binary_location keeps it
        # equal to EF5_BINARY.
        binary_ok = binary_check_file("KISSPATH_BINARIES/EF5/bin/ef5", checks)
    else:
        binary_ok = binary_check_file(binary, checks)
    if binary_ok:
        binary_realpath = str(binary.resolve())
        libs_ok, env = check_shared_libs(checks, binary_realpath)
        if libs_ok:
            check_binary_starts(checks, binary_realpath, env)

    check_file(checks, PYTHON_ENV, "HydroCraft Python interpreter", critical=True, executable=True, kind="import")
    for module in REQUIRED_IMPORTS:
        check_import(checks, module)

    passed = sum(1 for c in checks if c["status"] == "pass")
    failed = len(checks) - passed
    print(f"Results: {passed} passed, {failed} failed")
    if failed:
        print(f"Failures point to {TRIPLETS} for recovery guidance.")
    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
