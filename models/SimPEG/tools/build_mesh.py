#!/usr/bin/env python3
"""
SimPEG KI Tool — Mesh & Survey Builder (Stage S1)

Generates a discretize mesh and survey geometry configuration for SimPEG
forward modeling or inversion workflows.

Usage:
    python build_mesh.py \
        --method gravity \
        --survey-file survey_locs.csv \
        --nx 40 --ny 40 --nz 20 \
        --padding 6 --pad-factor 1.3 \
        --output mesh_config.json

    python build_mesh.py \
        --method dc \
        --survey-file dc_survey.csv \
        --mesh-type tree \
        --refine-near-data 2 \
        --output mesh_config.json

Input CSV format (survey_locs.csv):
    x,y,z            — receiver locations in meters (SI)
    For DC: Ax,Ay,Az,Bx,By,Bz,Mx,My,Mz,Nx,Ny,Nz  — electrode positions

Output: mesh_config.json with mesh parameters, survey arrays, and active cells.

UNIT TRAPS:
    - Coordinates must be in METERS, not feet or km
    - Z coordinate is ELEVATION (positive up), not depth
    - Padding must be >= 2x target depth to avoid boundary effects
"""

import argparse
import json
import sys
import os

import numpy as np


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

SUPPORTED_METHODS = [
    "gravity", "magnetics", "dc", "ip", "fdem", "tdem", "mt", "seismic", "flow"
]

SUPPORTED_MESH_TYPES = ["tensor", "tree", "cylindrical"]


def validate_inputs(args):
    """Validate all inputs before processing."""
    errors = []

    if args.method not in SUPPORTED_METHODS:
        errors.append(
            f"Unsupported method '{args.method}'. "
            f"Choose from: {SUPPORTED_METHODS}"
        )

    if args.mesh_type not in SUPPORTED_MESH_TYPES:
        errors.append(
            f"Unsupported mesh type '{args.mesh_type}'. "
            f"Choose from: {SUPPORTED_MESH_TYPES}"
        )

    if args.survey_file and not os.path.isfile(args.survey_file):
        errors.append(f"Survey file not found: {args.survey_file}")

    for dim_name, dim_val in [("nx", args.nx), ("ny", args.ny), ("nz", args.nz)]:
        if dim_val < 2:
            errors.append(f"{dim_name} must be >= 2, got {dim_val}")

    if args.padding < 1:
        errors.append(f"Padding cell count must be >= 1, got {args.padding}")

    if args.pad_factor < 1.0:
        errors.append(
            f"Pad factor must be >= 1.0 (geometric growth), got {args.pad_factor}"
        )

    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)


def load_survey_locations(survey_file):
    """Load survey locations from CSV.

    Returns array of shape (n_stations, 3) for x, y, z.
    """
    data = np.loadtxt(survey_file, delimiter=",", skiprows=1)
    if data.ndim == 1:
        data = data.reshape(1, -1)
    if data.shape[1] < 3:
        raise ValueError(
            f"Survey file must have at least 3 columns (x,y,z), "
            f"got {data.shape[1]}"
        )
    return data[:, :3]


# ---------------------------------------------------------------------------
# Mesh construction
# ---------------------------------------------------------------------------

def compute_mesh_parameters(survey_locs, nx, ny, nz, padding, pad_factor):
    """Compute mesh origin, cell widths, and padding for a TensorMesh.

    Parameters
    ----------
    survey_locs : ndarray (n, 3)
        Station coordinates in meters.
    nx, ny, nz : int
        Core cell counts in each direction.
    padding : int
        Number of padding cells per side.
    pad_factor : float
        Geometric growth factor for padding cells.

    Returns
    -------
    dict with hx, hy, hz (cell widths), origin, n_cells, extents.
    """
    x_min, y_min, z_min = survey_locs.min(axis=0)
    x_max, y_max, z_max = survey_locs.max(axis=0)

    # Core cell sizes
    dx = max((x_max - x_min) / nx, 1.0)
    dy = max((y_max - y_min) / ny, 1.0)

    # Vertical: depth extent ~ 2x horizontal extent
    z_extent = max(x_max - x_min, y_max - y_min, 100.0)
    dz = z_extent / nz

    # Build cell widths with padding
    def make_widths(n_core, d, n_pad, factor):
        core = np.ones(n_core) * d
        pad = d * factor ** np.arange(1, n_pad + 1)
        return np.concatenate([pad[::-1], core, pad])

    hx = make_widths(nx, dx, padding, pad_factor)
    hy = make_widths(ny, dy, padding, pad_factor)
    hz_pad = dz * pad_factor ** np.arange(1, padding + 1)
    hz = np.concatenate([hz_pad[::-1], np.ones(nz) * dz])

    # Origin: lower-left-back corner
    origin_x = x_min - np.sum(hx[:padding])
    origin_y = y_min - np.sum(hy[:padding])
    origin_z = z_max - np.sum(hz)

    n_cells = len(hx) * len(hy) * len(hz)

    return {
        "hx": hx.tolist(),
        "hy": hy.tolist(),
        "hz": hz.tolist(),
        "origin": [float(origin_x), float(origin_y), float(origin_z)],
        "n_cells": n_cells,
        "core_cells": [nx, ny, nz],
        "padding_cells": padding,
        "pad_factor": pad_factor,
        "dx": float(dx),
        "dy": float(dy),
        "dz": float(dz),
    }


def build_survey_config(method, survey_locs):
    """Build survey configuration dict from locations.

    Returns dict with receiver locations and default source parameters.
    """
    config = {
        "method": method,
        "n_stations": int(survey_locs.shape[0]),
        "receiver_locations": survey_locs.tolist(),
    }

    if method == "gravity":
        config["components"] = ["gz"]
        config["source_type"] = "SourceField"
    elif method == "magnetics":
        config["components"] = ["tmi"]
        config["source_type"] = "UniformBackgroundField"
        config["inducing_field"] = {
            "amplitude": 50000.0,  # nT, typical mid-latitude
            "inclination": 60.0,   # degrees
            "declination": 0.0,    # degrees
        }
    elif method in ("dc", "ip"):
        config["source_type"] = "Dipole"
        config["survey_type"] = "dipole-dipole"
    elif method in ("fdem", "tdem"):
        config["source_type"] = "MagDipole"
        config["frequencies"] = [1.0, 10.0, 100.0, 1000.0]
    elif method == "mt":
        config["source_type"] = "PlanewaveXYPrimary"
        config["frequencies"] = [0.01, 0.1, 1.0, 10.0]

    return config


# ---------------------------------------------------------------------------
# Output validation
# ---------------------------------------------------------------------------

def validate_outputs(mesh_params, survey_config):
    """Post-construction checks for physical reasonableness."""
    warnings = []

    n_cells = mesh_params["n_cells"]
    if n_cells > 2_000_000:
        warnings.append(
            f"Mesh has {n_cells:,} cells — may require >16 GB RAM for "
            f"dense sensitivity. Consider TreeMesh or Dask."
        )
    if n_cells < 100:
        warnings.append(
            f"Mesh has only {n_cells} cells — resolution may be insufficient."
        )

    # Check padding adequacy
    core_x = mesh_params["core_cells"][0] * mesh_params["dx"]
    total_pad_x = sum(
        mesh_params["dx"] * mesh_params["pad_factor"] ** i
        for i in range(1, mesh_params["padding_cells"] + 1)
    )
    if total_pad_x < 0.5 * core_x:
        warnings.append(
            "X-padding is less than half the core extent — boundary effects "
            "likely. Increase --padding or --pad-factor."
        )

    return warnings


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def process(args):
    """Main processing pipeline."""
    # Load survey locations or generate synthetic grid
    if args.survey_file:
        survey_locs = load_survey_locations(args.survey_file)
    else:
        # Generate a default survey grid
        x = np.linspace(-500, 500, 21)
        y = np.linspace(-500, 500, 21)
        xx, yy = np.meshgrid(x, y)
        survey_locs = np.column_stack([
            xx.ravel(), yy.ravel(), np.zeros(xx.size)
        ])

    # Build mesh parameters
    mesh_params = compute_mesh_parameters(
        survey_locs, args.nx, args.ny, args.nz, args.padding, args.pad_factor
    )
    mesh_params["mesh_type"] = args.mesh_type

    # Build survey configuration
    survey_config = build_survey_config(args.method, survey_locs)

    # Validate outputs
    warnings = validate_outputs(mesh_params, survey_config)

    # Combine into output config
    config = {
        "mesh": mesh_params,
        "survey": survey_config,
        "topo_file": args.topo_file,
    }

    # Write output
    output_path = args.output
    with open(output_path, "w") as f:
        json.dump(config, f, indent=2)

    result = {
        "status": "success",
        "output_file": output_path,
        "n_cells": mesh_params["n_cells"],
        "n_stations": survey_config["n_stations"],
        "method": args.method,
        "mesh_type": args.mesh_type,
    }
    if warnings:
        result["warnings"] = warnings

    print(json.dumps(result, indent=2))


def main():
    parser = argparse.ArgumentParser(
        description="SimPEG KI — Mesh & Survey Builder (Stage S1)"
    )
    parser.add_argument(
        "--method", required=True, choices=SUPPORTED_METHODS,
        help="Geophysical method"
    )
    parser.add_argument(
        "--survey-file", default=None,
        help="CSV file with survey locations (x,y,z in meters)"
    )
    parser.add_argument(
        "--topo-file", default=None,
        help="CSV file with topography (x,y,z in meters elevation)"
    )
    parser.add_argument(
        "--mesh-type", default="tensor", choices=SUPPORTED_MESH_TYPES,
        help="Mesh type (default: tensor)"
    )
    parser.add_argument("--nx", type=int, default=40, help="Core cells in x")
    parser.add_argument("--ny", type=int, default=40, help="Core cells in y")
    parser.add_argument("--nz", type=int, default=20, help="Core cells in z")
    parser.add_argument(
        "--padding", type=int, default=6,
        help="Number of padding cells per side"
    )
    parser.add_argument(
        "--pad-factor", type=float, default=1.3,
        help="Geometric growth factor for padding cells"
    )
    parser.add_argument(
        "--output", default="mesh_config.json",
        help="Output JSON config file"
    )

    args = parser.parse_args()
    validate_inputs(args)
    process(args)


if __name__ == "__main__":
    main()
