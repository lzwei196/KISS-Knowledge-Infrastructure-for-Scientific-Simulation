#!/usr/bin/env python3
"""
Preflight check for ParFlow.

Verifies the executable, Python runtime imports, KI tool syntax, diagnostics,
and known common data locations before a simulation is attempted.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


MODEL_ID = "ParFlow"
KI_DIR = Path(__file__).resolve().parent
TRIPLETS = KI_DIR / "diagnostics" / "triplets.yaml"
PARFLOW_BIN = Path("KISSPATH_BINARIES/parflow/install/bin/parflow")
PARFLOW_DIR = PARFLOW_BIN.parent.parent
HYDROCRAFT_PYTHON = Path("KISSPATH_PYTHON_ENV/bin/python")

CHECKS = []


def fix_text(message):
    return f"{message}; check {TRIPLETS} for known recovery steps"


def add_check(kind, subject, critical, status, fix=""):
    record = {
        "kind": kind,
        "subject": str(subject),
        "critical": bool(critical),
        "status": status,
        "fix": "" if status == "pass" else fix_text(fix),
    }
    CHECKS.append(record)
    label = "OK" if status == "pass" else ("FAIL" if critical else "WARN")
    print(f"  {label:<5} {kind}: {subject}")
    if status != "pass":
        print(f"        Fix: {record['fix']}")
    return status == "pass"


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}, sort_keys=True))
    sys.exit(0 if all(c["status"] == "pass" or not c.get("critical") for c in checks) else 1)


def check_file(path, label, *, critical=True, executable=False):
    path = Path(path)
    subject = path.resolve() if path.exists() else path
    if not path.is_file():
        return add_check("binary" if executable else "data", subject, critical, "fail", f"{label} not found at {path}")
    if executable and not os.access(path, os.X_OK):
        return add_check("binary", path.resolve(), critical, "fail", f"run chmod +x {path}")
    return add_check("binary" if executable else "data", path.resolve(), critical, "pass")


def check_dir(path, label, *, critical=False, non_empty=False):
    path = Path(path)
    subject = path.resolve() if path.exists() else path
    if not path.is_dir():
        return add_check("data", subject, critical, "fail", f"{label} directory not found")
    if non_empty and not any(path.iterdir()):
        return add_check("data", path.resolve(), critical, "fail", f"{label} directory is empty")
    return add_check("data", path.resolve(), critical, "pass")


def check_binary_starts(path):
    path = Path(path)
    if not path.is_file() or not os.access(path, os.X_OK):
        return

    env = os.environ.copy()
    env["PARFLOW_DIR"] = str(PARFLOW_DIR)
    env["PATH"] = f"{PARFLOW_BIN.parent}:{env.get('PATH', '')}"
    try:
        proc = subprocess.run(
            [str(path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=10,
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired:
        add_check("run", path.resolve(), True, "fail", f"{path} timed out during startup check")
        return
    except OSError as exc:
        add_check("run", path.resolve(), True, "fail", f"{path} could not start: {exc}")
        return

    output = proc.stdout or ""
    if "USAGE:" in output or "Usage:" in output or proc.returncode == 0:
        add_check("run", path.resolve(), True, "pass")
    else:
        add_check(
            "run",
            path.resolve(),
            True,
            "fail",
            f"{path} started but did not print usage or exit cleanly; return code {proc.returncode}",
        )


def check_import(module, *, critical=True):
    if not HYDROCRAFT_PYTHON.is_file():
        add_check(
            "import",
            f"{module} via {HYDROCRAFT_PYTHON}",
            critical,
            "fail",
            f"HydroCraft Python interpreter missing at {HYDROCRAFT_PYTHON}",
        )
        return

    env = os.environ.copy()
    env["PARFLOW_DIR"] = str(PARFLOW_DIR)
    env["PATH"] = f"{PARFLOW_BIN.parent}:{env.get('PATH', '')}"
    code = f"import {module}"
    proc = subprocess.run(
        [str(HYDROCRAFT_PYTHON), "-c", code],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=20,
        env=env,
        check=False,
    )
    if proc.returncode == 0:
        add_check("import", f"{module} via {HYDROCRAFT_PYTHON}", critical, "pass")
    else:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()[-1:] or ["import failed"]
        add_check(
            "import",
            f"{module} via {HYDROCRAFT_PYTHON}",
            critical,
            "fail",
            f"install or repair {module.split('.')[0]} in {HYDROCRAFT_PYTHON}: {detail[0]}",
        )


def check_python_tool_syntax():
    tool_files = sorted((KI_DIR / "tools").glob("**/*.py"))
    if not tool_files:
        add_check("data", KI_DIR / "tools", True, "fail", "KI tools directory has no Python tools")
        return
    if not HYDROCRAFT_PYTHON.is_file():
        add_check("import", f"tool syntax via {HYDROCRAFT_PYTHON}", True, "fail", "HydroCraft Python interpreter missing")
        return

    proc = subprocess.run(
        [str(HYDROCRAFT_PYTHON), "-m", "py_compile", *map(str, tool_files)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=30,
        check=False,
    )
    if proc.returncode == 0:
        add_check("import", f"{len(tool_files)} KI Python tools via {HYDROCRAFT_PYTHON}", True, "pass")
    else:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()[-1:] or ["py_compile failed"]
        add_check("import", "KI Python tool syntax", True, "fail", f"repair tool syntax/importability: {detail[0]}")


def check_binary_search(name, label):
    found = shutil.which(name)
    if found:
        add_check("binary", Path(found).resolve(), False, "pass")
        return
    add_check("binary", name, False, "fail", f"{label} not found in PATH")


def check_common_data():
    common = [
        ("KISSPATH_OBS", "Observation data"),
        ("KISSPATH_FORCING", "Forcing data"),
        ("KISSPATH_STATIC", "DEM data"),
        ("KISSPATH_STATIC", "Soil data"),
    ]
    for path, label in common:
        check_dir(path, label, critical=False)


def main():
    print("=" * 60)
    print(f"  PREFLIGHT CHECK: {MODEL_ID}")
    print("=" * 60)
    print()

    check_file(PARFLOW_BIN, "ParFlow executable", critical=True, executable=True)
    check_binary_starts(PARFLOW_BIN)
    check_binary_search("mpirun", "MPI launcher")

    print()
    check_import("numpy", critical=True)
    check_import("parflow", critical=True)
    check_import("parflow.tools.io", critical=True)
    check_import("parflow.tools.fs", critical=True)
    check_python_tool_syntax()

    print()
    check_file(KI_DIR / "knowledge_infrastructure.yaml", "KI manifest", critical=True)
    check_file(KI_DIR / "dag.yaml", "DAG contract", critical=True)
    check_file(TRIPLETS, "Diagnostic triplets", critical=True)

    print()
    check_common_data()

    print()
    passed = sum(1 for c in CHECKS if c["status"] == "pass")
    failed = len(CHECKS) - passed
    print(f"  Results: {passed} passed, {failed} failed")
    if any(c["status"] == "fail" and c["critical"] for c in CHECKS):
        print("  STATUS: PREFLIGHT FAILED - fix critical issues above before running")
    else:
        print("  STATUS: PREFLIGHT PASSED - safe to proceed with model execution")

    emit_report(MODEL_ID, CHECKS)


if __name__ == "__main__":
    main()
