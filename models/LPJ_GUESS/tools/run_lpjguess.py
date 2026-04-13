#!/usr/bin/env python3
"""
run_lpjguess.py
Execution wrapper for LPJ-GUESS analytic reimplementation.

This tool:
1. Validates that forcing data and parameters exist and are well-formed
2. Loads forcing CSV (from convert_forcing_to_lpjguess.py)
3. Loads parameter JSON (from convert_parameters_to_lpjguess.py)
4. Runs the core LPJ-GUESS analytic model (LUE GPP, Q10 respiration, NEE)
5. Optionally calibrates parameters against FLUXNET observations
6. Writes raw output to CSV
7. Validates output for physical plausibility

The core model implements:
  - GPP via Light Use Efficiency with temperature and VPD scalars
  - Autotrophic respiration via Q10 temperature dependence
  - Heterotrophic respiration via Q10 decomposition
  - NEE = Reco - GPP

Usage:
    # Basic run
    python run_lpjguess.py \\
        --forcing forcing.csv \\
        --params params.json \\
        --output model_output.csv

    # With calibration against FLUXNET observations
    python run_lpjguess.py \\
        --forcing forcing.csv \\
        --params params.json \\
        --output model_output.csv \\
        --obs-gpp GPP_NT_VUT_MEAN \\
        --obs-nee NEE_VUT_MEAN \\
        --calibrate \\
        --cal-fraction 0.7

    # With FLUXNET observation file (separate from forcing)
    python run_lpjguess.py \\
        --forcing forcing.csv \\
        --params params.json \\
        --output model_output.csv \\
        --obs-file fluxnet_obs.csv \\
        --obs-gpp GPP_NT_VUT_MEAN \\
        --obs-nee NEE_VUT_MEAN \\
        --calibrate
"""

import os
import sys
import json
import math
import time
import argparse
import csv

import numpy as np

try:
    import pandas as pd
except ImportError:
    pd = None


# ============================================================================
# Validation helpers
# ============================================================================

def validate_inputs(forcing_path, params_path, output_path,
                    obs_file=None, obs_gpp_col=None, obs_nee_col=None):
    """
    Pre-flight validation of all inputs.

    Returns list of errors (empty = all OK).
    """
    errors = []
    warnings = []

    # Forcing file
    if not os.path.isfile(forcing_path):
        errors.append(f"Forcing file not found: {forcing_path}")
    else:
        size = os.path.getsize(forcing_path)
        if size == 0:
            errors.append(f"Forcing file is empty: {forcing_path}")
        else:
            # Quick header check
            with open(forcing_path) as f:
                header = f.readline().strip()
            required_cols = ["SW_IN", "TA", "VPD"]
            for col in required_cols:
                if col not in header:
                    errors.append(
                        f"Forcing file missing required column '{col}'. "
                        f"Header: {header[:200]}"
                    )

    # Parameters file
    if not os.path.isfile(params_path):
        errors.append(f"Parameters file not found: {params_path}")
    else:
        try:
            with open(params_path) as f:
                params = json.load(f)
            required_params = ["LUE_max", "T_opt", "T_min", "T_max",
                               "Ra_base", "Ra_Q10", "Rh_base", "Rh_Q10"]
            for p in required_params:
                if p not in params:
                    errors.append(f"Parameters file missing required key: {p}")
        except json.JSONDecodeError as e:
            errors.append(f"Parameters file is not valid JSON: {e}")

    # Observation file (optional)
    if obs_file is not None:
        if not os.path.isfile(obs_file):
            errors.append(f"Observation file not found: {obs_file}")

    # Output directory
    output_dir = os.path.dirname(output_path)
    if output_dir and not os.path.isdir(output_dir):
        errors.append(f"Output directory does not exist: {output_dir}")

    for w in warnings:
        print(f"WARNING: {w}", file=sys.stderr)
    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)

    return errors


def validate_outputs(output_path, n_expected=None):
    """
    Validate model output CSV for physical plausibility.

    Returns True if valid, False if critical issues.
    """
    if not os.path.isfile(output_path):
        print(f"ERROR: Output file not created: {output_path}", file=sys.stderr)
        return False

    warnings = []
    n_rows = 0
    gpp_vals = []
    nee_vals = []
    reco_vals = []

    with open(output_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            n_rows += 1
            try:
                gpp = float(row.get("GPP", "nan"))
                nee = float(row.get("NEE", "nan"))
                reco = float(row.get("Reco", "nan"))
                if not math.isnan(gpp):
                    gpp_vals.append(gpp)
                if not math.isnan(nee):
                    nee_vals.append(nee)
                if not math.isnan(reco):
                    reco_vals.append(reco)
            except (ValueError, TypeError):
                continue

    if n_rows == 0:
        print("ERROR: No data rows in output", file=sys.stderr)
        return False

    if n_expected is not None and n_rows != n_expected:
        warnings.append(f"Expected {n_expected} rows, got {n_rows}")

    # GPP checks
    if gpp_vals:
        gpp_min, gpp_max, gpp_mean = min(gpp_vals), max(gpp_vals), np.mean(gpp_vals)
        if gpp_min < -0.1:
            warnings.append(f"GPP min={gpp_min:.3f} umol/m2/s is negative")
        if gpp_max > 50:
            warnings.append(f"GPP max={gpp_max:.1f} umol/m2/s extremely high")
        if gpp_mean > 20:
            warnings.append(f"GPP mean={gpp_mean:.1f} umol/m2/s unusually high")
        if gpp_max < 0.01:
            warnings.append("GPP is essentially zero everywhere -- check parameters")

    # Reco checks
    if reco_vals:
        reco_min = min(reco_vals)
        reco_max = max(reco_vals)
        if reco_min < -0.1:
            warnings.append(f"Reco min={reco_min:.3f} -- respiration should be non-negative")
        if reco_max > 30:
            warnings.append(f"Reco max={reco_max:.1f} umol/m2/s very high")

    # NEE checks
    if nee_vals:
        nee_min, nee_max = min(nee_vals), max(nee_vals)
        if nee_min > 0 and nee_max > 0:
            warnings.append(
                "NEE is always positive (net source) -- no carbon uptake. "
                "Check GPP parameters."
            )

    for w in warnings:
        print(f"WARNING: {w}", file=sys.stderr)

    if not warnings:
        print(f"Output validated: {n_rows} rows, GPP and NEE within expected ranges")

    return True


# ============================================================================
# LPJ-GUESS Analytic Model Core
# ============================================================================

class LPJGuessAnalytic:
    """
    Core LPJ-GUESS analytic reimplementation.

    Implements:
    1. GPP via Light Use Efficiency (LUE) with temperature/VPD scalars
    2. Autotrophic respiration (Q10 maintenance + growth fraction)
    3. Heterotrophic respiration (Q10 decomposition)
    4. NEE = Reco - GPP
    """

    def __init__(self, params):
        """
        Initialize with parameter dictionary.

        Required keys: LUE_max, T_opt, T_min, T_max, VPD_0, VPD_1,
                       SW_in_scale, Ra_base, Ra_Q10, Ra_Tref,
                       Rh_base, Rh_Q10, Rh_Tref, C_pool_scale
        """
        self.params = dict(params)

        # Fill in defaults for any missing optional parameters
        defaults = {
            "SW_in_scale": 0.48,
            "VPD_0": 10.0,
            "VPD_1": 35.0,
            "Ra_Tref": 15.0,
            "Rh_Tref": 15.0,
            "C_pool_scale": 1.0,
        }
        for k, v in defaults.items():
            if k not in self.params:
                self.params[k] = v

    def temperature_scalar(self, T):
        """
        Parabolic temperature response for photosynthesis.

        Returns scalar in [0, 1] with peak at T_opt and zeros at T_min, T_max.
        """
        p = self.params
        T_opt, T_min, T_max = p["T_opt"], p["T_min"], p["T_max"]

        T = np.asarray(T, dtype=float)
        scalar = np.zeros_like(T)

        mask = (T > T_min) & (T < T_max)
        num = (T[mask] - T_min) * (T[mask] - T_max)
        den = (T_opt - T_min) * (T_opt - T_max)
        scalar[mask] = num / den
        scalar = np.clip(scalar, 0.0, 1.0)

        return scalar

    def vpd_scalar(self, VPD):
        """
        VPD limitation on stomatal conductance / GPP.

        Exponential decline: scalar = exp(-ln(2) * max(VPD - VPD_0, 0) / VPD_1)
        VPD in hPa.
        """
        p = self.params
        VPD = np.asarray(VPD, dtype=float)
        scalar = np.exp(
            -np.log(2.0) * np.maximum(VPD - p["VPD_0"], 0.0) / p["VPD_1"]
        )
        return np.clip(scalar, 0.05, 1.0)

    def compute_gpp(self, SW_IN, TA, VPD):
        """
        Compute GPP using LUE model.

        Parameters
        ----------
        SW_IN : array-like
            Incoming shortwave radiation (W/m2)
        TA : array-like
            Air temperature (deg C)
        VPD : array-like
            Vapour pressure deficit (hPa)

        Returns
        -------
        GPP : ndarray
            Gross Primary Production (umol CO2/m2/s)
        """
        p = self.params
        SW_IN = np.asarray(SW_IN, dtype=float)
        TA = np.asarray(TA, dtype=float)
        VPD = np.asarray(VPD, dtype=float)

        # PAR from shortwave
        PAR_wm2 = SW_IN * p["SW_in_scale"]
        PAR_MJ = PAR_wm2 * 86400.0 / 1.0e6  # W/m2 -> MJ/m2/day

        # Temperature and VPD scalars
        f_T = self.temperature_scalar(TA)
        f_VPD = self.vpd_scalar(VPD)

        # GPP in gC/m2/day
        GPP_gC = p["LUE_max"] * PAR_MJ * f_T * f_VPD

        # Convert to umol CO2/m2/s
        # 1 gC = 1/12.011 molC = 1e6/12.011 umolC
        # Per second: / 86400
        GPP_umol = GPP_gC * 1.0e6 / 12.011 / 86400.0

        return np.maximum(GPP_umol, 0.0)

    def compute_ra(self, GPP, TA):
        """
        Autotrophic respiration (umol CO2/m2/s).

        Ra = Ra_base * GPP * Q10^((T-Tref)/10) / Q10
        Normalized so that at T=Tref, Ra = Ra_base * GPP.
        """
        p = self.params
        TA = np.asarray(TA, dtype=float)
        f_T = p["Ra_Q10"] ** ((TA - p["Ra_Tref"]) / 10.0)
        Ra = p["Ra_base"] * GPP * f_T / p["Ra_Q10"]
        return np.maximum(Ra, 0.0)

    def compute_rh(self, TA):
        """
        Heterotrophic respiration (umol CO2/m2/s).

        Rh = Rh_base * Q10^((T-Tref)/10) * C_pool_scale
        """
        p = self.params
        TA = np.asarray(TA, dtype=float)
        f_T = p["Rh_Q10"] ** ((TA - p["Rh_Tref"]) / 10.0)
        Rh = p["Rh_base"] * f_T * p["C_pool_scale"]
        return np.maximum(Rh, 0.0)

    def run(self, SW_IN, TA, VPD):
        """
        Run full model for a timeseries of forcing data.

        Parameters
        ----------
        SW_IN : array-like
            Shortwave radiation (W/m2)
        TA : array-like
            Air temperature (deg C)
        VPD : array-like
            Vapour pressure deficit (hPa)

        Returns
        -------
        dict with GPP, Ra, Rh, Reco, NEE, NPP arrays (all umol/m2/s)
        """
        GPP = self.compute_gpp(SW_IN, TA, VPD)
        Ra = self.compute_ra(GPP, TA)
        Rh = self.compute_rh(TA)
        Reco = Ra + Rh
        NEE = Reco - GPP
        NPP = GPP - Ra

        return {
            "GPP": GPP,
            "Ra": Ra,
            "Rh": Rh,
            "Reco": Reco,
            "NEE": NEE,
            "NPP": NPP,
        }


# ============================================================================
# Calibration
# ============================================================================

def calibrate_model(model, SW_IN, TA, VPD, obs_gpp, obs_nee):
    """
    Calibrate model parameters against observed GPP and NEE.

    Uses scipy.optimize.differential_evolution to minimize
    normalized RMSE of GPP and NEE simultaneously.

    Parameters
    ----------
    model : LPJGuessAnalytic
        Model instance (parameters will be updated in-place)
    SW_IN, TA, VPD : array
        Forcing data
    obs_gpp, obs_nee : array
        Observed GPP and NEE (can contain NaN)

    Returns
    -------
    dict of calibrated parameter values
    """
    try:
        from scipy import optimize
    except ImportError:
        print("ERROR: scipy required for calibration. pip install scipy",
              file=sys.stderr)
        return {}

    print("Starting calibration (differential evolution)...")

    valid_gpp = ~np.isnan(obs_gpp)
    valid_nee = ~np.isnan(obs_nee)

    if valid_gpp.sum() < 3 and valid_nee.sum() < 3:
        print("WARNING: Insufficient valid observations for calibration",
              file=sys.stderr)
        return {}

    param_names = ["LUE_max", "T_opt", "VPD_1", "Ra_base", "Rh_base", "Rh_Q10"]
    bounds = [
        (0.3, 4.0),     # LUE_max
        (12.0, 30.0),   # T_opt
        (5.0, 60.0),    # VPD_1
        (0.2, 0.8),     # Ra_base
        (0.5, 5.0),     # Rh_base
        (1.2, 3.5),     # Rh_Q10
    ]

    def objective(x):
        params = dict(zip(param_names, x))
        m = LPJGuessAnalytic({**model.params, **params})
        result = m.run(SW_IN, TA, VPD)

        cost = 0.0
        n = 0
        if valid_gpp.sum() > 0:
            rmse_gpp = np.sqrt(np.nanmean(
                (result["GPP"][valid_gpp] - obs_gpp[valid_gpp]) ** 2
            ))
            std_gpp = np.nanstd(obs_gpp[valid_gpp])
            cost += (rmse_gpp / max(std_gpp, 0.1)) ** 2
            n += 1
        if valid_nee.sum() > 0:
            rmse_nee = np.sqrt(np.nanmean(
                (result["NEE"][valid_nee] - obs_nee[valid_nee]) ** 2
            ))
            std_nee = np.nanstd(obs_nee[valid_nee])
            cost += (rmse_nee / max(std_nee, 0.1)) ** 2
            n += 1
        return cost / max(n, 1)

    result = optimize.differential_evolution(
        objective, bounds,
        seed=42, maxiter=200, tol=1e-6,
        workers=1,
        polish=True,
    )

    cal_params = dict(zip(param_names, result.x))
    print(f"Calibration converged: {result.success}, cost={result.fun:.4f}")
    print(f"Calibrated parameters: {cal_params}")

    # Update model parameters
    model.params.update(cal_params)

    return cal_params


# ============================================================================
# Main execution pipeline
# ============================================================================

def run_model(forcing_path, params_path, output_path,
              obs_file=None, obs_gpp_col=None, obs_nee_col=None,
              calibrate=False, cal_fraction=0.7):
    """
    Full execution pipeline: validate -> load -> [calibrate] -> run -> validate.

    Parameters
    ----------
    forcing_path : str
        Path to forcing CSV (from convert_forcing_to_lpjguess.py)
    params_path : str
        Path to parameter JSON (from convert_parameters_to_lpjguess.py)
    output_path : str
        Path to write model output CSV
    obs_file : str or None
        Path to observation CSV (for calibration/validation)
    obs_gpp_col : str or None
        Column name for observed GPP in obs_file or forcing_file
    obs_nee_col : str or None
        Column name for observed NEE
    calibrate : bool
        Whether to calibrate parameters before final run
    cal_fraction : float
        Fraction of data to use for calibration (rest for validation)

    Returns
    -------
    dict with status, output_path, n_rows, calibrated_params (if calibrated)
    """
    if pd is None:
        print("ERROR: pandas required. pip install pandas", file=sys.stderr)
        return {"status": "error", "errors": ["pandas not installed"]}

    # --- Validate inputs ---
    errors = validate_inputs(forcing_path, params_path, output_path,
                             obs_file, obs_gpp_col, obs_nee_col)
    if errors:
        return {"status": "error", "errors": errors}

    # --- Load forcing ---
    print(f"Loading forcing: {forcing_path}")
    df_forcing = pd.read_csv(forcing_path)
    print(f"  {len(df_forcing)} rows, columns: {list(df_forcing.columns)}")

    # Handle NaN strings
    for col in ["SW_IN", "TA", "VPD"]:
        if col in df_forcing.columns:
            df_forcing[col] = pd.to_numeric(df_forcing[col], errors="coerce")

    # Drop rows with missing forcing
    n_before = len(df_forcing)
    df_forcing = df_forcing.dropna(subset=["SW_IN", "TA", "VPD"]).reset_index(drop=True)
    if len(df_forcing) < n_before:
        print(f"  Dropped {n_before - len(df_forcing)} rows with missing forcing")

    if len(df_forcing) == 0:
        return {"status": "error", "errors": ["No valid forcing rows"]}

    # --- Load parameters ---
    print(f"Loading parameters: {params_path}")
    with open(params_path) as f:
        params = json.load(f)
    print(f"  {len(params)} parameters loaded")

    # --- Initialize model ---
    model = LPJGuessAnalytic(params)

    SW_IN = df_forcing["SW_IN"].values
    TA = df_forcing["TA"].values
    VPD = df_forcing["VPD"].values

    # --- Load observations (optional) ---
    obs_gpp = None
    obs_nee = None

    if obs_file is not None:
        print(f"Loading observations: {obs_file}")
        df_obs = pd.read_csv(obs_file)
        df_obs = df_obs.replace(-9999, np.nan).replace(-9999.0, np.nan)

        if obs_gpp_col and obs_gpp_col in df_obs.columns:
            obs_gpp = pd.to_numeric(df_obs[obs_gpp_col], errors="coerce").values
            # Align lengths
            obs_gpp = obs_gpp[:len(df_forcing)]
        if obs_nee_col and obs_nee_col in df_obs.columns:
            obs_nee = pd.to_numeric(df_obs[obs_nee_col], errors="coerce").values
            obs_nee = obs_nee[:len(df_forcing)]
    else:
        # Check if observation columns exist in forcing file
        if obs_gpp_col and obs_gpp_col in df_forcing.columns:
            obs_gpp = pd.to_numeric(df_forcing[obs_gpp_col], errors="coerce").values
        if obs_nee_col and obs_nee_col in df_forcing.columns:
            obs_nee = pd.to_numeric(df_forcing[obs_nee_col], errors="coerce").values

    # --- Calibration (optional) ---
    cal_params = {}
    if calibrate and (obs_gpp is not None or obs_nee is not None):
        n_cal = int(len(df_forcing) * cal_fraction)
        if n_cal < 6:
            print("WARNING: Too few calibration samples, using all data",
                  file=sys.stderr)
            n_cal = len(df_forcing)

        cal_gpp = obs_gpp[:n_cal] if obs_gpp is not None else np.full(n_cal, np.nan)
        cal_nee = obs_nee[:n_cal] if obs_nee is not None else np.full(n_cal, np.nan)

        print(f"\nCalibrating on first {n_cal} rows "
              f"({cal_fraction:.0%} of data)...")
        cal_params = calibrate_model(
            model, SW_IN[:n_cal], TA[:n_cal], VPD[:n_cal],
            cal_gpp, cal_nee
        )

    # --- Run model ---
    print(f"\nRunning model on {len(df_forcing)} timesteps...")
    t0 = time.time()
    result = model.run(SW_IN, TA, VPD)
    duration = time.time() - t0
    print(f"Model completed in {duration:.2f}s")

    # --- Build output DataFrame ---
    df_out = pd.DataFrame()
    if "date" in df_forcing.columns:
        df_out["date"] = df_forcing["date"]
    if "year" in df_forcing.columns:
        df_out["year"] = df_forcing["year"]
    if "month" in df_forcing.columns:
        df_out["month"] = df_forcing["month"]

    # Forcing columns
    df_out["SW_IN"] = SW_IN
    df_out["TA"] = TA
    df_out["VPD"] = VPD

    # Model output columns
    for var_name in ["GPP", "Ra", "Rh", "Reco", "NEE", "NPP"]:
        df_out[var_name] = result[var_name]

    # Observation columns (if available)
    if obs_gpp is not None:
        df_out["obs_GPP"] = obs_gpp[:len(df_out)]
    if obs_nee is not None:
        df_out["obs_NEE"] = obs_nee[:len(df_out)]

    # --- Write output ---
    df_out.to_csv(output_path, index=False, float_format="%.6f",
                  na_rep="NaN")
    print(f"Output written: {output_path} ({len(df_out)} rows)")

    # --- Validate output ---
    output_ok = validate_outputs(output_path, n_expected=len(df_out))

    # --- Summary ---
    print(f"\n--- Run Summary ---")
    print(f"  Forcing rows: {len(df_forcing)}")
    print(f"  GPP mean: {np.nanmean(result['GPP']):.3f} umol/m2/s")
    print(f"  GPP max:  {np.nanmax(result['GPP']):.3f} umol/m2/s")
    print(f"  NEE mean: {np.nanmean(result['NEE']):.3f} umol/m2/s")
    print(f"  Reco mean: {np.nanmean(result['Reco']):.3f} umol/m2/s")
    print(f"  Duration: {duration:.2f}s")

    return {
        "status": "success" if output_ok else "warning",
        "output_path": output_path,
        "n_rows": len(df_out),
        "duration_s": round(duration, 2),
        "calibrated_params": cal_params,
        "summary": {
            "GPP_mean": round(float(np.nanmean(result["GPP"])), 4),
            "GPP_max": round(float(np.nanmax(result["GPP"])), 4),
            "NEE_mean": round(float(np.nanmean(result["NEE"])), 4),
            "Reco_mean": round(float(np.nanmean(result["Reco"])), 4),
        },
    }


# ============================================================================
# CLI entry point
# ============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run LPJ-GUESS analytic model",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--forcing", required=True,
                        help="Forcing CSV file (from convert_forcing_to_lpjguess.py)")
    parser.add_argument("--params", required=True,
                        help="Parameter JSON file (from convert_parameters_to_lpjguess.py)")
    parser.add_argument("--output", required=True,
                        help="Output CSV file path")
    parser.add_argument("--obs-file", default=None,
                        help="Observation CSV file (for calibration)")
    parser.add_argument("--obs-gpp", default=None,
                        help="Column name for observed GPP")
    parser.add_argument("--obs-nee", default=None,
                        help="Column name for observed NEE")
    parser.add_argument("--calibrate", action="store_true",
                        help="Calibrate parameters against observations")
    parser.add_argument("--cal-fraction", type=float, default=0.7,
                        help="Fraction of data for calibration (default: 0.7)")

    args = parser.parse_args()

    result = run_model(
        forcing_path=args.forcing,
        params_path=args.params,
        output_path=args.output,
        obs_file=args.obs_file,
        obs_gpp_col=args.obs_gpp,
        obs_nee_col=args.obs_nee,
        calibrate=args.calibrate,
        cal_fraction=args.cal_fraction,
    )

    print(f"\nResult: {json.dumps(result, indent=2, default=str)}")
    sys.exit(0 if result["status"] in ("success", "warning") else 1)
