#!/usr/bin/env python3
"""Run HEC's official "Mixed Flow Regime Channel" steady example and check expected.json.

Foundation case for the HEC_RAS KI. The run goes through the KI's own tools/run_hecras.py
(real RasSteady.exe under WINE); output is read with the KI's tools/parse_output_hecras.py
and compared with the observed water surface in the official MIXED.f01 by the KI's
tools/validate_hecras.py. Exit 0 PASS, 2 checks failed, 3 engine/dependency missing.

RasSteady.exe lookup: --rassteady-bin -> $RASSTEADY_BIN -> which RasSteady.exe -> server
default. WINE prefix: $WINEPREFIX, else the part of the binary path before /drive_c/.
"""
import argparse, json, os, shutil, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP = json.loads((HERE / "expected.json").read_text())
TOOLS = HERE.parents[1] / "tools"
RUN_TOOL = TOOLS / "run_hecras.py"
_DEF = "/home/server/.wine/drive_c/Program Files (x86)/HEC/HEC-RAS/6.7 Beta 5/x64/RasSteady.exe"
INPUTS = ("MIXED.PRJ", "MIXED.P01", "MIXED.f01", "MIXED.g01", "MIXED.g01.hdf",
          "MIXED.r01", "MIXED.rasmap")

# The repo copy of tools/_hecras_env.py holds an install-time placeholder for the
# HEC-RAS path and has no flag for it, so we point its BINARIES/WINEPREFIX at the
# binary found here, then call run_hecras.main() unchanged (see README, KI gaps).
_LAUNCH = r"""
import sys
sys.dont_write_bytecode = True
tools, binary, prefix = sys.argv[1:4]
sys.path.insert(0, tools)
import _hecras_env as e
e.BINARIES["steady"] = binary
e.WINEPREFIX = prefix
import run_hecras
sys.argv = ["run_hecras.py"] + sys.argv[4:]
run_hecras.main()
"""


def summarise(hdf, flow_file):
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(TOOLS))
    import parse_output_hecras as pp
    import validate_hecras as vv
    parsed = pp.parse(str(hdf))
    recs = parsed["records"]
    profs = sorted({r["profile"] for r in recs})
    by = {p: [r for r in recs if r["profile"] == p] for p in profs}
    pf1, pf2 = by["PF 1"], by["PF 2"]
    ws1 = [r["ws"] for r in pf1]
    ws2 = [r["ws"] for r in pf2]
    sup1 = [r for r in pf1 if r.get("regime") == "supercritical"]
    sup2 = [r for r in pf2 if r.get("regime") == "supercritical"]
    first_sub1 = next(i for i, r in enumerate(pf1) if r.get("regime") != "supercritical")
    m = vv.validate(str(hdf), str(flow_file), profile_index=0)
    return {
        "n_profiles": len(profs),
        "n_cross_sections": len(pf1),
        "pf1_flow_all_xs": min(r["q"] for r in pf1) if len({r["q"] for r in pf1}) == 1 else -1,
        "pf2_flow_all_xs": min(r["q"] for r in pf2) if len({r["q"] for r in pf2}) == 1 else -1,
        "pf1_ws_upstream_ft": ws1[0],
        "pf1_ws_downstream_ft": ws1[-1],
        "pf1_ws_first_subcritical_xs_ft": ws1[first_sub1],
        "pf2_ws_upstream_ft": ws2[0],
        "pf2_ws_downstream_ft": ws2[-1],
        "pf1_n_supercritical_xs": len(sup1),
        "pf2_n_supercritical_xs": len(sup2),
        "pf1_first_subcritical_xs_index": first_sub1,
        "pf1_rmse_vs_observed_ws_ft": m["RMSE"],
        "pf1_nse_vs_observed_ws": m["NSE"],
        "pf1_max_abs_err_vs_observed_ws_ft": m["max_abs_err_ft"],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rassteady-bin")
    a = ap.parse_args()
    b = next((c for c in (a.rassteady_bin, os.environ.get("RASSTEADY_BIN"),
                          shutil.which("RasSteady.exe"), _DEF)
              if c and Path(c).is_file()), None)
    if not b:
        print("MISSING DEPENDENCY: HEC-RAS RasSteady.exe not found (set RASSTEADY_BIN or "
              "--rassteady-bin). NOT run.", file=sys.stderr)
        return 3
    if not shutil.which("wine"):
        print("MISSING DEPENDENCY: wine not on PATH (HEC-RAS is a Windows program). NOT run.",
              file=sys.stderr)
        return 3
    try:
        import h5py, numpy  # noqa: F401
    except ImportError as ex:
        print(f"MISSING DEPENDENCY: python package {ex.name}. NOT run.", file=sys.stderr)
        return 3
    prefix = os.environ.get("WINEPREFIX") or (b.split("/drive_c/")[0] if "/drive_c/" in b
                                              else os.path.expanduser("~/.wine"))

    tmp = Path(tempfile.mkdtemp(prefix="hecras_mixed_"))
    proj, out = tmp / "proj", tmp / "out"
    proj.mkdir()
    for f in INPUTS:
        shutil.copy(HERE / "inputs" / f, proj / f)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    cp = subprocess.run([sys.executable, "-c", _LAUNCH, str(TOOLS), b, prefix,
                         "--project", str(proj), "--prj", "MIXED", "--plan", "01",
                         "--out", str(out), "--timeout", "600"],
                        capture_output=True, text=True, timeout=900, env=env, cwd=tmp)
    fails = []
    try:
        st = json.loads(cp.stdout)
    except ValueError:
        st = {}
    if cp.returncode != 0 or not st.get("ok"):
        fails.append(f"run_hecras.py failed (rc={cp.returncode}): "
                     f"{(cp.stdout + cp.stderr)[-600:]}")
    elif not (st.get("returncode") == 0 and st.get("finished")
              and "Finished Steady Flow Simulation" in st.get("stdout_tail", "")):
        fails.append(f"solver did not finish normally: rc={st.get('returncode')}")
    else:
        print("  ran RasSteady.exe through KI tools/run_hecras.py: rc=0, "
              "'Finished Steady Flow Simulation'")
        try:
            got = summarise(out / "MIXED.p01.tmp.hdf", proj / "MIXED.f01")
        except Exception as ex:
            fails.append(f"could not read results: {ex!r}")
            got = None
        if got is not None:
            for c in EXP["numeric_checks"]:
                v = got[c["name"]]
                if abs(v - c["expected"]) > c["tol"]:
                    fails.append(f"{c['name']}: {v:.6g} vs {c['expected']}±{c['tol']}")
                else:
                    print(f"  OK {c['name']}: {v:.6g}")

    shutil.rmtree(tmp, ignore_errors=True)
    if fails:
        print("FAIL:", file=sys.stderr)
        for f in fails:
            print("  -", f, file=sys.stderr)
        return 2
    print("PASS: HEC-RAS Mixed Flow Regime Channel reproduced the expected results.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
