#!/usr/bin/env python3
"""
Convert physical properties (fluid, soil, material) to OpenFOAM dictionary format.

Generates:
  - constant/physicalProperties  (kinematic viscosity, transport model)
  - constant/momentumTransport   (turbulence model selection)
  - constant/g                   (gravity vector)
  - constant/transportProperties (VoF phase properties)

CRITICAL: OpenFOAM uses KINEMATIC viscosity nu [m^2/s], not dynamic viscosity
          mu [Pa.s]. If you have mu, divide by density: nu = mu / rho.

CRITICAL: For VoF (two-phase) simulations, both phases need separate
          transport properties with correct surface tension sigma.

Usage:
    python convert_properties_to_openfoam.py \\
        --case-dir ./myCase \\
        --fluid water \\
        --nu 1e-6 \\
        --turbulence-model kEpsilon \\
        --output result.json

    python convert_properties_to_openfoam.py \\
        --case-dir ./myCase \\
        --properties-json properties.json \\
        --output result.json

Input JSON format:
    {
        "nu": 1e-6,                    // kinematic viscosity [m^2/s]
        "rho": 998,                    // density [kg/m^3] (for compressible)
        "turbulence_model": "kEpsilon",
        "gravity": [0, -9.81, 0],
        "phases": {                    // for VoF only
            "water": {"nu": 1e-6, "rho": 998},
            "air":   {"nu": 1.48e-5, "rho": 1.225}
        },
        "sigma": 0.072                 // surface tension [N/m = kg/s^2]
    }
"""

import argparse
import json
import os
import sys


FOAM_HEADER = """FoamFile
{{
    format      ascii;
    class       dictionary;
    location    "constant";
    object      {obj_name};
}}"""

# Common fluid properties at 20C
FLUID_PRESETS = {
    "water": {"nu": 1.004e-6, "rho": 998.2},
    "seawater": {"nu": 1.08e-6, "rho": 1025.0},
    "air": {"nu": 1.516e-5, "rho": 1.204},
    "oil_light": {"nu": 5.0e-6, "rho": 850.0},
    "oil_heavy": {"nu": 1.0e-4, "rho": 920.0},
    "glycerol": {"nu": 1.19e-3, "rho": 1261.0},
    "mercury": {"nu": 1.14e-7, "rho": 13534.0},
}

TURBULENCE_MODELS = [
    "laminar", "kEpsilon", "kOmega", "kOmegaSST",
    "SpalartAllmaras", "LES", "realizableKE",
]


def validate_inputs(args):
    """Validate input arguments."""
    errors = []

    if args.properties_json and not os.path.isfile(args.properties_json):
        errors.append(f"Properties JSON not found: {args.properties_json}")

    if args.nu is not None and args.nu <= 0:
        errors.append(f"Kinematic viscosity must be > 0, got {args.nu}")

    if args.nu is not None and args.nu > 1.0:
        errors.append(
            f"WARNING: nu={args.nu} m^2/s seems very large. "
            "Did you accidentally use dynamic viscosity mu [Pa.s]? "
            "Convert: nu = mu / rho"
        )

    if args.fluid and args.fluid not in FLUID_PRESETS:
        errors.append(
            f"Unknown fluid preset: {args.fluid}. "
            f"Available: {', '.join(FLUID_PRESETS.keys())}"
        )

    if args.turbulence_model and args.turbulence_model not in TURBULENCE_MODELS:
        errors.append(
            f"Unknown turbulence model: {args.turbulence_model}. "
            f"Available: {', '.join(TURBULENCE_MODELS)}"
        )

    if errors:
        print(json.dumps({"status": "error", "errors": errors}, indent=2))
        sys.exit(1)


def load_properties(args):
    """Load properties from JSON file or command-line arguments."""
    props = {}

    if args.properties_json:
        with open(args.properties_json) as f:
            props = json.load(f)

    # CLI overrides
    if args.fluid:
        preset = FLUID_PRESETS[args.fluid]
        props.setdefault("nu", preset["nu"])
        props.setdefault("rho", preset["rho"])

    if args.nu is not None:
        props["nu"] = args.nu
    if args.rho is not None:
        props["rho"] = args.rho
    if args.turbulence_model:
        props["turbulence_model"] = args.turbulence_model

    # Defaults
    props.setdefault("nu", 1e-6)
    props.setdefault("rho", 998.0)
    props.setdefault("turbulence_model", "laminar")
    props.setdefault("gravity", [0, -9.81, 0])

    return props


def write_physical_properties(case_dir, props):
    """Write constant/physicalProperties."""
    header = FOAM_HEADER.format(obj_name="physicalProperties")
    nu = props["nu"]

    content = f"""{header}

viscosityModel  constant;

nu              {nu};
"""
    filepath = os.path.join(case_dir, "constant", "physicalProperties")
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w") as f:
        f.write(content)
    return filepath


def write_transport_properties_vof(case_dir, props):
    """Write constant/transportProperties for VoF simulations."""
    header = FOAM_HEADER.format(obj_name="transportProperties")
    phases = props.get("phases", {
        "water": {"nu": 1e-6, "rho": 998.0},
        "air": {"nu": 1.48e-5, "rho": 1.225},
    })
    sigma = props.get("sigma", 0.072)

    phase_blocks = []
    for name, pprops in phases.items():
        phase_blocks.append(f"""phases ({' '.join(phases.keys())});

{name}
{{
    transportModel  Newtonian;
    nu              {pprops['nu']};
    rho             {pprops['rho']};
}}""")

    content = f"""{header}

{chr(10).join(phase_blocks)}

sigma           {sigma};
"""
    filepath = os.path.join(case_dir, "constant", "transportProperties")
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w") as f:
        f.write(content)
    return filepath


def write_momentum_transport(case_dir, props):
    """Write constant/momentumTransport."""
    header = FOAM_HEADER.format(obj_name="momentumTransport")
    model = props["turbulence_model"]

    if model == "laminar":
        content = f"""{header}

simulationType  laminar;

laminar
{{
    model           Newtonian;
}}
"""
    else:
        content = f"""{header}

simulationType  RAS;

RAS
{{
    model           {model};
    turbulence      on;
    printCoeffs     on;
}}
"""
    filepath = os.path.join(case_dir, "constant", "momentumTransport")
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w") as f:
        f.write(content)
    return filepath


def write_gravity(case_dir, props):
    """Write constant/g (gravity vector)."""
    gx, gy, gz = props["gravity"]

    content = f"""FoamFile
{{
    format      ascii;
    class       uniformDimensionedVectorField;
    location    "constant";
    object      g;
}}

dimensions      [0 1 -2 0 0 0 0];
value           ({gx} {gy} {gz});
"""
    filepath = os.path.join(case_dir, "constant", "g")
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w") as f:
        f.write(content)
    return filepath


def process(args):
    """Main processing: load properties, write OpenFOAM dictionaries."""
    props = load_properties(args)

    result = {
        "status": "success",
        "properties": props,
        "files_written": [],
        "warnings": [],
    }

    # Write physicalProperties
    fp = write_physical_properties(args.case_dir, props)
    result["files_written"].append(fp)

    # Write momentumTransport
    fp = write_momentum_transport(args.case_dir, props)
    result["files_written"].append(fp)

    # Write gravity
    fp = write_gravity(args.case_dir, props)
    result["files_written"].append(fp)

    # Write VoF transport properties if phases defined
    if "phases" in props:
        fp = write_transport_properties_vof(args.case_dir, props)
        result["files_written"].append(fp)

    # Sanity checks
    nu = props["nu"]
    if nu > 1e-3:
        result["warnings"].append(
            f"nu={nu} is very high -- check if this is kinematic (m^2/s) "
            "or dynamic (Pa.s) viscosity"
        )

    return result


def validate_outputs(result):
    """Validate all output files exist and are non-empty."""
    warnings = result.get("warnings", [])
    for fp in result.get("files_written", []):
        if not os.path.isfile(fp):
            warnings.append(f"Expected output file missing: {fp}")
        elif os.path.getsize(fp) == 0:
            warnings.append(f"Output file is empty: {fp}")
    result["warnings"] = warnings
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Convert physical properties to OpenFOAM dictionary format"
    )
    parser.add_argument("--case-dir", default=".",
                        help="OpenFOAM case directory")
    parser.add_argument("--properties-json", default=None,
                        help="JSON file with all properties")
    parser.add_argument("--fluid", default=None,
                        help=f"Fluid preset: {', '.join(FLUID_PRESETS.keys())}")
    parser.add_argument("--nu", type=float, default=None,
                        help="Kinematic viscosity [m^2/s]")
    parser.add_argument("--rho", type=float, default=None,
                        help="Density [kg/m^3]")
    parser.add_argument("--turbulence-model", default=None,
                        help=f"Turbulence model: {', '.join(TURBULENCE_MODELS)}")
    parser.add_argument("--output", default=None,
                        help="Output JSON summary file")

    args = parser.parse_args()
    validate_inputs(args)
    result = process(args)
    result = validate_outputs(result)

    output_json = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            f.write(output_json)
        print(f"Written to {args.output}", file=sys.stderr)
    else:
        print(output_json)


if __name__ == "__main__":
    main()
