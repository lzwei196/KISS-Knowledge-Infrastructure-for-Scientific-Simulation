#!/usr/bin/env python3
"""
Convert external forcing data (velocity, pressure, discharge) to OpenFOAM
boundary condition field files.

CRITICAL: OpenFOAM incompressible solvers use KINEMATIC pressure (p/rho)
          with dimensions [0 2 -2 0 0 0 0], NOT dynamic pressure in Pa.
          All pressures from external sources (Pa) must be divided by density.

CRITICAL: Velocity must be in m/s. Discharge (m^3/s) must be converted to
          velocity by dividing by inlet cross-section area.

Usage:
    python convert_forcing_to_openfoam.py \\
        --forcing-csv forcing.csv \\
        --variable velocity \\
        --inlet-patch inlet \\
        --case-dir ./cavity \\
        --output fields.json

Input CSV format:
    time,Ux,Uy,Uz   (for velocity, m/s)
    time,p           (for pressure, Pa -- will be converted to kinematic)
    time,Q           (for discharge, m^3/s -- needs --inlet-area)

Output: OpenFOAM field files in 0/ directory or JSON summary
"""

import argparse
import csv
import json
import os
import sys


FOAM_HEADER = """FoamFile
{{
    format      ascii;
    class       {field_class};
    location    "0";
    object      {field_name};
}}"""

DIMENSION_MAP = {
    "velocity": "[0 1 -1 0 0 0 0]",
    "pressure_kinematic": "[0 2 -2 0 0 0 0]",
    "pressure_dynamic": "[1 -1 -2 0 0 0 0]",
    "k": "[0 2 -2 0 0 0 0]",
    "epsilon": "[0 2 -3 0 0 0 0]",
    "omega": "[0 0 -1 0 0 0 0]",
    "nu": "[0 2 -1 0 0 0 0]",
    "alpha": "[0 0 0 0 0 0 0]",
}


def validate_inputs(args):
    """Validate input arguments. Exit with JSON error if invalid."""
    errors = []

    if not os.path.isfile(args.forcing_csv):
        errors.append(f"Forcing CSV not found: {args.forcing_csv}")

    if args.variable not in ("velocity", "pressure", "discharge", "k", "epsilon"):
        errors.append(f"Unknown variable: {args.variable}. "
                       "Must be velocity|pressure|discharge|k|epsilon")

    if args.variable == "discharge" and args.inlet_area is None:
        errors.append("--inlet-area is required when variable=discharge "
                       "(to convert Q [m^3/s] to U [m/s])")

    if args.variable == "discharge" and args.inlet_area is not None:
        if args.inlet_area <= 0:
            errors.append(f"--inlet-area must be > 0, got {args.inlet_area}")

    if args.variable == "pressure" and args.density is None:
        errors.append("--density is required when variable=pressure "
                       "(to convert Pa to kinematic p/rho [m^2/s^2])")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}, indent=2))
        sys.exit(1)


def read_forcing_csv(csv_path):
    """Read time series from CSV. Returns list of dicts."""
    rows = []
    with open(csv_path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({k: float(v) for k, v in row.items()})
    return rows


def convert_discharge_to_velocity(rows, inlet_area):
    """Convert discharge Q (m^3/s) to velocity U (m/s) = Q / A.

    Assumes uniform velocity over inlet cross-section.
    """
    converted = []
    for row in rows:
        q = row.get("Q", row.get("q", row.get("discharge", 0.0)))
        u_mag = q / inlet_area
        converted.append({
            "time": row["time"],
            "Ux": u_mag,
            "Uy": 0.0,
            "Uz": 0.0,
        })
    return converted


def convert_pressure_to_kinematic(rows, density):
    """Convert dynamic pressure (Pa) to kinematic pressure (m^2/s^2).

    CRITICAL: p_kinematic = p_dynamic / rho
    For water at 20C, rho ~ 998 kg/m^3
    """
    converted = []
    for row in rows:
        p_pa = row.get("p", row.get("pressure", 0.0))
        p_kin = p_pa / density
        converted.append({
            "time": row["time"],
            "p": p_kin,
        })
    return converted


def write_velocity_field(case_dir, patch_name, value, all_patches):
    """Write 0/U field file with fixedValue on inlet patch."""
    header = FOAM_HEADER.format(field_class="volVectorField", field_name="U")
    ux, uy, uz = value

    bc_entries = []
    for patch in all_patches:
        if patch == patch_name:
            bc_entries.append(f"""    {patch}
    {{
        type            fixedValue;
        value           uniform ({ux} {uy} {uz});
    }}""")
        else:
            bc_entries.append(f"""    {patch}
    {{
        type            zeroGradient;
    }}""")

    content = f"""{header}

dimensions      {DIMENSION_MAP['velocity']};

internalField   uniform (0 0 0);

boundaryField
{{
{chr(10).join(bc_entries)}
}}
"""
    filepath = os.path.join(case_dir, "0", "U")
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w") as f:
        f.write(content)
    return filepath


def write_pressure_field(case_dir, patch_name, value, all_patches):
    """Write 0/p field file."""
    header = FOAM_HEADER.format(field_class="volScalarField", field_name="p")

    bc_entries = []
    for patch in all_patches:
        if patch == patch_name:
            bc_entries.append(f"""    {patch}
    {{
        type            fixedValue;
        value           uniform {value};
    }}""")
        else:
            bc_entries.append(f"""    {patch}
    {{
        type            zeroGradient;
    }}""")

    content = f"""{header}

dimensions      {DIMENSION_MAP['pressure_kinematic']};

internalField   uniform 0;

boundaryField
{{
{chr(10).join(bc_entries)}
}}
"""
    filepath = os.path.join(case_dir, "0", "p")
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w") as f:
        f.write(content)
    return filepath


def process(args):
    """Main processing: read CSV, convert units, write OpenFOAM fields."""
    rows = read_forcing_csv(args.forcing_csv)

    result = {
        "status": "success",
        "variable": args.variable,
        "n_timesteps": len(rows),
        "files_written": [],
        "conversions_applied": [],
        "warnings": [],
    }

    all_patches = [args.inlet_patch, "outlet", "walls"]
    if args.patches:
        all_patches = args.patches.split(",")

    if args.variable == "discharge":
        rows = convert_discharge_to_velocity(rows, args.inlet_area)
        result["conversions_applied"].append(
            f"Q [m^3/s] -> U [m/s] via A={args.inlet_area} m^2"
        )
        # Use first row as steady-state BC (or last for representative)
        row = rows[0]
        fp = write_velocity_field(
            args.case_dir, args.inlet_patch,
            (row["Ux"], row["Uy"], row["Uz"]), all_patches
        )
        result["files_written"].append(fp)

    elif args.variable == "velocity":
        row = rows[0]
        ux = row.get("Ux", row.get("ux", 0.0))
        uy = row.get("Uy", row.get("uy", 0.0))
        uz = row.get("Uz", row.get("uz", 0.0))
        fp = write_velocity_field(
            args.case_dir, args.inlet_patch,
            (ux, uy, uz), all_patches
        )
        result["files_written"].append(fp)

    elif args.variable == "pressure":
        rows = convert_pressure_to_kinematic(rows, args.density)
        result["conversions_applied"].append(
            f"p [Pa] -> p/rho [m^2/s^2] via rho={args.density} kg/m^3"
        )
        row = rows[0]
        fp = write_pressure_field(
            args.case_dir, args.inlet_patch, row["p"], all_patches
        )
        result["files_written"].append(fp)

    return result


def validate_outputs(result):
    """Validate output files exist and are non-empty."""
    warnings = result.get("warnings", [])

    for fp in result.get("files_written", []):
        if not os.path.isfile(fp):
            warnings.append(f"Expected output file missing: {fp}")
        elif os.path.getsize(fp) == 0:
            warnings.append(f"Output file is empty: {fp}")

    if not result.get("files_written"):
        warnings.append("No files were written")

    result["warnings"] = warnings
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Convert forcing data to OpenFOAM boundary conditions"
    )
    parser.add_argument("--forcing-csv", required=True,
                        help="Path to forcing CSV (time,Ux,Uy,Uz or time,p or time,Q)")
    parser.add_argument("--variable", required=True,
                        choices=["velocity", "pressure", "discharge", "k", "epsilon"],
                        help="Variable type to convert")
    parser.add_argument("--inlet-patch", default="inlet",
                        help="Name of inlet boundary patch")
    parser.add_argument("--case-dir", default=".",
                        help="OpenFOAM case directory")
    parser.add_argument("--inlet-area", type=float, default=None,
                        help="Inlet cross-section area [m^2] (required for discharge)")
    parser.add_argument("--density", type=float, default=None,
                        help="Fluid density [kg/m^3] (required for pressure conversion)")
    parser.add_argument("--patches", default=None,
                        help="Comma-separated list of all boundary patches")
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
