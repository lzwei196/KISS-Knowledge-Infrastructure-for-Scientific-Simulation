#!/usr/bin/env python3
"""
convert_geometry.py — Convert DEM/ice thickness data to Elmer mesh node format.

Reads bedrock elevation, surface elevation, and ice thickness from various
global datasets (BedMachine, ArcticDEM, REMA) and produces node-level data
files compatible with Elmer/Ice SIF Variable definitions.

CRITICAL UNIT ISSUES:
  - All coordinates MUST be in meters (not km). Elmer uses SI internally
    and gravity (9.81 m/s2) applied to km coordinates gives 1000x error.
  - Elevations must be in meters above sea level.
  - Ice thickness must be positive (H >= 0).

Expected input:
  NetCDF or GeoTIFF with bed, surface, thickness fields in meters.

Expected output:
  ASCII files with node-indexed values for SIF Initial Condition blocks:
    zb_nodes.dat  — bed elevation (m)
    zs_nodes.dat  — surface elevation (m)
    h_nodes.dat   — ice thickness (m)
    depth_nodes.dat — depth below surface (m)

Usage:
    python convert_geometry.py --bed bed.nc --surface surface.nc \
        --thickness thickness.nc --mesh_dir ./rectangle \
        --output_dir ./geometry --variable_bed bed --variable_surface surface \
        --variable_thickness thickness
"""

import argparse
import json
import os
import sys

import numpy as np

try:
    from scipy.interpolate import RegularGridInterpolator
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

try:
    import netCDF4 as nc
    HAS_NETCDF = True
except ImportError:
    HAS_NETCDF = False


def validate_inputs(args):
    """Check all input arguments for validity."""
    errors = []

    # Check mesh directory
    if not os.path.isdir(args.mesh_dir):
        errors.append(f"Mesh directory not found: {args.mesh_dir}")
    else:
        mesh_nodes = os.path.join(args.mesh_dir, "mesh.nodes")
        if not os.path.isfile(mesh_nodes):
            errors.append(f"mesh.nodes not found in {args.mesh_dir}")

    # Check input files (at least one source required)
    if args.bed and not os.path.isfile(args.bed):
        errors.append(f"Bed file not found: {args.bed}")
    if args.surface and not os.path.isfile(args.surface):
        errors.append(f"Surface file not found: {args.surface}")
    if args.thickness and not os.path.isfile(args.thickness):
        errors.append(f"Thickness file not found: {args.thickness}")

    # Check for synthetic mode
    if not args.bed and not args.surface and not args.synthetic:
        errors.append("Must provide --bed/--surface/--thickness files or --synthetic")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)


def read_mesh_nodes(mesh_dir):
    """Read Elmer mesh.nodes file and return node coordinates.

    Format: node_id  body_id  x  y  z
    """
    nodes_file = os.path.join(mesh_dir, "mesh.nodes")
    nodes = []
    with open(nodes_file, "r") as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) >= 5:
                node_id = int(parts[0])
                x = float(parts[2])
                y = float(parts[3])
                z = float(parts[4])
                nodes.append((node_id, x, y, z))
    return np.array(nodes)


def read_netcdf_field(filepath, varname, lat_var="lat", lon_var="lon"):
    """Read a 2D field from NetCDF and return (lons, lats, data)."""
    if not HAS_NETCDF:
        print(json.dumps({"status": "error",
                          "errors": ["netCDF4 not installed: pip install netCDF4"]}),
              file=sys.stderr)
        sys.exit(1)

    ds = nc.Dataset(filepath, "r")
    # Try common coordinate names
    for lname in [lat_var, "latitude", "y", "Y"]:
        if lname in ds.variables:
            lats = ds.variables[lname][:]
            break
    else:
        ds.close()
        raise ValueError(f"Cannot find latitude variable in {filepath}")

    for lname in [lon_var, "longitude", "x", "X"]:
        if lname in ds.variables:
            lons = ds.variables[lname][:]
            break
    else:
        ds.close()
        raise ValueError(f"Cannot find longitude variable in {filepath}")

    data = ds.variables[varname][:]
    if data.ndim == 3:
        data = data[0, :, :]  # take first time slice
    ds.close()
    return lons, lats, np.array(data)


def interpolate_to_nodes(lons, lats, data, node_coords):
    """Interpolate gridded data to mesh node locations."""
    if not HAS_SCIPY:
        print(json.dumps({"status": "error",
                          "errors": ["scipy not installed: pip install scipy"]}),
              file=sys.stderr)
        sys.exit(1)

    interp = RegularGridInterpolator(
        (lats, lons), data,
        method="linear", bounds_error=False, fill_value=np.nan
    )
    # node_coords: columns are (x, y) which map to (lon, lat) or (easting, northing)
    points = np.column_stack([node_coords[:, 1], node_coords[:, 0]])  # (lat, lon)
    return interp(points)


def generate_synthetic(node_coords, profile="slab"):
    """Generate synthetic geometry for testing.

    Profiles:
      slab   — flat bed at 0m, uniform 1000m thickness
      valley — parabolic valley bed, thickness varies
      ismip  — ISMIP-HOM style inclined slab
    """
    x = node_coords[:, 0]
    n = len(x)

    if profile == "slab":
        zb = np.zeros(n)
        h = np.full(n, 1000.0)
        zs = zb + h
    elif profile == "valley":
        x_norm = (x - x.min()) / (x.max() - x.min() + 1e-12)
        zb = 500.0 * (1.0 - 4.0 * (x_norm - 0.5) ** 2)
        h = np.maximum(1000.0 - 500.0 * x_norm, 100.0)
        zs = zb + h
    elif profile == "ismip":
        L = x.max() - x.min()
        x_norm = (x - x.min()) / (L + 1e-12)
        zs = 2000.0 - 1000.0 * x_norm  # surface slopes from 2000 to 1000
        h = np.full(n, 1000.0)
        zb = zs - h
    else:
        raise ValueError(f"Unknown profile: {profile}")

    return zb, zs, h


def process(args):
    """Core processing: read inputs, interpolate, write node data."""
    nodes = read_mesh_nodes(args.mesh_dir)
    node_ids = nodes[:, 0].astype(int)
    node_coords = nodes[:, 1:4]  # x, y, z
    n_nodes = len(node_ids)

    if args.synthetic:
        zb, zs, h = generate_synthetic(node_coords, profile=args.synthetic)
    else:
        # Read from NetCDF files
        if args.bed:
            lons_b, lats_b, bed_data = read_netcdf_field(
                args.bed, args.variable_bed)
            zb = interpolate_to_nodes(lons_b, lats_b, bed_data, node_coords)
        else:
            zb = np.zeros(n_nodes)

        if args.surface:
            lons_s, lats_s, surf_data = read_netcdf_field(
                args.surface, args.variable_surface)
            zs = interpolate_to_nodes(lons_s, lats_s, surf_data, node_coords)
        else:
            zs = None

        if args.thickness:
            lons_t, lats_t, thick_data = read_netcdf_field(
                args.thickness, args.variable_thickness)
            h = interpolate_to_nodes(lons_t, lats_t, thick_data, node_coords)
        else:
            h = None

        # Derive missing field
        if zs is not None and h is None:
            h = np.maximum(zs - zb, 0.0)
        elif h is not None and zs is None:
            zs = zb + h
        elif zs is None and h is None:
            raise ValueError("Must provide at least surface or thickness")

    # Ensure physical consistency
    h = np.maximum(h, 0.0)
    zs = zb + h
    depth = np.max(zs) - zs  # depth below max surface

    return {
        "node_ids": node_ids,
        "zb": zb,
        "zs": zs,
        "h": h,
        "depth": depth,
        "n_nodes": n_nodes,
    }


def validate_outputs(result):
    """Check output data for physical plausibility."""
    warnings = []

    zb = result["zb"]
    zs = result["zs"]
    h = result["h"]

    # Check for NaNs
    for name, arr in [("zb", zb), ("zs", zs), ("h", h)]:
        nan_count = np.sum(np.isnan(arr))
        if nan_count > 0:
            warnings.append(f"{name} has {nan_count} NaN values "
                            f"({100*nan_count/len(arr):.1f}%)")

    # Check thickness is non-negative
    neg_h = np.sum(h < 0)
    if neg_h > 0:
        warnings.append(f"Ice thickness has {neg_h} negative values — clamped to 0")

    # Check for km-scale coordinates (common trap dt_008)
    if np.nanmax(np.abs(zb)) < 10.0 and np.nanmax(h) > 0:
        warnings.append("POSSIBLE UNIT ERROR: bed elevations are very small — "
                        "are coordinates in km instead of m?")

    # Check unrealistic thickness
    if np.nanmax(h) > 5000.0:
        warnings.append(f"Max ice thickness = {np.nanmax(h):.0f} m — "
                        "exceeds 5000 m, check units")

    for w in warnings:
        print(f"WARNING: {w}", file=sys.stderr)

    return warnings


def write_node_data(filepath, node_ids, values):
    """Write node-indexed data file for Elmer SIF."""
    os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
    with open(filepath, "w") as f:
        for nid, val in zip(node_ids, values):
            if np.isnan(val):
                val = 0.0
            f.write(f"{int(nid)} {val:.6f}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Convert DEM/ice data to Elmer node format")
    parser.add_argument("--bed", type=str, default=None,
                        help="NetCDF file with bed elevation")
    parser.add_argument("--surface", type=str, default=None,
                        help="NetCDF file with surface elevation")
    parser.add_argument("--thickness", type=str, default=None,
                        help="NetCDF file with ice thickness")
    parser.add_argument("--variable_bed", type=str, default="bed",
                        help="Variable name for bed elevation")
    parser.add_argument("--variable_surface", type=str, default="surface",
                        help="Variable name for surface elevation")
    parser.add_argument("--variable_thickness", type=str, default="thickness",
                        help="Variable name for ice thickness")
    parser.add_argument("--mesh_dir", type=str, required=True,
                        help="Path to Elmer mesh directory")
    parser.add_argument("--output_dir", type=str, required=True,
                        help="Output directory for node data files")
    parser.add_argument("--synthetic", type=str, default=None,
                        choices=["slab", "valley", "ismip"],
                        help="Generate synthetic geometry instead of reading files")

    args = parser.parse_args()

    validate_inputs(args)
    result = process(args)
    warnings = validate_outputs(result)

    # Write output files
    os.makedirs(args.output_dir, exist_ok=True)
    write_node_data(os.path.join(args.output_dir, "zb_nodes.dat"),
                    result["node_ids"], result["zb"])
    write_node_data(os.path.join(args.output_dir, "zs_nodes.dat"),
                    result["node_ids"], result["zs"])
    write_node_data(os.path.join(args.output_dir, "h_nodes.dat"),
                    result["node_ids"], result["h"])
    write_node_data(os.path.join(args.output_dir, "depth_nodes.dat"),
                    result["node_ids"], result["depth"])

    status = {
        "status": "success",
        "n_nodes": result["n_nodes"],
        "files_written": [
            os.path.join(args.output_dir, "zb_nodes.dat"),
            os.path.join(args.output_dir, "zs_nodes.dat"),
            os.path.join(args.output_dir, "h_nodes.dat"),
            os.path.join(args.output_dir, "depth_nodes.dat"),
        ],
        "ranges": {
            "zb": [float(np.nanmin(result["zb"])),
                   float(np.nanmax(result["zb"]))],
            "zs": [float(np.nanmin(result["zs"])),
                   float(np.nanmax(result["zs"]))],
            "h": [float(np.nanmin(result["h"])),
                  float(np.nanmax(result["h"]))],
        },
        "warnings": warnings,
    }
    print(json.dumps(status, indent=2), file=sys.stderr)


if __name__ == "__main__":
    main()
