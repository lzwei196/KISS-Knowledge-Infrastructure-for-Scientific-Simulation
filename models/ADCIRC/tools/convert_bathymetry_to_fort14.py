#!/usr/bin/env python3
"""
convert_bathymetry_to_fort14.py — Convert DEM/bathymetry data to ADCIRC fort.14 mesh
and fort.13 nodal attributes.

Takes gridded bathymetry (GEBCO, ETOPO, custom DEM) and coastline data to produce:
  - fort.14: Unstructured triangular mesh with node coordinates and depths
  - fort.13: Nodal attributes (Manning's n based on depth classification)

CRITICAL UNIT CONVENTIONS:
  - Depth (DP) is POSITIVE below geoid, NEGATIVE above (dt_001)
  - Coordinates in degrees for spherical (ICS=2) mode
  - G must be 9.81 m/s² when using spherical coordinates (dt_002)

Usage:
    python convert_bathymetry_to_fort14.py \
        --dem /path/to/gebco.nc \
        --domain_sw 24.0,-98.0 --domain_ne 31.0,-88.0 \
        --min_resolution 500 --max_resolution 50000 \
        --output_fort14 fort.14 --output_fort13 fort.13

Output:
    fort.14 — ADCIRC grid file (nodes, elements, boundaries)
    fort.13 — Nodal attributes (Manning's n at each node)
"""

import argparse
import logging
import os
import sys

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
EARTH_RADIUS_M = 6378206.4  # ADCIRC default Earth radius

# Manning's n classification by depth (depth positive = below geoid)
MANNINGS_TABLE = {
    # (min_depth, max_depth): Manning's n
    (-100, 0): 0.12,     # Land/marsh (negative depth = above geoid)
    (0, 2): 0.08,        # Very shallow coastal
    (2, 10): 0.035,      # Shallow coastal
    (10, 50): 0.025,     # Continental shelf
    (50, 200): 0.022,    # Outer shelf
    (200, 5000): 0.02,   # Deep ocean
    (5000, 12000): 0.018,  # Abyssal
}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def validate_inputs(args):
    """Validate input parameters."""
    errors = []

    if not os.path.isfile(args.dem):
        errors.append(f"DEM file not found: {args.dem}")

    try:
        sw_lat, sw_lon = [float(x) for x in args.domain_sw.split(",")]
        ne_lat, ne_lon = [float(x) for x in args.domain_ne.split(",")]
    except (ValueError, AttributeError):
        errors.append("domain_sw/ne must be 'lat,lon'")
        sw_lat = sw_lon = ne_lat = ne_lon = 0

    if sw_lat >= ne_lat:
        errors.append(f"SW lat ({sw_lat}) >= NE lat ({ne_lat})")
    if sw_lon >= ne_lon:
        errors.append(f"SW lon ({sw_lon}) >= NE lon ({ne_lon})")

    if args.min_resolution <= 0 or args.max_resolution <= 0:
        errors.append("Resolution must be > 0")
    if args.min_resolution >= args.max_resolution:
        errors.append("min_resolution must be < max_resolution")

    if errors:
        for e in errors:
            logger.error(e)
        raise ValueError(f"{len(errors)} validation error(s)")

    return sw_lat, sw_lon, ne_lat, ne_lon


def validate_outputs(fort14_path, fort13_path):
    """Validate output mesh and attributes."""
    errors = []

    if not os.path.isfile(fort14_path):
        errors.append(f"fort.14 not written: {fort14_path}")
    else:
        with open(fort14_path) as f:
            lines = f.readlines()
        if len(lines) < 3:
            errors.append("fort.14 is too short")
        else:
            ne, nn = lines[1].strip().split()
            ne, nn = int(ne), int(nn)
            if ne < 1 or nn < 3:
                errors.append(f"Invalid mesh: {ne} elements, {nn} nodes")
            logger.info(f"fort.14: {nn} nodes, {ne} elements")

            # Verify depth convention (should have positive depths for ocean)
            depths = []
            for i in range(2, min(2 + nn, len(lines))):
                parts = lines[i].strip().split()
                if len(parts) >= 4:
                    depths.append(float(parts[3]))
            if depths:
                dp_arr = np.array(depths)
                n_positive = np.sum(dp_arr > 0)
                if n_positive == 0:
                    errors.append(
                        "WARNING: All depths are non-positive — "
                        "check sign convention (ADCIRC: positive = below geoid)"
                    )

    if fort13_path and not os.path.isfile(fort13_path):
        errors.append(f"fort.13 not written: {fort13_path}")

    if errors:
        for e in errors:
            logger.error(e)
        raise ValueError(f"{len(errors)} output validation error(s)")

    logger.info("Output validation passed")


# ---------------------------------------------------------------------------
# DEM reader
# ---------------------------------------------------------------------------
def read_dem(dem_path, sw_lat, sw_lon, ne_lat, ne_lon):
    """Read DEM/bathymetry from netCDF file.

    Handles GEBCO, ETOPO, and generic (lat, lon, elevation) netCDF.

    Returns:
        lats: 1D array of latitudes (ascending)
        lons: 1D array of longitudes (ascending)
        elev: 2D array [nlat, nlon] of elevation (positive up, meters)
    """
    try:
        import netCDF4 as nc
    except ImportError:
        raise ImportError("netCDF4 required: pip install netCDF4")

    with nc.Dataset(dem_path) as ds:
        # Try common coordinate names
        for lat_name in ("lat", "latitude", "y", "LAT"):
            if lat_name in ds.variables:
                break
        for lon_name in ("lon", "longitude", "x", "LON"):
            if lon_name in ds.variables:
                break

        lat = ds.variables[lat_name][:]
        lon = ds.variables[lon_name][:]

        # Try common elevation variable names
        for elev_name in ("elevation", "z", "Band1", "topo", "height", "depth"):
            if elev_name in ds.variables:
                break

        # Subset to domain (with buffer)
        buf = 0.1  # degree buffer
        lat_idx = np.where((lat >= sw_lat - buf) & (lat <= ne_lat + buf))[0]
        lon_idx = np.where((lon >= sw_lon - buf) & (lon <= ne_lon + buf))[0]

        if len(lat_idx) == 0 or len(lon_idx) == 0:
            raise ValueError("No DEM data found in specified domain")

        lats = lat[lat_idx]
        lons = lon[lon_idx]
        elev = ds.variables[elev_name][
            lat_idx[0]:lat_idx[-1]+1,
            lon_idx[0]:lon_idx[-1]+1
        ]

    # Ensure ascending latitude
    if lats[0] > lats[-1]:
        lats = lats[::-1]
        elev = elev[::-1, :]

    logger.info(
        f"DEM: {len(lats)}×{len(lons)} grid, "
        f"elevation range {np.min(elev):.1f} to {np.max(elev):.1f} m"
    )
    return lats, lons, np.array(elev, dtype=float)


# ---------------------------------------------------------------------------
# Mesh generation (structured triangulation from regular grid)
# ---------------------------------------------------------------------------
def generate_structured_mesh(lats, lons, elev, min_res_m, max_res_m):
    """Generate a structured triangular mesh from the DEM grid.

    Each grid cell is divided into 2 triangles. Resolution is controlled by
    subsampling the DEM grid based on min_res_m/max_res_m and local depth.

    Args:
        lats, lons: 1D coordinate arrays
        elev: 2D elevation array (positive up)
        min_res_m: Minimum resolution (near coast, in meters)
        max_res_m: Maximum resolution (deep ocean, in meters)

    Returns:
        nodes: (N, 3) array of [lon, lat, depth] — depth positive below geoid
        elements: (M, 3) array of 0-based node indices
    """
    # Calculate approximate grid spacing in meters
    mid_lat = (lats[0] + lats[-1]) / 2
    dx_deg = abs(lons[1] - lons[0]) if len(lons) > 1 else 0.01
    dy_deg = abs(lats[1] - lats[0]) if len(lats) > 1 else 0.01
    m_per_deg_lat = np.pi * EARTH_RADIUS_M / 180.0
    m_per_deg_lon = m_per_deg_lat * np.cos(np.radians(mid_lat))
    dx_m = dx_deg * m_per_deg_lon
    dy_m = dy_deg * m_per_deg_lat

    # Determine subsampling factor based on desired resolution
    target_res_m = (min_res_m + max_res_m) / 2
    skip = max(1, int(np.sqrt(dx_m * dy_m) / target_res_m * 2))
    # Limit to avoid too many nodes (cap at ~500k nodes)
    max_nodes = 500000
    while (len(lats[::skip]) * len(lons[::skip])) > max_nodes and skip < 100:
        skip += 1

    sub_lats = lats[::skip]
    sub_lons = lons[::skip]
    sub_elev = elev[::skip, ::skip]

    nlat = len(sub_lats)
    nlon = len(sub_lons)
    logger.info(
        f"Mesh grid: {nlat}×{nlon} = {nlat*nlon} nodes "
        f"(skip={skip}, ~{dx_m*skip:.0f}m resolution)"
    )

    # Create nodes: [lon, lat, depth]
    # CRITICAL: ADCIRC depth = positive below geoid = -elevation
    nodes = np.zeros((nlat * nlon, 3))
    for i in range(nlat):
        for j in range(nlon):
            idx = i * nlon + j
            nodes[idx, 0] = sub_lons[j]        # X = longitude
            nodes[idx, 1] = sub_lats[i]         # Y = latitude
            nodes[idx, 2] = -sub_elev[i, j]     # depth = -elevation (dt_001)

    # Create triangular elements (2 triangles per quad cell)
    elements = []
    for i in range(nlat - 1):
        for j in range(nlon - 1):
            n1 = i * nlon + j
            n2 = i * nlon + (j + 1)
            n3 = (i + 1) * nlon + (j + 1)
            n4 = (i + 1) * nlon + j
            # Two triangles per quad, counter-clockwise
            elements.append([n1, n2, n3])
            elements.append([n1, n3, n4])

    elements = np.array(elements)
    logger.info(f"Generated {len(nodes)} nodes, {len(elements)} elements")

    return nodes, elements


# ---------------------------------------------------------------------------
# fort.14 writer
# ---------------------------------------------------------------------------
def write_fort14(filepath, nodes, elements, grid_name="ADCIRC_MESH"):
    """Write ADCIRC fort.14 grid file.

    Format:
        Line 1: AGRID (grid name)
        Line 2: NE NP (element count, node count)
        Lines 3-NP+2: JN X Y DP (node#, lon, lat, depth)
        Lines NP+3-NP+NE+2: JE NHY NM1 NM2 NM3 (elem#, 3, node1, node2, node3)
        Boundary segments follow...
    """
    ne = len(elements)
    nn = len(nodes)

    with open(filepath, "w") as f:
        f.write(f"{grid_name}\n")
        f.write(f"{ne} {nn}\n")

        # Nodes (1-indexed)
        for i in range(nn):
            f.write(
                f"{i+1:8d} {nodes[i,0]:16.10f} {nodes[i,1]:16.10f} "
                f"{nodes[i,2]:16.10f}\n"
            )

        # Elements (1-indexed, counter-clockwise)
        for i in range(ne):
            f.write(
                f"{i+1:8d} 3 "
                f"{elements[i,0]+1:8d} {elements[i,1]+1:8d} "
                f"{elements[i,2]+1:8d}\n"
            )

        # Open boundary (simple: entire outer edge as elevation BC)
        # Find boundary nodes (nodes on the edge of the grid)
        nlon_grid = int(np.sqrt(nn * (nodes[-1, 0] - nodes[0, 0]) /
                                (nodes[-1, 1] - nodes[0, 1])))
        if nlon_grid <= 0:
            nlon_grid = int(np.sqrt(nn))
        nlat_grid = nn // nlon_grid

        # Ocean boundary: bottom edge (first row of nodes)
        ocean_boundary = list(range(1, nlon_grid + 1))

        # Write open boundaries
        f.write(f"1\n")  # NOPE: number of open boundary segments
        f.write(f"{len(ocean_boundary)}\n")  # Total open boundary nodes
        f.write(f"{len(ocean_boundary)} 0\n")  # nodes in segment, type
        for n in ocean_boundary:
            f.write(f"{n}\n")

        # Land boundary: left, top, right edges
        land_nodes = []
        # Right edge (bottom to top)
        for i in range(nlat_grid):
            land_nodes.append(i * nlon_grid + nlon_grid)
        # Top edge (right to left)
        for j in range(nlon_grid - 1, -1, -1):
            land_nodes.append((nlat_grid - 1) * nlon_grid + j + 1)
        # Left edge (top to bottom)
        for i in range(nlat_grid - 2, 0, -1):
            land_nodes.append(i * nlon_grid + 1)

        # Remove duplicates preserving order
        seen = set()
        unique_land = []
        for n in land_nodes:
            if n not in seen and 1 <= n <= nn:
                seen.add(n)
                unique_land.append(n)

        f.write(f"1\n")  # NBOU: number of land boundary segments
        f.write(f"{len(unique_land)}\n")  # Total land boundary nodes
        f.write(f"{len(unique_land)} 0\n")  # nodes in segment, IBTYPE=0
        for n in unique_land:
            f.write(f"{n}\n")

    logger.info(f"Wrote {filepath}: {nn} nodes, {ne} elements")


# ---------------------------------------------------------------------------
# fort.13 writer
# ---------------------------------------------------------------------------
def assign_mannings_n(depth):
    """Assign Manning's n based on depth using classification table.

    Args:
        depth: Bathymetric depth (positive below geoid)

    Returns:
        Manning's n value (s/m^(1/3))
    """
    for (dmin, dmax), n_val in MANNINGS_TABLE.items():
        if dmin <= depth < dmax:
            return n_val
    return 0.02  # Default for very deep water


def write_fort13(filepath, nodes, grid_name="ADCIRC_MESH"):
    """Write ADCIRC fort.13 nodal attributes file.

    Creates Manning's n at sea floor attribute based on depth classification.

    Format:
        Line 1: AGRID
        Line 2: number of nodes
        Line 3: number of attributes
        Then for each attribute:
            Name, Units, ValuesPerNode, DefaultValue
            Nodes with non-default values
    """
    nn = len(nodes)

    # Compute Manning's n for all nodes
    mannings = np.array([assign_mannings_n(nodes[i, 2]) for i in range(nn)])
    default_n = 0.025  # Default Manning's n

    # Find non-default nodes
    non_default = [(i, mannings[i]) for i in range(nn)
                   if abs(mannings[i] - default_n) > 1e-6]

    with open(filepath, "w") as f:
        f.write(f"{grid_name}\n")
        f.write(f"{nn}\n")
        f.write(f"1\n")  # Number of attributes

        # Attribute 1: Manning's n
        f.write(f"mannings_n_at_sea_floor\n")
        f.write(f"s/m^(1/3)\n")
        f.write(f"1\n")  # ValuesPerNode
        f.write(f"{default_n:.6f}\n")  # Default value

        # Non-default values
        f.write(f"mannings_n_at_sea_floor\n")
        f.write(f"{len(non_default)}\n")
        for idx, val in non_default:
            f.write(f"{idx+1:8d} {val:.6f}\n")

    logger.info(
        f"Wrote {filepath}: {len(non_default)}/{nn} non-default Manning's n values"
    )


# ---------------------------------------------------------------------------
# Main processing
# ---------------------------------------------------------------------------
def process(args):
    """Main pipeline: validate → read → mesh → write → validate."""

    # Step 1: Validate inputs
    sw_lat, sw_lon, ne_lat, ne_lon = validate_inputs(args)

    # Step 2: Read DEM
    lats, lons, elev = read_dem(args.dem, sw_lat, sw_lon, ne_lat, ne_lon)

    # Step 3: Generate mesh
    nodes, elements = generate_structured_mesh(
        lats, lons, elev,
        args.min_resolution, args.max_resolution
    )

    # Step 4: Write fort.14
    output_dir = os.path.dirname(args.output_fort14) or "."
    os.makedirs(output_dir, exist_ok=True)
    write_fort14(args.output_fort14, nodes, elements)

    # Step 5: Write fort.13
    if args.output_fort13:
        write_fort13(args.output_fort13, nodes)

    # Step 6: Validate outputs
    validate_outputs(args.output_fort14, args.output_fort13)

    logger.info("Bathymetry conversion complete")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Convert DEM/bathymetry to ADCIRC fort.14 mesh + fort.13 attributes",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--dem", required=True,
                        help="Path to DEM netCDF file (GEBCO, ETOPO, etc.)")
    parser.add_argument("--coastline", default=None,
                        help="Path to coastline shapefile (optional)")
    parser.add_argument("--domain_sw", required=True,
                        help="SW corner: 'lat,lon' (degrees)")
    parser.add_argument("--domain_ne", required=True,
                        help="NE corner: 'lat,lon' (degrees)")
    parser.add_argument("--min_resolution", type=float, default=500,
                        help="Min element size near coast (meters, default: 500)")
    parser.add_argument("--max_resolution", type=float, default=50000,
                        help="Max element size in deep ocean (meters, default: 50000)")
    parser.add_argument("--output_fort14", default="fort.14",
                        help="Output fort.14 path (default: fort.14)")
    parser.add_argument("--output_fort13", default="fort.13",
                        help="Output fort.13 path (default: fort.13)")

    args = parser.parse_args()
    process(args)


if __name__ == "__main__":
    main()
