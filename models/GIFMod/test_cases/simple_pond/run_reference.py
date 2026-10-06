#!/usr/bin/env python3
"""Run GIFMod's official Simple_pond wizard template (30 days) with the real engine and check expected.json.

Foundation case for the GIFMod KI. The unmodified upstream template inputs/Simple_pond.wiz
(USEPA/GIFMod commit 2a31475, bindata/templates/) and our 4 wizard answers
(inputs/wizard_answers.json) are copied to a fresh temp dir and run through the KI's own
tools/run_gifmod_engine.py, which drives the PATCHED-FORK headless GIFMod (see README and
gifmod_patches.diff). Exit 0 PASS, 2 run or checks failed, 3 engine/KI tool missing.

Run tool: --run-tool -> <this KI>/tools/run_gifmod_engine.py (HERE.parents[1]/tools).
Engine:   --binary / --wrapper -> $GIFMOD_BINARY / $GIFMOD_HEADLESS -> tool's server default
          (passed through to the run tool, which owns the lookup).
"""
import argparse
import json
import math
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP = json.loads((HERE / "expected.json").read_text())
DEFAULT_TOOL = HERE.parents[1] / "tools" / "run_gifmod_engine.py"
ANSWER_KEYS = ("project_start_date", "project_end_date", "ini_Depth", "Area")
TOOL_BUDGET_S = 600     # passed to the tool as --timeout
WATCHDOG_S = 800        # only for a stuck tool; it then gets SIGTERM and kills its engine by PID


def run_tool(cmd):
    """Run the KI tool; returns (returncode or None if stopped by the watchdog, stdout, stderr)."""
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        out, err = p.communicate(timeout=WATCHDOG_S)
        return p.returncode, out, err
    except subprocess.TimeoutExpired:
        p.send_signal(signal.SIGTERM)
        try:
            out, err = p.communicate(timeout=90)
        except subprocess.TimeoutExpired:
            p.kill()
            out, err = p.communicate()
        return None, out, err


def _num(x):
    """A finite, non-boolean real number, else ValueError (so NaN can never hide inside max/abs)."""
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x):
        raise ValueError(f"not a finite number: {x!r}")
    return x


def _absmax(rec):
    return max(abs(_num(rec["min"])), abs(_num(rec["max"])))


def check_summary(summary_path):
    """Compare the tool's summary with expected.json; returns a list of failures."""
    fails = []
    try:
        s = json.loads(summary_path.read_text())
        st = s["stats"]["experiment1"]
        h = st["hydro"]
        wq = st.get("wq", {})
        mb = st.get("mass_balance", {})
        if not (isinstance(h, dict) and isinstance(wq, dict) and isinstance(mb, dict)
                and all(isinstance(v, dict) for v in list(h.values()) + list(wq.values()) + list(mb.values()))):
            return ["tool summary malformed: stats families are not mappings of per-variable records"]
        if len(wq) != 8:
            fails.append(f"expected 8 water-quality series, got {len(wq)}")
        if "S_Pond" not in mb:
            return fails + ["mass-balance series S_Pond missing"]
        got = {
            "finished": 1 if s["experiments_finished"] == ["experiment1"] and not s["experiments_failed"] else 0,
            "model_check_errors": _num(s["check_errors"]),
            "model_check_warnings": _num(s["check_warnings"]),
            "hydro_records": _num(h["S_Pond"]["n"]),
            "t_first": _num(h["S_Pond"]["t_first"]),
            "t_last": _num(h["S_Pond"]["t_last"]),
            "storage_min": _num(h["S_Pond"]["min"]),
            "storage_max": _num(h["S_Pond"]["max"]),
            "head_min": _num(h["H_Pond"]["min"]),
            "head_max": _num(h["H_Pond"]["max"]),
            "evaporation_max_abs": _absmax(h["E_Pond"]),
            "wq_max_abs_all": max((_absmax(v) for v in wq.values()), default=None),
            "mb_records": _num(mb["S_Pond"]["n"]),
            "mb_max_abs": _absmax(mb["S_Pond"]),
        }
    except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError) as exc:
        return fails + [f"tool summary missing or malformed: {exc!r}"]
    for c in EXP["numeric_checks"]:
        v = got[c["name"]]
        if (isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
                or abs(v - c["expected"]) > c["tol"]):
            fails.append(f"{c['name']}: {v} vs {c['expected']} ± {c['tol']}")
        else:
            print(f"  OK {c['name']}: {v:.10g}")
    return fails


SERVER_WRAPPER = "/home/server/engine_builds_20261006/gifmod/install/gifmod_headless.sh"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run-tool", help=f"KI real-engine run tool (default {DEFAULT_TOOL})")
    ap.add_argument("--binary", help="patched headless GIFMod binary (passed to the run tool)")
    ap.add_argument("--wrapper", help="gifmod_headless.sh-style wrapper (passed to the run tool)")
    ap.add_argument("--keep", action="store_true", help="keep the temp run dir")
    a = ap.parse_args()

    tool = Path(a.run_tool).resolve() if a.run_tool else DEFAULT_TOOL
    if not tool.is_file():
        print(f"MISSING DEPENDENCY: KI run tool {tool} not found. NOT run.", file=sys.stderr)
        return 3
    print(f"run tool: {tool}")
    answers = json.loads((HERE / "inputs" / "wizard_answers.json").read_text())

    tmp = Path(tempfile.mkdtemp(prefix="gifmod_simple_pond_"))
    try:
        shutil.copy2(HERE / "inputs" / "Simple_pond.wiz", tmp / "Simple_pond.wiz")
        # The KI tool's built-in default is a server path (a KISSPATH placeholder in the
        # public repo), so pass the wrapper explicitly: --wrapper / --binary, else this
        # server's patched build if it exists.
        if not (a.wrapper or a.binary) and Path(SERVER_WRAPPER).is_file():
            a.wrapper = SERVER_WRAPPER
        cmd = [sys.executable, str(tool), "--wizard", str(tmp / "Simple_pond.wiz"),
               "--run-dir", str(tmp / "run"), "--timeout", str(TOOL_BUDGET_S)]
        for k in ANSWER_KEYS:
            cmd += ["--param", f"{k}={answers[k]}"]
        if a.binary:
            cmd += ["--binary", a.binary]
        if a.wrapper:
            cmd += ["--wrapper", a.wrapper]
        rc, out, err = run_tool(cmd)
        print((out or "").rstrip())
        if rc == 3:
            print("MISSING DEPENDENCY: patched headless GIFMod engine not available:\n" + (err or "").strip()
                  + "\nNOT run.", file=sys.stderr)
            return 3
        if rc is None:
            fails = [f"run tool did not finish within {WATCHDOG_S} s (stopped): {(err or '').strip()[-400:]}"]
        elif rc != 0:
            fails = [f"run tool failed (rc={rc}): {(err or '').strip()[-800:]}"]
        else:
            fails = check_summary(tmp / "run" / "gifmod_engine_summary.json")
    finally:
        if a.keep:
            print(f"kept: {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)

    if fails:
        print("FAIL:", file=sys.stderr)
        for f in fails:
            print("  -", f, file=sys.stderr)
        return 2
    print("PASS: GIFMod Simple_pond (official template, patched-fork engine) reproduced the expected results.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
