#!/usr/bin/env python3
"""
convert_parameters.py — Convert physical/material parameters to DualSPHysics XML.

Converts soil, sediment, fluid, and material properties from various databases
(HWSD, literature, user input) to DualSPHysics execution parameters XML.

Handles unit conversions:
  - Density: g/cm^3 -> kg/m^3
  - Viscosity: cSt or cm^2/s -> m^2/s
  - Gravity: varied -> m/s^2
  - Lengths: cm, mm, ft -> m

Usage:
    python convert_parameters.py --fluid water --dp 0.01 --depth 1.0 \\
        --output params.xml --timemax 5.0 --timeout 0.01
    python convert_parameters.py --fluid_density 1025 --fluid_viscosity 1.08e-6 \\
        --dp 0.005 --output params.xml
"""

import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET
from xml.dom import minidom


# ============================================================================
# Predefined fluid properties (at 20 degC unless noted)
# ============================================================================
FLUID_DB = {
    "water": {
        "density_kgm3": 998.2,
        "kinematic_viscosity_m2s": 1.004e-6,
        "description": "Fresh water at 20C",
    },
    "seawater": {
        "density_kgm3": 1025.0,
        "kinematic_viscosity_m2s": 1.08e-6,
        "description": "Seawater at 20C, 35 ppt salinity",
    },
    "oil_light": {
        "density_kgm3": 850.0,
        "kinematic_viscosity_m2s": 5.0e-5,
        "description": "Light crude oil",
    },
    "oil_heavy": {
        "density_kgm3": 920.0,
        "kinematic_viscosity_m2s": 2.0e-4,
        "description": "Heavy crude oil",
    },
    "glycerin": {
        "density_kgm3": 1261.0,
        "kinematic_viscosity_m2s": 1.18e-3,
        "description": "Glycerin at 20C",
    },
    "mud": {
        "density_kgm3": 1300.0,
        "kinematic_viscosity_m2s": 1.0e-3,
        "description": "Sediment-laden fluid",
    },
}

# Recommended parameter ranges
PARAM_RANGES = {
    "dp": (0.0005, 0.5, "m"),
    "coefsound": (10, 40, "dimensionless"),
    "coefh": (0.8, 2.5, "dimensionless"),
    "cflnumber": (0.05, 0.5, "dimensionless"),
    "visco_artificial": (0.001, 1.0, "dimensionless"),
    "visco_laminar": (1e-7, 1e-2, "m^2/s"),
    "gamma": (1, 7, "dimensionless"),
}


def validate_inputs(args):
    """Validate input parameters and check ranges."""
    errors = []
    warnings = []

    # Validate dp
    if args.dp is not None:
        if args.dp_unit == "mm":
            dp_m = args.dp * 0.001
        elif args.dp_unit == "cm":
            dp_m = args.dp * 0.01
        else:
            dp_m = args.dp

        rng = PARAM_RANGES["dp"]
        if dp_m < rng[0]:
            warnings.append(f"dp={dp_m}m is very small (<{rng[0]}m). "
                            "Simulation will be extremely slow.")
        if dp_m > rng[1]:
            warnings.append(f"dp={dp_m}m is very large (>{rng[1]}m). "
                            "Resolution may be insufficient.")

    # Validate density
    if args.fluid_density is not None:
        rho = args.fluid_density
        if args.density_unit == "g/cm3":
            rho *= 1000.0
        if rho < 1.0:
            warnings.append(f"Density {rho} kg/m^3 is extremely low. "
                            "Did you mean g/cm^3?")
        if rho > 20000:
            warnings.append(f"Density {rho} kg/m^3 is extremely high. "
                            "Check units.")

    # Validate viscosity
    if args.fluid_viscosity is not None:
        nu = args.fluid_viscosity
        if args.viscosity_unit == "cSt":
            nu *= 1e-6
        elif args.viscosity_unit == "cm2/s":
            nu *= 1e-4
        if nu > 1.0:
            warnings.append(f"Kinematic viscosity {nu} m^2/s is very high. "
                            "Check units.")

    # Check output directory
    out_dir = os.path.dirname(args.output)
    if out_dir and not os.path.isdir(out_dir):
        errors.append(f"Output directory not found: {out_dir}")

    result = {"status": "error" if errors else "ok", "errors": errors,
              "warnings": warnings}
    if errors:
        print(json.dumps(result, indent=2), file=sys.stderr)
    return result


def get_fluid_properties(args):
    """Get fluid properties from database or user input."""
    if args.fluid and args.fluid in FLUID_DB:
        props = FLUID_DB[args.fluid].copy()
    else:
        props = {
            "density_kgm3": 998.2,
            "kinematic_viscosity_m2s": 1.004e-6,
            "description": "Custom fluid",
        }

    # Override with user values
    if args.fluid_density is not None:
        rho = args.fluid_density
        if args.density_unit == "g/cm3":
            rho *= 1000.0
        props["density_kgm3"] = rho

    if args.fluid_viscosity is not None:
        nu = args.fluid_viscosity
        if args.viscosity_unit == "cSt":
            nu *= 1e-6
        elif args.viscosity_unit == "cm2/s":
            nu *= 1e-4
        props["kinematic_viscosity_m2s"] = nu

    return props


def compute_derived_parameters(dp, depth, fluid_props, args):
    """Compute derived SPH parameters from physical properties.

    Returns:
        dict with all parameters needed for XML generation.
    """
    import math

    rhop0 = fluid_props["density_kgm3"]
    nu = fluid_props["kinematic_viscosity_m2s"]

    # Gravity
    gravity = args.gravity if args.gravity else 9.81

    # Smoothing length
    coefh = args.coefh if args.coefh else 1.0
    h = coefh * math.sqrt(3.0 * dp ** 2)

    # Speed of system (dam break propagation)
    speedsystem = math.sqrt(gravity * depth)

    # Speed of sound (typically 10-20x max velocity)
    coefsound = args.coefsound if args.coefsound else 20
    speedsound = coefsound * speedsystem

    # CFL number
    cflnumber = args.cflnumber if args.cflnumber else 0.2

    # Viscosity treatment
    if args.visco_treatment == "artificial":
        visco_treatment = 1
        visco_value = args.visco_value if args.visco_value else 0.01
    elif args.visco_treatment == "laminar_sps":
        visco_treatment = 2
        visco_value = nu
    elif args.visco_treatment == "laminar":
        visco_treatment = 3
        visco_value = nu
    else:
        visco_treatment = 1
        visco_value = 0.01

    return {
        "dp": dp,
        "gravity_x": 0.0,
        "gravity_y": 0.0,
        "gravity_z": -gravity,
        "rhop0": rhop0,
        "gamma": args.gamma if args.gamma else 7,
        "coefh": coefh,
        "h": h,
        "coefsound": coefsound,
        "speedsound": speedsound,
        "cflnumber": cflnumber,
        "visco_treatment": visco_treatment,
        "visco_value": visco_value,
        "kinematic_viscosity": nu,
        "step_algorithm": 2 if args.symplectic else 1,
        "kernel": 2,  # Wendland default
        "boundary": 2 if args.mdbc else 1,
        "ddt_mode": args.ddt_mode if args.ddt_mode else 2,
        "ddt_value": args.ddt_value if args.ddt_value else 0.1,
        "timemax": args.timemax if args.timemax else 2.0,
        "timeout": args.timeout if args.timeout else 0.01,
        "rhop_out_min": max(100, rhop0 * 0.7),
        "rhop_out_max": rhop0 * 1.3,
    }


def generate_xml(params, fluid_props):
    """Generate DualSPHysics parameters XML."""
    execution = ET.Element("execution")
    parameters = ET.SubElement(execution, "parameters")

    # Add each parameter
    param_list = [
        ("SavePosDouble", "0", "Save position as double precision"),
        ("Boundary", str(params["boundary"]),
         "1:DBC, 2:mDBC"),
        ("StepAlgorithm", str(params["step_algorithm"]),
         "1:Verlet, 2:Symplectic"),
        ("VerletSteps", "40", "Euler steps for Verlet stability"),
        ("Kernel", str(params["kernel"]),
         "1:Cubic, 2:Wendland"),
        ("ViscoTreatment", str(params["visco_treatment"]),
         "1:Artificial, 2:Laminar+SPS, 3:Laminar"),
        ("Visco", f"{params['visco_value']:.6g}",
         f"Units: {'dimensionless' if params['visco_treatment'] == 1 else 'm^2/s'}"),
        ("ViscoBoundFactor", "1", "Boundary viscosity multiplier"),
        ("DensityDT", str(params["ddt_mode"]),
         "0:None, 1:Molteni, 2:Fourtakas, 3:Fourtakas(full)"),
        ("DensityDTvalue", f"{params['ddt_value']:.2f}",
         "DDT coefficient"),
        ("Shifting", "0", "0:None, 1:NoBound, 2:NoFixed, 3:Full"),
        ("ShiftCoef", "-2", "Shifting coefficient"),
        ("ShiftTFS", "0", "Free surface threshold"),
        ("RigidAlgorithm", "1", "0:collision-free, 1:SPH, 2:DEM, 3:Chrono"),
        ("FtPause", "0.0", "Floating body warmup time (s)"),
        ("CoefDtMin", "0.05", "Minimum dt coefficient"),
        ("DtIni", "0", "Initial dt (0=auto)"),
        ("DtMin", "0", "Minimum dt (0=auto)"),
        ("TimeMax", f"{params['timemax']:.4f}", "seconds"),
        ("TimeOut", f"{params['timeout']:.4f}", "seconds"),
        ("PartsOutMax", "1", "Max fraction of excluded particles"),
        ("RhopOutMin", f"{params['rhop_out_min']:.0f}", "kg/m^3"),
        ("RhopOutMax", f"{params['rhop_out_max']:.0f}", "kg/m^3"),
    ]

    for key, value, comment in param_list:
        ET.SubElement(parameters, "parameter",
                      key=key, value=value, comment=comment)

    return execution


def validate_output(filepath, params):
    """Validate the generated parameter XML."""
    warnings = []
    try:
        tree = ET.parse(filepath)
        root = tree.getroot()
        if root.tag != "execution":
            warnings.append(f"Root element is '{root.tag}', expected 'execution'")

        # Check critical parameters exist
        required_keys = ["TimeMax", "TimeOut", "Visco", "Kernel"]
        found_keys = {p.get("key") for p in root.iter("parameter")}
        for k in required_keys:
            if k not in found_keys:
                warnings.append(f"Missing parameter: {k}")
    except ET.ParseError as e:
        warnings.append(f"XML parse error: {e}")

    return warnings


def process(args):
    """Main processing pipeline: validate -> convert -> validate."""
    # 1. Validate inputs
    result = validate_inputs(args)
    if result["status"] == "error":
        return result

    # 2. Get fluid properties
    fluid_props = get_fluid_properties(args)

    # 3. Convert dp to meters
    dp = args.dp
    if args.dp_unit == "mm":
        dp *= 0.001
    elif args.dp_unit == "cm":
        dp *= 0.01

    depth = args.depth if args.depth else 1.0

    # 4. Compute derived parameters
    params = compute_derived_parameters(dp, depth, fluid_props, args)

    # 5. Generate XML
    xml_elem = generate_xml(params, fluid_props)
    rough = ET.tostring(xml_elem, encoding="unicode")
    parsed = minidom.parseString(rough)
    xml_str = parsed.toprettyxml(indent="  ")

    with open(args.output, "w") as f:
        f.write(xml_str)

    # 6. Validate output
    output_warnings = validate_output(args.output, params)
    all_warnings = result.get("warnings", []) + output_warnings

    return {
        "status": "ok",
        "output_file": args.output,
        "parameters": {
            "dp_m": params["dp"],
            "rhop0_kgm3": params["rhop0"],
            "h_m": params["h"],
            "speedsound_ms": params["speedsound"],
            "visco": params["visco_value"],
            "visco_type": params["visco_treatment"],
        },
        "fluid": fluid_props["description"] if "description" in fluid_props else "custom",
        "warnings": all_warnings,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Convert physical parameters to DualSPHysics XML")
    parser.add_argument("--output", "-o", required=True,
                        help="Output XML file")
    parser.add_argument("--fluid", choices=list(FLUID_DB.keys()),
                        help="Predefined fluid type")
    parser.add_argument("--fluid_density", type=float,
                        help="Custom fluid density")
    parser.add_argument("--density_unit", default="kg/m3",
                        choices=["kg/m3", "g/cm3"],
                        help="Density unit (default: kg/m3)")
    parser.add_argument("--fluid_viscosity", type=float,
                        help="Custom kinematic viscosity")
    parser.add_argument("--viscosity_unit", default="m2/s",
                        choices=["m2/s", "cSt", "cm2/s"],
                        help="Viscosity unit (default: m2/s)")
    parser.add_argument("--dp", type=float, required=True,
                        help="Particle spacing")
    parser.add_argument("--dp_unit", default="m",
                        choices=["m", "mm", "cm"],
                        help="Particle spacing unit")
    parser.add_argument("--depth", type=float, default=1.0,
                        help="Water depth in meters")
    parser.add_argument("--gravity", type=float, default=9.81,
                        help="Gravity magnitude (m/s^2)")
    parser.add_argument("--coefh", type=float,
                        help="Smoothing length coefficient")
    parser.add_argument("--coefsound", type=float,
                        help="Speed of sound coefficient")
    parser.add_argument("--cflnumber", type=float,
                        help="CFL number")
    parser.add_argument("--gamma", type=float,
                        help="Polytropic constant")
    parser.add_argument("--visco_treatment", default="artificial",
                        choices=["artificial", "laminar", "laminar_sps"],
                        help="Viscosity treatment")
    parser.add_argument("--visco_value", type=float,
                        help="Override viscosity value")
    parser.add_argument("--symplectic", action="store_true",
                        help="Use Symplectic instead of Verlet")
    parser.add_argument("--mdbc", action="store_true",
                        help="Use mDBC boundary conditions")
    parser.add_argument("--ddt_mode", type=int, default=2,
                        help="DDT mode (0-3)")
    parser.add_argument("--ddt_value", type=float, default=0.1,
                        help="DDT value")
    parser.add_argument("--timemax", type=float, default=2.0,
                        help="Max simulation time (s)")
    parser.add_argument("--timeout", type=float, default=0.01,
                        help="Output interval (s)")

    args = parser.parse_args()
    result = process(args)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["status"] == "ok" else 1)


if __name__ == "__main__":
    main()
