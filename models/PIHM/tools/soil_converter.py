#!/usr/bin/env python3
"""
soil_converter.py — Convert soil database to PIHM .soil and .geol format.

Reads soil data from CSV (e.g., HWSD, SSURGO, or custom database) and produces
PIHM-format .soil and .geol files with correct units. Applies pedotransfer
functions (Rosetta-style) when hydraulic parameters are missing.

CRITICAL unit conversions (see diagnostic triplets dt_007–dt_010):
  - Ksat: cm/hr → m/s (÷ 360000)
  - van Genuchten alpha: 1/cm → 1/m (× 100)
  - Bulk density: kg/m3 → g/cm3 (÷ 1000)
  - Depths: cm → m (÷ 100)

Usage:
    python soil_converter.py --input soils.csv --soil-output project.soil \\
        --geol-output project.geol --ksat-unit cm/hr --alpha-unit 1/cm \\
        --bd-unit g/cm3 --depth-unit m

    python soil_converter.py --input hwsd_extract.csv --soil-output project.soil \\
        --geol-output project.geol --use-ptf
"""

import argparse
import csv
import json
import math
import os
import sys


# Typical parameter ranges for validation (PIHM internal units)
VALID_RANGES = {
    "ksat_ms":    (1e-9, 1e-2),     # m/s (clay to gravel)
    "alpha_1m":   (0.1, 50.0),      # 1/m
    "beta":       (1.01, 10.0),     # dimensionless
    "porosity":   (0.2, 0.8),       # m3/m3
    "residual":   (0.01, 0.2),      # m3/m3
    "bd_gcm3":    (0.5, 2.0),       # g/cm3
    "silt_pct":   (0.0, 100.0),     # %
    "clay_pct":   (0.0, 100.0),     # %
    "om_pct":     (0.0, 30.0),      # %
}

# Pedotransfer functions: Schaap et al. (2001) Rosetta-like estimates
# Maps USDA texture class to (theta_r, theta_s, alpha_1cm, n, Ksat_cm_day)
PTF_LOOKUP = {
    "sand":           (0.045, 0.43,  0.145, 2.68,  712.8),
    "loamy_sand":     (0.057, 0.41,  0.124, 2.28,  350.2),
    "sandy_loam":     (0.065, 0.41,  0.075, 1.89,  106.1),
    "loam":           (0.078, 0.43,  0.036, 1.56,   25.0),
    "silt_loam":      (0.067, 0.45,  0.020, 1.41,   10.8),
    "silt":           (0.034, 0.46,  0.016, 1.37,    6.0),
    "sandy_clay_loam":(0.100, 0.39,  0.059, 1.48,   31.4),
    "clay_loam":      (0.095, 0.41,  0.019, 1.31,    6.2),
    "silty_clay_loam":(0.089, 0.43,  0.010, 1.23,    1.7),
    "sandy_clay":     (0.100, 0.38,  0.027, 1.23,    2.9),
    "silty_clay":     (0.070, 0.36,  0.005, 1.09,    0.5),
    "clay":           (0.068, 0.38,  0.008, 1.09,    4.8),
}


def validate_inputs(args):
    """Validate input arguments."""
    errors = []
    if not os.path.exists(args.input):
        errors.append(f"Input file not found: {args.input}")

    valid_ksat = ["m/s", "cm/hr", "cm/day", "m/day"]
    if args.ksat_unit not in valid_ksat:
        errors.append(f"Invalid ksat-unit '{args.ksat_unit}'. Valid: {valid_ksat}")

    valid_alpha = ["1/m", "1/cm"]
    if args.alpha_unit not in valid_alpha:
        errors.append(f"Invalid alpha-unit '{args.alpha_unit}'. Valid: {valid_alpha}")

    valid_bd = ["g/cm3", "kg/m3"]
    if args.bd_unit not in valid_bd:
        errors.append(f"Invalid bd-unit '{args.bd_unit}'. Valid: {valid_bd}")

    valid_depth = ["m", "cm"]
    if args.depth_unit not in valid_depth:
        errors.append(f"Invalid depth-unit '{args.depth_unit}'. Valid: {valid_depth}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)


def convert_ksat(value, unit):
    """Convert hydraulic conductivity to m/s."""
    v = float(value)
    if unit == "cm/hr":
        return v / 360000.0
    elif unit == "cm/day":
        return v / 8640000.0
    elif unit == "m/day":
        return v / 86400.0
    return v


def convert_alpha(value, unit):
    """Convert van Genuchten alpha to 1/m."""
    v = float(value)
    if unit == "1/cm":
        return v * 100.0
    return v


def convert_bd(value, unit):
    """Convert bulk density to g/cm3."""
    v = float(value)
    if unit == "kg/m3":
        return v / 1000.0
    return v


def convert_depth(value, unit):
    """Convert depth to meters."""
    v = float(value)
    if unit == "cm":
        return v / 100.0
    return v


def classify_texture(sand_pct, clay_pct):
    """Classify USDA soil texture from sand and clay percentages."""
    silt_pct = 100.0 - sand_pct - clay_pct
    if clay_pct >= 40 and silt_pct >= 40:
        return "silty_clay"
    elif clay_pct >= 40 and sand_pct >= 45:
        return "sandy_clay"
    elif clay_pct >= 40:
        return "clay"
    elif clay_pct >= 27 and sand_pct >= 20 and sand_pct < 45:
        return "clay_loam"
    elif clay_pct >= 27 and silt_pct >= 40:
        return "silty_clay_loam"
    elif clay_pct >= 20 and sand_pct >= 45:
        return "sandy_clay_loam"
    elif silt_pct >= 80:
        return "silt"
    elif silt_pct >= 50:
        return "silt_loam"
    elif sand_pct >= 85:
        return "sand"
    elif sand_pct >= 70:
        return "loamy_sand"
    elif sand_pct >= 50:
        return "sandy_loam"
    else:
        return "loam"


def apply_ptf(sand_pct, clay_pct):
    """Apply pedotransfer function based on texture class."""
    texture = classify_texture(sand_pct, clay_pct)
    theta_r, theta_s, alpha_cm, n, ksat_cmd = PTF_LOOKUP.get(texture, PTF_LOOKUP["loam"])
    return {
        "smcmin": theta_r,
        "smcmax": theta_s,
        "alpha": alpha_cm * 100.0,  # 1/cm → 1/m
        "beta": n,
        "ksat": ksat_cmd / 8640000.0,  # cm/day → m/s
    }


def process(args):
    """Read CSV soil data, convert units, write .soil and .geol files."""
    soils = []
    warnings = []

    with open(args.input, "r") as f:
        reader = csv.DictReader(f)
        headers = [h.strip().lower() for h in reader.fieldnames]

        for row in reader:
            row = {k.strip().lower(): v.strip() for k, v in row.items()}

            soil = {"index": int(row.get("index", len(soils) + 1))}

            # Required texture fields
            soil["silt"] = float(row.get("silt", row.get("silt_pct", 0)))
            soil["clay"] = float(row.get("clay", row.get("clay_pct", 0)))
            soil["om"] = float(row.get("om", row.get("om_pct", row.get("organic_matter", 1.0))))
            soil["bd"] = convert_bd(
                float(row.get("bd", row.get("bulk_density", 1.4))),
                args.bd_unit
            )
            soil["qtz"] = float(row.get("qtz", row.get("quartz", 0.25)))

            sand_pct = 100.0 - soil["silt"] - soil["clay"]

            # Hydraulic parameters — use PTF if missing or flagged
            if args.use_ptf or float(row.get("ksat", row.get("ksatv", -999))) == -999:
                ptf = apply_ptf(sand_pct, soil["clay"])
                soil["kinfv"] = ptf["ksat"]
                soil["ksatv"] = ptf["ksat"]
                soil["ksath"] = ptf["ksat"] * 10.0  # anisotropy ratio
                soil["smcmax"] = ptf["smcmax"]
                soil["smcmin"] = ptf["smcmin"]
                soil["alpha"] = ptf["alpha"]
                soil["beta"] = ptf["beta"]
            else:
                ksat_raw = float(row.get("ksat", row.get("ksatv", 1e-5)))
                soil["kinfv"] = convert_ksat(ksat_raw, args.ksat_unit)
                soil["ksatv"] = soil["kinfv"]
                soil["ksath"] = soil["ksatv"] * 10.0

                if "ksath" in row:
                    soil["ksath"] = convert_ksat(float(row["ksath"]), args.ksat_unit)
                if "kinfv" in row:
                    soil["kinfv"] = convert_ksat(float(row["kinfv"]), args.ksat_unit)

                soil["smcmax"] = float(row.get("smcmax", row.get("porosity", 0.45)))
                soil["smcmin"] = float(row.get("smcmin", row.get("theta_r", 0.05)))
                soil["alpha"] = convert_alpha(
                    float(row.get("alpha", 3.6)), args.alpha_unit
                )
                soil["beta"] = float(row.get("beta", row.get("n", 1.56)))

            # Derived parameters
            soil["smcwlt"] = soil["smcmin"] + 0.1 * (soil["smcmax"] - soil["smcmin"])
            soil["smcref"] = soil["smcmin"] + 0.7 * (soil["smcmax"] - soil["smcmin"])

            # Macropore parameters (defaults if not provided)
            soil["areafh"] = float(row.get("areafh", row.get("machf", 0.1)))
            soil["areafv"] = float(row.get("areafv", row.get("macvf", 0.1)))
            soil["dmac"] = convert_depth(
                float(row.get("dmac", 0.5 if args.depth_unit == "m" else 50)),
                args.depth_unit
            )

            # Validate
            if soil["kinfv"] < VALID_RANGES["ksat_ms"][0] or soil["kinfv"] > VALID_RANGES["ksat_ms"][1]:
                warnings.append(f"Soil {soil['index']}: Ksat={soil['kinfv']:.2e} m/s outside range")
            if soil["alpha"] < VALID_RANGES["alpha_1m"][0] or soil["alpha"] > VALID_RANGES["alpha_1m"][1]:
                warnings.append(f"Soil {soil['index']}: alpha={soil['alpha']:.2f} 1/m outside range")

            soils.append(soil)

    # Write .soil file
    os.makedirs(os.path.dirname(os.path.abspath(args.soil_output)), exist_ok=True)
    with open(args.soil_output, "w") as f:
        f.write(f"NUMSOIL\t{len(soils)}\n")
        for s in soils:
            f.write(
                f"{s['index']}\t"
                f"{s['silt']:.2f}\t{s['clay']:.2f}\t{s['om']:.2f}\t{s['bd']:.4f}\t"
                f"{s['kinfv']:.6e}\t{s['ksatv']:.6e}\t{s['ksath']:.6e}\t"
                f"{s['smcmax']:.4f}\t{s['smcmin']:.4f}\t"
                f"{s['alpha']:.4f}\t{s['beta']:.4f}\t"
                f"{s['areafh']:.4f}\t{s['areafv']:.4f}\t{s['dmac']:.4f}\t{s['qtz']:.4f}\n"
            )
        f.write(f"DINF\t0.10\n")
        f.write(f"KMACV_RO\t100.0\n")
        f.write(f"KMACH_RO\t1000.0\n")

    # Write .geol file (bedrock/geology — use reduced conductivity)
    with open(args.geol_output, "w") as f:
        f.write(f"NUMGEOL\t{len(soils)}\n")
        for s in soils:
            geol_ksatv = s["ksatv"] * 0.01  # bedrock ~100x less permeable
            geol_ksath = s["ksath"] * 0.01
            f.write(
                f"{s['index']}\t"
                f"{geol_ksatv:.6e}\t{geol_ksath:.6e}\t"
                f"{s['smcmax'] * 0.5:.4f}\t{s['smcmin']:.4f}\t"
                f"{s['alpha']:.4f}\t{s['beta']:.4f}\t"
                f"{s['areafh'] * 0.1:.4f}\t{s['areafv'] * 0.1:.4f}\t"
                f"{s['dmac'] * 0.1:.4f}\n"
            )
        f.write(f"KMACV_RO\t10.0\n")
        f.write(f"KMACH_RO\t100.0\n")

    return soils, warnings


def main():
    parser = argparse.ArgumentParser(
        description="Convert soil database to PIHM .soil and .geol format"
    )
    parser.add_argument("--input", required=True, help="Input CSV soil data file")
    parser.add_argument("--soil-output", required=True, help="Output .soil file path")
    parser.add_argument("--geol-output", required=True, help="Output .geol file path")
    parser.add_argument("--ksat-unit", default="cm/hr",
                        help="Ksat unit: m/s, cm/hr, cm/day, m/day")
    parser.add_argument("--alpha-unit", default="1/cm",
                        help="van Genuchten alpha unit: 1/m, 1/cm")
    parser.add_argument("--bd-unit", default="g/cm3",
                        help="Bulk density unit: g/cm3, kg/m3")
    parser.add_argument("--depth-unit", default="m",
                        help="Depth unit: m, cm")
    parser.add_argument("--use-ptf", action="store_true",
                        help="Use pedotransfer functions for all hydraulic parameters")
    args = parser.parse_args()

    validate_inputs(args)
    soils, warnings = process(args)

    result = {
        "status": "success",
        "soil_output": args.soil_output,
        "geol_output": args.geol_output,
        "n_soil_types": len(soils),
        "warnings": warnings,
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
