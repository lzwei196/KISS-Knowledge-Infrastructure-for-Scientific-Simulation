#!/usr/bin/env python3
"""Run the official ADCIRC test-suite case adcirc_quarterannular-2d and check expected.json.

Foundation case for the ADCIRC KI. The run goes through the KI's own tools/run_adcirc.py
(serial). expected.json holds values taken from the official ADCIRC test-suite solution
files, with the suite's own tolerance (1e-5). Exit 0 PASS, 2 checks failed, 3 binary missing.

adcirc lookup: --adcirc-bin -> $ADCIRC_BIN -> which adcirc -> server default.
"""
import argparse, json, os, shutil, subprocess, sys, tempfile
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from adcirc_ascii import read_ts  # noqa: E402

EXP = json.loads((HERE / "expected.json").read_text())
RUN_TOOL = HERE.parents[1] / "tools" / "run_adcirc.py"
_DEF = "/mnt/disk1/Hydrocraft_server/models/ADCIRC/bin/adcirc"


def summarise(d):
    o = {}
    t, e = read_ts(d / "fort.63")
    o.update(fort63_n_snap=len(t), fort63_t_end_s=t[-1], fort63_max_elev=e.max(),
             fort63_min_elev=e.min(), fort63_last_mean_abs_elev=np.abs(e[-1]).mean())
    t, v = read_ts(d / "fort.64")
    sp = np.hypot(v[..., 0], v[..., 1])
    o.update(fort64_max_speed=sp.max(), fort64_last_mean_speed=sp[-1].mean())
    t, s = read_ts(d / "fort.61")
    o.update(fort61_n_snap=len(t), fort61_max_elev=s.max(), fort61_min_elev=s.min())
    t, m = read_ts(d / "maxele.63")
    o.update(maxele_max=m[0].max(), maxele_mean=m[0].mean())
    return {k: float(v) for k, v in o.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--adcirc-bin")
    a = ap.parse_args()
    b = next((c for c in (a.adcirc_bin, os.environ.get("ADCIRC_BIN"), shutil.which("adcirc"), _DEF)
              if c and Path(c).is_file()), None)
    if not b:
        print("MISSING DEPENDENCY: adcirc binary not found (set ADCIRC_BIN). NOT run.", file=sys.stderr)
        return 3
    run = Path(tempfile.mkdtemp(prefix="adcirc_qa_"))
    for f in ("fort.14", "fort.15"):
        shutil.copy(HERE / "inputs" / f, run / f)
    cp = subprocess.run([sys.executable, str(RUN_TOOL), "--binary", b, "--work_dir", str(run),
                         "--mode", "serial", "--timeout", "900"],
                        capture_output=True, text=True, timeout=1200)
    fails = []
    if cp.returncode != 0:
        fails.append(f"run_adcirc.py failed (rc={cp.returncode}): {cp.stderr[-400:]}")
    else:
        print("  ran adcirc through KI tools/run_adcirc.py")
        try:
            got = summarise(run)
        except Exception as ex:  # missing/short output file
            got = {}
            fails.append(f"could not read outputs: {ex}")
        for c in EXP["numeric_checks"]:
            v = got.get(c["name"])
            if v is None:
                fails.append(f"{c['name']}: not computed")
            elif abs(v - c["expected"]) > c["tol"]:
                fails.append(f"{c['name']}: {v:.10g} vs {c['expected']}±{c['tol']}")
            else:
                print(f"  OK {c['name']}: {v:.10g}")
    shutil.rmtree(run, ignore_errors=True)
    if fails:
        print("FAIL:", file=sys.stderr)
        for f in fails:
            print("  -", f, file=sys.stderr)
        return 2
    print("PASS: ADCIRC quarter-annular case matches the official ADCIRC solution.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
