#!/usr/bin/env python3
"""Run the official pyGIMLi example "2D ERT modelling and inversion" and check expected.json.

Foundation case for the pyGIMLi KI. Steps:
  1. Copy the unmodified official script (doc/examples/3_ert/plot_01_ert_2d_mod_inv.py)
     to a fresh temp dir and run it with the pyGIMLi Python (non-GUI matplotlib backend).
     The script builds the model, simulates dipole-dipole data with a fixed noise seed
     (seed=1337), writes simple.dat, runs two inversions and checks its own official
     asserts (chi^2 ~ 0.7 and ~ 1.4). A small driver runs it with runpy and reads the
     final objects; the script text is not changed.
  2. Invert the script's simple.dat again through the KI tool tools/run_pygimli.py
     (lam=20, the same call as the script's first inversion), then read the result
     with the KI tool tools/parse_gimli_output.py.
Exit 0 PASS, 2 checks failed, 3 pyGIMLi Python missing.

Python lookup: --pygimli-python -> $PYGIMLI_PYTHON -> this interpreter (if it imports
pygimli) -> `python3` on PATH (if it imports pygimli) -> server default venv.
"""
import argparse, json, os, shutil, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP = json.loads((HERE / "expected.json").read_text())
TOOLS = HERE.parents[1] / "tools"
RUN_TOOL = TOOLS / "run_pygimli.py"
PARSE_TOOL = TOOLS / "parse_gimli_output.py"
SCRIPT = "plot_01_ert_2d_mod_inv.py"
_DEF = "/home/server/knowledge-dissection-toolkit/auto_dissect/_work/pyGIMLi/venv/bin/python"

DRIVER = r'''
import json, runpy, sys
import matplotlib; matplotlib.use("Agg")
import numpy as np
g = runpy.run_path(sys.argv[1], run_name="__main__")
mgr, data, inv, model, mesh = g["mgr"], g["data"], g["inv"], g["model"], g["mesh"]
print("RESULT_JSON " + json.dumps({
    "mesh_cells": mesh.cellCount(), "n_data": data.size(), "n_electrodes": data.sensorCount(),
    "rhoa_min": float(np.min(data["rhoa"])), "rhoa_max": float(np.max(data["rhoa"])),
    "inv_unstructured_ncells": len(inv),
    "inv_unstructured_min": float(np.min(inv)), "inv_unstructured_max": float(np.max(inv)),
    "inv_grid_chi2": float(mgr.inv.chi2()), "inv_grid_rrms": float(mgr.inv.relrms()),
    "inv_grid_ncells": len(model),
    "inv_grid_min": float(np.min(model)), "inv_grid_max": float(np.max(model)),
}))
'''


def has_pygimli(py):
    try:
        return subprocess.run([py, "-c", "import pygimli"], capture_output=True,
                              timeout=120).returncode == 0
    except Exception:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pygimli-python")
    a = ap.parse_args()
    cands = [a.pygimli_python, os.environ.get("PYGIMLI_PYTHON"), sys.executable,
             shutil.which("python3"), _DEF]
    py = next((c for c in cands if c and Path(c).exists() and has_pygimli(c)), None)
    if not py:
        print("MISSING DEPENDENCY: no Python with pygimli found (set PYGIMLI_PYTHON or "
              "--pygimli-python). NOT run.", file=sys.stderr)
        return 3
    # installed package versions (pygimli.__version__ follows git in the cwd, so not used)
    vcode = ("from importlib.metadata import version as v; "
             "print('pygimli', v('pygimli'), '+ pgcore', v('pgcore'))")
    ver = (subprocess.run([py, "-c", vcode], capture_output=True, text=True)
           .stdout.strip().splitlines() or ["?"])[-1]
    print(f"  {ver} via {py}")

    env = dict(os.environ, MPLBACKEND="Agg", OMP_NUM_THREADS=os.environ.get("OMP_NUM_THREADS", "4"))
    run = Path(tempfile.mkdtemp(prefix="pygimli_ert2d_"))
    fails, got = [], {}
    try:
        shutil.copy(HERE / "inputs" / SCRIPT, run / SCRIPT)
        (run / "driver.py").write_text(DRIVER)
        cp = subprocess.run([py, "driver.py", SCRIPT], cwd=run, env=env,
                            capture_output=True, text=True, timeout=1200)
        (run / "script.log").write_text(cp.stdout + cp.stderr)
        line = [l for l in cp.stdout.splitlines() if l.startswith("RESULT_JSON ")]
        if cp.returncode != 0 or not line:
            fails.append(f"official script failed (rc={cp.returncode}); its own asserts or "
                         f"the run broke: {(cp.stdout + cp.stderr)[-600:]}")
        else:
            print("  ran official script (its own chi^2 asserts passed)")
            got.update(json.loads(line[0][len("RESULT_JSON "):]))

        if not fails:
            cp = subprocess.run([py, str(RUN_TOOL), "--data", "simple.dat", "--method", "ert",
                                 "--mode", "invert", "--lam", "20", "--max-iter", "20",
                                 "--output", "ki_results"], cwd=run, env=env,
                                capture_output=True, text=True, timeout=1200)
            if cp.returncode != 0:
                fails.append(f"KI run_pygimli.py failed (rc={cp.returncode}): {cp.stderr[-400:]}")
            else:
                cp = subprocess.run([py, str(PARSE_TOOL), "-r", "ki_results", "-m", "ert",
                                     "-o", "ki_parsed"], cwd=run, env=env,
                                    capture_output=True, text=True, timeout=600)
                if cp.returncode != 0:
                    fails.append(f"KI parse_gimli_output.py failed (rc={cp.returncode}): "
                                 f"{cp.stderr[-400:]}")
                else:
                    print("  ran KI tools run_pygimli.py + parse_gimli_output.py")
                    m = json.loads((run / "ki_parsed" / "metrics.json").read_text())
                    meta = m["inversion_metadata"]
                    got.update({
                        "ki_status": 1 if meta["status"] == "success" else 0,
                        "ki_chi2": m["chi2"], "ki_iterations": meta["n_iterations"],
                        "ki_ncells": m["model_stats"]["n_cells"], "ki_ndata": meta["n_data"],
                        "ki_model_min": m["model_stats"]["min"],
                        "ki_model_max": m["model_stats"]["max"],
                        "ki_model_mean": m["model_stats"]["mean"],
                    })

        if not fails:
            for c in EXP["numeric_checks"]:
                v = got[c["name"]]
                if abs(v - c["expected"]) > c["tol"]:
                    fails.append(f"{c['name']}: {v:.6g} vs {c['expected']}±{c['tol']}")
                else:
                    print(f"  OK {c['name']}: {v:.6g}")
            for c in EXP["official_checks"]:
                v = got[c["name"]]
                if abs(v - c["expected"]) > c["tol"]:
                    fails.append(f"official {c['name']}: {v:.6g} vs {c['expected']}±{c['tol']}")
                else:
                    print(f"  OK official {c['name']}: {v:.4g} (upstream value {c['expected']})")
    finally:
        shutil.rmtree(run, ignore_errors=True)

    if fails:
        print("FAIL:", file=sys.stderr)
        for f in fails:
            print("  -", f, file=sys.stderr)
        return 2
    print("PASS: pyGIMLi 2D ERT modelling + inversion reproduced the expected results.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
