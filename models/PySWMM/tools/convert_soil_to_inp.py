#!/usr/bin/env python3
"""
convert_soil_to_inp.py — Map soil properties to SWMM infiltration parameters.

Converts soil data from HWSD, SSURGO, or SoilGrids into SWMM [INFILTRATION]
section parameters for Horton, Green-Ampt, or Curve Number methods.

CRITICAL: Infiltration rates must be in in/hr (US) or mm/hr (SI).
Providing mm/day or m/hr will produce 24x or 1000x errors respectively.

Usage:
    python convert_soil_to_inp.py \\
        --input soil_data.csv \\
        --output infiltration_block.txt \\
        --method horton \\
        --unit-system US

Inputs:
    CSV with columns: subcatchment_id, soil_texture, sand_pct, clay_pct,
                      organic_pct [, hydrologic_soil_group]

Outputs:
    Text file with SWMM [INFILTRATION] block ready for .inp insertion
"""

import argparse
import csv
import json
import sys
from pathlib import Path


# ── Horton infiltration parameters by USDA soil texture ────────────────
# MaxRate (in/hr), MinRate (in/hr), Decay (1/hr), DryTime (days), MaxInfil (in)
HORTON_BY_TEXTURE = {
    "sand":             (5.0, 1.20, 4.0, 7, 0),
    "loamy_sand":       (4.0, 0.80, 4.0, 7, 0),
    "sandy_loam":       (3.0, 0.50, 4.0, 7, 0),
    "loam":             (2.0, 0.30, 4.0, 7, 0),
    "silt_loam":        (1.5, 0.25, 3.0, 7, 0),
    "silt":             (1.2, 0.20, 3.0, 7, 0),
    "sandy_clay_loam":  (1.5, 0.15, 3.0, 7, 0),
    "clay_loam":        (1.0, 0.10, 3.0, 7, 0),
    "silty_clay_loam":  (0.8, 0.08, 2.0, 7, 0),
    "sandy_clay":       (0.6, 0.06, 2.0, 7, 0),
    "silty_clay":       (0.4, 0.04, 2.0, 7, 0),
    "clay":             (0.2, 0.02, 2.0, 7, 0),
}

# ── Green-Ampt parameters by USDA soil texture ────────────────────────
# Suction (in), Conductivity (in/hr), InitialDeficit (fraction)
GREEN_AMPT_BY_TEXTURE = {
    "sand":             (1.93, 4.74, 0.34),
    "loamy_sand":       (2.40, 1.18, 0.33),
    "sandy_loam":       (4.33, 0.43, 0.33),
    "loam":             (3.50, 0.13, 0.31),
    "silt_loam":        (6.69, 0.26, 0.32),
    "silt":             (7.50, 0.15, 0.33),
    "sandy_clay_loam":  (8.66, 0.06, 0.24),
    "clay_loam":        (8.27, 0.04, 0.22),
    "silty_clay_loam":  (10.63, 0.04, 0.22),
    "sandy_clay":       (9.45, 0.02, 0.21),
    "silty_clay":       (11.42, 0.02, 0.19),
    "clay":             (12.45, 0.01, 0.17),
}

# ── SCS Curve Numbers by hydrologic soil group ────────────────────────
# CN values for urban land use types by HSG (A, B, C, D)
CN_BY_HSG = {
    "A": {"open_space": 39, "commercial": 89, "residential_1/8ac": 77, "residential_1/4ac": 61,
           "residential_1/2ac": 54, "residential_1ac": 51, "industrial": 81, "parking": 98},
    "B": {"open_space": 61, "commercial": 92, "residential_1/8ac": 85, "residential_1/4ac": 75,
           "residential_1/2ac": 70, "residential_1ac": 68, "industrial": 88, "parking": 98},
    "C": {"open_space": 74, "commercial": 94, "residential_1/8ac": 90, "residential_1/4ac": 83,
           "residential_1/2ac": 80, "residential_1ac": 79, "industrial": 91, "parking": 98},
    "D": {"open_space": 80, "commercial": 95, "residential_1/8ac": 92, "residential_1/4ac": 87,
           "residential_1/2ac": 85, "residential_1ac": 84, "industrial": 93, "parking": 98},
}

# ── HWSD texture class to USDA texture mapping ────────────────────────
HWSD_TO_USDA = {
    1: "clay",       2: "silty_clay",     3: "silty_clay_loam",
    4: "clay_loam",  5: "sandy_clay",     6: "sandy_clay_loam",
    7: "silt_loam",  8: "silt",           9: "loam",
    10: "sandy_loam", 11: "loamy_sand",   12: "sand",
}

# Conversion: in/hr → mm/hr
IN_TO_MM = 25.4


def validate_inputs(args):
    """Validate inputs before processing."""
    errors = []

    if not Path(args.input).is_file():
        errors.append(f"Input file not found: {args.input}")

    if args.method not in ("horton", "green_ampt", "curve_number"):
        errors.append(f"Unknown method: {args.method}. Use horton, green_ampt, or curve_number")

    if args.unit_system not in ("US", "SI"):
        errors.append(f"Unit system must be US or SI, got {args.unit_system}")

    if errors:
        return False, errors
    return True, []


def classify_texture(sand_pct, clay_pct):
    """Classify USDA soil texture from sand and clay percentages."""
    silt_pct = 100.0 - sand_pct - clay_pct

    if clay_pct >= 40 and sand_pct <= 45 and silt_pct < 40:
        return "clay"
    elif clay_pct >= 40 and silt_pct >= 40:
        return "silty_clay"
    elif clay_pct >= 35 and sand_pct >= 45:
        return "sandy_clay"
    elif 27 <= clay_pct < 40 and sand_pct <= 20:
        return "silty_clay_loam"
    elif 27 <= clay_pct < 40 and 20 < sand_pct <= 45:
        return "clay_loam"
    elif 20 <= clay_pct < 35 and sand_pct >= 45:
        return "sandy_clay_loam"
    elif silt_pct >= 80:
        return "silt"
    elif 50 <= silt_pct < 80 and clay_pct < 27:
        return "silt_loam"
    elif clay_pct < 7 and sand_pct < 52 and silt_pct >= 50:
        return "silt_loam"
    elif 7 <= clay_pct < 27 and 28 <= silt_pct < 50 and sand_pct <= 52:
        return "loam"
    elif sand_pct >= 85:
        return "sand"
    elif sand_pct >= 70:
        return "loamy_sand"
    else:
        return "sandy_loam"


def classify_hsg(sand_pct, clay_pct):
    """Estimate hydrologic soil group from texture."""
    if sand_pct >= 70:
        return "A"
    elif sand_pct >= 50:
        return "B"
    elif clay_pct >= 40:
        return "D"
    else:
        return "C"


def get_horton_params(texture, unit_system="US"):
    """Get Horton parameters for a soil texture."""
    params = HORTON_BY_TEXTURE.get(texture, HORTON_BY_TEXTURE["loam"])
    max_rate, min_rate, decay, dry_time, max_infil = params

    if unit_system == "SI":
        max_rate *= IN_TO_MM
        min_rate *= IN_TO_MM

    return max_rate, min_rate, decay, dry_time, max_infil


def get_green_ampt_params(texture, unit_system="US"):
    """Get Green-Ampt parameters for a soil texture."""
    params = GREEN_AMPT_BY_TEXTURE.get(texture, GREEN_AMPT_BY_TEXTURE["loam"])
    suction, conductivity, init_deficit = params

    if unit_system == "SI":
        suction *= IN_TO_MM
        conductivity *= IN_TO_MM

    return suction, conductivity, init_deficit


def get_cn(hsg, land_use="residential_1/4ac"):
    """Get SCS Curve Number for a hydrologic soil group and land use."""
    return CN_BY_HSG.get(hsg, CN_BY_HSG["C"]).get(land_use, 75)


def process(args):
    """Main processing pipeline."""
    records = []
    with open(args.input, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            subcatch_id = row.get("subcatchment_id", row.get("id", "unknown"))
            soil_texture = row.get("soil_texture", "").lower().replace(" ", "_")
            sand_pct = float(row.get("sand_pct", 50))
            clay_pct = float(row.get("clay_pct", 20))
            hsg = row.get("hydrologic_soil_group", "").upper()

            # Classify texture if not provided
            if not soil_texture or soil_texture not in HORTON_BY_TEXTURE:
                soil_texture = classify_texture(sand_pct, clay_pct)

            # Classify HSG if not provided
            if not hsg or hsg not in CN_BY_HSG:
                hsg = classify_hsg(sand_pct, clay_pct)

            records.append({
                "id": subcatch_id,
                "texture": soil_texture,
                "hsg": hsg,
                "sand": sand_pct,
                "clay": clay_pct,
            })

    print(f"Read {len(records)} subcatchment soil records")

    # Generate infiltration block
    if args.method == "horton":
        block = format_horton_block(records, args.unit_system)
    elif args.method == "green_ampt":
        block = format_green_ampt_block(records, args.unit_system)
    else:
        block = format_cn_block(records)

    # Write output
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(block)

    # Validate output
    warnings = validate_output(records, args.method, args.unit_system)

    print(f"Wrote [{args.method.upper()}] infiltration block to {args.output}")

    return {
        "status": "success",
        "n_subcatchments": len(records),
        "method": args.method,
        "unit_system": args.unit_system,
        "warnings": warnings,
    }


def format_horton_block(records, unit_system):
    """Format Horton infiltration block."""
    lines = [
        "[INFILTRATION]",
        ";;Subcatchment   MaxRate    MinRate    Decay      DryTime    MaxInfil",
        ";;-------------- ---------- ---------- ---------- ---------- ----------",
    ]
    for rec in records:
        max_r, min_r, decay, dry_t, max_i = get_horton_params(rec["texture"], unit_system)
        lines.append(
            f"{rec['id']:<17s}{max_r:<11.2f}{min_r:<11.2f}{decay:<11.1f}{dry_t:<11d}{max_i}"
        )
    return "\n".join(lines)


def format_green_ampt_block(records, unit_system):
    """Format Green-Ampt infiltration block."""
    lines = [
        "[INFILTRATION]",
        ";;Subcatchment   Suction    Conduct.   InitDef.",
        ";;-------------- ---------- ---------- ----------",
    ]
    for rec in records:
        suction, cond, deficit = get_green_ampt_params(rec["texture"], unit_system)
        lines.append(
            f"{rec['id']:<17s}{suction:<11.2f}{cond:<11.4f}{deficit:<11.3f}"
        )
    return "\n".join(lines)


def format_cn_block(records):
    """Format SCS Curve Number infiltration block."""
    lines = [
        "[INFILTRATION]",
        ";;Subcatchment   CurveNum   Conduct.   DryTime",
        ";;-------------- ---------- ---------- ----------",
    ]
    for rec in records:
        cn = get_cn(rec["hsg"])
        lines.append(
            f"{rec['id']:<17s}{cn:<11d}{0.5:<11.2f}{7:<11d}"
        )
    return "\n".join(lines)


def validate_output(records, method, unit_system):
    """Post-validation checks."""
    warnings = []

    for rec in records:
        if method == "horton":
            max_r, min_r, _, _, _ = get_horton_params(rec["texture"], unit_system)
            if min_r > max_r:
                warnings.append(f"{rec['id']}: MinRate > MaxRate — check soil texture")
            if unit_system == "US" and max_r > 10:
                warnings.append(f"{rec['id']}: MaxRate = {max_r} in/hr — very high for US units")
            elif unit_system == "SI" and max_r > 250:
                warnings.append(f"{rec['id']}: MaxRate = {max_r} mm/hr — very high for SI units")

    return warnings


def main():
    parser = argparse.ArgumentParser(
        description="Convert soil properties to SWMM infiltration parameters"
    )
    parser.add_argument("--input", required=True, help="Input soil CSV file")
    parser.add_argument("--output", required=True, help="Output infiltration block file")
    parser.add_argument("--method", default="horton",
                        choices=["horton", "green_ampt", "curve_number"],
                        help="Infiltration method")
    parser.add_argument("--unit-system", default="US", choices=["US", "SI"],
                        help="SWMM unit system")

    args = parser.parse_args()

    ok, errors = validate_inputs(args)
    if not ok:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)

    result = process(args)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
