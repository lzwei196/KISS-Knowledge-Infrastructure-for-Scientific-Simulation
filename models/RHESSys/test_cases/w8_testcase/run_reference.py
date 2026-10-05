#!/usr/bin/env python3
"""Run the official RHESSys W8 test case (Testing/ folder of the RHESSys git) and check expected.json.

Foundation case for the RHESSys KI. It runs the exact command from the official
Testing/TestCase.Rmd (W8 catchment, HJ Andrews, 1988-10-01 to 2000-10-01, legacy
basin output -b, growth mode -g) through the KI's own tools/run_rhessys.py, then:
  * checks numbers in out/test_basin.daily and out/test_grow_basin.daily,
  * runs RHESSys's own water balance test (rhessys/test/rhessystest.py, ZERO = 1e-5),
  * prints (for information only) how far the run is from the official base output
    reference/base_basin_daily.csv.
Exit 0 PASS, 2 checks failed, 3 engine missing.

Binary lookup: --rhessys-bin -> $RHESSYS_BIN -> `which rhessys7.4` -> server default.
"""
import argparse, json, os, shutil, subprocess, sys, tempfile
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
EXP = json.loads((HERE / "expected.json").read_text())
RUN_TOOL = HERE.parents[1] / "tools" / "run_rhessys.py"
_DEF = ("/home/server/knowledge-dissection-toolkit/auto_dissect/_work/RHESSys/source/repo/"
        "rhessys/rhessys7.4")
ZERO = 1e-5  # rhessys/test/rhessystest.py


def find_bin(arg):
    for c in (arg, os.environ.get("RHESSYS_BIN"), shutil.which("rhessys7.4"), _DEF):
        if c and Path(c).is_file() and os.access(c, os.X_OK):
            return c
    return None


def read_table(fp):
    return np.genfromtxt(fp, names=True)


def moving_average(a, n=3):  # same as rhessystest.movingAverage
    ret = np.cumsum(a, dtype=float)
    return (ret[n - 1:] - ret[:1 - n]) / n


def water_balance_max3(d):
    """RHESSys's own WaterBalanceTest (rhessys/test/rhessystest.py), returns max 3-day mean |wb|."""
    dif = lambda a: np.insert(np.diff(a), 0, 0)
    sd = d["sat_def"] - d["rz_storage"] - d["unsat_stor"]
    et = d["evap"] + d["trans"]
    wb = (d["precip"] - d["streamflow"] - et - dif(d["detention_store"]) - dif(d["canopy_store"])
          - dif(d["litter_store"]) - dif(d["snowpack"]) + dif(sd) - dif(d["gwstorage"]))
    return float(moving_average(np.abs(wb), 3).max())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rhessys-bin")
    ap.add_argument("--keep", action="store_true", help="keep the temp run dir")
    a = ap.parse_args()
    binary = find_bin(a.rhessys_bin)
    if not binary:
        print("MISSING DEPENDENCY: rhessys7.4 binary not found (set RHESSYS_BIN or "
              "--rhessys-bin). NOT run.", file=sys.stderr)
        return 3

    run = Path(tempfile.mkdtemp(prefix="rhessys_w8_"))
    shutil.copytree(HERE / "inputs", run, dirs_exist_ok=True)
    (run / "out").mkdir(exist_ok=True)
    # Official command (TestCase.Rmd): -t tec -w world -whdr hdr -r flow -pre out/test
    #   -s 0.355794 651.390265 -sv 0.355794 651.390265 -svalt 1.083102 1.193924
    #   -gw 0.116316 0.916922 -st 1988 10 1 1 -ed 2000 10 1 1 -b -g
    cmd = [sys.executable, str(RUN_TOOL), "--binary", binary,
           "--worldfile", "worldfiles/w8TC.world", "--worldhdr", "worldfiles/w8TC.hdr",
           "--tecfile", "tecfiles/tec.test", "--flowtable", "flowtables/w8TC.flow",
           "--prefix", "out/test", "--start", "1988 10 1 1", "--end", "2000 10 1 1",
           "--basin", "--grow",
           "--sensitivity", "0.355794", "651.390265",
           "--sensitivity-vert", "0.355794", "651.390265",
           "--sensitivity-vert-alt", "1.083102", "1.193924",
           "--groundwater", "0.116316", "0.916922", "--timeout", "1200"]
    cp = subprocess.run(cmd, cwd=run, capture_output=True, text=True, timeout=1500)
    print("\n".join(cp.stdout.strip().splitlines()[:1]))
    fails = []
    if cp.returncode != 0:
        fails.append(f"run_rhessys.py rc={cp.returncode}: {cp.stdout[-600:]} {cp.stderr[-600:]}")
    elif "time cost" not in cp.stdout:
        fails.append("RHESSys did not print its end line 'time cost = ...'")
    else:
        print("  OK finished normally (rc=0, RHESSys printed 'time cost')")

    got = {}
    if not fails:
        b = read_table(run / "out" / "test_basin.daily")
        g = read_table(run / "out" / "test_grow_basin.daily")
        date = lambda d, i: f"{int(d['year'][i]):04d}{int(d['month'][i]):02d}{int(d['day'][i]):02d}"
        got = {
            "n_days_basin": len(b), "n_days_grow": len(g),
            "first_date": int(date(b, 0)), "last_date": int(date(b, -1)),
            "precip_sum_mm": float(b["precip"].sum()),
            "streamflow_sum_mm": float(b["streamflow"].sum()),
            "streamflow_max_mm": float(b["streamflow"].max()),
            "et_sum_mm": float((b["evap"] + b["trans"]).sum()),
            "sat_def_mean_mm": float(b["sat_def"].mean()),
            "snowpack_max_mm": float(b["snowpack"].max()),
            "lai_mean": float(b["lai"].mean()),
            "plantc_final": float(g["plantc"][-1]),
            "soilc_final": float(g["soilc"][-1]),
            "litrc_final": float(g["litrc"][-1]),
            "water_balance_max3day_abs_mm": water_balance_max3(b),
        }
        for c in EXP["numeric_checks"]:
            v = got[c["name"]]
            if abs(v - c["expected"]) > c["tol"]:
                fails.append(f"{c['name']}: {v:.9g} vs {c['expected']} +- {c['tol']}")
            else:
                print(f"  OK {c['name']}: {v:.9g}")
        if got["water_balance_max3day_abs_mm"] < ZERO:
            print(f"  OK RHESSys water balance test: max 3-day mean |wb| < {ZERO}")
        else:
            fails.append("RHESSys water balance test failed (max 3-day mean |wb| >= 1e-5)")

        # Information only: compare with the official base output (filter CSV, metres).
        ref = np.genfromtxt(HERE / "reference" / "base_basin_daily.csv", delimiter=",", names=True)
        print("  info: % difference of means vs official reference/base_basin_daily.csv:")
        for rc, lc, f in (("streamflow", "streamflow", 1e-3), ("sat_deficit", "sat_def", 1e-3),
                          ("rz_storage", "rz_storage", 1e-3), ("epvproj_lai", "lai", 1.0),
                          ("snowpackwater_equivalent_depth", "snowpack", 1e-3)):
            x, y = ref[rc].mean(), (b[lc] * f).mean()
            print(f"      {rc:32s} base={x:.6g} run={y:.6g} diff={(y - x) / x * 100:+.2f}%")

    if a.keep:
        print("run dir kept:", run)
    else:
        shutil.rmtree(run, ignore_errors=True)
    if os.environ.get("RHESSYS_W8_PRINT_JSON"):
        print(json.dumps(got, indent=1))
    if fails:
        print("FAIL:", file=sys.stderr)
        for f in fails:
            print("  -", f, file=sys.stderr)
        return 2
    print("PASS: RHESSys W8 official test case reproduced the expected results.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
