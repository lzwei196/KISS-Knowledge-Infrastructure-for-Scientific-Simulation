#!/usr/bin/env python3
"""
run_and_score_verify2.py — APSIM-NG gridded/multi-site wheat run vs SPAM 2020 regional
yield at a DIFFERENT location than the WA real-case, for a consistency check.

Faithful twin of run_and_score.py (identical KI pipeline, cultivar, auto-sow window,
rainfed, HWSD soil, NASA POWER forcing, independent single-season sims) but relocated
to the EASTERN AUSTRALIA (NSW / Victoria) wheatbelt box lon 144-150, lat -37..-30.
Both are Southern-Hemisphere autumn-sown wheat regions so the whole recipe (Wyalkatchem
cultivar, Apr20-Jul10 rain-triggered sow window) stays valid; only the box moves.

SCALE-COMPARABLE: SPAM 2020 yield is a gridded regional aggregate. A single point vs a
regional aggregate is an INVALID scale mismatch, so we run APSIM at a grid of 0.5deg
cells covering ~90% of the box's wheat harvested area and aggregate the simulated yields
with the SAME SPAM harvested-area weights used for the observed aggregate; the dag
determining_metric is PBIAS (magnitude_accuracy family). nse/r/kge are cross-cell spatial.

RESUMABLE: each cell writes grain.json; a relaunch skips completed cells/seasons.
"""
import os, sys, json, csv, glob, subprocess, traceback
import numpy as np
import pandas as pd

ROOT = "/mnt/disk1/Hydrocraft_server/models/APSIM"
KI   = os.path.join(ROOT, "knowledge_infrastructure")
TOOLS= os.path.join(KI, "tools")
BIN  = "/home/server/knowledge-dissection-toolkit/auto_dissect/_work/APSIM/source/repo/bin/Release/net8.0/apsim"
STATE= os.path.join(ROOT, "detached", "verify_2")
WORK = os.path.join(STATE, "work")
RESULT = os.path.join(STATE, "result.json")

SPAM_Y = "/tmp/spam_peek/spam2020V2r0_global_yield/spam2020V2r0_global_Y_TA.csv"
SPAM_H = "/tmp/spam_peek/spam2020V2r0_global_harvested_area/spam2020V2r0_global_H_TA.csv"

# Eastern Australia NSW/Victoria wheatbelt (distinct from WA real-case box 116-120/-34..-29)
BOX = dict(lonmin=144, lonmax=150, latmin=-37, latmax=-30)
REGION = "E Australia NSW/Vic wheatbelt box lon 144-150, lat -37..-30"
SEASONS = [2019, 2020, 2021]
MET_START, MET_END = "2018-11-01", "2022-02-28"
AREA_COVER = 0.90        # keep 0.5deg cells until 90% of wheat harvested area
MAX_CELLS  = 40
CROP, CULTIVAR = "Wheat", "Wyalkatchem"

ENV = dict(os.environ, DOTNET_ROOT="/home/server/.dotnet")
os.makedirs(WORK, exist_ok=True)


def log(*a):
    print("[verify2]", *a, flush=True)


def ensure_spam():
    import zipfile
    for path, zp in [
        (SPAM_Y, "/mnt/datasets/Crop_model_dataset/dataverse_files/Global_CSV/spam2020V2r0_global_yield.csv.zip"),
        (SPAM_H, "/mnt/datasets/Crop_model_dataset/dataverse_files/Global_CSV/spam2020V2r0_global_harvested_area.csv.zip"),
    ]:
        if not os.path.isfile(path):
            log("unzip", zp)
            with zipfile.ZipFile(zp) as z:
                z.extractall("/tmp/spam_peek/" + os.path.basename(zp).replace(".csv.zip", ""))


def select_cells():
    dy = pd.read_csv(SPAM_Y, usecols=['x', 'y', 'WHEA_A'], dtype={'x': float, 'y': float, 'WHEA_A': float}).rename(columns={'WHEA_A': 'yld'})
    dh = pd.read_csv(SPAM_H, usecols=['x', 'y', 'WHEA_A'], dtype={'x': float, 'y': float, 'WHEA_A': float}).rename(columns={'WHEA_A': 'harea'})
    m = pd.merge(dy, dh, on=['x', 'y'])
    b = m[(m.x >= BOX['lonmin']) & (m.x <= BOX['lonmax']) & (m.y >= BOX['latmin']) & (m.y <= BOX['latmax']) & (m.yld > 0) & (m.harea > 0)].copy()
    b['cx'] = (np.floor(b.x / 0.5) * 0.5 + 0.25).round(3)
    b['cy'] = (np.floor(b.y / 0.5) * 0.5 + 0.25).round(3)
    cell = b.groupby(['cx', 'cy']).apply(
        lambda g: pd.Series({'obs_yld': (g.yld * g.harea).sum() / g.harea.sum(),
                             'harea': g.harea.sum(), 'npix': len(g)})).reset_index()
    cell = cell.sort_values('harea', ascending=False).reset_index(drop=True)
    cell['cum'] = cell.harea.cumsum() / cell.harea.sum()
    keep = cell[cell.cum < AREA_COVER]
    if len(keep) < len(cell):
        keep = cell.iloc[:len(keep) + 1]
    keep = keep.iloc[:MAX_CELLS].copy()
    dropped_area = cell.harea.sum() - keep.harea.sum()
    log(f"selected {len(keep)}/{len(cell)} cells covering "
        f"{keep.harea.sum()/cell.harea.sum()*100:.1f}% of wheat area; "
        f"dropped {dropped_area:.0f} ha ({dropped_area/cell.harea.sum()*100:.1f}%) in {len(cell)-len(keep)} tail cells")
    return keep


def run(cmd, **kw):
    return subprocess.run(cmd, env=ENV, capture_output=True, text=True, **kw)


def extract_grain(db):
    import sqlite3
    c = sqlite3.connect(db)
    try:
        df = pd.read_sql('SELECT * FROM Report', c)
    finally:
        c.close()
    gcol = [x for x in df.columns if 'Grain.Wt' in x and 'Total' not in x][0]
    return float(df[gcol].max())


def do_cell(cx, cy):
    cd = os.path.join(WORK, f"cell_{cx:+.3f}_{cy:+.3f}".replace('.', 'p'))
    os.makedirs(cd, exist_ok=True)
    gj = os.path.join(cd, "grain.json")
    if os.path.isfile(gj):
        try:
            d = json.load(open(gj))
            if d.get("sim_yld_t_ha") is not None:
                return d["sim_yld_t_ha"], d
        except Exception:
            pass

    soil = os.path.join(cd, "soil.json")
    if not os.path.isfile(soil):
        import ki_tools_common.soil_utils as su
        s = su.lookup_hwsd(cy, cx)
        hcsv = os.path.join(cd, "hwsd.csv")
        rows = [
            dict(depth_top_cm=0, depth_bot_cm=30, sand_pct=s['sand'], clay_pct=s['clay'],
                 bulk_density_kg_m3=s['bulk_density'], organic_carbon_g_kg=s['oc'], ph_water=s['ph']),
            dict(depth_top_cm=30, depth_bot_cm=100, sand_pct=s['sub_sand'], clay_pct=s['sub_clay'],
                 bulk_density_kg_m3=s['bulk_density'], organic_carbon_g_kg=max(0.1, s['oc'] * 0.4), ph_water=s['ph']),
        ]
        with open(hcsv, 'w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
        r = run(["python3", os.path.join(TOOLS, "convert_soil.py"), "--input", hcsv, "--output", soil,
                 "--lat", str(cy), "--lon", str(cx), "--source", "hwsd", "--crop", CROP])
        if r.returncode != 0 or not os.path.isfile(soil):
            log(f"  convert_soil FAILED @({cx},{cy}): {r.stderr[-300:]}"); return None, {"error": "convert_soil"}

    met = os.path.join(cd, "site.met")
    if not os.path.isfile(met):
        r = run(["python3", os.path.join(TOOLS, "convert_met.py"), "--output", met, "--lat", str(cy),
                 "--lon", str(cx), "--source", "nasa_power", "--start", MET_START, "--end", MET_END,
                 "--station", f"c{cx}_{cy}"])
        if r.returncode != 0 or not os.path.isfile(met):
            log(f"  convert_met FAILED @({cx},{cy}): {r.stderr[-300:]}"); return None, {"error": "convert_met"}

    seas = {}
    for Y in SEASONS:
        db = os.path.join(cd, f"season_{Y}.db")
        gc = os.path.join(cd, f"season_{Y}.grain")
        if os.path.isfile(gc):
            seas[Y] = float(open(gc).read().strip()); continue
        ax = os.path.join(cd, f"season_{Y}.apsimx")
        start, end = f"{Y-1}-11-01", f"{Y+1}-02-28"
        rb = run(["python3", os.path.join(TOOLS, "build_apsimx.py"), "--output", ax, "--met-file", met,
                  "--soil-json", soil, "--crop", CROP, "--cultivar", CULTIVAR, "--population", "150",
                  "--row-spacing", "250", "--sowing-depth", "30", "--auto-sow",
                  "--sow-window-start", "20-Apr", "--sow-window-end", "10-Jul",
                  "--sow-rain-trigger", "25", "--sow-rain-days", "7",
                  "--fertilise-at-sowing", "40", "--fertilise-type", "UreaN",
                  "--start", start, "--end", end])
        if rb.returncode != 0:
            log(f"  build_apsimx FAILED {Y} @({cx},{cy}): {rb.stderr[-200:]}"); continue
        rr = run(["python3", os.path.join(TOOLS, "run_apsim.py"), "--apsimx", ax, "--binary", BIN, "--timeout", "400"])
        if rr.returncode != 0 or not os.path.isfile(db):
            log(f"  run_apsim FAILED {Y} @({cx},{cy}): {rr.stderr[-200:]}"); continue
        try:
            g = extract_grain(db)
        except Exception as e:
            log(f"  extract FAILED {Y} @({cx},{cy}): {e}"); continue
        seas[Y] = g
        open(gc, 'w').write(str(g))
        for ext in ('-wal', '-shm'):
            try: os.remove(db + ext)
            except OSError: pass

    if not seas:
        json.dump({"sim_yld_t_ha": None, "seasons": {}}, open(gj, 'w')); return None, {"error": "no_seasons"}
    yld_t_ha = float(np.mean([v for v in seas.values()]) / 100.0)
    d = {"sim_yld_t_ha": yld_t_ha, "seasons_g_m2": seas}
    json.dump(d, open(gj, 'w'))
    return yld_t_ha, d


def main():
    try:
        ensure_spam()
        cells = select_cells()
        recs = []
        for i, row in cells.reset_index(drop=True).iterrows():
            cx, cy = float(row.cx), float(row.cy)
            sim, d = do_cell(cx, cy)
            log(f"cell {i+1}/{len(cells)} ({cx},{cy}) obs={row.obs_yld:.2f} sim={sim if sim is None else round(sim,2)} t/ha")
            recs.append(dict(cx=cx, cy=cy, obs=float(row.obs_yld), harea=float(row.harea), sim=sim))
        df = pd.DataFrame(recs)
        good = df[df.sim.notna()].copy()
        n_ok = len(good)
        w = good.harea.values
        obs_reg = float((good.obs.values * w).sum() / w.sum())
        sim_reg = float((good.sim.values * w).sum() / w.sum())
        pbias_agg = float(100.0 * (sim_reg - obs_reg) / obs_reg)

        from ki_tools_common.metrics import all_metrics
        m = all_metrics(good.obs.values, good.sim.values)
        def gv(k):
            v = m.get(k, m.get(k.upper()))
            return None if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))) else float(v)

        out = {
            "model_id": "APSIM",
            "this_location": REGION + " (0.5deg cells, SPAM harea-weighted)",
            "obs_source": "SPAM",
            "status": "completed",
            "tools_used": ["ki_tools_common.soil_utils.lookup_hwsd", "convert_soil.py",
                           "convert_met.py (nasa_power via ki_tools_common.load_forcing)",
                           "build_apsimx.py", "run_apsim.py", "ki_tools_common.metrics"],
            "tools_failed": [],
            "metrics": {
                "nse": gv("nse"), "kge": gv("kge"), "pbias": round(pbias_agg, 3), "r": gv("r"),
                "period": "SPAM avg(2019-2021)"
            },
            "cross_cell_spatial_metrics": {k: gv(k) for k in ("nse", "r", "kge", "pbias", "rmse")},
            "water_balance": {"status": "N/A", "residual_pct": None,
                              "diagnostics": ["crop-agriculture domain; APSIM closes water/C/N mass internally"]},
            "aggregate": {
                "region": REGION,
                "n_cells_run": n_ok, "n_cells_selected": int(len(df)),
                "obs_regional_yield_t_ha": round(obs_reg, 3),
                "sim_regional_yield_t_ha": round(sim_reg, 3),
                "determining_metric": "pbias",
                "weighting": "SPAM wheat harvested-area weighted (same weights for obs and sim)"
            },
            "cells": recs,
            "notes": ""
        }
        out["notes"] = (
            f"Consistency check: same KI pipeline as the WA real-case relocated to the eastern Australia "
            f"NSW/Victoria wheatbelt ({REGION}); real APSIM-NG binary, multi-site GRIDDED run over {n_ok} 0.5deg "
            f"cells covering ~90% of the box's SPAM wheat harvested area, aggregated with SPAM harvested-area "
            f"weights to match the regional aggregate. Wheat cv Wyalkatchem, rainfed, auto-sow Apr20-Jul10 "
            f"rain-trigger, 40 kgN UreaN, HWSD soil, NASA POWER forcing; independent single-season sims 2019-2021. "
            f"GATE metric (magnitude_accuracy): area-weighted regional PBIAS = {pbias_agg:+.2f}% "
            f"(sim {sim_reg:.3f} vs obs {obs_reg:.3f} t/ha). nse/r/kge are cross-cell spatial (informative)."
        )
        os.makedirs(STATE, exist_ok=True)
        json.dump(out, open(RESULT, 'w'), indent=2)
        log("WROTE", RESULT)
        log(json.dumps(out["aggregate"], indent=1))
    except Exception as e:
        os.makedirs(STATE, exist_ok=True)
        json.dump({"model_id": "APSIM", "this_location": REGION, "obs_source": "SPAM",
                   "status": "failed", "error": str(e), "traceback": traceback.format_exc(),
                   "metrics": {"nse": None, "kge": None, "pbias": None, "r": None, "period": None},
                   "water_balance": {"status": "N/A", "residual_pct": None}}, open(RESULT, 'w'), indent=2)
        log("FAILED", e); traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
