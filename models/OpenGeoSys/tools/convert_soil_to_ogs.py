#!/usr/bin/env python3
"""
convert_soil_to_ogs.py — Convert soil/material properties to OGS format.

Converts soil texture and properties from HWSD or manual input to OpenGeoSys
material parameters in SI units. Produces JSON output compatible with the
OGS project file generator.

Pedotransfer functions implemented:
  - Saxton & Rawls (2006): texture → Ksat, porosity, field capacity
  - Carsel & Parrish (1988): texture class → van Genuchten parameters
  - Côté & Konrad (2005): texture → thermal conductivity

CRITICAL CONSTRAINTS:
  - OGS permeability is INTRINSIC (m²), NOT hydraulic conductivity (m/s)
    Conversion: κ = Ksat × μ / (ρ × g) ≈ Ksat × 1.02e-7 at 20°C
  - van Genuchten α must be converted from 1/cm to entry pressure in Pa:
    p_b = ρ × g / (α_m) where α_m = α_cm × 100
  - Temperature must be in K (add 273.15 to °C)
  - Density in kg/m³, viscosity in Pa·s

Usage:
    python convert_soil_to_ogs.py --sand 60 --clay 15 --silt 25 --output soil.json
    python convert_soil_to_ogs.py --texture_class "sandy_loam" --output soil.json
    python convert_soil_to_ogs.py --hwsd_csv hwsd_data.csv --lat 40.0 --lon 116.5 --output soil.json
"""

import argparse
import json
import math
import os
import sys

import numpy as np


# ============================================================================
# Physical constants (SI)
# ============================================================================
WATER_DENSITY = 998.2  # kg/m³ at 20°C
GRAVITY = 9.81  # m/s²
WATER_VISCOSITY = 1.002e-3  # Pa·s at 20°C
RHO_G = WATER_DENSITY * GRAVITY  # ≈ 9792 Pa/m

# ============================================================================
# Carsel & Parrish (1988) — van Genuchten parameters by USDA texture class
# α in 1/cm, n dimensionless, θ_r and θ_s as fractions, Ksat in cm/day
# ============================================================================
VG_PARAMS = {
    "sand":        {"alpha_cm": 0.145, "n": 2.68,  "theta_r": 0.045, "theta_s": 0.43,  "Ksat_cm_day": 712.8},
    "loamy_sand":  {"alpha_cm": 0.124, "n": 2.28,  "theta_r": 0.057, "theta_s": 0.41,  "Ksat_cm_day": 350.2},
    "sandy_loam":  {"alpha_cm": 0.075, "n": 1.89,  "theta_r": 0.065, "theta_s": 0.41,  "Ksat_cm_day": 106.1},
    "loam":        {"alpha_cm": 0.036, "n": 1.56,  "theta_r": 0.078, "theta_s": 0.43,  "Ksat_cm_day": 24.96},
    "silt":        {"alpha_cm": 0.016, "n": 1.37,  "theta_r": 0.034, "theta_s": 0.46,  "Ksat_cm_day": 6.00},
    "silt_loam":   {"alpha_cm": 0.020, "n": 1.41,  "theta_r": 0.067, "theta_s": 0.45,  "Ksat_cm_day": 10.80},
    "sandy_clay_loam": {"alpha_cm": 0.059, "n": 1.48, "theta_r": 0.100, "theta_s": 0.39, "Ksat_cm_day": 31.44},
    "clay_loam":   {"alpha_cm": 0.019, "n": 1.31,  "theta_r": 0.095, "theta_s": 0.41,  "Ksat_cm_day": 6.24},
    "silty_clay_loam": {"alpha_cm": 0.010, "n": 1.23, "theta_r": 0.089, "theta_s": 0.43, "Ksat_cm_day": 1.68},
    "sandy_clay":  {"alpha_cm": 0.027, "n": 1.23,  "theta_r": 0.100, "theta_s": 0.38,  "Ksat_cm_day": 2.88},
    "silty_clay":  {"alpha_cm": 0.005, "n": 1.09,  "theta_r": 0.070, "theta_s": 0.36,  "Ksat_cm_day": 0.48},
    "clay":        {"alpha_cm": 0.008, "n": 1.09,  "theta_r": 0.068, "theta_s": 0.38,  "Ksat_cm_day": 4.80},
}


def validate_inputs(args):
    """Validate input arguments."""
    errors = []

    if args.texture_class:
        tc = args.texture_class.lower().replace(" ", "_")
        if tc not in VG_PARAMS:
            errors.append(f"Unknown texture class: {args.texture_class}. "
                          f"Valid: {list(VG_PARAMS.keys())}")
    elif args.hwsd_csv:
        if not os.path.isfile(args.hwsd_csv):
            errors.append(f"HWSD CSV file not found: {args.hwsd_csv}")
    else:
        # Manual input: need sand + clay (silt = 100 - sand - clay)
        if args.sand is None or args.clay is None:
            errors.append("Either --texture_class, --hwsd_csv, or --sand + --clay required")
        else:
            total = args.sand + args.clay + (args.silt or (100 - args.sand - args.clay))
            if abs(total - 100.0) > 1.0:
                errors.append(f"Sand + clay + silt must equal 100%, got {total}%")
            if args.sand < 0 or args.clay < 0:
                errors.append("Sand and clay percentages must be non-negative")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)


def classify_texture(sand, clay):
    """Classify USDA texture class from sand and clay percentages."""
    silt = 100 - sand - clay
    if sand >= 85 and clay < 10:
        return "sand"
    elif sand >= 70 and clay < 15:
        return "loamy_sand"
    elif (sand >= 43 and clay < 20 and silt < 50) or (sand >= 52 and clay < 7):
        return "sandy_loam"
    elif clay >= 40 and silt >= 40:
        return "silty_clay"
    elif clay >= 40 and sand >= 45:
        return "sandy_clay"
    elif clay >= 40:
        return "clay"
    elif clay >= 27 and sand >= 20 and sand < 45:
        return "clay_loam"
    elif clay >= 27 and sand < 20:
        return "silty_clay_loam"
    elif clay >= 20 and sand >= 45:
        return "sandy_clay_loam"
    elif silt >= 80:
        return "silt"
    elif silt >= 50:
        return "silt_loam"
    else:
        return "loam"


def saxton_rawls_ksat(sand, clay, organic_matter=1.0):
    """Saxton & Rawls (2006) pedotransfer for Ksat in cm/hr."""
    S = sand / 100.0
    C = clay / 100.0
    OM = organic_matter / 100.0

    # Moisture at 1500 kPa (wilting point)
    theta_1500 = (-0.024 * S + 0.487 * C + 0.006 * OM
                  + 0.005 * S * OM - 0.013 * C * OM
                  + 0.068 * S * C + 0.031)
    theta_1500 = theta_1500 + (0.14 * theta_1500 - 0.02)

    # Moisture at 33 kPa (field capacity)
    theta_33 = (-0.251 * S + 0.195 * C + 0.011 * OM
                + 0.006 * S * OM - 0.027 * C * OM
                + 0.452 * S * C + 0.299)
    theta_33 = theta_33 + (1.283 * theta_33 ** 2 - 0.374 * theta_33 - 0.015)

    # Saturated moisture content
    theta_s_33 = (0.278 * S + 0.034 * C + 0.022 * OM
                  - 0.018 * S * OM - 0.027 * C * OM
                  - 0.584 * S * C + 0.078)
    theta_s_33 = theta_s_33 + (0.636 * theta_s_33 - 0.107)
    theta_s = theta_33 + theta_s_33 - 0.097 * S + 0.043

    # Pore size distribution parameter (B)
    B = (math.log(1500) - math.log(33)) / (math.log(theta_33) - math.log(theta_1500))

    # Lambda = 1/B
    lam = 1.0 / B

    # Ksat in mm/hr
    Ksat = 1930 * (theta_s - theta_33) ** (3 - lam)

    return Ksat / 10.0  # Convert mm/hr to cm/hr


def compute_thermal_conductivity(sand, clay, porosity, saturation=1.0):
    """Côté & Konrad (2005) thermal conductivity model. Returns W/(m·K)."""
    # Solid thermal conductivity (geometric mean of mineral components)
    quartz_fraction = sand / 100.0
    lambda_quartz = 7.7  # W/(m·K)
    lambda_other = 2.0   # W/(m·K) for non-quartz minerals
    lambda_solid = lambda_quartz ** quartz_fraction * lambda_other ** (1.0 - quartz_fraction)

    # Water and air conductivity
    lambda_water = 0.6   # W/(m·K)
    lambda_air = 0.025   # W/(m·K)

    # Saturated conductivity (geometric mean)
    lambda_sat = lambda_solid ** (1 - porosity) * lambda_water ** porosity

    # Dry conductivity
    lambda_dry = (0.135 * (1 - porosity) * 2650 + 64.7) / (2650 - 0.947 * (1 - porosity) * 2650)

    # Kersten number for saturation
    if saturation > 0.01:
        kappa = 0.7  # For coarse soils (sand > 50%)
        if sand < 50:
            kappa = 0.4  # For fine soils
        Ke = kappa * saturation / (1 + (kappa - 1) * saturation)
    else:
        Ke = 0.0

    lambda_eff = (lambda_sat - lambda_dry) * Ke + lambda_dry
    return lambda_eff


def process(args):
    """Main processing: compute OGS material parameters."""
    warnings = []

    # Determine texture class and van Genuchten parameters
    if args.texture_class:
        tc = args.texture_class.lower().replace(" ", "_")
        vg = VG_PARAMS[tc]
        sand = {"sand": 90, "loamy_sand": 80, "sandy_loam": 60, "loam": 40,
                "silt": 10, "silt_loam": 25, "sandy_clay_loam": 55, "clay_loam": 30,
                "silty_clay_loam": 10, "sandy_clay": 50, "silty_clay": 5, "clay": 20}[tc]
        clay = {"sand": 5, "loamy_sand": 8, "sandy_loam": 12, "loam": 20,
                "silt": 5, "silt_loam": 15, "sandy_clay_loam": 25, "clay_loam": 32,
                "silty_clay_loam": 33, "sandy_clay": 42, "silty_clay": 45, "clay": 55}[tc]
    else:
        sand = args.sand
        clay = args.clay
        tc = classify_texture(sand, clay)
        vg = VG_PARAMS[tc]

    silt = 100.0 - sand - clay
    organic = args.organic if args.organic else 1.0

    # Compute Ksat using Saxton-Rawls
    Ksat_cm_hr = saxton_rawls_ksat(sand, clay, organic)
    Ksat_m_s = Ksat_cm_hr / (100.0 * 3600.0)  # cm/hr → m/s

    # CRITICAL: Convert hydraulic conductivity to intrinsic permeability
    # κ = K × μ / (ρ × g)
    intrinsic_permeability = Ksat_m_s * WATER_VISCOSITY / RHO_G

    # van Genuchten parameters for OGS
    # OGS uses: residual saturation S_L_res, max saturation S_L_max, exponent m, entry pressure p_b
    alpha_cm = vg["alpha_cm"]  # 1/cm
    alpha_m = alpha_cm * 100.0  # 1/cm → 1/m  (CRITICAL: factor 100)
    entry_pressure_Pa = RHO_G / alpha_m  # p_b = ρg/α [Pa]

    n = vg["n"]
    m = 1.0 - 1.0 / n  # Mualem relationship

    residual_saturation = vg["theta_r"] / vg["theta_s"]
    max_saturation = 1.0
    porosity = vg["theta_s"]

    # Storage coefficient (specific storage for confined aquifer)
    # S_s = ρg(α_aquifer + n*β_water) where α_aquifer ≈ 1e-8 1/Pa, β_water = 4.4e-10 1/Pa
    specific_storage = RHO_G * (1e-8 + porosity * 4.4e-10)

    # Thermal properties
    bulk_density = args.bulk_density if args.bulk_density else (1.0 - porosity) * 2650
    thermal_conductivity = compute_thermal_conductivity(sand, clay, porosity)
    specific_heat_solid = 800.0  # J/(kg·K) typical for minerals

    # Validate ranges
    if intrinsic_permeability > 1e-8:
        warnings.append(f"Very high permeability {intrinsic_permeability:.2e} m² — gravel or coarser")
    if intrinsic_permeability < 1e-18:
        warnings.append(f"Very low permeability {intrinsic_permeability:.2e} m² — impervious")
    if porosity < 0.05 or porosity > 0.7:
        warnings.append(f"Unusual porosity {porosity:.3f} — check soil data")

    result = {
        "status": "success",
        "texture_class": tc,
        "sand_pct": sand,
        "clay_pct": clay,
        "silt_pct": silt,
        "organic_pct": organic,

        # Hydraulic parameters (OGS format, SI units)
        "ogs_parameters": {
            "permeability_m2": intrinsic_permeability,
            "porosity": porosity,
            "storage_1_per_Pa": specific_storage,
            "liquid_density_kg_m3": WATER_DENSITY,
            "liquid_viscosity_Pa_s": WATER_VISCOSITY,

            # van Genuchten (for RichardsFlow)
            "van_genuchten": {
                "residual_liquid_saturation": residual_saturation,
                "maximum_liquid_saturation": max_saturation,
                "exponent_m": m,
                "entry_pressure_Pa": entry_pressure_Pa,
                "n": n,
                "alpha_1_per_m": alpha_m,
                "alpha_1_per_cm_original": alpha_cm,
            },

            # Thermal parameters
            "solid_density_kg_m3": 2650.0,
            "solid_thermal_conductivity_W_per_mK": thermal_conductivity,
            "solid_specific_heat_J_per_kgK": specific_heat_solid,
            "liquid_thermal_conductivity_W_per_mK": 0.6,
            "liquid_specific_heat_J_per_kgK": 4182.0,
        },

        # Intermediate values for verification
        "intermediate": {
            "Ksat_cm_hr": Ksat_cm_hr,
            "Ksat_m_s": Ksat_m_s,
            "bulk_density_kg_m3": bulk_density,
        },

        "warnings": warnings,
    }

    return result


def validate_outputs(result):
    """Validate output parameters for physical consistency."""
    if result["status"] != "success":
        return result

    warnings = result.get("warnings", [])
    params = result["ogs_parameters"]

    # Cross-check: Ksat back-calculation
    ksat_check = params["permeability_m2"] * RHO_G / WATER_VISCOSITY
    if ksat_check < 1e-12:
        warnings.append("Back-calculated Ksat < 1e-12 m/s — aquiclude")

    # Check van Genuchten m range
    vg = params["van_genuchten"]
    if vg["exponent_m"] <= 0 or vg["exponent_m"] >= 1:
        warnings.append(f"van Genuchten m = {vg['exponent_m']:.3f} outside (0,1) — invalid")

    if vg["entry_pressure_Pa"] < 100:
        warnings.append(f"Entry pressure {vg['entry_pressure_Pa']:.0f} Pa very low — coarse gravel?")
    if vg["entry_pressure_Pa"] > 1e6:
        warnings.append(f"Entry pressure {vg['entry_pressure_Pa']:.0f} Pa very high — dense clay?")

    result["warnings"] = warnings
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Convert soil properties to OGS material parameters (SI units)"
    )
    parser.add_argument("--sand", type=float, default=None, help="Sand percentage (0-100)")
    parser.add_argument("--clay", type=float, default=None, help="Clay percentage (0-100)")
    parser.add_argument("--silt", type=float, default=None, help="Silt percentage (auto-calculated if omitted)")
    parser.add_argument("--organic", type=float, default=1.0, help="Organic matter percentage (default 1.0)")
    parser.add_argument("--bulk_density", type=float, default=None, help="Bulk density kg/m³")
    parser.add_argument("--texture_class", type=str, default=None, help="USDA texture class name")
    parser.add_argument("--hwsd_csv", type=str, default=None, help="HWSD CSV data file")
    parser.add_argument("--lat", type=float, default=None, help="Latitude (for HWSD lookup)")
    parser.add_argument("--lon", type=float, default=None, help="Longitude (for HWSD lookup)")
    parser.add_argument("--output", type=str, required=True, help="Output JSON file path")

    args = parser.parse_args()

    validate_inputs(args)
    result = process(args)
    result = validate_outputs(result)

    output_json = json.dumps(result, indent=2)
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w") as f:
        f.write(output_json)
    print(f"Output written to {args.output}", file=sys.stderr)
    print(output_json)


if __name__ == "__main__":
    main()
