#!/usr/bin/env python3
"""
Preflight check for BIOME-BGC.

Run this before attempting model execution. The final output line is consumed by
the KDT gate and must be:

    PREFLIGHT_REPORT=<json>
"""

import json
import os
import subprocess
import sys
from pathlib import Path


MODEL_ID = "BIOME_BGC"
KI_DIR = Path(__file__).resolve().parent
MODEL_ROOT = Path("KISSPATH_BINARIES/biome-bgc/bgc-src")
BGC_BINARY = MODEL_ROOT / "bgc"
PYTHON_ENV = Path("KISSPATH_PYTHON_ENV/bin/python")
TRIPLETS = KI_DIR / "diagnostics" / "triplets.yaml"


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}, sort_keys=True))
    blocking = [c for c in checks if c.get("critical") and c["status"] != "pass"]
    sys.exit(1 if blocking else 0)


def subject_path(path):
    return os.path.realpath(os.fspath(path))


def add_check(checks, kind, subject, critical, status, fix):
    checks.append(
        {
            "kind": kind,
            "subject": subject,
            "critical": bool(critical),
            "status": status,
            "fix": fix,
        }
    )
    label = "OK" if status == "pass" else ("FAIL" if critical else "WARN")
    print(f"  {label:<5} {kind}: {subject}")
    if status != "pass":
        print(f"        Fix: {fix}")


def diagnostic_fix(message):
    return f"{message}; then check {TRIPLETS} for matching recovery triplets."


def check_file(checks, path, label, critical=True, executable=False):
    real = subject_path(path)
    if Path(path).is_file() and (not executable or os.access(path, os.X_OK)):
        add_check(checks, "binary" if executable else "data", real, critical, "pass", "")
        return True

    if Path(path).is_file() and executable:
        fix = diagnostic_fix(f"Run chmod +x {path}")
    else:
        fix = diagnostic_fix(f"Restore or correct {label} at {path}")
    add_check(checks, "binary" if executable else "data", real, critical, "fail", fix)
    return False


def check_dir(checks, path, label, critical=True):
    real = subject_path(path)
    if Path(path).is_dir() and any(Path(path).iterdir()):
        add_check(checks, "data", real, critical, "pass", "")
        return True
    if Path(path).is_dir():
        fix = diagnostic_fix(f"Populate required {label} directory at {path}")
    else:
        fix = diagnostic_fix(f"Restore or correct {label} directory at {path}")
    add_check(checks, "data", real, critical, "fail", fix)
    return False


def check_binary_starts(checks, binary):
    real = subject_path(binary)
    try:
        result = subprocess.run(
            [os.fspath(binary), "-V"],
            cwd=subject_path(MODEL_ROOT),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5,
            check=False,
        )
    except Exception as exc:
        add_check(
            checks,
            "run",
            f"{real} -V",
            True,
            "fail",
            diagnostic_fix(f"Fix BIOME-BGC startup failure: {exc}"),
        )
        return False

    output = (result.stdout or "") + (result.stderr or "")
    if result.returncode == 0 and "BiomeBGC version" in output:
        add_check(checks, "run", f"{real} -V", True, "pass", "")
        print(f"        Version probe: {output.strip()}")
        return True

    add_check(
        checks,
        "run",
        f"{real} -V",
        True,
        "fail",
        diagnostic_fix(
            f"Expected BIOME-BGC version output from {binary}; got rc={result.returncode}, output={output.strip()!r}"
        ),
    )
    return False


def check_python_import(checks, module, critical=True):
    python_subject = subject_path(PYTHON_ENV)
    subject = f"{python_subject}:import:{module}"
    code = (
        "import importlib, sys\n"
        f"sys.path.insert(0, {str(KI_DIR / 'lib')!r})\n"
        f"sys.path.insert(0, {str(KI_DIR / 'tools')!r})\n"
        f"importlib.import_module({module!r})\n"
    )
    try:
        result = subprocess.run(
            [os.fspath(PYTHON_ENV), "-c", code],
            cwd=subject_path(KI_DIR),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
            check=False,
        )
    except Exception as exc:
        add_check(
            checks,
            "import",
            subject,
            critical,
            "fail",
            diagnostic_fix(f"Use {PYTHON_ENV} and repair import {module}: {exc}"),
        )
        return False

    if result.returncode == 0:
        add_check(checks, "import", subject, critical, "pass", "")
        return True

    add_check(
        checks,
        "import",
        subject,
        critical,
        "fail",
        diagnostic_fix(
            f"Install or repair Python dependency for {module} in KISSPATH_PYTHON_ENV; stderr={result.stderr.strip()!r}"
        ),
    )
    return False


def main():
    checks = []

    print("=" * 60)
    print("  PREFLIGHT CHECK: BIOME-BGC")
    print("=" * 60)
    print()

    check_file(checks, BGC_BINARY, "BIOME-BGC binary", critical=True, executable=True)
    check_binary_starts(checks, BGC_BINARY)

    check_file(checks, PYTHON_ENV, "HydroCraft Python interpreter", critical=True, executable=True)
    for module in [
        "ki_tools_common.units",
        "ki_tools_common.humidity",
        "bgc_utils",
        "generate_site_ini",
        "convert_forcing_to_bgc",
        "run_bgc",
        "run_bgc_spinup",
        "parse_bgc_output",
        "select_ecophysiology",
    ]:
        check_python_import(checks, module, critical=True)

    for rel_path in [
        "tools/generate_site_ini.py",
        "tools/select_ecophysiology.py",
        "tools/convert_forcing_to_bgc.py",
        "tools/run_bgc_spinup.py",
        "tools/run_bgc.py",
        "tools/parse_bgc_output.py",
        "lib/bgc_utils.py",
        "SKILL.md",
        "knowledge_infrastructure.yaml",
        "dag.yaml",
        "docs/format_spec.yaml",
    ]:
        check_file(checks, KI_DIR / rel_path, rel_path, critical=True)

    for path, label in [
        (MODEL_ROOT / "ini" / "enf_test1.ini", "bundled normal-run ini"),
        (MODEL_ROOT / "ini" / "enf_test1_spinup.ini", "bundled spinup ini"),
        (MODEL_ROOT / "metdata" / "miss5093.mtc41", "bundled Missoula meteorology"),
        (MODEL_ROOT / "epc" / "enf.epc", "bundled ENF ecophysiology"),
        (MODEL_ROOT / "USAGE.TXT", "BIOME-BGC usage documentation"),
    ]:
        check_file(checks, path, label, critical=True)

    check_file(checks, TRIPLETS, "diagnostic triplets", critical=True)

    # Legacy probes retained as noncritical: these are common HydroCraft data
    # locations, but this BIOME-BGC KI can run from user-provided forcing.
    for path, label in [
        ("KISSPATH_OBS", "Observation data"),
        ("KISSPATH_FORCING", "Forcing data"),
        ("KISSPATH_STATIC", "DEM data"),
        ("KISSPATH_STATIC", "Soil data"),
    ]:
        check_dir(checks, Path(path), label, critical=False)

    passed = sum(1 for c in checks if c["status"] == "pass")
    failed = len(checks) - passed
    print()
    print(f"  Results: {passed} passed, {failed} failed")
    if any(c["critical"] and c["status"] != "pass" for c in checks):
        print("  STATUS: PREFLIGHT FAILED - fix critical issues above before running")
    else:
        print("  STATUS: PREFLIGHT PASSED - safe to proceed with model execution")

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
