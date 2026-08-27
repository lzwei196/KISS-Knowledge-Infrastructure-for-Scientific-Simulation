#!/usr/bin/env python3
"""Preflight check for the PySWMM Knowledge Infrastructure."""

import json
import os
import py_compile
import subprocess
import sys
from pathlib import Path


MODEL_ID = "PySWMM"
KI_DIR = Path(__file__).resolve().parent
HYDROCRAFT_PYTHON = Path("KISSPATH_PYTHON_ENV/bin/python")
DIAGNOSTICS = KI_DIR / "diagnostics" / "triplets.yaml"
TOOLS = [
    KI_DIR / "tools" / "convert_forcing_to_inp.py",
    KI_DIR / "tools" / "convert_soil_to_inp.py",
    KI_DIR / "tools" / "parse_swmm_output.py",
    KI_DIR / "tools" / "run_pyswmm.py",
]
METADATA = [
    KI_DIR / "SKILL.md",
    KI_DIR / "knowledge_infrastructure.yaml",
    KI_DIR / "dag.yaml",
]


def recovery_fix(detail):
    return f"{detail}; then check {DIAGNOSTICS} for matching recovery triplets."


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}, sort_keys=True))
    failed_critical = [c for c in checks if c["critical"] and c["status"] != "pass"]
    sys.exit(1 if failed_critical else 0)


class Preflight:
    def __init__(self):
        self.checks = []

    def add(self, kind, subject, critical, status, fix=""):
        status = "pass" if status == "pass" else "fail"
        check = {
            "kind": kind,
            "subject": str(subject),
            "critical": bool(critical),
            "status": status,
            "fix": "" if status == "pass" else fix,
        }
        self.checks.append(check)
        label = "OK" if status == "pass" else "FAIL"
        print(f"  {label:<5} {kind:<8} {subject}")
        if status != "pass":
            print(f"        Fix: {fix}")

    def check_file(self, path, label, critical=True, executable=False):
        subject = os.path.realpath(path) if Path(path).exists() else str(path)
        if not Path(path).is_file():
            self.add("data", subject, critical, "fail", recovery_fix(f"Restore required file: {path}"))
            return
        if executable and not os.access(path, os.X_OK):
            self.add("binary", subject, critical, "fail", recovery_fix(f"Make executable: chmod +x {path}"))
            return
        self.add("binary" if executable else "data", subject, critical, "pass")

    def check_python_starts(self):
        subject = os.path.realpath(HYDROCRAFT_PYTHON) if HYDROCRAFT_PYTHON.exists() else str(HYDROCRAFT_PYTHON)
        if not HYDROCRAFT_PYTHON.is_file():
            self.add(
                "binary",
                subject,
                True,
                "fail",
                recovery_fix(f"Restore HydroCraft Python interpreter at {HYDROCRAFT_PYTHON}"),
            )
            return
        if not os.access(HYDROCRAFT_PYTHON, os.X_OK):
            self.add(
                "binary",
                subject,
                True,
                "fail",
                recovery_fix(f"Make HydroCraft Python executable: chmod +x {HYDROCRAFT_PYTHON}"),
            )
            return

        self.add("binary", subject, True, "pass")

        proc = subprocess.run(
            [str(HYDROCRAFT_PYTHON), "-c", "import sys; print(sys.executable)"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=15,
        )
        self.add(
            "run",
            subject,
            True,
            "pass" if proc.returncode == 0 else "fail",
            recovery_fix(f"HydroCraft Python failed to start: {proc.stderr.strip() or proc.stdout.strip()}"),
        )

    def check_import(self, module, label, critical=True):
        code = (
            "import importlib, os; "
            f"m = importlib.import_module({module!r}); "
            "print(os.path.realpath(getattr(m, '__file__', '') or '<builtin>'))"
        )
        try:
            proc = subprocess.run(
                [str(HYDROCRAFT_PYTHON), "-c", code],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=20,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            self.add(
                "import",
                f"{label}: {module}",
                critical,
                "fail",
                recovery_fix(f"Run {HYDROCRAFT_PYTHON} -m pip install {module.split('.')[0]} ({exc})"),
            )
            return

        subject = proc.stdout.strip().splitlines()[-1] if proc.returncode == 0 and proc.stdout.strip() else module
        self.add(
            "import",
            subject,
            critical,
            "pass" if proc.returncode == 0 else "fail",
            recovery_fix(
                f"Install or repair {module} for {HYDROCRAFT_PYTHON}: "
                f"{proc.stderr.strip() or proc.stdout.strip()}"
            ),
        )

    def check_tool_syntax(self, path):
        subject = os.path.realpath(path) if path.exists() else str(path)
        if not path.is_file():
            self.add("data", subject, True, "fail", recovery_fix(f"Restore required tool: {path}"))
            return
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as exc:
            self.add("data", subject, True, "fail", recovery_fix(f"Fix Python syntax in {path}: {exc.msg}"))
            return
        self.add("data", subject, True, "pass")

    def check_metadata_mentions_pyswmm(self, path):
        subject = os.path.realpath(path) if path.exists() else str(path)
        if not path.is_file():
            self.add("data", subject, True, "fail", recovery_fix(f"Restore required KI metadata file: {path}"))
            return
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            self.add("data", subject, True, "fail", recovery_fix(f"Make metadata readable: {exc}"))
            return
        ok = "pyswmm" in text.lower() or "swmm" in text.lower()
        self.add(
            "data",
            subject,
            True,
            "pass" if ok else "fail",
            recovery_fix(f"Repair {path}; it does not describe PySWMM/SWMM"),
        )


def main():
    print(f"{' PREFLIGHT: PySWMM ':=^60}")
    print()

    pf = Preflight()
    pf.check_python_starts()
    pf.check_import("pyswmm", "PySWMM package")
    pf.check_import("swmm.toolkit.solver", "SWMM toolkit solver")

    for path in METADATA:
        pf.check_metadata_mentions_pyswmm(path)

    pf.check_file(DIAGNOSTICS, "diagnostic triplets", critical=True)
    for path in TOOLS:
        pf.check_tool_syntax(path)

    print()
    passed = sum(1 for c in pf.checks if c["status"] == "pass")
    failed = len(pf.checks) - passed
    print(f"  Results: {passed} passed, {failed} failed")
    if failed:
        print(f"  STATUS: PREFLIGHT FAILED - check fixes above and {DIAGNOSTICS}")
    else:
        print("  STATUS: PREFLIGHT PASSED - model package and KI files are ready")

    emit_report(MODEL_ID, pf.checks)


if __name__ == "__main__":
    main()
