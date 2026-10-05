#!/usr/bin/env python3
"""Run the official EPANET tutorial network in a clean dir and check expected.json.

Foundation case for the EPANET KI. inputs/tutorial.inp is the unmodified example
from the EPANET 2.2 User Manual (Appendix C). reference/tutorial.out is the official
report excerpt that ships next to it in the same repo (also printed in the manual).

Steps: copy inputs to a fresh temp dir, run the engine through the KI's own
tools/run_epanet.py, turn the report into CSV with the KI's own
tools/parse_epanet_output.py --rpt (the same tool also reads the official excerpt),
then check expected.json and compare every number in the official excerpt.
Exit 0 PASS, 2 checks failed, 3 engine missing.

Binary lookup: --epanet-bin -> $EPANET_BIN -> `which runepanet` -> server default.
"""
import argparse, csv, json, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP = json.loads((HERE / "expected.json").read_text())
TOOLS = HERE.parents[1] / "tools"
RUN_TOOL = TOOLS / "run_epanet.py"
PARSE_TOOL = TOOLS / "parse_epanet_output.py"
OFFICIAL = HERE / "reference" / "tutorial.out"
_DEF = "/mnt/disk1/Hydrocraft_server/models/EPANET/source/repo/SRC_engines/build/src/run/runepanet"


def find_bin(arg):
    for c in (arg, os.environ.get("EPANET_BIN"), shutil.which("runepanet"), _DEF):
        if c and Path(c).is_file() and os.access(c, os.X_OK):
            return c
    return None


def num(s):
    try:
        return float(s)
    except ValueError:
        return None


def parse_with_ki_tool(rpt, csv_dir):
    """Report text -> {"node|link:<time>:<id>:<field>": value} via the KI parse tool."""
    cp = subprocess.run([sys.executable, str(PARSE_TOOL), "--rpt", str(rpt), "--csv", str(csv_dir)],
                        capture_output=True, text=True, timeout=120)
    if cp.returncode != 0:
        raise RuntimeError(f"parse_epanet_output.py failed: {cp.stdout[-300:]} {cp.stderr[-300:]}")
    vals = {}
    for kind, fields in (("node", ("demand", "head", "pressure", "quality")),
                         ("link", ("flow", "velocity", "headloss"))):
        with open(Path(csv_dir) / f"{kind}s.csv") as f:
            for r in csv.DictReader(f):
                if any(num(r[fld]) is None for fld in fields):
                    continue  # the tool also keeps column-header and page-header rows
                t = r["time"].replace(" hrs", "")
                for fld in fields:
                    vals[f"{kind}:{t}:{r[kind + '_id']}:{fld}"] = float(r[fld])
    return vals


def energy_row(text, pump="7"):
    """Pump line of the Energy Usage table -> 6 numbers."""
    m = re.search(rf"^\s*{pump}\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s*$",
                  text.split("Energy Usage:")[1].split("Demand Charge")[0], re.M)
    keys = ("usage_factor", "avg_effic", "kwh_per_mgal", "avg_kw", "peak_kw", "cost_per_day")
    return {f"energy:{pump}:{k}": float(v) for k, v in zip(keys, m.groups())}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--epanet-bin")
    a = ap.parse_args()
    binary = find_bin(a.epanet_bin)
    if not binary:
        print("MISSING DEPENDENCY: runepanet not found (set EPANET_BIN or --epanet-bin). NOT run.",
              file=sys.stderr)
        return 3

    run = Path(tempfile.mkdtemp(prefix="epanet_tutorial_"))
    fails = []
    try:
        shutil.copy(HERE / "inputs" / "tutorial.inp", run / "tutorial.inp")
        cp = subprocess.run([sys.executable, str(RUN_TOOL), "--inp", str(run / "tutorial.inp"),
                             "--rpt", str(run / "tutorial.rpt"), "--out", str(run / "tutorial.bin"),
                             "--binary", binary, "--timeout", "300"],
                            capture_output=True, text=True, timeout=400)
        rpt_text = (run / "tutorial.rpt").read_text() if (run / "tutorial.rpt").is_file() else ""
        ok_tool = cp.returncode == 0 and "[SUCCESS] EPANET completed" in cp.stdout
        ok_engine = "Analysis ended" in rpt_text and "Error" not in rpt_text
        if not (ok_tool and ok_engine):
            fails.append(f"run did not finish normally (rc={cp.returncode}, tool_success={ok_tool}, "
                         f"report 'Analysis ended'={ok_engine}): {cp.stdout[-400:]} {cp.stderr[-300:]}")
        else:
            print(f"  OK finished normally: run_epanet.py rc=0 [SUCCESS], report 'Analysis ended'")

        if not fails:
            got = parse_with_ki_tool(run / "tutorial.rpt", run / "csv_run")
            got.update(energy_row(rpt_text))
            got["n_node_report_periods"] = len(re.findall(r"Node Results at", rpt_text))
            got["n_link_report_periods"] = len(re.findall(r"Link Results at", rpt_text))

            # 1) the chosen checks in expected.json
            for c in EXP["numeric_checks"]:
                v = got.get(c["key"])
                if v is None:
                    fails.append(f"{c['name']}: value {c['key']} not found in run output")
                elif abs(v - c["expected"]) > c["tol"] + 1e-9:
                    fails.append(f"{c['name']}: {v} vs {c['expected']}±{c['tol']}")
                else:
                    print(f"  OK {c['name']}: {v:g} (expected {c['expected']}±{c['tol']})")

            # 2) every number in the official report excerpt
            off_text = OFFICIAL.read_text()
            off = parse_with_ki_tool(OFFICIAL, run / "csv_official")
            off.update(energy_row(off_text))
            tol = EXP["official_excerpt_check"]["tol"]
            bad = [f"{k}: run {got.get(k)} vs official {v}" for k, v in off.items()
                   if got.get(k) is None or abs(got[k] - v) > tol + 1e-9]
            n_exp = EXP["official_excerpt_check"]["n_values"]
            if len(off) != n_exp:
                fails.append(f"official excerpt gave {len(off)} values, expected {n_exp}")
            if bad:
                fails.append(f"{len(bad)} of {len(off)} official values differ: " + "; ".join(bad[:10]))
            else:
                print(f"  OK all {len(off)} numbers in reference/tutorial.out match the run (tol {tol})")
    finally:
        shutil.rmtree(run, ignore_errors=True)

    if fails:
        print("FAIL:", file=sys.stderr)
        for f in fails:
            print("  -", f, file=sys.stderr)
        return 2
    print("PASS: EPANET tutorial network reproduced the official reference results.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
