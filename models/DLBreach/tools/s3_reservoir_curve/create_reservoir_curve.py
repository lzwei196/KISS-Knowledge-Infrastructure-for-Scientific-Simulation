#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
==========================================
Tool ID:      create_reservoir_curve
Stage:        s3_reservoir_curve
Description:  Generate DLBreach Upstream_Reservoir card from V-z data,
              GRanD database lookup, or power-law parameters.

              DLBreach supports 5 methods:
                0: Tabulated V-z pairs (volume vs elevation)
                1: Tabulated As-z pairs (surface area vs elevation)
                2: Power law from known V_H, A_H, H
                3: Power law from known V_H, H, m (exponent)
                4: Power law from known A_H, H, m (exponent)

              For HydroCraft coupling, reservoir data can come from:
                - User-provided V-z or As-z tables
                - GRanD global dam database (storage capacity + surface area + height)
                - Estimated from dam height using empirical relationships

Inputs:
  --method:     Reservoir curve method (0-4)
  --vz_file:    CSV file with z,V columns (for method 0)
  --asz_file:   CSV file with z,As columns (for method 1)
  --volume_m3:  Reservoir storage volume at normal pool (for methods 2,3)
  --area_m2:    Reservoir surface area at normal pool (for methods 2,4)
  --dam_height: Dam/embankment height in meters (for methods 2,3,4)
  --exponent:   Power-law exponent m (for methods 3,4; default 2.0)
  --output:     Output JSON path

Outputs:
  - JSON with reservoir_card (text), method, summary statistics

Exit codes:
  0 -- success
  1 -- invalid inputs
  2 -- data processing error
  3 -- output validation failed
"""

import sys
import json
import argparse
import logging
import csv
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def validate_vz_data(z_values, v_values):
    """Validate V-z or As-z data is monotonically increasing."""
    errors = []
    if len(z_values) != len(v_values):
        errors.append(f"Mismatched lengths: z has {len(z_values)}, V has {len(v_values)}")
    if len(z_values) < 2:
        errors.append("Need at least 2 data points")

    # Check monotonicity
    for i in range(1, len(z_values)):
        if z_values[i] <= z_values[i - 1]:
            errors.append(f"z values not monotonically increasing at index {i}: {z_values[i-1]} >= {z_values[i]}")
            break
    for i in range(1, len(v_values)):
        if v_values[i] < v_values[i - 1]:
            errors.append(f"V/As values not monotonically non-decreasing at index {i}: {v_values[i-1]} > {v_values[i]}")
            break

    # Check positivity
    if any(v < 0 for v in v_values):
        errors.append("V/As values must be non-negative")

    return errors


def read_csv_pairs(filepath):
    """Read z,V pairs from CSV file."""
    z_vals = []
    v_vals = []
    with open(filepath, "r") as f:
        reader = csv.reader(f)
        for i, row in enumerate(reader):
            if i == 0 and not row[0].replace(".", "").replace("-", "").isdigit():
                continue  # Skip header
            if len(row) >= 2:
                z_vals.append(float(row[0]))
                v_vals.append(float(row[1]))
    return z_vals, v_vals


def generate_method0_card(z_values, v_values):
    """Generate Upstream_Reservoir card for method 0 (tabulated V-z)."""
    n = len(z_values)
    lines = [f"Upstream_Reservoir    0, {n},"]
    for z, v in zip(z_values, v_values):
        lines.append(f"    {z:.2f}, {v:.6e}")
    return "\n".join(lines)


def generate_method1_card(z_values, as_values):
    """Generate Upstream_Reservoir card for method 1 (tabulated As-z)."""
    n = len(z_values)
    lines = [f"Upstream_Reservoir    1, {n},"]
    for z, a in zip(z_values, as_values):
        lines.append(f"    {z:.2f}, {a:.6e}")
    return "\n".join(lines)


def generate_method2_card(volume_m3, area_m2, height_m):
    """Generate Upstream_Reservoir card for method 2 (power law from V_H, A_H, H)."""
    return f"Upstream_Reservoir    2, {volume_m3:.6e}, {area_m2:.6e}, {height_m:.2f}"


def generate_method3_card(volume_m3, height_m, exponent):
    """Generate Upstream_Reservoir card for method 3 (power law from V_H, H, m)."""
    return f"Upstream_Reservoir    3, {volume_m3:.6e}, {height_m:.2f}, {exponent:.2f}"


def generate_method4_card(area_m2, height_m, exponent):
    """Generate Upstream_Reservoir card for method 4 (power law from A_H, H, m)."""
    return f"Upstream_Reservoir    4, {area_m2:.6e}, {height_m:.2f}, {exponent:.2f}"


def estimate_from_height(height_m):
    """
    Estimate reservoir volume and area from dam height using empirical relationships.
    Based on ICOLD statistics: V ~ 0.01 * H^2.5 (MCM), A ~ 0.3 * H^1.5 (km2)
    These are very rough and should be replaced with actual data when available.
    """
    volume_mcm = 0.01 * height_m ** 2.5  # million cubic meters
    area_km2 = 0.3 * height_m ** 1.5     # square kilometers
    volume_m3 = volume_mcm * 1e6
    area_m2 = area_km2 * 1e6
    return volume_m3, area_m2


def main():
    parser = argparse.ArgumentParser(description="Create DLBreach reservoir curve card")
    parser.add_argument("--method", type=int, required=True, choices=[0, 1, 2, 3, 4],
                        help="Reservoir curve method (0-4)")
    parser.add_argument("--vz_file", type=str, help="CSV with z,V columns (method 0)")
    parser.add_argument("--asz_file", type=str, help="CSV with z,As columns (method 1)")
    parser.add_argument("--volume_m3", type=float, help="Storage volume at normal pool (m3)")
    parser.add_argument("--area_m2", type=float, help="Surface area at normal pool (m2)")
    parser.add_argument("--dam_height", type=float, help="Dam height (m)")
    parser.add_argument("--exponent", type=float, default=2.0,
                        help="Power-law exponent m (methods 3,4; default 2.0)")
    parser.add_argument("--estimate_from_height", action="store_true",
                        help="Estimate V and A from dam height (rough empirical)")
    parser.add_argument("--output", type=str, help="Output JSON path")
    args = parser.parse_args()

    result = {
        "reservoir_card": None,
        "method": args.method,
        "summary": {},
        "validation_errors": [],
        "status": "error",
    }

    try:
        if args.method == 0:
            if not args.vz_file:
                result["validation_errors"].append("--vz_file required for method 0")
                print(json.dumps(result, indent=2))
                sys.exit(1)
            z_vals, v_vals = read_csv_pairs(args.vz_file)
            errors = validate_vz_data(z_vals, v_vals)
            if errors:
                result["validation_errors"] = errors
                print(json.dumps(result, indent=2))
                sys.exit(1)
            result["reservoir_card"] = generate_method0_card(z_vals, v_vals)
            result["summary"] = {
                "n_points": len(z_vals),
                "z_min": min(z_vals), "z_max": max(z_vals),
                "v_min": min(v_vals), "v_max": max(v_vals),
            }

        elif args.method == 1:
            if not args.asz_file:
                result["validation_errors"].append("--asz_file required for method 1")
                print(json.dumps(result, indent=2))
                sys.exit(1)
            z_vals, as_vals = read_csv_pairs(args.asz_file)
            errors = validate_vz_data(z_vals, as_vals)
            if errors:
                result["validation_errors"] = errors
                print(json.dumps(result, indent=2))
                sys.exit(1)
            result["reservoir_card"] = generate_method1_card(z_vals, as_vals)
            result["summary"] = {
                "n_points": len(z_vals),
                "z_min": min(z_vals), "z_max": max(z_vals),
                "as_min": min(as_vals), "as_max": max(as_vals),
            }

        elif args.method == 2:
            if args.estimate_from_height and args.dam_height:
                vol, area = estimate_from_height(args.dam_height)
                args.volume_m3 = vol
                args.area_m2 = area
                logger.warning(f"Estimated from height: V={vol:.2e} m3, A={area:.2e} m2 (ROUGH)")
            if not all([args.volume_m3, args.area_m2, args.dam_height]):
                result["validation_errors"].append("--volume_m3, --area_m2, --dam_height required for method 2")
                print(json.dumps(result, indent=2))
                sys.exit(1)
            result["reservoir_card"] = generate_method2_card(args.volume_m3, args.area_m2, args.dam_height)
            result["summary"] = {
                "volume_m3": args.volume_m3,
                "area_m2": args.area_m2,
                "dam_height_m": args.dam_height,
            }

        elif args.method == 3:
            if not all([args.volume_m3, args.dam_height]):
                result["validation_errors"].append("--volume_m3, --dam_height required for method 3")
                print(json.dumps(result, indent=2))
                sys.exit(1)
            result["reservoir_card"] = generate_method3_card(args.volume_m3, args.dam_height, args.exponent)
            result["summary"] = {
                "volume_m3": args.volume_m3,
                "dam_height_m": args.dam_height,
                "exponent": args.exponent,
            }

        elif args.method == 4:
            if not all([args.area_m2, args.dam_height]):
                result["validation_errors"].append("--area_m2, --dam_height required for method 4")
                print(json.dumps(result, indent=2))
                sys.exit(1)
            result["reservoir_card"] = generate_method4_card(args.area_m2, args.dam_height, args.exponent)
            result["summary"] = {
                "area_m2": args.area_m2,
                "dam_height_m": args.dam_height,
                "exponent": args.exponent,
            }

        result["status"] = "success"
        logger.info(f"Reservoir card generated (method {args.method})")

    except Exception as e:
        result["validation_errors"].append(str(e))
        result["status"] = "error"
        logger.error(f"Error: {e}")
        print(json.dumps(result, indent=2))
        sys.exit(2)

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(result, indent=2))

    print(json.dumps(result, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
