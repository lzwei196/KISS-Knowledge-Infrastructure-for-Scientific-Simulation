#!/usr/bin/env python3
"""
convert_soil_params.py — Convert HWSD/STATSGO soil data to DHSVM parameter format.

Generates the soil parameter table section for DHSVM's configuration file,
including pedotransfer functions to estimate hydraulic properties from
texture data.

CRITICAL unit traps:
  - Soil depth must be in meters (NOT cm)
  - Hydraulic conductivity must be in m/s (NOT mm/hr)
  - Porosity must be fraction 0-1 (NOT percent)
  - Bulk density must be in kg/m3 (NOT g/cm3)

Usage:
  python convert_soil_params.py --hwsd-file HWSD_DATA.csv \\
      --soil-map soil_classes.tif --output soil_params.json

  python convert_soil_params.py --sand 60 --clay 15 --silt 25 \\
      --depth 1.5 --output soil_params.json
"""

import argparse
import json
import math
import os
import sys

import numpy as np


# --------------------------------------------------------------------------- #
# Pedotransfer functions (Saxton & Rawls 2006)
# --------------------------------------------------------------------------- #

def saxton_rawls_porosity(sand_pct, clay_pct, om_pct=1.0):
    """Estimate porosity from texture using Saxton & Rawls (2006).

    Args:
        sand_pct: Sand content (%)
        clay_pct: Clay content (%)
        om_pct: Organic matter content (%)

    Returns:
        Porosity as fraction (0-1)
    """
    S = sand_pct / 100.0
    C = clay_pct / 100.0
    OM = om_pct / 100.0

    theta_s = (0.278 * S + 0.034 * C + 0.022 * OM
               - 0.018 * S * OM - 0.027 * C * OM
               - 0.584 * S * C + 0.078)
    theta_s = 0.636 * theta_s + 0.097
    # Clamp to physical range
    return max(0.3, min(0.7, theta_s + 0.01))


def saxton_rawls_ksat(sand_pct, clay_pct, porosity):
    """Estimate saturated hydraulic conductivity (m/s).

    Args:
        sand_pct: Sand content (%)
        clay_pct: Clay content (%)
        porosity: Porosity fraction

    Returns:
        Ksat in m/s
    """
    S = sand_pct / 100.0
    C = clay_pct / 100.0

    # Approximate Ksat from texture (mm/hr)
    lambda_bc = 1.0 / (math.log(1500.0) - math.log(33.0))
    ksat_mmhr = 1930.0 * (porosity - 0.01) ** (3.0 - lambda_bc)
    ksat_mmhr = max(0.01, min(500.0, ksat_mmhr))

    # Convert mm/hr → m/s
    ksat_ms = ksat_mmhr / 3.6e6
    return ksat_ms


def estimate_field_capacity(sand_pct, clay_pct, om_pct=1.0):
    """Estimate field capacity (fraction) at -33 kPa."""
    S = sand_pct / 100.0
    C = clay_pct / 100.0
    OM = om_pct / 100.0

    fc = (-0.251 * S + 0.195 * C + 0.011 * OM
          + 0.006 * S * OM - 0.027 * C * OM
          + 0.452 * S * C + 0.299)
    return max(0.05, min(0.50, fc))


def estimate_wilting_point(sand_pct, clay_pct, om_pct=1.0):
    """Estimate wilting point (fraction) at -1500 kPa."""
    S = sand_pct / 100.0
    C = clay_pct / 100.0
    OM = om_pct / 100.0

    wp = (-0.024 * S + 0.487 * C + 0.006 * OM
          + 0.005 * S * OM - 0.013 * C * OM
          + 0.068 * S * C + 0.031)
    return max(0.01, min(0.35, wp))


def estimate_bulk_density(porosity, particle_density=2650.0):
    """Estimate bulk density (kg/m3) from porosity.

    Args:
        porosity: Fraction
        particle_density: Particle density in kg/m3 (default quartz)

    Returns:
        Bulk density in kg/m3
    """
    return particle_density * (1.0 - porosity)


def estimate_thermal_conductivity(porosity, sand_pct):
    """Estimate thermal conductivity W/(m*K) from texture."""
    # Johansen method simplified
    if sand_pct > 50:
        k_dry = 0.25
    else:
        k_dry = 0.15
    k_sat = 2.0 * (1.0 - porosity) + 0.57 * porosity
    return (k_dry + k_sat) / 2.0


def estimate_thermal_capacity(porosity, bulk_density):
    """Estimate volumetric heat capacity J/(m3*K)."""
    # Mineral heat capacity + water contribution
    c_mineral = 2.0e6  # J/(m3*K)
    c_water = 4.18e6
    return c_mineral * (1.0 - porosity) + c_water * porosity * 0.3


SOIL_TEXTURE_CLASSES = {
    "sand":        {"sand": 90, "silt": 5,  "clay": 5},
    "loamy_sand":  {"sand": 80, "silt": 10, "clay": 10},
    "sandy_loam":  {"sand": 65, "silt": 25, "clay": 10},
    "loam":        {"sand": 40, "silt": 40, "clay": 20},
    "silt_loam":   {"sand": 20, "silt": 60, "clay": 20},
    "silt":        {"sand": 10, "silt": 80, "clay": 10},
    "sandy_clay_loam": {"sand": 55, "silt": 15, "clay": 30},
    "clay_loam":   {"sand": 30, "silt": 35, "clay": 35},
    "silty_clay_loam": {"sand": 10, "silt": 55, "clay": 35},
    "sandy_clay":  {"sand": 50, "silt": 5,  "clay": 45},
    "silty_clay":  {"sand": 5,  "silt": 50, "clay": 45},
    "clay":        {"sand": 20, "silt": 20, "clay": 60},
}


def validate_inputs(args):
    """Validate input arguments."""
    errors = []

    if args.hwsd_file and not os.path.isfile(args.hwsd_file):
        errors.append(f"HWSD file not found: {args.hwsd_file}")

    if args.sand is not None:
        total = (args.sand or 0) + (args.clay or 0) + (args.silt or 0)
        if abs(total - 100) > 1:
            errors.append(f"Sand+clay+silt = {total}%, should be ~100%")
        if args.sand < 0 or args.sand > 100:
            errors.append(f"Sand {args.sand}% out of range")
        if args.clay < 0 or args.clay > 100:
            errors.append(f"Clay {args.clay}% out of range")

    if args.depth is not None:
        if args.depth > 50:
            errors.append(f"Soil depth {args.depth} m seems too large. "
                          "Did you mean cm? Use --depth-unit cm")
        if args.depth < 0.01:
            errors.append(f"Soil depth {args.depth} m seems too small")

    if args.texture_class and args.texture_class not in SOIL_TEXTURE_CLASSES:
        errors.append(f"Unknown texture class '{args.texture_class}'. "
                      f"Valid: {list(SOIL_TEXTURE_CLASSES.keys())}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}, indent=2))
        sys.exit(1)


def process_from_texture(sand, clay, silt, depth_m, nlayers=3):
    """Generate DHSVM soil parameters from texture percentages."""
    porosity = saxton_rawls_porosity(sand, clay)
    ksat = saxton_rawls_ksat(sand, clay, porosity)
    fc = estimate_field_capacity(sand, clay)
    wp = estimate_wilting_point(sand, clay)
    bulk_dens = estimate_bulk_density(porosity)
    thermal_k = estimate_thermal_conductivity(porosity, sand)
    thermal_c = estimate_thermal_capacity(porosity, bulk_dens)

    # Pore size distribution index (Brooks-Corey)
    pore_size_dist = max(0.1, min(0.8,
        0.5 * math.exp(-0.01 * clay + 0.005 * sand)))

    # Bubbling pressure (m)
    bubbling_pressure = max(0.05, min(1.0,
        0.3 * math.exp(0.02 * clay - 0.01 * sand)))

    # Layer depths (monotonically increasing)
    layer_depths = []
    for i in range(nlayers):
        layer_depths.append(round(depth_m * (i + 1) / nlayers, 3))

    params = {
        "lateral_conductivity": round(ksat * 10, 8),  # m/s, lateral > vertical
        "exponential_decrease": 3.0,
        "depth_threshold": round(depth_m * 0.8, 3),
        "maximum_infiltration": round(ksat * 5, 8),
        "capillary_drive": round(bubbling_pressure * 0.5, 4),
        "surface_albedo": 0.2,
        "number_of_layers": nlayers,
        "layer_depths_m": layer_depths,
        "porosity": [round(porosity, 4)] * nlayers,
        "pore_size_distribution": [round(pore_size_dist, 4)] * nlayers,
        "bubbling_pressure_m": [round(bubbling_pressure, 4)] * nlayers,
        "field_capacity": [round(fc, 4)] * nlayers,
        "wilting_point": [round(wp, 4)] * nlayers,
        "bulk_density_kgm3": [round(bulk_dens, 1)] * nlayers,
        "vertical_conductivity_ms": [round(ksat, 8)] * nlayers,
        "thermal_conductivity_Wm_K": [round(thermal_k, 3)] * nlayers,
        "thermal_capacity_Jm3_K": [round(thermal_c, 0)] * nlayers,
        "residual_water_content": [round(wp * 0.3, 4)] * nlayers,
        "mannings_n": 0.013,
        "source_texture": {
            "sand_pct": sand,
            "clay_pct": clay,
            "silt_pct": silt,
        },
    }
    return params


def process_hwsd(args):
    """Process HWSD CSV file to generate multi-type soil parameters."""
    import pandas as pd

    df = pd.read_csv(args.hwsd_file)

    required = ["soil_id", "sand", "clay", "silt"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        return {"status": "error",
                "errors": [f"Missing columns in HWSD file: {missing}"]}

    depth_col = "depth_m" if "depth_m" in df.columns else None
    depth_m = args.depth if args.depth else 1.5

    soil_types = {}
    for _, row in df.iterrows():
        sid = int(row["soil_id"])
        d = row[depth_col] if depth_col else depth_m

        # Unit check: if depth > 10, assume cm
        if d > 10:
            print(f"WARNING: Soil depth {d} for type {sid} > 10. "
                  "Assuming cm, converting to m.", file=sys.stderr)
            d = d / 100.0

        params = process_from_texture(
            row["sand"], row["clay"], row["silt"], d)
        soil_types[str(sid)] = params

    return {
        "status": "success",
        "num_soil_types": len(soil_types),
        "soil_types": soil_types,
    }


def process(args):
    """Main processing logic."""
    if args.hwsd_file:
        return process_hwsd(args)

    # Single texture specification
    if args.texture_class:
        tex = SOIL_TEXTURE_CLASSES[args.texture_class]
        sand, clay, silt = tex["sand"], tex["clay"], tex["silt"]
    else:
        sand = args.sand
        clay = args.clay
        silt = args.silt or (100 - sand - clay)

    depth_m = args.depth if args.depth else 1.5
    if args.depth_unit == "cm":
        depth_m = depth_m / 100.0

    params = process_from_texture(sand, clay, silt, depth_m)

    return {
        "status": "success",
        "num_soil_types": 1,
        "soil_types": {"1": params},
    }


def validate_outputs(result):
    """Validate output parameters against physical constraints."""
    if result.get("status") != "success":
        return result

    warnings = []
    for sid, params in result.get("soil_types", {}).items():
        prefix = f"Soil type {sid}"

        for i, p in enumerate(params.get("porosity", [])):
            if p < 0.2 or p > 0.7:
                warnings.append(f"{prefix} layer {i}: porosity {p} unusual")

        for i, fc in enumerate(params.get("field_capacity", [])):
            wp = params.get("wilting_point", [0])[i]
            por = params.get("porosity", [1])[i]
            if fc >= por:
                warnings.append(f"{prefix} layer {i}: FC {fc} >= porosity {por}")
            if wp >= fc:
                warnings.append(f"{prefix} layer {i}: WP {wp} >= FC {fc}")

        depths = params.get("layer_depths_m", [])
        for i in range(1, len(depths)):
            if depths[i] <= depths[i - 1]:
                warnings.append(f"{prefix}: layer depths not monotonic: {depths}")

        for i, bd in enumerate(params.get("bulk_density_kgm3", [])):
            if bd < 800 or bd > 2000:
                warnings.append(f"{prefix} layer {i}: bulk density {bd} unusual")

    result["warnings"] = warnings
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Convert soil data to DHSVM parameter format")
    parser.add_argument("--hwsd-file", help="HWSD CSV file path")
    parser.add_argument("--soil-map", help="Soil classification raster (GeoTIFF)")
    parser.add_argument("--sand", type=float, help="Sand content (%)")
    parser.add_argument("--clay", type=float, help="Clay content (%)")
    parser.add_argument("--silt", type=float, help="Silt content (%)")
    parser.add_argument("--depth", type=float, help="Total soil depth")
    parser.add_argument("--depth-unit", default="m", choices=["m", "cm"],
                        help="Soil depth unit (default: m)")
    parser.add_argument("--texture-class", help="USDA texture class name")
    parser.add_argument("--output", help="Output JSON file")
    args = parser.parse_args()

    validate_inputs(args)
    result = process(args)
    result = validate_outputs(result)

    output_json = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            f.write(output_json)
        print(f"Output written to {args.output}", file=sys.stderr)
    else:
        print(output_json)


if __name__ == "__main__":
    main()
