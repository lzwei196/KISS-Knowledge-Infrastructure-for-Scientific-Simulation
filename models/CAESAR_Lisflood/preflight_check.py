#!/usr/bin/env python3
"""Preflight check for the CAESAR_Lisflood knowledge infrastructure."""

import json
import os
import subprocess
import sys
from pathlib import Path


MODEL_ID = "CAESAR_Lisflood"
KI_DIR = Path(__file__).resolve().parent
MODEL_ROOT = Path("KISSPATH_KI_ROOT/CAESAR_Lisflood")
SOURCE_REPO = MODEL_ROOT / "source" / "repo"
BINARY = SOURCE_REPO / "bin" / "HAIL-CAESAR.exe"
HYDRO_PYTHON = Path("KISSPATH_PYTHON_ENV/bin/python")
PYTHON = HYDRO_PYTHON if HYDRO_PYTHON.exists() else Path(sys.executable)
TRIPLETS = KI_DIR / "diagnostics" / "triplets.yaml"
BOSCASTLE_DATA = SOURCE_REPO / "test" / "input_data" / "boscastle" / "boscastle_input_data"


checks = []


def diagnostic_fix(message):
    return f"{message} Check diagnostics/triplets.yaml for matching recovery steps."


def add_check(kind, subject, critical, status, fix=""):
    check = {
        "kind": kind,
        "subject": str(subject),
        "critical": bool(critical),
        "status": status,
        "fix": fix if status == "fail" else "",
    }
    checks.append(check)
    label = "OK" if status == "pass" else ("FAIL" if critical else "WARN")
    print(f"  {label:<5} {kind}: {subject}")
    if status == "fail" and fix:
        print(f"        Fix: {fix}")


def check_file(path, label, critical=True, executable=False):
    path = Path(path)
    subject = path.resolve() if path.exists() else path
    if not path.is_file():
        add_check(
            "binary" if executable else "data",
            subject,
            critical,
            "fail",
            diagnostic_fix(f"{label} not found at {path}."),
        )
        return False
    if executable and not os.access(path, os.X_OK):
        add_check(
            "binary",
            subject.resolve(),
            critical,
            "fail",
            diagnostic_fix(f"{label} exists but is not executable; run chmod +x {path}."),
        )
        return False
    add_check("binary" if executable else "data", subject.resolve(), critical, "pass")
    return True


def check_dir(path, label, critical=True, non_empty=True):
    path = Path(path)
    subject = path.resolve() if path.exists() else path
    if not path.is_dir():
        add_check(
            "data",
            subject,
            critical,
            "fail",
            diagnostic_fix(f"{label} directory not found at {path}."),
        )
        return False
    if non_empty and not any(path.iterdir()):
        add_check(
            "data",
            subject.resolve(),
            critical,
            "fail",
            diagnostic_fix(f"{label} directory is empty at {path}."),
        )
        return False
    add_check("data", subject.resolve(), critical, "pass")
    return True


def check_import(module, label, critical=True):
    cmd = [str(PYTHON), "-c", f"import {module}"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    subject = f"{PYTHON} -c 'import {module}'"
    if result.returncode == 0:
        add_check("import", subject, critical, "pass")
        return True
    detail = (result.stderr or result.stdout or "").strip().splitlines()
    reason = detail[-1] if detail else f"import {module} failed"
    add_check(
        "import",
        subject,
        critical,
        "fail",
        diagnostic_fix(f"{label} import failed under the HydroCraft interpreter: {reason}."),
    )
    return False


def check_python_syntax(script, critical=True):
    script = Path(script)
    cmd = [str(PYTHON), "-m", "py_compile", str(script)]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    subject = f"{PYTHON} -m py_compile {script.resolve() if script.exists() else script}"
    if result.returncode == 0:
        add_check("import", subject, critical, "pass")
        return True
    detail = (result.stderr or result.stdout or "").strip().splitlines()
    reason = detail[-1] if detail else f"syntax check failed for {script}"
    add_check(
        "import",
        subject,
        critical,
        "fail",
        diagnostic_fix(f"{script.name} is not importable/compilable: {reason}."),
    )
    return False


def check_binary_starts(binary):
    binary = Path(binary)
    if not binary.is_file() or not os.access(binary, os.X_OK):
        return False
    env = os.environ.copy()
    env["OMP_NUM_THREADS"] = "1"
    try:
        result = subprocess.run(
            [str(binary.resolve())],
            cwd=str(KI_DIR),
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except subprocess.TimeoutExpired:
        add_check(
            "run",
            binary.resolve(),
            True,
            "fail",
            diagnostic_fix("Binary startup timed out with OMP_NUM_THREADS=1."),
        )
        return False
    except OSError as exc:
        add_check(
            "run",
            binary.resolve(),
            True,
            "fail",
            diagnostic_fix(f"Binary could not be started: {exc}."),
        )
        return False

    output = f"{result.stdout}\n{result.stderr}"
    expected = "No parameter file supplied" in output or "HAIL-CAESAR" in output
    if expected:
        add_check("run", binary.resolve(), True, "pass")
        return True

    add_check(
        "run",
        binary.resolve(),
        True,
        "fail",
        diagnostic_fix(
            f"Binary started but did not print the expected HAIL-CAESAR banner/no-params message "
            f"(exit code {result.returncode})."
        ),
    )
    return False


def check_dynamic_libraries(binary):
    binary = Path(binary)
    if not binary.is_file():
        return False
    result = subprocess.run(["ldd", str(binary.resolve())], capture_output=True, text=True, timeout=20)
    subject = f"ldd {binary.resolve()}"
    if result.returncode == 0 and "not found" not in result.stdout:
        add_check("binary", subject, True, "pass")
        return True
    missing = [line.strip() for line in result.stdout.splitlines() if "not found" in line]
    reason = "; ".join(missing) if missing else (result.stderr.strip() or "ldd failed")
    add_check(
        "binary",
        subject,
        True,
        "fail",
        diagnostic_fix(f"Dynamic library check failed: {reason}."),
    )
    return False


def emit_report(model_id, report_checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": report_checks}, sort_keys=True))
    critical_failed = any(c["status"] == "fail" and c.get("critical") for c in report_checks)
    sys.exit(1 if critical_failed else 0)


def main():
    print("=" * 60)
    print(f"  PREFLIGHT CHECK: {MODEL_ID}")
    print("=" * 60)

    check_dir(KI_DIR / "tools", "KI tools directory", critical=True)
    check_file(BINARY, "CAESAR_Lisflood binary", critical=True, executable=True)
    check_binary_starts(BINARY)
    check_dynamic_libraries(BINARY)

    check_file(SOURCE_REPO / "Makefile", "HAIL-CAESAR Makefile", critical=True)
    check_file(SOURCE_REPO / "test" / "run_tests.sh", "HAIL-CAESAR shipped test runner", critical=False, executable=True)

    check_import("numpy", "NumPy", critical=True)
    for module in ("rasterio", "geopandas", "pandas", "xarray"):
        check_import(module, module, critical=False)

    for tool in (
        "run_caesar.py",
        "convert_dem_to_caesar.py",
        "convert_rainfall_to_caesar.py",
        "convert_soil_to_caesar.py",
        "parse_caesar_output.py",
    ):
        check_file(KI_DIR / "tools" / tool, f"KI tool {tool}", critical=True)
        check_python_syntax(KI_DIR / "tools" / tool, critical=True)

    check_dir(BOSCASTLE_DATA, "Boscastle shipped input data", critical=True)
    for data_file in (
        "boscastle_test_72hr_50m_u.params",
        "boscastle_square_50m.asc",
        "boscastle_72hr_rain_u.txt",
    ):
        check_file(BOSCASTLE_DATA / data_file, f"Boscastle {data_file}", critical=True)

    check_file(TRIPLETS, "diagnostic triplets", critical=False)

    passed = sum(1 for c in checks if c["status"] == "pass")
    failed = sum(1 for c in checks if c["status"] == "fail")
    critical_failed = sum(1 for c in checks if c["status"] == "fail" and c.get("critical"))
    print(f"\n  Results: {passed} passed, {failed} failed ({critical_failed} critical)")
    if critical_failed:
        print("  STATUS: PREFLIGHT FAILED. Fix blockers above; diagnostics/triplets.yaml has recovery guidance.")
    else:
        print("  STATUS: PREFLIGHT PASSED. Model execution prerequisites are present.")

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
