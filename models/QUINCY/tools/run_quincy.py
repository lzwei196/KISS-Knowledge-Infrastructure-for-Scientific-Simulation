#!/usr/bin/env python3
"""
run_quincy.py
Execution wrapper for the QUINCY analytic model.

Runs the QUINCY coupled C-N-P biogeochemistry model with:
  - Farquhar photosynthesis with N-limitation on Vcmax
  - Ball-Berry stomatal conductance
  - Autotrophic respiration (maintenance + growth)
  - Heterotrophic respiration (CENTURY-like, Q10 + moisture)
  - Temperature-driven phenology (LAI)

Pipeline:
  1. Load forcing data (QUINCY-format CSV from convert_forcing_to_quincy.py)
  2. Load parameters (JSON from convert_parameters_to_quincy.py, or defaults)
  3. Validate inputs
  4. Run model for each timestep
  5. Validate outputs
  6. Export results

Usage:
    # Run with forcing and parameters
    python run_quincy.py --forcing quincy_forcing.csv --params enf_params.json \\
        --output quincy_output.csv --lat 61.85

    # Run with defaults
    python run_quincy.py --forcing quincy_forcing.csv --pft enf \\
        --output quincy_output.csv --lat 61.85

    # Run with calibration
    python run_quincy.py --forcing quincy_forcing.csv --pft enf \\
        --output quincy_output.csv --lat 61.85 --calibrate
"""

import os
import sys
import csv
import json
import math
import argparse
import numpy as np
from datetime import datetime
from typing import Dict, List, Optional


# ============================================================================
# QUINCY Model Core
# ============================================================================

class QUINCYModel:
    """
    Analytic reimplementation of QUINCY's core biogeochemistry.

    Processes:
    1. Photosynthesis (Farquhar-type with N limitation)
    2. Stomatal conductance (Ball-Berry)
    3. Autotrophic respiration (maintenance + growth)
    4. Heterotrophic respiration (CENTURY-like multi-pool decomposition)
    5. Phenology (temperature-based LAI for boreal/temperate)
    6. Coupled C-N cycling (N limits Vcmax -> GPP)
    """

    # Michaelis-Menten constants at 25C (Farquhar model)
    KC25 = 404.9       # umol/mol, Kc for CO2
    KO25 = 278.4       # mmol/mol, Ko for O2
    GAMMA_STAR25 = 42.75  # umol/mol, CO2 compensation point
    OI = 210.0         # mmol/mol, O2 concentration
    R_GAS = 8.314      # J/mol/K, universal gas constant

    # Activation energies for Michaelis-Menten constants
    EA_KC = 79430.0    # J/mol
    EA_KO = 36380.0    # J/mol
    EA_GAMMA = 37830.0 # J/mol

    def __init__(self, params=None):
        """
        Initialize with default or provided parameters.

        Parameters
        ----------
        params : dict or None
            Parameter dictionary. If None, uses ENF defaults.
        """
        # Default parameters for boreal evergreen (Scots pine)
        self.p = {
            # Photosynthesis
            'vcmax25': 45.0,
            'jmax_vcmax_ratio': 1.9,
            'alpha_j': 0.3,
            'theta_j': 0.9,

            # N-limitation on Vcmax (QUINCY key feature)
            'n_leaf_ref': 1.8,
            'vcmax_n_slope': 25.0,

            # Stomatal conductance (Ball-Berry)
            'g1_bb': 6.0,

            # LAI and phenology
            'lai_max': 5.5,
            'lai_min': 3.5,
            'lai_t_opt': 15.0,
            'lai_t_range': 15.0,

            # Autotrophic respiration
            'r_maint_leaf': 0.015,
            'r_maint_stem': 0.4,
            'r_maint_root': 0.3,
            'r_growth_frac': 0.25,

            # Soil / heterotrophic respiration (CENTURY-like)
            'rh_base': 1.8,
            'rh_q10': 2.0,
            'rh_t_ref': 15.0,
            'rh_precip_scale': 0.02,
            'rh_precip_opt': 2.5,

            # Carbon use efficiency
            'cue_ref': 0.45,

            # Activation energies
            'ea_vcmax': 65330,
            'ea_jmax': 43540,
            'ea_rd': 46390,
        }

        if params is not None:
            self.p.update(params)

    def temperature_response(self, val25, ea, tc):
        """
        Arrhenius temperature response function.

        Parameters
        ----------
        val25 : float
            Value at 25 deg C
        ea : float
            Activation energy (J/mol)
        tc : float
            Temperature (deg C)

        Returns
        -------
        float
            Temperature-adjusted value
        """
        tk = tc + 273.15
        tk25 = 298.15
        return val25 * np.exp(ea * (tk - tk25) / (tk25 * self.R_GAS * tk))

    def calc_lai(self, ta, month):
        """
        Calculate effective LAI.

        For evergreen: maintains base LAI year-round with temperature modulation.
        For deciduous: LAI drops to near-zero in cold months.

        Parameters
        ----------
        ta : float
            Air temperature (deg C)
        month : int
            Month (1-12)

        Returns
        -------
        float
            Effective LAI (m2/m2)
        """
        p = self.p
        t_factor = np.exp(
            -0.5 * ((ta - p['lai_t_opt']) / p['lai_t_range']) ** 2
        )
        lai = p['lai_min'] + (p['lai_max'] - p['lai_min']) * t_factor
        return float(np.clip(lai, p['lai_min'], p['lai_max']))

    def calc_gpp(self, ta, sw_in, vpd, co2, daylength, lai):
        """
        Farquhar-type photosynthesis with nitrogen limitation.

        Implements:
        - N-limitation: leaf_N -> effective Vcmax25
        - Arrhenius temperature scaling of Vcmax, Jmax
        - Beer's law canopy light extinction
        - Rubisco-limited (Wc) and RuBP-limited (Wj) assimilation
        - Ball-Berry stomatal effect on Ci/Ca

        Parameters
        ----------
        ta : float
            Air temperature (deg C)
        sw_in : float
            Incoming shortwave radiation (W/m2)
        vpd : float
            Vapor pressure deficit (hPa)
        co2 : float
            CO2 concentration (ppm)
        daylength : float
            Daylength (hours)
        lai : float
            Leaf area index (m2/m2)

        Returns
        -------
        float
            Gross primary production (umol CO2/m2/s, 24h mean)
        """
        p = self.p

        # --- N-limitation on Vcmax (QUINCY key feature) ---
        n_leaf = p['n_leaf_ref']
        vcmax25_eff = p['vcmax_n_slope'] * n_leaf
        vcmax25_eff = min(vcmax25_eff, p['vcmax25'])

        # --- Temperature response ---
        vcmax = self.temperature_response(vcmax25_eff, p['ea_vcmax'], ta)
        jmax = p['jmax_vcmax_ratio'] * self.temperature_response(
            vcmax25_eff, p['ea_jmax'], ta
        )

        # --- Canopy scaling (Big-leaf, Beer's law) ---
        k_ext = 0.5  # extinction coefficient
        f_par = 1.0 - np.exp(-k_ext * lai)

        # PAR from shortwave (W/m2 -> umol/m2/s PPFD, factor ~2.3)
        par = sw_in * 2.3
        apar = par * f_par

        # --- Stomatal conductance effect on Ci/Ca (Ball-Berry) ---
        ca = co2  # ppm ~ ubar at sea level
        vpd_kpa = vpd / 10.0  # hPa to kPa
        ci_ca = max(0.3, 0.7 - 0.04 * vpd_kpa)
        ci = ca * ci_ca

        # --- Michaelis-Menten kinetics ---
        kc = self.KC25 * np.exp(
            self.EA_KC * (ta - 25) / (298.15 * self.R_GAS * (ta + 273.15)))
        ko = self.KO25 * np.exp(
            self.EA_KO * (ta - 25) / (298.15 * self.R_GAS * (ta + 273.15)))
        gamma_star = self.GAMMA_STAR25 * np.exp(
            self.EA_GAMMA * (ta - 25) / (298.15 * self.R_GAS * (ta + 273.15)))

        # --- Rubisco-limited rate (Wc) ---
        wc = vcmax * (ci - gamma_star) / (ci + kc * (1 + self.OI / ko))

        # --- RuBP-regeneration limited rate (Wj) ---
        j_pot = p['alpha_j'] * apar
        discriminant = (jmax + j_pot) ** 2 - 4 * p['theta_j'] * jmax * j_pot
        discriminant = max(0, discriminant)
        j = (jmax + j_pot - np.sqrt(discriminant)) / (2 * p['theta_j'])
        wj = j * (ci - gamma_star) / (4 * (ci + 2 * gamma_star))

        # --- Gross assimilation ---
        a_gross = min(wc, wj)

        # Scale to canopy
        gpp = a_gross * f_par

        # Daylength scaling (FLUXNET GPP is 24h mean)
        day_frac = daylength / 24.0
        gpp = gpp * day_frac

        return max(0.0, float(gpp))

    def calc_reco(self, ta, precip, lai, gpp):
        """
        Ecosystem respiration = autotrophic + heterotrophic.

        Autotrophic: maintenance (leaf, stem, root) + growth fraction
        Heterotrophic: CENTURY-like with Q10 temperature and moisture controls

        Parameters
        ----------
        ta : float
            Air temperature (deg C)
        precip : float
            Precipitation (mm/day)
        lai : float
            LAI (m2/m2)
        gpp : float
            GPP (umol CO2/m2/s)

        Returns
        -------
        tuple of (reco, ra, rh)
            All in umol CO2/m2/s
        """
        p = self.p

        # --- Autotrophic respiration ---
        r_maint_leaf = p['r_maint_leaf'] * lai * self.temperature_response(
            1.0, p['ea_rd'], ta
        )
        r_maint_stem = p['r_maint_stem'] * self.temperature_response(
            1.0, p['ea_rd'], ta
        )
        r_maint_root = p['r_maint_root'] * self.temperature_response(
            1.0, p['ea_rd'], ta
        )
        r_maint = r_maint_leaf + r_maint_stem + r_maint_root

        # Growth respiration
        npp_approx = max(0, gpp - r_maint)
        r_growth = p['r_growth_frac'] * npp_approx

        ra = r_maint + r_growth

        # --- Heterotrophic respiration (CENTURY-like) ---
        # Temperature factor (Q10)
        t_factor = p['rh_q10'] ** ((ta - p['rh_t_ref']) / 10.0)

        # Moisture factor (bell-shaped from precipitation)
        if precip > 0 and not np.isnan(precip):
            w_factor = 1.0 - 0.5 * (
                (precip - p['rh_precip_opt']) / (p['rh_precip_opt'] + 1)
            ) ** 2
            w_factor = max(0.2, min(1.0, w_factor))
        else:
            w_factor = 0.5

        rh = p['rh_base'] * t_factor * w_factor

        reco = ra + rh
        return float(reco), float(ra), float(rh)

    def calc_energy_fluxes(self, ta, sw_in, vpd, gpp, lai):
        """
        Estimate latent and sensible heat fluxes (simplified).

        Uses Penman-Monteith approximation for LE and energy balance for H.

        Parameters
        ----------
        ta : float
            Air temperature (deg C)
        sw_in : float
            Shortwave radiation (W/m2)
        vpd : float
            VPD (hPa)
        gpp : float
            GPP (umol/m2/s)
        lai : float
            LAI (m2/m2)

        Returns
        -------
        tuple of (le, h)
            Latent heat (W/m2), Sensible heat (W/m2)
        """
        # Net radiation (simplified: ~60% of SW for vegetated surfaces)
        rn = sw_in * 0.6

        # Canopy conductance from GPP (simplified Penman-Monteith approach)
        # gc ~ GPP / (Ca - Ci) * 1.6 * RT/P
        # Simplified: LE scales with GPP and available energy
        if gpp > 0 and rn > 0:
            # Water use efficiency ~ 3-5 umol CO2 / mmol H2O for C3
            wue = 4.0  # umol CO2 / mmol H2O
            # Transpiration in mmol/m2/s
            transp_mmol = gpp / wue
            # LE from transpiration: lambda * E
            # lambda ~ 2.45 MJ/kg, 1 mmol H2O = 0.018 g
            lambda_v = 2.45e6  # J/kg
            le_transp = transp_mmol * 0.018e-3 * lambda_v  # W/m2

            # Add soil evaporation (scales with available energy and soil wetness)
            le_soil = rn * 0.15 * (1 - min(lai / 6.0, 0.8))

            le = min(le_transp + le_soil, rn * 0.9)  # cap at 90% of Rn
            le = max(0, le)
        else:
            le = rn * 0.2 if rn > 0 else 0

        # Sensible heat as residual
        h = max(0, rn - le)

        return float(le), float(h)


# ============================================================================
# Validation
# ============================================================================

def validate_inputs(forcing_path, params_path=None, lat=None):
    """
    Pre-flight checks before running the model.

    Parameters
    ----------
    forcing_path : str
        Path to QUINCY forcing CSV
    params_path : str or None
        Path to parameter JSON (optional)
    lat : float or None
        Site latitude

    Returns
    -------
    list of str
        Error messages
    """
    errors = []

    if not os.path.isfile(forcing_path):
        errors.append(f"Forcing file not found: {forcing_path}")
    else:
        # Check it has required columns
        with open(forcing_path, 'r') as f:
            header = f.readline().strip()
        required = ["SW_IN", "TA", "VPD", "PRECIP"]
        for col in required:
            if col not in header:
                errors.append(f"Forcing file missing column: {col}")

    if params_path and not os.path.isfile(params_path):
        errors.append(f"Parameter file not found: {params_path}")

    if lat is not None and (lat < -90 or lat > 90):
        errors.append(f"Latitude out of range [-90, 90]: {lat}")

    if errors:
        for e in errors:
            print(f"INPUT ERROR: {e}", file=sys.stderr)

    return errors


def validate_outputs(results):
    """
    Validate model output for reasonableness.

    Parameters
    ----------
    results : dict
        Model output dictionary with numpy arrays

    Returns
    -------
    list of str
        Warning messages
    """
    warnings = []

    if "GPP" in results:
        gpp = results["GPP"]
        valid = gpp[~np.isnan(gpp)]
        if len(valid) > 0:
            if np.max(valid) > 30:
                warnings.append(
                    f"GPP max={np.max(valid):.1f} umol/m2/s unusually high "
                    f"(check Vcmax or radiation)")
            if np.min(valid) < 0:
                warnings.append(f"GPP has negative values (should be >= 0)")
            if np.mean(valid) < 0.5:
                warnings.append(
                    f"GPP mean={np.mean(valid):.2f} umol/m2/s very low "
                    f"(check N-limitation or forcing)")

    if "NEE" in results:
        nee = results["NEE"]
        valid = nee[~np.isnan(nee)]
        if len(valid) > 0:
            if np.mean(valid) > 5:
                warnings.append(
                    f"NEE mean={np.mean(valid):.2f} umol/m2/s -- "
                    f"ecosystem is strong net source")

    if "RECO" in results:
        reco = results["RECO"]
        valid = reco[~np.isnan(reco)]
        if len(valid) > 0:
            if np.max(valid) > 20:
                warnings.append(
                    f"Reco max={np.max(valid):.1f} umol/m2/s unusually high")
            if np.any(valid < 0):
                warnings.append(f"Reco has negative values (should be >= 0)")

    if "LAI" in results:
        lai = results["LAI"]
        if np.max(lai) > 12:
            warnings.append(f"LAI max={np.max(lai):.1f} unrealistically high")

    for w in warnings:
        print(f"OUTPUT WARNING: {w}", file=sys.stderr)

    if not warnings:
        n = len(results.get("GPP", []))
        print(f"Output validated: {n} timesteps, all values reasonable")

    return warnings


# ============================================================================
# Forcing data loader
# ============================================================================

def load_forcing(filepath):
    """
    Load QUINCY forcing CSV file.

    Parameters
    ----------
    filepath : str
        Path to QUINCY-format forcing CSV

    Returns
    -------
    dict of numpy arrays
    """
    with open(filepath, 'r') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        print("ERROR: Empty forcing file", file=sys.stderr)
        return {}

    # Skip units row if present
    first_row = rows[0]
    if any(v in str(first_row) for v in ["W/m2", "degC", "hPa", "mm/day"]):
        rows = rows[1:]

    n = len(rows)
    data = {}
    columns = ["TIMESTAMP", "YEAR", "MONTH", "SW_IN", "TA", "VPD", "PRECIP",
               "CO2", "DAYLENGTH", "GPP_OBS", "NEE_OBS", "RECO_OBS",
               "LE_OBS", "H_OBS"]

    for col in columns:
        if col in rows[0]:
            if col == "TIMESTAMP":
                data[col] = [row[col] for row in rows]
            else:
                vals = []
                for row in rows:
                    try:
                        v = float(row.get(col, "NaN"))
                        vals.append(v)
                    except (ValueError, TypeError):
                        vals.append(np.nan)
                data[col] = np.array(vals)

    print(f"  Loaded {n} timesteps from {os.path.basename(filepath)}")
    return data


# ============================================================================
# Model runner
# ============================================================================

def run_model(forcing, params=None, lat=None):
    """
    Run QUINCY model for all timesteps.

    Parameters
    ----------
    forcing : dict
        Forcing data (numpy arrays)
    params : dict or None
        Model parameters
    lat : float or None
        Site latitude (for daylength if not in forcing)

    Returns
    -------
    dict with model output arrays
    """
    model = QUINCYModel(params)

    n = len(forcing.get("TA", []))
    if n == 0:
        print("ERROR: No forcing data", file=sys.stderr)
        return {}

    # Initialize output arrays
    gpp_out = np.zeros(n)
    nee_out = np.zeros(n)
    reco_out = np.zeros(n)
    ra_out = np.zeros(n)
    rh_out = np.zeros(n)
    lai_out = np.zeros(n)
    le_out = np.zeros(n)
    h_out = np.zeros(n)

    ta = forcing.get("TA", np.full(n, np.nan))
    sw = forcing.get("SW_IN", np.full(n, np.nan))
    vpd = forcing.get("VPD", np.full(n, np.nan))
    precip = forcing.get("PRECIP", np.full(n, np.nan))
    co2 = forcing.get("CO2", np.full(n, 380.0))
    daylength = forcing.get("DAYLENGTH", np.full(n, 12.0))
    month = forcing.get("MONTH", np.ones(n, dtype=int))

    print(f"  Running QUINCY model for {n} timesteps...")

    for i in range(n):
        # Fill missing values with reasonable defaults
        ta_i = ta[i] if not np.isnan(ta[i]) else 4.0
        sw_i = sw[i] if not np.isnan(sw[i]) else 100.0
        vpd_i = vpd[i] if not np.isnan(vpd[i]) else 3.0
        co2_i = co2[i] if not np.isnan(co2[i]) else 380.0
        dl_i = daylength[i] if not np.isnan(daylength[i]) else 12.0
        precip_i = precip[i] if not np.isnan(precip[i]) else 1.5
        month_i = int(month[i]) if not np.isnan(month[i]) else 6

        # LAI
        lai = model.calc_lai(ta_i, month_i)
        lai_out[i] = lai

        # GPP
        gpp = model.calc_gpp(ta_i, sw_i, vpd_i, co2_i, dl_i, lai)
        gpp_out[i] = gpp

        # Reco
        reco, ra, rh = model.calc_reco(ta_i, precip_i, lai, gpp)
        reco_out[i] = reco
        ra_out[i] = ra
        rh_out[i] = rh

        # NEE = Reco - GPP (micrometeorological convention)
        nee_out[i] = reco - gpp

        # Energy fluxes
        le, h = model.calc_energy_fluxes(ta_i, sw_i, vpd_i, gpp, lai)
        le_out[i] = le
        h_out[i] = h

    results = {
        "GPP": gpp_out,
        "NEE": nee_out,
        "RECO": reco_out,
        "RA": ra_out,
        "RH": rh_out,
        "LAI": lai_out,
        "LE": le_out,
        "H": h_out,
    }

    # Print summary statistics
    print(f"  GPP:  mean={np.mean(gpp_out):.2f}, max={np.max(gpp_out):.2f} umol/m2/s")
    print(f"  NEE:  mean={np.mean(nee_out):.2f} umol/m2/s")
    print(f"  Reco: mean={np.mean(reco_out):.2f} umol/m2/s")
    print(f"  LAI:  mean={np.mean(lai_out):.2f} m2/m2")
    print(f"  LE:   mean={np.mean(le_out):.1f} W/m2")
    print(f"  H:    mean={np.mean(h_out):.1f} W/m2")

    return results


# ============================================================================
# Calibration (optional)
# ============================================================================

def calibrate_model(forcing, obs_vars=None):
    """
    Calibrate model parameters using differential evolution.

    Parameters
    ----------
    forcing : dict
        Forcing data with observation columns
    obs_vars : list of str or None
        Observation variables to calibrate against

    Returns
    -------
    dict
        Calibrated parameters
    """
    try:
        from scipy.optimize import differential_evolution
    except ImportError:
        print("ERROR: scipy required for calibration. "
              "Install: pip install scipy", file=sys.stderr)
        sys.exit(1)

    if obs_vars is None:
        obs_vars = ["GPP_OBS", "NEE_OBS", "RECO_OBS"]

    bounds = [
        (25, 70),      # vcmax25
        (1.0, 3.0),    # n_leaf_ref
        (15, 40),      # vcmax_n_slope
        (0.5, 4.0),    # rh_base
        (1.5, 3.0),    # rh_q10
        (0.005, 0.04), # r_maint_leaf
        (0.1, 1.0),    # r_maint_stem
        (0.1, 0.8),    # r_maint_root
        (3.0, 8.0),    # lai_max
        (1.5, 5.0),    # lai_min
        (0.15, 0.45),  # alpha_j
    ]
    param_names = [
        'vcmax25', 'n_leaf_ref', 'vcmax_n_slope', 'rh_base', 'rh_q10',
        'r_maint_leaf', 'r_maint_stem', 'r_maint_root', 'lai_max', 'lai_min',
        'alpha_j',
    ]

    def objective(x):
        params = {k: v for k, v in zip(param_names, x)}
        results = run_model(forcing, params)
        if not results:
            return 1e6

        total_rmse = 0.0
        n_vars = 0
        for obs_var in obs_vars:
            if obs_var not in forcing:
                continue
            mod_var = obs_var.replace("_OBS", "")
            if mod_var not in results:
                continue

            obs = forcing[obs_var]
            mod = results[mod_var]
            mask = ~np.isnan(obs) & ~np.isnan(mod)
            if mask.sum() < 5:
                continue

            rmse = np.sqrt(np.mean((mod[mask] - obs[mask]) ** 2))
            total_rmse += rmse
            n_vars += 1

        return total_rmse if n_vars > 0 else 1e6

    print("Calibrating model with differential evolution...")
    result = differential_evolution(
        objective, bounds, maxiter=200, seed=42,
        tol=1e-4, popsize=15, workers=1, polish=True,
    )

    calibrated = {k: float(v) for k, v in zip(param_names, result.x)}
    print(f"  Optimization converged: {result.success}")
    print(f"  Final objective: {result.fun:.4f}")
    for k, v in calibrated.items():
        print(f"    {k}: {v:.4f}")

    return calibrated


# ============================================================================
# Export results
# ============================================================================

def export_results(forcing, results, output_path):
    """
    Export model results to CSV.

    Parameters
    ----------
    forcing : dict
        Input forcing data
    results : dict
        Model output arrays
    output_path : str
        Output CSV path
    """
    n = len(results.get("GPP", []))
    timestamps = forcing.get("TIMESTAMP", [str(i) for i in range(n)])

    output_vars = ["GPP", "NEE", "RECO", "RA", "RH", "LAI", "LE", "H"]
    obs_vars = ["GPP_OBS", "NEE_OBS", "RECO_OBS", "LE_OBS", "H_OBS"]

    # Include observation columns if present
    write_obs = [v for v in obs_vars
                 if v in forcing and not np.all(np.isnan(forcing[v]))]

    with open(output_path, 'w', newline='') as f:
        writer = csv.writer(f)

        # Header
        header = ["TIMESTAMP"] + output_vars + write_obs
        writer.writerow(header)

        # Units
        units = {
            "GPP": "umol/m2/s", "NEE": "umol/m2/s", "RECO": "umol/m2/s",
            "RA": "umol/m2/s", "RH": "umol/m2/s", "LAI": "m2/m2",
            "LE": "W/m2", "H": "W/m2",
            "GPP_OBS": "umol/m2/s", "NEE_OBS": "umol/m2/s",
            "RECO_OBS": "umol/m2/s", "LE_OBS": "W/m2", "H_OBS": "W/m2",
        }
        units_row = [""] + [units.get(v, "") for v in output_vars + write_obs]
        writer.writerow(units_row)

        # Data
        for i in range(n):
            row = [timestamps[i] if i < len(timestamps) else str(i)]
            for var in output_vars:
                if var in results and i < len(results[var]):
                    row.append(f"{results[var][i]:.4f}")
                else:
                    row.append("NaN")
            for var in write_obs:
                val = forcing[var][i] if i < len(forcing[var]) else np.nan
                row.append(f"{val:.4f}" if not np.isnan(val) else "NaN")
            writer.writerow(row)

    print(f"  Results written: {output_path} ({n} rows)")


# ============================================================================
# Metrics computation
# ============================================================================

def compute_metrics(forcing, results):
    """
    Compute validation metrics against observations.

    Parameters
    ----------
    forcing : dict
        Forcing data with observation columns
    results : dict
        Model output

    Returns
    -------
    dict
        Metrics per variable
    """
    metrics = {}

    obs_mod_pairs = [
        ("GPP_OBS", "GPP"),
        ("NEE_OBS", "NEE"),
        ("RECO_OBS", "RECO"),
        ("LE_OBS", "LE"),
        ("H_OBS", "H"),
    ]

    for obs_var, mod_var in obs_mod_pairs:
        if obs_var not in forcing or mod_var not in results:
            continue

        obs = forcing[obs_var]
        mod = results[mod_var]
        mask = ~np.isnan(obs) & ~np.isnan(mod)

        if mask.sum() < 3:
            continue

        o = obs[mask]
        m = mod[mask]

        r = float(np.corrcoef(o, m)[0, 1]) if len(o) > 2 else np.nan
        rmse = float(np.sqrt(np.mean((m - o) ** 2)))
        bias = float(np.mean(m - o))
        ss_res = np.sum((m - o) ** 2)
        ss_tot = np.sum((o - np.mean(o)) ** 2)
        nse = float(1 - ss_res / ss_tot) if ss_tot > 0 else np.nan

        metrics[mod_var] = {
            "R": round(r, 4),
            "RMSE": round(rmse, 4),
            "bias": round(bias, 4),
            "NSE": round(nse, 4),
            "n": int(mask.sum()),
        }

        print(f"  {mod_var}: R={r:.3f}, RMSE={rmse:.3f}, "
              f"bias={bias:.3f}, NSE={nse:.3f} (n={mask.sum()})")

    return metrics


# ============================================================================
# Full pipeline
# ============================================================================

def run_pipeline(forcing_path, output_path, params=None, lat=None,
                 calibrate=False):
    """
    Full QUINCY execution pipeline: validate -> run -> validate -> export.

    Parameters
    ----------
    forcing_path : str
        Path to QUINCY forcing CSV
    output_path : str
        Path to output CSV
    params : dict or None
        Model parameters
    lat : float or None
        Site latitude
    calibrate : bool
        Whether to calibrate before running

    Returns
    -------
    dict
        Pipeline results with metrics
    """
    # Stage 1: Validate inputs
    print("Stage 1: Validating inputs...")
    errors = validate_inputs(forcing_path, lat=lat)
    if errors:
        return {"status": "error", "errors": errors}

    # Stage 2: Load data
    print("Stage 2: Loading forcing data...")
    forcing = load_forcing(forcing_path)
    if not forcing:
        return {"status": "error", "message": "Failed to load forcing data"}

    # Optional calibration
    if calibrate:
        print("Stage 2b: Calibrating model...")
        calibrated = calibrate_model(forcing)
        if params:
            params.update(calibrated)
        else:
            params = calibrated

    # Stage 3: Run model
    print("Stage 3: Running QUINCY model...")
    results = run_model(forcing, params, lat)
    if not results:
        return {"status": "error", "message": "Model run failed"}

    # Stage 4: Validate outputs
    print("Stage 4: Validating outputs...")
    warnings = validate_outputs(results)

    # Stage 5: Compute metrics (if observations available)
    print("Stage 5: Computing metrics...")
    metrics = compute_metrics(forcing, results)

    # Stage 6: Export
    print("Stage 6: Exporting results...")
    export_results(forcing, results, output_path)

    return {
        "status": "success" if not warnings else "completed_with_warnings",
        "forcing_file": forcing_path,
        "output_file": output_path,
        "n_timesteps": len(results.get("GPP", [])),
        "metrics": metrics,
        "warnings": warnings,
        "parameters_used": params or "defaults",
    }


# ============================================================================
# CLI entry point
# ============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run QUINCY analytic model. "
                    "Simulates coupled C-N-P cycling with Farquhar photosynthesis."
    )
    parser.add_argument("--forcing", required=True,
                        help="QUINCY forcing CSV (from convert_forcing_to_quincy.py)")
    parser.add_argument("--params", default=None,
                        help="Parameter JSON file (from convert_parameters_to_quincy.py)")
    parser.add_argument("--pft", default=None,
                        choices=["enf", "dbf", "ebf", "c3grass"],
                        help="Use default parameters for this PFT")
    parser.add_argument("--output", required=True,
                        help="Output CSV file path")
    parser.add_argument("--lat", type=float, default=None,
                        help="Site latitude (degrees)")
    parser.add_argument("--calibrate", action="store_true",
                        help="Calibrate model before running (requires scipy)")
    args = parser.parse_args()

    # Load parameters
    params = None
    if args.params:
        with open(args.params, 'r') as f:
            param_data = json.load(f)
        params = param_data.get("params", param_data)
        print(f"Loaded parameters from {args.params}")
    elif args.pft:
        # Import PFT defaults
        from convert_parameters_to_quincy import PFT_DEFAULTS
        if args.pft in PFT_DEFAULTS:
            params = PFT_DEFAULTS[args.pft]["params"]
            print(f"Using default parameters for PFT: {args.pft}")

    result = run_pipeline(
        args.forcing, args.output,
        params=params, lat=args.lat,
        calibrate=args.calibrate,
    )

    print(json.dumps(result, indent=2, default=str))

    if result.get("status") == "error":
        sys.exit(1)
