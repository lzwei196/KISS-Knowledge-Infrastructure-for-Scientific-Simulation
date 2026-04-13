#!/usr/bin/env python3
"""
adjust_parameters.py — Modify wflow parameters for calibration or regional tuning.

Two adjustment modes:
  1. TOML scale/offset: Modifies the wflow TOML file to apply scale and offset
     factors to parameters. wflow applies: actual = netcdf_value * scale + offset
  2. Direct NetCDF: Modifies parameter values directly in staticmaps.nc

Key calibration parameters for wflow_sbm:
  KsatVer     — Vertical saturated hydraulic conductivity (mm/day). Range: 10-10000
  f           — Exponential Ksat decay with depth (1/mm). Range: 0.0005-0.005
  SoilThickness — Total soil depth (mm). Range: 500-5000
  RootingDepth  — Root zone depth (mm). Range: 100-2000
  PathFrac    — Impervious/paved fraction (-). Range: 0.0-0.3
  N_River     — Manning's n for river (s/m^1/3). Range: 0.02-0.1
  InfiltCapSoil — Soil infiltration capacity (mm/day). Range: 50-500

IMPORTANT: KsatVer units are mm/day (not m/s like VIC, not m/hr like ParFlow).
Cross-model unit conversion is the #1 source of silent errors.

Usage:
    python adjust_parameters.py \
      --toml /path/to/wflow_sbm.toml \
      --param KsatVer --scale 1.5 --offset 0.0

    python adjust_parameters.py \
      --staticmaps /path/to/staticmaps.nc \
      --param KsatVer --multiply 1.5

    python adjust_parameters.py \
      --toml /path/to/wflow_sbm.toml \
      --params_json '{"KsatVer": {"scale": 1.5}, "f": {"scale": 0.8}, "SoilThickness": {"scale": 1.2}}'
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

import numpy as np


# Parameter metadata: name -> (unit, typical range, sensitivity, description)
PARAM_INFO = {
    "KsatVer": ("mm/day", (10, 10000), "high", "Vertical saturated hydraulic conductivity"),
    "f": ("1/mm", (0.0001, 0.01), "high", "Exponential Ksat decay parameter"),
    "SoilThickness": ("mm", (500, 5000), "high", "Total soil depth"),
    "RootingDepth": ("mm", (100, 2000), "medium", "Root zone depth"),
    "PathFrac": ("-", (0.0, 0.3), "medium", "Impervious/paved fraction"),
    "N_River": ("s/m^(1/3)", (0.02, 0.1), "medium", "River Manning's roughness"),
    "N": ("s/m^(1/3)", (0.02, 0.2), "low", "Overland flow Manning's roughness"),
    "InfiltCapSoil": ("mm/day", (50, 500), "medium", "Soil infiltration capacity"),
    "InfiltCapPath": ("mm/day", (1, 20), "low", "Paved area infiltration capacity"),
    "MaxLeakage": ("mm/day", (0, 10), "low", "Maximum soil leakage"),
    "c": ("-", (3, 15), "low", "Brooks-Corey coefficient"),
    "theta_s": ("-", (0.3, 0.6), "medium", "Saturated soil moisture content"),
    "theta_r": ("-", (0.01, 0.15), "low", "Residual soil moisture content"),
    "KsatHorFrac": ("-", (1, 1000), "medium", "Horizontal/vertical Ksat ratio"),
    "cfmax": ("mm/degC/day", (1, 10), "medium", "Degree-day snow melt factor"),
    "tt": ("degC", (-3, 3), "medium", "Temperature threshold for snow/rain"),
    "RiverSlope": ("-", (0.0001, 0.1), "low", "River bed slope"),
}


def validate_inputs(args):
    """Check inputs."""
    errors = []

    if args.toml and not os.path.exists(args.toml):
        errors.append(f"TOML file not found: {args.toml}")
    if args.staticmaps and not os.path.exists(args.staticmaps):
        errors.append(f"staticmaps.nc not found: {args.staticmaps}")
    if not args.toml and not args.staticmaps:
        errors.append("Must provide --toml or --staticmaps")

    # Parse params_json if provided
    if args.params_json:
        try:
            params = json.loads(args.params_json)
            for name in params:
                if name not in PARAM_INFO:
                    print(f"WARNING: Unknown parameter '{name}'. Known: {list(PARAM_INFO.keys())}",
                          file=sys.stderr)
        except json.JSONDecodeError as e:
            errors.append(f"Invalid JSON in --params_json: {e}")
    elif args.param:
        if args.param not in PARAM_INFO:
            print(f"WARNING: Unknown parameter '{args.param}'", file=sys.stderr)

    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


def adjust_toml(toml_path, param_adjustments):
    """Add or modify scale/offset entries in the wflow TOML file.

    For wflow v1.0+, parameters are referenced in the TOML as:
    [input.vertical.ksat]
    netcdf.variable.name = "KsatVer"
    scale = 1.0
    offset = 0.0
    """
    with open(toml_path) as f:
        content = f.read()

    changes_made = []

    for param_name, adj in param_adjustments.items():
        scale = adj.get("scale", 1.0)
        offset = adj.get("offset", 0.0)

        # Look for existing scale/offset for this parameter
        # Pattern: find the section containing this parameter
        param_pattern = re.compile(
            rf'(netcdf\.variable\.name\s*=\s*"{param_name}".*?)'
            rf'(scale\s*=\s*[\d.eE+-]+)',
            re.DOTALL,
        )

        if param_pattern.search(content):
            # Update existing scale
            content = param_pattern.sub(
                lambda m: m.group(1) + f"scale = {scale}", content
            )
            changes_made.append(f"{param_name}: scale={scale}")
        else:
            # Check if the parameter variable is referenced at all
            var_pattern = re.compile(
                rf'netcdf\.variable\.name\s*=\s*"{param_name}"'
            )
            if var_pattern.search(content):
                # Add scale and offset after the variable name line
                content = var_pattern.sub(
                    f'netcdf.variable.name = "{param_name}"\n'
                    f"scale = {scale}\noffset = {offset}",
                    content,
                )
                changes_made.append(f"{param_name}: scale={scale}, offset={offset}")
            else:
                changes_made.append(
                    f"{param_name}: NOT FOUND in TOML (manual edit needed)"
                )

    with open(toml_path, "w") as f:
        f.write(content)

    return changes_made


def adjust_staticmaps(nc_path, param_adjustments):
    """Modify parameter values directly in staticmaps.nc."""
    import xarray as xr

    ds = xr.open_dataset(nc_path)
    changes_made = []

    for param_name, adj in param_adjustments.items():
        if param_name not in ds:
            changes_made.append(f"{param_name}: NOT FOUND in staticmaps.nc")
            continue

        original_mean = float(ds[param_name].where(ds[param_name] != 0).mean())

        if "multiply" in adj:
            ds[param_name] = ds[param_name] * adj["multiply"]
            changes_made.append(
                f"{param_name}: multiplied by {adj['multiply']} "
                f"(mean: {original_mean:.3f} -> {float(ds[param_name].where(ds[param_name] != 0).mean()):.3f})"
            )
        elif "set_value" in adj:
            mask = ds[param_name] != 0  # only modify active cells
            ds[param_name] = ds[param_name].where(~mask, adj["set_value"])
            changes_made.append(f"{param_name}: set to {adj['set_value']}")
        elif "scale" in adj or "offset" in adj:
            scale = adj.get("scale", 1.0)
            offset = adj.get("offset", 0.0)
            ds[param_name] = ds[param_name] * scale + offset
            changes_made.append(
                f"{param_name}: scale={scale}, offset={offset}"
            )

        # Validate range
        if param_name in PARAM_INFO:
            _, (pmin, pmax), _, _ = PARAM_INFO[param_name]
            actual_mean = float(ds[param_name].where(ds[param_name] != 0).mean())
            if actual_mean < pmin or actual_mean > pmax:
                print(
                    f"WARNING: {param_name} mean ({actual_mean:.3f}) "
                    f"outside typical range ({pmin}-{pmax})",
                    file=sys.stderr,
                )

    ds.to_netcdf(nc_path)
    return changes_made


def main():
    parser = argparse.ArgumentParser(
        description="Adjust wflow parameters for calibration"
    )
    parser.add_argument("--toml", type=str, default="")
    parser.add_argument("--staticmaps", type=str, default="")
    parser.add_argument("--param", type=str, default="",
                        help="Single parameter name")
    parser.add_argument("--scale", type=float, default=1.0)
    parser.add_argument("--offset", type=float, default=0.0)
    parser.add_argument("--multiply", type=float, default=None)
    parser.add_argument("--params_json", type=str, default="",
                        help="JSON dict of {param: {scale/offset/multiply}}")
    parser.add_argument("--list_params", action="store_true",
                        help="List all known parameters and exit")
    args = parser.parse_args()

    if args.list_params:
        print("Known wflow_sbm parameters:")
        for name, (unit, (pmin, pmax), sens, desc) in PARAM_INFO.items():
            print(f"  {name:20s} [{unit:12s}] range: {pmin:10.4f} - {pmax:10.4f}  "
                  f"sensitivity: {sens:6s}  {desc}")
        sys.exit(0)

    validate_inputs(args)

    # Build adjustments dict
    if args.params_json:
        param_adjustments = json.loads(args.params_json)
    elif args.param:
        adj = {}
        if args.multiply is not None:
            adj["multiply"] = args.multiply
        else:
            adj["scale"] = args.scale
            adj["offset"] = args.offset
        param_adjustments = {args.param: adj}
    else:
        print("ERROR: Provide --param or --params_json", file=sys.stderr)
        sys.exit(1)

    # Apply adjustments
    if args.toml:
        changes = adjust_toml(args.toml, param_adjustments)
    elif args.staticmaps:
        changes = adjust_staticmaps(args.staticmaps, param_adjustments)

    result = {
        "status": "success",
        "target": args.toml or args.staticmaps,
        "changes": changes,
    }

    print(json.dumps(result, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
