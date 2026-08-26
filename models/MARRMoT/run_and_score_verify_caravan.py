#!/usr/bin/env python3
"""MARRMoT VERIFIER @ GRDC-Caravan Extension: gauge GRDC_3275140
(Rio de los Patos at La Plateada, San Juan, Argentine Andes).

Consistency twin of the Tangnaihai (upper Yellow River) Real-case: a cold,
high-elevation, snowmelt-dominated headwater basin. Same model structure
(m_12_alpine2_6p_2s), same optimiser recipe (CMA-ES on of_NSE with IPOP
restarts), same cal/val protocol, held-out validation window.

  gauge   GRDC_3275140   8,461 km2   31.881 S, 69.690 W
  mean elevation 3,649 m   frac_snow 0.66   mean T -0.2 C
  P 611 mm/yr   Ep 926 mm/yr   Q 146 mm/yr   =>  required Ea = P-Q = 465 mm/yr
  Ep (926) >> required Ea (465): water balance is closable, so the GR4J-style
  "PET too small, mass dumped through the exchange term" failure seen at
  Tangnaihai's Oudin PET cannot occur here.

Caravan bundles catchment-mean ERA5-Land forcing (P, PET, T already in mm/d and
degC) AND observed streamflow (already mm/d) in one per-gauge NetCDF, so no
CMFD extraction, no Hargreaves/Oudin PET, and no m3/s -> mm/d area conversion
are needed. convert_forcing.py --format caravan reads it with netCDF4 (NOT
xarray -- a bare xr.open_dataset() SIGSEGVs at teardown on this box because
pygmt is installed without libgmt).

Period: continuous 1990-01-01..2020-12-31 forcing (ERA5-Land, gap-free).
  1990            spin-up   (excluded from the objective via --cal-start)
  1991-01-01..1998-12-31    calibration  (rows 366..3287)
  2011-01-01..2020-12-31    validation   (held out; 12-year gap from cal)
Observed Q is NaN over 2006-2009 and patchy 1999-2010; MARRMoT's
check_and_select natively drops NaN obs, so no masking is required.

RESUMABLE: every stage skips if its output already exists.
  detached/verify_1/forcing.csv            convert_forcing.py --format caravan
  detached/verify_1/obs_q.csv              bundled streamflow (mm/d)
  detached/verify_1/calib/best_theta.json  CMA-ES of_NSE, 6 IPOP restarts
  detached/verify_1/final/run.json         final full-period run at best theta
  detached/verify_1/final/marrmot_timeseries.csv
  detached/verify_1/result.json            verifier scorecard
"""
import json
import os
import subprocess
import sys

import numpy as np
import pandas as pd

KI = "KISSPATH_KI_ROOT/MARRMoT/knowledge_infrastructure"
KTC = "KISSPATH_KI_TOOLS_COMMON"
STATE = "KISSPATH_KI_ROOT/MARRMoT/detached/verify_1"

sys.path.insert(0, KTC)
from ki_tools_common.metrics import all_metrics  # noqa: E402

PY = sys.executable or "/usr/bin/python3"
CFTOOL = os.path.join(KI, "tools", "convert_forcing.py")
RUNTOOL = os.path.join(KI, "tools", "run_marrmot.py")

GAUGE = "GRDC_3275140"
GAUGE_NAME = "Rio de los Patos at La Plateada, San Juan, Argentina (Andes)"
NC = ("KISSPATH_DATA/observed_data/dischargeandwatershed/"
      f"GRDC-Caravan-extension-nc/timeseries/netcdf/grdc/{GAUGE}.nc")
AREA_KM2 = 8460.835471
MODEL = "m_12_alpine2_6p_2s"
PAR_RANGES = [[-3.0, 5.0], [0.0, 20.0], [1.0, 2000.0],
              [0.05, 0.95], [0.0, 1.0], [0.0, 1.0]]

WIN_START, WIN_END = "1990-01-01", "2020-12-31"
CAL_START_D, CAL_END_D = "1991-01-01", "1998-12-31"
VAL_START_D, VAL_END_D = "2011-01-01", "2020-12-31"

MAX_FUN_EVALS = 900
RESTARTS = 6
SEED = 42

os.makedirs(STATE, exist_ok=True)
CALIB_DIR = os.path.join(STATE, "calib")
FINAL_DIR = os.path.join(STATE, "final")
os.makedirs(CALIB_DIR, exist_ok=True)
os.makedirs(FINAL_DIR, exist_ok=True)

FORCING = os.path.join(STATE, "forcing.csv")
OBS = os.path.join(STATE, "obs_q.csv")
BEST = os.path.join(CALIB_DIR, "best_theta.json")
CALIB_JSON = os.path.join(CALIB_DIR, "calib_run.json")
FINAL_JSON = os.path.join(FINAL_DIR, "run.json")
FINAL_TS = os.path.join(FINAL_DIR, "marrmot_timeseries.csv")
RESULT = os.path.join(STATE, "result.json")

tools_used = []
tools_failed = []
notes = []


def sh(cmd, label):
    print(f"\n=== {label} ===\n{' '.join(cmd)}", flush=True)
    p = subprocess.run(cmd, capture_output=True, text=True)
    print(p.stdout[-3000:], flush=True)
    if p.returncode != 0:
        print(p.stderr[-3000:], file=sys.stderr, flush=True)
        tools_failed.append(label)
        raise SystemExit(f"{label} failed with exit {p.returncode}")
    return p


def forcing_is_current():
    """Resume only on a forcing.csv actually built for THIS gauge and window.

    detached/verify_1 is reused across verifier generations; a previous run left
    a forcing.csv for a different gauge and period behind. Resuming on it would
    silently score this gauge's obs against another basin's forcing, so the
    header's Period stamp is checked before any stage is skipped.
    """
    if not (os.path.exists(FORCING) and os.path.exists(OBS)):
        return False
    want = f"# Period: {WIN_START} to {WIN_END}"
    with open(FORCING) as fh:
        head = [next(fh, "") for _ in range(5)]
    if not any(line.strip() == want for line in head):
        print(f"[stale] forcing.csv is not {want!r} -- rebuilding", flush=True)
        return False
    return True


# --- Stage 1: forcing + obs straight out of the Caravan NetCDF --------------
if not forcing_is_current():
    sh([PY, CFTOOL, "--format", "caravan", "--input", NC,
        "--start", WIN_START, "--end", WIN_END,
        "--output", FORCING, "--obs-output", OBS], "convert_forcing")
else:
    print("[resume] forcing.csv + obs_q.csv already present", flush=True)
tools_used.append("convert_forcing.py (--format caravan)")

forc = pd.read_csv(FORCING, comment="#", parse_dates=["date"])
obs = pd.read_csv(OBS, parse_dates=["date"])
assert len(forc) == len(obs), (len(forc), len(obs))
dates = forc["date"]

# 1-based row indices into the forcing series for the calibration objective
cal_start = int(np.where(dates == pd.Timestamp(CAL_START_D))[0][0]) + 1
cal_end = int(np.where(dates == pd.Timestamp(CAL_END_D))[0][0]) + 1
print(f"cal rows {cal_start}..{cal_end} "
      f"({CAL_START_D}..{CAL_END_D}); n_forcing={len(forc)}", flush=True)

# Sanity: units + closability (the Tangnaihai lesson -- check Ep > P-Q first)
P_yr = forc["P_mm_d"].mean() * 365.25
Ep_yr = forc["Ep_mm_d"].mean() * 365.25
Q_yr = obs["Q_mm_d"].mean() * 365.25
print(f"P={P_yr:.0f} Ep={Ep_yr:.0f} Q={Q_yr:.0f} mm/yr; "
      f"required Ea = P-Q = {P_yr - Q_yr:.0f} mm/yr", flush=True)
if Ep_yr <= (P_yr - Q_yr):
    notes.append(f"WARNING Ep ({Ep_yr:.0f}) <= required Ea ({P_yr-Q_yr:.0f}) "
                 "mm/yr -- water balance not closable by ET alone")

# --- Stage 2: CMA-ES calibration on 1991-1998 (of_NSE, IPOP restarts) -------
if not os.path.exists(BEST):
    sh([PY, RUNTOOL, "--forcing", FORCING, "--model", MODEL,
        "--s0", "[0,0]", "--delta-t", "1",
        "--calibrate", "--observed", OBS,
        "--optimizer", "cmaes", "--of-name", "of_NSE",
        "--restarts", str(RESTARTS), "--max-fun-evals", str(MAX_FUN_EVALS),
        "--seed", str(SEED),
        "--cal-start", str(cal_start), "--cal-end", str(cal_end),
        "--timeout", "86400",
        "--output", CALIB_JSON], "run_marrmot --calibrate cmaes")
else:
    print("[resume] best_theta.json already present", flush=True)
tools_used.append("run_marrmot.py --calibrate --optimizer cmaes")

with open(BEST) as f:
    best = json.load(f)
theta = best.get("theta") or best.get("best_theta")
theta = [float(x) for x in np.ravel(theta)]
cal_nse_opt = best.get("cal_nse", best.get("cal_of"))
print(f"best theta = {theta}  (cal_NSE from optimiser = {cal_nse_opt})",
      flush=True)

# --- Stage 3: final full-period run at the calibrated theta -----------------
if not (os.path.exists(FINAL_JSON) and os.path.exists(FINAL_TS)):
    sh([PY, RUNTOOL, "--forcing", FORCING, "--model", MODEL,
        "--theta", json.dumps(theta), "--s0", "[0,0]", "--delta-t", "1",
        "--timeout", "86400", "--output", FINAL_JSON], "run_marrmot (final)")
else:
    print("[resume] final run already present", flush=True)
tools_used.append("run_marrmot.py (final run)")

with open(FINAL_JSON) as f:
    runres = json.load(f)
ts = pd.read_csv(FINAL_TS)
qsim = ts["Q_mm_d"].to_numpy(dtype=float)
ea = ts["Ea_mm_d"].to_numpy(dtype=float)
assert len(qsim) == len(forc), (len(qsim), len(forc))
tools_used.append("parse_output (marrmot_timeseries.csv)")

df = pd.DataFrame({"date": dates, "Q_obs": obs["Q_mm_d"].to_numpy(),
                   "Q_sim": qsim, "Ea": ea,
                   "P": forc["P_mm_d"].to_numpy()}).set_index("date")
df.to_csv(os.path.join(STATE, "sim_vs_obs.csv"))


def score(a, b):
    d = df.loc[a:b].dropna(subset=["Q_obs"])
    if len(d) < 30:
        return None, 0
    m = all_metrics(d["Q_obs"].to_numpy(), d["Q_sim"].to_numpy())
    return {k.lower(): (None if not np.isfinite(v) else round(float(v), 4))
            for k, v in m.items()}, len(d)


m_cal, n_cal = score(CAL_START_D, CAL_END_D)
m_val, n_val = score(VAL_START_D, VAL_END_D)
m_full, n_full = score(CAL_START_D, VAL_END_D)
print("cal", n_cal, m_cal, "\nval", n_val, m_val, "\nfull", n_full, m_full,
      flush=True)

# --- Stage 4: water balance + bound pinning --------------------------------
wb_mm = float(runres.get("water_balance", float("nan")))
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

pinned = []
for i, (t, (lo, hi)) in enumerate(zip(theta, PAR_RANGES)):
    span = hi - lo
    if abs(t - lo) < 0.01 * span or abs(t - hi) < 0.01 * span:
        pinned.append({"index": i, "value": t, "range": [lo, hi]})
if pinned:
    notes.append(f"{len(pinned)} calibrated parameter(s) pinned at a "
                 f"parRanges bound: {pinned}")

det = (m_val or {}).get("nse")
if m_val is None:
    status = "failed"
    notes.append("validation window has <30 valid observed days")
else:
    status = "completed"

notes.append(
    f"Caravan gauge {GAUGE} ({GAUGE_NAME}), {AREA_KM2:.0f} km2, mean elev "
    f"3649 m, frac_snow 0.66, mean T -0.2 C. Ran the identical KI pipeline and "
    f"model structure as the Tangnaihai Real-case ({MODEL}, CMA-ES of_NSE, "
    f"{RESTARTS} IPOP restarts, {MAX_FUN_EVALS} eval budget). Forcing and "
    f"observed Q both come from the Caravan NetCDF (ERA5-Land catchment-mean "
    f"P/PET/T in mm/d and degC; streamflow already in mm/d), so no unit "
    f"conversion or PET synthesis was needed. Basin climatology "
    f"P={P_yr:.0f}, Ep={Ep_yr:.0f}, Qobs={Q_yr:.0f} mm/yr -- Ep exceeds the "
    f"required Ea of {P_yr-Q_yr:.0f} mm/yr, so the balance is closable. "
    f"Spin-up 1990, calibration {CAL_START_D}..{CAL_END_D} (n={n_cal}), "
    f"held-out validation {VAL_START_D}..{VAL_END_D} (n={n_val}); a 12-year "
    f"gap separates the two. cal NSE={(m_cal or {}).get('nse')}, "
    f"val NSE={(m_val or {}).get('nse')}. MARRMoT water balance closed to "
    f"{wb_mm:.3e} mm over {P_tot:.0f} mm of precipitation.")

result = {
    "model_id": "MARRMoT",
    "this_location": (f"GRDC-Caravan Extension gauge {GAUGE} -- {GAUGE_NAME}"),
    "obs_source": "GRDC",
    "status": status,
    "tools_used": tools_used,
    "tools_failed": tools_failed,
    "metrics": {
        "nse": det,
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
        "gauge_id": GAUGE,
        "area_km2": AREA_KM2,
        "lat": -31.8813, "lon": -69.6896,
        "model_structure": MODEL,
        "theta": theta,
        "par_ranges": PAR_RANGES,
        "bound_pinning": {"checked": True, "any_pinned": bool(pinned),
                          "pinned": pinned},
        "optimizer": {"name": "cmaes", "of_name": "of_NSE",
                      "restarts": RESTARTS, "max_fun_evals": MAX_FUN_EVALS,
                      "seed": SEED, "cal_nse_from_optimiser": cal_nse_opt},
        "metrics_cal": m_cal, "n_cal_days": n_cal,
        "metrics_val": m_val, "n_val_days": n_val,
        "metrics_cal_to_val_span": m_full, "n_full_days": n_full,
        "water_balance_mm": wb_mm,
        "precip_total_mm": P_tot,
        "climatology_mm_per_yr": {"P": round(P_yr, 1), "Ep": round(Ep_yr, 1),
                                  "Q_obs": round(Q_yr, 1)},
        "spinup": "1990 (excluded from objective via --cal-start)",
    },
}

with open(RESULT, "w") as f:
    json.dump(result, f, indent=2)
print("\nWROTE " + RESULT, flush=True)
print(json.dumps(result["metrics"], indent=2), flush=True)
