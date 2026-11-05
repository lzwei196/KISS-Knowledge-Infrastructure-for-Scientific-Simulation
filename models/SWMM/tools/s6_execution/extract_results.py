#!/usr/bin/env python3
"""
Extract timeseries results from SWMM binary output (.out) file.

Reads the SWMM binary output file and extracts complete, finite time series
for specified nodes, links, and/or subcatchments to CSV files via pyswmm.Output.
Without element selectors, extracts available node/link summaries from the RPT.
A summary never substitutes for requested time series.

Columns written (values in the model's own unit system, as stored in .out):
  Nodes: <id>_depth, <id>_head, <id>_total_inflow, <id>_flooding
  Links: <id>_flow, <id>_depth, <id>_velocity
  Subcatchments: <id>_rainfall, <id>_runoff, <id>_infiltration

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
import math
import tempfile
from pathlib import Path


def extract_with_pyswmm(out_path, output_dir, nodes=None, links=None, subcatchments=None):
    """Extract results using pyswmm Output API."""
    try:
        from pyswmm import Output
        from swmm.toolkit.shared_enum import NodeAttribute, LinkAttribute, SubcatchAttribute
    except ImportError:
        return False

    output_dir = Path(output_dir)
    plans = []
    with Output(str(out_path)) as out:
        times = list(out.times)
        if not times:
            raise ValueError("Output has no reporting periods")
        groups = [
            ("node_results.csv", nodes, out.nodes, out.node_series, [
                ("depth", NodeAttribute.INVERT_DEPTH),
                ("head", NodeAttribute.HYDRAULIC_HEAD),
                ("total_inflow", NodeAttribute.TOTAL_INFLOW),
                ("flooding", NodeAttribute.FLOODING_LOSSES)]),
            ("link_results.csv", links, out.links, out.link_series, [
                ("flow", LinkAttribute.FLOW_RATE),
                ("depth", LinkAttribute.FLOW_DEPTH),
                ("velocity", LinkAttribute.FLOW_VELOCITY)]),
            ("subcatchment_results.csv", subcatchments, out.subcatchments,
             out.subcatch_series, [("rainfall", SubcatchAttribute.RAINFALL),
                                  ("runoff", SubcatchAttribute.RUNOFF_RATE),
                                  ("infiltration", SubcatchAttribute.INFIL_LOSS)]),
        ]
        # Validate every requested ID before writing any results.
        for name, ids, available, read, variables in groups:
            if ids and (len(ids) != len(set(ids)) or any(x not in available for x in ids)):
                raise ValueError(f"Unknown or duplicate element IDs for {name}: {ids}")
        for name, ids, available, read, variables in groups:
            if not ids:
                continue
            header, columns = ["datetime"], []
            for ident in ids:
                for label, attribute in variables:
                    values = read(ident, attribute)
                    if list(values) != times:
                        raise ValueError(f"Incomplete time series: {ident}/{label}")
                    column = list(values.values())
                    if not all(math.isfinite(x) for x in column):
                        raise ValueError(f"Non-finite time series: {ident}/{label}")
                    header.append(f"{ident}_{label}")
                    columns.append(column)
            plans.append((name, header, columns))
    if not plans:
        return False
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, header, columns in plans:
        # Replace a CSV only after its complete contents have been written.
        fd, temporary = tempfile.mkstemp(dir=output_dir, prefix=".swmm-extract-")
        try:
            with os.fdopen(fd, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(header)
                writer.writerows(zip(map(str, times), *columns))
            os.replace(temporary, output_dir / name)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        print(f"    Written: {output_dir / name} ({len(times)} rows)")
    return True


def parse_link_flow_row(parts):
    """Parse one Link Flow Summary row by link type.

    EPA statsrpt.c (writeLinkFlows, SWMM 5.2.4) prints after the time of max:
      CONDUIT/CHANNEL: |velocity|, max/full flow, max/full depth (if full depth > 0)
      PUMP:            max/full flow only when the pump curve gives a capacity
      ORIFICE/WEIR:    max/full depth only (if full depth > 0)
      DUMMY/OUTLET:    nothing
    Columns that do not apply are left empty; they are never filled in.
    Returns None for rows that are not link rows.
    """
    if len(parts) < 5:
        return None
    link_id, link_type = parts[0], parts[1].upper()
    try:
        float(parts[2])
    except ValueError:
        return None
    rest = parts[5:]
    velocity = full_flow = full_depth = ""
    if link_type in ("CONDUIT", "CHANNEL"):
        if len(rest) not in (2, 3):
            raise ValueError(f"Unexpected Link Flow Summary row for {link_type}: {' '.join(parts)}")
        velocity, full_flow = rest[0], rest[1]
        full_depth = rest[2] if len(rest) == 3 else ""
    elif link_type == "PUMP":
        if len(rest) > 1:
            raise ValueError(f"Unexpected Link Flow Summary row for PUMP: {' '.join(parts)}")
        full_flow = rest[0] if rest else ""
    elif link_type in ("ORIFICE", "WEIR"):
        if len(rest) > 1:
            raise ValueError(f"Unexpected Link Flow Summary row for {link_type}: {' '.join(parts)}")
        full_depth = rest[0] if rest else ""
    elif link_type in ("DUMMY", "OUTLET"):
        if rest:
            raise ValueError(f"Unexpected Link Flow Summary row for {link_type}: {' '.join(parts)}")
    else:
        raise ValueError(f"Unknown link type in Link Flow Summary: {' '.join(parts)}")
    return [link_id, link_type, parts[2], " ".join(parts[3:5]), velocity, full_flow, full_depth]


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
    flow_units = velocity_units = ""

    # EPA writes raw bytes such as 0xB3 in some headers; latin-1 reads them all.
    with open(rpt_path_check, "r", encoding="latin-1") as f:
        lines = [line.rstrip() for line in f]
    depth_units = ""
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("***"):
            continue
        # EPA writes each section title between two '*' rule lines
        # (statsrpt.c), so only such a line changes the table; an element ID
        # containing "Summary" cannot end the table early.
        if (0 < index < len(lines) - 1 and lines[index - 1].strip().startswith("***")
                and lines[index + 1].strip().startswith("***")):
            current_table = {"Node Depth Summary": "node_depth",
                             "Node Inflow Summary": "node_inflow",
                             "Link Flow Summary": "link_flow"}.get(stripped)
            continue
        if not stripped or stripped.startswith("---"):
            continue

        parts = stripped.split()
        if current_table == "link_flow" and parts[:2] == ["Link", "Type"] and len(parts) >= 6:
            # Header: Link Type <flow units> days hr:min <velocity units> Flow Depth
            flow_units, velocity_units = parts[2], parts[5]
            continue
        if current_table == "node_depth":
            if parts[:2] == ["Node", "Type"] and len(parts) >= 3:
                depth_units = parts[2]
                continue
            # statsrpt.c writeNodeDepths row: ID, type, average depth, maximum
            # depth, maximum HGL, days, hr:min, reported maximum depth.
            try:
                float(parts[2])
            except (ValueError, IndexError):
                continue  # column-title line
            if len(parts) != 8:
                raise ValueError(f"Unexpected Node Depth Summary row: {stripped}")
            if not nodes or parts[0] in nodes:
                node_summary.append(parts)
        elif current_table == "link_flow":
            row = parse_link_flow_row(parts)
            if row is not None and (not links or row[0] in links):
                link_summary.append(row)

    if node_summary:
        node_file = output_dir / "node_summary.csv"
        with open(node_file, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["node_id", "node_type", "avg_depth", "max_depth", "max_HGL",
                             "depth_units", "time_max"])
            for row in node_summary:
                writer.writerow([row[0], row[1], *row[2:5], depth_units, " ".join(row[5:7])])
        print(f"    Node summary: {node_file}")

    if link_summary:
        link_file = output_dir / "link_summary.csv"
        with open(link_file, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["link_id", "link_type", "max_flow", "flow_units", "time_max",
                             "max_velocity", "velocity_units", "max_full_flow_ratio",
                             "max_full_depth_ratio"])
            for row in link_summary:
                writer.writerow([row[0], row[1], row[2], flow_units, row[3], row[4],
                                 velocity_units if row[4] else "", row[5], row[6]])
        print(f"    Link summary: {link_file}")

    return bool(node_summary or link_summary)


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

    try:
        if nodes or links or subcatchments:
            success = extract_with_pyswmm(args.out, args.output_dir, nodes, links, subcatchments)
            if not success:
                raise RuntimeError("pyswmm is required for requested time series; an RPT summary cannot replace them")
        else:
            success = extract_from_rpt(Path(args.out).with_suffix('.rpt'), args.output_dir)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    if success:
        print(f"\nResults extracted to: {args.output_dir}")
    else:
        print("\nFailed to extract results", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
