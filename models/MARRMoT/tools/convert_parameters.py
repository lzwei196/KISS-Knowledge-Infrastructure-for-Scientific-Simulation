"""
MARRMoT Parameter Converter
============================
Map soil and land-surface properties (e.g. from HWSD, SoilGrids) to
MARRMoT model parameter vectors within their defined ranges.

Each MARRMoT model defines its own parRanges (min/max bounds per parameter).
This tool generates an initial parameter vector by:
  1. Reading soil/land properties
  2. Applying pedotransfer functions to estimate hydrological parameters
  3. Clipping to the model's valid parameter ranges

CRITICAL: Storage parameters (Smax, etc.) must be in mm, not m (dt_008).
  HWSD depths are often in cm; SoilGrids in mm. Always verify units.

Usage:
  python convert_parameters.py --model m_29_hymod_5p_5s \
    --soil-data hwsd_extract.csv --output params.json

  python convert_parameters.py --model m_37_hbv96_15p_5s \
    --soil-depth-cm 150 --porosity 0.4 --clay-frac 0.3 \
    --output params.json
"""

import argparse
import json
import os
import sys

import numpy as np


# ── Model parameter metadata ─────────────────────────────────────────
# Each model: {name: (n_params, n_stores, [(pname, pmin, pmax, unit, desc)])}
MODEL_PARAMS = {
    "m_01_collie1_1p_1s": {
        "n_params": 1, "n_stores": 1,
        "params": [
            ("Smax", 1, 2000, "mm", "Maximum soil moisture storage"),
        ],
    },
    "m_07_gr4j_4p_2s": {
        "n_params": 4, "n_stores": 2,
        "params": [
            ("x1", 1, 1500, "mm", "Production store capacity"),
            ("x2", -10, 5, "mm", "Groundwater exchange coefficient"),
            ("x3", 1, 500, "mm", "Routing store capacity"),
            ("x4", 0.5, 4, "d", "Unit hydrograph time base"),
        ],
    },
    "m_29_hymod_5p_5s": {
        "n_params": 5, "n_stores": 5,
        "params": [
            ("Smax", 1, 2000, "mm", "Maximum soil moisture storage"),
            ("b", 0, 10, "-", "Distribution function shape"),
            ("a", 0, 1, "-", "Flow split coefficient (fast/slow)"),
            ("kf", 0, 1, "1/d", "Fast reservoir rate constant"),
            ("ks", 0, 1, "1/d", "Slow reservoir rate constant"),
        ],
    },
    "m_33_sacramento_11p_5s": {
        "n_params": 11, "n_stores": 5,
        "params": [
            ("pctim", 0, 1, "-", "Fraction permanently impervious"),
            ("smax", 1, 1500, "mm", "Max combined soil storage"),
            ("f1", 0, 1, "-", "Fraction of smax in upper zone tension"),
            ("f2", 0, 1, "-", "Fraction of smax-f1 in upper zone free"),
            ("kuz", 0, 1, "1/d", "Upper zone interflow rate"),
            ("rexp", 0, 5, "-", "Percolation demand exponent"),
            ("f3", 0, 1, "-", "Fraction of lower zone in tension"),
            ("f4", 0, 1, "-", "Fraction of lower free in primary"),
            ("klzp", 0, 0.05, "1/d", "Lower zone primary baseflow rate"),
            ("klzs", 0, 0.5, "1/d", "Lower zone supplemental baseflow rate"),
            ("pfree", 0, 1, "-", "Fraction perc going to lower free"),
        ],
    },
    "m_37_hbv96_15p_5s": {
        "n_params": 15, "n_stores": 5,
        "params": [
            ("TT", -3, 5, "degC", "Threshold temperature rain/snow"),
            ("TTI", 0, 5, "degC", "Temperature interval for mixed precip"),
            ("TTM", -3, 5, "degC", "Threshold temperature for melt"),
            ("ddf", 0, 20, "mm/d/C", "Degree-day melt factor"),
            ("Smax", 1, 2000, "mm", "Maximum soil moisture storage"),
            ("beta", 0, 7, "-", "Soil moisture non-linearity"),
            ("fc", 0, 1, "-", "Fraction field capacity"),
            ("k0", 0, 1, "1/d", "Near-surface flow rate"),
            ("k1", 0, 1, "1/d", "Interflow rate"),
            ("k2", 0, 0.1, "1/d", "Baseflow rate"),
            ("lp", 0, 1, "-", "Limit for PET reduction"),
            ("perc", 0, 20, "mm/d", "Max percolation rate"),
            ("cflux", 0, 5, "mm/d", "Max capillary rise"),
            ("alpha", 0, 5, "-", "Response box non-linearity"),
            ("maxbas", 1, 10, "d", "Routing UH time base"),
        ],
    },
}


def validate_inputs(args):
    """Validate input arguments."""
    errors = []

    if args.model not in MODEL_PARAMS:
        known = ", ".join(sorted(MODEL_PARAMS.keys()))
        errors.append(
            f"Unknown model: {args.model}. "
            f"Known models: {known}. "
            "For unlisted models, use --param-ranges JSON to supply ranges.")

    if args.soil_data and not os.path.isfile(args.soil_data):
        errors.append(f"Soil data file not found: {args.soil_data}")

    if args.porosity is not None and not (0 < args.porosity < 1):
        errors.append(f"Porosity must be 0-1, got {args.porosity}")

    if args.clay_frac is not None and not (0 <= args.clay_frac <= 1):
        errors.append(f"Clay fraction must be 0-1, got {args.clay_frac}")

    if args.soil_depth_cm is not None and args.soil_depth_cm <= 0:
        errors.append(f"Soil depth must be positive, got {args.soil_depth_cm}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)


def estimate_smax(soil_depth_cm, porosity, clay_frac):
    """
    Estimate maximum soil moisture storage (mm) from soil properties.

    Uses simplified pedotransfer: Smax = depth_mm * available_water_capacity
    where AWC depends on porosity and texture.
    """
    depth_mm = soil_depth_cm * 10.0  # cm -> mm (NOT m -> mm!)

    # Available water capacity: fraction of pore space that holds plant-available water
    # Cosby et al. (1984) approximation
    field_capacity = 0.1 + 0.3 * clay_frac + 0.2 * porosity
    wilting_point = 0.05 + 0.15 * clay_frac
    awc = max(field_capacity - wilting_point, 0.01)

    smax = depth_mm * awc
    return smax


def estimate_baseflow_k(clay_frac, soil_depth_cm):
    """
    Estimate baseflow rate constant (1/d) from soil texture.
    Sandy soils drain faster than clay soils.
    """
    # Approximate: k decreases with clay content
    k_base = 0.5 * (1.0 - clay_frac)
    # Deeper soils have slower baseflow
    depth_factor = min(soil_depth_cm / 200.0, 1.0)
    k = k_base * (1.0 - 0.5 * depth_factor)
    return max(0.001, min(k, 0.99))


def estimate_params_from_soil(model_name, soil_depth_cm, porosity, clay_frac):
    """
    Generate initial parameter vector from soil properties.
    Returns dict of {param_name: estimated_value}.
    """
    meta = MODEL_PARAMS[model_name]
    params = {}
    smax = estimate_smax(soil_depth_cm, porosity, clay_frac)
    k_slow = estimate_baseflow_k(clay_frac, soil_depth_cm)
    k_fast = min(k_slow * 5, 0.99)

    for pname, pmin, pmax, unit, desc in meta["params"]:
        pname_lower = pname.lower()

        if "smax" in pname_lower or pname_lower in ("x1", "x3", "smax"):
            # Storage parameters: use pedotransfer estimate, clip to range
            val = np.clip(smax, pmin, pmax)
        elif pname_lower in ("ks", "k2", "klzp", "klzs"):
            val = np.clip(k_slow, pmin, pmax)
        elif pname_lower in ("kf", "k0", "k1", "kuz"):
            val = np.clip(k_fast, pmin, pmax)
        elif pname_lower in ("a", "alpha"):
            # Flow split: default 0.7 fast / 0.3 slow
            val = np.clip(0.7, pmin, pmax)
        elif pname_lower in ("b", "beta"):
            # Non-linearity: default mid-range
            val = (pmin + pmax) / 2
        elif "tt" in pname_lower:
            # Temperature thresholds: default 0 degC
            val = np.clip(0.0, pmin, pmax)
        elif pname_lower == "ddf":
            # Degree-day factor: default 3 mm/d/C
            val = np.clip(3.0, pmin, pmax)
        elif pname_lower in ("fc", "lp", "f1", "f2", "f3", "f4", "pfree"):
            # Fraction parameters: default 0.5
            val = np.clip(0.5, pmin, pmax)
        elif pname_lower in ("perc", "cflux"):
            # Flux rates: default 2 mm/d
            val = np.clip(2.0, pmin, pmax)
        elif pname_lower in ("maxbas", "x4"):
            # Routing time base: default 2 days
            val = np.clip(2.0, pmin, pmax)
        elif pname_lower in ("pctim",):
            # Impervious fraction: default 0.01
            val = np.clip(0.01, pmin, pmax)
        elif pname_lower in ("rexp",):
            # Exponent: default 1.5
            val = np.clip(1.5, pmin, pmax)
        else:
            # Default: midpoint of range
            val = (pmin + pmax) / 2

        params[pname] = float(val)

    return params


def process(args):
    """Main processing: generate parameter vector."""
    model_name = args.model
    meta = MODEL_PARAMS.get(model_name)

    if meta is None:
        return {"status": "error",
                "errors": [f"Model {model_name} not in parameter database"]}

    # Get soil properties from args or defaults
    soil_depth_cm = args.soil_depth_cm or 150.0
    porosity = args.porosity or 0.40
    clay_frac = args.clay_frac or 0.25

    # If soil data file provided, try to parse it
    if args.soil_data:
        try:
            import pandas as pd
            df = pd.read_csv(args.soil_data)
            if "soil_depth_cm" in df.columns:
                soil_depth_cm = float(df["soil_depth_cm"].iloc[0])
            if "porosity" in df.columns:
                porosity = float(df["porosity"].iloc[0])
            if "clay_fraction" in df.columns:
                clay_frac = float(df["clay_fraction"].iloc[0])
            print(f"Read soil properties from {args.soil_data}",
                  file=sys.stderr)
        except Exception as e:
            print(f"Warning: Could not parse soil file: {e}",
                  file=sys.stderr)

    params = estimate_params_from_soil(model_name, soil_depth_cm,
                                        porosity, clay_frac)

    # Build result
    param_vector = [params[p[0]] for p in meta["params"]]
    s0_vector = [0.0] * meta["n_stores"]  # default: empty stores

    result = {
        "status": "success",
        "model": model_name,
        "n_params": meta["n_params"],
        "n_stores": meta["n_stores"],
        "theta": param_vector,
        "S0": s0_vector,
        "param_details": {},
        "soil_properties_used": {
            "soil_depth_cm": soil_depth_cm,
            "porosity": porosity,
            "clay_fraction": clay_frac,
        },
        "warnings": [],
    }

    for pname, pmin, pmax, unit, desc in meta["params"]:
        result["param_details"][pname] = {
            "value": params[pname],
            "min": pmin,
            "max": pmax,
            "unit": unit,
            "description": desc,
        }

    # Warnings
    if any(params[p[0]] == p[1] or params[p[0]] == p[2]
           for p in meta["params"]):
        result["warnings"].append(
            "Some parameters at range boundary -- consider calibration")

    return result


def validate_outputs(result):
    """Validate parameter vector."""
    if result["status"] != "success":
        return result

    warnings = result.get("warnings", [])

    # Check theta length matches model expectation
    if len(result["theta"]) != result["n_params"]:
        warnings.append(
            f"theta length {len(result['theta'])} != expected "
            f"{result['n_params']} (dt_012)")

    if len(result["S0"]) != result["n_stores"]:
        warnings.append(
            f"S0 length {len(result['S0'])} != expected "
            f"{result['n_stores']} (dt_012)")

    result["warnings"] = warnings
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Convert soil/land data to MARRMoT parameters")
    parser.add_argument("--model", required=True,
                        help="MARRMoT model name (e.g. m_29_hymod_5p_5s)")
    parser.add_argument("--soil-data", default=None,
                        help="CSV with soil properties")
    parser.add_argument("--soil-depth-cm", type=float, default=None,
                        help="Soil depth in cm")
    parser.add_argument("--porosity", type=float, default=None,
                        help="Soil porosity (0-1)")
    parser.add_argument("--clay-frac", type=float, default=None,
                        help="Clay fraction (0-1)")
    parser.add_argument("--output", required=True,
                        help="Output JSON file")
    parser.add_argument("--param-ranges", default=None,
                        help="JSON file with custom parameter ranges")

    args = parser.parse_args()
    validate_inputs(args)
    result = process(args)
    result = validate_outputs(result)

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(result, f, indent=2)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
