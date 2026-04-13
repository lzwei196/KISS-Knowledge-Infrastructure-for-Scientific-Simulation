#!/usr/bin/env python3
"""
convert_parameters.py - Convert soil/hydraulic parameters to OpenHydroQual format.

Reads soil parameter databases (HWSD, SSURGO) or user-supplied parameter tables
and generates OHQ-compatible parameter values with correct units.

CRITICAL: Hydraulic conductivity in OHQ is m/day (NOT m/s, NOT cm/hr).
CRITICAL: Porosity in OHQ is a fraction 0-1 (NOT percentage).
CRITICAL: Storage in OHQ is m^3 (NOT liters).
CRITICAL: Specific storage is 1/m.

Usage:
  python convert_parameters.py --input params.csv --output ohq_params.json \\
    --ksat-unit cm/hr --porosity-unit percent

  python convert_parameters.py --input hwsd_extract.csv --output ohq_params.json \\
    --format hwsd --depth 1.0

  python convert_parameters.py --defaults --block-type "Unconfined Groundwater cell" \\
    --output ohq_params.json
"""

import argparse
import csv
import json
import os
import sys


# Default parameter ranges for common block types
DEFAULT_PARAMS = {
    "Unconfined Groundwater cell": {
        "hydraulic_conductivity": {"value": 5.0, "unit": "m/day", "range": [0.001, 100]},
        "porosity": {"value": 0.3, "unit": "fraction", "range": [0.1, 0.6]},
        "specific_yield": {"value": 0.2, "unit": "fraction", "range": [0.01, 0.4]},
        "area": {"value": 5000, "unit": "m^2", "range": [100, 1e6]},
        "piezometric_head": {"value": 10.0, "unit": "m", "range": [-10, 500]},
    },
    "Bed_sediment": {
        "hydraulic_conductivity": {"value": 1.0, "unit": "m/day", "range": [0.001, 10]},
        "porosity": {"value": 0.4, "unit": "fraction", "range": [0.2, 0.7]},
        "specific_storage": {"value": 0.01, "unit": "1/m", "range": [1e-5, 0.1]},
        "depth": {"value": 0.1, "unit": "m", "range": [0.01, 1.0]},
        "water_content": {"value": 0.4, "unit": "fraction", "range": [0.1, 0.6]},
    },
    "Pond": {
        "Storage": {"value": 100, "unit": "m^3", "range": [1, 1e6]},
        "bottom_elevation": {"value": 0.0, "unit": "m", "range": [-10, 500]},
        "alpha": {"value": 100, "unit": "m^2", "range": [1, 1e5]},
        "beta": {"value": 2, "unit": "dimensionless", "range": [1, 5]},
    },
    "fixed_head": {
        "head": {"value": 0.0, "unit": "m", "range": [-100, 500]},
        "Storage": {"value": 100000, "unit": "m^3", "range": [10000, 1e8]},
    },
}

# Soil texture class to hydraulic conductivity (m/day) lookup
TEXTURE_KSAT = {
    "sand": 7.128,
    "loamy_sand": 3.502,
    "sandy_loam": 1.061,
    "loam": 0.250,
    "silt_loam": 0.108,
    "silt": 0.060,
    "sandy_clay_loam": 0.314,
    "clay_loam": 0.062,
    "silty_clay_loam": 0.017,
    "sandy_clay": 0.029,
    "silty_clay": 0.005,
    "clay": 0.005,
}

# Soil texture to porosity lookup
TEXTURE_POROSITY = {
    "sand": 0.43,
    "loamy_sand": 0.41,
    "sandy_loam": 0.41,
    "loam": 0.43,
    "silt_loam": 0.45,
    "silt": 0.46,
    "sandy_clay_loam": 0.39,
    "clay_loam": 0.41,
    "silty_clay_loam": 0.43,
    "sandy_clay": 0.38,
    "silty_clay": 0.36,
    "clay": 0.38,
}


def validate_inputs(args):
    """Validate input arguments."""
    errors = []

    if not args.defaults and not args.input:
        errors.append("Either --input or --defaults is required")

    if args.input and not os.path.isfile(args.input):
        errors.append(f"Input file not found: {args.input}")

    if not args.output:
        errors.append("--output is required")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)


def convert_ksat(value, from_unit):
    """Convert hydraulic conductivity to m/day."""
    conversions = {
        "m/day": 1.0,
        "m/s": 86400.0,
        "cm/s": 864.0,
        "cm/hr": 0.24,
        "ft/day": 0.3048,
        "in/hr": 0.6096,
    }
    factor = conversions.get(from_unit)
    if factor is None:
        raise ValueError(f"Unknown Ksat unit: {from_unit}")
    return value * factor


def convert_porosity_val(value, from_unit):
    """Convert porosity to fraction 0-1."""
    if from_unit == "percent":
        return value / 100.0
    return value


def convert_depth(value, from_unit):
    """Convert depth to meters."""
    conversions = {
        "m": 1.0,
        "cm": 0.01,
        "mm": 0.001,
        "ft": 0.3048,
        "in": 0.0254,
    }
    factor = conversions.get(from_unit)
    if factor is None:
        raise ValueError(f"Unknown depth unit: {from_unit}")
    return value * factor


def read_hwsd_format(filepath):
    """Read HWSD-format soil parameter CSV.

    Expected columns: id, texture, t_sand, t_silt, t_clay, t_oc, t_bd,
                      s_sand, s_silt, s_clay, s_oc, s_bd
    """
    params = []
    with open(filepath, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            texture = row.get("texture", "loam").strip().lower().replace(" ", "_")
            ksat = TEXTURE_KSAT.get(texture, 0.250)
            porosity = TEXTURE_POROSITY.get(texture, 0.43)

            # If bulk density is provided, estimate porosity
            bd = row.get("t_bd", "")
            if bd:
                try:
                    bd_val = float(bd)
                    if 0.5 < bd_val < 2.5:
                        porosity = 1.0 - bd_val / 2.65  # 2.65 g/cm^3 mineral density
                except ValueError:
                    pass

            params.append({
                "id": row.get("id", "unknown"),
                "texture": texture,
                "hydraulic_conductivity": ksat,
                "porosity": porosity,
                "unit_ksat": "m/day",
                "unit_porosity": "fraction",
            })
    return params


def read_generic_csv(filepath, ksat_unit, porosity_unit, depth_unit):
    """Read generic parameter CSV with named columns."""
    params = []
    with open(filepath, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            p = {"id": row.get("id", row.get("name", "unknown"))}

            if "ksat" in row or "hydraulic_conductivity" in row:
                raw = float(row.get("ksat", row.get("hydraulic_conductivity", 0)))
                p["hydraulic_conductivity"] = convert_ksat(raw, ksat_unit)

            if "porosity" in row:
                raw = float(row["porosity"])
                p["porosity"] = convert_porosity_val(raw, porosity_unit)

            if "depth" in row:
                raw = float(row["depth"])
                p["depth"] = convert_depth(raw, depth_unit)

            if "specific_storage" in row:
                p["specific_storage"] = float(row["specific_storage"])

            if "water_content" in row:
                raw = float(row["water_content"])
                p["water_content"] = convert_porosity_val(raw, porosity_unit)

            params.append(p)
    return params


def validate_parameters(params):
    """Validate converted parameters against physical bounds."""
    warnings = []
    for p in params:
        pid = p.get("id", "?")
        if "hydraulic_conductivity" in p:
            k = p["hydraulic_conductivity"]
            if k <= 0:
                warnings.append(f"{pid}: Ksat={k} <= 0 (must be positive)")
            elif k > 1000:
                warnings.append(f"{pid}: Ksat={k} m/day very high (gravel?)")
        if "porosity" in p:
            n = p["porosity"]
            if n <= 0 or n >= 1:
                warnings.append(f"{pid}: porosity={n} outside (0,1)")
        if "depth" in p:
            d = p["depth"]
            if d <= 0:
                warnings.append(f"{pid}: depth={d} <= 0")
    return warnings


def process(args):
    """Generate OHQ-compatible parameter set."""
    result = {"status": "success", "warnings": []}

    if args.defaults:
        block_type = args.block_type or "Unconfined Groundwater cell"
        if block_type not in DEFAULT_PARAMS:
            result["status"] = "error"
            result["errors"] = [
                f"Unknown block type: {block_type}. "
                f"Available: {list(DEFAULT_PARAMS.keys())}"
            ]
            print(json.dumps(result, indent=2))
            sys.exit(1)

        params = DEFAULT_PARAMS[block_type]
        result["block_type"] = block_type
        result["parameters"] = params
    elif args.format == "hwsd":
        params = read_hwsd_format(args.input)
        result["warnings"] = validate_parameters(params)
        result["parameters"] = params
        result["n_records"] = len(params)
    else:
        params = read_generic_csv(
            args.input, args.ksat_unit, args.porosity_unit, args.depth_unit
        )
        result["warnings"] = validate_parameters(params)
        result["parameters"] = params
        result["n_records"] = len(params)

    # Write output
    outdir = os.path.dirname(args.output)
    if outdir:
        os.makedirs(outdir, exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(result, f, indent=2)

    result["output_file"] = args.output
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Convert soil/hydraulic parameters to OpenHydroQual format"
    )
    parser.add_argument("--input", default=None, help="Input parameter CSV file")
    parser.add_argument("--output", required=True, help="Output JSON file")
    parser.add_argument("--format", default="generic",
                        choices=["generic", "hwsd"],
                        help="Input format (default: generic)")
    parser.add_argument("--defaults", action="store_true",
                        help="Generate default parameters for a block type")
    parser.add_argument("--block-type", default=None,
                        help="Block type for defaults (e.g., 'Pond', 'Bed_sediment')")
    parser.add_argument("--ksat-unit", default="m/day",
                        choices=["m/day", "m/s", "cm/s", "cm/hr", "ft/day", "in/hr"],
                        help="Input Ksat unit (default: m/day)")
    parser.add_argument("--porosity-unit", default="fraction",
                        choices=["fraction", "percent"],
                        help="Input porosity unit (default: fraction)")
    parser.add_argument("--depth-unit", default="m",
                        choices=["m", "cm", "mm", "ft", "in"],
                        help="Input depth unit (default: m)")

    args = parser.parse_args()
    validate_inputs(args)
    result = process(args)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
