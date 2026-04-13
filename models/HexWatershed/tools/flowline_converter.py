#!/usr/bin/env python3
"""
flowline_converter.py — Convert NHD/HydroSHEDS flowlines to HexWatershed basin JSON.

This tool reads flowline data (NHDPlus, HydroSHEDS, or generic shapefiles) and
produces the basin configuration JSON required by HexWatershed when stream
burning is enabled (iFlag_flowline=1).

CRITICAL: Flowline coordinates MUST be in Geographic Coordinate System (GCS/WGS84).
Projected flowlines will NOT intersect the mesh correctly, causing SILENT FAILURE
where stream burning produces no effect.

CRITICAL: The `lCellID_outlet` in the basin JSON must correspond to an actual cell
in the mesh JSON. Incorrect outlet IDs cause the entire watershed to be SILENTLY
SKIPPED with no error message.

Usage:
    python flowline_converter.py --flowline /path/to/nhd_flowlines.shp \
        --outlet-lat 39.5 --outlet-lon -76.2 \
        --basin-id 1 --output /path/to/basins.json

    python flowline_converter.py --flowline /path/to/flowlines.geojson \
        --outlet-lat 39.5 --outlet-lon -76.2 \
        --threshold-ratio 0.01 --output /path/to/basins.json
"""

import argparse
import json
import os
import sys


def validate_inputs(args):
    """Validate all input arguments before processing."""
    errors = []
    warnings = []

    if args.flowline and not os.path.isfile(args.flowline):
        errors.append(f"Flowline file not found: {args.flowline}")

    if args.outlet_lat is None or args.outlet_lon is None:
        errors.append("Outlet coordinates (--outlet-lat, --outlet-lon) are required")
    else:
        if abs(args.outlet_lat) > 90:
            errors.append(
                f"UNIT TRAP: Outlet latitude {args.outlet_lat} is outside [-90, 90]. "
                f"Coordinates must be in decimal degrees (GCS), not projected meters."
            )
        if abs(args.outlet_lon) > 180:
            errors.append(
                f"UNIT TRAP: Outlet longitude {args.outlet_lon} is outside [-180, 180]. "
                f"Coordinates must be in decimal degrees (GCS), not projected meters."
            )

    if args.threshold_ratio is not None:
        if args.threshold_ratio <= 0 or args.threshold_ratio >= 1.0:
            warnings.append(
                f"Threshold ratio {args.threshold_ratio} outside typical range (0, 1). "
                f"Values < 0.001 produce very dense streams; > 0.1 very sparse."
            )

    if args.basin_id is not None and args.basin_id <= 0:
        errors.append(f"Basin ID must be positive, got: {args.basin_id}")

    if errors:
        result = {"status": "error", "errors": errors, "warnings": warnings}
        print(json.dumps(result, indent=2))
        sys.exit(1)

    return args, warnings


def read_flowline_geojson(filepath):
    """Read flowline from GeoJSON file."""
    with open(filepath, "r") as f:
        data = json.load(f)

    features = data.get("features", [])
    flowlines = []

    for feat in features:
        geom = feat.get("geometry", {})
        props = feat.get("properties", {})

        if geom.get("type") in ("LineString", "MultiLineString"):
            coords = geom.get("coordinates", [])
            flowlines.append({
                "coordinates": coords,
                "properties": props,
                "type": geom["type"],
            })

    return flowlines


def read_flowline_shapefile(filepath):
    """Read flowline from shapefile using OGR if available."""
    try:
        from osgeo import ogr
        ds = ogr.Open(filepath)
        if ds is None:
            return {"status": "error", "message": f"Cannot open shapefile: {filepath}"}

        layer = ds.GetLayer(0)
        flowlines = []

        for feature in layer:
            geom = feature.GetGeometryRef()
            if geom is None:
                continue

            geojson = json.loads(geom.ExportToJson())
            props = {}
            for i in range(feature.GetFieldCount()):
                props[feature.GetFieldDefnRef(i).GetName()] = feature.GetField(i)

            flowlines.append({
                "coordinates": geojson.get("coordinates", []),
                "properties": props,
                "type": geojson.get("type", "LineString"),
            })

        ds = None
        return flowlines

    except ImportError:
        return {"status": "error", "message": "GDAL/OGR not available for shapefile reading"}


def validate_flowline_crs(flowlines):
    """
    Check that flowline coordinates are in geographic degrees.

    TRAP: If any coordinate exceeds 360 in absolute value, the flowlines
    are likely in a projected CRS. HexWatershed will silently fail to
    match flowlines to mesh cells.
    """
    warnings = []

    for fl in flowlines[:10]:  # Check first 10
        coords = fl.get("coordinates", [])
        flat_coords = []

        if fl["type"] == "LineString":
            flat_coords = coords
        elif fl["type"] == "MultiLineString":
            for line in coords:
                flat_coords.extend(line)

        for coord in flat_coords[:5]:
            if len(coord) >= 2:
                lon, lat = coord[0], coord[1]
                if abs(lon) > 360 or abs(lat) > 90:
                    warnings.append(
                        f"UNIT TRAP: Flowline coordinate ({lon}, {lat}) suggests "
                        f"projected CRS. Must be GCS degrees. Reproject with: "
                        f"ogr2ogr -t_srs EPSG:4326 output.shp input.shp"
                    )
                    return warnings

    return warnings


def find_nearest_cell_id(mesh_json_path, outlet_lat, outlet_lon):
    """
    Find the mesh cell nearest to the given outlet coordinates.

    Returns the lCellID of the nearest cell. This is CRITICAL because
    an incorrect lCellID_outlet causes the entire watershed to be silently skipped.
    """
    if mesh_json_path and os.path.isfile(mesh_json_path):
        import math

        with open(mesh_json_path, "r") as f:
            mesh = json.load(f)

        cells = mesh.get("aCells", [])
        min_dist = float("inf")
        nearest_id = -1

        for cell in cells:
            dlat = cell["dLatitude_center_degree"] - outlet_lat
            dlon = cell["dLongitude_center_degree"] - outlet_lon
            dist = math.sqrt(dlat ** 2 + dlon ** 2)
            if dist < min_dist:
                min_dist = dist
                nearest_id = cell["lCellID"]

        return nearest_id, min_dist

    return -1, -1.0


def process(args, input_warnings):
    """Build basin configuration JSON from flowline data."""
    result = {"status": "success", "warnings": list(input_warnings)}

    flowlines = []
    if args.flowline:
        ext = os.path.splitext(args.flowline)[1].lower()
        if ext in (".geojson", ".json"):
            flowlines = read_flowline_geojson(args.flowline)
        elif ext == ".shp":
            flowlines = read_flowline_shapefile(args.flowline)
            if isinstance(flowlines, dict) and flowlines.get("status") == "error":
                return flowlines
        else:
            result["warnings"].append(
                f"Unknown flowline format '{ext}'. Trying GeoJSON parser."
            )
            flowlines = read_flowline_geojson(args.flowline)

        crs_warnings = validate_flowline_crs(flowlines)
        result["warnings"].extend(crs_warnings)

    # Find nearest cell to outlet
    outlet_cell_id = args.outlet_cell_id or -1
    if outlet_cell_id <= 0 and args.mesh_json:
        outlet_cell_id, dist = find_nearest_cell_id(
            args.mesh_json, args.outlet_lat, args.outlet_lon
        )
        if outlet_cell_id > 0:
            result["outlet_cell_distance_deg"] = dist
        else:
            result["warnings"].append(
                "Could not find outlet cell in mesh. Set --outlet-cell-id manually."
            )

    # Build basin configuration
    basin = {
        "lBasinID": args.basin_id or 1,
        "lCellID_outlet": outlet_cell_id,
        "dLatitude_outlet_degree": args.outlet_lat,
        "dLongitude_outlet_degree": args.outlet_lon,
        "dAccumulation_threshold_ratio": args.threshold_ratio or 0.01,
        "dThreshold_small_river": args.small_river_threshold or 0.0,
        "iFlag_dam": 0,
        "iFlag_disconnected": 0,
    }

    if args.flowline:
        basin["sFilename_flowline_raw"] = os.path.abspath(args.flowline)

    basins_json = [basin]

    result["basins"] = basins_json
    result["n_basins"] = len(basins_json)
    result["n_flowlines"] = len(flowlines)
    result["outlet_cell_id"] = outlet_cell_id

    return result


def validate_outputs(result):
    """Check outputs for common issues."""
    if result.get("status") != "success":
        return result

    if result.get("outlet_cell_id", -1) <= 0:
        result["warnings"] = result.get("warnings", [])
        result["warnings"].append(
            "WARNING: Outlet cell ID is not set or invalid. "
            "The watershed will be SILENTLY SKIPPED by HexWatershed. "
            "Provide --outlet-cell-id or --mesh-json to auto-detect."
        )

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Convert flowlines to HexWatershed basin configuration JSON"
    )
    parser.add_argument(
        "--flowline", type=str, default=None,
        help="Path to flowline file (GeoJSON or Shapefile)"
    )
    parser.add_argument(
        "--outlet-lat", type=float, required=True,
        help="Outlet latitude in decimal degrees (GCS)"
    )
    parser.add_argument(
        "--outlet-lon", type=float, required=True,
        help="Outlet longitude in decimal degrees (GCS)"
    )
    parser.add_argument(
        "--basin-id", type=int, default=1,
        help="Basin identifier (default: 1)"
    )
    parser.add_argument(
        "--outlet-cell-id", type=int, default=None,
        help="Outlet cell ID from mesh (if known)"
    )
    parser.add_argument(
        "--mesh-json", type=str, default=None,
        help="Path to mesh JSON to auto-detect outlet cell ID"
    )
    parser.add_argument(
        "--threshold-ratio", type=float, default=0.01,
        help="Accumulation threshold ratio for stream definition (default: 0.01)"
    )
    parser.add_argument(
        "--small-river-threshold", type=float, default=0.0,
        help="Threshold to remove small rivers (default: 0.0 = keep all)"
    )
    parser.add_argument(
        "--output", type=str, required=True,
        help="Path to output basin configuration JSON"
    )

    args = parser.parse_args()
    args, input_warnings = validate_inputs(args)
    result = process(args, input_warnings)
    result = validate_outputs(result)

    if result.get("status") == "success" and "basins" in result:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            json.dump(result["basins"], f, indent=2)
        print(f"Basin config written to {args.output}", file=sys.stderr)
        print(f"  Basins: {result['n_basins']}", file=sys.stderr)
        print(f"  Flowlines: {result['n_flowlines']}", file=sys.stderr)

    summary = {k: v for k, v in result.items() if k != "basins"}
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
