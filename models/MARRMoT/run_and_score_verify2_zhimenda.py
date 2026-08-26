#!/usr/bin/env python3
"""MARRMoT verifier @ GRDC 2181500 Zhimenda (直门达), Tongtian He / upper Yangtze,
Qinghai (33.4333 N, 96.6 E). Second verification location.

SAME KI pipeline and SAME two candidate structures as the Tangnaihai Real-case
(m_12_alpine2 snow+soil, m_07_gr4j no-snow), same CMA-ES/of_NSE optimiser with
IPOP restarts, same "higher calibration NSE wins" selection rule.

  - basin cells  : HydroBASINS lev07 upstream traversal from the gauge
  - forcing      : ki_tools_common.load_forcing.load_daily_forcing('cmfd', <cells>)
                   AREAL/basin-mean mode -> KI tools/convert_forcing.py
                   --pet-method priestley_taylor (radiation-based; CMFD daily has
                   Tmin==Tmax so Hargreaves collapses and Oudin under-estimates Ep
                   on this cold ~4000 m plateau)
  - preflight    : validators/preflight_forcing.py  (RAW CMFD source)
  - calibration  : KI tools/run_marrmot.py --calibrate --optimizer cmaes --of-name of_NSE
  - forward run  : KI tools/run_marrmot.py
  - metrics      : ki_tools_common.metrics.all_metrics via validators.standard_calval
  - water balance: ki_tools_common.validation.validate_water_balance

Obs: GRDC daily mean discharge (m3/s, ';'-delimited, -999.000 = missing) converted
to mm/d over the gauged upstream area (dt_010).

RESUMABLE: every stage skips if its output file already exists.
Final action: writes the verifier result object to <STATE>/result.json
"""
import json
import os
import subprocess
import sys

import numpy as np
import pandas as pd

KI = "KISSPATH_KI_ROOT/MARRMoT/knowledge_infrastructure"
KTC = "KISSPATH_KI_TOOLS_COMMON"
MARRMOT_SRC = "KISSPATH_KI_ROOT/MARRMoT/source/repo/MARRMoT"
STATE = "KISSPATH_KI_ROOT/MARRMoT/detached/verify_2"
VALIDATORS = "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect_multi_agent"
CMFD_DIR = "KISSPATH_FORCING/Data_forcing_01dy_010deg"
HYBAS = "KISSPATH_DATA/awd_paper/hydrobasins/asia/hybas_as_lev07_v1c.shp"
OBS_TXT = ("KISSPATH_DATA/china_data/"
           "GRDC_asia_discharge_daily_20260511/2181500_Q_Day.Cmd.txt")

GAUGE_LAT, GAUGE_LON = 33.433333, 96.6
AREA_KM2 = 137704.0          # GRDC-published catchment area of Zhimenda
PY = sys.executable

START_Y, END_Y = 1978, 1997  # 1978-1979 spin-up, 1980-1989 cal, 1990-1997 val
CAL = ("1980-01-01", "1989-12-31")
VAL = ("1990-01-01", "1997-12-31")

MODELS = {
    "m_12_alpine2_6p_2s": dict(max_fun_evals=1000, restarts=6),
    "m_07_gr4j_4p_2s":    dict(max_fun_evals=800,  restarts=6),
}

os.makedirs(STATE, exist_ok=True)
# VALIDATORS must be APPENDED, never prepended: it contains a stale vendored copy
# of ki_tools_common whose _load_cmfd has no AREAL (basin-mean) mode. KTC (the
# canonical package) must win the import race.
sys.path.insert(0, KTC)
from ki_tools_common.metrics import all_metrics                      # noqa: E402
from ki_tools_common.validation import validate_water_balance        # noqa: E402

import importlib.util as _ilu                                        # noqa: E402
_spec = _ilu.spec_from_file_location(
    "kdt_standard_calval", os.path.join(VALIDATORS, "validators", "standard_calval.py"))
_scv = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_scv)
compute_calval_metrics = _scv.compute_calval_metrics

CELLS = os.path.join(STATE, "basin_cells.csv")
CMFD_CSV = os.path.join(STATE, "cmfd_daily.csv")
FORCING = os.path.join(STATE, "forcing.csv")
OBS_CSV = os.path.join(STATE, "obs_q.csv")
PREFLIGHT = os.path.join(STATE, "preflight.json")
RESULT = os.path.join(STATE, "result.json")

log = lambda *a: print(*a, flush=True)

tools_used, tools_failed = [], []


# ---------------------------------------------------------------- stage 1
def stage_cells():
    """Upstream HydroBASINS lev07 union above the gauge -> CMFD 0.1deg cell centres."""
    if os.path.exists(CELLS):
        return pd.read_csv(CELLS)
    import geopandas as gpd
    from shapely.geometry import Point
    from shapely.prepared import prep

    g = gpd.read_file(HYBAS, bbox=(91, 30, 101, 37))
    pt = Point(GAUGE_LON, GAUGE_LAT)
    hit = g[g.contains(pt)]
    if hit.empty:
        hit = g.iloc[[g.distance(pt).idxmin()]]
    seed = int(hit.iloc[0].HYBAS_ID)
    nxt = {}
    for _, r in g.iterrows():
        nxt.setdefault(int(r.NEXT_DOWN), []).append(int(r.HYBAS_ID))
    ups, stack = {seed}, [seed]
    while stack:
        c = stack.pop()
        for u in nxt.get(c, []):
            if u not in ups:
                ups.add(u)
                stack.append(u)
    basin = g[g.HYBAS_ID.isin(ups)].union_all()
    log(f"basin: {len(ups)} lev07 units, HydroBASINS area "
        f"{g[g.HYBAS_ID.isin(ups)].SUB_AREA.sum():.0f} km2 (published gauged {AREA_KM2})")

    pb = prep(basin)
    lat0, lon0 = 15.05, 70.05
    x0, y0, x1, y1 = basin.bounds
    lats = np.round(np.arange(lat0, 55.0, 0.1), 2)
    lons = np.round(np.arange(lon0, 140.0, 0.1), 2)
    lats = lats[(lats >= y0 - 0.1) & (lats <= y1 + 0.1)]
    lons = lons[(lons >= x0 - 0.1) & (lons <= x1 + 0.1)]
    rows = [(float(la), float(lo)) for la in lats for lo in lons
            if pb.contains(Point(lo, la))]
    df = pd.DataFrame(rows, columns=["lat", "lon"])
    df.to_csv(CELLS, index=False)
    log(f"basin cells: {len(df)} CMFD 0.1deg cells (~{len(df) * 100} km2)")
    return df


# ---------------------------------------------------------------- stage 2
def stage_cmfd(cells):
    """Basin-mean daily CMFD via load_forcing AREAL mode. Cached per year."""
    if os.path.exists(CMFD_CSV):
        return
    tools_used.append("ki_tools_common.load_forcing.load_daily_forcing")
    from ki_tools_common.load_forcing import load_daily_forcing
    la, lo = cells.lat.tolist(), cells.lon.tolist()
    parts = []
    for yr in range(START_Y, END_Y + 1):
        cache = os.path.join(STATE, f"cmfd_{yr}.csv")
        if not os.path.exists(cache):
            d = load_daily_forcing("cmfd", la, lo, yr, yr, forcing_dir=CMFD_DIR)
            pd.DataFrame({
                "date": pd.to_datetime(d["dates"]).strftime("%Y-%m-%d"),
                "precip_mm_d": np.asarray(d["precip_mm"], float),
                "temp_c": np.asarray(d["temp_mean_c"], float),
                "srad_wm2": np.asarray(d["srad_wm2"], float),
                "lrad_wm2": np.asarray(d["lrad_wm2"], float),
                "pres_pa": np.asarray(d["pres_pa"], float),
                "wind_ms": np.asarray(d["wind_ms"], float),
                "shum_kgkg": np.asarray(d["shum_kgkg"], float),
            }).to_csv(cache, index=False)
            log(f"  CMFD {yr} done")
        parts.append(pd.read_csv(cache))
    df = pd.concat(parts).sort_values("date").drop_duplicates("date")
    df.to_csv(CMFD_CSV, index=False)
    log(f"CMFD basin-mean: {len(df)} days, P={df.precip_mm_d.mean():.2f} mm/d, "
        f"T={df.temp_c.mean():.2f} C")


# ---------------------------------------------------------------- stage 3
def stage_forcing(cells):
    if os.path.exists(FORCING):
        return
    tools_used.append("convert_forcing.py")
    clat = float(cells.lat.mean())
    r = subprocess.run(
        [PY, os.path.join(KI, "tools/convert_forcing.py"),
         "--format", "csv", "--input", CMFD_CSV,
         "--p-col", "precip_mm_d", "--t-col", "temp_c", "--date-col", "date",
         "--pet-method", "priestley_taylor",
         "--srad-col", "srad_wm2", "--lrad-col", "lrad_wm2",
         "--pres-col", "pres_pa", "--lat", str(clat),
         "--output", FORCING], capture_output=True, text=True)
    if r.returncode != 0:
        tools_failed.append(f"convert_forcing.py: {r.stderr[-400:]}")
        raise SystemExit("convert_forcing failed")
    log(r.stdout)


# ---------------------------------------------------------------- stage 4
def stage_preflight():
    if os.path.exists(PREFLIGHT):
        return json.load(open(PREFLIGHT))
    r = subprocess.run(
        [PY, os.path.join(VALIDATORS, "validators/preflight_forcing.py"),
         CMFD_DIR, "--source", "cmfd", "--year", "1985"],
        capture_output=True, text=True)
    out = r.stdout
    log(out[-3000:])
    fails, warns = [], []
    for ln in out.splitlines():
        s = ln.strip()
        if s.startswith("[FAIL]"):
            fails.append(s)
        elif s.startswith("[WARN]"):
            warns.append(s)
    res = {"all_pass": not fails, "source": "CMFD daily 0.1deg (basin-mean) + Priestley-Taylor PET",
           "failures": fails, "warnings": warns[:12], "returncode": r.returncode}
    json.dump(res, open(PREFLIGHT, "w"), indent=2)
    return res


# ---------------------------------------------------------------- stage 5
def stage_obs():
    """Parse GRDC ';'-delimited daily discharge -> mm/d aligned to forcing dates."""
    if os.path.exists(OBS_CSV):
        return
    fc = pd.read_csv(FORCING, comment="#")
    fc["date"] = pd.to_datetime(fc["date"])
    rows = []
    with open(OBS_TXT, encoding="latin-1") as fh:
        for ln in fh:
            s = ln.strip()
            if not s or s.startswith("#") or s.startswith("YYYY"):
                continue
            parts = s.split(";")
            if len(parts) < 3:
                continue
            try:
                d = pd.to_datetime(parts[0].strip())
            except Exception:
                continue
            try:
                q = float(parts[2].strip())
            except ValueError:
                continue
            rows.append((d, q))
    raw = pd.DataFrame(rows, columns=["date", "Q"])
    raw.loc[raw["Q"] <= -999, "Q"] = np.nan          # GRDC -999.000 sentinel
    raw.loc[raw["Q"] < 0, "Q"] = np.nan
    # dt_010: m3/s -> mm/d over the gauged upstream area
    raw["Q_mm_d"] = raw["Q"] * 86400.0 / (AREA_KM2 * 1e6) * 1000.0
    aligned = raw.dropna(subset=["date"]).set_index("date")["Q_mm_d"].reindex(fc["date"])
    pd.DataFrame({"date": fc["date"].dt.strftime("%Y-%m-%d"),
                  "Q_mm_d": aligned.values}).to_csv(OBS_CSV, index=False)
    log(f"obs: {int(np.isfinite(aligned.values).sum())} finite of {len(aligned)} days; "
        f"mean {np.nanmean(aligned.values):.3f} mm/d")


# ---------------------------------------------------------------- stage 6/7
def cal_indices():
    fc = pd.read_csv(FORCING, comment="#")
    d = pd.to_datetime(fc["date"])
    i0 = int(np.argmax(d.values >= np.datetime64(CAL[0]))) + 1     # 1-based Octave
    i1 = int(np.sum(d.values <= np.datetime64(CAL[1])))
    return i0, i1, d


def calibrate(model, opts, i0, i1):
    wd = os.path.join(STATE, f"cal_{model}")
    best = os.path.join(wd, "best_theta.json")
    if os.path.exists(best):
        return json.load(open(best))
    os.makedirs(wd, exist_ok=True)
    tools_used.append("run_marrmot.py --calibrate --optimizer cmaes")
    cmd = [PY, os.path.join(KI, "tools/run_marrmot.py"),
           "--forcing", FORCING, "--observed", OBS_CSV, "--model", model,
           "--calibrate", "--optimizer", "cmaes", "--of-name", "of_NSE",
           "--restarts", str(opts["restarts"]),
           "--max-fun-evals", str(opts["max_fun_evals"]),
           "--cal-start", str(i0), "--cal-end", str(i1),
           "--marrmot-path", MARRMOT_SRC,
           "--output", os.path.join(wd, "calib.json"), "--timeout", "36000"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    log(f"[{model}] calibrate rc={r.returncode}\n{r.stdout[-1500:]}\n{r.stderr[-800:]}")
    if not os.path.exists(best):
        tools_failed.append(f"run_marrmot.py --calibrate ({model}): {r.stderr[-400:]}")
        return None
    return json.load(open(best))


def forward(model, theta):
    wd = os.path.join(STATE, f"run_{model}")
    ts = os.path.join(wd, "marrmot_timeseries.csv")
    rj = os.path.join(wd, "run.json")
    if os.path.exists(ts) and os.path.exists(rj):
        return pd.read_csv(ts), json.load(open(rj))
    os.makedirs(wd, exist_ok=True)
    tools_used.append("run_marrmot.py")
    r = subprocess.run(
        [PY, os.path.join(KI, "tools/run_marrmot.py"),
         "--forcing", FORCING, "--model", model, "--theta", json.dumps(theta),
         "--marrmot-path", MARRMOT_SRC, "--output", rj, "--timeout", "1800"],
        capture_output=True, text=True)
    if not os.path.exists(ts):
        tools_failed.append(f"run_marrmot.py ({model}): {r.stderr[-400:]}")
        raise SystemExit(f"forward run failed for {model}")
    return pd.read_csv(ts), json.load(open(rj))


# ---------------------------------------------------------------- main
def main():
    cells = stage_cells()
    stage_cmfd(cells)
    stage_forcing(cells)
    pf = stage_preflight()
    stage_obs()

    if pf["failures"]:
        json.dump({"model_id": "MARRMoT",
                   "this_location": "GRDC Asia-Region Daily Discharge Export (250 stations, 2026-05-11 download)",
                   "obs_source": "GRDC Asia-Region Daily Discharge Export (250 stations, 2026-05-11 download)",
                   "status": "failed", "tools_used": sorted(set(tools_used)),
                   "tools_failed": tools_failed,
                   "metrics": {"nse": None, "kge": None, "pbias": None, "r": None, "period": None},
                   "water_balance": {"status": "N/A", "residual_pct": None},
                   "forcing_preflight": pf,
                   "notes": "forcing preflight FAIL -- stopped before model run"},
                  open(RESULT, "w"), indent=2)
        return

    i0, i1, dates = cal_indices()
    log(f"cal_idx {i0}..{i1}  ({CAL[0]}..{CAL[1]})")

    obs = pd.read_csv(OBS_CSV)["Q_mm_d"].values
    fc = pd.read_csv(FORCING, comment="#")

    results = {}
    for model, opts in MODELS.items():
        bt = calibrate(model, opts, i0, i1)
        if bt is None:
            continue
        ts, rj = forward(model, bt["theta"])
        sim = ts["Q_mm_d"].values
        n = min(len(sim), len(obs), len(dates))
        m = compute_calval_metrics(dates.values[:n], obs[:n], sim[:n],
                                   cal_start=CAL[0], cal_end=CAL[1],
                                   val_start=VAL[0], val_end=VAL[1])
        results[model] = dict(theta=bt["theta"], cal_of=bt.get("cal_of"),
                              metrics=m, ts=ts, run=rj)
        log(f"[{model}] cal NSE={m['calibration']['NSE']:.3f} "
            f"val NSE={m['validation']['NSE']:.3f} pbias_val={m['validation']['PBIAS']:.2f}")

    if not results:
        json.dump({"model_id": "MARRMoT",
                   "this_location": "GRDC Asia-Region Daily Discharge Export (250 stations, 2026-05-11 download)",
                   "obs_source": "GRDC Asia-Region Daily Discharge Export (250 stations, 2026-05-11 download)",
                   "status": "failed", "tools_used": sorted(set(tools_used)),
                   "tools_failed": tools_failed,
                   "metrics": {"nse": None, "kge": None, "pbias": None, "r": None, "period": None},
                   "water_balance": {"status": "N/A", "residual_pct": None},
                   "notes": "all calibrations failed"}, open(RESULT, "w"), indent=2)
        return

    best_model = max(results, key=lambda k: results[k]["metrics"]["calibration"]["NSE"])
    R = results[best_model]
    m, ts = R["metrics"], R["ts"]

    # validation-period (held out) metrics are the primary verifier metrics,
    # matching the Real-case's reported nse_val/kge_val/pbias_val.
    def per(p):
        d = m[p]
        return lambda k: (round(float(d[k]), 4) if d.get(k) is not None
                          and np.isfinite(d[k]) else None)
    c, v = per("calibration"), per("validation")

    # ---- water balance over the scored window (model closure)
    n = min(len(ts), len(obs), len(dates))
    win = (dates.values[:n] >= np.datetime64(CAL[0])) & (dates.values[:n] <= np.datetime64(VAL[1]))
    P = fc["P_mm_d"].values[:n][win]
    ET = ts["Ea_mm_d"].values[:n][win]
    Q = ts["Q_mm_d"].values[:n][win]
    Scols = [col for col in ts.columns if col.startswith("S") and col[1:].isdigit()]
    Stot = ts[Scols].sum(axis=1).values[:n]
    idx = np.where(win)[0]
    dS = float(Stot[idx[-1]] - Stot[idx[0]])
    wb = validate_water_balance(precip_mm=float(P.sum()), et_mm=float(ET.sum()),
                                runoff_mm=float(Q.sum()), delta_storage_mm=dS,
                                period_days=int(win.sum()))
    wb_status = {"WARNING": "WARN", "OK": "PASS"}.get(wb["status"], wb["status"])

    out = {
        "model_id": "MARRMoT",
        "this_location": "GRDC Asia-Region Daily Discharge Export (250 stations, 2026-05-11 download)",
        "obs_source": ("GRDC Asia-Region Daily Discharge Export (250 stations, 2026-05-11 download); "
                       "station 2181500 Zhimenda (直门达), Tongtian He / upper Yangtze; variable discharge_m3s"),
        "status": "completed",
        "tools_used": sorted(set(tools_used)) + ["preflight_forcing.py",
                                                 "standard_calval.compute_calval_metrics",
                                                 "ki_tools_common.metrics.all_metrics",
                                                 "ki_tools_common.validation.validate_water_balance"],
        "tools_failed": tools_failed,
        "metrics": {
            "nse": v("NSE"), "kge": v("KGE"), "pbias": v("PBIAS"), "r": v("r"),
            "period": f"{VAL[0]}..{VAL[1]} (validation, held out)",
            "nse_cal": c("NSE"), "kge_cal": c("KGE"), "pbias_cal": c("PBIAS"),
            "period_calibration": f"{CAL[0]}..{CAL[1]}",
        },
        "water_balance": {"status": wb_status, "residual_pct": wb.get("residual_pct"),
                          "residual_mm": wb.get("residual_mm")},
        "detail": {
            "selected_model": best_model,
            "selection_rule": "higher calibration NSE (same as Real-case)",
            "catchment_area_km2": AREA_KM2,
            "n_basin_cells": int(len(cells)),
            "gauge_lat": GAUGE_LAT, "gauge_lon": GAUGE_LON,
            "octave_water_balance_mm": R["run"].get("water_balance"),
            "candidates": {
                k: {"theta": r_["theta"],
                    "nse_cal": round(float(r_["metrics"]["calibration"]["NSE"]), 4),
                    "nse_val": round(float(r_["metrics"]["validation"]["NSE"]), 4),
                    "kge_val": round(float(r_["metrics"]["validation"]["KGE"]), 4),
                    "pbias_val": round(float(r_["metrics"]["validation"]["PBIAS"]), 3),
                    "r_val": round(float(r_["metrics"]["validation"]["r"]), 4)}
                for k, r_ in results.items()
            },
        },
        "forcing_preflight": {"all_pass": pf["all_pass"], "source": pf["source"],
                              "failures": pf["failures"], "warnings": pf["warnings"]},
        "notes": (
            f"Second verification location: GRDC 2181500 Zhimenda, Tongtian He / upper "
            f"Yangtze (Qinghai), gauged area {AREA_KM2:.0f} km2, complete daily record "
            f"1978-1997 (no gaps). DIFFERENT basin from the Real-case (Tangnaihai, upper "
            f"Yellow). Ran the IDENTICAL KI pipeline: CMFD daily 0.1deg basin-mean over "
            f"{len(cells)} cells via load_forcing AREAL mode, Priestley-Taylor PET "
            f"(CMFD daily has Tmin==Tmax so Hargreaves collapses; Oudin under-estimates on "
            f"this cold high-alt plateau), the SAME two candidate structures "
            f"(m_12_alpine2 snow+soil, m_07_gr4j no-snow) with CMA-ES/of_NSE + IPOP restarts, "
            f"same 'higher cal NSE wins' rule; winner = {best_model}. Spin-up 1978-1979, "
            f"calibration {CAL[0]}..{CAL[1]}, held-out validation {VAL[0]}..{VAL[1]}. "
            f"Selected-model val NSE={v('NSE')} KGE={v('KGE')} PBIAS={v('PBIAS')}% "
            f"(cal NSE={c('NSE')}). Water balance {wb_status} ({wb.get('residual_pct')}%)."
        ),
    }
    json.dump(out, open(RESULT, "w"), indent=2, ensure_ascii=False)
    log(json.dumps({k: out[k] for k in ("metrics", "water_balance")}, indent=2))


if __name__ == "__main__":
    main()
