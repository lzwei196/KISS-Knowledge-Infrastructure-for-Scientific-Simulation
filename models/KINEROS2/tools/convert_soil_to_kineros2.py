#!/usr/bin/env python3
"""
convert_soil_to_kineros2.py -- Convert soil data to KINEROS2 Green-Ampt parameters.

Translates soil properties from HWSD, SoilGrids, or manual input into the
Green-Ampt infiltration parameters and routing parameters required by KINEROS2.

Output parameters (8 total):
  Ks      [1-80]      mm/d    Saturated hydraulic conductivity
  psi_f   [10-500]    mm      Wetting front suction head
  Smax    [100-800]   mm      Maximum soil moisture storage
  fc      [0.2-0.8]   --      Field capacity fraction
  k_fast  [0.01-0.5]  1/d     Fast reservoir recession rate
  k_slow  [0.001-0.05]1/d     Slow reservoir recession rate
  f_slow  [0.1-0.7]   --      Fraction of runoff to slow store
  alpha   [1.0-2.0]   --      Kinematic wave routing exponent

CRITICAL UNIT TRAPS:
  - Ks in HWSD is often in mm/h or cm/h. Must convert to mm/d (dt_006, dt_007).
    Using hourly Ks in a daily model makes infiltration capacity 24x too low.
  - psi_f in Rawls et al. tables may be in cm. Must convert to mm (dt_008).
  - Smax is depth_mm * available_water_capacity. If depth is in m instead of
    mm, Smax will be 1000x too large (dt_009).

Usage:
    python convert_soil_to_kineros2.py \\
        --texture "silt loam" \\
        --depth-cm 150 \\
        --output params.json

    python convert_soil_to_kineros2.py \\
        --soil-csv /path/to/hwsd_extract.csv \\
        --ks-unit mm/h \\
        --output params.json

    python convert_soil_to_kineros2.py \\
        --ks-mm-d 25.0 --psi-f-mm 170.0 --porosity 0.50 \\
        --depth-cm 150 \\
        --output params.json
"""

import argparse
import json
import os
import sys

import numpy as np


# ---- Green-Ampt parameter lookup tables ----------------------------------------
# Source: Rawls, Brakensiek, and Miller (1983), Table 1
# "Green-Ampt Infiltration Parameters from Soils Data"
# Journal of Hydraulic Engineering, 109(1), 62-70.
#
# Columns: Ks (mm/h), psi_f (mm), porosity, field_capacity, wilting_point

RAWLS_TABLE = {
    "sand":        {"Ks_mm_h": 117.8, "psi_f_mm": 49.5,  "porosity": 0.437, "fc": 0.062, "wp": 0.024},
    "loamy sand":  {"Ks_mm_h": 29.9,  "psi_f_mm": 61.3,  "porosity": 0.437, "fc": 0.105, "wp": 0.047},
    "sandy loam":  {"Ks_mm_h": 10.9,  "psi_f_mm": 110.1, "porosity": 0.453, "fc": 0.190, "wp": 0.085},
    "loam":        {"Ks_mm_h": 3.4,   "psi_f_mm": 88.9,  "porosity": 0.463, "fc": 0.232, "wp": 0.116},
    "silt loam":   {"Ks_mm_h": 6.5,   "psi_f_mm": 166.8, "porosity": 0.501, "fc": 0.284, "wp": 0.135},
    "sandy clay loam": {"Ks_mm_h": 1.5, "psi_f_mm": 218.5, "porosity": 0.398, "fc": 0.244, "wp": 0.136},
    "clay loam":   {"Ks_mm_h": 1.0,   "psi_f_mm": 208.8, "porosity": 0.464, "fc": 0.310, "wp": 0.187},
    "silty clay loam": {"Ks_mm_h": 1.0, "psi_f_mm": 273.0, "porosity": 0.471, "fc": 0.342, "wp": 0.210},
    "sandy clay":  {"Ks_mm_h": 0.6,   "psi_f_mm": 239.0, "porosity": 0.430, "fc": 0.321, "wp": 0.221},
    "silty clay":  {"Ks_mm_h": 0.5,   "psi_f_mm": 292.2, "porosity": 0.479, "fc": 0.371, "wp": 0.251},
    "clay":        {"Ks_mm_h": 0.3,   "psi_f_mm": 316.3, "porosity": 0.475, "fc": 0.378, "wp": 0.265},
}

# Unit conversion constants
MM_H_TO_MM_D = 24.0    # mm/h -> mm/d  (x 24 hours/day)
CM_H_TO_MM_D = 240.0   # cm/h -> mm/d  (x 10 mm/cm x 24 h/d)
CM_TO_MM = 10.0         # cm -> mm


# ---- Parameter bounds for KINEROS2 lumped model --------------------------------
PARAM_BOUNDS = {
    "Ks":     (1.0,   80.0),    # mm/d
    "psi_f":  (10.0,  500.0),   # mm
    "Smax":   (100.0, 800.0),   # mm
    "fc":     (0.2,   0.8),     # fraction
    "k_fast": (0.01,  0.5),     # 1/d
    "k_slow": (0.001, 0.05),    # 1/d
    "f_slow": (0.1,   0.7),     # fraction
    "alpha":  (1.0,   2.0),     # exponent (kinematic wave)
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

    if args.psi_f_mm is not None and args.psi_f_mm <= 0:
        errors.append(f"psi_f must be positive, got {args.psi_f_mm}")

    return errors


def convert_ks_to_mm_d(ks_value, from_unit):
    """Convert saturated hydraulic conductivity to mm/d.

    CRITICAL: Using mm/h values in a daily model makes infiltration capacity
    24x too low, causing excessive surface runoff (dt_006).
    """
    if from_unit == "mm/d":
        return ks_value
    elif from_unit == "mm/h":
        return ks_value * MM_H_TO_MM_D
    elif from_unit == "cm/h":
        return ks_value * CM_H_TO_MM_D
    else:
        raise ValueError(f"Unknown Ks unit: {from_unit}")


def estimate_green_ampt_from_texture(texture_class):
    """Look up Green-Ampt parameters from USDA texture class.

    Returns Ks (mm/d), psi_f (mm), porosity, field_capacity, wilting_point.
    """
    key = texture_class.lower().strip()
    if key not in RAWLS_TABLE:
        raise ValueError(f"Unknown texture class: {key}")

    entry = RAWLS_TABLE[key]
    ks_mm_d = entry["Ks_mm_h"] * MM_H_TO_MM_D  # Convert from mm/h to mm/d
    psi_f_mm = entry["psi_f_mm"]                # Already in mm
    porosity = entry["porosity"]
    fc = entry["fc"]
    wp = entry["wp"]

    return ks_mm_d, psi_f_mm, porosity, fc, wp


def estimate_routing_params(ks_mm_d, porosity, depth_cm):
    """Estimate reservoir routing parameters from soil properties.

    These are initial estimates for calibration -- not final values.

    Logic:
    - k_fast: Higher for sandier soils (higher Ks) -- faster surface response
    - k_slow: Lower for deeper/finer soils -- slower baseflow
    - f_slow: Higher for deeper/finer soils -- more water reaches baseflow
    - alpha:  Default 1.5 (between linear=1 and Manning's 5/3=1.67)
    """
    # Normalize Ks to [0, 1] range for interpolation
    # Ks ranges from ~7 (clay) to ~2800 (sand) mm/d
    ks_norm = np.clip(np.log10(ks_mm_d) / np.log10(2800), 0, 1)

    # Fast recession: sandier = faster drainage (0.05 to 0.3)
    k_fast = 0.05 + 0.25 * ks_norm

    # Slow recession: clayey/deep = slower (0.003 to 0.03)
    depth_factor = np.clip(depth_cm / 300.0, 0, 1)
    k_slow = 0.03 - 0.027 * depth_factor

    # Slow fraction: finer soils + deeper profiles = more baseflow (0.2 to 0.5)
    f_slow = 0.2 + 0.3 * (1.0 - ks_norm) * depth_factor

    # Routing exponent: default midpoint
    alpha = 1.5

    return (
        float(np.clip(k_fast, *PARAM_BOUNDS["k_fast"])),
        float(np.clip(k_slow, *PARAM_BOUNDS["k_slow"])),
        float(np.clip(f_slow, *PARAM_BOUNDS["f_slow"])),
        float(np.clip(alpha,  *PARAM_BOUNDS["alpha"])),
    )


def estimate_smax(porosity, fc_frac, wp_frac, depth_cm):
    """Estimate maximum soil storage (Smax) in mm.

    Smax = available_water_capacity * root_zone_depth
    AWC = field_capacity - wilting_point (volumetric fraction)

    CRITICAL: depth must be in cm, converted to mm here.
    If depth is accidentally in m, Smax will be 10x too small (dt_009).
    """
    depth_mm = depth_cm * CM_TO_MM  # cm -> mm
    awc = max(fc_frac - wp_frac, 0.01)
    smax = depth_mm * awc * 0.8  # 0.8 factor: not all depth is active root zone
    return float(np.clip(smax, *PARAM_BOUNDS["Smax"]))


def estimate_fc_fraction(fc_volumetric, porosity):
    """Convert volumetric field capacity to fraction of Smax.

    fc_fraction = field_capacity / porosity (both volumetric)
    This is the fraction of pore space occupied at field capacity.
    """
    if porosity <= 0:
        return 0.5  # fallback
    frac = fc_volumetric / porosity
    return float(np.clip(frac, *PARAM_BOUNDS["fc"]))


def process(args):
    """Generate KINEROS2 Green-Ampt parameters from soil data."""
    log = []

    # --- Determine soil properties ---
    if args.texture:
        # Use Rawls lookup table
        texture = args.texture.lower().strip()
        ks_mm_d, psi_f_mm, porosity, fc_vol, wp_vol = \
            estimate_green_ampt_from_texture(texture)
        log.append(f"Texture class: {texture}")
        log.append(f"  Ks (Rawls table): {ks_mm_d:.1f} mm/d "
                   f"(from {RAWLS_TABLE[texture]['Ks_mm_h']:.1f} mm/h)")
        log.append(f"  psi_f: {psi_f_mm:.1f} mm")
        log.append(f"  porosity: {porosity:.3f}")

    elif args.soil_csv:
        # Parse CSV file
        try:
            import pandas as pd
            df = pd.read_csv(args.soil_csv)
            ks_raw = float(df.get("Ks", df.get("ks", df.get("K_sat", [10.0]))).iloc[0])
            ks_mm_d = convert_ks_to_mm_d(ks_raw, args.ks_unit)
            psi_f_mm = float(df.get("psi_f", df.get("suction", [100.0])).iloc[0])
            porosity = float(df.get("porosity", df.get("theta_s", [0.45])).iloc[0])
            fc_vol = float(df.get("field_capacity", df.get("theta_fc", [0.25])).iloc[0])
            wp_vol = float(df.get("wilting_point", df.get("theta_wp", [0.12])).iloc[0])
            log.append(f"Loaded soil properties from {args.soil_csv}")
            log.append(f"  Ks: {ks_raw} {args.ks_unit} -> {ks_mm_d:.1f} mm/d")
        except Exception as e:
            return {"status": "error",
                    "errors": [f"Failed to parse soil CSV: {e}"],
                    "log": log}

    elif args.ks_mm_d is not None:
        # Direct parameter specification
        ks_mm_d = args.ks_mm_d
        psi_f_mm = args.psi_f_mm if args.psi_f_mm else 100.0
        porosity = args.porosity if args.porosity else 0.45
        fc_vol = porosity * 0.55  # rough default
        wp_vol = porosity * 0.25  # rough default
        log.append("Using directly specified soil parameters")
        log.append(f"  Ks: {ks_mm_d:.1f} mm/d")
        log.append(f"  psi_f: {psi_f_mm:.1f} mm")

    else:
        # Fall back to loam defaults
        ks_mm_d, psi_f_mm, porosity, fc_vol, wp_vol = \
            estimate_green_ampt_from_texture("loam")
        log.append("No soil data specified -- using loam defaults")

    # --- Depth ---
    depth_cm = args.depth_cm if args.depth_cm else 150.0
    log.append(f"  Soil depth: {depth_cm} cm")

    # --- Clip Green-Ampt params to model bounds ---
    ks_mm_d = float(np.clip(ks_mm_d, *PARAM_BOUNDS["Ks"]))
    psi_f_mm = float(np.clip(psi_f_mm, *PARAM_BOUNDS["psi_f"]))

    # --- Derived parameters ---
    smax = estimate_smax(porosity, fc_vol, wp_vol, depth_cm)
    fc_frac = estimate_fc_fraction(fc_vol, porosity)
    k_fast, k_slow, f_slow, alpha = estimate_routing_params(
        ks_mm_d, porosity, depth_cm)

    params = {
        "Ks": round(ks_mm_d, 4),
        "psi_f": round(psi_f_mm, 4),
        "Smax": round(smax, 4),
        "fc": round(fc_frac, 4),
        "k_fast": round(k_fast, 4),
        "k_slow": round(k_slow, 4),
        "f_slow": round(f_slow, 4),
        "alpha": round(alpha, 4),
    }

    log.append(f"\nEstimated parameters:")
    for name, val in params.items():
        lo, hi = PARAM_BOUNDS[name]
        at_bound = " [AT BOUND]" if val == lo or val == hi else ""
        log.append(f"  {name:8s} = {val:10.4f}  [{lo}, {hi}]{at_bound}")

    return params, log


def validate_output_params(params, log):
    """Verify all parameters are within valid ranges."""
    ok = True
    warnings = []

    for name, val in params.items():
        lo, hi = PARAM_BOUNDS[name]
        if val < lo or val > hi:
            warnings.append(
                f"[ERROR] {name} = {val} is outside valid range [{lo}, {hi}]")
            ok = False
        elif val == lo or val == hi:
            warnings.append(
                f"[WARN] {name} = {val} is at range boundary [{lo}, {hi}] "
                "-- calibration recommended")

    # Physics cross-checks
    if params["Ks"] > params["Smax"]:
        warnings.append(
            "[WARN] Ks > Smax: saturated conductivity exceeds total storage. "
            "Soil fills and drains within a single day. Verify parameters.")

    if params["k_fast"] < params["k_slow"]:
        warnings.append(
            "[WARN] k_fast < k_slow: fast reservoir drains slower than slow "
            "reservoir. This inverts the expected behavior.")

    log.extend(warnings)
    return ok


def main():
    parser = argparse.ArgumentParser(
        description="Convert soil data to KINEROS2 Green-Ampt parameters")

    # Soil data sources (mutually preferred, not exclusive)
    parser.add_argument("--texture", default=None,
                        help="USDA texture class (e.g., 'silt loam', 'clay loam')")
    parser.add_argument("--soil-csv", default=None,
                        help="CSV with soil properties (Ks, psi_f, porosity, etc.)")
    parser.add_argument("--ks-mm-d", type=float, default=None,
                        help="Direct Ks value in mm/d")
    parser.add_argument("--psi-f-mm", type=float, default=None,
                        help="Direct psi_f value in mm")
    parser.add_argument("--porosity", type=float, default=None,
                        help="Soil porosity (0-1)")
    parser.add_argument("--depth-cm", type=float, default=None,
                        help="Soil profile depth in cm (default: 150)")
    parser.add_argument("--ks-unit", default="mm/h",
                        choices=["mm/h", "cm/h", "mm/d"],
                        help="Unit of Ks in soil CSV (default: mm/h)")
    parser.add_argument("--output", required=True,
                        help="Output JSON file path")

    args = parser.parse_args()

    # Step 1: validate inputs
    errors = validate_inputs(args)
    if errors:
        print(json.dumps({"status": "error", "errors": errors}, indent=2))
        sys.exit(1)

    # Step 2: process
    result = process(args)
    if isinstance(result, dict) and result.get("status") == "error":
        print(json.dumps(result, indent=2))
        sys.exit(1)

    params, log = result

    # Step 3: validate outputs
    validate_output_params(params, log)

    # Step 4: write output
    output_data = {
        "status": "success",
        "model": "KINEROS2",
        "parameters": params,
        "bounds": {name: list(bounds) for name, bounds in PARAM_BOUNDS.items()},
        "param_details": {
            "Ks":     {"value": params["Ks"],     "unit": "mm/d",  "description": "Saturated hydraulic conductivity (Green-Ampt)"},
            "psi_f":  {"value": params["psi_f"],  "unit": "mm",    "description": "Wetting front suction head (Green-Ampt)"},
            "Smax":   {"value": params["Smax"],   "unit": "mm",    "description": "Maximum soil moisture storage"},
            "fc":     {"value": params["fc"],      "unit": "--",    "description": "Field capacity as fraction of Smax"},
            "k_fast": {"value": params["k_fast"], "unit": "1/d",   "description": "Fast (surface) reservoir recession rate"},
            "k_slow": {"value": params["k_slow"], "unit": "1/d",   "description": "Slow (baseflow) reservoir recession rate"},
            "f_slow": {"value": params["f_slow"], "unit": "--",    "description": "Fraction of runoff routed to slow reservoir"},
            "alpha":  {"value": params["alpha"],  "unit": "--",    "description": "Kinematic wave routing exponent"},
        },
        "note": "These are initial estimates. Calibrate against observed discharge.",
        "log": log,
    }

    out_dir = os.path.dirname(args.output)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    with open(args.output, "w") as f:
        json.dump(output_data, f, indent=2)

    # Print summary
    for line in log:
        print(line)
    print(f"\nOutput written to {args.output}")


if __name__ == "__main__":
    main()
