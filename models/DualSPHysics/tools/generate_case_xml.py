#!/usr/bin/env python3
"""
generate_case_xml.py — Generate complete DualSPHysics XML case definition.

Builds a full XML case definition file including geometry, constants,
and execution parameters. Supports common geometries (dam break, wave flume,
coastal structure) and handles all unit conversions.

DualSPHysics XML has two main sections:
  <casedef>: Constants, geometry, MK configuration
  <execution>: Simulation parameters, domain, output

All values must be in SI units (m, s, kg/m^3, m/s).

Usage:
    python generate_case_xml.py --template dambreak --dp 0.01 --output Case_Def.xml
    python generate_case_xml.py --template wave_flume --dp 0.005 --depth 0.5 \\
        --length 10 --output Flume_Def.xml --timemax 10
    python generate_case_xml.py --custom --dp 0.01 --fluid_box 0,0,0,1,1,0.5 \\
        --bound_box 0,0,0,3,1,0.8 --output Custom_Def.xml
"""

import argparse
import json
import math
import os
import sys
import xml.etree.ElementTree as ET
from xml.dom import minidom


# ============================================================================
# Template geometries
# ============================================================================

TEMPLATES = {
    "dambreak": {
        "description": "3D dam break with obstacle",
        "fluid_box": {"x": 0, "y": 0, "z": 0,
                      "sx": 0.4, "sy": 0.67, "sz": 0.3},
        "bound_box": {"x": 0, "y": 0, "z": 0,
                      "sx": 1.6, "sy": 0.67, "sz": 0.4},
        "bound_fill": "bottom|left|right|front|back",
        "obstacle": {"x": 0.9, "y": 0.24, "z": 0,
                     "sx": 0.12, "sy": 0.12, "sz": 0.45},
        "timemax": 1.6,
        "timeout": 0.01,
    },
    "dambreak_2d": {
        "description": "2D dam break (thin slice)",
        "fluid_box": {"x": 0, "y": 0, "z": 0,
                      "sx": 0.15, "sy": 0.01, "sz": 0.3},
        "bound_box": {"x": 0, "y": 0, "z": 0,
                      "sx": 0.8, "sy": 0.01, "sz": 0.35},
        "bound_fill": "bottom|left|right",
        "timemax": 1.0,
        "timeout": 0.005,
    },
    "wave_flume": {
        "description": "Wave flume with beach",
        "fluid_box": {"x": 0, "y": 0, "z": 0,
                      "sx": 10, "sy": 1, "sz": 0.5},
        "bound_box": {"x": -0.5, "y": 0, "z": 0,
                      "sx": 11, "sy": 1, "sz": 0.8},
        "bound_fill": "bottom|left|right|front|back",
        "timemax": 10.0,
        "timeout": 0.05,
    },
    "still_water": {
        "description": "Hydrostatic still water test",
        "fluid_box": {"x": 0, "y": 0, "z": 0,
                      "sx": 1, "sy": 1, "sz": 0.5},
        "bound_box": {"x": 0, "y": 0, "z": 0,
                      "sx": 1, "sy": 1, "sz": 0.6},
        "bound_fill": "bottom|left|right|front|back",
        "timemax": 2.0,
        "timeout": 0.01,
    },
}


def validate_inputs(args):
    """Validate inputs before generating XML."""
    errors = []
    warnings = []

    # Check dp
    if args.dp <= 0:
        errors.append(f"dp must be positive, got {args.dp}")
    if args.dp > 1.0:
        warnings.append(f"dp={args.dp}m is very large — probably in wrong units")
    if args.dp < 0.0001:
        warnings.append(f"dp={args.dp}m is extremely small — very slow simulation")

    # Check template
    if args.template and args.template not in TEMPLATES:
        errors.append(f"Unknown template '{args.template}'. "
                      f"Available: {list(TEMPLATES.keys())}")

    # Check custom geometry
    if args.custom:
        if not args.fluid_box:
            errors.append("--fluid_box required for custom geometry "
                          "(x,y,z,sx,sy,sz)")
        if not args.bound_box:
            errors.append("--bound_box required for custom geometry "
                          "(x,y,z,sx,sy,sz)")

    # Check output dir
    out_dir = os.path.dirname(args.output)
    if out_dir and not os.path.isdir(out_dir):
        os.makedirs(out_dir, exist_ok=True)

    # Check gravity direction
    if args.gravity_dir not in ("z", "y"):
        errors.append(f"gravity_dir must be 'z' or 'y', got '{args.gravity_dir}'")

    result = {"status": "error" if errors else "ok", "errors": errors,
              "warnings": warnings}
    if errors:
        print(json.dumps(result, indent=2), file=sys.stderr)
    return result


def parse_box_string(box_str):
    """Parse a box string 'x,y,z,sx,sy,sz' into dict."""
    parts = [float(p) for p in box_str.split(",")]
    if len(parts) != 6:
        raise ValueError(f"Box needs 6 values (x,y,z,sx,sy,sz), got {len(parts)}")
    return {"x": parts[0], "y": parts[1], "z": parts[2],
            "sx": parts[3], "sy": parts[4], "sz": parts[5]}


def build_constants_xml(parent, args):
    """Build <constantsdef> XML element."""
    cdef = ET.SubElement(parent, "constantsdef")

    gx, gy, gz = 0, 0, 0
    if args.gravity_dir == "z":
        gz = -args.gravity
    else:
        gy = -args.gravity

    ET.SubElement(cdef, "gravity", x=str(gx), y=str(gy), z=str(gz),
                  comment="Gravitational acceleration",
                  units_comment="m/s^2")
    ET.SubElement(cdef, "rhop0", value=str(args.rhop0),
                  comment="Reference density of the fluid",
                  units_comment="kg/m^3")
    ET.SubElement(cdef, "rhopgradient", value="2",
                  comment="1:Rhop0, 2:Water column, 3:Max water height")
    ET.SubElement(cdef, "hswl", value="0", auto="true",
                  units_comment="metres (m)")
    ET.SubElement(cdef, "gamma", value=str(args.gamma),
                  comment="Polytropic constant")
    ET.SubElement(cdef, "speedsystem", value="0", auto="true")
    ET.SubElement(cdef, "coefsound", value=str(args.coefsound),
                  comment="Coefficient to multiply speedsystem")
    ET.SubElement(cdef, "speedsound", value="0", auto="true")
    ET.SubElement(cdef, "coefh", value=str(args.coefh),
                  comment="h=coefh*sqrt(3*dp^2) in 3D")
    ET.SubElement(cdef, "cflnumber", value=str(args.cflnumber),
                  comment="CFL coefficient for dt")

    return cdef


def build_geometry_xml(parent, args, template=None):
    """Build <geometry> XML element."""
    geom = ET.SubElement(parent, "geometry")

    # Domain definition
    if template:
        bb = template["bound_box"]
        margin = args.dp * 5
        defn = ET.SubElement(geom, "definition", dp=str(args.dp),
                             units_comment="metres (m)")
        ET.SubElement(defn, "pointmin",
                      x=str(bb["x"] - margin),
                      y=str(bb["y"] - margin),
                      z=str(bb["z"] - margin))
        ET.SubElement(defn, "pointmax",
                      x=str(bb["x"] + bb["sx"] + margin),
                      y=str(bb["y"] + bb["sy"] + margin),
                      z=str(bb["z"] + bb["sz"] + margin))
    else:
        defn = ET.SubElement(geom, "definition", dp=str(args.dp),
                             units_comment="metres (m)")
        ET.SubElement(defn, "pointmin", x="-0.1", y="-0.1", z="-0.1")
        ET.SubElement(defn, "pointmax", x="5", y="5", z="5")

    commands = ET.SubElement(geom, "commands")
    mainlist = ET.SubElement(commands, "mainlist")

    ET.SubElement(mainlist, "setshapemode").text = "dp | bound"
    ET.SubElement(mainlist, "setdrawmode", mode="full")

    if template:
        # Fluid
        fb = template["fluid_box"]
        ET.SubElement(mainlist, "setmkfluid", mk="0")
        drawbox = ET.SubElement(mainlist, "drawbox")
        ET.SubElement(drawbox, "boxfill").text = "solid"
        ET.SubElement(drawbox, "point",
                      x=str(fb["x"]), y=str(fb["y"]), z=str(fb["z"]))
        ET.SubElement(drawbox, "size",
                      x=str(fb["sx"]), y=str(fb["sy"]), z=str(fb["sz"]))

        # Boundary
        bb = template["bound_box"]
        ET.SubElement(mainlist, "setmkbound", mk="0")
        drawbox_b = ET.SubElement(mainlist, "drawbox")
        ET.SubElement(drawbox_b, "boxfill").text = template.get(
            "bound_fill", "bottom|left|right|front|back")
        ET.SubElement(drawbox_b, "point",
                      x=str(bb["x"]), y=str(bb["y"]), z=str(bb["z"]))
        ET.SubElement(drawbox_b, "size",
                      x=str(bb["sx"]), y=str(bb["sy"]), z=str(bb["sz"]))
        ET.SubElement(mainlist, "shapeout", file="Container")

        # Obstacle (if present)
        if "obstacle" in template:
            ob = template["obstacle"]
            ET.SubElement(mainlist, "setmkbound", mk="1")
            drawbox_o = ET.SubElement(mainlist, "drawbox")
            ET.SubElement(drawbox_o, "boxfill").text = "top|left|right|front|back"
            ET.SubElement(drawbox_o, "point",
                          x=str(ob["x"]), y=str(ob["y"]), z=str(ob["z"]))
            ET.SubElement(drawbox_o, "size",
                          x=str(ob["sx"]), y=str(ob["sy"]), z=str(ob["sz"]))
            ET.SubElement(mainlist, "shapeout", file="Obstacle")

    elif args.custom:
        fb = parse_box_string(args.fluid_box)
        bb = parse_box_string(args.bound_box)

        ET.SubElement(mainlist, "setmkfluid", mk="0")
        drawbox = ET.SubElement(mainlist, "drawbox")
        ET.SubElement(drawbox, "boxfill").text = "solid"
        ET.SubElement(drawbox, "point",
                      x=str(fb["x"]), y=str(fb["y"]), z=str(fb["z"]))
        ET.SubElement(drawbox, "size",
                      x=str(fb["sx"]), y=str(fb["sy"]), z=str(fb["sz"]))

        ET.SubElement(mainlist, "setmkbound", mk="0")
        drawbox_b = ET.SubElement(mainlist, "drawbox")
        ET.SubElement(drawbox_b, "boxfill").text = "bottom|left|right|front|back"
        ET.SubElement(drawbox_b, "point",
                      x=str(bb["x"]), y=str(bb["y"]), z=str(bb["z"]))
        ET.SubElement(drawbox_b, "size",
                      x=str(bb["sx"]), y=str(bb["sy"]), z=str(bb["sz"]))
        ET.SubElement(mainlist, "shapeout", file="Domain")

    return geom


def build_execution_xml(parent, args, template=None):
    """Build <execution> XML element."""
    execution = ET.SubElement(parent, "execution")
    params = ET.SubElement(execution, "parameters")

    timemax = args.timemax or (template["timemax"] if template else 2.0)
    timeout = args.timeout or (template["timeout"] if template else 0.01)

    param_list = [
        ("SavePosDouble", "0"),
        ("StepAlgorithm", "2" if args.symplectic else "1"),
        ("VerletSteps", "40"),
        ("Kernel", "2"),
        ("ViscoTreatment", str(args.visco_treatment)),
        ("Visco", str(args.visco)),
        ("ViscoBoundFactor", "1"),
        ("DensityDT", str(args.ddt_mode)),
        ("DensityDTvalue", str(args.ddt_value)),
        ("Shifting", "0"),
        ("ShiftCoef", "-2"),
        ("ShiftTFS", "0"),
        ("RigidAlgorithm", "1"),
        ("FtPause", "0.0"),
        ("CoefDtMin", "0.05"),
        ("DtIni", "0"),
        ("DtMin", "0"),
        ("DtFixed", "0"),
        ("DtAllParticles", "0"),
        ("TimeMax", str(timemax)),
        ("TimeOut", str(timeout)),
        ("PartsOutMax", "1"),
        ("RhopOutMin", str(int(args.rhop0 * 0.7))),
        ("RhopOutMax", str(int(args.rhop0 * 1.3))),
    ]

    for key, value in param_list:
        ET.SubElement(params, "parameter", key=key, value=value)

    # Simulation domain
    simdom = ET.SubElement(params, "simulationdomain")
    ET.SubElement(simdom, "posmin", x="default", y="default", z="default")
    ET.SubElement(simdom, "posmax", x="default", y="default",
                  z="default + 50%")

    return execution


def prettify_xml(elem):
    """Pretty-print XML."""
    rough = ET.tostring(elem, encoding="unicode")
    parsed = minidom.parseString(rough)
    lines = parsed.toprettyxml(indent="    ").split("\n")
    # Remove blank lines
    return "\n".join(l for l in lines if l.strip())


def validate_output(filepath):
    """Validate generated case XML."""
    warnings = []
    try:
        tree = ET.parse(filepath)
        root = tree.getroot()
        if root.tag != "case":
            warnings.append(f"Root element is '{root.tag}', expected 'case'")

        # Check for casedef and execution
        if root.find("casedef") is None:
            warnings.append("Missing <casedef> section")
        if root.find("execution") is None:
            warnings.append("Missing <execution> section")

        # Check dp
        defn = root.find(".//definition")
        if defn is not None:
            dp = float(defn.get("dp", 0))
            if dp <= 0:
                warnings.append(f"Invalid dp={dp}")
    except ET.ParseError as e:
        warnings.append(f"XML parse error: {e}")

    return warnings


def process(args):
    """Main pipeline: validate -> generate -> validate."""
    # 1. Validate
    result = validate_inputs(args)
    if result["status"] == "error":
        return result

    template = TEMPLATES.get(args.template) if args.template else None

    # 2. Build XML
    case = ET.Element("case")

    casedef = ET.SubElement(case, "casedef")
    build_constants_xml(casedef, args)
    ET.SubElement(casedef, "mkconfig", boundcount="240", fluidcount="9")
    build_geometry_xml(casedef, args, template)

    build_execution_xml(case, args, template)

    # 3. Write
    xml_str = '<?xml version="1.0" encoding="UTF-8" ?>\n'
    xml_str += prettify_xml(case)

    with open(args.output, "w") as f:
        f.write(xml_str)

    # 4. Validate output
    out_warnings = validate_output(args.output)
    all_warnings = result.get("warnings", []) + out_warnings

    # Estimate particle count
    if template:
        fb = template["fluid_box"]
        vol = fb["sx"] * fb["sy"] * fb["sz"]
    elif args.custom and args.fluid_box:
        fb = parse_box_string(args.fluid_box)
        vol = fb["sx"] * fb["sy"] * fb["sz"]
    else:
        vol = 1.0

    est_particles = int(vol / (args.dp ** 3))

    return {
        "status": "ok",
        "output": args.output,
        "template": args.template or "custom",
        "dp": args.dp,
        "estimated_fluid_particles": est_particles,
        "warnings": all_warnings,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Generate DualSPHysics case XML")
    parser.add_argument("--output", "-o", required=True, help="Output XML")
    parser.add_argument("--template",
                        choices=list(TEMPLATES.keys()),
                        help="Use predefined template")
    parser.add_argument("--custom", action="store_true",
                        help="Custom geometry mode")
    parser.add_argument("--fluid_box", help="Fluid box: x,y,z,sx,sy,sz")
    parser.add_argument("--bound_box", help="Boundary box: x,y,z,sx,sy,sz")
    parser.add_argument("--dp", type=float, required=True,
                        help="Particle spacing (meters)")
    parser.add_argument("--rhop0", type=float, default=1000,
                        help="Reference density (kg/m^3)")
    parser.add_argument("--gravity", type=float, default=9.81,
                        help="Gravity magnitude (m/s^2)")
    parser.add_argument("--gravity_dir", default="z",
                        choices=["z", "y"],
                        help="Gravity direction (default: z)")
    parser.add_argument("--gamma", type=float, default=7,
                        help="Polytropic constant")
    parser.add_argument("--coefsound", type=float, default=20,
                        help="Speed of sound coefficient")
    parser.add_argument("--coefh", type=float, default=1.0,
                        help="Smoothing length coefficient")
    parser.add_argument("--cflnumber", type=float, default=0.2,
                        help="CFL number")
    parser.add_argument("--visco_treatment", type=int, default=1,
                        choices=[1, 2, 3],
                        help="1:Artificial, 2:Lam+SPS, 3:Laminar")
    parser.add_argument("--visco", type=float, default=0.1,
                        help="Viscosity value")
    parser.add_argument("--symplectic", action="store_true",
                        help="Symplectic integration")
    parser.add_argument("--ddt_mode", type=int, default=2,
                        help="DDT mode (0-3)")
    parser.add_argument("--ddt_value", type=float, default=0.1,
                        help="DDT coefficient")
    parser.add_argument("--timemax", type=float, help="Max time (s)")
    parser.add_argument("--timeout", type=float, help="Output interval (s)")

    args = parser.parse_args()
    result = process(args)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["status"] == "ok" else 1)


if __name__ == "__main__":
    main()
