#!/usr/bin/env python3
"""Preflight checks for the WRF knowledge infrastructure."""

from __future__ import annotations

import importlib.util
import json
import os
import py_compile
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


MODEL_ID = "WRF"
KI_DIR = Path(__file__).resolve().parent
TRIPLETS = KI_DIR / "diagnostics" / "triplets.yaml"
DIAGNOSTIC_FIX = f"Check {TRIPLETS} for the matching symptom and remedy."
CONFIGURED_WRF = Path(
    "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/WRF/source/repo/_build_real/main/wrf"
)


def emit_report(model_id: str, checks: list[dict]) -> None:
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}, sort_keys=True))
    has_blocker = any(c["status"] == "fail" and c.get("critical") for c in checks)
    sys.exit(1 if has_blocker else 0)


def make_check(kind: str, subject: str, critical: bool, passed: bool, fix: str = "") -> dict:
    return {
        "kind": kind,
        "subject": subject,
        "critical": critical,
        "status": "pass" if passed else "fail",
        "fix": "" if passed else fix,
    }


def note(checks: list[dict], check: dict) -> None:
    checks.append(check)
    label = "OK" if check["status"] == "pass" else "FAIL"
    importance = "critical" if check["critical"] else "noncritical"
    print(f"  {label:<4} {check['kind']} {importance}: {check['subject']}")
    if check["status"] == "fail":
        print(f"       Fix: {check['fix']}")


def check_file(checks: list[dict], path: Path, kind: str, critical: bool, executable: bool = False) -> None:
    subject = str(path)
    exists = path.is_file()
    passed = exists and (not executable or os.access(path, os.X_OK))
    if executable and exists:
        subject = str(path.resolve())
    fix = f"Restore or correct this path. {DIAGNOSTIC_FIX}"
    if executable and exists and not os.access(path, os.X_OK):
        fix = f"Run chmod +x {path}. {DIAGNOSTIC_FIX}"
    note(checks, make_check(kind, subject, critical, passed, fix))


def check_dir(checks: list[dict], path: Path, critical: bool) -> None:
    passed = path.is_dir()
    fix = f"Restore the required KI directory at {path}. {DIAGNOSTIC_FIX}"
    note(checks, make_check("data", str(path), critical, passed, fix))


def check_import(checks: list[dict], module: str, critical: bool) -> None:
    spec = importlib.util.find_spec(module)
    fix = f"Install the Python dependency for this interpreter: {sys.executable}. {DIAGNOSTIC_FIX}"
    note(checks, make_check("import", module, critical, spec is not None, fix))


def check_tool_compiles(checks: list[dict], path: Path, critical: bool) -> None:
    try:
        py_compile.compile(str(path), doraise=True)
        passed = True
        fix = ""
    except py_compile.PyCompileError as exc:
        passed = False
        fix = f"Fix Python syntax/import-time compile error in {path}: {exc.msg}. {DIAGNOSTIC_FIX}"
    note(checks, make_check("import", str(path), critical, passed, fix))


def companion_executable(path: Path, stem: str) -> Path:
    for name in (stem, f"{stem}.exe"):
        candidate = path.parent / name
        if candidate.is_file():
            return candidate
    return path.parent / stem


def check_binary_starts(checks: list[dict], path: Path, critical: bool) -> None:
    subject = str(path.resolve()) if path.exists() else str(path)
    if not path.is_file() or not os.access(path, os.X_OK):
        note(
            checks,
            make_check(
                "run",
                subject,
                critical,
                False,
                f"Fix the WRF executable before testing startup. {DIAGNOSTIC_FIX}",
            ),
        )
        return

    with tempfile.TemporaryDirectory(prefix="wrf-preflight-") as tmpdir:
        try:
            proc = subprocess.run(
                [str(path)],
                cwd=tmpdir,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=5,
                check=False,
            )
            output = proc.stdout or ""
        except subprocess.TimeoutExpired:
            note(checks, make_check("run", subject, critical, True, ""))
            return
        except OSError as exc:
            note(
                checks,
                make_check(
                    "run",
                    subject,
                    critical,
                    False,
                    f"Executable failed to start: {exc}. {DIAGNOSTIC_FIX}",
                ),
            )
            return

    starts = "namelist.input" in output
    fix = (
        "The WRF executable did not reach the expected namelist initialization check. "
        f"Run it manually and repair missing shared libraries or runtime setup. {DIAGNOSTIC_FIX}"
    )
    note(checks, make_check("run", subject, critical, starts, fix))


def check_command(checks: list[dict], command: str, critical: bool) -> None:
    resolved = shutil.which(command)
    fix = f"Install {command} or put it on PATH. {DIAGNOSTIC_FIX}"
    note(checks, make_check("binary", command if resolved is None else os.path.realpath(resolved), critical, resolved is not None, fix))


def main() -> None:
    checks: list[dict] = []
    print("=" * 60)
    print("  PREFLIGHT CHECK: WRF")
    print("=" * 60)

    wrf_binary = CONFIGURED_WRF
    real_binary = companion_executable(wrf_binary, "real")

    check_file(checks, wrf_binary, "binary", critical=True, executable=True)
    check_file(checks, real_binary, "binary", critical=True, executable=True)
    check_binary_starts(checks, wrf_binary, critical=True)

    check_command(checks, "mpirun", critical=False)
    check_import(checks, "numpy", critical=True)

    for rel in (
        "tools/run_wrf.py",
        "tools/convert_forcing_to_wrf.py",
        "tools/convert_soil_to_wrf.py",
        "tools/parse_wrfout.py",
    ):
        tool = KI_DIR / rel
        check_file(checks, tool, "data", critical=True)
        if tool.is_file():
            check_tool_compiles(checks, tool, critical=True)

    check_file(checks, KI_DIR / "SKILL.md", "data", critical=True)
    check_file(checks, KI_DIR / "knowledge_infrastructure.yaml", "data", critical=True)
    check_file(checks, KI_DIR / "dag.yaml", "data", critical=True)
    check_file(checks, KI_DIR / "docs" / "format_spec.yaml", "data", critical=False)
    check_file(checks, TRIPLETS, "data", critical=True)
    check_dir(checks, KI_DIR / "tools", critical=True)
    check_dir(checks, KI_DIR / "diagnostics", critical=True)

    print()
    passed = sum(1 for c in checks if c["status"] == "pass")
    failed = len(checks) - passed
    print(f"  Results: {passed} passed, {failed} failed")
    if failed:
        print(f"  Recovery: {DIAGNOSTIC_FIX}")

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
