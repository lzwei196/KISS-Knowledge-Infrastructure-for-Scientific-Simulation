#!/usr/bin/env python3
"""
setup_wflow_config.py — Generate HydroCraft-style configuration for a wflow simulation.

Creates a wflow_config.yaml that stores all user choices: basin, period, resolution,
model variant (sbm/sbm_gwf), routing method (kinematic/local_inertial), sediment toggle,
forcing dataset, and output paths.

This is the HydroCraft orchestration config, NOT the wflow TOML file (generated later
by generate_wflow_toml.py).

Usage:
    python setup_wflow_config.py \
      --basin_name chaohe --lat 40.77 --lon 116.85 \
      --start_year 2000 --end_year 2010 \
      --resolution 0.25 --forcing cmfd \
      --routing kinematic --sediment \
      --output /path/to/wflow_config.yaml
"""

import argparse
import json
import os
import sys
import yaml
from datetime import datetime
from pathlib import Path


HYDROCRAFT_ROOT = Path("/mnt/disk1/Hydrocraft_server")
JULIA_BINARY_DEFAULT = str(HYDROCRAFT_ROOT / "model" / "julia-1.10.7" / "bin" / "julia")
JULIA_ENV_DEFAULT = str(
    HYDROCRAFT_ROOT / "models" / "wflow" / "knowledge_infrastructure" / "julia"
)
WFLOW_RUNNER_DEFAULT = str(
    HYDROCRAFT_ROOT
    / "models"
    / "wflow"
    / "knowledge_infrastructure"
    / "julia"
    / "wflow_runner.jl"
)


def validate_inputs(args):
    """Validate user inputs."""
    errors = []

    if not args.basin_name:
        errors.append("--basin_name is required")
    if args.lat is None or args.lon is None:
        errors.append("--lat and --lon are required")
    if args.lat is not None and not (-90 <= args.lat <= 90):
        errors.append(f"--lat must be between -90 and 90, got {args.lat}")
    if args.lon is not None and not (-180 <= args.lon <= 180):
        errors.append(f"--lon must be between -180 and 180, got {args.lon}")
    if args.start_year >= args.end_year:
        errors.append(
            f"start_year ({args.start_year}) must be < end_year ({args.end_year})"
        )
    if args.resolution not in [0.25, 0.1]:
        errors.append(f"resolution must be 0.25 or 0.1, got {args.resolution}")
    if args.forcing not in ["cmfd", "mswx", "nasa_power"]:
        errors.append(f"forcing must be cmfd, mswx, or nasa_power, got {args.forcing}")
    if args.routing not in ["kinematic", "local_inertial"]:
        errors.append(
            f"routing must be kinematic or local_inertial, got {args.routing}"
        )

    # Forcing availability checks
    if args.forcing == "cmfd":
        if not (15 <= args.lat <= 55 and 73 <= args.lon <= 135):
            errors.append(
                "CMFD forcing only covers China (lat 15-55, lon 73-135). "
                "Use --forcing mswx for basins outside China."
            )
        if args.end_year > 2018:
            errors.append(
                "CMFD forcing only covers 1979-2018. "
                "Use --forcing mswx for years after 2018."
            )

    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


def process(args):
    """Generate the wflow configuration dictionary."""
    run_name = f"{args.basin_name}_{args.start_year}_{args.end_year}_{args.resolution}deg_wflow"
    output_base = HYDROCRAFT_ROOT / "outputs" / run_name

    config = {
        "package": "hydrocraft-wflow",
        "version": "1.0.0",
        "created": datetime.now().isoformat(),
        "basin": {
            "name": args.basin_name,
            "lat": args.lat,
            "lon": args.lon,
            "shapefile": args.shapefile or "",
        },
        "simulation": {
            "start_year": args.start_year,
            "end_year": args.end_year,
            "resolution": args.resolution,
            "timestep_seconds": 86400,  # daily
        },
        "model": {
            "variant": "sbm",  # sbm or sbm_gwf
            "routing": args.routing,
            "sediment": args.sediment,
            "glacier": args.glacier,
            "snow": True,
            "reservoirs": args.reservoirs,
        },
        "forcing": {
            "dataset": args.forcing,
            "cmfd_dir": str(HYDROCRAFT_ROOT / "data" / "forcing" / "Data_forcing_03hr_010deg"),
            "mswx_dir": "/mnt/disk3/msxw",
        },
        "paths": {
            "hydrocraft_root": str(HYDROCRAFT_ROOT),
            "output_base": str(output_base),
            "wflow_project": str(output_base / "wflow_project"),
            "staticmaps": str(output_base / "wflow_project" / "staticmaps.nc"),
            "forcing_nc": str(output_base / "wflow_project" / "forcing.nc"),
            "wflow_toml": str(output_base / "wflow_project" / "wflow_sbm.toml"),
            "output_dir": str(output_base / "wflow_output"),
            "output_grid_nc": str(output_base / "wflow_output" / "output_grid.nc"),
            "output_scalar_nc": str(output_base / "wflow_output" / "output_scalar.nc"),
        },
        "julia": {
            "binary": args.julia_binary or JULIA_BINARY_DEFAULT,
            "env": args.julia_env or JULIA_ENV_DEFAULT,
            "runner": WFLOW_RUNNER_DEFAULT,
            "threads": "auto",
        },
        "run_name": run_name,
    }

    return config


def main():
    parser = argparse.ArgumentParser(
        description="Generate HydroCraft configuration for a wflow simulation"
    )
    parser.add_argument("--basin_name", type=str, required=True)
    parser.add_argument("--lat", type=float, required=True)
    parser.add_argument("--lon", type=float, required=True)
    parser.add_argument("--start_year", type=int, required=True)
    parser.add_argument("--end_year", type=int, required=True)
    parser.add_argument("--resolution", type=float, default=0.25)
    parser.add_argument(
        "--forcing", type=str, default="cmfd", choices=["cmfd", "mswx", "nasa_power"]
    )
    parser.add_argument(
        "--routing",
        type=str,
        default="kinematic",
        choices=["kinematic", "local_inertial"],
    )
    parser.add_argument("--sediment", action="store_true", default=False)
    parser.add_argument("--glacier", action="store_true", default=False)
    parser.add_argument("--reservoirs", action="store_true", default=False)
    parser.add_argument("--shapefile", type=str, default="")
    parser.add_argument("--julia_binary", type=str, default="")
    parser.add_argument("--julia_env", type=str, default="")
    parser.add_argument(
        "--output",
        type=str,
        default="",
        help="Output path for wflow_config.yaml",
    )
    args = parser.parse_args()

    validate_inputs(args)
    config = process(args)

    # Determine output path
    if args.output:
        out_path = Path(args.output)
    else:
        out_path = Path(config["paths"]["output_base"]) / "wflow_config.yaml"

    os.makedirs(out_path.parent, exist_ok=True)

    with open(out_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    print(json.dumps({"status": "success", "config_path": str(out_path)}, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
