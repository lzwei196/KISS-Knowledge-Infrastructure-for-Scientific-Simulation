#!/usr/bin/env python3
"""
SimPEG KI Tool — Model & Parameter Initializer (Stage S2)

Builds the starting model vector, defines parameter maps, and sets physical
property bounds for SimPEG inversions.

Usage:
    python initialize_model.py \
        --mesh-config mesh_config.json \
        --property density \
        --background 0.0 \
        --bounds "-1.0,1.0" \
        --map-type identity \
        --output model_config.json

    python initialize_model.py \
        --mesh-config mesh_config.json \
        --property conductivity \
        --background 1e-3 \
        --bounds "1e-6,10" \
        --map-type log \
        --reference-model ref_sigma.npy \
        --output model_config.json

UNIT TRAPS:
    - Gravity: density contrast in g/cc (CGS) vs kg/m^3 (SI).
      SimPEG expects SI internally. Use --unit-system si.
    - Magnetics: susceptibility must be SI, NOT CGS (factor of 4*pi).
    - DC: use CONDUCTIVITY (S/m), not resistivity (Ohm-m).
      If your data is in resistivity, set --map-type reciprocal.
    - Always ensure background value matches the map transform.
      For log map: background = ln(sigma), NOT sigma itself.

Property reference:
    | Property       | SI Unit     | Typical background       | Notes           |
    |----------------|-------------|--------------------------|-----------------|
    | density        | kg/m^3      | 0 (contrast)             | Often g/cc input|
    | susceptibility | SI (dimless)| 0                        | CGS = SI/(4*pi) |
    | conductivity   | S/m         | 1e-3                     | σ = 1/ρ         |
    | resistivity    | Ohm-m       | 1000                     | ρ = 1/σ         |
    | velocity       | m/s         | 3000                     | Seismic P-wave  |
    | chargeability  | V/V         | 0                        | 0 to 1 range    |
"""

import argparse
import json
import os
import sys

import numpy as np


# ---------------------------------------------------------------------------
# Constants and conversions
# ---------------------------------------------------------------------------

PROPERTY_UNITS = {
    "density":        {"si": "kg/m^3",   "cgs": "g/cm^3",   "factor_to_si": 1000.0},
    "susceptibility": {"si": "SI",       "cgs": "CGS",      "factor_to_si": 4 * np.pi},
    "conductivity":   {"si": "S/m",      "cgs": None,       "factor_to_si": 1.0},
    "resistivity":    {"si": "Ohm-m",    "cgs": None,       "factor_to_si": 1.0},
    "velocity":       {"si": "m/s",      "cgs": "cm/s",     "factor_to_si": 0.01},
    "chargeability":  {"si": "V/V",      "cgs": "mV/V",     "factor_to_si": 0.001},
    "permeability":   {"si": "H/m",      "cgs": None,       "factor_to_si": 1.0},
}

MAP_TYPES = ["identity", "log", "exp", "reciprocal"]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_inputs(args):
    """Validate inputs before processing."""
    errors = []

    if not os.path.isfile(args.mesh_config):
        errors.append(f"Mesh config not found: {args.mesh_config}")

    if args.property not in PROPERTY_UNITS:
        errors.append(
            f"Unknown property '{args.property}'. "
            f"Choose from: {list(PROPERTY_UNITS.keys())}"
        )

    if args.map_type not in MAP_TYPES:
        errors.append(
            f"Unknown map type '{args.map_type}'. "
            f"Choose from: {MAP_TYPES}"
        )

    if args.bounds:
        try:
            lo, hi = [float(x) for x in args.bounds.split(",")]
            if lo >= hi:
                errors.append(f"Lower bound ({lo}) must be < upper bound ({hi})")
        except ValueError:
            errors.append(f"Bounds must be 'lo,hi' format, got: {args.bounds}")

    if args.reference_model and not os.path.isfile(args.reference_model):
        errors.append(f"Reference model file not found: {args.reference_model}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)


# ---------------------------------------------------------------------------
# Model construction
# ---------------------------------------------------------------------------

def load_mesh_config(config_path):
    """Load mesh configuration JSON."""
    with open(config_path) as f:
        return json.load(f)


def compute_active_cells(mesh_config, topo_file=None):
    """Determine which cells are active (below topography / in domain).

    In practice, this calls discretize.utils.active_from_xyz.
    Here we approximate: all cells with center z < max_topo are active.
    """
    mesh = mesh_config["mesh"]
    hx = np.array(mesh["hx"])
    hy = np.array(mesh["hy"])
    hz = np.array(mesh["hz"])
    n_cells = len(hx) * len(hy) * len(hz)

    if topo_file:
        # In production, load topography and compute active cells
        # using discretize.utils.active_from_xyz
        pass

    # Default: all cells active (no topography)
    n_active = n_cells
    active_indices = list(range(n_cells))

    return n_active, active_indices


def build_starting_model(n_active, background, map_type, unit_system, prop_name):
    """Build starting model vector with appropriate transform.

    Parameters
    ----------
    n_active : int
        Number of active cells.
    background : float
        Background physical property value in user units.
    map_type : str
        Parameter mapping ('identity', 'log', 'exp', 'reciprocal').
    unit_system : str
        'si' or 'cgs'.
    prop_name : str
        Physical property name.

    Returns
    -------
    m0 : list
        Starting model vector (as list for JSON serialization).
    background_si : float
        Background value in SI units.
    """
    # Convert to SI if needed
    factor = 1.0
    if unit_system == "cgs" and prop_name in PROPERTY_UNITS:
        factor = PROPERTY_UNITS[prop_name]["factor_to_si"]

    background_si = background * factor

    # Apply map transform to get model-space value
    if map_type == "log":
        if background_si <= 0:
            raise ValueError(
                f"Log map requires positive background, got {background_si}. "
                f"For conductivity, use a small positive value like 1e-4."
            )
        m0_val = float(np.log(background_si))
    elif map_type == "exp":
        m0_val = float(np.exp(background_si))
    elif map_type == "reciprocal":
        if background_si == 0:
            raise ValueError("Reciprocal map: background cannot be zero.")
        m0_val = float(1.0 / background_si)
    else:  # identity
        m0_val = float(background_si)

    m0 = [m0_val] * n_active

    return m0, float(background_si)


def build_map_config(map_type, n_active, n_cells, prop_name):
    """Build parameter map configuration.

    Returns a dict describing the map chain for SimPEG.
    """
    maps_chain = []

    # Active cell injection is almost always needed
    maps_chain.append({
        "type": "InjectActiveCells",
        "n_active": n_active,
        "n_cells": n_cells,
        "value_inactive": _get_air_value(prop_name, map_type),
    })

    # Property transform
    if map_type == "log":
        maps_chain.append({"type": "ExpMap", "n_params": n_active})
    elif map_type == "exp":
        maps_chain.append({"type": "LogMap", "n_params": n_active})
    elif map_type == "reciprocal":
        maps_chain.append({"type": "ReciprocalMap", "n_params": n_active})
    else:
        maps_chain.append({"type": "IdentityMap", "n_params": n_active})

    return {"chain": maps_chain}


def _get_air_value(prop_name, map_type):
    """Get the physical property value for air/inactive cells.

    TRAP: Using 0.0 for conductivity causes singular systems.
    Use a very small positive value instead.
    """
    air_values = {
        "density":        0.0,
        "susceptibility": 0.0,
        "conductivity":   1e-8,   # NOT 0 — causes singular matrix
        "resistivity":    1e8,
        "velocity":       340.0,  # Air velocity
        "chargeability":  0.0,
        "permeability":   1.2566370614e-6,  # mu_0
    }
    val = air_values.get(prop_name, 0.0)

    if map_type == "log" and val > 0:
        return float(np.log(val))
    return float(val)


# ---------------------------------------------------------------------------
# Output validation
# ---------------------------------------------------------------------------

def validate_outputs(model_config):
    """Verify model configuration is physically reasonable."""
    warnings = []

    m0 = model_config["starting_model"]
    n = len(m0)

    if n == 0:
        warnings.append("Starting model has zero active cells.")

    if n > 500_000:
        warnings.append(
            f"Model has {n:,} parameters — large inversions may need Dask "
            f"or reduced resolution."
        )

    if model_config.get("bounds"):
        lo, hi = model_config["bounds"]
        m0_val = m0[0] if m0 else 0
        if not (lo <= m0_val <= hi):
            warnings.append(
                f"Starting model value {m0_val} is outside bounds [{lo}, {hi}]. "
                f"Ensure bounds are in model space (after map transform)."
            )

    return warnings


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def process(args):
    """Main processing pipeline."""
    # Load mesh config
    mesh_config = load_mesh_config(args.mesh_config)

    # Compute active cells
    topo_file = mesh_config.get("topo_file")
    n_active, active_indices = compute_active_cells(mesh_config, topo_file)
    n_cells = mesh_config["mesh"]["n_cells"]

    # Build starting model
    m0, background_si = build_starting_model(
        n_active, args.background, args.map_type,
        args.unit_system, args.property
    )

    # Build map configuration
    map_config = build_map_config(args.map_type, n_active, n_cells, args.property)

    # Parse bounds
    bounds = None
    if args.bounds:
        lo, hi = [float(x) for x in args.bounds.split(",")]
        if args.unit_system == "cgs" and args.property in PROPERTY_UNITS:
            factor = PROPERTY_UNITS[args.property]["factor_to_si"]
            lo *= factor
            hi *= factor
        bounds = [lo, hi]

    # Load reference model if provided
    reference_model = None
    if args.reference_model:
        ref = np.load(args.reference_model)
        if len(ref) != n_active:
            print(json.dumps({
                "status": "error",
                "errors": [
                    f"Reference model length ({len(ref)}) != "
                    f"active cells ({n_active})"
                ]
            }))
            sys.exit(1)
        reference_model = ref.tolist()

    # Assemble output
    model_config = {
        "property": args.property,
        "unit_system": args.unit_system,
        "unit_si": PROPERTY_UNITS.get(args.property, {}).get("si", "unknown"),
        "map_type": args.map_type,
        "maps": map_config,
        "starting_model": m0[:5] + ["...truncated..."],  # save space
        "starting_model_file": args.output.replace(".json", "_m0.npy"),
        "background_si": background_si,
        "n_active": n_active,
        "n_cells_total": n_cells,
        "bounds": bounds,
        "reference_model": reference_model is not None,
    }

    # Save full starting model as numpy file
    m0_path = args.output.replace(".json", "_m0.npy")
    np.save(m0_path, np.array(m0))

    # Validate outputs
    model_config["starting_model"] = m0  # restore for validation
    warnings = validate_outputs(model_config)
    model_config["starting_model"] = m0[:5] + ["...truncated..."]

    # Write config
    with open(args.output, "w") as f:
        json.dump(model_config, f, indent=2)

    result = {
        "status": "success",
        "output_file": args.output,
        "m0_file": m0_path,
        "property": args.property,
        "map_type": args.map_type,
        "n_active": n_active,
        "background_si": background_si,
        "bounds": bounds,
    }
    if warnings:
        result["warnings"] = warnings

    print(json.dumps(result, indent=2))


def main():
    parser = argparse.ArgumentParser(
        description="SimPEG KI — Model & Parameter Initializer (Stage S2)"
    )
    parser.add_argument(
        "--mesh-config", required=True,
        help="Path to mesh_config.json from build_mesh.py"
    )
    parser.add_argument(
        "--property", required=True,
        choices=list(PROPERTY_UNITS.keys()),
        help="Physical property to invert for"
    )
    parser.add_argument(
        "--background", type=float, required=True,
        help="Background physical property value"
    )
    parser.add_argument(
        "--bounds", default=None,
        help="Model bounds as 'lo,hi' (in user units)"
    )
    parser.add_argument(
        "--map-type", default="identity", choices=MAP_TYPES,
        help="Parameter mapping type"
    )
    parser.add_argument(
        "--unit-system", default="si", choices=["si", "cgs"],
        help="Unit system for input values"
    )
    parser.add_argument(
        "--reference-model", default=None,
        help="Path to reference model (.npy file)"
    )
    parser.add_argument(
        "--output", default="model_config.json",
        help="Output JSON config file"
    )

    args = parser.parse_args()
    validate_inputs(args)
    process(args)


if __name__ == "__main__":
    main()
