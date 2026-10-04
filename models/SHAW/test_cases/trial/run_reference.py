#!/usr/bin/env python3
"""Run the SHAW 3.0.3 official 'Trial' test case in a clean directory and check
the result against expected.json.

This is the KI's FOUNDATION test case: an authentic, complete example that ships
with the SHAW distribution (inputs/ are the real Trial.* files, unmodified). It
proves the engine + this KI's I/O contract actually run end-to-end.

Usage:
    python run_reference.py                 # auto-find the shaw303 binary
    python run_reference.py --shaw-bin PATH # point at a specific binary
    SHAW_BIN=/path/to/shaw303 python run_reference.py

It copies inputs/ into a fresh temp directory, runs
    printf 'Trial.303.inp\\n\\n' | shaw303
there, then validates the outputs. Exit code 0 = PASS, 2 = checks failed,
3 = engine/dependency missing (reported explicitly, never silently skipped).
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
INPUTS = HERE / "inputs"
EXPECTED = json.loads((HERE / "expected.json").read_text())

# default install on the build server; override with --shaw-bin or $SHAW_BIN
_DEFAULT_BIN = "/mnt/disk1/Hydrocraft_server/model/shaw/shaw303"


def find_binary(arg):
    for cand in (arg, os.environ.get("SHAW_BIN"), shutil.which("shaw303"), _DEFAULT_BIN):
        if cand and Path(cand).exists():
            return cand
    return None


def _data_rows(path):
    rows = []
    for ln in path.read_text().splitlines():
        p = ln.split()
        if len(p) >= 3 and p[0].isdigit() and p[2].isdigit():
            rows.append(p)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shaw-bin", default=None)
    ap.add_argument("--keep", action="store_true", help="keep the run directory")
    args = ap.parse_args()

    binary = find_binary(args.shaw_bin)
    if not binary:
        print("MISSING DEPENDENCY: shaw303 binary not found. Build it from the SHAW "
              "3.0.3 distribution (Shaw303.zip / compile.sh) or set SHAW_BIN. "
              "This case was NOT run.", file=sys.stderr)
        return 3

    run = Path(tempfile.mkdtemp(prefix="shaw_trial_"))
    for f in INPUTS.iterdir():
        shutil.copy(f, run / f.name)
    cp = subprocess.run([binary], cwd=run, input="Trial.303.inp\n\n",
                        capture_output=True, text=True, timeout=600)
    fails = []
    if "Run Complete" not in cp.stdout:
        fails.append(f"engine did not report 'Run Complete' (rc={cp.returncode})")

    # outputs present
    for name in EXPECTED["outputs_present"]:
        if not (run / name).is_file():
            fails.append(f"missing output file {name}")

    # deterministic line counts
    for name, n in EXPECTED["output_line_counts"].items():
        fp = run / name
        if fp.is_file():
            got = len(fp.read_text().splitlines())
            if got != n:
                fails.append(f"{name}: {got} lines, expected {n}")

    # numeric checks against the authentic final-day values
    # 0-based column positions after splitting a data row on whitespace.
    # water.out: DAY HR YR PRECIP SNOWMELT INTRCP ET TRANSP CANOPY SNOW RESIDUE
    #            SOIL PERC RUNOFF PONDED OUTFLOW SINK CUM.ET ERROR
    # frost.out: DAY HR YR THAW FROST SNOW SWE <ice nodes...>
    col_index = {
        ("water.out", "CUM. ET"): 17, ("water.out", "ERROR"): 18,
        ("frost.out", "SNOW"): 5, ("frost.out", "SWE"): 6,
    }
    for chk in EXPECTED["numeric_checks"]:
        fp = run / chk["file"]
        if not fp.is_file():
            fails.append(f"{chk['name']}: {chk['file']} missing"); continue
        rows = [r for r in _data_rows(fp) if int(r[0]) == chk["day"]]
        if "hour" in chk:
            rows = [r for r in rows if int(r[1]) == chk["hour"]]
        if not rows:
            fails.append(f"{chk['name']}: no row for day {chk['day']}"); continue
        idx = col_index[(chk["file"], chk["column"])]
        try:
            val = float(rows[-1][idx])
        except (IndexError, ValueError) as e:
            fails.append(f"{chk['name']}: cannot read column ({e})"); continue
        if abs(val - chk["expected"]) > chk["tol"]:
            fails.append(f"{chk['name']}: got {val}, expected {chk['expected']}±{chk['tol']}")
        else:
            print(f"  OK {chk['name']}: {val} (expected {chk['expected']}±{chk['tol']})")

    if not args.keep:
        shutil.rmtree(run, ignore_errors=True)
    else:
        print(f"run dir kept: {run}")

    if fails:
        print("FAIL:", file=sys.stderr)
        for f in fails:
            print("  -", f, file=sys.stderr)
        return 2
    print("PASS: SHAW Trial reproduced the expected results.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
