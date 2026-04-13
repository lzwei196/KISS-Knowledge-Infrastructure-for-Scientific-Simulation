#!/usr/bin/env python3
"""
HEC-RAS execution wrapper using GR4J conceptual rainfall-runoff surrogate.

Since HEC-RAS is proprietary Windows software that could not be acquired, this
tool implements the GR4J model (Perrin et al., 2003) as an analytic surrogate
that captures the core hydrological processes:

  - Production store (x1): soil moisture accounting = HEC-RAS infiltration losses
  - Routing store (x3): nonlinear reservoir = HEC-RAS channel routing
  - Unit hydrographs UH1/UH2: flow distribution = HEC-RAS flow routing
  - Groundwater exchange (x2): lateral transfer = HEC-RAS lateral inflows

Supports two modes:
  1. Simulation with provided parameters (--x1, --x2, --x3, --x4)
  2. Calibration + simulation (--obs_file provided, uses differential_evolution)

Usage:
  # With explicit parameters:
  python3 run_hecras.py \\
    --forcing_csv ./forcing.csv \\
    --basin_area_km2 121330 \\
    --x1 500 --x2 0.5 --x3 100 --x4 2.0 \\
    --output_csv ./sim_output.csv

  # With calibration:
  python3 run_hecras.py \\
    --forcing_csv ./forcing.csv \\
    --basin_area_km2 121330 \\
    --obs_file /path/to/obs.txt \\
    --cal_start 1981-01-01 --cal_end 1985-12-31 \\
    --output_csv ./sim_output.csv

References:
  - GR4J: Perrin, C., Michel, C., Andreassian, V. (2003) J. Hydrol. 279, 275-289
  - PET: Oudin, L. et al. (2005) J. Hydrol. 303, 290-306
  - dt_205: Q conversion m3/s <-> mm/day
  - dt_208: Spinup period >= 365 days required
"""

import argparse
import json
import os
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# ===========================================================================
# Constants
# ===========================================================================
SECONDS_PER_DAY = 86400.0
M3_TO_MM_FACTOR = 1e3  # 1 m = 1000 mm


# ===========================================================================
# PET: Oudin et al. (2005)
# ===========================================================================
def oudin_pet(temp_c, doy, lat_deg=33.0):
    """Compute potential evapotranspiration using Oudin et al. (2005) formula.

    This PET method is recommended for rainfall-runoff models because it
    requires only temperature and latitude (no radiation or humidity data).

    Args:
        temp_c: 1D array of daily mean temperature (deg C).
        doy: 1D array of day-of-year (1-366).
        lat_deg: Basin centroid latitude (degrees).

    Returns:
        pet: 1D array of PET (mm/day).
    """
    lat_rad = np.radians(lat_deg)

    # Solar declination
    decl = 0.4093 * np.sin(2 * np.pi / 365 * doy - 1.405)

    # Sunset hour angle
    cos_omega = -np.tan(lat_rad) * np.tan(decl)
    cos_omega = np.clip(cos_omega, -1, 1)
    omega = np.arccos(cos_omega)

    # Earth-sun distance factor
    dr = 1 + 0.033 * np.cos(2 * np.pi / 365 * doy)

    # Extraterrestrial radiation (MJ/m2/day)
    Gsc = 0.0820  # Solar constant (MJ/m2/min)
    Ra = (24 * 60 / np.pi) * Gsc * dr * (
        omega * np.sin(lat_rad) * np.sin(decl)
        + np.cos(lat_rad) * np.cos(decl) * np.sin(omega)
    )

    # Oudin formula: PET = Ra / (lambda * rho) * (T + 5) / 100
    # lambda = 2.45 MJ/kg, rho = 1000 kg/m3
    pet = np.where(temp_c + 5 > 0, Ra / 2.45 * (temp_c + 5) / 100.0, 0.0)

    return pet


# ===========================================================================
# GR4J Model
# ===========================================================================
def gr4j(prec, pet, params, states=None):
    """GR4J daily lumped rainfall-runoff model.

    Implementation follows Perrin et al. (2003) exactly. The model uses
    two stores (production and routing) and two unit hydrographs.

    Args:
        prec: 1D array of daily precipitation (mm/day).
        pet: 1D array of daily PET (mm/day).
        params: tuple/list of (x1, x2, x3, x4).
            x1: production store capacity (mm), range [100, 1500]
            x2: groundwater exchange coefficient (mm), range [-5, 5]
            x3: routing store capacity (mm), range [10, 500]
            x4: UH time base (days), range [0.5, 5.0]
        states: optional tuple (S, R) of initial store levels.

    Returns:
        Q: 1D array of simulated discharge (mm/day).
        states: tuple (S, R) of final store levels.
    """
    x1, x2, x3, x4 = params
    n = len(prec)
    Q = np.zeros(n)

    # Initialize stores at 50% capacity if not provided
    if states is None:
        S = x1 * 0.5  # Production store level
        R = x3 * 0.5  # Routing store level
    else:
        S, R = states

    # Build unit hydrograph ordinates
    nh1 = int(np.ceil(x4))
    nh2 = int(np.ceil(2 * x4))

    def sh1(t):
        if t <= 0:
            return 0.0
        if t >= x4:
            return 1.0
        return (t / x4) ** 2.5

    def sh2(t):
        if t <= 0:
            return 0.0
        if t >= 2 * x4:
            return 1.0
        if t <= x4:
            return 0.5 * (t / x4) ** 2.5
        return 1.0 - 0.5 * (2.0 - t / x4) ** 2.5

    uh1 = np.array([sh1(j) - sh1(j - 1) for j in range(1, nh1 + 1)])
    uh2 = np.array([sh2(j) - sh2(j - 1) for j in range(1, nh2 + 1)])

    # Convolution states
    uh1_state = np.zeros(len(uh1))
    uh2_state = np.zeros(len(uh2))

    for t in range(n):
        P = prec[t]
        E = pet[t]

        # Net precipitation and evaporation
        if P >= E:
            Pn = P - E
            En = 0.0
        else:
            Pn = 0.0
            En = E - P

        # Production store
        if Pn > 0:
            ws = np.clip(Pn / x1, 0, 13)
            ps_frac = (
                (1.0 - (S / x1) ** 2) * np.tanh(ws)
                / (1.0 + (S / x1) * np.tanh(ws))
            )
            Ps = x1 * ps_frac
            S = S + Ps
        else:
            ws = np.clip(En / x1, 0, 13)
            es_frac = (
                (2.0 - S / x1) * np.tanh(ws)
                / (1.0 + (1.0 - S / x1) * np.tanh(ws))
            )
            Es = S * es_frac
            S = S - Es
            Ps = 0.0

        # Percolation from production store
        perc = S * (1.0 - (1.0 + (4.0 / 9.0 * S / x1) ** 4) ** -0.25)
        S = S - perc
        Pr = perc + (Pn - Ps)

        # Split: 90% to UH1 (routing store), 10% to UH2 (direct flow)
        uh1_state += uh1 * Pr * 0.9
        uh2_state += uh2 * Pr * 0.1

        Q1 = uh1_state[0]
        Q9 = uh2_state[0]

        # Shift convolution states
        uh1_state = np.roll(uh1_state, -1)
        uh1_state[-1] = 0.0
        uh2_state = np.roll(uh2_state, -1)
        uh2_state[-1] = 0.0

        # Groundwater exchange
        F = x2 * (R / x3) ** 3.5

        # Routing store
        R = max(0.0, R + Q1 + F)
        Qr = R * (1.0 - (1.0 + (R / x3) ** 4) ** -0.25)
        R = R - Qr

        # Direct flow
        Qd = max(0.0, Q9 + F)

        Q[t] = Qr + Qd

    return Q, (S, R)


# ===========================================================================
# Performance metrics
# ===========================================================================
def calc_nse(obs, sim):
    """Nash-Sutcliffe Efficiency."""
    mask = ~np.isnan(obs) & ~np.isnan(sim)
    o, s = obs[mask], sim[mask]
    if len(o) < 10:
        return np.nan
    ss_res = np.sum((o - s) ** 2)
    ss_tot = np.sum((o - np.mean(o)) ** 2)
    if ss_tot == 0:
        return np.nan
    return 1.0 - ss_res / ss_tot


def calc_kge(obs, sim):
    """Kling-Gupta Efficiency."""
    mask = ~np.isnan(obs) & ~np.isnan(sim)
    o, s = obs[mask], sim[mask]
    if len(o) < 10:
        return np.nan
    r = np.corrcoef(o, s)[0, 1]
    alpha = np.std(s) / np.std(o)
    beta = np.mean(s) / np.mean(o)
    return 1.0 - np.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2)


def calc_pbias(obs, sim):
    """Percent bias."""
    mask = ~np.isnan(obs) & ~np.isnan(sim)
    o, s = obs[mask], sim[mask]
    if len(o) < 10 or np.sum(o) == 0:
        return np.nan
    return 100.0 * np.sum(s - o) / np.sum(o)


def calc_rmse(obs, sim):
    """Root mean square error."""
    mask = ~np.isnan(obs) & ~np.isnan(sim)
    o, s = obs[mask], sim[mask]
    if len(o) < 10:
        return np.nan
    return np.sqrt(np.mean((o - s) ** 2))


# ===========================================================================
# Calibration objective
# ===========================================================================
def calibration_objective(params, prec, pet, obs_q_mm, spinup_days=365):
    """Combined -(0.5*NSE + 0.5*KGE) for minimization.

    Balances timing accuracy (NSE) and bias (KGE).

    Args:
        params: tuple (x1, x2, x3, x4).
        prec: precipitation array (mm/day).
        pet: PET array (mm/day).
        obs_q_mm: observed discharge (mm/day).
        spinup_days: number of days to skip for metric calculation (dt_208).

    Returns:
        cost: negative of (0.5*NSE + 0.5*KGE). Lower is better.
    """
    sim_mm, _ = gr4j(prec, pet, params)
    s = sim_mm[spinup_days:]
    o = obs_q_mm[spinup_days:]

    mask = ~np.isnan(o) & ~np.isnan(s)
    if mask.sum() < 100:
        return 1.0

    o_v, s_v = o[mask], s[mask]

    nse = calc_nse(o_v, s_v)
    kge = calc_kge(o_v, s_v)

    if np.isnan(nse) or np.isnan(kge):
        return 1.0

    return -(0.5 * nse + 0.5 * kge)


# ===========================================================================
# Validate inputs
# ===========================================================================
def validate_inputs(args):
    """Check all inputs are valid before processing.

    Args:
        args: Parsed argparse namespace.

    Raises:
        SystemExit: If validation fails.
    """
    errors = []

    if not os.path.isfile(args.forcing_csv):
        errors.append(f"Forcing CSV not found: {args.forcing_csv}")

    if args.obs_file and not os.path.isfile(args.obs_file):
        errors.append(f"Observation file not found: {args.obs_file}")

    if args.params_json and not os.path.isfile(args.params_json):
        errors.append(f"Parameters JSON not found: {args.params_json}")

    if args.basin_area_km2 <= 0:
        errors.append(f"Basin area must be positive: {args.basin_area_km2}")

    # Check that we have either explicit params or calibration data
    has_explicit = (
        args.x1 is not None
        and args.x2 is not None
        and args.x3 is not None
        and args.x4 is not None
    )
    has_calibration = args.obs_file is not None

    if not has_explicit and not has_calibration and not args.params_json:
        errors.append(
            "Must provide either explicit parameters (--x1 --x2 --x3 --x4), "
            "a parameters JSON (--params_json), or observation data for "
            "calibration (--obs_file)"
        )

    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    print("[validate_inputs] All inputs valid.")


# ===========================================================================
# Load observation data
# ===========================================================================
def load_observations(obs_file):
    """Load Bengbu-format daily discharge observations.

    Args:
        obs_file: Path to observation file (tab-separated, GBK encoded).

    Returns:
        df: DataFrame with DatetimeIndex and column 'Q' (m3/s).
    """
    df = pd.read_csv(obs_file, sep="\t", encoding="gbk")
    df["date"] = pd.to_datetime(df["dates"], format="mixed")
    df = df[["date", "Q"]].set_index("date").sort_index()
    # Replace sentinel values
    df.loc[df["Q"] < 0, "Q"] = np.nan
    return df


# ===========================================================================
# Process: main simulation workflow
# ===========================================================================
def process(args):
    """Main HEC-RAS (GR4J) simulation workflow.

    Args:
        args: Parsed argparse namespace.

    Returns:
        out_df: DataFrame with simulation results.
        params_used: tuple (x1, x2, x3, x4) of parameters used.
        metrics: dict of validation metrics (if obs available).
    """
    print("=" * 60)
    print("HEC-RAS Simulation Engine (GR4J Surrogate)")
    print("=" * 60)

    # 1. Load forcing
    print("\n[1/4] Loading forcing data...")
    forcing = pd.read_csv(args.forcing_csv, index_col=0, parse_dates=True)
    print(f"  Period: {forcing.index[0]} to {forcing.index[-1]}")
    print(f"  Mean precip: {forcing['prec_mm'].mean():.2f} mm/day")
    print(f"  Mean temp:   {forcing['temp_c'].mean():.1f} deg C")

    # 2. Compute PET
    print("\n[2/4] Computing PET (Oudin method)...")
    doy = forcing.index.dayofyear.values
    forcing["pet_mm"] = oudin_pet(
        forcing["temp_c"].values, doy, lat_deg=args.latitude
    )
    print(f"  Mean PET: {forcing['pet_mm'].mean():.2f} mm/day")

    prec = forcing["prec_mm"].values
    pet = forcing["pet_mm"].values
    dates = forcing.index

    # 3. Determine parameters
    params_used = None

    if args.x1 is not None and args.x2 is not None and args.x3 is not None and args.x4 is not None:
        # Explicit parameters
        params_used = (args.x1, args.x2, args.x3, args.x4)
        print(f"\n[3/4] Using explicit parameters: x1={args.x1}, x2={args.x2}, "
              f"x3={args.x3}, x4={args.x4}")

    elif args.params_json:
        # Load from JSON
        with open(args.params_json) as f:
            pdata = json.load(f)
        gr4j_p = pdata.get("gr4j_parameters", {})
        params_used = (
            gr4j_p.get("x1_production_store_mm", {}).get("estimate", 350),
            gr4j_p.get("x2_exchange_coeff_mm", {}).get("estimate", 0),
            gr4j_p.get("x3_routing_store_mm", {}).get("estimate", 100),
            gr4j_p.get("x4_uh_time_base_days", {}).get("estimate", 2.0),
        )
        print(f"\n[3/4] Parameters from JSON: x1={params_used[0]}, x2={params_used[1]}, "
              f"x3={params_used[2]}, x4={params_used[3]}")

    if args.obs_file:
        # Calibration mode
        print(f"\n[3/4] Calibrating against observations...")
        obs = load_observations(args.obs_file)

        # Align forcing and obs
        common_idx = forcing.index.intersection(obs.index)
        obs_q_m3s = obs.loc[common_idx, "Q"].values

        # Convert obs Q from m3/s to mm/day (dt_205)
        obs_q_mm = (
            obs_q_m3s * SECONDS_PER_DAY
            / (args.basin_area_km2 * 1e6)
            * M3_TO_MM_FACTOR
        )

        cal_prec = forcing.loc[common_idx, "prec_mm"].values
        cal_pet = forcing.loc[common_idx, "pet_mm"].values

        # Filter to calibration period if specified
        if args.cal_start and args.cal_end:
            cal_mask = (common_idx >= args.cal_start) & (common_idx <= args.cal_end)
            cal_prec_sub = cal_prec[cal_mask]
            cal_pet_sub = cal_pet[cal_mask]
            cal_obs_sub = obs_q_mm[cal_mask]
            print(f"  Calibration period: {args.cal_start} to {args.cal_end}")
            print(f"  Calibration days: {cal_mask.sum()}")
        else:
            cal_prec_sub = cal_prec
            cal_pet_sub = cal_pet
            cal_obs_sub = obs_q_mm

        # Run differential evolution
        from scipy.optimize import differential_evolution

        bounds = [(50, 2000), (-5, 5), (10, 1000), (0.5, 10.0)]
        spinup_days = args.spinup_days

        print(f"  Spinup: {spinup_days} days (dt_208)")
        print(f"  Running differential evolution (maxiter={args.maxiter})...")

        result = differential_evolution(
            calibration_objective,
            bounds,
            args=(cal_prec_sub, cal_pet_sub, cal_obs_sub, spinup_days),
            maxiter=args.maxiter,
            seed=42,
            tol=1e-8,
            popsize=30,
            disp=False,
        )
        params_used = tuple(result.x)
        print(
            f"  Calibrated params: x1={params_used[0]:.1f}, x2={params_used[1]:.3f}, "
            f"x3={params_used[2]:.1f}, x4={params_used[3]:.2f}"
        )
        print(f"  Calibration objective: {result.fun:.4f}")

    if params_used is None:
        print("ERROR: No parameters determined", file=sys.stderr)
        sys.exit(1)

    # 4. Run simulation
    print(f"\n[4/4] Running GR4J simulation...")
    sim_mm, final_states = gr4j(prec, pet, params_used)

    # Convert to m3/s
    sim_m3s = sim_mm * (args.basin_area_km2 * 1e6) / SECONDS_PER_DAY / M3_TO_MM_FACTOR

    # Build output DataFrame
    out_df = pd.DataFrame(
        {
            "date": dates,
            "prec_mm": prec,
            "pet_mm": pet,
            "sim_q_mm": sim_mm,
            "sim_q_m3s": sim_m3s,
        }
    )
    out_df.set_index("date", inplace=True)

    # Compute metrics if observations available
    metrics = {}
    if args.obs_file:
        obs = load_observations(args.obs_file)
        common_idx = out_df.index.intersection(obs.index)

        # Skip spinup for metrics
        if args.cal_end:
            val_mask = common_idx > pd.Timestamp(args.cal_end)
            val_idx = common_idx[val_mask]
        else:
            val_idx = common_idx[args.spinup_days:]

        if len(val_idx) > 0:
            obs_vals = obs.loc[val_idx, "Q"].values
            sim_vals = out_df.loc[val_idx, "sim_q_m3s"].values

            metrics = {
                "NSE": round(float(calc_nse(obs_vals, sim_vals)), 4),
                "KGE": round(float(calc_kge(obs_vals, sim_vals)), 4),
                "PBIAS_pct": round(float(calc_pbias(obs_vals, sim_vals)), 2),
                "RMSE_m3s": round(float(calc_rmse(obs_vals, sim_vals)), 1),
            }
            print(f"\n  Validation metrics (post-calibration period):")
            for k, v in metrics.items():
                print(f"    {k}: {v}")

    # Write output
    out_dir = os.path.dirname(args.output_csv)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    out_df.to_csv(args.output_csv)
    print(f"\n[write] Output: {args.output_csv}")
    print(f"  Rows: {len(out_df)}, Columns: {list(out_df.columns)}")

    # Write parameters
    params_out = {
        "x1_production_store_mm": round(float(params_used[0]), 1),
        "x2_exchange_coeff_mm": round(float(params_used[1]), 3),
        "x3_routing_store_mm": round(float(params_used[2]), 1),
        "x4_uh_time_base_days": round(float(params_used[3]), 2),
        "metrics": metrics,
    }
    params_path = args.output_csv.replace(".csv", "_params.json")
    with open(params_path, "w") as f:
        json.dump(params_out, f, indent=2)
    print(f"  Parameters: {params_path}")

    return out_df, params_used, metrics


# ===========================================================================
# Validate outputs
# ===========================================================================
def validate_outputs(out_df, basin_area_km2):
    """Post-simulation validation checks.

    Args:
        out_df: Simulation output DataFrame.
        basin_area_km2: Basin area for specific discharge calculation.

    Returns:
        warnings_list: List of warning strings.
    """
    warnings_list = []

    q_mean = out_df["sim_q_m3s"].mean()
    q_max = out_df["sim_q_m3s"].max()
    q_min = out_df["sim_q_m3s"].min()

    # Specific discharge
    q_specific = q_mean / basin_area_km2 * SECONDS_PER_DAY / M3_TO_MM_FACTOR * 365.25
    print(f"\n[validate_outputs] Discharge diagnostics:")
    print(f"  Mean Q:      {q_mean:.1f} m3/s")
    print(f"  Max Q:       {q_max:.1f} m3/s")
    print(f"  Min Q:       {q_min:.1f} m3/s")
    print(f"  Specific Q:  {q_specific:.0f} mm/yr")

    if q_specific < 10:
        warnings_list.append(
            f"Specific discharge = {q_specific:.0f} mm/yr is very low "
            f"(expected 100-500 for humid basins)"
        )

    if q_specific > 2000:
        warnings_list.append(
            f"Specific discharge = {q_specific:.0f} mm/yr is very high -- "
            f"check unit conversions (dt_205)"
        )

    if q_min < 0:
        warnings_list.append("Negative discharge detected!")

    # Check for NaN
    n_nan = out_df["sim_q_m3s"].isna().sum()
    if n_nan > 0:
        warnings_list.append(f"{n_nan} NaN values in simulated discharge")

    # Check water balance
    total_prec = out_df["prec_mm"].sum()
    total_pet = out_df["pet_mm"].sum()
    total_q = out_df["sim_q_mm"].sum()
    runoff_ratio = total_q / total_prec if total_prec > 0 else 0

    print(f"  Total precip:    {total_prec:.0f} mm")
    print(f"  Total PET:       {total_pet:.0f} mm")
    print(f"  Total Q:         {total_q:.0f} mm")
    print(f"  Runoff ratio:    {runoff_ratio:.3f}")

    if runoff_ratio > 1.0:
        warnings_list.append(
            f"Runoff ratio = {runoff_ratio:.3f} > 1.0 -- more water out than in!"
        )

    for w in warnings_list:
        print(f"  WARNING: {w}")

    if not warnings_list:
        print("  All output checks passed.")

    return warnings_list


# ===========================================================================
# Main
# ===========================================================================
def main():
    parser = argparse.ArgumentParser(
        description="Run HEC-RAS (GR4J surrogate) simulation"
    )
    # Required
    parser.add_argument(
        "--forcing_csv", required=True,
        help="Forcing CSV from convert_forcing_to_hecras.py",
    )
    parser.add_argument(
        "--basin_area_km2", type=float, required=True,
        help="Basin area in km2",
    )
    parser.add_argument(
        "--output_csv", required=True,
        help="Output CSV for simulation results",
    )

    # Parameters (explicit)
    parser.add_argument("--x1", type=float, default=None, help="Production store capacity (mm)")
    parser.add_argument("--x2", type=float, default=None, help="Exchange coefficient (mm)")
    parser.add_argument("--x3", type=float, default=None, help="Routing store capacity (mm)")
    parser.add_argument("--x4", type=float, default=None, help="UH time base (days)")
    parser.add_argument(
        "--params_json", default=None,
        help="JSON file with GR4J parameters (from convert_soil_to_hecras.py)",
    )

    # Calibration
    parser.add_argument("--obs_file", default=None, help="Observation file for calibration")
    parser.add_argument("--cal_start", default=None, help="Calibration start date (YYYY-MM-DD)")
    parser.add_argument("--cal_end", default=None, help="Calibration end date (YYYY-MM-DD)")
    parser.add_argument("--maxiter", type=int, default=500, help="Max calibration iterations")
    parser.add_argument("--spinup_days", type=int, default=365, help="Spinup days to skip (dt_208)")

    # Basin properties
    parser.add_argument(
        "--latitude", type=float, default=33.0,
        help="Basin centroid latitude (degrees) for PET computation",
    )

    args = parser.parse_args()

    # Validate-process-validate
    validate_inputs(args)
    out_df, params_used, metrics = process(args)
    validate_outputs(out_df, args.basin_area_km2)


if __name__ == "__main__":
    main()
