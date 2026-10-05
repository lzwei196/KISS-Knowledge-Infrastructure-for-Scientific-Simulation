#!/usr/bin/env python3
"""Run the official dfnWorks graph_transport example in a clean dir and check expected.json.

Foundation case for the dfnWorks KI. The official driver.py (examples/graph_transport)
makes a 3-family fracture network with DFNGen (seed = pydfnworks default 1), solves
graph-based flow left -> right, and tracks 10,000 particles on the graph. It needs only
DFNGen + pydfnworks (no LaGriT / PFLOTRAN / FEHM).
Exit 0 PASS, 2 checks failed, 3 engine/dependency missing.

Engine lookup (DFNGen binary): --dfngen-bin -> $DFNGEN_BIN -> `which DFNGen` -> server default.
pydfnworks finds DFNGen as <dfnworks_PATH>/DFNGen/DFNGen, so dfnworks_PATH is set to the
repo root two levels above the binary. Python (must import pydfnworks): --python ->
$DFNWORKS_PYTHON -> server python_env.

The driver is run unchanged. Only the run environment is set: a private HOME holding a
~/.dfnworksrc that points at the repo, and empty LAGRIT_EXE / PFLOTRAN_EXE / FEHM_EXE /
PETSC_DIR / PETSC_ARCH (pydfnworks crashes with KeyError 'LAGRIT_EXE' when they are not set
at all, even though this example never uses them).
Output is read with the KI tool tools/parse_dfnworks_output.py (graph_flow.hdf5) and directly
(DFN_output.txt, graph_partime.hdf5) because the KI parser does not read those two files.
Use --record to print the measured values without checking.
"""
import argparse, json, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP = json.loads((HERE / "expected.json").read_text())
PARSE_TOOL = HERE.parents[1] / "tools" / "parse_dfnworks_output.py"
_DEF_BIN = ("/home/server/knowledge-dissection-toolkit/auto_dissect/_work/dfnWorks/"
            "source/repo/DFNGen/DFNGen")
_DEF_PY = "/mnt/disk1/Hydrocraft_server/python_env/bin/python"
OK_LINES = ("Graph Particle Tracking Completed Successfully.", "All particles exited the network")

READ_PARTIME = r"""
import h5py, json, sys, numpy as np
with h5py.File(sys.argv[1], 'r') as h:
    t = np.array(h['Total travel time [s]']); a = np.array(h['Advective time [s]'])
    L = np.array(h['Pathline length [m]']); b = np.array(h['Beta [s m^-1]'])
print(json.dumps({"n_particles": int(t.size), "travel_time_min_s": float(t.min()),
    "travel_time_median_s": float(np.median(t)), "travel_time_mean_s": float(t.mean()),
    "travel_time_max_s": float(t.max()), "advective_time_mean_s": float(a.mean()),
    "pathline_length_mean_m": float(L.mean()), "beta_mean_s_per_m": float(b.mean())}))
"""


def first(cands, ok):
    return next((c for c in cands if c and ok(c)), None)


def dfn_output_stats(fp):
    txt = fp.read_text()
    g = lambda pat, f=float: f(re.search(pat, txt).group(1))
    after = txt.split("Statistics After Isolated Fractures Removed:")[1]
    return {
        "fractures_accepted": g(r"(\d+) Fractures Accepted \(Before", int),
        "fractures_final": g(r"Final Number of Fractures: (\d+)", int),
        "isolated_removed": g(r"Isolated Fractures Removed: (\d+)", int),
        "intersections": g(r"Number of Intersections: (\d+)", int),
        "final_p32": float(re.search(r"Total Fracture Intensity \(P32\): ([\d.eE+-]+)", after).group(1)),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dfngen-bin")
    ap.add_argument("--python")
    ap.add_argument("--record", action="store_true", help="print values, do not check")
    ap.add_argument("--keep", action="store_true", help="keep the temp run dir")
    a = ap.parse_args()

    dfngen = first((a.dfngen_bin, os.environ.get("DFNGEN_BIN"), shutil.which("DFNGen"), _DEF_BIN),
                   lambda p: os.path.isfile(p) and os.access(p, os.X_OK))
    if not dfngen:
        print("MISSING DEPENDENCY: DFNGen binary not found (set --dfngen-bin or $DFNGEN_BIN). NOT run.",
              file=sys.stderr)
        return 3
    repo = Path(dfngen).resolve().parents[1]
    for helper in ("DFNTrans/DFNTrans", "CPP_correct_volumes/correct_volume",
                   "DFN_Mesh_Connectivity_Test/ConnectivityTest"):
        if not (repo / helper).is_file():  # pydfnworks would try to compile it inside the repo
            print(f"MISSING DEPENDENCY: {repo / helper} not built. NOT run.", file=sys.stderr)
            return 3
    py = first((a.python, os.environ.get("DFNWORKS_PYTHON"), _DEF_PY), os.path.isfile)
    chk = subprocess.run([py or sys.executable, "-c", "import pydfnworks, h5py, networkx"],
                         capture_output=True, text=True)
    if not py or chk.returncode != 0:
        print(f"MISSING DEPENDENCY: python with pydfnworks + h5py + networkx ({py}): "
              f"{chk.stderr.strip()[-300:]} NOT run.", file=sys.stderr)
        return 3

    run = Path(tempfile.mkdtemp(prefix="dfnworks_graph_transport_"))
    home = run / "home"
    home.mkdir()
    (home / ".dfnworksrc").write_text(json.dumps({
        "dfnworks_PATH": str(repo) + "/", "PETSC_DIR": "", "PETSC_ARCH": "",
        "PFLOTRAN_EXE": "", "LAGRIT_EXE": "", "FEHM_EXE": ""}, indent=4))
    case = run / "case"
    case.mkdir()
    shutil.copy(HERE / "inputs" / "driver.py", case / "driver.py")
    env = dict(os.environ, HOME=str(home), MPLCONFIGDIR=str(home), PYTHONDONTWRITEBYTECODE="1",
               LAGRIT_EXE="", PFLOTRAN_EXE="", FEHM_EXE="", PETSC_DIR="", PETSC_ARCH="")

    fails, got = [], {}
    cp = subprocess.run([py, "driver.py"], cwd=case, env=env, capture_output=True, text=True,
                        timeout=1200)
    (run / "driver.stdout").write_text(cp.stdout)
    out = case / "output"
    if cp.returncode != 0:
        fails.append(f"driver.py rc={cp.returncode}: {cp.stderr.strip()[-600:]}")
    else:
        print(f"  ran driver.py (rc=0) with {py}, DFNGen {dfngen}")
        for line in OK_LINES:
            if line not in cp.stdout:
                fails.append(f"success line missing: {line!r}")
            else:
                print(f"  OK model line: {line}")
        got.update(dfn_output_stats(out / "DFN_output.txt"))
        pj = run / "parsed.json"
        pp = subprocess.run([py, str(PARSE_TOOL), "--job_dir", str(out), "--format", "json",
                             "--output", str(pj)], env=env, capture_output=True, text=True)
        if pp.returncode != 0 or not pj.is_file():
            fails.append(f"KI parse tool failed rc={pp.returncode}: {pp.stderr[-300:]}")
        else:
            gf = json.loads(pj.read_text())["graph_flow"]
            got["graph_edges"] = gf["vol_flow_rate"]["n_values"]
            got["edge_flow_rate_mean_m3s"] = gf["vol_flow_rate"]["mean"]
            got["edge_velocity_max_ms"] = gf["velocity"]["max"]
        rp = subprocess.run([py, "-c", READ_PARTIME, str(out / "graph_partime.hdf5")],
                            env=env, capture_output=True, text=True)
        if rp.returncode != 0:
            fails.append(f"reading graph_partime.hdf5 failed: {rp.stderr[-300:]}")
        else:
            got.update(json.loads(rp.stdout))

    if a.record:
        print(json.dumps(got, indent=2))
    elif not fails:
        for c in EXP["numeric_checks"]:
            v = got.get(c["name"])
            if v is None:
                fails.append(f"{c['name']}: not measured")
                continue
            lim = c["tol"] * abs(c["expected"]) if c.get("tol_type") == "relative" else c["tol"]
            if abs(v - c["expected"]) > lim:
                fails.append(f"{c['name']}: {v:.9g} vs {c['expected']} (tol {c['tol']} "
                             f"{c.get('tol_type', 'absolute')})")
            else:
                print(f"  OK {c['name']}: {v:.9g}")

    if a.keep:
        print(f"  kept run dir: {run}")
    else:
        shutil.rmtree(run, ignore_errors=True)
    if fails:
        print("FAIL:", file=sys.stderr)
        for f in fails:
            print("  -", f, file=sys.stderr)
        return 2
    if not a.record:
        print("PASS: dfnWorks graph_transport reproduced the expected results.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
