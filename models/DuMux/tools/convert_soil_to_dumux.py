#!/usr/bin/env python3
"""
convert_soil_to_dumux.py — Convert soil/aquifer data to DuMux spatial parameters.

Pipeline stage: s3 (Soil/Aquifer Parameters)
Pattern: validate → process → validate

Converts soil databases (HWSD, ROSETTA, field measurements) into DuMux-compatible
spatial parameters: intrinsic permeability, porosity, van Genuchten parameters.

Key unit conversions:
  - Hydraulic conductivity K_h [m/s or cm/day] → intrinsic permeability K [m²]
  - van Genuchten α [1/cm H₂O] → α [1/Pa]
  - Porosity [%] → [-] fraction

Usage:
    python convert_soil_to_dumux.py \\
        --input soil_data.csv \\
        --output params.json \\
        --source hwsd
"""

import argparse
import json
import os
import sys
import csv
from pathlib import Path

import numpy as np

# ─── Physical Constants ──────────────────────────────────────────────────────
RHO_WATER = 1000.0    # kg/m³
GRAVITY = 9.81         # m/s²
MU_WATER = 1.002e-3    # Pa·s (dynamic viscosity at 20°C)
CM_WATER_TO_PA = 98.0665  # 1 cm H₂O = 98.0665 Pa

# Conversion: 1 darcy = 9.869233e-13 m²
DARCY_TO_M2 = 9.869233e-13

# ─── USDA Soil Texture Classes (ROSETTA-based defaults) ─────────────────────
# Source: Schaap et al. (2001), ROSETTA pedotransfer functions
# K_h in cm/day, α in 1/cm, n dimensionless, θ_r and θ_s as fractions

SOIL_TEXTURE_DEFAULTS = {
    "sand": {
        "K_h_cm_day": 712.8, "alpha_1_cm": 0.145, "n": 2.68,
        "theta_r": 0.045, "theta_s": 0.43, "porosity": 0.43
    },
    "loamy_sand": {
        "K_h_cm_day": 350.2, "alpha_1_cm": 0.124, "n": 2.28,
        "theta_r": 0.057, "theta_s": 0.41, "porosity": 0.41
    },
    "sandy_loam": {
        "K_h_cm_day": 106.1, "alpha_1_cm": 0.075, "n": 1.89,
        "theta_r": 0.065, "theta_s": 0.41, "porosity": 0.41
    },
    "loam": {
        "K_h_cm_day": 24.96, "alpha_1_cm": 0.036, "n": 1.56,
        "theta_r": 0.078, "theta_s": 0.43, "porosity": 0.43
    },
    "silt_loam": {
        "K_h_cm_day": 10.80, "alpha_1_cm": 0.020, "n": 1.41,
        "theta_r": 0.067, "theta_s": 0.45, "porosity": 0.45
    },
    "silt": {
        "K_h_cm_day": 6.00, "alpha_1_cm": 0.016, "n": 1.37,
        "theta_r": 0.034, "theta_s": 0.46, "porosity": 0.46
    },
    "sandy_clay_loam": {
        "K_h_cm_day": 31.44, "alpha_1_cm": 0.059, "n": 1.48,
        "theta_r": 0.100, "theta_s": 0.39, "porosity": 0.39
    },
    "clay_loam": {
        "K_h_cm_day": 6.24, "alpha_1_cm": 0.019, "n": 1.31,
        "theta_r": 0.095, "theta_s": 0.41, "porosity": 0.41
    },
    "silty_clay_loam": {
        "K_h_cm_day": 1.68, "alpha_1_cm": 0.010, "n": 1.23,
        "theta_r": 0.089, "theta_s": 0.43, "porosity": 0.43
    },
    "sandy_clay": {
        "K_h_cm_day": 2.88, "alpha_1_cm": 0.027, "n": 1.23,
        "theta_r": 0.100, "theta_s": 0.38, "porosity": 0.38
    },
    "silty_clay": {
        "K_h_cm_day": 0.48, "alpha_1_cm": 0.005, "n": 1.09,
        "theta_r": 0.070, "theta_s": 0.36, "porosity": 0.36
    },
    "clay": {
        "K_h_cm_day": 4.80, "alpha_1_cm": 0.008, "n": 1.09,
        "theta_r": 0.068, "theta_s": 0.38, "porosity": 0.38
    },
    # Aquifer materials
    "gravel": {
        "K_h_cm_day": 86400.0, "alpha_1_cm": 0.5, "n": 3.0,
        "theta_r": 0.01, "theta_s": 0.30, "porosity": 0.30
    },
    "fractured_rock": {
        "K_h_cm_day": 0.864, "alpha_1_cm": 0.001, "n": 1.5,
        "theta_r": 0.01, "theta_s": 0.05, "porosity": 0.05
    },
}


# ─── Unit Conversion Functions ───────────────────────────────────────────────

def kh_to_permeability(k_h: float, unit: str = "m_per_s") -> float:
    """Convert hydraulic conductivity to intrinsic permeability [m²].

    CRITICAL TRAP: DuMux uses intrinsic permeability (m²), NOT hydraulic conductivity.
    K [m²] = K_h [m/s] × μ / (ρ × g)

    Args:
        k_h: Hydraulic conductivity value
        unit: Unit of input ('m_per_s', 'cm_per_day', 'darcy')

    Returns:
        Intrinsic permeability in m²
    """
    # Convert to m/s first
    if unit == "m_per_s":
        k_h_ms = k_h
    elif unit == "cm_per_day":
        k_h_ms = k_h / (100.0 * 86400.0)  # cm/day → m/s
    elif unit == "cm_per_s":
        k_h_ms = k_h / 100.0
    elif unit == "darcy":
        return k_h * DARCY_TO_M2  # Direct conversion
    elif unit == "m_per_day":
        k_h_ms = k_h / 86400.0
    else:
        raise ValueError(f"Unknown K_h unit: {unit}. Use m_per_s, cm_per_day, darcy")

    # Convert K_h [m/s] to K [m²]
    perm = k_h_ms * MU_WATER / (RHO_WATER * GRAVITY)
    return perm


def alpha_to_pa(alpha_cm: float) -> float:
    """Convert van Genuchten α from 1/cm H₂O to 1/Pa.

    CRITICAL TRAP: DuMux uses α in 1/Pa, soil databases give 1/cm H₂O.
    α [1/Pa] = α [1/cm] / (ρ·g/100) = α [1/cm] / 98.0665

    Args:
        alpha_cm: van Genuchten α in 1/cm water head

    Returns:
        α in 1/Pa
    """
    return alpha_cm / CM_WATER_TO_PA


def porosity_to_fraction(porosity_value: float, unit: str = "fraction") -> float:
    """Convert porosity to fraction (0-1).

    Args:
        porosity_value: Porosity value
        unit: 'fraction' (0-1) or 'percent' (0-100)

    Returns:
        Porosity as fraction (0-1)
    """
    if unit == "percent":
        return porosity_value / 100.0
    return porosity_value


# ─── Validation ──────────────────────────────────────────────────────────────

def validate_inputs(input_path: str, source: str) -> dict:
    """Validate input soil data."""
    result = {"valid": True, "errors": [], "warnings": [], "metadata": {}}

    if source == "texture" and input_path == "":
        # Texture-based lookup, no file needed
        return result

    if not os.path.isfile(input_path):
        result["valid"] = False
        result["errors"].append(f"Input file not found: {input_path}")
        return result

    # Try reading as CSV or JSON
    ext = os.path.splitext(input_path)[1].lower()
    if ext == ".json":
        try:
            with open(input_path) as f:
                data = json.load(f)
            result["metadata"]["format"] = "json"
            result["metadata"]["keys"] = list(data.keys()) if isinstance(data, dict) else "list"
        except json.JSONDecodeError as e:
            result["valid"] = False
            result["errors"].append(f"Invalid JSON: {e}")
    elif ext == ".csv":
        try:
            with open(input_path) as f:
                reader = csv.DictReader(f)
                headers = reader.fieldnames
                rows = list(reader)
            result["metadata"]["format"] = "csv"
            result["metadata"]["columns"] = headers
            result["metadata"]["n_rows"] = len(rows)
        except Exception as e:
            result["valid"] = False
            result["errors"].append(f"Failed to read CSV: {e}")
    else:
        result["warnings"].append(f"Unrecognized extension {ext}, trying as CSV")

    return result


def validate_params(params: dict) -> dict:
    """Validate computed DuMux parameters are physically reasonable."""
    result = {"valid": True, "errors": [], "warnings": []}

    perm = params.get("permeability_m2", 0)
    porosity = params.get("porosity", 0)
    alpha = params.get("vanGenuchten_alpha_1_Pa", None)
    n_vg = params.get("vanGenuchten_n", None)

    # Permeability bounds
    if perm <= 0:
        result["valid"] = False
        result["errors"].append(f"Permeability must be positive, got {perm}")
    elif perm > 1e-7:
        result["warnings"].append(
            f"Permeability {perm:.2e} m² is extremely high (>1e-7). "
            "This is typical only for clean gravel. Check units."
        )
    elif perm < 1e-20:
        result["warnings"].append(
            f"Permeability {perm:.2e} m² is extremely low (<1e-20). "
            "This is near-impermeable. Check units — did you forget to convert from m/s?"
        )

    # Porosity bounds
    if porosity <= 0 or porosity >= 1:
        result["valid"] = False
        result["errors"].append(f"Porosity must be 0-1, got {porosity}")
    if porosity > 0.6:
        result["warnings"].append(
            f"Porosity {porosity} is unusually high (>0.6). "
            "Typical range: 0.05-0.50."
        )

    # van Genuchten α
    if alpha is not None:
        if alpha <= 0:
            result["valid"] = False
            result["errors"].append(f"vG α must be positive, got {alpha}")
        elif alpha > 0.1:
            result["warnings"].append(
                f"vG α = {alpha:.4e} 1/Pa is very high. "
                "Did you forget to convert from 1/cm? Divide by 98.07."
            )

    # van Genuchten n
    if n_vg is not None:
        if n_vg <= 1:
            result["valid"] = False
            result["errors"].append(f"vG n must be > 1, got {n_vg}")
        if n_vg > 10:
            result["warnings"].append(f"vG n = {n_vg} is very high (>10). Typical: 1.1-5.0")

    return result


# ─── Processing ──────────────────────────────────────────────────────────────

def process_from_texture(texture: str) -> dict:
    """Get DuMux parameters from USDA soil texture class."""
    texture_key = texture.lower().replace(" ", "_").replace("-", "_")
    if texture_key not in SOIL_TEXTURE_DEFAULTS:
        available = ", ".join(sorted(SOIL_TEXTURE_DEFAULTS.keys()))
        raise ValueError(
            f"Unknown texture '{texture}'. Available: {available}"
        )

    soil = SOIL_TEXTURE_DEFAULTS[texture_key]

    # Convert to DuMux units
    perm = kh_to_permeability(soil["K_h_cm_day"], unit="cm_per_day")
    alpha_pa = alpha_to_pa(soil["alpha_1_cm"])

    return {
        "source_texture": texture,
        "permeability_m2": perm,
        "porosity": soil["porosity"],
        "vanGenuchten_alpha_1_Pa": alpha_pa,
        "vanGenuchten_n": soil["n"],
        "residual_saturation": soil["theta_r"] / soil["theta_s"],
        "theta_r": soil["theta_r"],
        "theta_s": soil["theta_s"],
        # Include original units for traceability
        "_original_K_h_cm_day": soil["K_h_cm_day"],
        "_original_alpha_1_cm": soil["alpha_1_cm"],
    }


def process_from_csv(input_path: str, kh_unit: str = "m_per_s") -> list:
    """Process soil CSV with columns: zone, K_h, porosity, alpha, n."""
    results = []
    with open(input_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            params = {}
            # Zone identifier
            params["zone"] = row.get("zone", row.get("id", "unknown"))

            # Hydraulic conductivity → permeability
            kh_val = float(row.get("K_h", row.get("kh", row.get("hydraulic_conductivity", 0))))
            params["permeability_m2"] = kh_to_permeability(kh_val, unit=kh_unit)

            # Porosity
            por_val = float(row.get("porosity", row.get("phi", 0.3)))
            por_unit = "percent" if por_val > 1 else "fraction"
            params["porosity"] = porosity_to_fraction(por_val, por_unit)

            # van Genuchten parameters (if present)
            if "alpha" in row or "alpha_cm" in row:
                alpha_val = float(row.get("alpha", row.get("alpha_cm", 0)))
                params["vanGenuchten_alpha_1_Pa"] = alpha_to_pa(alpha_val)
                params["_original_alpha_1_cm"] = alpha_val

            if "n" in row or "vg_n" in row:
                params["vanGenuchten_n"] = float(row.get("n", row.get("vg_n", 2.0)))

            results.append(params)
    return results


def generate_input_snippet(params: dict, section: str = "SpatialParams") -> str:
    """Generate DuMux .input file snippet for spatial parameters.

    Args:
        params: Parameter dictionary from processing
        section: INI section name

    Returns:
        String snippet for .input file
    """
    lines = [f"[{section}]"]
    lines.append(f"Permeability = {params['permeability_m2']:.6e}  # [m²]")
    lines.append(f"Porosity = {params['porosity']:.4f}  # [-]")

    if "vanGenuchten_alpha_1_Pa" in params:
        lines.append(
            f"VanGenuchtenAlpha = {params['vanGenuchten_alpha_1_Pa']:.6e}  "
            f"# [1/Pa] (from {params.get('_original_alpha_1_cm', '?')} 1/cm)"
        )
    if "vanGenuchten_n" in params:
        lines.append(f"VanGenuchtenN = {params['vanGenuchten_n']:.4f}  # [-]")
    if "residual_saturation" in params:
        lines.append(f"Swr = {params['residual_saturation']:.4f}  # [-]")

    return "\n".join(lines)


def process(
    input_path: str,
    output_path: str,
    source: str = "hwsd",
    texture: str = "",
    kh_unit: str = "m_per_s",
) -> dict:
    """Main pipeline: validate → process → validate."""
    summary = {"status": "failed"}

    # ── Validate inputs ──
    print("=== Validating inputs ===")
    input_val = validate_inputs(input_path, source)
    for w in input_val["warnings"]:
        print(f"  WARNING: {w}")
    if not input_val["valid"]:
        for e in input_val["errors"]:
            print(f"  ERROR: {e}")
        summary["errors"] = input_val["errors"]
        return summary

    # ── Process ──
    print("=== Processing ===")
    if source == "texture":
        params_list = [process_from_texture(texture)]
    elif source in ("hwsd", "csv"):
        params_list = process_from_csv(input_path, kh_unit=kh_unit)
    else:
        print(f"  ERROR: Unknown source '{source}'")
        summary["errors"] = [f"Unknown source: {source}"]
        return summary

    print(f"  Processed {len(params_list)} soil zone(s)")

    # ── Validate outputs ──
    print("=== Validating outputs ===")
    all_valid = True
    for i, params in enumerate(params_list):
        pval = validate_params(params)
        for w in pval["warnings"]:
            print(f"  Zone {i} WARNING: {w}")
        if not pval["valid"]:
            for e in pval["errors"]:
                print(f"  Zone {i} ERROR: {e}")
            all_valid = False

    if not all_valid:
        summary["errors"] = ["One or more zones have invalid parameters"]
        return summary

    # ── Write output ──
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    output = {
        "source": source,
        "n_zones": len(params_list),
        "zones": params_list,
        "input_snippets": [generate_input_snippet(p) for p in params_list],
    }

    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"  Written to: {output_path}")

    # Print summary
    for i, p in enumerate(params_list):
        print(f"\n  Zone {i}: {p.get('zone', p.get('source_texture', '?'))}")
        print(f"    Permeability: {p['permeability_m2']:.4e} m²")
        print(f"    Porosity:     {p['porosity']:.4f}")
        if "vanGenuchten_alpha_1_Pa" in p:
            print(f"    vG α:         {p['vanGenuchten_alpha_1_Pa']:.4e} 1/Pa")
        if "vanGenuchten_n" in p:
            print(f"    vG n:         {p['vanGenuchten_n']:.4f}")

    summary["status"] = "success"
    summary["n_zones"] = len(params_list)
    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Convert soil/aquifer data to DuMux spatial parameters"
    )
    parser.add_argument("--input", default="", help="Input CSV/JSON with soil data")
    parser.add_argument("--output", required=True, help="Output JSON with DuMux parameters")
    parser.add_argument(
        "--source", default="hwsd",
        choices=["hwsd", "csv", "texture"],
        help="Data source type"
    )
    parser.add_argument(
        "--texture", default="",
        help="USDA texture class (for --source texture)"
    )
    parser.add_argument(
        "--kh_unit", default="m_per_s",
        choices=["m_per_s", "cm_per_day", "cm_per_s", "darcy", "m_per_day"],
        help="Unit of hydraulic conductivity in input"
    )
    args = parser.parse_args()

    result = process(
        input_path=args.input,
        output_path=args.output,
        source=args.source,
        texture=args.texture,
        kh_unit=args.kh_unit,
    )

    if result["status"] != "success":
        print(f"\nFAILED: {result.get('errors', [])}")
        sys.exit(1)
    else:
        print(f"\nSUCCESS: {result['n_zones']} zone(s) processed")


if __name__ == "__main__":
    main()
