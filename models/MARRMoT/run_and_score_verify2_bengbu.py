#!/usr/bin/env python3
"""VERIFIER #2 — MARRMoT @ Bengbu 51080, Huai River (32.9N/117.4E, 121330 km2).

Runs the IDENTICAL KI pipeline as the Tangnaihai Real-case / retest
(run_and_score_retest.py), only the location changes:

    HydroBASINS lev07 upstream trace  ->  basin cells
    ki_tools_common.load_forcing (CMFD 0.1 deg daily, basin-mean)
    convert_forcing.py --pet-method priestley_taylor  (srad + lrad + real pres)
    dt_019 mass-feasibility gate: Ep_mean >= P_mean - Q_mean
    run_marrmot.py --calibrate --optimizer cmaes --of-name of_NSE (IPOP restarts)
    run_marrmot.py forward run
    ki_tools_common.metrics.all_metrics + validators/standard_calval
    ki_tools_common.validation.validate_water_balance

Model structures: m_12_alpine2_6p_2s (the Real-case structure -> PRIMARY, the
number the orchestrator compares) and m_07_gr4j_4p_2s (the structure the
Tangnaihai retest selected -> secondary, for the same-basin peer record).

Split matches every prior Bengbu run on this gauge:
    spin-up 1979-1980 | calibration 1981-1985 | validation 1986-1990

RESUMABLE: every stage skips when its output exists (basin cells, CMFD per
year, forcing, obs, calibration per model, forward run per model).
FINAL ACTION: writes the complete verifier JSON to <STATE>/result.json.
"""
import json
import os
import re
import subprocess
import sys

import numpy as np
import pandas as pd

KI = "/mnt/disk1/Hydrocraft_server/models/MARRMoT/knowledge_infrastructure"
KTC = "/mnt/disk1/Hydrocraft_server/models/ki_tools_common"
WORK = "/mnt/disk1/Hydrocraft_server/models/MARRMoT"
MARRMOT_SRC = os.path.join(WORK, "source/repo/MARRMoT")
STATE = os.path.join(WORK, "detached/verify_2")
VALIDATORS = "/home/server/knowledge-dissection-toolkit/auto_dissect_multi_agent"
CMFD_DIR = "/media/server/hc_ssd/forcing/Data_forcing_01dy_010deg"
HYBAS = "/mnt/disk1/Hydrocraft_server/data/awd_paper/hydrobasins/asia/hybas_as_lev07_v1c.shp"
OBS_TXT = "/mnt/disk1/Hydrocraft_server/data/obs/BB/51080_bengbu.txt"

LOCATION = "Bengbu"
GAUGE_LAT, GAUGE_LON = 32.9, 117.4
AREA_KM2 = 121330.0
PY = sys.executable

START_Y, END_Y = 1979, 1990          # 1979-1980 = spin-up (excluded from objective)
CAL = ("1981-01-01", "1985-12-31")
VAL = ("1986-01-01", "1990-12-31")

PRIMARY = "m_12_alpine2_6p_2s"       # == the Real-case structure at Tangnaihai
MODELS = {
    "m_12_alpine2_6p_2s": dict(max_fun_evals=1000, restarts=6),
    "m_07_gr4j_4p_2s":    dict(max_fun_evals=800,  restarts=6),
}

os.makedirs(STATE, exist_ok=True)
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
FEAS = os.path.join(STATE, "mass_feasibility.json")
RESULT = os.path.join(STATE, "result.json")

log = lambda *a: print(*a, flush=True)
tools_used, tools_failed = [], []


def _finite(x):
    try:
        return round(float(x), 4) if x is not None and np.isfinite(float(x)) else None
    except (TypeError, ValueError):
        return None


def par_ranges(model):
    p = os.path.join(MARRMOT_SRC, "Models", "Model files", f"{model}.m")
    txt = open(p, encoding="utf-8", errors="replace").read()
    m = re.search(r"parRanges\s*=\s*\[(.*?)\]\s*;", txt, re.S)
    if not m:
        return None
    body = re.sub(r"%[^\n]*", "", m.group(1))
    rows = [r for r in (r.strip() for r in re.split(r"[;\n]", body)) if r]
    out = []
    for r in rows:
        nums = [float(v) for v in re.split(r"[,\s]+", r.strip()) if v]
        if len(nums) == 2:
            out.append(nums)
    return out


def bound_pinning(model, theta, rtol=1e-6):
    pr = par_ranges(model)
    if pr is None or len(pr) != len(theta):
        return {"checked": False, "reason": "parRanges unreadable/length mismatch"}
    pinned = []
    for i, (v, (lo, hi)) in enumerate(zip(theta, pr)):
        span = max(abs(hi - lo), 1e-12)
        if abs(v - lo) <= rtol * span:
            pinned.append({"index": i, "value": v, "bound": "lower", "lo": lo, "hi": hi})
        elif abs(v - hi) <= rtol * span:
            pinned.append({"index": i, "value": v, "bound": "upper", "lo": lo, "hi": hi})
    return {"checked": True, "any_pinned": bool(pinned), "pinned": pinned,
            "par_ranges": pr, "theta": list(map(float, theta))}


# ---------------------------------------------------------------- stage 1
def stage_cells():
    if os.path.exists(CELLS):
        return pd.read_csv(CELLS)
    import geopandas as gpd
    from shapely.geometry import Point
    from shapely.prepared import prep

    g = gpd.read_file(HYBAS, bbox=(111, 30, 120, 36))
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
    pb = prep(basin)
    x0, y0, x1, y1 = basin.bounds
    lats = np.round(np.arange(15.05, 55.0, 0.1), 2)
    lons = np.round(np.arange(70.05, 140.0, 0.1), 2)
    lats = lats[(lats >= y0 - 0.1) & (lats <= y1 + 0.1)]
    lons = lons[(lons >= x0 - 0.1) & (lons <= x1 + 0.1)]
    rows = [(float(la), float(lo)) for la in lats for lo in lons
            if pb.contains(Point(lo, la))]
    df = pd.DataFrame(rows, columns=["lat", "lon"])
    df.to_csv(CELLS, index=False)
    log(f"basin cells: {len(df)}")
    return df


# ---------------------------------------------------------------- stage 2
def stage_cmfd(cells):
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
            }).to_csv(cache, index=False)
            log(f"  CMFD {yr} done")
        parts.append(pd.read_csv(cache))
    df = pd.concat(parts).sort_values("date").drop_duplicates("date")
    df.to_csv(CMFD_CSV, index=False)
    log(f"CMFD basin-mean: {len(df)} days, P={df.precip_mm_d.mean():.2f} mm/d, "
        f"T={df.temp_c.mean():.2f} C, pres={df.pres_pa.mean():.0f} Pa")


# ---------------------------------------------------------------- stage 3
def stage_forcing(cells):
    if os.path.exists(FORCING):
        return
    tools_used.append("convert_forcing.py --pet-method priestley_taylor")
    clat = float(cells.lat.mean())
    cmd = [PY, os.path.join(KI, "tools/convert_forcing.py"),
           "--format", "csv", "--input", CMFD_CSV,
           "--p-col", "precip_mm_d", "--t-col", "temp_c", "--date-col", "date",
           "--pet-method", "priestley_taylor",
           "--srad-col", "srad_wm2", "--lrad-col", "lrad_wm2",
           "--pres-col", "pres_pa", "--lat", str(clat),
           "--output", FORCING]
    r = subprocess.run(cmd, capture_output=True, text=True)
    log("convert_forcing rc=%d\n%s\n%s" % (r.returncode, r.stdout[-800:], r.stderr[-400:]))
    if r.returncode != 0 or not os.path.exists(FORCING):
        tools_failed.append(f"convert_forcing.py: {r.stderr[-400:]}")
        json.dump({"model_id": "MARRMoT", "this_location": LOCATION,
                   "obs_source": "ObservedQ", "status": "failed",
                   "tools_used": sorted(set(tools_used)), "tools_failed": tools_failed,
                   "metrics": {"nse": None, "kge": None, "pbias": None, "r": None,
                               "period": None},
                   "water_balance": {"status": "N/A", "residual_pct": None},
                   "notes": "convert_forcing.py --pet-method priestley_taylor failed.",
                   "stderr": r.stderr[-2000:]},
                  open(RESULT, "w"), indent=2, ensure_ascii=False)
        raise SystemExit("convert_forcing failed")


# ---------------------------------------------------------------- stage 4
def stage_obs():
    if os.path.exists(OBS_CSV):
        return
    fc = pd.read_csv(FORCING, comment="#")
    fc["date"] = pd.to_datetime(fc["date"])
    raw = pd.read_csv(OBS_TXT, sep="\t", encoding="latin-1")   # GBK station-name column
    raw["date"] = pd.to_datetime(raw["dates"], errors="coerce")
    raw["Q"] = pd.to_numeric(raw["Q"], errors="coerce")
    raw.loc[raw["Q"] <= -99, "Q"] = np.nan
    raw.loc[raw["Q"] < 0, "Q"] = np.nan
    raw["Q_mm_d"] = raw["Q"] * 86400.0 / (AREA_KM2 * 1e6) * 1000.0   # dt_010
    aligned = (raw.dropna(subset=["date"]).drop_duplicates("date")
                  .set_index("date")["Q_mm_d"].reindex(fc["date"]))
    pd.DataFrame({"date": fc["date"].dt.strftime("%Y-%m-%d"),
                  "Q_mm_d": aligned.values}).to_csv(OBS_CSV, index=False)
    log(f"obs: {int(np.isfinite(aligned.values).sum())} finite of {len(aligned)}")


# ---------------------------------------------------------------- stage 5: THE GATE
def stage_feasibility():
    if os.path.exists(FEAS):
        return json.load(open(FEAS))
    fc = pd.read_csv(FORCING, comment="#")
    fc["date"] = pd.to_datetime(fc["date"])
    obs = pd.read_csv(OBS_CSV)
    win = (fc["date"] >= CAL[0]) & (fc["date"] <= VAL[1])
    q = obs.loc[win.values, "Q_mm_d"].values
    P = float(fc.loc[win, "P_mm_d"].mean())
    Ep = float(fc.loc[win, "Ep_mm_d"].mean())
    Q = float(np.nanmean(q[np.isfinite(q)]))
    req = P - Q
    res = {"scored_window": f"{CAL[0]}..{VAL[1]}",
           "P_mean_mm_d": round(P, 4), "Ep_mean_mm_d": round(Ep, 4),
           "Q_mean_mm_d": round(Q, 4),
           "P_mean_mm_yr": round(P * 365.25, 1), "Ep_mean_mm_yr": round(Ep * 365.25, 1),
           "Q_mean_mm_yr": round(Q * 365.25, 1),
           "required_Ea_mm_yr": round(req * 365.25, 1),
           "feasible": bool(Ep >= req),
           "headroom_mm_yr": round((Ep - req) * 365.25, 1)}
    json.dump(res, open(FEAS, "w"), indent=2)
    log("MASS FEASIBILITY: Ep=%.1f mm/yr vs required Ea (P-Q)=%.1f mm/yr -> %s"
        % (res["Ep_mean_mm_yr"], res["required_Ea_mm_yr"],
           "PASS" if res["feasible"] else "FAIL"))
    return res


# ---------------------------------------------------------------- stage 6/7
def cal_indices():
    fc = pd.read_csv(FORCING, comment="#")
    d = pd.to_datetime(fc["date"])
    i0 = int(np.argmax(d.values >= np.datetime64(CAL[0]))) + 1
    i1 = int(np.sum(d.values <= np.datetime64(CAL[1])))
    return i0, i1, d


def calibrate(model, opts, i0, i1):
    wd = os.path.join(STATE, f"cal_{model}")
    best = os.path.join(wd, "best_theta.json")
    if os.path.exists(best):
        return json.load(open(best))
    os.makedirs(wd, exist_ok=True)
    tools_used.append("run_marrmot.py --calibrate --optimizer cmaes")
    r = subprocess.run(
        [PY, os.path.join(KI, "tools/run_marrmot.py"),
         "--forcing", FORCING, "--observed", OBS_CSV, "--model", model,
         "--calibrate", "--optimizer", "cmaes", "--of-name", "of_NSE",
         "--restarts", str(opts["restarts"]),
         "--max-fun-evals", str(opts["max_fun_evals"]),
         "--cal-start", str(i0), "--cal-end", str(i1),
         "--marrmot-path", MARRMOT_SRC,
         "--output", os.path.join(wd, "calib.json"), "--timeout", "36000"],
        capture_output=True, text=True)
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


def water_balance(fc, ts, dates, n):
    win = (dates.values[:n] >= np.datetime64(CAL[0])) & (dates.values[:n] <= np.datetime64(VAL[1]))
    P = fc["P_mm_d"].values[:n][win]
    ET = ts["Ea_mm_d"].values[:n][win]
    Q = ts["Q_mm_d"].values[:n][win]
    Scols = [c for c in ts.columns if c.startswith("S") and c[1:].isdigit()]
    Stot = ts[Scols].sum(axis=1).values[:n]
    idx = np.where(win)[0]
    dS = float(Stot[idx[-1]] - Stot[idx[0]])
    wb = validate_water_balance(precip_mm=float(P.sum()), et_mm=float(ET.sum()),
                                runoff_mm=float(Q.sum()), delta_storage_mm=dS,
                                period_days=int(win.sum()))
    wb["status"] = {"WARNING": "WARN", "OK": "PASS"}.get(wb["status"], wb["status"])
    wb["_diag"] = ("%s..%s: P=%.0f Q=%.0f Ea=%.0f dS=%.1f mm over %d d; runoff coef %.2f."
                   % (CAL[0][:4], VAL[1][:4], P.sum(), Q.sum(), ET.sum(), dS,
                      int(win.sum()), Q.sum() / max(P.sum(), 1e-9)))
    return wb, win


def main():
    cells = stage_cells()
    stage_cmfd(cells)
    stage_forcing(cells)
    stage_obs()
    feas = stage_feasibility()

    if not feas["feasible"]:
        json.dump({
            "model_id": "MARRMoT", "this_location": LOCATION, "obs_source": "ObservedQ",
            "status": "failed", "tools_used": sorted(set(tools_used)),
            "tools_failed": tools_failed,
            "metrics": {"nse": None, "kge": None, "pbias": None, "r": None,
                        "period": None},
            "water_balance": {"status": "FAIL", "residual_pct": None},
            "mass_feasibility": feas,
            "notes": ("Priestley-Taylor Ep (%.1f mm/yr) is below the required Ea = P-Q "
                      "(%.1f mm/yr) at Bengbu, so the forcing is mass-infeasible and "
                      "calibration was not attempted (dt_019 pre-calibration gate)."
                      % (feas["Ep_mean_mm_yr"], feas["required_Ea_mm_yr"])),
        }, open(RESULT, "w"), indent=2, ensure_ascii=False)
        return

    i0, i1, dates = cal_indices()
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
        wb, win = water_balance(fc, ts, dates, n)
        msk = win & np.isfinite(obs[:n]) & np.isfinite(sim[:n])
        full = all_metrics(obs[:n][msk], sim[:n][msk])
        results[model] = dict(theta=bt["theta"], metrics=m, run=rj, full=full, wb=wb,
                              pinning=bound_pinning(model, bt["theta"]))
        log(f"[{model}] cal NSE={m['calibration']['NSE']:.3f} "
            f"val NSE={m['validation']['NSE']:.3f} wb={wb['status']} "
            f"pinned={results[model]['pinning'].get('any_pinned')}")
        ts.assign(date=dates.values[:len(ts)]).to_csv(
            os.path.join(STATE, f"sim_vs_obs_{model}.csv"), index=False)

    if not results:
        json.dump({
            "model_id": "MARRMoT", "this_location": LOCATION, "obs_source": "ObservedQ",
            "status": "failed", "tools_used": sorted(set(tools_used)),
            "tools_failed": tools_failed,
            "metrics": {"nse": None, "kge": None, "pbias": None, "r": None,
                        "period": None},
            "water_balance": {"status": "N/A", "residual_pct": None},
            "mass_feasibility": feas,
            "notes": "All CMA-ES calibrations failed; no metrics produced.",
        }, open(RESULT, "w"), indent=2, ensure_ascii=False)
        return

    # PRIMARY = the Real-case structure, reported on the held-out validation window
    # (exactly as verify_1 and the Real-case did).
    key = PRIMARY if PRIMARY in results else next(iter(results))
    R = results[key]
    v = R["metrics"]["validation"]
    wb = R["wb"]

    secondary = {k: {"nse_cal": _finite(r["metrics"]["calibration"]["NSE"]),
                     "nse_val": _finite(r["metrics"]["validation"]["NSE"]),
                     "kge_val": _finite(r["metrics"]["validation"]["KGE"]),
                     "pbias_val": _finite(r["metrics"]["validation"]["PBIAS"]),
                     "r_val": _finite(r["metrics"]["validation"]["r"]),
                     "nse_full": _finite(r["full"].get("NSE")),
                     "theta": list(map(float, r["theta"])),
                     "water_balance": r["wb"]["status"],
                     "bound_pinning": r["pinning"]}
                 for k, r in results.items()}

    notes = (
        "Verifier #2 at Bengbu 51080, Huai River (32.9N/117.4E, gauged area 121330 km2), "
        "running the identical KI pipeline as the Tangnaihai Real-case: HydroBASINS lev07 "
        "upstream trace (53 sub-basins, 125402 km2, +3.4%% vs gauged) -> 1216 CMFD 0.1deg "
        "cells -> basin-mean daily forcing via ki_tools_common.load_forcing -> "
        "convert_forcing.py --pet-method priestley_taylor (srad+lrad+real surface pressure) "
        "-> dt_019 mass-feasibility gate -> run_marrmot.py CMA-ES of_NSE with 6 IPOP "
        "restarts -> forward run -> all_metrics + validate_water_balance. Spin-up 1979-1980, "
        "calibration 1981-1985, validation 1986-1990 (held out). PRIMARY structure is "
        "m_12_alpine2_6p_2s, the Real-case structure, scored on the held-out validation "
        "window; m_07_gr4j_4p_2s was run as a same-basin secondary. Mass feasibility: "
        "P=%.0f, Ep=%.0f, Qobs=%.0f mm/yr -> required Ea=%.0f mm/yr, headroom %+.0f mm/yr. "
        "m_12: cal NSE=%.4f, val NSE=%.4f, water_balance %s. m_07: cal NSE=%s, val NSE=%s. "
        "No calibrated parameter of the primary structure sits on a parRanges bound: %s. "
        "Same-gauge peers on this obs record: HBV 0.744, WSIMOD 0.695, GR4J real-case 0.618 (val)."
        % (feas["P_mean_mm_yr"], feas["Ep_mean_mm_yr"], feas["Q_mean_mm_yr"],
           feas["required_Ea_mm_yr"], feas["headroom_mm_yr"],
           R["metrics"]["calibration"]["NSE"], v["NSE"], wb["status"],
           secondary.get("m_07_gr4j_4p_2s", {}).get("nse_cal"),
           secondary.get("m_07_gr4j_4p_2s", {}).get("nse_val"),
           "yes (none pinned)" if not R["pinning"].get("any_pinned") else
           "NO -- pinned: %s" % R["pinning"]["pinned"]))

    json.dump({
        "model_id": "MARRMoT",
        "this_location": LOCATION,
        "obs_source": "ObservedQ",
        "status": "completed",
        "tools_used": sorted(set(tools_used)),
        "tools_failed": tools_failed,
        "metrics": {
            "nse": _finite(v["NSE"]), "kge": _finite(v["KGE"]),
            "pbias": _finite(v["PBIAS"]), "r": _finite(v["r"]),
            "period": f"{VAL[0]}..{VAL[1]} (validation, held out; "
                      f"calibration {CAL[0]}..{CAL[1]}, spin-up 1979-1980)",
            "nse_cal": _finite(R["metrics"]["calibration"]["NSE"]),
            "kge_cal": _finite(R["metrics"]["calibration"]["KGE"]),
            "nse_val": _finite(v["NSE"]),
            "nse_full_scored_window": _finite(R["full"].get("NSE")),
        },
        "water_balance": {"status": wb["status"],
                          "residual_pct": _finite(wb.get("residual_pct")),
                          "residual_mm": _finite(wb.get("residual_mm")),
                          "diagnostics": wb["_diag"]},
        "notes": notes,
        "detail": {
            "gauge": "51080 Bengbu, Huai River",
            "lat": GAUGE_LAT, "lon": GAUGE_LON, "area_km2": AREA_KM2,
            "primary_model_structure": key,
            "theta": list(map(float, R["theta"])),
            "bound_pinning": R["pinning"],
            "optimizer": {"name": "cmaes", "of_name": "of_NSE",
                          "restarts": MODELS[key]["restarts"],
                          "max_fun_evals": MODELS[key]["max_fun_evals"]},
            "metrics_cal": {k: _finite(x) for k, x in R["metrics"]["calibration"].items()
                            if not isinstance(x, (list, dict))},
            "metrics_val": {k: _finite(x) for k, x in R["metrics"]["validation"].items()
                            if not isinstance(x, (list, dict))},
            "octave_water_balance_mm": R["run"].get("water_balance"),
            "mass_feasibility": feas,
            "all_structures": secondary,
            "peers_same_gauge": {"HBV": 0.744, "WSIMOD": 0.695,
                                 "MARRMoT_GR4J_prior_val": 0.618},
        },
    }, open(RESULT, "w"), indent=2, ensure_ascii=False)
    log("WROTE " + RESULT)


if __name__ == "__main__":
    main()
