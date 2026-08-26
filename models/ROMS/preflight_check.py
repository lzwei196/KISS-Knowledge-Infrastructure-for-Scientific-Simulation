#!/usr/bin/env python3
"""Preflight check for the ROMS knowledge infrastructure."""

import json
import os
import py_compile
import subprocess
import sys
from pathlib import Path


MODEL_ID = "ROMS"
KI_DIR = Path(__file__).resolve().parent
HYDROCRAFT_PYTHON = Path("KISSPATH_PYTHON_ENV/bin/python")
ROMS_BINARY = Path(
    "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/ROMS/source/repo/build/romsS"
)
TRIPLETS = KI_DIR / "diagnostics" / "triplets.yaml"
RECOVERY = f"Check {TRIPLETS} for recovery steps."


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}))
    failed_critical = any(c["status"] != "pass" and c.get("critical") for c in checks)
    sys.exit(1 if failed_critical else 0)


def add_check(checks, kind, subject, critical, passed, fix=""):
    checks.append(
        {
            "kind": kind,
            "subject": str(subject),
            "critical": bool(critical),
            "status": "pass" if passed else "fail",
            "fix": "" if passed else fix,
        }
    )


def check_file(checks, path, label, critical=True, executable=False):
    path = Path(path)
    subject = path.resolve(strict=False)
    if not path.is_file():
        add_check(
            checks,
            "binary" if executable else "data",
            subject,
            critical,
            False,
            f"{label} not found at {subject}. {RECOVERY}",
        )
        return False
    if executable and not os.access(path, os.X_OK):
        add_check(
            checks,
            "binary",
            subject,
            critical,
            False,
            f"{label} exists but is not executable: chmod +x {subject}. {RECOVERY}",
        )
        return False
    add_check(checks, "binary" if executable else "data", subject, critical, True)
    return True


def check_dir(checks, path, label, critical=True, non_empty=False):
    path = Path(path)
    subject = path.resolve(strict=False)
    if not path.is_dir():
        add_check(
            checks,
            "data",
            subject,
            critical,
            False,
            f"{label} directory not found at {subject}. {RECOVERY}",
        )
        return False
    if non_empty and not any(path.iterdir()):
        add_check(
            checks,
            "data",
            subject,
            critical,
            False,
            f"{label} directory is empty at {subject}. Restore KI contents. {RECOVERY}",
        )
        return False
    add_check(checks, "data", subject, critical, True)
    return True


def check_import(checks, module, critical=True):
    subject = f"{HYDROCRAFT_PYTHON}:{module}"
    if not HYDROCRAFT_PYTHON.is_file() or not os.access(HYDROCRAFT_PYTHON, os.X_OK):
        add_check(
            checks,
            "import",
            subject,
            critical,
            False,
            f"HydroCraft Python interpreter is missing or not executable at {HYDROCRAFT_PYTHON}. {RECOVERY}",
        )
        return False

    result = subprocess.run(
        [str(HYDROCRAFT_PYTHON), "-c", f"import {module}"],
        cwd=str(KI_DIR),
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode == 0:
        add_check(checks, "import", subject, critical, True)
        return True

    detail = (result.stderr or result.stdout).strip().splitlines()
    message = detail[-1] if detail else f"import {module} failed"
    add_check(
        checks,
        "import",
        subject,
        critical,
        False,
        f"{message}. Install/repair the package in {HYDROCRAFT_PYTHON}. {RECOVERY}",
    )
    return False


def check_python_syntax(checks, path, critical=True):
    path = Path(path)
    subject = path.resolve(strict=False)
    try:
        py_compile.compile(str(path), doraise=True)
    except Exception as exc:
        add_check(
            checks,
            "import",
            subject,
            critical,
            False,
            f"Python syntax/compile check failed for {subject}: {exc}. {RECOVERY}",
        )
        return False
    add_check(checks, "import", subject, critical, True)
    return True


def check_binary_starts(checks, binary):
    binary = Path(binary)
    subject = binary.resolve(strict=False)
    if not binary.is_file() or not os.access(binary, os.X_OK):
        add_check(
            checks,
            "run",
            subject,
            True,
            False,
            f"Cannot launch missing or non-executable ROMS binary at {subject}. {RECOVERY}",
        )
        return False

    try:
        result = subprocess.run(
            [str(binary)],
            input=b"",
            cwd=str(binary.parent),
            capture_output=True,
            timeout=5,
        )
    except subprocess.TimeoutExpired:
        add_check(
            checks,
            "run",
            subject,
            True,
            False,
            f"ROMS binary did not return from a no-input startup probe within 5s. {RECOVERY}",
        )
        return False
    except OSError as exc:
        add_check(
            checks,
            "run",
            subject,
            True,
            False,
            f"ROMS binary failed to start: {exc}. {RECOVERY}",
        )
        return False

    output = (result.stdout + result.stderr).decode("utf-8", errors="replace")
    loader_failed = "error while loading shared libraries" in output
    started = "ROMS" in output and not loader_failed
    if started:
        add_check(checks, "run", subject, True, True)
        return True

    tail = output.strip().splitlines()[-1:] or [f"exit code {result.returncode} with no ROMS banner"]
    add_check(
        checks,
        "run",
        subject,
        True,
        False,
        f"ROMS binary did not produce a recognizable startup banner: {tail[0]}. {RECOVERY}",
    )
    return False


def main():
    checks = []

    print(f"{' PREFLIGHT: ROMS ':=^60}")
    print("Checking ROMS binary, KI files, diagnostics, and Python dependencies.")

    # Original real checks retained: KI tools directory and ROMS executable.
    check_dir(checks, KI_DIR / "tools", "KI tools", critical=True, non_empty=True)
    check_file(checks, ROMS_BINARY, "ROMS binary", critical=True, executable=True)
    check_binary_starts(checks, ROMS_BINARY)

    for rel in (
        "SKILL.md",
        "knowledge_infrastructure.yaml",
        "dag.yaml",
        "docs/format_spec.yaml",
        "diagnostics/triplets.yaml",
        "tools/build_roms_grid.py",
        "tools/convert_forcing.py",
        "tools/run_roms.py",
        "tools/parse_roms_output.py",
    ):
        check_file(checks, KI_DIR / rel, rel, critical=True)

    for module in ("numpy", "netCDF4", "scipy"):
        check_import(checks, module, critical=True)

    for tool in (
        "tools/build_roms_grid.py",
        "tools/convert_forcing.py",
        "tools/run_roms.py",
        "tools/parse_roms_output.py",
    ):
        check_python_syntax(checks, KI_DIR / tool, critical=True)

    failed = [c for c in checks if c["status"] != "pass"]
    if failed:
        print("Blockers found:")
        for check in failed:
            print(f"  FAIL {check['kind']} {check['subject']}")
            print(f"       Fix: {check['fix']}")
    else:
        print("All preflight checks passed.")

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
