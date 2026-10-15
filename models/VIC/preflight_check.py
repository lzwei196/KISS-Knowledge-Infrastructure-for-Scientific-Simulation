#!/usr/bin/env python3
"""
Preflight check for the VIC knowledge infrastructure.

This script verifies the real VIC executable, routing executable, HydroCraft
Python environment, KI metadata, stage tools, and default data paths before a
run. It always finishes by emitting:

    PREFLIGHT_REPORT=<json>
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


MODEL_ID = "VIC"
KI_DIR = Path(__file__).resolve().parent
DIAGNOSTICS = KI_DIR / "diagnostics" / "triplets.yaml"

# codex structure_sync r1 #3: every install path is written as ONE full literal under its role
# prefix (python_env, model), never rebuilt from a server root, so the KISS porter maps them to
# KISSPATH_PYTHON_ENV / KISSPATH_BINARIES and a desktop install (<root>/venv, <root>/binaries,
# or any configured location) resolves to the paths the installer actually wrote.
PYTHON_ENV = Path(os.environ.get("VIC_PYTHON", "KISSPATH_PYTHON_ENV/bin/python"))
VIC_EXE = Path(os.environ.get(
    "VIC_EXE", "KISSPATH_BINARIES/VIC-5.1.0/vic/drivers/classic/vic_classic.exe"))
ROUT_EXE = Path(os.environ.get("VIC_ROUT_EXE", "KISSPATH_BINARIES/route_1.0/src/rout"))
CAMA_EXE = Path(os.environ.get("CAMA_EXE", "KISSPATH_BINARIES/cmf_v420_pkg/src/MAIN_cmf"))

TRIPLETS_FIX = f"Check {DIAGNOSTICS} for known recovery steps."


def _subject(path: Path) -> str:
    return str(path.resolve()) if path.exists() else str(path)


def add_check(
    checks: list[dict],
    *,
    kind: str,
    subject: str,
    critical: bool,
    ok: bool,
    fix: str = "",
    detail: str = "",
) -> bool:
    status = "pass" if ok else "fail"
    checks.append(
        {
            "kind": kind,
            "subject": subject,
            "critical": critical,
            "status": status,
            "fix": "" if ok else (fix or TRIPLETS_FIX),
        }
    )

    label = "OK" if ok else ("FAIL" if critical else "WARN")
    print(f"  {label:<5} {kind}: {subject}")
    if detail:
        print(f"        {detail}")
    if not ok:
        print(f"        Fix: {checks[-1]['fix']}")
    return ok


def check_file(
    checks: list[dict],
    path: Path,
    label: str,
    *,
    critical: bool = True,
    executable: bool = False,
) -> bool:
    subject = _subject(path)
    if not path.is_file():
        return add_check(
            checks,
            kind="binary" if executable else "data",
            subject=subject,
            critical=critical,
            ok=False,
            fix=f"Restore or correct {label} at {path}. {TRIPLETS_FIX}",
        )
    if executable and not os.access(path, os.X_OK):
        return add_check(
            checks,
            kind="binary",
            subject=subject,
            critical=critical,
            ok=False,
            fix=f"Run chmod +x {path}, or rebuild/install the executable. {TRIPLETS_FIX}",
        )
    return add_check(
        checks,
        kind="binary" if executable else "data",
        subject=subject,
        critical=critical,
        ok=True,
        detail=label,
    )


def check_dir(
    checks: list[dict],
    path: Path,
    label: str,
    *,
    critical: bool = True,
    nonempty: bool = True,
) -> bool:
    subject = _subject(path)
    if not path.is_dir():
        return add_check(
            checks,
            kind="data",
            subject=subject,
            critical=critical,
            ok=False,
            fix=f"Restore or correct {label} directory at {path}. {TRIPLETS_FIX}",
        )
    count = len(list(path.iterdir()))
    if nonempty and count == 0:
        return add_check(
            checks,
            kind="data",
            subject=subject,
            critical=critical,
            ok=False,
            fix=f"Populate {label} directory at {path}. {TRIPLETS_FIX}",
        )
    return add_check(
        checks,
        kind="data",
        subject=subject,
        critical=critical,
        ok=True,
        detail=f"{label} ({count} items)",
    )


def check_python_import(
    checks: list[dict],
    module: str,
    *,
    critical: bool = True,
) -> bool:
    subject = f"{module} via {_subject(PYTHON_ENV)}"
    if not PYTHON_ENV.is_file():
        return add_check(
            checks,
            kind="import",
            subject=subject,
            critical=critical,
            ok=False,
            fix=f"Restore the HydroCraft Python interpreter at {PYTHON_ENV}. {TRIPLETS_FIX}",
        )

    code = f"import {module}"
    # codex structure_sync r1 #9: a non-executable interpreter (OSError) or a hung import
    # (TimeoutExpired) is a FAILED check, recorded so PREFLIGHT_REPORT is still emitted.
    try:
        proc = subprocess.run(
            [str(PYTHON_ENV), "-c", code],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=20,
        )
    except subprocess.TimeoutExpired:
        return add_check(
            checks, kind="import", subject=subject, critical=critical, ok=False,
            fix=f"'import {module}' did not finish within 20 s under {PYTHON_ENV}; repair the "
                f"package or the interpreter. {TRIPLETS_FIX}",
        )
    except OSError as exc:
        return add_check(
            checks, kind="import", subject=subject, critical=critical, ok=False,
            fix=f"Python interpreter {PYTHON_ENV} could not be started ({exc}). {TRIPLETS_FIX}",
        )
    if proc.returncode == 0:
        return add_check(
            checks,
            kind="import",
            subject=subject,
            critical=critical,
            ok=True,
        )
    err = (proc.stderr or proc.stdout).strip().splitlines()[-1:]
    detail = err[0] if err else f"return code {proc.returncode}"
    return add_check(
        checks,
        kind="import",
        subject=subject,
        critical=critical,
        ok=False,
        fix=(
            f"Install or repair Python dependency '{module}' in "
            f"KISSPATH_PYTHON_ENV. {TRIPLETS_FIX}"
        ),
        detail=detail,
    )


def check_command(
    checks: list[dict],
    command: list[str],
    subject: Path,
    label: str,
    *,
    critical: bool,
    ok_codes: set[int],
    required_text: str | None = None,
    fix: str | None = None,
) -> bool:
    real_subject = _subject(subject)
    # codex structure_sync r2 #1: MAIN_cmf (and the other binaries) start a run that reads
    # input_cmf.nam and writes log/output files in the CURRENT directory. The smoke test runs in
    # a fresh empty temp directory, so it can never touch a real run or the KI folder.
    scratch = tempfile.mkdtemp(prefix="vic_preflight_")
    try:
        proc = subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
            cwd=scratch,
        )
    except subprocess.TimeoutExpired:
        return add_check(
            checks,
            kind="run",
            subject=real_subject,
            critical=critical,
            ok=False,
            fix=fix or f"{label} did not return from a cheap smoke test. {TRIPLETS_FIX}",
        )
    except OSError as exc:
        return add_check(
            checks,
            kind="run",
            subject=real_subject,
            critical=critical,
            ok=False,
            fix=fix or f"{label} could not be started: {exc}. {TRIPLETS_FIX}",
        )
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    output = (proc.stdout or "") + (proc.stderr or "")
    ok = proc.returncode in ok_codes
    if required_text is not None:
        ok = ok and required_text in output
    tail = " ".join(output.strip().split())[:240]
    return add_check(
        checks,
        kind="run",
        subject=real_subject,
        critical=critical,
        ok=ok,
        fix=fix or f"Repair or rebuild {label}. {TRIPLETS_FIX}",
        detail=f"{label}; rc={proc.returncode}; {tail}" if tail else f"{label}; rc={proc.returncode}",
    )


def emit_report(model_id: str, checks: list[dict]) -> None:
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}, sort_keys=True))
    has_blocker = any(c["status"] == "fail" and c.get("critical") for c in checks)
    sys.exit(1 if has_blocker else 0)


def main() -> None:
    checks: list[dict] = []

    print("=" * 60)
    print("  PREFLIGHT CHECK: VIC classic + Lohmann routing")
    print("=" * 60)
    print(f"  KI: {KI_DIR}")
    print(f"  Recovery diagnostics: {DIAGNOSTICS}")
    print()

    # Primary executable from knowledge_infrastructure.yaml; subject is the realpath.
    check_file(checks, VIC_EXE, "VIC 5.1.0 classic driver", executable=True)
    check_command(
        checks,
        [str(VIC_EXE), "-v"],
        VIC_EXE,
        "VIC version smoke test",
        critical=True,
        ok_codes={0},
        required_text="VIC",
    )

    # Required downstream routing binary for gauge discharge scoring.
    check_file(checks, ROUT_EXE, "Lohmann route_1.0 rout", executable=True)
    check_command(
        checks,
        [str(ROUT_EXE)],
        ROUT_EXE,
        "route_1.0 usage smoke test",
        critical=True,
        ok_codes={0},
        required_text="USAGE",
    )

    # Existing legacy check retained: this KI also documents CaMa-Flood availability.
    check_file(checks, CAMA_EXE, "CaMa-Flood 4.20 MAIN_cmf", executable=True)
    check_command(
        checks,
        [str(CAMA_EXE)],
        CAMA_EXE,
        "CaMa-Flood startup smoke test",
        critical=True,
        ok_codes={0, 2},
        required_text="input_cmf.nam",
        fix=f"Rebuild CaMa-Flood; the smoke test runs it in an empty directory and expects the missing input_cmf.nam message. {TRIPLETS_FIX}",
    )

    print()
    check_file(checks, PYTHON_ENV, "HydroCraft Python interpreter", executable=True)
    for module in [
        "numpy",
        "pandas",
        "xarray",
        "netCDF4",
        "geopandas",
        "shapely",
        "rasterio",
        "rioxarray",
        "rasterstats",
        "yaml",
        "ki_tools_common.load_forcing",
        "ki_tools_common.soil_utils",
        "ki_tools_common.terrain_ops",
    ]:
        check_python_import(checks, module)

    print()
    for rel in [
        "SKILL.md",
        "knowledge_infrastructure.yaml",
        "dag.yaml",
        "diagnostics/triplets.yaml",
        "docs/format_spec.yaml",
        "docs/vic_param/global_param_template.txt",
        "s1_grid/make_basin_grid_nc.py",
        "s2_forcing/forcing_1d.py",
        "s2_forcing/process_forcing.py",
        "s3_soil/fill_parameters1.py",
        "s3_soil/fill_parameters2.py",
        "s4_veg/process_vegetation_detailed.py",
        "s5_routing/build_routing_param.py",
        "s5_routing/run_routing.py",
        "s6_post/grid_runoff_nc.py",
        "tools/calib_run.py",
    ]:
        check_file(checks, KI_DIR / rel, f"KI file {rel}", critical=True)

    # codex structure_sync r1 #5: the default China / Huai reference datasets below are
    # PROJECT inputs, not software. A project that uses other forcing, elevation or soil
    # inputs is a valid install, so these are reported (WARN, critical=False) and never block.
    # The project's own inputs are checked before a run (calib drivers fail closed on them).
    print()
    print("  Reference project data (informational, not install blockers):")
    check_dir(
        checks,
        Path("KISSPATH_FORCING/huai/Data_forcing_01dy_025deg"),
        "CMFD daily forcing",
        critical=False,
    )
    check_dir(
        checks,
        Path("KISSPATH_STATIC/china_dem_90m"),
        "DEM 90m directory",
        critical=False,
    )
    for path, label in [
        (Path("KISSPATH_STATIC/china_dem_90m/china_dem_90m.tif"), "DEM raster"),
        (Path("KISSPATH_DATA/elev/elev_CMFD_V0200_B-00_fx_010deg.nc"), "CMFD elevation grid"),
        (Path("KISSPATH_DATA/his_average_prec/prec_CMFD_010deg_meanAnnual_1951-2020_mm.nc"), "CMFD annual precipitation climatology"),
        (Path("KISSPATH_STATIC/HWSD_China_Geo.img"), "HWSD soil raster"),
        (Path("KISSPATH_DATA/landcover/AVHRR_1km_LANDCOVER_1981_1994.GLOBAL.tif"), "AVHRR landcover raster"),
        (Path("KISSPATH_DATA/vic_param/veglib.LDAS"), "VIC vegetation library"),
        (Path("KISSPATH_DATA/插值/global_soil_param_new.txt"), "global soil parameter table"),
    ]:
        check_file(checks, path, label, critical=False)

    print()
    for path, label in [
        (Path("KISSPATH_OBS"), "Observation data"),
        (Path("KISSPATH_FORCING"), "Forcing data root"),
        (Path("KISSPATH_STATIC"), "Soil data root"),
    ]:
        check_dir(checks, path, label, critical=False, nonempty=False)

    print()
    passed = sum(1 for c in checks if c["status"] == "pass")
    failed = len(checks) - passed
    critical_failed = sum(1 for c in checks if c["status"] == "fail" and c["critical"])
    print(f"  Results: {passed} passed, {failed} failed ({critical_failed} critical)")
    if critical_failed:
        print(f"  STATUS: PREFLIGHT FAILED. {TRIPLETS_FIX}")
    else:
        print("  STATUS: PREFLIGHT PASSED")

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
