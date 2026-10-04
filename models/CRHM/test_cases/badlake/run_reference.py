#!/usr/bin/env python3
"""Run the CRHM 'Bad Lake' official regression project in a clean directory and
check the result against expected.json.

This is the CRHM KI's FOUNDATION test case: the canonical Bad Lake (Saskatchewan)
example from the CRHMcode distribution's own system_regression_test suite. The
inputs in inputs/ are unmodified (badlake.prj + prj/BadLake/Badlake73_76.obs; the
prj references the obs by that relative path).

Expected values are pinned to the INSTALLED crhm build (v4.7_16), which is
deterministic. The distribution's shipped expected_output was made by a different
build and differs numerically — see expected.json; it is not used as pass/fail.

Usage:
    python run_reference.py                  # auto-find crhm (or $CRHM_BIN, --crhm-bin)
Exit 0 = PASS, 2 = checks failed, 3 = crhm binary missing (reported, not skipped).
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
INPUTS = HERE / "inputs"
EXPECTED = json.loads((HERE / "expected.json").read_text())
_DEFAULT_BIN = "/mnt/disk1/Hydrocraft_server/model/crhmcode/crhmcode/build/crhm"
_TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")


def find_binary(arg):
    for cand in (arg, os.environ.get("CRHM_BIN"), shutil.which("crhm"), _DEFAULT_BIN):
        if cand and Path(cand).exists():
            return cand
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--crhm-bin", default=None)
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()

    binary = find_binary(args.crhm_bin)
    if not binary:
        print("MISSING DEPENDENCY: crhm binary not found. Build CRHMcode or set "
              "CRHM_BIN. This case was NOT run.", file=sys.stderr)
        return 3

    run = Path(tempfile.mkdtemp(prefix="crhm_badlake_"))
    # copy inputs preserving the prj/BadLake/ subpath the prj expects
    for src in INPUTS.rglob("*"):
        if src.is_file():
            dst = run / src.relative_to(INPUTS)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(src, dst)
    out = run / "badlake_output.txt"
    cp = subprocess.run([binary, "badlake.prj", "-o", "badlake_output.txt"],
                        cwd=run, capture_output=True, text=True, timeout=1200)

    fails = []
    if "End of model run" not in cp.stdout:
        fails.append(f"engine did not report 'End of model run' (rc={cp.returncode})")
    if not out.is_file():
        print("FAIL: no output produced", file=sys.stderr)
        if not args.keep:
            shutil.rmtree(run, ignore_errors=True)
        return 2

    lines = out.read_text(errors="replace").splitlines()
    exp = EXPECTED["output"]
    if len(lines) != exp["n_lines"]:
        fails.append(f"output has {len(lines)} lines, expected {exp['n_lines']}")

    data = [ln for ln in lines if _TS.match(ln)]
    if data:
        first_ts, last_ts = data[0].split("\t")[0], data[-1].split("\t")[0]
        if first_ts != EXPECTED["simulation"]["start_timestamp"]:
            fails.append(f"first timestamp {first_ts}")
        if last_ts != EXPECTED["simulation"]["end_timestamp"]:
            fails.append(f"last timestamp {last_ts}")
        for chk in EXPECTED["numeric_checks"]:
            row = data[-1] if chk["row"] == "last" else data[0]
            cells = row.split("\t")
            idx = chk["tab_field_1based"] - 1
            try:
                val = float(cells[idx])
            except (IndexError, ValueError):
                fails.append(f"{chk['name']}: cannot read field {chk['tab_field_1based']}"); continue
            if abs(val - chk["expected"]) > chk["tol"]:
                fails.append(f"{chk['name']}: got {val}, expected {chk['expected']}±{chk['tol']}")
            else:
                print(f"  OK {chk['name']}: {val} (expected {chk['expected']}±{chk['tol']})")
    else:
        fails.append("no data rows with a timestamp found")

    # informational exact-match fingerprint
    got_sha = hashlib.sha256(out.read_bytes()).hexdigest()
    print(f"  output sha256 {'MATCHES' if got_sha == exp['sha256'] else 'differs from'} the recorded "
          f"v{EXPECTED['engine_version']} baseline (informational)")

    if not args.keep:
        shutil.rmtree(run, ignore_errors=True)
    if fails:
        print("FAIL:", file=sys.stderr)
        for f in fails:
            print("  -", f, file=sys.stderr)
        return 2
    print("PASS: CRHM Bad Lake reproduced the expected results.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
