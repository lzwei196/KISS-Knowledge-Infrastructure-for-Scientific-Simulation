#!/usr/bin/env python3
"""
Preflight check for the wflow Knowledge Infrastructure.

This script verifies the runtime, package imports, KI files, tools, and standard
data roots needed before attempting real Wflow.jl execution.
"""

import json
import os
import subprocess
import sys
from pathlib import Path


MODEL_ID = "wflow"
HYDROCRAFT_ROOT = Path("KISSPATH_ROOT")
KI_DIR = Path(__file__).resolve().parent
JULIA_BIN = HYDROCRAFT_ROOT / "model" / "julia-1.10.7" / "bin" / "julia"
JULIA_ENV = KI_DIR / "julia"
WFLOW_RUNNER = JULIA_ENV / "wflow_runner.jl"
PYTHON_ENV = HYDROCRAFT_ROOT / "python_env" / "bin" / "python"
TRIPLETS = KI_DIR / "diagnostics" / "triplets.yaml"

CHECKS = []


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}))
    sys.exit(0 if all(c["status"] == "pass" or not c.get("critical") for c in checks) else 1)


def add_check(kind, subject, critical, ok, fix, detail=""):
    subject = str(subject)
    check = {
        "kind": kind,
        "subject": subject,
        "critical": bool(critical),
        "status": "pass" if ok else "fail",
        "fix": "" if ok else f"{fix}; see {TRIPLETS}",
    }
    CHECKS.append(check)

    level = "OK" if ok else ("FAIL" if critical else "WARN")
    print(f"  {level:<5} {kind}: {subject}")
    if detail:
        print(f"        {detail}")
    if not ok:
        print(f"        Fix: {check['fix']}")
    return ok


def realpath(path):
    return os.path.realpath(str(path))


def check_file(path, label, kind="data", critical=True, executable=False, readable=False):
    path = Path(path)
    subject = realpath(path)
    if not path.is_file():
        return add_check(kind, subject, critical, False, f"restore required file {path}", label)
    if executable and not os.access(path, os.X_OK):
        return add_check(kind, subject, critical, False, f"chmod +x {path}", label)
    if readable and not os.access(path, os.R_OK):
        return add_check(kind, subject, critical, False, f"chmod +r {path}", label)
    return add_check(kind, subject, critical, True, "", label)


def check_dir(path, label, critical=True, must_be_nonempty=True):
    path = Path(path)
    subject = realpath(path)
    if not path.is_dir():
        return add_check("data", subject, critical, False, f"restore or mount directory {path}", label)
    if must_be_nonempty and not any(path.iterdir()):
        return add_check("data", subject, critical, False, f"populate directory {path}", label)
    return add_check("data", subject, critical, True, "", label)


def check_command(cmd, subject, kind, critical, fix, timeout=30, ok_returncodes=(0,), detail_label=""):
    try:
        result = subprocess.run(
            [str(c) for c in cmd],
            cwd=str(KI_DIR),
            text=True,
            capture_output=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        return add_check(kind, subject, critical, False, fix, f"{detail_label}{exc}")
    except subprocess.TimeoutExpired:
        return add_check(kind, subject, critical, False, fix, f"{detail_label}timed out after {timeout}s")

    output = "\n".join(x.strip() for x in (result.stdout, result.stderr) if x.strip())
    if len(output) > 300:
        output = output[:300] + "..."
    ok = result.returncode in ok_returncodes
    detail = f"{detail_label}returncode={result.returncode}"
    if output:
        detail = f"{detail}; {output}"
    return add_check(kind, subject, critical, ok, fix, detail)


def check_python_import(module, critical=True):
    subject = f"{PYTHON_ENV} -c import {module}"
    fix = (
        f"install {module.split('.')[0]} into {HYDROCRAFT_ROOT / 'python_env'} "
        f"with {PYTHON_ENV} -m pip install {module.split('.')[0]}"
    )
    return check_command(
        [PYTHON_ENV, "-c", f"__import__({module!r})"],
        subject,
        "import",
        critical,
        fix,
        timeout=30,
        detail_label=f"{module}: ",
    )


def check_julia_wflow_available():
    subject = f"{realpath(JULIA_BIN)} --project={realpath(JULIA_ENV)} import Wflow"
    code = 'using Wflow; println("Wflow import ok")'
    return check_command(
        [JULIA_BIN, f"--project={JULIA_ENV}", "-e", code],
        subject,
        "import",
        True,
        f"install Wflow.jl in {JULIA_ENV}: {JULIA_BIN} --project={JULIA_ENV} -e 'using Pkg; Pkg.add(\"Wflow\")'",
        timeout=120,
        detail_label="Wflow.jl: ",
    )


def check_runner_starts():
    subject = realpath(WFLOW_RUNNER)
    return check_command(
        [JULIA_BIN, f"--project={JULIA_ENV}", WFLOW_RUNNER],
        subject,
        "run",
        True,
        f"repair {WFLOW_RUNNER} or reinstall Wflow.jl; see {TRIPLETS}",
        timeout=30,
        ok_returncodes=(1,),
        detail_label="runner without TOML should return usage error: ",
    )


def check_runner_content():
    subject = realpath(WFLOW_RUNNER)
    try:
        text = WFLOW_RUNNER.read_text(encoding="utf-8")
    except OSError as exc:
        return add_check("binary", subject, True, False, f"restore readable runner script {WFLOW_RUNNER}", str(exc))
    ok = "using Wflow" in text and "Wflow.run" in text
    return add_check(
        "binary",
        subject,
        True,
        ok,
        f"restore the Wflow.jl runner script from KI source control",
        "runner loads Wflow and calls Wflow.run",
    )


def main():
    print("=" * 60)
    print("  PREFLIGHT CHECK: wflow")
    print("=" * 60)
    print()

    check_file(JULIA_BIN, "Julia 1.10.7 runtime", kind="binary", critical=True, executable=True)
    check_command(
        [JULIA_BIN, "--version"],
        realpath(JULIA_BIN),
        "run",
        True,
        f"install Julia at {JULIA_BIN}",
        timeout=30,
        detail_label="Julia startup: ",
    )

    check_file(WFLOW_RUNNER, "manifest model binary: julia/wflow_runner.jl", kind="binary", critical=True, executable=True)
    check_runner_content()
    check_runner_starts()

    check_dir(JULIA_ENV, "Julia project environment", critical=True)
    check_file(JULIA_ENV / "Project.toml", "Julia Project.toml", kind="data", critical=True, readable=True)
    check_file(JULIA_ENV / "Manifest.toml", "Julia Manifest.toml", kind="data", critical=True, readable=True)
    check_julia_wflow_available()

    check_file(PYTHON_ENV, "HydroCraft Python interpreter", kind="binary", critical=True, executable=True)
    for module in [
        "yaml",
        "numpy",
        "pandas",
        "xarray",
        "netCDF4",
        "geopandas",
        "shapely",
        "matplotlib",
        "rasterio",
        "scipy",
        "ki_tools_common.soil_utils",
        "ki_tools_common.load_forcing",
    ]:
        check_python_import(module, critical=True)
    check_python_import("hydromt_wflow", critical=False)

    for rel in [
        "SKILL.md",
        "knowledge_infrastructure.yaml",
        "dag.yaml",
        "diagnostics/triplets.yaml",
        "tools/run_wflow_full_pipeline.py",
        "tools/s0_config/setup_wflow_config.py",
        "tools/s1_hydromt/build_data_catalog.py",
        "tools/s1_hydromt/derive_landsurface_params.py",
        "tools/s1_hydromt/fetch_merit_hydro_tiles.py",
        "tools/s1_hydromt/run_hydromt_build.py",
        "tools/s2_forcing/calculate_pet.py",
        "tools/s2_forcing/convert_forcing_to_wflow.py",
        "tools/s3_parameters/adjust_parameters.py",
        "tools/s3_parameters/generate_wflow_toml.py",
        "tools/s4_execution/run_wflow.py",
        "tools/s5_postprocess/compare_with_vic.py",
        "tools/s5_postprocess/extract_discharge.py",
        "tools/s5_postprocess/extract_spatial_output.py",
        "tools/s5_postprocess/water_balance.py",
        "tools/s6_sediment/build_sediment_model.py",
        "tools/s6_sediment/derive_usle_c.py",
        "tools/s6_sediment/derive_usle_k.py",
        "tools/s6_sediment/run_wflow_sediment.py",
        "tools/s8_sediment_post/analyze_sediment.py",
        "tools/s9_coupling/wflow_recharge_to_modflow.py",
        "tools/s9_coupling/wflow_to_cama.py",
        "tools/s10_reservoir/configure_reservoirs.py",
        "tools/s10_reservoir/lookup_dams.py",
    ]:
        check_file(KI_DIR / rel, rel, kind="data", critical=True, readable=True)

    # Preserve the legacy common HydroCraft data checks as noncritical because
    # individual runs may provide their own TOML/static/forcing inputs.
    for path, label in [
        ("KISSPATH_OBS", "Observation data"),
        ("KISSPATH_FORCING", "Forcing data"),
        ("KISSPATH_STATIC", "DEM data"),
        ("KISSPATH_STATIC", "Soil data"),
        ("KISSPATH_DATA/MERIT_DEM", "Global MERIT DEM tiles"),
        ("KISSPATH_DATA/MERIT_Hydro", "MERIT-Hydro tiles"),
    ]:
        check_dir(path, label, critical=False)

    print()
    passed = sum(1 for c in CHECKS if c["status"] == "pass")
    failed = len(CHECKS) - passed
    critical_failed = [c for c in CHECKS if c["status"] == "fail" and c.get("critical")]
    print(f"  Results: {passed} passed, {failed} failed")
    if critical_failed:
        print("  STATUS: PREFLIGHT FAILED")
        print(f"  Recovery: check {TRIPLETS} first, then apply the fixes above.")
    else:
        print("  STATUS: PREFLIGHT PASSED")

    emit_report(MODEL_ID, CHECKS)


if __name__ == "__main__":
    main()
