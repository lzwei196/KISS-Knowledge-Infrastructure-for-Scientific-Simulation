#!/usr/bin/env python3
"""
Preflight check for the Pywr Knowledge Infrastructure.

This script verifies the real runtime contract before any model execution:
the HydroCraft Python environment with Pywr, the Pywr runner declared in the
KI manifest, the GLPK solver path exercised through a minimal Pywr model, KI
tools, required data, and diagnostic recovery metadata.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


MODEL_ID = "Pywr"
KI_DIR = Path(__file__).resolve().parent
DIAGNOSTICS = KI_DIR / "diagnostics" / "triplets.yaml"
PYWR_PYTHON = Path("KISSPATH_PYTHON_ENV/bin/python")
RUN_PYWR = KI_DIR / "tools" / "s8_execution" / "run_pywr.py"
GRAND_DB = Path("KISSPATH_BINARIES/cmf_v420_pkg/map/data/GRanD_allocated.csv")

REQUIRED_TOOLS = [
    KI_DIR / "tools" / "s1_installation" / "verify_pywr_installation.py",
    KI_DIR / "tools" / "s2_dam_inventory" / "find_dams_in_basin.py",
    KI_DIR / "tools" / "s3_reservoir_properties" / "build_reservoir_properties.py",
    KI_DIR / "tools" / "s4_inflow" / "convert_obs_to_inflow.py",
    KI_DIR / "tools" / "s4_inflow" / "convert_vic_to_inflow.py",
    KI_DIR / "tools" / "s5_operating_rules" / "create_operating_rules.py",
    KI_DIR / "tools" / "s6_demands" / "create_demand_nodes.py",
    KI_DIR / "tools" / "s7_assembly" / "assemble_pywr_model.py",
    RUN_PYWR,
    KI_DIR / "tools" / "s8_execution" / "plot_reservoir_operations.py",
    KI_DIR / "tools" / "s8_execution" / "inject_releases_to_cama.py",
    KI_DIR / "tools" / "s8_execution" / "check_overtopping.py",
]

OPTIONAL_COMMON_DATA = [
    Path("KISSPATH_OBS"),
    Path("KISSPATH_FORCING"),
    Path("KISSPATH_STATIC"),
    Path("KISSPATH_STATIC"),
]


def fix(text):
    return f"{text}; then check {DIAGNOSTICS} for matching recovery triplets."


def add_check(checks, kind, subject, critical, passed, fix_text=""):
    check = {
        "kind": kind,
        "subject": str(subject),
        "critical": bool(critical),
        "status": "pass" if passed else "fail",
        "fix": "" if passed else fix(fix_text),
    }
    checks.append(check)
    label = "OK" if passed else ("FAIL" if critical else "WARN")
    print(f"  {label:<5} {kind}: {subject}")
    if not passed:
        print(f"        Fix: {check['fix']}")
    return passed


def run_command(args, timeout=30):
    try:
        return subprocess.run(
            [str(a) for a in args],
            cwd=str(KI_DIR),
            text=True,
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        completed = subprocess.CompletedProcess(args, 124)
        completed.stdout = exc.stdout or ""
        completed.stderr = exc.stderr or f"timed out after {timeout}s"
        return completed
    except OSError as exc:
        completed = subprocess.CompletedProcess(args, 127)
        completed.stdout = ""
        completed.stderr = str(exc)
        return completed


def check_python_import(checks, module, critical=True):
    subject = f"{PYWR_PYTHON} imports {module}"
    proc = run_command(
        [
            PYWR_PYTHON,
            "-c",
            f"import {module}; print(getattr({module.split('.')[0]}, '__version__', 'ok'))",
        ]
    )
    return add_check(
        checks,
        "import",
        subject,
        critical,
        proc.returncode == 0,
        f"Install/repair {module.split('.')[0]} in {PYWR_PYTHON}",
    )


def check_manifest_runner(checks):
    real_runner = RUN_PYWR.resolve(strict=False)
    ready = RUN_PYWR.is_file() and os.access(RUN_PYWR, os.X_OK)
    add_check(
        checks,
        "binary",
        real_runner,
        True,
        ready,
        f"Restore the manifest binary at {RUN_PYWR} and run chmod +x on it",
    )
    if not RUN_PYWR.is_file():
        return

    proc = run_command([PYWR_PYTHON, RUN_PYWR, "--help"])
    add_check(
        checks,
        "run",
        f"{PYWR_PYTHON} {real_runner} --help",
        True,
        proc.returncode == 0 and "--model" in proc.stdout and "--output_dir" in proc.stdout,
        "Make run_pywr.py start cleanly under the Pywr Python environment",
    )


def check_glpk_solver(checks):
    script = r"""
import json
import tempfile
from pathlib import Path
from pywr.model import Model

model_def = {
    "metadata": {"title": "preflight_solver_test"},
    "timestepper": {"start": "2000-01-01", "end": "2000-01-03", "timestep": 1},
    "nodes": [
        {"name": "input1", "type": "input", "max_flow": 10.0},
        {"name": "output1", "type": "output", "max_flow": 5.0, "cost": -10.0},
    ],
    "edges": [["input1", "output1"]],
    "solver": {"name": "glpk"},
}

with tempfile.TemporaryDirectory() as tmp:
    model_path = Path(tmp) / "model.json"
    model_path.write_text(json.dumps(model_def), encoding="utf-8")
    model = Model.load(str(model_path))
    model.run()
    print(getattr(model.solver, "name", type(model.solver).__name__))
"""
    proc = run_command([PYWR_PYTHON, "-c", script], timeout=45)
    add_check(
        checks,
        "run",
        f"{PYWR_PYTHON} minimal Pywr GLPK model",
        True,
        proc.returncode == 0,
        "Install GLPK/libglpk and verify Pywr solver availability with tools/s1_installation/verify_pywr_installation.py",
    )


def check_required_tools(checks):
    for tool in REQUIRED_TOOLS:
        add_check(
            checks,
            "data",
            tool.resolve(strict=False),
            True,
            tool.is_file(),
            f"Restore required KI tool {tool.relative_to(KI_DIR)}",
        )


def check_grand_database(checks):
    passed = GRAND_DB.is_file() and GRAND_DB.stat().st_size > 0
    add_check(
        checks,
        "data",
        GRAND_DB,
        True,
        passed,
        "Restore GRanD_allocated.csv at the HydroCraft model data path used by find_dams_in_basin.py",
    )


def check_common_data(checks):
    for path in OPTIONAL_COMMON_DATA:
        add_check(
            checks,
            "data",
            path,
            False,
            path.is_dir(),
            f"Create or mount optional HydroCraft data directory {path} if this run needs it",
        )


def check_diagnostics(checks):
    add_check(
        checks,
        "data",
        DIAGNOSTICS,
        True,
        DIAGNOSTICS.is_file() and DIAGNOSTICS.stat().st_size > 0,
        "Restore diagnostics/triplets.yaml so failures point to recovery guidance",
    )


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}, sort_keys=True))
    sys.exit(0 if all(c["status"] == "pass" or not c.get("critical") for c in checks) else 1)


def main():
    checks = []
    print("=" * 60)
    print(f"  PREFLIGHT CHECK: {MODEL_ID}")
    print("=" * 60)
    print()

    add_check(
        checks,
        "binary",
        PYWR_PYTHON.resolve(strict=False),
        True,
        PYWR_PYTHON.is_file() and os.access(PYWR_PYTHON, os.X_OK),
        f"Restore executable Pywr Python interpreter at {PYWR_PYTHON}",
    )
    check_manifest_runner(checks)
    check_python_import(checks, "pywr")
    check_python_import(checks, "pywr.model")

    for module in ["numpy", "pandas", "geopandas", "netCDF4", "xarray", "matplotlib", "shapely", "scipy"]:
        check_python_import(checks, module, critical=False)

    check_glpk_solver(checks)
    check_required_tools(checks)
    check_grand_database(checks)
    check_common_data(checks)
    check_diagnostics(checks)

    passed = sum(1 for check in checks if check["status"] == "pass")
    failed = len(checks) - passed
    critical_failed = sum(1 for check in checks if check["critical"] and check["status"] == "fail")
    print()
    print(f"  Results: {passed} passed, {failed} failed ({critical_failed} critical)")
    if critical_failed:
        print(f"  STATUS: PREFLIGHT FAILED - check {DIAGNOSTICS} and fix the blockers above")
    else:
        print("  STATUS: PREFLIGHT PASSED - model runtime is ready")
    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
