#!/usr/bin/env python3
"""Preflight check for the OpenGeoSys knowledge infrastructure."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path


MODEL_ID = "OpenGeoSys"
KI_DIR = Path(__file__).resolve().parent
HYDROCRAFT_PYTHON = Path("KISSPATH_PYTHON_ENV/bin/python")
DEFAULT_OGS_BINARY = Path(
    "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/OpenGeoSys/venv/bin/ogs"
)
DIAGNOSTICS = KI_DIR / "diagnostics" / "triplets.yaml"


checks: list[dict[str, object]] = []


def add_check(kind: str, subject: str, critical: bool, status: str, fix: str = "") -> bool:
    check = {
        "kind": kind,
        "subject": subject,
        "critical": bool(critical),
        "status": status,
        "fix": fix,
    }
    checks.append(check)
    marker = "OK" if status == "pass" else "FAIL"
    print(f"  {marker:<5} {kind:<8} {subject}")
    if status != "pass" and fix:
        print(f"        Fix: {fix}")
    return status == "pass"


def emit_report(model_id: str, report_checks: list[dict[str, object]]) -> None:
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": report_checks}))
    ready = all(c["status"] == "pass" or not c.get("critical") for c in report_checks)
    sys.exit(0 if ready else 1)


def recovery_hint(extra: str) -> str:
    return f"{extra}; then check {DIAGNOSTICS} for known OpenGeoSys recovery steps"


def real_subject(path: Path) -> str:
    return os.path.realpath(path)


def manifest_binary_path() -> Path:
    manifest = KI_DIR / "knowledge_infrastructure.yaml"
    if not manifest.is_file():
        return DEFAULT_OGS_BINARY
    text = manifest.read_text(encoding="utf-8")
    match = re.search(r"(?m)^\s{4}path:\s*(\S+)\s*$", text)
    if not match:
        return DEFAULT_OGS_BINARY
    return Path(match.group(1))


def check_file(path: Path, label: str, *, critical: bool, executable: bool = False) -> bool:
    subject = real_subject(path)
    if not path.is_file():
        return add_check(
            "data",
            subject,
            critical,
            "fail",
            recovery_hint(f"restore or regenerate required file {path}"),
        )
    if executable and not os.access(path, os.X_OK):
        return add_check(
            "binary",
            subject,
            critical,
            "fail",
            recovery_hint(f"make {path} executable with chmod +x"),
        )
    kind = "binary" if executable else "data"
    return add_check(kind, subject, critical, "pass")


def check_import(module: str, python: Path, label: str, *, critical: bool) -> bool:
    subject = f"{real_subject(python)}: import {module}"
    if not python.is_file():
        return add_check(
            "import",
            subject,
            critical,
            "fail",
            recovery_hint(f"restore Python interpreter {python} before checking {module}"),
        )
    proc = subprocess.run(
        [str(python), "-c", f"import importlib; importlib.import_module({module!r})"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if proc.returncode == 0:
        return add_check("import", subject, critical, "pass")
    detail = (proc.stderr or proc.stdout).strip().splitlines()
    tail = detail[-1] if detail else f"import {module} failed"
    return add_check(
        "import",
        subject,
        critical,
        "fail",
        recovery_hint(f"{label}: install/repair Python module {module} for {python}: {tail}"),
    )


def check_py_compile(script: Path, python: Path, *, critical: bool) -> bool:
    subject = real_subject(script)
    if not script.is_file():
        return add_check(
            "data",
            subject,
            critical,
            "fail",
            recovery_hint(f"restore required tool {script}"),
        )
    proc = subprocess.run(
        [str(python), "-m", "py_compile", str(script)],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if proc.returncode == 0:
        return add_check("import", f"{real_subject(python)}: py_compile {subject}", critical, "pass")
    tail = (proc.stderr or proc.stdout).strip().splitlines()
    reason = tail[-1] if tail else "py_compile failed"
    return add_check(
        "import",
        f"{real_subject(python)}: py_compile {subject}",
        critical,
        "fail",
        recovery_hint(f"fix syntax/import-time issue in {script}: {reason}"),
    )


def check_binary_starts(binary: Path) -> bool:
    subject = real_subject(binary)
    if not binary.is_file() or not os.access(binary, os.X_OK):
        return add_check(
            "run",
            subject,
            True,
            "fail",
            recovery_hint(f"restore executable OGS binary at {binary}"),
        )
    proc = subprocess.run(
        [str(binary), "--version"],
        capture_output=True,
        text=True,
        timeout=20,
    )
    output = f"{proc.stdout}\n{proc.stderr}"
    if proc.returncode == 0 and "ogs  version:" in output:
        return add_check("run", subject, True, "pass")
    tail = output.strip().splitlines()
    reason = tail[-1] if tail else f"exit code {proc.returncode}"
    return add_check(
        "run",
        subject,
        True,
        "fail",
        recovery_hint(f"OGS did not start with --version: {reason}"),
    )


def interpreter_from_shebang(script: Path) -> Path:
    try:
        first = script.read_text(encoding="utf-8", errors="ignore").splitlines()[0]
    except (IndexError, OSError):
        return script.parent / "python"
    if first.startswith("#!"):
        return Path(first[2:].strip().split()[0])
    return script.parent / "python"


def main() -> None:
    print(f"{' PREFLIGHT: OpenGeoSys ':=^60}")
    print()

    ogs_binary = manifest_binary_path()
    ogs_python = interpreter_from_shebang(ogs_binary)

    check_file(ogs_binary, "OpenGeoSys CLI binary", critical=True, executable=True)
    check_binary_starts(ogs_binary)
    check_file(ogs_python, "OpenGeoSys launcher Python", critical=True, executable=True)
    check_import("ogs", ogs_python, "OpenGeoSys Python package used by the CLI wrapper", critical=True)

    check_file(HYDROCRAFT_PYTHON, "HydroCraft Python environment", critical=True, executable=True)
    for module in ("numpy", "pandas"):
        check_import(module, HYDROCRAFT_PYTHON, f"tool dependency {module}", critical=True)
    check_import("meshio", HYDROCRAFT_PYTHON, "optional VTU parser", critical=False)
    check_import("lxml", HYDROCRAFT_PYTHON, "documented XML dependency", critical=False)

    for rel in (
        "SKILL.md",
        "knowledge_infrastructure.yaml",
        "dag.yaml",
        "diagnostics/triplets.yaml",
        "docs/format_spec.yaml",
    ):
        check_file(KI_DIR / rel, rel, critical=True)

    for rel in (
        "docs/s0_configuration.md",
        "docs/s1_domain_setup.md",
        "docs/s2_forcing_input.md",
        "docs/s3_parameters.md",
        "docs/s4_execution.md",
        "docs/s5_output_parsing.md",
        "docs/s6_coupled_processes.md",
        "docs/s7_diagnostics_guide.md",
    ):
        check_file(KI_DIR / rel, rel, critical=False)

    for rel in (
        "tools/convert_forcing_to_ogs.py",
        "tools/convert_soil_to_ogs.py",
        "tools/run_ogs.py",
        "tools/parse_ogs_output.py",
    ):
        check_py_compile(KI_DIR / rel, HYDROCRAFT_PYTHON, critical=True)

    print()
    failed = [c for c in checks if c["status"] != "pass"]
    print(f"  Results: {len(checks) - len(failed)} passed, {len(failed)} failed")
    if failed:
        print(f"  Diagnostics: {DIAGNOSTICS}")

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
