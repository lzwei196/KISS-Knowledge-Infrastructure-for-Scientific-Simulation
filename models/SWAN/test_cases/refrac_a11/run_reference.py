#!/usr/bin/env python3
"""Run the official SWAN refraction test (a11refr) in a clean dir and check expected.json.

Foundation case for the SWAN KI. The inputs are the unmodified files of the official
SWAN test case "refrac" (swanmodel.sourceforge.io/download/zip/refrac.tar.gz). The run
goes through the KI's own tools/run_swan.py (binary mode). The output is read with the
KI's tools/parse_swan_output.py and compared with the official reference output that
ships with the case (reference/) and with the official analytical solution.

Like the official `swanrun` script, the command file is also copied to the name INPUT
in the temp run dir, because swan.exe always reads the file INPUT. The inputs are not
changed. Exit 0 PASS, 2 checks failed, 3 engine/dependency missing.

Binary lookup: --swan-bin -> $SWAN_BIN -> `which swan.exe` / `which swan` -> server default.
"""
import argparse, importlib.util, json, os, shutil, subprocess, sys, tempfile
from pathlib import Path
import numpy as np

sys.dont_write_bytecode = True   # importing the KI parse tool must not leave __pycache__
HERE = Path(__file__).resolve().parent
EXP = json.loads((HERE / "expected.json").read_text())
TOOLS = HERE.parents[1] / "tools"
RUN_TOOL = TOOLS / "run_swan.py"
PARSE_TOOL = TOOLS / "parse_swan_output.py"
_DEF = ("/home/server/knowledge-dissection-toolkit/auto_dissect/_work/ADCIRC/"
        "source/repo/thirdparty/swan/swan.exe")
INPUTS = ("a11refr.swn", "a11refr.bot", "a11refr.loc")
TAB_COLS = ("DIST", "HS", "TM01", "DIR", "DEP", "RTP")   # order in a11refr.swn TABLE line


def find_bin(arg):
    for c in (arg, os.environ.get("SWAN_BIN"), shutil.which("swan.exe"),
              shutil.which("swan"), _DEF):
        if c and Path(c).is_file() and os.access(c, os.X_OK):
            return c
    return None


def load_parser():
    spec = importlib.util.spec_from_file_location("parse_swan_output", PARSE_TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def read_ana(fp):
    rows = []
    for line in open(fp):
        try:
            r = [float(x) for x in line.split()]
        except ValueError:
            continue
        if len(r) == 7:
            rows.append(r)
    return np.array(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--swan-bin")
    a = ap.parse_args()
    exe = find_bin(a.swan_bin)
    if not exe:
        print("MISSING DEPENDENCY: SWAN executable (swan.exe) not found "
              "(set SWAN_BIN or --swan-bin). NOT run.", file=sys.stderr)
        return 3
    try:
        parser = load_parser()
    except ImportError as e:
        print(f"MISSING DEPENDENCY: KI parse tool import failed ({e}). NOT run.",
              file=sys.stderr)
        return 3

    run = Path(tempfile.mkdtemp(prefix="swan_a11refr_"))
    fails = []
    try:
        for f in INPUTS:
            shutil.copy(HERE / "inputs" / f, run / f)
        shutil.copy(run / "a11refr.swn", run / "INPUT")   # as official swanrun does
        cp = subprocess.run([sys.executable, str(RUN_TOOL), "binary", "a11refr.swn",
                             "--swan-exe", exe, "--timeout", "600"],
                            cwd=run, capture_output=True, text=True, timeout=900)
        out = cp.stdout + cp.stderr
        if "No module named" in out and "pyswan" in out:
            print("MISSING DEPENDENCY: pyswan (needed by tools/run_swan.py) not "
                  "importable by this python. NOT run.", file=sys.stderr)
            return 3
        norm = (run / "norm_end").read_text() if (run / "norm_end").exists() else ""
        finished = (cp.returncode == 0 and "Status: OK" in cp.stdout
                    and "Normal end of run A11" in norm)
        if not finished:
            fails.append(f"run did not finish normally (rc={cp.returncode}, "
                         f"norm_end={norm.strip()!r}): {out[-600:]}")
        else:
            print("  OK finished: KI tool 'Status: OK', SWAN 'Normal end of run A11'")
            t = parser.parse_table(str(run / "a11ref01.tab"))
            tab = t["data"]
            ref_tab = np.loadtxt(HERE / "reference" / "a11ref01.tab")
            col = {n: tab[:, j] for j, n in enumerate(TAB_COLS)}
            wet = col["HS"] >= 0          # last point is dry (SWAN exception value -9)
            tb = parser.parse_table(str(run / "a11ref01.tbl"))
            ref_tbl = np.loadtxt(HERE / "reference" / "a11ref01.tbl", comments="%")
            ana = read_ana(HERE / "reference" / "a11refr.ana")
            hs_ana = np.interp(col["DIST"][wet], ana[:, 0], ana[:, 1])
            got = {
                "tab_rows": t["n_rows"],
                "tab_wet_rows": int(wet.sum()),
                "tab_hs_max": float(col["HS"][wet].max()),
                "tab_hs_min_wet": float(col["HS"][wet].min()),
                "tab_dir_min_wet": float(col["DIR"][wet].min()),
                "tab_tm01_mean_wet": float(col["TM01"][wet].mean()),
                "tab_max_absdiff_vs_official": float(np.abs(tab - ref_tab).max())
                if tab.shape == ref_tab.shape else 1e9,
                "tbl_rows": tb["n_rows"],
                "tbl_hs_first": float(tb["Hsig"][0]),
                "tbl_hs_last": float(tb["Hsig"][-1]),
                "tbl_tm01_last": float(tb["Tm01"][-1]),
                "tbl_max_absdiff_vs_official": float(np.abs(tb["data"] - ref_tbl).max())
                if tb["data"].shape == ref_tbl.shape else 1e9,
                "hs_max_abs_error_vs_analytical": float(np.abs(col["HS"][wet] - hs_ana).max()),
            }
            for c in EXP["numeric_checks"]:
                v = got[c["name"]]
                if abs(v - c["expected"]) > c["tol"]:
                    fails.append(f"{c['name']}: {v:.6g} vs {c['expected']}±{c['tol']}")
                else:
                    print(f"  OK {c['name']}: {v:.6g}")
    finally:
        shutil.rmtree(run, ignore_errors=True)

    if fails:
        print("FAIL:", file=sys.stderr)
        for f in fails:
            print("  -", f, file=sys.stderr)
        return 2
    print("PASS: SWAN refraction test a11refr reproduced the official reference output.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
