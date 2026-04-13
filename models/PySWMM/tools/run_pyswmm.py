#!/usr/bin/env python3
"""
run_pyswmm.py — Execute a PySWMM/SWMM simulation with preflight checks.

Runs the EPA SWMM5 engine via PySWMM with:
  1. Input validation (file existence, section checks)
  2. Optional real-time control callbacks
  3. Progress reporting
  4. Mass balance error checking
  5. Output file verification

CRITICAL: Only ONE Simulation can exist at a time in a Python process.
Attempting multiple simultaneous simulations raises MultiSimulationError.

Usage:
    python run_pyswmm.py \\
        --input model.inp \\
        --report model.rpt \\
        --output model.out \\
        --step-advance 300 \\
        --collect-nodes J1,J2,Outfall \\
        --collect-links C1,C2,W1

Inputs:
    SWMM .inp file (validated before execution)

Outputs:
    - model.rpt: Text report with mass balance and peak values
    - model.out: Binary output with full timeseries
    - results.csv: Extracted timeseries (if --collect-* specified)
"""

import argparse
import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path


def validate_inputs(args):
    """Preflight validation of SWMM model inputs."""
    errors = []
    warnings = []

    inp_path = Path(args.input)

    # Check input file exists
    if not inp_path.is_file():
        errors.append(f"Input file not found: {args.input}")
        return False, errors, warnings

    # Read and validate .inp file sections
    content = inp_path.read_text()

    required_sections = ["[OPTIONS]", "[JUNCTIONS]", "[OUTFALLS]"]
    for section in required_sections:
        if section not in content:
            errors.append(f"Missing required section: {section}")

    recommended_sections = ["[RAINGAGES]", "[SUBCATCHMENTS]", "[CONDUITS]"]
    for section in recommended_sections:
        if section not in content:
            warnings.append(f"Missing recommended section: {section}")

    # Check OPTIONS for critical settings
    if "[OPTIONS]" in content:
        options_block = content.split("[OPTIONS]")[1].split("[")[0]
        if "FLOW_UNITS" not in options_block:
            warnings.append("FLOW_UNITS not specified — defaults to CFS")
        if "FLOW_ROUTING" not in options_block:
            warnings.append("FLOW_ROUTING not specified — defaults to KINWAVE")

    # Check step advance is reasonable
    if args.step_advance is not None:
        if args.step_advance < 1:
            errors.append("step-advance must be >= 1 second")
        elif args.step_advance > 86400:
            warnings.append("step-advance > 86400s (1 day) — may miss transient events")

    # Check output directory is writable
    out_dir = Path(args.output).parent
    if not out_dir.exists():
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            errors.append(f"Cannot create output directory: {e}")

    if errors:
        return False, errors, warnings
    return True, errors, warnings


def run_simulation(args):
    """Execute SWMM simulation with optional data collection."""
    try:
        from pyswmm import Simulation, Nodes, Links, Subcatchments
    except ImportError:
        return {
            "status": "error",
            "message": "pyswmm not installed. Run: pip install pyswmm"
        }

    results = {
        "status": "running",
        "start_time": datetime.now().isoformat(),
        "node_timeseries": {},
        "link_timeseries": {},
    }

    collect_node_ids = args.collect_nodes.split(",") if args.collect_nodes else []
    collect_link_ids = args.collect_links.split(",") if args.collect_links else []

    try:
        with Simulation(args.input, args.report, args.output) as sim:
            # Initialize collectors
            node_objs = {}
            link_objs = {}

            if collect_node_ids:
                nodes = Nodes(sim)
                for nid in collect_node_ids:
                    nid = nid.strip()
                    if nid in nodes:
                        node_objs[nid] = nodes[nid]
                        results["node_timeseries"][nid] = []
                    else:
                        print(f"WARNING: Node '{nid}' not found in model", file=sys.stderr)

            if collect_link_ids:
                links = Links(sim)
                for lid in collect_link_ids:
                    lid = lid.strip()
                    if lid in links:
                        link_objs[lid] = links[lid]
                        results["link_timeseries"][lid] = []
                    else:
                        print(f"WARNING: Link '{lid}' not found in model", file=sys.stderr)

            # Set step advance if specified
            if args.step_advance:
                sim.step_advance(args.step_advance)

            # Run simulation with progress tracking
            t_start = time.time()
            step_count = 0

            for step in sim:
                step_count += 1
                current_time = sim.current_time

                # Collect node data
                for nid, node in node_objs.items():
                    results["node_timeseries"][nid].append({
                        "time": str(current_time),
                        "depth": round(node.depth, 4),
                        "total_inflow": round(node.total_inflow, 4),
                        "flooding": round(node.flooding, 4),
                    })

                # Collect link data
                for lid, link in link_objs.items():
                    results["link_timeseries"][lid].append({
                        "time": str(current_time),
                        "flow": round(link.flow, 4),
                        "depth": round(link.depth, 4),
                        "setting": round(link.setting, 4),
                    })

                # Progress report every 100 steps
                if step_count % 100 == 0:
                    pct = sim.percent_complete * 100
                    print(f"  Progress: {pct:.1f}% ({step_count} steps, t={current_time})")

            t_elapsed = time.time() - t_start

            # Collect mass balance errors
            results["status"] = "completed"
            results["elapsed_seconds"] = round(t_elapsed, 2)
            results["total_steps"] = step_count
            results["runoff_error"] = round(sim.runoff_error, 4)
            results["routing_error"] = round(sim.flow_routing_error, 4)
            results["quality_error"] = round(sim.quality_error, 4)
            results["flow_units"] = str(sim.flow_units)
            results["system_units"] = str(sim.system_units)

            # Validate mass balance
            if abs(sim.runoff_error) > 5.0:
                results["warning_runoff"] = (
                    f"Runoff continuity error = {sim.runoff_error:.2f}% (>5% threshold)"
                )
            if abs(sim.flow_routing_error) > 5.0:
                results["warning_routing"] = (
                    f"Routing continuity error = {sim.flow_routing_error:.2f}% (>5% threshold)"
                )

    except Exception as e:
        results["status"] = "error"
        results["message"] = str(e)
        return results

    # Verify output files exist
    for fpath, label in [(args.report, "Report"), (args.output, "Binary output")]:
        if fpath and Path(fpath).is_file():
            results[f"{label.lower().replace(' ', '_')}_size"] = Path(fpath).stat().st_size
        elif fpath:
            results[f"warning_{label.lower()}"] = f"{label} file not created: {fpath}"

    return results


def write_collected_csv(results, output_csv):
    """Write collected timeseries to CSV."""
    rows = []

    for nid, ts in results.get("node_timeseries", {}).items():
        for rec in ts:
            rows.append({
                "element_type": "node",
                "element_id": nid,
                "time": rec["time"],
                "depth": rec["depth"],
                "flow": rec["total_inflow"],
                "flooding": rec["flooding"],
                "setting": "",
            })

    for lid, ts in results.get("link_timeseries", {}).items():
        for rec in ts:
            rows.append({
                "element_type": "link",
                "element_id": lid,
                "time": rec["time"],
                "depth": rec["depth"],
                "flow": rec["flow"],
                "flooding": "",
                "setting": rec["setting"],
            })

    if rows:
        output_path = Path(output_csv)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "element_type", "element_id", "time", "depth", "flow", "flooding", "setting"
            ])
            writer.writeheader()
            writer.writerows(rows)
        print(f"Wrote {len(rows)} records to {output_csv}")


def main():
    parser = argparse.ArgumentParser(
        description="Run PySWMM simulation with preflight checks and data collection"
    )
    parser.add_argument("--input", required=True, help="SWMM .inp file path")
    parser.add_argument("--report", default=None, help="Report .rpt file path")
    parser.add_argument("--output", default=None, help="Binary .out file path")
    parser.add_argument("--step-advance", type=int, default=None,
                        help="Step advance interval in seconds")
    parser.add_argument("--collect-nodes", default=None,
                        help="Comma-separated node IDs to collect timeseries")
    parser.add_argument("--collect-links", default=None,
                        help="Comma-separated link IDs to collect timeseries")
    parser.add_argument("--results-csv", default=None,
                        help="Output CSV for collected timeseries")

    args = parser.parse_args()

    # Set defaults for report and output
    if args.report is None:
        args.report = str(Path(args.input).with_suffix(".rpt"))
    if args.output is None:
        args.output = str(Path(args.input).with_suffix(".out"))

    # Validate
    ok, errors, warnings = validate_inputs(args)
    for w in warnings:
        print(f"WARNING: {w}", file=sys.stderr)
    if not ok:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)

    # Run
    result = run_simulation(args)

    # Write collected data
    if args.results_csv and result["status"] == "completed":
        write_collected_csv(result, args.results_csv)

    # Remove large timeseries from JSON output for readability
    summary = {k: v for k, v in result.items()
               if k not in ("node_timeseries", "link_timeseries")}
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
