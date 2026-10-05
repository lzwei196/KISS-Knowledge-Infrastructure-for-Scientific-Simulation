#!/usr/bin/env python3
"""Run the official CSDMS BMI heat example in a clean dir and check expected.json.

Foundation case for the BMI KI. The engine is the CSDMS reference BMI model
`BmiHeat` (package `heat` from csdms/bmi-example-python). Three parts:
  1. the official notebook inputs/run-model-from-bmi.ipynb, run cell by cell
     (with inputs/heat.yaml) -- spike of 100 K in the plate centre, 10 steps;
  2. the same case through the KI's own tools/bmi_runner.py (validate_inputs ->
     run_model, spike injected at t=0 via inject_schedule) and the KI's
     tools/compliance_checker.py on the BmiHeat class;
  3. the upstream unit tests inputs/tests/*.py (28 tests), called directly.
Exit 0 PASS, 2 checks failed, 3 engine/dependency missing.

Engine lookup (a Python that can import heat.bmi_heat):
  --heat-python -> $BMI_HEAT_PYTHON -> `which python3` -> server default venv.
"""
import argparse, importlib.util, json, os, shutil, subprocess, sys, tempfile
from pathlib import Path

sys.dont_write_bytecode = True  # keep the KI tools/ and case dirs clean
HERE = Path(__file__).resolve().parent
TOOLS = HERE.parents[1] / "tools"
_DEF = "/home/server/knowledge-dissection-toolkit/auto_dissect/_work/BMI/venv/bin/python"
VAR = "plate_surface__temperature"


def _bmiheat():
    """Return BmiHeat. Note: the server venv lost heat/__init__.py, so
    `from heat import BmiHeat` fails there; heat.bmi_heat still works. We then
    set heat.BmiHeat at run time (no file is changed) so the official notebook
    and tests, which use `from heat import BmiHeat`, run unchanged."""
    import heat
    import heat.bmi_heat
    if not hasattr(heat, "BmiHeat"):
        heat.BmiHeat = heat.bmi_heat.BmiHeat
    return heat.bmi_heat.BmiHeat


def worker(run):
    """Runs inside the engine Python, cwd = temp run dir. Prints one JSON line."""
    import numpy as np
    os.chdir(run)
    BmiHeat = _bmiheat()
    import heat._version as hv
    got = {"heat_version": hv.__version__}

    # ---- 1. official notebook, cell by cell -------------------------------
    nb = json.loads(Path("run-model-from-bmi.ipynb").read_text())
    ns = {}
    after_first_update = None
    for c in nb["cells"]:
        if c["cell_type"] != "code":
            continue
        src = "".join(c["source"])
        src = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("!"))
        exec(compile(src, "notebook", "exec"), ns)
        if src.strip() == "x.update()" and after_first_update is None:
            buf = np.empty(ns["shape"].prod())
            ns["x"].get_value(VAR, buf)
            after_first_update = buf.reshape(ns["shape"]).copy()
            got["nb_time_after_first_update"] = float(ns["x"].get_current_time())
        if "distant_time" in src:
            got["nb_final_time"] = float(ns["x"].get_current_time())
            got["nb_time_step"] = float(ns["x"].get_time_step())
    shape = tuple(int(v) for v in ns["shape"])
    fin = ns["temperature_flat"].reshape(shape)
    ci = tuple(s // 2 for s in shape)
    got.update({
        "nb_grid_size": int(fin.size),
        "nb_n_steps": int(round(got["nb_final_time"] / got["nb_time_step"])),
        "nb_center_after_1_step": float(after_first_update[ci]),
        "nb_center_final": float(fin[ci]),
        "nb_final_sum": float(fin.sum()),
        "nb_final_max": float(fin.max()),
        "nb_final_min": float(fin.min()),
    })

    # ---- 2. KI tools: bmi_runner + compliance_checker -----------------------
    def load(name):
        sp = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py")
        m = importlib.util.module_from_spec(sp)
        sp.loader.exec_module(m)
        return m
    runner = load("bmi_runner")
    spike = np.zeros(shape)
    spike[ci] = 100.0
    params = runner.validate_inputs(BmiHeat(), "heat.yaml", [VAR], 10 * 0.25,
                                    {0.0: {VAR: spike.flatten()}})
    res = runner.run_model(params, output_csv=str(Path(run) / "ki_runner_output.csv"))
    ok = runner.validate_outputs(res)
    last = res["variables"][VAR][-1]
    got.update({
        "ki_runner_ok": int(bool(ok)),
        "ki_runner_n_steps": int(res["n_steps"]),
        "ki_runner_final_time": float(res["times"][-1]),
        "ki_runner_final_max": float(last["max"]),
        "ki_runner_final_sum": float(last["mean"]) * got["nb_grid_size"],
        "ki_runner_csv_rows": sum(1 for _ in open("ki_runner_output.csv")) - 1,
    })
    comp = load("compliance_checker")
    rep = comp.check_compliance(BmiHeat)
    got["ki_compliance_implemented"] = int(rep["implemented"])
    got["ki_compliance_total"] = int(rep["total_functions"])
    got["ki_compliance_pass"] = int(rep["status"] == "PASS")

    # ---- 3. upstream unit tests (plain functions, no pytest needed) ---------
    n_pass, n_fail, failed = 0, 0, []
    for tf in sorted(Path("tests").glob("*_test.py")):
        sp = importlib.util.spec_from_file_location(tf.stem, tf)
        m = importlib.util.module_from_spec(sp)
        sp.loader.exec_module(m)
        for name in sorted(n for n in dir(m) if n.startswith("test_")):
            try:
                getattr(m, name)()
                n_pass += 1
            except Exception as e:  # noqa: BLE001
                n_fail += 1
                failed.append(f"{tf.stem}.{name}: {e!r}"[:200])
    got.update({"upstream_tests_passed": n_pass, "upstream_tests_failed": n_fail})
    got["_failed_tests"] = failed
    print("RESULT_JSON " + json.dumps(got))


def find_python(arg):
    cands = [arg, os.environ.get("BMI_HEAT_PYTHON"), shutil.which("python3"), _DEF]
    for c in cands:
        if not c or not Path(c).exists():
            continue
        r = subprocess.run([c, "-c", "import heat.bmi_heat, bmipy, numpy, scipy, yaml"],
                           capture_output=True, text=True, cwd="/")
        if r.returncode == 0:
            return c
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--heat-python")
    ap.add_argument("--worker")
    a = ap.parse_args()
    if a.worker:
        worker(a.worker)
        return 0

    py = find_python(a.heat_python)
    if not py:
        print("MISSING DEPENDENCY: no Python that can import heat.bmi_heat (bmi-heat from "
              "csdms/bmi-example-python) with bmipy, numpy, scipy, pyyaml "
              "(set BMI_HEAT_PYTHON or --heat-python). NOT run.", file=sys.stderr)
        return 3
    exp = json.loads((HERE / "expected.json").read_text())
    run = Path(tempfile.mkdtemp(prefix="bmi_heat_"))
    try:
        shutil.copytree(HERE / "inputs", run, dirs_exist_ok=True)
        cp = subprocess.run([py, "-B", str(Path(__file__).resolve()), "--worker", str(run)],
                            capture_output=True, text=True, timeout=600, cwd=run)
        line = next((l for l in cp.stdout.splitlines() if l.startswith("RESULT_JSON ")), None)
        if cp.returncode != 0 or not line:
            print(cp.stdout[-2000:], cp.stderr[-2000:], sep="\n")
            print(f"FAIL: engine run did not finish normally (rc={cp.returncode})")
            return 2
        got = json.loads(line[len("RESULT_JSON "):])
        print(f"engine python: {py}  (heat {got['heat_version']})")
        print("finished normally: rc=0, KI runner log: "
              + next((l for l in cp.stderr.splitlines() if "Model completed" in l), "?"))
        fails = []
        for chk in exp["numeric_checks"]:
            v = got.get(chk["name"])
            ok = v is not None and abs(v - chk["expected"]) <= chk["tol"]
            print(f"  {'ok  ' if ok else 'FAIL'} {chk['name']:30s} got={v!r:<24} "
                  f"expected={chk['expected']!r} tol={chk['tol']}")
            if not ok:
                fails.append(chk["name"])
        if got.get("_failed_tests"):
            print("  failed upstream tests:", *got["_failed_tests"], sep="\n    ")
        if abs(got["ki_runner_final_sum"] - got["nb_final_sum"]) > 1e-9:
            fails.append("ki_runner_vs_notebook_sum")
            print("  FAIL KI runner and notebook final sums differ")
        if fails:
            print(f"FAIL: {len(fails)} check(s) failed: {fails}")
            return 2
        print(f"PASS: all {len(exp['numeric_checks'])} checks ok "
              "(+ KI runner matches notebook)")
        return 0
    finally:
        shutil.rmtree(run, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
