#!/usr/bin/env python3
"""
build_init_profiles.py — Generate initial temperature/salinity profiles for GLM.

Strategies:
  1. Uniform: Single temperature throughout (best for cold-start in spring/autumn)
  2. Stratified: Surface warm, bottom cold (best for summer start)
  3. Isothermal at 4C: Maximum density state (best for winter start)
  4. Custom: User provides depth-temperature pairs

CRITICAL: lake_depth must NOT exceed max morphometry depth (max(H) - min(H)).
    If it does, GLM crashes at startup. This tool auto-clips.

Usage:
    python build_init_profiles.py --strategy uniform --temp 10.0 \
        --depth 18.3 --output init_profiles.json
    python build_init_profiles.py --strategy stratified --temp_surface 22 \
        --temp_bottom 4 --depth 60 --output init_profiles.json
"""

import argparse
import json
import os
import sys

import numpy as np


def validate_inputs(args):
    """Validate inputs."""
    errors = []
    if args.depth <= 0:
        errors.append(f"--depth must be positive, got {args.depth}")
    if args.strategy == 'custom' and args.custom_depths is None:
        errors.append("--custom_depths required for custom strategy")
    if args.strategy == 'custom' and args.custom_temps is None:
        errors.append("--custom_temps required for custom strategy")
    if args.max_morph_depth and args.depth > args.max_morph_depth:
        print(f"WARNING: lake_depth ({args.depth}) exceeds morphometry "
              f"max depth ({args.max_morph_depth}). Clipping to "
              f"{args.max_morph_depth}.", file=sys.stderr)
        args.depth = args.max_morph_depth
    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)


def process(args):
    """Build initial profiles."""
    depth = args.depth

    if args.strategy == 'uniform':
        temp = args.temp or 10.0
        the_depths = [0.0, depth * 0.5, depth]
        the_temps = [temp, temp, temp]

    elif args.strategy == 'stratified':
        t_surface = args.temp_surface or 20.0
        t_bottom = args.temp_bottom or 4.0
        # Create a profile with thermocline at ~1/3 depth
        thermocline_depth = depth * 0.33
        the_depths = [0.0, thermocline_depth * 0.5, thermocline_depth,
                      thermocline_depth * 1.5, depth]
        the_temps = [
            t_surface,
            t_surface - 1.0,
            (t_surface + t_bottom) / 2.0,
            t_bottom + 1.0,
            t_bottom,
        ]

    elif args.strategy == 'isothermal':
        # Maximum density at 4C (winter/deep mixing state)
        the_depths = [0.0, depth * 0.5, depth]
        the_temps = [4.0, 4.0, 4.0]

    elif args.strategy == 'custom':
        the_depths = [float(x) for x in args.custom_depths.split(',')]
        the_temps = [float(x) for x in args.custom_temps.split(',')]
        if len(the_depths) != len(the_temps):
            print(json.dumps({"status": "error",
                              "errors": ["depths and temps must have same length"]}))
            sys.exit(1)
    else:
        the_depths = [0.0, depth * 0.5, depth]
        the_temps = [10.0, 8.0, 4.0]

    # Salinity (freshwater default)
    the_sals = [args.salinity] * len(the_depths)

    result = {
        "status": "success",
        "lake_depth": round(depth, 3),
        "num_depths": len(the_depths),
        "the_depths": [round(d, 3) for d in the_depths],
        "the_temps": [round(t, 2) for t in the_temps],
        "the_sals": [round(s, 3) for s in the_sals],
        "num_wq_vars": 0,
        "wq_names": "",
        "wq_init_vals": [],
        "strategy": args.strategy,
    }

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Generate GLM initial profiles")
    parser.add_argument("--strategy", type=str, default="uniform",
                        choices=["uniform", "stratified", "isothermal", "custom"],
                        help="Initialization strategy (default: uniform)")
    parser.add_argument("--depth", type=float, required=True,
                        help="Initial lake depth (m)")
    parser.add_argument("--temp", type=float,
                        help="Uniform temperature (degC, for uniform strategy)")
    parser.add_argument("--temp_surface", type=float,
                        help="Surface temperature (degC, for stratified)")
    parser.add_argument("--temp_bottom", type=float,
                        help="Bottom temperature (degC, for stratified)")
    parser.add_argument("--custom_depths", type=str,
                        help="Comma-separated depths from surface (m)")
    parser.add_argument("--custom_temps", type=str,
                        help="Comma-separated temperatures (degC)")
    parser.add_argument("--salinity", type=float, default=0.0,
                        help="Salinity (psu, default: 0.0 for freshwater)")
    parser.add_argument("--max_morph_depth", type=float,
                        help="Maximum morphometry depth for validation")
    parser.add_argument("--output", type=str,
                        help="Output JSON file (default: stdout)")
    args = parser.parse_args()

    validate_inputs(args)
    result = process(args)

    output_json = json.dumps(result, indent=2)
    if args.output:
        os.makedirs(os.path.dirname(args.output) or '.', exist_ok=True)
        with open(args.output, 'w') as f:
            f.write(output_json)
        print(f"Init profiles written to {args.output}", file=sys.stderr)
    else:
        print(output_json)


if __name__ == "__main__":
    main()
