#!/usr/bin/env python3
"""Preflight check for the FSM2 Knowledge Infrastructure."""

from __future__ import annotations

import importlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


MODEL_ID = "FSM2"
KI_DIR = Path(__file__).resolve().parent
MODEL_DIR = KI_DIR.parent
SOURCE_DIR = MODEL_DIR / "source" / "repo"
BINARY = SOURCE_DIR / "FSM2"
TRIPLETS = KI_DIR / "diagnostics" / "triplets.yaml"

CHECKS: list[dict[str, object]] = []


def _subject(path: Path) -> str:
    if path.exists():
        return str(path.resolve())
    return str(path)


def add_check(kind: str, subject: str, critical: bool, passed: bool, fix: str = "") -> None:
    status = "pass" if passed else "fail"
    CHECKS.append(
        {
            "kind": kind,
            "subject": subject,
            "critical": critical,
            "status": status,
            "fix": "" if passed else fix,
        }
    )
    label = "OK" if passed else ("FAIL" if critical else "WARN")
    print(f"  {label:<5} {kind}: {subject}")
    if not passed and fix:
        print(f"        Fix: {fix}")


def check_file(path: Path, label: str, *, critical: bool = True, executable: bool = False) -> None:
    subject = _subject(path)
    if not path.is_file():
        add_check(
            "data",
            subject,
            critical,
            False,
            f"Restore {label} at {path}; see diagnostics/triplets.yaml for recovery.",
        )
        return
    if executable and not os.access(path, os.X_OK):
        add_check(
            "binary",
            subject,
            critical,
            False,
            f"Make {label} executable with chmod +x {path}; see diagnostics/triplets.yaml.",
        )
        return
    add_check("binary" if executable else "data", subject, critical, True)


def check_dir(path: Path, label: str, *, critical: bool = True, non_empty: bool = True) -> None:
    subject = _subject(path)
    if not path.is_dir():
        add_check(
            "data",
            subject,
            critical,
            False,
            f"Restore {label} at {path}; see diagnostics/triplets.yaml for recovery.",
        )
        return
    if non_empty and not any(path.iterdir()):
        add_check(
            "data",
            subject,
            critical,
            False,
            f"Populate {label} at {path}; see diagnostics/triplets.yaml for recovery.",
        )
        return
    add_check("data", subject, critical, True)


def check_import(module: str, *, critical: bool = True) -> None:
    error = ""
    try:
        importlib.import_module(module)
        passed = True
    except Exception as exc:
        passed = False
        error = f": {exc}"
    add_check(
        "import",
        f"{sys.executable}: import {module}",
        critical,
        passed,
        f"Install or repair Python dependency for {sys.executable}: pip install {module.split('.')[0]}{error}; see diagnostics/triplets.yaml.",
    )


def check_command(name: str, *, critical: bool = False) -> None:
    found = shutil.which(name)
    add_check(
        "binary",
        str(Path(found).resolve()) if found else name,
        critical,
        found is not None,
        f"Install {name} or put it on PATH; see diagnostics/triplets.yaml.",
    )


def check_binary_starts(binary: Path) -> None:
    subject = str(binary.resolve()) if binary.exists() else str(binary)
    if not binary.is_file() or not os.access(binary, os.X_OK):
        add_check(
            "run",
            subject,
            True,
            False,
            f"Fix the FSM2 executable first: {binary}; see diagnostics/triplets.yaml.",
        )
        return

    try:
        result = subprocess.run(
            [str(binary)],
            input="",
            text=True,
            cwd=str(SOURCE_DIR),
            capture_output=True,
            timeout=5,
        )
    except subprocess.TimeoutExpired:
        add_check(
            "run",
            subject,
            True,
            False,
            f"FSM2 did not reach its no-input EOF path within 5s; run it manually and check diagnostics/triplets.yaml.",
        )
        return
    except OSError as exc:
        add_check(
            "run",
            subject,
            True,
            False,
            f"FSM2 could not be executed: {exc}; see diagnostics/triplets.yaml.",
        )
        return

    combined = f"{result.stdout}\n{result.stderr}"
    started = result.returncode != 127 and "Fortran runtime error: End of file" in combined
    add_check(
        "run",
        subject,
        True,
        started,
        f"FSM2 did not reach the expected no-input EOF startup path; inspect stderr and diagnostics/triplets.yaml.",
    )


def emit_report(model_id: str, checks: list[dict[str, object]]) -> None:
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}, sort_keys=True))
    ready = bool(checks) and all(c["status"] == "pass" or not c.get("critical") for c in checks)
    sys.exit(0 if ready else 1)


def main() -> None:
    print(f"{' PREFLIGHT: FSM2 ':=^60}")

    check_dir(KI_DIR / "tools", "KI tools directory")
    for tool in (
        "convert_forcing_to_fsm2.py",
        "convert_soil_params.py",
        "parse_fsm2_output.py",
        "run_fsm2.py",
    ):
        check_file(KI_DIR / "tools" / tool, f"tool {tool}")

    check_file(BINARY, "FSM2 executable", executable=True)
    check_binary_starts(BINARY)
    check_dir(SOURCE_DIR / "src", "FSM2 Fortran source directory")
    check_file(SOURCE_DIR / "compil.sh", "FSM2 compile script", executable=True)
    check_file(SOURCE_DIR / "nlst_Alptal.txt", "FSM2 sample namelist")
    check_file(SOURCE_DIR / "met_Alptal_0405.txt", "FSM2 sample forcing")

    check_import("numpy")
    check_import("pandas")
    check_command("gfortran", critical=False)
    check_file(TRIPLETS, "diagnostic triplets", critical=False)

    passed = sum(1 for c in CHECKS if c["status"] == "pass")
    failed = len(CHECKS) - passed
    print(f"\n  Results: {passed} passed, {failed} failed")
    if failed:
        print(f"  Recovery: check {TRIPLETS} before changing model execution.")

    emit_report(MODEL_ID, CHECKS)


if __name__ == "__main__":
    main()
