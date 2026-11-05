#!/usr/bin/env python3
"""Preflight check for the QUINCY knowledge infrastructure (REAL engine qs.bin).

Checks, before any site run: the engine binary exists, is executable, is the one the models
DB names, and actually runs (built-in test_canopy self-test through tools/run_quincy_engine.py,
compared byte for byte with the build-log run = the KI's reference check, critical; test_radiation
likewise, non-critical); dag.yaml (real engine) and the surrogate contract file exist; the engine data file
(lctlib), the namelist template, the CO2 record and the engine source used for parameter-name
checks are present; the Python imports the tools need work; every engine tool starts (--help).

Ends with one line PREFLIGHT_REPORT=<json>. Exit 0 = ready, 1 = a critical check failed
(fixes are printed; see diagnostics/triplets.yaml).
The Python stand-in (tools/run_quincy.py) is a SURROGATE and is deliberately NOT run here.
Interpreter for the checks: $KI_PYTHON, else KISSPATH_PYTHON_ENV/bin/python,
else the interpreter running this script.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

MODEL_ID = "QUINCY"
KI_DIR = Path(__file__).resolve().parent
DIAG = KI_DIR / "diagnostics" / "triplets.yaml"
_PY_ENV = Path("KISSPATH_PYTHON_ENV/bin/python")
PYTHON = os.environ.get("KI_PYTHON") or (str(_PY_ENV) if _PY_ENV.exists() else sys.executable)
DB = Path("KISSPATH_ROOT/hydrocraft.db")
# QUINCY_ENGINE_ROOT: the engine build folder (binary, src/data, src/src, run_builtin_* references)
ENGINE_ROOT = Path(os.environ.get("QUINCY_ENGINE_ROOT", "KISSPATH_HOME/engine_builds_20261006/QUINCY")).expanduser().absolute()
BINARY = Path(os.environ.get("QUINCY_BIN", ENGINE_ROOT / "src/x86_64-gfortran/bin/qs.bin")).expanduser().absolute()
REFERENCES = {"test_canopy": (ENGINE_ROOT / "run_builtin_test_canopy", True),
              "test_radiation": (ENGINE_ROOT / "run_builtin_test_radiation", False)}
ENGINE_TOOLS = ["run_quincy_engine.py", "build_quincy_climate.py", "build_quincy_site_config.py",
                "edit_quincy_parameters.py", "parse_quincy_engine_output.py", "score_quincy_vs_fluxnet.py"]
CHECKS = []


def check(kind, subject, critical, ok, fix=""):
    CHECKS.append({"kind": kind, "subject": str(subject), "critical": bool(critical),
                   "status": "pass" if ok else "fail", "fix": "" if ok else f"{fix} (see {DIAG})"})
    print(f"  {'OK  ' if ok else 'FAIL'} {kind}: {subject}" + ("" if ok else f"\n       Fix: {fix}"))
    return ok


def db_binary():
    try:
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=5)
        row = con.execute("select binary_path from models where id=?", (MODEL_ID,)).fetchone()
        return row[0] if row else None
    except sqlite3.Error:
        return None


def main():
    print(f"{' PREFLIGHT: QUINCY (real engine) ':=^60}")
    real = Path(os.path.realpath(BINARY))
    ok_bin = check("binary", real, True, real.is_file() and os.access(real, os.X_OK),
                   f"engine missing or not executable at {real}; rebuild per {ENGINE_ROOT}/BUILD_LOG.md")
    dbb = db_binary()
    check("binary", f"models DB binary_path == {real}", True,
          dbb is not None and os.path.realpath(dbb) == str(real),
          f"models DB says {dbb!r}; point models.binary_path at {real} or set QUINCY_BIN")
    for path, label, crit in [
            (ENGINE_ROOT / "src/data/lctlib_quincy_nlct14.def", "engine PFT library (lctlib)", True),
            (ENGINE_ROOT / "src/data/fluxnet2_siteset_pft_info.csv", "engine FLUXNET site PFT list", True),
            (ENGINE_ROOT / "src/src/quincy_standalone/mo_qs_set_parameters.f90", "engine source (parameter names)", False),
            (KI_DIR / "templates/qs.namelist.template", "namelist template", True),
            (KI_DIR / "dag.yaml", "dag.yaml (real engine contract)", True),
            (KI_DIR / "docs/surrogate/surrogate_quincy_analytic_dag.yaml", "SURROGATE contract (not QUINCY)", False),
            (Path("KISSPATH_KI_ROOT/QUINCY/inputs/co2/co2_1901_2014.txt"), "CO2 record", True),
            (Path("KISSPATH_KI_ROOT/QUINCY/inputs/co2/co2_annmean_mlo.txt"), "CO2 record (MLO)", True),
            (Path("KISSPATH_OBS/fluxnet/sites"), "FLUXNET2015 sites (forcing + obs)", False)]:
        check("data", f"{label}: {path}", crit, path.exists(), f"restore {path}")
    for mod, crit in [("numpy", True), ("pandas", True), ("yaml", True), ("ki_tools_common.load_forcing", True),
                      ("ki_tools_common.metrics", True), ("ki_tools_common.soil_utils", False), ("matplotlib", False)]:
        r = subprocess.run([PYTHON, "-c", f"import {mod}"], capture_output=True, text=True, timeout=60)
        check("import", mod, crit, r.returncode == 0, f"install {mod} for {PYTHON}: {r.stderr.strip()[-200:]}")
    for t in ENGINE_TOOLS:
        p = KI_DIR / "tools" / t
        r = subprocess.run([PYTHON, str(p), "--help"], capture_output=True, text=True, timeout=60) if p.exists() else None
        check("tool", p, True, r is not None and r.returncode == 0, f"restore/repair {p}")
    if ok_bin:
        for mode, (ref, crit) in REFERENCES.items():
            with tempfile.TemporaryDirectory(prefix="quincy_preflight_") as tmp:
                cmd = [PYTHON, str(KI_DIR / "tools/run_quincy_engine.py"), "--mode", mode,
                       "--run_dir", str(Path(tmp) / "run"), "--binary", str(real), "--reference_dir", str(ref)]
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                try:
                    res = json.loads(r.stdout.strip().splitlines()[-1])
                except (ValueError, IndexError):
                    res = {}
                ok = r.returncode == 0 and res.get("reproduced") is True
                check("run", f"engine self-test {mode} reproduces the build-time run byte for byte "
                      f"({res.get('files_identical')}/{res.get('files_compared')} files vs {ref})", crit, ok,
                      f"self-test {mode} did not reproduce (exit {r.returncode}): {(r.stdout + r.stderr).strip()[-300:]}")
    failed = [c for c in CHECKS if c["status"] != "pass"]
    print(f"\n  Results: {len(CHECKS) - len(failed)} passed, {len(failed)} failed")
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": MODEL_ID, "checks": CHECKS}, sort_keys=True))
    sys.exit(1 if any(c["critical"] for c in failed) else 0)


if __name__ == "__main__":
    try:
        main()
    except subprocess.TimeoutExpired as exc:
        check("run", exc.cmd if isinstance(exc.cmd, str) else " ".join(map(str, exc.cmd)), True, False, "command timed out")
        print("PREFLIGHT_REPORT=" + json.dumps({"model_id": MODEL_ID, "checks": CHECKS}, sort_keys=True))
        sys.exit(1)
