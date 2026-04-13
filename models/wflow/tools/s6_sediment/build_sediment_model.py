#!/usr/bin/env python3
"""
build_sediment_model.py — Build wflow_sediment model for erosion & transport simulation.

wflow_sediment is a post-processor that uses wflow_sbm hydrological outputs
(overland flow, precipitation intensity) to compute:
  - Splash erosion (EUROSEM or ANSWERS method)
  - Overland flow erosion (ANSWERS with USLE C and K factors)
  - In-stream sediment transport (5 capacity formulas)
  - Deposition (Einstein's settling velocity equation)

Grain size classes: clay (2um), silt (10um), sand (200um),
  small aggregates (30um), large aggregates (500um)

Required additional data:
  - USLE C factor (from land use classification)
  - USLE K factor (from soil texture: clay/silt/sand fractions)
  - Canopy height (for EUROSEM splash erosion)
  - River bed D50 (for transport capacity)

Usage:
    python build_sediment_model.py \
      --sbm_staticmaps /path/to/wflow_sbm/staticmaps.nc \
      --output_dir /path/to/wflow_sediment_project \
      --erosion_method answers \
      --transport_formula engelund_hansen
"""

import argparse
import json
import os
import sys

import numpy as np


# USLE C factor lookup by land cover class (AVHRR/GlobCover)
# C=0 means no erosion (water, urban); C=1 means bare soil
USLE_C_LOOKUP = {
    0: 0.0,    # Water
    1: 0.003,  # Evergreen needleleaf forest
    2: 0.003,  # Evergreen broadleaf forest
    3: 0.003,  # Deciduous needleleaf forest
    4: 0.003,  # Deciduous broadleaf forest
    5: 0.003,  # Mixed forest
    6: 0.01,   # Closed shrubland
    7: 0.05,   # Open shrubland
    8: 0.01,   # Woody savanna
    9: 0.05,   # Savanna
    10: 0.03,  # Grassland
    11: 0.0,   # Wetland
    12: 0.30,  # Cropland
    13: 0.0,   # Urban
    14: 0.15,  # Cropland/natural mosaic
    15: 0.0,   # Snow/ice
    16: 0.45,  # Barren/sparse
    17: 0.0,   # Unclassified
}

# USLE K factor estimation from soil texture (Wischmeier & Smith, 1978)
# K in SI: t*ha*h / (ha*MJ*mm)


def estimate_usle_k(clay_pct, silt_pct, sand_pct, om_pct=2.0):
    """Estimate USLE K factor from soil texture.

    Uses the Wischmeier & Smith (1978) equation with organic matter correction.

    Parameters
    ----------
    clay_pct : float or ndarray — clay content (%)
    silt_pct : float or ndarray — silt content (%)
    sand_pct : float or ndarray — sand content (%)
    om_pct : float — organic matter content (%, default 2.0)

    Returns
    -------
    K : float or ndarray — USLE K factor (t*ha*h/(ha*MJ*mm))
    """
    # Modified silt factor
    M = (silt_pct + 0.2 * sand_pct) * (100.0 - clay_pct)

    # Wischmeier nomograph approximation
    K = (
        2.1e-4 * M ** 1.14 * (12.0 - om_pct)
        + 3.25 * (2.0 - 1)  # structure code 2 (medium granular)
        + 2.5 * (3.0 - 3)   # permeability class 3 (slow to moderate)
    ) / 100.0

    # Clamp to reasonable range
    K = np.clip(K, 0.001, 0.1)
    return K


def validate_inputs(args):
    """Validate inputs."""
    errors = []

    if not os.path.exists(args.sbm_staticmaps):
        errors.append(f"SBM staticmaps not found: {args.sbm_staticmaps}")

    valid_erosion = ["eurosem", "answers"]
    if args.erosion_method not in valid_erosion:
        errors.append(f"erosion_method must be one of {valid_erosion}")

    valid_transport = [
        "bagnold", "engelund_hansen", "kodatie", "yang", "molinas_wu"
    ]
    if args.transport_formula not in valid_transport:
        errors.append(f"transport_formula must be one of {valid_transport}")

    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


def process(args):
    """Build sediment model staticmaps and TOML."""
    import xarray as xr

    ds_sbm = xr.open_dataset(args.sbm_staticmaps)

    # Get basin mask
    if "wflow_subcatch" in ds_sbm:
        mask = ds_sbm["wflow_subcatch"].values > 0
    else:
        # Try any variable
        first_var = list(ds_sbm.data_vars)[0]
        mask = np.isfinite(ds_sbm[first_var].values) & (ds_sbm[first_var].values != 0)

    ny, nx = mask.shape
    print(f"  Grid: {nx} x {ny}, active cells: {mask.sum()}", file=sys.stderr)

    # --- Create sediment parameters ---

    # USLE C factor (default: use moderate cropland value)
    usle_c = np.where(mask, 0.15, 0.0).astype(np.float32)  # moderate default

    # USLE K factor (from soil texture if available, else default)
    if "clay" in ds_sbm and "silt" in ds_sbm and "sand" in ds_sbm:
        clay = ds_sbm["clay"].values
        silt = ds_sbm["silt"].values
        sand = ds_sbm["sand"].values
        usle_k = estimate_usle_k(clay, silt, sand)
    else:
        usle_k = np.where(mask, 0.035, 0.0).astype(np.float32)  # moderate silt loam

    # Canopy height (m) — default 5m for mixed vegetation
    canopy_height = np.where(mask, 5.0, 0.0).astype(np.float32)

    # Grain size fractions (must sum to 1.0)
    # Default: typical temperate river sediment
    clay_frac = np.where(mask, 0.10, 0.0).astype(np.float32)
    silt_frac = np.where(mask, 0.30, 0.0).astype(np.float32)
    sand_frac = np.where(mask, 0.35, 0.0).astype(np.float32)
    sagg_frac = np.where(mask, 0.15, 0.0).astype(np.float32)
    lagg_frac = np.where(mask, 0.10, 0.0).astype(np.float32)

    # Check grain fractions sum
    total_frac = clay_frac + silt_frac + sand_frac + sagg_frac + lagg_frac
    bad_cells = mask & (np.abs(total_frac - 1.0) > 0.01)
    if bad_cells.any():
        print(f"  WARNING: {bad_cells.sum()} cells have grain fractions not summing to 1.0",
              file=sys.stderr)

    # River bed D50 (mm) — for transport capacity
    d50 = np.where(mask, 0.5, 0.0).astype(np.float32)  # medium sand

    # Slope (from SBM if available)
    if "RiverSlope" in ds_sbm:
        slope = ds_sbm["RiverSlope"].values
    else:
        slope = np.where(mask, 0.01, 0.0).astype(np.float32)

    # Create sediment staticmaps
    coords = {dim: ds_sbm[dim].values for dim in ["y", "x"] if dim in ds_sbm.coords}
    if not coords:
        coords = {dim: ds_sbm[dim].values for dim in ["lat", "lon"] if dim in ds_sbm.coords}

    ds_sed = xr.Dataset(
        {
            "wflow_subcatch": (["y", "x"], ds_sbm["wflow_subcatch"].values if "wflow_subcatch" in ds_sbm else mask.astype(np.int32)),
            "USLE_C": (["y", "x"], usle_c, {"long_name": "USLE C factor", "units": "-"}),
            "USLE_K": (["y", "x"], usle_k.astype(np.float32), {"long_name": "USLE K factor", "units": "t*ha*h/(ha*MJ*mm)"}),
            "CanopyHeight": (["y", "x"], canopy_height, {"long_name": "Canopy height", "units": "m"}),
            "D50": (["y", "x"], d50, {"long_name": "River bed median grain size", "units": "mm"}),
            "ClayFrac": (["y", "x"], clay_frac, {"long_name": "Clay fraction of soil", "units": "-"}),
            "SiltFrac": (["y", "x"], silt_frac, {"long_name": "Silt fraction of soil", "units": "-"}),
            "SandFrac": (["y", "x"], sand_frac, {"long_name": "Sand fraction of soil", "units": "-"}),
            "SAggFrac": (["y", "x"], sagg_frac, {"long_name": "Small aggregate fraction", "units": "-"}),
            "LAggFrac": (["y", "x"], lagg_frac, {"long_name": "Large aggregate fraction", "units": "-"}),
            "Slope": (["y", "x"], slope.astype(np.float32), {"long_name": "Land surface slope", "units": "m/m"}),
        },
        coords=coords,
    )

    ds_sed.attrs["title"] = "wflow_sediment static maps"
    ds_sed.attrs["erosion_method"] = args.erosion_method
    ds_sed.attrs["transport_formula"] = args.transport_formula

    # Save
    os.makedirs(args.output_dir, exist_ok=True)
    staticmaps_path = os.path.join(args.output_dir, "staticmaps_sediment.nc")
    ds_sed.to_netcdf(staticmaps_path)

    # Generate sediment TOML
    toml_path = os.path.join(args.output_dir, "wflow_sediment.toml")
    with open(toml_path, "w") as f:
        f.write("# wflow_sediment configuration\n")
        f.write("# Generated by HydroCraft build_sediment_model.py\n\n")
        f.write("[model]\n")
        f.write('type = "sediment"\n')
        f.write(f'erosion_method = "{args.erosion_method}"\n')
        f.write(f'transport_formula = "{args.transport_formula}"\n\n')
        f.write("[input]\n")
        f.write(f'path_static = "{staticmaps_path}"\n')
        f.write(f'# path_forcing = "<set to wflow_sbm output>"\n\n')
        f.write("[output]\n")
        f.write(f'path = "{args.output_dir}/output"\n\n')
        f.write("[[output.gridded.variable]]\n")
        f.write('name = "soilloss"\n\n')
        f.write("[[output.gridded.variable]]\n")
        f.write('name = "sediment_concentration"\n\n')

    ds_sbm.close()

    return {
        "status": "success",
        "staticmaps_path": staticmaps_path,
        "toml_path": toml_path,
        "erosion_method": args.erosion_method,
        "transport_formula": args.transport_formula,
        "grid_cells": int(mask.sum()),
        "mean_USLE_C": round(float(np.mean(usle_c[mask])), 4),
        "mean_USLE_K": round(float(np.mean(usle_k[mask])), 4),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Build wflow_sediment model"
    )
    parser.add_argument("--sbm_staticmaps", type=str, required=True)
    parser.add_argument("--output_dir", type=str, required=True)
    parser.add_argument("--erosion_method", type=str, default="answers",
                        choices=["eurosem", "answers"])
    parser.add_argument("--transport_formula", type=str, default="engelund_hansen",
                        choices=["bagnold", "engelund_hansen", "kodatie", "yang", "molinas_wu"])
    args = parser.parse_args()

    validate_inputs(args)

    try:
        result = process(args)
    except Exception as e:
        print(json.dumps({"status": "failed", "error": str(e)}, indent=2))
        sys.exit(2)

    print(json.dumps(result, indent=2))
    sys.exit(0 if result["status"] == "success" else 2)


if __name__ == "__main__":
    main()
