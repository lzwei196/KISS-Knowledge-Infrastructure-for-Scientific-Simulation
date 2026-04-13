#!/usr/bin/env python3
"""
generate_muskingum_params.py — Generate Muskingum k and x parameter CSV files.

RAPID uses the Muskingum method with two parameters per reach:
  k = wave travel time through reach (seconds)
  x = weighting factor (dimensionless, 0 to 0.5)

Methods for estimating k:
  1. From reach length and celerity: k = L / c  (L in m, c in m/s)
  2. From NHDPlus/MERIT attributes: k = length_km × 1000 / celerity_m_s
  3. From kfac file: k = kfac × lambda  (lambda = calibration multiplier)

CRITICAL UNIT TRAP:
  - k MUST be in SECONDS. A common error is providing k in hours.
  - If k = 2.5 (meaning 2.5 hours), the actual value should be 9000 seconds.
  - Stability: k*x <= dt/2 <= k*(1-x), where dt = ZS_dtR in seconds.

Usage:
  python generate_muskingum_params.py \\
    --reach_properties /path/to/reach_properties.csv \\
    --riv_bas_id /path/to/riv_bas_id.csv \\
    --method celerity \\
    --default_celerity 1.0 \\
    --default_x 0.1 \\
    --dt_r 900 \\
    --output_k /path/to/k.csv \\
    --output_x /path/to/x.csv
"""

import argparse
import json
import os
import sys

import numpy as np


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_inputs(args):
    """Check inputs exist and parameters are reasonable."""
    errors = []

    if not os.path.isfile(args.riv_bas_id):
        errors.append(f"riv_bas_id file not found: {args.riv_bas_id}")

    if args.reach_properties and not os.path.isfile(args.reach_properties):
        errors.append(f"Reach properties file not found: {args.reach_properties}")

    if args.default_x < 0 or args.default_x > 0.5:
        errors.append(f"x must be in [0, 0.5], got {args.default_x}")

    if args.default_celerity <= 0:
        errors.append(f"Celerity must be positive, got {args.default_celerity}")

    if args.dt_r <= 0:
        errors.append(f"dt_r must be positive, got {args.dt_r}")

    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


def validate_outputs(k_arr, x_arr, dt_r, riv_ids):
    """Check Muskingum stability conditions and physical plausibility."""
    warnings = []
    n = len(k_arr)

    # Check for NaN or negative
    if np.any(np.isnan(k_arr)):
        warnings.append(f"k contains {np.isnan(k_arr).sum()} NaN values")
    if np.any(k_arr <= 0):
        warnings.append(f"k contains {(k_arr <= 0).sum()} non-positive values")
    if np.any(np.isnan(x_arr)):
        warnings.append(f"x contains {np.isnan(x_arr).sum()} NaN values")

    # Range checks
    if np.any(x_arr < 0) or np.any(x_arr > 0.5):
        warnings.append(f"x values outside [0, 0.5]: min={x_arr.min():.4f}, max={x_arr.max():.4f}")

    # Muskingum stability: k*x <= dt/2 <= k*(1-x)
    lower = k_arr * x_arr
    upper = k_arr * (1 - x_arr)
    dt_half = dt_r / 2.0

    unstable_lower = np.sum(lower > dt_half)
    unstable_upper = np.sum(upper < dt_half)

    if unstable_lower > 0:
        warnings.append(f"{unstable_lower}/{n} reaches violate k*x <= dt/2 "
                        f"(Courant lower bound)")
    if unstable_upper > 0:
        warnings.append(f"{unstable_upper}/{n} reaches violate dt/2 <= k*(1-x) "
                        f"(Courant upper bound)")

    # Plausibility: k should be 15 min to 100 hours for most rivers
    k_min, k_max = np.nanmin(k_arr), np.nanmax(k_arr)
    if k_min < 60:
        warnings.append(f"Min k = {k_min:.0f}s ({k_min/3600:.2f}h) — suspiciously short, "
                        "check if k is in hours instead of seconds")
    if k_max > 360000:
        warnings.append(f"Max k = {k_max:.0f}s ({k_max/3600:.1f}h) — very long travel time, "
                        "verify reach lengths")

    for w in warnings:
        print(f"WARNING: {w}", file=sys.stderr)

    return {
        "n_reaches": n,
        "k_min_s": float(k_min), "k_max_s": float(k_max),
        "k_mean_s": float(np.nanmean(k_arr)),
        "x_min": float(np.nanmin(x_arr)), "x_max": float(np.nanmax(x_arr)),
        "unstable_lower": int(unstable_lower),
        "unstable_upper": int(unstable_upper),
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Parameter generation methods
# ---------------------------------------------------------------------------

def read_riv_bas_id(filepath):
    """Read reach IDs from CSV (one per line)."""
    ids = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                ids.append(int(line))
    return np.array(ids)


def read_reach_properties(filepath):
    """
    Read reach properties CSV: reach_id, length_m, [slope], [celerity_m_s]
    Returns dict: {reach_id: {'length_m': ..., 'slope': ..., 'celerity': ...}}
    """
    props = {}
    with open(filepath) as f:
        header = None
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if header is None and not parts[0].isdigit():
                header = parts
                continue
            rid = int(parts[0])
            props[rid] = {
                "length_m": float(parts[1]) if len(parts) > 1 else 1000.0,
                "slope": float(parts[2]) if len(parts) > 2 else 0.001,
                "celerity": float(parts[3]) if len(parts) > 3 else None,
            }
    return props


def compute_k_from_celerity(length_m, celerity_m_s):
    """k = length / celerity (result in seconds)."""
    if celerity_m_s <= 0:
        return 3600.0  # default 1 hour
    return length_m / celerity_m_s


def compute_celerity_from_slope(slope, method="manning"):
    """
    Estimate wave celerity from channel slope.
    Manning approximation: c ≈ 5/3 × n^(-1) × R^(2/3) × S^(1/2)
    Simplified: c ≈ 1.0 × S^0.3 (empirical, m/s, for typical rivers)
    """
    if method == "manning":
        return max(0.1, 1.0 * slope ** 0.3)
    return 1.0  # fallback


def generate_params(riv_ids, reach_props, method, default_celerity, default_x, dt_r):
    """Generate k and x arrays for all reaches."""
    n = len(riv_ids)
    k_arr = np.zeros(n)
    x_arr = np.full(n, default_x)

    for i, rid in enumerate(riv_ids):
        if rid in reach_props:
            rp = reach_props[rid]
            length = rp["length_m"]

            if method == "celerity" and rp.get("celerity"):
                celerity = rp["celerity"]
            elif method == "slope" and rp.get("slope"):
                celerity = compute_celerity_from_slope(rp["slope"])
            else:
                celerity = default_celerity

            k_arr[i] = compute_k_from_celerity(length, celerity)
        else:
            # Default: assume 10 km reach at default celerity
            k_arr[i] = 10000.0 / default_celerity

    # Enforce stability: clamp k so that k*x <= dt/2 <= k*(1-x)
    k_min_stable = dt_r / (2.0 * (1.0 - x_arr))
    k_max_stable = dt_r / (2.0 * x_arr + 1e-10)

    clamped = 0
    for i in range(n):
        if k_arr[i] < k_min_stable[i]:
            k_arr[i] = k_min_stable[i]
            clamped += 1
        elif k_arr[i] > k_max_stable[i] and x_arr[i] > 0:
            k_arr[i] = k_max_stable[i]
            clamped += 1

    if clamped > 0:
        print(f"INFO: Clamped k for {clamped}/{n} reaches to satisfy stability", file=sys.stderr)

    return k_arr, x_arr


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def write_param_csv(filepath, values):
    """Write one value per line (RAPID CSV format)."""
    os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
    with open(filepath, "w") as f:
        for v in values:
            f.write(f"{v}\n")
    print(f"Wrote {len(values)} values to {filepath}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def process(args):
    """Main pipeline: validate → generate → write → validate."""
    riv_ids = read_riv_bas_id(args.riv_bas_id)
    print(f"Read {len(riv_ids)} reach IDs")

    if args.reach_properties:
        reach_props = read_reach_properties(args.reach_properties)
        print(f"Read properties for {len(reach_props)} reaches")
    else:
        reach_props = {}
        print("No reach properties file — using defaults for all reaches")

    k_arr, x_arr = generate_params(
        riv_ids, reach_props, args.method,
        args.default_celerity, args.default_x, args.dt_r
    )

    write_param_csv(args.output_k, k_arr)
    write_param_csv(args.output_x, x_arr)

    report = validate_outputs(k_arr, x_arr, args.dt_r, riv_ids)
    print(json.dumps(report, indent=2))
    return report


def main():
    parser = argparse.ArgumentParser(
        description="Generate Muskingum k (seconds) and x (dimensionless) CSV files for RAPID")
    parser.add_argument("--reach_properties", default=None,
                        help="CSV: reach_id, length_m, [slope], [celerity_m_s]")
    parser.add_argument("--riv_bas_id", required=True,
                        help="RAPID riv_bas_id file")
    parser.add_argument("--method", choices=["celerity", "slope", "default"],
                        default="celerity",
                        help="Method for estimating k")
    parser.add_argument("--default_celerity", type=float, default=1.0,
                        help="Default wave celerity in m/s (default: 1.0)")
    parser.add_argument("--default_x", type=float, default=0.1,
                        help="Default x weighting (default: 0.1)")
    parser.add_argument("--dt_r", type=float, default=900,
                        help="Routing sub-step ZS_dtR in seconds (default: 900)")
    parser.add_argument("--output_k", required=True, help="Output k CSV path")
    parser.add_argument("--output_x", required=True, help="Output x CSV path")
    args = parser.parse_args()

    validate_inputs(args)
    process(args)


if __name__ == "__main__":
    main()
