#!/usr/bin/env python3
"""
Convert soil/sediment data to HAIL-CAESAR grain size distribution format.

Sources supported:
  - HWSD (Harmonized World Soil Database) soil texture classes
  - Manual specification of grain fractions
  - CSV with sand/silt/clay percentages

HAIL-CAESAR uses 9 grain size fractions (d1-d9):
  d1 = 0.065 mm (silt/fine sand)
  d2 = 1.0 mm
  d3 = 2.0 mm
  d4 = 4.0 mm
  d5 = 8.0 mm
  d6 = 16.0 mm
  d7 = 32.0 mm
  d8 = 64.0 mm
  d9 = 128.0 mm

The default grain distribution (Swale catchment) is:
  dprop = [0.05, 0.05, 0.15, 0.225, 0.25, 0.1, 0.075, 0.05, 0.05]

Output: Grain data text file for HAIL-CAESAR, or parameter recommendations.

Usage:
    python convert_soil_to_caesar.py \\
        --mode texture \\
        --sand_pct 45 --silt_pct 30 --clay_pct 25 \\
        --output grain_params.txt
"""

import argparse
import sys
import os
import numpy as np


# HAIL-CAESAR grain size diameters in mm
GRAIN_DIAMETERS_MM = [0.065, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 64.0, 128.0]

# Default distributions for common environments
DISTRIBUTIONS = {
    "swale": [0.05, 0.05, 0.15, 0.225, 0.25, 0.1, 0.075, 0.05, 0.05],
    "default_caesar": [0.144, 0.022, 0.019, 0.029, 0.068, 0.146, 0.22, 0.231, 0.121],
    "gravel_bed": [0.02, 0.03, 0.05, 0.10, 0.15, 0.20, 0.20, 0.15, 0.10],
    "sandy": [0.30, 0.25, 0.15, 0.10, 0.08, 0.05, 0.04, 0.02, 0.01],
    "mountain": [0.01, 0.02, 0.03, 0.05, 0.10, 0.15, 0.20, 0.24, 0.20],
    "lowland_alluvial": [0.15, 0.15, 0.15, 0.15, 0.12, 0.10, 0.08, 0.06, 0.04],
}

# USDA texture class to approximate grain distributions
TEXTURE_TO_DIST = {
    "sand": [0.35, 0.25, 0.15, 0.10, 0.06, 0.04, 0.03, 0.01, 0.01],
    "loamy_sand": [0.28, 0.22, 0.15, 0.12, 0.08, 0.06, 0.05, 0.02, 0.02],
    "sandy_loam": [0.22, 0.18, 0.15, 0.13, 0.10, 0.08, 0.07, 0.04, 0.03],
    "loam": [0.15, 0.15, 0.14, 0.13, 0.12, 0.10, 0.09, 0.07, 0.05],
    "silt_loam": [0.20, 0.18, 0.15, 0.12, 0.10, 0.08, 0.07, 0.06, 0.04],
    "silt": [0.30, 0.20, 0.14, 0.10, 0.08, 0.07, 0.05, 0.04, 0.02],
    "sandy_clay_loam": [0.18, 0.15, 0.13, 0.12, 0.11, 0.10, 0.09, 0.07, 0.05],
    "clay_loam": [0.12, 0.12, 0.12, 0.12, 0.12, 0.12, 0.10, 0.10, 0.08],
    "silty_clay_loam": [0.15, 0.14, 0.13, 0.12, 0.11, 0.10, 0.09, 0.08, 0.08],
    "sandy_clay": [0.15, 0.13, 0.12, 0.12, 0.11, 0.11, 0.10, 0.09, 0.07],
    "silty_clay": [0.18, 0.15, 0.13, 0.11, 0.10, 0.10, 0.09, 0.08, 0.06],
    "clay": [0.10, 0.10, 0.11, 0.12, 0.12, 0.12, 0.12, 0.11, 0.10],
}


def validate_input(fractions: list) -> None:
    """Validate grain size fractions sum to ~1.0."""
    total = sum(fractions)
    if abs(total - 1.0) > 0.01:
        raise ValueError(
            f"Grain fractions sum to {total:.4f}, expected ~1.0. "
            f"Fractions: {fractions}"
        )
    if any(f < 0 for f in fractions):
        raise ValueError(f"Negative grain fractions found: {fractions}")
    if len(fractions) != 9:
        raise ValueError(f"Expected 9 grain fractions, got {len(fractions)}")


def texture_to_fractions(sand_pct: float, silt_pct: float, clay_pct: float) -> list:
    """Convert sand/silt/clay percentages to 9 grain size fractions.

    Uses USDA texture triangle classification, then maps to HAIL-CAESAR fractions.
    """
    total = sand_pct + silt_pct + clay_pct
    if abs(total - 100.0) > 1.0:
        raise ValueError(f"Sand+Silt+Clay = {total}%, expected ~100%")

    # Classify into USDA texture class
    if clay_pct >= 40:
        if silt_pct >= 40:
            texture = "silty_clay"
        elif sand_pct >= 45:
            texture = "sandy_clay"
        else:
            texture = "clay"
    elif clay_pct >= 27:
        if sand_pct >= 20 and sand_pct < 45:
            texture = "clay_loam"
        elif sand_pct >= 45:
            texture = "sandy_clay_loam"
        else:
            texture = "silty_clay_loam"
    elif silt_pct >= 80:
        texture = "silt"
    elif silt_pct >= 50:
        if clay_pct >= 12:
            texture = "silt_loam"
        else:
            texture = "silt_loam"
    elif sand_pct >= 85:
        texture = "sand"
    elif sand_pct >= 70:
        texture = "loamy_sand"
    elif sand_pct >= 50:
        texture = "sandy_loam"
    else:
        texture = "loam"

    print(f"Texture classification: {texture} (sand={sand_pct}%, silt={silt_pct}%, clay={clay_pct}%)")
    fractions = TEXTURE_TO_DIST[texture]

    # Fine-tune based on actual percentages
    fine_weight = (silt_pct + clay_pct) / 100.0
    fractions = list(fractions)  # copy
    # Shift weight toward finer fractions if high silt/clay
    for i in range(len(fractions)):
        if i < 3:
            fractions[i] *= (1.0 + 0.3 * fine_weight)
        else:
            fractions[i] *= (1.0 - 0.1 * fine_weight)

    # Renormalize
    total = sum(fractions)
    fractions = [f / total for f in fractions]

    return fractions


def recommend_parameters(fractions: list) -> dict:
    """Recommend HAIL-CAESAR parameters based on grain distribution."""
    d50_idx = 0
    cumsum = 0
    for i, f in enumerate(fractions):
        cumsum += f
        if cumsum >= 0.5:
            d50_idx = i
            break

    d50_mm = GRAIN_DIAMETERS_MM[d50_idx]
    print(f"Estimated D50: {d50_mm} mm (fraction index {d50_idx + 1})")

    recommendations = {
        "transport_law": "wilcock" if d50_mm > 2.0 else "einstein",
        "active_layer_thickness": max(0.1, d50_mm * 3 / 1000),
        "erode_limit": 0.01 if d50_mm < 10 else 0.02,
        "suspended_sediment_on": "yes" if fractions[0] > 0.1 else "no",
    }

    return recommendations


def write_grain_params(output_path: str, fractions: list, recommendations: dict) -> None:
    """Write grain distribution and parameter recommendations."""
    with open(output_path, "w") as f:
        f.write("# HAIL-CAESAR Grain Size Distribution\n")
        f.write("# Generated by convert_soil_to_caesar.py\n")
        f.write("#\n")
        f.write("# Grain diameters (mm): " +
                " ".join(f"{d}" for d in GRAIN_DIAMETERS_MM) + "\n")
        f.write("# Fractions (must sum to 1.0):\n")
        f.write("dprop: " + " ".join(f"{f:.4f}" for f in fractions) + "\n")
        f.write(f"# Sum: {sum(fractions):.6f}\n")
        f.write("#\n")
        f.write("# Recommended parameters:\n")
        for k, v in recommendations.items():
            f.write(f"# {k}: {v}\n")

    print(f"Written grain parameters to {output_path}")


def write_grain_data_file(output_path: str, ncols: int, nrows: int,
                          fractions: list) -> None:
    """Write a full grain data file for HAIL-CAESAR spatial grain input.

    Format: index x y [surface fractions x 9] [subsurface fractions x 9]
    """
    with open(output_path, "w") as f:
        idx = 0
        for i in range(nrows):
            for j in range(ncols):
                surface = " ".join(f"{frac:.4f}" for frac in fractions)
                subsurface = surface  # Same for uniform case
                f.write(f"{idx} {j} {i} {surface} {subsurface}\n")
                idx += 1

    print(f"Written spatial grain data: {nrows}x{ncols} cells to {output_path}")


def validate_output(output_path: str) -> None:
    """Validate the output file exists and is well-formed."""
    if not os.path.isfile(output_path):
        raise RuntimeError(f"Output file not created: {output_path}")
    if os.path.getsize(output_path) == 0:
        raise RuntimeError(f"Output file is empty: {output_path}")

    with open(output_path, "r") as f:
        for line in f:
            if line.startswith("dprop:"):
                vals = [float(x) for x in line.split(":")[1].strip().split()]
                if len(vals) != 9:
                    raise RuntimeError(f"Expected 9 fractions, got {len(vals)}")
                total = sum(vals)
                if abs(total - 1.0) > 0.01:
                    raise RuntimeError(f"Fractions sum to {total}, expected ~1.0")
                print(f"Validation passed: 9 fractions summing to {total:.4f}")
                return

    print("Validation: file written (spatial grain data format)")


def main():
    parser = argparse.ArgumentParser(
        description="Convert soil/sediment data to HAIL-CAESAR grain format"
    )
    parser.add_argument("--mode", default="texture",
                        choices=["texture", "preset", "manual", "spatial"],
                        help="Conversion mode")
    parser.add_argument("--output", required=True, help="Output file path")

    # Texture mode
    parser.add_argument("--sand_pct", type=float, help="Sand percentage (0-100)")
    parser.add_argument("--silt_pct", type=float, help="Silt percentage (0-100)")
    parser.add_argument("--clay_pct", type=float, help="Clay percentage (0-100)")

    # Preset mode
    parser.add_argument("--preset", default="swale",
                        choices=list(DISTRIBUTIONS.keys()),
                        help="Preset grain distribution name")

    # Manual mode
    parser.add_argument("--fractions", nargs=9, type=float,
                        help="9 grain fractions (must sum to 1.0)")

    # Spatial mode
    parser.add_argument("--ncols", type=int, help="DEM columns (for spatial mode)")
    parser.add_argument("--nrows", type=int, help="DEM rows (for spatial mode)")

    args = parser.parse_args()

    # Determine fractions based on mode
    if args.mode == "texture":
        if not all([args.sand_pct, args.silt_pct, args.clay_pct]):
            parser.error("Texture mode requires --sand_pct, --silt_pct, --clay_pct")
        fractions = texture_to_fractions(args.sand_pct, args.silt_pct, args.clay_pct)
    elif args.mode == "preset":
        fractions = DISTRIBUTIONS[args.preset]
        print(f"Using preset distribution: {args.preset}")
    elif args.mode == "manual":
        if not args.fractions:
            parser.error("Manual mode requires --fractions (9 values)")
        fractions = args.fractions
    elif args.mode == "spatial":
        if not args.fractions:
            fractions = DISTRIBUTIONS["swale"]
        else:
            fractions = args.fractions
        if not args.ncols or not args.nrows:
            parser.error("Spatial mode requires --ncols and --nrows")

    # Validate
    validate_input(fractions)

    # Process
    recommendations = recommend_parameters(fractions)

    # Write output
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)

    if args.mode == "spatial":
        write_grain_data_file(args.output, args.ncols, args.nrows, fractions)
    else:
        write_grain_params(args.output, fractions, recommendations)

    # Validate output
    validate_output(args.output)

    print("Done.")


if __name__ == "__main__":
    main()
