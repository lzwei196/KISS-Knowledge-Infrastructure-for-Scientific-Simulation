#!/usr/bin/env python3
"""
convert_soil_params.py — Convert HWSD (Harmonized World Soil Database) data
to openAMUNDSEN soil configuration parameters.

openAMUNDSEN requires:
  - soil.thickness: list of layer thicknesses (m) — CRITICAL: meters, not cm!
  - soil.sand_fraction: 0-1 fraction
  - soil.clay_fraction: 0-1 fraction
  - soil.albedo: surface albedo (0-1)

HWSD provides:
  - T_SAND, S_SAND: topsoil/subsoil sand content (%)
  - T_CLAY, S_CLAY: topsoil/subsoil clay content (%)
  - T_OC, S_OC: organic carbon content (%)

CRITICAL conversions:
  - HWSD sand/clay are in percent (0-100) → model expects fraction (0-1)
  - HWSD does not provide layer thickness → use standard defaults or custom
  - Soil thermal properties derived from sand/clay via de Vries (1963)

Usage:
  python convert_soil_params.py \\
    --hwsd-csv ./HWSD_DATA.csv \\
    --lat 47.0 --lon 11.5 \\
    --output soil_config.json

  python convert_soil_params.py \\
    --sand-percent 45 --clay-percent 25 \\
    --layers 0.1,0.2,0.4,0.8 \\
    --output soil_config.json
"""

import argparse
import json
import os
import sys

import numpy as np


# Default soil layer thicknesses (meters) — from openAMUNDSEN defaults
DEFAULT_LAYER_THICKNESSES = [0.1, 0.2, 0.4, 0.8]

# Soil albedo lookup by texture class (approximate)
SOIL_ALBEDO_BY_TEXTURE = {
    "sand": 0.25,
    "loamy_sand": 0.22,
    "sandy_loam": 0.20,
    "loam": 0.17,
    "silt_loam": 0.18,
    "silt": 0.18,
    "sandy_clay_loam": 0.16,
    "clay_loam": 0.15,
    "silty_clay_loam": 0.15,
    "sandy_clay": 0.14,
    "silty_clay": 0.13,
    "clay": 0.12,
    "organic": 0.10,
}

# Physical constants from openAMUNDSEN constants.py
VOL_HEAT_CAP_SAND = 2.128e6   # J m-3 K-1
VOL_HEAT_CAP_CLAY = 2.385e6   # J m-3 K-1
THERM_COND_SAND = 1.57        # W m-1 K-1
THERM_COND_CLAY = 1.16        # W m-1 K-1


def validate_inputs(args):
    """Validate input arguments."""
    errors = []

    if args.hwsd_csv and not os.path.exists(args.hwsd_csv):
        errors.append(f"HWSD file not found: {args.hwsd_csv}")

    if args.sand_percent is not None:
        if not 0 <= args.sand_percent <= 100:
            errors.append(f"Sand percent must be 0-100, got {args.sand_percent}")
    if args.clay_percent is not None:
        if not 0 <= args.clay_percent <= 100:
            errors.append(f"Clay percent must be 0-100, got {args.clay_percent}")

    if args.sand_percent is not None and args.clay_percent is not None:
        if args.sand_percent + args.clay_percent > 100:
            errors.append(f"Sand + clay = {args.sand_percent + args.clay_percent}% exceeds 100%")

    if args.layers:
        try:
            thicknesses = [float(x) for x in args.layers.split(",")]
            for t in thicknesses:
                if t <= 0:
                    errors.append(f"Layer thickness must be positive: {t}")
                if t > 10:
                    errors.append(f"Layer thickness {t}m suspiciously large — did you use cm?")
        except ValueError:
            errors.append(f"Cannot parse layer thicknesses: {args.layers}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)

    return True


def classify_soil_texture(sand_pct, clay_pct):
    """Classify soil texture using USDA triangle."""
    silt_pct = 100 - sand_pct - clay_pct

    if clay_pct >= 40:
        if silt_pct >= 40:
            return "silty_clay"
        elif sand_pct >= 45:
            return "sandy_clay"
        return "clay"
    elif clay_pct >= 27:
        if sand_pct >= 20 and sand_pct < 45:
            return "clay_loam"
        elif sand_pct >= 45:
            return "sandy_clay_loam"
        return "silty_clay_loam"
    elif clay_pct >= 7:
        if silt_pct >= 50:
            if clay_pct >= 12:
                return "silt_loam"
            return "silt"
        elif sand_pct >= 52:
            return "sandy_loam"
        return "loam"
    else:
        if sand_pct >= 85:
            return "sand"
        elif sand_pct >= 70:
            return "loamy_sand"
        if silt_pct >= 80:
            return "silt"
        return "silt_loam"


def extract_from_hwsd(hwsd_csv, lat, lon):
    """Extract soil properties from HWSD CSV for given coordinates."""
    import pandas as pd

    df = pd.read_csv(hwsd_csv)

    # HWSD typically has MU_GLOBAL, lat/lon fields
    # Find nearest grid cell
    if "LAT" in df.columns and "LON" in df.columns:
        distances = np.sqrt((df["LAT"] - lat) ** 2 + (df["LON"] - lon) ** 2)
        idx = distances.idxmin()
        row = df.iloc[idx]

        sand_pct = float(row.get("T_SAND", row.get("S_SAND", 60)))
        clay_pct = float(row.get("T_CLAY", row.get("S_CLAY", 20)))
        oc_pct = float(row.get("T_OC", row.get("S_OC", 1.0)))

        return sand_pct, clay_pct, oc_pct
    else:
        print("WARNING: HWSD CSV missing LAT/LON columns, using first row", file=sys.stderr)
        row = df.iloc[0]
        sand_pct = float(row.get("T_SAND", 60))
        clay_pct = float(row.get("T_CLAY", 20))
        oc_pct = float(row.get("T_OC", 1.0))
        return sand_pct, clay_pct, oc_pct


def compute_thermal_properties(sand_frac, clay_frac):
    """Compute soil thermal properties from sand/clay fractions."""
    silt_frac = 1.0 - sand_frac - clay_frac

    # Volumetric heat capacity (weighted average)
    vol_heat_cap = sand_frac * VOL_HEAT_CAP_SAND + clay_frac * VOL_HEAT_CAP_CLAY

    # Thermal conductivity (geometric mean approximation)
    therm_cond = (THERM_COND_SAND ** sand_frac) * (THERM_COND_CLAY ** clay_frac)

    return vol_heat_cap, therm_cond


def process(args):
    """Main processing: convert soil data to openAMUNDSEN parameters."""
    # Get sand/clay percentages
    if args.hwsd_csv:
        sand_pct, clay_pct, oc_pct = extract_from_hwsd(args.hwsd_csv, args.lat, args.lon)
        print(f"HWSD extraction: sand={sand_pct}%, clay={clay_pct}%, OC={oc_pct}%", file=sys.stderr)
    else:
        sand_pct = args.sand_percent if args.sand_percent is not None else 60.0
        clay_pct = args.clay_percent if args.clay_percent is not None else 20.0
        oc_pct = 1.0

    # Convert percent to fraction — CRITICAL: model expects 0-1
    sand_frac = sand_pct / 100.0
    clay_frac = clay_pct / 100.0

    # Get layer thicknesses
    if args.layers:
        layer_thicknesses = [float(x) for x in args.layers.split(",")]
    else:
        layer_thicknesses = DEFAULT_LAYER_THICKNESSES

    # Classify texture and get albedo
    texture_class = classify_soil_texture(sand_pct, clay_pct)
    soil_albedo = SOIL_ALBEDO_BY_TEXTURE.get(texture_class, 0.15)

    # Compute thermal properties
    vol_heat_cap, therm_cond = compute_thermal_properties(sand_frac, clay_frac)

    result = {
        "status": "success",
        "soil_config": {
            "thickness": layer_thicknesses,
            "sand_fraction": round(sand_frac, 3),
            "clay_fraction": round(clay_frac, 3),
            "albedo": round(soil_albedo, 3),
        },
        "derived_properties": {
            "texture_class": texture_class,
            "silt_fraction": round(1.0 - sand_frac - clay_frac, 3),
            "volumetric_heat_capacity_J_m3_K": round(vol_heat_cap, 0),
            "thermal_conductivity_W_m_K": round(therm_cond, 3),
            "organic_carbon_percent": oc_pct,
        },
        "yaml_snippet": (
            f"soil:\n"
            f"  thickness: {layer_thicknesses}\n"
            f"  sand_fraction: {round(sand_frac, 3)}\n"
            f"  clay_fraction: {round(clay_frac, 3)}\n"
            f"  albedo: {round(soil_albedo, 3)}\n"
        ),
        "warnings": [],
    }

    # Validate outputs
    result = validate_outputs(result)

    print(json.dumps(result, indent=2))

    # Write to file if requested
    if args.output:
        with open(args.output, "w") as f:
            json.dump(result, f, indent=2)
        print(f"Written: {args.output}", file=sys.stderr)

    return result


def validate_outputs(result):
    """Validate computed soil parameters."""
    cfg = result["soil_config"]

    if cfg["sand_fraction"] + cfg["clay_fraction"] > 1.0:
        result["warnings"].append("Sand + clay fraction > 1.0 — check input data")

    if any(t > 5.0 for t in cfg["thickness"]):
        result["warnings"].append("Layer thickness > 5m — unusually deep, verify units are meters")

    if any(t < 0.01 for t in cfg["thickness"]):
        result["warnings"].append("Layer thickness < 0.01m — suspiciously thin, are values in cm?")

    total_depth = sum(cfg["thickness"])
    if total_depth > 10:
        result["warnings"].append(f"Total soil depth {total_depth}m > 10m — verify units")

    if cfg["albedo"] < 0.05 or cfg["albedo"] > 0.40:
        result["warnings"].append(f"Soil albedo {cfg['albedo']} outside typical range (0.05-0.40)")

    if result["warnings"]:
        result["status"] = "warning"

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Convert HWSD soil data to openAMUNDSEN soil parameters"
    )
    parser.add_argument("--hwsd-csv", help="Path to HWSD CSV data file")
    parser.add_argument("--lat", type=float, help="Latitude for HWSD lookup")
    parser.add_argument("--lon", type=float, help="Longitude for HWSD lookup")
    parser.add_argument("--sand-percent", type=float, help="Sand content (%%)")
    parser.add_argument("--clay-percent", type=float, help="Clay content (%%)")
    parser.add_argument("--layers", help="Comma-separated layer thicknesses in meters (e.g. 0.1,0.2,0.4,0.8)")
    parser.add_argument("--output", help="Output JSON file path")

    args = parser.parse_args()
    validate_inputs(args)
    process(args)


if __name__ == "__main__":
    main()
