#!/usr/bin/env python3
"""
convert_soil.py - Convert HWSD or SoilGrids data to GEOtop soil parameter files.

Derives Van Genuchten parameters from soil texture using Rosetta-style pedotransfer
functions, then writes soilXXXX.txt files in GEOtop format.

CRITICAL UNIT CONVERSIONS:
  - Dz (layer thickness): MILLIMETERS, not meters or centimeters
  - Kh, Kv (hydraulic conductivity): m/s, not cm/day or mm/hr
  - alpha (Van Genuchten): 1/mm, not 1/cm or 1/m
  - n (Van Genuchten): dimensionless
  - vwc_r, vwc_w, vwc_fc, vwc_s: volumetric fraction (m3/m3, 0-1)
  - stor (specific storativity): 1/m

Common errors:
  - HWSD Ksat is in cm/day -> divide by 86400 and by 100 for m/s
  - Literature alpha is usually in 1/cm -> divide by 10 for 1/mm
  - SoilGrids depth is in cm -> multiply by 10 for mm

Usage:
    python convert_soil.py \\
        --source hwsd \\
        --input /path/to/hwsd_data.csv \\
        --lat 46.668 --lon 10.579 \\
        --layers "10,10,10,20,20,30,50,50,50,50,100,100,100,100,150,150" \\
        --output /path/to/sim/soil/soil0001.txt

    python convert_soil.py \\
        --source manual \\
        --sand 40 --silt 35 --clay 25 \\
        --bulk-density 1400 --organic-carbon 2.0 \\
        --layers "10,10,10,20,20,30,50,50,50,50,100,100,100,100,150,150" \\
        --output /path/to/sim/soil/soil0001.txt
"""

import argparse
import json
import math
import os
import sys

import numpy as np


def validate_inputs(args):
    """Validate all input arguments."""
    errors = []

    if args.source == "manual":
        total = args.sand + args.silt + args.clay
        if abs(total - 100) > 1:
            errors.append(f"Sand + Silt + Clay = {total}%, must sum to ~100%")
        if args.bulk_density < 500 or args.bulk_density > 2000:
            errors.append(f"Bulk density {args.bulk_density} kg/m3 out of typical range (500-2000)")
    elif args.source == "hwsd":
        # --input is OPTIONAL for hwsd since 2026-07-21: the lookup goes through
        # ki_tools_common.soil_utils.lookup_hwsd, which resolves the server's
        # hwsd.bil + attribute table itself. Only validate an explicit override.
        if args.input and not os.path.exists(args.input):
            errors.append(f"HWSD raster override not found: {args.input}")
        if abs(args.lat) < 1e-9 and abs(args.lon) < 1e-9:
            errors.append("--source hwsd requires --lat/--lon (point lookup)")

    layers = [float(x) for x in args.layers.split(",")]
    for i, dz in enumerate(layers):
        if dz <= 0:
            errors.append(f"Layer {i+1} thickness {dz} must be positive")
        if dz < 1:
            errors.append(f"Layer {i+1} thickness {dz} < 1 mm. Did you use meters instead of mm?")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)

    return layers


def rosetta_pedotransfer(sand, silt, clay, bulk_density=1400, organic_carbon=1.0):
    """Estimate Van Genuchten parameters from soil texture using Rosetta-style PTFs.

    Based on Schaap et al. (2001) class-average pedotransfer functions.

    Args:
        sand: Sand content (%)
        silt: Silt content (%)
        clay: Clay content (%)
        bulk_density: Bulk density (kg/m3)
        organic_carbon: Organic carbon content (%)

    Returns:
        dict with keys: theta_r, theta_s, alpha_cm, n, Ksat_cm_day
        (in LITERATURE units - must convert for GEOtop)
    """
    # USDA texture class determination
    if sand >= 85:
        texture = "sand"
    elif sand >= 70 and clay <= 15:
        texture = "loamy_sand"
    elif (sand >= 50 and clay <= 20) or (sand >= 43 and silt <= 28 and clay >= 7):
        texture = "sandy_loam"
    elif silt >= 80:
        texture = "silt"
    elif silt >= 50 and clay <= 27:
        texture = "silt_loam"
    elif clay >= 27 and clay <= 40 and sand >= 20:
        texture = "sandy_clay_loam"
    elif clay >= 27 and clay <= 40 and sand < 20:
        texture = "clay_loam"
    elif silt >= 40 and clay >= 27 and clay <= 40:
        texture = "silty_clay_loam"
    elif clay >= 35 and sand >= 45:
        texture = "sandy_clay"
    elif clay >= 40 and silt >= 40:
        texture = "silty_clay"
    elif clay >= 40:
        texture = "clay"
    else:
        texture = "loam"

    # Schaap et al. (2001) class-average Van Genuchten parameters
    # theta_r, theta_s, alpha (1/cm), n, Ksat (cm/day)
    ptf_table = {
        "sand":             (0.053, 0.375, 0.035, 3.18, 712.8),
        "loamy_sand":       (0.049, 0.390, 0.035, 1.75, 350.2),
        "sandy_loam":       (0.039, 0.387, 0.027, 1.45, 106.1),
        "loam":             (0.061, 0.399, 0.011, 1.47, 25.0),
        "silt_loam":        (0.065, 0.439, 0.005, 1.66, 18.0),
        "silt":             (0.050, 0.489, 0.007, 1.68, 43.7),
        "sandy_clay_loam":  (0.063, 0.384, 0.021, 1.33, 31.4),
        "clay_loam":        (0.079, 0.442, 0.016, 1.42, 6.2),
        "silty_clay_loam":  (0.090, 0.482, 0.008, 1.52, 1.7),
        "sandy_clay":       (0.117, 0.385, 0.033, 1.21, 2.9),
        "silty_clay":       (0.111, 0.481, 0.016, 1.32, 0.5),
        "clay":             (0.098, 0.459, 0.015, 1.25, 4.8),
    }

    params = ptf_table.get(texture, ptf_table["loam"])

    # Adjust theta_s for bulk density (if provided)
    porosity = 1.0 - (bulk_density / 2650.0)  # Assume particle density 2650 kg/m3
    theta_s = min(porosity, params[1])

    # Adjust Ksat for organic carbon (higher OC -> higher K)
    oc_factor = 1.0 + 0.1 * (organic_carbon - 1.0)
    ksat = params[4] * max(0.1, oc_factor)

    return {
        "texture": texture,
        "theta_r": params[0],
        "theta_s": theta_s,
        "alpha_cm": params[2],  # in 1/cm (literature units)
        "n": params[3],
        "Ksat_cm_day": ksat,  # in cm/day (literature units)
    }


def estimate_field_capacity(theta_r, theta_s, alpha_cm, n):
    """Estimate field capacity at psi = -330 cm (pF 2.54).

    Uses Van Genuchten retention curve:
        theta = theta_r + (theta_s - theta_r) / (1 + (alpha*|psi|)^n)^m
    """
    m = 1.0 - 1.0 / n
    psi = 330.0  # cm (positive = suction)
    Se = 1.0 / (1.0 + (alpha_cm * psi) ** n) ** m
    return theta_r + Se * (theta_s - theta_r)


def estimate_wilting_point(theta_r, theta_s, alpha_cm, n):
    """Estimate wilting point at psi = -15000 cm (pF 4.2)."""
    m = 1.0 - 1.0 / n
    psi = 15000.0  # cm
    Se = 1.0 / (1.0 + (alpha_cm * psi) ** n) ** m
    return theta_r + Se * (theta_s - theta_r)


def convert_to_geotop_units(params):
    """Convert from literature units to GEOtop units.

    CRITICAL CONVERSIONS:
        alpha: 1/cm -> 1/mm  (divide by 10)
        Ksat:  cm/day -> m/s (divide by 86400, divide by 100)
    """
    alpha_mm = params["alpha_cm"] / 10.0   # 1/cm -> 1/mm
    ksat_ms = params["Ksat_cm_day"] / 86400.0 / 100.0  # cm/day -> m/s

    fc = estimate_field_capacity(params["theta_r"], params["theta_s"],
                                  params["alpha_cm"], params["n"])
    wp = estimate_wilting_point(params["theta_r"], params["theta_s"],
                                params["alpha_cm"], params["n"])

    return {
        "theta_r": params["theta_r"],
        "theta_s": params["theta_s"],
        "alpha": alpha_mm,
        "n": params["n"],
        "Kh": ksat_ms,
        "Kv": ksat_ms,
        "vwc_fc": fc,
        "vwc_w": wp,
        "stor": 5.0e-7,  # Default specific storativity (1/m)
    }


def read_hwsd(input_path, lat, lon):
    """Look up HWSD topsoil/subsoil texture at a point.

    BUGFIX (2026-07-21, GEOtop NCP MODIS-LST real case): this used to
    `pd.read_csv(input_path)` and nearest-neighbour a tidy table with columns
    lat/lon/sand_top/... . No such table exists on the server. HWSD ships as a
    30-arcsec raster of MU_GLOBAL mapping-unit ids (data/soil/HWSD_RASTER/
    hwsd.bil) plus a separate attribute table keyed on MU_GLOBAL, so
    `--source hwsd` failed on the real dataset and prior GEOtop runs fell back
    to `--source manual` with guessed texture.

    Fixed by routing through the canonical lookup,
    ki_tools_common.soil_utils.lookup_hwsd(lat, lon), which does the
    raster -> MU_GLOBAL -> attribute-table join and returns T_*/S_* texture.
    `input_path` is now OPTIONAL and, when given, is an explicit hwsd.bil path.
    """
    from ki_tools_common.soil_utils import lookup_hwsd

    raster = input_path if (input_path and os.path.exists(input_path)) else None
    h = lookup_hwsd(lat, lon, hwsd_raster=raster)

    # HWSD T_REF_BULK_DENSITY is g/cm3; the pedotransfer wants kg/m3.
    bd = float(h.get("bulk_density", 1.3))
    bd_kgm3 = bd * 1000.0 if bd < 100 else bd

    topsoil = {
        "sand": float(h["sand"]),
        "silt": float(h["silt"]),
        "clay": float(h["clay"]),
        "bulk_density": bd_kgm3,
        "organic_carbon": float(h.get("oc", 1.0)),
    }
    subsoil = {
        "sand": float(h.get("sub_sand", topsoil["sand"])),
        "silt": float(h.get("sub_silt", topsoil["silt"])),
        "clay": float(h.get("sub_clay", topsoil["clay"])),
        "bulk_density": bd_kgm3,
        "organic_carbon": max(0.1, topsoil["organic_carbon"] * 0.5),
    }
    print(json.dumps({"hwsd_mu_global": h.get("mu_id"), "texture": h.get("texture"),
                      "topsoil": topsoil, "subsoil": subsoil}), file=sys.stderr)
    return topsoil, subsoil


def process(args, layers):
    """Generate soil parameter file."""
    if args.source == "manual":
        ptf = rosetta_pedotransfer(args.sand, args.silt, args.clay,
                                    args.bulk_density, args.organic_carbon)
        geotop_params = convert_to_geotop_units(ptf)
        # Use same params for all layers
        layer_params = [geotop_params] * len(layers)

    elif args.source == "hwsd":
        topsoil, subsoil = read_hwsd(args.input, args.lat, args.lon)
        ptf_top = rosetta_pedotransfer(**topsoil)
        ptf_sub = rosetta_pedotransfer(**subsoil)
        gp_top = convert_to_geotop_units(ptf_top)
        gp_sub = convert_to_geotop_units(ptf_sub)

        # Top 30 cm = topsoil, below = subsoil
        cumulative = 0
        layer_params = []
        for dz in layers:
            cumulative += dz
            if cumulative <= 300:  # 300 mm = 30 cm
                layer_params.append(gp_top)
            else:
                layer_params.append(gp_sub)
    else:
        print(json.dumps({"status": "error", "errors": [f"Unknown source: {args.source}"]}),
              file=sys.stderr)
        sys.exit(1)

    # Write soil file
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    header = "Dz,Kh,Kv,vwc_r,vwc_w,vwc_fc,vwc_s,alpha,n,stor"

    with open(args.output, "w") as f:
        f.write(header + "\n")
        for dz, p in zip(layers, layer_params):
            f.write(
                f"{dz:.0f},"
                f"{p['Kh']:.2E},"
                f"{p['Kv']:.2E},"
                f"{p['theta_r']:.2f},"
                f"{p['vwc_w']:.2f},"
                f"{p['vwc_fc']:.2f},"
                f"{p['theta_s']:.2f},"
                f"{p['alpha']:.5f},"
                f"{p['n']:.1f},"
                f"{p['stor']:.2E}\n"
            )

    return len(layers)


def validate_outputs(output_path, layers):
    """Validate the generated soil file."""
    warnings = []

    with open(output_path) as f:
        header = f.readline().strip().split(",")
        rows = [line.strip().split(",") for line in f if line.strip()]

    if len(rows) != len(layers):
        warnings.append(f"Expected {len(layers)} layers, got {len(rows)}")

    for i, row in enumerate(rows):
        dz = float(row[0])
        kh = float(row[1])
        alpha = float(row[7])
        n_vg = float(row[8])
        theta_r = float(row[3])
        theta_s = float(row[6])

        if dz < 1:
            warnings.append(f"Layer {i+1}: Dz={dz} < 1 mm. Probably in meters (need mm).")
        if kh > 0.01:
            warnings.append(f"Layer {i+1}: Kh={kh:.2E} m/s > 0.01. Unrealistically high.")
        if kh < 1e-10:
            warnings.append(f"Layer {i+1}: Kh={kh:.2E} m/s < 1E-10. Unrealistically low.")
        if alpha > 0.1:
            warnings.append(f"Layer {i+1}: alpha={alpha} (1/mm) > 0.1. Might be in 1/cm (divide by 10).")
        if n_vg < 1.01 or n_vg > 5:
            warnings.append(f"Layer {i+1}: n={n_vg} outside typical range (1.01-5.0).")
        if theta_r >= theta_s:
            warnings.append(f"Layer {i+1}: theta_r ({theta_r}) >= theta_s ({theta_s}). Impossible.")

    total_depth = sum(float(row[0]) for row in rows)

    result = {
        "status": "ok" if not warnings else "warning",
        "n_layers": len(rows),
        "total_depth_mm": total_depth,
        "total_depth_m": total_depth / 1000.0,
        "warnings": warnings,
    }
    print(json.dumps(result, indent=2), file=sys.stderr)
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Convert soil data to GEOtop soilXXXX.txt format"
    )
    parser.add_argument("--source", required=True, choices=["hwsd", "soilgrids", "manual"],
                        help="Data source type")
    parser.add_argument("--input", default="", help="Input file path (for hwsd/soilgrids)")
    parser.add_argument("--lat", type=float, default=0, help="Latitude")
    parser.add_argument("--lon", type=float, default=0, help="Longitude")
    parser.add_argument("--sand", type=float, default=40, help="Sand content (%)")
    parser.add_argument("--silt", type=float, default=35, help="Silt content (%)")
    parser.add_argument("--clay", type=float, default=25, help="Clay content (%)")
    parser.add_argument("--bulk-density", type=float, default=1400, help="Bulk density (kg/m3)")
    parser.add_argument("--organic-carbon", type=float, default=1.0, help="Organic carbon (%)")
    parser.add_argument("--layers", required=True,
                        help="Comma-separated layer thicknesses in MILLIMETERS")
    parser.add_argument("--output", required=True, help="Output soil file path")

    args = parser.parse_args()
    layers = validate_inputs(args)
    n_layers = process(args, layers)
    validate_outputs(args.output, layers)
    print(f"Wrote {n_layers} soil layers to {args.output}")


if __name__ == "__main__":
    main()
