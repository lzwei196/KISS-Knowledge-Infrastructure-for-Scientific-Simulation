#!/usr/bin/env python3
"""
run_kineros2.py -- Execute KINEROS2 analytic lumped model.

Runs the KINEROS2-inspired lumped daily model with Green-Ampt infiltration
and dual-reservoir kinematic wave routing. Supports two modes:
  - simulate:  Single forward run with given parameters
  - calibrate: Optimize parameters against observed discharge using
               differential evolution

The model implements KINEROS2's core physics at daily time steps:
  1. Green-Ampt infiltration partitions rainfall into surface excess and
     soil absorption
  2. Soil moisture reservoir with ET extraction (Hamon PET)
  3. Gravity drainage when moisture exceeds field capacity
  4. Two-reservoir routing: fast (surface, nonlinear) + slow (baseflow, linear)

CRITICAL:
  - Forcing data must already be in mm/d and deg C (use convert_forcing first)
  - Parameters must already be in mm/d and mm (use convert_soil first)
  - Basin area in km2 is required for the mm/d -> m3/s conversion (dt_012)
  - The mm-to-m3/s conversion factor is: area_km2 * 1e6 / 86400 * 1e-3

Usage:
    # Simulation
    python run_kineros2.py \\
        --mode simulate \\
        --forcing forcing.json \\
        --params params.json \\
        --basin-area-km2 121330 \\
        --output simulation.json

    # Calibration
    python run_kineros2.py \\
        --mode calibrate \\
        --forcing forcing.json \\
        --observed /path/to/observed_Q.csv \\
        --basin-area-km2 121330 \\
        --cal-start 1981-01-01 --cal-end 1985-12-31 \\
        --maxiter 150 --popsize 20 \\
        --output calibrated.json
"""

import argparse
import json
import os
import sys
import time
import warnings

import numpy as np

try:
    import pandas as pd
except ImportError:
    pd = None

try:
    from scipy.optimize import differential_evolution
except ImportError:
    differential_evolution = None

warnings.filterwarnings("ignore")


# ---- Physical constants --------------------------------------------------------
# Conversion factor: 1 mm/d over 1 km2 -> m3/s
# = 1e-3 m / 86400 s * 1e6 m2 = 1e6 / 86400 * 1e-3 = 0.01157 m3/s per km2
MM_D_KM2_TO_M3_S = 1e6 / 86400.0 * 1e-3  # ~0.01157 per km2


# ---- Parameter bounds (same as convert_soil) -----------------------------------
PARAM_BOUNDS = [
    (1.0,   80.0),     # Ks (mm/d)
    (10.0,  500.0),    # psi_f (mm)
    (100.0, 800.0),    # Smax (mm)
    (0.2,   0.8),      # fc
    (0.01,  0.5),      # k_fast (1/d)
    (0.001, 0.05),     # k_slow (1/d)
    (0.1,   0.7),      # f_slow
    (1.0,   2.0),      # alpha
]

PARAM_NAMES = ["Ks", "psi_f", "Smax", "fc", "k_fast", "k_slow", "f_slow", "alpha"]


def validate_inputs(args):
    """Validate all inputs before running."""
    errors = []

    if not os.path.isfile(args.forcing):
        errors.append(f"Forcing file not found: {args.forcing}")

    if args.params and not os.path.isfile(args.params):
        errors.append(f"Parameter file not found: {args.params}")

    if args.mode == "simulate" and not args.params:
        errors.append("--params required for simulate mode")

    if args.mode == "calibrate":
        if not args.observed:
            errors.append("--observed required for calibrate mode")
        elif not os.path.isfile(args.observed):
            errors.append(f"Observed file not found: {args.observed}")

        if differential_evolution is None:
            errors.append("scipy required for calibration. Run: pip install scipy")

    if args.basin_area_km2 <= 0:
        errors.append(f"Basin area must be positive, got {args.basin_area_km2}")

    if args.mode not in ["simulate", "calibrate"]:
        errors.append(f"Mode must be 'simulate' or 'calibrate', got: {args.mode}")

    if pd is None:
        errors.append("pandas required. Run: pip install pandas")

    return errors


def hamon_pet(temp_c, doy, latitude_deg=33.0):
    """Compute Hamon PET (mm/d) from daily mean temperature and day of year.

    Parameters
    ----------
    temp_c : array-like
        Daily mean temperature in deg C.
    doy : array-like
        Day of year (1-366).
    latitude_deg : float
        Basin centroid latitude in degrees.

    Returns
    -------
    pet : ndarray
        Potential evapotranspiration in mm/d.
    """
    lat_rad = np.radians(latitude_deg)

    # Solar declination (degrees)
    dec = 23.45 * np.sin(np.radians(360.0 / 365.0 * (284 + doy)))
    dec_rad = np.radians(dec)

    # Sunset hour angle -> daylight hours
    # Clamp argument to avoid NaN at high latitudes during polar day/night
    arg = -np.tan(lat_rad) * np.tan(dec_rad)
    arg = np.clip(arg, -1.0, 1.0)
    ws = np.arccos(arg)
    dayl = 24.0 * ws / np.pi  # daylight hours

    # Saturated vapor pressure (kPa) - Tetens formula
    es = 0.611 * np.exp(17.27 * temp_c / (temp_c + 237.3))

    # Saturated vapor density (g/m3)
    svd = 216.7 * es / (temp_c + 273.3)

    # Hamon PET (mm/d) - Hamon 1961
    pet = 0.1651 * dayl * svd / 100.0
    pet = np.maximum(pet, 0.0)

    return pet


def kineros2_lumped(P, PET, params, area_km2):
    """
    Lumped daily model inspired by KINEROS2 physics.

    Green-Ampt infiltration partitions rainfall into surface excess and
    infiltration. Soil moisture is tracked with ET extraction and gravity
    drainage. Two reservoirs (fast + slow) approximate kinematic wave routing.

    Parameters
    ----------
    P : ndarray
        Daily precipitation in mm/d.
    PET : ndarray
        Daily potential evapotranspiration in mm/d.
    params : tuple of 8 floats
        (Ks, psi_f, Smax, fc, k_fast, k_slow, f_slow, alpha)
    area_km2 : float
        Basin area in km2 for unit conversion.

    Returns
    -------
    Q_sim : ndarray
        Simulated daily discharge in m3/s.
    """
    Ks, psi_f, Smax, fc, k_fast, k_slow, f_slow, alpha = params

    n = len(P)
    Q_sim = np.zeros(n)

    # State variables
    S = Smax * fc       # initial soil moisture (mm)
    S_fast = 0.0        # fast reservoir (mm)
    S_slow = 50.0       # slow reservoir (mm) -- baseflow store

    # Conversion: mm/d over basin -> m3/s
    mm2cms = area_km2 * MM_D_KM2_TO_M3_S

    for t in range(n):
        p = max(P[t], 0.0)
        pet_t = max(PET[t], 0.0)

        # ---- Green-Ampt infiltration ----
        # Moisture deficit: fraction of pore space currently empty
        theta_def = max(0.0, 1.0 - S / Smax)

        # Infiltration capacity (Green-Ampt simplified for daily step)
        # f = Ks * (1 + psi_f * theta_def / F_cum)
        # F_cum approximated by current soil moisture S
        if theta_def > 0.01:
            f_cap = Ks * (1.0 + psi_f * theta_def / max(S, 1.0))
        else:
            f_cap = Ks  # near saturation: capacity collapses to Ks

        # Partition rainfall
        infil = min(p, f_cap)
        surf_excess = max(0.0, p - infil)

        # ---- Soil moisture update ----
        S += infil

        # Actual ET (limited by available moisture above wilting point)
        wp = Smax * 0.15  # wilting point approximation
        if S > wp:
            aet = min(pet_t, (S - wp) / max(Smax * fc - wp, 1.0) * pet_t)
        else:
            aet = 0.0
        S -= aet

        # Gravity drainage (percolation when S > field capacity)
        if S > Smax * fc:
            perc = min(Ks * 0.5, S - Smax * fc)
            S -= perc
        else:
            perc = 0.0

        # Saturation excess
        sat_excess = max(0.0, S - Smax)
        S = min(S, Smax)

        total_runoff = surf_excess + sat_excess

        # ---- Routing: fast + slow reservoirs ----
        S_fast += total_runoff * (1.0 - f_slow)
        S_slow += total_runoff * f_slow + perc

        # Nonlinear fast reservoir (kinematic wave approximation)
        Q_fast = k_fast * (S_fast ** alpha)
        Q_fast = min(Q_fast, S_fast)
        S_fast -= Q_fast

        # Linear slow reservoir (baseflow)
        Q_slow = k_slow * S_slow
        Q_slow = min(Q_slow, S_slow)
        S_slow -= Q_slow

        Q_sim[t] = (Q_fast + Q_slow) * mm2cms

    return Q_sim


def load_forcing(forcing_path):
    """Load forcing data from JSON (output of convert_forcing_to_kineros2.py).

    Returns dates, precip (mm/d), temp (deg C).
    """
    with open(forcing_path) as f:
        data = json.load(f)

    if data.get("status") == "error":
        raise ValueError(f"Forcing file has error status: {data.get('errors')}")

    output = data.get("output", data)
    dates = pd.DatetimeIndex(output["dates"])
    prec = np.array(output["prec_mm_d"], dtype=float)
    temp = np.array(output["temp_deg_c"], dtype=float)

    return dates, prec, temp


def load_observed(obs_path, date_col="dates", q_col="Q"):
    """Load observed discharge from CSV/TSV.

    Handles Bengbu format (tab-separated, dates column, Q column).
    Flags negative values (e.g., -99.9) as NaN.
    """
    # Try tab-separated first (Bengbu format), then comma
    try:
        obs = pd.read_csv(obs_path, sep="\t", encoding="latin1")
    except Exception:
        obs = pd.read_csv(obs_path)

    # Find date column
    for col in [date_col, "date", "Date", "time", "Time"]:
        if col in obs.columns:
            obs["dates"] = pd.to_datetime(obs[col])
            break
    else:
        raise KeyError(f"No date column found in {obs_path}")

    obs = obs.set_index("dates").sort_index()

    # Find Q column
    for col in [q_col, "Q", "discharge", "q", "streamflow", "Q_m3s"]:
        if col in obs.columns:
            q_series = obs[col].copy()
            break
    else:
        raise KeyError(f"No discharge column found in {obs_path}")

    # Flag negative sentinel values as NaN
    q_series.loc[q_series < 0] = np.nan

    return q_series


def validate_forcing(prec, temp, log):
    """Pre-run sanity check on forcing data."""
    mean_p = float(np.nanmean(prec))
    mean_t = float(np.nanmean(temp))

    if mean_p > 50:
        log.append(
            f"[CRITICAL] Mean precip = {mean_p:.2f} mm/d -- possible unit error (dt_001)")
        return False
    if mean_p < 0.1:
        log.append(
            f"[CRITICAL] Mean precip = {mean_p:.4f} mm/d -- likely kg/m2/s not mm/d (dt_001)")
        return False
    if mean_t > 100:
        log.append(
            f"[CRITICAL] Mean temp = {mean_t:.1f} -- likely Kelvin not deg C (dt_004)")
        return False
    if np.any(prec < 0):
        log.append("[WARN] Negative precipitation values detected")

    log.append(f"Forcing validation passed (mean P={mean_p:.2f} mm/d, T={mean_t:.1f} C)")
    return True


def validate_outputs(Q_sim, Q_obs, log):
    """Post-run sanity check on simulated discharge."""
    if np.any(Q_sim < 0):
        log.append("[WARN] Negative simulated discharge detected -- model instability")

    if np.any(~np.isfinite(Q_sim)):
        log.append("[CRITICAL] Non-finite values in simulated discharge")
        return False

    if Q_obs is not None:
        mask = ~np.isnan(Q_obs) & np.isfinite(Q_sim)
        if mask.sum() > 0:
            ratio = np.mean(Q_sim[mask]) / max(np.mean(Q_obs[mask]), 1e-6)
            if ratio > 10:
                log.append(
                    f"[WARN] Sim/Obs ratio = {ratio:.1f}x -- "
                    "precipitation or area units may be wrong (dt_012)")
            elif ratio < 0.1:
                log.append(
                    f"[WARN] Sim/Obs ratio = {ratio:.1f}x -- "
                    "check mm/d to m3/s conversion factor")

    max_q = float(np.max(Q_sim))
    mean_q = float(np.mean(Q_sim))
    log.append(f"Output check: mean Q = {mean_q:.1f} m3/s, max Q = {max_q:.1f} m3/s")
    return True


def calc_nse(obs, sim):
    """Nash-Sutcliffe Efficiency."""
    mask = ~np.isnan(obs) & ~np.isnan(sim) & np.isfinite(sim)
    o, s = obs[mask], sim[mask]
    if len(o) < 2:
        return np.nan
    ss_res = np.sum((o - s) ** 2)
    ss_tot = np.sum((o - np.mean(o)) ** 2)
    if ss_tot == 0:
        return np.nan
    return 1.0 - ss_res / ss_tot


def calc_kge(obs, sim):
    """Kling-Gupta Efficiency (2009)."""
    mask = ~np.isnan(obs) & ~np.isnan(sim) & np.isfinite(sim)
    o, s = obs[mask], sim[mask]
    if len(o) < 2:
        return np.nan
    r = np.corrcoef(o, s)[0, 1]
    alpha = np.std(s) / np.std(o) if np.std(o) > 0 else np.nan
    beta = np.mean(s) / np.mean(o) if np.mean(o) > 0 else np.nan
    return 1.0 - np.sqrt((r - 1)**2 + (alpha - 1)**2 + (beta - 1)**2)


def calc_pbias(obs, sim):
    """Percent Bias."""
    mask = ~np.isnan(obs) & ~np.isnan(sim) & np.isfinite(sim)
    o, s = obs[mask], sim[mask]
    if np.sum(o) == 0:
        return np.nan
    return 100.0 * np.sum(s - o) / np.sum(o)


def calc_rmse(obs, sim):
    """Root Mean Square Error."""
    mask = ~np.isnan(obs) & ~np.isnan(sim) & np.isfinite(sim)
    o, s = obs[mask], sim[mask]
    if len(o) == 0:
        return np.nan
    return np.sqrt(np.mean((o - s) ** 2))


def calc_r(obs, sim):
    """Pearson correlation coefficient."""
    mask = ~np.isnan(obs) & ~np.isnan(sim) & np.isfinite(sim)
    o, s = obs[mask], sim[mask]
    if len(o) < 2:
        return np.nan
    return float(np.corrcoef(o, s)[0, 1])


def run_simulation(args):
    """Run a single forward simulation with given parameters."""
    log = []
    t0 = time.time()

    # Load forcing
    dates, prec, temp = load_forcing(args.forcing)
    log.append(f"Loaded forcing: {len(dates)} timesteps "
               f"({dates[0].date()} to {dates[-1].date()})")

    # Validate forcing
    if not validate_forcing(prec, temp, log):
        return {"status": "error", "errors": log}

    # Compute PET
    doy = dates.dayofyear.values
    pet = hamon_pet(temp, doy, latitude_deg=args.latitude)
    log.append(f"PET computed (Hamon method, lat={args.latitude}): "
               f"mean = {np.mean(pet):.2f} mm/d")

    # Load parameters
    with open(args.params) as f:
        pdata = json.load(f)

    if "parameters" in pdata:
        p = pdata["parameters"]
        params = tuple(p[name] for name in PARAM_NAMES)
    else:
        params = tuple(pdata[name] for name in PARAM_NAMES)

    log.append(f"Parameters loaded from {args.params}")
    for name, val in zip(PARAM_NAMES, params):
        log.append(f"  {name:8s} = {val:.4f}")

    # Run model
    Q_sim = kineros2_lumped(prec, pet, params, args.basin_area_km2)
    elapsed = time.time() - t0
    log.append(f"Simulation completed in {elapsed:.2f}s")

    # Validate outputs
    validate_outputs(Q_sim, None, log)

    # Build result
    result = {
        "status": "success",
        "output": {
            "dates": [d.strftime("%Y-%m-%d") for d in dates],
            "Q_sim_m3s": [round(float(v), 4) for v in Q_sim],
            "n_timesteps": len(dates),
            "start_date": dates[0].strftime("%Y-%m-%d"),
            "end_date": dates[-1].strftime("%Y-%m-%d"),
            "basin_area_km2": args.basin_area_km2,
            "parameters": dict(zip(PARAM_NAMES, [round(float(v), 4) for v in params])),
            "stats": {
                "Q_mean_m3s": round(float(np.mean(Q_sim)), 2),
                "Q_max_m3s": round(float(np.max(Q_sim)), 2),
                "Q_min_m3s": round(float(np.min(Q_sim)), 2),
            },
            "elapsed_s": round(elapsed, 2),
        },
        "log": log,
    }

    return result


def run_calibration(args):
    """Run differential evolution calibration against observed discharge."""
    log = []
    t0 = time.time()

    # Load forcing
    dates, prec, temp = load_forcing(args.forcing)
    log.append(f"Loaded forcing: {len(dates)} timesteps")

    if not validate_forcing(prec, temp, log):
        return {"status": "error", "errors": log}

    # Compute PET
    doy = dates.dayofyear.values
    pet = hamon_pet(temp, doy, latitude_deg=args.latitude)
    log.append(f"PET computed: mean = {np.mean(pet):.2f} mm/d")

    # Load observed
    q_obs_full = load_observed(args.observed)
    log.append(f"Loaded observed discharge: "
               f"{q_obs_full.notna().sum()} valid days")

    # Align forcing and obs on common dates
    common_idx = dates.intersection(q_obs_full.dropna().index)
    if len(common_idx) == 0:
        return {"status": "error",
                "errors": ["No overlapping dates between forcing and observations"],
                "log": log}

    P_all = pd.Series(prec, index=dates).reindex(common_idx).values
    PET_all = pd.Series(pet, index=dates).reindex(common_idx).values
    Q_obs_all = q_obs_full.reindex(common_idx).values

    log.append(f"Common period: {common_idx[0].date()} to {common_idx[-1].date()} "
               f"({len(common_idx)} days)")

    # Define calibration mask
    cal_start = pd.Timestamp(args.cal_start)
    cal_end = pd.Timestamp(args.cal_end)
    cal_mask = (common_idx >= cal_start) & (common_idx <= cal_end)
    n_cal = cal_mask.sum()
    log.append(f"Calibration period: {args.cal_start} to {args.cal_end} "
               f"({n_cal} days)")

    if n_cal < 100:
        return {"status": "error",
                "errors": [f"Too few calibration days ({n_cal}). Need >= 100."],
                "log": log}

    # Objective function
    def objective(params_vec):
        """Minimize negative (0.5*KGE + 0.5*NSE) on calibration period."""
        params = tuple(params_vec)
        Q_sim = kineros2_lumped(P_all, PET_all, params, args.basin_area_km2)

        obs_cal = Q_obs_all[cal_mask]
        sim_cal = Q_sim[cal_mask]

        valid = ~np.isnan(obs_cal) & ~np.isnan(sim_cal) & np.isfinite(sim_cal)
        if valid.sum() < 100:
            return 999.0

        kge = calc_kge(obs_cal[valid], sim_cal[valid])
        nse = calc_nse(obs_cal[valid], sim_cal[valid])

        if np.isnan(kge) or np.isnan(nse):
            return 999.0

        return -(0.5 * kge + 0.5 * nse)

    # Run optimization
    log.append(f"Starting differential evolution: "
               f"maxiter={args.maxiter}, popsize={args.popsize}")

    de_result = differential_evolution(
        objective, PARAM_BOUNDS,
        maxiter=args.maxiter, popsize=args.popsize,
        seed=args.seed, tol=1e-6,
        disp=False, workers=1,
        polish=True,
    )

    best_params = tuple(de_result.x)
    log.append(f"Optimization converged: {de_result.success}")
    log.append(f"Best objective: {de_result.fun:.4f}")
    log.append(f"Optimized parameters:")
    for name, val in zip(PARAM_NAMES, best_params):
        log.append(f"  {name:8s} = {val:.4f}")

    # Run final simulation with best params
    Q_sim_all = kineros2_lumped(P_all, PET_all, best_params, args.basin_area_km2)

    # Compute metrics on calibration period
    obs_cal = Q_obs_all[cal_mask]
    sim_cal = Q_sim_all[cal_mask]
    v = ~np.isnan(obs_cal)

    cal_metrics = {
        "NSE": round(float(calc_nse(obs_cal[v], sim_cal[v])), 4),
        "KGE": round(float(calc_kge(obs_cal[v], sim_cal[v])), 4),
        "r": round(float(calc_r(obs_cal[v], sim_cal[v])), 4),
        "PBIAS": round(float(calc_pbias(obs_cal[v], sim_cal[v])), 2),
        "RMSE": round(float(calc_rmse(obs_cal[v], sim_cal[v])), 1),
    }
    log.append(f"\nCalibration metrics:")
    for k, v_val in cal_metrics.items():
        log.append(f"  {k} = {v_val}")

    # Compute metrics on validation period (everything outside calibration)
    val_mask = ~cal_mask
    val_metrics = {}
    if val_mask.sum() > 100:
        obs_val = Q_obs_all[val_mask]
        sim_val = Q_sim_all[val_mask]
        v2 = ~np.isnan(obs_val)
        if v2.sum() > 50:
            val_metrics = {
                "NSE": round(float(calc_nse(obs_val[v2], sim_val[v2])), 4),
                "KGE": round(float(calc_kge(obs_val[v2], sim_val[v2])), 4),
                "r": round(float(calc_r(obs_val[v2], sim_val[v2])), 4),
                "PBIAS": round(float(calc_pbias(obs_val[v2], sim_val[v2])), 2),
                "RMSE": round(float(calc_rmse(obs_val[v2], sim_val[v2])), 1),
            }
            log.append(f"\nValidation metrics:")
            for k, v_val in val_metrics.items():
                log.append(f"  {k} = {v_val}")

    # Validate outputs
    validate_outputs(Q_sim_all, Q_obs_all, log)

    elapsed = time.time() - t0
    log.append(f"\nTotal calibration time: {elapsed:.1f}s")

    # Build result
    result = {
        "status": "success",
        "output": {
            "dates": [d.strftime("%Y-%m-%d") for d in common_idx],
            "Q_sim_m3s": [round(float(v), 4) for v in Q_sim_all],
            "Q_obs_m3s": [round(float(v), 4) if not np.isnan(v) else None
                          for v in Q_obs_all],
            "n_timesteps": len(common_idx),
            "basin_area_km2": args.basin_area_km2,
            "parameters": dict(zip(PARAM_NAMES,
                                   [round(float(v), 4) for v in best_params])),
            "bounds": dict(zip(PARAM_NAMES,
                               [list(b) for b in PARAM_BOUNDS])),
            "calibration_period": f"{args.cal_start} to {args.cal_end}",
            "calibration_metrics": cal_metrics,
            "validation_metrics": val_metrics,
            "optimization": {
                "converged": bool(de_result.success),
                "objective": round(float(de_result.fun), 4),
                "maxiter": args.maxiter,
                "popsize": args.popsize,
                "seed": args.seed,
            },
            "elapsed_s": round(elapsed, 2),
        },
        "log": log,
    }

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Run KINEROS2 analytic lumped model")
    parser.add_argument("--mode", required=True,
                        choices=["simulate", "calibrate"],
                        help="Run mode: simulate or calibrate")
    parser.add_argument("--forcing", required=True,
                        help="Forcing JSON file (from convert_forcing_to_kineros2.py)")
    parser.add_argument("--params", default=None,
                        help="Parameter JSON file (from convert_soil_to_kineros2.py)")
    parser.add_argument("--observed", default=None,
                        help="Observed discharge file (CSV/TSV)")
    parser.add_argument("--basin-area-km2", type=float, required=True,
                        help="Basin area in km2")
    parser.add_argument("--latitude", type=float, default=33.0,
                        help="Basin centroid latitude in degrees (for Hamon PET)")
    parser.add_argument("--output", required=True,
                        help="Output JSON file path")

    # Calibration options
    parser.add_argument("--cal-start", default="1981-01-01",
                        help="Calibration start date (YYYY-MM-DD)")
    parser.add_argument("--cal-end", default="1985-12-31",
                        help="Calibration end date (YYYY-MM-DD)")
    parser.add_argument("--maxiter", type=int, default=150,
                        help="Max iterations for differential evolution")
    parser.add_argument("--popsize", type=int, default=20,
                        help="Population size for differential evolution")
    parser.add_argument("--seed", type=int, default=42,
                        help="Random seed for reproducibility")

    args = parser.parse_args()

    # Step 1: validate inputs
    errors = validate_inputs(args)
    if errors:
        print(json.dumps({"status": "error", "errors": errors}, indent=2))
        sys.exit(1)

    # Step 2: run
    if args.mode == "simulate":
        result = run_simulation(args)
    else:
        result = run_calibration(args)

    # Step 3: write output
    out_dir = os.path.dirname(args.output)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    with open(args.output, "w") as f:
        json.dump(result, f, indent=2)

    # Print log
    if result["status"] == "error":
        print(json.dumps(result, indent=2))
        sys.exit(1)
    else:
        for line in result.get("log", []):
            print(line)
        print(f"\nOutput written to {args.output}")


if __name__ == "__main__":
    main()
