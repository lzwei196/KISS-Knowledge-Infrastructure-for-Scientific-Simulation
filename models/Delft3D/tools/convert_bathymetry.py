#!/usr/bin/env python3
"""
convert_bathymetry.py — GEBCO/ETOPO bathymetry → Delft3D depth format

Converts global bathymetry datasets (GEBCO, ETOPO) to Delft3D-compatible
depth files. Supports both structured grid (.dep) and unstructured grid
(xyz samples for interpolation onto _net.nc).

Pipeline stage: s2 (bathymetry preparation)
Pattern: validate → process → validate

Critical unit trap:
  - GEBCO: elevation positive UP (ocean = negative values)
  - Delft3D: depth positive DOWN (ocean = positive values)
  - MUST negate GEBCO values → if omitted, model sees ocean as mountains
"""

import argparse
import os
import sys
from pathlib import Path

import numpy as np

try:
    import netCDF4 as nc
except ImportError:
    nc = None


# ──────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────

GEBCO_ELEVATION_VAR = "elevation"
ETOPO_ELEVATION_VAR = "z"
MISSING_VALUE = -999.0

EXPECTED_DEPTH_RANGE = (-50, 12000)  # meters (positive down for Delft3D)
LAND_THRESHOLD = -5.0  # depth < this → definitely land


# ──────────────────────────────────────────────────────────────────────
# Validation
# ──────────────────────────────────────────────────────────────────────

def validate_inputs(args):
    """Validate input arguments and file existence."""
    errors = []

    if not os.path.isfile(args.bathymetry_file):
        errors.append(f"Bathymetry file not found: {args.bathymetry_file}")

    if args.grid_file and not os.path.isfile(args.grid_file):
        errors.append(f"Grid file not found: {args.grid_file}")

    if args.domain_bounds:
        parts = args.domain_bounds.split()
        if len(parts) != 4:
            errors.append("--domain_bounds must be 'lon_min lat_min lon_max lat_max'")
        else:
            try:
                bounds = [float(x) for x in parts]
                if bounds[0] >= bounds[2] or bounds[1] >= bounds[3]:
                    errors.append("domain_bounds: min must be < max")
            except ValueError:
                errors.append("domain_bounds: all values must be numeric")

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)

    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    print("[validate_inputs] All inputs valid.")


def validate_outputs(output_file, negate_depth):
    """Validate generated bathymetry for physical plausibility."""
    warnings = []

    if not os.path.isfile(output_file):
        warnings.append(f"Output file not created: {output_file}")
        return warnings

    if output_file.endswith(".xyz"):
        data = np.loadtxt(output_file, comments="#")
        if len(data) == 0:
            warnings.append("Output file is empty")
            return warnings
        depths = data[:, 2]
    elif output_file.endswith(".dep"):
        depths = np.loadtxt(output_file, comments="#").flatten()
    else:
        return warnings

    # Filter out missing values
    valid = depths[depths != MISSING_VALUE]
    if len(valid) == 0:
        warnings.append("All depth values are missing")
        return warnings

    d_min, d_max = np.min(valid), np.max(valid)
    d_mean = np.mean(valid)
    n_land = np.sum(valid < 0)
    pct_land = 100.0 * n_land / len(valid)

    print(f"  Depth stats: min={d_min:.1f}, max={d_max:.1f}, mean={d_mean:.1f}")
    print(f"  Land cells: {n_land}/{len(valid)} ({pct_land:.1f}%)")

    # Check sign convention
    if negate_depth and np.mean(valid) < -10:
        warnings.append(
            "Mean depth is negative after negation — source may already be positive-down. "
            "Remove --negate_depth flag."
        )

    if not negate_depth and np.mean(valid) > 10 and d_max > 100:
        warnings.append(
            "Mean depth is positive and large — if source is GEBCO (elevation up), "
            "you need --negate_depth to convert to positive-down convention."
        )

    if d_max > 12000:
        warnings.append(f"Max depth {d_max:.0f} m exceeds deepest ocean (11034 m)")

    if pct_land > 95:
        warnings.append(f"Domain is {pct_land:.0f}% land — check domain bounds")

    if warnings:
        print("[validate_outputs] WARNINGS:")
        for w in warnings:
            print(f"  ⚠ {w}")
    else:
        print("[validate_outputs] Bathymetry within expected ranges.")

    return warnings


# ──────────────────────────────────────────────────────────────────────
# Processing
# ──────────────────────────────────────────────────────────────────────

def read_gebco_etopo(bathymetry_file, domain_bounds=None):
    """Read GEBCO or ETOPO NetCDF bathymetry file."""
    if nc is None:
        print("ERROR: netCDF4 not installed", file=sys.stderr)
        sys.exit(1)

    ds = nc.Dataset(bathymetry_file, "r")

    # Detect variable name
    elev_var = None
    for vname in [GEBCO_ELEVATION_VAR, ETOPO_ELEVATION_VAR, "Band1", "topo"]:
        if vname in ds.variables:
            elev_var = vname
            break
    if elev_var is None:
        available = list(ds.variables.keys())
        print(f"ERROR: No elevation variable found. Available: {available}",
              file=sys.stderr)
        sys.exit(1)

    # Read coordinates
    lat = ds.variables.get("lat", ds.variables.get("latitude"))[:]
    lon = ds.variables.get("lon", ds.variables.get("longitude"))[:]

    # Spatial subset
    if domain_bounds:
        lon_min, lat_min, lon_max, lat_max = [float(x) for x in domain_bounds.split()]
        # Add buffer for interpolation
        buf = 0.1  # degrees
        lat_mask = (lat >= lat_min - buf) & (lat <= lat_max + buf)
        lon_mask = (lon >= lon_min - buf) & (lon <= lon_max + buf)
        lat_idx = np.where(lat_mask)[0]
        lon_idx = np.where(lon_mask)[0]

        if len(lat_idx) == 0 or len(lon_idx) == 0:
            print("ERROR: No data points within domain bounds", file=sys.stderr)
            sys.exit(1)

        lat = lat[lat_idx]
        lon = lon[lon_idx]
        elev = ds.variables[elev_var][lat_idx[0]:lat_idx[-1]+1,
                                       lon_idx[0]:lon_idx[-1]+1]
    else:
        elev = ds.variables[elev_var][:]

    ds.close()

    print(f"  Read bathymetry: {elev.shape}, lat=[{lat[0]:.2f}, {lat[-1]:.2f}], "
          f"lon=[{lon[0]:.2f}, {lon[-1]:.2f}]")
    print(f"  Elevation range: [{np.nanmin(elev):.1f}, {np.nanmax(elev):.1f}] m")

    return lon, lat, elev


def interpolate_to_grid(lon_src, lat_src, elev_src, grid_file):
    """Interpolate bathymetry onto model grid nodes."""
    ds = nc.Dataset(grid_file, "r")

    # Try UGRID conventions first
    node_x = None
    for xname in ["NetNode_x", "mesh2d_node_x", "node_x", "x"]:
        if xname in ds.variables:
            node_x = ds.variables[xname][:]
            yname = xname.replace("_x", "_y").replace("node_x", "node_y")
            node_y = ds.variables.get(yname, ds.variables.get("y"))[:]
            break

    if node_x is None:
        print("ERROR: Cannot find node coordinates in grid file", file=sys.stderr)
        ds.close()
        sys.exit(1)

    ds.close()

    n_nodes = len(node_x)
    print(f"  Grid has {n_nodes} nodes, x=[{np.min(node_x):.2f}, {np.max(node_x):.2f}], "
          f"y=[{np.min(node_y):.2f}, {np.max(node_y):.2f}]")

    # Nearest-neighbor interpolation (fast, good enough for bathymetry)
    from scipy.interpolate import RegularGridInterpolator

    # Ensure lat is ascending for interpolation
    if lat_src[0] > lat_src[-1]:
        lat_src = lat_src[::-1]
        elev_src = elev_src[::-1, :]

    interp = RegularGridInterpolator(
        (lat_src, lon_src), elev_src,
        method="linear", bounds_error=False, fill_value=MISSING_VALUE
    )

    # Interpolate at grid node positions
    points = np.column_stack([node_y, node_x])  # lat, lon order
    depths = interp(points)

    print(f"  Interpolated {n_nodes} nodes, "
          f"depth range: [{np.nanmin(depths):.1f}, {np.nanmax(depths):.1f}]")

    return node_x, node_y, depths


def write_xyz(output_file, x, y, depth):
    """Write XYZ bathymetry file for Delft3D."""
    with open(output_file, "w") as f:
        f.write("# Delft3D bathymetry (XYZ format)\n")
        f.write("# Generated by convert_bathymetry.py\n")
        f.write("# Columns: x  y  depth_m (positive down)\n")
        for i in range(len(x)):
            if depth[i] != MISSING_VALUE:
                f.write(f"{x[i]:.6f}  {y[i]:.6f}  {depth[i]:.4f}\n")

    n_valid = np.sum(depth != MISSING_VALUE)
    print(f"  Written: {output_file} ({n_valid} valid points)")


def write_dep(output_file, depth_grid, n_cols):
    """Write .dep bathymetry file for Delft3D-FLOW (structured grid)."""
    with open(output_file, "w") as f:
        for i, row in enumerate(depth_grid):
            vals = " ".join(f"{d:12.4f}" for d in row)
            f.write(vals + "\n")

    print(f"  Written: {output_file} ({depth_grid.shape})")


def write_samples_to_netcdf(output_file, x, y, depth):
    """Write bathymetry samples as NetCDF for D-Flow FM interpolation."""
    ds = nc.Dataset(output_file, "w", format="NETCDF4")

    ds.createDimension("samples", len(x))
    ds.description = "Bathymetry samples for D-Flow FM grid interpolation"
    ds.source = "Generated by convert_bathymetry.py"

    xv = ds.createVariable("x", "f8", ("samples",))
    yv = ds.createVariable("y", "f8", ("samples",))
    zv = ds.createVariable("z", "f8", ("samples",))

    xv[:] = x
    yv[:] = y
    zv[:] = depth

    xv.units = "m"
    yv.units = "m"
    zv.units = "m"
    zv.positive = "down"
    zv.long_name = "bed_level_depth_below_reference"

    ds.close()
    print(f"  Written: {output_file} ({len(x)} samples)")


# ──────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Convert GEBCO/ETOPO bathymetry to Delft3D format"
    )
    parser.add_argument("--bathymetry_file", required=True,
                        help="GEBCO/ETOPO NetCDF file")
    parser.add_argument("--grid_file", help="Model grid file (_net.nc or .grd)")
    parser.add_argument("--domain_bounds",
                        help="lon_min lat_min lon_max lat_max")
    parser.add_argument("--output", required=True,
                        help="Output file (.xyz, .dep, or .nc)")
    parser.add_argument("--negate_depth", action="store_true",
                        help="Negate elevation (GEBCO positive-up → Delft3D positive-down)")
    parser.add_argument("--format", choices=["xyz", "dep", "netcdf"],
                        default="xyz", help="Output format")
    parser.add_argument("--min_depth", type=float, default=0.1,
                        help="Minimum water depth (clip land to this value) [m]")
    args = parser.parse_args()

    # Step 1: Validate inputs
    validate_inputs(args)

    # Step 2: Read bathymetry
    print(f"[process] Reading bathymetry: {args.bathymetry_file}")
    lon, lat, elev = read_gebco_etopo(args.bathymetry_file, args.domain_bounds)

    # Step 3: Apply sign convention
    if args.negate_depth:
        print("  [unit] Negating elevation (positive-up → positive-down)")
        depth = -elev
    else:
        depth = elev.copy()

    # Step 4: Interpolate to grid if provided
    if args.grid_file:
        print(f"[process] Interpolating to grid: {args.grid_file}")
        x, y, depth_interp = interpolate_to_grid(lon, lat, depth, args.grid_file)

        if args.negate_depth:
            # Already negated above, but interpolation uses original
            pass

        # Clip minimum depth
        water_mask = depth_interp > 0
        depth_interp[water_mask & (depth_interp < args.min_depth)] = args.min_depth

        if args.format == "xyz" or args.output.endswith(".xyz"):
            write_xyz(args.output, x, y, depth_interp)
        elif args.format == "netcdf" or args.output.endswith(".nc"):
            write_samples_to_netcdf(args.output, x, y, depth_interp)
        else:
            write_xyz(args.output, x, y, depth_interp)
    else:
        # Write full grid as XYZ or DEP
        lon2d, lat2d = np.meshgrid(lon, lat)
        x_flat = lon2d.flatten()
        y_flat = lat2d.flatten()
        d_flat = depth.flatten()

        if args.format == "dep" or args.output.endswith(".dep"):
            write_dep(args.output, depth, len(lon))
        else:
            write_xyz(args.output, x_flat, y_flat, d_flat)

    # Step 5: Validate outputs
    warnings = validate_outputs(args.output, args.negate_depth)

    if warnings:
        print(f"\n[DONE] Bathymetry generated with {len(warnings)} warning(s)")
    else:
        print(f"\n[DONE] Bathymetry generated successfully")


if __name__ == "__main__":
    main()
