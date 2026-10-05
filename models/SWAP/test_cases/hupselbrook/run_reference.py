#!/usr/bin/env python3
"""Run SWAP's official Hupselbrook test case in a clean dir and check expected.json.

Foundation case for the SWAP KI. Steps follow SWAP's own test task
(pixi.toml `test-linux`): copy swap_linux.swp.template to swap.swp, then run
swap in the case folder. Here the run goes through the KI's own
tools/run_swap.py, and the output is read with the KI's tools/parse_swap_output.py.
Exit 0 PASS, 2 checks failed, 3 engine/dependency missing.

Binary lookup: --swap-bin -> $SWAP_BIN -> `which swap` -> server default.
"""
import argparse, csv, json, os, shutil, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP = json.loads((HERE / "expected.json").read_text())
TOOLS = HERE.parents[1] / "tools"
RUN_TOOL = TOOLS / "run_swap.py"
PARSE_TOOL = TOOLS / "parse_swap_output.py"
_DEF = "/home/server/knowledge-dissection-toolkit/auto_dissect/_work/SWAP/source/repo/builddir/swap"
INPUTS = ("283.met", "grassd.crp", "maizes.crp", "potatod.crp", "swap.dra",
          "swap_linux.swp.template")


def find_bin(arg):
    for c in (arg, os.environ.get("SWAP_BIN"), shutil.which("swap"), _DEF):
        if c and Path(c).is_file() and os.access(c, os.X_OK):
            return str(Path(c).resolve())
    return None


def read_csv(fp):
    with open(fp, newline="") as f:
        return list(csv.DictReader(f))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--swap-bin")
    ap.add_argument("--print-values", action="store_true",
                    help="print the measured values as JSON (for recording)")
    a = ap.parse_args()

    swap = find_bin(a.swap_bin)
    if not swap:
        print("MISSING DEPENDENCY: SWAP 4.2.0 executable not found (use --swap-bin or "
              "$SWAP_BIN). NOT run.", file=sys.stderr)
        return 3
    for t in (RUN_TOOL, PARSE_TOOL):
        if not t.is_file():
            print(f"MISSING DEPENDENCY: KI tool {t} not found. NOT run.", file=sys.stderr)
            return 3
    try:
        import numpy  # noqa: F401  (needed by parse_swap_output.py)
    except ImportError:
        print("MISSING DEPENDENCY: numpy (needed by parse_swap_output.py). NOT run.",
              file=sys.stderr)
        return 3

    run = Path(tempfile.mkdtemp(prefix="swap_hupsel_"))
    fails = []
    try:
        for f in INPUTS:
            shutil.copy(HERE / "inputs" / f, run / f)
        # SWAP's own test step: cp swap_linux.swp.template swap.swp
        shutil.copy(run / "swap_linux.swp.template", run / "swap.swp")

        cp = subprocess.run([sys.executable, str(RUN_TOOL), "--binary", swap,
                             "--allow-unpinned-binary", "--work-dir", str(run),
                             "--swp-file", "swap.swp", "--timeout", "600"],
                            cwd=run, capture_output=True, text=True, timeout=900)
        ok_txt = (run / "swap.ok").read_text(errors="replace") if (run / "swap.ok").is_file() else ""
        if cp.returncode != 0 or "SWAP completed successfully" not in cp.stdout:
            fails.append(f"run_swap.py failed (rc={cp.returncode}): "
                         f"{(cp.stdout + cp.stderr)[-600:]}")
        elif "succesfully terminated" not in ok_txt:
            fails.append("swap.ok does not hold SWAP's 'simulation succesfully terminated' line")
        else:
            print("  OK finished normally: run_swap.py reports success and swap.ok "
                  "holds SWAP's 'simulation succesfully terminated' line")

        if not fails:
            pdir = run / "parsed"
            pp = subprocess.run([sys.executable, str(PARSE_TOOL), "--work-dir", str(run),
                                 "--outfil", "result", "--output-dir", str(pdir)],
                                cwd=run, capture_output=True, text=True, timeout=300)
            if pp.returncode != 0:
                fails.append(f"parse_swap_output.py failed (rc={pp.returncode}): "
                             f"{(pp.stdout + pp.stderr)[-600:]}")
            else:
                wb = read_csv(pdir / "water_balance.csv")
                inc = read_csv(pdir / "daily_increments.csv")
                vap = read_csv(pdir / "soil_profiles.csv")
                s = lambda k: sum(float(r[k]) for r in wb)
                gwl = [float(r["Gwl"]) for r in inc]
                got = {
                    "n_balance_years": len(wb),
                    "n_monthly_increments": len(inc),
                    "n_profile_snapshots": len({r["date"] for r in vap}),
                    "initial_storage_cm": float(wb[0]["initial_storage_cm"]),
                    "final_storage_cm": float(wb[-1]["final_storage_cm"]),
                    "total_rain_cm": s("rain_cm"),
                    "total_irrigation_cm": s("gross_irrigation_cm"),
                    "total_interception_cm": s("interception_cm"),
                    "total_transpiration_cm": s("transpiration_cm"),
                    "total_soil_evaporation_cm": s("soil_evaporation_cm"),
                    "total_drainage_cm": s("drainage_cm"),
                    "max_abs_balance_deviation_cm": max(abs(float(r["balance_deviation_cm"]))
                                                        for r in wb),
                    "min_groundwater_level_cm": min(gwl),
                    "max_groundwater_level_cm": max(gwl),
                    "mean_groundwater_level_cm": sum(gwl) / len(gwl),
                }
                if a.print_values:
                    print(json.dumps(got, indent=2))
                for c in EXP["numeric_checks"]:
                    v = got[c["name"]]
                    if abs(v - c["expected"]) > c["tol"]:
                        fails.append(f"{c['name']}: {v:.6g} vs {c['expected']}+-{c['tol']}")
                    else:
                        print(f"  OK {c['name']}: {v:.6g}")
    finally:
        shutil.rmtree(run, ignore_errors=True)

    if fails:
        print("FAIL:", file=sys.stderr)
        for f in fails:
            print("  -", f, file=sys.stderr)
        return 2
    print("PASS: SWAP Hupselbrook reproduced the expected results.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
