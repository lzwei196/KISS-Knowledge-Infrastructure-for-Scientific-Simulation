#!/usr/bin/env python3
"""Convert rock and fluid material properties to PorePy SolidConstants / FluidComponent format.

This tool maps external data sources (HWSD soil database, literature values, lab
measurements) to PorePy's material constant dictionaries.

CRITICAL UNIT REQUIREMENTS (all SI):
- Permeability: m² (NOT Darcy; 1 Darcy = 9.869e-13 m²)
- Young's modulus / Lame parameters: Pa (NOT GPa; multiply by 1e9)
- Viscosity: Pa·s (NOT cP; 1 cP = 1e-3 Pa·s)
- Density: kg/m³ (NOT g/cm³; multiply by 1000)
- Porosity: fraction 0–1 (NOT percentage)
- Specific storage: 1/Pa (NOT 1/m; divide by ρg ≈ 9810)

Usage:
    python convert_material_params.py --input rock_data.json --output porepy_materials.json
    python convert_material_params.py --from-hwsd --lat 32.5 --lon 117.2 \\
        --output porepy_materials.json
"""

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional, Tuple


# ─────────────────────────────────────────────────────────────
# Default PorePy material values (SI units) — from source code
# ─────────────────────────────────────────────────────────────
DEFAULT_GRANITE = {
    "name": "granite",
    "biot_coefficient": 0.47,
    "density": 2683.0,           # kg/m³
    "friction_coefficient": 0.6,
    "lame_lambda": 7.021e9,      # Pa
    "permeability": 5.0e-18,     # m²
    "porosity": 0.013,
    "shear_modulus": 1.485e10,   # Pa
    "specific_heat_capacity": 790.0,  # J/(kg·K)
    "thermal_conductivity": 2.5,      # W/(m·K)
    "thermal_expansion": 7.5e-6,      # 1/K
    "specific_storage": 4.74e-10,     # 1/Pa
}

DEFAULT_WATER = {
    "name": "water",
    "compressibility": 4.559e-10,  # 1/Pa
    "density": 998.2,              # kg/m³
    "specific_heat_capacity": 4182.0,  # J/(kg·K)
    "thermal_conductivity": 0.5975,    # W/(m·K)
    "thermal_expansion": 2.068e-4,     # 1/K
    "viscosity": 1.002e-3,            # Pa·s
}

# Common rock types with typical ranges
ROCK_LIBRARY = {
    "granite": DEFAULT_GRANITE,
    "sandstone": {
        "name": "sandstone",
        "biot_coefficient": 0.79,
        "density": 2300.0,
        "friction_coefficient": 0.5,
        "lame_lambda": 4.0e9,
        "permeability": 1.0e-14,
        "porosity": 0.15,
        "shear_modulus": 6.0e9,
        "specific_heat_capacity": 920.0,
        "thermal_conductivity": 2.3,
        "thermal_expansion": 1.1e-5,
        "specific_storage": 1.0e-8,
    },
    "shale": {
        "name": "shale",
        "biot_coefficient": 0.85,
        "density": 2500.0,
        "friction_coefficient": 0.3,
        "lame_lambda": 8.0e9,
        "permeability": 1.0e-20,
        "porosity": 0.05,
        "shear_modulus": 5.0e9,
        "specific_heat_capacity": 800.0,
        "thermal_conductivity": 1.5,
        "thermal_expansion": 1.0e-5,
        "specific_storage": 5.0e-10,
    },
    "limestone": {
        "name": "limestone",
        "biot_coefficient": 0.70,
        "density": 2600.0,
        "friction_coefficient": 0.55,
        "lame_lambda": 1.5e10,
        "permeability": 1.0e-16,
        "porosity": 0.10,
        "shear_modulus": 1.2e10,
        "specific_heat_capacity": 840.0,
        "thermal_conductivity": 2.8,
        "thermal_expansion": 8.0e-6,
        "specific_storage": 3.0e-9,
    },
}

# Unit conversion maps for material properties
PROPERTY_CONVERSIONS = {
    "permeability": {
        "m2": 1.0,
        "darcy": 9.869e-13,
        "millidarcy": 9.869e-16,
    },
    "density": {
        "kg/m3": 1.0,
        "g/cm3": 1000.0,
    },
    "viscosity": {
        "Pa.s": 1.0,
        "Pa*s": 1.0,
        "cP": 1.0e-3,
        "mPa.s": 1.0e-3,
    },
    "modulus": {  # For lame_lambda, shear_modulus, bulk_modulus
        "Pa": 1.0,
        "kPa": 1.0e3,
        "MPa": 1.0e6,
        "GPa": 1.0e9,
    },
    "thermal_conductivity": {
        "W/(m*K)": 1.0,
        "cal/(cm*s*C)": 418.68,
    },
    "specific_storage": {
        "1/Pa": 1.0,
        "1/m": 1.0 / 9810.0,  # Divide by ρ_water * g
    },
}


def validate_inputs(args: argparse.Namespace) -> List[str]:
    """Validate input arguments."""
    errors = []

    if args.input and not os.path.isfile(args.input):
        errors.append(f"Input file not found: {args.input}")

    if args.rock_type and args.rock_type not in ROCK_LIBRARY:
        errors.append(
            f"Unknown rock type '{args.rock_type}'. "
            f"Valid: {list(ROCK_LIBRARY.keys())}"
        )

    return errors


def convert_property(value: float, prop_name: str, from_unit: str) -> Tuple[float, str]:
    """Convert a single material property to SI units.

    Returns:
        Tuple of (converted_value, conversion_note).
    """
    # Find the right conversion category
    category = None
    if prop_name in ("permeability",):
        category = "permeability"
    elif prop_name in ("density",):
        category = "density"
    elif prop_name in ("viscosity",):
        category = "viscosity"
    elif prop_name in ("lame_lambda", "shear_modulus", "bulk_modulus", "youngs_modulus"):
        category = "modulus"
    elif prop_name in ("thermal_conductivity",):
        category = "thermal_conductivity"
    elif prop_name in ("specific_storage",):
        category = "specific_storage"
    else:
        return value, f"No conversion applied (assumed SI)"

    conversions = PROPERTY_CONVERSIONS.get(category, {})
    if from_unit not in conversions:
        return value, f"Unknown unit '{from_unit}' for {category}, no conversion applied"

    factor = conversions[from_unit]
    converted = value * factor
    note = f"{value} {from_unit} → {converted:.6e} SI (×{factor})"
    return converted, note


def process_input_file(filepath: str) -> Dict[str, Any]:
    """Read and parse input material data file.

    Expected JSON format:
    {
        "solid": {
            "permeability": {"value": 1.0, "unit": "darcy"},
            "density": {"value": 2.65, "unit": "g/cm3"},
            ...
        },
        "fluid": {
            "viscosity": {"value": 1.0, "unit": "cP"},
            ...
        }
    }
    """
    with open(filepath, "r") as f:
        data = json.load(f)
    return data


def process(
    input_data: Optional[Dict] = None,
    rock_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Convert material properties to PorePy format.

    Returns:
        Dictionary with solid and fluid material constants in SI.
    """
    result = {
        "solid": {},
        "fluid": {},
        "conversions": [],
        "warnings": [],
    }

    # Start with defaults if rock type specified
    if rock_type:
        result["solid"] = ROCK_LIBRARY[rock_type].copy()
        result["fluid"] = DEFAULT_WATER.copy()
        result["conversions"].append(f"Base: {rock_type} defaults from PorePy library")

    # Override with input data if provided
    if input_data:
        for category in ("solid", "fluid"):
            if category not in input_data:
                continue
            for prop_name, spec in input_data[category].items():
                if isinstance(spec, dict) and "value" in spec:
                    value = float(spec["value"])
                    unit = spec.get("unit", "SI")
                    converted, note = convert_property(value, prop_name, unit)
                    result[category][prop_name] = converted
                    result["conversions"].append(note)
                else:
                    result[category][prop_name] = float(spec)

    # Fill missing values with defaults
    if not result["solid"]:
        result["solid"] = DEFAULT_GRANITE.copy()
        result["conversions"].append("Using default granite values (no input provided)")
    if not result["fluid"]:
        result["fluid"] = DEFAULT_WATER.copy()
        result["conversions"].append("Using default water values (no input provided)")

    return result


def validate_outputs(result: Dict[str, Any]) -> List[str]:
    """Validate material properties for physical reasonableness."""
    warnings = []
    solid = result["solid"]
    fluid = result["fluid"]

    # Solid checks
    if "porosity" in solid:
        phi = solid["porosity"]
        if phi > 1.0:
            warnings.append(
                f"CRITICAL: Porosity = {phi}. If > 1, likely in percentage. "
                f"PorePy expects fraction (0–1). Divide by 100."
            )
        if phi < 0 or phi > 1.0:
            warnings.append(f"WARNING: Porosity {phi} outside physical range [0, 1].")

    if "biot_coefficient" in solid:
        alpha = solid["biot_coefficient"]
        if alpha > 1.0 or alpha < 0:
            warnings.append(
                f"CRITICAL: Biot coefficient = {alpha}. Must be in (0, 1]. "
                f"Values > 1 cause negative effective stress."
            )

    if "permeability" in solid:
        k = solid["permeability"]
        if k > 1e-8:
            warnings.append(
                f"CRITICAL: Permeability = {k:.2e} m². Extremely high. "
                f"If in Darcy, multiply by 9.869e-13."
            )
        if k < 1e-25:
            warnings.append(
                f"WARNING: Permeability = {k:.2e} m². Extremely low — "
                f"flow will be negligible."
            )

    if "density" in solid:
        rho = solid["density"]
        if rho < 100:
            warnings.append(
                f"CRITICAL: Solid density = {rho} kg/m³. Likely in g/cm³. "
                f"Multiply by 1000."
            )

    # Fluid checks
    if "viscosity" in fluid:
        mu = fluid["viscosity"]
        if mu > 1.0:
            warnings.append(
                f"CRITICAL: Viscosity = {mu} Pa·s. Likely in cP. "
                f"Divide by 1000."
            )
        if mu < 1e-6:
            warnings.append(
                f"WARNING: Viscosity = {mu:.2e} Pa·s. Very low for typical fluids."
            )

    if "density" in fluid:
        rho_f = fluid["density"]
        if rho_f < 10:
            warnings.append(
                f"CRITICAL: Fluid density = {rho_f} kg/m³. Likely in g/cm³. "
                f"Multiply by 1000."
            )

    return warnings


def main():
    parser = argparse.ArgumentParser(
        description="Convert material properties to PorePy SI format.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--input", help="Input JSON file with material properties")
    parser.add_argument("--output", required=True, help="Output JSON file path")
    parser.add_argument(
        "--rock-type", choices=list(ROCK_LIBRARY.keys()),
        help="Use preset rock type as base"
    )
    args = parser.parse_args()

    # Step 1: Validate inputs
    errors = validate_inputs(args)
    if errors:
        print(json.dumps({"status": "error", "errors": errors}, indent=2))
        sys.exit(1)

    # Step 2: Process
    input_data = None
    if args.input:
        input_data = process_input_file(args.input)

    result = process(input_data=input_data, rock_type=args.rock_type)

    # Step 3: Validate outputs
    warnings = validate_outputs(result)
    result["warnings"] = warnings
    result["status"] = "success" if not any("CRITICAL" in w for w in warnings) else "warning"

    # Write output
    with open(args.output, "w") as f:
        json.dump(result, f, indent=2)

    print(json.dumps({
        "status": result["status"],
        "output_file": args.output,
        "rock_type": result["solid"].get("name", "custom"),
        "warnings": warnings,
    }, indent=2))


if __name__ == "__main__":
    main()
