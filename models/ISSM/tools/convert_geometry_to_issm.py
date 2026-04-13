#!/usr/bin/env python3
"""
convert_geometry_to_issm.py — Convert bed/surface/thickness data to ISSM mesh format.

Handles conversion of gridded geometry datasets (BedMachine, SeaRISE, BEDMAP2)
to ISSM-compatible per-vertex arrays. Enforces the critical consistency
constraint: surface = base + thickness.

CRITICAL CONSTRAINTS:
  - Thickness must be in meters (not km) (dt_003)
  - Coordinates must be in meters (projected), not degrees (dt_004)
  - surface = base + thickness MUST hold (dt_018)
  - Floating ice: base = -ρ_ice/ρ_water * thickness (hydrostatic equilibrium)
  - Grounded ice: base = bed (ice rests on bedrock)

Usage:
    python convert_geometry_to_issm.py \
        --bedmachine BedMachineGreenland-v5.nc \
        --mesh_x mesh_x.npy --mesh_y mesh_y.npy \
        --output_dir ./issm_geometry/

    python convert_geometry_to_issm.py \
        --surface surface.npy --bed bed.npy --thickness thickness.npy \
        --mesh_x mesh_x.npy --mesh_y mesh_y.npy \
        --output_dir ./issm_geometry/
"""

import argparse
import json
import os
import sys

import numpy as np

try:
    from scipy.interpolate import griddata
except ImportError:
    griddata = None

try:
    from netCDF4 import Dataset as NCDataset
except ImportError:
    NCDataset = None


# =============================================================================
# Constants
# =============================================================================
RHO_ICE = 917.0           # kg/m^3
RHO_WATER = 1023.0        # kg/m^3 (ocean water for ice sheets)
RHO_FRESHWATER = 1000.0   # kg/m^3
MIN_THICKNESS = 1.0        # m — minimum ice thickness to avoid singularities


# =============================================================================
# Validation
# =============================================================================
def validate_inputs(args):
    """Validate command-line arguments."""
    errors = []
    warnings = []

    if args.bedmachine:
        if not os.path.exists(args.bedmachine):
            errors.append(f"BedMachine file not found: {args.bedmachine}")
        if NCDataset is None:
            errors.append("netCDF4 required for BedMachine: pip install netCDF4")
    else:
        # Manual input mode — check individual files
        for name, path in [("surface", args.surface), ("bed", args.bed), ("thickness", args.thickness)]:
            if path and not os.path.exists(path):
                errors.append(f"{name} file not found: {path}")
        if not args.surface and not args.thickness:
            errors.append("Must provide at least --surface or --thickness (or --bedmachine)")

    if not os.path.exists(args.mesh_x):
        errors.append(f"Mesh x-coordinates not found: {args.mesh_x}")
    if not os.path.exists(args.mesh_y):
        errors.append(f"Mesh y-coordinates not found: {args.mesh_y}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)
    if warnings:
        for w in warnings:
            print(f"WARNING: {w}", file=sys.stderr)


def validate_outputs(surface, base, thickness, bed):
    """Validate geometric consistency of output arrays."""
    errors = []
    warnings = []

    nv = len(surface)

    # Check consistency: surface = base + thickness
    residual = np.abs(surface - (base + thickness))
    max_residual = np.max(residual)
    if max_residual > 0.01:
        errors.append(
            f"Geometry inconsistency: max |surface - (base + thickness)| = {max_residual:.4f} m (dt_018)")

    # Check for negative thickness
    if np.any(thickness < 0):
        n_neg = np.sum(thickness < 0)
        errors.append(f"Negative thickness at {n_neg} vertices (dt_003)")

    # Check for unrealistic values
    if np.max(thickness) > 5000:
        warnings.append(f"Max thickness {np.max(thickness):.0f} m — exceeds typical ice sheet values")
    if np.max(thickness) < 10:
        warnings.append(f"Max thickness only {np.max(thickness):.1f} m — may be in km (dt_003)")

    # Check coordinate scale (should be in meters, not degrees)
    mesh_x = np.load(args.mesh_x) if hasattr(args, 'mesh_x') else None
    if mesh_x is not None:
        x_range = np.max(mesh_x) - np.min(mesh_x)
        if x_range < 1000:
            warnings.append(
                f"Mesh x-range only {x_range:.1f} — may be in degrees, not meters (dt_004)")

    if errors:
        print(json.dumps({"status": "error", "errors": errors, "warnings": warnings}))
        sys.exit(1)

    return warnings


# =============================================================================
# Interpolation
# =============================================================================
def interp_grid_to_mesh(grid_x, grid_y, grid_data, mesh_x, mesh_y, method='linear'):
    """Interpolate from regular grid to unstructured mesh vertices."""
    if griddata is None:
        raise ImportError("scipy.interpolate.griddata required")

    gx, gy = np.meshgrid(grid_x, grid_y)
    points = np.column_stack([gx.ravel(), gy.ravel()])
    values = grid_data.ravel()

    valid = ~np.isnan(values)
    if np.sum(valid) == 0:
        raise ValueError("All grid values are NaN")

    result = griddata(points[valid], values[valid],
                      (mesh_x, mesh_y), method=method)

    # Fill NaNs with nearest neighbor
    nan_mask = np.isnan(result)
    if np.any(nan_mask):
        result_nn = griddata(points[valid], values[valid],
                             (mesh_x[nan_mask], mesh_y[nan_mask]), method='nearest')
        result[nan_mask] = result_nn

    return result


# =============================================================================
# Geometry computation
# =============================================================================
def compute_base_from_hydrostatic(thickness, bed, surface):
    """Compute ice base elevation enforcing hydrostatic equilibrium for floating ice.

    For grounded ice: base = bed
    For floating ice: base = -ρ_ice/ρ_water * thickness (ocean surface at 0)

    The ice is floating where bed < -ρ_ice/ρ_water * thickness (bed below flotation depth).
    """
    # Flotation criterion
    flotation_depth = -RHO_ICE / RHO_WATER * thickness
    is_floating = bed < flotation_depth

    base = np.copy(bed)
    base[is_floating] = flotation_depth[is_floating]

    return base, is_floating


def enforce_consistency(surface, base, thickness, priority="thickness"):
    """Enforce surface = base + thickness.

    Args:
        surface: ice surface elevation (m)
        base: ice base elevation (m)
        thickness: ice thickness (m)
        priority: which two fields to trust ('thickness', 'surface', 'base')

    Returns:
        Corrected (surface, base, thickness) tuple
    """
    if priority == "thickness":
        # Trust base and thickness, compute surface
        surface = base + thickness
    elif priority == "surface":
        # Trust surface and base, compute thickness
        thickness = surface - base
        thickness = np.maximum(thickness, 0)
    elif priority == "base":
        # Trust surface and thickness, compute base
        base = surface - thickness

    return surface, base, thickness


# =============================================================================
# Processing
# =============================================================================
def process_geometry(args):
    """Main processing: load data, interpolate, enforce consistency, save."""
    os.makedirs(args.output_dir, exist_ok=True)

    mesh_x = np.load(args.mesh_x)
    mesh_y = np.load(args.mesh_y)
    nv = len(mesh_x)
    print(f"Mesh: {nv} vertices", file=sys.stderr)

    if args.bedmachine:
        # Load from BedMachine NetCDF
        print(f"Loading from BedMachine: {args.bedmachine}", file=sys.stderr)
        with NCDataset(args.bedmachine) as ds:
            grid_x = np.array(ds.variables['x'][:])
            grid_y = np.array(ds.variables['y'][:])
            surface_grid = np.array(ds.variables['surface'][:])
            bed_grid = np.array(ds.variables['bed'][:])
            thickness_grid = np.array(ds.variables['thickness'][:])

        surface = interp_grid_to_mesh(grid_x, grid_y, surface_grid, mesh_x, mesh_y)
        bed = interp_grid_to_mesh(grid_x, grid_y, bed_grid, mesh_x, mesh_y)
        thickness = interp_grid_to_mesh(grid_x, grid_y, thickness_grid, mesh_x, mesh_y)

    else:
        # Load from individual arrays
        surface = np.load(args.surface) if args.surface else None
        bed = np.load(args.bed) if args.bed else None
        thickness = np.load(args.thickness) if args.thickness else None

        # Compute missing fields
        if thickness is not None and bed is not None and surface is None:
            surface = bed + thickness
        elif surface is not None and bed is not None and thickness is None:
            thickness = surface - bed
        elif surface is not None and thickness is not None and bed is None:
            bed = surface - thickness

    # Enforce minimum thickness
    thickness = np.maximum(thickness, MIN_THICKNESS)

    # Compute base with hydrostatic equilibrium
    base, is_floating = compute_base_from_hydrostatic(thickness, bed, surface)

    # Enforce consistency
    surface, base, thickness = enforce_consistency(surface, base, thickness, args.priority)

    # Validate
    warnings = validate_outputs(surface, base, thickness, bed)

    # Save outputs
    np.save(os.path.join(args.output_dir, "surface.npy"), surface)
    np.save(os.path.join(args.output_dir, "base.npy"), base)
    np.save(os.path.join(args.output_dir, "thickness.npy"), thickness)
    np.save(os.path.join(args.output_dir, "bed.npy"), bed)

    # Generate mask arrays (for setmask)
    ocean_levelset = np.ones(nv)  # positive = grounded
    ocean_levelset[is_floating] = -1.0  # negative = floating
    np.save(os.path.join(args.output_dir, "ocean_levelset.npy"), ocean_levelset)

    ice_levelset = -np.ones(nv)  # negative = ice present
    ice_levelset[thickness <= MIN_THICKNESS] = 1.0  # positive = no ice
    np.save(os.path.join(args.output_dir, "ice_levelset.npy"), ice_levelset)

    n_floating = np.sum(is_floating)
    n_grounded = nv - n_floating

    results = {
        "status": "success",
        "output_dir": args.output_dir,
        "n_vertices": nv,
        "n_grounded": int(n_grounded),
        "n_floating": int(n_floating),
        "thickness": {
            "min": float(np.min(thickness)), "max": float(np.max(thickness)),
            "mean": float(np.mean(thickness))
        },
        "surface": {
            "min": float(np.min(surface)), "max": float(np.max(surface)),
            "mean": float(np.mean(surface))
        },
        "bed": {
            "min": float(np.min(bed)), "max": float(np.max(bed)),
            "mean": float(np.mean(bed))
        },
        "warnings": warnings
    }
    print(json.dumps(results, indent=2))


# =============================================================================
# CLI
# =============================================================================
def main():
    parser = argparse.ArgumentParser(
        description="Convert geometry data to ISSM format")

    parser.add_argument("--bedmachine", help="BedMachine NetCDF file (auto-loads all geometry)")
    parser.add_argument("--surface", help="Surface elevation array (.npy)")
    parser.add_argument("--bed", help="Bedrock elevation array (.npy)")
    parser.add_argument("--thickness", help="Ice thickness array (.npy)")
    parser.add_argument("--mesh_x", required=True, help="Mesh x-coordinates (.npy)")
    parser.add_argument("--mesh_y", required=True, help="Mesh y-coordinates (.npy)")
    parser.add_argument("--priority", default="thickness",
                        choices=["thickness", "surface", "base"],
                        help="Which fields to trust for consistency enforcement")
    parser.add_argument("--output_dir", required=True, help="Output directory")

    global args
    args = parser.parse_args()
    validate_inputs(args)
    process_geometry(args)


if __name__ == "__main__":
    main()
