#!/usr/bin/env python3
"""
Configure SWMM simulation OPTIONS section.

Sets simulation control parameters including:
  - Flow units (CFS, GPM, MGD, CMS, LPS, MLD)
  - Routing method (STEADY, KINWAVE, DYNWAVE)
  - Simulation period (start/end dates)
  - Timestep settings (wet, dry, routing, report)
  - Ponding, snow, groundwater toggles

Outputs a JSON file with the configured options, to be consumed by
assemble_inp_file.py.
"""

import argparse
import json
import sys
from pathlib import Path

VALID_FLOW_UNITS = ["CFS", "GPM", "MGD", "CMS", "LPS", "MLD"]
VALID_ROUTING = ["STEADY", "KINWAVE", "DYNWAVE"]
VALID_INFILTRATION = ["HORTON", "MODIFIED_HORTON", "GREEN_AMPT",
                      "MODIFIED_GREEN_AMPT", "CURVE_NUMBER"]


def validate_date(date_str, name):
    """Validate MM/DD/YYYY format."""
    parts = date_str.split("/")
    if len(parts) != 3:
        print(f"ERROR: {name} must be MM/DD/YYYY format (got '{date_str}')", file=sys.stderr)
        sys.exit(1)
    try:
        month, day, year = int(parts[0]), int(parts[1]), int(parts[2])
        if month < 1 or month > 12 or day < 1 or day > 31 or year < 1900:
            raise ValueError()
    except ValueError:
        print(f"ERROR: Invalid {name}: '{date_str}'", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Configure SWMM simulation options"
    )
    parser.add_argument("--flow_units", default="CMS",
                        choices=VALID_FLOW_UNITS,
                        help="Flow units (default: CMS)")
    parser.add_argument("--routing", default="DYNWAVE",
                        choices=VALID_ROUTING,
                        help="Routing method (default: DYNWAVE)")
    parser.add_argument("--infiltration", default="GREEN_AMPT",
                        choices=VALID_INFILTRATION,
                        help="Infiltration method (default: GREEN_AMPT)")
    parser.add_argument("--start", required=True,
                        help="Start date (MM/DD/YYYY)")
    parser.add_argument("--end", required=True,
                        help="End date (MM/DD/YYYY)")
    parser.add_argument("--start_time", default="00:00:00",
                        help="Start time (HH:MM:SS, default: 00:00:00)")
    parser.add_argument("--end_time", default="23:59:59",
                        help="End time (HH:MM:SS, default: 23:59:59)")
    parser.add_argument("--routing_step", type=float, default=10.0,
                        help="Routing timestep in seconds (default: 10)")
    parser.add_argument("--report_step", default="00:05:00",
                        help="Report timestep HH:MM:SS (default: 00:05:00)")
    parser.add_argument("--wet_step", default="00:05:00",
                        help="Wet weather timestep HH:MM:SS (default: 00:05:00)")
    parser.add_argument("--dry_step", default="01:00:00",
                        help="Dry weather timestep HH:MM:SS (default: 01:00:00)")
    parser.add_argument("--allow_ponding", action="store_true",
                        help="Allow ponding at nodes")
    parser.add_argument("--variable_step", type=float, default=0.75,
                        help="Variable timestep factor (0-1, default: 0.75)")
    parser.add_argument("--min_slope", type=float, default=0.0,
                        help="Minimum conduit slope (default: 0)")
    parser.add_argument("--link_offsets", default="DEPTH",
                        choices=["DEPTH", "ELEVATION"],
                        help="Link offset convention (default: DEPTH)")
    parser.add_argument("--normal_flow", default="BOTH",
                        choices=["SLOPE", "FROUDE", "BOTH"],
                        help="Normal flow limited criterion (default: BOTH)")
    parser.add_argument("--inertial_damping", default="PARTIAL",
                        choices=["NONE", "PARTIAL", "FULL"],
                        help="Inertial damping for DYNWAVE (default: PARTIAL)")
    parser.add_argument("--output", required=True,
                        help="Output JSON path")
    args = parser.parse_args()

    # Validate dates
    validate_date(args.start, "start date")
    validate_date(args.end, "end date")

    # Build options
    options = {
        "flow_units": args.flow_units,
        "routing": args.routing,
        "infiltration": args.infiltration,
        "start_date": args.start,
        "start_time": args.start_time,
        "end_date": args.end,
        "end_time": args.end_time,
        "routing_step": str(int(args.routing_step)),
        "report_step": args.report_step,
        "wet_step": args.wet_step,
        "dry_step": args.dry_step,
        "allow_ponding": "YES" if args.allow_ponding else "NO",
        "variable_step": str(args.variable_step),
        "min_slope": str(args.min_slope),
        "link_offsets": args.link_offsets,
        "normal_flow": args.normal_flow,
        "inertial_damping": args.inertial_damping,
        "start": args.start,
        "end": args.end,
    }

    # Write JSON
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(options, f, indent=2)

    print(f"Simulation options written: {output_path}")
    print(f"  Flow units: {args.flow_units}")
    print(f"  Routing: {args.routing}")
    print(f"  Infiltration: {args.infiltration}")
    print(f"  Period: {args.start} to {args.end}")
    print(f"  Routing step: {args.routing_step}s")
    print(f"  Report step: {args.report_step}")
    print(f"  Ponding: {'YES' if args.allow_ponding else 'NO'}")


if __name__ == "__main__":
    main()
