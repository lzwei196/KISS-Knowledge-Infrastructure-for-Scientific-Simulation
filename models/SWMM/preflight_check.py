#!/usr/bin/env python3
"""
Preflight check for the SWMM Knowledge Infrastructure.

This verifies the real SWMM runtime before model execution: the KI-local venv,
the compiled SWMM engine shared library, Python packages used by the tools,
and required KI control/diagnostic files. The final line is the KDT gate
contract: PREFLIGHT_REPORT=<json>.
"""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
from pathlib import Path


MODEL_ID = "SWMM"
KI_DIR = Path(__file__).resolve().parent
MODEL_DIR = KI_DIR.parent
SWMM_PYTHON = MODEL_DIR / "venv" / "bin" / "python"
SWMM_ENGINE = (
    MODEL_DIR
    / "venv"
    / "lib"
    / "python3.12"
    / "site-packages"
    / "swmm"
    / "toolkit"
    / "libswmm5.so"
)
TRIPLETS = KI_DIR / "diagnostics" / "triplets.yaml"
FIX_DIAGNOSTICS = f"Check {TRIPLETS} for recovery guidance, then repair the reported path/package."


def add_check(checks, kind, subject, critical, ok, fix):
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
    return ok


def check_file(checks, path, label, critical=True, executable=False):
    path = Path(path)
    ok = path.is_file()
    if ok and executable:
        ok = os.access(path, os.X_OK)
    fix = f"Restore {label} at {path}. {FIX_DIAGNOSTICS}"
    if executable:
        fix = f"Restore {label} at {path} and ensure it is executable. {FIX_DIAGNOSTICS}"
    return add_check(checks, "binary" if executable else "data", path, critical, ok, fix)


def check_dir(checks, path, label, critical=False):
    path = Path(path)
    ok = path.is_dir()
    count = len(list(path.iterdir())) if ok else 0
    subject = f"{path} ({count} items)" if ok else path
    fix = f"Restore or mount {label} at {path}. {FIX_DIAGNOSTICS}"
    return add_check(checks, "data", subject, critical, ok, fix)


def check_import(checks, module, critical=True):
    if not SWMM_PYTHON.is_file():
        return add_check(
            checks,
            "import",
            f"{module} via {SWMM_PYTHON}",
            critical,
            False,
            f"Restore the SWMM venv interpreter at {SWMM_PYTHON}. {FIX_DIAGNOSTICS}",
        )

    code = (
        "import importlib.util, sys; "
        f"spec = importlib.util.find_spec({module!r}); "
        "sys.exit(0 if spec is not None else 1)"
    )
    try:
        result = subprocess.run(
            [str(SWMM_PYTHON), "-c", code],
            capture_output=True,
            text=True,
            timeout=30,
        )
        ok = result.returncode == 0
        detail = (result.stderr or result.stdout).strip()
    except Exception as exc:
        ok = False
        detail = str(exc)
    fix = (
        f"Install {module.split('.')[0]} into the SWMM venv with "
        f"{SWMM_PYTHON} -m pip install {module.split('.')[0]}; probe detail: {detail}. "
        f"{FIX_DIAGNOSTICS}"
    )
    return add_check(
        checks,
        "import",
        f"{module} via {SWMM_PYTHON}",
        critical,
        ok,
        fix,
    )


def check_engine_loads(checks):
    real_engine = Path(os.path.realpath(SWMM_ENGINE))
    ok = SWMM_ENGINE.is_file() and os.access(SWMM_ENGINE, os.X_OK)
    if ok:
        try:
            ctypes.CDLL(str(real_engine))
        except OSError as exc:
            ok = False
            fix = f"SWMM engine library failed to load: {exc}. {FIX_DIAGNOSTICS}"
        else:
            fix = ""
    else:
        fix = f"Restore the compiled SWMM engine at {SWMM_ENGINE}. {FIX_DIAGNOSTICS}"

    # Subject must be the realpath of the executable/library verified so the
    # KDT gate can compare it against the models DB.
    return add_check(checks, "binary", real_engine, True, ok, fix)


def check_swmm_smoke(checks):
    if not SWMM_PYTHON.is_file():
        return add_check(
            checks,
            "run",
            f"pyswmm/swmm.toolkit smoke via {SWMM_PYTHON}",
            True,
            False,
            f"Restore the SWMM venv interpreter at {SWMM_PYTHON}. {FIX_DIAGNOSTICS}",
        )

    code = """
from pyswmm import Simulation
from swmm.toolkit import solver
assert Simulation is not None
assert hasattr(solver, "swmm_open")
assert hasattr(solver, "swmm_close")
"""
    try:
        result = subprocess.run(
            [str(SWMM_PYTHON), "-c", code],
            capture_output=True,
            text=True,
            timeout=60,
        )
        ok = result.returncode == 0
        detail = (result.stderr or result.stdout).strip()
    except Exception as exc:
        ok = False
        detail = str(exc)
    fix = f"Repair the SWMM venv/package stack; smoke probe failed: {detail}. {FIX_DIAGNOSTICS}"
    return add_check(
        checks,
        "run",
        f"pyswmm/swmm.toolkit smoke via {SWMM_PYTHON}",
        True,
        ok,
        fix,
    )


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}, sort_keys=True))
    critical_failed = any(c["status"] != "pass" and c.get("critical") for c in checks)
    sys.exit(1 if critical_failed else 0)


def main():
    checks = []
    print("=" * 60)
    print(f"  PREFLIGHT CHECK: {MODEL_ID}")
    print("=" * 60)
    print()

    check_file(checks, SWMM_PYTHON, "SWMM venv Python interpreter", critical=True, executable=True)
    check_engine_loads(checks)
    check_import(checks, "pyswmm", critical=True)
    check_import(checks, "swmm.toolkit", critical=True)
    check_import(checks, "swmmanywhere", critical=True)
    check_import(checks, "numpy", critical=True)
    check_swmm_smoke(checks)

    print()
    check_file(checks, KI_DIR / "SKILL.md", "KI entrypoint", critical=True)
    check_file(checks, KI_DIR / "knowledge_infrastructure.yaml", "KI manifest", critical=True)
    check_file(checks, KI_DIR / "dag.yaml", "KI DAG", critical=True)
    check_file(checks, TRIPLETS, "diagnostic triplets", critical=True)
    check_file(checks, KI_DIR / "tools" / "s6_execution" / "run_swmm.py", "SWMM execution tool", critical=True)
    check_file(checks, KI_DIR / "tools" / "s5_model_assembly" / "validate_inp_file.py", "INP validation tool", critical=True)

    print()
    # Legacy checks preserved as noncritical: these shared HydroCraft data
    # mounts are useful for some runs but are not universally required by SWMM.
    check_dir(checks, "KISSPATH_OBS", "Observation data", critical=False)
    check_dir(checks, "KISSPATH_FORCING", "Forcing data", critical=False)
    check_dir(checks, "KISSPATH_STATIC", "DEM data", critical=False)
    check_dir(checks, "KISSPATH_STATIC", "Soil data", critical=False)

    print()
    failed = [c for c in checks if c["status"] != "pass"]
    critical_failed = [c for c in failed if c.get("critical")]
    print(f"  Results: {len(checks) - len(failed)} passed, {len(failed)} failed")
    if critical_failed:
        print("  STATUS: PREFLIGHT FAILED - fix critical blockers before running")
    else:
        print("  STATUS: PREFLIGHT PASSED - safe to proceed with model execution")
        if failed:
            print("  Note: noncritical data mounts are missing; supply run-specific data as needed.")

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
