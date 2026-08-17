#!/usr/bin/env python3
"""MARRMoT verifier @ GRDC-Caravan Extension: gauge GRDC_3653620
(Rio Carreiro, Passo Carreiro, Santa Catarina, Brazil).

Consistency twin of the Bengbu 51080 (Huai) Real-case: a warm, humid,
snow-free subtropical basin -> same structure m_07 gr4j (2 stores, no snow),
same recipe (CMA-ES of_NSE, IPOP restarts, cal/val split). Caravan bundles
ERA5-Land forcing (P, PET, T in mm/d and C) AND streamflow (mm/d) in one NetCDF,
so NO CMFD/Hargreaves/Oudin is needed -- forcing and obs come straight from the
gauge file, already in MARRMoT units.

End-to-end via the KI tools (convert_forcing -> run_marrmot --calibrate cmaes
-> run_marrmot), RESUMABLE (each stage skips if its output exists). Writes the
verifier JSON to result.json.
"""
import os, sys, json, subprocess
import numpy as np
import pandas as pd

KI = "KISSPATH_KI_ROOT/MARRMoT/knowledge_infrastructure"
STATE = "KISSPATH_KI_ROOT/MARRMoT/detached/verify_1"
NC = ("KISSPATH_DATA/observed_data/dischargeandwatershed/"
      "GRDC-Caravan-extension-nc/timeseries/netcdf/grdc/GRDC_3653620.nc")
PY = "/usr/bin/python3"
MODEL = "m_07_gr4j_4p_2s"
GAUGE = "GRDC_3653620"
GAUGE_NAME = "Rio Carreiro, Passo Carreiro, Santa Catarina, Brazil"
AREA_KM2 = 1826.8
# window: 1999 spin-up, 2000-2009 calibration, 2010-2019 validation
WIN_START, WIN_END = "1999-01-01", "2019-12-31"
SPINUP_END = "1999-12-31"
CAL_START_D, CAL_END_D = "2000-01-01", "2009-12-31"
VAL_START_D, VAL_END_D = "2010-01-01", "2019-12-31"

os.makedirs(STATE, exist_ok=True)
sys.path.insert(0, "KISSPATH_KI_TOOLS_COMMON")
from ki_tools_common.metrics import all_metrics

inter = os.path.join(STATE, "intermediate.csv")
forcing = os.path.join(STATE, "forcing.csv")
obs_csv = os.path.join(STATE, "obs_q.csv")
ts_csv = os.path.join(STATE, "marrmot_timeseries.csv")
run_json = os.path.join(STATE, "run.json")
calib_json = os.path.join(STATE, "calib_result.json")
best_json = os.path.join(STATE, "best_theta.json")

# --- Stage 1: extract Caravan forcing+obs from the gauge NetCDF ---
if not os.path.exists(inter):
    import xarray as xr
    ds = xr.open_dataset(NC)
    df = ds[["total_precipitation_sum", "potential_evaporation_sum",
             "temperature_2m_mean", "streamflow"]].to_dataframe()
    df.index = pd.to_datetime(df.index)
    w = df.loc[WIN_START:WIN_END].copy()
    w = w.rename(columns={"total_precipitation_sum": "P",
                          "potential_evaporation_sum": "Ep",
                          "temperature_2m_mean": "T",
                          "streamflow": "Q_obs"})
    w["date"] = w.index
    # forcing must be gap-free for the model; P/Ep/T have no NaN in this window
    w["P"] = w.P.clip(lower=0.0)
    w["Ep"] = w.Ep.clip(lower=0.0)
    w[["date", "P", "Ep", "T", "Q_obs"]].to_csv(inter, index=False)

# --- Stage 2: KI convert_forcing -> [P, Ep, T] CSV (Ep already computed) ---
if not os.path.exists(forcing):
    subprocess.run([PY, os.path.join(KI, "tools/convert_forcing.py"),
                    "--input", inter, "--format", "csv", "--output", forcing,
                    "--p-col", "P", "--ep-col", "Ep", "--t-col", "T",
                    "--date-col", "date", "--pet-method", "column"], check=True)

# --- align obs to the exact forcing rows (row-indexed by Octave) ---
fdf = pd.read_csv(forcing, comment="#")
fdates = pd.to_datetime(fdf.iloc[:, 0])
idf = pd.read_csv(inter, parse_dates=["date"]).set_index("date")
qobs = idf["Q_obs"].reindex(fdates).values
if not os.path.exists(obs_csv):
    pd.DataFrame({"date": fdates.dt.strftime("%Y-%m-%d"),
                  "Q_mm_d": qobs}).to_csv(obs_csv, index=False)

# 1-based calibration row indices into the forcing series
cal_start = int(np.searchsorted(fdates.values,
                np.datetime64(CAL_START_D)) + 1)
cal_end = int(np.searchsorted(fdates.values,
              np.datetime64(CAL_END_D), side="right"))

# --- Stage 3: CMA-ES calibrate m_07 gr4j on 2000-2009 (of_NSE, IPOP restarts) ---
if not os.path.exists(best_json):
    subprocess.run([PY, os.path.join(KI, "tools/run_marrmot.py"),
                    "--forcing", forcing, "--model", MODEL,
                    "--calibrate", "--optimizer", "cmaes",
                    "--observed", obs_csv, "--of-name", "of_NSE",
                    "--restarts", "5", "--max-fun-evals", "1500",
                    "--cal-start", str(cal_start), "--cal-end", str(cal_end),
                    "--output", calib_json], check=True)

theta = json.load(open(best_json))["theta"]

# --- Stage 4: run m_07 gr4j over the full window with the calibrated theta ---
if not os.path.exists(ts_csv):
    subprocess.run([PY, os.path.join(KI, "tools/run_marrmot.py"),
                    "--forcing", forcing, "--model", MODEL,
                    "--theta", json.dumps(theta),
                    "--output", run_json, "--timeout", "1200"], check=True)

# --- Stage 5: score Q_sim vs Caravan streamflow (mm/d) ---
ts = pd.read_csv(ts_csv)
scdf = pd.DataFrame({"date": fdates.values,
                     "Q_obs": qobs,
                     "Q_sim": ts.Q_mm_d.values})
scdf = scdf.dropna(subset=["Q_obs"])


def score(mask_frame):
    m = all_metrics(mask_frame.Q_obs.values, mask_frame.Q_sim.values)
    return {k: (round(float(v), 4) if v is not None else None)
            for k, v in m.items()}


evalf = scdf[scdf.date >= np.datetime64(CAL_START_D)]     # drop 1999 spin-up
full = score(evalf)
cal = score(scdf[(scdf.date >= np.datetime64(CAL_START_D)) &
                 (scdf.date <= np.datetime64(CAL_END_D))])
val = score(scdf[scdf.date >= np.datetime64(VAL_START_D)])

# --- water balance over the eval window ---
P = fdf.iloc[:, 1].values
mask = fdates.values >= np.datetime64(CAL_START_D)
tot_P = float(P[mask].sum())
tot_Ea = float(ts.Ea_mm_d.values[mask].sum())
tot_Q = float(ts.Q_mm_d.values[mask].sum())
scols = [c for c in ts.columns if c.startswith("S")]
dS = float(sum(ts[c].values[mask][-1] - ts[c].values[mask][0] for c in scols))
resid = tot_P - tot_Ea - tot_Q - dS
wb_pct = abs(resid) / tot_P * 100.0
wb_status = "PASS" if wb_pct < 5 else ("WARN" if wb_pct < 15 else "FAIL")

result = {
    "model_id": "MARRMoT",
    "this_location": "GRDC-Caravan Extension (5,357 global gauges + basin shapes)",
    "obs_source": ("GRDC-Caravan Extension %s (%s), var=streamflow (mm/d)"
                   % (GAUGE, GAUGE_NAME)),
    "status": "completed",
    "tools_used": [
        "convert_forcing.py (--format csv --pet-method column)",
        "run_marrmot.py (--calibrate --optimizer cmaes, of_NSE, 5 IPOP restarts)",
        "run_marrmot.py (run with calibrated theta)",
        "ki_tools_common.metrics.all_metrics",
    ],
    "tools_failed": [],
    "metrics": {
        "nse": full["NSE"], "kge": full["KGE"], "pbias": full["PBIAS"],
        "r": full["r"],
        "period": "%s..%s daily (1999 spin-up excluded)" % (CAL_START_D, VAL_END_D),
        "nse_cal": cal["NSE"], "kge_cal": cal["KGE"], "pbias_cal": cal["PBIAS"],
        "nse_val": val["NSE"], "kge_val": val["KGE"], "pbias_val": val["PBIAS"],
        "period_calibration": "%s..%s" % (CAL_START_D, CAL_END_D),
        "period_validation": "%s..%s" % (VAL_START_D, VAL_END_D),
    },
    "water_balance": {"status": wb_status, "residual_pct": round(wb_pct, 3)},
    "calibrated_theta": [round(t, 4) for t in theta],
    "notes": (
        "Consistency verifier @ GRDC-Caravan Extension gauge %s (%s; %.0f km2), "
        "warm humid subtropical snow-free -> same m_07 gr4j structure & recipe as "
        "the Bengbu 51080 (Huai) Real-case. Caravan bundles ERA5-Land forcing "
        "(P~5.16, PET~4.99 mm/d, T~17.4C) and streamflow (mm/d) in the gauge "
        "NetCDF, so no CMFD/PET conversion needed. CMA-ES of_NSE, 5 IPOP restarts, "
        "calibrated 2000-2009, validated 2010-2019. Full NSE %s/KGE %s/r %s/"
        "PBIAS %s%%, cal NSE %s, val NSE %s. WB residual %.2f%%. Runoff coef ~0.45."
        % (GAUGE, GAUGE_NAME, AREA_KM2, full["NSE"], full["KGE"], full["r"],
           full["PBIAS"], cal["NSE"], val["NSE"], wb_pct)
    ),
}
with open(os.path.join(STATE, "result.json"), "w") as f:
    json.dump(result, f, indent=2)
print(json.dumps(result, indent=2))
