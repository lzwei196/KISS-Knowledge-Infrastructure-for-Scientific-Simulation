#!/usr/bin/env python3
"""
parse_swmm_output.py — Extract timeseries from SWMM binary output files.

Reads SWMM .out binary files via the PySWMM Output API and exports
timeseries for nodes, links, subcatchments, and system-wide variables
to CSV format.

Usage:
    python parse_swmm_output.py \\
        --input model.out \\
        --output-dir ./results/ \\
        --nodes J1,J2,Outfall \\
        --links C1,C2,W1 \\
        --subcatchments S1,S2 \\
        --system

    # Extract all elements
    python parse_swmm_output.py \\
        --input model.out \\
        --output-dir ./results/ \\
        --all

Inputs:
    SWMM binary output file (.out)

Outputs:
    CSV files per element type:
    - nodes_{id}.csv: time, depth, inflow, outflow, flooding, volume, head
    - links_{id}.csv: time, flow, depth, velocity, volume, setting
    - subcatch_{id}.csv: time, rainfall, runoff, infiltration, evaporation
    - system.csv: time, rainfall, runoff, outflow, flooding, storage
"""

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path


def validate_inputs(args):
    """Validate inputs before processing."""
    errors = []

    if not Path(args.input).is_file():
        errors.append(f"Output file not found: {args.input}")

    out_dir = Path(args.output_dir)
    if not out_dir.exists():
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            errors.append(f"Cannot create output directory: {e}")

    if errors:
        return False, errors
    return True, []


def parse_output(args):
    """Main processing: read binary output and export to CSV."""
    try:
        from pyswmm import Output, NodeSeries, LinkSeries, SubcatchSeries, SystemSeries
    except ImportError:
        return {"status": "error", "message": "pyswmm not installed. Run: pip install pyswmm"}

    out_dir = Path(args.output_dir)
    summary = {
        "status": "completed",
        "files_written": [],
        "elements": {},
    }

    try:
        with Output(args.input) as out:
            # Report metadata
            summary["start"] = str(out.start)
            summary["end"] = str(out.end)
            summary["n_timesteps"] = len(out.times)
            summary["n_subcatchments"] = len(out.subcatchments)
            summary["n_nodes"] = len(out.nodes)
            summary["n_links"] = len(out.links)

            available_nodes = set(out.nodes.keys())
            available_links = set(out.links.keys())
            available_subcatch = set(out.subcatchments.keys())

            # Determine which elements to extract
            if args.all:
                node_ids = list(available_nodes)
                link_ids = list(available_links)
                subcatch_ids = list(available_subcatch)
                extract_system = True
            else:
                node_ids = [n.strip() for n in args.nodes.split(",")] if args.nodes else []
                link_ids = [l.strip() for l in args.links.split(",")] if args.links else []
                subcatch_ids = [s.strip() for s in args.subcatchments.split(",")] if args.subcatchments else []
                extract_system = args.system

            # Validate requested elements exist
            for nid in node_ids:
                if nid not in available_nodes:
                    print(f"WARNING: Node '{nid}' not in output file", file=sys.stderr)

            for lid in link_ids:
                if lid not in available_links:
                    print(f"WARNING: Link '{lid}' not in output file", file=sys.stderr)

            for sid in subcatch_ids:
                if sid not in available_subcatch:
                    print(f"WARNING: Subcatchment '{sid}' not in output file", file=sys.stderr)

            # Extract node timeseries
            if node_ids:
                node_series = NodeSeries(out)
                for nid in node_ids:
                    if nid not in available_nodes:
                        continue
                    ns = node_series[nid]
                    fpath = out_dir / f"node_{nid}.csv"

                    depth_ts = ns.invert_depth
                    inflow_ts = ns.total_inflow
                    outflow_ts = ns.outflow
                    flooding_ts = ns.overflow
                    volume_ts = ns.volume

                    with open(fpath, "w", newline="") as f:
                        writer = csv.writer(f)
                        writer.writerow(["datetime", "depth", "total_inflow", "outflow",
                                         "flooding", "volume"])
                        for t in sorted(depth_ts.keys()):
                            writer.writerow([
                                t.strftime("%Y-%m-%d %H:%M:%S"),
                                f"{depth_ts.get(t, 0):.6f}",
                                f"{inflow_ts.get(t, 0):.6f}",
                                f"{outflow_ts.get(t, 0):.6f}",
                                f"{flooding_ts.get(t, 0):.6f}",
                                f"{volume_ts.get(t, 0):.6f}",
                            ])

                    summary["files_written"].append(str(fpath))
                    summary["elements"][f"node_{nid}"] = len(depth_ts)

            # Extract link timeseries
            if link_ids:
                link_series = LinkSeries(out)
                for lid in link_ids:
                    if lid not in available_links:
                        continue
                    ls = link_series[lid]
                    fpath = out_dir / f"link_{lid}.csv"

                    flow_ts = ls.flow_rate
                    depth_ts = ls.flow_depth
                    volume_ts = ls.flow_volume
                    setting_ts = ls.setting

                    with open(fpath, "w", newline="") as f:
                        writer = csv.writer(f)
                        writer.writerow(["datetime", "flow", "depth", "volume", "setting"])
                        for t in sorted(flow_ts.keys()):
                            writer.writerow([
                                t.strftime("%Y-%m-%d %H:%M:%S"),
                                f"{flow_ts.get(t, 0):.6f}",
                                f"{depth_ts.get(t, 0):.6f}",
                                f"{volume_ts.get(t, 0):.6f}",
                                f"{setting_ts.get(t, 0):.6f}",
                            ])

                    summary["files_written"].append(str(fpath))
                    summary["elements"][f"link_{lid}"] = len(flow_ts)

            # Extract subcatchment timeseries
            if subcatch_ids:
                sub_series = SubcatchSeries(out)
                for sid in subcatch_ids:
                    if sid not in available_subcatch:
                        continue
                    ss = sub_series[sid]
                    fpath = out_dir / f"subcatch_{sid}.csv"

                    rain_ts = ss.rainfall
                    runoff_ts = ss.runoff_rate
                    infil_ts = ss.infiltration_loss
                    evap_ts = ss.evap_loss

                    with open(fpath, "w", newline="") as f:
                        writer = csv.writer(f)
                        writer.writerow(["datetime", "rainfall", "runoff", "infiltration",
                                         "evaporation"])
                        for t in sorted(rain_ts.keys()):
                            writer.writerow([
                                t.strftime("%Y-%m-%d %H:%M:%S"),
                                f"{rain_ts.get(t, 0):.6f}",
                                f"{runoff_ts.get(t, 0):.6f}",
                                f"{infil_ts.get(t, 0):.6f}",
                                f"{evap_ts.get(t, 0):.6f}",
                            ])

                    summary["files_written"].append(str(fpath))
                    summary["elements"][f"subcatch_{sid}"] = len(rain_ts)

            # Extract system timeseries
            if extract_system:
                sys_series = SystemSeries(out)
                fpath = out_dir / "system.csv"

                rain_ts = sys_series.rainfall
                runoff_ts = sys_series.runoff_flow
                outflow_ts = sys_series.outflow

                with open(fpath, "w", newline="") as f:
                    writer = csv.writer(f)
                    writer.writerow(["datetime", "rainfall", "runoff", "outflow"])
                    for t in sorted(rain_ts.keys()):
                        writer.writerow([
                            t.strftime("%Y-%m-%d %H:%M:%S"),
                            f"{rain_ts.get(t, 0):.6f}",
                            f"{runoff_ts.get(t, 0):.6f}",
                            f"{outflow_ts.get(t, 0):.6f}",
                        ])

                summary["files_written"].append(str(fpath))
                summary["elements"]["system"] = len(rain_ts)

    except Exception as e:
        summary["status"] = "error"
        summary["message"] = str(e)

    # Post-validation
    if summary["status"] == "completed":
        total_records = sum(summary["elements"].values())
        summary["total_records"] = total_records
        if total_records == 0:
            summary["warning"] = "No records extracted — check element IDs"

    return summary


def validate_output(summary):
    """Post-process validation of extracted data."""
    warnings = []

    if summary.get("n_timesteps", 0) == 0:
        warnings.append("Output file contains zero timesteps")

    total = summary.get("total_records", 0)
    if total == 0:
        warnings.append("No records extracted — verify element IDs match model")

    return warnings


def main():
    parser = argparse.ArgumentParser(
        description="Extract timeseries from SWMM binary output file"
    )
    parser.add_argument("--input", required=True, help="SWMM .out file path")
    parser.add_argument("--output-dir", required=True, help="Output directory for CSVs")
    parser.add_argument("--nodes", default=None,
                        help="Comma-separated node IDs to extract")
    parser.add_argument("--links", default=None,
                        help="Comma-separated link IDs to extract")
    parser.add_argument("--subcatchments", default=None,
                        help="Comma-separated subcatchment IDs to extract")
    parser.add_argument("--system", action="store_true",
                        help="Extract system-wide timeseries")
    parser.add_argument("--all", action="store_true",
                        help="Extract all elements")

    args = parser.parse_args()

    ok, errors = validate_inputs(args)
    if not ok:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)

    result = parse_output(args)

    post_warnings = validate_output(result)
    if post_warnings:
        result["post_validation_warnings"] = post_warnings

    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
