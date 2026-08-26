#!/usr/bin/env python3
"""Preflight check for the COAWST knowledge infrastructure."""

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


MODEL_ID = "COAWST"
KI_DIR = Path(__file__).resolve().parent
TRIPLETS = KI_DIR / "diagnostics" / "triplets.yaml"
PYTHON_ENV_SITE = Path("KISSPATH_PYTHON_ENV/lib/python3.12/site-packages")
COAWST_BINARY = Path(
    "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/COAWST/source/repo/coawstM"
)


def diagnostics_fix(message):
    return f"{message}; then check {TRIPLETS} for matching recovery triplets."


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}, sort_keys=True))
    sys.exit(0 if all(c["status"] == "pass" or not c.get("critical") for c in checks) else 1)


def add_check(checks, kind, subject, critical, passed, fix=""):
    status = "pass" if passed else "fail"
    subject = str(subject)
    check = {
        "kind": kind,
        "subject": subject,
        "critical": bool(critical),
        "status": status,
        "fix": "" if passed else fix,
    }
    checks.append(check)
    label = "OK" if passed else "FAIL"
    print(f"  {label:<5} {kind}: {subject}")
    if not passed and fix:
        print(f"        Fix: {fix}")
    return passed


def check_file(checks, path, label, critical=True, executable=False):
    path = Path(path)
    subject = path.resolve(strict=False)
    exists = path.is_file()
    can_execute = (not executable) or os.access(path, os.X_OK)
    if exists and can_execute:
        return add_check(checks, "binary" if executable else "data", subject, critical, True)

    if not exists:
        fix = diagnostics_fix(f"{label} is missing at {subject}")
    else:
        fix = diagnostics_fix(f"{label} exists but is not executable; run chmod +x {subject}")
    return add_check(checks, "binary" if executable else "data", subject, critical, False, fix)


def check_dir(checks, path, label, critical=True):
    path = Path(path)
    subject = path.resolve(strict=False)
    passed = path.is_dir() and any(path.iterdir())
    if passed:
        return add_check(checks, "data", subject, critical, True)
    return add_check(
        checks,
        "data",
        subject,
        critical,
        False,
        diagnostics_fix(f"{label} directory is missing or empty"),
    )


def check_import(checks, module, label, critical=True):
    if PYTHON_ENV_SITE.is_dir() and str(PYTHON_ENV_SITE) not in sys.path:
        sys.path.insert(0, str(PYTHON_ENV_SITE))

    spec = importlib.util.find_spec(module)
    if spec is None:
        return add_check(
            checks,
            "import",
            module,
            critical,
            False,
            diagnostics_fix(f"Install Python dependency for {label}: {module}"),
        )

    try:
        __import__(module)
    except Exception as exc:
        return add_check(
            checks,
            "import",
            module,
            critical,
            False,
            diagnostics_fix(f"Import {module} failed under {sys.executable}: {exc}"),
        )
    return add_check(checks, "import", module, critical, True)


def check_ldd(checks, binary):
    binary = Path(binary)
    subject = str(binary.resolve(strict=False)) + " dynamic libraries"
    if not binary.is_file():
        return add_check(
            checks,
            "binary",
            subject,
            True,
            False,
            diagnostics_fix("Cannot inspect dynamic libraries until the COAWST binary exists"),
        )

    ldd = shutil.which("ldd")
    if not ldd:
        return add_check(
            checks,
            "binary",
            subject,
            True,
            False,
            diagnostics_fix("ldd is not available; install libc-bin or verify binary libraries manually"),
        )

    proc = subprocess.run([ldd, str(binary)], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=10)
    missing = [line.strip() for line in proc.stdout.splitlines() if "not found" in line]
    if proc.returncode == 0 and not missing:
        return add_check(checks, "binary", subject, True, True)
    ldd_lines = proc.stdout.strip().splitlines()
    detail = "; ".join(missing) if missing else (ldd_lines[-1] if ldd_lines else f"ldd exited {proc.returncode}")
    return add_check(
        checks,
        "binary",
        subject,
        True,
        False,
        diagnostics_fix(f"COAWST binary has unresolved shared libraries: {detail}"),
    )


def check_binary_starts(checks, binary):
    binary = Path(binary)
    subject = str(binary.resolve(strict=False)) + " startup"
    if not binary.is_file() or not os.access(binary, os.X_OK):
        return add_check(
            checks,
            "run",
            subject,
            True,
            False,
            diagnostics_fix("Cannot run startup probe until the COAWST binary exists and is executable"),
        )

    try:
        proc = subprocess.run(
            [str(binary)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=5,
            cwd=str(binary.parent),
        )
    except subprocess.TimeoutExpired:
        return add_check(
            checks,
            "run",
            subject,
            True,
            False,
            diagnostics_fix("COAWST binary startup probe timed out with no prompt/error"),
        )
    except Exception as exc:
        return add_check(
            checks,
            "run",
            subject,
            True,
            False,
            diagnostics_fix(f"COAWST binary could not be started: {exc}"),
        )

    output = proc.stdout.replace("\x00", "")
    expected_prompt = "Coupled Input File name" in output or "READ_COAWST_PAR" in output
    return add_check(
        checks,
        "run",
        subject,
        True,
        expected_prompt,
        diagnostics_fix("COAWST binary started but did not emit the expected input-file prompt/error"),
    )


def main():
    checks = []
    print(f"{' PREFLIGHT: COAWST ':=^60}")
    print()

    check_dir(checks, KI_DIR / "tools", "KI tools")
    for tool in [
        "convert_forcing.py",
        "convert_grid.py",
        "generate_config.py",
        "parse_output.py",
        "run_coawst.py",
    ]:
        check_file(checks, KI_DIR / "tools" / tool, f"KI tool {tool}", critical=True)

    check_file(checks, COAWST_BINARY, "COAWST binary", critical=True, executable=True)
    check_ldd(checks, COAWST_BINARY)
    check_binary_starts(checks, COAWST_BINARY)

    check_import(checks, "numpy", "NumPy", critical=True)
    check_import(checks, "netCDF4", "NetCDF4", critical=True)
    check_import(checks, "xarray", "xarray", critical=False)
    for module in [
        "tools.convert_forcing",
        "tools.convert_grid",
        "tools.generate_config",
        "tools.parse_output",
        "tools.run_coawst",
    ]:
        check_import(checks, module, module, critical=True)

    check_file(checks, TRIPLETS, "diagnostic triplets", critical=True)
    check_file(checks, KI_DIR / "SKILL.md", "KI skill document", critical=True)
    check_file(checks, KI_DIR / "knowledge_infrastructure.yaml", "KI manifest", critical=True)
    check_file(checks, KI_DIR / "dag.yaml", "KI DAG", critical=True)

    passed = sum(1 for check in checks if check["status"] == "pass")
    failed = len(checks) - passed
    print()
    print(f"  Results: {passed} passed, {failed} failed")
    if failed:
        print(f"  STATUS: PREFLIGHT FAILED - check fixes above and {TRIPLETS}")
    else:
        print("  STATUS: PREFLIGHT PASSED - safe to proceed with COAWST execution")

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
