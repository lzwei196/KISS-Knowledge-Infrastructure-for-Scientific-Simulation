#!/usr/bin/env python3
"""Run the official Daisy tutorial setup (sample/test.dai, "Andeby farm") and check expected.json.

Foundation case for the Daisy KI. A sandy Danish soil column, Taastrup weather,
1986-12-01 to 1988-04-01: plowing, mineral N, spring barley sown with grass under-sown,
barley harvest, autumn N, grass cut. The run goes through the KI's own tools/run_daisy.py
and the .dlf outputs are read with the KI's own tools/parse_daisy_output.py.
Exit 0 PASS, 2 checks failed, 3 engine/dependency missing.

Binary lookup: --daisy-bin -> $DAISY_BIN -> `which daisy` -> server default.
Daisy library (lib/ with tillage.dai, crop.dai, log.dai): --daisy-home -> $DAISYHOME ->
<binary dir>/../source/repo -> server default. The library is part of the Daisy install,
so it is not copied into inputs/.
"""
import argparse, json, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP = json.loads((HERE / "expected.json").read_text())
TOOLS = HERE.parents[1] / "tools"
RUN_TOOL = TOOLS / "run_daisy.py"
_DEF_BIN = "/mnt/disk1/Hydrocraft_server/models/Daisy/bin/daisy"
_DEF_HOME = "/mnt/disk1/Hydrocraft_server/models/Daisy/source/repo"
INPUTS = ("test.dai", "dk-taastrup.dwf")
LIBS = ("tillage.dai", "crop.dai", "log.dai")
DLF = ("harvest.dlf", "sbarley.dlf", "field_water.dlf", "field_nitrogen.dlf",
       "soil_water.dlf", "soil_nitrogen.dlf")


def find_bin(arg):
    for c in (arg, os.environ.get("DAISY_BIN"), shutil.which("daisy"), _DEF_BIN):
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


def find_home(arg, binary):
    cands = [arg, os.environ.get("DAISYHOME")]
    if binary:
        cands.append(str(Path(binary).resolve().parent.parent / "source" / "repo"))
    cands.append(_DEF_HOME)
    for c in cands:
        if c and all((Path(c) / "lib" / f).is_file() for f in LIBS):
            return c
    return None


def collect(run, parse_dlf):
    """Read the run outputs and return the values named in expected.json."""
    log = (run / "daisy.log").read_text(errors="replace")
    hv = parse_dlf(str(run / "harvest.dlf"))["dataframe"]
    sb = parse_dlf(str(run / "sbarley.dlf"))["dataframe"]
    fw = parse_dlf(str(run / "field_water.dlf"))["dataframe"]
    fn = parse_dlf(str(run / "field_nitrogen.dlf"))["dataframe"]
    barley = hv[hv["crop"] == "Spring Barley"].iloc[0]
    grass = hv[hv["crop"] == "Grass"].iloc[0]
    bal = [float(x) for x in re.findall(r"Balance \(= In - Out - Increase\) =\s*(-?[\d.]+)", log)]
    return {
        "n_dlf_files": sum((run / f).is_file() for f in DLF),
        "n_harvest_rows": len(hv),
        "barley_harvest_doy": int(__import__("datetime").date(
            int(barley["year"]), int(barley["month"]), int(barley["day"])).timetuple().tm_yday),
        "barley_grain_DM": float(barley["sorg_DM"]),
        "barley_stem_DM": float(barley["stem_DM"]),
        "barley_grain_N": float(barley["sorg_N"]),
        "grass_cut_leaf_DM": float(grass["leaf_DM"]),
        "n_sbarley_daily_rows": len(sb),
        "barley_max_LAI": float(sb["LAI"].max()),
        "precip_total_mm": float(fw["Precipitation"].sum()),
        "actual_ET_total_mm": float(fw["Actual evapotranspiration"].sum()),
        "matrix_percolation_total_mm": float(fw["Matrix percolation"].sum()),
        "final_soil_matrix_water_mm": float(fw["Soil matrix water"].iloc[-1]),
        "matrix_N_leaching_total": float(fn["Matrix-Leaching"].sum()),
        "crop_N_uptake_total": float(fn["Crop-Uptake"].sum()),
        "n_balance_lines": len(bal),
        "max_abs_balance_error": max((abs(b) for b in bal), default=float("nan")),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--daisy-bin")
    ap.add_argument("--daisy-home")
    ap.add_argument("--keep", action="store_true", help="keep the temp run dir")
    a = ap.parse_args()

    binary = find_bin(a.daisy_bin)
    if not binary:
        print("MISSING DEPENDENCY: Daisy binary not found (--daisy-bin / $DAISY_BIN / PATH). NOT run.",
              file=sys.stderr)
        return 3
    home = find_home(a.daisy_home, binary)
    if not home:
        print("MISSING DEPENDENCY: Daisy library dir (DAISYHOME with lib/tillage.dai, crop.dai, "
              "log.dai) not found (--daisy-home / $DAISYHOME). NOT run.", file=sys.stderr)
        return 3
    try:
        sys.path.insert(0, str(TOOLS))
        from parse_daisy_output import parse_dlf
    except Exception as e:  # pandas/numpy missing
        print(f"MISSING DEPENDENCY: cannot import KI parse tool ({e}). NOT run.", file=sys.stderr)
        return 3

    run = Path(tempfile.mkdtemp(prefix="daisy_tutorial_"))
    for f in INPUTS:
        shutil.copy(HERE / "inputs" / f, run / f)
    env = dict(os.environ, DAISYHOME=home)
    fails = []
    cp = subprocess.run([sys.executable, str(RUN_TOOL), "--dai-file", "test.dai",
                         "--work-dir", str(run), "--binary", binary, "--timeout", "600",
                         "--output-json", str(run / "run_result.json")],
                        cwd=run, env=env, capture_output=True, text=True, timeout=900)
    res = json.loads((run / "run_result.json").read_text()) if (run / "run_result.json").is_file() else {}
    log = (run / "daisy.log").read_text(errors="replace") if (run / "daisy.log").is_file() else ""
    if cp.returncode != 0 or res.get("exit_code") != 0:
        fails.append(f"run failed (tool rc={cp.returncode}, daisy rc={res.get('exit_code')}): "
                     f"{(cp.stdout + cp.stderr)[-600:]}")
    elif "Program finished" not in log:
        fails.append("daisy.log has no 'Program finished' line")
    else:
        print(f"  ran Daisy ({binary}), rc=0, 'Program finished' in daisy.log")
        got = collect(run, parse_dlf)
        for c in EXP["numeric_checks"]:
            v = got[c["name"]]
            if not abs(v - c["expected"]) <= c["tol"]:
                fails.append(f"{c['name']}: {v:.6g} vs {c['expected']}±{c['tol']}")
            else:
                print(f"  OK {c['name']}: {v:.6g}")

    if a.keep:
        print(f"  run dir kept: {run}")
    else:
        shutil.rmtree(run, ignore_errors=True)
    if fails:
        print("FAIL:", file=sys.stderr)
        for f in fails:
            print("  -", f, file=sys.stderr)
        return 2
    print("PASS: Daisy tutorial (Andeby farm) reproduced the expected results.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
