#!/usr/bin/env python3
"""
build_model_config.py — Generate a HydroCNHS model.yaml configuration file.

Creates a complete model configuration YAML file from basin geometry, parameter
estimates, and optional ABM specifications. The YAML file is the primary input
to hydrocnhs.Model().

CRITICAL:
  - Date format must be "YYYY/M/D" (e.g., "1981/1/1"), NOT "YYYY-MM-DD"
  - Area must be in hectares (ha), NOT km² or m²
  - FlowLength must be in meters (m), NOT km
  - DataLength must exactly equal (end_date - start_date).days + 1
  - Parameters set to -99 are marked for calibration

Usage:
    python build_model_config.py \\
        --start-date "1981/1/1" \\
        --end-date "2013/12/31" \\
        --outlets "WSLO,DLLO,TRGC" \\
        --areas "47646.85,3243.45,6783.12" \\
        --latitudes "45.35,45.40,45.32" \\
        --runoff-model GWLF \\
        --routing-outlet WSLO \\
        --upstream-outlets "DLLO,TRGC" \\
        --flow-lengths "80064.864,52341.2" \\
        --params-json /path/to/params.json \\
        --output model.yaml
"""

import argparse
import json
import os
import sys
from datetime import datetime

import yaml


def validate_inputs(args):
    """Validate all inputs before generating config."""
    errors = []

    # Date format
    for label, date_str in [("start", args.start_date), ("end", args.end_date)]:
        try:
            datetime.strptime(date_str, "%Y/%m/%d")
        except ValueError:
            errors.append(
                f"Invalid {label} date '{date_str}'. Must be YYYY/M/D format. "
                f"HydroCNHS uses '/' separators, NOT '-'."
            )

    # Outlets
    outlets = [o.strip() for o in args.outlets.split(",")]
    if len(outlets) == 0:
        errors.append("At least one outlet required")

    # Areas
    areas = [float(a) for a in args.areas.split(",")]
    if len(areas) != len(outlets):
        errors.append(f"Number of areas ({len(areas)}) must match outlets ({len(outlets)})")
    for i, a in enumerate(areas):
        if a > 1e9:  # 1e9 ha = 1e7 km^2, larger than any real river basin
            errors.append(
                f"Area for {outlets[i]}={a} ha seems too large. "
                f"Did you pass m² instead of ha? (1 ha = 10000 m²)"
            )
        if a < 0.01:
            errors.append(
                f"Area for {outlets[i]}={a} ha seems too small. "
                f"Did you pass km² instead of ha? (1 km² = 100 ha)"
            )

    # Latitudes
    lats = [float(l) for l in args.latitudes.split(",")]
    if len(lats) != len(outlets):
        errors.append(f"Number of latitudes ({len(lats)}) must match outlets ({len(outlets)})")
    for i, lat in enumerate(lats):
        if abs(lat) > 90:
            errors.append(f"Latitude for {outlets[i]}={lat} out of range [-90, 90]")

    return errors


def compute_data_length(start_str, end_str):
    """Compute number of days between start and end dates (inclusive)."""
    start = datetime.strptime(start_str, "%Y/%m/%d")
    end = datetime.strptime(end_str, "%Y/%m/%d")
    return (end - start).days + 1


def build_rainfall_runoff_section(outlets, areas, latitudes, model_type, params=None):
    """Build the RainfallRunoff section of the YAML config."""
    rr = {}
    for i, outlet in enumerate(outlets):
        entry = {
            "Inputs": {
                "Area": areas[i],
                "Latitude": latitudes[i],
                "S0": 2,       # Initial shallow saturated water [cm]
                "U0": 10,      # Initial unsaturated water [cm]
                "SnowS": 5,    # Initial snow storage [cm]
            },
            "Pars": {}
        }

        if model_type == "GWLF":
            if params and outlet in params:
                entry["Pars"] = params[outlet]
            else:
                # Default values (should be calibrated)
                entry["Pars"] = {
                    "CN2": -99, "IS": -99, "Res": -99, "Sep": -99,
                    "Alpha": -99, "Beta": -99, "Ur": -99, "Df": -99, "Kc": -99,
                }
        elif model_type == "ABCD":
            if params and outlet in params:
                entry["Pars"] = params[outlet]
            else:
                entry["Pars"] = {
                    "a": -99, "b": -99, "c": -99, "d": -99, "Df": -99,
                }

        rr[outlet] = entry
    return rr


def build_routing_section(routing_outlet, upstream_outlets, flow_lengths):
    """Build the Routing section of the YAML config."""
    if not routing_outlet or not upstream_outlets:
        return {}

    routing = {routing_outlet: {}}
    upstreams = [u.strip() for u in upstream_outlets.split(",")]
    lengths = [float(fl) for fl in flow_lengths.split(",")]

    for i, upstream in enumerate(upstreams):
        routing[routing_outlet][upstream] = {
            "Inputs": {
                "FlowLength": lengths[i],
                "InstreamControl": False,
            },
            "Pars": {
                "GShape": -99,
                "GScale": -99,
                "Velo": -99,
                "Diff": -99,
            }
        }
    return routing


def process(args):
    """Generate the model YAML configuration."""
    log = []
    outlets = [o.strip() for o in args.outlets.split(",")]
    areas = [float(a) for a in args.areas.split(",")]
    latitudes = [float(l) for l in args.latitudes.split(",")]

    data_length = compute_data_length(args.start_date, args.end_date)
    log.append(f"DataLength computed: {data_length} days")

    # Load parameters if provided
    params = None
    if args.params_json and os.path.exists(args.params_json):
        with open(args.params_json) as f:
            params_data = json.load(f)
        params = params_data.get("output", {}).get("parameters", None)
        log.append(f"Loaded parameters from {args.params_json}")

    # Build config
    config = {
        "Path": {
            "WD": args.working_dir or os.getcwd(),
            "Modules": args.modules_dir or "",
        },
        "WaterSystem": {
            "StartDate": args.start_date,
            "EndDate": args.end_date,
            "DataLength": data_length,
            "NumSubbasins": len(outlets),
            "Outlets": outlets,
            "NodeGroups": [],
            "RainfallRunoff": args.runoff_model,
            "Routing": "Lohmann",
            "ABM": {
                "Modules": [],
                "DamAPI": [],
                "RiverDivAPI": [],
                "ConveyingAPI": [],
                "InsituAPI": [],
                "DMClasses": [],
                "Institutions": {},
            }
        },
        "RainfallRunoff": build_rainfall_runoff_section(
            outlets, areas, latitudes, args.runoff_model, params
        ),
        "Routing": build_routing_section(
            args.routing_outlet, args.upstream_outlets, args.flow_lengths
        ) if args.routing_outlet else {},
        "ABM": {},
    }

    log.append(f"Config generated: {len(outlets)} outlets, model={args.runoff_model}")

    return {
        "status": "success",
        "output": {
            "config": config,
            "n_outlets": len(outlets),
            "data_length": data_length,
        },
        "log": log
    }


def main():
    parser = argparse.ArgumentParser(
        description="Generate HydroCNHS model.yaml configuration"
    )
    parser.add_argument("--start-date", required=True, help="Start date YYYY/M/D")
    parser.add_argument("--end-date", required=True, help="End date YYYY/M/D")
    parser.add_argument("--outlets", required=True, help="Comma-separated outlet names")
    parser.add_argument("--areas", required=True, help="Comma-separated areas in ha")
    parser.add_argument("--latitudes", required=True, help="Comma-separated latitudes in decimal degrees")
    parser.add_argument("--runoff-model", default="GWLF", choices=["GWLF", "ABCD"])
    parser.add_argument("--routing-outlet", default=None, help="Main routing outlet name")
    parser.add_argument("--upstream-outlets", default="", help="Comma-separated upstream outlets")
    parser.add_argument("--flow-lengths", default="", help="Comma-separated flow lengths in meters")
    parser.add_argument("--params-json", default=None, help="Parameters JSON from convert_parameters.py")
    parser.add_argument("--working-dir", default=None, help="Model working directory")
    parser.add_argument("--modules-dir", default=None, help="ABM modules directory")
    parser.add_argument("--output", default="model.yaml", help="Output YAML file path")

    args = parser.parse_args()

    errors = validate_inputs(args)
    if errors:
        print(json.dumps({"status": "error", "errors": errors}, indent=2))
        sys.exit(1)

    result = process(args)

    if result["status"] == "success" and args.output:
        with open(args.output, "w") as f:
            yaml.dump(result["output"]["config"], f, default_flow_style=False,
                      sort_keys=False)
        print(f"Model config written to {args.output}")
        for line in result["log"]:
            print(f"  {line}")
    else:
        print(json.dumps(result, indent=2))

    if result["status"] == "error":
        sys.exit(1)


if __name__ == "__main__":
    main()
