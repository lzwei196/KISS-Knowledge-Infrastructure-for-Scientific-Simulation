#!/usr/bin/env python3
"""
Generate OpenFOAM case configuration files: controlDict, fvSchemes, fvSolution.

Creates a consistent set of system dictionaries based on solver type and
simulation parameters.

CRITICAL: writeControl semantics depend on the chosen mode:
  - timeStep: writeInterval is number of time steps
  - runTime: writeInterval is simulation seconds
  - adjustableRunTime: adjusts dt to hit exact write times
  Mixing these up produces unexpected output frequency.

CRITICAL: For SIMPLE (steady-state), nOuterCorrectors=1 and large deltaT.
          For PISO (transient), nOuterCorrectors=1 and small deltaT.
          For PIMPLE (transient, implicit), nOuterCorrectors>1.

Usage:
    python configure_case.py \\
        --case-dir ./myCase \\
        --solver incompressibleFluid \\
        --end-time 1.0 \\
        --delta-t 0.001 \\
        --write-interval 0.1 \\
        --algorithm PIMPLE \\
        --output result.json
"""

import argparse
import json
import os
import sys


FOAM_HEADER = """FoamFile
{{
    format      ascii;
    class       dictionary;
    location    "system";
    object      {obj_name};
}}"""


def validate_inputs(args):
    """Validate input arguments."""
    errors = []

    if args.end_time <= 0:
        errors.append(f"end-time must be > 0, got {args.end_time}")
    if args.delta_t <= 0:
        errors.append(f"delta-t must be > 0, got {args.delta_t}")
    if args.write_interval <= 0:
        errors.append(f"write-interval must be > 0, got {args.write_interval}")

    if args.algorithm not in ("SIMPLE", "PISO", "PIMPLE"):
        errors.append(f"Unknown algorithm: {args.algorithm}. Use SIMPLE|PISO|PIMPLE")

    if args.algorithm == "SIMPLE" and args.delta_t < 1.0:
        errors.append(
            "SIMPLE is steady-state: deltaT should be large (e.g., 1). "
            f"Got deltaT={args.delta_t}. Did you mean PIMPLE or PISO?"
        )

    if errors:
        print(json.dumps({"status": "error", "errors": errors}, indent=2))
        sys.exit(1)


def write_control_dict(case_dir, args):
    """Write system/controlDict."""
    header = FOAM_HEADER.format(obj_name="controlDict")

    write_control = "adjustableRunTime" if args.adaptive_dt else "runTime"

    adaptive_block = ""
    if args.adaptive_dt:
        adaptive_block = f"""
adjustTimeStep  yes;
maxCo           {args.max_courant};
"""

    content = f"""{header}

solver          {args.solver};

startFrom       startTime;
startTime       0;

stopAt          endTime;
endTime         {args.end_time};

deltaT          {args.delta_t};

writeControl    {write_control};
writeInterval   {args.write_interval};

purgeWrite      {args.purge_write};

writeFormat     ascii;
writePrecision  6;
writeCompression off;

timeFormat      general;
timePrecision   6;

runTimeModifiable true;
{adaptive_block}
functions
{{
    #includeFunc residuals
}}
"""
    filepath = os.path.join(case_dir, "system", "controlDict")
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w") as f:
        f.write(content)
    return filepath


def write_fv_schemes(case_dir, args):
    """Write system/fvSchemes."""
    header = FOAM_HEADER.format(obj_name="fvSchemes")

    # Select schemes based on algorithm
    if args.algorithm == "SIMPLE":
        ddt_scheme = "steadyState"
        div_default = "bounded Gauss linearUpwind grad(U)"
    elif args.algorithm == "PISO":
        ddt_scheme = "Euler"
        div_default = "Gauss linearUpwind grad(U)"
    else:  # PIMPLE
        ddt_scheme = "backward"
        div_default = "Gauss linearUpwind grad(U)"

    content = f"""{header}

ddtSchemes
{{
    default         {ddt_scheme};
}}

gradSchemes
{{
    default         Gauss linear;
    grad(U)         cellLimited Gauss linear 1;
}}

divSchemes
{{
    default         none;
    div(phi,U)      {div_default};
    div(phi,k)      bounded Gauss linearUpwind grad(k);
    div(phi,epsilon) bounded Gauss linearUpwind grad(epsilon);
    div(phi,omega)  bounded Gauss linearUpwind grad(omega);
    div((nuEff*dev2(T(grad(U))))) Gauss linear;
}}

laplacianSchemes
{{
    default         Gauss linear corrected;
}}

interpolationSchemes
{{
    default         linear;
}}

snGradSchemes
{{
    default         corrected;
}}

wallDist
{{
    method          meshWave;
}}
"""
    filepath = os.path.join(case_dir, "system", "fvSchemes")
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w") as f:
        f.write(content)
    return filepath


def write_fv_solution(case_dir, args):
    """Write system/fvSolution."""
    header = FOAM_HEADER.format(obj_name="fvSolution")

    # PIMPLE settings
    if args.algorithm == "SIMPLE":
        n_outer = 1
        n_correctors = 2
        relax_u = 0.7
        relax_p = 0.3
    elif args.algorithm == "PISO":
        n_outer = 1
        n_correctors = 2
        relax_u = 1.0
        relax_p = 1.0
    else:  # PIMPLE
        n_outer = args.n_outer_correctors
        n_correctors = 2
        relax_u = 0.7
        relax_p = 0.3

    content = f"""{header}

solvers
{{
    p
    {{
        solver          GAMG;
        smoother        DICGaussSeidel;
        tolerance       1e-06;
        relTol          0.01;
    }}

    pFinal
    {{
        $p;
        relTol          0;
    }}

    "(U|k|epsilon|omega)"
    {{
        solver          smoothSolver;
        smoother        symGaussSeidel;
        tolerance       1e-06;
        relTol          0.1;
    }}

    "(U|k|epsilon|omega)Final"
    {{
        $U;
        relTol          0;
    }}
}}

PIMPLE
{{
    nOuterCorrectors    {n_outer};
    nCorrectors         {n_correctors};
    nNonOrthogonalCorrectors {args.n_non_ortho};
    pRefCell            0;
    pRefValue           0;

    residualControl
    {{
        U               1e-5;
        p               1e-4;
    }}
}}

relaxationFactors
{{
    equations
    {{
        U               {relax_u};
        p               {relax_p};
        k               {relax_u};
        epsilon         {relax_u};
        omega           {relax_u};
    }}
}}
"""
    filepath = os.path.join(case_dir, "system", "fvSolution")
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w") as f:
        f.write(content)
    return filepath


def process(args):
    """Generate all configuration files."""
    result = {
        "status": "success",
        "files_written": [],
        "warnings": [],
        "configuration": {
            "solver": args.solver,
            "algorithm": args.algorithm,
            "end_time": args.end_time,
            "delta_t": args.delta_t,
            "write_interval": args.write_interval,
            "adaptive_dt": args.adaptive_dt,
        },
    }

    fp = write_control_dict(args.case_dir, args)
    result["files_written"].append(fp)

    fp = write_fv_schemes(args.case_dir, args)
    result["files_written"].append(fp)

    fp = write_fv_solution(args.case_dir, args)
    result["files_written"].append(fp)

    # Sanity warnings
    n_steps = args.end_time / args.delta_t
    if n_steps > 1e6:
        result["warnings"].append(
            f"Estimated {n_steps:.0e} time steps -- this may take very long. "
            "Consider increasing deltaT or reducing endTime."
        )

    return result


def validate_outputs(result):
    """Validate output files."""
    warnings = result.get("warnings", [])
    for fp in result.get("files_written", []):
        if not os.path.isfile(fp):
            warnings.append(f"Expected output file missing: {fp}")
    result["warnings"] = warnings
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Generate OpenFOAM case configuration files"
    )
    parser.add_argument("--case-dir", required=True,
                        help="OpenFOAM case directory")
    parser.add_argument("--solver", default="incompressibleFluid",
                        help="Solver module name")
    parser.add_argument("--end-time", type=float, default=1.0,
                        help="Simulation end time [s]")
    parser.add_argument("--delta-t", type=float, default=0.001,
                        help="Time step [s]")
    parser.add_argument("--write-interval", type=float, default=0.1,
                        help="Output write interval [s]")
    parser.add_argument("--algorithm", default="PIMPLE",
                        choices=["SIMPLE", "PISO", "PIMPLE"],
                        help="Solution algorithm")
    parser.add_argument("--adaptive-dt", action="store_true",
                        help="Enable adaptive time stepping")
    parser.add_argument("--max-courant", type=float, default=1.0,
                        help="Max Courant number for adaptive dt")
    parser.add_argument("--n-outer-correctors", type=int, default=2,
                        help="PIMPLE outer correctors")
    parser.add_argument("--n-non-ortho", type=int, default=1,
                        help="Non-orthogonal correctors")
    parser.add_argument("--purge-write", type=int, default=0,
                        help="Keep only last N time dirs (0=keep all)")
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
