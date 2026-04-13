#!/usr/bin/env python3
"""
Create SWMM LID (Low Impact Development) control definitions.

Defines LID controls with layered parameters for green infrastructure
modeling. Supports all SWMM LID types:
  - BC: Bio-Retention Cell
  - RG: Rain Garden
  - GR: Green Roof
  - IT: Infiltration Trench
  - PP: Permeable Pavement
  - RB: Rain Barrel
  - VS: Vegetative Swale

Each LID type requires specific layers (surface, soil, storage, drain,
drainmat). This tool validates parameter consistency (e.g., WP < FC < porosity).

Inputs:
  - LID type and name
  - Layer parameters as key=value strings
  - Output JSON path

Outputs:
  - JSON file with LID control definition
"""

import argparse
import json
import os
import sys
from pathlib import Path

# LID type definitions: which layers are required and optional
LID_TYPE_LAYERS = {
    "BC": {"required": ["surface", "soil", "storage", "drain"], "optional": [],
            "desc": "Bio-Retention Cell"},
    "RG": {"required": ["surface", "soil"], "optional": ["drain"],
            "desc": "Rain Garden"},
    "GR": {"required": ["surface", "soil", "drainmat"], "optional": ["drain"],
            "desc": "Green Roof"},
    "IT": {"required": ["surface", "storage", "drain"], "optional": [],
            "desc": "Infiltration Trench"},
    "PP": {"required": ["surface", "pavement", "soil", "storage", "drain"], "optional": [],
            "desc": "Permeable Pavement"},
    "RB": {"required": ["storage", "drain"], "optional": [],
            "desc": "Rain Barrel"},
    "VS": {"required": ["surface"], "optional": [],
            "desc": "Vegetative Swale"},
}

# Default parameter values per layer
DEFAULT_PARAMS = {
    "surface": {
        "berm_height": 150.0,   # mm
        "vegetation_fraction": 0.0,
        "roughness": 0.1,       # Manning's N
        "slope": 1.0,           # percent
    },
    "soil": {
        "thickness": 600.0,     # mm
        "porosity": 0.45,
        "field_capacity": 0.20,
        "wilting_point": 0.10,
        "conductivity": 50.0,   # mm/hr (Ksat)
        "conductivity_slope": 10.0,
        "suction_head": 100.0,  # mm
    },
    "storage": {
        "thickness": 300.0,     # mm (height)
        "void_ratio": 0.75,
        "conductivity": 100.0,  # mm/hr (seepage rate)
        "clog_factor": 0.0,
    },
    "drain": {
        "coefficient": 0.0,
        "exponent": 0.5,
        "offset": 0.0,         # mm
        "delay": 6.0,          # hours
    },
    "drainmat": {
        "thickness": 25.0,      # mm
        "void_fraction": 0.5,
        "roughness": 0.1,       # Manning's N
    },
    "pavement": {
        "thickness": 100.0,     # mm
        "void_ratio": 0.15,
        "impervious_fraction": 0.0,
        "permeability": 100.0,  # mm/hr
        "clog_factor": 0.0,
    },
}


def parse_layer_params(param_str, layer_name):
    """Parse 'key=value,key=value' string into dict, filling defaults."""
    params = dict(DEFAULT_PARAMS.get(layer_name, {}))  # start with defaults
    if param_str:
        for pair in param_str.split(","):
            pair = pair.strip()
            if "=" not in pair:
                continue
            key, value = pair.split("=", 1)
            key = key.strip()
            try:
                params[key] = float(value.strip())
            except ValueError:
                params[key] = value.strip()
    return params


def validate_lid_params(lid_type, layers):
    """Validate LID parameter consistency."""
    issues = []
    warnings = []

    # Soil consistency: WP < FC < porosity
    if "soil" in layers:
        soil = layers["soil"]
        wp = soil.get("wilting_point", 0)
        fc = soil.get("field_capacity", 0)
        poro = soil.get("porosity", 0)

        if wp >= fc:
            issues.append(f"Soil: wilting_point ({wp}) must be < field_capacity ({fc})")
        if fc >= poro:
            issues.append(f"Soil: field_capacity ({fc}) must be < porosity ({poro})")
        if soil.get("thickness", 0) <= 0:
            issues.append("Soil: thickness must be > 0")
        if soil.get("conductivity", 0) <= 0:
            issues.append("Soil: conductivity (Ksat) must be > 0")

    # Surface checks
    if "surface" in layers:
        surface = layers["surface"]
        if surface.get("berm_height", 0) < 0:
            issues.append("Surface: berm_height must be >= 0")
        if surface.get("roughness", 0) <= 0:
            issues.append("Surface: roughness must be > 0")
        if surface.get("slope", 0) < 0:
            issues.append("Surface: slope must be >= 0")
        veg_frac = surface.get("vegetation_fraction", 0)
        if veg_frac < 0 or veg_frac > 1:
            warnings.append(f"Surface: vegetation_fraction ({veg_frac}) should be 0-1")

    # Storage checks
    if "storage" in layers:
        storage = layers["storage"]
        if storage.get("thickness", 0) <= 0:
            issues.append("Storage: thickness must be > 0")
        vr = storage.get("void_ratio", 0)
        if vr < 0 or vr > 1:
            issues.append(f"Storage: void_ratio ({vr}) must be 0-1")
        if storage.get("conductivity", 0) < 0:
            issues.append("Storage: conductivity must be >= 0")

    # Pavement checks
    if "pavement" in layers:
        pave = layers["pavement"]
        if pave.get("thickness", 0) <= 0:
            issues.append("Pavement: thickness must be > 0")
        if pave.get("permeability", 0) <= 0:
            issues.append("Pavement: permeability must be > 0")

    return issues, warnings


def main():
    parser = argparse.ArgumentParser(
        description="Create SWMM LID control definition"
    )
    parser.add_argument("--type", required=True, choices=list(LID_TYPE_LAYERS.keys()),
                        help="LID type (BC/RG/GR/IT/PP/RB/VS)")
    parser.add_argument("--name", required=True, help="LID control name")
    parser.add_argument("--surface", default=None,
                        help='Surface layer params: "berm=150,rough=0.1,slope=1,veg=0"')
    parser.add_argument("--soil", default=None,
                        help='Soil layer params: "thick=600,poro=0.45,fc=0.2,wp=0.1,ksat=50"')
    parser.add_argument("--storage", default=None,
                        help='Storage layer params: "thick=300,void=0.75,ksat=100"')
    parser.add_argument("--drain", default=None,
                        help='Drain layer params: "coeff=0,exp=0.5,offset=0,delay=6"')
    parser.add_argument("--drainmat", default=None,
                        help='Drainage mat params: "thick=25,void=0.5,rough=0.1"')
    parser.add_argument("--pavement", default=None,
                        help='Pavement layer params: "thick=100,void=0.15,perm=100"')
    parser.add_argument("--output", required=True, help="Output JSON path")
    args = parser.parse_args()

    lid_type = args.type
    lid_info = LID_TYPE_LAYERS[lid_type]

    print(f"Creating LID control: {args.name} ({lid_info['desc']})")

    # Build layers
    # Map short param names to full names
    param_aliases = {
        "berm": "berm_height", "rough": "roughness", "veg": "vegetation_fraction",
        "thick": "thickness", "poro": "porosity", "fc": "field_capacity",
        "wp": "wilting_point", "ksat": "conductivity", "slope_c": "conductivity_slope",
        "suction": "suction_head", "void": "void_ratio", "clog": "clog_factor",
        "coeff": "coefficient", "exp": "exponent",
        "imperv": "impervious_fraction", "perm": "permeability",
    }

    def resolve_aliases(param_str):
        if not param_str:
            return param_str
        resolved = []
        for pair in param_str.split(","):
            if "=" in pair:
                key, val = pair.split("=", 1)
                key = key.strip()
                key = param_aliases.get(key, key)
                resolved.append(f"{key}={val.strip()}")
        return ",".join(resolved)

    layers = {}
    layer_args = {
        "surface": args.surface,
        "soil": args.soil,
        "storage": args.storage,
        "drain": args.drain,
        "drainmat": args.drainmat,
        "pavement": args.pavement,
    }

    for layer_name in lid_info["required"] + lid_info["optional"]:
        param_str = resolve_aliases(layer_args.get(layer_name))
        layers[layer_name] = parse_layer_params(param_str, layer_name)

    # Validate
    issues, warnings = validate_lid_params(lid_type, layers)
    if issues:
        print(f"  VALIDATION ISSUES:", file=sys.stderr)
        for issue in issues:
            print(f"    - {issue}", file=sys.stderr)
    if warnings:
        print(f"  WARNINGS:", file=sys.stderr)
        for w in warnings:
            print(f"    - {w}", file=sys.stderr)

    # Build output
    lid_control = {
        "name": args.name,
        "type": lid_type,
        "description": lid_info["desc"],
        "layers": layers,
        "validation": {
            "valid": len(issues) == 0,
            "n_issues": len(issues),
            "n_warnings": len(warnings),
            "issues": issues,
            "warnings": warnings,
        },
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(lid_control, f, indent=2)

    print(f"\nLID control written: {output_path}")
    for layer_name, params in layers.items():
        print(f"  {layer_name}: {len(params)} parameters")

    if issues:
        print(f"\n  {len(issues)} validation issue(s) — fix before use")
        sys.exit(1)


if __name__ == "__main__":
    main()
