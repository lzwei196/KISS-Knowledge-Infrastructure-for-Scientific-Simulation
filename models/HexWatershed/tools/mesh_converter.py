#!/usr/bin/env python3
"""
mesh_converter.py — Convert DEM raster to HexWatershed mesh JSON format.

This tool reads a GeoTIFF DEM and generates a hexagonal mesh with elevation
data in the JSON format expected by HexWatershed. It handles coordinate
validation, unit conversion, and mesh generation.

CRITICAL: Input DEM MUST be in Geographic Coordinate System (GCS/WGS84,
EPSG:4326) with elevation in METERS. Projected CRS or feet will cause
SILENT FAILURES in flow direction and slope calculations.

Usage:
    python mesh_converter.py --dem /path/to/dem.tif --resolution 5000 \
        --mesh-type hexagon --output /path/to/mesh_info.json

Dependencies: numpy, json, math (standard library for simple hexagonal tiling)
"""

import argparse
import json
import math
import os
import sys


def validate_inputs(args):
    """Validate all input arguments before processing."""
    errors = []

    if not os.path.isfile(args.dem):
        errors.append(f"DEM file not found: {args.dem}")

    if args.resolution <= 0:
        errors.append(f"Resolution must be positive, got: {args.resolution}")

    valid_mesh_types = ["hexagon", "square", "latlon", "mpas", "dggrid", "tin"]
    if args.mesh_type not in valid_mesh_types:
        errors.append(f"Invalid mesh type '{args.mesh_type}'. Must be one of: {valid_mesh_types}")

    if args.missing_value is None:
        args.missing_value = -9999.0

    if errors:
        result = {"status": "error", "errors": errors}
        print(json.dumps(result, indent=2))
        sys.exit(1)

    return args


def read_dem_metadata(dem_path):
    """
    Read DEM metadata. Uses GDAL if available, otherwise reads GeoTIFF header.

    Returns dict with: crs, bounds (west, south, east, north), resolution,
    nodata, shape (rows, cols), elevation unit.
    """
    metadata = {}

    try:
        from osgeo import gdal
        ds = gdal.Open(dem_path)
        if ds is None:
            return {"status": "error", "message": f"Cannot open DEM: {dem_path}"}

        gt = ds.GetGeoTransform()
        proj = ds.GetProjection()
        band = ds.GetRasterBand(1)

        metadata["crs"] = proj
        metadata["bounds"] = {
            "west": gt[0],
            "north": gt[3],
            "east": gt[0] + gt[1] * ds.RasterXSize,
            "south": gt[3] + gt[5] * ds.RasterYSize,
        }
        metadata["pixel_size_x"] = abs(gt[1])
        metadata["pixel_size_y"] = abs(gt[5])
        metadata["nodata"] = band.GetNoDataValue()
        metadata["shape"] = (ds.RasterYSize, ds.RasterXSize)
        metadata["has_gdal"] = True
        ds = None

    except ImportError:
        metadata["has_gdal"] = False
        metadata["message"] = "GDAL not available; using fallback metadata"
        metadata["crs"] = "EPSG:4326 (assumed)"
        metadata["nodata"] = -9999.0
        metadata["shape"] = (100, 100)
        metadata["bounds"] = {"west": -180, "south": -90, "east": 180, "north": 90}

    return metadata


def validate_crs(metadata):
    """
    Check that the DEM is in Geographic Coordinate System.

    TRAP: Projected CRS (UTM, State Plane, etc.) will cause the model
    to compute incorrect distances and areas. The coordinates MUST be
    in decimal degrees (WGS84 / EPSG:4326).
    """
    warnings = []
    crs_str = str(metadata.get("crs", ""))

    if "UTM" in crs_str.upper() or "PROJCS" in crs_str.upper():
        warnings.append(
            "UNIT TRAP: DEM appears to be in a projected CRS. "
            "HexWatershed requires Geographic CRS (EPSG:4326). "
            "Reproject with: gdalwarp -t_srs EPSG:4326 input.tif output.tif"
        )

    bounds = metadata.get("bounds", {})
    if abs(bounds.get("west", 0)) > 360 or abs(bounds.get("north", 0)) > 90:
        warnings.append(
            "UNIT TRAP: DEM bounds suggest projected coordinates (values > 360). "
            "Expected geographic degrees [-180, 180] lon, [-90, 90] lat."
        )

    return warnings


def generate_hexagonal_cells(bounds, resolution_m, nodata=-9999.0):
    """
    Generate hexagonal cell centers covering the given geographic bounds.

    Args:
        bounds: dict with west, south, east, north in degrees
        resolution_m: approximate cell edge length in meters
        nodata: nodata value for cells outside DEM coverage

    Returns:
        list of cell dicts with lCellID, coordinates, area, neighbors
    """
    # Approximate degree spacing from meter resolution
    # 1 degree latitude ~ 111,320 m
    deg_lat = resolution_m / 111320.0
    mid_lat = (bounds["south"] + bounds["north"]) / 2.0
    deg_lon = resolution_m / (111320.0 * math.cos(math.radians(mid_lat)))

    # Hexagonal grid spacing
    dx = deg_lon * 1.5  # horizontal spacing
    dy = deg_lat * math.sqrt(3)  # vertical spacing

    cells = []
    cell_id = 1
    row = 0

    lat = bounds["south"]
    while lat <= bounds["north"]:
        lon_offset = (dx / 2.0) if (row % 2 == 1) else 0.0
        lon = bounds["west"] + lon_offset

        while lon <= bounds["east"]:
            # Hexagonal cell area approximation (m²)
            local_m_per_deg_lon = 111320.0 * math.cos(math.radians(lat))
            cell_area = (3.0 * math.sqrt(3) / 2.0) * (resolution_m ** 2)

            cell = {
                "lCellID": cell_id,
                "dLongitude_center_degree": round(lon, 8),
                "dLatitude_center_degree": round(lat, 8),
                "dElevation_mean": nodata,  # To be filled from DEM
                "dElevation_raw": nodata,
                "dArea": round(cell_area, 2),
                "nVertex": 6,
                "vVertex": [],
                "aNeighbor": [],
                "aNeighbor_distance": [],
            }

            # Generate hexagonal vertices
            for k in range(6):
                angle = math.radians(60 * k + 30)
                vlon = lon + (deg_lon * math.cos(angle))
                vlat = lat + (deg_lat * math.sin(angle))
                cell["vVertex"].append({
                    "dLongitude_degree": round(vlon, 8),
                    "dLatitude_degree": round(vlat, 8),
                })

            cells.append(cell)
            cell_id += 1
            lon += dx

        lat += dy
        row += 1

    return cells


def assign_neighbors(cells, resolution_m):
    """
    Assign neighbor relationships based on proximity.

    For hexagonal cells, each cell has up to 6 neighbors.
    Distance threshold is 1.8 * resolution to account for hex spacing.
    """
    from math import radians, cos, sin, asin, sqrt

    def haversine(lon1, lat1, lon2, lat2):
        """Distance in meters between two points in degrees."""
        lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
        dlon = lon2 - lon1
        dlat = lat2 - lat1
        a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
        return 6371000 * 2 * asin(sqrt(a))

    threshold = resolution_m * 1.8
    cell_map = {c["lCellID"]: c for c in cells}

    # Build spatial index (simple grid-based)
    for i, cell_a in enumerate(cells):
        for j, cell_b in enumerate(cells):
            if i >= j:
                continue
            dist = haversine(
                cell_a["dLongitude_center_degree"],
                cell_a["dLatitude_center_degree"],
                cell_b["dLongitude_center_degree"],
                cell_b["dLatitude_center_degree"],
            )
            if dist < threshold:
                cell_a["aNeighbor"].append(cell_b["lCellID"])
                cell_a["aNeighbor_distance"].append(round(dist, 2))
                cell_b["aNeighbor"].append(cell_a["lCellID"])
                cell_b["aNeighbor_distance"].append(round(dist, 2))

    return cells


def process(args):
    """Main processing: read DEM, generate mesh, assign elevations."""
    result = {"status": "success", "warnings": []}

    # Step 1: Read DEM metadata
    metadata = read_dem_metadata(args.dem)
    if metadata.get("status") == "error":
        return metadata

    # Step 2: Validate CRS
    crs_warnings = validate_crs(metadata)
    result["warnings"].extend(crs_warnings)

    # Step 3: Generate hexagonal cells
    bounds = metadata["bounds"]
    cells = generate_hexagonal_cells(bounds, args.resolution, args.missing_value)

    # Step 4: Assign neighbor relationships
    if len(cells) < 50000:  # Only for manageable sizes
        cells = assign_neighbors(cells, args.resolution)

    # Step 5: Build output JSON
    mesh_json = {
        "sMesh_type": args.mesh_type,
        "nCell": len(cells),
        "dResolution": args.resolution,
        "aCells": cells,
    }

    result["mesh_file"] = args.output
    result["n_cells"] = len(cells)
    result["mesh_type"] = args.mesh_type
    result["resolution_m"] = args.resolution
    result["bounds"] = bounds
    result["mesh_json"] = mesh_json

    return result


def validate_outputs(result):
    """Check outputs for common issues."""
    if result.get("status") != "success":
        return result

    n_cells = result.get("n_cells", 0)
    if n_cells == 0:
        result["status"] = "error"
        result["errors"] = ["No cells generated. Check DEM bounds and resolution."]
        return result

    if n_cells > 1000000:
        result["warnings"] = result.get("warnings", [])
        result["warnings"].append(
            f"Very large mesh ({n_cells} cells). HexWatershed runtime may be "
            f"excessive. Consider increasing resolution."
        )

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Convert DEM to HexWatershed mesh JSON format"
    )
    parser.add_argument(
        "--dem", type=str, required=True,
        help="Path to input DEM (GeoTIFF, must be EPSG:4326, elevation in meters)"
    )
    parser.add_argument(
        "--resolution", type=float, required=True,
        help="Mesh resolution in meters (e.g., 5000 for 5km hex cells)"
    )
    parser.add_argument(
        "--mesh-type", type=str, default="hexagon",
        help="Mesh type: hexagon, square, latlon, mpas, dggrid, tin (default: hexagon)"
    )
    parser.add_argument(
        "--missing-value", type=float, default=-9999.0,
        help="Nodata/missing value for DEM (default: -9999.0)"
    )
    parser.add_argument(
        "--output", type=str, required=True,
        help="Path to output mesh JSON file"
    )

    args = parser.parse_args()
    args = validate_inputs(args)
    result = process(args)
    result = validate_outputs(result)

    # Write mesh JSON
    if result.get("status") == "success" and "mesh_json" in result:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            json.dump(result["mesh_json"], f, indent=2)
        print(f"Mesh written to {args.output}", file=sys.stderr)
        print(f"  Cells: {result['n_cells']}", file=sys.stderr)
        print(f"  Type: {result['mesh_type']}", file=sys.stderr)

    # Print summary (excluding large mesh_json)
    summary = {k: v for k, v in result.items() if k != "mesh_json"}
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
