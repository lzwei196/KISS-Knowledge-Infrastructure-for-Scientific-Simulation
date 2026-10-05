#!/usr/bin/env python3
"""Run SimPEG's official gravity-vs-analytic test in a clean dir and check expected.json.

Foundation case for the SimPEG KI. Source: SimPEG's own test file
tests/pf/test_forward_Grav_Linear.py (v0.25.2, commit ba60041). Two parts:

  A. The official pytest tests that compare the gravity forward simulation with the
     exact (analytic) answer for two nested dense prisms (geoana engine only):
     test_accelerations_vs_analytic, test_tensor_vs_analytic, test_guv_vs_analytic.
  B. The same model (geometry taken from the official test's own fixtures, tensor mesh)
     is run forward for gz the way the KI tool tools/run_simpeg.py sets it up (all cells
     active, zero density outside the blocks, store_sensitivities="forward_only"), and the
     gz answer is compared with the official analytic answer using the official tolerance
     (rtol 1e-9, atol 1e-6 mGal). Part B calls the SimPEG engine directly, because the KI
     tool currently fails on SimPEG 0.25 (gravity Survey(source_list=...) -> TypeError, see
     README "Known KI gaps"). The KI tool is still tried once; its result is only printed.

Exit 0 PASS, 2 checks failed, 3 engine/dependency missing.
Python lookup: --python-bin -> $SIMPEG_PYTHON_BIN -> `which python3` -> server python_env.
The chosen python must import simpeg, discretize, geoana and pytest.
"""
import argparse, json, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP = json.loads((HERE / "expected.json").read_text())
RUN_TOOL = HERE.parents[1] / "tools" / "run_simpeg.py"
_DEF = "/mnt/disk1/Hydrocraft_server/python_env/bin/python"
NEEDED = "import simpeg, discretize, geoana, pytest, numpy"
PYTEST_K = "analytic and geoana"  # choclo engine is optional and not installed on the server

# Part B helper, run with the engine python inside the temp dir. It takes the mesh,
# blocks, density and receivers from the official test's own fixtures (no restating).
PREP = r'''
import json, sys, numpy as np
sys.path.insert(0, "tests/pf")
import test_forward_Grav_Linear as T
from simpeg.potential_fields import gravity
C = T.TestsGravitySimulation
self = C()
class Req: param = "tensormesh"
blocks = C.blocks.__wrapped__(self)
mesh = C.mesh.__wrapped__(self, blocks, Req())
dens_red, active = C.density_and_active_cells.__wrapped__(self, mesh, blocks)
rx = C.receivers_locations.__wrapped__(self)
full = np.zeros(mesh.n_cells); full[active] = dens_red      # all cells, zero outside blocks
np.save("m0.npy", full)
survey = gravity.Survey(gravity.SourceField([gravity.Point(rx, components=["gz"])]))
analytic = self.get_analytic_solution(blocks, survey)[:, 2]  # official analytic gz, mGal
np.save("analytic_gz.npy", analytic)
json.dump({"mesh": {"hx": mesh.h[0].tolist(), "hy": mesh.h[1].tolist(),
                    "hz": mesh.h[2].tolist(), "origin": mesh.origin.tolist(),
                    "n_cells": int(mesh.n_cells)},
           "survey": {"receiver_locations": rx.tolist()}}, open("mesh_config.json", "w"))
json.dump({"n_active": int(mesh.n_cells), "starting_model_file": "m0.npy",
           "background_si": 0.0, "map_type": "linear", "property": "density"},
          open("model_config.json", "w"))
# Direct engine run, set up like tools/run_simpeg.py build_simulation()/run_forward()
from simpeg import maps
sim = gravity.Simulation3DIntegral(mesh, survey=survey,
        rhoMap=maps.InjectActiveCells(mesh, np.ones(mesh.n_cells, bool), 0.0),
        active_cells=np.ones(mesh.n_cells, bool), store_sensitivities="forward_only")
np.save("dpred_direct.npy", sim.dpred(full))
print(json.dumps({"n_cells": int(mesh.n_cells), "n_dense_cells": int(active.sum())}))
'''


def find_python(arg):
    which = shutil.which("python3")
    for c in (arg, os.environ.get("SIMPEG_PYTHON_BIN"), which, _DEF):
        if c and Path(c).is_file():
            ok = subprocess.run([c, "-c", NEEDED], capture_output=True, cwd=tempfile.gettempdir())
            if ok.returncode == 0:
                return c
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--python-bin")
    a = ap.parse_args()
    py = find_python(a.python_bin)
    if not py:
        print("MISSING DEPENDENCY: no python with simpeg, discretize, geoana, pytest, numpy "
              "(set SIMPEG_PYTHON_BIN or --python-bin). NOT run.", file=sys.stderr)
        return 3
    import numpy as np

    env = dict(os.environ, OMP_NUM_THREADS="4", MPLBACKEND="Agg")
    run = Path(tempfile.mkdtemp(prefix="simpeg_grav_"))
    shutil.copytree(HERE / "inputs" / "tests", run / "tests")
    fails, got = [], {}
    try:
        # Part A: official pytest tests (analytic reference + official tolerances inside)
        cp = subprocess.run([py, "-m", "pytest", "-p", "no:cacheprovider", "-q",
                             "tests/pf/test_forward_Grav_Linear.py", "-k", PYTEST_K],
                            cwd=run, env=env, capture_output=True, text=True, timeout=1200)
        tail = cp.stdout.strip().splitlines()[-1] if cp.stdout.strip() else ""
        print("  pytest:", tail)
        m = lambda w: int(re.search(rf"(\d+) {w}", tail).group(1)) if re.search(rf"(\d+) {w}", tail) else 0
        got["pytest_returncode"] = cp.returncode
        got["pytest_passed"] = m("passed")
        got["pytest_failed"] = m("failed") + m("error")

        # Part B: same official model, direct engine run (+ informational KI tool try)
        cp = subprocess.run([py, "-c", PREP], cwd=run, env=env, capture_output=True, text=True,
                            timeout=600)
        if cp.returncode != 0:
            fails.append(f"model prep failed: {cp.stderr[-600:]}")
        else:
            got.update(json.loads(cp.stdout.strip().splitlines()[-1]))
            cp = subprocess.run([py, str(RUN_TOOL), "--mode", "forward", "--method", "gravity",
                                 "--mesh-config", "mesh_config.json",
                                 "--model-config", "model_config.json", "--output", "results"],
                                cwd=run, env=env, capture_output=True, text=True, timeout=1200)
            if cp.returncode == 0:
                print("  note: KI tool run_simpeg.py now runs this case (gap may be fixed);"
                      " checks below still use the direct engine run")
            else:
                last = (cp.stderr.strip().splitlines() or ["?"])[-1]
                print(f"  note: KI tool run_simpeg.py failed (known KI gap): {last}")
            d = np.load(run / "dpred_direct.npy")
            an = np.load(run / "analytic_gz.npy")
            rtol, atol = 1e-9, 1e-6  # official tolerance of test_accelerations_vs_analytic
            got.update({
                "n_finite": int(np.isfinite(d).sum()),
                "n_data": int(d.size),
                "n_within_official_tol": int(np.sum(np.abs(d - an) <= atol + rtol * np.abs(an))),
                "gz_max": float(d.max()), "gz_min": float(d.min()),
                "gz_mean": float(d.mean()), "gz_center": float(d[d.size // 2]),
                "max_abs_diff_vs_analytic": float(np.max(np.abs(d - an))),
            })
            print(f"  analytic gz: max {an.max():.9g} min {an.min():.9g} mean {an.mean():.9g}")
        for c in EXP["numeric_checks"]:
            if c["name"] not in got:
                fails.append(f"{c['name']}: not computed")
                continue
            v = got[c["name"]]
            if abs(v - c["expected"]) > c["tol"]:
                fails.append(f"{c['name']}: {v:.10g} vs {c['expected']}±{c['tol']}")
            else:
                print(f"  OK {c['name']}: {v:.10g}")
    finally:
        shutil.rmtree(run, ignore_errors=True)
    if fails:
        print("FAIL:", file=sys.stderr)
        for f in fails:
            print("  -", f, file=sys.stderr)
        return 2
    print("PASS: SimPEG gravity forward matches the official analytic prism answer.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
