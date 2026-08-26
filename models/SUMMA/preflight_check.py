#!/usr/bin/env python3
"""
Preflight check for the SUMMA Knowledge Infrastructure.

Run this before attempting any SUMMA setup or execution. It verifies the real
model executable, companion routing executable, Python environment, KI recovery
metadata, stage tools, and model parameter tables required by the workflow.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


MODEL_ID = "SUMMA"
KI_DIR = Path(__file__).resolve().parent
DIAGNOSTICS = KI_DIR / "diagnostics" / "triplets.yaml"

SUMMA_EXE = Path("KISSPATH_BINARIES/summa/bin/summa.exe")
SUMMA_BASE_SETTINGS = Path("KISSPATH_BINARIES/summa/case_study/base_settings")
MIZUROUTE_EXE = Path(
    "KISSPATH_BINARIES/mizuRoute/mizuRoute-main/route/bin/mizuroute.exe"
)
MIZUROUTE_PARAM_NML = Path(
    "KISSPATH_BINARIES/mizuRoute/mizuRoute-main/route/ancillary_data/param.nml.default"
)
PYTHON_ENV = Path("KISSPATH_PYTHON_ENV/bin/python")

CHECKS: list[dict[str, object]] = []


def add_check(kind: str, subject: str, critical: bool, ok: bool, fix: str = "") -> None:
    status = "pass" if ok else "fail"
    check = {
        "kind": kind,
        "subject": subject,
        "critical": bool(critical),
        "status": status,
        "fix": "" if ok else fix,
    }
    CHECKS.append(check)
    marker = "OK" if ok else ("FAIL" if critical else "WARN")
    print(f"  {marker:<5} {kind}: {subject}")
    if not ok and fix:
        print(f"        Fix: {fix}")


def emit_report(model_id: str, checks: list[dict[str, object]]) -> None:
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}))
    failed_critical = [c for c in checks if c["status"] != "pass" and c.get("critical")]
    sys.exit(1 if failed_critical else 0)


def check_file(path: Path, label: str, *, kind: str = "data", critical: bool = True) -> bool:
    ok = path.is_file() and path.stat().st_size > 0
    fix = f"Restore {label}; check {DIAGNOSTICS} for known SUMMA recovery steps."
    add_check(kind, str(path), critical, ok, fix)
    return ok


def check_executable(path: Path, label: str, *, critical: bool = True) -> bool:
    subject = os.path.realpath(path)
    ok = path.is_file() and os.access(path, os.X_OK)
    fix = f"Install or rebuild {label} at {path}; see {DIAGNOSTICS}."
    if path.is_file() and not os.access(path, os.X_OK):
        fix = f"Make {label} executable: chmod +x {path}; see {DIAGNOSTICS}."
    add_check("binary", subject, critical, ok, fix)
    return ok


def check_summa_starts(path: Path) -> None:
    subject = f"{os.path.realpath(path)} --help"
    if not (path.is_file() and os.access(path, os.X_OK)):
        add_check(
            "run",
            subject,
            True,
            False,
            f"Fix the SUMMA executable first; see {DIAGNOSTICS}.",
        )
        return
    try:
        proc = subprocess.run(
            [str(path), "--help"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5,
            check=False,
        )
    except subprocess.TimeoutExpired:
        add_check("run", subject, True, False, f"SUMMA startup timed out; see {DIAGNOSTICS}.")
        return
    except OSError as exc:
        add_check("run", subject, True, False, f"SUMMA failed to start: {exc}; see {DIAGNOSTICS}.")
        return

    output = f"{proc.stdout}\n{proc.stderr}"
    ok = proc.returncode == 0 and "Usage:" in output and "-m" in output
    add_check(
        "run",
        subject,
        True,
        ok,
        f"SUMMA did not print the expected usage banner; see {DIAGNOSTICS}.",
    )


def check_mizuroute_starts(path: Path) -> None:
    subject = f"{os.path.realpath(path)} --help"
    if not (path.is_file() and os.access(path, os.X_OK)):
        add_check(
            "run",
            subject,
            True,
            False,
            f"Fix the mizuRoute executable first; see {DIAGNOSTICS}.",
        )
        return
    try:
        proc = subprocess.run(
            [str(path), "--help"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5,
            check=False,
        )
    except subprocess.TimeoutExpired:
        add_check("run", subject, True, False, f"mizuRoute startup timed out; see {DIAGNOSTICS}.")
        return
    except OSError as exc:
        add_check("run", subject, True, False, f"mizuRoute failed to start: {exc}; see {DIAGNOSTICS}.")
        return

    output = f"{proc.stdout}\n{proc.stderr}"
    ok = "FileNotFound[file='--help']" in output or "init_model/read_control" in output
    add_check(
        "run",
        subject,
        True,
        ok,
        f"mizuRoute did not reach its control-file reader; see {DIAGNOSTICS}.",
    )


def check_python_imports() -> None:
    modules = [
        "numpy",
        "netCDF4",
        "xarray",
        "pandas",
        "yaml",
        "geopandas",
        "rasterio",
        "shapely",
        "scipy",
        "ki_tools_common.units",
        "ki_tools_common.metrics",
        "ki_tools_common.soil_utils",
        "ki_tools_common.landcover",
    ]

    if not PYTHON_ENV.is_file():
        add_check(
            "binary",
            os.path.realpath(PYTHON_ENV),
            True,
            False,
            f"Restore the HydroCraft Python environment at {PYTHON_ENV}; see {DIAGNOSTICS}.",
        )
        for module in modules:
            add_check(
                "import",
                f"{PYTHON_ENV}: {module}",
                True,
                False,
                f"Cannot check import until {PYTHON_ENV} exists; see {DIAGNOSTICS}.",
            )
        return

    add_check(
        "binary",
        os.path.realpath(PYTHON_ENV),
        True,
        os.access(PYTHON_ENV, os.X_OK),
        f"Make the HydroCraft Python executable runnable: chmod +x {PYTHON_ENV}; see {DIAGNOSTICS}.",
    )

    for module in modules:
        subject = f"{PYTHON_ENV}: import {module}"
        try:
            proc = subprocess.run(
                [str(PYTHON_ENV), "-c", f"import {module}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10,
                check=False,
            )
        except subprocess.TimeoutExpired:
            add_check("import", subject, True, False, f"Import timed out; see {DIAGNOSTICS}.")
            continue
        except OSError as exc:
            add_check("import", subject, True, False, f"Python env failed to run: {exc}; see {DIAGNOSTICS}.")
            continue
        add_check(
            "import",
            subject,
            True,
            proc.returncode == 0,
            f"Install {module.split('.')[0]} into {PYTHON_ENV}; see {DIAGNOSTICS}.",
        )


def check_stage_tools() -> None:
    tool_files = [
        "tools/s1_domain_setup/create_gru_hru.py",
        "tools/s1_domain_setup/create_local_attributes.py",
        "tools/s2_forcing_prep/convert_vic_forcing_to_summa.py",
        "tools/s2_forcing_prep/build_summa_forcing_from_reanalysis.py",
        "tools/s3_decisions/configure_decisions.py",
        "tools/s4_parameters/set_trial_parameters.py",
        "tools/s5_initial_conditions/create_initial_conditions.py",
        "tools/s6_execution/create_file_manager.py",
        "tools/s6_execution/validate_file_manager.py",
        "tools/s6_execution/run_summa.py",
        "tools/s6_execution/parse_summa_output.py",
        "tools/s7_physics_comparison/compare_physics.py",
        "tools/s7_physics_comparison/plot_summa_results.py",
        "tools/s7_physics_comparison/compare_spatial_field.py",
        "tools/s8_routing/build_river_network.py",
        "tools/s8_routing/summa_to_mizuroute.py",
        "tools/s8_routing/run_mizuroute.py",
    ]
    for rel in tool_files:
        check_file(KI_DIR / rel, rel, kind="data", critical=True)


def check_metadata_and_docs() -> None:
    required = [
        "SKILL.md",
        "knowledge_infrastructure.yaml",
        "dag.yaml",
        "docs/format_spec.yaml",
        "docs/s1_domain_setup_skill.md",
        "docs/s2_forcing_prep_skill.md",
        "docs/s3_decisions_skill.md",
        "docs/s4_parameters_skill.md",
        "docs/s5_initial_conditions_skill.md",
        "docs/s6_execution_skill.md",
        "docs/s7_physics_comparison_skill.md",
        "docs/s8_routing_skill.md",
    ]
    for rel in required:
        check_file(KI_DIR / rel, rel, kind="data", critical=True)
    check_file(DIAGNOSTICS, "diagnostic triplets", kind="data", critical=True)


def check_summa_tables() -> None:
    for name in ("VEGPARM.TBL", "SOILPARM.TBL", "GENPARM.TBL", "MPTABLE.TBL"):
        check_file(SUMMA_BASE_SETTINGS / name, name, kind="data", critical=True)


def check_manifest_binary_path() -> None:
    manifest = KI_DIR / "knowledge_infrastructure.yaml"
    subject = f"{manifest}: package.binary.path == {SUMMA_EXE}"
    if not manifest.is_file():
        add_check(
            "data",
            subject,
            True,
            False,
            f"Restore {manifest}; see {DIAGNOSTICS}.",
        )
        return
    text = manifest.read_text(encoding="utf-8")
    ok = f"path: {SUMMA_EXE}" in text
    add_check(
        "data",
        subject,
        True,
        ok,
        f"Update package.binary.path in {manifest} to {SUMMA_EXE}; see {DIAGNOSTICS}.",
    )


def main() -> None:
    print("=" * 60)
    print(f"  PREFLIGHT CHECK: {MODEL_ID}")
    print("=" * 60)
    print()

    check_manifest_binary_path()
    check_executable(SUMMA_EXE, "SUMMA")
    check_summa_starts(SUMMA_EXE)
    check_executable(MIZUROUTE_EXE, "mizuRoute")
    check_mizuroute_starts(MIZUROUTE_EXE)
    check_file(MIZUROUTE_PARAM_NML, "mizuRoute param.nml.default", kind="data", critical=True)
    check_python_imports()
    check_summa_tables()
    check_metadata_and_docs()
    check_stage_tools()

    print()
    passed = sum(1 for check in CHECKS if check["status"] == "pass")
    failed = len(CHECKS) - passed
    print(f"  Results: {passed} passed, {failed} failed")
    if failed:
        print(f"  STATUS: PREFLIGHT HAS FAILURES - check fixes above and {DIAGNOSTICS}")
    else:
        print("  STATUS: PREFLIGHT PASSED - safe to proceed with SUMMA execution")
    emit_report(MODEL_ID, CHECKS)


if __name__ == "__main__":
    main()
