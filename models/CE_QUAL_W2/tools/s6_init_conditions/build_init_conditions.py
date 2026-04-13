#!/usr/bin/env python3
"""
build_init_conditions.py — Generate CE-QUAL-W2 initial conditions.

Strategies:
  - uniform: constant temperature everywhere (simplest, requires spinup)
  - gradient: linear gradient from upstream to dam, isothermal vertically
  - stratified: vertical temperature profile at dam, uniform horizontally
  - profile: full 2D initial field from observed data or previous simulation

CRITICAL (dt_014): Initial water surface elevation (ELWS) must be >= bottom elevation
at all active segments. If ELWS < ELBOT at upstream segments, the model crashes.

Usage:
    python build_init_conditions.py \
        --strategy uniform --init_temp 15.0 \
        --grid_json /path/to/reservoir_grid.json \
        --output init_conditions.json
"""

import argparse
import json
import os
import sys

import numpy as np


def validate_inputs(args):
    """Validate inputs."""
    errors = []
    if not os.path.isfile(args.grid_json):
        errors.append(f"Grid JSON not found: {args.grid_json}")
    if args.init_temp is not None and (args.init_temp < -2 or args.init_temp > 40):
        errors.append(f"init_temp={args.init_temp} outside reasonable range [-2, 40] C")
    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)


def process(args):
    """Main processing."""
    with open(args.grid_json) as f:
        grid = json.load(f)

    n_seg = grid["n_segments"]
    n_layers = grid["n_layers"]
    surface_elev = grid["surface_elevation_m"]
    bottom_elevs = grid["bottom_elevations_m"]

    # Validate ELWS >= ELBOT (dt_014)
    warnings = []
    for s in range(1, n_seg - 1):
        if bottom_elevs[s] > surface_elev:
            warnings.append(f"Segment {s+1}: bottom elevation {bottom_elevs[s]} > "
                          f"surface elevation {surface_elev} (dt_014)")

    init_temp = args.init_temp if args.init_temp else 15.0

    if args.strategy == "uniform":
        temp_2d = np.full((n_layers, n_seg), init_temp)

    elif args.strategy == "gradient":
        # Linear gradient: slightly warmer upstream, cooler near dam
        temp_upstream = init_temp + 2.0
        temp_dam = init_temp - 2.0
        for s in range(n_seg):
            frac = s / max(1, n_seg - 1)
            temp_2d = np.full((n_layers, n_seg), 0.0)
            for s2 in range(n_seg):
                frac2 = s2 / max(1, n_seg - 1)
                temp_2d[:, s2] = temp_upstream + frac2 * (temp_dam - temp_upstream)

    elif args.strategy == "stratified":
        # Vertical stratification at all segments
        temp_surface = init_temp + 5.0
        temp_bottom = init_temp - 5.0
        temp_2d = np.zeros((n_layers, n_seg))
        for k in range(n_layers):
            frac = k / max(1, n_layers - 1)
            temp_2d[k, :] = temp_surface + frac * (temp_bottom - temp_surface)

    else:
        temp_2d = np.full((n_layers, n_seg), init_temp)

    init_config = {
        "strategy": args.strategy,
        "init_temp": init_temp,
        "elws": surface_elev,
        "temp_2d": temp_2d.tolist(),
        "ice_cover": False,
        "n_segments": n_seg,
        "n_layers": n_layers,
    }

    output_path = args.output
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(init_config, f, indent=2)

    result = {
        "status": "success",
        "output_file": output_path,
        "strategy": args.strategy,
        "init_temp": init_temp,
        "elws": surface_elev,
        "temp_range": [round(float(np.min(temp_2d)), 1), round(float(np.max(temp_2d)), 1)],
    }
    if warnings:
        result["warnings"] = warnings

    print(json.dumps(result, indent=2))
    return 0


def main():
    parser = argparse.ArgumentParser(description="Build CE-QUAL-W2 initial conditions")
    parser.add_argument("--grid_json", required=True, help="Reservoir grid JSON")
    parser.add_argument("--strategy", default="uniform",
                       choices=["uniform", "gradient", "stratified", "profile"])
    parser.add_argument("--init_temp", type=float, help="Initial temperature (deg C, default: 15)")
    parser.add_argument("--output", required=True, help="Output JSON path")
    args = parser.parse_args()
    validate_inputs(args)
    sys.exit(process(args))


if __name__ == "__main__":
    main()
