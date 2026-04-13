#!/usr/bin/env python3
"""
convert_soil_params.py — Convert soil/rock properties to pyBadlands erodibility layers.

Converts HWSD (Harmonized World Soil Database) or lithological data into erodibility
layer specifications for the pyBadlands <erocoeff> and <creep> XML sections.

Mapping logic:
    - Rock type → SPL erodibility coefficient (Kd)
    - Soil texture → hillslope diffusion coefficient (κ)
    - Lithology → layer thickness and spatial erodibility maps

CRITICAL:
    - Kd has units m^(1-2m)/year — depends on SPL m exponent
    - Diffusion coefficients in m²/year (NOT m²/kyr)
    - Literature Kd values assume specific m,n — verify before use

Usage:
    python convert_soil_params.py --input hwsd_extract.csv \\
        --output erodibility_layers.json \\
        --spl-m 0.5 --spl-n 1.0

    python convert_soil_params.py --input lithology_map.csv \\
        --output erodibility_layers.json \\
        --mode lithology --spl-m 0.5 --spl-n 1.0
"""

import argparse
import json
import os
import sys
import numpy as np


# ---------------------------------------------------------------------------
# Rock/soil type to erodibility mapping tables
# ---------------------------------------------------------------------------

# SPL erodibility Kd (m^(1-2m)/year) for m=0.5, n=1.0
# Sources: Stock & Montgomery 1999, Whipple & Tucker 1999
LITHOLOGY_KD = {
    "granite":       1.0e-7,
    "gneiss":        2.0e-7,
    "basalt":        5.0e-7,
    "limestone":     1.0e-6,
    "sandstone":     5.0e-6,
    "shale":         1.0e-5,
    "mudstone":      2.0e-5,
    "alluvium":      5.0e-5,
    "unconsolidated": 1.0e-4,
    "loess":         8.0e-5,
    "volcanic_ash":  3.0e-5,
    "quartzite":     5.0e-8,
    "marble":        3.0e-7,
    "schist":        4.0e-7,
    "slate":         3.0e-7,
}

# Hillslope diffusion κ (m²/year)
# Sources: Fernandes & Dietrich 1997, Roering et al. 1999
LITHOLOGY_KAPPA = {
    "granite":       0.001,
    "gneiss":        0.002,
    "basalt":        0.005,
    "limestone":     0.01,
    "sandstone":     0.02,
    "shale":         0.05,
    "mudstone":      0.08,
    "alluvium":      0.1,
    "unconsolidated": 0.5,
    "loess":         0.3,
    "volcanic_ash":  0.2,
    "quartzite":     0.0005,
    "marble":        0.003,
    "schist":        0.005,
    "slate":         0.004,
}

# HWSD soil texture to approximate erodibility
HWSD_TEXTURE_KD = {
    "Cl":   2.0e-5,   # Clay
    "SiCl": 3.0e-5,   # Silty clay
    "SaCl": 4.0e-5,   # Sandy clay
    "ClLo": 5.0e-5,   # Clay loam
    "SiClLo": 4.0e-5, # Silty clay loam
    "SaClLo": 6.0e-5, # Sandy clay loam
    "Lo":   7.0e-5,    # Loam
    "SiLo": 6.0e-5,   # Silt loam
    "SaLo": 8.0e-5,   # Sandy loam
    "Si":   5.0e-5,    # Silt
    "LoSa": 9.0e-5,   # Loamy sand
    "Sa":   1.0e-4,    # Sand
}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_inputs(args):
    """Validate inputs and fail fast."""
    errors = []

    if not os.path.isfile(args.input):
        errors.append(f"Input file not found: {args.input}")

    if args.spl_m <= 0 or args.spl_m > 2:
        errors.append(f"SPL m exponent out of range: {args.spl_m}. Expected 0 < m <= 2.")

    if args.spl_n <= 0 or args.spl_n > 3:
        errors.append(f"SPL n exponent out of range: {args.spl_n}. Expected 0 < n <= 3.")

    if args.mode not in ("hwsd", "lithology"):
        errors.append(f"Unknown mode: {args.mode}. Must be 'hwsd' or 'lithology'.")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)


# ---------------------------------------------------------------------------
# Processors
# ---------------------------------------------------------------------------

def process_hwsd(input_path, spl_m, spl_n):
    """
    Process HWSD soil texture data into erodibility parameters.

    Input CSV format: x, y, texture_class
    Output: list of erodibility layers with spatial maps.
    """
    layers = []

    try:
        import csv
        with open(input_path, "r") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
    except Exception as e:
        return {"status": "error", "message": f"Failed to read HWSD CSV: {e}"}

    # Collect unique textures
    textures = set()
    for row in rows:
        tex = row.get("texture", row.get("TEXTURE", "Lo"))
        textures.add(tex)

    # Build layer for each texture class
    for tex in sorted(textures):
        kd = HWSD_TEXTURE_KD.get(tex, 5.0e-5)

        # Adjust Kd for different m values (reference is m=0.5)
        # Kd_new = Kd_ref * A^(m_ref - m_new) where A is characteristic area
        # For simplicity, use scaling factor
        if abs(spl_m - 0.5) > 0.01:
            kd *= 10 ** ((0.5 - spl_m) * 2)  # Approximate scaling

        layers.append({
            "texture_class": tex,
            "erodibility_Kd": kd,
            "units": f"m^(1-{2*spl_m})/year",
            "spl_m": spl_m,
            "spl_n": spl_n,
            "diffusion_aerial": 0.05,
            "diffusion_marine": 0.1,
        })

    return {
        "mode": "hwsd",
        "n_layers": len(layers),
        "layers": layers,
        "notes": [
            "Kd values are approximate; calibrate against observed denudation rates",
            f"Reference: m={spl_m}, n={spl_n}",
            "Diffusion coefficients are default estimates (m²/year)",
        ],
    }


def process_lithology(input_path, spl_m, spl_n):
    """
    Process lithology data into erodibility layers.

    Input CSV format: x, y, lithology_type [, thickness_m]
    Output: list of erodibility layers with Kd and κ values.
    """
    layers = []

    try:
        import csv
        with open(input_path, "r") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
    except Exception as e:
        return {"status": "error", "message": f"Failed to read lithology CSV: {e}"}

    # Collect unique lithologies
    lithologies = set()
    for row in rows:
        lith = row.get("lithology", row.get("LITHOLOGY", "sandstone")).lower()
        lithologies.add(lith)

    for lith in sorted(lithologies):
        kd = LITHOLOGY_KD.get(lith, 1.0e-5)
        kappa = LITHOLOGY_KAPPA.get(lith, 0.01)

        # Adjust for m exponent
        if abs(spl_m - 0.5) > 0.01:
            kd *= 10 ** ((0.5 - spl_m) * 2)

        layers.append({
            "lithology": lith,
            "erodibility_Kd": kd,
            "diffusion_aerial": kappa,
            "diffusion_marine": kappa * 2.0,
            "units_Kd": f"m^(1-{2*spl_m})/year",
            "units_kappa": "m²/year",
            "spl_m": spl_m,
            "spl_n": spl_n,
        })

    return {
        "mode": "lithology",
        "n_layers": len(layers),
        "layers": layers,
        "notes": [
            "Kd from Stock & Montgomery 1999, Whipple & Tucker 1999",
            "κ from Fernandes & Dietrich 1997, Roering et al. 1999",
            f"Reference: m={spl_m}, n={spl_n}",
            "CRITICAL: Kd units depend on m — adjust if m changes (dt_006)",
        ],
    }


def generate_xml_snippet(result):
    """Generate XML snippet for badlands config."""
    lines = []

    if result["n_layers"] > 1:
        lines.append(f"    <erocoeff>")
        lines.append(f"        <erolayers>{result['n_layers']}</erolayers>")
        for i, layer in enumerate(result["layers"]):
            lines.append(f"        <erolay>")
            lines.append(f"            <erocst>{layer['erodibility_Kd']:.2e}</erocst>")
            lines.append(f"            <thcst>50.0</thcst>")
            lines.append(f"        </erolay>")
        lines.append(f"    </erocoeff>")
    else:
        layer = result["layers"][0]
        lines.append(f"    <erosion>")
        lines.append(f"        <SPLero>{layer['erodibility_Kd']:.2e}</SPLero>")
        lines.append(f"        <SPLm>{layer.get('spl_m', 0.5)}</SPLm>")
        lines.append(f"        <SPLn>{layer.get('spl_n', 1.0)}</SPLn>")
        lines.append(f"    </erosion>")

    lines.append("")
    lines.append(f"    <creep>")
    kappa_a = result["layers"][0].get("diffusion_aerial", 0.01)
    kappa_m = result["layers"][0].get("diffusion_marine", 0.05)
    lines.append(f"        <caerial>{kappa_a}</caerial>")
    lines.append(f"        <cmarine>{kappa_m}</cmarine>")
    lines.append(f"    </creep>")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def process(args):
    """Route to appropriate processor."""
    if args.mode == "hwsd":
        result = process_hwsd(args.input, args.spl_m, args.spl_n)
    else:
        result = process_lithology(args.input, args.spl_m, args.spl_n)

    # Generate XML snippet
    if result.get("n_layers", 0) > 0:
        result["xml_snippet"] = generate_xml_snippet(result)

    return result


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--input", required=True,
                        help="Path to soil/lithology CSV")
    parser.add_argument("--output", required=True,
                        help="Path to output JSON")
    parser.add_argument("--mode", default="lithology",
                        choices=["hwsd", "lithology"],
                        help="Input data type (default: lithology)")
    parser.add_argument("--spl-m", dest="spl_m", type=float, default=0.5,
                        help="SPL discharge exponent m (default: 0.5)")
    parser.add_argument("--spl-n", dest="spl_n", type=float, default=1.0,
                        help="SPL slope exponent n (default: 1.0)")

    args = parser.parse_args()
    validate_inputs(args)
    result = process(args)

    with open(args.output, "w") as f:
        json.dump(result, f, indent=2)

    print(json.dumps({"status": "success", "output": args.output}))


if __name__ == "__main__":
    main()
