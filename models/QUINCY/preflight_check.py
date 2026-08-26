#!/usr/bin/env python3
"""Preflight check for the QUINCY knowledge infrastructure."""

from __future__ import annotations

import csv
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


MODEL_ID = "QUINCY"
KI_DIR = Path(__file__).resolve().parent
DIAGNOSTICS = KI_DIR / "diagnostics" / "triplets.yaml"
PYTHON = sys.executable


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}, sort_keys=True))
    failed_critical = [c for c in checks if c["status"] != "pass" and c.get("critical")]
    sys.exit(1 if failed_critical else 0)


def check(kind, subject, critical, status, fix=""):
    item = {
        "kind": kind,
        "subject": str(subject),
        "critical": bool(critical),
        "status": status,
        "fix": fix,
    }
    label = "OK" if status == "pass" else "FAIL"
    print(f"  {label:<4} {kind}: {subject}")
    if status != "pass" and fix:
        print(f"       Fix: {fix}")
    return item


def check_file(path, label, critical=True, executable=False):
    path = Path(path)
    subject = path if label is None else f"{label}: {path}"
    if not path.is_file():
        return check(
            "data",
            subject,
            critical,
            "fail",
            f"Restore or regenerate {path}. See {DIAGNOSTICS} for recovery.",
        )
    if executable and not os.access(path, os.X_OK):
        return check(
            "data",
            subject,
            critical,
            "fail",
            f"chmod +x {path}; if execution still fails, check {DIAGNOSTICS}.",
        )
    if path.stat().st_size == 0:
        return check(
            "data",
            subject,
            critical,
            "fail",
            f"Replace empty file {path}. See {DIAGNOSTICS} for recovery.",
        )
    return check("data", subject, critical, "pass")


def read_manifest_binary_path():
    manifest = KI_DIR / "knowledge_infrastructure.yaml"
    if not manifest.is_file():
        return None
    text = manifest.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"(?ms)^\s*binary:\s*\n(?:\s+.*\n)*?\s+path:\s*(\S+)\s*$", text)
    return Path(match.group(1)) if match else None


def check_import(module, critical=True):
    cmd = [PYTHON, "-c", f"import {module}"]
    proc = subprocess.run(cmd, cwd=KI_DIR, capture_output=True, text=True, timeout=10)
    subject = f"{module} via {PYTHON}"
    if proc.returncode == 0:
        return check("import", subject, critical, "pass")
    detail = (proc.stderr or proc.stdout).strip().splitlines()
    reason = detail[-1] if detail else f"import {module} failed"
    return check(
        "import",
        subject,
        critical,
        "fail",
        f"Install {module} for {PYTHON}: {reason}. Check {DIAGNOSTICS} for known fixes.",
    )


def check_binary_start(script, critical=True):
    script = Path(script)
    real_script = Path(os.path.realpath(script))
    if not real_script.is_file():
        return check(
            "binary",
            real_script,
            critical,
            "fail",
            f"Restore the QUINCY execution wrapper at {real_script}. See {DIAGNOSTICS}.",
        )
    if not os.access(real_script, os.X_OK):
        return check(
            "binary",
            real_script,
            critical,
            "fail",
            f"chmod +x {real_script}; then rerun this preflight. See {DIAGNOSTICS}.",
        )
    cmd = [PYTHON, str(real_script), "--help"]
    proc = subprocess.run(cmd, cwd=KI_DIR, capture_output=True, text=True, timeout=10)
    if proc.returncode == 0 and "Run QUINCY analytic model" in (proc.stdout + proc.stderr):
        return check("binary", real_script, critical, "pass")
    detail = (proc.stderr or proc.stdout).strip().splitlines()
    reason = detail[-1] if detail else f"{real_script} --help failed"
    return check(
        "binary",
        real_script,
        critical,
        "fail",
        f"Fix wrapper startup for {real_script}: {reason}. Check {DIAGNOSTICS}.",
    )


def check_manifest_binary_matches(manifest_path, expected_path, critical=True):
    subject = f"manifest binary path: {manifest_path}"
    if manifest_path is None:
        return check(
            "data",
            subject,
            critical,
            "fail",
            f"Add package.implementation.binary.path to knowledge_infrastructure.yaml. See {DIAGNOSTICS}.",
        )
    manifest_real = Path(os.path.realpath(manifest_path))
    expected_real = Path(os.path.realpath(expected_path))
    if manifest_real == expected_real:
        return check("data", subject, critical, "pass")
    return check(
        "data",
        subject,
        critical,
        "fail",
        f"Set binary.path to {expected_real}; current resolved path is {manifest_real}. See {DIAGNOSTICS}.",
    )


def check_csv_columns(path, required_columns, label, critical=True):
    path = Path(path)
    if not path.is_file():
        return check(
            "data",
            f"{label}: {path}",
            critical,
            "fail",
            f"Restore fixture {path}. Check {DIAGNOSTICS} for recovery.",
        )
    try:
        with path.open(newline="", encoding="utf-8") as fh:
            reader = csv.reader(fh)
            header = next(reader)
    except Exception as exc:
        return check(
            "data",
            f"{label}: {path}",
            critical,
            "fail",
            f"Repair readable CSV header for {path}: {exc}. See {DIAGNOSTICS}.",
        )
    missing = [col for col in required_columns if col not in header]
    if missing:
        return check(
            "data",
            f"{label}: {path}",
            critical,
            "fail",
            f"Required columns missing: {missing}. Regenerate with tools/convert_forcing_to_quincy.py; see {DIAGNOSTICS}.",
        )
    return check("data", f"{label}: {path}", critical, "pass")


def check_sample_run(runner, forcing, params, critical=True):
    runner = Path(runner)
    forcing = Path(forcing)
    params = Path(params)
    with tempfile.TemporaryDirectory(prefix="quincy_preflight_") as tmpdir:
        output = Path(tmpdir) / "quincy_output.csv"
        cmd = [
            PYTHON,
            str(runner),
            "--forcing",
            str(forcing),
            "--params",
            str(params),
            "--output",
            str(output),
            "--lat",
            "32.92",
        ]
        proc = subprocess.run(cmd, cwd=KI_DIR, capture_output=True, text=True, timeout=30)
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout).strip().splitlines()
            reason = detail[-1] if detail else "sample model run failed"
            return check(
                "run",
                f"sample QUINCY execution: {runner}",
                critical,
                "fail",
                f"Fix model execution failure: {reason}. Check {DIAGNOSTICS} first.",
            )
        if not output.is_file() or output.stat().st_size == 0:
            return check(
                "run",
                f"sample QUINCY execution: {runner}",
                critical,
                "fail",
                f"Model exited 0 but did not write {output}. Check {DIAGNOSTICS}.",
            )
        return check("run", f"sample QUINCY execution: {runner}", critical, "pass")


def main():
    print(f"{' PREFLIGHT: QUINCY ':=^60}")
    print(f"  KI directory: {KI_DIR}")
    print(f"  Python: {PYTHON}")
    print()

    runner = KI_DIR / "tools" / "run_quincy.py"
    tool_files = [
        KI_DIR / "tools" / "convert_forcing_to_quincy.py",
        KI_DIR / "tools" / "convert_parameters_to_quincy.py",
        KI_DIR / "tools" / "parse_output_quincy.py",
        runner,
    ]
    required_files = [
        (KI_DIR / "SKILL.md", "skill document", True),
        (KI_DIR / "knowledge_infrastructure.yaml", "KI manifest", True),
        (KI_DIR / "dag.yaml", "DAG", True),
        (DIAGNOSTICS, "diagnostic triplets", True),
        (KI_DIR / "docs" / "format_spec.yaml", "format spec", False),
        (KI_DIR / "bengbu_params.json", "Bengbu parameter fixture", True),
        (KI_DIR / "outputs" / "bengbu_quincy_forcing.csv", "Bengbu forcing fixture", True),
    ]

    checks = []
    for path, label, critical in required_files:
        checks.append(check_file(path, label, critical=critical))
    for path in tool_files:
        checks.append(check_file(path, "tool script", critical=True))

    manifest_binary_path = read_manifest_binary_path()
    checks.append(check_manifest_binary_matches(manifest_binary_path, runner, critical=True))
    checks.append(check_import("numpy", critical=True))
    checks.append(check_binary_start(runner, critical=True))
    checks.append(
        check_csv_columns(
            KI_DIR / "outputs" / "bengbu_quincy_forcing.csv",
            ["SW_IN", "TA", "VPD", "PRECIP", "CO2", "DAYLENGTH"],
            "QUINCY forcing columns",
            critical=True,
        )
    )
    checks.append(
        check_sample_run(
            runner,
            KI_DIR / "outputs" / "bengbu_quincy_forcing.csv",
            KI_DIR / "bengbu_params.json",
            critical=True,
        )
    )

    print()
    failed = [c for c in checks if c["status"] != "pass"]
    print(f"  Results: {len(checks) - len(failed)} passed, {len(failed)} failed")
    if failed:
        print(f"  Recovery: check {DIAGNOSTICS} before changing wrappers or inputs.")
    else:
        print("  STATUS: PREFLIGHT PASSED")
    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    try:
        main()
    except subprocess.TimeoutExpired as exc:
        checks = [
            check(
                "run",
                exc.cmd if isinstance(exc.cmd, str) else " ".join(exc.cmd),
                True,
                "fail",
                f"Command timed out. Check {DIAGNOSTICS} for QUINCY runtime recovery.",
            )
        ]
        emit_report(MODEL_ID, checks)
