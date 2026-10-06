#!/usr/bin/env python3
"""Run the official Badlands workshop example "mountain" and check expected.json.

Foundation case for the pyBadlands KI. The run goes through the KI's own tools:
tools/s5_run/run_badlands.py (runs the model) and tools/s6_output/parse_badlands_output.py
(reads the tin.time<N>.hdf5 output). expected.json holds values recorded from real runs on
this server (the workshop ships no reference output). Exit 0 PASS, 2 checks failed,
3 engine/dependency missing.

pyBadlands python lookup: --pybadlands-python -> $PYBADLANDS_PYTHON -> this python or
`which python3` / `which python` if it imports badlands -> server default venv.
Use --print to print the computed values without checking (for recording).
"""
import argparse, json, math, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP = json.loads((HERE / "expected.json").read_text())
TOOLS = HERE.parents[1] / "tools"
RUN_TOOL = TOOLS / "s5_run" / "run_badlands.py"
PARSE_TOOL = TOOLS / "s6_output" / "parse_badlands_output.py"
_DEF = "/home/server/knowledge-dissection-toolkit/auto_dissect/_work/pyBadlands/venv/bin/python"


def imports_badlands(py):
    try:
        cp = subprocess.run([py, "-c", "from badlands.model import Model"],
                            capture_output=True, timeout=120)
        return cp.returncode == 0
    except Exception:
        return False


def find_python(cli):
    for c in (cli, os.environ.get("PYBADLANDS_PYTHON")):
        if c:
            return c if Path(c).is_file() and imports_badlands(c) else None
    for c in (sys.executable, shutil.which("python3"), shutil.which("python")):
        if c and imports_badlands(c):
            return c
    if Path(_DEF).is_file() and imports_badlands(_DEF):
        return _DEF
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pybadlands-python")
    ap.add_argument("--print", action="store_true", help="print values, do not check")
    a = ap.parse_args()
    py = find_python(a.pybadlands_python)
    if not py:
        print("MISSING DEPENDENCY: no python that imports badlands (set PYBADLANDS_PYTHON). "
              "NOT run.", file=sys.stderr)
        return 3
    run = Path(tempfile.mkdtemp(prefix="badlands_mountain_"))
    fails, got = [], {}
    try:
        shutil.copy(HERE / "inputs" / "mountain.xml", run / "mountain.xml")
        shutil.copytree(HERE / "inputs" / "data", run / "data")
        # Badlands opens the XML's files relative to the current folder, so run inside `run`.
        cp = subprocess.run([sys.executable, str(RUN_TOOL), "--xml", "mountain.xml",
                             "--pybadlands-python", py, "--output-json", "run_result.json"],
                            cwd=run, capture_output=True, text=True, timeout=1500)
        if cp.returncode != 0:
            fails.append(f"run_badlands.py failed (rc={cp.returncode}): "
                         f"{(cp.stdout + cp.stderr)[-600:]}")
        else:
            res = json.loads((run / "run_result.json").read_text())
            print(f"  ran pyBadlands through KI tools/s5_run/run_badlands.py "
                  f"({res.get('run_time_s')} s)")
            # Badlands' own end-of-run line: "tNow = <years> (<s> seconds)".
            tnow = re.findall(r"tNow = ([0-9.eE+-]+)", cp.stdout)
            pp = subprocess.run([py, str(PARSE_TOOL), "--output-dir", res["output_dir"],
                                 "--summary", str(run / "summary.json")],
                                capture_output=True, text=True, timeout=600)
            if pp.returncode != 0:
                fails.append(f"parse_badlands_output.py failed (rc={pp.returncode}): "
                             f"{(pp.stdout + pp.stderr)[-600:]}")
            else:
                recs = json.loads((run / "summary.json").read_text())["records"]
                last, first = recs[-1], recs[0]
                got = {
                    "run_status_completed": 1.0 if res.get("status") == "completed" else 0.0,
                    "model_tnow_line_yr": float(tnow[-1]) if tnow else float("nan"),
                    "final_time_yr": float(res["final_time"]),
                    "n_tin_steps": float(len(recs)),
                    "last_step_number": float(last["step"]),
                    "n_nodes": float(last["n_nodes"]),
                    "initial_elev_max_m": first["elev_max"],
                    "final_elev_min_m": last["elev_min"],
                    "final_elev_max_m": last["elev_max"],
                    "final_elev_mean_m": last["elev_mean"],
                    "final_cumdiff_min_m": last["cumdiff_min"],
                    "final_cumdiff_max_m": last["cumdiff_max"],
                    "final_cumdiff_mean_m": last["cumdiff_mean"],
                    "final_total_erosion_m": last["total_erosion_m"],
                    "final_discharge_max": last["discharge_max"],
                }
    except Exception as ex:  # timeout, bad/missing JSON, missing fields, empty records
        fails.append(f"run or read failed: {type(ex).__name__}: {ex}")
    finally:
        shutil.rmtree(run, ignore_errors=True)
    if a.print:
        print(json.dumps(got, indent=2))
        for f in fails:
            print("  -", f, file=sys.stderr)
        return 0 if not fails else 2
    if not fails:
        for c in EXP["numeric_checks"]:
            v = got.get(c["name"])
            if v is not None and not isinstance(v, (int, float)):
                fails.append(f"{c['name']}: not a number ({v!r})")
            elif v is None:
                fails.append(f"{c['name']}: not computed")
            elif not math.isfinite(v):
                fails.append(f"{c['name']}: not a finite number ({v})")
            elif abs(v - c["expected"]) > c["tol"]:
                fails.append(f"{c['name']}: {v:.12g} vs {c['expected']}±{c['tol']}")
            else:
                print(f"  OK {c['name']}: {v:.12g}")
    if fails:
        print("FAIL:", file=sys.stderr)
        for f in fails:
            print("  -", f, file=sys.stderr)
        return 2
    print("PASS: Badlands workshop 'mountain' case matches the recorded values.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
