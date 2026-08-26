#!/usr/bin/env python3
"""
Preflight check for Lohmann Routing 1.0.

Run this before attempting model execution. The gate requires the final output
line to be PREFLIGHT_REPORT=<json> listing every real check performed.
"""

import json
import os
import subprocess
import sys
from pathlib import Path


MODEL_ID = "Lohmann_Routing"
KI_DIR = Path(__file__).resolve().parent
DIAGNOSTICS = KI_DIR / "diagnostics" / "triplets.yaml"
BINARY = Path("KISSPATH_BINARIES/route_1.0/src/rout")
DEM_DIR = Path("KISSPATH_STATIC/china_dem_90m")
PYTHON_ENV = Path("KISSPATH_PYTHON_ENV/bin/python")


def report_check(checks, kind, subject, critical, passed, fix):
    """Append a contract-shaped check and print a human-readable status."""
    status = "pass" if passed else "fail"
    checks.append(
        {
            "kind": kind,
            "subject": str(subject),
            "critical": bool(critical),
            "status": status,
            "fix": "" if passed else fix,
        }
    )
    label = "OK" if passed else ("FAIL" if critical else "WARN")
    print(f"  {label:<5} {kind}: {subject}")
    if not passed:
        print(f"        Fix: {fix}")


def check_file(checks, path, label, critical=True, executable=False):
    path = Path(path)
    subject = str(path.resolve()) if path.exists() else str(path)
    if not path.is_file():
        report_check(
            checks,
            "binary" if executable else "data",
            subject,
            critical,
            False,
            f"Restore {label} at {path}; see {DIAGNOSTICS} for recovery patterns.",
        )
        return False
    if executable and not os.access(path, os.X_OK):
        report_check(
            checks,
            "binary",
            str(path.resolve()),
            critical,
            False,
            f"Make {label} executable: chmod +x {path}. See {DIAGNOSTICS}.",
        )
        return False
    report_check(
        checks,
        "binary" if executable else "data",
        str(path.resolve()),
        critical,
        True,
        "",
    )
    return True


def check_dir(checks, path, label, critical=True, required_files=None):
    path = Path(path)
    missing_files = []
    if path.is_dir() and required_files:
        missing_files = [name for name in required_files if not (path / name).is_file()]
    passed = path.is_dir() and not missing_files
    if missing_files:
        fix = (
            f"Restore required {label} files under {path}: {', '.join(missing_files)}. "
            f"See {DIAGNOSTICS}."
        )
    else:
        fix = f"Restore {label} directory at {path}. See {DIAGNOSTICS}."
    report_check(
        checks,
        "data",
        str(path.resolve()) if path.exists() else str(path),
        critical,
        passed,
        fix,
    )
    return passed


def check_binary_starts(checks, binary):
    """Verify the Fortran executable can be invoked cheaply."""
    binary = Path(binary)
    subject = str(binary.resolve()) if binary.exists() else str(binary)
    if not binary.is_file() or not os.access(binary, os.X_OK):
        report_check(
            checks,
            "run",
            subject,
            True,
            False,
            f"Fix the executable before startup testing: {binary}. See {DIAGNOSTICS}.",
        )
        return False
    try:
        result = subprocess.run(
            [str(binary)],
            input="",
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5,
            check=False,
        )
    except Exception as exc:
        report_check(
            checks,
            "run",
            subject,
            True,
            False,
            f"Executable did not start: {exc}. Rebuild route_1.0/src/rout; see {DIAGNOSTICS}.",
        )
        return False

    output = (result.stdout + result.stderr).strip()
    passed = result.returncode == 0 and "USAGE:" in output and "rout <infile>" in output
    report_check(
        checks,
        "run",
        subject,
        True,
        passed,
        f"Expected rout to print usage when run without args; got rc={result.returncode}, output={output!r}. Rebuild or inspect with {DIAGNOSTICS}.",
    )
    return passed


def check_import_with_interpreter(checks, interpreter, module, critical):
    interpreter = Path(interpreter)
    subject = f"{interpreter.absolute()}: import {module}"
    if not interpreter.is_file():
        report_check(
            checks,
            "import",
            subject,
            critical,
            False,
            f"Restore HydroCraft Python environment at {interpreter}. See {DIAGNOSTICS}.",
        )
        return False
    result = subprocess.run(
        [str(interpreter), "-c", f"import {module}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=10,
        check=False,
    )
    passed = result.returncode == 0
    report_check(
        checks,
        "import",
        subject,
        critical,
        passed,
        f"Install {module.split('.')[0]} into {interpreter.parent.parent}: {result.stderr.strip() or result.stdout.strip()}. See {DIAGNOSTICS}.",
    )
    return passed


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}, sort_keys=True))
    critical_failed = any(c["status"] != "pass" and c.get("critical") for c in checks)
    sys.exit(1 if critical_failed else 0)


def main():
    checks = []
    print("=" * 60)
    print("  PREFLIGHT CHECK: Lohmann Routing 1.0")
    print("=" * 60)
    print()

    check_file(checks, BINARY, "Lohmann routing binary", critical=True, executable=True)
    check_binary_starts(checks, BINARY)
    check_dir(
        checks,
        DEM_DIR,
        "DEM 90m",
        critical=True,
        required_files=["china_dem_90m.tif"],
    )
    check_import_with_interpreter(checks, PYTHON_ENV, "pandas", critical=False)
    check_file(checks, KI_DIR / "s5_routing_param" / "run_build_routing_new.py", "routing parameter tool", critical=False)
    check_file(checks, KI_DIR / "preprocess_vic_for_routing.py", "VIC routing preprocessor", critical=False)
    check_file(checks, KI_DIR / "knowledge_infrastructure.yaml", "KI manifest", critical=True)
    check_file(checks, KI_DIR / "dag.yaml", "KDT DAG", critical=True)
    check_file(checks, DIAGNOSTICS, "diagnostic triplets", critical=True)

    print()
    passed = sum(1 for check in checks if check["status"] == "pass")
    failed = len(checks) - passed
    print(f"  Results: {passed} passed, {failed} failed")
    if any(check["status"] != "pass" and check.get("critical") for check in checks):
        print(f"  STATUS: PREFLIGHT FAILED - fix critical issues above; start with {DIAGNOSTICS}")
    else:
        print("  STATUS: PREFLIGHT PASSED - safe to proceed with model execution")
    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
