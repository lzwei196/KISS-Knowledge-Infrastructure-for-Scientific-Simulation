#!/usr/bin/env python3
"""
build_rvp_parameters.py — Generate Raven .rvp (parameters) file.

The set of parameters Raven requires is a function of the hydrologic process
list in the .rvi, not of the template name, and it changes between Raven
versions. Rather than carry a hand-maintained per-template table (which drifts
and silently emits .rvp files Raven rejects at ParsePropertyFile), this tool
asks the Raven binary itself: it runs Raven with :CreateRVPTemplate on the
.rvi, parses the emitted template, and fills every declared parameter from
PARAM_DEFAULTS.

Usage:
    python build_rvp_parameters.py \
        --template hbv_ec \
        --rvh_file outputs/chaohe_raven/chaohe.rvh \
        --output_dir outputs/chaohe_raven/ \
        --basin_name chaohe

--rvi_file defaults to <output_dir>/<basin_name>.rvi (where
select_model_template.py writes it), so existing call sites need no change.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime

RAVEN_EXE_DEFAULT = "KISSPATH_BINARIES/raven/Raven.exe"

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

# Default vegetation class attributes
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

# Uncalibrated starting values for every parameter Raven can declare required
# across the supported emulations. Values are mid-range literature defaults
# (Raven User's Manual v4.1 Tables A.3/A.4/A.5/A.6 "Range"/"Default" columns);
# they are DDS calibration start points, not final parameters.
PARAM_DEFAULTS = {
    # --- global ---
    "RAINSNOW_TEMP": 0.0, "RAINSNOW_DELTA": 2.0, "AIRSNOW_COEFF": 0.05,
    "AVG_ANNUAL_SNOW": 100.0, "AVG_ANNUAL_RUNOFF": 300.0,
    "SNOW_SWI": 0.05, "SNOW_SWI_MIN": 0.05, "SNOW_SWI_MAX": 0.12,
    "SWI_REDUCT_COEFF": 0.02, "SNOW_TEMPERATURE": -1.0, "SNOW_ROUGHNESS": 1.0,
    "MAX_SNOW_ALBEDO": 0.95, "MIN_SNOW_ALBEDO": 0.3, "BARE_GROUND_ALBEDO": 0.25,
    "ADIABATIC_LAPSE": 6.5, "WET_ADIABATIC_LAPSE": 5.0, "PRECIP_LAPSE": 0.0,
    "MOHYSE_PET_COEFF": 1.0,
    "UBC_GW_SPLIT": 0.4, "UBC_FLASH_PONDING": 36.0, "UBC_ALBASE": 0.65,
    "UBC_ALBREC": 0.9, "UBC_ALBSNW": 15.0, "UBC_MAX_CUM_MELT": 4000.0,
    "UBC_SW_S_CORR": 1.0, "UBC_SW_N_CORR": 1.0, "UBC_EXPOSURE_FACT": 0.01,
    "UBC_CLOUD_PENET": 0.25, "UBC_LW_FOREST_FACT": 1.0,
    "ALB_DECAY_COLD": 0.008, "ALB_DECAY_MELT": 0.12, "SNOWFALL_ALBTHRESH": 10.0,
    "MAX_REACH_SEGLENGTH": 10000.0, "MAX_SWE_SURFACE": 100.0,
    # --- soil ---
    "POROSITY": 0.451, "PET_CORRECTION": 1.0, "STONE_FRAC": 0.0,
    "FIELD_CAPACITY": 0.310, "SAT_WILT": 0.155, "SAT_RES": 0.05,
    "HYDRAUL_COND": 132.0, "BULK_DENSITY": 1400.0, "CLAPP_B": 5.0,
    "ALBEDO_WET": 0.10, "ALBEDO_DRY": 0.20,
    "HBV_BETA": 2.0, "MAX_CAP_RISE_RATE": 1.0, "MAX_PERC_RATE": 2.0,
    "PERC_COEFF": 0.01, "PERC_N": 2.0,
    "BASEFLOW_COEFF": 0.05, "BASEFLOW_COEFF2": 0.01, "BASEFLOW_N": 1.0,
    "BASEFLOW_THRESH": 0.0, "MAX_BASEFLOW_RATE": 100.0,
    "STORAGE_THRESHOLD": 0.0, "MAX_INTERFLOW_RATE": 10.0, "INTERFLOW_COEFF": 0.05,
    "UNAVAIL_FRAC": 0.10,
    "SAC_PERC_ALPHA": 50.0, "SAC_PERC_EXPON": 2.0, "SAC_PERC_PFREE": 0.06,
    "UBC_EVAP_SOIL_DEF": 100.0, "UBC_INFIL_SOIL_DEF": 100.0,
    "GR4J_X2": 0.0, "GR4J_X3": 90.0,
    "VIC_ZMIN": 0.0, "VIC_ZMAX": 100.0, "VIC_ALPHA": 0.2, "VIC_EVAP_GAMMA": 1.0,
    # --- land use ---
    "IMPERMEABLE_FRAC": 0.0, "FOREST_COVERAGE": 0.0, "FOREST_SPARSENESS": 0.0,
    "ROUGHNESS": 0.1, "LAKE_PET_CORR": 1.0, "OW_PET_CORR": 1.0,
    "FOREST_PET_CORR": 1.0, "WIND_VEL_CORR": 1.0, "RELHUM_CORR": 1.0,
    "MELT_FACTOR": 4.0, "MIN_MELT_FACTOR": 2.0, "MAX_MELT_FACTOR": 6.0,
    "DD_MELT_TEMP": 0.0, "DD_REFREEZE_TEMP": 0.0, "DD_AGGRADATION": 0.05,
    "REFREEZE_FACTOR": 2.0, "REFREEZE_EXP": 1.0, "SNOW_PATCH_LIMIT": 0.0,
    "HBV_MELT_FOR_CORR": 0.70, "HBV_MELT_ASP_CORR": 0.48,
    "HBV_MELT_GLACIER_CORR": 1.64, "HBV_GLACIER_KMIN": 0.05, "HBV_GLACIER_AG": 0.05,
    "GLAC_STORAGE_COEFF": 0.30, "CC_DECAY_COEFF": 0.05,
    "RAIN_MELT_MULT": 1.0, "CONV_MELT_MULT": 1.0, "COND_MELT_MULT": 1.0,
    "GAMMA_SHAPE": 3.0, "GAMMA_SCALE": 0.5, "GAMMA_SHAPE2": 3.0, "GAMMA_SCALE2": 0.5,
    "HMETS_RUNOFF_COEFF": 0.30, "AET_COEFF": 0.05,
    "PDM_B": 0.5, "PDMROF_B": 0.5, "PONDED_EXP": 2.0,
    "HYMOD2_G": 0.5, "HYMOD2_KMAX": 1.0, "HYMOD2_EXP": 1.0,
    "MAX_SAT_AREA_FRAC": 0.10, "BF_LOSS_FRACTION": 0.10, "STREAM_FRACTION": 0.01,
    "SCS_CN": 65.0, "SCS_IA_FRACTION": 0.1, "PARTITION_COEFF": 0.5,
    "B_EXP": 0.3, "ABST_PERCENT": 0.0,
    "DEP_MAX": 0.0, "MAX_DEP_AREA_FRAC": 0.0, "DEP_MAX_FLOW": 10.0,
    "DEP_N": 1.0, "DEP_SEEP_K": 0.01, "DEP_K": 0.05, "DEP_THRESHOLD": 0.0,
    "LAKE_REL_COEFF": 0.01, "PRIESTLEYTAYLOR_COEFF": 1.26,
    "UBC_ICEPT_FACTOR": 0.0, "GR4J_X4": 1.5,
    # --- vegetation ---
    "MAX_HEIGHT": 18.0, "MAX_LEAF_COND": 5.0, "MAX_LAI": 5.0,
    "RAIN_ICEPT_PCT": 0.05, "SNOW_ICEPT_PCT": 0.05,
    "RAIN_ICEPT_FACT": 0.06, "SNOW_ICEPT_FACT": 0.04,
    "SAI_HT_RATIO": 0.54, "TRUNK_FRACTION": 0.15, "STEMFLOW_FRAC": 0.03,
    "SVF_EXTINCTION": 0.5, "ALBEDO": 0.15, "ALBEDO_WET_VEG": 0.13,
    "MAX_CAPACITY": 10000.0, "MAX_SNOW_CAPACITY": 10000.0,
    "ROOT_EXTINCT": 2.0, "MAX_ROOT_LENGTH": 1000.0, "MIN_RESISTIVITY": 0.1,
}

# Soil-layer storage capacities [mm] for emulations where layer thickness
# encodes a conceptual store. thickness_m = capacity_mm / 1000 / porosity.
#   gr4j    : SOIL[0] production store = GR4J_X1 (Raven manual F.4)
#   sac_sma : SOIL[0..6] = UZTWM,UZFWM,LZTWM,LZFPM,LZFSM,ADIMC,GW (manual 3.8)
TEMPLATE_LAYER_STORAGE_MM = {
    "gr4j": [350.0, 300.0, 1000.0, 1000.0],
    "sac_sma": [50.0, 40.0, 130.0, 40.0, 25.0, 60.0, 1000.0],
}
# Generic layer thicknesses [m] used when the template has no storage semantics
GENERIC_LAYER_THICKNESS_M = [0.1, 0.3, 0.5, 1.0, 1.0, 1.0, 2.0]


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
                        tc = parts[10] if len(parts) > 10 else "DEFAULT_TERRAIN"
                        if tc != "[NONE]":
                            terrain_classes.add(tc)
                    except (ValueError, IndexError):
                        continue

    return (land_uses or {"MIXED_FOREST"},
            veg_classes or {"MIXED_VEG"},
            soil_profiles or {"DEFAULT_PROF"},
            terrain_classes or {"DEFAULT_TERRAIN"})


def query_required_parameters(rvi_path, raven_exe):
    """Ask the Raven binary which parameters this .rvi configuration requires.

    Runs Raven with :CreateRVPTemplate (only the .rvi is needed) and parses the
    emitted *.rvp_temp.rvp. Returns a dict with the required parameter names per
    block and the soil-profile layer count Raven expects.
    """
    if not os.path.isfile(raven_exe):
        raise RuntimeError(f"Raven executable not found: {raven_exe}")
    if not os.path.isfile(rvi_path):
        raise RuntimeError(f".rvi file not found (needed to query required parameters): {rvi_path}")

    workdir = tempfile.mkdtemp(prefix="rvp_template_")
    try:
        stem = "probe"
        probe_rvi = os.path.join(workdir, f"{stem}.rvi")
        with open(rvi_path) as src:
            body = src.read()
        # :CreateRVPTemplate turns off model operation; only the template is written
        body = re.sub(r"(?m)^\s*:CreateRVPTemplate\s*$", "", body)
        with open(probe_rvi, "w") as dst:
            dst.write(body.rstrip() + "\n\n:CreateRVPTemplate\n")

        proc = subprocess.run(
            [os.path.abspath(raven_exe), stem],
            cwd=workdir, capture_output=True, text=True, timeout=120,
        )

        tmpl = None
        for name in os.listdir(workdir):
            if name.endswith("_temp.rvp"):
                tmpl = os.path.join(workdir, name)
                break
        if tmpl is None:
            raise RuntimeError(
                "Raven did not emit an .rvp template for "
                f"{rvi_path}. stdout tail: {proc.stdout[-500:]}"
            )

        with open(tmpl) as f:
            lines = f.readlines()

        req = {"globals": [], "soil": [], "landuse": [], "vegetation": [], "n_layers": None}
        block = None
        for line in lines:
            s = line.strip()
            if s.startswith(":GlobalParameter"):
                toks = s.split()
                if len(toks) >= 2:
                    req["globals"].append(toks[1])
                continue
            if s.startswith(":SoilParameterList"):
                block = "soil"; continue
            if s.startswith(":LandUseParameterList"):
                block = "landuse"; continue
            if s.startswith(":VegetationParameterList"):
                block = "vegetation"; continue
            if s.startswith(":End"):
                block = None; continue
            if block and s.startswith(":Parameters"):
                toks = [t.strip() for t in s.split(",")]
                req[block] = [t for t in toks[1:] if t and not t.startswith("#")]
                continue
            if req["n_layers"] is None and s.startswith("*PROFILE_1*"):
                toks = [t.strip() for t in s.split(",")]
                if len(toks) >= 2:
                    try:
                        req["n_layers"] = int(toks[1])
                    except ValueError:
                        pass

        if req["n_layers"] is None:
            raise RuntimeError(f"could not parse soil layer count from Raven template {tmpl}")
        return req
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _fmt_table(block_name, param_names, rows):
    """Emit a Raven columnar *ParameterList block.

    rows: list of (class_name, {param: value}) — every class row carries a value
    for every column, so Raven's column alignment cannot drift.
    """
    out = [f":{block_name}"]
    out.append("  :Parameters,  " + ",  ".join(param_names) + ",")
    out.append("  :Units,       " + ",  ".join(["none"] * len(param_names)) + ",")
    for cls, vals in rows:
        cells = [f"{vals[p]:.6f}" for p in param_names]
        out.append(f"  {cls},  " + ",  ".join(cells) + ",")
    out.append(f":End{block_name}")
    return out


def generate_rvp_content(template, basin_name, land_uses, veg_classes,
                         soil_profiles, terrain_classes, required):
    """Generate .rvp content covering exactly the parameters Raven declared required."""
    unknown = sorted(
        {p for key in ("globals", "soil", "landuse", "vegetation") for p in required[key]}
        - set(PARAM_DEFAULTS)
    )
    if unknown:
        raise RuntimeError(
            "Raven requires parameters with no default in PARAM_DEFAULTS: "
            + ", ".join(unknown)
            + " — add literature values to build_rvp_parameters.PARAM_DEFAULTS "
              "(Raven manual Tables A.3-A.6) rather than emitting an incomplete .rvp."
        )

    n = required["n_layers"]
    soil_classes = [f"SOIL_L{i}" for i in range(n)]
    soil = DEFAULT_SOIL_BY_TEXTURE["LOAM"]
    porosity = soil["porosity"]

    caps = TEMPLATE_LAYER_STORAGE_MM.get(template)
    if caps and len(caps) >= n:
        thickness = [caps[i] / 1000.0 / porosity for i in range(n)]
    else:
        thickness = [GENERIC_LAYER_THICKNESS_M[min(i, len(GENERIC_LAYER_THICKNESS_M) - 1)]
                     for i in range(n)]

    lines = [
        f"# Raven .rvp file -- Parameters for {basin_name}",
        f"# Template: {template}",
        "# Generated by HydroCraft build_rvp_parameters.py",
        f"# Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "# Parameter set queried from the Raven binary via :CreateRVPTemplate",
        "",
        "# --- Soil Classes ---",
        ":SoilClasses",
        "  :Attributes,",
        "  :Units,",
    ]
    for sc in soil_classes:
        lines.append(f"  {sc},")
    lines += [":EndSoilClasses", ""]

    lines += ["# --- Soil Profiles ---", ":SoilProfiles"]
    for sp in sorted(soil_profiles):
        cells = []
        for i in range(n):
            cells.append(f"{soil_classes[i]},  {thickness[i]:.4f}")
        lines.append(f"  {sp},  {n},  " + ",  ".join(cells))
    lines += [":EndSoilProfiles", ""]

    # Soil parameters: [DEFAULT] row plus one row per layer class, so
    # per-layer parameters (e.g. SAC-SMA BASEFLOW_COEFF) can differ by layer.
    soil_vals = {p: PARAM_DEFAULTS[p] for p in required["soil"]}
    soil_vals.update({k: v for k, v in (
        ("POROSITY", porosity),
        ("FIELD_CAPACITY", soil["field_capacity"]),
        ("SAT_WILT", soil["wilting_point"]),
    ) if k in soil_vals})
    if required["soil"]:
        rows = [("[DEFAULT]", soil_vals)] + [(sc, soil_vals) for sc in soil_classes]
        lines += ["# --- Soil Parameters ---"] + _fmt_table(
            "SoilParameterList", required["soil"], rows) + [""]

    # Land use classes carry their own attribute block
    lines += [
        "# --- Land Use Classes ---",
        ":LandUseClasses,",
        "  :Attributes,  IMPERMEABLE_FRAC,  FOREST_COVERAGE,",
        "  :Units,       frac,              frac,",
    ]
    for lu in sorted(land_uses):
        imperm = 0.8 if lu == "URBAN" else 0.0
        forest = 0.9 if "FOREST" in lu or "LEAF" in lu else (0.5 if "SHRUB" in lu or "SAVANNA" in lu else 0.0)
        lines.append(f"  {lu},  {imperm:.2f},  {forest:.2f},")
    lines += [":EndLandUseClasses", ""]

    if required["landuse"]:
        lu_vals = {p: PARAM_DEFAULTS[p] for p in required["landuse"]}
        rows = [("[DEFAULT]", lu_vals)] + [(lu, lu_vals) for lu in sorted(land_uses)]
        lines += _fmt_table("LandUseParameterList", required["landuse"], rows) + [""]

    lines += [
        "# --- Vegetation Classes ---",
        ":VegetationClasses,",
        "  :Attributes,  MAX_HT,  MAX_LAI,  MAX_LEAF_COND,",
        "  :Units,       m,       none,     mm_per_s,",
    ]
    for vc in sorted(veg_classes):
        vp = DEFAULT_VEG_PARAMS.get(vc, DEFAULT_VEG_PARAMS["MIXED_VEG"])
        lines.append(f"  {vc},  {vp['max_ht']:.1f},  {vp['max_lai']:.1f},  {vp['max_leaf_cond']:.1f},")
    lines += [":EndVegetationClasses", ""]

    if required["vegetation"]:
        vg_vals = {p: PARAM_DEFAULTS[p] for p in required["vegetation"]}
        rows = [("[DEFAULT]", vg_vals)] + [(vc, vg_vals) for vc in sorted(veg_classes)]
        lines += _fmt_table("VegetationParameterList", required["vegetation"], rows) + [""]

    lines += ["# --- Terrain Classes ---",
              ":TerrainClasses,",
              "  :Attributes,  HILLSLOPE_LENGTH,  DRAINAGE_DENSITY,",
              "  :Units,       m,                 km/km2,"]
    for tc in sorted(terrain_classes):
        lines.append(f"  {tc},  500.0,  1.0,")
    lines += [":EndTerrainClasses", ""]

    if required["globals"]:
        lines.append("# --- Global Parameters ---")
        for pname in required["globals"]:
            lines.append(f":GlobalParameter {pname}  {PARAM_DEFAULTS[pname]:.6f}")
        lines.append("")

    return "\n".join(lines)


def build_rvp_file(template, basin_name, rvh_path, rvi_path, out_path,
                   raven_exe=RAVEN_EXE_DEFAULT):
    """Write a complete .rvp for one template. Stable entry point for callers
    (e.g. run_ensemble_comparison.py) that previously composed the pieces
    themselves. Returns the required-parameter set Raven declared."""
    land_uses, veg_classes, soil_profiles, terrain_classes = parse_rvh_classes(rvh_path)
    required = query_required_parameters(rvi_path, raven_exe)
    content = generate_rvp_content(template, basin_name, land_uses, veg_classes,
                                   soil_profiles, terrain_classes, required)
    with open(out_path, "w") as f:
        f.write(content)
    return required


def validate_inputs(args):
    errors = []
    if args.rvh_file and not os.path.isfile(args.rvh_file):
        errors.append(f"RVH file not found: {args.rvh_file}")
    if errors:
        return {"status": "error", "errors": errors}
    return {"status": "ok"}


def process(args):
    if args.rvh_file:
        land_uses, veg_classes, soil_profiles, terrain_classes = parse_rvh_classes(args.rvh_file)
    else:
        land_uses = {"MIXED_FOREST", "GRASSLAND", "CROPLAND"}
        veg_classes = {"MIXED_VEG", "GRASSLAND_VEG", "CROP_VEG"}
        soil_profiles = {"DEFAULT_PROF"}
        terrain_classes = {"DEFAULT_TERRAIN"}

    template = args.template or "hbv_ec"
    rvi_file = args.rvi_file or os.path.join(args.output_dir, f"{args.basin_name}.rvi")
    required = query_required_parameters(rvi_file, args.raven_exe)

    rvp_content = generate_rvp_content(
        template, args.basin_name,
        land_uses, veg_classes, soil_profiles, terrain_classes, required,
    )

    os.makedirs(args.output_dir, exist_ok=True)
    rvp_path = os.path.join(args.output_dir, f"{args.basin_name}.rvp")
    with open(rvp_path, "w") as f:
        f.write(rvp_content)

    return {
        "status": "success",
        "output_rvp": rvp_path,
        "template": template,
        "rvi_queried": rvi_file,
        "soil_layers": required["n_layers"],
        "classes": {
            "land_use": sorted(land_uses),
            "vegetation": sorted(veg_classes),
            "soil_profiles": sorted(soil_profiles),
            "terrain": sorted(terrain_classes),
        },
        "required_parameters": {
            "global": required["globals"],
            "soil": required["soil"],
            "landuse": required["landuse"],
            "vegetation": required["vegetation"],
        },
    }


def main():
    parser = argparse.ArgumentParser(description="Generate Raven .rvp parameters file")
    parser.add_argument("--template", default="hbv_ec", help="Model template name")
    parser.add_argument("--rvh_file", default=None, help="Path to .rvh file (to extract class names)")
    parser.add_argument("--rvi_file", default=None,
                        help="Path to .rvi file (default: <output_dir>/<basin_name>.rvi). "
                             "Queried via :CreateRVPTemplate for required parameters.")
    parser.add_argument("--raven_exe", default=RAVEN_EXE_DEFAULT, help="Path to Raven executable")
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
