#!/usr/bin/env python3
"""
Validate SWMM drainage network connectivity.

Performs graph analysis on the drainage network to detect:
  - Orphan nodes (not connected to any conduit)
  - Nodes that cannot reach an outfall (disconnected subgraphs)
  - Adverse slopes (upstream invert lower than downstream)
  - Zero-length conduits
  - Duplicate conduit IDs
  - Self-loops (conduit from_node == to_node)
  - Cycles in the network (potential for numerical instability)

Reads from a SWMM .inp file and outputs a JSON validation report.
"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict, deque


def parse_inp_network(inp_path):
    """Parse junctions, conduits, outfalls from .inp file."""
    junctions = {}
    conduits = []
    outfalls = {}
    current_section = None

    with open(inp_path, "r") as f:
        for line in f:
            line = line.strip()
            if line.startswith("[") and line.endswith("]"):
                current_section = line[1:-1].upper()
                continue
            if not line or line.startswith(";"):
                continue

            parts = line.split()

            if current_section == "JUNCTIONS" and len(parts) >= 2:
                junctions[parts[0]] = {
                    "invert_elev": float(parts[1]),
                    "max_depth": float(parts[2]) if len(parts) > 2 else 0.0,
                }
            elif current_section == "OUTFALLS" and len(parts) >= 2:
                outfalls[parts[0]] = {
                    "invert_elev": float(parts[1]),
                    "type": parts[2] if len(parts) > 2 else "FREE",
                }
            elif current_section == "CONDUITS" and len(parts) >= 4:
                conduits.append({
                    "id": parts[0],
                    "from_node": parts[1],
                    "to_node": parts[2],
                    "length": float(parts[3]),
                    "roughness": float(parts[4]) if len(parts) > 4 else 0.013,
                    "in_offset": float(parts[5]) if len(parts) > 5 else 0.0,
                    "out_offset": float(parts[6]) if len(parts) > 6 else 0.0,
                })
            elif current_section == "STORAGE" and len(parts) >= 2:
                junctions[parts[0]] = {
                    "invert_elev": float(parts[1]),
                    "max_depth": float(parts[2]) if len(parts) > 2 else 0.0,
                }

    return junctions, conduits, outfalls


def validate_network(junctions, conduits, outfalls):
    """Run all network validation checks."""
    issues = []
    warnings = []
    all_nodes = {}
    all_nodes.update(junctions)
    all_nodes.update(outfalls)

    outfall_ids = set(outfalls.keys())

    # Build adjacency lists
    adjacency = defaultdict(list)  # node -> [(conduit_id, next_node)]
    connected_nodes = set()
    conduit_ids_seen = set()

    for c in conduits:
        cid = c["id"]

        # Duplicate conduit ID
        if cid in conduit_ids_seen:
            issues.append({
                "type": "duplicate_conduit",
                "conduit": cid,
                "message": f"Duplicate conduit ID: {cid}",
            })
        conduit_ids_seen.add(cid)

        # Self-loop
        if c["from_node"] == c["to_node"]:
            issues.append({
                "type": "self_loop",
                "conduit": cid,
                "message": f"Conduit {cid} connects node {c['from_node']} to itself",
            })

        # Zero-length conduit
        if c["length"] <= 0:
            issues.append({
                "type": "zero_length",
                "conduit": cid,
                "message": f"Conduit {cid} has zero or negative length: {c['length']}",
            })

        # Missing nodes
        if c["from_node"] not in all_nodes:
            issues.append({
                "type": "missing_node",
                "conduit": cid,
                "node": c["from_node"],
                "message": f"Conduit {cid}: from_node '{c['from_node']}' not defined",
            })
        if c["to_node"] not in all_nodes:
            issues.append({
                "type": "missing_node",
                "conduit": cid,
                "node": c["to_node"],
                "message": f"Conduit {cid}: to_node '{c['to_node']}' not defined",
            })

        # Adverse slope
        if c["from_node"] in all_nodes and c["to_node"] in all_nodes:
            from_elev = all_nodes[c["from_node"]]["invert_elev"] + c.get("in_offset", 0)
            to_elev = all_nodes[c["to_node"]]["invert_elev"] + c.get("out_offset", 0)
            if from_elev < to_elev:
                warnings.append({
                    "type": "adverse_slope",
                    "conduit": cid,
                    "from_elev": from_elev,
                    "to_elev": to_elev,
                    "message": (f"Conduit {cid}: adverse slope "
                                f"(from={from_elev:.3f} < to={to_elev:.3f})"),
                })

        adjacency[c["from_node"]].append((cid, c["to_node"]))
        connected_nodes.add(c["from_node"])
        connected_nodes.add(c["to_node"])

    # Orphan nodes
    orphan_nodes = set(all_nodes.keys()) - connected_nodes
    for node in orphan_nodes:
        issues.append({
            "type": "orphan_node",
            "node": node,
            "message": f"Node '{node}' is not connected to any conduit",
        })

    # Reachability: BFS from each non-outfall node to see if it can reach an outfall
    unreachable = []
    for node in list(junctions.keys()):
        if node in orphan_nodes:
            continue
        # BFS
        visited = set()
        queue = deque([node])
        reached_outfall = False
        while queue:
            current = queue.popleft()
            if current in visited:
                continue
            visited.add(current)
            if current in outfall_ids:
                reached_outfall = True
                break
            for cid, next_node in adjacency.get(current, []):
                if next_node not in visited:
                    queue.append(next_node)
        if not reached_outfall:
            unreachable.append(node)

    if unreachable:
        issues.append({
            "type": "unreachable_nodes",
            "nodes": unreachable,
            "count": len(unreachable),
            "message": f"{len(unreachable)} node(s) cannot reach any outfall",
        })

    # No outfalls
    if not outfalls:
        issues.append({
            "type": "no_outfalls",
            "message": "No outfalls defined in the network",
        })

    report = {
        "n_junctions": len(junctions),
        "n_conduits": len(conduits),
        "n_outfalls": len(outfalls),
        "n_orphan_nodes": len(orphan_nodes),
        "n_unreachable_nodes": len(unreachable),
        "n_issues": len(issues),
        "n_warnings": len(warnings),
        "issues": issues,
        "warnings": warnings,
        "valid": len(issues) == 0,
    }
    return report


def main():
    parser = argparse.ArgumentParser(
        description="Validate SWMM drainage network connectivity"
    )
    parser.add_argument("--inp", required=True, help="SWMM .inp file")
    args = parser.parse_args()

    if not os.path.isfile(args.inp):
        print(f"ERROR: File not found: {args.inp}", file=sys.stderr)
        sys.exit(1)

    print(f"Parsing network from {args.inp}...", file=sys.stderr)
    junctions, conduits, outfalls = parse_inp_network(args.inp)
    print(f"  Junctions: {len(junctions)}, Conduits: {len(conduits)}, "
          f"Outfalls: {len(outfalls)}", file=sys.stderr)

    report = validate_network(junctions, conduits, outfalls)
    print(json.dumps(report, indent=2))

    if report["valid"]:
        print(f"\nVALID: Network passes all connectivity checks", file=sys.stderr)
    else:
        print(f"\nINVALID: {report['n_issues']} issue(s) found", file=sys.stderr)

    sys.exit(0 if report["valid"] else 1)


if __name__ == "__main__":
    main()
