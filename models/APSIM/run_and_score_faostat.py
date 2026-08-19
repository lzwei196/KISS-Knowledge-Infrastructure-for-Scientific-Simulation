#!/usr/bin/env python3
"""
run_and_score_faostat.py — APSIM-NG single-point wheat run vs FAOSTAT national yield.

VERIFIER (verify_1) consistency point for the APSIM KI. The Real-case (SPAM WA
wheatbelt box) and the earlier canonical FAOSTAT case are both AUSTRALIA. To test
whether the SAME KI recipe generalises to a DIFFERENT location (i.e. is not overfit
to the WA wheatbelt), this run moves to ARGENTINA: a nationally-representative point
in the SW Buenos Aires wheat belt, scored against FAOSTAT Argentina national wheat
yield (element 5412, kg/ha), 1984-2020.

obs_shape = regional_aggregate_time_series -> gate-valid families [trend_match,
magnitude_accuracy]. A single rainfed point cannot reproduce a national aggregate's
smooth technology trend, so raw NSE/KGE are off-family (reported per all-or-nothing
all_metrics() rule); the GATE metrics are magnitude_accuracy (PBIAS) and trend_match
(detrended / first-difference r on the interannual weather-driven anomaly).

Pipeline per season — uses ONLY the KI tools (identical recipe to the Australia case):
  ki_tools_common.soil_utils.lookup_hwsd  -> HWSD 2-layer extract CSV
  tools/convert_soil.py --source hwsd      -> APSIM soil JSON
  tools/convert_met.py --source nasa_power -> APSIM .met
  tools/build_apsimx.py                    -> .apsimx (Wyalkatchem, auto-sow, 40 kgN UreaN, rainfed)
  tools/run_apsim.py                       -> real APSIM-NG binary
  (sqlite read of Report.Grain.Wt peak)    -> grain g/m^2 -> t/ha (/100)

Each season is an INDEPENDENT single-season sim (window (Y-1)-11-01 .. (Y+1)-02-28,
one austral-autumn/winter sow window) so there is no stalled-crop cascade and no
continuous-monoculture N-mining (see project memory).

RESUMABLE: each season writes season_Y.grain; a relaunch skips completed seasons.
"""
import os, sys, json, csv, subprocess, traceback
import numpy as np

ROOT = "KISSPATH_KI_ROOT/APSIM"
KI   = os.path.join(ROOT, "knowledge_infrastructure")
TOOLS= os.path.join(KI, "tools")
BIN  = "KISSPATH_BINARIES/APSIM/source/repo/bin/Release/net8.0/apsim"
STATE= os.path.join(ROOT, "detached", "verify_1")
WORK = os.path.join(STATE, "work")
RESULT = os.path.join(STATE, "result.json")

FAOSTAT = ("KISSPATH_OBS/faostat/"
           "Production_Crops_Livestock_E_All_Data/Production_Crops_Livestock_E_All_Data_NOFLAG.csv")
COUNTRY = "Argentina"
ITEM    = "Wheat"
ELEMENT = "5412"          # Yield, unit kg/ha

# Nationally-representative point: SW Buenos Aires wheat belt (core Argentine wheat area,
# rainfed, ~700-800 mm) — the Argentine analogue of Merredin WA for Australia.
LAT, LON = -36.0, -61.5
SITE = "SW_BuenosAires_wheatbelt"
CROP, CULTIVAR = "Wheat", "Wyalkatchem"
YEARS = list(range(1984, 2021))       # NASA POWER radiation record starts 1984; FAOSTAT to 2020
MET_START, MET_END = "1983-11-01", "2021-02-28"
# Argentine winter-wheat sowing window (austral late-autumn/winter). Same rain-trigger
# auto-sow mechanism as the Australia recipe; only the calendar window is localised.
SOW_START, SOW_END = "20-May", "31-Jul"

SMOKE = os.environ.get("SMOKE")       # if set, run only the first N seasons (inline smoke test)

ENV = dict(os.environ, DOTNET_ROOT="KISSPATH_HOME/.dotnet")
os.makedirs(WORK, exist_ok=True)


def log(*a):
    print("[faostat]", *a, flush=True)


def run(cmd, **kw):
    return subprocess.run(cmd, env=ENV, capture_output=True, text=True, **kw)


def load_obs():
    """FAOSTAT national wheat yield (kg/ha) -> {year: t/ha}."""
    with open(FAOSTAT, encoding="latin-1") as f:
        r = csv.reader(f)
        hdr = next(r)
        idx = {h: i for i, h in enumerate(hdr)}
        ycols = [(int(h[1:]), i) for h, i in idx.items() if h.startswith("Y") and h[1:].isdigit()]
        for row in r:
            if (row[idx["Area"]] == COUNTRY and row[idx["Item"]] == ITEM
                    and row[idx["Element Code"]] == ELEMENT):
                out = {}
                for yr, i in ycols:
                    v = row[i]
                    if v not in ("", "0.000000") and float(v) > 0:
                        out[yr] = float(v) / 1000.0     # kg/ha -> t/ha
                return out
    raise RuntimeError("FAOSTAT series not found for %s/%s/%s" % (COUNTRY, ITEM, ELEMENT))


def extract_grain(db):
    import sqlite3, pandas as pd
    c = sqlite3.connect(db)
    try:
        df = pd.read_sql("SELECT * FROM Report", c)
    finally:
        c.close()
    gcol = [x for x in df.columns if "Grain.Wt" in x and "Total" not in x][0]
    return float(df[gcol].max())      # g/m^2 (peak = grain at maturity)


def ensure_soil_met(cd):
    soil = os.path.join(cd, "soil.json")
    if not os.path.isfile(soil):
        import ki_tools_common.soil_utils as su
        s = su.lookup_hwsd(LAT, LON)
        hcsv = os.path.join(cd, "hwsd.csv")
        rows = [
            dict(depth_top_cm=0, depth_bot_cm=30, sand_pct=s['sand'], clay_pct=s['clay'],
                 bulk_density_kg_m3=s['bulk_density'], organic_carbon_g_kg=s['oc'], ph_water=s['ph']),
            dict(depth_top_cm=30, depth_bot_cm=100, sand_pct=s['sub_sand'], clay_pct=s['sub_clay'],
                 bulk_density_kg_m3=s['bulk_density'], organic_carbon_g_kg=max(0.1, s['oc'] * 0.4), ph_water=s['ph']),
        ]
        with open(hcsv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
        r = run(["python3", os.path.join(TOOLS, "convert_soil.py"), "--input", hcsv, "--output", soil,
                 "--lat", str(LAT), "--lon", str(LON), "--source", "hwsd", "--crop", CROP])
        if r.returncode != 0 or not os.path.isfile(soil):
            raise RuntimeError("convert_soil failed: " + r.stderr[-500:])
    met = os.path.join(cd, "site.met")
    if not os.path.isfile(met):
        r = run(["python3", os.path.join(TOOLS, "convert_met.py"), "--output", met, "--lat", str(LAT),
                 "--lon", str(LON), "--source", "nasa_power", "--start", MET_START, "--end", MET_END,
                 "--station", SITE])
        if r.returncode != 0 or not os.path.isfile(met):
            raise RuntimeError("convert_met failed: " + r.stderr[-500:])
    return soil, met


def do_season(cd, soil, met, Y):
    gc = os.path.join(cd, f"season_{Y}.grain")
    if os.path.isfile(gc):
        txt = open(gc).read().strip()
        return None if txt in ("", "None") else float(txt)
    ax = os.path.join(cd, f"season_{Y}.apsimx")
    db = os.path.join(cd, f"season_{Y}.db")
    start, end = f"{Y-1}-11-01", f"{Y+1}-02-28"
    rb = run(["python3", os.path.join(TOOLS, "build_apsimx.py"), "--output", ax, "--met-file", met,
              "--soil-json", soil, "--crop", CROP, "--cultivar", CULTIVAR, "--population", "150",
              "--row-spacing", "250", "--sowing-depth", "30", "--auto-sow",
              "--sow-window-start", SOW_START, "--sow-window-end", SOW_END,
              "--sow-rain-trigger", "25", "--sow-rain-days", "7",
              "--fertilise-at-sowing", "40", "--fertilise-type", "UreaN",
              "--start", start, "--end", end])
    if rb.returncode != 0:
        log(f"  build FAILED {Y}: {rb.stderr[-300:]}"); open(gc, "w").write("None"); return None
    rr = run(["python3", os.path.join(TOOLS, "run_apsim.py"), "--apsimx", ax, "--binary", BIN, "--timeout", "400"])
    if rr.returncode != 0 or not os.path.isfile(db):
        log(f"  run FAILED {Y}: {rr.stderr[-300:]}"); open(gc, "w").write("None"); return None
    try:
        g = extract_grain(db)
    except Exception as e:
        log(f"  extract FAILED {Y}: {e}"); open(gc, "w").write("None"); return None
    open(gc, "w").write(str(g))
    for ext in ("-wal", "-shm"):
        try: os.remove(db + ext)
        except OSError: pass
    return g


def detrended_r(obs, sim):
    """Pearson r on linearly-detrended series (trend_match determining metric)."""
    n = len(obs)
    if n < 4:
        return None
    t = np.arange(n, dtype=float)
    def resid(y):
        a, b = np.polyfit(t, y, 1)
        return y - (a * t + b)
    ro, rs = resid(obs), resid(sim)
    if np.std(ro) == 0 or np.std(rs) == 0:
        return None
    return float(np.corrcoef(ro, rs)[0, 1])


def firstdiff_r(obs, sim):
    do, ds = np.diff(obs), np.diff(sim)
    if len(do) < 3 or np.std(do) == 0 or np.std(ds) == 0:
        return None
    return float(np.corrcoef(do, ds)[0, 1])


def main():
    try:
        obs = load_obs()
        cd = os.path.join(WORK, SITE)
        os.makedirs(cd, exist_ok=True)
        soil, met = ensure_soil_met(cd)

        years = [y for y in YEARS if y in obs]
        if SMOKE:
            years = years[:int(SMOKE)]
        sim = {}
        for Y in years:
            g = do_season(cd, soil, met, Y)
            sim[Y] = None if g is None else g / 100.0     # g/m^2 -> t/ha
            log(f"season {Y} obs={obs.get(Y):.2f} sim={'None' if g is None else round(sim[Y],2)} t/ha")

        pairs = [(obs[y], sim[y]) for y in years if sim.get(y) is not None]
        o = np.array([p[0] for p in pairs], float)
        s = np.array([p[1] for p in pairs], float)
        n_ok = len(pairs)

        from ki_tools_common.metrics import all_metrics
        m = all_metrics(o, s) if n_ok >= 2 else {}
        def gv(k):
            v = m.get(k, m.get(k.upper()))
            return None if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))) else float(v)

        pbias = gv("pbias")
        r_det = detrended_r(o, s) if n_ok >= 4 else None
        r_fd  = firstdiff_r(o, s) if n_ok >= 4 else None

        out = {
            "model_id": "APSIM",
            "this_location": "FAOSTAT Global Production — Crops & Livestock (1961–2024)",
            "obs_source": "FAOSTAT",
            "status": "completed" if n_ok >= 2 else "failed",
            "tools_used": ["ki_tools_common.soil_utils.lookup_hwsd", "convert_soil.py",
                           "convert_met.py (nasa_power via ki_tools_common.load_forcing)",
                           "build_apsimx.py", "run_apsim.py", "ki_tools_common.metrics"],
            "tools_failed": [],
            "metrics": {
                "nse": gv("nse"), "kge": gv("kge"), "pbias": None if pbias is None else round(pbias, 3),
                "r": gv("r"), "r_detrended": None if r_det is None else round(r_det, 3),
                "r_firstdiff": None if r_fd is None else round(r_fd, 3),
                "rmse": gv("rmse"),
                "period": f"{years[0]}-{years[-1]} (n={n_ok} paired years)"
            },
            "water_balance": {"status": "N/A", "residual_pct": None,
                              "diagnostics": ["crop-agriculture domain; APSIM closes water/C/N mass internally"]},
            "obs_shape": "regional_aggregate_time_series",
            "determining_metric": "trend_match(r_detrended) + magnitude_accuracy(pbias)",
            "location_detail": {"country": COUNTRY, "site": SITE, "lat": LAT, "lon": LON,
                                "cultivar": CULTIVAR, "obs_mean_t_ha": round(float(o.mean()), 3) if n_ok else None,
                                "sim_mean_t_ha": round(float(s.mean()), 3) if n_ok else None,
                                "n_years": n_ok, "n_seasons_failed": len(years) - n_ok},
            "series": {str(y): {"obs": round(obs[y], 3), "sim": None if sim.get(y) is None else round(sim[y], 3)}
                       for y in years},
            "notes": ""
        }
        out["notes"] = (
            f"Real APSIM-NG binary, single nationally-representative point ({LAT},{LON}, SW Buenos Aires "
            f"wheat belt) vs FAOSTAT ARGENTINA national wheat yield (element 5412 kg/ha), {years[0]}-{years[-1]}, "
            f"{n_ok} paired years. Identical KI recipe to the validated Australia FAOSTAT case (cv Wyalkatchem, "
            f"rainfed, 40 kgN UreaN, HWSD soil, NASA POWER forcing, independent single-season sims), only the "
            f"location and the austral sowing window (20-May..31-Jul) localised — a DIFFERENT location than the "
            f"WA wheatbelt so this tests recipe generalisation, not overfitting. GATE metrics (obs_shape="
            f"regional_aggregate_time_series): magnitude_accuracy PBIAS={pbias}%%, trend_match r_detrended={r_det}, "
            f"r_firstdiff={r_fd} (sim mean {s.mean():.2f} vs obs mean {o.mean():.2f} t/ha). Raw NSE/KGE off-family "
            f"(a single rainfed point cannot follow a national technology trend); reported per all_metrics rule."
        )
        os.makedirs(STATE, exist_ok=True)
        json.dump(out, open(RESULT, "w"), indent=2)
        log("WROTE", RESULT)
        log(json.dumps(out["metrics"], indent=1))
    except Exception as e:
        os.makedirs(STATE, exist_ok=True)
        json.dump({"model_id": "APSIM", "this_location": "FAOSTAT", "status": "failed",
                   "error": str(e), "traceback": traceback.format_exc()}, open(RESULT, "w"), indent=2)
        log("FAILED", e); traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    sys.path.insert(0, KI)
    main()
