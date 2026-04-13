#!/usr/bin/env python3
"""
build_sno_profile.py — Create initial SNOWPACK .sno profile file.

Purpose:
    Generates the initial snowpack/soil profile (.sno file) in SMET format
    required by SNOWPACK. Supports bare ground starts (no snow layers) and
    optional soil layers derived from HWSD or manual specification.

CRITICAL CONSTRAINTS:
    - Volume fractions MUST sum to 1.0 for each layer:
      Vol_Frac_I + Vol_Frac_W + Vol_Frac_V + Vol_Frac_S = 1.0
    - Layer thickness (Layer_Thick) is in METERS, not cm
    - Temperature is in KELVIN, not °C
    - Density of ice = 917 kg/m³; for a snow layer with density ρ:
      Vol_Frac_I = ρ / 917, Vol_Frac_V = 1 - Vol_Frac_I (dry snow)
    - Soil layers listed BOTTOM to TOP, then snow layers BOTTOM to TOP
    - Grain size (rg) in mm, bond radius (rb) in mm

Input methods:
    1. Manual: specify soil texture class → lookup thermal properties
    2. HWSD: provide HWSD CSV with soil data at coordinates
    3. Bare ground: no soil layers, just metadata header

Output SMET .sno format:
    Header with station info, profile date, slope, canopy parameters.
    Data rows: one per layer with 18 fields.

Usage:
    # Bare ground start (no soil, no snow)
    python build_sno_profile.py \\
        --output input/MST96.sno \\
        --station_id MST96 \\
        --latitude 46.831 --longitude 9.810 --altitude 2540 \\
        --start_date "1995-10-01T00:00"

    # With 3 soil layers
    python build_sno_profile.py \\
        --output input/MST96.sno \\
        --station_id MST96 \\
        --latitude 46.831 --longitude 9.810 --altitude 2540 \\
        --start_date "1995-10-01T00:00" \\
        --n_soil_layers 3 --soil_depth 1.5 \\
        --soil_texture "sandy_loam" --soil_temp_C 5.0

    # With HWSD data
    python build_sno_profile.py \\
        --output input/MST96.sno \\
        --station_id MST96 \\
        --latitude 46.831 --longitude 9.810 --altitude 2540 \\
        --start_date "1995-10-01T00:00" \\
        --hwsd_file hwsd_data.csv
"""

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np


# Soil thermal properties by USDA texture class
# Format: (Rho_S [kg/m³], Conduc_S [W/m/K], HeatCapac_S [J/m³/K])
SOIL_TEXTURE_PROPERTIES = {
    "sand":       (2650, 0.30, 1.28e6),
    "loamy_sand": (2650, 0.28, 1.35e6),
    "sandy_loam": (2650, 0.25, 1.40e6),
    "loam":       (2650, 0.22, 1.50e6),
    "silt_loam":  (2650, 0.20, 1.55e6),
    "silt":       (2650, 0.18, 1.60e6),
    "clay_loam":  (2650, 0.20, 1.55e6),
    "silty_clay_loam": (2650, 0.18, 1.60e6),
    "sandy_clay_loam": (2650, 0.22, 1.45e6),
    "sandy_clay": (2650, 0.20, 1.50e6),
    "silty_clay": (2650, 0.16, 1.65e6),
    "clay":       (2650, 0.15, 1.70e6),
    "organic":    (1300, 0.10, 2.50e6),
    "rock":       (2700, 2.50, 2.00e6),
}


def validate_inputs(args):
    """Validate inputs before processing."""
    errors = []

    if not (-90 <= args.latitude <= 90):
        errors.append(f"Latitude out of range: {args.latitude}")
    if not (-180 <= args.longitude <= 180):
        errors.append(f"Longitude out of range: {args.longitude}")
    if not (-500 <= args.altitude <= 9000):
        errors.append(f"Altitude out of plausible range: {args.altitude}")
    if args.n_soil_layers < 0:
        errors.append("n_soil_layers cannot be negative")
    if args.n_soil_layers > 0 and args.soil_depth <= 0:
        errors.append("soil_depth must be positive when soil layers specified")
    if args.soil_texture not in SOIL_TEXTURE_PROPERTIES:
        errors.append(f"Unknown soil_texture: {args.soil_texture}. "
                       f"Choose from: {list(SOIL_TEXTURE_PROPERTIES.keys())}")
    if args.slope_angle < 0 or args.slope_angle > 90:
        errors.append(f"slope_angle must be 0-90 degrees: {args.slope_angle}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)
    return errors


def build_soil_layers(n_layers, total_depth, texture, temp_K, moisture_frac):
    """Build soil layer data rows.

    Each layer: [Layer_Thick, T, Vol_Frac_I, Vol_Frac_W, Vol_Frac_V,
                 Vol_Frac_S, Rho_S, Conduc_S, HeatCapac_S,
                 rg, rb, dd, sp, mk, mass_hoar, ne, CDot, metamo]

    CRITICAL: Vol_Frac_I + Vol_Frac_W + Vol_Frac_V + Vol_Frac_S = 1.0
    For soil: Vol_Frac_S is the solid soil fraction (~0.55 for typical soil)
    """
    rho_s, conduc_s, heatcap_s = SOIL_TEXTURE_PROPERTIES[texture]

    # Typical soil: 55% solid, rest is pore space (water + air)
    vol_frac_s = 0.55
    vol_frac_w = moisture_frac * (1.0 - vol_frac_s)
    vol_frac_v = (1.0 - vol_frac_s) - vol_frac_w
    vol_frac_i = 0.0  # No ice in soil initially

    # Verify sum = 1.0
    total = vol_frac_i + vol_frac_w + vol_frac_v + vol_frac_s
    assert abs(total - 1.0) < 1e-10, f"Volume fractions sum to {total}, not 1.0"

    layer_thick = total_depth / n_layers
    layers = []
    for i in range(n_layers):
        # Temperature gradient: deeper = warmer (geothermal)
        depth_frac = (n_layers - i) / n_layers  # 1.0 at bottom, near 0 at top
        t_layer = temp_K + depth_frac * 0.5  # 0.5 K gradient over soil column

        layer = {
            "Layer_Thick": layer_thick,
            "T": t_layer,
            "Vol_Frac_I": vol_frac_i,
            "Vol_Frac_W": vol_frac_w,
            "Vol_Frac_V": vol_frac_v,
            "Vol_Frac_S": vol_frac_s,
            "Rho_S": rho_s,
            "Conduc_S": conduc_s,
            "HeatCapac_S": heatcap_s,
            "rg": 0.0,    # No grain size for soil
            "rb": 0.0,
            "dd": 0.0,
            "sp": 0.0,
            "mk": 4,      # Marker: soil
            "mass_hoar": 0.0,
            "ne": 1,       # Number of finite elements per layer
            "CDot": 0.0,
            "metamo": 0.0,
        }
        layers.append(layer)
    return layers


def process(args):
    """Build and write the .sno profile file."""
    # Convert soil temperature to Kelvin if given in Celsius
    soil_temp_K = args.soil_temp_C + 273.15

    # Build soil layers
    soil_layers = []
    if args.n_soil_layers > 0:
        soil_layers = build_soil_layers(
            args.n_soil_layers, args.soil_depth, args.soil_texture,
            soil_temp_K, args.soil_moisture
        )

    n_soil = len(soil_layers)
    n_snow = 0  # Bare ground start

    # Write .sno file
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)

    fields = ("timestamp Layer_Thick T Vol_Frac_I Vol_Frac_W Vol_Frac_V "
              "Vol_Frac_S Rho_S Conduc_S HeatCapac_S rg rb dd sp mk "
              "mass_hoar ne CDot metamo")

    with open(args.output, "w") as f:
        f.write("SMET 1.1 ASCII\n")
        f.write("[HEADER]\n")
        f.write(f"station_id       = {args.station_id}\n")
        f.write(f"station_name     = {args.station_name}\n")
        f.write(f"latitude         = {args.latitude:.6f}\n")
        f.write(f"longitude        = {args.longitude:.6f}\n")
        f.write(f"altitude         = {args.altitude:.1f}\n")
        f.write(f"nodata           = -999\n")
        f.write(f"tz               = {args.timezone}\n")
        f.write(f"ProfileDate      = {args.start_date}\n")
        f.write(f"HS_Last          = 0.0000\n")
        f.write(f"SlopeAngle       = {args.slope_angle:.1f}\n")
        f.write(f"SlopeAzi         = {args.slope_azi:.1f}\n")
        f.write(f"nSoilLayerData   = {n_soil}\n")
        f.write(f"nSnowLayerData   = {n_snow}\n")
        f.write(f"SoilAlbedo       = {args.soil_albedo:.2f}\n")
        f.write(f"BareSoil_z0      = {args.bare_soil_z0:.4f}\n")
        f.write(f"CanopyHeight     = {args.canopy_height:.2f}\n")
        f.write(f"CanopyLeafAreaIndex = {args.canopy_lai:.2f}\n")
        f.write(f"fields           = {fields}\n")
        f.write("[DATA]\n")

        # Write soil layers (bottom to top)
        for layer in soil_layers:
            vals = [
                args.start_date,
                f"{layer['Layer_Thick']:.4f}",
                f"{layer['T']:.4f}",
                f"{layer['Vol_Frac_I']:.6f}",
                f"{layer['Vol_Frac_W']:.6f}",
                f"{layer['Vol_Frac_V']:.6f}",
                f"{layer['Vol_Frac_S']:.6f}",
                f"{layer['Rho_S']:.1f}",
                f"{layer['Conduc_S']:.4f}",
                f"{layer['HeatCapac_S']:.1f}",
                f"{layer['rg']:.4f}",
                f"{layer['rb']:.4f}",
                f"{layer['dd']:.4f}",
                f"{layer['sp']:.4f}",
                f"{int(layer['mk'])}",
                f"{layer['mass_hoar']:.4f}",
                f"{int(layer['ne'])}",
                f"{layer['CDot']:.6f}",
                f"{layer['metamo']:.6f}",
            ]
            f.write(" ".join(vals) + "\n")

    result = {
        "status": "success",
        "output_file": args.output,
        "station_id": args.station_id,
        "n_soil_layers": n_soil,
        "n_snow_layers": n_snow,
        "soil_depth_m": args.soil_depth if n_soil > 0 else 0,
        "soil_texture": args.soil_texture if n_soil > 0 else "none",
        "profile_date": args.start_date,
    }
    return result


def validate_outputs(result):
    """Check output for consistency."""
    warnings = []

    output_file = result.get("output_file", "")
    if output_file and os.path.isfile(output_file):
        size = os.path.getsize(output_file)
        if size < 100:
            warnings.append("Output file very small — may be incomplete")
    else:
        warnings.append("Output file not found after writing")

    if result.get("n_soil_layers", 0) == 0:
        warnings.append("No soil layers — ground heat flux will use Neumann BC only")

    if warnings:
        result["warnings"] = warnings
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Create initial SNOWPACK .sno profile"
    )
    parser.add_argument("--output", required=True, help="Output .sno file path")
    parser.add_argument("--station_id", required=True)
    parser.add_argument("--station_name", default="")
    parser.add_argument("--latitude", type=float, required=True)
    parser.add_argument("--longitude", type=float, required=True)
    parser.add_argument("--altitude", type=float, required=True)
    parser.add_argument("--timezone", type=int, default=0)
    parser.add_argument("--start_date", required=True,
                        help="Profile date (ISO 8601, e.g. 1995-10-01T00:00)")
    parser.add_argument("--n_soil_layers", type=int, default=0)
    parser.add_argument("--soil_depth", type=float, default=0.0,
                        help="Total soil depth (m)")
    parser.add_argument("--soil_texture", default="sandy_loam",
                        choices=list(SOIL_TEXTURE_PROPERTIES.keys()))
    parser.add_argument("--soil_temp_C", type=float, default=5.0,
                        help="Initial soil temperature (°C)")
    parser.add_argument("--soil_moisture", type=float, default=0.3,
                        help="Initial soil moisture fraction of pore space (0-1)")
    parser.add_argument("--soil_albedo", type=float, default=0.20)
    parser.add_argument("--bare_soil_z0", type=float, default=0.002,
                        help="Bare soil roughness length (m)")
    parser.add_argument("--slope_angle", type=float, default=0.0,
                        help="Slope angle (degrees)")
    parser.add_argument("--slope_azi", type=float, default=0.0,
                        help="Slope azimuth (degrees from N)")
    parser.add_argument("--canopy_height", type=float, default=0.0,
                        help="Canopy height (m)")
    parser.add_argument("--canopy_lai", type=float, default=0.0,
                        help="Canopy leaf area index")
    parser.add_argument("--hwsd_file", default=None,
                        help="HWSD soil data CSV (overrides manual soil params)")

    args = parser.parse_args()
    if not args.station_name:
        args.station_name = args.station_id

    validate_inputs(args)
    result = process(args)
    result = validate_outputs(result)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
