#!/usr/bin/env python3
"""Run GemPy's official anticline (fold) example in a clean dir and check expected.json.

Foundation case for the GemPy KI. The model is built exactly as GemPy's own
gempy/API/examples_generator.py::_generate_anticline_model does (extent 0-1000 m on
all axes, octree refinement 5, series "Strat_Series" = rock2, rock1), but the two CSV
files are read from inputs/ instead of from the gempy_data GitHub URL.

Main check: the 51 sampled scalar-field values must match GemPy's own approved test
file (reference/anticline_scalar_field.approved.txt, from
test/test_model_types/test_example_models_I.py::test_generate_fold_model) with
GemPy's own tolerance (np.allclose rtol=1e-5, atol=1e-5).

Steps:
  1. Try the KI run tool tools/run_gempy_model.py on the same data (information only:
     it computes the model, then fails on gp.save_model(name=...); see README).
  2. Run the engine directly with the official generator code (local CSV paths).
  3. Read the saved model with the KI parse tool tools/parse_gempy_output.py (summary).
  4. Compare against expected.json.
Exit 0 PASS, 2 checks failed, 3 engine/dependency missing.

Python lookup (needs gempy importable): --gempy-python -> $GEMPY_PYTHON ->
server default venv -> `which python3`.
"""
import argparse, json, os, shutil, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP = json.loads((HERE / "expected.json").read_text())
TOOLS = HERE.parents[1] / "tools"
RUN_TOOL = TOOLS / "run_gempy_model.py"
PARSE_TOOL = TOOLS / "parse_gempy_output.py"
_DEF = "/home/server/knowledge-dissection-toolkit/auto_dissect/_work/GemPy/venv/bin/python"
INPUTS = ("model2_surface_points.csv", "model2_orientations.csv")

# Same calls as gempy/API/examples_generator.py::_generate_anticline_model,
# only the two CSV paths point to local copies of the official files.
DRIVER = r'''
import json, sys
import numpy as np
import gempy as gp
geo = gp.create_geomodel(
    project_name="fold",
    extent=[0, 1000, 0, 1000, 0, 1000],
    refinement=5,
    importer_helper=gp.data.ImporterHelper(
        path_to_orientations="model2_orientations.csv",
        path_to_surface_points="model2_surface_points.csv",
    ),
)
gp.map_stack_to_surfaces(gempy_model=geo, mapping_object={"Strat_Series": ("rock2", "rock1")})
gp.compute_model(geo)
# Same sampling as test/test_model_types/test_example_models_I.py::_verify_scalar_field
sf = np.asarray(geo.solutions.octrees_output[-1].outputs_centers[0].exported_fields.scalar_field)
sample = sf[::int(len(sf) / 50)]
lith = np.asarray(geo.solutions.raw_arrays.lith_block)
ids, counts = np.unique(lith, return_counts=True)
gp.save_model(geo, path="fold.gempy")
out = {
    "gempy_version": gp.__version__,
    "sample": [float(v) for v in sample],
    "n_octree_levels": len(geo.solutions.octrees_output),
    "n_finest_level_points": int(len(sf)),
    "sf_finest_min": float(sf.min()), "sf_finest_max": float(sf.max()),
    "sf_finest_mean": float(sf.mean()),
    "lith_block_size": int(lith.size),
    "lith_counts": {str(int(i)): int(c) for i, c in zip(ids, counts)},
}
json.dump(out, open("driver_result.json", "w"), indent=1)
print("DRIVER_OK")
'''


def find_python(arg):
    cands = [arg, os.environ.get("GEMPY_PYTHON"), _DEF, shutil.which("python3")]
    for c in cands:
        if c and Path(c).is_file():
            r = subprocess.run([c, "-c", "import gempy"], capture_output=True, text=True,
                               timeout=300)
            if r.returncode == 0:
                return c
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gempy-python")
    a = ap.parse_args()
    py = find_python(a.gempy_python)
    if not py:
        print("MISSING DEPENDENCY: no Python with gempy found (set GEMPY_PYTHON or "
              "--gempy-python). NOT run.", file=sys.stderr)
        return 3
    env = dict(os.environ, OMP_NUM_THREADS=os.environ.get("OMP_NUM_THREADS", "4"),
               MPLBACKEND="Agg")
    run = Path(tempfile.mkdtemp(prefix="gempy_anticline_"))
    fails = []
    try:
        for f in INPUTS:
            shutil.copy(HERE / "inputs" / f, run / f)

        # 1. KI run tool (information only, known gap)
        if RUN_TOOL.is_file():
            (run / "ki_params.json").write_text(json.dumps({"params": {
                "project_name": "fold", "extent": [0, 1000, 0, 1000, 0, 1000],
                "refinement": 5, "interpolation_type": "octree",
                "mapping_object": {"Strat_Series": ["rock2", "rock1"]}}}))
            subprocess.run([py, str(RUN_TOOL), "--params", "ki_params.json",
                            "--surface-points", INPUTS[0], "--orientations", INPUTS[1],
                            "--output-dir", "ki_results", "--output", "ki_result.json"],
                           cwd=run, env=env, capture_output=True, text=True, timeout=900)
            try:
                kr = json.loads((run / "ki_result.json").read_text())
                msg = kr.get("status") + (": " + "; ".join(kr.get("errors", [])) if kr.get("errors") else "")
            except Exception as e:
                msg = f"no result ({e})"
            print(f"  [info] KI tools/run_gempy_model.py: {msg}")

        # 2. Engine run with the official generator code
        (run / "driver.py").write_text(DRIVER)
        cp = subprocess.run([py, "driver.py"], cwd=run, env=env, capture_output=True,
                            text=True, timeout=1200)
        if cp.returncode != 0 or "DRIVER_OK" not in cp.stdout:
            fails.append(f"engine run failed (rc={cp.returncode}): {cp.stderr[-800:]}")
        else:
            print(f"  OK engine finished (rc=0, DRIVER_OK)")
            got = json.loads((run / "driver_result.json").read_text())
            print(f"  gempy {got['gempy_version']}")

            # official reference: GemPy's own approved array + own tolerance
            import numpy as np
            ref = EXP["official_reference_check"]
            appr = np.array((HERE / ref["file"]).read_text().replace("[", " ").replace("]", " ").split(), float)
            rec = np.array(got["sample"])
            if rec.shape != appr.shape:
                fails.append(f"scalar-field sample length {rec.shape} vs official {appr.shape}")
            elif not np.allclose(rec, appr, rtol=ref["rtol"], atol=ref["atol"]):
                fails.append(f"scalar-field sample differs from official approved file "
                             f"(max abs diff {np.abs(rec - appr).max():.3g})")
            else:
                print(f"  OK official approved scalar field: {len(rec)} values match "
                      f"(max abs diff {np.abs(rec - appr).max():.2g}, rtol/atol {ref['rtol']})")

            # 3. KI parse tool on the saved model
            pcp = subprocess.run([py, str(PARSE_TOOL), "--model-file", "fold.gempy",
                                  "--extract", "summary", "--output", "summary.json"],
                                 cwd=run, env=env, capture_output=True, text=True, timeout=600)
            try:
                s = json.loads((run / "summary.json").read_text())["summary"]["summary"]
                got["parse_n_groups"] = s["n_groups"]
                got["parse_n_elements"] = s["structural_groups"][0]["n_elements"]
                got["parse_grid_n_points"] = s["grid"]["n_points"]
            except Exception as e:
                fails.append(f"KI parse tool failed (rc={pcp.returncode}): {e} {pcp.stderr[-300:]}")

            for k, v in got.pop("lith_counts").items():
                got[f"lith_count_id{k}"] = v
            for c in EXP["numeric_checks"]:
                if c["name"] not in got:
                    if not any(c["name"].startswith("parse_") and "parse tool" in f for f in fails):
                        fails.append(f"{c['name']}: missing")
                    continue
                v = got[c["name"]]
                if abs(v - c["expected"]) > c["tol"]:
                    fails.append(f"{c['name']}: {v!r} vs {c['expected']}±{c['tol']}")
                else:
                    print(f"  OK {c['name']}: {v:.8g}")
    finally:
        shutil.rmtree(run, ignore_errors=True)

    if fails:
        print("FAIL:", file=sys.stderr)
        for f in fails:
            print("  -", f, file=sys.stderr)
        return 2
    print("PASS: GemPy anticline example reproduced GemPy's own approved result.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
