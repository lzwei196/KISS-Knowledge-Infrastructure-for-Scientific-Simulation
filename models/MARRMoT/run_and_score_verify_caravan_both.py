#!/usr/bin/env python3
"""MARRMoT VERIFIER @ GRDC-Caravan Extension: gauge GRDC_3275140
(Rio de los Patos at La Plateada, San Juan, Argentine Andes).

Consistency check for the Tangnaihai (upper Yellow River) Real-case. A cold,
high-elevation, snowmelt-dominated headwater basin is used as the twin so the
SAME KI pipeline, the SAME two candidate structures, and the SAME model-
selection rule as the Real-case are exercised at a DIFFERENT location:

  Real-case @ Tangnaihai calibrated BOTH m_12_alpine2_6p_2s (snow) and
  m_07_gr4j_4p_2s (no snow) with CMA-ES/of_NSE + IPOP restarts and selected the
  structure with the higher CALIBRATION NSE (gr4j won there). This verifier
  reproduces that exact procedure -- both structures, same optimiser, same
  cal/val protocol -- and reports the winner's held-out validation metrics so
  the two locations are strictly comparable.

  gauge   GRDC_3275140   8,461 km2   31.881 S, 69.690 W   mean elev ~3,650 m
  clim (1990-2020): P=599  Ep=938  Q=131 mm/yr  =>  required Ea = P-Q = 468
  Ep (938) >> required Ea (468): balance closable by ET alone, so the
  Tangnaihai "Oudin/Hargreaves PET too small -> GR4J x2 pinned at its bound,
  water balance FAIL behind a good NSE" trap (dt_019) CANNOT occur here. Here
  the forcing is Caravan's ERA5-Land PET, not a temperature-index PET.

Caravan bundles catchment-mean ERA5-Land forcing (P, PET, T already in mm/d and
degC) AND observed streamflow (already mm/d) in one per-gauge NetCDF, so no CMFD
extraction, no Hargreaves/Oudin PET synthesis, and no m3/s->mm/d area conversion
are needed. convert_forcing.py --format caravan reads it with netCDF4 (NOT a
bare xr.open_dataset(), which SIGSEGVs at teardown on this box because pygmt is
installed without libgmt).

Period: continuous 1990-01-01..2020-12-31 ERA5-Land forcing (gap-free).
  1990                      spin-up      (excluded from objective via --cal-start)
  1991-01-01..1998-12-31    calibration  (obs Q 100% present, n=2922)
  2011-01-01..2020-12-31    validation   (held out; obs Q ~100% present, n=3652)
A 12-year gap separates cal and val. MARRMoT's check_and_select natively drops
NaN/negative obs, so no masking is required.

RESUMABLE: every stage skips if its output already exists.
  detached/verify_1/forcing.csv                  convert_forcing.py --format caravan
  detached/verify_1/obs_q.csv                    bundled streamflow (mm/d)
  detached/verify_1/cal_<model>/best_theta.json  CMA-ES of_NSE, IPOP restarts
  detached/verify_1/run_<model>/run.json         final full-period run @ best theta
  detached/verify_1/run_<model>/marrmot_timeseries.csv
  detached/verify_1/result.json                  verifier scorecard
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
STATE = "KISSPATH_KI_ROOT/MARRMoT/detached/verify_1"

sys.path.insert(0, KTC)
from ki_tools_common.metrics import all_metrics  # noqa: E402

PY = sys.executable or "/usr/bin/python3"
CFTOOL = os.path.join(KI, "tools", "convert_forcing.py")
RUNTOOL = os.path.join(KI, "tools", "run_marrmot.py")

GAUGE = "GRDC_3275140"
GAUGE_NAME = "Rio de los Patos at La Plateada, San Juan, Argentina (Andes)"
GAUGE_LAT, GAUGE_LON = -31.8813, -69.6896
AREA_KM2 = 8460.835471
NC = ("KISSPATH_DATA/observed_data/dischargeandwatershed/"
      f"GRDC-Caravan-extension-nc/timeseries/netcdf/grdc/{GAUGE}.nc")

# Same two candidate structures + selection rule as the Tangnaihai Real-case.
MODELS = {
    "m_12_alpine2_6p_2s": dict(
        max_fun_evals=1000, restarts=6,
        par_ranges=[[-3.0, 5.0], [0.0, 20.0], [1.0, 2000.0],
                    [0.05, 0.95], [0.0, 1.0], [0.0, 1.0]]),
    "m_07_gr4j_4p_2s": dict(
        max_fun_evals=800, restarts=6,
        par_ranges=[[1.0, 2000.0], [-20.0, 20.0], [1.0, 300.0], [0.5, 15.0]]),
}

WIN_START, WIN_END = "1990-01-01", "2020-12-31"
CAL_START_D, CAL_END_D = "1991-01-01", "1998-12-31"
VAL_START_D, VAL_END_D = "2011-01-01", "2020-12-31"
SEED = 42

os.makedirs(STATE, exist_ok=True)
FORCING = os.path.join(STATE, "forcing.csv")
OBS = os.path.join(STATE, "obs_q.csv")
RESULT = os.path.join(STATE, "result.json")

tools_used = []
tools_failed = []
notes = []
log = lambda *a: print(*a, flush=True)


def sh(cmd, label, fatal=True):
    log(f"\n=== {label} ===\n{' '.join(cmd)}")
    p = subprocess.run(cmd, capture_output=True, text=True)
    log(p.stdout[-3000:])
    if p.returncode != 0:
        print(p.stderr[-3000:], file=sys.stderr, flush=True)
        tools_failed.append(label)
        if fatal:
            raise SystemExit(f"{label} failed with exit {p.returncode}")
    return p


def forcing_is_current():
    """Resume only on a forcing.csv actually built for THIS gauge/window.

    detached/verify_1 is reused across verifier generations; resuming on a
    forcing.csv left by a different gauge/period would silently score this
    gauge's obs against another basin's forcing. The header Period stamp is
    checked before any stage is skipped.
    """
    if not (os.path.exists(FORCING) and os.path.exists(OBS)):
        return False
    want = f"# Period: {WIN_START} to {WIN_END}"
    with open(FORCING) as fh:
        head = [next(fh, "") for _ in range(5)]
    if not any(line.strip() == want for line in head):
        log(f"[stale] forcing.csv is not {want!r} -- rebuilding")
        return False
    return True


# --- Stage 1: forcing + obs straight out of the Caravan NetCDF --------------
if not forcing_is_current():
    sh([PY, CFTOOL, "--format", "caravan", "--input", NC,
        "--start", WIN_START, "--end", WIN_END,
        "--output", FORCING, "--obs-output", OBS], "convert_forcing")
else:
    log("[resume] forcing.csv + obs_q.csv already present")
tools_used.append("convert_forcing.py (--format caravan)")

forc = pd.read_csv(FORCING, comment="#", parse_dates=["date"])
obs = pd.read_csv(OBS, parse_dates=["date"])
assert len(forc) == len(obs), (len(forc), len(obs))
dates = forc["date"]

# 1-based row indices into the forcing series for the calibration objective
cal_start = int(np.where(dates == pd.Timestamp(CAL_START_D))[0][0]) + 1
cal_end = int(np.where(dates == pd.Timestamp(CAL_END_D))[0][0]) + 1
log(f"cal rows {cal_start}..{cal_end} ({CAL_START_D}..{CAL_END_D}); "
    f"n_forcing={len(forc)}")

# Sanity: units + closability (the Tangnaihai lesson -- check Ep > P-Q first)
P_yr = forc["P_mm_d"].mean() * 365.25
Ep_yr = forc["Ep_mm_d"].mean() * 365.25
Q_yr = obs["Q_mm_d"].mean() * 365.25
log(f"P={P_yr:.0f} Ep={Ep_yr:.0f} Q={Q_yr:.0f} mm/yr; "
    f"required Ea = P-Q = {P_yr - Q_yr:.0f} mm/yr")
if Ep_yr <= (P_yr - Q_yr):
    notes.append(f"WARNING Ep ({Ep_yr:.0f}) <= required Ea ({P_yr-Q_yr:.0f}) "
                 "mm/yr -- balance not closable by ET alone")

master = pd.DataFrame({"date": dates, "Q_obs": obs["Q_mm_d"].to_numpy(),
                       "P": forc["P_mm_d"].to_numpy()}).set_index("date")


def score_window(df, a, b):
    d = df.loc[a:b].dropna(subset=["Q_obs", "Q_sim"])
    if len(d) < 30:
        return None, len(d)
    m = all_metrics(d["Q_obs"].to_numpy(), d["Q_sim"].to_numpy())
    return ({k.lower(): (None if not np.isfinite(v) else round(float(v), 4))
             for k, v in m.items()}, len(d))


# --- Stage 2/3: calibrate + final run for BOTH structures -------------------
runs = {}
for model, opt in MODELS.items():
    cdir = os.path.join(STATE, f"cal_{model}")
    rdir = os.path.join(STATE, f"run_{model}")
    os.makedirs(cdir, exist_ok=True)
    os.makedirs(rdir, exist_ok=True)
    best_json = os.path.join(cdir, "best_theta.json")
    calib_json = os.path.join(cdir, "calib_run.json")
    final_json = os.path.join(rdir, "run.json")
    final_ts = os.path.join(rdir, "marrmot_timeseries.csv")

    if not os.path.exists(best_json):
        sh([PY, RUNTOOL, "--forcing", FORCING, "--model", model,
            "--s0", "[0,0]", "--delta-t", "1",
            "--calibrate", "--observed", OBS,
            "--optimizer", "cmaes", "--of-name", "of_NSE",
            "--restarts", str(opt["restarts"]),
            "--max-fun-evals", str(opt["max_fun_evals"]), "--seed", str(SEED),
            "--cal-start", str(cal_start), "--cal-end", str(cal_end),
            "--marrmot-path", MARRMOT_SRC, "--timeout", "86400",
            "--output", calib_json], f"run_marrmot --calibrate cmaes [{model}]",
           fatal=False)
    else:
        log(f"[resume] {model} best_theta.json present")
    if not os.path.exists(best_json):
        tools_failed.append(f"calibrate {model} produced no best_theta.json")
        continue
    tools_used.append("run_marrmot.py --calibrate --optimizer cmaes")

    with open(best_json) as f:
        best = json.load(f)
    theta = [float(x) for x in np.ravel(best.get("theta") or best.get("best_theta"))]
    cal_of = best.get("cal_of", best.get("cal_nse"))
    log(f"[{model}] best theta={theta}  (optimiser cal_of={cal_of})")

    if not (os.path.exists(final_json) and os.path.exists(final_ts)):
        sh([PY, RUNTOOL, "--forcing", FORCING, "--model", model,
            "--theta", json.dumps(theta), "--s0", "[0,0]", "--delta-t", "1",
            "--marrmot-path", MARRMOT_SRC, "--timeout", "86400",
            "--output", final_json], f"run_marrmot final [{model}]", fatal=False)
    else:
        log(f"[resume] {model} final run present")
    if not (os.path.exists(final_json) and os.path.exists(final_ts)):
        tools_failed.append(f"final run {model} produced no timeseries")
        continue
    tools_used.append("run_marrmot.py (final run)")

    with open(final_json) as f:
        runres = json.load(f)
    ts = pd.read_csv(final_ts)
    qsim = ts["Q_mm_d"].to_numpy(dtype=float)
    ea = ts["Ea_mm_d"].to_numpy(dtype=float)
    assert len(qsim) == len(forc), (len(qsim), len(forc))

    df = master.copy()
    df["Q_sim"] = qsim
    df["Ea"] = ea
    Scols = [c for c in ts.columns if c.startswith("S") and c[1:].isdigit()]
    df["Stot"] = ts[Scols].sum(axis=1).to_numpy()

    m_cal, n_cal = score_window(df, CAL_START_D, CAL_END_D)
    m_val, n_val = score_window(df, VAL_START_D, VAL_END_D)
    m_full, n_full = score_window(df, CAL_START_D, VAL_END_D)
    log(f"[{model}] cal(n={n_cal})={m_cal}\n         val(n={n_val})={m_val}")

    runs[model] = dict(theta=theta, cal_of=cal_of, df=df, runres=runres,
                       par_ranges=opt["par_ranges"],
                       m_cal=m_cal, n_cal=n_cal, m_val=m_val, n_val=n_val,
                       m_full=m_full, n_full=n_full)

if not runs:
    json.dump({"model_id": "MARRMoT",
               "this_location": f"GRDC-Caravan Extension gauge {GAUGE} -- {GAUGE_NAME}",
               "obs_source": "GRDC", "status": "failed",
               "tools_used": sorted(set(tools_used)), "tools_failed": tools_failed,
               "metrics": {"nse": None, "kge": None, "pbias": None, "r": None,
                           "period": None},
               "water_balance": {"status": "N/A", "residual_pct": None},
               "notes": "all calibrations/runs failed; " + " ".join(notes)},
              open(RESULT, "w"), indent=2)
    log("all runs failed"); sys.exit(0)

# --- Stage 4: model selection (higher calibration NSE), like the Real-case --
def cal_nse(k):
    mc = runs[k]["m_cal"]
    return mc["nse"] if (mc and mc.get("nse") is not None) else -1e9

best_model = max(runs, key=cal_nse)
R = runs[best_model]
df = R["df"]
log(f"SELECTED {best_model} by calibration NSE "
    f"(alpine2 cal_NSE={cal_nse('m_12_alpine2_6p_2s') if 'm_12_alpine2_6p_2s' in runs else 'NA'}, "
    f"gr4j cal_NSE={cal_nse('m_07_gr4j_4p_2s') if 'm_07_gr4j_4p_2s' in runs else 'NA'})")

# --- water balance over the scored window (model closure) -------------------
win = df.loc[CAL_START_D:VAL_END_D]
wb_mm = float(R["runres"].get("water_balance", float("nan")))
P_tot = float(df["P"].sum())
wb_pct = abs(wb_mm) / P_tot * 100.0 if P_tot else float("nan")
if not np.isfinite(wb_mm):
    wb_status = "N/A"
elif wb_pct < 0.1:
    wb_status = "PASS"
elif wb_pct < 1.0:
    wb_status = "WARN"
else:
    wb_status = "FAIL"

# --- bound pinning on the selected model ------------------------------------
pinned = []
for i, (t, (lo, hi)) in enumerate(zip(R["theta"], R["par_ranges"])):
    span = hi - lo
    if abs(t - lo) < 0.01 * span or abs(t - hi) < 0.01 * span:
        pinned.append({"index": i, "value": t, "range": [lo, hi]})
if pinned:
    notes.append(f"selected model {best_model}: {len(pinned)} calibrated "
                 f"parameter(s) pinned at a parRanges bound: {pinned}")

m_val = R["m_val"]
status = "completed" if m_val is not None else "failed"
if m_val is None:
    notes.append("validation window has <30 valid observed days")

notes.append(
    f"Caravan gauge {GAUGE} ({GAUGE_NAME}), {AREA_KM2:.0f} km2, mean elev "
    f"~3650 m, mean T -0.2 C. Ran the IDENTICAL KI pipeline, the SAME two "
    f"candidate structures (m_12_alpine2, m_07_gr4j), the same CMA-ES/of_NSE "
    f"optimiser with IPOP restarts, and the same 'higher calibration NSE wins' "
    f"selection rule as the Tangnaihai Real-case; winner = {best_model}. "
    f"Forcing and observed Q both come from the Caravan NetCDF (ERA5-Land "
    f"catchment-mean P/PET/T in mm/d and degC; streamflow already mm/d), so no "
    f"unit conversion or PET synthesis was needed. Climatology P={P_yr:.0f}, "
    f"Ep={Ep_yr:.0f}, Qobs={Q_yr:.0f} mm/yr -- Ep exceeds required Ea "
    f"{P_yr-Q_yr:.0f} mm/yr, so the balance is closable (unlike Tangnaihai's "
    f"temperature-index PET). Spin-up 1990, calibration {CAL_START_D}.."
    f"{CAL_END_D} (n={R['n_cal']}), held-out validation {VAL_START_D}.."
    f"{VAL_END_D} (n={R['n_val']}), 12-yr cal/val gap. Selected-model cal "
    f"NSE={(R['m_cal'] or {}).get('nse')}, val NSE={(m_val or {}).get('nse')}. "
    f"MARRMoT water balance closed to {wb_mm:.3e} mm over {P_tot:.0f} mm P.")

result = {
    "model_id": "MARRMoT",
    "this_location": f"GRDC-Caravan Extension gauge {GAUGE} -- {GAUGE_NAME}",
    "obs_source": "GRDC",
    "status": status,
    "tools_used": sorted(set(tools_used)) + ["ki_tools_common.metrics.all_metrics"],
    "tools_failed": tools_failed,
    "metrics": {
        "nse": (m_val or {}).get("nse"),
        "kge": (m_val or {}).get("kge"),
        "pbias": (m_val or {}).get("pbias"),
        "r": (m_val or {}).get("r"),
        "period": f"{VAL_START_D}..{VAL_END_D} (validation, held out)",
    },
    "water_balance": {"status": wb_status,
                      "residual_pct": (None if not np.isfinite(wb_pct)
                                       else round(wb_pct, 6))},
    "notes": " ".join(notes),
    "detail": {
        "gauge_id": GAUGE, "area_km2": AREA_KM2,
        "lat": GAUGE_LAT, "lon": GAUGE_LON,
        "selected_model": best_model,
        "selection_rule": "higher calibration NSE (same as Real-case)",
        "theta": R["theta"], "par_ranges": R["par_ranges"],
        "bound_pinning": {"checked": True, "any_pinned": bool(pinned),
                          "pinned": pinned},
        "optimizer": {"name": "cmaes", "of_name": "of_NSE", "seed": SEED,
                      "restarts": {k: MODELS[k]["restarts"] for k in MODELS},
                      "max_fun_evals": {k: MODELS[k]["max_fun_evals"] for k in MODELS}},
        "candidates": {
            k: {"theta": r["theta"], "cal_of_optimiser": r["cal_of"],
                "metrics_cal": r["m_cal"], "n_cal_days": r["n_cal"],
                "metrics_val": r["m_val"], "n_val_days": r["n_val"],
                "metrics_cal_to_val_span": r["m_full"], "n_full_days": r["n_full"]}
            for k, r in runs.items()},
        "water_balance_mm": wb_mm, "precip_total_mm": P_tot,
        "climatology_mm_per_yr": {"P": round(P_yr, 1), "Ep": round(Ep_yr, 1),
                                  "Q_obs": round(Q_yr, 1)},
        "spinup": "1990 (excluded from objective via --cal-start)",
    },
}

# persist the selected model's sim-vs-obs for auditability
df[["Q_obs", "Q_sim", "Ea", "P"]].to_csv(os.path.join(STATE, "sim_vs_obs.csv"))
with open(RESULT, "w") as f:
    json.dump(result, f, indent=2)
log("\nWROTE " + RESULT)
log(json.dumps(result["metrics"], indent=2))
