#!/usr/bin/env python3
"""Preflight check for RHESSys."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


MODEL_ID = "RHESSys"
KI_DIR = Path(__file__).resolve().parent
DIAGNOSTICS = KI_DIR / "diagnostics" / "triplets.yaml"
RHESSYS_BINARY = Path(
    "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/"
    "RHESSys/source/repo/rhessys/rhessys7.4"
)


def report_check(kind: str, subject: str, critical: bool, passed: bool, fix: str = "") -> dict:
    status = "pass" if passed else "fail"
    check = {
        "kind": kind,
        "subject": subject,
        "critical": critical,
        "status": status,
        "fix": "" if passed else fix,
    }
    marker = "OK" if passed else ("FAIL" if critical else "WARN")
    print(f"  {marker:<5} {kind}: {subject}")
    if not passed and fix:
        print(f"        Fix: {fix}")
    return check


def check_file(path: Path, label: str, *, kind: str = "data", critical: bool = True) -> dict:
    passed = path.is_file()
    fix = f"Restore {label}; check {DIAGNOSTICS} for recovery."
    return report_check(kind, str(path), critical, passed, fix)


def check_dir(path: Path, label: str, *, critical: bool = True) -> dict:
    passed = path.is_dir()
    subject = f"{path} ({len(os.listdir(path))} items)" if passed else str(path)
    fix = f"Restore {label}; check {DIAGNOSTICS} for recovery."
    return report_check("data", subject, critical, passed, fix)


def check_binary(path: Path) -> list[dict]:
    realpath = os.path.realpath(path)
    checks = []
    exists_and_exec = path.is_file() and os.access(path, os.X_OK)
    checks.append(
        report_check(
            "binary",
            realpath,
            True,
            exists_and_exec,
            f"Restore or rebuild RHESSys 7.4 binary at {path}; check {DIAGNOSTICS}.",
        )
    )
    if not exists_and_exec:
        return checks

    try:
        proc = subprocess.run(
            [str(path)],
            cwd=str(KI_DIR),
            capture_output=True,
            text=True,
            timeout=5,
        )
        output = (proc.stdout + proc.stderr).strip()
        starts = "FATAL ERROR" in output or "world file" in output.lower()
        checks.append(
            report_check(
                "run",
                f"{realpath} starts without loader failure",
                True,
                starts,
                f"Run the binary directly and resolve loader/runtime startup errors; check {DIAGNOSTICS}.",
            )
        )
    except Exception as exc:
        checks.append(
            report_check(
                "run",
                f"{realpath} starts without loader failure",
                True,
                False,
                f"Binary startup raised {type(exc).__name__}: {exc}; check {DIAGNOSTICS}.",
            )
        )
    return checks


def check_tool_syntax(tool: Path) -> dict:
    proc = subprocess.run(
        [sys.executable, "-m", "py_compile", str(tool)],
        cwd=str(KI_DIR),
        capture_output=True,
        text=True,
    )
    fix = (
        f"Fix Python syntax/import-time errors in {tool.relative_to(KI_DIR)}; "
        f"check {DIAGNOSTICS} for recovery."
    )
    return report_check("import", str(tool), True, proc.returncode == 0, fix)


def emit_report(model_id: str, checks: list[dict]) -> None:
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}, sort_keys=True))
    failed_critical = any(c["status"] != "pass" and c.get("critical") for c in checks)
    sys.exit(1 if failed_critical else 0)


def main() -> None:
    print(f"{' PREFLIGHT: RHESSys ':=^60}")
    print()
    checks: list[dict] = []

    checks.extend(check_binary(RHESSYS_BINARY))
    checks.append(check_dir(KI_DIR / "tools", "KI tools directory"))

    for rel in [
        "tools/convert_forcing.py",
        "tools/convert_soil_params.py",
        "tools/gen_rain_duration.py",
        "tools/init_carbon_pools.py",
        "tools/parse_output.py",
        "tools/run_rhessys.py",
        "tools/split_kdown.py",
    ]:
        checks.append(check_tool_syntax(KI_DIR / rel))

    for rel in [
        "SKILL.md",
        "knowledge_infrastructure.yaml",
        "dag.yaml",
        "docs/format_spec.yaml",
        "workflow/workflow.md",
    ]:
        checks.append(check_file(KI_DIR / rel, rel))

    checks.append(
        check_file(
            DIAGNOSTICS,
            "diagnostics/triplets.yaml",
            critical=False,
        )
    )
    if DIAGNOSTICS.is_file():
        print(f"  INFO  Diagnostics available: {DIAGNOSTICS}")
        print("        If the model fails, check triplets FIRST for known fixes.")

    passed = sum(1 for c in checks if c["status"] == "pass")
    failed = len(checks) - passed
    print(f"\n  Results: {passed} passed, {failed} failed")
    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
