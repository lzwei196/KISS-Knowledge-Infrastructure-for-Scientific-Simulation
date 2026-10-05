#!/usr/bin/env python3
"""Run the official OpenHydroQual validation case "first order decay in a batch reactor"
in a clean temp dir and check expected.json.

Foundation case for the OpenHydroQual KI. The model is run through the KI's own
tools/run_ohq.py (with --fix-paths, which rewrites the developer's hard-coded template
paths in a copy of the .ohq inside the temp dir only). The output is read with the KI's
tools/parse_output.py, and the concentration curve is compared with the official exact
solution (inputs/exact_solution.csv, C = 2*exp(-0.7 t)).

Exit 0 PASS, 2 checks failed, 3 engine/dependency missing.

Binary lookup: --ohq-bin -> $OHQ_BIN -> `which OHQLibTest` -> server default.
Resources (JSON templates) lookup: --resources -> $OHQ_RESOURCES -> <bin>/../resources.
The binary must stay in its build tree: it reads settings.json from <bin>/../../../resources.
"""
import argparse, bisect, csv, json, os, shutil, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP = json.loads((HERE / "expected.json").read_text())
TOOLS = HERE.parents[1] / "tools"
RUN_TOOL = TOOLS / "run_ohq.py"
PARSE_TOOL = TOOLS / "parse_output.py"
_DEF_BIN = ("/home/server/knowledge-dissection-toolkit/auto_dissect/_work/OpenHydroQual/"
            "source/repo/OHQLibTest/OHQLibTest")
INPUTS = ("first_order_decay.ohq", "exact_solution.csv")
CONC = "Reactor (1)_A:concentration"
MASS = "Reactor (1)_A:mass"
STOR = "Reactor (1)_Storage"


def missing(msg):
    print(f"MISSING DEPENDENCY: {msg} NOT run.", file=sys.stderr)
    return 3


def read_cols(fp, names):
    """OHQ output: interleaved (t, value) columns. Returns {name: (times, values)}."""
    with open(fp) as f:
        rows = list(csv.reader(f))
    head = [h.strip() for h in rows[0]]
    out = {}
    for n in names:
        i = head.index(n)
        t, v = [], []
        for r in rows[1:]:
            if len(r) > i and r[i].strip():
                t.append(float(r[i - 1])); v.append(float(r[i]))
        out[n] = (t, v)
    return out


def interp(t, v, x):
    j = bisect.bisect_left(t, x)
    if j <= 0:
        return v[0]
    if j >= len(t):
        return v[-1]
    t0, t1 = t[j - 1], t[j]
    return v[j - 1] + (v[j] - v[j - 1]) * (x - t0) / (t1 - t0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ohq-bin")
    ap.add_argument("--resources")
    a = ap.parse_args()
    cands = (a.ohq_bin, os.environ.get("OHQ_BIN"), shutil.which("OHQLibTest"), _DEF_BIN)
    binp = next((c for c in cands if c and os.path.isfile(c) and os.access(c, os.X_OK)), None)
    if not binp:
        return missing("OpenHydroQual engine OHQLibTest not found (set OHQ_BIN or --ohq-bin).")
    binp = os.path.abspath(binp)
    res = a.resources or os.environ.get("OHQ_RESOURCES") or str(Path(binp).parents[1] / "resources")
    if not (Path(res) / "main_components.json").is_file():
        return missing(f"OHQ resources dir with main_components.json not found ({res}); "
                       "set OHQ_RESOURCES or --resources.")
    if not Path(binp).parent.joinpath("../../../resources/settings.json").resolve().is_file():
        return missing("settings.json not found at <bin>/../../../resources/ "
                       "(the engine reads it from there).")
    ldd = shutil.which("ldd")
    if ldd:
        lo = subprocess.run([ldd, binp], capture_output=True, text=True).stdout
        if "not found" in lo:
            return missing("shared libraries of OHQLibTest: " +
                           "; ".join(l.strip() for l in lo.splitlines() if "not found" in l) + ".")
    for t in (RUN_TOOL, PARSE_TOOL):
        if not t.is_file():
            return missing(f"KI tool {t} not found.")

    run = Path(tempfile.mkdtemp(prefix="ohq_batch_decay_"))
    fails, got = [], {}
    try:
        for f in INPUTS:
            shutil.copy(HERE / "inputs" / f, run / f)
        cp = subprocess.run([sys.executable, str(RUN_TOOL), "--binary", binp,
                             "--input", str(run / "first_order_decay.ohq"),
                             "--resources", res, "--fix-paths", "--timeout", "600"],
                            capture_output=True, text=True, timeout=900, cwd=run)
        try:
            rj = json.loads(cp.stdout)
        except ValueError:
            rj = {"status": "error", "run": {"returncode": None, "stdout": cp.stdout}}
        rr = rj.get("run", {})
        stdout = rr.get("stdout", "")
        print(f"  ran OHQLibTest via tools/run_ohq.py: status={rj.get('status')} "
              f"rc={rr.get('returncode')} {rr.get('elapsed_s')} s")
        got["returncode"] = rr.get("returncode")
        got["finished_line"] = "Simulation finished!" in stdout
        out = run / "output.txt"
        if rj.get("status") != "success" or got["returncode"] != 0 or not out.is_file():
            fails.append(f"engine run failed: {json.dumps(rj)[-800:]}")
        else:
            pj = json.loads(subprocess.run(
                [sys.executable, str(PARSE_TOOL), "--input", str(out),
                 "--variables", ",".join((CONC, MASS, STOR))],
                capture_output=True, text=True, timeout=300, cwd=run).stdout)
            sc = pj[f"stats_{CONC}"]
            ss = pj[f"stats_{STOR}"]
            cols = read_cols(out, (CONC, MASS, STOR))
            t, c = cols[CONC]
            _, m = cols[MASS]
            _, s = cols[STOR]
            ex = [tuple(map(float, l.split(","))) for l in (run / "exact_solution.csv").read_text().split()
                  if l.strip()]
            errs = [abs(interp(t, c, te) - ce) for te, ce in ex]
            rel = [abs(interp(t, c, te) - ce) / ce for te, ce in ex if ce > 0]
            got.update({
                "n_rows": pj["n_rows"],
                "t_final": t[-1],
                "conc_first": c[0],
                "conc_min": sc["min"],
                "conc_mean": sc["mean"],
                "conc_t1": interp(t, c, 1.0),
                "conc_t2": interp(t, c, 2.0),
                "conc_t5": interp(t, c, 5.0),
                "storage_min": ss["min"],
                "storage_max": ss["max"],
                "mass_minus_conc_x_storage_max": max(abs(mi - ci * si) for mi, ci, si in zip(m, c, s)),
                "n_exact_points": len(ex),
                "max_abs_err_vs_exact": max(errs),
                "max_rel_err_vs_exact": max(rel),
            })
        if got.get("returncode") == 0 and got.get("finished_line"):
            print("  OK finished normally: rc=0 and 'Simulation finished!'")
        else:
            fails.append("model did not finish normally (rc!=0 or no 'Simulation finished!')")
        if "n_rows" in got:
            for chk in EXP["numeric_checks"]:
                v = got[chk["name"]]
                if abs(v - chk["expected"]) > chk["tol"]:
                    fails.append(f"{chk['name']}: {v:.8g} vs {chk['expected']}±{chk['tol']}")
                else:
                    print(f"  OK {chk['name']}: {v:.8g}")
    finally:
        shutil.rmtree(run, ignore_errors=True)

    if fails:
        print("FAIL:", file=sys.stderr)
        for f in fails:
            print("  -", f, file=sys.stderr)
        return 2
    print("PASS: OpenHydroQual batch first-order decay matches the official exact solution "
          "and the recorded run.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
