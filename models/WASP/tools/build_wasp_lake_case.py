#!/usr/bin/env python3
"""
build_wasp_lake_case.py -- turn EPA's Steady State example .wif into a well-mixed lake-box case.

Copy-first: the EPA example (Advanced Eutrophication model, 10 segments, systems CBOD x2, DO,
Solids, Water Temperature) is the template; only listed values are changed, through EPA's own API
(tools/wasp_wif_api.py). Nothing is generated from scratch. Template sha256 is checked.

Changes made (and nothing else):
  run window     PSEEDDATE/PSEEDTIME/PENDJULIAN, output every --print-days (PPRINTFUNC), PMAXDT
  hydraulics     flow option 7 "Flow Routing" for the model and every segment (template = 4,
                 kinematic wave); each segment a box: volume = area*depth, depth multiplier =
                 depth, exponents 0, velocity 0 (VMULT/VEXP 0) -> constant depth, no current
  flows          every inflow function = --flow-m3s (tiny by default) at start and end: the boxes
                 are hydraulically isolated, so segment 1 is the lake box that is scored
  boundaries     every boundary of every system = that system's initial value (start and end)
  weather        time functions Solar-1 (ISC 4), Air T-1 (17), Wind-1 (21), Cloud-1 (25),
                 Dew point-1 (29) <- --weather CSV (build_wasp_weather_from_source.py), one point
                 per day; every segment points to function 1 with multiplier 1 (params 2-11)
  site           constants 57 elevation (DO saturation pressure term), 2/3 lat/lon, 501 ice switch;
                 segment param 24 elevation, 32 SOD (g O2/m2/d)
  kinetics       constant 47 CBOD decay (both CBOD instances), 55 global reaeration (0 = use the
                 computed wind/hydraulic rate), initial conditions per system
Writes <out-dir>/<name>.wif, <name>_commands.txt (every API command, for audit) and
<name>_case.json (inputs, hashes, values). Exit 0 ok; 1 API/validation failure; 2 bad args;
3 WINE/wasptool missing. The WINE prefix and wine are found as in wasp_wif_api.py (--wineprefix ->
$WASP_WINEPREFIX -> $WASP_ENGINE_ROOT/wineprefix -> server default; --wine -> $WASP_WINE -> PATH).

Usage
  python build_wasp_lake_case.py --weather weather.csv --start 2004-01-01 --end 2014-12-31 \
      --depth 20 --lat 41.95 --lon -81.55 --elev 174 --sod 0.5 --out-dir case --name erie_cb
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).expanduser().absolute().parent))
sys.dont_write_bytecode = True  # importing the sibling tool must not leave __pycache__ in the KI
import wasp_wif_api as api  # noqa: E402

KI = Path(__file__).expanduser().absolute().parents[1]
TEMPLATE = KI / "test_cases" / "steady_state" / "inputs" / "SteadyState.wif"
TEMPLATE_SHA = "41a3178f444dfc3ef8952a2de05713187ce4aeed55a88ef5fe5f78611e0eb4cf"
WEATHER_TF = {"solar_wm2": 4, "air_temp_c": 17, "wind_ms": 21, "cloud_frac": 25, "dew_point_c": 29}
SEG_POINTERS = {2: 1.0, 3: 1, 4: 1.0, 5: 1, 6: 1.0, 7: 1, 8: 1.0, 9: 1, 10: 1.0, 11: 1, 13: 1.0}
SYS_KEYS = {"CBODU", "DISOX", "SOLID", "WTEMP"}


def sha256(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def read_structure(wif, eng=None):
    """Counts the edit plan depends on, read from the template itself."""
    eng = eng or {}
    r = dict(api.query(wif, ["GNUMSEG", "GNUMSYS", "GNFIELD", "GNPRINT", "GMODELTYPE"], **eng))
    n = {"seg": r["GNUMSEG"]["numseg"], "sys": r["GNUMSYS"]["numsysinstances"],
         "field": r["GNFIELD"]["nfield"], "print": r["GNPRINT"]["nprint"],
         "model": r["GMODELTYPE"]["model_type"]}
    q = [f"GSYSNAME {s}" for s in range(1, n["sys"] + 1)]
    q += [f"GNOBC {s}" for s in range(1, n["sys"] + 1)] + [f"GNOWK {s}" for s in range(1, n["sys"] + 1)]
    q += [f"GNINQ {f}" for f in range(1, n["field"] + 1)]
    res = api.query(wif, q, **eng)
    n["keys"] = [r["sys_key"] for c, r in res if c.startswith("GSYSNAME")]
    n["nobc"] = [r["nobc"] for c, r in res if c.startswith("GNOBC")]
    n["nowk"] = [r["nowk"] for c, r in res if c.startswith("GNOWK")]
    n["ninq"] = [r["ninq"] for c, r in res if c.startswith("GNINQ")]
    return n


def plan(a, n, wx, ndays):
    init = {"CBODU": [a.cbod0] + [0.0] * 9, "DISOX": [a.do0], "SOLID": [a.solids0], "WTEMP": [a.temp0]}
    seen, ic = {}, []
    for k in n["keys"]:
        i = seen.get(k, 0)
        seen[k] = i + 1
        ic.append(init[k][i] if i < len(init[k]) else 0.0)
    t0 = pd.Timestamp(a.start)
    c = [f"PSEEDDATE {t0.month} {t0.day} {t0.year}", "PSEEDTIME 0 0 0", f"PENDJULIAN {ndays:.1f}",
         f"PMAXDT {a.max_dt}"]
    for k in range(1, n["print"] + 1):
        c.append(f"PPRINTFUNC {k} {0.0 if k == 1 else float(ndays)} {a.print_days}")
    side = (a.area_km2 * 1e6) ** 0.5
    c.append("PIQOPT 7")
    for s in range(1, n["seg"] + 1):
        c += [f"PFLOWTYPE {s} 7", f"PVOLUME {s} {side * side * a.depth:.6g}", f"PDMULT {s} {a.depth}",
              f"PDEXP {s} 0", f"PVMULT {s} 0", f"PVEXP {s} 0", f"PINITIALDEPTH {s} {a.depth}",
              f"PSEGLENGTH {s} {side:.6g}", f"PSEGWIDTH {s} {side:.6g}"]
        c += [f"PCONSTPARAM {s} {p} 1 {v}" for p, v in SEG_POINTERS.items()]
        c += [f"PCONSTPARAM {s} 24 1 {a.elev}", f"PCONSTPARAM {s} 32 1 {a.sod}"]
        c += [f"PINITC {i + 1} {s} {v}" for i, v in enumerate(ic)]
    for f, ninq in enumerate(n["ninq"], 1):
        for fn in range(1, ninq + 1):
            c += [f"PNBRKQ {f} {fn} 2", f"PNOQFUNC {f} {fn} 1 0.0 {a.flow_m3s}",
                  f"PNOQFUNC {f} {fn} 2 {float(ndays)} {a.flow_m3s}"]
    for i, nb in enumerate(n["nobc"], 1):
        for b in range(1, nb + 1):
            c += [f"PNBFP {i} {b} 2", f"PBOUNDFUNC {i} {b} 1 0.0 {ic[i - 1]}",
                  f"PBOUNDFUNC {i} {b} 2 {float(ndays)} {ic[i - 1]}"]
    c += [f"PCONSTVALUEBYISC 57 1 {a.elev}", f"PCONSTVALUEBYISC 2 1 {a.lat}",
          f"PCONSTVALUEBYISC 3 1 {a.lon}", f"PCONSTVALUEBYISC 501 1 {a.ice}",
          f"PCONSTVALUEBYISC 55 1 {a.global_ka}"]
    c += [f"PCONSTVALUEBYISC 47 {i} {a.cbod_decay}" for i in (1, 2)]
    # A value is only seen by the engine if its "used" flag is 1 (template has 0 for e.g. params
    # 8/9/11/24/32, constants 2/3/57, cloud TF 25); without it the PUT echoes fine and is IGNORED.
    c += [f"PPARAMISUSED {p} 1 1" for p in list(SEG_POINTERS) + [24, 32]]
    c += [f"PCONSTISUSED {k} 1 1" for k in (57, 2, 3, 501, 55)] + ["PCONSTISUSED 47 2 1"]
    c += [f"PTFISUSED {isc} 1 1" for isc in WEATHER_TF.values()]
    days = (wx["date"] - t0).dt.days.astype(float).tolist()
    for col, isc in WEATHER_TF.items():
        vals = (wx[col] * (a.cloud_scale if col == "cloud_frac" else 1.0)).tolist()
        c.append(f"PNBRKTF {isc} 1 {len(vals) + 1}")
        c += [f"PBRKTF {isc} 1 {k + 1} {d:.1f} {v:.4f}" for k, (d, v) in enumerate(zip(days, vals))]
        c.append(f"PBRKTF {isc} 1 {len(vals) + 1} {float(ndays):.1f} {vals[-1]:.4f}")
    return c, ic


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--template", default=str(TEMPLATE))
    ap.add_argument("--weather", required=True, help="CSV from build_wasp_weather_from_source.py")
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True, help="last simulated day (inclusive)")
    ap.add_argument("--depth", type=float, required=True, help="box (water column) depth, m")
    ap.add_argument("--area-km2", type=float, default=1.0, help="box surface area (sets volume)")
    ap.add_argument("--lat", type=float, required=True)
    ap.add_argument("--lon", type=float, required=True)
    ap.add_argument("--elev", type=float, required=True, help="water surface elevation, m a.s.l.")
    ap.add_argument("--sod", type=float, default=0.0, help="sediment oxygen demand, g O2/m2/d")
    ap.add_argument("--cbod0", type=float, default=1.0, help="initial CBOD (ultimate), mg/L")
    ap.add_argument("--cbod-decay", type=float, default=0.1, help="CBOD decay @20C, 1/d")
    ap.add_argument("--do0", type=float, required=True, help="initial DO, mg/L")
    ap.add_argument("--temp0", type=float, required=True, help="initial water temperature, C")
    ap.add_argument("--solids0", type=float, default=1.0)
    ap.add_argument("--ice", type=int, default=0, choices=[0, 1, 2], help="constant 501 ice switch")
    ap.add_argument("--global-ka", type=float, default=0.0,
                    help="constant 55; 0 = engine computes wind/hydraulic reaeration")
    ap.add_argument("--cloud-scale", type=float, default=1.0,
                    help="multiply the 0-1 cloud fraction by this before writing TF 25")
    ap.add_argument("--flow-m3s", type=float, default=1e-4)
    ap.add_argument("--max-dt", type=float, default=0.05, help="max time step, days")
    ap.add_argument("--print-days", type=float, default=1.0)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--name", default="lake_box")
    ap.add_argument("--allow-other-template", action="store_true")
    ap.add_argument("--wineprefix", help="WINE prefix holding C:\\WASP8 (else $WASP_WINEPREFIX, else "
                                         "$WASP_ENGINE_ROOT/wineprefix, else the server install)")
    ap.add_argument("--wine", help="wine executable (else $WASP_WINE, else wine on PATH)")
    a = ap.parse_args()
    eng = {"wineprefix": a.wineprefix, "wine": a.wine}
    if not Path(a.template).is_file() or not Path(a.weather).is_file():
        print("ERROR: template or weather file missing", file=sys.stderr)
        return 2
    if sha256(a.template) != TEMPLATE_SHA and not a.allow_other_template:
        print("ERROR: template is not EPA's SteadyState.wif (sha256 mismatch)", file=sys.stderr)
        return 2
    if a.depth <= 0 or a.area_km2 <= 0 or a.sod < 0:
        print("ERROR: depth/area must be > 0 and SOD >= 0", file=sys.stderr)
        return 2
    wx = pd.read_csv(a.weather, comment="#", parse_dates=["date"])
    t0, t1 = pd.Timestamp(a.start), pd.Timestamp(a.end)
    wx = wx[(wx.date >= t0) & (wx.date <= t1)].reset_index(drop=True)
    ndays = (t1 - t0).days + 1
    if len(wx) != ndays or wx.isna().any().any():
        print(f"ERROR: weather has {len(wx)} complete days, run needs {ndays}", file=sys.stderr)
        return 1
    try:
        n = read_structure(a.template, eng)
        if n["model"] != 11 or not set(n["keys"]) <= SYS_KEYS or "DISOX" not in n["keys"]:
            raise api.WifApiError(f"template is not the expected Advanced Eutrophication DO deck: {n}")
        if any(n["nowk"]):
            raise api.WifApiError(f"template has point loads {n['nowk']}; this builder does not edit loads")
        cmds, ic = plan(a, n, wx, ndays)
        out = Path(a.out_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{a.name}_commands.txt").write_text("\n".join(cmds) + "\n")
        api.edit_wif(a.template, out / f"{a.name}.wif", cmds, **eng)
        chk = dict(api.query(out / f"{a.name}.wif", ["GSEEDDATE", "GENDJULIAN", "GIQOPT", "GDMULT 1",
                                                     "GNBRKTF 17 1", "GCONSTVALUEBYISC 57 1"], **eng))
    except FileNotFoundError as e:
        print(f"MISSING DEPENDENCY: {e}", file=sys.stderr)
        return 3
    except api.WifApiError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    if (chk["GSEEDDATE"]["year"], chk["GIQOPT"]["iqopt"], chk["GNBRKTF 17 1"]["nbrktf"]) != \
            (t0.year, 7, ndays + 1) or abs(chk["GDMULT 1"]["dmult"] - a.depth) > 1e-6:
        print(f"ERROR: saved .wif does not read back as written: {chk}", file=sys.stderr)
        return 1
    case = {"wif": str(out / f"{a.name}.wif"), "wif_sha256": sha256(out / f"{a.name}.wif"),
            "template": str(a.template), "template_sha256": sha256(a.template),
            "weather": str(a.weather), "weather_sha256": sha256(a.weather), "n_days": ndays,
            "structure": n, "initial_conditions_by_system": ic, "n_api_commands": len(cmds),
            "args": vars(a), "scored_segment": 1, "readback": chk}
    (out / f"{a.name}_case.json").write_text(json.dumps(case, indent=1, default=str))
    print(f"wrote {case['wif']} ({len(cmds)} API commands, {ndays} days, {n['seg']} isolated boxes "
          f"of {a.depth} m; read-back ok)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
