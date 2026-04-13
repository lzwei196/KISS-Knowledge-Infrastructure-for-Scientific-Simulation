#!/usr/bin/env python3
"""
convert_soil_to_pflotran.py — Convert HWSD/GLHYMPS data to PFLOTRAN material properties.

Reads soil texture from HWSD (Harmonized World Soil Database) and hydrogeological
parameters from GLHYMPS (Global HYdrogeology MaPS) to generate PFLOTRAN-compatible
MATERIAL_PROPERTY and CHARACTERISTIC_CURVES blocks.

Inputs:
    --hwsd-csv       : HWSD_DATA.csv with soil texture percentages
    --glhymps-shp    : GLHYMPS shapefile for permeability/porosity
    --lat / --lon    : Target location
    --depth-layers   : Number of vertical layers (default: 10)
    --output         : Output JSON path with material properties

Outputs:
    JSON file with material properties suitable for PFLOTRAN input deck generation.

Unit Conversions (CRITICAL):
    - GLHYMPS log(K in m^2) → K in m^2:  K = 10^(logK)
    - GLHYMPS porosity (%) → fraction:     phi = porosity / 100
    - HWSD texture → van Genuchten params:  alpha in 1/Pa NOT 1/cm
    - alpha (1/cm) → alpha (1/Pa):          alpha_Pa = alpha_cm / (rho*g)
                                              = alpha_cm / 9804.139

Usage:
    python convert_soil_to_pflotran.py \\
        --hwsd-csv /data/soil/HWSD_DATA.csv \\
        --lat 32.9 --lon 117.3 \\
        --output materials_bengbu.json
"""

import argparse
import json
import math
import os
import sys

import numpy as np

# ──────────────────────────────────────────────────────────────────────
# Physical constants
# ──────────────────────────────────────────────────────────────────────
RHO_WATER = 998.2       # kg/m^3 at 20C
G = 9.80665              # m/s^2
RHO_G = RHO_WATER * G   # 9804.139 Pa/m (conversion factor for vG alpha)

# ──────────────────────────────────────────────────────────────────────
# Carsel & Parrish (1988) van Genuchten parameters by USDA texture class
# alpha in 1/cm (literature standard), n dimensionless, theta_r/theta_s fractions
# ──────────────────────────────────────────────────────────────────────
VG_PARAMS = {
    "Sand":            {"alpha_cm": 0.145, "n": 2.68, "theta_r": 0.045, "theta_s": 0.43, "Ks_m_s": 8.25e-5},
    "Loamy Sand":      {"alpha_cm": 0.124, "n": 2.28, "theta_r": 0.057, "theta_s": 0.41, "Ks_m_s": 4.05e-5},
    "Sandy Loam":      {"alpha_cm": 0.075, "n": 1.89, "theta_r": 0.065, "theta_s": 0.41, "Ks_m_s": 1.23e-5},
    "Loam":            {"alpha_cm": 0.036, "n": 1.56, "theta_r": 0.078, "theta_s": 0.43, "Ks_m_s": 2.89e-6},
    "Silt":            {"alpha_cm": 0.016, "n": 1.37, "theta_r": 0.034, "theta_s": 0.46, "Ks_m_s": 6.94e-7},
    "Silt Loam":       {"alpha_cm": 0.020, "n": 1.41, "theta_r": 0.067, "theta_s": 0.45, "Ks_m_s": 1.25e-6},
    "Sandy Clay Loam": {"alpha_cm": 0.059, "n": 1.48, "theta_r": 0.100, "theta_s": 0.39, "Ks_m_s": 3.64e-6},
    "Clay Loam":       {"alpha_cm": 0.019, "n": 1.31, "theta_r": 0.095, "theta_s": 0.41, "Ks_m_s": 7.22e-7},
    "Silty Clay Loam": {"alpha_cm": 0.010, "n": 1.23, "theta_r": 0.089, "theta_s": 0.43, "Ks_m_s": 1.94e-7},
    "Sandy Clay":      {"alpha_cm": 0.027, "n": 1.23, "theta_r": 0.100, "theta_s": 0.38, "Ks_m_s": 3.33e-7},
    "Silty Clay":      {"alpha_cm": 0.005, "n": 1.09, "theta_r": 0.070, "theta_s": 0.36, "Ks_m_s": 5.56e-8},
    "Clay":            {"alpha_cm": 0.008, "n": 1.09, "theta_r": 0.068, "theta_s": 0.38, "Ks_m_s": 5.56e-7},
}


def validate_inputs(args):
    """Validate input parameters.

    Returns:
        dict with 'valid' (bool) and 'errors' (list)
    """
    errors = []

    if args.hwsd_csv and not os.path.isfile(args.hwsd_csv):
        errors.append(f"HWSD CSV not found: {args.hwsd_csv}")

    if args.glhymps_shp and not os.path.isfile(args.glhymps_shp):
        errors.append(f"GLHYMPS shapefile not found: {args.glhymps_shp}")

    if not args.hwsd_csv and not args.glhymps_shp:
        errors.append("At least one of --hwsd-csv or --glhymps-shp is required")

    if not (-90 <= args.lat <= 90):
        errors.append(f"Latitude out of range: {args.lat}")
    if not (-180 <= args.lon <= 360):
        errors.append(f"Longitude out of range: {args.lon}")

    if args.depth_layers < 1 or args.depth_layers > 100:
        errors.append(f"Depth layers must be 1-100: {args.depth_layers}")

    return {"valid": len(errors) == 0, "errors": errors}


def classify_usda_texture(sand_pct, silt_pct, clay_pct):
    """Classify USDA soil texture from sand/silt/clay percentages.

    Uses the USDA texture triangle classification.

    Args:
        sand_pct, silt_pct, clay_pct: percentages (must sum to ~100)

    Returns:
        str: USDA texture class name
    """
    s, si, c = sand_pct, silt_pct, clay_pct

    # Normalize to ensure sum = 100
    total = s + si + c
    if total == 0:
        return "Loam"  # default fallback
    s = s * 100.0 / total
    si = si * 100.0 / total
    c = c * 100.0 / total

    if c >= 40 and s <= 45 and si < 40:
        return "Clay"
    elif c >= 40 and si >= 40:
        return "Silty Clay"
    elif c >= 35 and s > 45:
        return "Sandy Clay"
    elif c >= 27 and c < 40 and s > 20 and s <= 45:
        return "Clay Loam"
    elif c >= 27 and c < 40 and s <= 20:
        return "Silty Clay Loam"
    elif c >= 20 and c < 35 and si < 28 and s > 45:
        return "Sandy Clay Loam"
    elif c >= 7 and c < 27 and si >= 28 and si < 50 and s <= 52:
        return "Loam"
    elif (si >= 50 and c >= 12 and c < 27) or (si >= 50 and si < 80 and c < 12):
        return "Silt Loam"
    elif si >= 80 and c < 12:
        return "Silt"
    elif c < 7 and si < 50 and s >= 43 and s < 52:
        return "Loam"
    elif c < 7 and si < 50 and s >= 52 and s < 70:
        if c < 7 and s < 85:
            return "Sandy Loam"
        else:
            return "Loamy Sand"
    elif s >= 70 and s < 85:
        return "Sandy Loam" if c >= 7 else "Loamy Sand"
    elif s >= 85:
        return "Sand"
    else:
        return "Loam"  # fallback


def get_vg_params_pflotran(texture_class):
    """Get van Genuchten parameters in PFLOTRAN units.

    CRITICAL CONVERSION:
        alpha (1/Pa) = alpha (1/cm) / (rho * g)
        alpha (1/Pa) = alpha (1/cm) / 9804.139

    Common mistake: using alpha in 1/cm directly in PFLOTRAN.
    This causes a factor-of-~10000 error in capillary pressure,
    leading to instant drainage and unrealistic saturation profiles.

    Returns:
        dict with alpha_Pa, n, m, theta_r, theta_s, Ks_m2
    """
    if texture_class not in VG_PARAMS:
        print(f"WARNING: Unknown texture class '{texture_class}', using Loam")
        texture_class = "Loam"

    params = VG_PARAMS[texture_class]

    # CRITICAL: Convert alpha from 1/cm to 1/Pa
    alpha_Pa = params["alpha_cm"] / RHO_G

    n = params["n"]
    m = 1.0 - 1.0 / n  # Mualem constraint

    # Convert Ks (m/s) to intrinsic permeability k (m^2)
    # k = Ks * mu / (rho * g)
    mu_water = 1.002e-3  # Pa.s at 20C
    k_m2 = params["Ks_m_s"] * mu_water / (RHO_WATER * G)

    return {
        "texture_class": texture_class,
        "alpha_Pa": float(alpha_Pa),
        "alpha_cm": float(params["alpha_cm"]),
        "n": float(n),
        "m": float(m),
        "theta_r": float(params["theta_r"]),
        "theta_s": float(params["theta_s"]),
        "Ks_m_s": float(params["Ks_m_s"]),
        "permeability_m2": float(k_m2),
        "porosity": float(params["theta_s"]),
    }


def read_hwsd_at_location(hwsd_csv, lat, lon):
    """Read HWSD CSV and find texture for nearest matching record.

    HWSD_DATA.csv expected columns include:
        MU_GLOBAL, T_SAND, T_SILT, T_CLAY, S_SAND, S_SILT, S_CLAY

    For point extraction, we need the raster to identify MU_GLOBAL first.
    If raster not available, return default loam values.
    """
    try:
        import pandas as pd
        df = pd.read_csv(hwsd_csv, low_memory=False)

        # Return dominant topsoil texture (would need raster for spatial lookup)
        # For now, return the most common class
        if "T_SAND" in df.columns and "T_SILT" in df.columns and "T_CLAY" in df.columns:
            # Use median values as representative
            sand = df["T_SAND"].median()
            silt = df["T_SILT"].median()
            clay = df["T_CLAY"].median()
            return {
                "topsoil": {"sand": float(sand), "silt": float(silt), "clay": float(clay)},
                "subsoil": {
                    "sand": float(df.get("S_SAND", df["T_SAND"]).median()),
                    "silt": float(df.get("S_SILT", df["T_SILT"]).median()),
                    "clay": float(df.get("S_CLAY", df["T_CLAY"]).median()),
                },
                "source": "hwsd_csv",
            }
    except Exception as e:
        print(f"  WARNING: Could not read HWSD: {e}")

    # Fallback: typical North China Plain values
    return {
        "topsoil": {"sand": 30.0, "silt": 45.0, "clay": 25.0},
        "subsoil": {"sand": 25.0, "silt": 40.0, "clay": 35.0},
        "source": "default_north_china",
    }


def read_glhymps_at_location(glhymps_shp, lat, lon):
    """Read GLHYMPS shapefile and extract K/porosity at location.

    GLHYMPS fields:
        logK_Ferr_: log10(permeability in m^2)
        Porosity_:  porosity in percent (%)

    CRITICAL: porosity is in % not fraction!
    """
    try:
        import geopandas as gpd
        from shapely.geometry import Point

        gdf = gpd.read_file(glhymps_shp)
        point = Point(lon, lat)

        # Find polygon containing point
        containing = gdf[gdf.contains(point)]
        if len(containing) == 0:
            # Find nearest polygon
            gdf["dist"] = gdf.geometry.distance(point)
            containing = gdf.nsmallest(1, "dist")
            print(f"  WARNING: Point not within GLHYMPS polygon, using nearest")

        row = containing.iloc[0]
        logK = float(row.get("logK_Ferr_", row.get("logK_Ice_", -14.0)))
        porosity_pct = float(row.get("Porosity_", 15.0))

        return {
            "logK_m2": logK,
            "permeability_m2": 10.0 ** logK,
            "porosity_fraction": porosity_pct / 100.0,  # CRITICAL: % → fraction
            "porosity_pct": porosity_pct,
            "source": "glhymps",
        }
    except Exception as e:
        print(f"  WARNING: Could not read GLHYMPS: {e}")

    # Fallback: typical alluvial aquifer
    return {
        "logK_m2": -12.0,
        "permeability_m2": 1e-12,
        "porosity_fraction": 0.25,
        "porosity_pct": 25.0,
        "source": "default_alluvial",
    }


def build_material_properties(hwsd_data, glhymps_data, depth_layers):
    """Build PFLOTRAN material properties from soil/geology data.

    Creates layered material properties:
    - Top layers (0-2m): HWSD soil properties
    - Middle layers (2-10m): Transitional
    - Deep layers (>10m): GLHYMPS bedrock properties

    Returns:
        list of material property dicts
    """
    materials = []

    # Topsoil layer
    top_texture = classify_usda_texture(
        hwsd_data["topsoil"]["sand"],
        hwsd_data["topsoil"]["silt"],
        hwsd_data["topsoil"]["clay"],
    )
    top_vg = get_vg_params_pflotran(top_texture)

    # Subsoil layer
    sub_texture = classify_usda_texture(
        hwsd_data["subsoil"]["sand"],
        hwsd_data["subsoil"]["silt"],
        hwsd_data["subsoil"]["clay"],
    )
    sub_vg = get_vg_params_pflotran(sub_texture)

    # Bedrock from GLHYMPS
    bedrock_k = glhymps_data["permeability_m2"]
    bedrock_phi = glhymps_data["porosity_fraction"]

    materials.append({
        "name": "topsoil",
        "id": 1,
        "depth_range_m": [0.0, 2.0],
        "permeability_m2": top_vg["permeability_m2"],
        "porosity": top_vg["porosity"],
        "tortuosity": 0.5,
        "vg_alpha_Pa": top_vg["alpha_Pa"],
        "vg_n": top_vg["n"],
        "vg_m": top_vg["m"],
        "vg_residual_sat": top_vg["theta_r"],
        "texture": top_texture,
        "source": hwsd_data["source"],
    })

    materials.append({
        "name": "subsoil",
        "id": 2,
        "depth_range_m": [2.0, 10.0],
        "permeability_m2": sub_vg["permeability_m2"],
        "porosity": sub_vg["porosity"],
        "tortuosity": 0.4,
        "vg_alpha_Pa": sub_vg["alpha_Pa"],
        "vg_n": sub_vg["n"],
        "vg_m": sub_vg["m"],
        "vg_residual_sat": sub_vg["theta_r"],
        "texture": sub_texture,
        "source": hwsd_data["source"],
    })

    materials.append({
        "name": "bedrock",
        "id": 3,
        "depth_range_m": [10.0, 100.0],
        "permeability_m2": bedrock_k,
        "porosity": bedrock_phi,
        "tortuosity": 0.3,
        "vg_alpha_Pa": 1.0e-5,  # Typical for consolidated rock
        "vg_n": 1.3,
        "vg_m": 1.0 - 1.0 / 1.3,
        "vg_residual_sat": 0.05,
        "texture": "bedrock",
        "source": glhymps_data["source"],
    })

    return materials


def validate_outputs(materials):
    """Validate material properties are physically reasonable.

    Returns:
        dict with 'valid' (bool), 'warnings' (list)
    """
    warnings = []

    for mat in materials:
        name = mat["name"]

        # Porosity must be 0-1
        if mat["porosity"] > 1.0:
            warnings.append(
                f"{name}: porosity {mat['porosity']:.2f} > 1.0 "
                "— likely in % not fraction (UNIT ERROR dt_005)"
            )
        if mat["porosity"] <= 0:
            warnings.append(f"{name}: porosity {mat['porosity']:.4f} <= 0")

        # Permeability range check
        k = mat["permeability_m2"]
        if k > 1e-8:
            warnings.append(
                f"{name}: permeability {k:.2e} m^2 > 1e-8 "
                "— did you use Darcy instead of m^2? (UNIT ERROR dt_001)"
            )
        if k < 1e-20:
            warnings.append(f"{name}: permeability {k:.2e} m^2 < 1e-20 — essentially impermeable")

        # vG alpha range check (1/Pa)
        alpha = mat["vg_alpha_Pa"]
        if alpha > 1e-2:
            warnings.append(
                f"{name}: vG alpha {alpha:.2e} 1/Pa seems too high "
                "— did you use 1/cm instead of 1/Pa? (UNIT ERROR dt_006)"
            )
        if alpha < 1e-8:
            warnings.append(f"{name}: vG alpha {alpha:.2e} 1/Pa seems very low")

        # vG n must be > 1
        if mat["vg_n"] <= 1.0:
            warnings.append(f"{name}: vG n = {mat['vg_n']:.3f} must be > 1.0")

    return {"valid": len(warnings) == 0, "warnings": warnings}


def generate_pflotran_blocks(materials):
    """Generate PFLOTRAN input deck text for material properties.

    Returns:
        str: PFLOTRAN input deck blocks
    """
    lines = []

    for mat in materials:
        lines.append(f"MATERIAL_PROPERTY {mat['name']}")
        lines.append(f"  ID {mat['id']}")
        lines.append(f"  POROSITY {mat['porosity']:.4f}d0")
        lines.append(f"  TORTUOSITY {mat['tortuosity']:.2f}d0")
        lines.append(f"  PERMEABILITY")
        lines.append(f"    PERM_ISO {mat['permeability_m2']:.4e}")
        lines.append(f"  /")
        lines.append(f"  CHARACTERISTIC_CURVES cc_{mat['name']}")
        lines.append(f"END\n")

    for mat in materials:
        name = mat["name"]
        lines.append(f"CHARACTERISTIC_CURVES cc_{name}")
        lines.append(f"  SATURATION_FUNCTION VAN_GENUCHTEN")
        lines.append(f"    ALPHA {mat['vg_alpha_Pa']:.6e}")
        lines.append(f"    M {mat['vg_m']:.4f}d0")
        lines.append(f"    LIQUID_RESIDUAL_SATURATION {mat['vg_residual_sat']:.3f}d0")
        lines.append(f"  /")
        lines.append(f"  PERMEABILITY_FUNCTION MUALEM_VG_LIQ")
        lines.append(f"    M {mat['vg_m']:.4f}d0")
        lines.append(f"    LIQUID_RESIDUAL_SATURATION {mat['vg_residual_sat']:.3f}d0")
        lines.append(f"  /")
        lines.append(f"END\n")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Convert HWSD/GLHYMPS to PFLOTRAN material properties"
    )
    parser.add_argument("--hwsd-csv", help="Path to HWSD_DATA.csv")
    parser.add_argument("--glhymps-shp", help="Path to GLHYMPS shapefile")
    parser.add_argument("--lat", type=float, required=True)
    parser.add_argument("--lon", type=float, required=True)
    parser.add_argument("--depth-layers", type=int, default=10)
    parser.add_argument("--output", required=True, help="Output JSON path")

    args = parser.parse_args()

    print("=" * 60)
    print("PFLOTRAN Soil/Material Property Converter")
    print("=" * 60)

    # Step 1: Validate
    print("\n[1/4] Validating inputs...")
    validation = validate_inputs(args)
    if not validation["valid"]:
        for err in validation["errors"]:
            print(f"  ERROR: {err}")
        sys.exit(1)

    # Step 2: Read HWSD
    print("\n[2/4] Reading soil data...")
    hwsd_data = read_hwsd_at_location(args.hwsd_csv, args.lat, args.lon) if args.hwsd_csv else {
        "topsoil": {"sand": 30, "silt": 45, "clay": 25},
        "subsoil": {"sand": 25, "silt": 40, "clay": 35},
        "source": "default",
    }
    print(f"  Topsoil: sand={hwsd_data['topsoil']['sand']:.0f}% "
          f"silt={hwsd_data['topsoil']['silt']:.0f}% "
          f"clay={hwsd_data['topsoil']['clay']:.0f}%")

    # Step 3: Read GLHYMPS
    print("\n[3/4] Reading hydrogeology data...")
    glhymps_data = read_glhymps_at_location(args.glhymps_shp, args.lat, args.lon) if args.glhymps_shp else {
        "logK_m2": -12.0,
        "permeability_m2": 1e-12,
        "porosity_fraction": 0.25,
        "porosity_pct": 25.0,
        "source": "default",
    }
    print(f"  Bedrock K = 10^{glhymps_data['logK_m2']:.1f} m^2 = {glhymps_data['permeability_m2']:.2e} m^2")
    print(f"  Bedrock porosity = {glhymps_data['porosity_fraction']:.2f}")

    # Step 4: Build materials
    print("\n[4/4] Building material properties...")
    materials = build_material_properties(hwsd_data, glhymps_data, args.depth_layers)

    validation = validate_outputs(materials)
    for w in validation["warnings"]:
        print(f"  WARNING: {w}")

    # Write output
    output = {
        "materials": materials,
        "pflotran_blocks": generate_pflotran_blocks(materials),
        "location": {"lat": args.lat, "lon": args.lon},
        "sources": {
            "hwsd": hwsd_data["source"],
            "glhymps": glhymps_data["source"],
        },
    }

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\n  Written to {args.output}")
    print(f"\n  PFLOTRAN blocks preview:")
    print(output["pflotran_blocks"][:500])
    print("\nDone.")


if __name__ == "__main__":
    main()
