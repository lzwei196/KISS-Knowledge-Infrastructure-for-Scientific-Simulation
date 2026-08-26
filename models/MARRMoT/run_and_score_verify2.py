#!/usr/bin/env python3
"""
MARRMoT VERIFIER (verify_2) runner+scorer at Bengbu gauge 51080, Huai River,
China (32.9N, 117.4E; gauged upstream area 121,330 km2).

Independent re-run of the exact KI pipeline the Real-case used, to check
consistency: CMFD daily 0.25deg Huai basin-mean forcing -> Oudin PET (via
convert_forcing.py --pet-method oudin; CMFD daily Tmin==Tmax breaks Hargreaves)
-> m_07_gr4j_4p_2s calibrated by CMA-ES (of_NSE, 5 IPOP restarts) on 1981-1985,
validated 1986-1990. Metrics via ki_tools_common.metrics.all_metrics.

RESUMABLE: each stage skips if its output already exists.
  detached/verify_2/cmfd_daily.csv        (basin-mean CMFD via load_forcing)
  detached/verify_2/forcing.csv           (convert_forcing.py --pet-method oudin)
  detached/verify_2/obs_q.csv             (Bengbu m3/s -> mm/d, area 121330)
  detached/verify_2/best_theta.json       (CMA-ES of_NSE, 5 IPOP restarts)
  detached/verify_2/marrmot_timeseries.csv(final run)
  detached/verify_2/result.json           (verifier scorecard)
"""
import json, os, subprocess, sys
import numpy as np
import pandas as pd

KI = "KISSPATH_KI_ROOT/MARRMoT/knowledge_infrastructure"
KTC = "KISSPATH_KI_TOOLS_COMMON"
BASE = "KISSPATH_KI_ROOT/MARRMoT/detached/verify_2"
sys.path.insert(0, KI)
sys.path.insert(0, KTC)
from ki_tools_common.metrics import all_metrics
from ki_tools_common.validation import validate_water_balance
from ki_tools_common.load_forcing import load_daily_forcing

os.makedirs(BASE, exist_ok=True)

MODEL = "m_07_gr4j_4p_2s"
AREA_KM2 = 121330.0
CMFD_DIR = "KISSPATH_FORCING/huai/Data_forcing_01dy_025deg"
OBS_TXT = "KISSPATH_OBS/BB/51080_bengbu.txt"
CENTROID_LAT = 33.0
START_Y, END_Y = 1979, 1990

CMFD_CSV = os.path.join(BASE, "cmfd_daily.csv")
FORCING = os.path.join(BASE, "forcing.csv")
OBS = os.path.join(BASE, "obs_q.csv")
BEST = os.path.join(BASE, "best_theta.json")
TS = os.path.join(BASE, "marrmot_timeseries.csv")
RESULT = os.path.join(BASE, "result.json")
CFTOOL = os.path.join(KI, "tools", "convert_forcing.py")
RUNTOOL = os.path.join(KI, "tools", "run_marrmot.py")

# --- Stage 1: CMFD basin-mean daily forcing via load_forcing ----------------
if not os.path.exists(CMFD_CSV):
    lats = [32.0, 33.0, 34.0]
    lons = [114.5, 116.0, 117.5]
    per_point = []
    for la in lats:
        for lo in lons:
            d = load_daily_forcing("cmfd", la, lo, START_Y, END_Y,
                                   forcing_dir=CMFD_DIR)
            dfp = pd.DataFrame({
                "date": pd.to_datetime(d["dates"]),
                "P": np.asarray(d["precip_mm"], float),
                "T": np.asarray(d["temp_mean_c"], float),
            }).set_index("date")
            per_point.append(dfp)
            print(f"loaded point {la},{lo}: P {dfp['P'].mean():.2f} mm/d, "
                  f"T {dfp['T'].mean():.2f} C", flush=True)
    Pstack = pd.concat([p["P"] for p in per_point], axis=1)
    Tstack = pd.concat([p["T"] for p in per_point], axis=1)
    out = pd.DataFrame({
        "date": Pstack.index.strftime("%Y-%m-%d"),
        "precip_mm_d": Pstack.mean(axis=1).values,
        "temp_c": Tstack.mean(axis=1).values,
    })
    out.to_csv(CMFD_CSV, index=False)
    print(f"WROTE {CMFD_CSV}: {len(out)} days, basin-mean P "
          f"{out['precip_mm_d'].mean():.2f} mm/d, T {out['temp_c'].mean():.2f} C",
          flush=True)

# --- Stage 1b: assemble MARRMoT [P,Ep,T] forcing (Oudin PET) via KI tool -----
if not os.path.exists(FORCING):
    cmd = [sys.executable, CFTOOL, "--format", "csv", "--input", CMFD_CSV,
           "--p-col", "precip_mm_d", "--t-col", "temp_c", "--date-col", "date",
           "--pet-method", "oudin", "--lat", str(CENTROID_LAT),
           "--output", FORCING]
    print("CONVERT_FORCING:", " ".join(cmd), flush=True)
    r = subprocess.run(cmd, capture_output=True, text=True)
    print(r.stdout[-1500:], flush=True)
    print(r.stderr[-800:], file=sys.stderr, flush=True)
    if not os.path.exists(FORCING):
        json.dump({"model_id": "MARRMoT", "this_location": "Bengbu",
                   "status": "failed",
                   "notes": "convert_forcing failed: " + r.stderr[-500:]},
                  open(RESULT, "w"), indent=2)
        sys.exit(1)

fc = pd.read_csv(FORCING, comment="#")
fc["date"] = pd.to_datetime(fc["date"])
fdates = fc["date"].values

# --- Stage 2: observed Q (m3/s) -> mm/d, row-aligned to forcing dates --------
if not os.path.exists(OBS):
    raw = pd.read_csv(OBS_TXT, sep="\t", encoding="latin-1")
    raw["date"] = pd.to_datetime(raw["dates"], format="%Y-%m-%d", errors="coerce")
    raw["Q"] = pd.to_numeric(raw["Q"], errors="coerce")
    raw.loc[raw["Q"] < 0, "Q"] = np.nan          # -99.9 = missing
    raw["Q_mm_d"] = raw["Q"] * 86400.0 / (AREA_KM2 * 1e6) * 1000.0
    qmap = raw.set_index("date")["Q_mm_d"]
    aligned = qmap.reindex(fc["date"]).values
    obs_df = pd.DataFrame({"date": fc["date"].dt.strftime("%Y-%m-%d"),
                           "Q_mm_d": aligned})
    obs_df.to_csv(OBS, index=False)
    nfin = int(np.isfinite(aligned).sum())
    print(f"WROTE {OBS}: {len(obs_df)} rows, {nfin} finite, mean "
          f"{np.nanmean(aligned):.3f} mm/d", flush=True)

def row(d):
    return int(np.searchsorted(fdates, np.datetime64(d)) + 1)
CAL_S, CAL_E = row("1981-01-01"), row("1985-12-31")
VAL_S, VAL_E = row("1986-01-01"), row("1990-12-31")
print(f"windows: cal {CAL_S}-{CAL_E}  val {VAL_S}-{VAL_E}  ntot {len(fc)}",
      flush=True)

# --- Stage 3: CMA-ES calibration (of_NSE) over 1981-1985 ---------------------
if not os.path.exists(BEST):
    cal_out = os.path.join(BASE, "calib_result.json")
    cmd = [sys.executable, RUNTOOL, "--forcing", FORCING, "--model", MODEL,
           "--calibrate", "--observed", OBS, "--optimizer", "cmaes",
           "--of-name", "of_NSE", "--restarts", "5", "--max-fun-evals", "1800",
           "--cal-start", str(CAL_S), "--cal-end", str(CAL_E),
           "--seed", "7", "--timeout", "7200", "--output", cal_out]
    print("CALIBRATE:", " ".join(cmd), flush=True)
    r = subprocess.run(cmd, capture_output=True, text=True)
    print(r.stdout[-2000:], flush=True)
    print(r.stderr[-1500:], file=sys.stderr, flush=True)
    cr = json.load(open(cal_out))
    theta = cr.get("theta")
    if not theta:
        json.dump({"model_id": "MARRMoT", "this_location": "Bengbu",
                   "status": "failed",
                   "notes": "CMA-ES produced no theta: " + str(cr.get("errors"))},
                  open(RESULT, "w"), indent=2)
        sys.exit(1)
    json.dump({"theta": theta, "cal_of": cr.get("cal_of")}, open(BEST, "w"))

theta = json.load(open(BEST))["theta"]
print("BEST theta:", theta, flush=True)

# --- Stage 4: final run over full forcing with calibrated theta --------------
if not os.path.exists(TS):
    run_out = os.path.join(BASE, "run_final.json")
    cmd = [sys.executable, RUNTOOL, "--forcing", FORCING, "--model", MODEL,
           "--theta", json.dumps(theta), "--output", run_out, "--timeout", "600"]
    print("RUN:", " ".join(cmd), flush=True)
    r = subprocess.run(cmd, capture_output=True, text=True)
    print(r.stdout[-1500:], flush=True)
    print(r.stderr[-800:], file=sys.stderr, flush=True)

# --- Score -------------------------------------------------------------------
ts = pd.read_csv(TS)
sim = ts["Q_mm_d"].values
obs = pd.read_csv(OBS)["Q_mm_d"].values
n = min(len(sim), len(obs))
sim, obs = sim[:n], obs[:n]

def win(s, e):
    o, q = obs[s-1:e], sim[s-1:e]
    msk = np.isfinite(o) & np.isfinite(q)
    return all_metrics(o[msk], q[msk])

m_cal = win(CAL_S, CAL_E)
m_val = win(VAL_S, VAL_E)
m_full = win(CAL_S, VAL_E)

# --- Water balance (period totals over 1981-1990) ---------------------------
sl = slice(CAL_S-1, VAL_E)
P = float(fc["P_mm_d"].values[sl].sum())
Ea = float(ts["Ea_mm_d"].values[sl].sum())
Q = float(np.nansum(sim[sl]))
scols = [c for c in ts.columns if c.startswith("S") and c[1:].isdigit()]
dS = float(sum(ts[c].values[VAL_E-1] - ts[c].values[CAL_S-1] for c in scols))
ndays = VAL_E - CAL_S + 1
wb = validate_water_balance(precip_mm=P, et_mm=Ea, runoff_mm=Q,
                            delta_storage_mm=dS, period_days=ndays)

result = {
    "model_id": "MARRMoT",
    "this_location": "Bengbu",
    "obs_source": "ObservedQ",
    "status": "completed",
    "tools_used": ["convert_forcing.py (--pet-method oudin)",
                   "run_marrmot.py (cmaes calibrate + run)",
                   "ki_tools_common.load_forcing (cmfd daily Huai)",
                   "ki_tools_common.metrics.all_metrics",
                   "ki_tools_common.validation.validate_water_balance"],
    "tools_failed": [],
    "metrics": {
        "nse": round(m_full["NSE"], 4), "kge": round(m_full["KGE"], 4),
        "pbias": round(m_full["PBIAS"], 4), "r": round(m_full["r"], 4),
        "period": "1981-01-01..1990-12-31 (cal 1981-1985 / val 1986-1990)",
        "nse_cal": round(m_cal["NSE"], 4), "kge_cal": round(m_cal["KGE"], 4),
        "nse_val": round(m_val["NSE"], 4), "kge_val": round(m_val["KGE"], 4),
        "pbias_val": round(m_val["PBIAS"], 4),
    },
    "water_balance": {
        "status": wb["status"], "residual_pct": round(wb["residual_pct"], 3),
        "residual_mm": round(wb["residual_mm"], 3),
        "diagnostics": f"1981-1990: P={P:.0f} Q={Q:.0f} Ea={Ea:.0f} dS={dS:.1f} mm "
                       f"over {ndays} d; runoff coef {Q/P:.2f}.",
    },
    "calibrated_theta": theta,
    "notes": (f"Verifier at Bengbu 51080 Huai River (121330 km2) reproducing the "
              f"Real-case KI pipeline: m_07 GR4J, CMFD daily 0.25deg Huai basin-mean "
              f"(3x3, load_forcing), Oudin PET, CMA-ES of_NSE 5 restarts (seed 7, "
              f"independent of Real-case seed 42) on 1981-1985, validated 1986-1990. "
              f"full NSE {m_full['NSE']:.3f}/KGE {m_full['KGE']:.3f}/r {m_full['r']:.3f}/"
              f"PBIAS {m_full['PBIAS']:.1f}, val NSE {m_val['NSE']:.3f}. Same-gauge peers "
              f"HBV 0.744, WSIMOD 0.695; Real-case NSE 0.752/val 0.618."),
}
json.dump(result, open(RESULT, "w"), indent=2)
print("WROTE", RESULT, flush=True)
print(json.dumps(result["metrics"], indent=2), flush=True)
