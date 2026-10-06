#!/usr/bin/env python3
"""Run the official ATS regression test 01_richards_steadystate / fv through the KI tool
and judge it with the official ATS regression checker.

Foundation case for the Amanzi_ATS KI. Steps:
  1. copy inputs/ (fv.xml, richards_steadystate.cfg, fv.regression.gold/) to a fresh temp dir;
  2. run ATS through the KI run tool tools/run_amanzi.py (run dir <tmp>/fv.regression,
     the same layout the official test manager uses);
  3. run the official checker (inputs/official_checker/regression_tests.py with its
     test_manager.py, unmodified) in --check-only mode: it compares the new
     checkpoint00001.h5 with the official gold file using the official tolerances of
     richards_steadystate.cfg;
  4. check expected.json: tool and checker exit codes, test count, every official
     criterion PASSED with its delta inside the official tolerance, and run facts.
Exit 0 PASS, 2 checks failed, 3 engine/dependency missing.

ATS lookup: --ats-bin -> $ATS_BIN -> server default
/home/server/engine_builds_20261006/ats/amanzi-install-master42cadd9-Release/bin/ats.
PATH is not searched (same rule as the KI tool and preflight: never pick another engine
silently). The engine found here is always passed to the KI tool with --binary, because
the tool's built-in default is a server path (a KISSPATH placeholder in the public repo).
"""
import argparse
import glob
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP = json.loads((HERE / "expected.json").read_text())
TOOL = HERE.parents[1] / "tools" / "run_amanzi.py"
_DEF = "/home/server/engine_builds_20261006/ats/amanzi-install-master42cadd9-Release/bin/ats"
CRIT = re.compile(r"^\s+(PASS|FAIL): fv : (\S+) : (\S+) (?:<=|>) (\S+) \[([^\]]*)\]")


def find_ats(arg):
    explicit = arg or os.environ.get("ATS_BIN", "").strip() or None
    cand = explicit or _DEF
    if os.sep not in cand:
        cand = shutil.which(cand) or ""
    if cand and os.path.isfile(cand) and os.access(cand, os.X_OK):
        return os.path.abspath(cand), bool(explicit)
    return None, bool(explicit)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ats-bin", help="ATS executable (default $ATS_BIN, else server build)")
    a = ap.parse_args()
    ats, explicit = find_ats(a.ats_bin)
    if not ats:
        print("MISSING DEPENDENCY: ATS executable not found (--ats-bin, $ATS_BIN, or "
              f"{_DEF}). NOT run.", file=sys.stderr)
        return 3
    dep = subprocess.run([sys.executable, "-c", "import h5py, numpy"], capture_output=True, text=True)
    if dep.returncode != 0 or not TOOL.is_file():
        print(f"MISSING DEPENDENCY: need h5py + numpy in {sys.executable} and the KI tool {TOOL}. "
              "NOT run.", file=sys.stderr)
        return 3
    ver = subprocess.run([ats, "--version"], capture_output=True, text=True).stdout.strip()
    print(f"  ats: {ats} ({ver})  [{'explicit' if explicit else 'tool default lookup'}]")

    run = Path(tempfile.mkdtemp(prefix="ats_richards_ss_fv_"))
    fails = []
    got = {}
    try:
        inp = HERE / "inputs"
        shutil.copy2(inp / "fv.xml", run / "fv.xml")
        shutil.copy2(inp / "richards_steadystate.cfg", run / "richards_steadystate.cfg")
        shutil.copytree(inp / "fv.regression.gold", run / "fv.regression.gold")
        env = {k: v for k, v in os.environ.items() if k != "ATS_SRC_DIR"}
        env["OMP_NUM_THREADS"] = "1"
        env["PYTHONDONTWRITEBYTECODE"] = "1"  # keep inputs/official_checker clean

        # 1) KI run tool
        cmd = [sys.executable, str(TOOL), "--xml_file", str(run / "fv.xml"),
               "--run_dir", str(run / "fv.regression"), "--output", str(run / "run_result.json")]
        cmd += ["--binary", ats]
        cp = subprocess.run(cmd, capture_output=True, text=True, cwd=run, env=env, timeout=600)
        got["tool_returncode"] = cp.returncode
        used = re.search(r"\[OK\] Binary found: (.+)", cp.stdout)
        print(f"  KI tool rc={cp.returncode}, binary used: {used.group(1) if used else '?'}")
        if not used or os.path.abspath(used.group(1).strip()) != ats:
            fails.append(f"KI tool did not use {ats}: {cp.stdout[-300:]} {cp.stderr[-300:]}")
        log = run / "fv.regression" / "amanzi_run.log"
        txt = log.read_text(errors="replace") if log.is_file() else ""
        it = re.findall(r"success: (\d+) nonlinear itrs", txt)
        if it:
            got["nonlinear_iterations"] = int(it[-1])
        fdir = run / "fv.regression"
        ck = [f for f in glob.glob(str(fdir / "checkpoint*.h5")) if not f.endswith("checkpoint_final.h5")]
        got["checkpoint_files"] = len(ck)

        # 2) official checker, --check-only (gives -e so it does not fall back to a dry run)
        chk = [sys.executable, str(inp / "official_checker" / "regression_tests.py"),
               "richards_steadystate.cfg", "--check-only", "-e", ats, "-t", "fv"]
        cc = subprocess.run(chk, capture_output=True, text=True, cwd=run, env=env, timeout=600)
        got["checker_returncode"] = cc.returncode
        m = re.search(r"Tests run : (\d+)", cc.stdout)
        got["checker_tests_run"] = int(m.group(1)) if m else -1
        got["checker_all_passed"] = 1 if "All tests passed." in cc.stdout else 0
        logs = sorted((run / "LOGS").glob("*.testlog"))
        tl = logs[-1].read_text(errors="replace") if logs else ""
        crit = {}
        for line in tl.splitlines():
            mm = CRIT.match(line)
            if mm:
                crit[mm.group(2)] = (mm.group(1), float(mm.group(3)), float(mm.group(4)), mm.group(5))
        print(f"  official checker rc={cc.returncode}: "
              f"{'All tests passed.' if got['checker_all_passed'] else 'NOT all passed'}")
        for c in EXP["criteria"]:
            k = c["key"]
            if k not in crit:
                fails.append(f"official criterion {k}: not reported by the checker")
                continue
            st, delta, tol, kind = crit[k]
            ok = (st == "PASS" and math.isfinite(delta) and delta <= c["official_tol"]
                  and tol == c["official_tol"] and kind == c["official_kind"])
            line = f"{k}: delta {delta:.4g} <= {tol:g} [{kind}] ({st})"
            if ok:
                print(f"  OK {line}")
            else:
                fails.append(f"official criterion {line}; expected tol {c['official_tol']} [{c['official_kind']}]")
        extra = sorted(set(crit) - {c["key"] for c in EXP["criteria"]})
        if extra:
            fails.append(f"checker reported criteria not in expected.json: {extra}")

        for c in EXP["numeric_checks"]:
            v = got.get(c["name"])
            if v is None:
                fails.append(f"{c['name']}: not produced")
            elif abs(v - c["expected"]) <= c["tol"]:
                print(f"  OK {c['name']}: {v}")
            else:
                fails.append(f"{c['name']}: {v} vs {c['expected']}+-{c['tol']}")
    except subprocess.TimeoutExpired as e:
        fails.append(f"timed out: {e.cmd[:2]}")
    finally:
        shutil.rmtree(run, ignore_errors=True)

    if fails:
        print("FAIL:", file=sys.stderr)
        for f in fails:
            print("  -", f, file=sys.stderr)
        return 2
    print("PASS: ATS official regression test richards_steadystate/fv matches the official gold "
          "within the official tolerances (run through the KI tool).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
