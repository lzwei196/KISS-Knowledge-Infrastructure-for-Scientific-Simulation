#!/usr/bin/env python3
"""
convert_soil_to_noahmp.py — Stage s2: Soil Parameter Converter

Converts HWSD (Harmonized World Soil Database) or SoilGrids data to
Noah-MP soil type classification (ISLTYP) and optionally generates
spatially-varying soil hydraulic parameters.

Noah-MP uses the STATSGO/STAS soil classification (19 types):
  1=Sand, 2=Loamy Sand, 3=Sandy Loam, 4=Silt Loam, 5=Silt,
  6=Loam, 7=Sandy Clay Loam, 8=Silty Clay Loam, 9=Clay Loam,
  10=Sandy Clay, 11=Silty Clay, 12=Clay, 13=Organic,
  14=Water, 15=Bedrock, 16=Other, 17=Playa, 18=Lava, 19=White Sand

Key soil hydraulic parameters (from NoahmpTable.TBL):
  SMCMAX  — Porosity / max soil moisture [m³/m³]
  SMCREF  — Field capacity [m³/m³]
  SMCWLT  — Wilting point [m³/m³]
  BEXP    — Clapp-Hornberger B exponent [-]
  DKSAT   — Saturated hydraulic conductivity [m/s]
  PSISAT  — Saturated matric potential [m]
  QUARTZ  — Quartz content fraction [-]

Pattern: validate_inputs → process → validate_outputs
"""

import os
import sys
import json
import argparse
import numpy as np

try:
    import netCDF4 as nc
except ImportError:
    nc = None

# ---------------------------------------------------------------------------
# USDA texture triangle classification
# ---------------------------------------------------------------------------
# Thresholds for USDA soil texture classes based on sand/clay percentages
TEXTURE_CLASSES = {
    "sand":            {"sand_min": 85, "clay_max": 10},
    "loamy_sand":      {"sand_min": 70, "sand_max": 90, "clay_max": 15},
    "sandy_loam":      {"sand_min": 43, "sand_max": 85, "clay_max": 20},
    "silt_loam":       {"silt_min": 50, "clay_max": 27},
    "silt":            {"silt_min": 80, "clay_max": 12},
    "loam":            {"sand_min": 23, "sand_max": 52, "clay_min": 7, "clay_max": 27},
    "sandy_clay_loam": {"sand_min": 45, "clay_min": 20, "clay_max": 35},
    "silty_clay_loam": {"clay_min": 27, "clay_max": 40, "sand_max": 20},
    "clay_loam":       {"clay_min": 27, "clay_max": 40, "sand_min": 20, "sand_max": 45},
    "sandy_clay":      {"sand_min": 45, "clay_min": 35},
    "silty_clay":      {"clay_min": 40, "sand_max": 20},
    "clay":            {"clay_min": 40, "sand_min": 0},
}

# Map USDA texture name -> Noah-MP STATSGO index
USDA_TO_NOAHMP = {
    "sand": 1, "loamy_sand": 2, "sandy_loam": 3,
    "silt_loam": 4, "silt": 5, "loam": 6,
    "sandy_clay_loam": 7, "silty_clay_loam": 8, "clay_loam": 9,
    "sandy_clay": 10, "silty_clay": 11, "clay": 12,
    "organic": 13, "water": 14, "bedrock": 15, "other": 16,
}

# Noah-MP default soil parameters by type (from NoahmpTable.TBL)
SOIL_PARAMS = {
    1:  {"name": "Sand",            "SMCMAX": 0.395, "SMCREF": 0.174, "SMCWLT": 0.068,
         "BEXP": 4.05,  "DKSAT": 1.76e-4, "PSISAT": -0.121, "QUARTZ": 0.92},
    2:  {"name": "Loamy Sand",      "SMCMAX": 0.410, "SMCREF": 0.179, "SMCWLT": 0.075,
         "BEXP": 4.38,  "DKSAT": 1.56e-4, "PSISAT": -0.090, "QUARTZ": 0.82},
    3:  {"name": "Sandy Loam",      "SMCMAX": 0.435, "SMCREF": 0.249, "SMCWLT": 0.114,
         "BEXP": 4.90,  "DKSAT": 3.47e-5, "PSISAT": -0.218, "QUARTZ": 0.60},
    4:  {"name": "Silt Loam",       "SMCMAX": 0.485, "SMCREF": 0.369, "SMCWLT": 0.179,
         "BEXP": 5.30,  "DKSAT": 7.20e-6, "PSISAT": -0.786, "QUARTZ": 0.25},
    5:  {"name": "Silt",            "SMCMAX": 0.485, "SMCREF": 0.369, "SMCWLT": 0.179,
         "BEXP": 5.30,  "DKSAT": 7.20e-6, "PSISAT": -0.786, "QUARTZ": 0.10},
    6:  {"name": "Loam",            "SMCMAX": 0.451, "SMCREF": 0.314, "SMCWLT": 0.155,
         "BEXP": 5.39,  "DKSAT": 6.95e-6, "PSISAT": -0.478, "QUARTZ": 0.40},
    7:  {"name": "Sandy Clay Loam", "SMCMAX": 0.420, "SMCREF": 0.299, "SMCWLT": 0.175,
         "BEXP": 7.12,  "DKSAT": 6.30e-6, "PSISAT": -0.299, "QUARTZ": 0.60},
    8:  {"name": "Silty Clay Loam", "SMCMAX": 0.477, "SMCREF": 0.387, "SMCWLT": 0.218,
         "BEXP": 7.75,  "DKSAT": 1.70e-6, "PSISAT": -0.356, "QUARTZ": 0.10},
    9:  {"name": "Clay Loam",       "SMCMAX": 0.476, "SMCREF": 0.382, "SMCWLT": 0.250,
         "BEXP": 8.52,  "DKSAT": 2.45e-6, "PSISAT": -0.630, "QUARTZ": 0.35},
    10: {"name": "Sandy Clay",      "SMCMAX": 0.426, "SMCREF": 0.338, "SMCWLT": 0.219,
         "BEXP": 10.4,  "DKSAT": 2.17e-6, "PSISAT": -0.153, "QUARTZ": 0.52},
    11: {"name": "Silty Clay",      "SMCMAX": 0.492, "SMCREF": 0.404, "SMCWLT": 0.283,
         "BEXP": 10.4,  "DKSAT": 1.03e-6, "PSISAT": -0.490, "QUARTZ": 0.10},
    12: {"name": "Clay",            "SMCMAX": 0.482, "SMCREF": 0.412, "SMCWLT": 0.286,
         "BEXP": 11.4,  "DKSAT": 1.28e-6, "PSISAT": -0.405, "QUARTZ": 0.25},
    13: {"name": "Organic",         "SMCMAX": 0.451, "SMCREF": 0.314, "SMCWLT": 0.155,
         "BEXP": 5.25,  "DKSAT": 8.00e-6, "PSISAT": -0.356, "QUARTZ": 0.05},
}


def validate_inputs(args):
    """Validate input arguments."""
    errors = []

    if args.hwsd_path and not os.path.exists(args.hwsd_path):
        errors.append(f"HWSD file not found: {args.hwsd_path}")

    if args.lat < -90 or args.lat > 90:
        errors.append(f"Latitude out of range: {args.lat}")
    if args.lon < -180 or args.lon > 360:
        errors.append(f"Longitude out of range: {args.lon}")

    if args.sand is not None and (args.sand < 0 or args.sand > 100):
        errors.append(f"Sand percentage out of range: {args.sand}")
    if args.clay is not None and (args.clay < 0 or args.clay > 100):
        errors.append(f"Clay percentage out of range: {args.clay}")
    if args.sand is not None and args.clay is not None:
        if args.sand + args.clay > 100:
            errors.append(f"Sand + Clay > 100%: {args.sand} + {args.clay}")

    if errors:
        print("INPUT VALIDATION FAILED:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(1)


def classify_usda_texture(sand_pct, clay_pct):
    """Classify soil texture from sand and clay percentages using the USDA triangle.

    Rewritten 2026-08-02 against the USDA-NRCS Soil Survey Manual class
    definitions.  The previous cascade got three boundaries wrong, and each one
    lands on a DIFFERENT NoahmpTable soil row (so SMCMAX/BEXP/DKSAT change --
    all dag-listed HIGH/MEDIUM sensitivity levers for LH and runoff):

      * sandy clay was gated behind ``clay >= 40``; the class starts at
        clay >= 35, so clay 35-40 with sand >= 45 was returned as sandy clay loam.
      * sandy clay loam omitted the ``silt < 28`` side of the class, so e.g.
        sand 47 / clay 21 / silt 32 (a LOAM, and the real HWSD texture at the
        US-MMS flux tower) was returned as sandy clay loam -- ISLTYP 7 instead
        of 6, BEXP 7.12 instead of 5.25, DKSAT 6.3e-6 instead of 3.47e-6.
      * ``sand >= 43 -> sandy_loam`` ignored the silt limb, so sand 45 /
        clay 15 / silt 40 (a LOAM) came back sandy loam.

    Fixed again 2026-08-02: the rewrite above still evaluated the
    ``27 <= clay < 40`` loam belt BEFORE the sandy clay loam test, so the
    sandy-clay-loam wedge with clay >= 27 was returned as clay loam.  Sandy clay
    loam is "20 to 35 percent clay, less than 28 percent silt, and more than 45
    percent sand" (USDA-NRCS; 310 CMR 15.244), which overlaps the clay-loam clay
    range on 27-35% clay -- the two are separated by SAND (clay loam is 20-45%
    sand), not by clay.  Example: sand 50 / clay 30 / silt 20 returned clay loam
    (ISLTYP 9: BEXP 8.52, DKSAT 2.45e-6) instead of sandy clay loam (ISLTYP 7:
    BEXP 7.12, DKSAT 6.30e-6).  The sandy clay loam test now precedes the belt.

    The class tests below are mutually exclusive and ordered coarse->fine, the
    conventional way to evaluate the triangle.
    """
    sand_pct = float(sand_pct)
    clay_pct = float(clay_pct)
    silt_pct = 100.0 - sand_pct - clay_pct

    # Sand limb.  The two limb boundaries use DIFFERENT clay weights: the
    # sand/loamy-sand line is silt + 1.5*clay = 15, the loamy-sand/sandy-loam
    # line is silt + 2*clay = 30 (USDA-NRCS).  Using 1.5 on the lower line
    # contradicted the sandy_loam test below (which already requires
    # silt + 2*clay >= 30) and stole that wedge -- e.g. sand 72 / clay 3 /
    # silt 25 (silt + 2*clay = 31, a SANDY LOAM) came back loamy sand,
    # ISLTYP 2 instead of 3.
    if silt_pct + 1.5 * clay_pct < 15.0:
        return "sand"
    if silt_pct + 2.0 * clay_pct < 30.0:
        return "loamy_sand"
    if ((7.0 <= clay_pct < 20.0 and sand_pct > 52.0 and silt_pct + 2.0 * clay_pct >= 30.0) or
            (clay_pct < 7.0 and silt_pct < 50.0 and silt_pct + 2.0 * clay_pct >= 30.0)):
        return "sandy_loam"

    # Clay corner
    if clay_pct >= 40.0:
        if silt_pct >= 40.0:
            return "silty_clay"
        if sand_pct > 45.0:
            return "sandy_clay"
        return "clay"
    if clay_pct >= 35.0 and sand_pct > 45.0:
        return "sandy_clay"

    # Loam belt.  Sandy clay loam FIRST: it shares the 27-35% clay band with
    # clay loam and is distinguished by sand > 45 / silt < 28, so the belt test
    # below would otherwise claim it.
    if 20.0 <= clay_pct < 35.0 and silt_pct < 28.0 and sand_pct > 45.0:
        return "sandy_clay_loam"
    if 27.0 <= clay_pct < 40.0:
        if sand_pct <= 20.0:
            return "silty_clay_loam"
        return "clay_loam"
    if silt_pct >= 80.0 and clay_pct < 12.0:
        return "silt"
    if (silt_pct >= 50.0 and 12.0 <= clay_pct < 27.0) or (50.0 <= silt_pct < 80.0 and clay_pct < 12.0):
        return "silt_loam"
    if 7.0 <= clay_pct < 27.0 and 28.0 <= silt_pct < 50.0 and sand_pct <= 52.0:
        return "loam"

    return "loam"


def read_hwsd_at_point(hwsd_path, lat, lon):
    """Read HWSD data at a point and return sand/clay percentages."""
    with nc.Dataset(hwsd_path, 'r') as ds:
        lats = ds.variables['lat'][:]
        lons = ds.variables['lon'][:]
        ilat = int(np.argmin(np.abs(lats - lat)))
        ilon = int(np.argmin(np.abs(lons - lon)))

        # HWSD variable names vary; try common ones
        sand_vars = ['T_SAND', 'sand', 'SAND', 't_sand']
        clay_vars = ['T_CLAY', 'clay', 'CLAY', 't_clay']

        sand = None
        clay = None
        for sv in sand_vars:
            if sv in ds.variables:
                sand = float(ds.variables[sv][ilat, ilon])
                break
        for cv in clay_vars:
            if cv in ds.variables:
                clay = float(ds.variables[cv][ilat, ilon])
                break

    if sand is None or clay is None:
        raise ValueError("Could not find sand/clay variables in HWSD file")

    return sand, clay


def pedotransfer_saxton_rawls(sand_pct, clay_pct, om_pct=2.5):
    """
    Saxton & Rawls (2006) pedotransfer functions.
    Returns estimated hydraulic parameters from texture.
    """
    S = sand_pct / 100.0
    C = clay_pct / 100.0
    OM = om_pct / 100.0

    # Wilting point (1500 kPa)
    theta_1500t = (-0.024 * S + 0.487 * C + 0.006 * OM
                   + 0.005 * S * OM - 0.013 * C * OM + 0.068 * S * C + 0.031)
    theta_1500 = theta_1500t + (0.14 * theta_1500t - 0.02)

    # Field capacity (33 kPa)
    theta_33t = (-0.251 * S + 0.195 * C + 0.011 * OM
                 + 0.006 * S * OM - 0.027 * C * OM + 0.452 * S * C + 0.299)
    theta_33 = theta_33t + (1.283 * theta_33t * theta_33t - 0.374 * theta_33t - 0.015)

    # Saturation
    theta_s_33t = (0.278 * S + 0.034 * C + 0.022 * OM
                   - 0.018 * S * OM - 0.027 * C * OM - 0.584 * S * C + 0.078)
    theta_s_33 = theta_s_33t + (0.636 * theta_s_33t - 0.107)
    theta_s = theta_33 + theta_s_33 - 0.097 * S + 0.043

    # Saturated hydraulic conductivity (mm/hr -> m/s)
    B_val = (np.log(1500) - np.log(33)) / (np.log(theta_33) - np.log(theta_1500))
    lambda_val = 1.0 / B_val
    ksat_mmhr = 1930.0 * (theta_s - theta_33) ** (3.0 - lambda_val)
    ksat_ms = ksat_mmhr / (3600.0 * 1000.0)

    return {
        "SMCMAX": float(np.clip(theta_s, 0.3, 0.55)),
        "SMCREF": float(np.clip(theta_33, 0.1, 0.45)),
        "SMCWLT": float(np.clip(theta_1500, 0.02, 0.30)),
        "BEXP":   float(np.clip(B_val, 2.0, 14.0)),
        "DKSAT":  float(np.clip(ksat_ms, 1e-8, 1e-3)),
    }


def process(args):
    """Main processing: determine soil type and parameters."""
    # Get sand/clay percentages
    if args.sand is not None and args.clay is not None:
        sand = args.sand
        clay = args.clay
        source = "manual"
    elif args.hwsd_path:
        sand, clay = read_hwsd_at_point(args.hwsd_path, args.lat, args.lon)
        source = "hwsd"
    else:
        # Default: loam (moderate soil)
        sand = 40.0
        clay = 20.0
        source = "default_loam"

    silt = 100.0 - sand - clay
    print(f"  Soil composition: Sand={sand:.1f}%, Clay={clay:.1f}%, Silt={silt:.1f}%")
    print(f"  Source: {source}")

    # Classify texture
    texture = classify_usda_texture(sand, clay)
    noahmp_type = USDA_TO_NOAHMP.get(texture, 6)  # Default to loam

    print(f"  USDA texture: {texture}")
    print(f"  Noah-MP ISLTYP: {noahmp_type} ({SOIL_PARAMS.get(noahmp_type, {}).get('name', 'Unknown')})")

    # Get parameters
    table_params = SOIL_PARAMS.get(noahmp_type, SOIL_PARAMS[6])
    ptf_params = pedotransfer_saxton_rawls(sand, clay)

    result = {
        "source": source,
        "sand_pct": sand,
        "clay_pct": clay,
        "silt_pct": silt,
        "usda_texture": texture,
        "noahmp_isltyp": noahmp_type,
        "noahmp_type_name": table_params["name"],
        "table_parameters": table_params,
        "pedotransfer_parameters": ptf_params,
        "recommendation": "Use table_parameters (NoahmpTable.TBL default) unless "
                          "soil_data_option=4 for spatially-varying parameters.",
        "layers": {
            "nsoil": 4,
            "dzs_m": [0.10, 0.30, 0.60, 1.00],
            "zsoil_m": [-0.10, -0.40, -1.00, -2.00],
            "soil_thick_input_m": [0.10, 0.40, 1.00, 2.00],
        }
    }

    return result


def validate_outputs(result):
    """Validate output soil parameters are physically reasonable."""
    errors = []
    params = result["table_parameters"]

    if params["SMCMAX"] <= params["SMCREF"]:
        errors.append(f"SMCMAX ({params['SMCMAX']}) <= SMCREF ({params['SMCREF']})")
    if params["SMCREF"] <= params["SMCWLT"]:
        errors.append(f"SMCREF ({params['SMCREF']}) <= SMCWLT ({params['SMCWLT']})")
    if params["SMCWLT"] <= 0:
        errors.append(f"SMCWLT ({params['SMCWLT']}) <= 0")
    if params["DKSAT"] <= 0:
        errors.append(f"DKSAT ({params['DKSAT']}) <= 0")
    if params["BEXP"] < 1 or params["BEXP"] > 20:
        errors.append(f"BEXP ({params['BEXP']}) outside [1, 20]")

    isltyp = result["noahmp_isltyp"]
    if isltyp < 1 or isltyp > 19:
        errors.append(f"ISLTYP ({isltyp}) outside [1, 19]")

    if errors:
        print("OUTPUT VALIDATION WARNINGS:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return False
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Convert soil data to Noah-MP soil type classification"
    )
    parser.add_argument("--hwsd_path", default=None, help="Path to HWSD NetCDF file")
    parser.add_argument("--lat", type=float, required=True, help="Latitude")
    parser.add_argument("--lon", type=float, required=True, help="Longitude")
    parser.add_argument("--sand", type=float, default=None, help="Sand percentage (manual)")
    parser.add_argument("--clay", type=float, default=None, help="Clay percentage (manual)")
    parser.add_argument("--output", required=True, help="Output JSON file path")

    args = parser.parse_args()

    print("=" * 60)
    print("Noah-MP Soil Parameter Converter")
    print("=" * 60)

    validate_inputs(args)

    result = process(args)
    ok = validate_outputs(result)

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, 'w') as f:
        json.dump(result, f, indent=2)

    print(f"\nOutput written to {args.output}")
    print(f"Validation: {'PASSED' if ok else 'WARNINGS'}")


if __name__ == "__main__":
    main()
