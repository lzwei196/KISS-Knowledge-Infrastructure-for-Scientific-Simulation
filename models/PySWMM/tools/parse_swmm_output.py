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
    CSV files per element type (only quantities that SWMM stores in the .out file;
    names of the swmm.toolkit attributes in brackets):
    - node_{id}.csv: datetime, depth [INVERT_DEPTH], head [HYDRAULIC_HEAD],
      total_inflow [TOTAL_INFLOW], lateral_inflow [LATERAL_INFLOW],
      flooding [FLOODING_LOSSES], volume [PONDED_VOLUME = stored + ponded volume]
      (node outflow is not stored in the .out file)
    - link_{id}.csv: datetime, flow [FLOW_RATE], depth [FLOW_DEPTH],
      velocity [FLOW_VELOCITY], volume [FLOW_VOLUME], capacity [CAPACITY]
      (the link setting is not stored in the .out file; run_pyswmm.py --collect-links
      records it during the run)
    - subcatch_{id}.csv: datetime, rainfall [RAINFALL], runoff [RUNOFF_RATE],
      infiltration [INFIL_LOSS], evaporation [EVAP_LOSS]
    - system.csv: datetime, rainfall [RAINFALL], runoff [RUNOFF_FLOW],
      outflow [OUTFALL_FLOWS], flooding [FLOOD_LOSSES], storage [VOLUME_STORED]
    Exit code 1 if the file cannot be read, a requested element is not in the file,
    or nothing was extracted.
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
    else:
        # SWMM binary output starts and ends with the magic number 516114522; checking it
        # first gives a clear error instead of a crash inside the reader on a wrong/partial file
        try:
            with open(args.input, "rb") as f:
                head = f.read(4)
                f.seek(0, 2)
                size = f.tell()
                f.seek(max(size - 4, 0))
                tail = f.read(4)
            magic = (516114522).to_bytes(4, "little")
            if size < 8 or head != magic or tail != magic:
                errors.append(f"Not a complete SWMM binary output file (magic number check "
                              f"failed): {args.input}")
        except OSError as e:
            errors.append(f"Cannot read {args.input}: {e}")

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

            # Validate requested elements exist (before any CSV is written)
            missing = ([f"node '{n}'" for n in node_ids if n not in available_nodes]
                       + [f"link '{l}'" for l in link_ids if l not in available_links]
                       + [f"subcatchment '{c}'" for c in subcatch_ids
                          if c not in available_subcatch])
            if missing:
                summary["status"] = "error"
                summary["message"] = "Not in output file: " + ", ".join(missing)
                return summary

            # Extract node timeseries
            if node_ids:
                node_series = NodeSeries(out)
                for nid in node_ids:
                    if nid not in available_nodes:
                        continue
                    ns = node_series[nid]
                    fpath = out_dir / f"node_{nid}.csv"

                    depth_ts = ns.invert_depth
                    head_ts = ns.hydraulic_head
                    inflow_ts = ns.total_inflow
                    lateral_ts = ns.lateral_inflow
                    flooding_ts = ns.flooding_losses
                    volume_ts = ns.ponded_volume

                    with open(fpath, "w", newline="") as f:
                        writer = csv.writer(f)
                        writer.writerow(["datetime", "depth", "head", "total_inflow",
                                         "lateral_inflow", "flooding", "volume"])
                        for t in sorted(depth_ts.keys()):
                            writer.writerow([
                                t.strftime("%Y-%m-%d %H:%M:%S"),
                                f"{depth_ts.get(t, 0):.6f}",
                                f"{head_ts.get(t, 0):.6f}",
                                f"{inflow_ts.get(t, 0):.6f}",
                                f"{lateral_ts.get(t, 0):.6f}",
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
                    velocity_ts = ls.flow_velocity
                    volume_ts = ls.flow_volume
                    capacity_ts = ls.capacity

                    with open(fpath, "w", newline="") as f:
                        writer = csv.writer(f)
                        writer.writerow(["datetime", "flow", "depth", "velocity", "volume",
                                         "capacity"])
                        for t in sorted(flow_ts.keys()):
                            writer.writerow([
                                t.strftime("%Y-%m-%d %H:%M:%S"),
                                f"{flow_ts.get(t, 0):.6f}",
                                f"{depth_ts.get(t, 0):.6f}",
                                f"{velocity_ts.get(t, 0):.6f}",
                                f"{volume_ts.get(t, 0):.6f}",
                                f"{capacity_ts.get(t, 0):.6f}",
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
                    infil_ts = ss.infil_loss
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
                outflow_ts = sys_series.outfall_flows
                flooding_ts = sys_series.flood_losses
                storage_ts = sys_series.volume_stored

                with open(fpath, "w", newline="") as f:
                    writer = csv.writer(f)
                    writer.writerow(["datetime", "rainfall", "runoff", "outflow", "flooding",
                                     "storage"])
                    for t in sorted(rain_ts.keys()):
                        writer.writerow([
                            t.strftime("%Y-%m-%d %H:%M:%S"),
                            f"{rain_ts.get(t, 0):.6f}",
                            f"{runoff_ts.get(t, 0):.6f}",
                            f"{outflow_ts.get(t, 0):.6f}",
                            f"{flooding_ts.get(t, 0):.6f}",
                            f"{storage_ts.get(t, 0):.6f}",
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
            summary["status"] = "error"
            summary["message"] = ("No records extracted — give --nodes/--links/"
                                  "--subcatchments/--system or --all")

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

    if result.get("status") != "completed":
        print("parse_swmm_output FAILED: " + str(result.get("message", "see JSON result")),
              file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
