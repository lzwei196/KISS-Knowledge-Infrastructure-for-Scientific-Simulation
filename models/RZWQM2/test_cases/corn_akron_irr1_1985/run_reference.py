#!/usr/bin/env python3
"""Run the official RZWQM2 Corn-Akron Irr-1-85DS example in a clean dir and check expected.json.

Foundation case for the RZWQM2 KI. The scenario comes from the RZWQM2 Windows install
(DATA\\Corn-Akron\\Irr-1-85DS: 1985 irrigated corn, Akron, Colorado). The model is run
through the KI's own tools/s8_execution/run_rzwqm2.py and the daily .ana output is read
with the KI's own tools/s9_result_parsing/parse_ana_output.py.

Only the temp run copy is changed, the same way the RZWQM2 Windows interface does it on RUN:
  * IPNAMES.DAT and MZDSSAT.RZX get relative Linux paths instead of the C:\\RZWQM2\\... paths.
  * The Linux engine opens some files by UPPER-CASE name (IPNAMES.DAT, MZDSSAT.RZX,
    MZCER040.CUL, EXPDATA.DAT, EXPDSSAT.MZA); Windows does not care about case, Linux does,
    so upper-case copies are made. File contents are not touched (except the path lines).

Exit 0 PASS, 2 checks failed, 3 engine/dependency missing.
Binary lookup: --rzwqm2-bin -> $RZWQM2_BIN -> which main_ryzen_patched -> server default.
"""
import argparse, importlib.util, json, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP = json.loads((HERE / "expected.json").read_text())
KI = HERE.parents[1]
RUN_TOOL = KI / "tools" / "s8_execution" / "run_rzwqm2.py"
PARSE_TOOL = KI / "tools" / "s9_result_parsing" / "parse_ana_output.py"
_DEF = "/mnt/disk1/Hydrocraft_server/model/rzwqm2/main_ryzen_patched"
SCEN = "Irr-1-85DS"
ANA_VARS = ["precipitation", "irrigation", "actual_evaporation", "actual_transpiration",
            "runoff", "stored_soil_water", "biomass_above", "grain_yield", "lai",
            "grain_n", "mineralization"]


def find_bin(arg):
    for c in (arg, os.environ.get("RZWQM2_BIN"), shutil.which("main_ryzen_patched"), _DEF):
        if c and Path(c).is_file() and os.access(c, os.X_OK):
            return c
    return None


def prepare(run):
    """Copy inputs to run/ and do the path + upper-case-name step (temp copy only)."""
    for sub in (SCEN, "Meteorology", "DSSAT"):
        shutil.copytree(HERE / "inputs" / sub, run / sub)
    (run / "Analysis").mkdir()
    sd = run / SCEN
    ip = (sd / "ipnames.dat").read_text(encoding="latin-1")
    ip = ip.replace("C:\\RZWQM2\\data\\Corn-Akron\\Irr-1-85DS\\", "./")
    ip = ip.replace("C:\\RZWQM2\\data\\Corn-Akron\\", "../").replace("\\", "/")
    (sd / "ipnames.dat").unlink()          # KI tool would pick the lower-case one first
    (sd / "IPNAMES.DAT").write_text(ip, encoding="latin-1")
    rz = (sd / "mzdssat.rzx").read_text(encoding="latin-1")
    rz = rz.replace("C:\\RZWQM2\\DATABASES\\DSSAT\\", "../DSSAT/")
    rz = rz.replace("C:\\RZWQM2\\DATA\\CORN-AKRON\\IRR-1-85DS\\", "./")
    (sd / "mzdssat.rzx").unlink()
    (sd / "MZDSSAT.RZX").write_text(rz, encoding="latin-1")
    for f in ("mzcer040.cul", "expdata.dat", "expdssat.MZA"):
        shutil.copy(sd / f, sd / f.upper())


def read_massbal(fp):
    txt = fp.read_text(encoding="latin-1")
    out = {}
    for key, name in (("WATER", "water_balance_end_cm"), ("NITROGEN", "nitrogen_balance_end_kgha")):
        m = re.search(key + r"\s+BALANCE AT END OF SIMULATION:\s+(\S+)", txt)
        out[name] = abs(float(m.group(1))) if m else float("nan")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rzwqm2-bin")
    a = ap.parse_args()
    binp = find_bin(a.rzwqm2_bin)
    if not binp:
        print("MISSING DEPENDENCY: RZWQM2 Linux engine main_ryzen_patched not found "
              "(set RZWQM2_BIN or --rzwqm2-bin). NOT run.", file=sys.stderr)
        return 3
    for t in (RUN_TOOL, PARSE_TOOL):
        if not t.is_file():
            print(f"MISSING DEPENDENCY: KI tool {t} not found. NOT run.", file=sys.stderr)
            return 3

    run = Path(tempfile.mkdtemp(prefix="rzwqm2_akron_"))
    fails = []
    try:
        prepare(run)
        cp = subprocess.run([sys.executable, str(RUN_TOOL), str(run / SCEN), binp, "1200"],
                            capture_output=True, text=True, timeout=1500, cwd=run)
        res = {}
        try:
            res = json.loads(cp.stdout.strip().splitlines()[-1])
        except Exception:
            pass
        if cp.returncode != 0 or res.get("status") != "SUCCESS":
            fails.append(f"KI run tool failed (rc={cp.returncode}): {cp.stdout[-400:]} {cp.stderr[-400:]}")
        else:
            print(f"  ran RZWQM2 via KI tool: {res.get('message')}")
            spec = importlib.util.spec_from_file_location("parse_ana_output", PARSE_TOOL)
            pa = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(pa)
            ana = run / "Analysis" / f"{SCEN}.ana"
            r = pa.extract_variables(str(ana), ANA_VARS)
            col = {k: [v for _, v in s] for k, s in r.items()}
            dates = [d for d, _ in r["precipitation"]]
            got = {
                "n_daily_records": len(dates),
                "last_doy_1985": dates[-1].timetuple().tm_yday if dates[-1].year == 1985 else -1,
                "sum_precipitation_cm": sum(col["precipitation"]),
                "sum_irrigation_cm": sum(col["irrigation"]),
                "sum_actual_evaporation_cm": sum(col["actual_evaporation"]),
                "sum_actual_transpiration_cm": sum(col["actual_transpiration"]),
                "sum_runoff_cm": sum(col["runoff"]),
                "final_stored_soil_water_cm": col["stored_soil_water"][-1],
                "max_biomass_above_kgha": max(col["biomass_above"]),
                "max_grain_yield_kgha": max(col["grain_yield"]),
                "max_lai": max(col["lai"]),
                "max_grain_n_kgha": max(col["grain_n"]),
                "sum_mineralization_kgha": sum(col["mineralization"]),
            }
            got.update(read_massbal(run / SCEN / "MASSBAL.OUT"))
            for c in EXP["numeric_checks"]:
                v = got[c["name"]]
                if not abs(v - c["expected"]) <= c["tol"]:
                    fails.append(f"{c['name']}: {v:.6g} vs {c['expected']}+-{c['tol']}")
                else:
                    print(f"  OK {c['name']}: {v:.6g}")
            # finished normally = KI tool SUCCESS (return code 0, .ana written), last .ana day
            # is 31 Dec 1985 (checked above) and MASSBAL.OUT has the model's own
            # "BALANCE AT END OF SIMULATION" lines (a missing line gives NaN and fails above).
            print("  OK finished normally: return code 0, .ana reaches 1985 DOY 365, "
                  "MASSBAL end-of-simulation lines present")
    finally:
        shutil.rmtree(run, ignore_errors=True)

    if fails:
        print("FAIL:", file=sys.stderr)
        for f in fails:
            print("  -", f, file=sys.stderr)
        return 2
    print("PASS: RZWQM2 Corn-Akron Irr-1-85DS reproduced the expected results.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
