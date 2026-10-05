#!/usr/bin/env python3
"""Run the official DuMux example examples/1ptracer and check expected.json.

Foundation case for the DuMux KI. The engine is the compiled example program
example_1ptracer (DuMux 3.10). The run is started through the KI's own
tools/run_dumux.py (its run_simulation function) in a fresh temp dir. The final
pressure and tracer fields are compared with the OFFICIAL DuMux test-suite
reference files using the OFFICIAL DuMux fuzzy-compare script and tolerance
(relative 1e-2, absolute 1.5e-7 * max value), exactly as the DuMux ctest
"example_1ptracer" does. Exit 0 PASS, 2 checks failed, 3 engine missing.

example_1ptracer lookup: --dumux-bin -> $DUMUX_BIN -> which example_1ptracer -> server default.
"""
import argparse, json, os, re, shutil, sys, tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
EXP = json.loads((HERE / "expected.json").read_text())
TOOLS = HERE.parents[1] / "tools"
_DEF = ("/home/server/knowledge-dissection-toolkit/auto_dissect/_work/DuMux/dumux/dumux/"
        "build-cmake/examples/1ptracer/example_1ptracer")
NAME = "example_1ptracer"
# Official ctest command: example_1ptracer params.input -Problem.Name example_1ptracer.
# Problem.FlowDirection=1 is extra: the server build has a KI-edited problem_1p.hh whose
# default (0) is a left-right flow; any value other than 0/2 runs the original official
# bottom-top code path. An unedited official build ignores this unused key.
OVERRIDES = {"Problem.Name": NAME, "Problem.FlowDirection": "1"}


def read_vtu(fn):
    out = {}
    for da in ET.parse(fn).getroot().iter("DataArray"):
        a = np.array(da.text.split(), float)
        n = int(da.get("NumberOfComponents", "1"))
        out[da.get("Name")] = a.reshape(-1, n) if n > 1 else a
    return out


def summarise(run, tail):
    o = {}
    p = read_vtu(run / "1p.vtu")
    o.update(p_min=p["p"].min(), p_max=p["p"].max(), p_mean=p["p"].mean(),
             permeability_mean=p["permeability"].mean())
    vtus = sorted(run.glob(f"{NAME}-*.vtu"))
    o["n_tracer_vtu"] = len(vtus)
    t0 = read_vtu(vtus[0])
    o["tracer_x_mean_start"] = t0["x^tracer_0"].mean()
    t = read_vtu(run / f"{NAME}-00010.vtu")
    v = t["velocity_Groundwater (m/s)"]
    o.update(tracer_x_max_end=t["x^tracer_0"].max(), tracer_x_mean_end=t["x^tracer_0"].mean(),
             velocity_max=np.linalg.norm(v, axis=1).max(), velocity_mean_y=v[:, 1].mean())
    times = [float(d.get("timestep")) for d in ET.parse(run / f"{NAME}.pvd").getroot().iter("DataSet")]
    o["pvd_last_time_s"] = times[-1]
    steps = re.findall(r"Time step (\d+) done.*?, time: ([0-9.eE+-]+), time step size", tail)
    o["n_time_steps"] = int(steps[-1][0]) if steps else -1
    o["final_time_s"] = float(steps[-1][1]) if steps else -1
    sys.path.insert(0, str(HERE / "compare"))
    from dumux_fuzzycompare_legacy import compareVTK  # official DuMux script, unmodified
    ref = HERE / "reference"
    # same argument order as DuMux bin/testing/dumux_runtest.py (legacy backend)
    o["fuzzy_fail_transport"] = compareVTK(str(run / f"{NAME}-00010.vtu"),
                                           str(ref / "test_1ptracer_transport-reference.vtu"),
                                           1.5e-7, 1e-2, {}, None, verbose=False)
    o["fuzzy_fail_pressure"] = compareVTK(str(run / "1p.vtu"),
                                          str(ref / "test_1ptracer_pressure-reference.vtu"),
                                          1.5e-7, 1e-2, {}, None, verbose=False)
    return {k: float(v) for k, v in o.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dumux-bin")
    ap.add_argument("--keep", action="store_true", help="keep the temp run dir")
    a = ap.parse_args()
    b = next((c for c in (a.dumux_bin, os.environ.get("DUMUX_BIN"), shutil.which(NAME), _DEF)
              if c and Path(c).is_file()), None)
    if not b:
        print("MISSING DEPENDENCY: example_1ptracer binary not found (set DUMUX_BIN). NOT run.",
              file=sys.stderr)
        return 3
    sys.path.insert(0, str(TOOLS))
    try:
        import run_dumux  # KI tool
    except ImportError as ex:
        print(f"MISSING DEPENDENCY: KI tool {TOOLS / 'run_dumux.py'} ({ex}). NOT run.", file=sys.stderr)
        return 3
    # The example uses OpenMP; without a limit it spins one thread per core (192 here).
    # Thread count does not change the results (checked: outputs byte-identical).
    os.environ.setdefault("DUMUX_NUM_THREADS", "4")
    os.environ.setdefault("OMP_NUM_THREADS", "4")
    run = Path(tempfile.mkdtemp(prefix="dumux_1ptracer_"))
    shutil.copy(HERE / "inputs" / "params.input", run / "params.input")
    r = run_dumux.run_simulation(b, "params.input", str(run), OVERRIDES, timeout=900)
    print(f"  ran {b} through KI tools/run_dumux.py run_simulation in {run} "
          f"({r['runtime_s']:.1f}s)")
    tail = r.get("stdout", "")
    fails = []
    if r["returncode"] != 0:
        fails.append(f"engine failed (rc={r['returncode']}): {r.get('stderr', '')[-400:]}")
    elif "Simulation took" not in tail:
        fails.append("engine success line 'Simulation took ...' not found")
    else:
        print("  OK finished: rc=0 and model line: "
              + [l for l in tail.splitlines() if "Simulation took" in l][-1].strip())
        try:
            got = summarise(run, tail)
        except Exception as ex:
            got = {}
            fails.append(f"could not read outputs: {ex}")
        for c in EXP["numeric_checks"]:
            v = got.get(c["name"])
            if v is None:
                fails.append(f"{c['name']}: not computed")
            elif abs(v - c["expected"]) > c["tol"]:
                fails.append(f"{c['name']}: {v:.10g} vs {c['expected']}+-{c['tol']}")
            else:
                print(f"  OK {c['name']}: {v:.10g}")
    if a.keep:
        print(f"  kept run dir {run}")
    else:
        shutil.rmtree(run, ignore_errors=True)
    if fails:
        print("FAIL:", file=sys.stderr)
        for f in fails:
            print("  -", f, file=sys.stderr)
        return 2
    print("PASS: DuMux 1ptracer example matches the official DuMux reference results.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
