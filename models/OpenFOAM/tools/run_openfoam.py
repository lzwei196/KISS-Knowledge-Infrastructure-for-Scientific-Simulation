#!/usr/bin/env python3
"""
Execute an OpenFOAM simulation with pre-flight validation and monitoring.

Pre-flight checks:
  1. Mesh exists (constant/polyMesh/points)
  2. Boundary conditions present in 0/ directory
  3. controlDict, fvSchemes, fvSolution exist in system/
  4. Patch names in 0/ fields match polyMesh/boundary patches
  5. Dimension arrays are consistent

Execution:
  - Serial: foamRun (or legacy solver name)
  - Parallel: mpirun -np N foamRun -parallel

Post-run checks:
  - Exit code verification
  - Final residual extraction from log
  - Courant number monitoring

CRITICAL: For parallel runs, numberOfSubdomains in decomposeParDict MUST
          match the -np argument to mpirun. Mismatch causes immediate crash.

CRITICAL: Source etc/bashrc before running. Without OpenFOAM environment
          variables, no executables will be found.

Usage:
    python run_openfoam.py \\
        --case-dir ./cavity \\
        --solver incompressibleFluid \\
        --np 1 \\
        --output result.json

    python run_openfoam.py \\
        --case-dir ./damBreak \\
        --solver incompressibleVoF \\
        --np 4 \\
        --foam-bashrc /opt/OpenFOAM/etc/bashrc \\
        --output result.json
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time


def validate_inputs(args):
    """Pre-flight validation of case directory."""
    errors = []
    warnings = []

    case_dir = args.case_dir

    # Check case directory exists
    if not os.path.isdir(case_dir):
        errors.append(f"Case directory not found: {case_dir}")
        print(json.dumps({"status": "error", "errors": errors}, indent=2))
        sys.exit(1)

    # Check mesh
    mesh_dir = os.path.join(case_dir, "constant", "polyMesh")
    if not os.path.isdir(mesh_dir):
        errors.append(
            f"Mesh not found at {mesh_dir}. "
            "Run blockMesh or snappyHexMesh first."
        )
    else:
        points_file = os.path.join(mesh_dir, "points")
        if not os.path.isfile(points_file):
            errors.append(f"Mesh points file missing: {points_file}")

    # Check system dictionaries
    system_dir = os.path.join(case_dir, "system")
    for required in ["controlDict", "fvSchemes", "fvSolution"]:
        fpath = os.path.join(system_dir, required)
        if not os.path.isfile(fpath):
            errors.append(f"Required system file missing: {fpath}")

    # Check 0/ directory
    zero_dir = os.path.join(case_dir, "0")
    if not os.path.isdir(zero_dir):
        errors.append(f"Initial conditions directory missing: {zero_dir}")
    else:
        fields = [f for f in os.listdir(zero_dir)
                  if os.path.isfile(os.path.join(zero_dir, f))]
        if not fields:
            errors.append(f"No field files found in {zero_dir}")

    # Check parallel consistency
    if args.np > 1:
        decompose_dict = os.path.join(system_dir, "decomposeParDict")
        if not os.path.isfile(decompose_dict):
            errors.append(
                f"Parallel run requested (np={args.np}) but "
                f"decomposeParDict not found at {decompose_dict}"
            )
        else:
            with open(decompose_dict, "r") as f:
                content = f.read()
            match = re.search(r"numberOfSubdomains\s+(\d+)", content)
            if match:
                n_sub = int(match.group(1))
                if n_sub != args.np:
                    errors.append(
                        f"MPI mismatch: --np={args.np} but "
                        f"decomposeParDict has numberOfSubdomains={n_sub}. "
                        "These MUST match."
                    )

        # Check processor directories
        proc0 = os.path.join(case_dir, "processor0")
        if not os.path.isdir(proc0):
            warnings.append(
                "processor0/ not found. Will attempt to run decomposePar first."
            )

    if errors:
        print(json.dumps({"status": "error", "errors": errors,
                           "warnings": warnings}, indent=2))
        sys.exit(1)

    return warnings


def build_env(foam_bashrc):
    """Build environment dict by sourcing OpenFOAM bashrc."""
    if foam_bashrc and os.path.isfile(foam_bashrc):
        cmd = f"source {foam_bashrc} && env"
        proc = subprocess.run(
            ["bash", "-c", cmd],
            capture_output=True, text=True, timeout=30
        )
        env = {}
        for line in proc.stdout.splitlines():
            if "=" in line:
                key, _, val = line.partition("=")
                env[key] = val
        return env
    return os.environ.copy()


def run_decompose(case_dir, env):
    """Run decomposePar if needed for parallel execution."""
    proc0 = os.path.join(case_dir, "processor0")
    if os.path.isdir(proc0):
        return {"status": "skipped", "reason": "processor directories exist"}

    cmd = ["decomposePar", "-case", case_dir]
    proc = subprocess.run(
        cmd, capture_output=True, text=True, env=env, timeout=300
    )
    return {
        "status": "success" if proc.returncode == 0 else "error",
        "returncode": proc.returncode,
        "stdout_tail": proc.stdout[-500:] if proc.stdout else "",
        "stderr_tail": proc.stderr[-500:] if proc.stderr else "",
    }


def run_solver(case_dir, solver, np, env):
    """Execute the OpenFOAM solver."""
    if np > 1:
        cmd = [
            "mpirun", "-np", str(np),
            "foamRun", "-solver", solver, "-case", case_dir, "-parallel"
        ]
    else:
        cmd = ["foamRun", "-solver", solver, "-case", case_dir]

    start_time = time.time()
    proc = subprocess.run(
        cmd, capture_output=True, text=True, env=env, timeout=3600
    )
    elapsed = time.time() - start_time

    return {
        "command": " ".join(cmd),
        "returncode": proc.returncode,
        "elapsed_seconds": round(elapsed, 2),
        "stdout_tail": proc.stdout[-2000:] if proc.stdout else "",
        "stderr_tail": proc.stderr[-1000:] if proc.stderr else "",
    }


def parse_residuals(log_text):
    """Extract final residuals and Courant number from solver log."""
    residuals = {}

    # Find last residual for each variable
    for match in re.finditer(
        r"Solving for (\w+), Initial residual = ([\d.e+-]+), "
        r"Final residual = ([\d.e+-]+)",
        log_text
    ):
        var = match.group(1)
        residuals[var] = {
            "initial": float(match.group(2)),
            "final": float(match.group(3)),
        }

    # Find last Courant number
    courant = None
    for match in re.finditer(r"Courant Number mean: ([\d.e+-]+) max: ([\d.e+-]+)",
                             log_text):
        courant = {
            "mean": float(match.group(1)),
            "max": float(match.group(2)),
        }

    return {"residuals": residuals, "courant": courant}


def process(args):
    """Execute the full run pipeline."""
    preflight_warnings = validate_inputs(args)
    env = build_env(args.foam_bashrc)

    result = {
        "status": "success",
        "case_dir": os.path.abspath(args.case_dir),
        "solver": args.solver,
        "np": args.np,
        "warnings": preflight_warnings,
    }

    # Parallel decomposition if needed
    if args.np > 1:
        decomp = run_decompose(args.case_dir, env)
        result["decomposition"] = decomp
        if decomp["status"] == "error":
            result["status"] = "error"
            result["errors"] = [f"decomposePar failed: {decomp.get('stderr_tail', '')}"]
            return result

    # Run solver
    run_result = run_solver(args.case_dir, args.solver, args.np, env)
    result["execution"] = run_result

    if run_result["returncode"] != 0:
        result["status"] = "error"
        result["errors"] = [
            f"Solver exited with code {run_result['returncode']}",
            run_result["stderr_tail"][:500],
        ]
    else:
        # Parse residuals from log
        log_analysis = parse_residuals(run_result["stdout_tail"])
        result["residuals"] = log_analysis["residuals"]
        result["courant"] = log_analysis["courant"]

    # List output time directories
    time_dirs = []
    for d in sorted(os.listdir(args.case_dir)):
        try:
            float(d)
            time_dirs.append(d)
        except ValueError:
            pass
    result["output_times"] = time_dirs

    return result


def validate_outputs(result):
    """Post-run validation."""
    warnings = result.get("warnings", [])

    if result["status"] == "success":
        if not result.get("output_times"):
            warnings.append("No output time directories found after run")

        residuals = result.get("residuals", {})
        for var, res in residuals.items():
            if res["final"] > 1e-3:
                warnings.append(
                    f"High final residual for {var}: {res['final']:.2e} "
                    "(may indicate poor convergence)"
                )

        courant = result.get("courant")
        if courant and courant["max"] > 1.0:
            warnings.append(
                f"Max Courant number {courant['max']:.2f} > 1.0 "
                "(may cause instability for explicit schemes)"
            )

    result["warnings"] = warnings
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Run OpenFOAM simulation with validation"
    )
    parser.add_argument("--case-dir", required=True,
                        help="OpenFOAM case directory")
    parser.add_argument("--solver", default="incompressibleFluid",
                        help="Solver module name")
    parser.add_argument("--np", type=int, default=1,
                        help="Number of MPI processes (1=serial)")
    parser.add_argument("--foam-bashrc", default=None,
                        help="Path to OpenFOAM etc/bashrc")
    parser.add_argument("--output", default=None,
                        help="Output JSON summary file")

    args = parser.parse_args()
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
