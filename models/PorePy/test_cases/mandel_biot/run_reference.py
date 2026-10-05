#!/usr/bin/env python3
"""Run PorePy's official Mandel test in a clean dir and check expected.json.

Foundation case for the PorePy KI. It repeats PorePy's own functional test
tests/functional/test_mandel.py (porepy 1.12.0) with the unmodified official model file
src/porepy/examples/mandel_biot.py:
  run A: MandelModel, TimeManager([0, 25, 50], dt=25) -> relative errors against the exact
         analytical Mandel solution at t = 25 s and t = 50 s, compared with the
         test's own "desired_errors" and its tolerances (atol 1e-5, rtol 1e-3).
  run B: unscaled vs scaled (m=1e-3, kg=1e-3) system, one 10 s step -> pressure and
         displacement errors must agree to 4 decimals (the test's own check).
pytest is not needed: the same setup is driven by a small script written to the temp dir.

The KI tool tools/run_porepy.py cannot run this case (its --example map imports a
class MandelSetup that does not exist in porepy 1.12.0), so the engine is run directly.

Python lookup: --porepy-python -> $POREPY_PYTHON -> `python3` on PATH that imports porepy
-> server default venv. Exit 0 PASS, 2 checks failed, 3 engine/dependency missing.
"""
import argparse, ast, json, os, shutil, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP = json.loads((HERE / "expected.json").read_text())
_DEF = "/home/server/knowledge-dissection-toolkit/auto_dissect/_work/PorePy/venv/bin/python"

DRIVER = r'''
import importlib.util, json, sys, time
import numpy as np
import porepy as pp
spec = importlib.util.spec_from_file_location("mandel_biot", "mandel_biot.py")
mb = importlib.util.module_from_spec(spec); sys.modules["mandel_biot"] = mb
spec.loader.exec_module(mb)

def mats():
    return {"fluid": pp.FluidComponent(**mb.mandel_fluid_constants),
            "solid": pp.SolidConstants(**mb.mandel_solid_constants)}

out = {"porepy_version": pp.__version__}
t0 = time.time()
# run A: exactly the `results` fixture of tests/functional/test_mandel.py
model = mb.MandelModel({"material_constants": mats(),
                        "time_manager": pp.TimeManager([0, 25, 50], 25, True),
                        "times_to_export": []})
pp.run_time_dependent_model(model)
out["n_results"] = len(model.results)
out["final_time"] = float(model.time_manager.time)
out["n_cells"] = int(model.mdg.subdomains()[0].num_cells)
for r in model.results:
    t = int(round(r.time))
    out[f"t{t}"] = {"error_pressure": float(r.error_pressure),
                    "error_flux": float(r.error_flux),
                    "error_displacement": float(r.error_displacement),
                    "error_force": float(r.error_force),
                    "error_consolidation_degree_x": float(r.error_consolidation_degree[0]),
                    "error_consolidation_degree_y": float(r.error_consolidation_degree[1])}
# run B: test_scaled_vs_unscaled_systems
res = {}
for tag, extra in (("unscaled", {}), ("scaled", {"units": pp.Units(m=1e-3, kg=1e-3)})):
    m = mb.MandelModel({"material_constants": mats(),
                        "time_manager": pp.TimeManager([0, 10], 10, True),
                        "times_to_export": [], **extra})
    pp.run_time_dependent_model(m)
    res[tag] = (float(m.results[-1].error_pressure), float(m.results[-1].error_displacement))
out["scaled_minus_unscaled_error_pressure"] = abs(res["scaled"][0] - res["unscaled"][0])
out["scaled_minus_unscaled_error_displacement"] = abs(res["scaled"][1] - res["unscaled"][1])
out["elapsed_s"] = round(time.time() - t0, 1)
print("MANDEL_RESULTS=" + json.dumps(out))
print("MANDEL RUN FINISHED NORMALLY")
'''


def find_python(arg):
    cands = [arg, os.environ.get("POREPY_PYTHON"), shutil.which("python3"), _DEF]
    for c in cands:
        if c and Path(c).is_file():
            r = subprocess.run([c, "-c", "import porepy, gmsh; print(porepy.__version__)"],
                               capture_output=True, text=True)
            if r.returncode == 0:
                return c, r.stdout.strip()
    return None, None


def official_desired(test_file):
    """Read desired_errors straight from the official test file (no hand copy)."""
    tree = ast.parse(test_file.read_text())
    vals = []
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == "desired_errors":
            for call in node.value.elts:
                d = {kw.arg: ast.literal_eval(kw.value) for kw in call.keywords}
                cx, cy = d.pop("error_consolidation_degree")
                d["error_consolidation_degree_x"], d["error_consolidation_degree_y"] = cx, cy
                vals.append(d)
    return dict(zip(("t25", "t50"), vals))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--porepy-python")
    a = ap.parse_args()
    py, ver = find_python(a.porepy_python)
    if not py:
        print("MISSING DEPENDENCY: a Python with porepy + gmsh (set POREPY_PYTHON or "
              "--porepy-python). NOT run.", file=sys.stderr)
        return 3
    print(f"  engine: {py} (porepy {ver})")

    run = Path(tempfile.mkdtemp(prefix="porepy_mandel_"))
    for f in ("mandel_biot.py", "test_mandel.py"):
        shutil.copy(HERE / "inputs" / f, run / f)
    (run / "drive_mandel.py").write_text(DRIVER)
    env = dict(os.environ)
    for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMBA_NUM_THREADS"):
        env.setdefault(k, "4")
    fails = []
    try:
        cp = subprocess.run([py, "drive_mandel.py"], cwd=run, env=env,
                            capture_output=True, text=True, timeout=1200)
    except subprocess.TimeoutExpired:
        cp = None
        fails.append("run timed out (1200 s)")
    if cp is not None:
        if cp.returncode != 0 or "MANDEL RUN FINISHED NORMALLY" not in cp.stdout:
            fails.append(f"run failed (rc={cp.returncode}): {cp.stderr[-800:]}")
        else:
            print("  OK finished normally (rc=0, success line seen)")
    if not fails:
        line = next(l for l in cp.stdout.splitlines() if l.startswith("MANDEL_RESULTS="))
        got = json.loads(line.split("=", 1)[1])
        print(f"  run time {got['elapsed_s']} s, {got['n_cells']} cells")
        # the expected values must be the ones in the official test file
        off = official_desired(run / "test_mandel.py")
        flat = {"n_results": got["n_results"], "final_time": got["final_time"],
                "scaled_minus_unscaled_error_pressure": got["scaled_minus_unscaled_error_pressure"],
                "scaled_minus_unscaled_error_displacement": got["scaled_minus_unscaled_error_displacement"]}
        for t in ("t25", "t50"):
            for k, v in got[t].items():
                flat[f"{k}_{t}"] = v
        for c in EXP["numeric_checks"]:
            name, v = c["name"], flat[c["name"]]
            for t in ("t25", "t50"):
                if name.endswith("_" + t):
                    o = off[t][name[: -len(t) - 1]]
                    if o != c["expected"]:
                        fails.append(f"{name}: expected.json {c['expected']} != official {o}")
            tol = c["atol"] + c.get("rtol", 0.0) * abs(c["expected"])
            if abs(v - c["expected"]) > tol:
                fails.append(f"{name}: {v:.10g} vs {c['expected']} (tol {tol:.3g})")
            else:
                print(f"  OK {name}: {v:.10g}")
    shutil.rmtree(run, ignore_errors=True)
    if fails:
        print("FAIL:", file=sys.stderr)
        for f in fails:
            print("  -", f, file=sys.stderr)
        return 2
    print("PASS: PorePy Mandel problem matches the official test values.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
