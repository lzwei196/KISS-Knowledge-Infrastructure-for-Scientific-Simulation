#!/usr/bin/env python3
"""
Define ParFlow 3D computational domain from basin shapefile + DEM.

Sets grid dimensions (nx, ny, nz), cell sizes (dx, dy, dz), coordinate origin,
and projects the basin to UTM for ParFlow's Cartesian meter-based grid.

Usage:
    python define_parflow_domain.py \
        --shp_path data/shp/chaohe_shp/chaohe.shp \
        --dem_path data/dem/china_dem_90m/china_dem_90m.tif \
        --resolution 1000 \
        --nz 10 \
        --output_dir outputs/parflow_run/domain/

Author: Jianyun Zhang Research Group, Hohai University
"""

import argparse
import json
import os
import sys
import math

import numpy as np

try:
    import geopandas as gpd
    import rasterio
    from rasterio.mask import mask as rio_mask
    from pyproj import CRS, Transformer
    from shapely.geometry import box, mapping
except ImportError as e:
    print(json.dumps({"status": "error", "message": f"Missing dependency: {e}"}))
    sys.exit(1)


# ========================== CONFIGURATION ==========================
# Default subsurface layer thicknesses (meters, from bottom to top)
# Deeper layers are thicker (aquifer), shallower layers are thinner (root zone)
DEFAULT_DZ_LAYERS = {
    5:  [20.0, 10.0, 5.0, 1.0, 0.5],
    10: [20.0, 10.0, 5.0, 5.0, 3.0, 2.0, 1.0, 0.5, 0.3, 0.2],
    15: [30.0, 20.0, 10.0, 10.0, 5.0, 5.0, 3.0, 2.0, 1.0, 0.5, 0.3, 0.2, 0.1, 0.1, 0.05],
}
# ===================================================================


def determine_utm_zone(lon, lat):
    """Determine UTM zone and EPSG code from lon/lat."""
    zone_number = int((lon + 180) / 6) + 1
    if lat >= 0:
        epsg = 32600 + zone_number
    else:
        epsg = 32700 + zone_number
    return zone_number, epsg


def validate_inputs(shp_path, dem_path, resolution, nz):
    """Validate all inputs before processing."""
    errors = []
    if not os.path.exists(shp_path):
        errors.append(f"Shapefile not found: {shp_path}")
    if dem_path and not os.path.exists(dem_path):
        errors.append(f"DEM not found: {dem_path}")
    if resolution <= 0:
        errors.append(f"Resolution must be positive, got {resolution}")
    if nz < 1 or nz > 100:
        errors.append(f"NZ must be 1-100, got {nz}")
    if resolution < 10:
        errors.append(f"Resolution {resolution}m is extremely fine -- ParFlow will be very slow")
    return errors


def process(shp_path, dem_path, resolution, nz, dz_layers, output_dir,
            buffer_m=0, terrain_following=True):
    """
    Process basin shapefile into ParFlow domain definition.

    Parameters
    ----------
    shp_path : str
        Path to basin boundary shapefile.
    dem_path : str
        Path to DEM raster (GeoTIFF). If None, uses flat domain.
    resolution : float
        Horizontal grid cell size in meters (dx = dy).
    nz : int
        Number of vertical layers.
    dz_layers : list of float or None
        Layer thicknesses from bottom to top (meters). If None, uses defaults.
    output_dir : str
        Output directory for domain definition files.
    buffer_m : float
        Buffer in meters to extend domain beyond basin boundary.
    terrain_following : bool
        Whether to use terrain-following grid (TFG).

    Returns
    -------
    dict
        Domain definition with all grid parameters.
    """
    os.makedirs(output_dir, exist_ok=True)

    # Read shapefile
    gdf = gpd.read_file(shp_path)
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")

    # Get centroid for UTM zone determination
    centroid = gdf.to_crs("EPSG:4326").geometry.unary_union.centroid
    lon_c, lat_c = centroid.x, centroid.y
    utm_zone, utm_epsg = determine_utm_zone(lon_c, lat_c)

    # Project to UTM
    gdf_utm = gdf.to_crs(epsg=utm_epsg)
    basin_geom = gdf_utm.geometry.unary_union

    # Get basin bounds in UTM
    minx, miny, maxx, maxy = basin_geom.bounds

    # Apply buffer
    if buffer_m > 0:
        minx -= buffer_m
        miny -= buffer_m
        maxx += buffer_m
        maxy += buffer_m

    # Compute grid dimensions
    # Round to make grid evenly divisible (helps with MPI decomposition)
    extent_x = maxx - minx
    extent_y = maxy - miny
    nx = int(math.ceil(extent_x / resolution))
    ny = int(math.ceil(extent_y / resolution))

    # Adjust extent to exact grid
    maxx = minx + nx * resolution
    maxy = miny + ny * resolution

    # Set origin (lower-left corner)
    origin_x = minx
    origin_y = miny

    # Determine dz layers
    if dz_layers is None:
        if nz in DEFAULT_DZ_LAYERS:
            dz_layers = DEFAULT_DZ_LAYERS[nz]
        else:
            # Generate default: geometric progression from thick (bottom) to thin (top)
            total_depth = 50.0  # default 50m total subsurface depth
            ratio = 0.7
            dz_layers = []
            remaining = total_depth
            for i in range(nz):
                if i < nz - 1:
                    dz = remaining * (1 - ratio)
                    dz_layers.append(max(dz, 0.05))
                    remaining -= dz
                else:
                    dz_layers.append(max(remaining, 0.05))
            dz_layers.reverse()  # bottom to top

    total_depth = sum(dz_layers)

    # For terrain-following grid, dz values are fractions of total depth
    if terrain_following:
        dz_fractions = [d / total_depth for d in dz_layers]
    else:
        dz_fractions = None

    # Get elevation statistics from DEM if available
    elev_stats = {"min": 0, "max": 0, "mean": 0, "range": 0}
    if dem_path and os.path.exists(dem_path):
        try:
            # Clip DEM to domain extent in WGS84
            transformer = Transformer.from_crs(
                CRS.from_epsg(utm_epsg), CRS.from_epsg(4326), always_xy=True
            )
            x1, y1 = transformer.transform(minx, miny)
            x2, y2 = transformer.transform(maxx, maxy)
            domain_box_4326 = box(min(x1, x2), min(y1, y2),
                                  max(x1, x2), max(y1, y2))
            with rasterio.open(dem_path) as src:
                try:
                    clipped, _ = rio_mask(src, [mapping(domain_box_4326)], crop=True)
                    dem_data = clipped[0]
                    valid = dem_data[dem_data > -9999]
                    if len(valid) > 0:
                        elev_stats = {
                            "min": float(np.min(valid)),
                            "max": float(np.max(valid)),
                            "mean": float(np.mean(valid)),
                            "range": float(np.max(valid) - np.min(valid)),
                        }
                except Exception:
                    pass
        except Exception:
            pass

    # Basin area in km2
    area_km2 = basin_geom.area / 1e6

    # Check grid cell count for MPI decomposition suggestions
    total_cells = nx * ny * nz
    mpi_suggestions = []
    for p in [1, 2, 4, 8, 16]:
        for q in [1, 2, 4, 8, 16]:
            if nx % p == 0 and ny % q == 0:
                mpi_suggestions.append({"P": p, "Q": q, "R": 1, "nprocs": p * q})

    # Sort by total cores, pick reasonable ones
    mpi_suggestions.sort(key=lambda x: x["nprocs"])
    mpi_suggestions = [s for s in mpi_suggestions if s["nprocs"] <= 32][:5]

    domain_def = {
        "status": "success",
        "basin_name": os.path.splitext(os.path.basename(shp_path))[0],
        "crs": {
            "utm_zone": utm_zone,
            "epsg": utm_epsg,
            "proj4": CRS.from_epsg(utm_epsg).to_proj4(),
        },
        "centroid": {"lat": lat_c, "lon": lon_c},
        "grid": {
            "nx": nx,
            "ny": ny,
            "nz": nz,
            "dx": resolution,
            "dy": resolution,
            "dz_layers_m": dz_layers,
            "dz_fractions": dz_fractions,
            "total_depth_m": total_depth,
            "terrain_following": terrain_following,
        },
        "origin": {
            "x": origin_x,
            "y": origin_y,
            "z": 0.0,
        },
        "extent_utm": {
            "xmin": minx,
            "ymin": miny,
            "xmax": maxx,
            "ymax": maxy,
        },
        "elevation": elev_stats,
        "basin_area_km2": round(area_km2, 2),
        "total_cells": total_cells,
        "surface_cells": nx * ny,
        "mpi_topology_suggestions": mpi_suggestions,
    }

    # Save domain definition
    output_file = os.path.join(output_dir, "domain_definition.json")
    with open(output_file, "w") as f:
        json.dump(domain_def, f, indent=2)

    domain_def["output_file"] = output_file
    return domain_def


def validate_outputs(result):
    """Validate output domain definition."""
    errors = []
    if result["grid"]["nx"] < 2 or result["grid"]["ny"] < 2:
        errors.append(f"Grid too small: {result['grid']['nx']}x{result['grid']['ny']}")
    if result["grid"]["nx"] * result["grid"]["ny"] > 1e7:
        errors.append(
            f"WARNING: {result['total_cells']} total cells may require HPC resources"
        )
    if result["grid"]["total_depth_m"] < 1:
        errors.append("Total subsurface depth < 1m -- too shallow for most applications")
    return errors


def main():
    parser = argparse.ArgumentParser(
        description="Define ParFlow 3D computational domain from basin shapefile + DEM"
    )
    parser.add_argument("--shp_path", required=True, help="Basin boundary shapefile")
    parser.add_argument("--dem_path", default=None, help="DEM raster (GeoTIFF)")
    parser.add_argument("--resolution", type=float, default=1000, help="Grid cell size (m)")
    parser.add_argument("--nz", type=int, default=10, help="Number of vertical layers")
    parser.add_argument("--dz_layers", type=float, nargs="+", default=None,
                        help="Layer thicknesses bottom-to-top (m)")
    parser.add_argument("--output_dir", required=True, help="Output directory")
    parser.add_argument("--buffer_m", type=float, default=0, help="Domain buffer (m)")
    parser.add_argument("--no_terrain_following", action="store_true",
                        help="Disable terrain-following grid")
    args = parser.parse_args()

    # Validate inputs
    errs = validate_inputs(args.shp_path, args.dem_path, args.resolution, args.nz)
    if errs:
        print(json.dumps({"status": "error", "errors": errs}))
        sys.exit(1)

    # Process
    result = process(
        shp_path=args.shp_path,
        dem_path=args.dem_path,
        resolution=args.resolution,
        nz=args.nz,
        dz_layers=args.dz_layers,
        output_dir=args.output_dir,
        buffer_m=args.buffer_m,
        terrain_following=not args.no_terrain_following,
    )

    # Validate outputs
    warnings = validate_outputs(result)
    if warnings:
        result["warnings"] = warnings

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
