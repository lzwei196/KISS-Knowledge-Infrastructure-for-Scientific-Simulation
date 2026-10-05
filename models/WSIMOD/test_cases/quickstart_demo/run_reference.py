#!/usr/bin/env python3
"""Run the official WSIMOD quickstart demo in a clean dir and check expected.json.

Foundation case for the WSIMOD KI. The official demo (docs/demo/examples/quickstart_demo.yaml
+ docs/demo/data/processed/timeseries_data.csv from ImperialCollegeLondon/wsi) is run
through the KI's own tools/run_wsimod.py (API mode, same code path as the `wsimod` CLI),
and the output is read with the KI's tools/parse_wsimod_output.py plus pandas.
Exit 0 PASS, 2 checks failed, 3 wsimod package/dependency missing.

wsimod lookup: --wsimod-src arg -> $WSIMOD_SRC env -> already importable -> server default
repo source. The source dir is put on PYTHONPATH (the package is not pip-installed).
"""
import argparse, json, os, shutil, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP = json.loads((HERE / "expected.json").read_text())
TOOLS = HERE.parents[1] / "tools"
RUN_TOOL = TOOLS / "run_wsimod.py"
PARSE_TOOL = TOOLS / "parse_wsimod_output.py"
_DEF = "/home/server/knowledge-dissection-toolkit/auto_dissect/_work/WSIMOD/source/repo"
INPUTS = ("quickstart_demo.yaml", "timeseries_data.csv")


def find_src(arg):
    """Return (env, label) that makes `import wsimod` work, or (None, None)."""
    cands = [arg, os.environ.get("WSIMOD_SRC"), "", _DEF]
    for c in cands:
        if c is None:
            continue
        env = dict(os.environ)
        if c:
            if not (Path(c) / "wsimod" / "__init__.py").is_file():
                continue
            env["PYTHONPATH"] = c + os.pathsep + env.get("PYTHONPATH", "")
        cp = subprocess.run([sys.executable, "-c", "import wsimod, yaml, pandas, dill, tqdm"],
                            env=env, capture_output=True, text=True)
        if cp.returncode == 0:
            return env, (c or "installed package")
    return None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wsimod-src", help="WSIMOD repo source dir (holds wsimod/)")
    a = ap.parse_args()
    env, label = find_src(a.wsimod_src)
    if env is None:
        print("MISSING DEPENDENCY: python package wsimod (or yaml/pandas/dill/tqdm) not "
              "importable; set WSIMOD_SRC or --wsimod-src to the wsi repo source. NOT run.",
              file=sys.stderr)
        return 3
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    print(f"  wsimod from: {label}")

    run = Path(tempfile.mkdtemp(prefix="wsimod_qs_"))
    try:
        for f in INPUTS:
            shutil.copy(HERE / "inputs" / f, run / f)
        out = run / "out"
        fails = []
        cp = subprocess.run([sys.executable, str(RUN_TOOL), "--settings", str(run / INPUTS[0]),
                             "--inputs", str(run), "--outputs", str(out), "--mode", "api"],
                            cwd=run, env=env, capture_output=True, text=True, timeout=1200)
        try:
            res = json.loads(cp.stdout[cp.stdout.index("{"):])
        except ValueError:
            res = {}
        if cp.returncode != 0 or res.get("status") != "success":
            fails.append(f"run_wsimod failed (rc={cp.returncode}): {cp.stdout[-600:]} {cp.stderr[-600:]}")
        else:
            print(f"  ran run_wsimod.py: status=success rc=0 ({res.get('elapsed_seconds')} s)")
            pp = subprocess.run([sys.executable, str(PARSE_TOOL), "--output-dir", str(out),
                                 "--summary"], cwd=run, env=env, capture_output=True,
                                text=True, timeout=600)
            try:
                ps = json.loads(pp.stdout[pp.stdout.index("{"):])
            except ValueError:
                ps = {}
            if pp.returncode != 0 or ps.get("status") != "success":
                fails.append(f"parse_wsimod_output failed (rc={pp.returncode}): {pp.stdout[-400:]}")
            else:
                print("  ran parse_wsimod_output.py: status=success")

        if not fails:
            import pandas as pd
            f = pd.read_csv(out / "flows.csv")
            t = pd.read_csv(out / "tanks.csv")
            s = pd.read_csv(out / "surfaces.csv")
            q = f[f.arc == "catchment_outflow"].flow
            last = t.time.max()
            P, E = s.precipitation.sum(), s.evaporation.sum()
            S_end = t[t.time == last].storage.sum() + s[s.time == last].storage.sum()
            gw = t[(t.node == "my_groundwater") & (t.time == last)].storage.iloc[0]
            rural = s[(s.surface == "rural") & (s.time == last)].storage.iloc[0]
            got = {
                "n_timesteps": int(f.time.nunique()),
                "n_flow_records": len(f), "n_tank_records": len(t), "n_surface_records": len(s),
                "outlet_flow_sum": float(q.sum()), "outlet_flow_max": float(q.max()),
                "outlet_flow_mean": float(q.mean()),
                "baseflow_sum": float(f[f.arc == "baseflow"].flow.sum()),
                "storm_outflow_sum": float(f[f.arc == "storm_outflow"].flow.sum()),
                "precipitation_total": float(P), "evaporation_total": float(E),
                "final_groundwater_storage": float(gw),
                "final_rural_surface_storage": float(rural),
                "water_balance_residual": float(P - E - q.sum() - S_end),
            }
            for c in EXP["numeric_checks"]:
                v = got[c["name"]]
                ok = abs(v - c["expected"]) <= c["tol"]
                print(f"  {'ok  ' if ok else 'FAIL'} {c['name']}: got {v:.10g} "
                      f"expected {c['expected']} tol {c['tol']}")
                if not ok:
                    fails.append(c["name"])
    finally:
        shutil.rmtree(run, ignore_errors=True)

    if fails:
        print("FAIL:", "; ".join(fails))
        return 2
    print("PASS: WSIMOD quickstart demo matches expected.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
