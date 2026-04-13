#!/usr/bin/env python3
"""
set_hydraulic_params.py — Set CE-QUAL-W2 hydraulic and thermal parameters.

Auto-estimates from reservoir characteristics when values not provided.

Key parameters:
  AX:   Longitudinal eddy viscosity (0.1-10 m^2/s). Higher for wider reservoirs.
  DX:   Longitudinal dispersion (0.1-100 m^2/s). Scale with length.
  CHEZY/MANNING: Friction. Manning 0.02-0.05.
  WSC:  Wind sheltering (0.5-1.0). Lower for sheltered valleys.
  CBHE: Bottom heat exchange (0.3-1.5 W/m^2/C).
  TSED: Sediment temperature (5-15 C). Approximate = annual mean air temp.
  BETA: Fraction of SW absorbed at surface (0.3-0.6).
  EXH2O: Light extinction (0.1-1.0 m^-1). ≈ 1.7/Secchi_depth.

Usage:
    python set_hydraulic_params.py \
        --grid_json /path/to/reservoir_grid.json \
        --annual_mean_temp 12.5 \
        --output hydraulic_params.json
"""

import argparse
import json
import os
import sys

import numpy as np


def process(args):
    """Main processing."""
    with open(args.grid_json) as f:
        grid = json.load(f)

    length_km = grid.get("reservoir_length_km", 10)
    max_depth = grid.get("max_depth_m", 20)
    area_km2 = grid.get("surface_area_km2", 10)
    avg_width = (area_km2 * 1e6) / (length_km * 1000) if length_km > 0 else 500

    # Auto-estimation of hydraulic parameters
    # AX: eddy viscosity scales with reservoir width
    ax = args.ax if args.ax else np.clip(avg_width / 500.0, 0.1, 10.0)

    # DX: dispersion scales with length
    dx = args.dx if args.dx else np.clip(length_km * 0.1, 0.1, 100.0)

    # Manning's n
    manning_n = args.manning_n if args.manning_n else 0.035

    # Wind sheltering: sheltered = smaller valley
    wsc = args.wsc if args.wsc else np.clip(0.6 + avg_width / 5000, 0.5, 1.0)

    # Bottom heat exchange
    cbhe = args.cbhe if args.cbhe else 0.3

    # Sediment temperature ≈ annual mean air temperature
    tsed = args.tsed if args.tsed else (args.annual_mean_temp if args.annual_mean_temp else 10.0)

    # Light extinction
    exh2o = args.exh2o if args.exh2o else 0.45

    # Beta (fraction of SW at surface)
    beta = args.beta if args.beta else 0.45

    params = {
        "AX": round(float(ax), 2),
        "DX": round(float(dx), 2),
        "manning_n": round(float(manning_n), 3),
        "WSC": round(float(wsc), 2),
        "CBHE": round(float(cbhe), 2),
        "TSED": round(float(tsed), 1),
        "EXH2O": round(float(exh2o), 3),
        "BETA": round(float(beta), 3),
        "estimation_basis": {
            "reservoir_length_km": round(length_km, 1),
            "max_depth_m": round(max_depth, 1),
            "avg_width_m": round(float(avg_width), 0),
            "surface_area_km2": round(area_km2, 1),
        }
    }

    output_path = args.output
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(params, f, indent=2)

    result = {"status": "success", "output_file": output_path, **params}
    print(json.dumps(result, indent=2))
    return 0


def main():
    parser = argparse.ArgumentParser(description="Set CE-QUAL-W2 hydraulic parameters")
    parser.add_argument("--grid_json", required=True)
    parser.add_argument("--annual_mean_temp", type=float, help="Annual mean air temp (C)")
    parser.add_argument("--ax", type=float, help="Eddy viscosity")
    parser.add_argument("--dx", type=float, help="Dispersion")
    parser.add_argument("--manning_n", type=float, help="Manning's n")
    parser.add_argument("--wsc", type=float, help="Wind sheltering coefficient")
    parser.add_argument("--cbhe", type=float, help="Bottom heat exchange")
    parser.add_argument("--tsed", type=float, help="Sediment temperature")
    parser.add_argument("--exh2o", type=float, help="Light extinction")
    parser.add_argument("--beta", type=float, help="Surface SW absorption fraction")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    sys.exit(process(args))


if __name__ == "__main__":
    main()
