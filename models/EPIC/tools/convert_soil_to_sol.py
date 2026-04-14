#!/usr/bin/env python3
"""
Convert HWSD soil + ROSETTA van Genuchten parameters into an EPIC0810 .SOL file.

Pattern: validate inputs -> lookup HWSD -> rosetta_vgn -> assemble 19-property
profile -> write fixed-width 6-layer SOL -> sanitize alpha codes.
"""

import os
import sys
import numpy as np

# 6 layer thicknesses in metres (cumulative depth from surface).
# These match the standard HWSD 6-layer convention.
DEFAULT_LAYER_DEPTHS_M = [0.05, 0.15, 0.30, 0.60, 1.00, 1.50]


def _try_lookup_hwsd(lat: float, lon: float):
    try:
        from ki_tools_common.soil_utils import lookup_hwsd, rosetta_vgn
    except ImportError as e:
        raise ImportError(
            "ki_tools_common.soil_utils is required. Add the kdt-release path to PYTHONPATH."
        ) from e
    soil = lookup_hwsd(lat, lon)
    vgn = rosetta_vgn(soil["sand"], soil["clay"])
    return soil, vgn


def build_profile(soil: dict, vgn: dict,
                  layer_depths_m: list = None) -> dict:
    """
    Build 19 EPIC soil properties × N layers from HWSD + ROSETTA outputs.

    Returns dict {property_name: list[float]} length len(layer_depths_m).
    """
    if layer_depths_m is None:
        layer_depths_m = DEFAULT_LAYER_DEPTHS_M
    n_layers = len(layer_depths_m)

    sand = float(soil.get("sand", 40.0))
    silt = float(soil.get("silt", 40.0))
    clay = float(soil.get("clay", 20.0))
    bd = float(soil.get("bulk_density", 1.4))
    om = float(soil.get("organic_matter", 1.0))
    ph = float(soil.get("ph", 6.5))
    cec = float(soil.get("cec", 12.0))
    caco3 = float(soil.get("caco3", 0.0))

    oc = om / 1.724  # Van Bemmelen factor

    fc = float(vgn.get("field_capacity", 0.30))
    wp = float(vgn.get("wilting_point", 0.12))
    ksat_mmhr = float(vgn.get("ksat_mmhr", 10.0))

    rep = lambda x: [float(x)] * n_layers
    profile = {
        "Layer_depth_m":          list(layer_depths_m),
        "Bulk_density":           rep(bd),
        "Wilting_point":          rep(wp),
        "Field_capacity":         rep(fc),
        "Sand_pct":               rep(sand),
        "Silt_pct":               rep(silt),
        "Initial_soil_water":     rep(fc * 0.8),
        "Organic_N_g_t":          rep(oc * 100.0),
        "pH":                     rep(ph),
        "Sum_bases":              rep(cec * 0.6),
        "Organic_C_pct":          rep(oc),
        "CaCO3_pct":              rep(caco3),
        "CEC":                    rep(cec),
        "Coarse_frag_pct":        rep(0.0),
        "Initial_NO3_g_t":        rep(5.0),
        "Initial_labile_P_g_t":   rep(15.0),
        "Crop_residue_t_ha":      rep(0.0),
        "BD_dry":                 rep(bd),
        "Ksat_mmhr":              rep(ksat_mmhr),
    }
    return profile


def write_sol(profile: dict, sol_path: str, soil_name: str = "HWSD_SOIL",
              soil_order: str = "INCEPTISOL", albedo: float = 0.20,
              hyd_grp: int = 2, lat: float = 0.0, slope_pct: float = 1.0) -> None:
    """
    Write an EPIC0810-compatible SOL file with all numeric tokens
    (no alphabetic structure codes).

    Layout:
      Line 1: free-text header
      Line 2: 10 site-level reals (8.2f)
      Line 3: 10 site-level reals (8.2f)
      Lines 4-22: 19 property rows × N layers (8.2f each)
    """
    n_layers = len(profile["Layer_depth_m"])

    with open(sol_path, "w") as f:
        f.write(f"{soil_name:25s}{soil_order}\n")

        # Site reals row 1: albedo  hyd_grp  depth(m)  min_thick  spl  rcr  cn2  ridge  rsd  zsr
        row1 = [albedo, float(hyd_grp), float(profile["Layer_depth_m"][-1]),
                50.0, 100.0, 75.0, 25.0, 50.0, 0.0, 0.0]
        f.write("".join(f"{v:8.2f}" for v in row1) + "\n")

        # Site reals row 2: more parameters (slope length, steepness, ...)
        row2 = [10.00, 3.00, 100.00, 1.00, slope_pct, 0.10, 1.00, 0.04, 0.50, 0.00]
        f.write("".join(f"{v:8.2f}" for v in row2) + "\n")

        property_order = [
            "Layer_depth_m", "Bulk_density", "Wilting_point", "Field_capacity",
            "Sand_pct", "Silt_pct", "Initial_soil_water", "Organic_N_g_t",
            "pH", "Sum_bases", "Organic_C_pct", "CaCO3_pct", "CEC",
            "Coarse_frag_pct", "Initial_NO3_g_t", "Initial_labile_P_g_t",
            "Crop_residue_t_ha", "BD_dry", "Ksat_mmhr",
        ]
        for prop in property_order:
            vals = profile[prop]
            f.write("".join(f"{v:8.2f}" for v in vals) + "\n")


def validate_sol(sol_path: str) -> list:
    """Open the SOL we just wrote and check for any alpha tokens."""
    errors = []
    if not os.path.exists(sol_path):
        return [f"ERROR: {sol_path} not produced"]
    import re
    with open(sol_path) as f:
        for i, line in enumerate(f, start=1):
            if i == 1:
                continue
            if re.search(r"[A-Za-z]", line):
                errors.append(f"ERROR: alpha character on line {i}: {line.rstrip()}")
    return errors


def convert(lat: float, lon: float, sol_path: str,
            soil_name: str = None, slope_pct: float = 1.0) -> dict:
    """Top-level pipeline: HWSD lookup -> ROSETTA -> write SOL -> validate."""
    soil, vgn = _try_lookup_hwsd(lat, lon)
    profile = build_profile(soil, vgn)
    name = soil_name or f"hwsd_{lat:.2f}_{lon:.2f}"
    write_sol(profile, sol_path, soil_name=name,
              hyd_grp=int(soil.get("hyd_group", 2)),
              lat=lat, slope_pct=slope_pct)
    errors = validate_sol(sol_path)
    if errors:
        raise ValueError(f"SOL validation failed: {errors}")
    return {"sol": sol_path, "n_layers": len(profile["Layer_depth_m"]), "soil": soil}


def main():
    import argparse, json
    p = argparse.ArgumentParser()
    p.add_argument("--lat", type=float, required=True)
    p.add_argument("--lon", type=float, required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()
    result = convert(args.lat, args.lon, args.out)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
