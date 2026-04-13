#!/usr/bin/env python3
"""
Validate SWMM LID control parameters.

Comprehensive validation of LID (Low Impact Development) control definitions:
  - Soil consistency: wilting_point < field_capacity < porosity
  - All physical values are positive
  - Parameter ranges are physically reasonable
  - Required layers are present for each LID type
  - Cross-layer consistency (e.g., storage drain below storage depth)

Reads LID control definitions from JSON (as produced by create_lid_control.py)
and outputs a JSON validation report to stdout.
"""

import argparse
import json
import os
import sys

# Reasonable parameter ranges (min, max, unit)
PARAM_RANGES = {
    "surface": {
        "berm_height":         (0, 500,   "mm"),
        "vegetation_fraction": (0, 1.0,   "fraction"),
        "roughness":           (0.001, 1.0, "Manning's N"),
        "slope":               (0, 50,    "percent"),
    },
    "soil": {
        "thickness":           (50, 2000,  "mm"),
        "porosity":            (0.1, 0.7,  "fraction"),
        "field_capacity":      (0.05, 0.5, "fraction"),
        "wilting_point":       (0.01, 0.3, "fraction"),
        "conductivity":        (0.01, 500, "mm/hr"),
        "conductivity_slope":  (1, 100,    "unitless"),
        "suction_head":        (10, 500,   "mm"),
    },
    "storage": {
        "thickness":           (10, 5000,  "mm"),
        "void_ratio":          (0.1, 1.0,  "fraction"),
        "conductivity":        (0, 500,    "mm/hr"),
        "clog_factor":         (0, 100,    "unitless"),
    },
    "drain": {
        "coefficient":         (0, 100,    "unitless"),
        "exponent":            (0, 5,      "unitless"),
        "offset":              (0, 5000,   "mm"),
        "delay":               (0, 168,    "hours"),
    },
    "drainmat": {
        "thickness":           (1, 200,    "mm"),
        "void_fraction":       (0.1, 1.0,  "fraction"),
        "roughness":           (0.001, 1.0, "Manning's N"),
    },
    "pavement": {
        "thickness":           (10, 500,   "mm"),
        "void_ratio":          (0.01, 0.5, "fraction"),
        "impervious_fraction": (0, 1.0,    "fraction"),
        "permeability":        (0.1, 1000, "mm/hr"),
        "clog_factor":         (0, 100,    "unitless"),
    },
}

# Required layers per LID type
REQUIRED_LAYERS = {
    "BC": ["surface", "soil", "storage", "drain"],
    "RG": ["surface", "soil"],
    "GR": ["surface", "soil", "drainmat"],
    "IT": ["surface", "storage", "drain"],
    "PP": ["surface", "pavement", "soil", "storage", "drain"],
    "RB": ["storage", "drain"],
    "VS": ["surface"],
}


def validate_lid_controls(lid_controls):
    """Validate a list of LID control definitions."""
    all_issues = []
    all_warnings = []

    if isinstance(lid_controls, dict):
        # Single control
        lid_controls = [lid_controls]

    for lid in lid_controls:
        name = lid.get("name", "UNKNOWN")
        lid_type = lid.get("type", "??")
        layers = lid.get("layers", {})
        prefix = f"LID '{name}' ({lid_type})"

        # Check required layers
        required = REQUIRED_LAYERS.get(lid_type, [])
        for req_layer in required:
            if req_layer not in layers:
                all_issues.append({
                    "lid": name,
                    "type": "missing_layer",
                    "message": f"{prefix}: Missing required layer '{req_layer}'",
                })

        # Validate each layer's parameters
        for layer_name, params in layers.items():
            if not isinstance(params, dict):
                continue

            ranges = PARAM_RANGES.get(layer_name, {})
            for param, value in params.items():
                if not isinstance(value, (int, float)):
                    continue
                if param in ranges:
                    rmin, rmax, unit = ranges[param]
                    if value < rmin:
                        all_issues.append({
                            "lid": name,
                            "layer": layer_name,
                            "param": param,
                            "type": "below_range",
                            "value": value,
                            "min": rmin,
                            "message": f"{prefix}.{layer_name}.{param}: "
                                       f"{value} < min {rmin} ({unit})",
                        })
                    elif value > rmax:
                        all_warnings.append({
                            "lid": name,
                            "layer": layer_name,
                            "param": param,
                            "type": "above_range",
                            "value": value,
                            "max": rmax,
                            "message": f"{prefix}.{layer_name}.{param}: "
                                       f"{value} > max {rmax} ({unit})",
                        })

        # Cross-parameter checks for soil
        if "soil" in layers:
            soil = layers["soil"]
            wp = soil.get("wilting_point", 0)
            fc = soil.get("field_capacity", 0)
            poro = soil.get("porosity", 0)

            if wp >= fc:
                all_issues.append({
                    "lid": name,
                    "type": "soil_consistency",
                    "message": f"{prefix}: wilting_point ({wp}) >= field_capacity ({fc})",
                })
            if fc >= poro:
                all_issues.append({
                    "lid": name,
                    "type": "soil_consistency",
                    "message": f"{prefix}: field_capacity ({fc}) >= porosity ({poro})",
                })

        # Cross-layer: drain offset vs storage thickness
        if "drain" in layers and "storage" in layers:
            drain_offset = layers["drain"].get("offset", 0)
            storage_thick = layers["storage"].get("thickness", 0)
            if drain_offset > storage_thick:
                all_warnings.append({
                    "lid": name,
                    "type": "drain_offset",
                    "message": f"{prefix}: drain offset ({drain_offset} mm) > "
                               f"storage thickness ({storage_thick} mm)",
                })

    report = {
        "n_controls": len(lid_controls) if isinstance(lid_controls, list) else 1,
        "n_issues": len(all_issues),
        "n_warnings": len(all_warnings),
        "issues": all_issues,
        "warnings": all_warnings,
        "valid": len(all_issues) == 0,
    }
    return report


def main():
    parser = argparse.ArgumentParser(
        description="Validate SWMM LID control parameters"
    )
    parser.add_argument("--lid_controls", required=True,
                        help="JSON file with LID control definitions")
    args = parser.parse_args()

    if not os.path.isfile(args.lid_controls):
        print(f"ERROR: File not found: {args.lid_controls}", file=sys.stderr)
        sys.exit(1)

    with open(args.lid_controls, "r") as f:
        data = json.load(f)

    # Handle both single control and list of controls
    if isinstance(data, dict):
        if "lid_controls" in data:
            controls = data["lid_controls"]
        elif "name" in data and "type" in data:
            controls = [data]
        else:
            controls = [data]
    elif isinstance(data, list):
        controls = data
    else:
        print("ERROR: Unexpected JSON structure", file=sys.stderr)
        sys.exit(1)

    print(f"Validating {len(controls)} LID control(s)...", file=sys.stderr)
    report = validate_lid_controls(controls)
    print(json.dumps(report, indent=2))

    if report["valid"]:
        print(f"\nVALID: {report['n_controls']} control(s) passed", file=sys.stderr)
    else:
        print(f"\nINVALID: {report['n_issues']} issue(s)", file=sys.stderr)

    sys.exit(0 if report["valid"] else 1)


if __name__ == "__main__":
    main()
