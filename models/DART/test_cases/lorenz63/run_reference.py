#!/usr/bin/env python3
"""Run the official DART Lorenz-63 example in a clean dir and check expected.json.

Foundation case for the DART KI. Steps (DART's own workflow for lorenz_63/work):
ncgen the two start-state .cdl files, perfect_model_obs (truth run + synthetic obs),
then filter (20-member ensemble assimilation). Both programs are run through the
KI's own tools/run_dart.py. Exit 0 PASS, 2 checks failed, 3 programs/ncgen missing.

Program lookup: --dart-work-dir -> $DART_WORK_DIR -> dir of $DART_FILTER_BINARY ->
server default. The dir must hold built perfect_model_obs and filter (lorenz_63).
"""
import argparse, json, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
EXP = json.loads((HERE / "expected.json").read_text())
RUN_TOOL = HERE.parents[1] / "tools" / "run_dart.py"
_DEF = "/home/server/knowledge-dissection-toolkit/auto_dissect/_work/DART/source/repo/models/lorenz_63/work"
PROGS = ("perfect_model_obs", "filter")
INPUTS = ("input.nml", "obs_seq.in", "filter_input.cdl", "perfect_input.cdl",
          "filter_input_list.txt", "filter_output_list.txt")


def parse_obs_seq(fp):
    """ASCII obs_seq -> (values array [n_obs, copies+qc], num_copies)."""
    txt = open(fp).read()
    nc = int(re.search(r"num_copies:\s*(\d+)", txt).group(1))
    nq = int(re.search(r"num_qc:\s*(\d+)", txt).group(1))
    lines = txt.split("\n")
    rows = [[float(lines[i + 1 + k].replace("D", "E")) for k in range(nc + nq)]
            for i, l in enumerate(lines) if l.strip().startswith("OBS ")]
    return np.array(rows), nc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dart-work-dir")
    a = ap.parse_args()
    fb = os.environ.get("DART_FILTER_BINARY")
    cands = (a.dart_work_dir, os.environ.get("DART_WORK_DIR"),
             str(Path(fb).parent) if fb else None, _DEF)
    wd = next((c for c in cands if c and all((Path(c) / p).is_file() for p in PROGS)), None)
    if not wd:
        print("MISSING DEPENDENCY: built DART lorenz_63 perfect_model_obs + filter not found "
              "(set DART_WORK_DIR or --dart-work-dir). NOT run.", file=sys.stderr)
        return 3
    if not shutil.which("ncgen"):
        print("MISSING DEPENDENCY: ncgen (netCDF tools) not on PATH. NOT run.", file=sys.stderr)
        return 3

    run = Path(tempfile.mkdtemp(prefix="dart_l63_"))
    for f in INPUTS:
        shutil.copy(HERE / "inputs" / f, run / f)
    for p in PROGS:
        shutil.copy(Path(wd) / p, run / p)
    for stem in ("perfect_input", "filter_input"):
        subprocess.run(["ncgen", "-o", f"{stem}.nc", f"{stem}.cdl"], cwd=run, check=True)

    fails = []
    for p in PROGS:
        cp = subprocess.run([sys.executable, str(RUN_TOOL), "--program", p,
                             "--work_dir", str(run), "--timeout", "600"],
                            capture_output=True, text=True, timeout=900)
        if cp.returncode != 0:
            fails.append(f"{p} failed (rc={cp.returncode}): {cp.stderr[-400:]}")
            break
        print(f"  ran {p}")

    if not fails:
        out, _ = parse_obs_seq(run / "obs_seq.out")
        fin, nc = parse_obs_seq(run / "obs_seq.final")
        obs, truth, prior, post = fin[:, 0], fin[:, 1], fin[:, 2], fin[:, 3]
        rmse = lambda x: float(np.sqrt(np.mean((x - truth) ** 2)))
        got = {
            "n_obs_out": len(out), "n_obs_final": len(fin), "num_copies_final": nc,
            "rmse_obs": rmse(obs), "rmse_prior_mean": rmse(prior),
            "rmse_posterior_mean": rmse(post),
            "mean_prior_spread": float(fin[:, 4].mean()),
            "mean_posterior_spread": float(fin[:, 5].mean()),
        }
        for c in EXP["numeric_checks"]:
            v = got[c["name"]]
            if abs(v - c["expected"]) > c["tol"]:
                fails.append(f"{c['name']}: {v:.6g} vs {c['expected']}±{c['tol']}")
            else:
                print(f"  OK {c['name']}: {v:.6g}")
        if not got["rmse_posterior_mean"] < got["rmse_prior_mean"] < got["rmse_obs"]:
            fails.append("filter did not reduce error (need posterior < prior < obs RMSE)")
        else:
            print("  OK error drops: obs > prior > posterior")

    shutil.rmtree(run, ignore_errors=True)
    if fails:
        print("FAIL:", file=sys.stderr)
        for f in fails:
            print("  -", f, file=sys.stderr)
        return 2
    print("PASS: DART Lorenz-63 reproduced the expected results.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
