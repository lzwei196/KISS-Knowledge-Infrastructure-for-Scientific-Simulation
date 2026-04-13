#!/usr/bin/env python3
"""
convert_hydraulic_params.py - Convert hydraulic parameters to dfnWorks format.

Converts hydraulic conductivity (K, m/s), transmissivity (T, m^2/s), or
aperture (b, m) measurements to dfnWorks permeability (k, m^2) format.

Key conversions:
  - K (m/s) to k (m^2):  k = K * mu / (rho * g)
  - T (m^2/s) to k (m^2):  k = T * mu / (rho * g * b)
  - b (m) to k (m^2):  k = b^2 / 12  (cubic law)
  - mD to m^2:  k_m2 = k_mD * 9.869233e-16

CRITICAL: dfnWorks uses intrinsic permeability in m^2, NOT hydraulic
conductivity in m/s. Using K directly as k overestimates by ~7 orders of
magnitude. This is the single most common unit error.

Usage:
    python convert_hydraulic_params.py --K 1e-5 --output params.json
    python convert_hydraulic_params.py --T 1e-4 --aperture 1e-3 --output params.json
    python convert_hydraulic_params.py --input packer_tests.csv --output params.json
    python convert_hydraulic_params.py --aperture 1e-4 --cubic_law --output params.json
"""

import argparse
import json
import math
import os
import sys

import numpy as np


# Physical constants
RHO_WATER = 997.0       # kg/m^3, water density at 20 C
G = 9.81                 # m/s^2, gravitational acceleration
MU_WATER = 8.9e-4        # Pa.s, dynamic viscosity of water at 20 C
MD_TO_M2 = 9.869233e-16  # millidarcy to m^2


# ============================================================================
# Input Validation
# ============================================================================

def validate_inputs(args):
    """Validate all input arguments.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed command-line arguments.

    Returns
    -------
    dict
        Validated parameters.
    """
    errors = []

    # Check at least one input source
    has_direct = any([args.K, args.T, args.aperture, args.k_mD])
    has_file = args.input is not None

    if not has_direct and not has_file:
        errors.append("Must provide at least one of: --K, --T, --aperture, --k_mD, or --input")

    if has_file and not os.path.isfile(args.input):
        errors.append(f"Input file not found: {args.input}")

    # Validate physical ranges
    if args.K is not None and args.K <= 0:
        errors.append(f"Hydraulic conductivity K must be positive, got {args.K}")
    if args.T is not None and args.T <= 0:
        errors.append(f"Transmissivity T must be positive, got {args.T}")
    if args.aperture is not None and args.aperture <= 0:
        errors.append(f"Aperture must be positive, got {args.aperture}")
    if args.k_mD is not None and args.k_mD <= 0:
        errors.append(f"Permeability in mD must be positive, got {args.k_mD}")

    # Validate fluid properties
    if args.viscosity is not None and args.viscosity <= 0:
        errors.append(f"Viscosity must be positive, got {args.viscosity}")
    if args.density is not None and args.density <= 0:
        errors.append(f"Density must be positive, got {args.density}")

    # Check aperture unit
    valid_aper_units = ["m", "mm", "um", "cm"]
    if args.aperture_unit not in valid_aper_units:
        errors.append(f"Invalid aperture unit '{args.aperture_unit}'. Must be one of: {valid_aper_units}")

    if errors:
        result = {"status": "error", "errors": errors}
        sys.stderr.write(json.dumps(result, indent=2) + "\n")
        sys.exit(1)

    return vars(args)


# ============================================================================
# Unit Conversion Functions
# ============================================================================

def convert_aperture_to_meters(value, unit):
    """Convert aperture to meters.

    Parameters
    ----------
    value : float
        Aperture value.
    unit : str
        Source unit: 'm', 'mm', 'um', 'cm'.

    Returns
    -------
    float
        Aperture in meters.
    """
    factors = {
        "m": 1.0,
        "cm": 0.01,
        "mm": 1e-3,
        "um": 1e-6,
    }
    return value * factors[unit]


def K_to_k(K, mu=MU_WATER, rho=RHO_WATER, g=G):
    """Convert hydraulic conductivity (m/s) to intrinsic permeability (m^2).

    k = K * mu / (rho * g)

    Parameters
    ----------
    K : float
        Hydraulic conductivity in m/s.
    mu : float
        Dynamic viscosity in Pa.s (default: water at 20 C).
    rho : float
        Fluid density in kg/m^3 (default: water).
    g : float
        Gravitational acceleration in m/s^2.

    Returns
    -------
    float
        Intrinsic permeability in m^2.
    """
    return K * mu / (rho * g)


def T_to_k(T, b, mu=MU_WATER, rho=RHO_WATER, g=G):
    """Convert transmissivity (m^2/s) to intrinsic permeability (m^2).

    T = K * b, so k = T * mu / (rho * g * b)

    Parameters
    ----------
    T : float
        Transmissivity in m^2/s.
    b : float
        Aperture (fracture thickness) in meters.
    mu : float
        Dynamic viscosity in Pa.s.
    rho : float
        Fluid density in kg/m^3.
    g : float
        Gravitational acceleration in m/s^2.

    Returns
    -------
    float
        Intrinsic permeability in m^2.
    """
    return T * mu / (rho * g * b)


def aperture_to_k_cubic(b):
    """Convert aperture to permeability using cubic law.

    k = b^2 / 12

    Parameters
    ----------
    b : float
        Aperture in meters.

    Returns
    -------
    float
        Intrinsic permeability in m^2.
    """
    return b ** 2 / 12.0


def mD_to_m2(k_mD):
    """Convert millidarcy to m^2.

    Parameters
    ----------
    k_mD : float
        Permeability in millidarcy.

    Returns
    -------
    float
        Permeability in m^2.
    """
    return k_mD * MD_TO_M2


def k_to_transmissivity(k, b, mu=MU_WATER, rho=RHO_WATER, g=G):
    """Convert permeability to transmissivity.

    T = k * rho * g * b / mu

    Parameters
    ----------
    k : float
        Intrinsic permeability in m^2.
    b : float
        Aperture in meters.

    Returns
    -------
    float
        Transmissivity in m^2/s.
    """
    return k * rho * g * b / mu


# ============================================================================
# File Parsing
# ============================================================================

def parse_packer_test_csv(filepath):
    """Parse packer test results CSV.

    Expected columns: depth_m, K_m_s (or T_m2_s), aperture_m (optional)

    Parameters
    ----------
    filepath : str
        Path to CSV file.

    Returns
    -------
    list of dict
        Parsed test results.
    """
    data = np.genfromtxt(filepath, delimiter=',', names=True, dtype=None,
                         encoding='utf-8')

    results = []
    for row in data:
        entry = {"depth_m": float(row['depth_m'])}

        if 'K_m_s' in data.dtype.names:
            entry["K_m_s"] = float(row['K_m_s'])
            entry["k_m2"] = K_to_k(entry["K_m_s"])

        if 'T_m2_s' in data.dtype.names:
            entry["T_m2_s"] = float(row['T_m2_s'])

        if 'aperture_m' in data.dtype.names:
            entry["aperture_m"] = float(row['aperture_m'])

            if 'T_m2_s' in entry and entry["aperture_m"] > 0:
                entry["k_m2_from_T"] = T_to_k(entry["T_m2_s"], entry["aperture_m"])

            entry["k_m2_cubic"] = aperture_to_k_cubic(entry["aperture_m"])

        results.append(entry)

    return results


# ============================================================================
# Main Processing
# ============================================================================

def process(args):
    """Convert hydraulic parameters to dfnWorks format.

    Parameters
    ----------
    args : dict
        Validated input arguments.

    Returns
    -------
    dict
        Result with converted parameters.
    """
    conversions = []
    mu = args.get("viscosity") or MU_WATER
    rho = args.get("density") or RHO_WATER

    # Direct conversions
    if args.get("K"):
        k = K_to_k(args["K"], mu, rho)
        conversions.append({
            "source": "hydraulic_conductivity",
            "K_m_s": args["K"],
            "k_m2": k,
            "method": "k = K * mu / (rho * g)",
            "mu_Pa_s": mu,
            "rho_kg_m3": rho,
        })

    if args.get("T"):
        aper = args.get("aperture")
        if aper:
            aper_m = convert_aperture_to_meters(aper, args["aperture_unit"])
            k = T_to_k(args["T"], aper_m, mu, rho)
            conversions.append({
                "source": "transmissivity",
                "T_m2_s": args["T"],
                "aperture_m": aper_m,
                "k_m2": k,
                "method": "k = T * mu / (rho * g * b)",
            })
        else:
            conversions.append({
                "source": "transmissivity",
                "T_m2_s": args["T"],
                "warning": "No aperture provided; cannot convert T to k without aperture",
            })

    if args.get("aperture") and args.get("cubic_law"):
        aper_m = convert_aperture_to_meters(args["aperture"], args["aperture_unit"])
        k = aperture_to_k_cubic(aper_m)
        T = k_to_transmissivity(k, aper_m, mu, rho)
        conversions.append({
            "source": "aperture_cubic_law",
            "aperture_m": aper_m,
            "k_m2": k,
            "T_m2_s": T,
            "method": "k = b^2 / 12 (parallel plate cubic law)",
        })

    if args.get("k_mD"):
        k = mD_to_m2(args["k_mD"])
        conversions.append({
            "source": "millidarcy",
            "k_mD": args["k_mD"],
            "k_m2": k,
            "method": "k_m2 = k_mD * 9.869e-16",
        })

    # File-based conversions
    if args.get("input"):
        file_results = parse_packer_test_csv(args["input"])
        for entry in file_results:
            conversions.append({
                "source": "packer_test_file",
                **entry,
            })

    # Build dfnWorks-ready output
    all_k = [c["k_m2"] for c in conversions if "k_m2" in c]

    dfnworks_params = {}
    if all_k:
        k_mean = float(np.mean(all_k))
        k_std = float(np.std(all_k)) if len(all_k) > 1 else 0.0
        k_log_mean = float(np.mean(np.log10(all_k)))
        k_log_std = float(np.std(np.log10(all_k))) if len(all_k) > 1 else 0.0

        dfnworks_params = {
            "hy_variable": "permeability",
            "constant": {"hy_function": "constant", "hy_params": {"mu": k_mean}},
            "correlated": {
                "hy_function": "correlated",
                "hy_params": {"alpha": k_mean, "beta": 0.8},
            },
            "semi_correlated": {
                "hy_function": "semi-correlated",
                "hy_params": {
                    "alpha": 10 ** k_log_mean,
                    "beta": 0.8,
                    "sigma": max(k_log_std, 0.5),
                },
            },
            "statistics": {
                "n_values": len(all_k),
                "k_mean_m2": k_mean,
                "k_std_m2": k_std,
                "k_log10_mean": k_log_mean,
                "k_log10_std": k_log_std,
                "k_min_m2": float(np.min(all_k)),
                "k_max_m2": float(np.max(all_k)),
            },
        }

    return {
        "status": "success",
        "conversions": conversions,
        "dfnworks_params": dfnworks_params,
        "units": {
            "permeability": "m^2",
            "transmissivity": "m^2/s",
            "hydraulic_conductivity": "m/s",
            "aperture": "m",
            "viscosity": "Pa.s",
            "density": "kg/m^3",
        },
    }


# ============================================================================
# Output Validation
# ============================================================================

def validate_outputs(result):
    """Validate converted parameters are physically reasonable.

    Parameters
    ----------
    result : dict
        Processing result.

    Returns
    -------
    dict
        Result with warnings added.
    """
    warnings = []

    for conv in result.get("conversions", []):
        k = conv.get("k_m2")
        if k is not None:
            if k > 1e-6:
                warnings.append(
                    f"Permeability {k:.2e} m^2 is very high (> 1e-6). "
                    "Check if input was K (m/s) instead of k (m^2)."
                )
            if k < 1e-20:
                warnings.append(
                    f"Permeability {k:.2e} m^2 is extremely low (< 1e-20). "
                    "Check input values and units."
                )

    result["warnings"] = warnings
    return result


# ============================================================================
# CLI Entry Point
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Convert hydraulic parameters to dfnWorks permeability (m^2)"
    )
    parser.add_argument("--K", type=float, help="Hydraulic conductivity (m/s)")
    parser.add_argument("--T", type=float, help="Transmissivity (m^2/s)")
    parser.add_argument("--aperture", type=float, help="Fracture aperture")
    parser.add_argument("--aperture_unit", default="m",
                        choices=["m", "mm", "um", "cm"],
                        help="Aperture unit (default: m)")
    parser.add_argument("--cubic_law", action="store_true",
                        help="Compute k from aperture via cubic law (k=b^2/12)")
    parser.add_argument("--k_mD", type=float, help="Permeability in millidarcy")
    parser.add_argument("--input", "-i", help="CSV file with packer test data")
    parser.add_argument("--output", "-o", default="hydraulic_params.json",
                        help="Output JSON file")
    parser.add_argument("--viscosity", type=float,
                        help=f"Fluid viscosity in Pa.s (default: {MU_WATER})")
    parser.add_argument("--density", type=float,
                        help=f"Fluid density in kg/m^3 (default: {RHO_WATER})")

    args = parser.parse_args()
    validated = validate_inputs(args)
    result = process(validated)
    result = validate_outputs(result)

    with open(validated["output"], "w") as f:
        json.dump(result, f, indent=2)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
