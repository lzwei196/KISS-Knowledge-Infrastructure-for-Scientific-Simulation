#!/usr/bin/env python3
"""
run_velma.py -- Execute VELMA analytic multi-layer soil hydrology model.

Runs the VELMA-inspired lumped daily model with 4-layer soil water balance,
vertical percolation, lateral subsurface flow, and dual reservoir routing.
Supports two modes:
  - simulate:  Single forward run with given parameters
  - calibrate: Optimize parameters against observed discharge using
               differential evolution

The model implements VELMA's core hydrological processes at daily time steps:
  1. Snow accumulation / melt (degree-day method)
  2. Infiltration into layer 1 (limited by Ksat of L1)
  3. Evapotranspiration extraction from L1-L3 (Hargreaves PET, root-weighted)
  4. Vertical percolation L1->L2->L3->L4 (gravity drainage above FC)
  5. Lateral subsurface flow from each layer (Darcy-based)
  6. Baseflow recession from L4
  7. Surface runoff (saturation excess + direct fraction)
  8. Channel routing (fast + slow linear reservoirs in parallel)

CRITICAL:
  - Forcing data: precip in mm/d, temperature in K, srad in W/m2
    (use convert_forcing_to_velma.py first)
  - Temperature MUST be in Kelvin. The model converts to Celsius internally
    for PET computation.
  - Parameters must be in correct units (use convert_soil_to_velma.py first)
  - Basin area in km2 is required for the mm/d -> m3/s conversion (dt_014)
  - The mm-to-m3/s conversion factor is: area_km2 * 1e6 / 86400 * 1e-3

Usage:
    # Simulation
    python run_velma.py \\
        --mode simulate \\
        --forcing forcing.json \\
        --params params.json \\
        --basin-area-km2 121330 \\
        --output simulation.json

    # Calibration
    python run_velma.py \\
        --mode calibrate \\
        --forcing forcing.json \\
        --observed /path/to/observed_Q.csv \\
        --basin-area-km2 121330 \\
        --cal-start 1981-01-01 --cal-end 1985-12-31 \\
        --maxiter 80 --popsize 20 \\
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

# VELMA default layer thicknesses (mm)
LAYER_THICK = np.array([100.0, 400.0, 1000.0, 1500.0])
N_LAYERS = 4

# Root fraction per layer (for ET partitioning)
ROOT_FRAC = np.array([0.30, 0.40, 0.25, 0.05])

# Parameter names and calibration bounds
PARAM_NAMES = [
    "pet_scale", "perc1", "perc2", "perc3",
    "klat1", "klat2", "klat3", "klat4",
    "k_base", "k_fast", "k_slow", "split", "f_direct", "ddf",
]

PARAM_BOUNDS = [
    (0.3, 2.5),     # pet_scale
    (0.1, 0.9),     # perc1 (fraction/day)
    (0.05, 0.7),    # perc2
    (0.01, 0.5),    # perc3
    (0.01, 0.8),    # klat1 (fraction/day)
    (0.005, 0.5),   # klat2
    (0.001, 0.3),   # klat3
    (0.001, 0.1),   # klat4
    (0.001, 0.1),   # k_base (1/day)
    (0.05, 0.9),    # k_fast (1/day)
    (0.005, 0.15),  # k_slow (1/day)
    (0.1, 0.9),     # split (fast fraction)
    (0.01, 0.20),   # f_direct (impervious fraction)
    (1.0, 8.0),     # ddf (degree-day factor)
]


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


def pet_hargreaves(temp_K, srad_Wm2, pet_scale=1.0):
    """Estimate PET (mm/day) using modified Hargreaves with radiation.

    Parameters
    ----------
    temp_K : float
        Daily mean temperature in Kelvin.
    srad_Wm2 : float
        Daily mean incoming shortwave radiation in W/m2.
    pet_scale : float
        Calibration multiplier on PET.

    Returns
    -------
    pet : float
        Potential evapotranspiration in mm/d.

    Notes
    -----
    Temperature is converted from K to C internally (T_C = temp_K - 273.15).
    This is why forcing must provide temperature in Kelvin.
    """
    T_C = temp_K - 273.15
    # Incoming shortwave -> equivalent evaporation (mm/day)
    # 1 W/m2 = 0.0864 MJ/m2/day; latent heat ~2.45 MJ/kg
    Rn_mm = max(srad_Wm2 * 0.0864 / 2.45, 0)
    # Modified Hargreaves: PET ~ f(T) * Rn
    if T_C < -5:
        pet = 0.0
    else:
        # Priestley-Taylor simplified: PET = alpha * delta/(delta+gamma) * Rn
        # Approximation: delta/(delta+gamma) ~ 0.5 at 15C, varying with T
        s_ratio = 0.3 + 0.025 * max(T_C, 0)
        s_ratio = min(s_ratio, 0.8)
        pet = 1.26 * s_ratio * Rn_mm
    return max(pet * pet_scale, 0.0)


def velma_4layer(prec_mm, temp_K, srad_Wm2, params_dict, area_km2):
    """
    VELMA 4-layer lumped daily soil hydrology model.

    Parameters
    ----------
    prec_mm : ndarray
        Daily precipitation in mm/d.
    temp_K : ndarray
        Daily mean temperature in Kelvin.
    srad_Wm2 : ndarray
        Daily mean solar radiation in W/m2.
    params_dict : dict
        Model parameters (see PARAM_NAMES).
    area_km2 : float
        Basin area in km2 for unit conversion.

    Returns
    -------
    Q_sim : ndarray
        Simulated daily discharge in m3/s.
    diagnostics : dict
        Intermediate variables for debugging.
    """
    p = params_dict

    # Layer properties
    porosity = np.array(p.get("layer_porosity", [0.45, 0.42, 0.38, 0.35]))
    fc_frac = np.array(p.get("layer_fc_frac", [0.55, 0.60, 0.65, 0.70]))
    wp_frac = np.array(p.get("layer_wp_frac", [0.20, 0.22, 0.25, 0.28]))

    layer_cap = porosity * LAYER_THICK
    fc = fc_frac * layer_cap
    wp = wp_frac * layer_cap

    # Process parameters
    pet_scale = p.get("pet_scale", 1.0)
    perc_rate = np.array([p.get("perc1", 0.5), p.get("perc2", 0.3),
                          p.get("perc3", 0.1), 0.0])
    klat = np.array([p.get("klat1", 0.15), p.get("klat2", 0.08),
                     p.get("klat3", 0.03), p.get("klat4", 0.005)])
    k_base = p.get("k_base", 0.02)
    k_fast = p.get("k_fast", 0.3)
    k_slow = p.get("k_slow", 0.02)
    split = p.get("split", 0.5)
    f_direct = p.get("f_direct", 0.05)
    ddf = p.get("ddf", 3.0)
    t_snow = p.get("t_snow", 273.15)
    t_melt = p.get("t_melt", 273.15)

    ndays = len(prec_mm)

    # State variables
    sw = fc.copy()  # initial soil water in each layer (mm)
    swe = 0.0       # snow water equivalent (mm)
    S_fast = 0.0    # fast routing reservoir (mm)
    S_slow = 0.0    # slow routing reservoir (mm)

    # Conversion factor: mm/d over basin -> m3/s
    mm2cms = area_km2 * MM_D_KM2_TO_M3_S

    Q_sim = np.zeros(ndays)
    et_total = np.zeros(ndays)
    runoff_total = np.zeros(ndays)

    for t in range(ndays):
        P = float(prec_mm[t])
        T = float(temp_K[t])
        R = float(srad_Wm2[t])

        # Handle NaN in forcing
        if not np.isfinite(P):
            P = 0.0
        if not np.isfinite(T):
            T = 288.0
        if not np.isfinite(R):
            R = 150.0

        # --- Snow accumulation / melt (degree-day) ---
        if T < t_snow:
            swe += P
            water_input = 0.0
        else:
            water_input = P
            melt = min(swe, ddf * max(T - t_melt, 0))
            swe -= melt
            water_input += melt

        # --- PET (Hargreaves) ---
        pet = pet_hargreaves(T, R, pet_scale)

        # --- Direct runoff (impervious/channel precipitation) ---
        direct_runoff = water_input * f_direct
        water_input -= direct_runoff

        # --- Infiltration into L1 ---
        sw[0] += water_input

        # --- Saturation excess from L1 -> surface runoff ---
        surf_excess = 0.0
        if sw[0] > layer_cap[0]:
            surf_excess = sw[0] - layer_cap[0]
            sw[0] = layer_cap[0]

        # --- ET extraction from L1-L3 (root-weighted with stress) ---
        daily_et = 0.0
        for i in range(N_LAYERS):
            et_demand_i = pet * ROOT_FRAC[i]
            available = max(sw[i] - wp[i], 0)
            if sw[i] > fc[i]:
                stress = 1.0
            elif sw[i] > wp[i]:
                stress = (sw[i] - wp[i]) / max(fc[i] - wp[i], 0.01)
            else:
                stress = 0.0
            actual_et = min(et_demand_i * stress, available)
            sw[i] -= actual_et
            daily_et += actual_et

        # --- Vertical percolation L1->L2->L3->L4 ---
        for i in range(N_LAYERS - 1):
            excess = max(sw[i] - fc[i], 0)
            perc = excess * perc_rate[i]
            sw[i] -= perc
            sw[i + 1] += perc
            # Return saturation excess upward as interflow
            if sw[i + 1] > layer_cap[i + 1]:
                back = sw[i + 1] - layer_cap[i + 1]
                sw[i + 1] = layer_cap[i + 1]
                surf_excess += back

        # --- Lateral subsurface flow from each layer ---
        lat_flow = 0.0
        for i in range(N_LAYERS):
            excess = max(sw[i] - fc[i], 0)
            lat_i = excess * klat[i]
            sw[i] -= lat_i
            lat_flow += lat_i

        # --- Baseflow from L4 ---
        gw_excess = max(sw[3] - wp[3], 0)
        baseflow = gw_excess * k_base
        sw[3] -= baseflow

        # --- Total runoff (mm/day) ---
        total_runoff = direct_runoff + surf_excess + lat_flow + baseflow

        # --- Routing: parallel fast + slow linear reservoirs ---
        S_fast += total_runoff * split
        q_fast = S_fast * k_fast
        S_fast -= q_fast

        S_slow += total_runoff * (1.0 - split)
        q_slow = S_slow * k_slow
        S_slow -= q_slow

        Q_mm = q_fast + q_slow  # mm/day over basin

        # Convert mm/day over basin to m3/s
        Q_sim[t] = Q_mm * mm2cms
        et_total[t] = daily_et
        runoff_total[t] = total_runoff

    diagnostics = {
        "mean_et_mm_d": float(np.mean(et_total)),
        "mean_runoff_mm_d": float(np.mean(runoff_total)),
        "mean_Q_m3s": float(np.mean(Q_sim)),
        "max_Q_m3s": float(np.max(Q_sim)),
        "final_swe_mm": float(swe),
        "final_sw_mm": [float(v) for v in sw],
    }

    return Q_sim, diagnostics


def load_forcing(forcing_path):
    """Load forcing data from JSON (output of convert_forcing_to_velma.py).

    Returns dates, precip (mm/d), temp (K), srad (W/m2).
    """
    with open(forcing_path) as f:
        data = json.load(f)

    if data.get("status") == "error":
        raise ValueError(f"Forcing file has error status: {data.get('errors')}")

    output = data.get("output", data)
    dates = pd.DatetimeIndex(output["dates"])
    prec = np.array(output["prec_mm_d"], dtype=float)
    temp = np.array(output["temp_K"], dtype=float)
    srad = np.array(output.get("srad_Wm2", [200.0] * len(prec)), dtype=float)

    return dates, prec, temp, srad


def load_params(params_path):
    """Load parameter set from JSON (output of convert_soil_to_velma.py)."""
    with open(params_path) as f:
        data = json.load(f)

    if data.get("status") == "error":
        raise ValueError(f"Parameter file has error status: {data.get('errors')}")

    output = data.get("output", data)
    params = output.get("parameters", output)
    return params


def load_observed(obs_path, date_col="dates", q_col="Q"):
    """Load observed discharge from CSV/TSV.

    Handles Bengbu format (tab-separated, dates column, Q column).
    Flags negative values as NaN.
    """
    try:
        obs = pd.read_csv(obs_path, sep="\t", encoding="latin1")
    except Exception:
        obs = pd.read_csv(obs_path)

    # Find date column
    for col in [date_col, "date", "Date", "time", "Time"]:
        if col in obs.columns:
            obs["dates"] = pd.to_datetime(obs[col])
            break

    obs = obs.set_index("dates").sort_index()

    # Find Q column
    for col in [q_col, "Q", "discharge", "q", "streamflow", "Q_m3s"]:
        if col in obs.columns:
            q_series = obs[col].astype(float).copy()
            break
    else:
        raise KeyError(f"No discharge column found in {obs_path}. "
                       f"Available: {list(obs.columns)}")

    q_series.loc[q_series < 0] = np.nan
    return q_series


def compute_nse(obs, sim):
    """Nash-Sutcliffe Efficiency."""
    mask = np.isfinite(obs) & np.isfinite(sim) & (obs > 0)
    if mask.sum() < 10:
        return -999.0
    o, s = obs[mask], sim[mask]
    ss_res = np.sum((o - s) ** 2)
    ss_tot = np.sum((o - np.mean(o)) ** 2)
    return 1.0 - ss_res / ss_tot if ss_tot > 0 else -999.0


def compute_kge(obs, sim):
    """Kling-Gupta Efficiency."""
    mask = np.isfinite(obs) & np.isfinite(sim) & (obs > 0)
    if mask.sum() < 10:
        return -999.0
    o, s = obs[mask], sim[mask]
    r = np.corrcoef(o, s)[0, 1]
    alpha = np.std(s) / np.std(o) if np.std(o) > 0 else 0.0
    beta = np.mean(s) / np.mean(o) if np.mean(o) > 0 else 0.0
    return 1.0 - np.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2)


def compute_pbias(obs, sim):
    """Percent Bias."""
    mask = np.isfinite(obs) & np.isfinite(sim) & (obs > 0)
    if mask.sum() < 10:
        return 999.0
    o, s = obs[mask], sim[mask]
    return 100.0 * np.sum(s - o) / np.sum(o)


def validate_outputs(Q_sim, Q_obs, log):
    """Check output values for physical plausibility."""
    if np.any(Q_sim < 0):
        log.append("[WARN] Negative simulated discharge -- possible model instability")

    if np.any(~np.isfinite(Q_sim)):
        log.append("[CRITICAL] Non-finite values in simulated discharge")

    if np.max(Q_sim) > 100000:
        log.append(f"[WARN] Max simulated Q = {np.max(Q_sim):.1f} m3/s "
                   "-- verify precipitation units and basin area")

    if np.mean(Q_sim) < 0.01:
        log.append(
            "[CRITICAL] Mean simulated Q < 0.01 m3/s -- likely precipitation "
            "is still in kg/m2/s (forgot x 86400, dt_001)")

    if Q_obs is not None:
        mask = np.isfinite(Q_obs) & np.isfinite(Q_sim) & (Q_obs > 0)
        if mask.sum() > 0:
            ratio = np.mean(Q_sim[mask]) / np.mean(Q_obs[mask])
            if ratio > 10:
                log.append(
                    f"[CRITICAL] Sim/Obs mean ratio = {ratio:.1f}x -- "
                    "likely unit mismatch in forcing or area (dt_014)")
            elif ratio < 0.1:
                log.append(
                    f"[CRITICAL] Sim/Obs mean ratio = {ratio:.1f}x -- "
                    "check precipitation conversion or basin area")

    return True


def calibration_objective(param_vec, prec, temp, srad, obs_Q, cal_mask,
                          area_km2, base_params):
    """Objective function for differential evolution.

    Returns negative of (0.5*NSE + 0.5*KGE - 0.002*|PBIAS|).
    """
    params = dict(base_params)
    for name, val in zip(PARAM_NAMES, param_vec):
        params[name] = val

    Q_sim, _ = velma_4layer(prec, temp, srad, params, area_km2)

    sim_cal = Q_sim[cal_mask]
    obs_cal = obs_Q[cal_mask]

    nse = compute_nse(obs_cal, sim_cal)
    kge = compute_kge(obs_cal, sim_cal)
    pbias = compute_pbias(obs_cal, sim_cal)

    obj = -(0.5 * nse + 0.5 * kge - 0.002 * abs(pbias))
    return obj if np.isfinite(obj) else 999.0


def run_simulate(args, log):
    """Run single forward simulation."""
    dates, prec, temp, srad = load_forcing(args.forcing)
    params = load_params(args.params)

    log.append(f"Simulation: {len(dates)} days, area={args.basin_area_km2} km2")

    Q_sim, diag = velma_4layer(prec, temp, srad, params, args.basin_area_km2)

    # Validate outputs
    validate_outputs(Q_sim, None, log)

    log.append(f"Results: mean Q = {diag['mean_Q_m3s']:.1f} m3/s, "
               f"max Q = {diag['max_Q_m3s']:.1f} m3/s")
    log.append(f"Water balance: mean ET = {diag['mean_et_mm_d']:.2f} mm/d, "
               f"mean runoff = {diag['mean_runoff_mm_d']:.2f} mm/d")

    output = {
        "dates": [d.strftime("%Y-%m-%d") for d in dates],
        "Q_sim_m3s": [round(float(v), 3) for v in Q_sim],
        "basin_area_km2": args.basin_area_km2,
        "parameters": params,
        "diagnostics": diag,
    }

    return {"status": "success", "output": output, "log": log}


def run_calibrate(args, log):
    """Run calibration with differential evolution."""
    dates, prec, temp, srad = load_forcing(args.forcing)
    obs_Q = load_observed(args.observed)

    # Align dates
    common = dates.intersection(obs_Q.index)
    date_idx = dates.isin(common)
    obs_aligned = obs_Q.reindex(dates).values

    # Load base parameters (layer properties) if provided
    base_params = {}
    if args.params:
        base_params = load_params(args.params)

    # Define calibration period mask
    cal_start = pd.Timestamp(args.cal_start) if args.cal_start else dates[365]
    cal_end = pd.Timestamp(args.cal_end) if args.cal_end else dates[-1]
    cal_mask = np.array((dates >= cal_start) & (dates <= cal_end))

    n_cal = cal_mask.sum()
    log.append(f"Calibration: {n_cal} days from {cal_start.date()} to {cal_end.date()}")
    log.append(f"Total period: {len(dates)} days, area = {args.basin_area_km2} km2")

    t0 = time.time()
    result = differential_evolution(
        calibration_objective,
        PARAM_BOUNDS,
        args=(prec, temp, srad, obs_aligned, cal_mask,
              args.basin_area_km2, base_params),
        maxiter=args.maxiter,
        popsize=args.popsize,
        tol=1e-4,
        seed=42,
        workers=1,
        disp=True,
    )
    elapsed = time.time() - t0

    best_params = dict(base_params)
    for name, val in zip(PARAM_NAMES, result.x):
        best_params[name] = float(val)

    log.append(f"Calibration completed in {elapsed:.1f}s, "
               f"objective = {result.fun:.4f}")
    log.append("Best parameters:")
    for name, val in zip(PARAM_NAMES, result.x):
        log.append(f"  {name:15s} = {val:.6f}")

    # Run best model
    Q_sim, diag = velma_4layer(prec, temp, srad, best_params, args.basin_area_km2)

    # Compute metrics
    nse = compute_nse(obs_aligned[cal_mask], Q_sim[cal_mask])
    kge = compute_kge(obs_aligned[cal_mask], Q_sim[cal_mask])
    pbias = compute_pbias(obs_aligned[cal_mask], Q_sim[cal_mask])

    log.append(f"Calibration metrics: NSE={nse:.4f}, KGE={kge:.4f}, PBIAS={pbias:.2f}%")

    # Validate outputs
    validate_outputs(Q_sim, obs_aligned, log)

    output = {
        "dates": [d.strftime("%Y-%m-%d") for d in dates],
        "Q_sim_m3s": [round(float(v), 3) for v in Q_sim],
        "Q_obs_m3s": [float(v) if np.isfinite(v) else None for v in obs_aligned],
        "basin_area_km2": args.basin_area_km2,
        "parameters": best_params,
        "calibration": {
            "period": f"{cal_start.date()} to {cal_end.date()}",
            "n_days": int(n_cal),
            "objective": float(result.fun),
            "maxiter": args.maxiter,
            "popsize": args.popsize,
            "elapsed_s": round(elapsed, 1),
            "success": bool(result.success),
        },
        "metrics": {
            "NSE": round(float(nse), 4),
            "KGE": round(float(kge), 4),
            "PBIAS": round(float(pbias), 2),
        },
        "diagnostics": diag,
    }

    return {"status": "success", "output": output, "log": log}


def main():
    parser = argparse.ArgumentParser(
        description="Run VELMA 4-layer soil hydrology model.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
CRITICAL:
  - Temperature MUST be in Kelvin (model converts to C internally)
  - Precipitation must be in mm/d (use convert_forcing_to_velma.py)
  - Basin area must be in km2 for correct Q conversion (dt_014)
""")

    parser.add_argument("--mode", required=True,
                        choices=["simulate", "calibrate"],
                        help="Run mode: simulate or calibrate")
    parser.add_argument("--forcing", required=True,
                        help="Forcing JSON file (from convert_forcing_to_velma.py)")
    parser.add_argument("--params", default=None,
                        help="Parameter JSON file (from convert_soil_to_velma.py)")
    parser.add_argument("--observed", default=None,
                        help="Observed discharge CSV (for calibration)")
    parser.add_argument("--basin-area-km2", type=float, required=True,
                        help="Basin area in km2")
    parser.add_argument("--cal-start", default=None,
                        help="Calibration start date (YYYY-MM-DD)")
    parser.add_argument("--cal-end", default=None,
                        help="Calibration end date (YYYY-MM-DD)")
    parser.add_argument("--maxiter", type=int, default=80,
                        help="Max iterations for calibration (default: 80)")
    parser.add_argument("--popsize", type=int, default=20,
                        help="Population size for DE (default: 20)")
    parser.add_argument("--output", required=True,
                        help="Output JSON file path")

    args = parser.parse_args()

    # Validate inputs
    errors = validate_inputs(args)
    if errors:
        result = {"status": "error", "errors": errors, "log": []}
        json.dump(result, sys.stdout, indent=2)
        sys.exit(1)

    # Run
    log = []
    if args.mode == "simulate":
        result = run_simulate(args, log)
    else:
        result = run_calibrate(args, log)

    # Write output
    output_dir = os.path.dirname(args.output)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    with open(args.output, "w") as f:
        json.dump(result, f, indent=2)

    status = result["status"]
    print(f"\n[run_velma] Status: {status}, mode: {args.mode}")
    print(f"  Output: {args.output}")
    if status == "success":
        out = result["output"]
        n = len(out["dates"])
        print(f"  Days: {n}")
        print(f"  Mean Q: {out['diagnostics']['mean_Q_m3s']:.1f} m3/s")
        print(f"  Max Q: {out['diagnostics']['max_Q_m3s']:.1f} m3/s")
        if "metrics" in out:
            m = out["metrics"]
            print(f"  NSE: {m['NSE']:.4f}, KGE: {m['KGE']:.4f}, "
                  f"PBIAS: {m['PBIAS']:.2f}%")
    for entry in log:
        if "[CRITICAL]" in entry or "[WARN]" in entry:
            print(f"  {entry}")


if __name__ == "__main__":
    main()
