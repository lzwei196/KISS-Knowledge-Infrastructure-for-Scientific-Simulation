#!/usr/bin/env python3
"""
Preflight check for the CE-QUAL-W2 knowledge infrastructure.

This script verifies the executable, HydroCraft Python environment, KI tools,
and diagnostic assets before any model run is attempted. It always emits a
final PREFLIGHT_REPORT=<json> line for the KDT gate.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


MODEL_ID = "CE_QUAL_W2"
KI_DIR = Path(__file__).resolve().parent
TRIPLETS = KI_DIR / "diagnostics" / "triplets.yaml"
TRIPLETS_FIX = f"Check {TRIPLETS} for the matching diagnostic and recovery steps."

BINARY = Path("KISSPATH_BINARIES/ce_qual_w2/bin/w2_v5")
HYDROCRAFT_PYTHON = Path("KISSPATH_PYTHON_ENV/bin/python")

REQUIRED_IMPORTS = [
    "numpy",
    "pandas",
    "xarray",
    "netCDF4",
    "geopandas",
    "shapely",
    "rasterio",
    "matplotlib",
    "scipy",
    "ki_tools_common.humidity",
]

REQUIRED_KI_FILES = [
    "SKILL.md",
    "knowledge_infrastructure.yaml",
    "dag.yaml",
    "docs/format_spec.yaml",
    "diagnostics/triplets.yaml",
]

REQUIRED_TOOL_FILES = [
    "tools/s1_bathymetry/build_reservoir_grid.py",
    "tools/s2_branch_topology/build_branch_topology.py",
    "tools/s3_met_forcing/convert_met_to_w2.py",
    "tools/s4_inflow/convert_inflow_to_w2.py",
    "tools/s4_inflow/generate_distributed_inflow.py",
    "tools/s5_outflow/configure_w2_outflow.py",
    "tools/s6_init_conditions/build_init_conditions.py",
    "tools/s7_hydraulic_params/set_hydraulic_params.py",
    "tools/s8_wq_config/configure_wq.py",
    "tools/s9_control_file/generate_w2_control.py",
    "tools/s10_execution/run_w2.py",
    "tools/s11_output_analysis/parse_w2_output.py",
    "tools/s11_output_analysis/plot_w2_curtain.py",
    "tools/s11_output_analysis/plot_w2_timeseries.py",
    "tools/s12_calibration/calibrate_w2.py",
    "tools/s13_coupling/w2_to_cama_coupling.py",
]

OPTIONAL_DATA_DIRS = [
    ("KISSPATH_OBS", "Observation data"),
    ("KISSPATH_FORCING", "Forcing data"),
    ("KISSPATH_STATIC", "DEM data"),
    ("KISSPATH_STATIC", "Soil data"),
]


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}, sort_keys=True))
    failed_critical = any(c["status"] != "pass" and c.get("critical") for c in checks)
    sys.exit(1 if failed_critical else 0)


def add_check(checks, kind, subject, critical, passed, fix=""):
    status = "pass" if passed else "fail"
    check = {
        "kind": kind,
        "subject": str(subject),
        "critical": bool(critical),
        "status": status,
        "fix": "" if passed else fix,
    }
    checks.append(check)
    label = "OK" if passed else ("FAIL" if critical else "WARN")
    print(f"  {label:<5} {kind}: {subject}")
    if not passed and fix:
        print(f"        Fix: {fix}")
    return passed


def check_file(checks, path, label, critical=True, executable=False):
    path = Path(path)
    subject = path if not path.is_absolute() else path.resolve(strict=False)
    if not path.is_file():
        return add_check(
            checks,
            "data",
            subject,
            critical,
            False,
            f"{label} is missing. {TRIPLETS_FIX}",
        )
    if executable and not os.access(path, os.X_OK):
        return add_check(
            checks,
            "binary",
            path.resolve(),
            critical,
            False,
            f"Make {label} executable: chmod +x {path}. {TRIPLETS_FIX}",
        )
    return add_check(checks, "binary" if executable else "data", path.resolve(), critical, True)


def check_python_import(checks, module):
    if not HYDROCRAFT_PYTHON.is_file():
        return add_check(
            checks,
            "import",
            f"{module} via {HYDROCRAFT_PYTHON}",
            True,
            False,
            f"HydroCraft Python interpreter is missing: {HYDROCRAFT_PYTHON}. {TRIPLETS_FIX}",
        )

    proc = subprocess.run(
        [str(HYDROCRAFT_PYTHON), "-c", f"import {module}"],
        cwd=str(KI_DIR),
        capture_output=True,
        text=True,
        timeout=20,
    )
    subject = f"{module} via {HYDROCRAFT_PYTHON} (realpath {HYDROCRAFT_PYTHON.resolve(strict=False)})"
    if proc.returncode == 0:
        return add_check(checks, "import", subject, True, True)
    detail = (proc.stderr or proc.stdout).strip().splitlines()
    reason = detail[-1] if detail else f"exit code {proc.returncode}"
    return add_check(
        checks,
        "import",
        subject,
        True,
        False,
        f"Install/fix {module} in {HYDROCRAFT_PYTHON}: {reason}. {TRIPLETS_FIX}",
    )


def check_python_interpreter(checks):
    subject = f"HydroCraft Python interpreter: {HYDROCRAFT_PYTHON} (realpath {HYDROCRAFT_PYTHON.resolve(strict=False)})"
    if not HYDROCRAFT_PYTHON.is_file():
        return add_check(
            checks,
            "binary",
            subject,
            True,
            False,
            f"HydroCraft Python interpreter is missing: {HYDROCRAFT_PYTHON}. {TRIPLETS_FIX}",
        )
    if not os.access(HYDROCRAFT_PYTHON, os.X_OK):
        return add_check(
            checks,
            "binary",
            subject,
            True,
            False,
            f"Make HydroCraft Python executable: chmod +x {HYDROCRAFT_PYTHON}. {TRIPLETS_FIX}",
        )
    return add_check(checks, "binary", subject, True, True)


def check_binary_starts(checks, binary):
    binary = Path(binary)
    if not binary.is_file() or not os.access(binary, os.X_OK):
        return add_check(
            checks,
            "run",
            binary.resolve(strict=False),
            True,
            False,
            f"CE-QUAL-W2 executable cannot be started until the binary check passes. {TRIPLETS_FIX}",
        )

    with tempfile.TemporaryDirectory(prefix="w2_preflight_") as tmpdir:
        proc = subprocess.run(
            [str(binary.resolve())],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            timeout=10,
        )

    output = f"{proc.stdout}\n{proc.stderr}"
    expected_no_inputs = "Could not open w2_con.npt" in output or "Could not open w2_con.csv" in output
    started = proc.returncode == 0 and expected_no_inputs
    if started:
        return add_check(checks, "run", f"{binary.resolve()} startup", True, True)

    tail = " ".join(output.strip().splitlines()[-3:]) or f"exit code {proc.returncode}"
    return add_check(
        checks,
        "run",
        f"{binary.resolve()} startup",
        True,
        False,
        f"Binary did not reach the expected missing-control-file startup state: {tail}. {TRIPLETS_FIX}",
    )


def check_optional_dir(checks, path, label):
    path = Path(path)
    if path.is_dir():
        subject = f"{label}: {path.resolve()}"
        return add_check(checks, "data", subject, False, True)
    return add_check(
        checks,
        "data",
        f"{label}: {path}",
        False,
        False,
        f"Provide this dataset only for workflows that require it. {TRIPLETS_FIX}",
    )


def main():
    checks = []

    print("=" * 60)
    print(f"  PREFLIGHT CHECK: {MODEL_ID}")
    print("=" * 60)
    print()

    check_file(checks, BINARY, "CE-QUAL-W2 binary", critical=True, executable=True)
    check_binary_starts(checks, BINARY)
    check_python_interpreter(checks)

    print()
    for module in REQUIRED_IMPORTS:
        check_python_import(checks, module)

    print()
    for relpath in REQUIRED_KI_FILES:
        check_file(checks, KI_DIR / relpath, relpath, critical=True)
    for relpath in REQUIRED_TOOL_FILES:
        check_file(checks, KI_DIR / relpath, relpath, critical=True)

    print()
    for path, label in OPTIONAL_DATA_DIRS:
        check_optional_dir(checks, path, label)

    print()
    passed = sum(1 for c in checks if c["status"] == "pass")
    failed = len(checks) - passed
    critical_failed = sum(1 for c in checks if c["status"] != "pass" and c.get("critical"))
    print(f"  Results: {passed} passed, {failed} failed, {critical_failed} critical failed")
    if critical_failed:
        print(f"  STATUS: PREFLIGHT FAILED - fix critical issues above before running {MODEL_ID}")
    else:
        print(f"  STATUS: PREFLIGHT PASSED - safe to proceed with {MODEL_ID} setup/execution")
    print(f"  Diagnostics: {TRIPLETS}")

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
