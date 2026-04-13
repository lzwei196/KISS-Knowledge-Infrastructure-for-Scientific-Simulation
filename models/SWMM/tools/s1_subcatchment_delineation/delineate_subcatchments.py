#!/usr/bin/env python3
"""
Delineate SWMM subcatchments from DEM and drainage node locations.

Uses Voronoi tessellation (scipy + geopandas) to partition a basin into
subcatchment polygons, each draining to one junction node. Computes basic
geometric parameters (area, centroid, connection node) and writes a
subcatchment shapefile plus a parameter CSV for model assembly.

Inputs:
  - DEM raster (GeoTIFF) for slope/elevation context
  - Drainage node CSV (id, x, y, invert_elev)
  - Optional basin boundary shapefile to clip Voronoi polygons

Outputs:
  - Subcatchment shapefile (<output_dir>/subcatchments.shp)
  - Parameter CSV (<output_dir>/subcatchment_params.csv)
"""

import argparse
import csv
import json
import os
import sys
from pathlib import Path

import numpy as np


def read_nodes_csv(csv_path):
    """Read drainage node locations from CSV."""
    nodes = []
    with open(csv_path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            nodes.append({
                "id": row["id"],
                "x": float(row["x"]),
                "y": float(row["y"]),
                "invert_elev": float(row.get("invert_elev", 0.0)),
            })
    if not nodes:
        raise ValueError(f"No nodes found in {csv_path}")
    return nodes


def voronoi_subcatchments(nodes, basin_boundary=None):
    """
    Generate Voronoi polygons from node points, optionally clipped
    to a basin boundary.

    Returns a list of dicts with 'id', 'geometry' (as WKT), 'area_ha',
    'centroid_x', 'centroid_y'.
    """
    try:
        import geopandas as gpd
        from scipy.spatial import Voronoi
        from shapely.geometry import Polygon, MultiPoint, box
        from shapely.ops import unary_union
    except ImportError as e:
        print(f"ERROR: Required package not installed: {e}", file=sys.stderr)
        print("Install with: pip install geopandas scipy shapely", file=sys.stderr)
        sys.exit(1)

    points = np.array([[n["x"], n["y"]] for n in nodes])

    if len(points) < 2:
        # Single node: the entire basin is one subcatchment
        if basin_boundary is not None:
            basin_gdf = gpd.read_file(basin_boundary)
            geom = basin_gdf.unary_union
        else:
            # Create a default bounding box around the single point
            buf = 0.01  # ~1 km at mid-latitudes
            geom = box(
                points[0][0] - buf, points[0][1] - buf,
                points[0][0] + buf, points[0][1] + buf,
            )
        area_m2 = geom.area  # in CRS units (degrees^2 if geographic)
        return [{
            "id": nodes[0]["id"],
            "geometry": geom,
            "area_ha": area_m2 * 1e4 if area_m2 < 1 else area_m2 / 1e4,
            "centroid_x": geom.centroid.x,
            "centroid_y": geom.centroid.y,
            "outlet": nodes[0]["id"],
        }]

    # Add far-away dummy points so Voronoi regions are bounded
    x_range = points[:, 0].max() - points[:, 0].min()
    y_range = points[:, 1].max() - points[:, 1].min()
    buffer = max(x_range, y_range) * 10
    cx, cy = points.mean(axis=0)
    far_points = np.array([
        [cx - buffer, cy - buffer],
        [cx + buffer, cy - buffer],
        [cx + buffer, cy + buffer],
        [cx - buffer, cy + buffer],
    ])
    all_points = np.vstack([points, far_points])

    vor = Voronoi(all_points)

    # Build polygons for each original node
    subcatchments = []
    for i, node in enumerate(nodes):
        region_idx = vor.point_region[i]
        region = vor.regions[region_idx]
        if -1 in region or len(region) == 0:
            print(f"WARNING: Node {node['id']} has unbounded Voronoi region, skipping",
                  file=sys.stderr)
            continue
        polygon = Polygon([vor.vertices[v] for v in region])

        # Clip to basin boundary if provided
        if basin_boundary is not None:
            basin_gdf = gpd.read_file(basin_boundary)
            basin_geom = basin_gdf.unary_union
            polygon = polygon.intersection(basin_geom)
            if polygon.is_empty:
                print(f"WARNING: Node {node['id']} subcatchment is empty after clipping",
                      file=sys.stderr)
                continue

        # Compute area (approximate: if CRS is geographic, area is in deg^2)
        area = polygon.area

        subcatchments.append({
            "id": f"S_{node['id']}",
            "geometry": polygon,
            "area_ha": area * 1e4 if area < 1 else area / 1e4,
            "centroid_x": polygon.centroid.x,
            "centroid_y": polygon.centroid.y,
            "outlet": node["id"],
        })

    return subcatchments


def write_outputs(subcatchments, output_dir):
    """Write subcatchment shapefile and parameter CSV."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Parameter CSV
    csv_path = output_dir / "subcatchment_params.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "id", "area_ha", "centroid_x", "centroid_y", "outlet",
        ])
        writer.writeheader()
        for sc in subcatchments:
            writer.writerow({
                "id": sc["id"],
                "area_ha": f"{sc['area_ha']:.4f}",
                "centroid_x": f"{sc['centroid_x']:.6f}",
                "centroid_y": f"{sc['centroid_y']:.6f}",
                "outlet": sc["outlet"],
            })
    print(f"Parameter CSV written: {csv_path}")

    # Shapefile
    try:
        import geopandas as gpd
        gdf = gpd.GeoDataFrame(
            [{"id": s["id"], "outlet": s["outlet"], "area_ha": s["area_ha"]}
             for s in subcatchments],
            geometry=[s["geometry"] for s in subcatchments],
        )
        shp_path = output_dir / "subcatchments.shp"
        gdf.to_file(shp_path)
        print(f"Shapefile written: {shp_path}")
    except ImportError:
        print("WARNING: geopandas not available, shapefile not written", file=sys.stderr)

    return csv_path


def main():
    parser = argparse.ArgumentParser(
        description="Delineate SWMM subcatchments via Voronoi tessellation"
    )
    parser.add_argument("--dem", required=True, help="DEM raster (GeoTIFF)")
    parser.add_argument("--nodes", required=True,
                        help="Drainage node CSV (columns: id, x, y, invert_elev)")
    parser.add_argument("--output_dir", required=True,
                        help="Output directory for shapefile and CSV")
    parser.add_argument("--basin_shp", default=None,
                        help="Basin boundary shapefile to clip subcatchments")
    args = parser.parse_args()

    if not os.path.isfile(args.dem):
        print(f"ERROR: DEM not found: {args.dem}", file=sys.stderr)
        sys.exit(1)
    if not os.path.isfile(args.nodes):
        print(f"ERROR: Nodes CSV not found: {args.nodes}", file=sys.stderr)
        sys.exit(1)
    if args.basin_shp and not os.path.isfile(args.basin_shp):
        print(f"ERROR: Basin shapefile not found: {args.basin_shp}", file=sys.stderr)
        sys.exit(1)

    print(f"Reading nodes from {args.nodes}...")
    nodes = read_nodes_csv(args.nodes)
    print(f"  Found {len(nodes)} nodes")

    print("Generating Voronoi subcatchments...")
    subcatchments = voronoi_subcatchments(nodes, args.basin_shp)
    print(f"  Generated {len(subcatchments)} subcatchments")

    csv_path = write_outputs(subcatchments, args.output_dir)
    print(f"\nDone. {len(subcatchments)} subcatchments delineated.")


if __name__ == "__main__":
    main()
