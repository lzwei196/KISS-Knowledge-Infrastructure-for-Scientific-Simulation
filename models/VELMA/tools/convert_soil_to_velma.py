#!/usr/bin/env python3
"""
convert_soil_to_velma.py -- Convert soil data to VELMA 4-layer soil parameters.

Translates soil properties from HWSD, SoilGrids, or manual input into the
4-layer soil parameters required by the VELMA multi-layer hydrology model.

Output parameters per layer (4 layers):
  Ksat      mm/d    Saturated hydraulic conductivity
  porosity  --      Porosity (fraction)
  fc_frac   --      Field capacity as fraction of saturation
  wp_frac   --      Wilting point as fraction of saturation

Plus routing and process parameters:
  perc1-3   1/d     Percolation rate coefficients (L1->L2, L2->L3, L3->L4)
  klat1-4   1/d     Lateral flow coefficients per layer
  k_base    1/d     Baseflow recession from L4
  k_fast    1/d     Fast routing reservoir recession
  k_slow    1/d     Slow routing reservoir recession
  split     --      Fast/slow routing split
  f_direct  --      Direct runoff fraction (impervious area)
  pet_scale --      PET scaling factor
  ddf       mm/K/d  Degree-day factor for snow melt
  t_snow    K       Snow/rain temperature threshold
  t_melt    K       Snowmelt temperature threshold

CRITICAL UNIT TRAPS:
  - Ks in HWSD is often in mm/h or cm/h. Must convert to mm/d (dt_008, dt_009).
    Using hourly Ks in a daily model makes percolation capacity 24x too low.
  - Porosity from some databases is in percent (0-100). Must be fraction (0-1) (dt_010).
  - Layer thickness must be in mm internally. Input in cm is x10 (dt_011).

VELMA layer structure:
  L1: 0-10 cm   (100 mm)   Fast response, high root density
  L2: 10-50 cm  (400 mm)   Main root zone
  L3: 50-150 cm (1000 mm)  Deep roots, slow interflow
  L4: 150-300 cm (1500 mm) Groundwater store

Usage:
    python convert_soil_to_velma.py \\
        --texture "silt loam" \\
        --depth-cm 300 \\
        --output params.json

    python convert_soil_to_velma.py \\
        --soil-csv /path/to/hwsd_extract.csv \\
        --ks-unit mm/h \\
        --output params.json

    python convert_soil_to_velma.py \\
        --ks-mm-d 25.0 --porosity 0.50 \\
        --output params.json
"""

import argparse
import json
import os
import sys

import numpy as np


# ---- Soil texture lookup table ------------------------------------------------
# Source: Rawls, Brakensiek, and Miller (1983), Table 1
# "Green-Ampt Infiltration Parameters from Soils Data"
# Journal of Hydraulic Engineering, 109(1), 62-70.
#
# Plus Clapp & Hornberger (1978) for porosity/FC/WP by texture.
# Columns: Ks (mm/h), porosity, field_capacity (fraction), wilting_point (fraction)

RAWLS_TABLE = {
    "sand":            {"Ks_mm_h": 117.8, "porosity": 0.437, "fc": 0.062, "wp": 0.024},
    "loamy sand":      {"Ks_mm_h": 29.9,  "porosity": 0.437, "fc": 0.105, "wp": 0.047},
    "sandy loam":      {"Ks_mm_h": 10.9,  "porosity": 0.453, "fc": 0.190, "wp": 0.085},
    "loam":            {"Ks_mm_h": 3.4,   "porosity": 0.463, "fc": 0.232, "wp": 0.116},
    "silt loam":       {"Ks_mm_h": 6.5,   "porosity": 0.501, "fc": 0.284, "wp": 0.135},
    "sandy clay loam": {"Ks_mm_h": 1.5,   "porosity": 0.398, "fc": 0.244, "wp": 0.136},
    "clay loam":       {"Ks_mm_h": 1.0,   "porosity": 0.464, "fc": 0.310, "wp": 0.187},
    "silty clay loam": {"Ks_mm_h": 1.0,   "porosity": 0.471, "fc": 0.342, "wp": 0.210},
    "sandy clay":      {"Ks_mm_h": 0.6,   "porosity": 0.430, "fc": 0.321, "wp": 0.221},
    "silty clay":      {"Ks_mm_h": 0.5,   "porosity": 0.479, "fc": 0.371, "wp": 0.251},
    "clay":            {"Ks_mm_h": 0.3,   "porosity": 0.475, "fc": 0.378, "wp": 0.265},
}

# Unit conversion constants
MM_H_TO_MM_D = 24.0    # mm/h -> mm/d  (x 24 hours/day)
CM_H_TO_MM_D = 240.0   # cm/h -> mm/d  (x 10 mm/cm x 24 h/d)
CM_TO_MM = 10.0         # cm -> mm

# VELMA default layer thicknesses (mm) and depths (cm)
LAYER_THICK_MM = np.array([100.0, 400.0, 1000.0, 1500.0])
LAYER_DEPTHS_CM = np.array([10.0, 50.0, 150.0, 300.0])  # bottom of each layer
N_LAYERS = 4

# Root fraction per layer (for ET partitioning -- informational)
ROOT_FRAC = np.array([0.30, 0.40, 0.25, 0.05])

# Parameter bounds for VELMA model
PARAM_BOUNDS = {
    "pet_scale": (0.3,   2.5),
    "perc1":     (0.1,   0.9),
    "perc2":     (0.05,  0.7),
    "perc3":     (0.01,  0.5),
    "klat1":     (0.01,  0.8),
    "klat2":     (0.005, 0.5),
    "klat3":     (0.001, 0.3),
    "klat4":     (0.001, 0.1),
    "k_base":    (0.001, 0.1),
    "k_fast":    (0.05,  0.9),
    "k_slow":    (0.005, 0.15),
    "split":     (0.1,   0.9),
    "f_direct":  (0.01,  0.20),
    "ddf":       (1.0,   8.0),
}


def validate_inputs(args):
    """Validate all inputs before processing. Returns list of errors."""
    errors = []

    if args.soil_csv and not os.path.isfile(args.soil_csv):
        errors.append(f"Soil CSV file not found: {args.soil_csv}")

    if args.texture and args.texture.lower() not in RAWLS_TABLE:
        known = ", ".join(sorted(RAWLS_TABLE.keys()))
        errors.append(
            f"Unknown texture class '{args.texture}'. "
            f"Known classes: {known}")

    if args.ks_unit not in ["mm/h", "cm/h", "mm/d"]:
        errors.append(
            f"Invalid Ks unit '{args.ks_unit}'. Must be mm/h, cm/h, or mm/d.")

    if args.porosity is not None and not (0.0 < args.porosity < 1.0):
        errors.append(f"Porosity must be between 0 and 1, got {args.porosity}")

    if args.depth_cm is not None and args.depth_cm <= 0:
        errors.append(f"Soil depth must be positive, got {args.depth_cm}")

    if args.ks_mm_d is not None and args.ks_mm_d <= 0:
        errors.append(f"Ks must be positive, got {args.ks_mm_d}")

    # Check for no input source
    if not args.texture and not args.soil_csv and args.ks_mm_d is None:
        errors.append(
            "Must specify one of: --texture, --soil-csv, or --ks-mm-d")

    return errors


def convert_ks_to_mm_d(ks_value, from_unit):
    """Convert saturated hydraulic conductivity to mm/d.

    CRITICAL: Using mm/h values in a daily model makes percolation capacity
    24x too low, causing excessive surface runoff (dt_008).
    """
    if from_unit == "mm/d":
        return ks_value
    elif from_unit == "mm/h":
        return ks_value * MM_H_TO_MM_D
    elif from_unit == "cm/h":
        return ks_value * CM_H_TO_MM_D
    else:
        raise ValueError(f"Unknown Ks unit: {from_unit}")


def get_base_properties(args, log):
    """Extract base soil properties from the specified input source.

    Returns (Ks_mm_d, porosity, fc_volumetric, wp_volumetric).
    """
    if args.texture:
        key = args.texture.lower().strip()
        entry = RAWLS_TABLE[key]
        ks_mm_d = entry["Ks_mm_h"] * MM_H_TO_MM_D
        porosity = entry["porosity"]
        fc = entry["fc"]
        wp = entry["wp"]
        log.append(f"Texture class '{key}': Ks={ks_mm_d:.1f} mm/d, "
                   f"n={porosity:.3f}, FC={fc:.3f}, WP={wp:.3f}")
        return ks_mm_d, porosity, fc, wp

    elif args.soil_csv:
        import pandas as pd
        df = pd.read_csv(args.soil_csv)
        ks_col = [c for c in df.columns if "ks" in c.lower() or "ksat" in c.lower()]
        n_col = [c for c in df.columns if "porosity" in c.lower() or "por" in c.lower()]
        fc_col = [c for c in df.columns if "fc" in c.lower() or "field" in c.lower()]
        wp_col = [c for c in df.columns if "wp" in c.lower() or "wilt" in c.lower()]

        ks_raw = float(df[ks_col[0]].mean()) if ks_col else 6.5  # silt loam default
        ks_mm_d = convert_ks_to_mm_d(ks_raw, args.ks_unit)

        porosity = float(df[n_col[0]].mean()) if n_col else 0.45
        if porosity > 1.0:
            log.append(f"[WARN] Porosity = {porosity} > 1.0 -- assuming percent, "
                       f"dividing by 100 (dt_010)")
            porosity /= 100.0

        fc = float(df[fc_col[0]].mean()) if fc_col else 0.28
        wp = float(df[wp_col[0]].mean()) if wp_col else 0.13

        log.append(f"From CSV: Ks={ks_mm_d:.1f} mm/d, n={porosity:.3f}, "
                   f"FC={fc:.3f}, WP={wp:.3f}")
        return ks_mm_d, porosity, fc, wp

    else:
        # Manual specification
        ks_mm_d = args.ks_mm_d
        porosity = args.porosity if args.porosity else 0.45
        fc = args.fc if args.fc else 0.28
        wp = args.wp if args.wp else 0.13
        log.append(f"Manual: Ks={ks_mm_d:.1f} mm/d, n={porosity:.3f}, "
                   f"FC={fc:.3f}, WP={wp:.3f}")
        return ks_mm_d, porosity, fc, wp


def build_4layer_params(ks_mm_d, porosity, fc_vol, wp_vol, depth_cm, log):
    """Build VELMA 4-layer soil parameters from base properties.

    Soil properties vary with depth:
    - Porosity decreases (compaction)
    - Ks decreases (denser structure)
    - FC fraction of saturation increases (more retained water)
    - WP fraction of saturation increases (more bound water)

    Returns dict with per-layer arrays and process parameters.
    """
    # Depth-dependent scaling factors (relative to surface values)
    # Based on typical soil profile observations
    porosity_scale = np.array([1.00, 0.93, 0.84, 0.78])
    ks_scale = np.array([1.00, 0.70, 0.40, 0.20])
    fc_frac_scale = np.array([1.00, 1.09, 1.18, 1.27])   # FC fraction increases with depth
    wp_frac_scale = np.array([1.00, 1.10, 1.25, 1.40])    # WP fraction increases with depth

    # Compute per-layer properties
    layer_porosity = np.clip(porosity * porosity_scale, 0.20, 0.60)
    layer_ks = ks_mm_d * ks_scale

    # FC and WP as fractions of saturation (porosity * thickness)
    # Convert volumetric FC/WP to fraction of saturation
    fc_sat_frac = np.clip(fc_vol / porosity, 0.3, 0.85) if porosity > 0 else 0.55
    wp_sat_frac = np.clip(wp_vol / porosity, 0.1, 0.5) if porosity > 0 else 0.20

    layer_fc_frac = np.clip(fc_sat_frac * fc_frac_scale, 0.30, 0.85)
    layer_wp_frac = np.clip(wp_sat_frac * wp_frac_scale, 0.10, 0.50)

    # Layer capacities (mm)
    layer_cap = layer_porosity * LAYER_THICK_MM
    layer_fc = layer_fc_frac * layer_cap
    layer_wp = layer_wp_frac * layer_cap

    log.append("4-layer soil parameters:")
    for i in range(N_LAYERS):
        log.append(
            f"  L{i+1}: thick={LAYER_THICK_MM[i]:.0f} mm, "
            f"n={layer_porosity[i]:.3f}, Ks={layer_ks[i]:.1f} mm/d, "
            f"Cap={layer_cap[i]:.1f} mm, FC={layer_fc[i]:.1f} mm, "
            f"WP={layer_wp[i]:.1f} mm")

    # Estimate process parameters from soil properties
    # Percolation rates: sandier (higher Ks) -> faster percolation
    ks_norm = np.clip(np.log10(max(ks_mm_d, 1.0)) / np.log10(3000), 0, 1)

    perc1 = 0.2 + 0.5 * ks_norm    # L1->L2: fast for sandy soils
    perc2 = 0.1 + 0.4 * ks_norm    # L2->L3
    perc3 = 0.05 + 0.25 * ks_norm  # L3->L4: slower

    # Lateral flow: higher for sandier soils near surface
    klat1 = 0.05 + 0.3 * ks_norm
    klat2 = 0.02 + 0.15 * ks_norm
    klat3 = 0.005 + 0.05 * ks_norm
    klat4 = 0.002 + 0.02 * ks_norm

    # Baseflow: slower for deeper/finer soils
    depth_factor = np.clip(depth_cm / 300.0, 0, 1)
    k_base = 0.05 - 0.04 * (1.0 - ks_norm) * depth_factor

    # Routing parameters
    k_fast = 0.15 + 0.3 * ks_norm
    k_slow = 0.01 + 0.03 * (1.0 - ks_norm)
    split = 0.4 + 0.2 * ks_norm

    # Clip to bounds
    def clip_param(name, val):
        lo, hi = PARAM_BOUNDS[name]
        return float(np.clip(val, lo, hi))

    params = {
        # Layer properties
        "layer_thickness_mm": LAYER_THICK_MM.tolist(),
        "layer_porosity": layer_porosity.tolist(),
        "layer_fc_frac": layer_fc_frac.tolist(),
        "layer_wp_frac": layer_wp_frac.tolist(),
        "layer_ks_mm_d": layer_ks.tolist(),
        "layer_cap_mm": layer_cap.tolist(),
        "layer_fc_mm": layer_fc.tolist(),
        "layer_wp_mm": layer_wp.tolist(),
        "root_frac": ROOT_FRAC.tolist(),

        # Process parameters (initial estimates for calibration)
        "pet_scale": clip_param("pet_scale", 1.0),
        "perc1": clip_param("perc1", perc1),
        "perc2": clip_param("perc2", perc2),
        "perc3": clip_param("perc3", perc3),
        "klat1": clip_param("klat1", klat1),
        "klat2": clip_param("klat2", klat2),
        "klat3": clip_param("klat3", klat3),
        "klat4": clip_param("klat4", klat4),
        "k_base": clip_param("k_base", k_base),
        "k_fast": clip_param("k_fast", k_fast),
        "k_slow": clip_param("k_slow", k_slow),
        "split": clip_param("split", split),
        "f_direct": clip_param("f_direct", 0.05),
        "ddf": clip_param("ddf", 3.0),
        "t_snow": 273.15,
        "t_melt": 273.15,
    }

    return params


def validate_outputs(params, log):
    """Validate parameter set for physical plausibility.

    Returns True if all checks pass.
    """
    ok = True

    # Check per-layer consistency
    for i in range(N_LAYERS):
        cap = params["layer_cap_mm"][i]
        fc = params["layer_fc_mm"][i]
        wp = params["layer_wp_mm"][i]

        if wp >= fc:
            log.append(f"[CRITICAL] L{i+1}: WP ({wp:.1f}) >= FC ({fc:.1f})")
            ok = False
        if fc >= cap:
            log.append(f"[CRITICAL] L{i+1}: FC ({fc:.1f}) >= Cap ({cap:.1f})")
            ok = False
        if cap <= 0:
            log.append(f"[CRITICAL] L{i+1}: Cap = {cap:.1f} <= 0")
            ok = False

    # Check percolation rates decrease with depth
    percs = [params["perc1"], params["perc2"], params["perc3"]]
    if not (percs[0] >= percs[1] >= percs[2]):
        log.append("[WARN] Percolation rates do not decrease with depth "
                   f"({percs}) -- unusual but not necessarily wrong")

    # Check lateral flow rates decrease with depth
    klats = [params["klat1"], params["klat2"], params["klat3"], params["klat4"]]
    if not (klats[0] >= klats[1] >= klats[2] >= klats[3]):
        log.append("[WARN] Lateral flow coefficients do not decrease with depth "
                   f"({klats}) -- unusual but not necessarily wrong")

    # Check routing split
    if params["split"] < 0.1 or params["split"] > 0.9:
        log.append(f"[WARN] Routing split = {params['split']:.2f} is extreme "
                   "(expected 0.3-0.7 for most basins)")

    # Check process parameters are within bounds
    for name, (lo, hi) in PARAM_BOUNDS.items():
        val = params.get(name)
        if val is not None and (val < lo or val > hi):
            log.append(f"[WARN] {name} = {val} outside bounds [{lo}, {hi}]")

    return ok


def process(args, log):
    """Main processing pipeline: load -> convert -> build -> validate -> output."""

    # Get base soil properties
    ks_mm_d, porosity, fc_vol, wp_vol = get_base_properties(args, log)

    depth_cm = args.depth_cm if args.depth_cm else 300.0

    # Build 4-layer parameters
    params = build_4layer_params(ks_mm_d, porosity, fc_vol, wp_vol, depth_cm, log)

    # Validate outputs
    outputs_ok = validate_outputs(params, log)
    if not outputs_ok:
        log.append("[CRITICAL] Output validation failed")

    # Add metadata
    output = {
        "model": "VELMA",
        "n_layers": N_LAYERS,
        "source_texture": args.texture or "manual",
        "source_ks_unit": args.ks_unit,
        "total_depth_cm": depth_cm,
        "parameters": params,
        "parameter_bounds": {k: list(v) for k, v in PARAM_BOUNDS.items()},
        "notes": [
            "Layer properties are initial estimates from pedotransfer functions.",
            "Process parameters (perc, klat, routing) are initial estimates for calibration.",
            "Run calibration to optimize process parameters against observed discharge.",
            "Layer FC/WP are expressed as fractions of saturation, NOT as absolute storages.",
        ],
    }

    return {"status": "success", "output": output, "log": log}


def main():
    parser = argparse.ArgumentParser(
        description="Convert soil data to VELMA 4-layer parameters.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
VELMA layer structure:
  L1: 0-10 cm   (100 mm)   Fast interflow
  L2: 10-50 cm  (400 mm)   Root zone
  L3: 50-150 cm (1000 mm)  Deep roots
  L4: 150-300 cm (1500 mm) Groundwater

CRITICAL UNIT TRAPS:
  dt_008: Ks in mm/h, not mm/d -- percolation 24x too low
  dt_009: Ks in cm/h, not mm/d -- percolation 240x too low
  dt_010: Porosity in percent, not fraction -- cap 100x too large
""")

    # Input sources (mutually exclusive in practice but not enforced)
    parser.add_argument("--texture", type=str, default=None,
                        help="USDA texture class (e.g., 'silt loam', 'clay')")
    parser.add_argument("--soil-csv", type=str, default=None,
                        help="Path to CSV with soil properties")
    parser.add_argument("--ks-mm-d", type=float, default=None,
                        help="Manual Ks in mm/d")
    parser.add_argument("--porosity", type=float, default=None,
                        help="Manual porosity (fraction 0-1)")
    parser.add_argument("--fc", type=float, default=None,
                        help="Manual field capacity (volumetric fraction)")
    parser.add_argument("--wp", type=float, default=None,
                        help="Manual wilting point (volumetric fraction)")
    parser.add_argument("--depth-cm", type=float, default=300.0,
                        help="Total soil column depth in cm (default: 300)")
    parser.add_argument("--ks-unit", default="mm/h",
                        choices=["mm/h", "cm/h", "mm/d"],
                        help="Unit of Ks in source CSV (default: mm/h)")
    parser.add_argument("--output", required=True,
                        help="Output JSON file path")

    args = parser.parse_args()

    # Validate inputs
    errors = validate_inputs(args)
    if errors:
        result = {"status": "error", "errors": errors, "log": []}
        json.dump(result, sys.stdout, indent=2)
        sys.exit(1)

    # Process
    log = []
    result = process(args, log)

    # Write output
    output_dir = os.path.dirname(args.output)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    with open(args.output, "w") as f:
        json.dump(result, f, indent=2)

    status = result["status"]
    print(f"\n[convert_soil_to_velma] Status: {status}")
    print(f"  Output: {args.output}")
    if status == "success":
        p = result["output"]["parameters"]
        print(f"  Layers: {N_LAYERS}")
        print(f"  Source: {result['output']['source_texture']}")
        for i in range(N_LAYERS):
            print(f"  L{i+1}: Cap={p['layer_cap_mm'][i]:.1f} mm, "
                  f"FC={p['layer_fc_mm'][i]:.1f} mm, "
                  f"Ks={p['layer_ks_mm_d'][i]:.1f} mm/d")
    for entry in log:
        if "[CRITICAL]" in entry or "[WARN]" in entry:
            print(f"  {entry}")


if __name__ == "__main__":
    main()
