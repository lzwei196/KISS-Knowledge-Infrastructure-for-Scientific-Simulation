#!/usr/bin/env python3
"""
Preflight check for WRF-Hydro standalone KI.

The KDT gate executes this script before model execution. It performs real
environment checks, prints actionable failures, and ends with exactly one
PREFLIGHT_REPORT= JSON line.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


MODEL_ID = "WRF_Hydro"
KI_DIR = Path(__file__).resolve().parent
TRIPLETS = KI_DIR / "diagnostics" / "triplets.yaml"

RUN_DIR = Path("KISSPATH_BINARIES/wrf_hydro/source/trunk/NDHMS/Run")
WRF_HYDRO_EXE = RUN_DIR / "wrf_hydro_NoahMP.exe"
MPIRUN = Path("KISSPATH_BINARIES/wrf_hydro/deps/mpich-install/bin/mpirun")
PYTHON = Path("KISSPATH_PYTHON_ENV/bin/python")

REQUIRED_TBLS = [
    RUN_DIR / "HYDRO.TBL",
    RUN_DIR / "CHANPARM.TBL",
    RUN_DIR / "GENPARM.TBL",
    RUN_DIR / "MPTABLE.TBL",
    RUN_DIR / "SOILPARM.TBL",
]

REQUIRED_IMPORTS = [
    "netCDF4",
    "numpy",
    "scipy",
    "geopandas",
    "rasterio",
    "pyproj",
    "whitebox",
    "pandas",
    "ki_tools_common.units",
]


checks: list[dict[str, object]] = []


def emit_report() -> None:
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": MODEL_ID, "checks": checks}, sort_keys=True))
    failed_critical = any(c["status"] == "fail" and c.get("critical") for c in checks)
    sys.exit(1 if failed_critical else 0)


def add_check(kind: str, subject: str, critical: bool, ok: bool, fix: str = "") -> None:
    checks.append(
        {
            "kind": kind,
            "subject": subject,
            "critical": critical,
            "status": "pass" if ok else "fail",
            "fix": "" if ok else fix,
        }
    )


def real_subject(path: Path) -> str:
    return os.path.realpath(path)


def print_result(ok: bool, label: str, subject: str, critical: bool, fix: str = "") -> None:
    level = "OK" if ok else ("FAIL" if critical else "WARN")
    print(f"  {level:<5} {label}: {subject}")
    if not ok and fix:
        print(f"        Fix: {fix}")


def check_file(
    path: Path,
    label: str,
    *,
    kind: str = "data",
    critical: bool = True,
    executable: bool = False,
    use_realpath: bool = True,
) -> bool:
    subject = real_subject(path) if use_realpath else str(path)
    if not path.is_file():
        fix = f"Restore {path}; check {TRIPLETS} for matching recovery steps."
        print_result(False, label, subject, critical, fix)
        add_check(kind, subject, critical, False, fix)
        return False
    if executable and not os.access(path, os.X_OK):
        fix = f"chmod +x {path}; if permissions drift again, check {TRIPLETS}."
        print_result(False, label, subject, critical, fix)
        add_check(kind, subject, critical, False, fix)
        return False
    print_result(True, label, subject, critical)
    add_check(kind, subject, critical, True)
    return True


def check_dir(path: Path, label: str, *, critical: bool = True, non_empty: bool = True) -> bool:
    subject = real_subject(path)
    if not path.is_dir():
        fix = f"Restore or mount {path}; see {TRIPLETS} before attempting model execution."
        print_result(False, label, subject, critical, fix)
        add_check("data", subject, critical, False, fix)
        return False
    count = sum(1 for _ in path.iterdir())
    if non_empty and count == 0:
        fix = f"Populate {path} with the required WRF-Hydro input data; see {TRIPLETS}."
        print_result(False, label, f"{subject} (empty)", critical, fix)
        add_check("data", subject, critical, False, fix)
        return False
    print_result(True, label, f"{subject} ({count} items)", critical)
    add_check("data", subject, critical, True)
    return True


def check_import(module: str) -> bool:
    py_subject = str(PYTHON)
    subject = f"{py_subject} import {module}"
    if not PYTHON.is_file() or not os.access(PYTHON, os.X_OK):
        fix = f"Restore executable Python venv at {PYTHON}; then re-run preflight."
        print_result(False, f"Python import {module}", subject, True, fix)
        add_check("import", subject, True, False, fix)
        return False
    proc = subprocess.run(
        [str(PYTHON), "-c", f"import {module}"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
    )
    if proc.returncode == 0:
        print_result(True, f"Python import {module}", subject, True)
        add_check("import", subject, True, True)
        return True
    detail = (proc.stderr or proc.stdout).strip().splitlines()
    msg = detail[-1] if detail else f"exit code {proc.returncode}"
    fix = f"Install/fix {module} in {PYTHON.parent.parent}: {msg}; check {TRIPLETS}."
    print_result(False, f"Python import {module}", subject, True, fix)
    add_check("import", subject, True, False, fix)
    return False


def check_mpirun() -> bool:
    candidates = [MPIRUN]
    found = shutil.which("mpirun")
    if found:
        candidates.append(Path(found))
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            subject = real_subject(candidate)
            proc = subprocess.run(
                [str(candidate), "--version"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=10,
            )
            ok = proc.returncode == 0 and ("HYDRA" in proc.stdout or "Version" in proc.stdout or proc.stdout.strip())
            if ok:
                print_result(True, "MPI launcher", subject, True)
                add_check("binary", subject, True, True)
                return True
            fix = f"{candidate} exists but did not report a version; reinstall MPICH and check {TRIPLETS}."
            print_result(False, "MPI launcher", subject, True, fix)
            add_check("binary", subject, True, False, fix)
            return False
    subject = str(MPIRUN)
    fix = f"Install MPICH or restore {MPIRUN}; WRF-Hydro is run via mpirun. Check {TRIPLETS}."
    print_result(False, "MPI launcher", subject, True, fix)
    add_check("binary", subject, True, False, fix)
    return False


def check_binary_starts() -> bool:
    subject = real_subject(WRF_HYDRO_EXE)
    if not WRF_HYDRO_EXE.is_file() or not os.access(WRF_HYDRO_EXE, os.X_OK):
        fix = f"Restore executable {WRF_HYDRO_EXE} before startup probing; check {TRIPLETS}."
        print_result(False, "WRF-Hydro startup probe", subject, True, fix)
        add_check("run", subject, True, False, fix)
        return False
    # Probe in a throw-away folder, never in RUN_DIR: the executable opens
    # namelist.hrldas / diag_hydro.* in its working folder (it even creates an
    # empty namelist.hrldas when none is there) and could write output, so a probe
    # in the shared install could overwrite files or disturb another run.
    # Only the namelists and tables are copied; their ./DOMAIN and ./FORCING
    # paths do not exist in the temp folder, so the model stops after reading the
    # namelists (READ_HRLDAS_HDRINFO) and cannot simulate.
    with tempfile.TemporaryDirectory(prefix="wrfhydro_preflight_") as probe_dir:
        for name in ("namelist.hrldas", "hydro.namelist"):
            src = RUN_DIR / name
            if src.is_file():
                shutil.copy2(src, Path(probe_dir) / name)
        for tbl in REQUIRED_TBLS:
            if tbl.is_file():
                shutil.copy2(tbl, Path(probe_dir) / tbl.name)
        try:
            proc = subprocess.run(
                [str(WRF_HYDRO_EXE)],
                cwd=probe_dir,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5,
            )
        except subprocess.TimeoutExpired as exc:
            # A timeout alone is no proof of a start (it could hang before
            # initialisation); the output seen so far must show the config/read phase.
            def _txt(x):
                return x.decode(errors="replace") if isinstance(x, bytes) else (x or "")
            seen = _txt(exc.stdout) + "\n" + _txt(exc.stderr)
            if "Calling config noahlsm_offline" in seen or "READ_HRLDAS_HDRINFO" in seen:
                print_result(True, "WRF-Hydro startup probe",
                             f"{subject} (reached config/read phase before the 5 s probe limit)", True)
                add_check("run", subject, True, True)
                return True
            fix = (f"Executable ran 5 s without reaching WRF-Hydro initialization (no config/read "
                   f"output); it may hang at start-up. Check MPI/NetCDF libs and {TRIPLETS}.")
            print_result(False, "WRF-Hydro startup probe", subject, True, fix)
            add_check("run", subject, True, False, fix)
            return False
        except OSError as exc:
            fix = f"Executable could not start: {exc}; check shared libraries and {TRIPLETS}."
            print_result(False, "WRF-Hydro startup probe", subject, True, fix)
            add_check("run", subject, True, False, fix)
            return False

    output = (proc.stdout or "") + "\n" + (proc.stderr or "")
    started = "Calling config noahlsm_offline" in output or "READ_HRLDAS_HDRINFO" in output
    if started:
        print_result(True, "WRF-Hydro startup probe", f"{subject} (reached config/read phase)", True)
        add_check("run", subject, True, True)
        return True
    tail = " | ".join(output.strip().splitlines()[-3:]) or f"exit code {proc.returncode}"
    fix = f"Binary did not reach WRF-Hydro initialization: {tail}; check NetCDF/Fortran libs and {TRIPLETS}."
    print_result(False, "WRF-Hydro startup probe", subject, True, fix)
    add_check("run", subject, True, False, fix)
    return False


def main() -> None:
    print("=" * 60)
    print("  PREFLIGHT CHECK: WRF-Hydro")
    print("=" * 60)
    print()

    check_file(WRF_HYDRO_EXE, "WRF-Hydro NoahMP executable", kind="binary", critical=True, executable=True)
    check_binary_starts()
    check_mpirun()

    print()
    for tbl in REQUIRED_TBLS:
        check_file(tbl, f"WRF-Hydro table {tbl.name}", kind="data", critical=True)

    print()
    check_file(PYTHON, "HydroCraft Python interpreter", kind="binary", critical=True, executable=True, use_realpath=False)
    for module in REQUIRED_IMPORTS:
        check_import(module)

    print()
    # Informational only: the forcing a run uses is chosen per run (NASA POWER
    # download, CMFD/MSWX conversion, or a prepared FORCING/ folder) and is checked
    # when that run is prepared (wrfhydro_run_gate.input_snapshot stops on a
    # missing or empty forcing folder). A shared global forcing folder is not
    # required for every workflow, so it must not fail the install check.
    check_dir(Path("KISSPATH_FORCING"), "Global forcing archive (optional)", critical=False, non_empty=True)
    check_dir(Path("KISSPATH_OBS"), "Observation data", critical=False, non_empty=True)
    check_dir(Path("KISSPATH_STATIC"), "DEM data", critical=False, non_empty=True)
    check_dir(Path("KISSPATH_STATIC"), "Soil data", critical=False, non_empty=True)
    check_dir(Path("KISSPATH_DATA/landcover"), "Landcover data", critical=False, non_empty=True)
    check_dir(Path("KISSPATH_DATA/merit_hydro"), "MERIT Hydro data", critical=False, non_empty=True)

    print()
    check_file(KI_DIR / "knowledge_infrastructure.yaml", "KI manifest", kind="data", critical=True)
    check_file(KI_DIR / "dag.yaml", "DAG manifest", kind="data", critical=True)
    check_file(TRIPLETS, "Diagnostic triplets", kind="data", critical=True)
    print(f"  INFO  Recovery reference: {TRIPLETS}")

    print()
    passed = sum(1 for c in checks if c["status"] == "pass")
    failed = len(checks) - passed
    failed_critical = sum(1 for c in checks if c["status"] == "fail" and c.get("critical"))
    print(f"  Results: {passed} passed, {failed} failed ({failed_critical} critical failed)")
    if failed_critical:
        print("  STATUS: PREFLIGHT FAILED - fix critical issues above before running")
    else:
        print("  STATUS: PREFLIGHT PASSED - safe to proceed with model execution")

    emit_report()


if __name__ == "__main__":
    main()
