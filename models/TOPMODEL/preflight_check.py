#!/usr/bin/env python3
"""Preflight check for the TOPMODEL knowledge infrastructure."""

import json
import os
import subprocess
import sys
from pathlib import Path


MODEL_ID = "TOPMODEL"
KI_DIR = Path(__file__).resolve().parent
MODEL_ROOT = KI_DIR.parent
SOURCE_DIR = MODEL_ROOT / "source" / "repo"
BINARY = SOURCE_DIR / "run_bmi"
DIAGNOSTICS = KI_DIR / "diagnostics" / "triplets.yaml"
HYDRO_PYTHON = Path("KISSPATH_PYTHON_ENV/bin/python")
PYTHON = HYDRO_PYTHON if HYDRO_PYTHON.exists() else Path(sys.executable)


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}, sort_keys=True))
    failed_critical = [c for c in checks if c.get("critical") and c["status"] != "pass"]
    sys.exit(1 if failed_critical else 0)


def add_check(checks, kind, subject, critical, ok, fix):
    status = "pass" if ok else "fail"
    checks.append(
        {
            "kind": kind,
            "subject": str(subject),
            "critical": bool(critical),
            "status": status,
            "fix": "" if ok else f"{fix}; see {DIAGNOSTICS} for recovery triplets",
        }
    )
    label = "OK" if ok else "FAIL"
    print(f"  {label:<5} {kind}: {subject}")


def check_file(checks, path, label, critical=True, executable=False, kind="data"):
    path = Path(path)
    subject = path.resolve() if path.exists() else path
    ok = path.is_file()
    fix = f"restore or regenerate {label} at {path}"
    if ok and executable:
        ok = os.access(path, os.X_OK)
        fix = f"make {label} executable with chmod +x {path}"
    add_check(checks, kind, subject, critical, ok, fix)
    return ok


def check_dir(checks, path, label, critical=True, nonempty=False):
    path = Path(path)
    subject = path.resolve() if path.exists() else path
    ok = path.is_dir()
    if ok and nonempty:
        ok = any(path.iterdir())
    fix = f"restore or regenerate {label} at {path}"
    add_check(checks, "data", subject, critical, ok, fix)
    return ok


def check_import(checks, module, critical=True):
    result = subprocess.run(
        [str(PYTHON), "-c", f"import {module}"],
        cwd=str(KI_DIR),
        capture_output=True,
        text=True,
        timeout=10,
    )
    ok = result.returncode == 0
    fix = f"install {module.split('.')[0]} into {PYTHON} or repair PYTHONPATH"
    add_check(checks, "import", f"{module} via {PYTHON}", critical, ok, fix)
    if not ok and result.stderr:
        print(f"        {result.stderr.strip().splitlines()[-1]}")
    return ok


def check_tool_import(checks, module, critical=True):
    validators = Path("KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect_multi_agent/validators")
    code = (
        "import sys; "
        f"sys.path.insert(0, {str(KI_DIR / 'tools')!r}); "
        f"sys.path.insert(0, {str(validators)!r}); "
        f"import {module}"
    )
    result = subprocess.run(
        [str(PYTHON), "-c", code],
        cwd=str(KI_DIR),
        capture_output=True,
        text=True,
        timeout=10,
    )
    ok = result.returncode == 0
    fix = f"repair imports for tools/{module}.py or restore validator dependencies"
    add_check(checks, "import", f"tools.{module} via {PYTHON}", critical, ok, fix)
    if not ok and result.stderr:
        print(f"        {result.stderr.strip().splitlines()[-1]}")
    return ok


def check_binary_starts(checks):
    binary_realpath = BINARY.resolve() if BINARY.exists() else BINARY
    if not BINARY.is_file() or not os.access(BINARY, os.X_OK):
        add_check(
            checks,
            "binary",
            binary_realpath,
            True,
            False,
            f"build TOPMODEL with: cd {SOURCE_DIR / 'src'} && make clean && make",
        )
        return False

    add_check(
        checks,
        "binary",
        binary_realpath,
        True,
        True,
        f"build TOPMODEL with: cd {SOURCE_DIR / 'src'} && make clean && make",
    )

    result = subprocess.run(
        [str(BINARY)],
        cwd=str(SOURCE_DIR),
        capture_output=True,
        text=True,
        timeout=10,
    )
    ok = result.returncode == 0
    add_check(
        checks,
        "run",
        f"{binary_realpath} cheap demo start in {SOURCE_DIR}",
        True,
        ok,
        f"run {BINARY} from {SOURCE_DIR} and inspect data/topmod.run, inputs.dat, subcat.dat, params.dat",
    )
    if result.stdout:
        print(f"        stdout: {result.stdout.strip().splitlines()[0]}")
    if not ok and result.stderr:
        print(f"        stderr: {result.stderr.strip().splitlines()[-1]}")
    return ok


def main():
    checks = []
    print(f"{' PREFLIGHT: TOPMODEL ':=^60}")
    print(f"  KI: {KI_DIR}")
    print(f"  Python for import checks: {PYTHON}")

    check_dir(checks, KI_DIR / "tools", "KI tools directory", critical=True, nonempty=True)
    for tool in [
        "convert_forcing_to_topmodel.py",
        "generate_twi_subcat.py",
        "run_topmodel.py",
        "parse_topmodel_output.py",
        "calibrate_topmodel.py",
    ]:
        check_file(checks, KI_DIR / "tools" / tool, f"KI tool {tool}", critical=True)

    check_file(checks, KI_DIR / "SKILL.md", "SKILL.md", critical=True)
    check_file(checks, KI_DIR / "knowledge_infrastructure.yaml", "KI manifest", critical=True)
    check_file(checks, KI_DIR / "dag.yaml", "DAG", critical=True)
    check_file(checks, DIAGNOSTICS, "diagnostic triplets", critical=True)

    check_dir(checks, SOURCE_DIR, "TOPMODEL source repo", critical=True, nonempty=True)
    check_file(checks, SOURCE_DIR / "src" / "Makefile", "TOPMODEL Makefile", critical=True)
    for fname in ["topmod.run", "inputs.dat", "subcat.dat", "params.dat"]:
        check_file(checks, SOURCE_DIR / "data" / fname, f"demo data/{fname}", critical=True)

    check_binary_starts(checks)

    for module in [
        "numpy",
        "pandas",
        "yaml",
        "ki_tools_common.load_forcing",
    ]:
        check_import(checks, module, critical=True)

    for module in [
        "convert_forcing_to_topmodel",
        "generate_twi_subcat",
        "run_topmodel",
        "parse_topmodel_output",
        "calibrate_topmodel",
    ]:
        check_tool_import(checks, module, critical=True)

    # Optional: GDAL unlocks higher-quality TWI generation, but the tool has a
    # documented simplified fallback, so absence is not a model execution blocker.
    check_import(checks, "osgeo.gdal", critical=False)

    failed = [c for c in checks if c["status"] != "pass"]
    print(f"\n  Results: {len(checks) - len(failed)} passed, {len(failed)} failed")
    if failed:
        print(f"  Fixes point to {DIAGNOSTICS}")
    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
