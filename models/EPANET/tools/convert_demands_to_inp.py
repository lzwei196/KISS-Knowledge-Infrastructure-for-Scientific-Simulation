#!/usr/bin/env python3
"""
convert_demands_to_inp.py — Convert external demand/network data to EPANET .inp format.

Converts junction demands, reservoir heads, tank geometry, and time patterns
from CSV or tabular data into a complete EPANET .inp input file. Handles
unit conversion between SI and US Customary systems.

Usage:
    python convert_demands_to_inp.py \
        --junctions junctions.csv \
        --reservoirs reservoirs.csv \
        --tanks tanks.csv \
        --pipes pipes.csv \
        --pumps pumps.csv \
        --patterns patterns.csv \
        --curves curves.csv \
        --units GPM \
        --headloss H-W \
        --duration 24 \
        --timestep 1 \
        --output network.inp

Pattern: validate → process → validate
"""

import argparse
import csv
import os
import sys
from pathlib import Path

# Unit system determination
US_FLOW_UNITS = {"CFS", "GPM", "MGD", "IMGD", "AFD"}
SI_FLOW_UNITS = {"LPS", "LPM", "MLD", "CMH", "CMD"}
ALL_FLOW_UNITS = US_FLOW_UNITS | SI_FLOW_UNITS

# Conversion factors to SI base (meters, LPS)
ELEVATION_FT_TO_M = 0.3048
PIPE_DIAM_IN_TO_MM = 25.4
LENGTH_FT_TO_M = 0.3048
PRESSURE_PSI_TO_M = 0.703070


def validate_inputs(args):
    """Validate all input files exist and parameters are valid."""
    errors = []

    # Check required files
    if args.junctions and not os.path.isfile(args.junctions):
        errors.append(f"Junctions file not found: {args.junctions}")

    if args.pipes and not os.path.isfile(args.pipes):
        errors.append(f"Pipes file not found: {args.pipes}")

    # Validate unit choice
    if args.units.upper() not in ALL_FLOW_UNITS:
        errors.append(f"Invalid flow units '{args.units}'. Must be one of: {ALL_FLOW_UNITS}")

    # Validate headloss formula
    if args.headloss.upper() not in {"H-W", "D-W", "C-M"}:
        errors.append(f"Invalid headloss formula '{args.headloss}'. Must be H-W, D-W, or C-M")

    # Validate duration and timestep
    if args.duration <= 0:
        errors.append("Duration must be positive")
    if args.timestep <= 0:
        errors.append("Timestep must be positive")

    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"[OK] Input validation passed")
    return True


def read_csv_section(filepath):
    """Read a CSV file and return list of dicts."""
    if filepath is None or not os.path.isfile(filepath):
        return []
    with open(filepath, "r") as f:
        reader = csv.DictReader(f)
        return list(reader)


def convert_elevation(value_str, from_unit, to_unit):
    """Convert elevation between ft and m."""
    val = float(value_str)
    if from_unit == "ft" and to_unit == "m":
        return val * ELEVATION_FT_TO_M
    elif from_unit == "m" and to_unit == "ft":
        return val / ELEVATION_FT_TO_M
    return val


def convert_pipe_diameter(value_str, from_unit, to_unit):
    """Convert pipe diameter between inches and mm."""
    val = float(value_str)
    if from_unit == "in" and to_unit == "mm":
        return val * PIPE_DIAM_IN_TO_MM
    elif from_unit == "mm" and to_unit == "in":
        return val / PIPE_DIAM_IN_TO_MM
    return val


def convert_length(value_str, from_unit, to_unit):
    """Convert length between ft and m."""
    val = float(value_str)
    if from_unit == "ft" and to_unit == "m":
        return val * LENGTH_FT_TO_M
    elif from_unit == "m" and to_unit == "ft":
        return val / LENGTH_FT_TO_M
    return val


def determine_unit_system(flow_units):
    """Determine if US or SI based on flow unit choice."""
    flow_upper = flow_units.upper()
    if flow_upper in US_FLOW_UNITS:
        return "US"
    elif flow_upper in SI_FLOW_UNITS:
        return "SI"
    else:
        raise ValueError(f"Unknown flow unit: {flow_units}")


def write_title(f, title="EPANET Network"):
    """Write [TITLE] section."""
    f.write("[TITLE]\n")
    f.write(f"{title}\n\n")


def write_junctions(f, junctions, input_elev_unit, target_elev_unit):
    """Write [JUNCTIONS] section with optional unit conversion."""
    f.write("[JUNCTIONS]\n")
    f.write(";ID              Elev            Demand          Pattern\n")
    for j in junctions:
        jid = j.get("id", j.get("ID", ""))
        elev = j.get("elevation", j.get("Elev", "0"))
        demand = j.get("demand", j.get("Demand", "0"))
        pattern = j.get("pattern", j.get("Pattern", ""))

        elev_conv = convert_elevation(elev, input_elev_unit, target_elev_unit)
        line = f" {jid:<15s} {elev_conv:<15.2f} {float(demand):<15.2f}"
        if pattern:
            line += f" {pattern}"
        f.write(line + "\n")
    f.write("\n")


def write_reservoirs(f, reservoirs, input_elev_unit, target_elev_unit):
    """Write [RESERVOIRS] section."""
    f.write("[RESERVOIRS]\n")
    f.write(";ID              Head            Pattern\n")
    for r in reservoirs:
        rid = r.get("id", r.get("ID", ""))
        head = r.get("head", r.get("Head", "0"))
        pattern = r.get("pattern", r.get("Pattern", ""))

        head_conv = convert_elevation(head, input_elev_unit, target_elev_unit)
        line = f" {rid:<15s} {head_conv:<15.2f}"
        if pattern:
            line += f" {pattern}"
        f.write(line + "\n")
    f.write("\n")


def write_tanks(f, tanks, input_elev_unit, target_elev_unit):
    """Write [TANKS] section."""
    f.write("[TANKS]\n")
    f.write(";ID    Elev    InitLvl  MinLvl  MaxLvl  Diam    MinVol  VolCurve\n")
    for t in tanks:
        tid = t.get("id", t.get("ID", ""))
        elev = convert_elevation(
            t.get("elevation", t.get("Elev", "0")),
            input_elev_unit, target_elev_unit
        )
        init_lvl = float(t.get("init_level", t.get("InitLvl", "0")))
        min_lvl = float(t.get("min_level", t.get("MinLvl", "0")))
        max_lvl = float(t.get("max_level", t.get("MaxLvl", "0")))
        diam = float(t.get("diameter", t.get("Diam", "0")))
        min_vol = float(t.get("min_volume", t.get("MinVol", "0")))
        volcurve = t.get("vol_curve", t.get("VolCurve", ""))

        f.write(f" {tid:<6s} {elev:<7.1f} {init_lvl:<8.1f} {min_lvl:<7.1f} "
                f"{max_lvl:<7.1f} {diam:<7.1f} {min_vol:<7.1f}")
        if volcurve:
            f.write(f" {volcurve}")
        f.write("\n")
    f.write("\n")


def write_pipes(f, pipes, input_len_unit, target_len_unit,
                input_diam_unit, target_diam_unit):
    """Write [PIPES] section with unit conversion."""
    f.write("[PIPES]\n")
    f.write(";ID    Node1  Node2  Length   Diam   Roughness  MinorLoss  Status\n")
    for p in pipes:
        pid = p.get("id", p.get("ID", ""))
        n1 = p.get("node1", p.get("Node1", ""))
        n2 = p.get("node2", p.get("Node2", ""))
        length = convert_length(
            p.get("length", p.get("Length", "0")),
            input_len_unit, target_len_unit
        )
        diam = convert_pipe_diameter(
            p.get("diameter", p.get("Diam", "0")),
            input_diam_unit, target_diam_unit
        )
        rough = float(p.get("roughness", p.get("Roughness", "100")))
        mloss = float(p.get("minor_loss", p.get("MinorLoss", "0")))
        status = p.get("status", p.get("Status", "Open"))

        f.write(f" {pid:<6s} {n1:<6s} {n2:<6s} {length:<8.1f} {diam:<6.1f} "
                f"{rough:<10.4f} {mloss:<10.4f} {status}\n")
    f.write("\n")


def write_pumps(f, pumps):
    """Write [PUMPS] section."""
    f.write("[PUMPS]\n")
    f.write(";ID    Node1   Node2   Parameters\n")
    for p in pumps:
        pid = p.get("id", p.get("ID", ""))
        n1 = p.get("node1", p.get("Node1", ""))
        n2 = p.get("node2", p.get("Node2", ""))
        params = p.get("parameters", p.get("Parameters", ""))
        f.write(f" {pid:<6s} {n1:<7s} {n2:<7s} {params}\n")
    f.write("\n")


def write_patterns(f, patterns):
    """Write [PATTERNS] section."""
    f.write("[PATTERNS]\n")
    f.write(";ID    Multipliers\n")
    for p in patterns:
        pid = p.get("id", p.get("ID", ""))
        multipliers = p.get("multipliers", p.get("Multipliers", ""))
        f.write(f" {pid:<6s} {multipliers}\n")
    f.write("\n")


def write_curves(f, curves):
    """Write [CURVES] section."""
    f.write("[CURVES]\n")
    f.write(";ID    X-Value   Y-Value\n")
    for c in curves:
        cid = c.get("id", c.get("ID", ""))
        x = c.get("x", c.get("X-Value", "0"))
        y = c.get("y", c.get("Y-Value", "0"))
        f.write(f" {cid:<6s} {float(x):<9.2f} {float(y):<9.2f}\n")
    f.write("\n")


def write_options(f, flow_units, headloss, quality="NONE", pattern="1"):
    """Write [OPTIONS] section."""
    f.write("[OPTIONS]\n")
    f.write(f" Units            {flow_units}\n")
    f.write(f" Headloss         {headloss}\n")
    f.write(f" Pattern          {pattern}\n")
    f.write(f" Quality          {quality}\n")
    f.write(f" Tolerance        0.01\n")
    f.write("\n")


def write_times(f, duration_hrs, hyd_timestep_hrs, qual_timestep_min=5,
                pattern_step_hrs=6, report_step_hrs=1):
    """Write [TIMES] section."""
    f.write("[TIMES]\n")
    f.write(f" Duration            {duration_hrs}:00\n")
    f.write(f" Hydraulic Timestep  {hyd_timestep_hrs}:00\n")
    f.write(f" Quality Timestep    0:{qual_timestep_min:02d}\n")
    f.write(f" Pattern Timestep    {pattern_step_hrs}:00\n")
    f.write(f" Report Timestep     {report_step_hrs}:00\n")
    f.write("\n")


def write_report(f, nodes="All", links="All"):
    """Write [REPORT] section."""
    f.write("[REPORT]\n")
    f.write(f" Page     55\n")
    f.write(f" Energy   Yes\n")
    f.write(f" Nodes    {nodes}\n")
    f.write(f" Links    {links}\n")
    f.write("\n")


def write_end(f):
    """Write [END] section."""
    f.write("[END]\n")


def validate_output(output_path):
    """Validate the generated .inp file has required sections."""
    required_sections = {"[TITLE]", "[JUNCTIONS]", "[OPTIONS]", "[TIMES]", "[END]"}
    found_sections = set()

    with open(output_path, "r") as f:
        for line in f:
            stripped = line.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                found_sections.add(stripped)

    missing = required_sections - found_sections
    if missing:
        print(f"WARNING: Missing required sections: {missing}", file=sys.stderr)
        return False

    print(f"[OK] Output validation passed: {output_path}")
    print(f"     Sections found: {sorted(found_sections)}")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Convert external data to EPANET .inp format"
    )
    parser.add_argument("--junctions", help="Junctions CSV file")
    parser.add_argument("--reservoirs", help="Reservoirs CSV file")
    parser.add_argument("--tanks", help="Tanks CSV file")
    parser.add_argument("--pipes", help="Pipes CSV file")
    parser.add_argument("--pumps", help="Pumps CSV file")
    parser.add_argument("--patterns", help="Patterns CSV file")
    parser.add_argument("--curves", help="Curves CSV file")
    parser.add_argument("--units", default="GPM", help="Flow units (default: GPM)")
    parser.add_argument("--headloss", default="H-W",
                        help="Headloss formula: H-W, D-W, C-M (default: H-W)")
    parser.add_argument("--quality", default="NONE",
                        help="Quality type: NONE, Chlorine mg/L, AGE, TRACE nodeID")
    parser.add_argument("--duration", type=int, default=24,
                        help="Simulation duration in hours (default: 24)")
    parser.add_argument("--timestep", type=int, default=1,
                        help="Hydraulic timestep in hours (default: 1)")
    parser.add_argument("--input-units", default="native",
                        help="Input data units: 'native' (match flow units), 'SI', 'US'")
    parser.add_argument("--title", default="EPANET Network",
                        help="Project title")
    parser.add_argument("--output", required=True, help="Output .inp file path")

    args = parser.parse_args()

    # Step 1: Validate inputs
    validate_inputs(args)

    # Determine target unit system
    unit_system = determine_unit_system(args.units)
    if unit_system == "US":
        target_elev = "ft"
        target_len = "ft"
        target_diam = "in"
    else:
        target_elev = "m"
        target_len = "m"
        target_diam = "mm"

    # Determine input units
    if args.input_units == "native" or args.input_units == unit_system:
        input_elev = target_elev
        input_len = target_len
        input_diam = target_diam
    elif args.input_units == "SI":
        input_elev = "m"
        input_len = "m"
        input_diam = "mm"
    else:
        input_elev = "ft"
        input_len = "ft"
        input_diam = "in"

    # Step 2: Read input data
    junctions = read_csv_section(args.junctions)
    reservoirs = read_csv_section(args.reservoirs)
    tanks = read_csv_section(args.tanks)
    pipes = read_csv_section(args.pipes)
    pumps = read_csv_section(args.pumps)
    patterns = read_csv_section(args.patterns)
    curves = read_csv_section(args.curves)

    print(f"[INFO] Loaded: {len(junctions)} junctions, {len(reservoirs)} reservoirs, "
          f"{len(tanks)} tanks, {len(pipes)} pipes, {len(pumps)} pumps")

    # Step 3: Write .inp file
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w") as f:
        write_title(f, args.title)
        write_junctions(f, junctions, input_elev, target_elev)
        write_reservoirs(f, reservoirs, input_elev, target_elev)
        write_tanks(f, tanks, input_elev, target_elev)
        write_pipes(f, pipes, input_len, target_len, input_diam, target_diam)
        write_pumps(f, pumps)
        write_patterns(f, patterns)
        write_curves(f, curves)
        write_options(f, args.units, args.headloss, args.quality)
        write_times(f, args.duration, args.timestep)
        write_report(f)
        write_end(f)

    # Step 4: Validate output
    validate_output(args.output)
    print(f"[DONE] EPANET input file written: {args.output}")


if __name__ == "__main__":
    main()
