#!/usr/bin/env python3
"""
Create a SWMM drainage network from CSV specifications.

Reads junctions, conduits, and outfalls from CSV files and produces a
JSON network definition suitable for model assembly. Validates basic
connectivity and geometry.

CSV column formats:
  - junctions: id, invert_elev, max_depth, x, y
  - conduits: id, from_node, to_node, length, roughness, shape, geom1 [, geom2, geom3, geom4]
  - outfalls: id, invert_elev, type [, x, y]

Outputs:
  - JSON file with junctions, conduits, outfalls, and metadata
"""

import argparse
import csv
import json
import os
import sys
from pathlib import Path


def read_junctions(csv_path):
    """Read junction definitions from CSV."""
    junctions = []
    with open(csv_path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            junctions.append({
                "id": row["id"].strip(),
                "invert_elev": float(row["invert_elev"]),
                "max_depth": float(row.get("max_depth", 2.0)),
                "init_depth": float(row.get("init_depth", 0.0)),
                "surcharge_depth": float(row.get("surcharge_depth", 0.0)),
                "ponded_area": float(row.get("ponded_area", 0.0)),
                "x": float(row.get("x", 0.0)),
                "y": float(row.get("y", 0.0)),
            })
    return junctions


def read_conduits(csv_path):
    """Read conduit definitions from CSV."""
    conduits = []
    with open(csv_path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            conduit = {
                "id": row["id"].strip(),
                "from_node": row["from_node"].strip(),
                "to_node": row["to_node"].strip(),
                "length": float(row["length"]),
                "roughness": float(row.get("roughness", 0.013)),
                "shape": row.get("shape", "CIRCULAR").strip().upper(),
                "geom1": float(row.get("geom1", 0.6)),
                "geom2": float(row.get("geom2", 0.0)),
                "geom3": float(row.get("geom3", 0.0)),
                "geom4": float(row.get("geom4", 0.0)),
                "in_offset": float(row.get("in_offset", 0.0)),
                "out_offset": float(row.get("out_offset", 0.0)),
            }
            conduits.append(conduit)
    return conduits


def read_outfalls(csv_path):
    """Read outfall definitions from CSV."""
    outfalls = []
    with open(csv_path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            outfalls.append({
                "id": row["id"].strip(),
                "invert_elev": float(row["invert_elev"]),
                "type": row.get("type", "FREE").strip().upper(),
                "stage_data": row.get("stage_data", ""),
                "gated": row.get("gated", "NO").strip().upper(),
                "x": float(row.get("x", 0.0)),
                "y": float(row.get("y", 0.0)),
            })
    return outfalls


def validate_network(junctions, conduits, outfalls):
    """Basic validation of network connectivity."""
    issues = []
    all_nodes = set()

    for j in junctions:
        all_nodes.add(j["id"])
    for o in outfalls:
        all_nodes.add(o["id"])

    # Check conduit references
    for c in conduits:
        if c["from_node"] not in all_nodes:
            issues.append(f"Conduit {c['id']}: from_node '{c['from_node']}' not found")
        if c["to_node"] not in all_nodes:
            issues.append(f"Conduit {c['id']}: to_node '{c['to_node']}' not found")
        if c["length"] <= 0:
            issues.append(f"Conduit {c['id']}: length must be > 0 (got {c['length']})")
        if c["roughness"] <= 0:
            issues.append(f"Conduit {c['id']}: roughness must be > 0 (got {c['roughness']})")
        if c["geom1"] <= 0:
            issues.append(f"Conduit {c['id']}: geom1 (diameter/height) must be > 0")

    # Check for orphan nodes (not connected to any conduit)
    connected_nodes = set()
    for c in conduits:
        connected_nodes.add(c["from_node"])
        connected_nodes.add(c["to_node"])
    orphans = all_nodes - connected_nodes
    for orphan in orphans:
        issues.append(f"Node '{orphan}' is not connected to any conduit")

    # Check at least one outfall exists
    if not outfalls:
        issues.append("No outfalls defined — network has no outlet")

    return issues


def main():
    parser = argparse.ArgumentParser(
        description="Create SWMM drainage network from CSV specifications"
    )
    parser.add_argument("--junctions", required=True,
                        help="Junctions CSV (id, invert_elev, max_depth, x, y)")
    parser.add_argument("--conduits", required=True,
                        help="Conduits CSV (id, from_node, to_node, length, roughness, shape, geom1)")
    parser.add_argument("--outfalls", required=True,
                        help="Outfalls CSV (id, invert_elev, type)")
    parser.add_argument("--output", required=True, help="Output JSON path")
    args = parser.parse_args()

    for fpath in [args.junctions, args.conduits, args.outfalls]:
        if not os.path.isfile(fpath):
            print(f"ERROR: File not found: {fpath}", file=sys.stderr)
            sys.exit(1)

    print("Reading network components...")
    junctions = read_junctions(args.junctions)
    conduits = read_conduits(args.conduits)
    outfalls = read_outfalls(args.outfalls)

    print(f"  Junctions: {len(junctions)}")
    print(f"  Conduits:  {len(conduits)}")
    print(f"  Outfalls:  {len(outfalls)}")

    # Validate
    issues = validate_network(junctions, conduits, outfalls)
    if issues:
        print(f"\nWARNING: {len(issues)} issue(s) found:", file=sys.stderr)
        for issue in issues:
            print(f"  - {issue}", file=sys.stderr)

    # Build output
    network = {
        "junctions": junctions,
        "conduits": conduits,
        "outfalls": outfalls,
        "metadata": {
            "n_junctions": len(junctions),
            "n_conduits": len(conduits),
            "n_outfalls": len(outfalls),
            "n_issues": len(issues),
            "issues": issues,
        },
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(network, f, indent=2)

    print(f"\nNetwork written: {output_path}")
    if issues:
        print(f"  {len(issues)} issues require attention")
    else:
        print("  No issues found")


if __name__ == "__main__":
    main()
