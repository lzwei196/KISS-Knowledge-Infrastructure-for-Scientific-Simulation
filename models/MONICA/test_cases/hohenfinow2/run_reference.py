#!/usr/bin/env python3
"""Run the official MONICA Hohenfinow2 example in a clean dir and check expected.json.

Foundation case for the MONICA KI. The four official files (sim.json, crop.json,
site.json, climate.csv from monica/installer/Hohenfinow2) are copied unchanged to a
fresh temp dir and run through the KI's own tools/run_monica.py. The output CSV is
read directly (it has several event sections: daily, monthly, yearly, run, crop,
xxxx-03-31). Exit 0 PASS, 2 checks failed, 3 engine/parameters missing.

Binary lookup:     --monica-bin -> $MONICA_BIN -> which monica-run -> server default.
Parameters lookup: --monica-parameters -> $MONICA_PARAMETERS -> server default.
"""
import argparse, csv, json, os, shutil, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP = json.loads((HERE / "expected.json").read_text())
RUN_TOOL = HERE.parents[1] / "tools" / "run_monica.py"
_DEF_BIN = "/mnt/disk1/Hydrocraft_server/models/MONICA/bin/monica-run"
_DEF_PAR = "/mnt/disk1/Hydrocraft_server/models/MONICA/source/monica-parameters"
INPUTS = ("sim.json", "crop.json", "site.json", "climate.csv")


def read_sections(fp):
    """MONICA CSV -> {section: (header, rows)}; each section = name line, header, units, rows."""
    secs, name, lines = {}, None, []
    with open(fp, encoding="latin-1") as f:
        raw = f.read().splitlines()
    for ln in raw + [""]:
        if ln.startswith('"') and ln.endswith('"'):
            name, lines = ln.strip('"'), []
        elif ln.strip() == "":
            if name and lines:
                rows = list(csv.reader(lines))
                secs[name] = (rows[0], rows[2:])
            name, lines = None, []
        elif name:
            lines.append(ln)
    return secs


def col(sec, key, idx=0):
    hdr, rows = sec
    j = [i for i, h in enumerate(hdr) if h == key][idx]
    return [r[j] for r in rows]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--monica-bin")
    ap.add_argument("--monica-parameters")
    a = ap.parse_args()
    binp = next((c for c in (a.monica_bin, os.environ.get("MONICA_BIN"),
                             shutil.which("monica-run"), _DEF_BIN)
                 if c and os.path.isfile(c) and os.access(c, os.X_OK)), None)
    if not binp:
        print("MISSING DEPENDENCY: monica-run binary not found (use --monica-bin or "
              "$MONICA_BIN). NOT run.", file=sys.stderr)
        return 3
    par = next((c for c in (a.monica_parameters, os.environ.get("MONICA_PARAMETERS"), _DEF_PAR)
                if c and (Path(c) / "crops").is_dir()), None)
    if not par:
        print("MISSING DEPENDENCY: monica-parameters dir (github.com/zalf-rpm/monica-parameters) "
              "not found (use --monica-parameters or $MONICA_PARAMETERS). NOT run.", file=sys.stderr)
        return 3

    run = Path(tempfile.mkdtemp(prefix="monica_hohenfinow2_"))
    for f in INPUTS:
        shutil.copy(HERE / "inputs" / f, run / f)
    out = run / "sim-out.csv"
    fails = []
    try:
        cp = subprocess.run([sys.executable, str(RUN_TOOL), "--binary", binp,
                             "--sim-json", str(run / "sim.json"), "--output", str(out),
                             "--parameters-dir", par, "--timeout", "600"],
                            capture_output=True, text=True, timeout=900, cwd=run)
        res = {}
        try:
            res = json.loads(cp.stdout)
        except ValueError:
            pass
        if cp.returncode != 0 or res.get("status") != "success" or not out.is_file():
            fails.append(f"run failed (rc={cp.returncode}, status={res.get('status')}): "
                         f"{(cp.stderr or cp.stdout)[-400:]}")
        else:
            print(f"  OK finished normally: rc=0, run tool status=success, "
                  f"{out.stat().st_size} bytes written")
            s = read_sections(out)
            daily, crop = s["daily"], s["crop"]
            yearly, runsec = s["yearly"], s["run"]
            f = lambda xs: [float(x) for x in xs]
            yields = f(col(crop, "Yield"))
            got = {
                "n_daily_rows": len(daily[1]),
                "n_monthly_rows": len(s["monthly"][1]),
                "n_yearly_rows": len(yearly[1]),
                "n_crops": len(crop[1]),
                "run_precip_sum_mm": f(col(runsec, "Precip"))[0],
                "daily_precip_sum_mm": sum(f(col(daily, "Precip"))),
                "yield_rye_1992": yields[0],
                "yield_silage_maize_1993": yields[1],
                "yield_potato_1994": yields[2],
                "yield_winter_wheat_1995": yields[3],
                "yield_spring_barley_1996": yields[5],
                "sum_crop_yields": sum(yields),
                "max_daily_LAI": max(f(col(daily, "LAI"))),
                "max_daily_AbBiom": max(f(col(daily, "AbBiom"))),
                "sum_yearly_NLeach": sum(f(col(yearly, "NLeach"))),
                "sum_yearly_Recharge": sum(f(col(yearly, "Recharge"))),
            }
            for c in EXP["numeric_checks"]:
                v = got[c["name"]]
                if abs(v - c["expected"]) > c["tol"]:
                    fails.append(f"{c['name']}: {v:.6g} vs {c['expected']}+-{c['tol']}")
                else:
                    print(f"  OK {c['name']}: {v:.6g}")
            first, last = col(daily, "Date")[0], col(daily, "Date")[-1]
            want = EXP.get("daily_date_range")
            if want and [first, last] != want:
                fails.append(f"daily date range {first}..{last} vs {want}")
            else:
                print(f"  OK daily date range: {first} .. {last}")
    finally:
        shutil.rmtree(run, ignore_errors=True)

    if fails:
        print("FAIL:", file=sys.stderr)
        for x in fails:
            print("  -", x, file=sys.stderr)
        return 2
    print("PASS: MONICA Hohenfinow2 reproduced the expected results.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
