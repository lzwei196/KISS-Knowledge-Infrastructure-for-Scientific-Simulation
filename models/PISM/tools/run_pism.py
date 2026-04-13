#!/usr/bin/env python3
"""
run_pism.py — Execution wrapper for the PISM ice sheet model.

Constructs and executes a validated PISM command line. Pre-checks the input file,
verifies PETSc/MPI availability, and monitors the run for common failure patterns.

Usage:
    python run_pism.py \\
        --input pism_bootstrap.nc \\
        --output result.nc \\
        --duration 1000 \\
        --grid-dx 20 \\
        --mode bootstrap \\
        --dynamics hybrid \\
        --nprocs 4 \\
        [--pism-bin /path/to/pism] \\
        [--extra-args "-sia_e 3.0 -pseudo_plastic_q 0.25"] \\
        [--output-json result.json]
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time

try:
    import numpy as np
    from netCDF4 import Dataset
except ImportError:
    pass  # Non-fatal — needed only for input validation


def validate_inputs(args):
    """Pre-flight checks before running PISM."""
    errors = []
    warnings = []

    # Check PISM binary
    pism_bin = args.pism_bin or "pism"
    pism_path = shutil.which(pism_bin)
    if pism_path is None:
        # Try common locations
        for candidate in [
            os.path.expanduser("~/pism/bin/pism"),
            "/usr/local/bin/pism",
            "/usr/bin/pism",
        ]:
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                pism_path = candidate
                break
        if pism_path is None:
            errors.append(f"PISM executable '{pism_bin}' not found in PATH. "
                          "Set --pism-bin or add PISM to PATH.")

    # Check MPI
    mpiexec = shutil.which("mpiexec") or shutil.which("mpirun")
    if mpiexec is None and args.nprocs > 1:
        errors.append("mpiexec/mpirun not found — cannot run in parallel. "
                      "Set --nprocs 1 for serial execution.")

    # Check input file
    if args.mode != "eisII" and args.mode != "test":
        if not os.path.isfile(args.input):
            errors.append(f"Input file not found: {args.input}")
        else:
            try:
                ds = Dataset(args.input, "r")
                # Bootstrap mode needs minimum variables
                if args.mode == "bootstrap":
                    required = ["topg", "thk"]
                    for var in required:
                        if var not in ds.variables:
                            warnings.append(f"Bootstrap variable '{var}' not in input — "
                                            "PISM will use defaults")
                ds.close()
            except Exception as e:
                warnings.append(f"Cannot validate input NetCDF: {e}")

    # Check grid parameters
    if args.grid_dx <= 0:
        errors.append(f"Grid spacing must be positive, got {args.grid_dx}")
    if args.duration <= 0:
        errors.append(f"Duration must be positive, got {args.duration}")
    if args.nprocs < 1:
        errors.append(f"nprocs must be >= 1, got {args.nprocs}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}, indent=2))
        sys.exit(1)

    return pism_path, mpiexec, warnings


def build_command(args, pism_path, mpiexec):
    """Build the PISM command line."""
    cmd_parts = []

    # MPI prefix
    if args.nprocs > 1 and mpiexec:
        cmd_parts.extend([mpiexec, "-n", str(args.nprocs)])

    cmd_parts.append(pism_path or "pism")

    # Run mode
    if args.mode == "eisII":
        cmd_parts.extend(["-eisII", args.eisII_exp or "A"])
        cmd_parts.extend(["-Mx", str(args.grid_mx or 61)])
        cmd_parts.extend(["-My", str(args.grid_my or 61)])
        cmd_parts.extend(["-Mz", str(args.grid_mz or 61)])
        cmd_parts.extend(["-Lz", "5000"])
    elif args.mode == "bootstrap":
        cmd_parts.extend(["-i", args.input, "-bootstrap"])
        cmd_parts.extend([f"-dx", f"{args.grid_dx}km", f"-dy", f"{args.grid_dx}km"])
        cmd_parts.extend(["-Mz", str(args.grid_mz or 101)])
        cmd_parts.extend(["-Lz", str(args.lz or 4000)])
        cmd_parts.extend(["-Mbz", str(args.mbz or 11)])
        cmd_parts.extend(["-Lbz", str(args.lbz or 2000)])
    elif args.mode == "restart":
        cmd_parts.extend(["-i", args.input])

    # Time
    if args.ys is not None:
        cmd_parts.extend(["-ys", str(args.ys)])
        cmd_parts.extend(["-ye", str(args.ye or 0)])
    else:
        cmd_parts.extend(["-y", str(int(args.duration))])

    # Dynamics
    if args.dynamics == "hybrid":
        cmd_parts.extend(["-stress_balance", "ssa+sia"])
        cmd_parts.extend(["-pseudo_plastic"])
        cmd_parts.extend(["-pseudo_plastic_q", str(args.ppq or 0.25)])
        cmd_parts.extend(["-till_effective_fraction_overburden",
                          str(args.tefo or 0.02)])
    elif args.dynamics == "sia":
        pass  # SIA is default

    # Physics
    if args.sia_e:
        cmd_parts.extend(["-sia_e", str(args.sia_e)])

    # Skip mechanism for efficiency
    cmd_parts.extend(["-skip", "-skip_max", str(args.skip_max or 10)])

    # Output
    cmd_parts.extend(["-o", args.output])

    # Diagnostics
    if args.scalar_file:
        cmd_parts.extend(["-scalar_file", args.scalar_file])
        cmd_parts.extend(["-scalar_times", args.scalar_times or "yearly"])
    if args.spatial_file:
        cmd_parts.extend(["-spatial_file", args.spatial_file])
        cmd_parts.extend(["-spatial_times", args.spatial_times or "0:100:end"])
        if args.spatial_vars:
            cmd_parts.extend(["-spatial_vars", args.spatial_vars])

    # Extra arguments
    if args.extra_args:
        cmd_parts.extend(args.extra_args.split())

    return cmd_parts


def process(args):
    """Execute PISM and capture output."""
    pism_path, mpiexec, warnings = validate_inputs(args)

    cmd = build_command(args, pism_path, mpiexec)
    cmd_str = " ".join(cmd)

    print(f"Executing: {cmd_str}", file=sys.stderr)

    start_time = time.time()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=args.timeout or 86400,
        )
        elapsed = time.time() - start_time

        # Check for common error patterns in output
        combined_output = proc.stdout + proc.stderr
        error_patterns = {
            "PETSC ERROR": "PETSc error — check solver configuration",
            "SNES Diverged": "SSA solver diverged — reduce time step or check input",
            "CFL violation": "CFL violation — grid too coarse or time step too large",
            "KSP Diverged": "Linear solver diverged — try different preconditioner",
            "memory": "Possible memory issue — reduce grid resolution or increase nodes",
        }

        detected_issues = []
        for pattern, msg in error_patterns.items():
            if pattern.lower() in combined_output.lower():
                detected_issues.append(msg)

        result = {
            "status": "success" if proc.returncode == 0 else "error",
            "command": cmd_str,
            "return_code": proc.returncode,
            "elapsed_seconds": round(elapsed, 1),
            "output_file": args.output,
            "stdout_tail": proc.stdout[-2000:] if proc.stdout else "",
            "stderr_tail": proc.stderr[-2000:] if proc.stderr else "",
            "warnings": warnings,
            "detected_issues": detected_issues,
        }

        if proc.returncode != 0:
            result["errors"] = [
                f"PISM exited with code {proc.returncode}",
                proc.stderr[-500:] if proc.stderr else "No stderr output",
            ]

        return result

    except subprocess.TimeoutExpired:
        return {
            "status": "error",
            "errors": [f"PISM timed out after {args.timeout}s"],
            "command": cmd_str,
            "warnings": warnings,
        }
    except Exception as e:
        return {
            "status": "error",
            "errors": [f"Failed to execute PISM: {e}"],
            "command": cmd_str,
            "warnings": warnings,
        }


def validate_outputs(result):
    """Verify PISM output file exists and is valid."""
    if result["status"] != "success":
        return result

    output_file = result.get("output_file")
    if not output_file or not os.path.isfile(output_file):
        result["warnings"].append("Output file not found after run")
        return result

    try:
        ds = Dataset(output_file, "r")
        result["output_variables"] = list(ds.variables.keys())
        result["output_dimensions"] = {
            d: len(ds.dimensions[d]) for d in ds.dimensions
        }
        if "thk" in ds.variables:
            thk = ds.variables["thk"][:]
            result["ice_volume_check"] = {
                "max_thickness_m": float(np.nanmax(thk)),
                "mean_thickness_m": float(np.nanmean(thk)),
                "ice_cells": int(np.sum(thk > 0)),
            }
        ds.close()
    except Exception as e:
        result["warnings"].append(f"Cannot read output: {e}")

    return result


def main():
    parser = argparse.ArgumentParser(description="PISM execution wrapper")
    parser.add_argument("--input", default="", help="Input NetCDF file")
    parser.add_argument("--output", required=True, help="Output NetCDF file")
    parser.add_argument("--duration", type=float, default=1000, help="Run duration (years)")
    parser.add_argument("--grid-dx", type=float, default=20, help="Grid spacing (km)")
    parser.add_argument("--grid-mx", type=int, default=None, help="Grid points in X")
    parser.add_argument("--grid-my", type=int, default=None, help="Grid points in Y")
    parser.add_argument("--grid-mz", type=int, default=101, help="Vertical layers")
    parser.add_argument("--lz", type=float, default=4000, help="Vertical domain height (m)")
    parser.add_argument("--lbz", type=float, default=2000, help="Bedrock thermal depth (m)")
    parser.add_argument("--mbz", type=int, default=11, help="Bedrock thermal layers")
    parser.add_argument("--mode", default="bootstrap",
                        choices=["bootstrap", "restart", "eisII", "test"])
    parser.add_argument("--dynamics", default="sia", choices=["sia", "hybrid"])
    parser.add_argument("--nprocs", type=int, default=4, help="MPI processes")
    parser.add_argument("--pism-bin", default=None, help="Path to PISM executable")
    parser.add_argument("--sia-e", type=float, default=3.0, help="SIA enhancement factor")
    parser.add_argument("--ppq", type=float, default=0.25, help="Pseudo-plastic q")
    parser.add_argument("--tefo", type=float, default=0.02,
                        help="Till effective fraction overburden")
    parser.add_argument("--skip-max", type=int, default=10, help="Skip max count")
    parser.add_argument("--ys", type=float, default=None, help="Start year")
    parser.add_argument("--ye", type=float, default=None, help="End year")
    parser.add_argument("--eisII-exp", default="A", help="EISMINT II experiment letter")
    parser.add_argument("--scalar-file", default=None, help="Scalar output file")
    parser.add_argument("--scalar-times", default=None, help="Scalar output times")
    parser.add_argument("--spatial-file", default=None, help="Spatial output file")
    parser.add_argument("--spatial-times", default=None, help="Spatial output times")
    parser.add_argument("--spatial-vars", default=None, help="Spatial variables")
    parser.add_argument("--extra-args", default=None, help="Additional PISM arguments")
    parser.add_argument("--timeout", type=int, default=86400, help="Timeout in seconds")
    parser.add_argument("--output-json", default=None, help="Write result JSON to file")

    args = parser.parse_args()
    result = process(args)
    result = validate_outputs(result)

    output_json = json.dumps(result, indent=2, default=str)
    if args.output_json:
        os.makedirs(os.path.dirname(args.output_json) or ".", exist_ok=True)
        with open(args.output_json, "w") as f:
            f.write(output_json)
    print(output_json)


if __name__ == "__main__":
    main()
