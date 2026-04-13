#!/usr/bin/env python3
"""
generate_sif.py — Generate Elmer/Ice SIF (Simulation Input File) from parameters.

Builds a complete SIF file for ice dynamics simulations, handling all blocks:
Header, Simulation, Constants, Body, Material, Solver, Equation, Boundary Condition,
Body Force, and Initial Condition.

CRITICAL ISSUES:
  - Viscosity Exponent MUST be 1/n, NOT n. For Glen's law n=3, use 0.333333.
    If n is passed directly, viscosity is 27x wrong (SILENT ERROR — dt_002).
  - Time step sizes are in SECONDS unless the solver handles unit conversion.
    1 year = 31556926 seconds. If you set Timestep Sizes = 1.0 thinking "1 year",
    the simulation will run for 1 second (dt_009).
  - Critical Shear Rate MUST be > 0 (e.g., 1.0e-10). Zero causes division
    by zero → NaN propagation (dt_013).
  - Density in kg/m3 (ice=910, seawater=1025). Using g/cm3 = 1000x error (dt_003).

Usage:
    python generate_sif.py --template ssa_2d --mesh_dir ./rectangle \
        --output simulation.sif --n_timesteps 100 --dt_years 1.0 \
        --friction_law weertman --friction_parameter 1e-3 \
        --glen_n 3.0 --ice_density 910.0
"""

import argparse
import json
import os
import sys


SEC_PER_YEAR = 31556926.0  # seconds per Julian year


def validate_inputs(args):
    """Validate all input parameters."""
    errors = []

    if args.glen_n <= 0:
        errors.append(f"Glen's n must be positive, got {args.glen_n}")
    if args.glen_n > 10:
        errors.append(f"Glen's n = {args.glen_n} is unrealistically large. "
                      "Did you pass 1/n instead of n?")
    if args.ice_density < 100 or args.ice_density > 2000:
        errors.append(f"Ice density = {args.ice_density}. Expected ~910 kg/m3. "
                      "Are you using g/cm3?")
    if args.critical_shear_rate <= 0:
        errors.append("Critical Shear Rate must be > 0 to avoid NaN (dt_013)")
    if args.dt_years <= 0:
        errors.append(f"Time step must be positive, got {args.dt_years}")
    if args.friction_parameter < 0:
        errors.append("Friction parameter must be non-negative")

    valid_friction = ["linear", "weertman", "coulomb", "regularised coulomb", "budd"]
    if args.friction_law not in valid_friction:
        errors.append(f"Unknown friction law '{args.friction_law}'. "
                      f"Must be one of {valid_friction}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)


def generate_header(mesh_dir):
    """Generate SIF Header block."""
    return f"""Header
  Mesh DB "." "{mesh_dir}"
End
"""


def generate_simulation(args):
    """Generate SIF Simulation block."""
    dt_seconds = args.dt_years * SEC_PER_YEAR
    sim_type = "Transient" if args.n_timesteps > 1 else "Steady State"

    block = f"""Simulation
  Coordinate System = {args.coordinate_system}
  Simulation Type = {sim_type}
"""
    if sim_type == "Transient":
        block += f"""  Timestepping Method = "bdf"
  BDF Order = 1
  Timestep Intervals = {args.n_timesteps}
  Timestep Sizes = {dt_seconds:.1f}
"""
    else:
        block += f"""  Steady State Max Iterations = {args.steady_max_iter}
  Steady State Min Iterations = 1
"""
    block += f"""  Output Intervals = {args.output_interval}
  Post File = "{args.post_file}"
  Max Output Level = {args.output_level}
End
"""
    return block


def generate_constants(args):
    """Generate SIF Constants block."""
    return f"""Constants
  Gas Constant = Real 8.314       ! J/(mol K)
  Stefan Boltzmann = Real 0.0
  Sea Level = Real 0.0            ! m
  Water Density = Real {args.water_density:.1f}  ! kg/m3
End
"""


def generate_body(n_bodies=1):
    """Generate SIF Body blocks."""
    blocks = ""
    for i in range(1, n_bodies + 1):
        blocks += f"""
Body {i}
  Equation = {i}
  Material = {i}
  Body Force = {i}
  Initial Condition = {i}
End
"""
    return blocks


def generate_material_ssa(args):
    """Generate Material block for SSA solver."""
    visc_exp = 1.0 / args.glen_n
    return f"""
Material 1
  ! Ice rheology (Glen's flow law)
  Viscosity Exponent = Real {visc_exp:.10f}   ! 1/n where n={args.glen_n}
  Critical Shear Rate = Real {args.critical_shear_rate:.2e}  ! s^-1

  ! Ice density
  Density = Real {args.ice_density:.1f}  ! kg/m3

  ! SSA friction parameters
  SSA Friction Law = String "{args.friction_law}"
  SSA Friction Parameter = Real {args.friction_parameter:.6e}
  SSA Friction Exponent = Real {1.0/args.glen_n:.10f}
  SSA Mean Density = Real {args.ice_density:.1f}
  SSA Mean Viscosity = Real {args.mean_viscosity:.6e}
End
"""


def generate_solver_ssa(solver_id, args):
    """Generate Solver block for SSA."""
    dofs = 1 if "2D" in args.coordinate_system else 2
    return f"""
Solver {solver_id}
  Equation = "SSA"
  Procedure = "ElmerIceSolvers" "SSABasalSolver"
  Variable = -dofs {dofs} "SSAVelocity"

  Linear System Solver = {args.linear_solver}
  Linear System Direct Method = {args.direct_method}
  Linear System Iterative Method = {args.iterative_method}
  Linear System Max Iterations = {args.linear_max_iter}
  Linear System Convergence Tolerance = {args.linear_tol:.2e}
  Linear System Preconditioning = {args.preconditioner}

  Nonlinear System Max Iterations = {args.nonlinear_max_iter}
  Nonlinear System Convergence Tolerance = {args.nonlinear_tol:.2e}
  Nonlinear System Newton After Iterations = {args.newton_after_iter}
  Nonlinear System Newton After Tolerance = {args.newton_after_tol:.2e}
  Nonlinear System Relaxation Factor = {args.relaxation_factor}
End
"""


def generate_solver_thickness(solver_id, args):
    """Generate Solver block for thickness evolution."""
    return f"""
Solver {solver_id}
  Equation = "Thickness"
  Procedure = "ElmerIceSolvers" "ThicknessSolver"
  Variable = -dofs 1 "H"

  Linear System Solver = Direct
  Linear System Direct Method = umfpack

  ! Stabilization
  Stabilization Method = Stabilized
  Apply Dirichlet = Logical True

  ! Exported variables
  Exported Variable 1 = -dofs 1 "dHdt"
  Exported Variable 2 = -dofs 1 "H Residual"

  ! Limiters to prevent negative thickness
  Compute Loads = Logical True
End
"""


def generate_solver_output(solver_id, args):
    """Generate result output solver."""
    return f"""
Solver {solver_id}
  Equation = "Result Output"
  Procedure = "ResultOutputSolve" "ResultOutputSolver"
  Output File Name = "{args.post_file.replace('.vtu', '')}"
  Output Format = vtu
  Save Geometry IDs = Logical True
End
"""


def generate_equation(eq_id, solver_ids):
    """Generate Equation block."""
    active = " ".join(str(s) for s in solver_ids)
    return f"""
Equation {eq_id}
  Active Solvers({len(solver_ids)}) = {active}
End
"""


def generate_body_force(bf_id, args):
    """Generate Body Force block with SMB."""
    return f"""
Body Force {bf_id}
  ! Surface mass balance (m/a ice equivalent)
  Top Surface Accumulation = Real {args.smb_value}

  ! Basal melt (m/a ice equivalent, positive = melting)
  Bottom Surface Accumulation = Real {args.basal_melt_value}
End
"""


def generate_initial_condition(ic_id, args):
    """Generate Initial Condition block."""
    return f"""
Initial Condition {ic_id}
  SSAVelocity 1 = Real 0.0
  SSAVelocity 2 = Real 0.0
  H = Real {args.initial_thickness}
  Zs = Variable Coordinate 1
    Real MATC "tx"
  Zb = Variable Coordinate 1
    Real MATC "tx - {args.initial_thickness}"
End
"""


def generate_boundary_conditions(args):
    """Generate Boundary Condition blocks."""
    blocks = ""
    # Inflow boundary
    blocks += f"""
Boundary Condition 1
  Target Boundaries = 4
  ! Inflow: fixed velocity or thickness
  SSAVelocity 1 = Real 0.0
  H = Real {args.initial_thickness}
End
"""
    # Calving front / outflow
    blocks += f"""
Boundary Condition 2
  Target Boundaries = 2
  ! Calving front: free stress
  Calving Front = Logical True
End
"""
    # Lateral boundaries (no-slip or free-slip)
    blocks += """
Boundary Condition 3
  Target Boundaries(2) = 1 3
  ! Lateral: no flow perpendicular
  SSAVelocity 2 = Real 0.0
End
"""
    return blocks


def process(args):
    """Assemble the complete SIF file."""
    sif = ""

    # Header
    sif += generate_header(args.mesh_dir)

    # Simulation
    sif += generate_simulation(args)

    # Constants
    sif += generate_constants(args)

    # Bodies
    sif += generate_body(n_bodies=1)

    # Material
    sif += generate_material_ssa(args)

    # Solvers
    solver_ids = []
    sid = 1
    sif += generate_solver_ssa(sid, args)
    solver_ids.append(sid)
    sid += 1

    if args.n_timesteps > 1:
        sif += generate_solver_thickness(sid, args)
        solver_ids.append(sid)
        sid += 1

    sif += generate_solver_output(sid, args)
    solver_ids.append(sid)

    # Equation
    sif += generate_equation(1, solver_ids)

    # Body Force
    sif += generate_body_force(1, args)

    # Initial Condition
    sif += generate_initial_condition(1, args)

    # Boundary Conditions
    sif += generate_boundary_conditions(args)

    return sif


def validate_outputs(sif_content):
    """Check generated SIF for common errors."""
    warnings = []

    # Check for viscosity exponent trap
    for line in sif_content.split("\n"):
        if "Viscosity Exponent" in line and "!" not in line.split("=")[0]:
            parts = line.split("=")
            if len(parts) >= 2:
                try:
                    val = float(parts[-1].strip().split()[0])
                    if val > 1.0:
                        warnings.append(
                            f"Viscosity Exponent = {val} > 1 — "
                            "did you pass n instead of 1/n? (dt_002)")
                except (ValueError, IndexError):
                    pass

    # Check for zero critical shear rate
    if "Critical Shear Rate = Real 0" in sif_content:
        warnings.append("Critical Shear Rate = 0 will cause NaN (dt_013)")

    # Check timestep
    for line in sif_content.split("\n"):
        if "Timestep Sizes" in line:
            try:
                val = float(line.split("=")[-1].strip())
                if val < 100:
                    warnings.append(
                        f"Timestep = {val}s is very small — "
                        "did you mean years? (dt_009)")
            except (ValueError, IndexError):
                pass

    for w in warnings:
        print(f"WARNING: {w}", file=sys.stderr)
    return warnings


def main():
    parser = argparse.ArgumentParser(
        description="Generate Elmer/Ice SIF file from parameters")

    # Template and paths
    parser.add_argument("--mesh_dir", type=str, default="rectangle",
                        help="Mesh directory name")
    parser.add_argument("--output", type=str, required=True,
                        help="Output SIF file path")
    parser.add_argument("--post_file", type=str, default="results.vtu",
                        help="VTU output filename")

    # Simulation parameters
    parser.add_argument("--coordinate_system", type=str,
                        default="Cartesian 2D",
                        help="Coordinate system (Cartesian 2D or 3D)")
    parser.add_argument("--n_timesteps", type=int, default=100,
                        help="Number of time steps")
    parser.add_argument("--dt_years", type=float, default=1.0,
                        help="Time step in years (converted to seconds internally)")
    parser.add_argument("--output_interval", type=int, default=10,
                        help="Output every N timesteps")
    parser.add_argument("--output_level", type=int, default=5,
                        help="Elmer output verbosity (1-20)")
    parser.add_argument("--steady_max_iter", type=int, default=1,
                        help="Max iterations for steady state")

    # Ice physics
    parser.add_argument("--glen_n", type=float, default=3.0,
                        help="Glen's flow law exponent n (NOT 1/n)")
    parser.add_argument("--ice_density", type=float, default=910.0,
                        help="Ice density in kg/m3")
    parser.add_argument("--water_density", type=float, default=1025.0,
                        help="Seawater density in kg/m3")
    parser.add_argument("--critical_shear_rate", type=float, default=1.0e-10,
                        help="Critical shear rate (s^-1), must be > 0")
    parser.add_argument("--mean_viscosity", type=float, default=1.0e14,
                        help="Mean viscosity for SSA (Pa s)")

    # Friction
    parser.add_argument("--friction_law", type=str, default="weertman",
                        choices=["linear", "weertman", "coulomb",
                                 "regularised coulomb", "budd"],
                        help="Basal friction law")
    parser.add_argument("--friction_parameter", type=float, default=1.0e-3,
                        help="Friction parameter (units depend on law)")

    # Forcing
    parser.add_argument("--smb_value", type=float, default=0.3,
                        help="Surface mass balance (m/a ice eq.)")
    parser.add_argument("--basal_melt_value", type=float, default=0.0,
                        help="Basal melt rate (m/a ice eq.)")
    parser.add_argument("--initial_thickness", type=float, default=1000.0,
                        help="Initial ice thickness (m)")

    # Linear solver
    parser.add_argument("--linear_solver", type=str, default="Direct",
                        choices=["Direct", "Iterative"],
                        help="Linear system solver type")
    parser.add_argument("--direct_method", type=str, default="umfpack",
                        choices=["umfpack", "mumps"],
                        help="Direct solver method")
    parser.add_argument("--iterative_method", type=str, default="BiCGStab",
                        help="Iterative solver method")
    parser.add_argument("--linear_max_iter", type=int, default=1500,
                        help="Max linear solver iterations")
    parser.add_argument("--linear_tol", type=float, default=1.0e-12,
                        help="Linear solver convergence tolerance")
    parser.add_argument("--preconditioner", type=str, default="ILU0",
                        help="Preconditioner for iterative solver")

    # Nonlinear solver
    parser.add_argument("--nonlinear_max_iter", type=int, default=50,
                        help="Max nonlinear iterations")
    parser.add_argument("--nonlinear_tol", type=float, default=1.0e-6,
                        help="Nonlinear convergence tolerance")
    parser.add_argument("--newton_after_iter", type=int, default=5,
                        help="Switch to Newton after N iterations")
    parser.add_argument("--newton_after_tol", type=float, default=1.0e-5,
                        help="Switch to Newton after this tolerance")
    parser.add_argument("--relaxation_factor", type=float, default=1.0,
                        help="Nonlinear relaxation factor")

    args = parser.parse_args()

    validate_inputs(args)
    sif_content = process(args)
    warnings = validate_outputs(sif_content)

    # Write SIF file
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w") as f:
        f.write(sif_content)

    status = {
        "status": "success",
        "output_file": args.output,
        "sif_lines": sif_content.count("\n"),
        "coordinate_system": args.coordinate_system,
        "simulation_type": "Transient" if args.n_timesteps > 1 else "Steady State",
        "n_timesteps": args.n_timesteps,
        "dt_seconds": args.dt_years * SEC_PER_YEAR,
        "friction_law": args.friction_law,
        "warnings": warnings,
    }
    print(json.dumps(status, indent=2), file=sys.stderr)


if __name__ == "__main__":
    main()
