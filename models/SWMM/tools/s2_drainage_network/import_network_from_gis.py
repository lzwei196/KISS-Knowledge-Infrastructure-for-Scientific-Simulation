#!/usr/bin/env python3
"""
Import SWMM drainage network from GIS shapefiles.

Reads node points and pipe linestrings from shapefiles and converts them
to a SWMM-compatible JSON network definition. Auto-computes conduit lengths
from geometry and infers connectivity from spatial proximity.

Inputs:
  - Nodes shapefile (points): must have 'id' and 'invert_elev' attributes
  - Pipes shapefile (lines): must have 'id', 'roughness', 'shape', 'geom1' attributes
    (from_node/to_node can be attributes, or inferred from endpoint proximity)

Outputs:
  - JSON file with junctions, conduits, outfalls
"""

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np


def find_nearest_node(point, nodes, tolerance=1.0):
    """Find the nearest node to a point within tolerance distance."""
    min_dist = float("inf")
    nearest = None
    px, py = point

    for node in nodes:
        dist = np.sqrt((node["x"] - px) ** 2 + (node["y"] - py) ** 2)
        if dist < min_dist and dist <= tolerance:
            min_dist = dist
            nearest = node["id"]

    return nearest, min_dist


def main():
    parser = argparse.ArgumentParser(
        description="Import SWMM drainage network from GIS shapefiles"
    )
    parser.add_argument("--nodes_shp", required=True,
                        help="Nodes shapefile (points with id, invert_elev)")
    parser.add_argument("--pipes_shp", required=True,
                        help="Pipes shapefile (lines with id, roughness, shape, geom1)")
    parser.add_argument("--output", required=True, help="Output JSON path")
    parser.add_argument("--snap_tolerance", type=float, default=1.0,
                        help="Max distance (CRS units) to snap pipe endpoints to nodes")
    parser.add_argument("--outfall_attr", default="type",
                        help="Node attribute indicating outfall (value='OUTFALL')")
    args = parser.parse_args()

    for fpath in [args.nodes_shp, args.pipes_shp]:
        if not os.path.isfile(fpath):
            print(f"ERROR: File not found: {fpath}", file=sys.stderr)
            sys.exit(1)

    try:
        import geopandas as gpd
    except ImportError:
        print("ERROR: geopandas required. Install with: pip install geopandas",
              file=sys.stderr)
        sys.exit(1)

    # Read nodes
    print(f"Reading nodes from {args.nodes_shp}...")
    nodes_gdf = gpd.read_file(args.nodes_shp)
    print(f"  Found {len(nodes_gdf)} nodes")

    junctions = []
    outfalls = []
    all_nodes = []

    for idx, row in nodes_gdf.iterrows():
        node_id = str(row.get("id", row.get("ID", f"J{idx}")))
        invert_elev = float(row.get("invert_elev", row.get("INVERT_EL", 0.0)))
        max_depth = float(row.get("max_depth", row.get("MAX_DEPTH", 2.0)))
        x = row.geometry.x
        y = row.geometry.y
        node_type = str(row.get(args.outfall_attr, row.get("TYPE", "JUNCTION"))).upper()

        node_info = {
            "id": node_id,
            "invert_elev": invert_elev,
            "x": x,
            "y": y,
        }
        all_nodes.append(node_info)

        if node_type == "OUTFALL":
            outfalls.append({
                "id": node_id,
                "invert_elev": invert_elev,
                "type": str(row.get("outfall_type", "FREE")).upper(),
                "stage_data": "",
                "gated": "NO",
                "x": x,
                "y": y,
            })
        else:
            junctions.append({
                "id": node_id,
                "invert_elev": invert_elev,
                "max_depth": max_depth,
                "init_depth": 0.0,
                "surcharge_depth": 0.0,
                "ponded_area": 0.0,
                "x": x,
                "y": y,
            })

    # Read pipes
    print(f"Reading pipes from {args.pipes_shp}...")
    pipes_gdf = gpd.read_file(args.pipes_shp)
    print(f"  Found {len(pipes_gdf)} pipes")

    conduits = []
    unsnapped = 0

    for idx, row in pipes_gdf.iterrows():
        pipe_id = str(row.get("id", row.get("ID", f"C{idx}")))
        geom = row.geometry

        # Compute length from geometry
        if hasattr(geom, "length"):
            length = geom.length
            # Convert from degrees to meters if needed
            if length < 1:  # likely geographic CRS
                mid_lat = (geom.bounds[1] + geom.bounds[3]) / 2
                length_m = length * 111320 * np.cos(np.radians(mid_lat))
            else:
                length_m = length
        else:
            length_m = float(row.get("length", 100.0))

        # Get from/to nodes from attributes or snap endpoints
        from_node = str(row.get("from_node", row.get("FROM_NODE", ""))).strip()
        to_node = str(row.get("to_node", row.get("TO_NODE", ""))).strip()

        if not from_node:
            start_pt = (geom.coords[0][0], geom.coords[0][1])
            from_node, dist = find_nearest_node(start_pt, all_nodes, args.snap_tolerance)
            if from_node is None:
                print(f"WARNING: Pipe {pipe_id} start point could not snap to any node",
                      file=sys.stderr)
                unsnapped += 1
                continue

        if not to_node:
            end_pt = (geom.coords[-1][0], geom.coords[-1][1])
            to_node, dist = find_nearest_node(end_pt, all_nodes, args.snap_tolerance)
            if to_node is None:
                print(f"WARNING: Pipe {pipe_id} end point could not snap to any node",
                      file=sys.stderr)
                unsnapped += 1
                continue

        conduits.append({
            "id": pipe_id,
            "from_node": from_node,
            "to_node": to_node,
            "length": round(max(length_m, 0.1), 3),
            "roughness": float(row.get("roughness", row.get("ROUGHNESS", 0.013))),
            "shape": str(row.get("shape", row.get("SHAPE_", "CIRCULAR"))).upper(),
            "geom1": float(row.get("geom1", row.get("GEOM1", 0.6))),
            "geom2": float(row.get("geom2", row.get("GEOM2", 0.0))),
            "geom3": float(row.get("geom3", row.get("GEOM3", 0.0))),
            "geom4": float(row.get("geom4", row.get("GEOM4", 0.0))),
            "in_offset": float(row.get("in_offset", 0.0)),
            "out_offset": float(row.get("out_offset", 0.0)),
        })

    # Output
    network = {
        "junctions": junctions,
        "conduits": conduits,
        "outfalls": outfalls,
        "metadata": {
            "n_junctions": len(junctions),
            "n_conduits": len(conduits),
            "n_outfalls": len(outfalls),
            "n_unsnapped": unsnapped,
            "snap_tolerance": args.snap_tolerance,
            "source_nodes_shp": os.path.basename(args.nodes_shp),
            "source_pipes_shp": os.path.basename(args.pipes_shp),
        },
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(network, f, indent=2)

    print(f"\nNetwork imported: {output_path}")
    print(f"  Junctions: {len(junctions)}, Conduits: {len(conduits)}, "
          f"Outfalls: {len(outfalls)}")
    if unsnapped:
        print(f"  WARNING: {unsnapped} pipes could not be snapped to nodes")


if __name__ == "__main__":
    main()
