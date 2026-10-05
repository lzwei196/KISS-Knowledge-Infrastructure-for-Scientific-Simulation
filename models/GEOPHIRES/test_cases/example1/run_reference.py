#!/usr/bin/env python3
"""Run the official GEOPHIRES-X example1 in a clean temp dir and check expected.json.

Foundation case for the GEOPHIRES KI. The unmodified official input inputs/example1.txt
is run through the KI's own tools/run_geophires.py. The new .out is then compared with
the official reference/example1.out the same way the GEOPHIRES-X test suite does it
(GeophiresXResult on both, drop metadata, exact dict equality), and the numeric checks
in expected.json are read from the new run. The KI tools/parse_geophires_output.py is
also run and must agree with the official parser on four headline numbers.

Exit 0 PASS, 2 checks failed, 3 engine missing.
Engine lookup (a Python that can import geophires_x and geophires_x_client):
--geophires-python -> $GEOPHIRES_PYTHON -> `which python3` -> server default venv.
"""
import argparse, json, os, shutil, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP = json.loads((HERE / "expected.json").read_text())
TOOLS = HERE.parents[1] / "tools"
RUN_TOOL = TOOLS / "run_geophires.py"
PARSE_TOOL = TOOLS / "parse_geophires_output.py"
_DEF = "/home/server/knowledge-dissection-toolkit/auto_dissect/_work/GEOPHIRES/venv/bin/python"

# Runs inside the engine Python: official parser on both files -> JSON on stdout.
_COMPARE = r"""
import json, math, sys
from geophires_x_client import GeophiresXResult
def load(p):
    r = GeophiresXResult(p).result
    meta = r.get('Simulation Metadata') or {}
    r.pop('metadata', None); r.pop('Simulation Metadata', None)
    irr = (r.get('ECONOMIC PARAMETERS') or {}).get('After-tax IRR')
    if isinstance(irr, dict) and isinstance(irr.get('value'), float) and math.isnan(irr['value']):
        irr['value'] = 'NaN'   # same NaN fix as the suite's _sanitize_nan
    return r, meta
new, meta = load(sys.argv[1]); ref, _ = load(sys.argv[2])
diff = sorted(k for k in set(new) | set(ref) if new.get(k) != ref.get(k))
print(json.dumps({"equal": new == ref, "diff_sections": diff, "new": new,
                  "version": str((meta.get('GEOPHIRES Version') or {}).get('value', '?'))}))
"""


def engine_ok(py):
    if not py or not Path(py).exists():
        return False
    r = subprocess.run([py, "-c", "import geophires_x, geophires_x_client"],
                       capture_output=True, timeout=120)
    return r.returncode == 0


def get_value(res, c):
    if "path" in c:
        sec, key = c["path"]
        return res[sec][key]["value"]
    table = res[c["profile"]]
    rows = table[1:]
    if c["stat"] == "n_years":
        return len(rows)
    col = table[0].index(c["column"])
    return rows[-1][col]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--geophires-python")
    a = ap.parse_args()
    cands = (a.geophires_python, os.environ.get("GEOPHIRES_PYTHON"), shutil.which("python3"), _DEF)
    py = next((c for c in cands if engine_ok(c)), None)
    if not py:
        print("MISSING DEPENDENCY: a Python with GEOPHIRES-X (geophires_x + geophires_x_client) "
              "not found (set GEOPHIRES_PYTHON or --geophires-python). NOT run.", file=sys.stderr)
        return 3

    run = Path(tempfile.mkdtemp(prefix="geophires_ex1_"))
    fails = []
    try:
        shutil.copy(HERE / "inputs" / "example1.txt", run / "example1.txt")
        # KI run tool, started with the engine Python so it runs `<py> -m geophires_x`.
        cp = subprocess.run([py, str(RUN_TOOL), "--input", str(run / "example1.txt"),
                             "--output", str(run / "example1.out"), "--timeout", "600"],
                            capture_output=True, text=True, timeout=900, cwd=run)
        try:
            info = json.loads(cp.stdout[cp.stdout.index("{"):])
        except ValueError:
            info = {}
        out = run / "example1.out"
        ok_run = (cp.returncode == 0 and info.get("status") == "success" and out.is_file()
                  and "***CASE REPORT***" in out.read_text()[:300])
        if not ok_run:
            fails.append(f"run failed (rc={cp.returncode}, status={info.get('status')}): "
                         f"{(info.get('stderr') or cp.stderr)[-400:]}")
        else:
            print(f"  ran GEOPHIRES via tools/run_geophires.py ({info.get('elapsed_seconds')} s)")
            print("  OK finished normally: rc 0, status success, CASE REPORT written")

            cmp_ = subprocess.run([py, "-c", _COMPARE, str(out), str(HERE / "reference" / "example1.out")],
                                  capture_output=True, text=True, timeout=300)
            if cmp_.returncode != 0:
                fails.append(f"official result parser failed: {cmp_.stderr[-400:]}")
            else:
                res = json.loads(cmp_.stdout)
                print(f"  engine: GEOPHIRES-X {res['version']}")
                if res["equal"]:
                    print("  OK official comparison: result equals reference/example1.out exactly")
                else:
                    fails.append(f"official comparison: sections differ from reference: {res['diff_sections']}")
                new = res["new"]
                for c in EXP["numeric_checks"]:
                    v = get_value(new, c)
                    if abs(v - c["expected"]) > c["tol"]:
                        fails.append(f"{c['name']}: {v} vs {c['expected']}+-{c['tol']}")
                    else:
                        print(f"  OK {c['name']}: {v}")

                # KI parser cross-check
                kj = run / "ki_parse.json"
                kp = subprocess.run([py, str(PARSE_TOOL), "--input", str(out), "--json", str(kj)],
                                    capture_output=True, text=True, timeout=300, cwd=run)
                if kp.returncode != 0 or not kj.is_file():
                    fails.append(f"KI parse tool failed (rc={kp.returncode}): {kp.stderr[-300:]}")
                else:
                    kd = json.loads(kj.read_text())
                    pairs = [("summary", "SUMMARY OF RESULTS", "Average Net Electricity Production"),
                             ("summary", "SUMMARY OF RESULTS", "Electricity breakeven price"),
                             ("economic_parameters", "ECONOMIC PARAMETERS", "Project NPV"),
                             ("economic_parameters", "ECONOMIC PARAMETERS", "Project IRR")]
                    bad = [k for ks, sec, k in pairs
                           if (kd.get(ks, {}).get(k) or {}).get("value") != new[sec][k]["value"]]
                    if bad:
                        fails.append(f"KI parse tool disagrees with official parser on: {bad}")
                    else:
                        print("  OK KI parse tool agrees on net power, LCOE, NPV, IRR")
    finally:
        shutil.rmtree(run, ignore_errors=True)

    if fails:
        print("FAIL:", file=sys.stderr)
        for f in fails:
            print("  -", f, file=sys.stderr)
        return 2
    print("PASS: GEOPHIRES-X example1 reproduced the official expected results.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
