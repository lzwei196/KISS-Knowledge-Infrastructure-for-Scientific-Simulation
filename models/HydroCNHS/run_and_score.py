#!/usr/bin/env python3
"""HydroCNHS VERIFIER #4: Southwest Miramichi River at Blackville (01BO001), NB, Canada.

DIFFERENT location from the real-case (九江 Jiujiang, Yangtze). Same KI tools,
end-to-end, resumable at every stage.

Gauge: HYDAT 01BO001 SOUTHWEST MIRAMICHI RIVER AT BLACKVILLE, New Brunswick,
46.736N / -65.826E, RHBN reference station, natural (unregulated), humid-maritime
snowmelt regime. HYDAT gross drainage area 5,050 km2; the ECCC drainage-basin
polygon (HydrometricNetworkBasinPolygons, MDA region 01) gives 5,127 km2 — used
here for the model area and as the areal-mean forcing footprint. Daily discharge
2000-2019 is 100% complete.

Obs: HYDAT SQLite DLY_FLOWS (FLOW1..FLOW31 monthly-wide -> daily long), values in
m3/s (cms), directly comparable to the model's native Q_routed (cms). No sentinel
scaling; NULL cells -> NaN.

Domain: the ECCC drainage-basin polygon for 01BO001 (reprojected to EPSG:4326).
MSWX 0.1deg cells whose centre falls inside the polygon (59 cells) are the
areal-mean footprint (cos-lat weighted), matching the verify_3 (Miyun) recipe but
with MSWX instead of CMFD because Miramichi is outside the CMFD (China) domain.

Forcing: LOCAL MSWX global 0.1deg 3-hourly (aggregated to daily by the KI loader:
precip summed mm/day, temp averaged degC), basin-mean over the 59 cells, loaded via
ki_tools_common.load_daily_forcing_points(source='mswx'). It is a LOCAL product
covering the basin exactly (no network fetch, no hang risk). PET auto-Hamon
(matches real-case). Humid-maritime P/T asserted to a wide plausible range.

Period: sim 2000-2019 (spinup 2000-2001 = 2-yr warmup), cal 2002-2011,
val 2012-2019. MSWX starts 1979; 2000-2019 chosen for full MSWX coverage and 100%
obs completeness.

Pipeline (each stage skips itself if its output exists, so a relaunch resumes):
  S0  geometry     59 MSWX cells inside the ECCC polygon + centroid lat
  S1  forcing      MSWX daily 2000-2019 basin-mean -> per-year pkl -> Miramichi.csv
  S1b climate      KI convert_climate_inputs.py (mm->cm) -> climate.json/pickle
  S2/S3 config     KI convert_parameters.py + build_model_config.py -> model.yaml
  S4  observed     HYDAT 01BO001 DLY_FLOWS (cms) -> observed.pickle + full csv
  S5  calibrate    KI run_hydrocnhs.py --mode calibrate (GA, KGE on cal window)
  S6  simulate     KI run_hydrocnhs.py --mode simulate -> sim_results.pickle
  S7  parse        KI parse_output.py -> simulated.csv + metrics
  S8  score        ki_tools_common.metrics.all_metrics + standard_calval -> result.json
"""
import calendar
import json
import os
import pickle
import subprocess
import sys
import traceback
from datetime import datetime

MODEL_ROOT = "/mnt/disk1/Hydrocraft_server/models/HydroCNHS"
KI_TOOLS = f"{MODEL_ROOT}/knowledge_infrastructure/tools"
HCNHS_SRC = f"{MODEL_ROOT}/source/repo/src"
STATE_DIR = f"{MODEL_ROOT}/detached/verify_4"
WORK = f"{STATE_DIR}/work"
FORC_CACHE = f"{WORK}/forcing"
RESULT_JSON = f"{STATE_DIR}/result.json"

MSWX_DIR = "/mnt/disk3/msxw"
HYDAT_DB = ("/mnt/datasets/observed_data/dischargeandwatershed/"
            "National Water Data Archive HYDAT/Hydat.sqlite3")
BASIN_GPKG = ("/mnt/datasets/observed_data/dischargeandwatershed/"
              "National Water Data Archive HYDAT/HydrometricNetworkBasinPolygons/"
              "gpkg/MDA_ADP_01.gpkg")
BASIN_LAYER = "DrainageBasin_BassinDeDrainage"
STATION = "01BO001"

OUTLET = "Miramichi"
AREA_KM2 = 5126.594               # ECCC drainage-basin polygon area
AREA_HA = AREA_KM2 * 100.0        # dt_005: model wants hectares
Y0, Y1 = 2000, 2019               # sim window (2000-2001 = spinup/warmup)
START_DATE = "2000/1/1"           # model date format YYYY/M/D
CAL0, CAL1 = "2002-01-01", "2011-12-31"
VAL0, VAL1 = "2012-01-01", "2019-12-31"
GA_POP, GA_GEN, GA_SEED = 48, 60, 42

sys.path.append("/mnt/disk1/Hydrocraft_server/models/ki_tools_common")
sys.path.append(HCNHS_SRC)  # sim_results.pickle holds a hydrocnhs dc object

ENV = dict(os.environ)
ENV["PYTHONPATH"] = HCNHS_SRC
PY = "/usr/bin/python3"

os.makedirs(WORK, exist_ok=True)
os.makedirs(FORC_CACHE, exist_ok=True)
STAGE_LOG = []


def log(msg):
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    STAGE_LOG.append(line)


def run_tool(cmd, tag):
    log(f"RUN {tag}: {' '.join(cmd)}")
    r = subprocess.run(cmd, env=ENV, cwd=WORK, capture_output=True, text=True)
    tail = (r.stdout + r.stderr)[-3000:]
    log(f"{tag} rc={r.returncode}\n{tail}")
    if r.returncode != 0:
        raise RuntimeError(f"{tag} failed rc={r.returncode}: {tail[-800:]}")
    return r


def write_result(obj):
    tmp = RESULT_JSON + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
    os.replace(tmp, RESULT_JSON)
    log(f"result.json written ({obj.get('status')})")


def lower_keys(d):
    return {k.lower(): v for k, v in d.items()}


# ---------------------------------------------------------------- S0 geometry
def stage_geometry():
    """MSWX 0.1deg cells whose centre falls inside the ECCC 01BO001 polygon."""
    import math
    cj = f"{WORK}/basin_cells.json"
    if os.path.exists(cj):
        d = json.load(open(cj))
        cells = [tuple(c) for c in d["cells"]]
        log(f"geometry: cached {len(cells)} cells, centroid lat {d['clat']:.3f}")
        return cells, d["weights"], d["clat"]
    import geopandas as gpd
    import h5py
    import numpy as np
    from shapely.geometry import Point
    g = gpd.read_file(BASIN_GPKG, layer=BASIN_LAYER)
    row = g[g["StationNum"] == STATION].to_crs("EPSG:4326")
    assert len(row) == 1, f"station {STATION} not found in polygon set"
    poly = row.geometry.union_all() if hasattr(row.geometry, "union_all") \
        else row.geometry.unary_union
    minx, miny, maxx, maxy = poly.bounds
    with h5py.File(os.path.join(MSWX_DIR, "P", f"P_{Y0}.nc"), "r") as f:
        glat = np.asarray(f["lat"][:])
        glon = np.asarray(f["lon"][:])
    la_in = glat[(glat >= miny - 0.1) & (glat <= maxy + 0.1)]
    lo_in = glon[(glon >= minx - 0.1) & (glon <= maxx + 0.1)]
    cells = []
    for la in la_in:
        for lo in lo_in:
            if poly.contains(Point(float(lo), float(la))):
                cells.append((round(float(la), 2), round(float(lo), 2)))
    assert 30 < len(cells) < 120, f"unexpected cell count {len(cells)}"
    weights = [math.cos(math.radians(la)) for la, _ in cells]
    clat = sum(la * w for (la, _), w in zip(cells, weights)) / sum(weights)
    json.dump({"cells": cells, "weights": weights, "clat": clat}, open(cj, "w"))
    log(f"geometry: {len(cells)} MSWX cells in polygon, centroid lat {clat:.3f}, "
        f"area {AREA_KM2:.0f} km2")
    return cells, weights, clat


# ---------------------------------------------------------------- S1 forcing
def stage_forcing(cells, weights):
    from ki_tools_common.load_forcing import load_daily_forcing_points
    import numpy as np
    import pandas as pd

    frames = []
    for year in range(Y0, Y1 + 1):
        cpath = f"{FORC_CACHE}/mean_{year}.pkl"
        if os.path.exists(cpath):
            frames.append(pickle.load(open(cpath, "rb")))
            log(f"forcing {year}: cached")
            continue
        log(f"forcing {year}: loading MSWX daily ({len(cells)} cells)...")
        recs = load_daily_forcing_points("mswx", cells, year, year,
                                         forcing_dir=MSWX_DIR)
        n = len(recs[0]["dates"])
        wsum = float(np.sum(weights))
        tm = np.zeros(n)
        pm = np.zeros(n)
        for rec, w in zip(recs, weights):
            tm += np.asarray(rec["temp_mean_c"]) * w
            pm += np.asarray(rec["precip_mm"]) * w
        tm /= wsum
        pm /= wsum
        fr = {"dates": [pd.Timestamp(d).strftime("%Y-%m-%d")
                        for d in recs[0]["dates"]],
              "temp_c": tm.tolist(), "prec_mm": pm.tolist()}
        pickle.dump(fr, open(cpath, "wb"))
        frames.append(fr)
        log(f"forcing {year}: {n} days, P={pm.mean()*365.25:.0f} mm/yr, "
            f"T={tm.mean():.2f} C")

    dates = sum((f["dates"] for f in frames), [])
    temp = sum((f["temp_c"] for f in frames), [])
    prec = sum((f["prec_mm"] for f in frames), [])
    idx = pd.to_datetime(dates)
    assert idx.is_monotonic_increasing and (idx[1:] - idx[:-1]).max().days == 1, \
        "forcing dates not contiguous"
    p_ann = float(np.mean(prec)) * 365.25
    t_mean = float(np.mean(temp))
    assert 700 < p_ann < 1800, f"annual P {p_ann:.0f} mm implausible for Miramichi"
    assert -2 < t_mean < 12, f"mean T {t_mean:.1f} C implausible for Miramichi"
    assert not (np.isnan(temp).any() or np.isnan(prec).any()), "NaNs in forcing"
    assert min(temp) > -50 and max(temp) < 45, "temp out of range (unit?)"
    assert min(prec) >= 0 and max(prec) < 400, "prec out of range (unit?)"
    df = pd.DataFrame({"date": dates, "temp": temp, "prec": prec})
    df.to_csv(f"{WORK}/{OUTLET}.csv", index=False)
    log(f"forcing total: {len(dates)} days {dates[0]}..{dates[-1]}, "
        f"P={p_ann:.0f} mm/yr, T={t_mean:.2f} C")
    return dates[-1], len(dates), p_ann, t_mean


# ------------------------------------------------------- S1b climate convert
def stage_climate(end_date_iso, ndays):
    d = datetime.strptime(end_date_iso, "%Y-%m-%d")
    end_str = f"{d.year}/{d.month}/{d.day}"
    cj = f"{WORK}/climate.json"
    if not os.path.exists(cj):
        run_tool([PY, f"{KI_TOOLS}/convert_climate_inputs.py",
                  "--input-dir", WORK, "--outlets", OUTLET,
                  "--start-date", START_DATE, "--end-date", end_str,
                  "--temp-unit", "C", "--prec-unit", "mm",
                  "--output", cj], "convert_climate_inputs")
    o = json.load(open(cj))["output"]
    assert len(o["prec"][OUTLET]) == ndays, "climate.json length mismatch"
    with open(f"{WORK}/climate.pickle", "wb") as f:
        pickle.dump({"temp": o["temp"], "prec": o["prec"]}, f)
    log(f"climate.pickle: {ndays} days, prec unit cm/day")
    return end_str


# -------------------------------------------------------------- S2/S3 config
def stage_config(end_str, clat):
    pj = f"{WORK}/params.json"
    if not os.path.exists(pj):
        run_tool([PY, f"{KI_TOOLS}/convert_parameters.py",
                  "--outlets", OUTLET, "--model", "GWLF",
                  "--default-soil-group", "B",
                  "--default-land-use", "forest",
                  "--output", pj], "convert_parameters")
    my = f"{WORK}/model.yaml"
    if not os.path.exists(my):
        run_tool([PY, f"{KI_TOOLS}/build_model_config.py",
                  "--start-date", START_DATE, "--end-date", end_str,
                  "--outlets", OUTLET, "--areas", str(AREA_HA),
                  "--latitudes", f"{clat:.4f}", "--runoff-model", "GWLF",
                  "--routing-outlet", OUTLET, "--upstream-outlets", OUTLET,
                  "--flow-lengths", "0", "--params-json", pj,
                  "--working-dir", WORK, "--output", my], "build_model_config")


# ----------------------------------------------------------------- S4 observed
def stage_observed(ndays):
    import sqlite3
    import numpy as np
    import pandas as pd

    con = sqlite3.connect(HYDAT_DB)
    cols = ["FLOW" + str(i) for i in range(1, 32)]
    recs = {}
    q = ("SELECT YEAR,MONTH," + ",".join(cols) +
         " FROM DLY_FLOWS WHERE STATION_NUMBER=? AND YEAR BETWEEN ? AND ?"
         " ORDER BY YEAR,MONTH")
    for rr in con.execute(q, (STATION, Y0, Y1)):
        y, m = rr[0], rr[1]
        nd = calendar.monthrange(y, m)[1]
        for d in range(nd):
            v = rr[2 + d]
            recs[pd.Timestamp(y, m, d + 1)] = np.nan if v is None else float(v)
    con.close()
    s = pd.Series(recs).sort_index()
    idx = pd.date_range(datetime.strptime(START_DATE, "%Y/%m/%d"),
                        periods=ndays, freq="D")
    q_full = s.reindex(idx)
    log(f"obs: HYDAT {STATION} valid {int(q_full.notna().sum())}/{ndays}, "
        f"mean {q_full.mean():.2f} cms, max {q_full.max():.0f} cms")
    q_cal = q_full.copy()
    mask = (idx >= CAL0) & (idx <= CAL1)
    q_cal[~mask] = np.nan
    n_cal = int(q_cal.notna().sum())
    assert n_cal > 2500, f"cal-window obs too sparse: {n_cal}"
    with open(f"{WORK}/observed.pickle", "wb") as f:
        pickle.dump({OUTLET: q_cal.values.tolist()}, f)
    pd.DataFrame({f"Q_{OUTLET}_cms": q_full.values}, index=idx).rename_axis(
        "date").to_csv(f"{WORK}/observed_full.csv")
    log(f"observed.pickle: {n_cal} cal days ({CAL0}..{CAL1})")
    return q_full


# ---------------------------------------------------------- S5/S6 calibrate/run
def stage_calibrate():
    cm = f"{WORK}/calibrated_model.yaml"
    if os.path.exists(cm):
        log("calibrated_model.yaml exists — skip GA")
        return
    run_tool([PY, f"{KI_TOOLS}/run_hydrocnhs.py", "--mode", "calibrate",
              "--model", f"{WORK}/model.yaml",
              "--climate-pickle", f"{WORK}/climate.pickle",
              "--observed-pickle", f"{WORK}/observed.pickle",
              "--generations", str(GA_GEN), "--population", str(GA_POP),
              "--seed", str(GA_SEED), "--cali-name", "Cali_Miramichi",
              "--output", cm], "run_hydrocnhs.calibrate")


def stage_simulate():
    sp = f"{WORK}/sim_results.pickle"
    if not os.path.exists(sp):
        run_tool([PY, f"{KI_TOOLS}/run_hydrocnhs.py", "--mode", "simulate",
                  "--model", f"{WORK}/calibrated_model.yaml",
                  "--climate-pickle", f"{WORK}/climate.pickle",
                  "--output", f"{WORK}/sim_results.json"],
                 "run_hydrocnhs.simulate")
    return sp


# ------------------------------------------------------------------ S7 parse
def stage_parse():
    mj = f"{WORK}/metrics_full.json"
    if not os.path.exists(mj):
        run_tool([PY, f"{KI_TOOLS}/parse_output.py",
                  "--results-pickle", f"{WORK}/sim_results.pickle",
                  "--observed-csv", f"{WORK}/observed_full.csv",
                  "--start-date", START_DATE, "--warmup-years", "2",
                  "--output-csv", f"{WORK}/simulated.csv",
                  "--metrics-json", mj,
                  "--plot", f"{WORK}/validation.png"], "parse_output")


# ------------------------------------------------------------------ S8 score
def stage_score(ndays, q_full, p_ann, t_mean, n_cells):
    import importlib.util
    import numpy as np
    import pandas as pd
    from ki_tools_common.metrics import all_metrics

    spec = importlib.util.spec_from_file_location(
        "standard_calval",
        "/home/server/knowledge-dissection-toolkit/auto_dissect_multi_agent/"
        "validators/standard_calval.py")
    scv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scv)

    with open(f"{WORK}/sim_results.pickle", "rb") as f:
        res = pickle.load(f)
    sim = np.asarray(res["Q_routed"][OUTLET], dtype=float)
    assert len(sim) == ndays and not np.isnan(sim).any(), "sim length/NaN check"
    idx = pd.date_range(datetime.strptime(START_DATE, "%Y/%m/%d"),
                        periods=ndays, freq="D")
    sim_s = pd.Series(sim, index=idx)
    obs_s = q_full

    post = idx >= CAL0
    pair = post & obs_s.notna().values
    m_full = lower_keys(all_metrics(obs_s[pair].values, sim_s[pair].values))
    n_paired = int(pair.sum())

    cv = scv.compute_calval_metrics(
        list(idx), obs_s.values, sim_s.values,
        cal_start=CAL0, cal_end=CAL1, val_start=VAL0, val_end=VAL1)
    cal = lower_keys(cv.get("calibration", {}))
    val = lower_keys(cv.get("validation", {}))

    diag = []
    wb_status, wb_res_mm, wb_res_pct = "N/A", None, None
    try:
        dc = res.get("dc")
        pet_cm = np.asarray(dc.pet[OUTLET], dtype=float)
        prec_cm = np.asarray(dc.prec[OUTLET], dtype=float)
        yrs = ndays / 365.25
        p_mm = prec_cm.sum() * 10 / yrs
        pet_mm = pet_cm.sum() * 10 / yrs
        q_mm = sim.mean() * 86400 * 365.25 / (AREA_KM2 * 1e6) * 1000
        qobs_mm = obs_s[pair].mean() * 86400 * 365.25 / (AREA_KM2 * 1e6) * 1000
        rc = q_mm / p_mm if p_mm > 0 else None
        headroom = (p_mm - qobs_mm) / pet_mm if pet_mm > 0 else None
        diag = [
            f"P={p_mm:.0f} mm/yr, Hamon PET={pet_mm:.0f} mm/yr, "
            f"Q_sim={q_mm:.0f} mm/yr, Q_obs={qobs_mm:.0f} mm/yr",
            f"runoff coefficient={rc:.3f}" if rc is not None else "rc unavailable",
            (f"required Ea/PET headroom={headroom:.3f} (water-limited if <1; "
             f"GWLF ET cap = Kc*PET, Kc<=1.5)" if headroom is not None
             else "PET unavailable"),
            "AET and storage not exposed by the data collector "
            "(Q_routed/Q_runoff/prec/temp/pet only) — closure not computable "
            "from KI tool outputs; runoff coefficient used as unit sanity.",
        ]
    except Exception as e:
        diag = [f"water-balance diagnostics failed: {e}"]

    result = {
        "model_id": "HydroCNHS",
        "this_location": "Canada HYDAT SQLite Database (complete national archive)",
        "location": "Southwest Miramichi River at Blackville (HYDAT 01BO001), "
                    "New Brunswick, Canada",
        "obs_source": "Canada HYDAT SQLite Database (complete national archive)",
        "status": "completed",
        "ki_usable": True,
        "tools_used": [
            "geopandas/shapely (ECCC drainage-basin polygon 01BO001 -> MSWX cells)",
            "ki_tools_common.load_forcing.load_daily_forcing_points (mswx)",
            "convert_climate_inputs.py", "convert_parameters.py",
            "build_model_config.py", "run_hydrocnhs.py (--mode calibrate)",
            "run_hydrocnhs.py (--mode simulate)", "parse_output.py",
            "ki_tools_common.metrics.all_metrics",
            "validators.standard_calval.compute_calval_metrics",
        ],
        "tools_failed": [],
        "metrics": {
            "nse": m_full.get("nse"), "r": m_full.get("r"),
            "kge": m_full.get("kge"), "pbias": m_full.get("pbias"),
            "nse_cal": cal.get("nse"), "kge_cal": cal.get("kge"),
            "nse_val": val.get("nse"), "kge_val": val.get("kge"),
            "pbias_val": val.get("pbias"),
            "period": f"{CAL0}..{VAL1} (post-warmup)",
            "period_calibration": f"{CAL0}..{CAL1}",
            "period_validation": f"{VAL0}..{VAL1}",
        },
        "water_balance": {
            "status": wb_status, "residual_mm": wb_res_mm,
            "residual_pct": wb_res_pct, "diagnostics": diag,
        },
        "input_availability": {
            "all_required_reachable": True,
            "unreachable_required": [],
            "unreachable_optional": [],
            "degraded_mode": None,
        },
        "variable": "Q_routed",
        "obs_shape": "point_time_series",
        "test_runs": [{
            "location": "Southwest Miramichi River at Blackville (01BO001), NB, Canada",
            "variable": "Q_routed",
            "obs_shape": "point_time_series",
            "determining_metric": "nse",
            "n_paired_days": n_paired,
            "nse": m_full.get("nse"), "kge": m_full.get("kge"),
            "pbias": m_full.get("pbias"), "r": m_full.get("r"),
        }],
        "notes": (
            f"VERIFIER #4 — lumped GWLF + Lohmann self-routing over the Southwest "
            f"Miramichi River at Blackville catchment ({AREA_KM2:.0f} km2, HYDAT "
            f"01BO001, 46.74N/-65.83E, New Brunswick), a DIFFERENT location from "
            f"the humid Jiujiang/Yangtze real-case. Same KI tools end-to-end. "
            f"Domain = ECCC drainage-basin polygon; MSWX global 0.1deg daily "
            f"basin-mean over {n_cells} cells (cos-lat weighted), P={p_ann:.0f} "
            f"mm/yr, T={t_mean:.1f} C, via ki load_daily_forcing_points('mswx'); "
            f"PET auto-Hamon. Obs = HYDAT SQLite DLY_FLOWS for 01BO001 (m3/s, "
            f"natural/unregulated RHBN reference station, 100% complete 2000-2019), "
            f"comparable to model Q_routed (cms). Spinup 2000-01, "
            f"cal {CAL0}..{CAL1}, val {VAL0}..{VAL1}. GA pop {GA_POP} x gen "
            f"{GA_GEN}, KGE objective on cal window. A natural humid-maritime "
            f"snowmelt basin, an independent regime from the real-case; "
            f"real-case NSE was 0.636 (r 0.922, PBIAS -20.6)."
        ),
        "stage_log_tail": STAGE_LOG[-25:],
    }
    write_result(result)
    log(f"FINAL: nse={m_full.get('nse')}, nse_cal={cal.get('nse')}, "
        f"nse_val={val.get('nse')}, pbias={m_full.get('pbias')}, "
        f"r={m_full.get('r')}")


def main():
    missing = [p for p in (MSWX_DIR, BASIN_GPKG, HYDAT_DB)
               if not os.path.exists(p)]
    ia = {"all_required_reachable": not missing,
          "unreachable_required": missing, "unreachable_optional": [],
          "degraded_mode": None,
          "note": "all inputs local disk (MSWX, HYDAT sqlite, ECCC polygon gpkg); "
                  "no remote fetches"}
    with open(f"{STATE_DIR}/input_availability.json", "w") as f:
        json.dump(ia, f, indent=2)
    if missing:
        write_result({"model_id": "HydroCNHS",
                      "this_location": "Canada HYDAT SQLite Database (complete national archive)",
                      "obs_source": "Canada HYDAT SQLite Database (complete national archive)",
                      "status": "failed", "ki_usable": None,
                      "input_availability": ia,
                      "metrics": {"nse": None, "kge": None, "pbias": None,
                                  "r": None, "period": None},
                      "water_balance": {"status": "N/A", "residual_pct": None},
                      "tools_used": [], "tools_failed": [],
                      "notes": f"required local inputs missing: {missing}"})
        sys.exit(1)

    try:
        cells, weights, clat = stage_geometry()
        end_iso, ndays, p_ann, t_mean = stage_forcing(cells, weights)
        end_str = stage_climate(end_iso, ndays)
        stage_config(end_str, clat)
        q_full = stage_observed(ndays)
        stage_calibrate()
        stage_simulate()
        stage_parse()
        stage_score(ndays, q_full, p_ann, t_mean, len(cells))
        os._exit(0)   # dodge libgmt teardown SIGSEGV; result.json already on disk
    except Exception:
        tb = traceback.format_exc()
        log(f"FATAL:\n{tb}")
        write_result({
            "model_id": "HydroCNHS",
            "this_location": "Canada HYDAT SQLite Database (complete national archive)",
            "obs_source": "Canada HYDAT SQLite Database (complete national archive)",
            "status": "failed", "ki_usable": None,
            "tools_used": [], "tools_failed": [f"pipeline: {tb[-1500:]}"],
            "metrics": {"nse": None, "r": None, "kge": None, "pbias": None,
                        "period": None},
            "water_balance": {"status": "N/A", "residual_pct": None,
                              "diagnostics": []},
            "input_availability": ia,
            "variable": "Q_routed", "obs_shape": "point_time_series",
            "location": "Southwest Miramichi River at Blackville (01BO001), NB, Canada",
            "notes": f"runner crashed; stage log tail: {STAGE_LOG[-8:]}",
        })
        sys.exit(1)


if __name__ == "__main__":
    main()
