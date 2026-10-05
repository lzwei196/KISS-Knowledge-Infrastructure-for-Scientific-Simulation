#!/usr/bin/env python3
"""Run the official mosartwmpy tutorial case (CONUS, May 1981) in a clean dir and check expected.json.

Foundation case for the MOSART KI. Inputs are the unmodified official tutorial data
(Zenodo record 6959736, fetched by mosartwmpy.utilities.download_data('tutorial')) and the
official tutorial config notebooks/config.yaml from github.com/IMMM-SFA/mosartwmpy.
The model is run through the KI's own tools/run_mosartwmpy.py (1981-05-01 .. 1981-05-30,
3-hour step, water management + ISTARF reservoirs on). Output is read with the KI's
tools/parse_mosart_output.py (basin sums) and directly with xarray (other checks).

Two run settings, both set only in this script (inputs and model code are untouched):
  * pandas >= 3: the launcher sets pandas option future.infer_string=False before the KI
    tool runs. Without it mosartwmpy 0.6.2 crashes in the first step (ISTARF), because
    pandas 3 text columns are not numpy arrays and are skipped by the model's mask step.
  * NUMBA_NUM_THREADS=1: mosartwmpy's parallel numba loops give slightly different numbers
    each run when many threads are used; with one thread the run repeats exactly.

Python lookup: --mosart-python -> $MOSART_PYTHON -> server default venv -> python3 on PATH.
The python must import mosartwmpy. Exit 0 PASS, 2 checks failed, 3 engine/dependency missing.
"""
import argparse, json, os, shutil, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP = json.loads((HERE / "expected.json").read_text())
RUN_TOOL = HERE.parents[1] / "tools" / "run_mosartwmpy.py"
PARSE_TOOL = HERE.parents[1] / "tools" / "parse_mosart_output.py"
_DEF = "/mnt/disk1/Hydrocraft_server/models/MOSART/venv/bin/python"

LAUNCHER = r'''
import runpy, sys
import pandas as pd
if int(pd.__version__.split(".")[0]) >= 3:
    pd.set_option("future.infer_string", False)
tool = sys.argv[1]
sys.argv = sys.argv[1:]
runpy.run_path(tool, run_name="__main__")
'''

METRICS = r'''
import json, sys
import numpy as np, xarray as xr
ds = xr.open_dataset(sys.argv[1])
def tot(v, i): return float(np.nansum(ds[v].isel(time=i).values.astype("float64")))
def alltot(v): return float(np.nansum(ds[v].values.astype("float64")))
q = ds["RIVER_DISCHARGE_OVER_LAND_LIQ"].values.astype("float64")
print(json.dumps({
    "n_days": int(ds.sizes["time"]),
    "first_day": str(ds.time.values[0])[:10],
    "last_day": str(ds.time.values[-1])[:10],
    "qsur_mean_all": float(np.nanmean(ds["QSUR_LIQ"].values.astype("float64"))),
    "qsub_mean_all": float(np.nanmean(ds["QSUB_LIQ"].values.astype("float64"))),
    "discharge_max_all": float(np.nanmax(q)),
    "discharge_sum_last_day": tot("RIVER_DISCHARGE_OVER_LAND_LIQ", -1),
    "wrm_supply_sum_all": alltot("WRM_SUPPLY"),
    "wrm_demand_sum_all": alltot("WRM_DEMAND"),
    "wrm_deficit_sum_all": alltot("WRM_DEFICIT"),
}))
'''


def find_python(arg):
    for c in (arg, os.environ.get("MOSART_PYTHON"), _DEF, shutil.which("python3")):
        if not c or not Path(c).exists():
            continue
        try:
            cp = subprocess.run([c, "-c", "import mosartwmpy"], capture_output=True,
                                text=True, timeout=300)
        except subprocess.TimeoutExpired:
            continue
        if cp.returncode == 0:
            return c
    return None


def last_value(csv_path):
    lines = [l for l in Path(csv_path).read_text().splitlines() if l.strip()]
    return float(lines[-1].split(",")[-1]), len(lines) - 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mosart-python")
    ap.add_argument("--print-values", action="store_true",
                    help="also print all computed values as JSON (for re-recording)")
    a = ap.parse_args()
    py = find_python(a.mosart_python)
    if not py:
        print("MISSING DEPENDENCY: no python that can import mosartwmpy (set MOSART_PYTHON or "
              "--mosart-python). NOT run.", file=sys.stderr)
        return 3
    for t in (RUN_TOOL, PARSE_TOOL):
        if not t.is_file():
            print(f"MISSING DEPENDENCY: KI tool {t} not found. NOT run.", file=sys.stderr)
            return 3

    run = Path(tempfile.mkdtemp(prefix="mosart_tutorial_"))
    shutil.copy(HERE / "inputs" / "config.yaml", run / "config.yaml")
    shutil.copytree(HERE / "inputs" / "input", run / "input")
    (run / "_launch.py").write_text(LAUNCHER)
    env = dict(os.environ, NUMBA_NUM_THREADS="1")

    fails, got = [], {}
    print(f"  python: {py}")
    print("  running KI tool run_mosartwmpy.py (1981-05-01..05-30, about 6 min on one thread)")
    cp = subprocess.run([py, "_launch.py", str(RUN_TOOL), "--config", "config.yaml",
                         "--output-json", "summary.json"], cwd=run, env=env,
                        capture_output=True, text=True, timeout=1800)
    out_nc = run / "output" / "tutorial" / "tutorial_1981_05.nc"
    log = run / "output" / "tutorial" / "mosartwmpy.log"
    ok_line = "[run_mosartwmpy] SUCCESS" in cp.stdout
    log_ok = log.is_file() and "Simulation completed" in log.read_text()
    if cp.returncode != 0 or not ok_line or not log_ok or not out_nc.is_file():
        fails.append(f"run failed (rc={cp.returncode}, success_line={ok_line}, "
                     f"model_log_completed={log_ok}): {cp.stdout[-600:]} {cp.stderr[-600:]}")
    else:
        print("  OK finished normally: rc=0, '[run_mosartwmpy] SUCCESS', "
              "model log 'Simulation completed'")
        summ = json.loads((run / "summary.json").read_text())
        chk = {c["variable"]: c for c in summ["output_validation"]["checks"]}
        got["final_discharge_max"] = chk["discharge"]["max"]
        got["final_storage_max"] = chk["storage"]["max"]
        for var, key in (("WRM_STORAGE", "wrm_storage_sum_last_day"),
                         ("STORAGE_LIQ", "storage_liq_sum_last_day")):
            csv = run / f"{var}.csv"
            pp = subprocess.run([py, str(PARSE_TOOL), "--input-dir", "output/tutorial",
                                 "--output", str(csv), "--variable", var, "--mode", "basin-sum"],
                                cwd=run, capture_output=True, text=True, timeout=600)
            if pp.returncode != 0 or not csv.is_file():
                fails.append(f"parse_mosart_output.py failed for {var}: {pp.stderr[-400:]}")
                continue
            got[key], got[f"parse_rows_{var}"] = last_value(csv)
        mp = subprocess.run([py, "-c", METRICS, str(out_nc)], capture_output=True,
                            text=True, timeout=600)
        if mp.returncode != 0:
            fails.append(f"reading output failed: {mp.stderr[-400:]}")
        else:
            got.update(json.loads(mp.stdout.strip().splitlines()[-1]))

        if a.print_values:
            print("VALUES " + json.dumps(got))
        for k, want in (("first_day", "1981-05-01"), ("last_day", "1981-05-30")):
            if got.get(k) != want:
                fails.append(f"{k}: {got.get(k)} vs {want}")
            else:
                print(f"  OK {k}: {want}")
        for c in EXP["numeric_checks"]:
            v = got.get(c["name"])
            if v is None:
                fails.append(f"{c['name']}: not computed")
                continue
            lim = c["tol"] * abs(c["expected"]) if c.get("tol_type") == "relative" else c["tol"]
            if abs(v - c["expected"]) > lim:
                fails.append(f"{c['name']}: {v:.10g} vs {c['expected']} (tol {c['tol']})")
            else:
                print(f"  OK {c['name']}: {v:.10g}")

    shutil.rmtree(run, ignore_errors=True)
    if fails:
        print("FAIL:", file=sys.stderr)
        for f in fails:
            print("  -", f, file=sys.stderr)
        return 2
    print("PASS: mosartwmpy tutorial (May 1981 CONUS) reproduced the expected results.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
