#!/usr/bin/env python3
"""
convert_parameters.py — Convert soil/land-use data to SuperflexPy parameters.

Maps soil properties (from HWSD, SoilGrids, or manual input) and land-use
characteristics to model parameters for common SuperflexPy model structures
(GR4J, HBV-style, HYMOD).

Uses pedotransfer functions and empirical relationships to estimate:
- Storage capacities (x1, x3, Smax)
- Recession coefficients (k, x2)
- Shape parameters (alpha, beta)

Usage:
    python convert_parameters.py --model gr4j --output params.json
    python convert_parameters.py --model gr4j --soil-texture clay --depth 1.5 --output params.json
    python convert_parameters.py --model hbv --porosity 0.45 --fc 0.30 --output params.json
"""

import argparse
import json
import sys

import numpy as np

# Default parameter ranges for each model
MODEL_DEFAULTS = {
    "gr4j": {
        "x1": {"default": 350.0, "min": 10.0, "max": 2000.0, "unit": "mm", "desc": "Production store capacity"},
        "x2": {"default": 0.0, "min": -5.0, "max": 5.0, "unit": "mm/d", "desc": "Exchange coefficient"},
        "x3": {"default": 90.0, "min": 1.0, "max": 500.0, "unit": "mm", "desc": "Routing store capacity"},
        "x4": {"default": 1.7, "min": 0.5, "max": 10.0, "unit": "d", "desc": "Unit hydrograph time base"},
        "alpha": {"default": 2.0, "fixed": True, "unit": "-", "desc": "PS exponent"},
        "beta": {"default": 5.0, "fixed": True, "unit": "-", "desc": "Percolation exponent"},
        "ni": {"default": 0.4444, "fixed": True, "unit": "-", "desc": "Percolation coefficient"},
        "gamma": {"default": 5.0, "fixed": True, "unit": "-", "desc": "RS outflow exponent"},
        "omega": {"default": 3.5, "fixed": True, "unit": "-", "desc": "Exchange flux exponent"},
    },
    "hbv": {
        "Smax": {"default": 200.0, "min": 10.0, "max": 1000.0, "unit": "mm", "desc": "Max soil moisture storage"},
        "Ce": {"default": 1.0, "min": 0.1, "max": 2.0, "unit": "-", "desc": "PET correction factor"},
        "m": {"default": 0.01, "min": 0.001, "max": 1.0, "unit": "-", "desc": "ET smoothing factor"},
        "beta": {"default": 2.0, "min": 0.5, "max": 5.0, "unit": "-", "desc": "Runoff exponent"},
        "k": {"default": 0.05, "min": 0.001, "max": 1.0, "unit": "1/d", "desc": "Recession coefficient"},
        "alpha": {"default": 2.5, "min": 1.0, "max": 5.0, "unit": "-", "desc": "Power reservoir exponent"},
    },
    "hymod": {
        "Smax": {"default": 100.0, "min": 10.0, "max": 500.0, "unit": "mm", "desc": "Max storage capacity"},
        "m": {"default": 0.01, "min": 0.001, "max": 1.0, "unit": "-", "desc": "ET smoothing factor"},
        "beta": {"default": 2.0, "min": 0.5, "max": 5.0, "unit": "-", "desc": "Distribution function shape"},
        "k": {"default": 0.1, "min": 0.01, "max": 1.0, "unit": "1/d", "desc": "Reservoir recession"},
    },
}

# Soil texture lookup table for pedotransfer
SOIL_TEXTURE_PROPERTIES = {
    "sand": {"porosity": 0.43, "fc": 0.10, "wp": 0.05, "ksat": 500.0},
    "loamy_sand": {"porosity": 0.44, "fc": 0.15, "wp": 0.07, "ksat": 300.0},
    "sandy_loam": {"porosity": 0.45, "fc": 0.22, "wp": 0.10, "ksat": 100.0},
    "loam": {"porosity": 0.46, "fc": 0.30, "wp": 0.15, "ksat": 50.0},
    "silt_loam": {"porosity": 0.47, "fc": 0.35, "wp": 0.17, "ksat": 30.0},
    "silt": {"porosity": 0.46, "fc": 0.38, "wp": 0.18, "ksat": 25.0},
    "sandy_clay_loam": {"porosity": 0.39, "fc": 0.28, "wp": 0.17, "ksat": 20.0},
    "clay_loam": {"porosity": 0.46, "fc": 0.36, "wp": 0.22, "ksat": 10.0},
    "silty_clay_loam": {"porosity": 0.47, "fc": 0.38, "wp": 0.25, "ksat": 8.0},
    "sandy_clay": {"porosity": 0.43, "fc": 0.34, "wp": 0.24, "ksat": 5.0},
    "silty_clay": {"porosity": 0.48, "fc": 0.40, "wp": 0.28, "ksat": 3.0},
    "clay": {"porosity": 0.48, "fc": 0.42, "wp": 0.30, "ksat": 2.0},
}


def validate_inputs(args):
    """Validate command-line arguments."""
    errors = []

    if args.model not in MODEL_DEFAULTS:
        errors.append(
            f"Unknown model: {args.model}. "
            f"Supported: {list(MODEL_DEFAULTS.keys())}"
        )

    if args.soil_texture and args.soil_texture not in SOIL_TEXTURE_PROPERTIES:
        errors.append(
            f"Unknown soil texture: {args.soil_texture}. "
            f"Supported: {list(SOIL_TEXTURE_PROPERTIES.keys())}"
        )

    if args.depth is not None and args.depth <= 0:
        errors.append(f"Soil depth must be positive, got {args.depth}")

    if args.porosity is not None and not (0 < args.porosity < 1):
        errors.append(f"Porosity must be 0-1, got {args.porosity}")

    if args.fc is not None and not (0 < args.fc < 1):
        errors.append(f"Field capacity must be 0-1, got {args.fc}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)


def estimate_from_soil(args):
    """Estimate hydrological parameters from soil properties."""
    # Get soil properties
    if args.soil_texture:
        soil = SOIL_TEXTURE_PROPERTIES[args.soil_texture]
        porosity = soil["porosity"]
        fc = soil["fc"]
        wp = soil["wp"]
        ksat = soil["ksat"]
    else:
        porosity = args.porosity or 0.45
        fc = args.fc or 0.30
        wp = args.wp or 0.15
        ksat = args.ksat or 50.0

    depth = args.depth or 1.0  # meters

    # Available water capacity (mm)
    awc = (fc - wp) * depth * 1000.0

    # Total porosity storage (mm)
    total_storage = porosity * depth * 1000.0

    # Recession coefficient from Ksat (rough empirical)
    k_recession = min(1.0, max(0.001, ksat / 10000.0))

    return {
        "awc_mm": awc,
        "total_storage_mm": total_storage,
        "porosity": porosity,
        "fc": fc,
        "wp": wp,
        "ksat_mm_d": ksat,
        "depth_m": depth,
        "k_recession": k_recession,
    }


def process(args):
    """Generate model parameters from soil/land data."""
    model = args.model
    defaults = MODEL_DEFAULTS[model]

    # Start with defaults
    params = {}
    for name, spec in defaults.items():
        params[name] = spec["default"]

    # Override from soil data if provided
    soil_info = None
    if args.soil_texture or args.porosity:
        soil_info = estimate_from_soil(args)

        if model == "gr4j":
            # x1 ~ available water capacity
            params["x1"] = np.clip(soil_info["awc_mm"] * 2.5, 10.0, 2000.0)
            # x3 ~ subset of total storage
            params["x3"] = np.clip(soil_info["total_storage_mm"] * 0.3, 1.0, 500.0)

        elif model == "hbv":
            params["Smax"] = np.clip(soil_info["awc_mm"] * 1.5, 10.0, 1000.0)
            params["k"] = np.clip(soil_info["k_recession"], 0.001, 1.0)
            # beta increases with clay content (slower runoff generation)
            params["beta"] = np.clip(2.0 + (0.42 - soil_info["fc"]) * 10.0, 0.5, 5.0)

        elif model == "hymod":
            params["Smax"] = np.clip(soil_info["awc_mm"], 10.0, 500.0)
            params["k"] = np.clip(soil_info["k_recession"] * 2.0, 0.01, 1.0)

    # Override from explicit CLI parameters
    if args.params:
        for kv in args.params:
            key, val = kv.split("=")
            if key in params:
                params[key] = float(val)
            else:
                print(
                    f"WARNING: Unknown parameter '{key}' for model '{model}'",
                    file=sys.stderr,
                )

    # Build parameter dict with proper prefixes for SuperflexPy
    prefixed = {}
    param_info = {}
    for name, value in params.items():
        spec = defaults.get(name, {})
        param_info[name] = {
            "value": float(value),
            "unit": spec.get("unit", "-"),
            "description": spec.get("desc", ""),
            "range": [spec.get("min", None), spec.get("max", None)],
            "fixed": spec.get("fixed", False),
        }
        prefixed[name] = float(value)

    result = {
        "status": "success",
        "model": model,
        "parameters": prefixed,
        "parameter_info": param_info,
    }

    if soil_info:
        result["soil_properties"] = {k: float(v) for k, v in soil_info.items()}

    return result


def validate_outputs(result):
    """Validate output parameters for common errors."""
    if result["status"] != "success":
        return result

    warnings = []
    model = result["model"]
    params = result["parameters"]

    # Check parameter ranges
    for name, value in params.items():
        spec = MODEL_DEFAULTS[model].get(name, {})
        pmin = spec.get("min")
        pmax = spec.get("max")
        if pmin is not None and value < pmin:
            warnings.append(
                f"WARNING: {name}={value} is below minimum {pmin}"
            )
        if pmax is not None and value > pmax:
            warnings.append(
                f"WARNING: {name}={value} is above maximum {pmax}"
            )

    # Model-specific checks
    if model == "gr4j":
        if params.get("x1", 0) < 50:
            warnings.append(
                "WARNING: x1 < 50 mm is unusually small — "
                "check if soil depth is in meters (dt_005)"
            )

    if warnings:
        result["warnings"] = warnings
        for w in warnings:
            print(w, file=sys.stderr)

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Convert soil/land-use data to SuperflexPy parameters"
    )
    parser.add_argument("--model", type=str, required=True, help="Model type: gr4j, hbv, hymod")
    parser.add_argument("--output", type=str, default=None, help="Output JSON file path")
    parser.add_argument("--soil-texture", type=str, default=None, help="USDA soil texture class")
    parser.add_argument("--depth", type=float, default=None, help="Soil depth in meters")
    parser.add_argument("--porosity", type=float, default=None, help="Soil porosity (0-1)")
    parser.add_argument("--fc", type=float, default=None, help="Field capacity (0-1)")
    parser.add_argument("--wp", type=float, default=None, help="Wilting point (0-1)")
    parser.add_argument("--ksat", type=float, default=None, help="Saturated hydraulic conductivity (mm/d)")
    parser.add_argument("--params", nargs="*", default=None, help="Override params as key=value pairs")

    args = parser.parse_args()

    validate_inputs(args)
    result = process(args)
    result = validate_outputs(result)

    output_json = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        with open(args.output, "w") as f:
            f.write(output_json)
        print(f"Results written to {args.output}", file=sys.stderr)
    else:
        print(output_json)


if __name__ == "__main__":
    main()
