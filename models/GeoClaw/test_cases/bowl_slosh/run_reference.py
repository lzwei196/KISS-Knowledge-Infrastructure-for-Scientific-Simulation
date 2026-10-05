#!/usr/bin/env python3
"""Run the official GeoClaw regression test "bowl_slosh" and check expected.json.

Foundation case for the GeoClaw KI. Steps, all in a fresh temp dir:
  1. copy the Clawpack Fortran sources (amrclaw, clawutil, geoclaw, riemann src/) from
     $CLAW into the temp dir, so compiling never writes into the real source tree;
  2. copy the unmodified official files from inputs/ and make the bowl topography with the
     official maketopo.py (what `make topo` runs);
  3. run the KI's own tools/run_geoclaw.py --use-makefile (setrun.py -> make .exe -> xgeoclaw);
  4. read the frames with the KI's tools/parse_geoclaw_output.py, and read gauge 1 and the
     fgmax grid with Clawpack's own readers (as geoclaw/tests/bowl_slosh/regression_tests.py
     does), then compare with the OFFICIAL regression_data with the official tolerance
     (gauge: rtol 1e-14, atol 1e-8; fgmax sums: rtol 1e-14, atol 1e-8).
Exit 0 PASS, 2 checks failed, 3 engine/dependency missing.

Engine lookup (GeoClaw has no prebuilt binary; it is Clawpack source + gfortran + Python):
  Clawpack source : --claw-dir    -> $CLAW        -> server default
  Clawpack Python : --claw-python -> $CLAW_PYTHON -> server default -> which python3
  Fortran compiler: --fc          -> $FC          -> which gfortran
"""
import argparse, json, os, shutil, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP = json.loads((HERE / "expected.json").read_text())
TOOLS = HERE.parents[1] / "tools"
RUN_TOOL = TOOLS / "run_geoclaw.py"
PARSE_TOOL = TOOLS / "parse_geoclaw_output.py"
_WORK = "/home/server/knowledge-dissection-toolkit/auto_dissect/_work/GeoClaw"
_DEF_CLAW = _WORK + "/clawpack"
_DEF_PY = _WORK + "/venv/bin/python"
NEEDED_SRC = ["clawutil/src/Makefile.common", "geoclaw/src/2d/shallow/Makefile.geoclaw",
              "amrclaw/src/2d", "riemann/src/rpn2_geoclaw.f"]

# Reader run with the Clawpack Python (it holds the official readers).
READER = r"""
import json, sys, numpy as np
from clawpack.pyclaw import gauges
from clawpack.geoclaw import fgmax_tools
run, ref = sys.argv[1], sys.argv[2]
g = gauges.GaugeSolution(1, path=run)
r = gauges.GaugeSolution(1, path=ref)
o = dict(gauge1_n_records=g.t.size, gauge1_t_end=g.t[-1],
         gauge1_eta_max=g.q[3].max(), gauge1_eta_min=g.q[3].min(),
         gauge1_hv_max=g.q[2].max(), gauge1_hv_final=g.q[2][-1])
# the official check: check_gauges(indices=(2,3)) -> hv and eta, rtol 1e-14, atol 1e-8
same = g.q.shape == r.q.shape
for n, name in ((2, "hv"), (3, "eta")):
    o["gauge1_%s_series_matches_official" % name] = int(
        same and np.allclose(g.q[n], r.q[n], rtol=1e-14, atol=1e-8))
fg = fgmax_tools.FGmaxGrid()
fg.read_fgmax_grids_data(1, run + "/fgmax_grids.data")
fg.read_output(outdir=run)
o["fgmax_h_sum"] = fg.h.sum()
o["fgmax_s_sum"] = fg.s.sum()
print("JSON=" + json.dumps({k: float(v) for k, v in o.items()}))
"""


def first(*cands):
    return next((c for c in cands if c), None)


def has_clawpack(py):
    try:
        return subprocess.run([py, "-c", "import clawpack.geoclaw, clawpack.clawutil"],
                              capture_output=True, timeout=60).returncode == 0
    except Exception:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--claw-dir")
    ap.add_argument("--claw-python")
    ap.add_argument("--fc")
    a = ap.parse_args()

    claw = first(a.claw_dir, os.environ.get("CLAW"), _DEF_CLAW)
    py = next((p for p in (a.claw_python, os.environ.get("CLAW_PYTHON"), _DEF_PY,
                           shutil.which("python3")) if p and Path(p).is_file() and has_clawpack(p)), None)
    fc = first(a.fc, os.environ.get("FC"), "gfortran")
    fc_path = shutil.which(fc)
    miss = []
    if not claw or not all((Path(claw) / s).exists() for s in NEEDED_SRC):
        miss.append(f"Clawpack source tree (need {NEEDED_SRC} under --claw-dir/$CLAW, tried {claw})")
    if not py:
        miss.append("a Python with clawpack installed (--claw-python/$CLAW_PYTHON)")
    if not fc_path:
        miss.append(f"Fortran compiler '{fc}' (--fc/$FC)")
    for t in (RUN_TOOL, PARSE_TOOL):
        if not t.is_file():
            miss.append(f"KI tool {t}")
    if miss:
        print("MISSING DEPENDENCY: " + "; ".join(miss) + ". NOT run.", file=sys.stderr)
        return 3

    tmp = Path(tempfile.mkdtemp(prefix="geoclaw_bowl_slosh_"))
    fails, got = [], {}
    try:
        # 1. private copy of the Clawpack sources (objects are compiled next to them)
        ign = shutil.ignore_patterns("*.o", "*.mod", "__pycache__", "*.pyc")
        for pkg in ("amrclaw", "clawutil", "geoclaw", "riemann"):
            shutil.copytree(Path(claw) / pkg / "src", tmp / "claw" / pkg / "src", ignore=ign)
        # 2. unmodified official files
        run = tmp / "run"
        shutil.copytree(HERE / "inputs", run)
        env = dict(os.environ, CLAW=str(tmp / "claw"), FC=fc_path, OMP_NUM_THREADS="4",
                   PATH=str(Path(py).parent) + os.pathsep + os.environ.get("PATH", ""))
        env.pop("FFLAGS", None)
        cp = subprocess.run([py, "maketopo.py"], cwd=run, env=env, capture_output=True,
                            text=True, timeout=300)
        if cp.returncode != 0:
            raise RuntimeError(f"maketopo.py failed: {cp.stderr[-400:]}")
        # 3. KI run tool
        tool_json = tmp / "run_tool.json"
        cp = subprocess.run([py, str(RUN_TOOL), "--run-dir", str(run), "--use-makefile",
                             "--timeout", "900", "--json-output", str(tool_json)],
                            cwd=tmp, env=env, capture_output=True, text=True, timeout=1200)
        res = json.loads(tool_json.read_text()) if tool_json.is_file() else {}
        amr = (run / "fort.amr").read_text() if (run / "fort.amr").is_file() else ""
        ok = (cp.returncode == 0 and res.get("status") == "success"
              and all(s.get("returncode") == 0 for s in res.get("steps", []))
              and "end of AMRCLAW integration" in amr)
        got["finished_normally"] = float(ok)
        if not ok:
            fails.append(f"run_geoclaw.py: rc={cp.returncode} status={res.get('status')} "
                         f"error={res.get('error')} {cp.stderr[-300:]}")
        else:
            print("  ran GeoClaw through KI tools/run_geoclaw.py (setrun -> make .exe -> xgeoclaw)")
            # 4a. KI parse tool: frames (xgeoclaw writes into the run dir, see README)
            pj = tmp / "parse.json"
            subprocess.run([py, str(PARSE_TOOL), "--output-dir", str(run), "--json-output", str(pj)],
                           cwd=tmp, env=env, capture_output=True, text=True, timeout=300)
            if pj.is_file():
                p = json.loads(pj.read_text())
                if p.get("n_frames"):
                    got["n_frames"] = float(p["n_frames"])
                    got["final_frame_time"] = float(p["time_range"][1])
            # 4b. official readers, official reference data
            cp = subprocess.run([py, "-c", READER, str(run), str(run / "regression_data")],
                                cwd=tmp, env=env, capture_output=True, text=True, timeout=300)
            line = [l for l in cp.stdout.splitlines() if l.startswith("JSON=")]
            if line:
                got.update(json.loads(line[0][5:]))
            else:
                fails.append(f"could not read outputs: {cp.stderr[-400:]}")
    except Exception as ex:
        fails.append(f"run error: {ex}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    for c in EXP["numeric_checks"]:
        v = got.get(c["name"])
        lim = c["tol"] + c.get("rtol", 0.0) * abs(c["expected"])
        if v is None:
            fails.append(f"{c['name']}: not computed")
        elif abs(v - c["expected"]) > lim:
            fails.append(f"{c['name']}: {v:.17g} vs {c['expected']} +/- {lim:.3g}")
        else:
            print(f"  OK {c['name']}: {v:.17g}")
    if fails:
        print("FAIL:", file=sys.stderr)
        for f in fails:
            print("  -", f, file=sys.stderr)
        return 2
    print("PASS: GeoClaw bowl_slosh matches the official Clawpack regression data.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
