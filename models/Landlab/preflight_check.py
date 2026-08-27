#!/usr/bin/env python3
"""Preflight check for the Landlab knowledge infrastructure."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


MODEL_ID = "Landlab"
EXPECTED_VERSION = "2.10.1"
KI_DIR = Path(__file__).resolve().parent
TRIPLETS = KI_DIR / "diagnostics" / "triplets.yaml"
PYTHON_ENV = Path("KISSPATH_PYTHON_ENV/bin/python")
MANIFEST_PACKAGE = Path(
    "KISSPATH_KI_ROOT/Landlab/source/repo/src/landlab/__init__.py"
)

checks: list[dict[str, object]] = []


def add_check(
    kind: str,
    subject: str | Path,
    critical: bool,
    ok: bool,
    fix: str,
) -> None:
    checks.append(
        {
            "kind": kind,
            "subject": os.path.realpath(str(subject)),
            "critical": critical,
            "status": "pass" if ok else "fail",
            "fix": "" if ok else fix,
        }
    )


def run_python(code: str, timeout: int = 20) -> subprocess.CompletedProcess[str] | None:
    if not PYTHON_ENV.is_file():
        return None
    env = os.environ.copy()
    existing_path = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        str(KI_DIR) if not existing_path else f"{KI_DIR}{os.pathsep}{existing_path}"
    )
    return subprocess.run(
        [str(PYTHON_ENV), "-c", code],
        text=True,
        capture_output=True,
        timeout=timeout,
        env=env,
        check=False,
    )


def check_file(path: Path, label: str, critical: bool = True) -> None:
    ok = path.is_file()
    print(("  OK    " if ok else "  FAIL  ") + f"{label}: {path}")
    add_check(
        "data",
        path,
        critical,
        ok,
        f"Restore {path}. Check {TRIPLETS} for recovery steps.",
    )


def check_python_env() -> None:
    ok = PYTHON_ENV.is_file() and os.access(PYTHON_ENV, os.X_OK)
    print(("  OK    " if ok else "  FAIL  ") + f"HydroCraft Python interpreter: {PYTHON_ENV}")
    add_check(
        "binary",
        PYTHON_ENV,
        True,
        ok,
        f"Restore executable Python at {PYTHON_ENV}; then rerun this preflight. Check {TRIPLETS}.",
    )


def check_manifest_package() -> None:
    ok = MANIFEST_PACKAGE.is_file()
    print(("  OK    " if ok else "  FAIL  ") + f"Manifest Landlab package file: {MANIFEST_PACKAGE}")
    add_check(
        "binary",
        MANIFEST_PACKAGE,
        True,
        ok,
        f"Restore the Landlab source package file recorded in the models DB. Check {TRIPLETS}.",
    )


def check_import(module: str, label: str, critical: bool = True) -> None:
    code = (
        "import importlib, os; "
        f"m = importlib.import_module({module!r}); "
        "print(os.path.realpath(getattr(m, '__file__', 'built-in')))"
    )
    try:
        proc = run_python(code)
    except subprocess.TimeoutExpired:
        proc = None
        timed_out = True
    else:
        timed_out = False

    ok = proc is not None and proc.returncode == 0 and not timed_out
    detail = proc.stdout.strip().splitlines()[-1] if ok and proc.stdout.strip() else module
    if ok:
        print(f"  OK    {label}: import {module} via {PYTHON_ENV}")
    elif timed_out:
        print(f"  FAIL  {label}: import {module} timed out via {PYTHON_ENV}")
    else:
        err = (proc.stderr if proc else "HydroCraft Python interpreter not available").strip()
        print(f"  FAIL  {label}: import {module} failed: {err}")
    add_check(
        "import",
        detail,
        critical,
        ok,
        f"Use {PYTHON_ENV} and install/repair {module.split('.')[0]}; check {TRIPLETS} first.",
    )


def check_landlab_version() -> None:
    code = "import landlab; print(landlab.__version__)"
    try:
        proc = run_python(code)
    except subprocess.TimeoutExpired:
        proc = None
        timed_out = True
    else:
        timed_out = False

    found = proc.stdout.strip().splitlines()[-1] if proc and proc.stdout.strip() else ""
    ok = proc is not None and proc.returncode == 0 and not timed_out and found == EXPECTED_VERSION
    if ok:
        print(f"  OK    Landlab version: {found}")
    else:
        err = "timed out" if timed_out else (proc.stderr.strip() if proc else "no interpreter")
        print(f"  FAIL  Landlab version: expected {EXPECTED_VERSION}, got {found or err}")
    add_check(
        "import",
        "landlab version",
        True,
        ok,
        f"Install Landlab {EXPECTED_VERSION} in {PYTHON_ENV}; check {TRIPLETS} for known fixes.",
    )


def check_landlab_smoke() -> None:
    code = r"""
from landlab import RasterModelGrid
from landlab.components import FlowAccumulator
mg = RasterModelGrid((3, 3), xy_spacing=1.0)
mg.add_zeros("topographic__elevation", at="node")
fa = FlowAccumulator(mg)
fa.run_one_step()
assert "drainage_area" in mg.at_node
print("ok")
"""
    try:
        proc = run_python(code, timeout=30)
    except subprocess.TimeoutExpired:
        proc = None
        timed_out = True
    else:
        timed_out = False

    ok = proc is not None and proc.returncode == 0 and not timed_out
    if ok:
        print("  OK    Landlab smoke run: RasterModelGrid + FlowAccumulator")
    elif timed_out:
        print("  FAIL  Landlab smoke run: timed out")
    else:
        err = (proc.stderr if proc else "HydroCraft Python interpreter not available").strip()
        print(f"  FAIL  Landlab smoke run: {err}")
    add_check(
        "run",
        "RasterModelGrid FlowAccumulator smoke run",
        True,
        ok,
        f"Repair the Landlab runtime in {PYTHON_ENV}; check {TRIPLETS} for matching diagnostics.",
    )


def check_tools() -> None:
    required_tools = [
        "tools/convert_dem_to_grid.py",
        "tools/convert_soil_params.py",
        "tools/dissect_atchafalaya_ssc_q_surrogate.py",
        "tools/dissect_loess_plateau_sediment_yield.py",
        "tools/dissect_loess_plateau_slope_area.py",
        "tools/dissect_space_ssc_q_rating.py",
        "tools/parse_landlab_output.py",
        "tools/run_landlab.py",
    ]
    for rel_path in required_tools:
        check_file(KI_DIR / rel_path, rel_path, critical=True)


def emit_report() -> None:
    print(
        "PREFLIGHT_REPORT="
        + json.dumps({"model_id": MODEL_ID, "checks": checks}, sort_keys=True)
    )
    failed_critical = [
        c for c in checks if c["status"] == "fail" and bool(c.get("critical"))
    ]
    sys.exit(1 if failed_critical else 0)


def main() -> None:
    print(f"{' PREFLIGHT: Landlab ':=^60}")
    print()

    check_python_env()
    check_manifest_package()
    check_import("landlab", "Landlab")
    check_import("landlab.grid", "Landlab grid module")
    check_import("landlab.components", "Landlab components")
    check_import("numpy", "NumPy")
    check_import("yaml", "PyYAML")
    check_landlab_version()
    check_landlab_smoke()
    check_tools()
    check_file(TRIPLETS, "diagnostics/triplets.yaml", critical=True)

    passed = sum(1 for c in checks if c["status"] == "pass")
    failed = len(checks) - passed
    print()
    if TRIPLETS.is_file():
        print(f"  INFO  Diagnostic triplets available: {TRIPLETS}")
        print("        If the model fails, check diagnostics/triplets.yaml first.")
    print(f"  Results: {passed} passed, {failed} failed")
    print(
        "  STATUS: PREFLIGHT FAILED"
        if any(c["status"] == "fail" and c.get("critical") for c in checks)
        else "  STATUS: PREFLIGHT PASSED"
    )
    emit_report()


if __name__ == "__main__":
    main()
