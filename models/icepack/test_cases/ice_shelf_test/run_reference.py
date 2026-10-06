#!/usr/bin/env python3
"""Run icepack's own official ice-shelf test (test/ice_shelf_test.py) and check its results.

Foundation case for the icepack KI. Steps:
  1. copy inputs/ice_shelf_test.py (unmodified, icepack master c9a29780) to a fresh temp dir;
  2. run it with pytest using a Python that has firedrake + icepack + pytest;
     the test file carries the official asserted limits (mesh-convergence slope of the
     diagnostic solver against the exact Greve & Blatter ice-shelf solution);
  3. read each printed convergence slope from the JUnit report and check it against the
     official limit AND the value recorded on this server (expected.json).
Exit 0 PASS, 2 checks failed, 3 engine/dependency missing.

Python lookup (same order as the KI preflight_check.py): --python -> $ICEPACK_PYTHON ->
server default /home/server/engine_builds_20261006/firedrake/venv/bin/python.
An explicit choice is used as-is (no fallback to another interpreter).
The KI run tool is not used: it cannot drive this test (see README "Known KI gaps").
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP = json.loads((HERE / "expected.json").read_text())
_DEF = "/home/server/engine_builds_20261006/firedrake/venv/bin/python"
DEPS = ("import firedrake, icepack, pytest, importlib.metadata as m; "
        "print(m.version('icepack'), m.version('firedrake'))")
THREADS = {k: "1" for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")}
SLOPE = re.compile(r"log\(error\) ~= (\S+) \* log\(dx\)")


def find_python(arg):
    explicit = arg or os.environ.get("ICEPACK_PYTHON", "").strip()
    # explicit choice is used as-is (no fallback), else the server default
    for c in [explicit or _DEF]:
        if not Path(c).is_file():
            continue
        cp = subprocess.run([c, "-c", DEPS], capture_output=True, text=True,
                            cwd=tempfile.gettempdir(), env={**os.environ, **THREADS})
        if cp.returncode == 0:
            return c, cp.stdout.strip().splitlines()[-1]
    return None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--python", help="Python with firedrake + icepack + pytest")
    a = ap.parse_args()
    py, ver = find_python(a.python)
    if not py:
        print("MISSING DEPENDENCY: a python with firedrake, icepack and pytest not found "
              "(set ICEPACK_PYTHON or --python). NOT run.", file=sys.stderr)
        return 3
    print(f"  python: {py}  (icepack, firedrake) = {ver}")

    run = Path(tempfile.mkdtemp(prefix="icepack_ice_shelf_"))
    fails = []
    try:
        shutil.copy2(HERE / "inputs" / "ice_shelf_test.py", run / "ice_shelf_test.py")
        junit = run / "junit.xml"
        args = [py, "-m", "pytest", "-p", "no:cacheprovider", "-q", "ice_shelf_test.py",
                f"--junitxml={junit}", "-o", "junit_logging=system-out"]
        cp = subprocess.run(args, capture_output=True, text=True, cwd=run,
                            env={**os.environ, **THREADS}, timeout=1500)
        tail = [l for l in cp.stdout.splitlines() if re.search(r"\d+ (passed|failed|error)", l)][-1:]
        print(f"  pytest rc={cp.returncode}: {tail[0] if tail else ''}")
        if not junit.is_file():
            fails.append(f"pytest wrote no report (rc={cp.returncode}): {cp.stderr[-400:]}")
            raise RuntimeError
        r = ET.parse(junit).getroot()
        ts = r if r.tag == "testsuite" else r.find("testsuite")
        got = {"pytest_returncode": cp.returncode, "pytest_tests": int(ts.get("tests")),
               "pytest_failures": int(ts.get("failures")), "pytest_errors": int(ts.get("errors")),
               "pytest_skipped": int(ts.get("skipped"))}
        bad = []
        for tc in r.iter("testcase"):
            name = tc.get("name")
            if any(ch.tag in ("failure", "error", "skipped") for ch in tc):
                bad.append(name)
            out = "".join((so.text or "") for so in tc.iter("system-out"))
            slopes = [float(x) for x in SLOPE.findall(out)]
            if name.startswith("test_diagnostic_solver_convergence["):
                solver = name.split("[", 1)[1].rstrip("]")
                for deg, s in enumerate(slopes, start=1):
                    got[f"slope_{solver}_degree{deg}"] = s
            elif name == "test_diagnostic_solver_parameterization":
                for s in slopes:
                    got["slope_parameterization_degree2"] = s
            elif name == "test_diagnostic_solver_side_friction":
                got["side_friction_passed"] = 0 if name in bad else 1
        if bad:
            fails.append("official tests not passed: " + ", ".join(bad))

        for c in EXP["numeric_checks"]:
            v = got.get(c["name"])
            if v is None:
                fails.append(f"{c['name']}: not produced")
                continue
            ok = abs(v - c["expected"]) <= c["tol"]
            lim = ""
            if "official_min" in c:
                ok = ok and v > c["official_min"]
                lim = f" (> official {c['official_min']})"
            if ok:
                print(f"  OK {c['name']}: {v:.6g}{lim}")
            else:
                fails.append(f"{c['name']}: {v:.6g} vs {c['expected']}+-{c['tol']}{lim}")
    except RuntimeError:
        pass
    except subprocess.TimeoutExpired:
        fails.append("pytest timed out after 1500 s")
    finally:
        shutil.rmtree(run, ignore_errors=True)

    if fails:
        print("FAIL:", file=sys.stderr)
        for f in fails:
            print("  -", f, file=sys.stderr)
        return 2
    print("PASS: icepack official ice_shelf_test reproduced the expected results.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
