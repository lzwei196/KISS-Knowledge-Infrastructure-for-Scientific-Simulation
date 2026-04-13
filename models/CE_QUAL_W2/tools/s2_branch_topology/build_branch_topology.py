#!/usr/bin/env python3
"""
build_branch_topology.py — Define CE-QUAL-W2 branch connectivity.

Computes branch properties: segment ranges, slopes, upstream/downstream linkages.
For multi-branch reservoirs (e.g., Danjiangkou with Han + Dan River arms).

CRITICAL (dt_012): DHS (downstream head segment) must point to a valid segment
in the receiving branch. Invalid references cause model crash at branch junction.

Usage:
    python build_branch_topology.py \
        --grid_json /path/to/reservoir_grid.json \
        --branches '[{"name":"main","upstream_lat":33.1,"upstream_lon":111.8,"downstream_lat":32.54,"downstream_lon":111.51}]' \
        --output branch_topology.json

    # Single branch (default — just validate existing grid):
    python build_branch_topology.py \
        --grid_json /path/to/reservoir_grid.json \
        --output branch_topology.json
"""

import argparse
import json
import os
import sys

import numpy as np


def validate_inputs(args):
    """Validate inputs."""
    errors = []
    if not os.path.isfile(args.grid_json):
        errors.append(f"Grid JSON not found: {args.grid_json}")
    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)


def process(args):
    """Main processing."""
    with open(args.grid_json) as f:
        grid = json.load(f)

    branches = grid.get("branch_info", [])

    if args.branches:
        # User-defined multi-branch configuration
        user_branches = json.loads(args.branches)
        # Rebuild branch info from user specification
        branches = []
        seg_offset = 2  # start after first boundary segment

        for i, ub in enumerate(user_branches):
            n_segs = ub.get("n_segments", 10)
            us = seg_offset
            ds = seg_offset + n_segs - 1

            # Compute slope from coordinates
            if "upstream_lat" in ub and "downstream_lat" in ub:
                # Approximate distance in meters
                lat_mid = (ub["upstream_lat"] + ub["downstream_lat"]) / 2
                dx = (ub["upstream_lon"] - ub["downstream_lon"]) * 111320 * np.cos(np.radians(lat_mid))
                dy = (ub["upstream_lat"] - ub["downstream_lat"]) * 110540
                length_m = np.sqrt(dx**2 + dy**2)
                elev_drop = ub.get("elevation_drop_m", length_m * 0.001)
                slope = elev_drop / max(length_m, 1)
            else:
                slope = ub.get("slope", 0.001)

            branch = {
                "branch_id": i + 1,
                "waterbody_id": ub.get("waterbody_id", 1),
                "name": ub.get("name", f"branch_{i+1}"),
                "upstream_segment": us,
                "downstream_segment": ds,
                "upstream_head_segment": ub.get("uhs", 0),
                "downstream_head_segment": ub.get("dhs", 0 if i == 0 else branches[0]["downstream_segment"]),
                "slope": round(slope, 6),
                "n_active_segments": n_segs,
            }
            branches.append(branch)
            seg_offset = ds + 2  # gap for next boundary segment
    else:
        # Validate existing single-branch configuration
        if not branches:
            branches = [{
                "branch_id": 1,
                "waterbody_id": 1,
                "name": "main",
                "upstream_segment": 2,
                "downstream_segment": grid["n_segments"] - 1,
                "upstream_head_segment": 0,
                "downstream_head_segment": 0,
                "slope": 0.001,
                "n_active_segments": grid["n_active_segments"],
            }]

    # Validate branch connectivity (dt_012)
    warnings = []
    all_segments = set()
    for br in branches:
        for s in range(br["upstream_segment"], br["downstream_segment"] + 1):
            if s in all_segments:
                warnings.append(f"Segment {s} assigned to multiple branches")
            all_segments.add(s)

        dhs = br["downstream_head_segment"]
        if dhs > 0:
            # Check if DHS points to a valid segment in another branch
            found = False
            for other_br in branches:
                if other_br["branch_id"] == br["branch_id"]:
                    continue
                if other_br["upstream_segment"] <= dhs <= other_br["downstream_segment"]:
                    found = True
                    break
            if not found:
                warnings.append(f"Branch {br['branch_id']} DHS={dhs} does not point to a valid "
                              f"segment in any other branch (dt_012)")

    topology = {
        "n_branches": len(branches),
        "n_waterbodies": max(br.get("waterbody_id", 1) for br in branches),
        "branches": branches,
        "total_active_segments": sum(br.get("n_active_segments", br["downstream_segment"] - br["upstream_segment"] + 1) for br in branches),
    }

    output_path = args.output
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(topology, f, indent=2)

    result = {
        "status": "success",
        "output_file": output_path,
        "n_branches": len(branches),
        "branch_names": [br.get("name", f"branch_{br['branch_id']}") for br in branches],
    }
    if warnings:
        result["warnings"] = warnings

    print(json.dumps(result, indent=2))
    return 0


def main():
    parser = argparse.ArgumentParser(description="Build CE-QUAL-W2 branch topology")
    parser.add_argument("--grid_json", required=True, help="Reservoir grid JSON")
    parser.add_argument("--branches", help="JSON string with branch definitions")
    parser.add_argument("--output", required=True, help="Output topology JSON")
    args = parser.parse_args()
    validate_inputs(args)
    sys.exit(process(args))


if __name__ == "__main__":
    main()
