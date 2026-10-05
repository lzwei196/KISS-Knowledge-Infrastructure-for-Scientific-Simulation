#!/usr/bin/env python3
"""Run the official pyswmm test model "model_storage_pump.inp" and check expected.json.

Foundation case for the PySWMM KI. Steps:
  1. copy inputs/ to a fresh temp dir;
  2. run the model through the KI's own tools/run_pyswmm.py (writes .rpt/.out);
  3. read the .rpt it wrote (continuity errors, outfall load, start/end lines);
  4. run the model once more the way pyswmm's own tests do (test_nodes.py
     test_storage_7 / test_outfalls_8) and read the node, storage and outfall
     statistics they assert.
Exit 0 PASS, 2 checks failed, 3 pyswmm/swmm-toolkit missing.

Python lookup (needs pyswmm + swmm-toolkit): --python-bin -> $PYSWMM_PYTHON_BIN ->
this python -> `which python3` -> server default python_env.
"""
import argparse, json, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP = json.loads((HERE / "expected.json").read_text())
RUN_TOOL = HERE.parents[1] / "tools" / "run_pyswmm.py"
_DEF = "/mnt/disk1/Hydrocraft_server/python_env/bin/python"
INP = "model_storage_pump.inp"

STATS_SCRIPT = r'''
import json, sys
from pyswmm import Simulation, Nodes
with Simulation(sys.argv[1], sys.argv[2], sys.argv[3]) as sim:
    n = Nodes(sim); su = n["SU1"]; j3 = n["J3"]
    for _ in sim:
        pass
    out = {"engine_version": sim.engine_version,
           "storage": su.storage_statistics, "node": su.statistics,
           "outfall": j3.outfall_statistics, "cum_inflow": j3.cumulative_inflow}
print("STATS=" + json.dumps(out, default=str))
'''


def has_pyswmm(py):
    try:
        return subprocess.run([py, "-c", "import pyswmm, swmm.toolkit"],
                              capture_output=True, timeout=60).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def rpt_value(txt, pattern):
    m = re.search(pattern, txt)
    return float(m.group(1)) if m else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--python-bin")
    a = ap.parse_args()
    cands = (a.python_bin, os.environ.get("PYSWMM_PYTHON_BIN"), sys.executable,
             shutil.which("python3"), _DEF)
    py = next((c for c in cands if c and has_pyswmm(c)), None)
    if not py:
        print("MISSING DEPENDENCY: a python with pyswmm + swmm-toolkit "
              "(set PYSWMM_PYTHON_BIN or --python-bin). NOT run.", file=sys.stderr)
        return 3
    if not RUN_TOOL.is_file():
        print(f"MISSING DEPENDENCY: KI run tool {RUN_TOOL}. NOT run.", file=sys.stderr)
        return 3

    run = Path(tempfile.mkdtemp(prefix="pyswmm_storage_pump_"))
    fails, got = [], {}
    try:
        shutil.copy(HERE / "inputs" / INP, run / INP)

        # 1) KI run tool
        cp = subprocess.run([py, str(RUN_TOOL), "--input", INP, "--report", "ki.rpt",
                             "--output", "ki.out"], cwd=run, capture_output=True,
                            text=True, timeout=900)
        js = cp.stdout[cp.stdout.find("{\n"):] if "{\n" in cp.stdout else "{}"
        try:
            summ = json.loads(js)
        except json.JSONDecodeError:
            summ = {}
        if cp.returncode != 0 or summ.get("status") != "completed":
            fails.append(f"KI run tool failed (rc={cp.returncode}, status="
                         f"{summ.get('status')}): {cp.stderr[-400:]}")
        else:
            print(f"  ran KI tool run_pyswmm.py (status=completed, "
                  f"{summ['total_steps']} steps)")
            got["ki_total_steps"] = summ["total_steps"]
            rpt = (run / "ki.rpt").read_text(errors="replace")
            if "Analysis begun on:" not in rpt or "Analysis ended on:" not in rpt:
                fails.append("report has no 'Analysis begun/ended on' lines")
            else:
                print("  OK report says: Analysis begun ... Analysis ended")
            if "ERROR" in rpt:
                fails.append("report contains ERROR")
            got["rpt_runoff_continuity_error_pct"] = rpt_value(
                rpt, r"Runoff Quantity Continuity[\s\S]*?Continuity Error \(%\) \.+\s+(-?[\d.]+)")
            got["rpt_flow_routing_continuity_error_pct"] = rpt_value(
                rpt, r"Flow Routing Continuity[\s\S]*?Continuity Error \(%\) \.+\s+(-?[\d.]+)")
            got["rpt_outfall_J3_total_test_lbs"] = rpt_value(
                rpt, r"\n\s+J3\s+[\d.]+\s+[\d.]+\s+[\d.]+\s+[\d.]+\s+([\d.]+)")

        # 2) official test procedure (pyswmm tests/test_nodes.py)
        (run / "stats.py").write_text(STATS_SCRIPT)
        cp2 = subprocess.run([py, "stats.py", INP, "st.rpt", "st.out"], cwd=run,
                             capture_output=True, text=True, timeout=900)
        line = next((l for l in cp2.stdout.splitlines() if l.startswith("STATS=")), None)
        if cp2.returncode != 0 or not line:
            fails.append(f"statistics run failed (rc={cp2.returncode}): {cp2.stderr[-400:]}")
        else:
            st = json.loads(line[6:])
            print(f"  ran statistics pass (SWMM engine {st['engine_version']})")
            for k in ("max_volume", "average_volume", "max_vol_date"):
                got[f"SU1_storage_{k}"] = st["storage"][k]
            for k in ("peak_total_inflow", "average_depth", "flooding_duration",
                      "peak_flooding_rate", "max_depth", "flooding_volume"):
                got[f"SU1_{k}"] = st["node"][k]
            o = st["outfall"]
            got["J3_total_periods"] = o["total_periods"]
            got["J3_pollutant_loading_test"] = o["pollutant_loading"]["test"]
            got["J3_average_flowrate"] = o["average_flowrate"]
            got["J3_peak_flowrate"] = o["peak_flowrate"]
            got["J3_cumulative_inflow"] = st["cum_inflow"]

        if not fails:
            for c in EXP["numeric_checks"]:
                v = got.get(c["name"])
                if v is None:
                    fails.append(f"{c['name']}: not found in output")
                elif abs(v - c["expected"]) > c["tol"]:
                    fails.append(f"{c['name']}: {v:.8g} vs {c['expected']}±{c['tol']}")
                else:
                    print(f"  OK {c['name']}: {v:.8g}  ({c['source']})")
    finally:
        shutil.rmtree(run, ignore_errors=True)

    if fails:
        print("FAIL:", file=sys.stderr)
        for f in fails:
            print("  -", f, file=sys.stderr)
        return 2
    print("PASS: PySWMM model_storage_pump reproduced the expected results.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
