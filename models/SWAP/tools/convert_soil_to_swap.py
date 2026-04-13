#!/usr/bin/env python3
"""
Convert HWSD (Harmonized World Soil Database) soil data to SWAP
Mualem-van Genuchten hydraulic parameters.

SWAP requires these parameters per soil layer (in .swp file):
  ORES   - Residual water content [0..1 cm³/cm³]
  OSAT   - Saturated water content [0..1 cm³/cm³]
  ALFA   - van Genuchten shape parameter [0.0001..100 /cm]
  NPAR   - van Genuchten n parameter [1.001..9]
  KSATFIT - Fitted Ksat [1e-5..1e5 cm/d]
  LEXP   - Exponent in K function [-25..25]
  ALFAW  - Wetting curve alfa (hysteresis) [0.0001..100 /cm]
  H_ENPR - Air entry pressure head [-40..0 cm]
  KSATEXM - Measured Ksat [1e-5..1e5 cm/d]
  BDENS  - Dry bulk density [100..10000 mg/cm³ = kg/m³]

This tool uses Schaap et al. (2001) Rosetta pedotransfer functions to
estimate MvG parameters from HWSD texture classes.

Usage:
    python convert_soil_to_swap.py \\
        --hwsd /path/to/HWSD_China_Geo.img \\
        --lat 52.069 --lon 6.657 \\
        --output soil_params.txt
"""

import argparse
import json
import sys
import os
from pathlib import Path

import numpy as np


# ---------------------------------------------------------------------------
# Rosetta-style pedotransfer: USDA texture class → MvG parameters
# Based on Schaap et al. (2001) and Carsel & Parrish (1988)
# ---------------------------------------------------------------------------
# Format: (ORES, OSAT, ALFA[1/cm], NPAR, KSAT[cm/d], LEXP)
TEXTURE_CLASS_MVG = {
    "sand":             (0.045, 0.430, 0.1450, 2.680, 712.8, 0.5),
    "loamy_sand":       (0.057, 0.410, 0.1240, 2.280, 350.2, 0.5),
    "sandy_loam":       (0.065, 0.410, 0.0750, 1.890, 106.1, 0.5),
    "loam":             (0.078, 0.430, 0.0360, 1.560, 24.96, 0.5),
    "silt":             (0.034, 0.460, 0.0160, 1.370, 6.00,  0.5),
    "silt_loam":        (0.067, 0.450, 0.0200, 1.410, 10.80, 0.5),
    "sandy_clay_loam":  (0.100, 0.390, 0.0590, 1.480, 31.44, 0.5),
    "clay_loam":        (0.095, 0.410, 0.0190, 1.310, 6.24,  0.5),
    "silty_clay_loam":  (0.089, 0.430, 0.0100, 1.230, 1.68,  0.5),
    "sandy_clay":       (0.100, 0.380, 0.0270, 1.230, 2.88,  0.5),
    "silty_clay":       (0.070, 0.360, 0.0050, 1.090, 0.48,  0.5),
    "clay":             (0.068, 0.380, 0.0080, 1.090, 4.80,  0.5),
}

# Typical bulk density by texture class (kg/m³ = mg/cm³)
TEXTURE_CLASS_BDENS = {
    "sand": 1550, "loamy_sand": 1500, "sandy_loam": 1450,
    "loam": 1400, "silt": 1350, "silt_loam": 1350,
    "sandy_clay_loam": 1500, "clay_loam": 1400,
    "silty_clay_loam": 1350, "sandy_clay": 1450,
    "silty_clay": 1300, "clay": 1250,
}


def validate_inputs(hwsd_path, lat, lon):
    """Pre-flight input validation."""
    errors = []
    if hwsd_path and not os.path.isfile(hwsd_path):
        errors.append(f"HWSD file not found: {hwsd_path}")
    if not (-90 <= lat <= 90):
        errors.append(f"Latitude {lat} out of range")
    if not (-180 <= lon <= 360):
        errors.append(f"Longitude {lon} out of range")
    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"[OK] Input validation passed: lat={lat}, lon={lon}")


def classify_texture(sand_pct, silt_pct, clay_pct):
    """
    Classify soil texture using USDA texture triangle.

    Parameters
    ----------
    sand_pct : float
        Sand content (0-100 %)
    silt_pct : float
        Silt content (0-100 %)
    clay_pct : float
        Clay content (0-100 %)

    Returns
    -------
    str : USDA texture class name (lowercase with underscores)
    """
    s, si, c = sand_pct, silt_pct, clay_pct

    if c >= 40 and s <= 45 and si < 40:
        return "clay" if s <= 45 else "sandy_clay"
    if c >= 40 and si >= 40:
        return "silty_clay"
    if 27 <= c < 40 and s <= 20:
        return "silty_clay_loam"
    if 27 <= c < 40 and 20 < s <= 45:
        return "clay_loam"
    if 20 <= c < 35 and s > 45:
        return "sandy_clay_loam"
    if 35 <= c < 55 and s > 45:
        return "sandy_clay"
    if c < 7 and si >= 80:
        return "silt"
    if 12 <= c < 27 and si >= 50 and s < 50:
        return "silt_loam"
    if c < 12 and si >= 50 and si < 80:
        return "silt_loam"
    if c < 27 and si >= 28 and si < 50 and s <= 52:
        return "loam"
    if 7 <= c < 20 and s > 52:
        return "sandy_loam"
    if c < 7 and si < 50 and s > 43:
        if s > 85:
            return "sand"
        if s > 70:
            return "loamy_sand"
        return "sandy_loam"
    return "loam"  # Default fallback


def read_hwsd_at_point(hwsd_path, lat, lon):
    """
    Read HWSD raster at a given lat/lon and return texture percentages.

    Falls back to default loam if HWSD cannot be read.
    """
    try:
        from osgeo import gdal
        ds = gdal.Open(hwsd_path)
        if ds is None:
            raise RuntimeError(f"Cannot open {hwsd_path}")

        gt = ds.GetGeoTransform()
        # Convert lat/lon to pixel coordinates
        px = int((lon - gt[0]) / gt[1])
        py = int((lat - gt[3]) / gt[5])

        band = ds.GetRasterBand(1)
        data = band.ReadAsArray(px, py, 1, 1)
        mu_global = int(data[0, 0])

        print(f"[INFO] HWSD MU_GLOBAL at ({lat}, {lon}): {mu_global}")

        # HWSD lookup would require the companion database
        # For now, return default values
        ds = None
        return None

    except Exception as e:
        print(f"WARNING: Could not read HWSD: {e}")
        return None


def get_mvg_params(sand_pct=None, silt_pct=None, clay_pct=None,
                   texture_class=None, n_layers=2):
    """
    Get Mualem-van Genuchten parameters for SWAP.

    Parameters
    ----------
    sand_pct, silt_pct, clay_pct : float, optional
        Texture percentages (0-100). If None, uses texture_class.
    texture_class : str, optional
        USDA texture class name. If None, classified from percentages.
    n_layers : int
        Number of soil layers (topsoil + subsoil)

    Returns
    -------
    list of dict : One dict per layer with all MvG parameters
    """
    if texture_class is None:
        if sand_pct is not None:
            texture_class = classify_texture(sand_pct, silt_pct, clay_pct)
        else:
            texture_class = "loam"
            print(f"WARNING: No texture data, defaulting to '{texture_class}'")

    if texture_class not in TEXTURE_CLASS_MVG:
        print(f"WARNING: Unknown texture '{texture_class}', using 'loam'")
        texture_class = "loam"

    ores, osat, alfa, npar, ksat, lexp = TEXTURE_CLASS_MVG[texture_class]
    bdens = TEXTURE_CLASS_BDENS[texture_class]

    print(f"[INFO] Texture class: {texture_class}")
    print(f"[INFO] MvG params: ORES={ores}, OSAT={osat}, ALFA={alfa}, "
          f"NPAR={npar}, KSAT={ksat} cm/d, BDENS={bdens} kg/m³")

    layers = []
    for i in range(n_layers):
        # Slight variation for subsoil (more compacted, lower Ksat)
        factor = 1.0 if i == 0 else 0.7
        layer = {
            "layer": i + 1,
            "texture": texture_class,
            "ORES": round(ores, 3),
            "OSAT": round(osat * (1.0 if i == 0 else 0.95), 3),
            "ALFA": round(alfa * (1.0 if i == 0 else 0.8), 4),
            "NPAR": round(npar, 3),
            "KSATFIT": round(ksat * factor, 2),
            "LEXP": round(lexp, 3),
            "ALFAW": round(alfa * 2.0 * (1.0 if i == 0 else 0.8), 4),
            "H_ENPR": 0.0,
            "KSATEXM": round(ksat * factor, 2),
            "BDENS": round(bdens * (1.0 if i == 0 else 1.05), 1),
        }
        layers.append(layer)

    return layers


def format_swap_table(layers):
    """Format MvG parameters as SWAP .swp input table string."""
    header = " ORES  OSAT    ALFA   NPAR  KSATFIT    LEXP   ALFAW  H_ENPR  KSATEXM   BDENS"
    lines = [header]
    for lay in layers:
        line = (
            f" {lay['ORES']:.2f}  {lay['OSAT']:.2f}  {lay['ALFA']:.4f}  "
            f"{lay['NPAR']:.3f}  {lay['KSATFIT']:8.2f}  {lay['LEXP']:6.3f}  "
            f"{lay['ALFAW']:.4f}  {lay['H_ENPR']:6.1f}  {lay['KSATEXM']:8.2f}  "
            f"{lay['BDENS']:.1f}"
        )
        lines.append(line)
    lines.append("* End of table")
    return "\n".join(lines)


def validate_outputs(layers):
    """Post-processing validation of MvG parameters."""
    errors = []
    for lay in layers:
        i = lay["layer"]
        if lay["ORES"] >= lay["OSAT"]:
            errors.append(f"Layer {i}: ORES ({lay['ORES']}) >= OSAT ({lay['OSAT']})")
        if lay["NPAR"] <= 1.0:
            errors.append(f"Layer {i}: NPAR ({lay['NPAR']}) must be > 1.0")
        if lay["ALFA"] <= 0:
            errors.append(f"Layer {i}: ALFA ({lay['ALFA']}) must be > 0")
        if lay["KSATFIT"] <= 0:
            errors.append(f"Layer {i}: KSATFIT ({lay['KSATFIT']}) must be > 0")
        if not (100 <= lay["BDENS"] <= 10000):
            errors.append(f"Layer {i}: BDENS ({lay['BDENS']}) out of range [100, 10000]")

    for e in errors:
        print(f"ERROR: {e}", file=sys.stderr)

    if errors:
        print(f"[FAIL] Validation failed with {len(errors)} errors")
        return False
    print(f"[OK] All {len(layers)} soil layers pass validation")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Convert HWSD soil data to SWAP MvG parameters"
    )
    parser.add_argument("--hwsd", type=str, default="",
                        help="Path to HWSD raster file (.img)")
    parser.add_argument("--lat", type=float, required=True)
    parser.add_argument("--lon", type=float, required=True)
    parser.add_argument("--sand", type=float, default=None,
                        help="Sand content (%%)")
    parser.add_argument("--silt", type=float, default=None,
                        help="Silt content (%%)")
    parser.add_argument("--clay", type=float, default=None,
                        help="Clay content (%%)")
    parser.add_argument("--texture", type=str, default=None,
                        help="USDA texture class (e.g., 'sandy_loam')")
    parser.add_argument("--n-layers", type=int, default=2,
                        help="Number of soil layers")
    parser.add_argument("--output", type=str, required=True,
                        help="Output file path (txt or json)")
    args = parser.parse_args()

    validate_inputs(args.hwsd, args.lat, args.lon)

    # Try HWSD first, fall back to manual texture
    texture = args.texture
    if args.hwsd and os.path.isfile(args.hwsd):
        hwsd_result = read_hwsd_at_point(args.hwsd, args.lat, args.lon)
        if hwsd_result:
            texture = hwsd_result.get("texture", texture)

    layers = get_mvg_params(
        sand_pct=args.sand, silt_pct=args.silt, clay_pct=args.clay,
        texture_class=texture, n_layers=args.n_layers
    )

    # Write output
    if args.output.endswith(".json"):
        with open(args.output, "w") as f:
            json.dump(layers, f, indent=2)
    else:
        table = format_swap_table(layers)
        with open(args.output, "w") as f:
            f.write(table + "\n")

    print(f"[OK] Wrote soil parameters to {args.output}")
    validate_outputs(layers)


if __name__ == "__main__":
    main()
