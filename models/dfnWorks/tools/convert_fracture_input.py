#!/usr/bin/env python3
"""
convert_fracture_input.py - Convert field fracture survey data to dfnWorks format.

Converts fracture orientation, size, and intensity data from common field survey
formats (scanline CSV, borehole logs, outcrop mapping) into pydfnworks
add_fracture_family() parameter dictionaries.

Handles unit conversions:
  - Strike/dip (degrees) to Fisher distribution (theta, phi, kappa)
  - Trace lengths (m, cm, ft) to radius distributions (m)
  - p10 (fractures/m along borehole) to approximate p32 (m²/m³)
  - Orientation convention: right-hand rule strike/dip to dfnWorks theta/phi

CRITICAL: All output radii and domain sizes are in METERS. If input trace lengths
are in cm or ft, they are converted. Failure to convert produces networks at wrong scale.

Usage:
    python convert_fracture_input.py --input scanline.csv --format scanline --output families.json
    python convert_fracture_input.py --input borehole.csv --format borehole --p10 2.5 --output families.json
    python convert_fracture_input.py --strike 45 --dip 60 --trace_mean 5.0 --trace_std 2.0 --output families.json
"""

import argparse
import json
import math
import os
import sys

import numpy as np


# ============================================================================
# Input Validation
# ============================================================================

def validate_inputs(args):
    """Validate all input arguments before processing.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed command-line arguments.

    Returns
    -------
    dict
        Validated parameters dictionary.

    Raises
    ------
    SystemExit
        If validation fails, exits with JSON error message.
    """
    errors = []

    # Check input file exists if provided
    if args.input and not os.path.isfile(args.input):
        errors.append(f"Input file not found: {args.input}")

    # Check format is valid
    valid_formats = ["scanline", "borehole", "manual"]
    if args.format not in valid_formats:
        errors.append(f"Invalid format '{args.format}'. Must be one of: {valid_formats}")

    # Check unit conversions
    valid_length_units = ["m", "cm", "mm", "ft", "in"]
    if args.length_unit not in valid_length_units:
        errors.append(f"Invalid length unit '{args.length_unit}'. Must be one of: {valid_length_units}")

    # Check manual mode has required params
    if args.format == "manual":
        if args.strike is None or args.dip is None:
            errors.append("Manual mode requires --strike and --dip")
        if args.trace_mean is None:
            errors.append("Manual mode requires --trace_mean")

    # Validate angle ranges
    if args.strike is not None and not (0 <= args.strike <= 360):
        errors.append(f"Strike must be 0-360 degrees, got {args.strike}")
    if args.dip is not None and not (0 <= args.dip <= 90):
        errors.append(f"Dip must be 0-90 degrees, got {args.dip}")

    # Validate positive values
    if args.trace_mean is not None and args.trace_mean <= 0:
        errors.append(f"Trace mean must be positive, got {args.trace_mean}")
    if args.p10 is not None and args.p10 <= 0:
        errors.append(f"p10 must be positive, got {args.p10}")
    if args.kappa_override is not None and args.kappa_override < 0:
        errors.append(f"kappa must be non-negative, got {args.kappa_override}")

    if errors:
        result = {"status": "error", "errors": errors}
        sys.stderr.write(json.dumps(result, indent=2) + "\n")
        sys.exit(1)

    return vars(args)


# ============================================================================
# Unit Conversion Functions
# ============================================================================

def convert_length_to_meters(value, unit):
    """Convert length value to meters.

    Parameters
    ----------
    value : float
        Length value in source units.
    unit : str
        Source unit: 'm', 'cm', 'mm', 'ft', 'in'.

    Returns
    -------
    float
        Length in meters.
    """
    factors = {
        "m": 1.0,
        "cm": 0.01,
        "mm": 0.001,
        "ft": 0.3048,
        "in": 0.0254,
    }
    return value * factors[unit]


def strike_dip_to_normal(strike_deg, dip_deg):
    """Convert strike/dip (right-hand rule) to unit normal vector.

    Parameters
    ----------
    strike_deg : float
        Strike angle in degrees (0-360, clockwise from N).
    dip_deg : float
        Dip angle in degrees (0-90, measured from horizontal).

    Returns
    -------
    tuple
        (nx, ny, nz) unit normal vector.
    """
    strike_rad = math.radians(strike_deg)
    dip_rad = math.radians(dip_deg)

    # Normal vector (pointing into upper hemisphere)
    nx = -math.sin(dip_rad) * math.sin(strike_rad)
    ny = math.sin(dip_rad) * math.cos(strike_rad)
    nz = math.cos(dip_rad)

    return (nx, ny, nz)


def normal_to_theta_phi(nx, ny, nz):
    """Convert normal vector to dfnWorks theta (trend) and phi (plunge).

    dfnWorks convention:
      theta = trend of pole (degrees from north, clockwise)
      phi = plunge of pole (degrees from horizontal)

    Parameters
    ----------
    nx, ny, nz : float
        Unit normal vector components.

    Returns
    -------
    tuple
        (theta_deg, phi_deg) in degrees.
    """
    # Ensure upper hemisphere
    if nz < 0:
        nx, ny, nz = -nx, -ny, -nz

    phi = math.degrees(math.acos(min(abs(nz), 1.0)))
    theta = math.degrees(math.atan2(nx, ny)) % 360

    return (theta, phi)


def estimate_fisher_kappa(orientations_deg):
    """Estimate Fisher concentration parameter kappa from orientation data.

    Uses the maximum likelihood estimate: kappa = (N-1) / (N - R)
    where R is the resultant length of unit vectors.

    Parameters
    ----------
    orientations_deg : np.ndarray
        Array of (strike, dip) pairs in degrees, shape (N, 2).

    Returns
    -------
    float
        Estimated Fisher kappa parameter.
    """
    if len(orientations_deg) < 3:
        return 10.0  # Default moderate concentration

    normals = []
    for strike, dip in orientations_deg:
        n = strike_dip_to_normal(strike, dip)
        normals.append(n)
    normals = np.array(normals)

    # Resultant vector
    resultant = np.sum(normals, axis=0)
    R = np.linalg.norm(resultant)
    N = len(normals)

    if R >= N - 1e-10:
        return 500.0  # Nearly parallel, very high concentration

    kappa = (N - 1.0) / (N - R)
    return max(0.1, min(kappa, 1000.0))


def p10_to_p32(p10, mean_radius, distribution="exp"):
    """Approximate p32 from p10 using stereological correction.

    p10 = fractures per unit length along a scanline (1/m)
    p32 = fracture area per unit volume (1/m)

    For randomly oriented circular fractures:
      p32 ~ p10 * pi * <r> / 2

    Parameters
    ----------
    p10 : float
        Linear fracture intensity (1/m).
    mean_radius : float
        Mean fracture radius in meters.
    distribution : str
        Size distribution type (affects correction factor).

    Returns
    -------
    float
        Estimated p32 in 1/m.
    """
    correction = math.pi / 2.0  # Circular fractures, random orientations
    p32 = p10 * correction * mean_radius
    return p32


def fit_size_distribution(trace_lengths_m, distribution="exp"):
    """Fit a size distribution to trace length data.

    Assumes trace length ~ 2 * radius for through-going fractures.

    Parameters
    ----------
    trace_lengths_m : np.ndarray
        Trace lengths in meters.
    distribution : str
        Target distribution: 'exp', 'log_normal', 'tpl'.

    Returns
    -------
    dict
        Distribution parameters for dfnWorks.
    """
    radii = trace_lengths_m / 2.0  # Approximate radius from trace length
    radii = radii[radii > 0]

    if len(radii) < 2:
        return {
            "distribution": distribution,
            "min_radius": float(np.min(radii)) if len(radii) > 0 else 1.0,
            "max_radius": float(np.max(radii)) if len(radii) > 0 else 10.0,
            "exp_mean": float(np.mean(radii)) if len(radii) > 0 else 5.0,
        }

    result = {
        "min_radius": float(np.min(radii)),
        "max_radius": float(np.max(radii)),
    }

    if distribution == "exp":
        result["distribution"] = "exp"
        result["exp_mean"] = float(np.mean(radii))
    elif distribution == "log_normal":
        result["distribution"] = "log_normal"
        log_radii = np.log(radii)
        result["log_mean"] = float(np.mean(log_radii))
        result["log_std"] = float(np.std(log_radii))
    elif distribution == "tpl":
        result["distribution"] = "tpl"
        # Estimate power-law exponent via MLE
        r_min = np.min(radii)
        if r_min > 0:
            alpha = 1.0 + len(radii) / np.sum(np.log(radii / r_min))
            result["alpha"] = float(alpha)
        else:
            result["alpha"] = 2.5

    return result


# ============================================================================
# File Parsing
# ============================================================================

def parse_scanline_csv(filepath, length_unit="m"):
    """Parse scanline survey CSV file.

    Expected columns: strike, dip, trace_length
    Optional columns: aperture, set_id

    Parameters
    ----------
    filepath : str
        Path to CSV file.
    length_unit : str
        Unit of trace_length column.

    Returns
    -------
    list of dict
        One dict per fracture set with orientations and sizes.
    """
    data = np.genfromtxt(filepath, delimiter=',', names=True, dtype=None,
                         encoding='utf-8')

    # Group by set_id if available
    if 'set_id' in data.dtype.names:
        set_ids = np.unique(data['set_id'])
    else:
        set_ids = [0]

    families = []
    for sid in set_ids:
        if 'set_id' in data.dtype.names:
            mask = data['set_id'] == sid
            subset = data[mask]
        else:
            subset = data

        orientations = np.column_stack([subset['strike'], subset['dip']])
        trace_lengths = np.array([convert_length_to_meters(t, length_unit)
                                  for t in subset['trace_length']])

        family = {
            "set_id": int(sid),
            "n_fractures": len(subset),
            "orientations": orientations,
            "trace_lengths_m": trace_lengths,
            "mean_strike": float(np.mean(subset['strike'])),
            "mean_dip": float(np.mean(subset['dip'])),
        }

        if 'aperture' in data.dtype.names:
            family["apertures_m"] = np.array([
                convert_length_to_meters(a, length_unit) for a in subset['aperture']
            ])

        families.append(family)

    return families


def parse_borehole_csv(filepath, length_unit="m"):
    """Parse borehole fracture log CSV.

    Expected columns: depth, strike, dip
    Optional: aperture, set_id

    Parameters
    ----------
    filepath : str
        Path to CSV file.
    length_unit : str
        Unit for depth and aperture columns.

    Returns
    -------
    list of dict
        Parsed fracture data grouped by set.
    """
    data = np.genfromtxt(filepath, delimiter=',', names=True, dtype=None,
                         encoding='utf-8')

    depths_m = np.array([convert_length_to_meters(d, length_unit)
                         for d in data['depth']])

    if 'set_id' in data.dtype.names:
        set_ids = np.unique(data['set_id'])
    else:
        set_ids = [0]

    families = []
    for sid in set_ids:
        if 'set_id' in data.dtype.names:
            mask = data['set_id'] == sid
            subset = data[mask]
            subset_depths = depths_m[mask]
        else:
            subset = data
            subset_depths = depths_m

        orientations = np.column_stack([subset['strike'], subset['dip']])

        # Compute p10 from borehole interval
        borehole_length = np.max(subset_depths) - np.min(subset_depths)
        if borehole_length > 0:
            p10_val = len(subset) / borehole_length
        else:
            p10_val = 1.0

        family = {
            "set_id": int(sid),
            "n_fractures": len(subset),
            "orientations": orientations,
            "p10": float(p10_val),
            "mean_strike": float(np.mean(subset['strike'])),
            "mean_dip": float(np.mean(subset['dip'])),
        }
        families.append(family)

    return families


# ============================================================================
# Main Processing
# ============================================================================

def process(args):
    """Convert field data to dfnWorks fracture family parameters.

    Parameters
    ----------
    args : dict
        Validated input arguments.

    Returns
    -------
    dict
        Result dictionary with dfnWorks-compatible fracture family parameters.
    """
    families_output = []

    if args["format"] == "manual":
        # Direct specification
        theta, phi = normal_to_theta_phi(
            *strike_dip_to_normal(args["strike"], args["dip"])
        )
        trace_mean_m = convert_length_to_meters(args["trace_mean"], args["length_unit"])
        trace_std_m = convert_length_to_meters(
            args.get("trace_std") or trace_mean_m * 0.5, args["length_unit"]
        )

        family = {
            "shape": args.get("shape", "ell"),
            "distribution": args.get("distribution", "exp"),
            "theta": round(theta, 2),
            "phi": round(phi, 2),
            "kappa": args["kappa_override"] if args["kappa_override"] else 10.0,
            "min_radius": round(trace_mean_m / 4.0, 4),
            "max_radius": round(trace_mean_m * 2.0, 4),
            "exp_mean": round(trace_mean_m / 2.0, 4),
            "hy_variable": "permeability",
            "hy_function": "constant",
            "hy_params": {"mu": 1e-12},
        }

        if args.get("p10"):
            family["p32"] = round(p10_to_p32(args["p10"], trace_mean_m / 2.0), 4)
        else:
            family["p32"] = 0.5  # Default

        families_output.append(family)

    elif args["format"] == "scanline":
        raw_families = parse_scanline_csv(args["input"], args["length_unit"])

        for fam in raw_families:
            theta, phi = normal_to_theta_phi(
                *strike_dip_to_normal(fam["mean_strike"], fam["mean_dip"])
            )
            kappa = estimate_fisher_kappa(fam["orientations"])
            size_params = fit_size_distribution(fam["trace_lengths_m"],
                                               args.get("distribution", "exp"))

            family = {
                "shape": args.get("shape", "ell"),
                "theta": round(theta, 2),
                "phi": round(phi, 2),
                "kappa": round(kappa, 2),
                **size_params,
                "hy_variable": "permeability",
                "hy_function": "semi-correlated",
                "hy_params": {"alpha": 1e-12, "beta": 0.8, "sigma": 0.5},
                "n_measurements": fam["n_fractures"],
            }

            if "apertures_m" in fam:
                mean_aper = float(np.mean(fam["apertures_m"]))
                family["hy_params"]["mu"] = mean_aper ** 2 / 12.0

            families_output.append(family)

    elif args["format"] == "borehole":
        raw_families = parse_borehole_csv(args["input"], args["length_unit"])
        default_mean_radius = convert_length_to_meters(
            args.get("trace_mean") or 5.0, args["length_unit"]
        ) / 2.0

        for fam in raw_families:
            theta, phi = normal_to_theta_phi(
                *strike_dip_to_normal(fam["mean_strike"], fam["mean_dip"])
            )
            kappa = estimate_fisher_kappa(fam["orientations"])
            p32 = p10_to_p32(fam["p10"], default_mean_radius)

            family = {
                "shape": args.get("shape", "ell"),
                "distribution": args.get("distribution", "exp"),
                "theta": round(theta, 2),
                "phi": round(phi, 2),
                "kappa": round(kappa, 2),
                "p32": round(p32, 4),
                "min_radius": round(default_mean_radius * 0.2, 4),
                "max_radius": round(default_mean_radius * 4.0, 4),
                "exp_mean": round(default_mean_radius, 4),
                "hy_variable": "permeability",
                "hy_function": "constant",
                "hy_params": {"mu": 1e-12},
                "n_measurements": fam["n_fractures"],
                "p10_observed": fam["p10"],
            }
            families_output.append(family)

    return {
        "status": "success",
        "n_families": len(families_output),
        "families": families_output,
        "units": {
            "radii": "m",
            "permeability": "m^2",
            "angles": "degrees",
            "p32": "1/m",
        },
        "warnings": [],
    }


# ============================================================================
# Output Validation
# ============================================================================

def validate_outputs(result):
    """Validate output parameters are physically reasonable.

    Parameters
    ----------
    result : dict
        Processing result dictionary.

    Returns
    -------
    dict
        Result with warnings added.
    """
    warnings = result.get("warnings", [])

    for i, fam in enumerate(result.get("families", [])):
        # Check radius range
        if fam.get("min_radius", 0) < 0.001:
            warnings.append(f"Family {i}: min_radius={fam['min_radius']}m is very small (<1mm)")
        if fam.get("max_radius", 0) > 10000:
            warnings.append(f"Family {i}: max_radius={fam['max_radius']}m is very large (>10km)")
        if fam.get("min_radius", 0) >= fam.get("max_radius", 1):
            warnings.append(f"Family {i}: min_radius >= max_radius")

        # Check kappa
        if fam.get("kappa", 10) < 0.5:
            warnings.append(f"Family {i}: kappa={fam['kappa']} is very low (nearly random orientations)")

        # Check p32
        if fam.get("p32", 0) > 20:
            warnings.append(f"Family {i}: p32={fam['p32']} is very high (>20/m), may cause meshing issues")

        # Check permeability
        k = fam.get("hy_params", {}).get("mu", 1e-12)
        if k > 1e-6:
            warnings.append(f"Family {i}: permeability={k} m^2 is very high. Did you use K (m/s) instead of k (m^2)?")

    result["warnings"] = warnings
    return result


# ============================================================================
# CLI Entry Point
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Convert field fracture data to dfnWorks fracture families"
    )
    parser.add_argument("--input", "-i", help="Input CSV file path")
    parser.add_argument("--format", "-f", default="manual",
                        choices=["scanline", "borehole", "manual"],
                        help="Input data format")
    parser.add_argument("--output", "-o", default="families.json",
                        help="Output JSON file path")
    parser.add_argument("--length_unit", default="m",
                        choices=["m", "cm", "mm", "ft", "in"],
                        help="Length unit in input data (default: m)")
    parser.add_argument("--distribution", default="exp",
                        choices=["exp", "log_normal", "tpl"],
                        help="Target size distribution")
    parser.add_argument("--shape", default="ell",
                        choices=["ell", "rect"],
                        help="Fracture shape (default: ell)")

    # Manual mode parameters
    parser.add_argument("--strike", type=float, help="Mean strike (degrees)")
    parser.add_argument("--dip", type=float, help="Mean dip (degrees)")
    parser.add_argument("--trace_mean", type=float, help="Mean trace length")
    parser.add_argument("--trace_std", type=float, help="Trace length std dev")
    parser.add_argument("--p10", type=float, help="Linear fracture intensity (1/m)")
    parser.add_argument("--kappa_override", type=float, help="Override Fisher kappa")

    args = parser.parse_args()
    validated = validate_inputs(args)
    result = process(validated)
    result = validate_outputs(result)

    with open(validated["output"], "w") as f:
        json.dump(result, f, indent=2, default=str)

    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
