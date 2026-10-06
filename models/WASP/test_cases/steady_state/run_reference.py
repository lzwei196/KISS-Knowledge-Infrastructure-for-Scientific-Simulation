#!/usr/bin/env python3
"""Run EPA's official WASP "Steady State" example with the REAL WASP 8.5 engine and check expected.json.

Foundation case for the WASP KI. The unmodified SteadyState.wif (EPA WASP model examples,
steady-state-example.zip) is copied to a fresh temp dir and run through the KI's own
tools/run_wasp_engine.py (EPA waspccli.exe under WINE); all variables of all 10 segments are
extracted from SteadyState.BMD2 with EPA's BMD2_Extract.exe and compared with expected.json.

Exit 0 PASS, 2 run or checks failed, 3 engine/WINE/KI tool missing (nothing faked; the KI's
analytic surrogate tools/run_wasp.py is never used here).

Run tool: --run-tool -> <this KI>/tools/run_wasp_engine.py (HERE.parents[1]/tools).
Engine:   --wineprefix -> $WASP_WINEPREFIX -> tool default; --wine -> $WASP_WINE -> PATH
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
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP = json.loads((HERE / "expected.json").read_text())
DEFAULT_TOOL = HERE.parents[1] / "tools" / "run_wasp_engine.py"
WIF = "SteadyState.wif"
TOOL_BUDGET_S = 900     # passed to the tool as --timeout (engine + extraction)
WATCHDOG_S = 1100       # only for a stuck tool; it then gets SIGTERM and kills its own engine processes


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


def check_summary(summary_path):
    """Compare the tool's summary with expected.json; returns a list of failures."""
    fails = []
    try:
        s = json.loads(summary_path.read_text())
        st = s["extract"]["stats"]
        got = {
            "closed_out": 1 if s["closed_out"] else 0,
            "n_segments": s["bmd2"]["n_segments"],
            "n_variables": s["bmd2"]["n_variables"],
            "n_output_times": st["Dissolved Oxygen"]["1"]["n"],
            "known_time_function_errors": s["known_time_function_errors"],
        }
        for c in EXP["numeric_checks"]:
            if c["name"] not in got:
                got[c["name"]] = st[c["var"]][str(c["segment"])][c["stat"]]
        other_errors = s["other_error_lines"]
    except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError) as exc:
        return [f"tool summary missing or malformed: {exc!r}"]
    for c in EXP["numeric_checks"]:
        v = got[c["name"]]
        if (isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
                or abs(v - c["expected"]) > c["tol"]):
            fails.append(f"{c['name']}: {v} vs {c['expected']} ± {c['tol']}")
        else:
            print(f"  OK {c['name']}: {v:.8g}")
    if other_errors:
        fails.append(f"unexpected engine ERROR lines: {other_errors[:3]}")
    return fails


SERVER_WINEPREFIX = "/home/server/engine_builds_20261006/wasp/wineprefix"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run-tool", help=f"KI real-engine run tool (default {DEFAULT_TOOL})")
    ap.add_argument("--wineprefix", help="WINE prefix with C:\\WASP8 (else $WASP_WINEPREFIX, else tool default)")
    ap.add_argument("--wine", help="wine executable (else $WASP_WINE, else PATH)")
    ap.add_argument("--keep", action="store_true", help="keep the temp run dir")
    a = ap.parse_args()

    tool = Path(a.run_tool).resolve() if a.run_tool else DEFAULT_TOOL
    if not tool.is_file():
        print(f"MISSING DEPENDENCY: KI run tool {tool} not found. NOT run.", file=sys.stderr)
        return 3
    print(f"run tool: {tool}")

    tmp = Path(tempfile.mkdtemp(prefix="wasp_steady_state_"))
    try:
        shutil.copy2(HERE / "inputs" / WIF, tmp / WIF)
        # The KI tool's built-in default is a server path (a KISSPATH placeholder in the
        # public repo), so pass the prefix explicitly: --wineprefix, $WASP_WINEPREFIX,
        # else this server's install if it exists.
        if not (a.wineprefix or os.environ.get("WASP_WINEPREFIX")) and Path(SERVER_WINEPREFIX).is_dir():
            a.wineprefix = SERVER_WINEPREFIX
        cmd = [sys.executable, str(tool), "--wif", str(tmp / WIF), "--run-dir", str(tmp / "run"),
               "--extract-all", "--timeout", str(TOOL_BUDGET_S)]
        if a.wineprefix:
            cmd += ["--wineprefix", a.wineprefix]
        if a.wine:
            cmd += ["--wine", a.wine]
        rc, out, err = run_tool(cmd)
        print((out or "").rstrip())
        if rc == 3:
            print("MISSING DEPENDENCY: real EPA WASP engine / WINE not available:\n" + (err or "").strip()
                  + "\nNOT run.", file=sys.stderr)
            return 3
        if rc is None:
            fails = [f"run tool did not finish within {WATCHDOG_S} s (stopped): {(err or '').strip()[-400:]}"]
        elif rc != 0:
            fails = [f"run tool failed (rc={rc}): {(err or '').strip()[-800:]}"]
        else:
            fails = check_summary(tmp / "run" / "wasp_engine_summary.json")
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
    print("PASS: EPA WASP 8.5 Steady State example reproduced the expected results.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
