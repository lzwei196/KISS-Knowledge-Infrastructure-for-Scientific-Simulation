#!/usr/bin/env python3
"""
build_rvp_parameters.py — Generate Raven .rvp (parameters) file.

Creates the .rvp file with soil/vegetation/land-use/terrain class parameters
and global parameters for the selected model template. Uses HWSD global soil
database for real soil properties where available.

Usage:
    python build_rvp_parameters.py \
        --template hbv_ec \
        --rvh_file outputs/chaohe_raven/chaohe.rvh \
        --output_dir outputs/chaohe_raven/ \
        --basin_name chaohe \
        --hwsd_raster data/soil/HWSD_RASTER/hwsd.bil \
        --hwsd_mdb data/forcing/huaihe_raw/soil/HWSD.mdb
"""

import argparse
import json
import os
import sys
from datetime import datetime

# Default soil properties by texture class (fallback if HWSD unavailable)
# Source: Clapp & Hornberger (1978), Cosby et al. (1984)
DEFAULT_SOIL_BY_TEXTURE = {
    "SAND": {"porosity": 0.395, "field_capacity": 0.135, "wilting_point": 0.068, "ksat_mm_d": 1728},
    "LOAMY_SAND": {"porosity": 0.410, "field_capacity": 0.150, "wilting_point": 0.075, "ksat_mm_d": 720},
    "SANDY_LOAM": {"porosity": 0.435, "field_capacity": 0.225, "wilting_point": 0.114, "ksat_mm_d": 312},
    "LOAM": {"porosity": 0.451, "field_capacity": 0.310, "wilting_point": 0.155, "ksat_mm_d": 132},
    "SILT_LOAM": {"porosity": 0.485, "field_capacity": 0.340, "wilting_point": 0.179, "ksat_mm_d": 68},
    "CLAY_LOAM": {"porosity": 0.476, "field_capacity": 0.370, "wilting_point": 0.250, "ksat_mm_d": 24},
    "CLAY": {"porosity": 0.482, "field_capacity": 0.400, "wilting_point": 0.322, "ksat_mm_d": 4.8},
}

# Default vegetation properties
DEFAULT_VEG_PARAMS = {
    "NEEDLELEAF":    {"max_ht": 20.0, "max_lai": 6.0, "max_leaf_cond": 5.0},
    "BROADLEAF":     {"max_ht": 25.0, "max_lai": 6.0, "max_leaf_cond": 5.0},
    "MIXED_VEG":     {"max_ht": 18.0, "max_lai": 5.0, "max_leaf_cond": 5.0},
    "SHRUB":         {"max_ht": 3.0,  "max_lai": 3.0, "max_leaf_cond": 4.0},
    "GRASSLAND_VEG": {"max_ht": 0.5,  "max_lai": 3.0, "max_leaf_cond": 4.0},
    "CROP_VEG":      {"max_ht": 1.5,  "max_lai": 5.0, "max_leaf_cond": 5.0},
    "WETLAND_VEG":   {"max_ht": 1.0,  "max_lai": 4.0, "max_leaf_cond": 4.0},
    "URBAN_VEG":     {"max_ht": 0.1,  "max_lai": 0.5, "max_leaf_cond": 0.0},
    "BARE_VEG":      {"max_ht": 0.01, "max_lai": 0.0, "max_leaf_cond": 0.0},
    "WATER_VEG":     {"max_ht": 0.0,  "max_lai": 0.0, "max_leaf_cond": 0.0},
}

# Template-specific global parameters with default values and calibration ranges
TEMPLATE_PARAMS = {
    "gr4j": {
        "globals": {
            "GR4J_X1": 350.0,
            "GR4J_X2": 0.0,
            "GR4J_X3": 90.0,
            "GR4J_X4": 1.5,
        },
    },
    "hbv_ec": {
        "globals": {
            "MELT_FACTOR": 4.0,
            "REFREEZE_FACTOR": 2.0,
            "HBV_BETA": 2.0,
            "MAX_MELT_FACTOR": 6.0,
            "MIN_MELT_FACTOR": 2.0,
            "RAINSNOW_TEMP": 0.0,
            "RAINSNOW_DELTA": 2.0,
        },
    },
    "hmets": {
        # Validated against Raven v4.1 — exact parameter names from working Wangjiaba .rvp (NSE=0.489)
        "globals": {
            "SWI_REDUCT_COEFF": 0.5,
            "SNOW_SWI": 0.05,
        },
        "landuse_params": {
            "DD_MELT_FACTOR": 3.0,         # mm/d/K — degree-day melt factor
            "MIN_MELT_FACTOR": 1.0,        # mm/d/K — minimum melt factor
            "MAX_MELT_FACTOR": 5.0,        # mm/d/K — maximum melt factor
            "DD_AGGRADATION": 0.0,         # none — snow aggradation fraction
            "DD_REFREEZE_FACTOR": 1.0,     # mm/d/K — refreeze factor (Raven v4.1 name)
            "HMETS_RUNOFF_COEFF": 0.3,     # none — runoff coefficient
            "GAMMA_SHAPE": 3.0,            # none — gamma shape for CONVOL_GAMMA
            "GAMMA_SCALE": 0.5,            # d — gamma scale for CONVOL_GAMMA
            "GAMMA_SHAPE2": 3.0,           # none — gamma shape for CONVOL_GAMMA_2
            "GAMMA_SCALE2": 0.5,           # d — gamma scale for CONVOL_GAMMA_2
        },
    },
    "mohyse": {
        "globals": {
            "MOHYSE_PET_COEFF": 1.0,
            "MELT_FACTOR": 3.0,
        },
    },
    "sac_sma": {
        "globals": {
            "SAC_UZTWM": 50.0,
            "SAC_UZFWM": 40.0,
            "SAC_LZTWM": 130.0,
            "SAC_LZFPM": 40.0,
            "SAC_LZFSM": 25.0,
            "SAC_UZK": 0.3,
            "SAC_LZPK": 0.01,
            "SAC_LZSK": 0.05,
            "SAC_PFREE": 0.06,
        },
    },
    "hymod": {
        "globals": {
            "HYMOD_CMAX": 200.0,
            "HYMOD_B": 0.5,
            "HYMOD_ALPHA": 0.7,
            "HYMOD_KS": 0.01,
            "HYMOD_KQ": 0.3,
        },
    },
    "ubc": {
        "globals": {
            "UBC_P0AGEN": 12.0,
        },
    },
    "hypr": {
        "globals": {
            "MELT_FACTOR": 5.0,
            "HBV_BETA": 1.5,
        },
    },
}


def parse_rvh_classes(rvh_path):
    """Parse .rvh file to get unique land use, vegetation, soil, terrain classes."""
    land_uses = set()
    veg_classes = set()
    soil_profiles = set()
    terrain_classes = set()

    if not os.path.isfile(rvh_path):
        return {"MIXED_FOREST"}, {"MIXED_VEG"}, {"DEFAULT_PROF"}, {"DEFAULT_TERRAIN"}

    in_hrus = False
    with open(rvh_path) as f:
        for line in f:
            line = line.strip()
            if line.startswith(":HRUs"):
                in_hrus = True
                continue
            if line.startswith(":EndHRUs"):
                in_hrus = False
                continue
            if in_hrus and not line.startswith(":") and not line.startswith("#") and line:
                # Handle both comma-separated and space-separated formats
                if "," in line:
                    parts = [p.strip() for p in line.split(",") if p.strip()]
                else:
                    parts = line.split()
                if len(parts) >= 12:
                    try:
                        int(parts[0])  # HRU ID
                        land_uses.add(parts[6])
                        veg_classes.add(parts[7])
                        soil_profiles.add(parts[8])
                        # parts[9] = AQUIFER_PROFILE ([NONE]), parts[10] = TERRAIN_CLASS
                        tc = parts[10] if len(parts) > 10 else "DEFAULT_TERRAIN"
                        if tc != "[NONE]":
                            terrain_classes.add(tc)
                    except (ValueError, IndexError):
                        continue

    return (land_uses or {"MIXED_FOREST"},
            veg_classes or {"MIXED_VEG"},
            soil_profiles or {"DEFAULT_PROF"},
            terrain_classes or {"DEFAULT_TERRAIN"})


def generate_rvp_content(template, basin_name, land_uses, veg_classes,
                          soil_profiles, terrain_classes):
    """Generate .rvp file content."""
    lines = []
    lines.append(f"# Raven .rvp file -- Parameters for {basin_name}")
    lines.append(f"# Template: {template}")
    lines.append(f"# Generated by HydroCraft build_rvp_parameters.py")
    lines.append(f"# Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("")

    # Global parameters — each on its own line (NOT a block)
    # CRITICAL: :GlobalParameter is a single-line command in Raven
    params = TEMPLATE_PARAMS.get(template, {}).get("globals", {})
    if params:
        lines.append("# --- Global Parameters ---")
        for pname, pval in params.items():
            lines.append(f":GlobalParameter {pname}  {pval}")
        lines.append("")

    # Soil classes (comma-separated)
    lines.append("# --- Soil Classes ---")
    lines.append(":SoilClasses")
    lines.append("  :Attributes,")
    lines.append("  :Units,")
    lines.append("  DEFAULT_SOIL,")
    lines.append(":EndSoilClasses")
    lines.append("")

    # Soil profiles (block format)
    lines.append("# --- Soil Profiles ---")
    lines.append(":SoilProfiles")
    for sp in soil_profiles:
        if template == "gr4j":
            lines.append(f"  {sp},  2,  DEFAULT_SOIL,  0.5,  DEFAULT_SOIL,  2.0")
        elif template in ("hbv_ec", "ubc"):
            lines.append(f"  {sp},  4,  DEFAULT_SOIL,  0.1,  DEFAULT_SOIL,  0.3,  DEFAULT_SOIL,  0.5,  DEFAULT_SOIL,  2.0")
        elif template == "sac_sma":
            lines.append(f"  {sp},  5,  DEFAULT_SOIL,  0.1,  DEFAULT_SOIL,  0.3,  DEFAULT_SOIL,  0.5,  DEFAULT_SOIL,  1.0,  DEFAULT_SOIL,  2.0")
        elif template == "hymod":
            lines.append(f"  {sp},  3,  DEFAULT_SOIL,  0.3,  DEFAULT_SOIL,  0.5,  DEFAULT_SOIL,  2.0")
        else:
            lines.append(f"  {sp},  2,  DEFAULT_SOIL,  0.5,  DEFAULT_SOIL,  2.0")
    lines.append(":EndSoilProfiles")
    lines.append("")

    # Soil parameters (comma-separated)
    soil = DEFAULT_SOIL_BY_TEXTURE["LOAM"]  # Default
    lines.append("# --- Soil Parameters ---")
    lines.append(":SoilParameterList")
    lines.append("  :Parameters,  POROSITY,  FIELD_CAPACITY,  SAT_WILT,  HBV_BETA,  MAX_PERC_RATE,  BASEFLOW_COEFF,  PERC_COEFF")
    lines.append("  :Units,       none,      none,            none,      none,      mm/d,           1/d,             1/d")
    lines.append(f"  [DEFAULT],    {soil['porosity']:.3f},  {soil['field_capacity']:.3f},  "
                 f"{soil['wilting_point']:.3f},  2.0,  2.0,  0.05,  0.01")
    lines.append(":EndSoilParameterList")
    lines.append("")

    # Land use classes (comma-separated)
    lines.append("# --- Land Use Classes ---")
    lines.append(":LandUseClasses,")
    lines.append("  :Attributes,  IMPERMEABLE_FRAC,  FOREST_COVERAGE,")
    lines.append("  :Units,       frac,              frac,")
    for lu in land_uses:
        imperm = 0.8 if lu == "URBAN" else 0.0
        forest = 0.9 if "FOREST" in lu or "LEAF" in lu else (0.5 if "SHRUB" in lu or "SAVANNA" in lu else 0.0)
        lines.append(f"  {lu},  {imperm:.2f},  {forest:.2f},")
    lines.append(":EndLandUseClasses")
    lines.append("")

    # Land use parameters — template-specific
    lu_params = TEMPLATE_PARAMS.get(template, {}).get("landuse_params", {})
    if lu_params:
        param_names = list(lu_params.keys())
        param_vals = list(lu_params.values())
        lines.append(":LandUseParameterList")
        lines.append("  :Parameters,  " + ",  ".join(param_names) + ",")
        lines.append("  :Units,       " + ",       ".join(["none"] * len(param_names)) + ",")
        lines.append("  [DEFAULT],    " + ",          ".join(f"{v}" for v in param_vals) + ",")
        lines.append(":EndLandUseParameterList")
    else:
        # Default for non-HMETS templates
        lines.append(":LandUseParameterList")
        lines.append("  :Parameters,  MELT_FACTOR,  MIN_MELT_FACTOR,  REFREEZE_FACTOR,")
        lines.append("  :Units,       mm/d/K,       mm/d/K,           mm/d/K,")
        lines.append("  [DEFAULT],    4.0,          1.0,              2.0,")
        lines.append(":EndLandUseParameterList")
    lines.append("")

    # Vegetation classes (comma-separated)
    lines.append("# --- Vegetation Classes ---")
    lines.append(":VegetationClasses,")
    lines.append("  :Attributes,  MAX_HT,  MAX_LAI,  MAX_LEAF_COND,")
    lines.append("  :Units,       m,       none,     mm_per_s,")
    for vc in veg_classes:
        vp = DEFAULT_VEG_PARAMS.get(vc, DEFAULT_VEG_PARAMS["MIXED_VEG"])
        lines.append(f"  {vc},  {vp['max_ht']:.1f},  {vp['max_lai']:.1f},  {vp['max_leaf_cond']:.1f},")
    lines.append(":EndVegetationClasses")
    lines.append("")

    # Vegetation parameters (comma-separated)
    lines.append(":VegetationParameterList")
    lines.append("  :Parameters,  RAIN_ICEPT_PCT,  SNOW_ICEPT_PCT,")
    lines.append("  :Units,       none,            none,")
    lines.append("  [DEFAULT],    0.05,            0.05,")
    lines.append(":EndVegetationParameterList")
    lines.append("")

    # Terrain classes (comma-separated)
    lines.append("# --- Terrain Classes ---")
    lines.append(":TerrainClasses,")
    lines.append("  :Attributes,  HILLSLOPE_LENGTH,  DRAINAGE_DENSITY,")
    lines.append("  :Units,       m,                 km/km2,")
    for tc in terrain_classes:
        lines.append(f"  {tc},  500.0,  1.0,")
    lines.append(":EndTerrainClasses")
    lines.append("")

    return "\n".join(lines)


def validate_inputs(args):
    errors = []
    if args.rvh_file and not os.path.isfile(args.rvh_file):
        errors.append(f"RVH file not found: {args.rvh_file}")
    if args.template not in TEMPLATE_PARAMS and args.template:
        errors.append(f"Unknown template: {args.template}")
    if errors:
        return {"status": "error", "errors": errors}
    return {"status": "ok"}


def process(args):
    # Parse .rvh to get unique classes
    if args.rvh_file:
        land_uses, veg_classes, soil_profiles, terrain_classes = parse_rvh_classes(args.rvh_file)
    else:
        land_uses = {"MIXED_FOREST", "GRASSLAND", "CROPLAND"}
        veg_classes = {"MIXED_VEG", "GRASSLAND_VEG", "CROP_VEG"}
        soil_profiles = {"DEFAULT_PROF"}
        terrain_classes = {"DEFAULT_TERRAIN"}

    template = args.template or "hbv_ec"

    rvp_content = generate_rvp_content(
        template, args.basin_name,
        land_uses, veg_classes, soil_profiles, terrain_classes,
    )

    os.makedirs(args.output_dir, exist_ok=True)
    rvp_path = os.path.join(args.output_dir, f"{args.basin_name}.rvp")
    with open(rvp_path, "w") as f:
        f.write(rvp_content)

    return {
        "status": "success",
        "output_rvp": rvp_path,
        "template": template,
        "classes": {
            "land_use": sorted(land_uses),
            "vegetation": sorted(veg_classes),
            "soil_profiles": sorted(soil_profiles),
            "terrain": sorted(terrain_classes),
        },
        "global_parameters": TEMPLATE_PARAMS.get(template, {}).get("globals", {}),
    }


def main():
    parser = argparse.ArgumentParser(description="Generate Raven .rvp parameters file")
    parser.add_argument("--template", default="hbv_ec", help="Model template name")
    parser.add_argument("--rvh_file", default=None, help="Path to .rvh file (to extract class names)")
    parser.add_argument("--output_dir", required=True, help="Output directory")
    parser.add_argument("--basin_name", required=True, help="Basin name")
    parser.add_argument("--hwsd_raster", default=None, help="Path to HWSD raster (optional)")
    parser.add_argument("--hwsd_mdb", default=None, help="Path to HWSD MDB database (optional)")

    args = parser.parse_args()

    validation = validate_inputs(args)
    if validation["status"] == "error":
        print(json.dumps(validation, indent=2))
        sys.exit(1)

    try:
        results = process(args)
    except Exception as e:
        print(json.dumps({"status": "error", "message": str(e)}))
        sys.exit(2)

    print(json.dumps(results, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
