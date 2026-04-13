#!/usr/bin/env python3
"""
convert_parameters.py — Convert soil and land-use data to HydroCNHS parameter estimates.

Generates initial GWLF or ABCD parameter estimates from soil/land-use properties.
These are starting points for calibration, not final values.

CRITICAL:
  - Ur (soil water capacity) must be in cm, not mm
  - CN2 depends on hydrologic soil group (A/B/C/D) AND land use
  - Df (snowmelt) must be in cm/°C, not mm/°C

GWLF parameters (9 per subbasin):
  CN2  [25-100]   — SCS curve number (unitless)
  IS   [0-0.5]    — Interception coefficient (unitless)
  Res  [0.001-0.5] — Recession coefficient (unitless)
  Sep  [0-0.5]    — Deep seepage coefficient (unitless)
  Alpha [0-1]     — Baseflow coefficient (unitless)
  Beta  [0-1]     — Percolation coefficient (unitless)
  Ur   [1-15]     — Available water capacity (cm)
  Df   [0-1]      — Degree-day snowmelt coefficient (cm/°C)
  Kc   [0.5-1.5]  — Land cover coefficient (unitless)

ABCD parameters (5 per subbasin):
  a    [0-1]      — Runoff control (unitless)
  b    [0-400]    — Max soil water storage (cm)
  c    [0-1]      — Groundwater recharge fraction (unitless)
  d    [0-1]      — Groundwater discharge rate (unitless)
  Df   [0-1]      — Degree-day snowmelt coefficient (cm/°C)

Usage:
    python convert_parameters.py \\
        --soil-data /path/to/soil.csv \\
        --landuse-data /path/to/landuse.csv \\
        --outlets "WSLO,DLLO" \\
        --model GWLF \\
        --output /path/to/params.json
"""

import argparse
import json
import os
import sys

import numpy as np


# SCS CN2 lookup table: land_use → hydrologic_soil_group → CN2
CN2_LOOKUP = {
    "forest":      {"A": 36, "B": 60, "C": 73, "D": 79},
    "grassland":   {"A": 49, "B": 69, "C": 79, "D": 84},
    "cropland":    {"A": 67, "B": 77, "C": 83, "D": 87},
    "urban_low":   {"A": 51, "B": 68, "C": 79, "D": 84},
    "urban_high":  {"A": 89, "B": 92, "C": 94, "D": 95},
    "water":       {"A": 98, "B": 98, "C": 98, "D": 98},
    "wetland":     {"A": 78, "B": 78, "C": 78, "D": 78},
    "barren":      {"A": 77, "B": 86, "C": 91, "D": 94},
}

# Kc (crop coefficient) by land use
KC_LOOKUP = {
    "forest": 1.15, "grassland": 0.95, "cropland": 1.05,
    "urban_low": 0.85, "urban_high": 0.70, "water": 1.20,
    "wetland": 1.10, "barren": 0.60,
}

# IS (interception) by land use
IS_LOOKUP = {
    "forest": 0.20, "grassland": 0.10, "cropland": 0.08,
    "urban_low": 0.05, "urban_high": 0.02, "water": 0.0,
    "wetland": 0.05, "barren": 0.01,
}


def validate_inputs(args):
    """Validate inputs before processing."""
    errors = []

    if args.soil_data and not os.path.exists(args.soil_data):
        errors.append(f"Soil data file not found: {args.soil_data}")

    if args.landuse_data and not os.path.exists(args.landuse_data):
        errors.append(f"Land-use data file not found: {args.landuse_data}")

    if not args.outlets:
        errors.append("No outlets specified")

    if args.model not in ["GWLF", "ABCD"]:
        errors.append(f"Model must be GWLF or ABCD, got: {args.model}")

    return errors


def estimate_ur_from_soil(soil_group, depth_cm=100):
    """Estimate available water capacity (Ur) in cm from soil group.

    CRITICAL: Ur is in cm, not mm. Passing mm values (e.g., 80 instead of 8)
    causes the unsaturated zone to never fill, suppressing runoff.
    """
    # Available water capacity (cm water per cm soil) by soil group
    awc_per_cm = {"A": 0.10, "B": 0.15, "C": 0.12, "D": 0.08}
    awc = awc_per_cm.get(soil_group, 0.12)
    # Root zone depth assumption: top 100 cm
    ur = awc * min(depth_cm, 100)
    # Clamp to GWLF range [1, 15]
    return max(1.0, min(15.0, ur))


def estimate_gwlf_params(outlet, soil_group="B", land_use="grassland",
                          latitude=45.0, elevation_m=200):
    """Generate initial GWLF parameters for a subbasin."""
    cn2 = CN2_LOOKUP.get(land_use, CN2_LOOKUP["grassland"]).get(soil_group, 69)
    is_coeff = IS_LOOKUP.get(land_use, 0.10)
    kc = KC_LOOKUP.get(land_use, 1.0)
    ur = estimate_ur_from_soil(soil_group)

    # Recession and baseflow depend on soil permeability
    res_by_group = {"A": 0.05, "B": 0.10, "C": 0.20, "D": 0.30}
    alpha_by_group = {"A": 0.8, "B": 0.6, "C": 0.4, "D": 0.2}

    # Snowmelt Df depends on elevation (higher = more snow, lower Df)
    df = max(0.1, min(1.0, 0.5 - elevation_m / 5000.0))

    params = {
        "CN2": cn2,
        "IS": round(is_coeff, 3),
        "Res": round(res_by_group.get(soil_group, 0.10), 3),
        "Sep": 0.01,
        "Alpha": round(alpha_by_group.get(soil_group, 0.6), 3),
        "Beta": 0.5,
        "Ur": round(ur, 3),
        "Df": round(df, 3),
        "Kc": round(kc, 3),
    }
    return params


def estimate_abcd_params(outlet, soil_group="B", land_use="grassland"):
    """Generate initial ABCD parameters for a subbasin."""
    # 'a' controls tendency to produce runoff: lower for urban, higher for forest
    a_by_lu = {"forest": 0.95, "grassland": 0.90, "cropland": 0.85,
               "urban_low": 0.70, "urban_high": 0.50, "barren": 0.60}
    # 'b' is max soil storage in cm — related to soil depth and type
    b_by_group = {"A": 300, "B": 200, "C": 150, "D": 100}

    params = {
        "a": round(a_by_lu.get(land_use, 0.90), 3),
        "b": b_by_group.get(soil_group, 200),
        "c": 0.5,
        "d": 0.5,
        "Df": 0.3,
    }
    return params


def validate_output_params(params, model_type, log):
    """Verify all parameters are within valid ranges."""
    if model_type == "GWLF":
        ranges = {
            "CN2": (25, 100), "IS": (0, 0.5), "Res": (0.001, 0.5),
            "Sep": (0, 0.5), "Alpha": (0, 1), "Beta": (0, 1),
            "Ur": (1, 15), "Df": (0, 1), "Kc": (0.5, 1.5),
        }
    else:
        ranges = {
            "a": (0, 1), "b": (0, 400), "c": (0, 1),
            "d": (0, 1), "Df": (0, 1),
        }

    ok = True
    for key, (lo, hi) in ranges.items():
        for outlet, p in params.items():
            val = p.get(key)
            if val is not None and (val < lo or val > hi):
                log.append(f"[ERROR] {outlet}.{key}={val} out of range [{lo}, {hi}]")
                ok = False
    return ok


def process(args):
    """Generate parameter estimates for all outlets."""
    log = []
    outlets = [o.strip() for o in args.outlets.split(",")]
    params = {}

    for outlet in outlets:
        soil_group = args.default_soil_group
        land_use = args.default_land_use

        if args.model == "GWLF":
            params[outlet] = estimate_gwlf_params(
                outlet, soil_group=soil_group, land_use=land_use
            )
            log.append(f"{outlet}: GWLF params estimated (soil={soil_group}, lu={land_use})")
        else:
            params[outlet] = estimate_abcd_params(
                outlet, soil_group=soil_group, land_use=land_use
            )
            log.append(f"{outlet}: ABCD params estimated (soil={soil_group}, lu={land_use})")

    # Validate output
    if not validate_output_params(params, args.model, log):
        return {"status": "error", "errors": log}

    return {
        "status": "success",
        "output": {
            "model": args.model,
            "parameters": params,
            "n_outlets": len(outlets),
            "note": "These are initial estimates for calibration. Set to -99 for GA optimization.",
        },
        "log": log
    }


def main():
    parser = argparse.ArgumentParser(
        description="Convert soil/land-use data to HydroCNHS parameter estimates"
    )
    parser.add_argument("--soil-data", default=None, help="Soil properties CSV")
    parser.add_argument("--landuse-data", default=None, help="Land-use CSV")
    parser.add_argument("--outlets", required=True, help="Comma-separated outlet names")
    parser.add_argument("--model", default="GWLF", choices=["GWLF", "ABCD"],
                        help="Rainfall-runoff model type")
    parser.add_argument("--default-soil-group", default="B", choices=["A", "B", "C", "D"],
                        help="Default hydrologic soil group")
    parser.add_argument("--default-land-use", default="grassland",
                        help="Default land use type")
    parser.add_argument("--output", default=None, help="Output JSON file")

    args = parser.parse_args()

    errors = validate_inputs(args)
    if errors:
        print(json.dumps({"status": "error", "errors": errors}, indent=2))
        sys.exit(1)

    result = process(args)

    if args.output:
        with open(args.output, "w") as f:
            json.dump(result, f, indent=2)
        print(f"Output written to {args.output}")
    else:
        print(json.dumps(result, indent=2))

    if result["status"] == "error":
        sys.exit(1)


if __name__ == "__main__":
    main()
