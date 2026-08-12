#!/usr/bin/env python3
"""
convert_dem_to_grid.py — Convert DEM (ESRI ASCII / GeoTIFF) to Landlab RasterModelGrid

Reads a DEM file, creates a Landlab RasterModelGrid with topographic__elevation
field, sets boundary conditions, and saves to NetCDF.

CRITICAL UNIT CONVERSIONS:
  - DEM must be in METERS (not feet, not cm). If feet, multiply by 0.3048.
  - Grid spacing (xy_spacing) must be in METERS. DEMs in geographic coordinates
    (degrees) will produce nonsensical slopes. Reproject first.
  - NoData values must be identified and masked. Common nodata: -9999, -32768, nan.

Usage:
    python convert_dem_to_grid.py --dem input.asc --output grid.nc --spacing 100
    python convert_dem_to_grid.py --dem input.tif --output grid.nc --nodata -9999
"""

import argparse
import json
import os
import sys

import numpy as np


def validate_inputs(args):
    """Validate command-line arguments and file paths."""
    errors = []

    if not os.path.exists(args.dem):
        errors.append(f"DEM file not found: {args.dem}")

    if args.spacing is not None and args.spacing <= 0:
        errors.append(f"Grid spacing must be positive, got {args.spacing}")

    if args.spacing is not None and args.spacing < 1.0:
        errors.append(
            f"WARNING: spacing={args.spacing} m is very small. "
            "If DEM is in degrees, reproject to a metric CRS first."
        )

    ext = os.path.splitext(args.dem)[1].lower()
    if ext not in (".asc", ".txt", ".tif", ".tiff", ".nc"):
        errors.append(f"Unsupported DEM format: {ext}. Use .asc, .tif, or .nc")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)


def process(args):
    """Load DEM and create Landlab RasterModelGrid with elevation field."""
    from landlab import RasterModelGrid
    from landlab.io import esri_ascii

    ext = os.path.splitext(args.dem)[1].lower()

    if ext in (".asc", ".txt"):
        # Load ESRI ASCII
        with open(args.dem) as f:
            grid = esri_ascii.load(f, name="topographic__elevation", at="node")

        z = grid.at_node["topographic__elevation"]

    elif ext in (".tif", ".tiff"):
        try:
            import rasterio
        except ImportError:
            print(json.dumps({
                "status": "error",
                "errors": ["rasterio required for GeoTIFF. Install: pip install rasterio"]
            }), file=sys.stderr)
            sys.exit(1)

        with rasterio.open(args.dem) as src:
            data = src.read(1)
            nodata = src.nodata if src.nodata is not None else args.nodata
            transform = src.transform
            dx = abs(transform.a)
            dy = abs(transform.e)

        if args.spacing:
            dx = dy = args.spacing

        nrows, ncols = data.shape
        grid = RasterModelGrid((nrows, ncols), xy_spacing=(dx, dy))
        # Flip vertically: rasterio reads top-to-bottom, Landlab is bottom-to-top
        z = grid.add_field(
            "topographic__elevation",
            data[::-1, :].flatten().astype(float),
            at="node",
        )
    elif ext == ".nc":
        from landlab.io.netcdf import from_netcdf
        grid = from_netcdf(args.dem)
        z = grid.at_node["topographic__elevation"]
    else:
        print(json.dumps({"status": "error", "errors": [f"Unsupported: {ext}"]}),
              file=sys.stderr)
        sys.exit(1)

    # Handle nodata
    nodata_val = args.nodata
    if nodata_val is not None:
        nodata_mask = np.isclose(z, nodata_val, atol=0.1)
        n_nodata = np.sum(nodata_mask)
        if n_nodata > 0:
            z[nodata_mask] = np.nan
            # Close nodata nodes
            grid.status_at_node[nodata_mask] = grid.BC_NODE_IS_CLOSED
            print(f"Masked {n_nodata} nodata nodes (value={nodata_val})",
                  file=sys.stderr)

    # Unit conversion: feet to meters
    if args.feet_to_meters:
        z *= 0.3048
        print("Converted elevation from feet to meters (×0.3048)", file=sys.stderr)

    # Set boundary conditions
    if args.boundary == "open_south":
        grid.set_closed_boundaries_at_grid_edges(True, False, True, True)
    elif args.boundary == "open_all":
        # Default: all edges open (Landlab default for fixed-value)
        pass
    elif args.boundary == "closed_all_but_outlet":
        grid.set_closed_boundaries_at_grid_edges(True, True, True, True)
        # Open the lowest-elevation boundary node
        boundary_nodes = grid.boundary_nodes
        if len(boundary_nodes) > 0:
            lowest = boundary_nodes[np.nanargmin(z[boundary_nodes])]
            grid.status_at_node[lowest] = grid.BC_NODE_IS_FIXED_VALUE
            print(f"Opened outlet at node {lowest} (z={z[lowest]:.1f} m)",
                  file=sys.stderr)

    return grid


def validate_outputs(grid):
    """Validate output grid for physical plausibility."""
    warnings = []
    z = grid.at_node["topographic__elevation"]
    valid_z = z[~np.isnan(z)]

    if len(valid_z) == 0:
        warnings.append("CRITICAL: All elevation values are NaN")
        return warnings

    z_min, z_max = np.min(valid_z), np.max(valid_z)
    z_range = z_max - z_min

    if z_range < 0.01:
        warnings.append(f"WARNING: Elevation range is only {z_range:.4f} m (flat?)")

    if z_max > 9000:
        warnings.append(f"WARNING: Max elevation {z_max:.0f} m exceeds Everest")

    if z_min < -500:
        warnings.append(f"WARNING: Min elevation {z_min:.0f} m is very negative")

    # Check if spacing looks like degrees
    dx = grid.dx if hasattr(grid, "dx") else grid.spacing[0]
    if dx < 0.01:
        warnings.append(
            f"WARNING: Grid spacing {dx} is very small. "
            "If DEM is in geographic coords, reproject to meters."
        )

    n_open = np.sum(grid.status_at_node == grid.BC_NODE_IS_FIXED_VALUE)
    if n_open == 0:
        warnings.append(
            "CRITICAL: No open boundary nodes. "
            "Flow cannot exit the grid. Set at least one open boundary."
        )

    return warnings


def main():
    parser = argparse.ArgumentParser(
        description="Convert DEM to Landlab RasterModelGrid with elevation field"
    )
    parser.add_argument("--dem", type=str, required=True,
                        help="Path to input DEM (.asc, .tif, .nc)")
    parser.add_argument("--output", type=str, required=True,
                        help="Output path (.nc for NetCDF)")
    parser.add_argument("--spacing", type=float, default=None,
                        help="Override grid spacing in meters")
    parser.add_argument("--nodata", type=float, default=-9999,
                        help="NoData value in DEM (default: -9999)")
    parser.add_argument("--boundary", type=str, default="open_south",
                        choices=["open_south", "open_all", "closed_all_but_outlet"],
                        help="Boundary condition preset (default: open_south)")
    parser.add_argument("--feet-to-meters", action="store_true",
                        help="Convert elevation from feet to meters")
    args = parser.parse_args()

    validate_inputs(args)
    grid = process(args)
    warnings = validate_outputs(grid)

    # Save output
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    from landlab.io.netcdf import write_netcdf
    write_netcdf(args.output, grid, format="NETCDF4", at="node")

    summary = {
        "status": "success",
        "output_file": args.output,
        "grid_shape": list(grid.shape),
        "n_nodes": int(grid.number_of_nodes),
        "spacing": float(grid.dx) if hasattr(grid, "dx") else None,
        "elevation_range": [
            float(np.nanmin(grid.at_node["topographic__elevation"])),
            float(np.nanmax(grid.at_node["topographic__elevation"])),
        ],
        "n_open_boundary": int(
            np.sum(grid.status_at_node == grid.BC_NODE_IS_FIXED_VALUE)
        ),
        "warnings": warnings,
    }
    print(json.dumps(summary, indent=2), file=sys.stderr)


if __name__ == "__main__":
    main()
