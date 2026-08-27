#!/usr/bin/env python3
"""Preflight check for the PHREEQC knowledge infrastructure."""

from __future__ import annotations

import importlib
import json
import os
import py_compile
import re
import subprocess
import sys
import tempfile
from pathlib import Path


MODEL_ID = "PHREEQC"
KI_DIR = Path(__file__).resolve().parent
DIAGNOSTICS = KI_DIR / "diagnostics" / "triplets.yaml"
MANIFEST = KI_DIR / "knowledge_infrastructure.yaml"
DEFAULT_BINARY = (
    "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/"
    "PHREEQC/source/repo/build/phreeqc"
)
TOOL_FILES = [
    KI_DIR / "tools" / "run_phreeqc.py",
    KI_DIR / "tools" / "parse_output.py",
    KI_DIR / "tools" / "convert_solution_input.py",
    KI_DIR / "tools" / "convert_soil_params.py",
]
REQUIRED_IMPORTS = ["argparse", "csv", "json", "os", "re", "subprocess", "sys"]


def emit_report(model_id: str, checks: list[dict]) -> None:
    """Emit the KDT gate report as the final line, then exit."""
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}, sort_keys=True))
    failed_critical = any(c["critical"] and c["status"] != "pass" for c in checks)
    sys.exit(1 if failed_critical else 0)


def add_check(
    checks: list[dict],
    kind: str,
    subject: str | os.PathLike,
    critical: bool,
    ok: bool,
    fix: str = "",
) -> bool:
    status = "pass" if ok else "fail"
    fix_text = "" if ok else (fix or f"See {DIAGNOSTICS} for recovery guidance.")
    subject_text = os.fspath(subject)
    print(f"  {'OK  ' if ok else 'FAIL'}  {kind}: {subject_text}")
    if not ok and fix_text:
        print(f"        Fix: {fix_text}")
    checks.append(
        {
            "kind": kind,
            "subject": subject_text,
            "critical": critical,
            "status": status,
            "fix": fix_text,
        }
    )
    return ok


def manifest_binary_path() -> str:
    if not MANIFEST.is_file():
        return DEFAULT_BINARY
    text = MANIFEST.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"(?m)^\s+path:\s*(\S+)\s*$", text)
    return match.group(1) if match else DEFAULT_BINARY


def database_path(binary_path: Path) -> Path:
    candidates = [
        binary_path.parent / "database" / "phreeqc.dat",
        binary_path.parent.parent / "database" / "phreeqc.dat",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


def check_python_imports(checks: list[dict]) -> None:
    for module in REQUIRED_IMPORTS:
        try:
            importlib.import_module(module)
            add_check(checks, "import", module, False, True)
        except Exception as exc:
            add_check(
                checks,
                "import",
                module,
                True,
                False,
                f"Run with a working Python interpreter; import failed: {exc}. "
                f"Then check {DIAGNOSTICS}.",
            )


def check_tool_syntax(checks: list[dict]) -> None:
    for tool in TOOL_FILES:
        ok = tool.is_file()
        if not add_check(
            checks,
            "data",
            tool,
            True,
            ok,
            f"Restore the KI tool file or regenerate the KI; then check {DIAGNOSTICS}.",
        ):
            continue
        try:
            py_compile.compile(str(tool), doraise=True)
            add_check(checks, "import", str(tool), True, True)
        except py_compile.PyCompileError as exc:
            add_check(
                checks,
                "import",
                str(tool),
                True,
                False,
                f"Fix Python syntax in {tool}: {exc.msg}. Then check {DIAGNOSTICS}.",
            )


def check_binary(checks: list[dict], binary_path: Path) -> bool:
    if binary_path.is_file():
        subject = os.path.realpath(binary_path)
        ok = os.access(binary_path, os.X_OK)
        return add_check(
            checks,
            "binary",
            subject,
            True,
            ok,
            f"Make the PHREEQC executable runnable with chmod +x {binary_path}, "
            f"or rebuild PHREEQC. Check {DIAGNOSTICS}.",
        )
    return add_check(
        checks,
        "binary",
        binary_path,
        True,
        False,
        f"PHREEQC executable is missing. Rebuild from the source noted in SKILL.md "
        f"or update {MANIFEST}; then check {DIAGNOSTICS}.",
    )


def check_minimal_run(checks: list[dict], binary_path: Path, db_path: Path) -> None:
    subject = os.path.realpath(binary_path) if binary_path.exists() else str(binary_path)
    if not (binary_path.is_file() and os.access(binary_path, os.X_OK) and db_path.is_file()):
        add_check(
            checks,
            "run",
            subject,
            True,
            False,
            f"Cannot start PHREEQC until the executable and phreeqc.dat pass. "
            f"Check {DIAGNOSTICS}.",
        )
        return

    with tempfile.TemporaryDirectory(prefix="phreeqc_preflight_") as tmp:
        tmpdir = Path(tmp)
        input_file = tmpdir / "minimal.pqi"
        output_file = tmpdir / "minimal.pqo"
        input_file.write_text("SOLUTION 1\n    pH 7\nEND\n", encoding="ascii")
        proc = subprocess.run(
            [str(binary_path), str(input_file), str(output_file), str(db_path)],
            cwd=str(tmpdir),
            text=True,
            capture_output=True,
            timeout=15,
        )
        output_ok = output_file.is_file() and output_file.stat().st_size > 0
        banner = (proc.stdout + proc.stderr + output_file.read_text(encoding="utf-8", errors="ignore")[:4000])
        ok = proc.returncode == 0 and output_ok and "PHREEQC" in banner
        fix = (
            f"PHREEQC failed a minimal run with exit code {proc.returncode}. "
            f"Review stderr/stdout and diagnostics in {DIAGNOSTICS}; rebuild the binary or "
            f"use a valid thermodynamic database if needed."
        )
        add_check(checks, "run", subject, True, ok, fix)


def main() -> None:
    checks: list[dict] = []
    print(f"{' PREFLIGHT: PHREEQC ':=^60}")
    print(f"  KI: {KI_DIR}")
    print()

    add_check(
        checks,
        "data",
        KI_DIR / "SKILL.md",
        True,
        (KI_DIR / "SKILL.md").is_file(),
        f"Restore SKILL.md for PHREEQC usage instructions. Check {DIAGNOSTICS}.",
    )
    add_check(
        checks,
        "data",
        MANIFEST,
        True,
        MANIFEST.is_file(),
        f"Restore knowledge_infrastructure.yaml or regenerate the KI. Check {DIAGNOSTICS}.",
    )
    add_check(
        checks,
        "data",
        KI_DIR / "dag.yaml",
        True,
        (KI_DIR / "dag.yaml").is_file(),
        f"Restore dag.yaml or regenerate the KI. Check {DIAGNOSTICS}.",
    )
    add_check(
        checks,
        "data",
        DIAGNOSTICS,
        False,
        DIAGNOSTICS.is_file(),
        "Restore diagnostics/triplets.yaml so failures have recovery guidance.",
    )

    check_python_imports(checks)
    check_tool_syntax(checks)

    binary = Path(manifest_binary_path())
    db = database_path(binary)
    check_binary(checks, binary)
    add_check(
        checks,
        "data",
        db,
        True,
        db.is_file(),
        f"Restore PHREEQC thermodynamic database phreeqc.dat near the binary, "
        f"or update the KI to the correct database path. Check {DIAGNOSTICS}.",
    )
    check_minimal_run(checks, binary, db)

    passed = sum(1 for check in checks if check["status"] == "pass")
    failed = len(checks) - passed
    print()
    print(f"  Results: {passed} passed, {failed} failed")
    if failed:
        print(f"  Recovery: start with {DIAGNOSTICS}")
    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
