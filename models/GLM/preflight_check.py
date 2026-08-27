#!/usr/bin/env python3
"""
Preflight check for the GLM knowledge infrastructure.

This verifies the static prerequisites needed before a GLM run is attempted:
the configured GLM executable, HydroCraft Python imports used by the KI tools,
tool files, diagnostics, and known shared data locations. Per-run files such as
glm3.nml and boundary CSVs are validated by tools/s8_execution/run_glm.py.
"""

import json
import os
import subprocess
import sys
from pathlib import Path


MODEL_ID = "GLM"
KI_DIR = Path(__file__).resolve().parent
GLM_BINARY = Path("KISSPATH_BINARIES/glm/bin/glm")
PYTHON_ENV = Path("KISSPATH_PYTHON_ENV/bin/python")
TRIPLETS = KI_DIR / "diagnostics" / "triplets.yaml"

TOOL_FILES = [
    "tools/s10_coupling/glm_to_cama_outflow.py",
    "tools/s1_lake_identification/build_morphometry.py",
    "tools/s1_lake_identification/lookup_hydrolakes.py",
    "tools/s2_met_forcing/convert_met_to_glm.py",
    "tools/s3_inflow/convert_inflow_to_glm.py",
    "tools/s4_outflow/configure_outflow.py",
    "tools/s5_init_profiles/build_init_profiles.py",
    "tools/s6_namelist/generate_glm_nml.py",
    "tools/s7_aed_config/configure_inflow_wq.py",
    "tools/s7_aed_config/generate_aed_config.py",
    "tools/s8_execution/run_glm.py",
    "tools/s9_output_analysis/calibrate_glm.py",
    "tools/s9_output_analysis/load_ismn_obs.py",
    "tools/s9_output_analysis/load_ntl_lter_obs.py",
    "tools/s9_output_analysis/parse_aed_output.py",
    "tools/s9_output_analysis/parse_glm_output.py",
    "tools/s9_output_analysis/plot_glm_results.py",
]

IMPORTS = [
    "numpy",
    "pandas",
    "xarray",
    "netCDF4",
    "geopandas",
    "shapely",
    "matplotlib",
    "ki_tools_common",
]


def add_check(checks, kind, subject, critical, ok, fix):
    checks.append(
        {
            "kind": kind,
            "subject": str(subject),
            "critical": bool(critical),
            "status": "pass" if ok else "fail",
            "fix": "" if ok else fix,
        }
    )


def print_check(check):
    level = "OK" if check["status"] == "pass" else ("FAIL" if check["critical"] else "WARN")
    print(f"  {level:<5} {check['kind']}: {check['subject']}")
    if check["status"] == "fail":
        print(f"        Fix: {check['fix']}")


def check_file(checks, path, label, critical=True, executable=False):
    path = Path(path)
    subject = path.resolve(strict=False)
    ok = path.is_file() and (not executable or os.access(path, os.X_OK))
    if path.is_file() and executable:
        fix = f"chmod +x {path}; if it still fails, see {TRIPLETS}"
    else:
        fix = f"restore {label} at {path}; see {TRIPLETS}"
    add_check(checks, "binary" if executable else "data", subject, critical, ok, fix)


def check_dir(checks, path, label, critical=False):
    path = Path(path)
    subject = path.resolve(strict=False)
    ok = path.is_dir()
    fix = f"restore or mount {label} at {path}; see {TRIPLETS}"
    add_check(checks, "data", subject, critical, ok, fix)


def run_command(cmd, cwd=None, timeout=8):
    try:
        return subprocess.run(
            cmd,
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except Exception as exc:
        return exc


def check_glm_starts(checks):
    subject = GLM_BINARY.resolve(strict=False)
    result = run_command([str(GLM_BINARY), "--version"], cwd=KI_DIR, timeout=5)
    ok = (
        isinstance(result, subprocess.CompletedProcess)
        and result.returncode == 0
        and "General Lake Model" in (result.stdout + result.stderr)
    )
    fix = f"verify GLM starts with '{GLM_BINARY} --version'; see {TRIPLETS}"
    add_check(checks, "run", subject, True, ok, fix)


def check_import(checks, module):
    subject = f"{PYTHON_ENV}:import:{module}"
    code = f"import {module}"
    result = run_command([str(PYTHON_ENV), "-c", code], cwd=KI_DIR, timeout=10)
    ok = isinstance(result, subprocess.CompletedProcess) and result.returncode == 0
    fix = (
        f"install {module} into KISSPATH_PYTHON_ENV "
        f"and check {TRIPLETS}"
    )
    add_check(checks, "import", subject, True, ok, fix)


def check_tools_compile(checks):
    paths = [str(KI_DIR / rel) for rel in TOOL_FILES]
    result = run_command([str(PYTHON_ENV), "-m", "py_compile", *paths], cwd=KI_DIR, timeout=20)
    ok = isinstance(result, subprocess.CompletedProcess) and result.returncode == 0
    fix = f"fix Python syntax/import-time compile errors in tools/; see {TRIPLETS}"
    add_check(checks, "run", f"{PYTHON_ENV}:py_compile:tools", True, ok, fix)


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}))
    sys.exit(0 if all(c["status"] == "pass" or not c.get("critical") for c in checks) else 1)


def main():
    checks = []

    print("=" * 60)
    print("  PREFLIGHT CHECK: GLM")
    print("=" * 60)

    check_file(checks, GLM_BINARY, "GLM executable", critical=True, executable=True)
    check_glm_starts(checks)
    check_file(
        checks,
        "KISSPATH_BINARIES/glm/bin/VERSION",
        "GLM version file",
        critical=True,
    )

    check_file(checks, KI_DIR / "SKILL.md", "KI skill document", critical=True)
    check_file(checks, KI_DIR / "knowledge_infrastructure.yaml", "KI manifest", critical=True)
    check_file(checks, KI_DIR / "dag.yaml", "KI DAG", critical=True)
    check_file(checks, TRIPLETS, "diagnostic triplets", critical=True)

    for rel in TOOL_FILES:
        check_file(checks, KI_DIR / rel, rel, critical=True)

    check_file(
        checks,
        "KISSPATH_BINARIES/glm/examples/Sparkling/glm3.nml",
        "Sparkling Lake example namelist",
        critical=False,
    )
    check_dir(
        checks,
        "KISSPATH_BINARIES/glm/examples/Sparkling/bcs",
        "Sparkling Lake boundary-condition examples",
        critical=False,
    )

    check_file(
        checks,
        PYTHON_ENV,
        "HydroCraft Python interpreter",
        critical=True,
        executable=True,
    )
    for module in IMPORTS:
        check_import(checks, module)
    check_tools_compile(checks)

    check_file(
        checks,
        "KISSPATH_DATA/lakes/HydroLAKES_polys_v10.shp",
        "HydroLAKES shapefile for lake lookup",
        critical=False,
    )
    check_dir(checks, "KISSPATH_DATA/forcing", "forcing data", critical=False)
    check_dir(checks, "KISSPATH_OBS", "observation data", critical=False)
    check_dir(checks, "KISSPATH_STATIC", "DEM data", critical=False)
    check_dir(checks, "KISSPATH_STATIC", "soil data", critical=False)
    check_file(checks, "KISSPATH_DATA/ismn_clean.db", "ISMN observation database", critical=False)
    check_file(
        checks,
        "KISSPATH_DATA/obs/ntl-lter-phys-limno/ntl29_physical_limnology.csv",
        "NTL LTER water-temperature observations",
        critical=False,
    )

    print()
    for check in checks:
        print_check(check)

    passed = sum(1 for c in checks if c["status"] == "pass")
    failed = len(checks) - passed
    failed_critical = sum(1 for c in checks if c["critical"] and c["status"] == "fail")
    print()
    print(f"  Results: {passed} passed, {failed} failed, {failed_critical} critical failed")
    if failed_critical:
        print(f"  STATUS: PREFLIGHT FAILED - fix critical issues above. Recovery: {TRIPLETS}")
    else:
        print("  STATUS: PREFLIGHT PASSED - static GLM prerequisites are ready")

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
