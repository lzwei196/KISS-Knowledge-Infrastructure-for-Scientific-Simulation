#!/usr/bin/env python3
"""
parse_forefire_output.py — Extract fire perimeters from ForeFire output.

Parses ForeFire output files (KML, GeoJSON, NetCDF, .ff text) and extracts
fire front perimeters to CSV or GeoJSON for analysis.

Output formats:
  - CSV: timestamp, node_id, x, y, z, velocity
  - GeoJSON: MultiPolygon per timestep
  - Burning map from NetCDF: arrival time at each grid cell

CRITICAL NOTES:
  - Coordinates are in UTM meters, not lon/lat.
  - Time is in seconds from domain start (t=0), not absolute time.
  - Burning map values: arrival time in seconds (0 = never burned, positive = burn time).
  - The .ff text output contains full node state including velocity vectors.

Usage:
    python parse_forefire_output.py \\
        --input ForeFire.0.nc \\
        --format netcdf \\
        --output fire_perimeters.csv

    python parse_forefire_output.py \\
        --input simulation_result.geojson \\
        --format geojson \\
        --output fire_perimeters.csv

    python parse_forefire_output.py \\
        --input real_case.kml \\
        --format kml \\
        --output fire_perimeters.csv
"""

import argparse
import csv
import json
import os
import re
import sys
from pathlib import Path

import numpy as np


def validate_inputs(args):
    """Validate input arguments."""
    errors = []

    if not os.path.isfile(args.input):
        errors.append(f"Input file not found: {args.input}")

    valid_formats = ["netcdf", "kml", "geojson", "ff"]
    if args.format not in valid_formats:
        errors.append(f"Format must be one of {valid_formats}, got: {args.format}")

    # Auto-detect format from extension
    if args.format == "auto":
        ext = Path(args.input).suffix.lower()
        fmt_map = {".nc": "netcdf", ".kml": "kml", ".geojson": "geojson", ".ff": "ff"}
        if ext in fmt_map:
            args.format = fmt_map[ext]
        else:
            errors.append(f"Cannot auto-detect format for extension: {ext}")

    if errors:
        for e in errors:
            print(f"VALIDATION ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"Input validation passed. Format: {args.format}")


def parse_netcdf(filepath):
    """Parse ForeFire NetCDF output to extract burning map and perimeters."""
    try:
        import netCDF4
    except ImportError:
        print("ERROR: netCDF4 required. Install with: pip install netCDF4", file=sys.stderr)
        sys.exit(1)

    ds = netCDF4.Dataset(filepath, 'r')
    results = {"type": "netcdf", "variables": list(ds.variables.keys())}

    # Look for burning map / arrival time
    bmap_names = ["arrival_time", "bmap", "BMap", "burningMap", "fuel"]
    for name in bmap_names:
        if name in ds.variables:
            results["burning_map"] = ds[name][:].data
            results["burning_map_var"] = name
            break

    # Extract coordinate info
    for xname in ["XHAT", "x", "lon", "longitude"]:
        if xname in ds.variables:
            results["x_coords"] = ds[xname][:].data
            break
    for yname in ["YHAT", "y", "lat", "latitude"]:
        if yname in ds.variables:
            results["y_coords"] = ds[yname][:].data
            break

    # Get all variable statistics
    stats = {}
    for vname in ds.variables:
        try:
            data = ds[vname][:]
            stats[vname] = {
                "shape": list(data.shape),
                "min": float(np.nanmin(data)),
                "max": float(np.nanmax(data)),
                "mean": float(np.nanmean(data)),
            }
        except Exception:
            stats[vname] = {"shape": list(ds[vname].shape)}
    results["stats"] = stats

    ds.close()
    return results


def parse_geojson(filepath):
    """Parse GeoJSON output to extract fire perimeters."""
    with open(filepath) as f:
        data = json.load(f)

    features = data.get("features", [])
    results = {"type": "geojson", "n_features": len(features), "perimeters": []}

    for feat in features:
        geom = feat.get("geometry", {})
        props = feat.get("properties", {})
        coords = geom.get("coordinates", [])
        timestamp = props.get("time", props.get("t", None))

        if geom["type"] in ("Polygon", "MultiPolygon"):
            flat_coords = []
            if geom["type"] == "Polygon":
                for ring in coords:
                    flat_coords.extend(ring)
            else:
                for poly in coords:
                    for ring in poly:
                        flat_coords.extend(ring)

            results["perimeters"].append({
                "timestamp": timestamp,
                "n_points": len(flat_coords),
                "coords": flat_coords,
                "properties": props,
            })

    return results


def parse_kml(filepath):
    """Parse KML output to extract fire perimeters."""
    try:
        from lxml import etree
    except ImportError:
        # Fallback to regex parsing
        return parse_kml_regex(filepath)

    tree = etree.parse(filepath)
    ns = {"kml": "http://www.opengis.net/kml/2.2"}
    placemarks = tree.findall(".//kml:Placemark", ns)

    results = {"type": "kml", "n_placemarks": len(placemarks), "perimeters": []}

    for pm in placemarks:
        name = pm.find("kml:name", ns)
        coords_elem = pm.find(".//kml:coordinates", ns)
        if coords_elem is not None and coords_elem.text:
            coord_text = coords_elem.text.strip()
            points = []
            for pt in coord_text.split():
                parts = pt.split(",")
                if len(parts) >= 2:
                    points.append([float(parts[0]), float(parts[1]),
                                   float(parts[2]) if len(parts) > 2 else 0.0])
            results["perimeters"].append({
                "name": name.text if name is not None else "",
                "n_points": len(points),
                "coords": points,
            })

    return results


def parse_kml_regex(filepath):
    """Fallback KML parser using regex."""
    with open(filepath) as f:
        content = f.read()

    results = {"type": "kml_regex", "perimeters": []}
    coord_blocks = re.findall(r"<coordinates>(.*?)</coordinates>", content, re.DOTALL)

    for block in coord_blocks:
        points = []
        for pt in block.strip().split():
            parts = pt.strip().split(",")
            if len(parts) >= 2:
                points.append([float(parts[0]), float(parts[1]),
                               float(parts[2]) if len(parts) > 2 else 0.0])
        if points:
            results["perimeters"].append({"n_points": len(points), "coords": points})

    results["n_placemarks"] = len(results["perimeters"])
    return results


def parse_ff_text(filepath):
    """Parse ForeFire text output (print[] format)."""
    with open(filepath) as f:
        content = f.read()

    results = {"type": "ff_text", "nodes": [], "fronts": []}

    # Parse FireNode entries
    node_pattern = r"FireNode\[.*?loc=\(([^)]+)\).*?vel=\(([^)]+)\).*?t=([0-9.]+)"
    for match in re.finditer(node_pattern, content):
        loc = [float(x) for x in match.group(1).split(",")]
        vel = [float(x) for x in match.group(2).split(",")]
        t = float(match.group(3))
        results["nodes"].append({"loc": loc, "vel": vel, "t": t})

    # Parse FireFront entries
    front_pattern = r"FireFront\[.*?t=([0-9.]+)"
    for match in re.finditer(front_pattern, content):
        t = float(match.group(1))
        results["fronts"].append({"t": t})

    return results


def to_csv(results, output_path):
    """Write parsed results to CSV."""
    with open(output_path, 'w', newline='') as f:
        writer = csv.writer(f)

        if results["type"] == "ff_text":
            writer.writerow(["time_s", "x", "y", "z", "vx", "vy", "vz"])
            for node in results["nodes"]:
                writer.writerow([
                    node["t"],
                    node["loc"][0], node["loc"][1],
                    node["loc"][2] if len(node["loc"]) > 2 else 0,
                    node["vel"][0], node["vel"][1],
                    node["vel"][2] if len(node["vel"]) > 2 else 0,
                ])
        elif "perimeters" in results:
            writer.writerow(["perimeter_id", "timestamp", "point_idx", "x", "y", "z"])
            for pid, perim in enumerate(results["perimeters"]):
                ts = perim.get("timestamp", perim.get("name", pid))
                for i, coord in enumerate(perim["coords"]):
                    writer.writerow([pid, ts, i, coord[0], coord[1],
                                     coord[2] if len(coord) > 2 else 0])
        elif "burning_map" in results:
            bmap = results["burning_map"]
            writer.writerow(["row", "col", "arrival_time_s"])
            if bmap.ndim >= 2:
                data = bmap[-1, -1] if bmap.ndim == 4 else bmap[-1] if bmap.ndim == 3 else bmap
                for i in range(data.shape[0]):
                    for j in range(data.shape[1]):
                        if data[i, j] > 0:
                            writer.writerow([i, j, data[i, j]])

    print(f"CSV written: {output_path}")


def process(args):
    """Main processing: parse input and write output."""
    fmt = args.format
    print(f"Parsing {fmt}: {args.input}")

    if fmt == "netcdf":
        results = parse_netcdf(args.input)
    elif fmt == "geojson":
        results = parse_geojson(args.input)
    elif fmt == "kml":
        results = parse_kml(args.input)
    elif fmt == "ff":
        results = parse_ff_text(args.input)
    else:
        print(f"ERROR: Unknown format: {fmt}", file=sys.stderr)
        sys.exit(1)

    # Print summary
    print(f"Parse type: {results['type']}")
    if "perimeters" in results:
        print(f"Perimeters found: {len(results['perimeters'])}")
        for i, p in enumerate(results["perimeters"]):
            print(f"  [{i}] {p.get('timestamp', p.get('name', ''))} — {p['n_points']} points")
    if "nodes" in results:
        print(f"Fire nodes: {len(results['nodes'])}")
    if "burning_map" in results:
        bmap = results["burning_map"]
        print(f"Burning map shape: {bmap.shape}")
        burned = np.sum(bmap > 0)
        print(f"Burned cells: {burned}")
    if "stats" in results:
        for vname, s in results["stats"].items():
            print(f"  {vname}: shape={s['shape']}, range=[{s.get('min', '?'):.2f}, {s.get('max', '?'):.2f}]")

    # Write CSV output
    to_csv(results, args.output)
    return results


def validate_outputs(output_path):
    """Validate the output CSV."""
    if not os.path.isfile(output_path):
        print(f"OUTPUT ERROR: File not created: {output_path}", file=sys.stderr)
        return False

    size = os.path.getsize(output_path)
    if size == 0:
        print(f"OUTPUT ERROR: File is empty: {output_path}", file=sys.stderr)
        return False

    with open(output_path) as f:
        reader = csv.reader(f)
        n_rows = sum(1 for _ in reader) - 1  # Subtract header

    print(f"Output validation passed: {n_rows} data rows, {size} bytes")
    return True


def main():
    parser = argparse.ArgumentParser(description="Parse ForeFire output files")
    parser.add_argument("--input", required=True, help="Input file path")
    parser.add_argument("--format", default="auto", choices=["netcdf", "kml", "geojson", "ff", "auto"],
                        help="Input format")
    parser.add_argument("--output", default="fire_perimeters.csv", help="Output CSV path")
    args = parser.parse_args()

    validate_inputs(args)
    process(args)
    validate_outputs(args.output)


if __name__ == "__main__":
    main()
