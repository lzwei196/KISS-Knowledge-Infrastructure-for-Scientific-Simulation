#!/usr/bin/env python3
"""
run_wasp.py -- Execute WASP analytic water quality model.

Runs the WASP-inspired analytic lake water quality model with three modes:
  - simulate:  Single forward run with given parameters
  - calibrate: Optimize parameters against WQP observations using Nelder-Mead
  - profile:   Generate vertical T/DO profiles for a given depth range

The model implements WASP's core physics:
  1. Sinusoidal seasonal temperature model: T(doy) = T_mean + A*sin(2*pi*(doy-phase)/365)
  2. Benson-Krause DO saturation: DO_sat(T) from temperature
  3. Streeter-Phelps BOD-DO coupling: deficit evolution with deoxygenation + reaeration
  4. Logistic thermocline: T(z) = T_bot + (T_surf-T_bot)/(1+exp((z-z_thermo)/w))
  5. 1-D DO profile: epilimnion near saturation, hypolimnion depleted
  6. Carlson TSI: trophic state from Chl-a, Secchi, and/or TP

CRITICAL:
  - Forcing data must already be in deg C and mg/L (use convert_forcing_to_wasp first)
  - Parameters must already be in model units (use convert_parameters_to_wasp first)
  - DO saturation is computed internally from temperature via Benson-Krause

Usage:
    # Simulation with preset parameters
    python run_wasp.py \\
        --mode simulate \\
        --forcing forcing.json \\
        --params params.json \\
        --output simulation.json

    # Calibration against observations
    python run_wasp.py \\
        --mode calibrate \\
        --forcing forcing.json \\
        --params params.json \\
        --cal-split 0.6 \\
        --output calibrated.json

    # Vertical profile generation
    python run_wasp.py \\
        --mode profile \\
        --params params.json \\
        --z-max 25 --z-step 0.5 \\
        --output profiles.json
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
    from scipy.optimize import minimize
except ImportError:
    minimize = None

warnings.filterwarnings("ignore")


# ============================================================================
# WASP PHYSICS MODULES
# ============================================================================

def do_saturation(T_celsius):
    """DO saturation concentration (mg/L) as function of temperature.

    Benson & Krause (1984) formula used in WASP.
    Valid range: 0-40 deg C. Outside this range, values are extrapolated
    but may be inaccurate.

    At 20 C: ~9.09 mg/L.  At 0 C: ~14.6 mg/L.  At 30 C: ~7.56 mg/L.
    """
    TK = np.asarray(T_celsius, dtype=float) + 273.15
    ln_DO = (-139.34411 + 1.575701e5 / TK - 6.642308e7 / TK**2
             + 1.2438e10 / TK**3 - 8.621949e11 / TK**4)
    return np.exp(ln_DO)


def streeter_phelps(t, BOD0, DO0, DOsat, kd, ka):
    """Classic Streeter-Phelps BOD-DO model (vectorized time stepping).

    Parameters
    ----------
    t : ndarray
        Time points (days).
    BOD0 : float
        Initial biochemical oxygen demand (mg/L).
    DO0 : float
        Initial dissolved oxygen (mg/L).
    DOsat : float
        Saturated dissolved oxygen at current temperature (mg/L).
    kd : float
        BOD deoxygenation rate (1/d).
    ka : float
        Reaeration rate (1/d).

    Returns
    -------
    BOD : ndarray
        BOD concentration at each time point (mg/L).
    DO : ndarray
        DO concentration at each time point (mg/L).
    """
    n = len(t)
    BOD = np.zeros(n)
    DO = np.zeros(n)
    BOD[0] = BOD0
    DO[0] = DO0

    for i in range(1, n):
        dt = t[i] - t[i - 1]
        BOD[i] = BOD[i - 1] * np.exp(-kd * dt)
        deficit_prev = DOsat - DO[i - 1]
        if abs(ka - kd) > 1e-10:
            deficit = (kd * BOD[i - 1] / (ka - kd)) * \
                (np.exp(-kd * dt) - np.exp(-ka * dt)) + \
                deficit_prev * np.exp(-ka * dt)
        else:
            # L'Hopital limit for ka == kd
            deficit = kd * BOD[i - 1] * dt * np.exp(-kd * dt) + \
                deficit_prev * np.exp(-ka * dt)
        DO[i] = max(0.0, DOsat - deficit)

    return BOD, DO


def thermal_profile_1d(depths, T_surface, T_bottom, thermo_depth, thermo_width):
    """1-D lake thermal profile using logistic thermocline model.

    CE-QUAL-W2 style sigmoid function:
    T(z) = T_bottom + (T_surface - T_bottom) / (1 + exp((z - z_thermo) / w))

    Parameters
    ----------
    depths : ndarray
        Depth values (m), 0 = surface.
    T_surface : float
        Epilimnion temperature (deg C).
    T_bottom : float
        Hypolimnion temperature (deg C).
    thermo_depth : float
        Depth of thermocline center (m).
    thermo_width : float
        Thermocline transition width (m). Smaller = sharper.

    Returns
    -------
    T_profile : ndarray
        Temperature at each depth (deg C).
    """
    tw = max(thermo_width, 0.1)  # prevent division by zero
    return T_bottom + (T_surface - T_bottom) / \
        (1.0 + np.exp((depths - thermo_depth) / tw))


def do_profile_1d(depths, T_profile, hypo_depletion_rate, thermocline_depth):
    """1-D DO profile: epilimnion near saturation, hypolimnion depleted.

    Parameters
    ----------
    depths : ndarray
        Depth values (m).
    T_profile : ndarray
        Temperature at each depth (deg C).
    hypo_depletion_rate : float
        DO depletion rate per meter below thermocline.
    thermocline_depth : float
        Depth of thermocline (m).

    Returns
    -------
    DO_profile : ndarray
        Dissolved oxygen at each depth (mg/L).
    """
    DOsat = do_saturation(T_profile)
    DO = np.zeros_like(depths, dtype=float)

    for i, z in enumerate(depths):
        if z <= thermocline_depth * 0.7:
            # Epilimnion: near saturation with slight depth decay
            DO[i] = DOsat[i] * (0.95 + 0.05 * np.exp(-z / 2.0))
        elif z <= thermocline_depth * 1.3:
            # Metalimnion: transition zone
            frac = np.clip(
                (z - thermocline_depth * 0.7) /
                max(thermocline_depth * 0.6, 0.1), 0, 1)
            DO_epi = DOsat[i] * 0.95
            DO_hypo = DOsat[i] * max(
                0, 1.0 - hypo_depletion_rate * (z - thermocline_depth))
            DO[i] = DO_epi * (1 - frac) + DO_hypo * frac
        else:
            # Hypolimnion: depleted by SOD
            DO[i] = DOsat[i] * max(
                0, 1.0 - hypo_depletion_rate * (z - thermocline_depth))

    return np.clip(DO, 0, 20)


def carlson_tsi(chla=None, secchi=None, tp=None):
    """Carlson Trophic State Index (1977).

    Parameters
    ----------
    chla : float or None
        Chlorophyll-a concentration (ug/L).
    secchi : float or None
        Secchi disk depth (m).
    tp : float or None
        Total phosphorus concentration (ug/L).

    Returns
    -------
    tsi : dict
        Dictionary of TSI values and mean.
    """
    tsi = {}
    if chla is not None and chla > 0:
        tsi["TSI_chla"] = 9.81 * np.log(chla) + 30.6
    if secchi is not None and secchi > 0:
        tsi["TSI_secchi"] = 60 - 14.41 * np.log(secchi)
    if tp is not None and tp > 0:
        tsi["TSI_tp"] = 14.42 * np.log(tp) + 4.15
    if tsi:
        tsi["TSI_mean"] = float(np.mean(list(tsi.values())))
    return tsi


def temp_seasonal_model(params, doy):
    """Sinusoidal seasonal temperature model.

    T(doy) = T_mean + amplitude * sin(2*pi*(doy - phase)/365)

    Parameters
    ----------
    params : tuple or list of 3
        (T_mean, amplitude, phase)
    doy : ndarray
        Day of year values (1-366).

    Returns
    -------
    T : ndarray
        Temperature predictions (deg C).
    """
    T_mean, amplitude, phase = params
    return T_mean + amplitude * np.sin(2 * np.pi * (doy - phase) / 365.0)


def do_seasonal_model(params, doy, temp_params):
    """Seasonal DO model coupled to temperature via Streeter-Phelps steady-state.

    Parameters
    ----------
    params : tuple or list of 4
        (kd, ka, BOD0, DO_offset)
    doy : ndarray
        Day of year values.
    temp_params : dict
        Temperature model parameters with keys T_mean, amplitude, phase.

    Returns
    -------
    DO : ndarray
        Dissolved oxygen predictions (mg/L).
    """
    kd, ka, BOD0, DO_offset = params
    T = temp_seasonal_model(
        [temp_params["T_mean"], temp_params["amplitude"],
         temp_params["phase"]], doy)
    DOsat = do_saturation(T)

    if abs(ka - kd) > 1e-6:
        deficit = kd * BOD0 / (ka - kd + 1e-10)
    else:
        deficit = BOD0 * kd

    return np.clip(DOsat - deficit + DO_offset, 0, 20)


def calc_metrics(obs, sim):
    """Compute R, RMSE, bias, MAE between observed and simulated arrays."""
    mask = np.isfinite(obs) & np.isfinite(sim)
    o, s = np.asarray(obs)[mask], np.asarray(sim)[mask]
    if len(o) < 3:
        return {"R": float("nan"), "RMSE": float("nan"),
                "bias": float("nan"), "MAE": float("nan"), "n": int(len(o))}
    return {
        "R": float(np.corrcoef(o, s)[0, 1]),
        "RMSE": float(np.sqrt(np.mean((s - o)**2))),
        "bias": float(np.mean(s - o)),
        "MAE": float(np.mean(np.abs(s - o))),
        "n": int(len(o)),
    }


# ============================================================================
# INPUT/OUTPUT
# ============================================================================

def validate_inputs(args):
    """Validate all inputs before running."""
    errors = []

    if args.mode in ("simulate", "calibrate") and not args.forcing:
        errors.append("--forcing required for simulate/calibrate mode")
    if args.forcing and not os.path.isfile(args.forcing):
        errors.append(f"Forcing file not found: {args.forcing}")

    if not args.params:
        errors.append("--params required")
    elif not os.path.isfile(args.params):
        errors.append(f"Parameter file not found: {args.params}")

    if args.mode == "calibrate" and minimize is None:
        errors.append(
            "scipy required for calibration. Run: pip install scipy")

    if args.mode not in ("simulate", "calibrate", "profile"):
        errors.append(
            f"Mode must be 'simulate', 'calibrate', or 'profile', "
            f"got: {args.mode}")

    if pd is None:
        errors.append("pandas required. Run: pip install pandas")

    if args.cal_split <= 0 or args.cal_split >= 1:
        errors.append(
            f"--cal-split must be between 0 and 1, got: {args.cal_split}")

    return errors


def load_forcing(forcing_path, log):
    """Load forcing data from JSON (output of convert_forcing_to_wasp.py).

    Returns dict with temperature, DO, chla data as DataFrames.
    """
    with open(forcing_path) as f:
        data = json.load(f)

    if data.get("status") == "error":
        raise ValueError(f"Forcing file has error status: {data.get('errors')}")

    output = data.get("output", data)
    result = {}

    for var_key in ("temperature", "do", "chla"):
        records = output.get(var_key)
        if records and isinstance(records, list) and len(records) > 0:
            df = pd.DataFrame(records)
            df["date"] = pd.to_datetime(df["date"])
            df["doy"] = df["date"].dt.dayofyear
            result[var_key] = df
            log.append(
                f"  Loaded {var_key}: {len(df)} records, "
                f"{df['date'].min().date()} to {df['date'].max().date()}")

    # Load profile data if present
    profiles = output.get("profiles")
    if profiles and isinstance(profiles, list) and len(profiles) > 0:
        result["profiles"] = pd.DataFrame(profiles)
        log.append(f"  Loaded profiles: {len(profiles)} records")

    return result


def load_params(params_path, log):
    """Load parameter set from JSON (output of convert_parameters_to_wasp.py)."""
    with open(params_path) as f:
        data = json.load(f)

    if "parameters" in data:
        params = data["parameters"]
    else:
        params = data

    log.append(f"  Loaded parameters from {params_path}")
    return params


# ============================================================================
# SIMULATION
# ============================================================================

def run_simulation(args):
    """Run forward simulation with given parameters."""
    log = []
    t0 = time.time()
    log.append("WASP Simulation")
    log.append("=" * 50)

    # Load inputs
    forcing = load_forcing(args.forcing, log)
    params = load_params(args.params, log)

    seasonal = params.get("seasonal", {})
    kinetics = params.get("kinetics", {})
    thermal = params.get("thermal", {})

    output = {"seasonal_temp": None, "seasonal_do": None,
              "profiles": None, "tsi": None}

    # --- Seasonal temperature simulation ---
    if "temperature" in forcing and seasonal:
        temp_df = forcing["temperature"]
        doy = temp_df["doy"].values

        temp_params_vec = [
            seasonal.get("T_mean", 10),
            seasonal.get("amplitude", 10),
            seasonal.get("phase", 130),
        ]
        T_sim = temp_seasonal_model(temp_params_vec, doy)
        T_obs = temp_df["value"].values

        temp_metrics = calc_metrics(T_obs, T_sim)
        log.append(
            f"\n  Temperature: R={temp_metrics['R']:.3f}, "
            f"RMSE={temp_metrics['RMSE']:.2f} C, n={temp_metrics['n']}")

        output["seasonal_temp"] = {
            "dates": temp_df["date"].dt.strftime("%Y-%m-%d").tolist(),
            "doy": doy.tolist(),
            "T_obs": [round(float(v), 2) for v in T_obs],
            "T_sim": [round(float(v), 2) for v in T_sim],
            "metrics": {k: round(v, 4) if isinstance(v, float) else v
                        for k, v in temp_metrics.items()},
            "params": {
                "T_mean": seasonal.get("T_mean"),
                "amplitude": seasonal.get("amplitude"),
                "phase": seasonal.get("phase"),
            },
        }

    # --- Seasonal DO simulation ---
    if "do" in forcing and seasonal and kinetics:
        do_df = forcing["do"]
        doy_do = do_df["doy"].values

        do_params_vec = [
            kinetics.get("kd", 0.1),
            kinetics.get("ka", 0.5),
            kinetics.get("BOD0", 3.0),
            kinetics.get("DO_offset", 0.0),
        ]
        DO_sim = do_seasonal_model(do_params_vec, doy_do, seasonal)
        DO_obs = do_df["value"].values

        do_metrics = calc_metrics(DO_obs, DO_sim)
        log.append(
            f"  DO: R={do_metrics['R']:.3f}, "
            f"RMSE={do_metrics['RMSE']:.2f} mg/L, n={do_metrics['n']}")

        output["seasonal_do"] = {
            "dates": do_df["date"].dt.strftime("%Y-%m-%d").tolist(),
            "doy": doy_do.tolist(),
            "DO_obs": [round(float(v), 2) for v in DO_obs],
            "DO_sim": [round(float(v), 2) for v in DO_sim],
            "metrics": {k: round(v, 4) if isinstance(v, float) else v
                        for k, v in do_metrics.items()},
            "params": dict(zip(
                ["kd", "ka", "BOD0", "DO_offset"], do_params_vec)),
        }

    # --- Vertical profiles ---
    if thermal:
        z_max = params.get("morphometry", {}).get("z_max_m", 25)
        z_step = args.z_step
        depths = np.arange(0, z_max + z_step, z_step)

        T_prof = thermal_profile_1d(
            depths,
            thermal.get("T_surface", 22),
            thermal.get("T_bottom", 8),
            thermal.get("thermo_depth", 15),
            thermal.get("thermo_width", 3),
        )

        hypo_rate = params.get("hypo_depletion_rate", 0.05)
        DO_prof = do_profile_1d(
            depths, T_prof, hypo_rate,
            thermal.get("thermo_depth", 15))

        output["profiles"] = {
            "depths_m": [round(float(d), 2) for d in depths],
            "T_profile_c": [round(float(t), 2) for t in T_prof],
            "DO_profile_mg_l": [round(float(d), 2) for d in DO_prof],
            "thermal_params": thermal,
            "hypo_depletion_rate": hypo_rate,
        }
        log.append(
            f"\n  Profile: {len(depths)} depth points, "
            f"T=[{T_prof.min():.1f}, {T_prof.max():.1f}] C, "
            f"DO=[{DO_prof.min():.1f}, {DO_prof.max():.1f}] mg/L")

    # --- TSI ---
    if "chla" in forcing:
        chla_median = float(forcing["chla"]["value"].median())
        tsi = carlson_tsi(chla=chla_median)
        output["tsi"] = tsi
        log.append(f"\n  TSI (Chl-a median={chla_median:.2f} ug/L):")
        for k, v in tsi.items():
            log.append(f"    {k} = {v:.1f}")

    # --- Streeter-Phelps BOD-DO demonstration ---
    if kinetics:
        t_sp = np.linspace(0, 10, 200)
        T_ref = seasonal.get("T_mean", 15)
        DOsat_ref = float(do_saturation(T_ref))
        BOD_sp, DO_sp = streeter_phelps(
            t_sp,
            BOD0=kinetics.get("BOD0", 3.0),
            DO0=DOsat_ref * 0.95,
            DOsat=DOsat_ref,
            kd=kinetics.get("kd", 0.1),
            ka=kinetics.get("ka", 0.5),
        )
        output["streeter_phelps"] = {
            "t_days": [round(float(t), 3) for t in t_sp],
            "BOD_mg_l": [round(float(b), 3) for b in BOD_sp],
            "DO_mg_l": [round(float(d), 3) for d in DO_sp],
            "DOsat_mg_l": round(DOsat_ref, 3),
            "T_ref_c": T_ref,
        }

    elapsed = time.time() - t0
    log.append(f"\nSimulation completed in {elapsed:.2f}s")

    result = {
        "status": "success",
        "model": "WASP",
        "mode": "simulate",
        "output": output,
        "log": log,
    }

    return result


# ============================================================================
# CALIBRATION
# ============================================================================

def run_calibration(args):
    """Calibrate seasonal T and DO models against observations."""
    log = []
    t0 = time.time()
    log.append("WASP Calibration")
    log.append("=" * 50)

    if minimize is None:
        return {"status": "error",
                "errors": ["scipy required for calibration"],
                "log": log}

    # Load inputs
    forcing = load_forcing(args.forcing, log)
    params = load_params(args.params, log)

    seasonal = params.get("seasonal", {})
    kinetics = params.get("kinetics", {})
    cal_split = args.cal_split

    calibrated_params = {"seasonal": {}, "kinetics": {}}
    output = {}

    # --- Calibrate temperature ---
    temp_metrics_cal = {}
    temp_metrics_val = {}

    if "temperature" in forcing:
        temp_df = forcing["temperature"]
        temp_df = temp_df.dropna(subset=["value"])
        temp_df = temp_df[(temp_df["value"] >= -2) & (temp_df["value"] <= 40)]
        temp_df = temp_df.sort_values("date").reset_index(drop=True)

        n = len(temp_df)
        sp = int(n * cal_split)
        cal_df = temp_df.iloc[:sp]
        val_df = temp_df.iloc[sp:]

        log.append(
            f"\n  Temperature: {n} total -> {len(cal_df)} cal / {len(val_df)} val")

        if len(cal_df) > 20:
            cal_doy = cal_df["doy"].values
            cal_T = cal_df["value"].values

            # Initial guesses
            T_mean_g = float(np.mean(cal_T))
            T_amp_g = float(
                (np.percentile(cal_T, 95) - np.percentile(cal_T, 5)) / 2)

            def temp_cost(p):
                sim = temp_seasonal_model(p, cal_doy)
                return float(np.mean((sim - cal_T)**2))

            res = minimize(
                temp_cost,
                [T_mean_g, T_amp_g, seasonal.get("phase", 100)],
                method="Nelder-Mead",
                options={"maxiter": 5000})

            calibrated_params["seasonal"] = {
                "T_mean": float(res.x[0]),
                "amplitude": float(res.x[1]),
                "phase": float(res.x[2]),
            }

            log.append(
                f"  T params: T_mean={res.x[0]:.2f}, amp={res.x[1]:.2f}, "
                f"phase={res.x[2]:.0f}")

            # Calibration metrics
            sim_cal = temp_seasonal_model(res.x, cal_doy)
            temp_metrics_cal = calc_metrics(cal_T, sim_cal)
            log.append(
                f"  T Cal: R={temp_metrics_cal['R']:.3f}, "
                f"RMSE={temp_metrics_cal['RMSE']:.2f} C")

            # Validation metrics
            if len(val_df) > 10:
                val_doy = val_df["doy"].values
                val_T = val_df["value"].values
                sim_val = temp_seasonal_model(res.x, val_doy)
                temp_metrics_val = calc_metrics(val_T, sim_val)
                log.append(
                    f"  T Val: R={temp_metrics_val['R']:.3f}, "
                    f"RMSE={temp_metrics_val['RMSE']:.2f} C")

    # --- Calibrate DO ---
    do_metrics_cal = {}
    do_metrics_val = {}

    if "do" in forcing and calibrated_params.get("seasonal"):
        do_df = forcing["do"]
        do_df = do_df.dropna(subset=["value"])
        do_df = do_df[(do_df["value"] >= 0) & (do_df["value"] <= 20)]
        do_df = do_df.sort_values("date").reset_index(drop=True)

        n = len(do_df)
        sp = int(n * cal_split)
        cal_do_df = do_df.iloc[:sp]
        val_do_df = do_df.iloc[sp:]

        log.append(
            f"\n  DO: {n} total -> {len(cal_do_df)} cal / {len(val_do_df)} val")

        if len(cal_do_df) > 20:
            cal_doy_do = cal_do_df["doy"].values
            cal_DO = cal_do_df["value"].values
            temp_p = calibrated_params["seasonal"]

            def do_cost(p):
                sim = do_seasonal_model(p, cal_doy_do, temp_p)
                return float(np.mean((sim - cal_DO)**2))

            res_do = minimize(
                do_cost,
                [kinetics.get("kd", 0.1), kinetics.get("ka", 0.5),
                 kinetics.get("BOD0", 3.0), kinetics.get("DO_offset", 0.0)],
                method="Nelder-Mead",
                options={"maxiter": 5000})

            calibrated_params["kinetics"] = {
                "kd": float(res_do.x[0]),
                "ka": float(res_do.x[1]),
                "BOD0": float(res_do.x[2]),
                "DO_offset": float(res_do.x[3]),
            }

            log.append(
                f"  DO params: kd={res_do.x[0]:.4f}, ka={res_do.x[1]:.4f}, "
                f"BOD0={res_do.x[2]:.2f}, offset={res_do.x[3]:.2f}")

            sim_cal_do = do_seasonal_model(res_do.x, cal_doy_do, temp_p)
            do_metrics_cal = calc_metrics(cal_DO, sim_cal_do)
            log.append(
                f"  DO Cal: R={do_metrics_cal['R']:.3f}, "
                f"RMSE={do_metrics_cal['RMSE']:.2f} mg/L")

            if len(val_do_df) > 10:
                val_doy_do = val_do_df["doy"].values
                val_DO = val_do_df["value"].values
                sim_val_do = do_seasonal_model(res_do.x, val_doy_do, temp_p)
                do_metrics_val = calc_metrics(val_DO, sim_val_do)
                log.append(
                    f"  DO Val: R={do_metrics_val['R']:.3f}, "
                    f"RMSE={do_metrics_val['RMSE']:.2f} mg/L")

    elapsed = time.time() - t0
    log.append(f"\nCalibration completed in {elapsed:.2f}s")

    output = {
        "calibrated_params": calibrated_params,
        "temperature": {
            "calibration_metrics": {
                k: round(v, 4) if isinstance(v, float) else v
                for k, v in temp_metrics_cal.items()},
            "validation_metrics": {
                k: round(v, 4) if isinstance(v, float) else v
                for k, v in temp_metrics_val.items()},
        },
        "dissolved_oxygen": {
            "calibration_metrics": {
                k: round(v, 4) if isinstance(v, float) else v
                for k, v in do_metrics_cal.items()},
            "validation_metrics": {
                k: round(v, 4) if isinstance(v, float) else v
                for k, v in do_metrics_val.items()},
        },
        "cal_split": cal_split,
    }

    result = {
        "status": "success",
        "model": "WASP",
        "mode": "calibrate",
        "output": output,
        "log": log,
    }

    return result


# ============================================================================
# PROFILE GENERATION
# ============================================================================

def run_profile(args):
    """Generate vertical T/DO profiles."""
    log = []
    t0 = time.time()
    log.append("WASP Profile Generation")
    log.append("=" * 50)

    params = load_params(args.params, log)
    thermal = params.get("thermal", {})
    morphometry = params.get("morphometry", {})

    z_max = args.z_max if args.z_max else morphometry.get("z_max_m", 25)
    z_step = args.z_step
    depths = np.arange(0, z_max + z_step, z_step)

    T_prof = thermal_profile_1d(
        depths,
        thermal.get("T_surface", 22),
        thermal.get("T_bottom", 8),
        thermal.get("thermo_depth", 15),
        thermal.get("thermo_width", 3),
    )

    hypo_rate = params.get("hypo_depletion_rate", 0.05)
    DO_prof = do_profile_1d(
        depths, T_prof, hypo_rate,
        thermal.get("thermo_depth", 15))

    DOsat_prof = do_saturation(T_prof)

    log.append(
        f"  Depth range: 0 - {z_max} m, step = {z_step} m")
    log.append(
        f"  {len(depths)} depth points")
    log.append(
        f"  T range: {T_prof.min():.1f} - {T_prof.max():.1f} C")
    log.append(
        f"  DO range: {DO_prof.min():.1f} - {DO_prof.max():.1f} mg/L")
    log.append(
        f"  DOsat range: {DOsat_prof.min():.1f} - {DOsat_prof.max():.1f} mg/L")

    elapsed = time.time() - t0

    output = {
        "depths_m": [round(float(d), 2) for d in depths],
        "T_profile_c": [round(float(t), 3) for t in T_prof],
        "DO_profile_mg_l": [round(float(d), 3) for d in DO_prof],
        "DOsat_profile_mg_l": [round(float(d), 3) for d in DOsat_prof],
        "n_depths": len(depths),
        "z_max_m": z_max,
        "z_step_m": z_step,
        "thermal_params": thermal,
        "hypo_depletion_rate": hypo_rate,
        "stats": {
            "T_surface_c": round(float(T_prof[0]), 2),
            "T_bottom_c": round(float(T_prof[-1]), 2),
            "T_range_c": round(float(T_prof.max() - T_prof.min()), 2),
            "DO_surface_mg_l": round(float(DO_prof[0]), 2),
            "DO_bottom_mg_l": round(float(DO_prof[-1]), 2),
            "DO_min_mg_l": round(float(DO_prof.min()), 2),
        },
        "elapsed_s": round(elapsed, 3),
    }

    result = {
        "status": "success",
        "model": "WASP",
        "mode": "profile",
        "output": output,
        "log": log,
    }

    return result


# ============================================================================
# OUTPUT VALIDATION
# ============================================================================

def validate_outputs(result, log):
    """Post-run sanity check on model outputs."""
    if result.get("status") == "error":
        return result

    output = result.get("output", {})

    # Check seasonal temperature metrics
    temp_out = output.get("seasonal_temp") or \
        output.get("temperature", {})
    if isinstance(temp_out, dict):
        metrics = temp_out.get("metrics") or \
            temp_out.get("calibration_metrics", {})
        r_val = metrics.get("R")
        if r_val is not None and not np.isnan(r_val):
            if r_val < 0:
                log.append(
                    "[WARN] Temperature R < 0 -- model worse than mean. "
                    "Check parameter initialization.")
            elif r_val < 0.5:
                log.append(
                    f"[WARN] Temperature R = {r_val:.3f} -- weak fit. "
                    "Consider adjusting phase parameter.")

    # Check DO metrics
    do_out = output.get("seasonal_do") or \
        output.get("dissolved_oxygen", {})
    if isinstance(do_out, dict):
        metrics = do_out.get("metrics") or \
            do_out.get("calibration_metrics", {})
        rmse = metrics.get("RMSE")
        if rmse is not None and not np.isnan(rmse):
            if rmse > 5.0:
                log.append(
                    f"[WARN] DO RMSE = {rmse:.2f} mg/L -- large error. "
                    "Check BOD/reaeration parameters or data quality.")

    # Check profiles
    prof = output.get("profiles", {})
    if isinstance(prof, dict) and "T_profile_c" in prof:
        T_prof = prof["T_profile_c"]
        if len(T_prof) > 1 and T_prof[0] < T_prof[-1]:
            log.append(
                "[WARN] Surface colder than bottom in profile -- "
                "inverted stratification (check T_surface, T_bottom)")

    return result


# ============================================================================
# MAIN
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Run WASP analytic water quality model")
    parser.add_argument("--mode", required=True,
                        choices=["simulate", "calibrate", "profile"],
                        help="Run mode")
    parser.add_argument("--forcing", default=None,
                        help="Forcing JSON (from convert_forcing_to_wasp.py)")
    parser.add_argument("--params", required=True,
                        help="Parameter JSON (from convert_parameters_to_wasp.py)")
    parser.add_argument("--output", required=True,
                        help="Output JSON file path")

    # Calibration options
    parser.add_argument("--cal-split", type=float, default=0.6,
                        help="Calibration/validation split ratio (default: 0.6)")

    # Profile options
    parser.add_argument("--z-max", type=float, default=None,
                        help="Maximum depth for profile (m)")
    parser.add_argument("--z-step", type=float, default=1.0,
                        help="Depth step for profile (default: 1.0 m)")

    args = parser.parse_args()

    # Step 1: validate inputs
    errors = validate_inputs(args)
    if errors:
        print(json.dumps({"status": "error", "errors": errors}, indent=2))
        sys.exit(1)

    # Step 2: run
    if args.mode == "simulate":
        result = run_simulation(args)
    elif args.mode == "calibrate":
        result = run_calibration(args)
    else:
        result = run_profile(args)

    # Step 3: validate outputs
    result = validate_outputs(result, result.get("log", []))

    # Step 4: write output
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
