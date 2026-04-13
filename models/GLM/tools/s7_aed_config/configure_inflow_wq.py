#!/usr/bin/env python3
"""
configure_inflow_wq.py — Add nutrient/WQ concentrations to GLM inflow CSV.

GLM-AED2 requires inflow CSV files to include water quality variables
alongside FLOW, TEMP, SALT. Without nutrient inflow loading, AED2 runs
with zero external nutrient input — producing unrealistic results (no
phytoplankton growth, no eutrophication response).

This tool takes an existing GLM inflow CSV (with FLOW, TEMP, SALT) and
adds nutrient concentration columns using either:
  (a) Constant concentrations (default, from trophic state or user values)
  (b) A seasonal pattern (cosine with peak in spring/summer)
  (c) An external CSV of observed nutrient timeseries

AED2 inflow variable naming convention:
  NIT_nit  : Nitrate-N (mmol N/m3) — divide mg/L by 14.01 to get mmol/m3
  NIT_amm  : Ammonium-N (mmol N/m3)
  PHS_frp  : Filterable reactive phosphorus (mmol P/m3) — divide mg/L by 30.97
  OGM_don  : Dissolved organic nitrogen (mmol N/m3)
  OGM_pon  : Particulate organic nitrogen (mmol N/m3)
  OGM_dop  : Dissolved organic phosphorus (mmol P/m3)
  OGM_pop  : Particulate organic phosphorus (mmol P/m3)
  OGM_doc  : Dissolved organic carbon (mmol C/m3) — divide mg/L by 12.01
  OGM_poc  : Particulate organic carbon (mmol C/m3)
  OXY_oxy  : Dissolved oxygen (mmol O2/m3) — divide mg/L by 32.0
  SIL_rsi  : Reactive silica (mmol Si/m3) — divide mg/L by 28.09
  PHY_*    : Phytoplankton groups in inflow (typically ~0, mmol C/m3)

Unit conversions (common lab units to AED2 mmol/m3):
  NO3-N (mg/L) / 14.01 * 1000 = mmol N/m3
  NH4-N (mg/L) / 14.01 * 1000 = mmol N/m3
  PO4-P (mg/L) / 30.97 * 1000 = mmol P/m3
  DOC   (mg/L) / 12.01 * 1000 = mmol C/m3
  DO    (mg/L) / 32.0  * 1000 = mmol O2/m3
  SiO2  (mg/L) / 60.08 * 1000 = mmol Si/m3

Trophic state presets (concentrations in mmol/m3):
  Oligotrophic:  Low N (5), low P (0.05), low DOC (100)
  Mesotrophic:   Moderate N (30), moderate P (0.3), moderate DOC (250)
  Eutrophic:     High N (80), high P (1.0), high DOC (500)

Usage:
    # Add mesotrophic nutrients to existing inflow
    python configure_inflow_wq.py \
        --inflow_csv bcs/inflow_1.csv \
        --trophic mesotrophic \
        --output bcs/inflow_1_wq.csv

    # Add custom concentrations
    python configure_inflow_wq.py \
        --inflow_csv bcs/inflow_1.csv \
        --nit_nit 15.0 --nit_amm 3.0 --phs_frp 0.2 \
        --ogm_doc 200.0 --oxy_oxy 300.0 \
        --output bcs/inflow_1_wq.csv

    # Seasonal pattern (peak in summer)
    python configure_inflow_wq.py \
        --inflow_csv bcs/inflow_1.csv \
        --trophic eutrophic --seasonal \
        --output bcs/inflow_1_wq.csv

    # Include phytoplankton groups in inflow (near-zero)
    python configure_inflow_wq.py \
        --inflow_csv bcs/inflow_1.csv \
        --trophic mesotrophic \
        --phyto_groups diatom,green,cyano \
        --output bcs/inflow_1_wq.csv
"""

import argparse
import json
import math
import os
import sys

import numpy as np
import pandas as pd


# Trophic state presets (all in mmol/m3 — AED2 units)
TROPHIC_PRESETS = {
    'oligotrophic': {
        'NIT_nit': 5.0,      # ~0.07 mg/L NO3-N
        'NIT_amm': 1.0,      # ~0.014 mg/L NH4-N
        'PHS_frp': 0.05,     # ~0.0015 mg/L PO4-P
        'OGM_don': 3.0,
        'OGM_pon': 1.0,
        'OGM_dop': 0.05,
        'OGM_pop': 0.02,
        'OGM_doc': 100.0,    # ~1.2 mg/L DOC
        'OGM_poc': 20.0,
        'OXY_oxy': 350.0,    # ~11.2 mg/L (near-saturated)
        'SIL_rsi': 30.0,
    },
    'mesotrophic': {
        'NIT_nit': 30.0,     # ~0.42 mg/L NO3-N
        'NIT_amm': 5.0,      # ~0.07 mg/L NH4-N
        'PHS_frp': 0.3,      # ~0.009 mg/L PO4-P
        'OGM_don': 10.0,
        'OGM_pon': 3.0,
        'OGM_dop': 0.2,
        'OGM_pop': 0.1,
        'OGM_doc': 250.0,    # ~3 mg/L DOC
        'OGM_poc': 50.0,
        'OXY_oxy': 300.0,    # ~9.6 mg/L
        'SIL_rsi': 50.0,
    },
    'eutrophic': {
        'NIT_nit': 80.0,     # ~1.12 mg/L NO3-N
        'NIT_amm': 15.0,     # ~0.21 mg/L NH4-N
        'PHS_frp': 1.0,      # ~0.031 mg/L PO4-P
        'OGM_don': 20.0,
        'OGM_pon': 8.0,
        'OGM_dop': 0.5,
        'OGM_pop': 0.3,
        'OGM_doc': 500.0,    # ~6 mg/L DOC
        'OGM_poc': 100.0,
        'OXY_oxy': 250.0,    # ~8 mg/L
        'SIL_rsi': 80.0,
    },
    'hypereutrophic': {
        'NIT_nit': 200.0,    # ~2.8 mg/L NO3-N
        'NIT_amm': 50.0,     # ~0.7 mg/L NH4-N
        'PHS_frp': 5.0,      # ~0.155 mg/L PO4-P
        'OGM_don': 40.0,
        'OGM_pon': 15.0,
        'OGM_dop': 1.0,
        'OGM_pop': 0.5,
        'OGM_doc': 1000.0,   # ~12 mg/L DOC
        'OGM_poc': 200.0,
        'OXY_oxy': 200.0,    # ~6.4 mg/L (may be hypoxic)
        'SIL_rsi': 100.0,
    },
}

# WQ variable metadata
WQ_VARS_INFO = {
    'NIT_nit': {'unit': 'mmol N/m3', 'description': 'Nitrate nitrogen'},
    'NIT_amm': {'unit': 'mmol N/m3', 'description': 'Ammonium nitrogen'},
    'PHS_frp': {'unit': 'mmol P/m3', 'description': 'Filterable reactive P'},
    'OGM_don': {'unit': 'mmol N/m3', 'description': 'Dissolved organic N'},
    'OGM_pon': {'unit': 'mmol N/m3', 'description': 'Particulate organic N'},
    'OGM_dop': {'unit': 'mmol P/m3', 'description': 'Dissolved organic P'},
    'OGM_pop': {'unit': 'mmol P/m3', 'description': 'Particulate organic P'},
    'OGM_doc': {'unit': 'mmol C/m3', 'description': 'Dissolved organic C'},
    'OGM_poc': {'unit': 'mmol C/m3', 'description': 'Particulate organic C'},
    'OXY_oxy': {'unit': 'mmol O2/m3', 'description': 'Dissolved oxygen'},
    'SIL_rsi': {'unit': 'mmol Si/m3', 'description': 'Reactive silica'},
}


def validate_inputs(args):
    """Validate inputs."""
    errors = []

    if not os.path.exists(args.inflow_csv):
        errors.append(f"Inflow CSV not found: {args.inflow_csv}")

    if args.trophic and args.trophic not in TROPHIC_PRESETS:
        errors.append(
            f"Unknown trophic state: {args.trophic}. "
            f"Available: {', '.join(TROPHIC_PRESETS.keys())}")

    if args.obs_wq_csv and not os.path.exists(args.obs_wq_csv):
        errors.append(f"Observed WQ CSV not found: {args.obs_wq_csv}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)


def apply_seasonal_pattern(base_value, dates, peak_doy=180,
                           amplitude_frac=0.5, hemisphere='north'):
    """
    Apply seasonal cosine pattern to base concentration.

    Peak in summer (DOY ~180 for N hemisphere, ~365 for S hemisphere).
    Nutrients peak in spring/early summer from snowmelt/runoff.

    Args:
        base_value: Mean annual concentration (mmol/m3)
        dates: Array of datetime objects
        peak_doy: Day of year for peak concentration (default: 180 = July)
        amplitude_frac: Fraction of base_value for seasonal amplitude
        hemisphere: 'north' or 'south'
    """
    if hemisphere == 'south':
        peak_doy = (peak_doy + 182) % 365

    doy = np.array([d.timetuple().tm_yday for d in dates])
    seasonal = base_value * (
        1.0 + amplitude_frac * np.cos(2 * math.pi * (doy - peak_doy) / 365.0))
    # Ensure non-negative
    return np.maximum(seasonal, 0.01)


def process(args):
    """Add WQ columns to inflow CSV."""
    # Read existing inflow CSV
    df = pd.read_csv(args.inflow_csv)

    # Parse time column
    time_col = None
    for col in df.columns:
        if col.strip().lower() in ('time', 'date', 'datetime'):
            time_col = col
            break
    if time_col is None:
        time_col = df.columns[0]

    dates = pd.to_datetime(df[time_col])

    # Determine base concentrations
    if args.trophic:
        base_concs = dict(TROPHIC_PRESETS[args.trophic])
    else:
        # Use user-specified or defaults (mesotrophic)
        base_concs = dict(TROPHIC_PRESETS['mesotrophic'])

    # Override with any user-specified values
    user_overrides = {}
    for var_name in WQ_VARS_INFO:
        attr_name = var_name.lower()
        if hasattr(args, attr_name) and getattr(args, attr_name) is not None:
            base_concs[var_name] = getattr(args, attr_name)
            user_overrides[var_name] = getattr(args, attr_name)

    # Apply values to dataframe
    if args.seasonal:
        # Seasonal nutrient pattern
        # N peaks in spring (DOY 120), P peaks in summer (DOY 200)
        # DO peaks in winter (cold water holds more O2)
        seasonal_params = {
            'NIT_nit': {'peak_doy': 120, 'amplitude_frac': 0.6},
            'NIT_amm': {'peak_doy': 150, 'amplitude_frac': 0.4},
            'PHS_frp': {'peak_doy': 200, 'amplitude_frac': 0.5},
            'OGM_don': {'peak_doy': 150, 'amplitude_frac': 0.3},
            'OGM_pon': {'peak_doy': 150, 'amplitude_frac': 0.4},
            'OGM_dop': {'peak_doy': 180, 'amplitude_frac': 0.3},
            'OGM_pop': {'peak_doy': 180, 'amplitude_frac': 0.3},
            'OGM_doc': {'peak_doy': 180, 'amplitude_frac': 0.3},
            'OGM_poc': {'peak_doy': 150, 'amplitude_frac': 0.5},
            'OXY_oxy': {'peak_doy': 15, 'amplitude_frac': 0.2},  # winter peak
            'SIL_rsi': {'peak_doy': 120, 'amplitude_frac': 0.3},
        }
        for var_name, base_val in base_concs.items():
            params = seasonal_params.get(var_name,
                                         {'peak_doy': 180,
                                          'amplitude_frac': 0.3})
            df[var_name] = apply_seasonal_pattern(
                base_val, dates, **params).round(3)
    elif args.obs_wq_csv:
        # Read observed WQ data and merge
        obs = pd.read_csv(args.obs_wq_csv)
        obs_time_col = None
        for col in obs.columns:
            if col.strip().lower() in ('time', 'date', 'datetime'):
                obs_time_col = col
                break
        if obs_time_col:
            obs[obs_time_col] = pd.to_datetime(obs[obs_time_col])
            # Merge on nearest date
            df_temp = df.copy()
            df_temp['_merge_date'] = dates
            obs['_merge_date'] = obs[obs_time_col]
            # Use merge_asof for nearest time matching
            df_temp = df_temp.sort_values('_merge_date')
            obs = obs.sort_values('_merge_date')
            merged = pd.merge_asof(df_temp, obs.drop(columns=[obs_time_col]),
                                   on='_merge_date', direction='nearest')
            df = merged.drop(columns=['_merge_date'])
        # Fill any remaining vars with base concentrations
        for var_name, base_val in base_concs.items():
            if var_name not in df.columns:
                df[var_name] = base_val
    else:
        # Constant concentrations
        for var_name, base_val in base_concs.items():
            df[var_name] = round(base_val, 3)

    # Add phytoplankton groups (typically near-zero in inflow)
    phyto_inflow_conc = args.phyto_inflow_conc
    if args.phyto_groups:
        for grp in args.phyto_groups.split(','):
            grp = grp.strip()
            col_name = f'PHY_{grp}'
            df[col_name] = phyto_inflow_conc

    return df, base_concs


def validate_outputs(df, base_concs):
    """Validate WQ values are physically reasonable."""
    warnings = []

    for var_name, info in WQ_VARS_INFO.items():
        if var_name in df.columns:
            vals = df[var_name]
            if vals.min() < 0:
                warnings.append(
                    f"{var_name} has negative values (min={vals.min():.3f})")
            if var_name == 'OXY_oxy' and vals.max() > 500:
                warnings.append(
                    f"OXY_oxy exceeds 500 mmol/m3 ({vals.max():.1f}) — "
                    f"likely supersaturated")
            if var_name == 'PHS_frp' and vals.max() > 50:
                warnings.append(
                    f"PHS_frp very high ({vals.max():.1f} mmol/m3 = "
                    f"{vals.max()*30.97/1000:.2f} mg/L) — "
                    f"check units (should be mmol P/m3)")

    return warnings


def generate_inflow_vars_list(df):
    """
    Generate the inflow_vars string for glm3.nml.

    GLM needs to know which variables are in the inflow CSV.
    The order must match the column order in the CSV.
    """
    # Standard vars first, then WQ vars
    base_vars = ['FLOW', 'TEMP', 'SALT']
    wq_vars = [c for c in df.columns if c not in base_vars
               and c.lower() not in ('time', 'date', 'datetime')]
    all_vars = base_vars + wq_vars
    return all_vars


def main():
    parser = argparse.ArgumentParser(
        description="Add nutrient/WQ concentrations to GLM inflow CSV "
                    "for AED2 simulation")

    parser.add_argument("--inflow_csv", type=str, required=True,
                        help="Existing GLM inflow CSV (FLOW, TEMP, SALT)")
    parser.add_argument("--output", type=str, required=True,
                        help="Output CSV with WQ columns added")

    # Concentration source
    parser.add_argument("--trophic", type=str, default=None,
                        choices=list(TROPHIC_PRESETS.keys()),
                        help="Trophic state preset for concentrations")
    parser.add_argument("--seasonal", action="store_true",
                        help="Apply seasonal cosine pattern to concentrations")
    parser.add_argument("--obs_wq_csv", type=str, default=None,
                        help="Observed WQ timeseries CSV to merge")

    # Individual nutrient overrides (mmol/m3)
    parser.add_argument("--nit_nit", type=float, default=None,
                        help="Nitrate-N (mmol N/m3)")
    parser.add_argument("--nit_amm", type=float, default=None,
                        help="Ammonium-N (mmol N/m3)")
    parser.add_argument("--phs_frp", type=float, default=None,
                        help="Filterable reactive P (mmol P/m3)")
    parser.add_argument("--ogm_don", type=float, default=None,
                        help="Dissolved organic N (mmol N/m3)")
    parser.add_argument("--ogm_pon", type=float, default=None,
                        help="Particulate organic N (mmol N/m3)")
    parser.add_argument("--ogm_dop", type=float, default=None,
                        help="Dissolved organic P (mmol P/m3)")
    parser.add_argument("--ogm_pop", type=float, default=None,
                        help="Particulate organic P (mmol P/m3)")
    parser.add_argument("--ogm_doc", type=float, default=None,
                        help="Dissolved organic C (mmol C/m3)")
    parser.add_argument("--ogm_poc", type=float, default=None,
                        help="Particulate organic C (mmol C/m3)")
    parser.add_argument("--oxy_oxy", type=float, default=None,
                        help="Dissolved oxygen (mmol O2/m3)")
    parser.add_argument("--sil_rsi", type=float, default=None,
                        help="Reactive silica (mmol Si/m3)")

    # Phytoplankton in inflow
    parser.add_argument("--phyto_groups", type=str, default=None,
                        help="Phyto groups to add (comma-separated, e.g. "
                             "diatom,green,cyano)")
    parser.add_argument("--phyto_inflow_conc", type=float, default=0.1,
                        help="Phytoplankton concentration in inflow "
                             "(mmol C/m3, default: 0.1, near-zero)")

    args = parser.parse_args()

    validate_inputs(args)
    df, base_concs = process(args)
    warnings = validate_outputs(df, base_concs)

    # Write output
    os.makedirs(os.path.dirname(args.output) or '.', exist_ok=True)
    df.to_csv(args.output, index=False)

    # Generate inflow_vars for glm3.nml
    all_vars = generate_inflow_vars_list(df)

    result = {
        "status": "success",
        "output_file": args.output,
        "num_records": len(df),
        "wq_variables_added": [c for c in df.columns
                               if c not in ('time', 'FLOW', 'TEMP', 'SALT')],
        "trophic_state": args.trophic or "custom",
        "seasonal_pattern": args.seasonal,
        "warnings": warnings,
        "glm_nml_inflow_config": {
            "inflow_varnum": len(all_vars),
            "inflow_vars": ', '.join(f"'{v}'" for v in all_vars),
            "note": "Update these values in the &inflow block of glm3.nml",
        },
    }

    # Summary statistics for key variables
    summary_vars = ['NIT_nit', 'NIT_amm', 'PHS_frp', 'OGM_doc', 'OXY_oxy']
    result["concentration_summary"] = {}
    for var in summary_vars:
        if var in df.columns:
            result["concentration_summary"][var] = {
                "mean": round(float(df[var].mean()), 3),
                "min": round(float(df[var].min()), 3),
                "max": round(float(df[var].max()), 3),
                "unit": WQ_VARS_INFO[var]['unit'],
            }

    for w in warnings:
        print(f"WARNING: {w}", file=sys.stderr)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
