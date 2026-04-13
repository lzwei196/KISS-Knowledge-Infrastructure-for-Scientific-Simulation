#!/usr/bin/env python3
"""
convert_soil_params.py - Convert soil database parameters to GIFMod block properties.

Converts soil properties from HWSD (Harmonized World Soil Database) or SoilGrids
format into GIFMod-compatible Soil block parameters.

CRITICAL UNIT CONVERSIONS (see SKILL.md):
  - Hydraulic conductivity: cm/s -> m/day (* 864.0)   [dt_001]
  - Bulk density: g/cm^3 -> kg/m^3 (* 1000.0)         [dt_005]
  - Porosity: percent -> fraction (* 0.01)              [dt_012]
  - Dispersivity: cm -> m (* 0.01)                      [dt_006]

GIFMod Soil block properties:
  - Ks: hydraulic conductivity (m/day)
  - porosity: total porosity (fraction 0-1)
  - theta_r: residual moisture content (fraction)
  - theta_s: saturated moisture content (fraction)
  - bulk_density: dry bulk density (kg/m^3)
  - dispersivity: longitudinal dispersivity (m)

Usage:
    python convert_soil_params.py --input hwsd_extract.csv --output soil_params.json
    python convert_soil_params.py --input soilgrids.csv --format soilgrids --output soil_params.json
"""

import argparse
import csv
import json
import math
import os
import sys


# Pedotransfer functions (Saxton & Rawls 2006)
def saxton_rawls_ks(sand_pct, clay_pct, om_pct=1.0):
    """Estimate Ks in cm/hr from sand/clay/OM percentages using Saxton & Rawls."""
    S = sand_pct / 100.0
    C = clay_pct / 100.0
    OM = om_pct / 100.0

    # Moisture at 1500 kPa (wilting point)
    theta_1500t = (
        -0.024 * S + 0.487 * C + 0.006 * OM
        + 0.005 * S * OM - 0.013 * C * OM
        + 0.068 * S * C + 0.031
    )
    theta_1500 = theta_1500t + 0.14 * theta_1500t - 0.02

    # Moisture at 33 kPa (field capacity)
    theta_33t = (
        -0.251 * S + 0.195 * C + 0.011 * OM
        + 0.006 * S * OM - 0.027 * C * OM
        + 0.452 * S * C + 0.299
    )
    theta_33 = theta_33t + 1.283 * theta_33t * theta_33t - 0.374 * theta_33t - 0.015

    # Saturated moisture (porosity)
    theta_s_33t = (
        0.278 * S + 0.034 * C + 0.022 * OM
        - 0.018 * S * OM - 0.027 * C * OM
        - 0.584 * S * C + 0.078
    )
    theta_s_33 = theta_s_33t + 0.636 * theta_s_33t - 0.107
    theta_s = theta_33 + theta_s_33 - 0.097 * S + 0.043

    # Ks in mm/hr
    B = (math.log(1500) - math.log(33)) / (math.log(theta_33) - math.log(theta_1500))
    lam = 1.0 / B
    ks_mmhr = 1930.0 * (theta_s - theta_33) ** (3.0 - lam)

    return {
        "ks_cm_hr": ks_mmhr / 10.0,
        "theta_s": theta_s,
        "theta_33": theta_33,
        "theta_1500": theta_1500,
    }


def validate_inputs(args):
    """Validate input file and format."""
    errors = []

    if not os.path.isfile(args.input):
        errors.append(f"Input file not found: {args.input}")

    if args.format not in ("hwsd", "soilgrids", "usda", "generic"):
        errors.append(f"Unknown format '{args.format}'. Valid: hwsd, soilgrids, usda, generic")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)

    return {"status": "ok"}


def process(args):
    """Read soil data, apply pedotransfer functions and unit conversions."""
    results = []
    warnings = []

    with open(args.input, "r") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            # Extract raw values (handle multiple column naming conventions)
            sand = float(row.get("sand", row.get("T_SAND", row.get("sand_pct", 50))))
            clay = float(row.get("clay", row.get("T_CLAY", row.get("clay_pct", 20))))
            om = float(row.get("om", row.get("T_OC", row.get("organic_matter", 1.0))))
            bd_raw = float(row.get("bulk_density", row.get("T_BULK_DENSITY",
                          row.get("bd", 1.4))))
            depth_raw = float(row.get("depth", row.get("T_REF_DEPTH",
                             row.get("depth_cm", 100))))
            layer_id = row.get("id", row.get("layer", f"soil_{i+1}"))

            # Detect input units and convert
            # Bulk density: if < 10, assume g/cm^3; if > 100, assume kg/m^3
            if bd_raw < 10:
                bd_kg_m3 = bd_raw * 1000.0  # g/cm^3 -> kg/m^3
                warnings.append(
                    f"Layer {layer_id}: bulk density {bd_raw} assumed g/cm^3, "
                    f"converted to {bd_kg_m3} kg/m^3 (dt_005)"
                )
            else:
                bd_kg_m3 = bd_raw

            # Depth: if > 10, assume cm -> convert to m
            if depth_raw > 10:
                depth_m = depth_raw * 0.01  # cm -> m
            else:
                depth_m = depth_raw

            # Pedotransfer functions
            ptf = saxton_rawls_ks(sand, clay, om)

            # Convert Ks from cm/hr to m/day
            ks_m_day = ptf["ks_cm_hr"] * 0.24  # cm/hr * 24hr/day * 0.01m/cm = * 0.24

            # Dispersivity estimate (1/10 of layer depth, minimum 0.01 m)
            dispersivity_m = max(depth_m * 0.1, 0.01)

            # Residual moisture ~ theta_1500 * 0.8
            theta_r = ptf["theta_1500"] * 0.8

            # Validation checks
            if ks_m_day <= 0:
                warnings.append(f"Layer {layer_id}: Ks <= 0 ({ks_m_day}), setting to 0.01 m/day")
                ks_m_day = 0.01
            if ptf["theta_s"] <= 0 or ptf["theta_s"] > 1.0:
                warnings.append(
                    f"Layer {layer_id}: porosity {ptf['theta_s']:.3f} out of range"
                )

            results.append({
                "layer_id": layer_id,
                "Ks": round(ks_m_day, 6),
                "porosity": round(ptf["theta_s"], 4),
                "theta_r": round(max(theta_r, 0.01), 4),
                "theta_s": round(ptf["theta_s"], 4),
                "bulk_density": round(bd_kg_m3, 1),
                "depth": round(depth_m, 3),
                "dispersivity": round(dispersivity_m, 4),
                "field_capacity": round(ptf["theta_33"], 4),
                "wilting_point": round(ptf["theta_1500"], 4),
                "source_sand_pct": sand,
                "source_clay_pct": clay,
            })

    # Write output
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w") as f:
        json.dump({
            "status": "success",
            "n_layers": len(results),
            "unit_system": "GIFMod (m/day, kg/m^3, fraction)",
            "layers": results,
            "warnings": warnings[:20],
        }, f, indent=2)

    return {
        "status": "success",
        "n_layers": len(results),
        "output_file": args.output,
        "warnings": warnings[:20],
    }


def validate_outputs(result):
    """Check output file was created."""
    errors = []

    if result["n_layers"] == 0:
        errors.append("No soil layers produced — check input format")

    if not os.path.isfile(result["output_file"]):
        errors.append(f"Output file not created: {result['output_file']}")

    if errors:
        result["status"] = "error"
        result["errors"] = errors
        print(json.dumps(result, indent=2))
        sys.exit(1)

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Convert soil parameters to GIFMod format"
    )
    parser.add_argument("--input", required=True, help="Input soil data CSV")
    parser.add_argument("--output", required=True, help="Output JSON file")
    parser.add_argument("--format", default="hwsd",
                        help="Input format: hwsd, soilgrids, usda, generic (default: hwsd)")

    args = parser.parse_args()

    validate_inputs(args)
    result = process(args)
    result = validate_outputs(result)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
