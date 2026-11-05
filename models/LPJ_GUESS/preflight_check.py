#!/usr/bin/env python3
"""Preflight check for the LPJ-GUESS knowledge infrastructure.

Checks the REAL engine first (LPJ-GUESS 4.1.1 `guess`, built 2026-10-06):
binary present + executable + starts (`guess -help`), NetCDF linked (needed
for `-input cf`), shipped instruction files and demo/soil data, the CO2 file,
Python imports, and that the engine tools compile and answer --help.
The Python SURROGATE tools (run_lpjguess.py & co.) are checked as
NON-critical: they are not the model.

Exit 0 = ready; 1 = a critical check failed (fix printed, see
diagnostics/triplets.yaml). The last line is PREFLIGHT_REPORT=<json>.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

MODEL_ID = "LPJ-GUESS"
KI_DIR = Path(__file__).resolve().parent
TOOLS_DIR = KI_DIR / "tools"
TRIPLETS = KI_DIR / "diagnostics" / "triplets.yaml"
_HC_PY = Path("KISSPATH_PYTHON_ENV/bin/python")
# interpreter for the tools: $KI_PYTHON, else the HydroCraft python_env, else this interpreter
PYTHON_ENV = Path(os.environ.get("KI_PYTHON")
                  or (str(_HC_PY) if _HC_PY.is_file() else sys.executable))
ENGINE_ROOT = Path(os.environ.get("LPJGUESS_ENGINE_ROOT",
                                  "KISSPATH_HOME/engine_builds_20261006/LPJ_GUESS"))
ENGINE_BIN = Path(os.environ.get("LPJGUESS_BIN", str(ENGINE_ROOT / "build" / "guess")))
INS_DIR = ENGINE_ROOT / "src" / "data" / "ins"
ENV_DIR = ENGINE_ROOT / "src" / "data" / "env"
REF_DEMO = ENGINE_ROOT / "run_global_demo"
SURROGATE_CONTRACT = KI_DIR / "docs" / "surrogate_lpjguess_lue_dag.yaml"
_CO2_REL = KI_DIR.parent / "inputs" / "co2" / "co2_1901_2014.txt"
CO2_FILE = Path(os.environ.get("LPJGUESS_CO2_FILE") or (
    _CO2_REL if _CO2_REL.is_file()
    else "KISSPATH_KI_ROOT/LPJ_GUESS/inputs/co2/co2_1901_2014.txt"))
DB = Path("KISSPATH_ROOT/hydrocraft.db")

ENGINE_TOOLS = ["run_lpjguess_engine.py", "build_lpjguess_cf_forcing.py",
                "build_lpjguess_co2_file.py", "parse_lpjguess_engine_output.py"]
SURROGATE_TOOLS = ["run_lpjguess.py", "convert_forcing_to_lpjguess.py",
                   "convert_parameters_to_lpjguess.py", "parse_output_lpjguess.py"]


def fix_text(action: str) -> str:
    return f"{action}; then check {TRIPLETS} for matching diagnostics."


def record(checks, kind, subject, critical, ok, fix):
    checks.append({"kind": kind, "subject": str(subject), "critical": bool(critical),
                   "status": "pass" if ok else "fail", "fix": "" if ok else fix})
    print(f"  {'OK' if ok else 'FAIL':<5} {kind}: {subject}{'' if critical else ' (non-critical)'}")
    if not ok:
        print(f"        Fix: {fix}")
    return ok


def run_command(cmd, *, cwd=KI_DIR, timeout=30):
    try:
        return subprocess.run([str(p) for p in cmd], cwd=str(cwd), text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as e:
        return subprocess.CompletedProcess(cmd, 127, "", str(e))


def db_binary_path():
    try:
        import sqlite3
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        row = con.execute("select binary_path from models where id=?", (MODEL_ID,)).fetchone()
        con.close()
        return row[0] if row else None
    except Exception:
        return None


def check_engine(checks):
    real = os.path.realpath(ENGINE_BIN)
    ok = os.path.isfile(real) and os.access(real, os.X_OK)
    record(checks, "binary", real, True, ok,
           fix_text(f"Restore the LPJ-GUESS 4.1.1 build at {ENGINE_BIN} "
                    f"(see {ENGINE_ROOT}/BUILD_LOG.md; do not substitute the surrogate)"))
    dbp = db_binary_path()
    if dbp:
        record(checks, "binary", f"models.binary_path == {dbp}", False,
               os.path.realpath(dbp) == real,
               fix_text(f"models.binary_path ({dbp}) differs from the engine checked ({real})"))
    if not ok:
        return False
    proc = run_command([real, "-help"], cwd="/tmp")
    started = proc.returncode == 0 and "Keywords defined within block" in proc.stdout
    record(checks, "run", f"{real} -help", True, started,
           fix_text(f"Engine does not start (rc={proc.returncode}): "
                    f"{(proc.stderr or proc.stdout).strip()[:300]}"))
    ldd = run_command(["ldd", real], cwd="/tmp")
    nc_ok = ldd.returncode == 0 and "libnetcdf" in ldd.stdout and "not found" not in ldd.stdout
    record(checks, "binary", f"{real} links libnetcdf (needed for -input cf)", True, nc_ok,
           fix_text("Install libnetcdf (apt libnetcdf-dev) or rebuild with NetCDF found"))
    return started


def check_path(checks, path, label, critical=True, kind="data"):
    ok = path.exists() and (path.is_dir() or path.stat().st_size > 0)
    return record(checks, kind, path, critical, ok, fix_text(f"Restore {label} at {path}"))


def check_import(checks, module, critical=True):
    proc = run_command([PYTHON_ENV, "-c", f"import {module}"])
    return record(checks, "import", module, critical, proc.returncode == 0,
                  fix_text(f"Install {module} into {PYTHON_ENV.parent.parent}"))


def check_tool(checks, name, critical):
    path = TOOLS_DIR / name
    if not record(checks, "data", path, critical, path.is_file(), fix_text(f"Restore {path}")):
        return
    proc = run_command([PYTHON_ENV, path, "--help"], timeout=60)
    record(checks, "run", f"{path} --help", critical, proc.returncode == 0,
           fix_text(f"Fix {name}: {(proc.stderr or proc.stdout).strip()[-300:]}"))


def main():
    checks = []
    print("=" * 60)
    print(f"  PREFLIGHT CHECK: {MODEL_ID} (real engine)")
    print("=" * 60)
    check_engine(checks)
    for f in ["global.ins", "global_cf.ins", "global_demo.ins", "global_soiln.ins"]:
        check_path(checks, INS_DIR / f, f"shipped instruction file {f}")
    for f in ["soils_lpj.dat", "tmp30_21.grd", "prc30_21.grd", "clo30_21.grd"]:
        check_path(checks, ENV_DIR / f, f"shipped demo/soil data {f}")
    check_path(checks, CO2_FILE, "CO2 file (build with tools/build_lpjguess_co2_file.py)",
               critical=False)
    n_ref = len(list(REF_DEMO.glob("*.out"))) if REF_DEMO.is_dir() else 0
    record(checks, "data", f"{REF_DEMO} (build-time demo reference, {n_ref} .out files)", False,
           n_ref >= 10, fix_text(f"Restore the build-time demo run at {REF_DEMO} (BUILD_LOG.md); "
                                 "without it `run_lpjguess_engine.py example` exits 5"))
    check_path(checks, TRIPLETS, "diagnostic triplets")
    check_path(checks, KI_DIR / "dag.yaml", "dag.yaml (real-engine contract)")
    check_path(checks, SURROGATE_CONTRACT, "surrogate contract (not the model)", critical=False)
    py_ok = record(checks, "binary", PYTHON_ENV, True,
                   PYTHON_ENV.is_file() and os.access(PYTHON_ENV, os.X_OK),
                   fix_text(f"Point KI_PYTHON at a Python with requirements.txt installed (now {PYTHON_ENV})"))
    if py_ok:
        for m in ["numpy", "pandas", "netCDF4", "ki_tools_common.load_forcing",
                  "ki_tools_common.metrics"]:
            check_import(checks, m, critical=True)
        check_import(checks, "matplotlib", critical=False)
        for t in ENGINE_TOOLS:
            check_tool(checks, t, critical=True)
        for t in SURROGATE_TOOLS:   # Python stand-in, NOT the model
            check_tool(checks, t, critical=False)

    passed = sum(c["status"] == "pass" for c in checks)
    print(f"\n  Results: {passed} passed, {len(checks) - passed} failed")
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": MODEL_ID, "checks": checks},
                                           sort_keys=True))
    sys.exit(1 if any(c["critical"] and c["status"] != "pass" for c in checks) else 0)


if __name__ == "__main__":
    main()
