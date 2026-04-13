#!/usr/bin/env python3
"""
convert_soil_params.py — Convert soil/parameter data to Landlab grid fields

Maps HWSD (Harmonized World Soil Database) or SoilGrids data to Landlab grid
fields for soil depth, erodibility, diffusivity, porosity, etc.

CRITICAL UNIT CONVERSIONS:
  - HWSD soil depth: cm → m (divide by 100)
  - SoilGrids bulk density: cg/cm³ → kg/m³ (multiply by 10)
  - Porosity: often given as fraction 0–1; Landlab expects fraction 0–1 (OK)
  - Hydraulic conductivity: HWSD gives cm/day → m/s (divide by 8.64e6)
  - Erodibility (K_sp): cannot be derived from soil data alone; requires
    calibration or literature values. This tool sets reasonable defaults.

Usage:
    python convert_soil_params.py --hwsd soil.csv --grid grid.nc --output params.json
    python convert_soil_params.py --depth 1.5 --porosity 0.4 --K_sp 1e-5 --output params.json
"""

import argparse
import json
import os
import sys

import numpy as np


# Typical soil parameter ranges for validation
PARAM_RANGES = {
    "soil__depth": (0.0, 50.0, "m"),
    "soil_porosity": (0.1, 0.7, "fraction"),
    "hydraulic_conductivity": (1e-10, 1e-2, "m/s"),
    "K_sp": (1e-10, 1e-1, "1/yr"),
    "linear_diffusivity": (1e-5, 10.0, "m^2/yr"),
    "soil_production_maximum_rate": (1e-7, 1e-2, "m/yr"),
    "soil_production_decay_depth": (0.05, 5.0, "m"),
}

# HWSD texture class → approximate parameters
TEXTURE_DEFAULTS = {
    "sand": {"porosity": 0.38, "K_sat_m_s": 5.8e-5, "diffusivity": 0.05},
    "loamy_sand": {"porosity": 0.39, "K_sat_m_s": 1.7e-5, "diffusivity": 0.04},
    "sandy_loam": {"porosity": 0.41, "K_sat_m_s": 7.2e-6, "diffusivity": 0.03},
    "loam": {"porosity": 0.43, "K_sat_m_s": 3.7e-6, "diffusivity": 0.02},
    "silt_loam": {"porosity": 0.45, "K_sat_m_s": 1.9e-6, "diffusivity": 0.015},
    "silt": {"porosity": 0.46, "K_sat_m_s": 1.0e-6, "diffusivity": 0.01},
    "clay_loam": {"porosity": 0.44, "K_sat_m_s": 6.4e-7, "diffusivity": 0.008},
    "silty_clay_loam": {"porosity": 0.47, "K_sat_m_s": 4.2e-7, "diffusivity": 0.007},
    "sandy_clay": {"porosity": 0.40, "K_sat_m_s": 3.3e-7, "diffusivity": 0.006},
    "silty_clay": {"porosity": 0.48, "K_sat_m_s": 2.5e-7, "diffusivity": 0.005},
    "clay": {"porosity": 0.48, "K_sat_m_s": 1.7e-7, "diffusivity": 0.004},
}


def validate_inputs(args):
    """Validate command-line arguments and file paths."""
    errors = []

    if args.hwsd and not os.path.exists(args.hwsd):
        errors.append(f"HWSD file not found: {args.hwsd}")

    if args.grid and not os.path.exists(args.grid):
        errors.append(f"Grid file not found: {args.grid}")

    if args.depth is not None and args.depth < 0:
        errors.append(f"Soil depth must be non-negative, got {args.depth}")

    if args.porosity is not None and not (0 < args.porosity < 1):
        errors.append(f"Porosity must be 0–1, got {args.porosity}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)


def process(args):
    """Process soil data and generate Landlab-compatible parameters."""
    params = {}

    if args.hwsd:
        params = _process_hwsd(args)
    else:
        params = _process_manual(args)

    return params


def _process_hwsd(args):
    """Read HWSD CSV and extract soil parameters."""
    import pandas as pd

    df = pd.read_csv(args.hwsd)

    # Expected columns: lat, lon, T_GRAVEL, T_SAND, T_SILT, T_CLAY,
    #                    T_REF_DEPTH, T_BULK_DENSITY, T_OC
    result = {}

    # Soil depth: HWSD T_REF_DEPTH is in cm → convert to m
    if "T_REF_DEPTH" in df.columns:
        depth_cm = df["T_REF_DEPTH"].mean()
        depth_m = depth_cm / 100.0  # CRITICAL: cm → m
        result["soil__depth"] = depth_m
        result["_unit_conversion_applied"] = "T_REF_DEPTH cm → m (÷100)"
    else:
        result["soil__depth"] = args.depth if args.depth else 1.0

    # Porosity from bulk density: porosity = 1 - (bulk_density / 2650)
    if "T_BULK_DENSITY" in df.columns:
        # HWSD bulk density is in kg/dm³ → kg/m³ = ×1000
        bd_kg_dm3 = df["T_BULK_DENSITY"].mean()
        bd_kg_m3 = bd_kg_dm3 * 1000.0
        porosity = 1.0 - (bd_kg_m3 / 2650.0)
        porosity = np.clip(porosity, 0.1, 0.7)
        result["soil_porosity"] = float(porosity)
    else:
        result["soil_porosity"] = args.porosity if args.porosity else 0.4

    # Determine texture class from sand/clay percentages
    if "T_SAND" in df.columns and "T_CLAY" in df.columns:
        sand_pct = df["T_SAND"].mean()
        clay_pct = df["T_CLAY"].mean()
        texture = _classify_texture(sand_pct, clay_pct)
        defaults = TEXTURE_DEFAULTS.get(texture, TEXTURE_DEFAULTS["loam"])
        result["texture_class"] = texture
        result["hydraulic_conductivity"] = defaults["K_sat_m_s"]
        result["linear_diffusivity"] = defaults["diffusivity"]
    else:
        result["hydraulic_conductivity"] = 3.7e-6  # loam default
        result["linear_diffusivity"] = 0.02

    # Erodibility: rough estimation from soil properties
    # K_sp is primarily a calibration parameter, but we provide a starting point
    result["K_sp"] = args.K_sp if args.K_sp else 1e-5
    result["soil_production_maximum_rate"] = 1e-4  # m/yr, typical
    result["soil_production_decay_depth"] = 0.5  # m, typical

    return result


def _process_manual(args):
    """Generate parameters from manual command-line inputs."""
    result = {
        "soil__depth": args.depth if args.depth else 1.0,
        "soil_porosity": args.porosity if args.porosity else 0.4,
        "K_sp": args.K_sp if args.K_sp else 1e-5,
        "linear_diffusivity": args.diffusivity if args.diffusivity else 0.01,
        "soil_production_maximum_rate": 1e-4,
        "soil_production_decay_depth": 0.5,
        "hydraulic_conductivity": 3.7e-6,
    }
    return result


def _classify_texture(sand_pct, clay_pct):
    """Classify soil texture from sand and clay percentages (USDA triangle)."""
    if clay_pct >= 40:
        if sand_pct >= 45:
            return "sandy_clay"
        elif sand_pct < 20:
            return "silty_clay" if clay_pct < 60 else "clay"
        else:
            return "clay"
    elif clay_pct >= 27:
        if sand_pct >= 20:
            return "clay_loam"
        else:
            return "silty_clay_loam"
    elif sand_pct >= 85:
        return "sand"
    elif sand_pct >= 70:
        return "loamy_sand"
    elif sand_pct >= 50:
        return "sandy_loam"
    elif clay_pct < 12:
        return "silt" if sand_pct < 20 else "silt_loam"
    else:
        return "loam"


def validate_outputs(params):
    """Validate parameter values for physical plausibility."""
    warnings = []

    for param_name, (lo, hi, units) in PARAM_RANGES.items():
        if param_name in params:
            val = params[param_name]
            if val < lo or val > hi:
                warnings.append(
                    f"WARNING: {param_name}={val} {units} outside typical "
                    f"range [{lo}, {hi}]"
                )

    # Check for common unit errors
    if "soil__depth" in params and params["soil__depth"] > 10:
        warnings.append(
            "WARNING: soil__depth > 10 m. Did you forget to convert from cm? "
            "HWSD depth is in cm, Landlab expects m."
        )

    if "soil_porosity" in params and params["soil_porosity"] > 1:
        warnings.append(
            "WARNING: porosity > 1. This should be a fraction (0–1), not percent."
        )

    return warnings


def main():
    parser = argparse.ArgumentParser(
        description="Convert soil/parameter data to Landlab grid fields"
    )
    parser.add_argument("--hwsd", type=str, default=None,
                        help="Path to HWSD CSV file")
    parser.add_argument("--grid", type=str, default=None,
                        help="Path to Landlab grid NetCDF (for spatial mapping)")
    parser.add_argument("--output", type=str, required=True,
                        help="Output JSON file path")
    parser.add_argument("--depth", type=float, default=None,
                        help="Uniform soil depth in METERS")
    parser.add_argument("--porosity", type=float, default=None,
                        help="Uniform porosity (fraction 0–1)")
    parser.add_argument("--K_sp", type=float, default=None,
                        help="Stream power erodibility (1/yr for m=0.5, n=1)")
    parser.add_argument("--diffusivity", type=float, default=None,
                        help="Hillslope diffusivity (m^2/yr)")
    args = parser.parse_args()

    validate_inputs(args)
    params = process(args)
    warnings = validate_outputs(params)

    # Write output
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(params, f, indent=2)

    summary = {
        "status": "success",
        "output_file": args.output,
        "n_parameters": len(params),
        "parameters": {k: v for k, v in params.items() if not k.startswith("_")},
        "warnings": warnings,
    }
    print(json.dumps(summary, indent=2), file=sys.stderr)


if __name__ == "__main__":
    main()
