#!/usr/bin/env python3
"""Preflight check for the HydroTrend Knowledge Infrastructure."""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path


MODEL_ID = "HydroTrend"
KI_DIR = Path(__file__).resolve().parent
MODEL_ROOT = KI_DIR.parent
SOURCE_DIR = MODEL_ROOT / "source" / "repo"
BINARY = MODEL_ROOT / "bin" / "hydrotrend"
DIAGNOSTICS = KI_DIR / "diagnostics" / "triplets.yaml"


checks = []


def add_check(kind, subject, critical, ok, fix):
    status = "pass" if ok else "fail"
    checks.append(
        {
            "kind": kind,
            "subject": str(subject),
            "critical": bool(critical),
            "status": status,
            "fix": "" if ok else fix,
        }
    )
    label = "OK" if ok else ("FAIL" if critical else "WARN")
    print(f"  {label:<5} {kind}: {subject}")
    if not ok:
        print(f"        Fix: {fix}")


def emit_report(model_id, report_checks):
    print(
        "PREFLIGHT_REPORT="
        + json.dumps({"model_id": model_id, "checks": report_checks}, sort_keys=True)
    )
    critical_failed = any(
        c["status"] != "pass" and c.get("critical") for c in report_checks
    )
    sys.exit(1 if critical_failed else 0)


def check_file(path, label, critical=True, executable=False):
    path = Path(path)
    subject = path.resolve(strict=False)
    if not path.is_file():
        add_check(
            "binary" if executable else "data",
            subject,
            critical,
            False,
            f"Restore {label} at {subject}; check {DIAGNOSTICS} for recovery.",
        )
        return False
    if executable and not os.access(path, os.X_OK):
        add_check(
            "binary",
            subject,
            critical,
            False,
            f"Run chmod +x {subject}, or rebuild HydroTrend; see {DIAGNOSTICS}.",
        )
        return False
    add_check("binary" if executable else "data", subject, critical, True, "")
    return True


def check_dir(path, label, critical=True, non_empty=False):
    path = Path(path)
    subject = path.resolve(strict=False)
    if not path.is_dir():
        add_check(
            "data",
            subject,
            critical,
            False,
            f"Restore {label} directory at {subject}; check {DIAGNOSTICS}.",
        )
        return False
    if non_empty and not any(path.iterdir()):
        add_check(
            "data",
            subject,
            critical,
            False,
            f"Populate {label} directory at {subject}; check {DIAGNOSTICS}.",
        )
        return False
    add_check("data", subject, critical, True, "")
    return True


def check_tool_import(tool_path, critical=True):
    tool_path = Path(tool_path)
    subject = tool_path.resolve(strict=False)
    if not tool_path.is_file():
        add_check(
            "import",
            subject,
            critical,
            False,
            f"Restore KI tool {subject}; check {DIAGNOSTICS}.",
        )
        return False
    module_name = f"_preflight_{tool_path.stem}"
    try:
        spec = importlib.util.spec_from_file_location(module_name, str(tool_path))
        if spec is None or spec.loader is None:
            raise ImportError(f"unable to load module spec for {tool_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception as exc:
        add_check(
            "import",
            subject,
            critical,
            False,
            f"Fix imports or syntax in {subject}: {exc}; check {DIAGNOSTICS}.",
        )
        return False
    add_check("import", subject, critical, True, "")
    return True


def check_binary_starts(binary):
    binary = Path(binary)
    subject = binary.resolve(strict=False)
    if not binary.is_file():
        add_check(
            "run",
            subject,
            True,
            False,
            f"Build or restore HydroTrend executable at {subject}; see {DIAGNOSTICS}.",
        )
        return False
    try:
        result = subprocess.run(
            [str(binary), "--version"],
            cwd=str(KI_DIR),
            text=True,
            capture_output=True,
            timeout=5,
        )
    except Exception as exc:
        add_check(
            "run",
            subject,
            True,
            False,
            f"HydroTrend did not start with --version: {exc}; check {DIAGNOSTICS}.",
        )
        return False
    ok = result.returncode == 0 and "HydroTrend" in (
        (result.stdout or "") + (result.stderr or "")
    )
    fix = (
        "Rebuild HydroTrend from "
        f"{SOURCE_DIR} or restore {subject}; check {DIAGNOSTICS}."
    )
    add_check("run", subject, True, ok, fix)
    return ok


def main():
    print(f"{' PREFLIGHT: HydroTrend ':=^60}")
    print(f"KI directory: {KI_DIR}")
    print(f"Model root:   {MODEL_ROOT}")
    print()

    check_dir(KI_DIR / "tools", "KI tools", critical=True, non_empty=True)
    for name in [
        "run_hydrotrend.py",
        "parse_hydrotrend_output.py",
        "convert_climate_to_hydrotrend.py",
        "build_hypsometry.py",
    ]:
        check_tool_import(KI_DIR / "tools" / name, critical=True)

    check_file(BINARY, "HydroTrend binary", critical=True, executable=True)
    check_binary_starts(BINARY)

    check_dir(SOURCE_DIR, "HydroTrend source tree", critical=False, non_empty=True)
    check_file(SOURCE_DIR / "CMakeLists.txt", "HydroTrend CMake build file", critical=False)
    check_file(SOURCE_DIR / ".bmi" / "HYDRO.IN.tmpl", "BMI input template", critical=True)
    check_file(SOURCE_DIR / ".bmi" / "HYDRO0.HYPS", "BMI hypsometry template", critical=True)
    check_file(SOURCE_DIR / "data" / "input" / "HYDRO.IN", "sample HYDRO.IN", critical=False)
    check_file(SOURCE_DIR / "data" / "input" / "HYDRO0.HYPS", "sample HYDRO0.HYPS", critical=False)
    check_file(DIAGNOSTICS, "diagnostic triplets", critical=True)

    print()
    failures = [c for c in checks if c["status"] != "pass"]
    print(f"  Results: {len(checks) - len(failures)} passed, {len(failures)} failed")
    if failures:
        print(f"  Recovery: inspect {DIAGNOSTICS} for known HydroTrend fixes.")
    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
