#!/usr/bin/env python3
"""
convert_soil_to_amanzi.py — Soil/Material Parameter Converter for Amanzi/ATS

Converts soil properties from HWSD (Harmonized World Soil Database) or
SoilGrids to Amanzi-compatible van Genuchten / Brooks-Corey parameters.

Key unit conversions:
  - Hydraulic conductivity: cm/day → m² (intrinsic permeability)
    k = K * μ / (ρ * g) ≈ K_m_s * 1.02e-7
  - van Genuchten α: 1/cm → 1/Pa
    α_Pa = α_cm / (ρ * g * 100) ≈ α_cm / 980665
  - Kd (sorption): mL/g → m³/kg
    Kd_m3_kg = Kd_mL_g * 0.001
  - Dispersivity: cm → m (÷100)

Pattern: validate_inputs → process → validate_outputs

Reference pedotransfer functions:
  - Schaap et al. (2001) — Rosetta model for vG parameters
  - Carsel & Parrish (1988) — USDA texture class averages
"""

import argparse
import json
import sys
import os
import math

# ============================================================================
# Constants
# ============================================================================
WATER_DENSITY = 998.2  # kg/m³
WATER_VISCOSITY = 1.002e-3  # Pa·s at ~20°C
GRAVITY = 9.80665  # m/s²

# van Genuchten parameters by USDA texture class
# Source: Carsel & Parrish (1988), Journal of Hydrology
# α [1/cm], n [-], θ_r [-], θ_s [-], K_sat [cm/day]
VG_BY_TEXTURE = {
    "sand":        {"alpha_cm": 0.145, "n": 2.68,  "theta_r": 0.045, "theta_s": 0.43, "ksat_cm_day": 712.8},
    "loamy sand":  {"alpha_cm": 0.124, "n": 2.28,  "theta_r": 0.057, "theta_s": 0.41, "ksat_cm_day": 350.2},
    "sandy loam":  {"alpha_cm": 0.075, "n": 1.89,  "theta_r": 0.065, "theta_s": 0.41, "ksat_cm_day": 106.1},
    "loam":        {"alpha_cm": 0.036, "n": 1.56,  "theta_r": 0.078, "theta_s": 0.43, "ksat_cm_day": 24.96},
    "silt":        {"alpha_cm": 0.016, "n": 1.37,  "theta_r": 0.034, "theta_s": 0.46, "ksat_cm_day": 6.00},
    "silt loam":   {"alpha_cm": 0.020, "n": 1.41,  "theta_r": 0.067, "theta_s": 0.45, "ksat_cm_day": 10.80},
    "sandy clay loam": {"alpha_cm": 0.059, "n": 1.48, "theta_r": 0.100, "theta_s": 0.39, "ksat_cm_day": 31.44},
    "clay loam":   {"alpha_cm": 0.019, "n": 1.31,  "theta_r": 0.095, "theta_s": 0.41, "ksat_cm_day": 6.24},
    "silty clay loam": {"alpha_cm": 0.010, "n": 1.23, "theta_r": 0.089, "theta_s": 0.43, "ksat_cm_day": 1.68},
    "sandy clay":  {"alpha_cm": 0.027, "n": 1.23,  "theta_r": 0.100, "theta_s": 0.38, "ksat_cm_day": 2.88},
    "silty clay":  {"alpha_cm": 0.005, "n": 1.09,  "theta_r": 0.070, "theta_s": 0.36, "ksat_cm_day": 0.48},
    "clay":        {"alpha_cm": 0.008, "n": 1.09,  "theta_r": 0.068, "theta_s": 0.38, "ksat_cm_day": 4.80},
}


# ============================================================================
# Validation
# ============================================================================
def validate_inputs(args):
    """Validate input arguments before processing."""
    errors = []

    if args.texture and args.texture.lower() not in VG_BY_TEXTURE:
        errors.append(
            f"Unknown texture class: '{args.texture}'. "
            f"Valid: {list(VG_BY_TEXTURE.keys())}"
        )

    if args.ksat_cm_day is not None and args.ksat_cm_day <= 0:
        errors.append(f"K_sat must be positive: {args.ksat_cm_day} cm/day")

    if args.porosity is not None:
        if args.porosity <= 0 or args.porosity >= 1:
            errors.append(f"Porosity must be 0 < φ < 1: {args.porosity}")

    if args.residual_sat is not None:
        if args.residual_sat < 0 or args.residual_sat >= 1:
            errors.append(f"Residual saturation must be 0 ≤ S_r < 1: {args.residual_sat}")

    if args.alpha_cm is not None and args.alpha_cm <= 0:
        errors.append(f"van Genuchten α must be positive: {args.alpha_cm} 1/cm")

    if args.vg_n is not None:
        if args.vg_n <= 1.0:
            errors.append(f"van Genuchten n must be > 1.0: {args.vg_n}")

    if errors:
        for e in errors:
            print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)

    print("[OK] Input validation passed.")


def validate_outputs(result):
    """Validate output values are physically reasonable."""
    warnings = []

    perm = result.get("permeability_m2", 0)
    if perm > 1e-9:
        warnings.append(
            f"Permeability {perm:.2e} m² is very high (gravel/fractured rock). "
            f"Check K_sat input units — expected cm/day."
        )
    if perm < 1e-18:
        warnings.append(
            f"Permeability {perm:.2e} m² is extremely low (impermeable). "
            f"May cause very slow simulation convergence."
        )

    alpha_pa = result.get("alpha_Pa", 0)
    if alpha_pa > 1e-2:
        warnings.append(
            f"van Genuchten α = {alpha_pa:.2e} 1/Pa is very high. "
            f"Did you convert from 1/cm? α_Pa = α_cm / 980665."
        )

    for w in warnings:
        print(f"[WARNING] {w}", file=sys.stderr)

    if not warnings:
        print("[OK] Output validation passed.")

    return len(warnings) == 0


# ============================================================================
# Converters
# ============================================================================
def ksat_cm_day_to_permeability_m2(ksat_cm_day):
    """Convert saturated hydraulic conductivity (cm/day) to intrinsic permeability (m²).

    k = K * μ / (ρ * g)
    K [m/s] = K [cm/day] / 100 / 86400
    k [m²] = K [m/s] * μ [Pa·s] / (ρ [kg/m³] * g [m/s²])
    """
    ksat_m_s = ksat_cm_day / 100.0 / 86400.0
    permeability = ksat_m_s * WATER_VISCOSITY / (WATER_DENSITY * GRAVITY)
    return permeability


def alpha_cm_to_pa(alpha_cm):
    """Convert van Genuchten α from 1/cm to 1/Pa.

    α [1/Pa] = α [1/cm] / (ρ * g * 100)
    The factor 100 converts cm to m: α[1/m] = α[1/cm] * 100
    Then α[1/Pa] = α[1/m] / (ρ*g)
    """
    alpha_per_m = alpha_cm * 100.0  # 1/cm → 1/m
    alpha_per_pa = alpha_per_m / (WATER_DENSITY * GRAVITY)
    return alpha_per_pa


def kd_ml_g_to_m3_kg(kd_ml_g):
    """Convert sorption Kd from mL/g to m³/kg.

    1 mL = 1e-6 m³, 1 g = 1e-3 kg
    Kd [m³/kg] = Kd [mL/g] * 1e-6 / 1e-3 = Kd * 1e-3
    """
    return kd_ml_g * 1e-3


def dispersivity_cm_to_m(disp_cm):
    """Convert dispersivity from cm to m."""
    return disp_cm / 100.0


# ============================================================================
# Processing
# ============================================================================
def process_texture(args):
    """Convert texture class to full Amanzi parameter set."""
    texture = args.texture.lower()
    base = VG_BY_TEXTURE[texture]

    # Allow overrides
    ksat = args.ksat_cm_day if args.ksat_cm_day is not None else base["ksat_cm_day"]
    porosity = args.porosity if args.porosity is not None else base["theta_s"]
    theta_r = args.residual_sat if args.residual_sat is not None else base["theta_r"]
    alpha_cm = args.alpha_cm if args.alpha_cm is not None else base["alpha_cm"]
    vg_n = args.vg_n if args.vg_n is not None else base["n"]

    # Convert to Amanzi units
    perm_m2 = ksat_cm_day_to_permeability_m2(ksat)
    alpha_pa = alpha_cm_to_pa(alpha_cm)
    vg_m = 1.0 - 1.0 / vg_n  # van Genuchten m = 1 - 1/n

    result = {
        "texture_class": texture,
        "source": "Carsel_Parrish_1988",
        # Input values
        "ksat_cm_day": ksat,
        "ksat_m_s": ksat / 100.0 / 86400.0,
        "alpha_cm": alpha_cm,
        "vg_n": vg_n,
        "theta_r": theta_r,
        "theta_s": porosity,
        # Amanzi-unit values
        "permeability_m2": perm_m2,
        "alpha_Pa": alpha_pa,
        "vg_m": vg_m,
        "porosity": porosity,
        "residual_saturation": theta_r / porosity,  # Amanzi uses S_r, not θ_r
        # XML snippet
        "amanzi_xml": {
            "material_name": f"Soil_{texture.replace(' ', '_')}",
            "porosity": porosity,
            "permeability_x": perm_m2,
            "permeability_y": perm_m2,
            "permeability_z": perm_m2,
            "capillary_pressure_model": "van Genuchten",
            "alpha": alpha_pa,
            "sr": theta_r / porosity,
            "m": vg_m,
        },
        # Unit conversion log
        "unit_conversions_applied": [
            f"K_sat: {ksat} cm/day → {ksat / 100 / 86400:.6e} m/s → {perm_m2:.6e} m² (intrinsic perm)",
            f"α: {alpha_cm} 1/cm → {alpha_cm * 100:.2f} 1/m → {alpha_pa:.6e} 1/Pa",
            f"θ_r: {theta_r} → S_r = {theta_r / porosity:.4f} (residual saturation)",
            f"n: {vg_n} → m = 1 - 1/n = {vg_m:.4f}",
        ],
    }

    # Add Kd conversion if provided
    if args.kd_ml_g is not None:
        kd_m3_kg = kd_ml_g_to_m3_kg(args.kd_ml_g)
        result["kd_mL_g"] = args.kd_ml_g
        result["kd_m3_kg"] = kd_m3_kg
        result["unit_conversions_applied"].append(
            f"Kd: {args.kd_ml_g} mL/g → {kd_m3_kg:.6e} m³/kg"
        )

    return result


# ============================================================================
# Main
# ============================================================================
def main():
    parser = argparse.ArgumentParser(
        description="Convert soil properties to Amanzi material parameters"
    )
    parser.add_argument("--texture", type=str,
                        help="USDA texture class (e.g., 'sandy loam', 'clay')")
    parser.add_argument("--ksat_cm_day", type=float,
                        help="Saturated hydraulic conductivity (cm/day)")
    parser.add_argument("--porosity", type=float,
                        help="Total porosity (0-1)")
    parser.add_argument("--residual_sat", type=float,
                        help="Residual water content θ_r (0-1)")
    parser.add_argument("--alpha_cm", type=float,
                        help="van Genuchten α (1/cm)")
    parser.add_argument("--vg_n", type=float,
                        help="van Genuchten n (>1)")
    parser.add_argument("--kd_ml_g", type=float,
                        help="Sorption distribution coefficient Kd (mL/g)")
    parser.add_argument("--output", type=str, required=True,
                        help="Output JSON file path")
    args = parser.parse_args()

    if not args.texture and not args.ksat_cm_day:
        print("[ERROR] Must specify --texture or individual parameters", file=sys.stderr)
        sys.exit(1)

    # Validate
    validate_inputs(args)

    # Process
    result = process_texture(args)

    # Validate outputs
    validate_outputs(result)

    # Write
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(result, f, indent=2)

    print(f"[OK] Wrote soil parameters to {args.output}")
    print(f"     Permeability: {result['permeability_m2']:.4e} m²")
    print(f"     α (vG): {result['alpha_Pa']:.4e} 1/Pa")
    print(f"     n (vG): {result['vg_n']:.2f}")
    print(f"     Porosity: {result['porosity']:.3f}")


if __name__ == "__main__":
    main()
