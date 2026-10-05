#!/usr/bin/env python3
"""Run the official USGS GSFLOW Sagehen Creek sample (condition 1: GSFLOW mode, PCG solver)
and check expected.json.

Foundation case for the GSFLOW KI. inputs/ holds the unmodified official files in the
official folder layout (windows/gsflow.control, input/prms, input/modflow). The run copies
them to a fresh temp dir and runs the gsflow binary directly from windows/ (as the official
gsflow.bat does). expected.json holds values taken from the OFFICIAL reference output
(GSFLOW/data/sagehen/output-test/1_GSFLOW_mode.PCG) with the GSFLOW autotest tolerance
(1 % relative, autotest/t002_test.py validate()).

One path-only tweak, done ONLY in the temp copy: the official control file and MODFLOW name
file use Windows "..\\" paths; on Linux these are changed to "../" (the same fix the official
autotest/t001_test.py applies on non-Windows). No values change.

The KI tool tools/run_gsflow.py is NOT used: its pre-run check treats the unused
stat_var_file / var_init_file / var_save_file entries as required inputs and stops
(see README "Known KI gaps").

Exit 0 PASS, 2 checks failed, 3 engine missing.
gsflow lookup: --gsflow-bin -> $GSFLOW_BIN -> which gsflow -> server default.
Use --summarise-dir DIR to print the check values for an existing output folder laid out
like the official output-test folder (gsflow.out, gsflow.csv, modflow/...).
"""
import argparse, json, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
_DEF = ("/home/server/knowledge-dissection-toolkit/auto_dissect/_work/GSFLOW/source/repo/"
        "autotest/gsflow")
TIMEOUT_S = 3000


def _last_float(pattern, text):
    m = re.findall(pattern, text)
    return float(m[-1]) if m else None


def summarise(d, gsflow_out="gsflow.out", gsflow_csv="gsflow.csv"):
    """Check values from an output folder (run output or the official output-test)."""
    d = Path(d)
    o = {}
    df = pd.read_csv(d / gsflow_csv, skipinitialspace=True)
    o["csv_n_days"] = len(df)
    q = df["StreamOut_Q"].to_numpy(float)
    o["csv_streamout_mean"] = q.mean()
    o["csv_streamout_max"] = q.max()
    o["csv_precip_sum"] = df["Precip_Q"].sum()
    o["csv_recharge_mean"] = df["RechargeUnsat2Sat_Q"].mean()
    o["csv_sat_storage_final"] = df["Sat_S"].iloc[-1]
    o["csv_infil_mean"] = df["Infil2Soil_Q"].mean()

    txt = (d / gsflow_out).read_text(errors="replace")
    m = re.findall(r"Number of time steps:\s+(\d+);\s+Number of non-convergence:\s+(\d+)", txt)
    if m:
        o["gsflow_out_time_steps"] = int(m[-1][0])
        o["gsflow_out_nonconvergence"] = int(m[-1][1])
    o["gsflow_out_cum_percent_discrepancy"] = _last_float(
        r"PERCENT DISCREPANCY =\s+(-?[\d.]+)\s+PERCENT", txt)

    lst = (d / "modflow" / "sagehen.mf.list").read_text(errors="replace")
    tail = lst[lst.rfind("VOLUMETRIC BUDGET FOR ENTIRE MODEL"):]
    out_part = tail[tail.find("OUT:"):]
    o["mf_cum_uzf_recharge_in"] = float(re.search(r"UZF RECHARGE\s+=\s+([\d.]+)", tail[:tail.find("OUT:")]).group(1))
    o["mf_cum_stream_leakage_out"] = float(re.search(r"STREAM LEAKAGE\s+=\s+([\d.]+)", out_part).group(1))
    o["mf_cum_surface_leakage_out"] = float(re.search(r"SURFACE LEAKAGE\s+=\s+([\d.]+)", out_part).group(1))

    g = np.loadtxt(d / "modflow" / "sagehen_sfrseg17.out", skiprows=2)
    o["gage4_seg15_flow_mean"] = g[:, 2].mean()
    o["gage4_seg15_flow_final"] = g[-1, 2]
    return {k: (float(v) if v is not None else None) for k, v in o.items()}


def _fix_paths(p):
    p.write_text(p.read_text().replace("\\", "/"))


def check(got):
    fails = []
    exp = json.loads((HERE / "expected.json").read_text())
    for c in exp["numeric_checks"]:
        v, e, tol = got.get(c["name"]), c["expected"], c["tol"]
        if v is None:
            fails.append(f"{c['name']}: not computed")
            continue
        lim = tol * abs(e) if c.get("tol_type") == "rel" else tol
        if abs(v - e) > lim:
            fails.append(f"{c['name']}: {v:.10g} vs {e} (tol {tol} {c.get('tol_type', 'abs')})")
        else:
            print(f"  OK {c['name']}: {v:.10g}  (official {e:.10g})")
    return fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gsflow-bin")
    ap.add_argument("--summarise-dir")
    ap.add_argument("--keep", action="store_true", help="keep the temp run dir")
    a = ap.parse_args()
    if a.summarise_dir:
        print(json.dumps(summarise(a.summarise_dir), indent=1))
        return 0
    b = next((c for c in (a.gsflow_bin, os.environ.get("GSFLOW_BIN"), shutil.which("gsflow"), _DEF)
              if c and Path(c).is_file()), None)
    if not b:
        print("MISSING DEPENDENCY: gsflow binary not found (set GSFLOW_BIN). NOT run.", file=sys.stderr)
        return 3
    run = Path(tempfile.mkdtemp(prefix="gsflow_sagehen_"))
    shutil.copytree(HERE / "inputs", run, dirs_exist_ok=True)
    (run / "output" / "modflow").mkdir(parents=True)
    (run / "output" / "prms").mkdir(parents=True)
    _fix_paths(run / "windows" / "gsflow.control")
    _fix_paths(run / "input" / "modflow" / "sagehen.nam")
    print(f"  running {b} gsflow.control in {run / 'windows'} (about 15 min)")
    fails = []
    try:
        cp = subprocess.run([b, "gsflow.control"], cwd=run / "windows", capture_output=True,
                            text=True, timeout=TIMEOUT_S)
        rc, out = cp.returncode, cp.stdout + cp.stderr
    except subprocess.TimeoutExpired:
        rc, out = -1, "TIMEOUT"
    (run / "output" / "screen.log").write_text(out)
    if rc != 0 or "Normal termination of simulation" not in out:
        fails.append(f"gsflow did not finish normally (rc={rc}): {out[-400:]}")
    else:
        print("  OK finished_normally: rc=0 and 'Normal termination of simulation'")
        try:
            got = summarise(run / "output")
        except Exception as ex:
            got = {}
            fails.append(f"could not read outputs: {ex}")
        fails += check(got)
    if a.keep:
        print(f"  kept run dir: {run}")
    else:
        shutil.rmtree(run, ignore_errors=True)
    if fails:
        print("FAIL:", file=sys.stderr)
        for f in fails:
            print("  -", f, file=sys.stderr)
        return 2
    print("PASS: GSFLOW Sagehen (GSFLOW mode, PCG) matches the official USGS reference output.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
