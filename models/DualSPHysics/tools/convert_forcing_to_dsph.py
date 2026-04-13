#!/usr/bin/env python3
"""
convert_forcing_to_dsph.py — Convert wave/current forcing data to DualSPHysics XML format.

Converts global forcing data (wave heights, periods, currents, water levels)
into DualSPHysics-compatible XML inlet/outlet boundary conditions or
wave paddle configurations.

DualSPHysics expects all values in SI units:
  - Velocity: m/s
  - Wave height: m (NOT cm or mm)
  - Wave period: s
  - Water level: m (NOT cm)
  - Density: kg/m^3 (NOT g/cm^3)

Usage:
    python convert_forcing_to_dsph.py --input forcing.csv --output inlet_config.xml \\
        --type inlet --velocity 2.0 --depth 1.0
    python convert_forcing_to_dsph.py --input waves.csv --output wave_config.xml \\
        --type wave_paddle --height_col Hs --period_col Tp
"""

import argparse
import csv
import json
import os
import sys
import xml.etree.ElementTree as ET
from xml.dom import minidom


# ============================================================================
# Unit conversion constants
# ============================================================================
UNIT_CONVERSIONS = {
    "velocity": {
        "m/s": 1.0,
        "cm/s": 0.01,
        "ft/s": 0.3048,
        "knots": 0.51444,
        "km/h": 1.0 / 3.6,
    },
    "length": {
        "m": 1.0,
        "cm": 0.01,
        "mm": 0.001,
        "ft": 0.3048,
        "in": 0.0254,
    },
    "density": {
        "kg/m3": 1.0,
        "g/cm3": 1000.0,
        "g/L": 1.0,
    },
    "time": {
        "s": 1.0,
        "min": 60.0,
        "hr": 3600.0,
    },
}


def convert_unit(value, quantity, from_unit):
    """Convert a value to SI units (m, s, kg/m3).

    Args:
        value: Numeric value to convert.
        quantity: One of 'velocity', 'length', 'density', 'time'.
        from_unit: Source unit string.

    Returns:
        Value in SI units.

    Raises:
        ValueError: If unit not recognized.
    """
    if quantity not in UNIT_CONVERSIONS:
        raise ValueError(f"Unknown quantity: {quantity}. "
                         f"Valid: {list(UNIT_CONVERSIONS.keys())}")
    units = UNIT_CONVERSIONS[quantity]
    if from_unit not in units:
        raise ValueError(f"Unknown unit '{from_unit}' for {quantity}. "
                         f"Valid: {list(units.keys())}")
    return value * units[from_unit]


def validate_inputs(args):
    """Validate input arguments and file existence.

    Returns:
        dict with 'status', 'errors', 'warnings' keys.
    """
    errors = []
    warnings = []

    # Check input file exists (if provided)
    if args.input and not os.path.exists(args.input):
        errors.append(f"Input file not found: {args.input}")

    # Check output directory exists
    out_dir = os.path.dirname(args.output)
    if out_dir and not os.path.isdir(out_dir):
        errors.append(f"Output directory not found: {out_dir}")

    # Check type
    valid_types = ["inlet", "wave_paddle", "relaxation_zone", "velocity_profile"]
    if args.type not in valid_types:
        errors.append(f"Invalid type '{args.type}'. Valid: {valid_types}")

    # Check velocity range
    if args.velocity is not None:
        vel_si = convert_unit(args.velocity, "velocity", args.vel_unit)
        if vel_si > 50.0:
            warnings.append(f"Velocity {vel_si:.2f} m/s is very high (>50 m/s). "
                            "Check units.")
        if vel_si < 0:
            warnings.append(f"Negative velocity {vel_si:.2f} m/s — flow is reversed.")

    # Check depth
    if args.depth is not None:
        depth_si = convert_unit(args.depth, "length", args.length_unit)
        if depth_si > 100.0:
            warnings.append(f"Depth {depth_si:.2f} m is very large. Check units.")
        if depth_si <= 0:
            errors.append(f"Depth must be positive, got {depth_si:.2f} m")

    result = {"status": "error" if errors else "ok", "errors": errors,
              "warnings": warnings}
    if errors:
        print(json.dumps(result, indent=2), file=sys.stderr)
    return result


def prettify_xml(elem):
    """Return a pretty-printed XML string."""
    rough = ET.tostring(elem, encoding="unicode")
    parsed = minidom.parseString(rough)
    return parsed.toprettyxml(indent="  ")


def generate_inlet_xml(args):
    """Generate XML for inlet/outlet boundary conditions.

    DualSPHysics inlet expects velocity in m/s and positions in meters.
    """
    vel_si = convert_unit(args.velocity, "velocity", args.vel_unit)
    depth_si = convert_unit(args.depth, "length", args.length_unit)

    # Build XML structure
    special = ET.Element("special")
    inout = ET.SubElement(special, "inout")

    # Memory configuration
    mem = ET.SubElement(inout, "memoryresize", size0="2", size="4")

    # Inlet zone
    zone = ET.SubElement(inout, "inoutzone")
    ET.SubElement(zone, "refilling", value="1",
                  comment="0:Full, 1:BelowZsurf, 2:Advanced")
    ET.SubElement(zone, "inputtreatment", value="0",
                  comment="0:NoChange, 1:Convert, 2:Remove")
    ET.SubElement(zone, "layers", value="8")

    # Zone geometry (2D line or 3D plane)
    if args.dimension == "2d":
        zone2d = ET.SubElement(zone, "zone2d")
        line = ET.SubElement(zone2d, "line")
        ET.SubElement(line, "point", x=str(args.inlet_x), z="0")
        ET.SubElement(line, "point2", x=str(args.inlet_x),
                      z=str(depth_si))
        ET.SubElement(line, "direction", x="1", z="0")
    else:
        zone3d = ET.SubElement(zone, "zone3d")
        plane = ET.SubElement(zone3d, "plane")
        ET.SubElement(plane, "point", x=str(args.inlet_x), y="0", z="0")
        ET.SubElement(plane, "point2", x=str(args.inlet_x),
                      y=str(args.width or 1.0), z="0")
        ET.SubElement(plane, "point3", x=str(args.inlet_x), y="0",
                      z=str(depth_si))
        ET.SubElement(plane, "direction", x="1", y="0", z="0")

    # Velocity
    impose_vel = ET.SubElement(zone, "imposevelocity", mode="0",
                               comment="0:Fixed, 1:Variable, 2:Extrapolated")
    ET.SubElement(impose_vel, "velocity", v=f"{vel_si:.6f}",
                  comment=f"m/s (converted from {args.velocity} {args.vel_unit})")

    # Density
    ET.SubElement(zone, "imposerhop", mode="2",
                  comment="0:Fixed, 1:Hydrostatic, 2:Extrapolated")

    return special


def generate_wave_paddle_xml(args):
    """Generate XML for wave paddle configuration.

    Reads wave data from CSV (height, period columns) and generates
    regular or irregular wave paddle specification.
    """
    special = ET.Element("special")

    if args.input and os.path.exists(args.input):
        # Read wave data from CSV
        with open(args.input) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        if not rows:
            raise ValueError("Empty CSV file")

        # Get mean wave parameters
        heights = [float(r[args.height_col]) for r in rows
                   if args.height_col in r]
        periods = [float(r[args.period_col]) for r in rows
                   if args.period_col in r]

        h_mean = sum(heights) / len(heights)
        t_mean = sum(periods) / len(periods)

        # Convert units
        h_si = convert_unit(h_mean, "length", args.length_unit)
        t_si = convert_unit(t_mean, "time", args.time_unit)
    else:
        h_si = convert_unit(args.wave_height or 0.1, "length", args.length_unit)
        t_si = convert_unit(args.wave_period or 1.0, "time", args.time_unit)

    depth_si = convert_unit(args.depth, "length", args.length_unit)

    # Wave paddle XML
    wavepaddles = ET.SubElement(special, "wavepaddles")
    piston = ET.SubElement(wavepaddles, "piston")
    ET.SubElement(piston, "mkbound", value="0",
                  comment="MK of piston boundary particles")
    ET.SubElement(piston, "waveorder", value="2",
                  comment="1:1st order, 2:2nd order")
    ET.SubElement(piston, "start", value="0",
                  comment="Start time in seconds")
    ET.SubElement(piston, "duration", value="0",
                  comment="0=entire simulation")
    ET.SubElement(piston, "depth", value=f"{depth_si:.4f}",
                  comment=f"Water depth in meters")
    ET.SubElement(piston, "pistondir", x="1", y="0", z="0")

    awas = ET.SubElement(piston, "awas")
    ET.SubElement(awas, "startawas", value="0")
    ET.SubElement(awas, "swl", value=f"{depth_si:.4f}",
                  comment="Still water level (m)")
    ET.SubElement(awas, "elevation", value="2",
                  comment="2=use free surface")
    ET.SubElement(awas, "gaugex", value="2.0")
    ET.SubElement(awas, "gaugey", value="0")
    ET.SubElement(awas, "gaugezmin", value="0")
    ET.SubElement(awas, "gaugezmax", value=f"{depth_si * 1.5:.4f}")
    ET.SubElement(awas, "coefmasslimit", value="0.5")
    ET.SubElement(awas, "savedata", value="1")

    regular = ET.SubElement(piston, "regular")
    ET.SubElement(regular, "waveheight", value=f"{h_si:.6f}",
                  comment=f"Wave height in meters")
    ET.SubElement(regular, "waveperiod", value=f"{t_si:.4f}",
                  comment=f"Wave period in seconds")
    ET.SubElement(regular, "phase", value="0")

    return special


def generate_relaxation_zone_xml(args):
    """Generate relaxation zone XML for wave absorption."""
    vel_si = convert_unit(args.velocity or 0, "velocity", args.vel_unit)
    depth_si = convert_unit(args.depth, "length", args.length_unit)

    special = ET.Element("special")
    rzones = ET.SubElement(special, "relaxationzones")

    rz = ET.SubElement(rzones, "rzwaves_regular")
    ET.SubElement(rz, "start", value="0")
    ET.SubElement(rz, "duration", value="0")
    ET.SubElement(rz, "depth", value=f"{depth_si:.4f}")
    ET.SubElement(rz, "swl", value=f"{depth_si:.4f}")
    ET.SubElement(rz, "center", x="0", y="0", z="0")
    ET.SubElement(rz, "width", value="1.0")
    ET.SubElement(rz, "waveheight",
                  value=f"{convert_unit(args.wave_height or 0.1, 'length', args.length_unit):.6f}")
    ET.SubElement(rz, "waveperiod",
                  value=f"{convert_unit(args.wave_period or 1.0, 'time', args.time_unit):.4f}")
    ET.SubElement(rz, "phase", value="0")
    ET.SubElement(rz, "ramp", value="1.0")

    return special


def process(args):
    """Main processing: validate -> convert -> validate output."""
    # 1. Validate inputs
    result = validate_inputs(args)
    if result["status"] == "error":
        return result

    # 2. Generate XML
    generators = {
        "inlet": generate_inlet_xml,
        "wave_paddle": generate_wave_paddle_xml,
        "relaxation_zone": generate_relaxation_zone_xml,
        "velocity_profile": generate_inlet_xml,  # same structure
    }

    gen_func = generators[args.type]
    xml_elem = gen_func(args)

    # 3. Write output
    xml_str = prettify_xml(xml_elem)
    with open(args.output, "w") as f:
        f.write(xml_str)

    # 4. Validate output
    output_errors = validate_output(args.output)
    if output_errors:
        return {"status": "warning", "errors": [], "warnings": output_errors,
                "output_file": args.output}

    return {"status": "ok", "output_file": args.output,
            "warnings": result.get("warnings", [])}


def validate_output(filepath):
    """Validate the generated XML output."""
    warnings = []
    try:
        tree = ET.parse(filepath)
        root = tree.getroot()
        if root.tag != "special":
            warnings.append(f"Root element is '{root.tag}', expected 'special'")
    except ET.ParseError as e:
        warnings.append(f"Generated XML is not valid: {e}")

    fsize = os.path.getsize(filepath)
    if fsize < 50:
        warnings.append(f"Output file is very small ({fsize} bytes)")

    return warnings


def main():
    parser = argparse.ArgumentParser(
        description="Convert forcing data to DualSPHysics XML format")
    parser.add_argument("--input", "-i", help="Input CSV file with forcing data")
    parser.add_argument("--output", "-o", required=True,
                        help="Output XML file path")
    parser.add_argument("--type", "-t", required=True,
                        choices=["inlet", "wave_paddle", "relaxation_zone",
                                 "velocity_profile"],
                        help="Type of forcing configuration")
    parser.add_argument("--velocity", type=float,
                        help="Inlet velocity value")
    parser.add_argument("--depth", type=float, default=1.0,
                        help="Water depth (default: 1.0)")
    parser.add_argument("--vel_unit", default="m/s",
                        choices=list(UNIT_CONVERSIONS["velocity"].keys()),
                        help="Velocity input unit (default: m/s)")
    parser.add_argument("--length_unit", default="m",
                        choices=list(UNIT_CONVERSIONS["length"].keys()),
                        help="Length input unit (default: m)")
    parser.add_argument("--time_unit", default="s",
                        choices=list(UNIT_CONVERSIONS["time"].keys()),
                        help="Time input unit (default: s)")
    parser.add_argument("--dimension", default="3d", choices=["2d", "3d"],
                        help="Simulation dimension")
    parser.add_argument("--inlet_x", type=float, default=0.0,
                        help="Inlet X position (meters)")
    parser.add_argument("--width", type=float,
                        help="Channel width for 3D (meters)")
    parser.add_argument("--wave_height", type=float,
                        help="Wave height (in length_unit)")
    parser.add_argument("--wave_period", type=float,
                        help="Wave period (in time_unit)")
    parser.add_argument("--height_col", default="Hs",
                        help="CSV column name for wave height")
    parser.add_argument("--period_col", default="Tp",
                        help="CSV column name for wave period")

    args = parser.parse_args()
    result = process(args)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["status"] in ("ok", "warning") else 1)


if __name__ == "__main__":
    main()
