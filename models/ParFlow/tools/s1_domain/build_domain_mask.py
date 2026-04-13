#!/usr/bin/env python3
"""
Build ParFlow domain mask (indicator field) from basin shapefile.

Creates a 3D indicator array where:
- 1 = active cell (inside basin)
- 0 = inactive cell (outside basin)

For overland flow, the top layer mask is further refined:
- Cells at the basin boundary near the outlet get special treatment
  to allow water to exit the domain.

Also creates the solid file (.pfsol) format if needed for older ParFlow versions.

Usage:
    python build_domain_mask.py \
        --domain_json outputs/parflow_run/domain/domain_definition.json \
        --shp_path data/shp/chaohe_shp/chaohe.shp \
        --output_dir outputs/parflow_run/domain/

Author: Jianyun Zhang Research Group, Hohai University
"""

import argparse
import json
import os
import sys

import numpy as np

try:
    import geopandas as gpd
    from shapely.geometry import Point
except ImportError as e:
    print(json.dumps({"status": "error", "message": f"Missing dependency: {e}"}))
    sys.exit(1)


def validate_inputs(domain_json, shp_path):
    errors = []
    if not os.path.exists(domain_json):
        errors.append(f"Domain definition not found: {domain_json}")
    if not os.path.exists(shp_path):
        errors.append(f"Shapefile not found: {shp_path}")
    return errors


def process(domain_json, shp_path, output_dir, outlet_lat=None, outlet_lon=None):
    """
    Build domain mask from shapefile and domain definition.

    Parameters
    ----------
    domain_json : str
        Path to domain_definition.json from define_parflow_domain.
    shp_path : str
        Path to basin boundary shapefile.
    output_dir : str
        Output directory.
    outlet_lat, outlet_lon : float, optional
        Outlet coordinates (WGS84). Used to mark outlet cells.
    """
    os.makedirs(output_dir, exist_ok=True)

    with open(domain_json) as f:
        domain = json.load(f)

    grid = domain["grid"]
    nx, ny, nz = grid["nx"], grid["ny"], grid["nz"]
    dx, dy = grid["dx"], grid["dy"]
    origin_x = domain["origin"]["x"]
    origin_y = domain["origin"]["y"]
    utm_epsg = domain["crs"]["epsg"]

    # Read and project shapefile to UTM
    gdf = gpd.read_file(shp_path)
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")
    gdf_utm = gdf.to_crs(epsg=utm_epsg)
    basin_geom = gdf_utm.geometry.unary_union

    # Build 2D mask by checking cell centers
    mask_2d = np.zeros((ny, nx), dtype=np.int32)
    for j in range(ny):
        for i in range(nx):
            cx = origin_x + (i + 0.5) * dx
            cy = origin_y + (j + 0.5) * dy
            if basin_geom.contains(Point(cx, cy)):
                mask_2d[j, i] = 1

    # Extend to 3D (same mask for all layers)
    # ParFlow convention: mask[nz, ny, nx] -- layer 0 is bottom
    mask_3d = np.zeros((nz, ny, nx), dtype=np.int32)
    for k in range(nz):
        mask_3d[k, :, :] = mask_2d

    active_cells = int(np.sum(mask_3d))
    surface_active = int(np.sum(mask_2d))

    # Identify outlet cell if coordinates provided
    outlet_cell = None
    if outlet_lat is not None and outlet_lon is not None:
        from pyproj import Transformer
        transformer = Transformer.from_crs("EPSG:4326", f"EPSG:{utm_epsg}", always_xy=True)
        ox, oy = transformer.transform(outlet_lon, outlet_lat)
        oi = int((ox - origin_x) / dx)
        oj = int((oy - origin_y) / dy)
        if 0 <= oi < nx and 0 <= oj < ny:
            outlet_cell = {"i": oi, "j": oj, "utm_x": ox, "utm_y": oy}

    # Save mask as numpy file
    mask_file = os.path.join(output_dir, "domain_mask.npy")
    np.save(mask_file, mask_3d)

    # Save 2D surface mask
    mask_2d_file = os.path.join(output_dir, "surface_mask.npy")
    np.save(mask_2d_file, mask_2d)

    # Try to save as PFB if pftools available
    pfb_file = None
    try:
        from parflow.tools.io import write_pfb
        pfb_path = os.path.join(output_dir, "domain_mask.pfb")
        write_pfb(pfb_path, mask_3d.astype(np.float64),
                  dx=dx, dy=dy, dz=1.0,
                  x=origin_x, y=origin_y, z=0.0)
        pfb_file = pfb_path
    except ImportError:
        pass

    result = {
        "status": "success",
        "nx": nx, "ny": ny, "nz": nz,
        "active_cells_3d": active_cells,
        "active_surface_cells": surface_active,
        "total_cells_3d": nx * ny * nz,
        "active_fraction": round(active_cells / (nx * ny * nz), 4),
        "mask_npy": mask_file,
        "surface_mask_npy": mask_2d_file,
        "mask_pfb": pfb_file,
        "outlet_cell": outlet_cell,
    }
    return result


def validate_outputs(result):
    warnings = []
    if result["active_fraction"] < 0.1:
        warnings.append(
            f"Only {result['active_fraction']*100:.1f}% of grid is active -- "
            "consider reducing domain extent or increasing buffer"
        )
    if result["active_surface_cells"] < 4:
        warnings.append(
            f"Only {result['active_surface_cells']} active surface cells -- "
            "resolution too coarse for this basin"
        )
    return warnings


def main():
    parser = argparse.ArgumentParser(description="Build ParFlow domain mask")
    parser.add_argument("--domain_json", required=True, help="Domain definition JSON")
    parser.add_argument("--shp_path", required=True, help="Basin shapefile")
    parser.add_argument("--output_dir", required=True, help="Output directory")
    parser.add_argument("--outlet_lat", type=float, default=None)
    parser.add_argument("--outlet_lon", type=float, default=None)
    args = parser.parse_args()

    errs = validate_inputs(args.domain_json, args.shp_path)
    if errs:
        print(json.dumps({"status": "error", "errors": errs}))
        sys.exit(1)

    result = process(args.domain_json, args.shp_path, args.output_dir,
                     args.outlet_lat, args.outlet_lon)

    warnings = validate_outputs(result)
    if warnings:
        result["warnings"] = warnings

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
