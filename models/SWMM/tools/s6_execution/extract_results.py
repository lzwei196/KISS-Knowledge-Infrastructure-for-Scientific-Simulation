#!/usr/bin/env python3
"""
Extract timeseries results from SWMM binary output (.out) file.

Reads the SWMM binary output file and extracts timeseries for specified
nodes, links, and/or subcatchments to CSV files. Uses the swmm-toolkit
output API (pyswmm.Output) or falls back to parsing the .rpt file.

Available variables:
  Nodes: depth, head, volume, lateral_inflow, total_inflow, flooding
  Links: flow, depth, velocity, volume, capacity
  Subcatchments: rainfall, snow_depth, evaporation, infiltration,
                 runoff, gwflow, gw_elev, soil_moisture

Inputs:
  - SWMM .out binary file
  - Node/link/subcatchment IDs to extract

Outputs:
  - CSV files per element type in output directory
"""

import argparse
import csv
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path


# SWMM output variable indices (from swmm_output.h)
NODE_VARIABLES = {
    "depth": 0,
    "head": 1,
    "volume": 2,
    "lateral_inflow": 3,
    "total_inflow": 4,
    "flooding": 5,
}

LINK_VARIABLES = {
    "flow": 0,
    "depth": 1,
    "velocity": 2,
    "volume": 3,
    "capacity": 4,
}

SUBCATCH_VARIABLES = {
    "rainfall": 0,
    "snow_depth": 1,
    "evaporation": 2,
    "infiltration": 3,
    "runoff": 4,
}


def extract_with_pyswmm(out_path, output_dir, nodes=None, links=None, subcatchments=None):
    """Extract results using pyswmm Output API."""
    try:
        from pyswmm import Output
        from pyswmm.lib import ObjectType
    except ImportError:
        return False  # signal fallback

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    with Output(str(out_path)) as out:
        # Get simulation times
        n_periods = out.times[-1] if hasattr(out, 'times') else 0

        # Extract node results
        if nodes:
            node_file = output_dir / "node_results.csv"
            print(f"  Extracting {len(nodes)} node(s)...")
            with open(node_file, "w", newline="") as f:
                writer = csv.writer(f)
                header = ["datetime"]
                for nid in nodes:
                    for var in ["depth", "head", "total_inflow", "flooding"]:
                        header.append(f"{nid}_{var}")
                writer.writerow(header)

                try:
                    for nid in nodes:
                        ts = out.node_series(nid, "total_inflow")
                        # Write time-indexed data
                        for t_idx, (dt, val) in enumerate(ts.items()):
                            if t_idx == 0 or len(nodes) == 1:
                                row_data = [str(dt), val]
                            else:
                                row_data.append(val)
                except Exception as e:
                    print(f"    Note: pyswmm series extraction: {e}", file=sys.stderr)

            print(f"    Written: {node_file}")

        # Extract link results
        if links:
            link_file = output_dir / "link_results.csv"
            print(f"  Extracting {len(links)} link(s)...")
            with open(link_file, "w", newline="") as f:
                writer = csv.writer(f)
                header = ["datetime"]
                for lid in links:
                    for var in ["flow", "depth", "velocity"]:
                        header.append(f"{lid}_{var}")
                writer.writerow(header)

                try:
                    for lid in links:
                        ts = out.link_series(lid, "flow")
                        for dt, val in ts.items():
                            writer.writerow([str(dt), val])
                except Exception as e:
                    print(f"    Note: pyswmm series extraction: {e}", file=sys.stderr)

            print(f"    Written: {link_file}")

        # Extract subcatchment results
        if subcatchments:
            sc_file = output_dir / "subcatchment_results.csv"
            print(f"  Extracting {len(subcatchments)} subcatchment(s)...")
            with open(sc_file, "w", newline="") as f:
                writer = csv.writer(f)
                header = ["datetime"]
                for sid in subcatchments:
                    for var in ["rainfall", "runoff", "infiltration"]:
                        header.append(f"{sid}_{var}")
                writer.writerow(header)

                try:
                    for sid in subcatchments:
                        ts = out.subcatch_series(sid, "runoff")
                        for dt, val in ts.items():
                            writer.writerow([str(dt), val])
                except Exception as e:
                    print(f"    Note: pyswmm series extraction: {e}", file=sys.stderr)

            print(f"    Written: {sc_file}")

    return True


def extract_from_rpt(rpt_path, output_dir, nodes=None, links=None):
    """Fallback: extract summary from .rpt file."""
    rpt_path_check = Path(rpt_path)
    if not rpt_path_check.exists():
        # Try replacing .out with .rpt
        rpt_path_check = rpt_path_check.with_suffix(".rpt")
        if not rpt_path_check.exists():
            print("WARNING: No .rpt file found for fallback extraction", file=sys.stderr)
            return False

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"  Extracting summary from {rpt_path_check}...")

    # Parse node depth summary
    node_summary = []
    link_summary = []
    current_table = None

    with open(rpt_path_check, "r") as f:
        for line in f:
            line = line.rstrip()
            if "Node Depth Summary" in line:
                current_table = "node_depth"
                continue
            elif "Node Inflow Summary" in line:
                current_table = "node_inflow"
                continue
            elif "Link Flow Summary" in line:
                current_table = "link_flow"
                continue
            elif line.startswith("  ****") or line.startswith("  ----"):
                continue
            elif not line.strip():
                current_table = None
                continue

            parts = line.split()
            if current_table == "node_depth" and len(parts) >= 4:
                try:
                    float(parts[1])
                    node_summary.append(parts)
                except ValueError:
                    pass
            elif current_table == "link_flow" and len(parts) >= 4:
                try:
                    float(parts[1])
                    link_summary.append(parts)
                except ValueError:
                    pass

    if node_summary:
        node_file = output_dir / "node_summary.csv"
        with open(node_file, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["node_id", "avg_depth", "max_depth", "max_HGL", "time_max"])
            for row in node_summary:
                writer.writerow(row[:5])
        print(f"    Node summary: {node_file}")

    if link_summary:
        link_file = output_dir / "link_summary.csv"
        with open(link_file, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["link_id", "max_flow", "time_max", "max_velocity", "max_depth"])
            for row in link_summary:
                writer.writerow(row[:5])
        print(f"    Link summary: {link_file}")

    return True


def main():
    parser = argparse.ArgumentParser(
        description="Extract timeseries results from SWMM .out binary file"
    )
    parser.add_argument("--out", required=True,
                        help="SWMM binary output file (.out)")
    parser.add_argument("--output_dir", required=True,
                        help="Output directory for CSV files")
    parser.add_argument("--nodes", default=None,
                        help='Node IDs to extract (comma-separated, e.g. "J1,J2,J3")')
    parser.add_argument("--links", default=None,
                        help='Link IDs to extract (comma-separated, e.g. "C1,C2")')
    parser.add_argument("--subcatchments", default=None,
                        help='Subcatchment IDs (comma-separated, e.g. "S1,S2")')
    args = parser.parse_args()

    if not os.path.isfile(args.out):
        print(f"ERROR: Output file not found: {args.out}", file=sys.stderr)
        sys.exit(1)

    nodes = [n.strip() for n in args.nodes.split(",")] if args.nodes else None
    links = [l.strip() for l in args.links.split(",")] if args.links else None
    subcatchments = [s.strip() for s in args.subcatchments.split(",")] if args.subcatchments else None

    if not nodes and not links and not subcatchments:
        print("WARNING: No elements specified. Extracting all available summaries.",
              file=sys.stderr)

    print(f"Extracting results from {args.out}...")

    # Try pyswmm first
    success = extract_with_pyswmm(args.out, args.output_dir, nodes, links, subcatchments)

    if not success:
        print("  pyswmm not available, falling back to .rpt parsing...", file=sys.stderr)
        rpt_path = Path(args.out).with_suffix(".rpt")
        success = extract_from_rpt(str(rpt_path), args.output_dir, nodes, links)

    if success:
        print(f"\nResults extracted to: {args.output_dir}")
    else:
        print("\nFailed to extract results", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
