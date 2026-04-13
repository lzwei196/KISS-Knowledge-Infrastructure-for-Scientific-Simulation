#!/usr/bin/env python3
"""
build_morphometry.py — Generate GLM bathymetry (depth-area hypsographic curve).

Constructs the morphometry block for glm3.nml from HydroLAKES attributes or
user-provided bathymetry data. Supports three methods:
  1. Conical approximation: A(z) = A_surface * (z/z_max)^p  (default p=2)
  2. Trapezoidal: A(z) = A_surface * (a + (1-a) * z/z_max)^2
  3. Custom: User provides H[] and A[] arrays directly

CRITICAL: GLM requires H[] in ascending order (bottom to top) and A[] must
correspond to each H level. The crest_elev must equal the maximum H value.

Usage:
    python build_morphometry.py --from_hydrolakes morphometry_lookup.json --output morphometry.json
    python build_morphometry.py --area_km2 0.64 --depth_avg 6.1 --depth_max 18.3 \
        --elevation 320 --lat 46.0 --lon -89.7 --name "Sparkling" --output morphometry.json
    python build_morphometry.py --H "301,305,310,315,320" --A "0,50000,200000,450000,637000" \
        --lat 46.0 --lon -89.7 --name "CustomLake" --output morphometry.json
"""

import argparse
import json
import math
import os
import sys

import numpy as np


def validate_inputs(args):
    """Validate input arguments."""
    errors = []

    has_hydrolakes = args.from_hydrolakes is not None
    has_manual = args.area_km2 is not None and args.depth_max is not None
    has_custom = args.H is not None and args.A is not None

    if not (has_hydrolakes or has_manual or has_custom):
        errors.append(
            "Must provide one of: --from_hydrolakes <json>, "
            "--area_km2 + --depth_max, or --H + --A arrays"
        )

    if has_manual:
        if args.area_km2 <= 0:
            errors.append(f"--area_km2 must be positive, got {args.area_km2}")
        if args.depth_max <= 0:
            errors.append(f"--depth_max must be positive, got {args.depth_max}")
        if args.elevation is None:
            errors.append("--elevation is required for manual mode")

    if has_custom:
        h_vals = [float(x) for x in args.H.split(',')]
        a_vals = [float(x) for x in args.A.split(',')]
        if len(h_vals) != len(a_vals):
            errors.append(
                f"H and A arrays must have same length: "
                f"H has {len(h_vals)}, A has {len(a_vals)}"
            )
        if len(h_vals) < 3:
            errors.append("H and A arrays must have at least 3 points")

    if args.num_levels < 3:
        errors.append(f"--num_levels must be >= 3, got {args.num_levels}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)


def build_conical(area_km2, depth_max, elevation, num_levels, shape_param=2.0):
    """
    Build hypsographic curve using conical/power-law approximation.
    A(z) = A_surface * (z / z_max)^p where z is height from bottom.
    p=2 gives a cone, p=1 gives a cylinder, p=3 gives a steep-sided bowl.
    """
    area_m2 = area_km2 * 1e6
    bottom_elev = elevation - depth_max
    H = np.linspace(bottom_elev, elevation, num_levels)
    z_from_bottom = H - bottom_elev
    A = area_m2 * (z_from_bottom / depth_max) ** shape_param

    # Ensure bottom area is 0 and top area equals surface area
    A[0] = 0.0
    A[-1] = area_m2

    return H.tolist(), A.tolist()


def build_trapezoidal(area_km2, depth_max, elevation, num_levels,
                      bottom_fraction=0.1):
    """
    Build hypsographic curve with a flat bottom (trapezoidal cross-section).
    bottom_fraction is A_bottom / A_surface.
    """
    area_m2 = area_km2 * 1e6
    bottom_elev = elevation - depth_max
    H = np.linspace(bottom_elev, elevation, num_levels)
    z_norm = (H - bottom_elev) / depth_max
    a = bottom_fraction
    A = area_m2 * (a + (1 - a) * z_norm) ** 2

    A[0] = area_m2 * a ** 2
    A[-1] = area_m2

    return H.tolist(), A.tolist()


def estimate_bsn_dimensions(area_km2, shore_len_km=None, shore_dev=None):
    """
    Estimate bsn_len and bsn_wid from lake area.
    If shore_dev (shoreline development ratio) is available, use it
    to adjust the aspect ratio. Otherwise assume circular.
    """
    area_m2 = area_km2 * 1e6

    if shore_dev and shore_dev > 1.0:
        # Higher shore_dev means more elongated
        aspect = max(1.0, shore_dev)
        bsn_wid = math.sqrt(area_m2 / aspect)
        bsn_len = area_m2 / bsn_wid
    else:
        # Assume square-ish
        bsn_len = math.sqrt(area_m2)
        bsn_wid = bsn_len

    return round(bsn_len, 1), round(bsn_wid, 1)


def compute_volume(H, A):
    """Compute lake volume using trapezoidal integration of A(H)."""
    vol = 0.0
    for i in range(1, len(H)):
        dh = H[i] - H[i - 1]
        avg_a = (A[i] + A[i - 1]) / 2.0
        vol += dh * avg_a
    return vol


def process(args):
    """Build morphometry from inputs."""
    name = args.name or "GLM_Lake"
    lat = args.lat or 0.0
    lon = args.lon or 0.0

    if args.from_hydrolakes:
        # Load from HydroLAKES lookup JSON
        with open(args.from_hydrolakes) as f:
            data = json.load(f)

        if "lakes" in data and len(data["lakes"]) > 0:
            lake = data["lakes"][0]  # Use first match
        elif "lake_area_km2" in data:
            lake = data
        else:
            print(json.dumps({"status": "error",
                              "errors": ["Invalid HydroLAKES JSON format"]}))
            sys.exit(1)

        area_km2 = lake.get("lake_area_km2", 1.0)
        depth_avg = lake.get("depth_avg_m", 5.0)
        depth_max = lake.get("depth_max_est_m", depth_avg * 2.5)
        elevation = lake.get("elevation_m", 100.0)
        lat = lake.get("latitude", lat)
        lon = lake.get("longitude", lon)
        name = lake.get("lake_name", name)
        shore_dev = lake.get("shore_dev", None)
        vol_ref = lake.get("vol_total_mcm", None)

        if args.depth_max is not None:
            depth_max = args.depth_max
        if args.elevation is not None:
            elevation = args.elevation

    elif args.H and args.A:
        # Custom H/A arrays
        H = [float(x) for x in args.H.split(',')]
        A = [float(x) for x in args.A.split(',')]

        # Validate monotonicity
        for i in range(1, len(H)):
            if H[i] <= H[i - 1]:
                print(json.dumps({"status": "error",
                                  "errors": [f"H must be monotonically increasing: "
                                             f"H[{i-1}]={H[i-1]}, H[{i}]={H[i]}"]}))
                sys.exit(1)

        elevation = H[-1]
        depth_max = H[-1] - H[0]
        area_km2 = A[-1] / 1e6
        shore_dev = None
        vol_ref = None

        bsn_len, bsn_wid = estimate_bsn_dimensions(area_km2)
        volume_m3 = compute_volume(H, A)

        result = {
            "status": "success",
            "lake_name": name,
            "latitude": lat,
            "longitude": lon,
            "bsn_len": bsn_len,
            "bsn_wid": bsn_wid,
            "crest_elev": elevation,
            "bsn_vals": len(H),
            "H": [round(h, 3) for h in H],
            "A": [round(a, 1) for a in A],
            "depth_max_m": round(depth_max, 2),
            "surface_area_km2": round(area_km2, 4),
            "volume_mcm": round(volume_m3 / 1e6, 3),
            "method": "custom",
        }
        return result

    else:
        # Manual mode
        area_km2 = args.area_km2
        depth_max = args.depth_max
        depth_avg = args.depth_avg or depth_max / 2.5
        elevation = args.elevation
        shore_dev = None
        vol_ref = None

    # Determine shape parameter from depth ratio
    if depth_avg and depth_avg > 0 and depth_max > 0:
        ratio = depth_avg / depth_max
        # For conical: V = A_s * d_max / (p+1), so depth_avg = d_max / (p+1)
        # Therefore p = d_max / depth_avg - 1
        shape_p = max(1.0, min(4.0, depth_max / depth_avg - 1.0))
    else:
        shape_p = 2.0

    # Choose method based on lake type
    if args.method == "trapezoidal":
        H, A = build_trapezoidal(area_km2, depth_max, elevation,
                                 args.num_levels, args.bottom_fraction)
    else:
        H, A = build_conical(area_km2, depth_max, elevation,
                             args.num_levels, shape_p)

    bsn_len, bsn_wid = estimate_bsn_dimensions(area_km2, shore_dev=shore_dev)
    volume_m3 = compute_volume(H, A)

    result = {
        "status": "success",
        "lake_name": name,
        "latitude": lat,
        "longitude": lon,
        "bsn_len": bsn_len,
        "bsn_wid": bsn_wid,
        "crest_elev": elevation,
        "bsn_vals": len(H),
        "H": [round(h, 3) for h in H],
        "A": [round(a, 1) for a in A],
        "depth_max_m": round(depth_max, 2),
        "depth_avg_m": round(depth_avg, 2) if depth_avg else None,
        "surface_area_km2": round(area_km2, 4),
        "volume_mcm": round(volume_m3 / 1e6, 3),
        "shape_parameter": round(shape_p, 2),
        "method": args.method,
    }

    if vol_ref:
        result["vol_reference_mcm"] = vol_ref
        result["vol_error_pct"] = round(
            abs(volume_m3 / 1e6 - vol_ref) / vol_ref * 100, 1)

    return result


def validate_outputs(result):
    """Validate morphometry output."""
    if result["status"] != "success":
        return result

    H = result["H"]
    A = result["A"]

    # Check monotonicity
    for i in range(1, len(H)):
        if H[i] <= H[i - 1]:
            result["warnings"] = result.get("warnings", [])
            result["warnings"].append(
                f"H is not monotonically increasing at index {i}")
        if A[i] < A[i - 1]:
            result["warnings"] = result.get("warnings", [])
            result["warnings"].append(
                f"A is not monotonically increasing at index {i}")

    # Check crest_elev matches max H
    if abs(result["crest_elev"] - H[-1]) > 0.01:
        result["warnings"] = result.get("warnings", [])
        result["warnings"].append(
            f"crest_elev ({result['crest_elev']}) does not match max H ({H[-1]})")

    # Check bsn_vals matches array length
    if result["bsn_vals"] != len(H):
        result["warnings"] = result.get("warnings", [])
        result["warnings"].append(
            f"bsn_vals ({result['bsn_vals']}) does not match H length ({len(H)})")

    # Check bottom area is 0 (for non-custom methods)
    if result.get("method") != "trapezoidal" and A[0] > 1.0:
        result["warnings"] = result.get("warnings", [])
        result["warnings"].append(
            f"Bottom area should be ~0 for conical lakes, got {A[0]}")

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Generate GLM morphometry (depth-area hypsographic curve)")
    parser.add_argument("--from_hydrolakes", type=str,
                        help="JSON file from lookup_hydrolakes.py")
    parser.add_argument("--area_km2", type=float,
                        help="Lake surface area in km^2")
    parser.add_argument("--depth_avg", type=float,
                        help="Average depth in meters")
    parser.add_argument("--depth_max", type=float,
                        help="Maximum depth in meters")
    parser.add_argument("--elevation", type=float,
                        help="Lake surface elevation (m ASL)")
    parser.add_argument("--lat", type=float, help="Lake latitude")
    parser.add_argument("--lon", type=float, help="Lake longitude")
    parser.add_argument("--name", type=str, help="Lake name")
    parser.add_argument("--H", type=str,
                        help="Custom elevation array (comma-separated, m ASL)")
    parser.add_argument("--A", type=str,
                        help="Custom area array (comma-separated, m^2)")
    parser.add_argument("--method", type=str, default="conical",
                        choices=["conical", "trapezoidal"],
                        help="Shape approximation method (default: conical)")
    parser.add_argument("--num_levels", type=int, default=15,
                        help="Number of depth levels (default: 15)")
    parser.add_argument("--bottom_fraction", type=float, default=0.1,
                        help="Bottom/surface area ratio for trapezoidal (default: 0.1)")
    parser.add_argument("--output", type=str,
                        help="Output JSON file path (default: stdout)")

    args = parser.parse_args()
    validate_inputs(args)
    result = process(args)
    result = validate_outputs(result)

    output_json = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        os.makedirs(os.path.dirname(args.output) or '.', exist_ok=True)
        with open(args.output, 'w') as f:
            f.write(output_json)
        print(f"Morphometry written to {args.output}", file=sys.stderr)
    else:
        print(output_json)


if __name__ == "__main__":
    main()
