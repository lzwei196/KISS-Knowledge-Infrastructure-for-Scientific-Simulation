#!/usr/bin/env python3
"""
convert_parameters.py — Convert petrophysical parameters to pyGIMLi region config.

Translates geological/geotechnical databases (e.g., borehole logs, rock-type tables,
HWSD soil data) into pyGIMLi region definitions with starting models, bounds,
and regularization constraints.

Usage:
    python convert_parameters.py --input rock_types.csv --method ert --output regions.json
    python convert_parameters.py --input borehole.csv --method srt --output regions.json
    python convert_parameters.py --input soil_profile.csv --method ert --depth-column depth \
        --value-column resistivity --output regions.json

Petrophysical databases (typical ranges):
    ERT (Resistivity, Ohm·m):
        Clay:           1 - 100
        Silt:           10 - 200
        Sand (dry):     100 - 5000
        Sand (wet):     50 - 500
        Gravel:         100 - 1000
        Sandstone:      50 - 5000
        Limestone:      100 - 10000
        Granite:        1000 - 100000
        Groundwater:    10 - 100
        Sea water:      0.2 - 0.5

    SRT (P-wave velocity, m/s):
        Air:            330
        Soil:           100 - 500
        Clay:           1000 - 2500
        Sand:           200 - 2000
        Gravel:         400 - 2000
        Sandstone:      1400 - 4500
        Limestone:      2000 - 6000
        Granite:        4000 - 6500
        Water:          1450 - 1550

Critical traps:
    - Resistivity vs. conductivity confusion (reciprocal relationship)
    - Velocity vs. slowness (pyGIMLi inverts slowness for SRT)
    - Log-space bounds: lower bound must be > 0 for TransLog
    - HWSD soil types need mapping to geophysical properties
"""

import argparse
import json
import os
import sys
import csv
import numpy as np


# Default petrophysical lookup tables
RESISTIVITY_TABLE = {
    "clay": {"min": 1, "max": 100, "typical": 20, "unit": "Ohm·m"},
    "silt": {"min": 10, "max": 200, "typical": 50, "unit": "Ohm·m"},
    "sand_dry": {"min": 100, "max": 5000, "typical": 1000, "unit": "Ohm·m"},
    "sand_wet": {"min": 50, "max": 500, "typical": 200, "unit": "Ohm·m"},
    "sand": {"min": 50, "max": 5000, "typical": 500, "unit": "Ohm·m"},
    "gravel": {"min": 100, "max": 1000, "typical": 500, "unit": "Ohm·m"},
    "sandstone": {"min": 50, "max": 5000, "typical": 500, "unit": "Ohm·m"},
    "limestone": {"min": 100, "max": 10000, "typical": 1000, "unit": "Ohm·m"},
    "granite": {"min": 1000, "max": 100000, "typical": 10000, "unit": "Ohm·m"},
    "shale": {"min": 5, "max": 100, "typical": 30, "unit": "Ohm·m"},
    "water_fresh": {"min": 10, "max": 100, "typical": 50, "unit": "Ohm·m"},
    "water_saline": {"min": 0.2, "max": 0.5, "typical": 0.3, "unit": "Ohm·m"},
}

VELOCITY_TABLE = {
    "soil": {"min": 100, "max": 500, "typical": 300, "unit": "m/s"},
    "clay": {"min": 1000, "max": 2500, "typical": 1800, "unit": "m/s"},
    "silt": {"min": 500, "max": 1500, "typical": 1000, "unit": "m/s"},
    "sand": {"min": 200, "max": 2000, "typical": 800, "unit": "m/s"},
    "gravel": {"min": 400, "max": 2000, "typical": 1200, "unit": "m/s"},
    "sandstone": {"min": 1400, "max": 4500, "typical": 3000, "unit": "m/s"},
    "limestone": {"min": 2000, "max": 6000, "typical": 4000, "unit": "m/s"},
    "granite": {"min": 4000, "max": 6500, "typical": 5500, "unit": "m/s"},
    "water": {"min": 1450, "max": 1550, "typical": 1500, "unit": "m/s"},
}


def validate_inputs(args):
    """Validate command-line arguments."""
    errors = []

    if not os.path.isfile(args.input):
        errors.append(f"Input file not found: {args.input}")

    if args.method not in ("ert", "srt", "sip"):
        errors.append(f"Unsupported method: {args.method}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)


def load_rock_type_table(filepath):
    """Load a CSV table mapping region IDs to rock types.

    Expected columns: region_id, rock_type, [depth_top, depth_bottom]
    """
    regions = []
    with open(filepath, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            row = {k.strip().lower(): v.strip() for k, v in row.items()}
            region = {
                "region_id": int(row.get("region_id", row.get("id", len(regions) + 1))),
                "rock_type": row.get("rock_type", row.get("lithology", "unknown")).lower(),
            }
            if "depth_top" in row:
                region["depth_top"] = float(row["depth_top"])
            if "depth_bottom" in row:
                region["depth_bottom"] = float(row["depth_bottom"])
            regions.append(region)
    return regions


def load_borehole_profile(filepath, depth_col="depth", value_col="value"):
    """Load borehole profile with depth-value pairs."""
    depths = []
    values = []
    with open(filepath, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            row = {k.strip().lower(): v.strip() for k, v in row.items()}
            depths.append(float(row[depth_col]))
            values.append(float(row[value_col]))
    return np.array(depths), np.array(values)


def map_to_resistivity(rock_type):
    """Map rock type string to resistivity range."""
    key = rock_type.lower().replace(" ", "_").replace("-", "_")
    if key in RESISTIVITY_TABLE:
        return RESISTIVITY_TABLE[key]
    # Fuzzy match
    for k, v in RESISTIVITY_TABLE.items():
        if k in key or key in k:
            return v
    return {"min": 10, "max": 10000, "typical": 100, "unit": "Ohm·m"}


def map_to_velocity(rock_type):
    """Map rock type string to velocity range."""
    key = rock_type.lower().replace(" ", "_").replace("-", "_")
    if key in VELOCITY_TABLE:
        return VELOCITY_TABLE[key]
    for k, v in VELOCITY_TABLE.items():
        if k in key or key in k:
            return v
    return {"min": 200, "max": 5000, "typical": 1500, "unit": "m/s"}


def process(args):
    """Generate pyGIMLi region configuration from input data."""
    result = {
        "status": "success",
        "method": args.method,
        "input": args.input,
        "regions": [],
    }

    if args.mode == "rock_table":
        rock_regions = load_rock_type_table(args.input)

        for reg in rock_regions:
            if args.method == "ert":
                props = map_to_resistivity(reg["rock_type"])
                region_config = {
                    "region_id": reg["region_id"],
                    "rock_type": reg["rock_type"],
                    "starting_model": props["typical"],
                    "lower_bound": props["min"],
                    "upper_bound": props["max"],
                    "unit": "Ohm·m",
                    "transform": "TransLogLU",
                    "single": False,
                }
            elif args.method == "srt":
                props = map_to_velocity(reg["rock_type"])
                # Convert velocity to slowness for pyGIMLi
                region_config = {
                    "region_id": reg["region_id"],
                    "rock_type": reg["rock_type"],
                    "starting_velocity": props["typical"],
                    "starting_slowness": 1.0 / props["typical"],
                    "lower_bound_velocity": props["min"],
                    "upper_bound_velocity": props["max"],
                    "lower_bound_slowness": 1.0 / props["max"],
                    "upper_bound_slowness": 1.0 / props["min"],
                    "unit": "s/m (slowness) | m/s (velocity)",
                    "transform": "TransLogLU",
                    "single": False,
                }
            else:
                region_config = {
                    "region_id": reg["region_id"],
                    "rock_type": reg["rock_type"],
                }

            if "depth_top" in reg:
                region_config["depth_top"] = reg["depth_top"]
            if "depth_bottom" in reg:
                region_config["depth_bottom"] = reg["depth_bottom"]

            result["regions"].append(region_config)

    elif args.mode == "borehole":
        depths, values = load_borehole_profile(
            args.input, args.depth_column, args.value_column
        )
        # Create layered starting model
        for i in range(len(depths)):
            region_config = {
                "region_id": i + 1,
                "depth": float(depths[i]),
                "value": float(values[i]),
            }
            if args.method == "ert":
                region_config["unit"] = "Ohm·m"
                region_config["transform"] = "TransLogLU"
            elif args.method == "srt":
                region_config["velocity"] = float(values[i])
                region_config["slowness"] = 1.0 / float(values[i])
                region_config["unit"] = "m/s"
            result["regions"].append(region_config)

    result["n_regions"] = len(result["regions"])

    # Add regularization defaults
    result["regularization"] = {
        "lambda": 20.0,
        "z_weight": 0.7,
        "smoothing_type": "first_order",
        "robust_data": False,
        "block_model": False,
    }

    return result


def validate_outputs(result):
    """Validate region configuration for common issues."""
    warnings = []

    for reg in result.get("regions", []):
        rid = reg.get("region_id", "?")

        if result["method"] == "ert":
            val = reg.get("starting_model", reg.get("value"))
            if val is not None:
                if val <= 0:
                    warnings.append(
                        f"Region {rid}: starting resistivity <= 0. "
                        "TransLog requires positive values."
                    )
                if val > 1e6:
                    warnings.append(
                        f"Region {rid}: resistivity = {val:.0f} Ohm·m is unusually high. "
                        "Check units (Ohm·m not mOhm·m)."
                    )

        if result["method"] == "srt":
            vel = reg.get("starting_velocity", reg.get("velocity"))
            if vel is not None:
                if vel <= 0:
                    warnings.append(
                        f"Region {rid}: velocity <= 0 is non-physical."
                    )
                if vel > 8000:
                    warnings.append(
                        f"Region {rid}: velocity = {vel:.0f} m/s exceeds crustal P-wave. "
                        "Check units (m/s not km/s)."
                    )

    if warnings:
        result["warnings"] = warnings

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Convert petrophysical parameters to pyGIMLi region config."
    )
    parser.add_argument("--input", "-i", required=True,
                        help="Input CSV file (rock types or borehole profile)")
    parser.add_argument("--method", "-m", required=True,
                        choices=["ert", "srt", "sip"],
                        help="Geophysical method")
    parser.add_argument("--mode", default="rock_table",
                        choices=["rock_table", "borehole"],
                        help="Input mode: rock_table or borehole profile")
    parser.add_argument("--output", "-o", default=None,
                        help="Output JSON file path")
    parser.add_argument("--depth-column", default="depth",
                        help="Column name for depth (borehole mode)")
    parser.add_argument("--value-column", default="value",
                        help="Column name for property value (borehole mode)")
    parser.add_argument("--lambda-init", type=float, default=20.0,
                        help="Initial regularization strength (default: 20)")
    parser.add_argument("--z-weight", type=float, default=0.7,
                        help="Vertical regularization weight (default: 0.7)")

    args = parser.parse_args()

    validate_inputs(args)
    result = process(args)
    result["regularization"]["lambda"] = args.lambda_init
    result["regularization"]["z_weight"] = args.z_weight
    result = validate_outputs(result)

    output_json = json.dumps(result, indent=2)
    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            f.write(output_json)
        print(f"Region config written to {args.output}", file=sys.stderr)
    else:
        print(output_json)


if __name__ == "__main__":
    main()
