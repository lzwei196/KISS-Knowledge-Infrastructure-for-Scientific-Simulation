#!/usr/bin/env python3
"""
run_issm.py — Execute an ISSM simulation end-to-end using the Python API.

This wrapper handles the complete ISSM workflow:
1. Create model object
2. Generate mesh from domain outline
3. Set ice/ocean masks
4. Parameterize (load geometry, materials, friction, BCs)
5. Set flow equation
6. Configure solver
7. Run solve
8. Export results

ISSM is a compiled C++/Fortran code called via Python wrappers. The Python API
mirrors the MATLAB API exactly. Both require compiled ISSM binaries with PETSc.

CRITICAL REQUIREMENTS:
  - ISSM must be compiled and installed (issm binary in PATH)
  - ISSM Python modules must be in PYTHONPATH (set via etc/environment.sh)
  - PETSc must be available for parallel solves
  - All inputs in ISSM units: meters (coordinates), m/yr (velocity), K (temp)

Usage:
    python run_issm.py \
        --issm_dir /path/to/ISSM \
        --domain DomainOutline.exp \
        --resolution 50000 \
        --par_file Greenland.py \
        --flow_equation SSA \
        --solution Stressbalance \
        --nprocs 4 \
        --output_dir ./results/

    python run_issm.py \
        --issm_dir /path/to/ISSM \
        --example SquareIceShelf \
        --output_dir ./results/
"""

import argparse
import json
import os
import subprocess
import sys
import time


# =============================================================================
# Validation
# =============================================================================
def validate_inputs(args):
    """Preflight checks before running ISSM."""
    errors = []
    warnings = []

    # Check ISSM installation
    if not os.path.isdir(args.issm_dir):
        errors.append(f"ISSM directory not found: {args.issm_dir}")
    else:
        # Check for key files
        env_script = os.path.join(args.issm_dir, "etc", "environment.sh")
        if not os.path.exists(env_script):
            errors.append(f"ISSM environment script not found: {env_script}")

        # Check Python API
        model_py = os.path.join(args.issm_dir, "src", "m", "classes", "model.py")
        if not os.path.exists(model_py):
            warnings.append("model.py not found in src/m/classes/ — Python API may not be available")

        # Check binary
        issm_bin = os.path.join(args.issm_dir, "bin", "issm")
        alt_bin = os.path.join(args.issm_dir, "bin", "issm.exe")
        if not os.path.exists(issm_bin) and not os.path.exists(alt_bin):
            warnings.append("ISSM binary not found in bin/ — may not be compiled yet")

    # Check domain file for non-example mode
    if not args.example:
        if args.domain and not os.path.exists(args.domain):
            errors.append(f"Domain outline not found: {args.domain}")
        if args.par_file and not os.path.exists(args.par_file):
            errors.append(f"Parameter file not found: {args.par_file}")
    else:
        example_dir = os.path.join(args.issm_dir, "examples", args.example)
        if not os.path.isdir(example_dir):
            errors.append(f"Example directory not found: {example_dir}")

    # Validate flow equation
    valid_flow_eqs = ["SSA", "SIA", "HO", "FS", "L1L2", "MOLHO"]
    if args.flow_equation not in valid_flow_eqs:
        errors.append(f"Invalid flow equation '{args.flow_equation}'. Must be one of: {valid_flow_eqs}")

    # Validate solution type
    valid_solutions = ["Stressbalance", "Masstransport", "Thermal", "Transient",
                       "Balancethickness", "Hydrology", "DamageEvolution", "Steadystate"]
    if args.solution not in valid_solutions:
        errors.append(f"Invalid solution '{args.solution}'. Must be one of: {valid_solutions}")

    if args.nprocs < 1:
        errors.append(f"--nprocs must be >= 1, got {args.nprocs}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors, "warnings": warnings}))
        sys.exit(1)
    if warnings:
        for w in warnings:
            print(f"WARNING: {w}", file=sys.stderr)

    return True


def validate_outputs(output_dir):
    """Validate that ISSM produced expected output files."""
    errors = []
    warnings = []

    result_files = ["results.json"]
    for rf in result_files:
        path = os.path.join(output_dir, rf)
        if not os.path.exists(path):
            warnings.append(f"Expected output not found: {path}")

    return warnings


# =============================================================================
# ISSM execution
# =============================================================================
def generate_run_script(args, script_path):
    """Generate a Python script that runs the ISSM simulation.

    We generate a standalone script rather than importing ISSM directly because
    ISSM's Python path setup requires sourcing etc/environment.sh first.
    """
    if args.example:
        example_dir = os.path.join(args.issm_dir, "examples", args.example)
        script = f"""#!/usr/bin/env python3
import sys
import os
import json
import time
import numpy as np

# Add ISSM paths
issm_dir = "{args.issm_dir}"
sys.path.insert(0, os.path.join(issm_dir, "src", "m", "classes"))
sys.path.insert(0, os.path.join(issm_dir, "src", "m", "solve"))
sys.path.insert(0, os.path.join(issm_dir, "src", "m", "mesh"))
sys.path.insert(0, os.path.join(issm_dir, "src", "m", "parameterization"))
sys.path.insert(0, os.path.join(issm_dir, "src", "m", "io"))
sys.path.insert(0, os.path.join(issm_dir, "src", "m", "boundaryconditions"))

os.chdir("{example_dir}")

# Run the example
start_time = time.time()
try:
    exec(open("runme.py").read())
    elapsed = time.time() - start_time
    result = {{
        "status": "success",
        "example": "{args.example}",
        "elapsed_s": round(elapsed, 2),
        "output_dir": "{args.output_dir}"
    }}
except Exception as e:
    elapsed = time.time() - start_time
    result = {{
        "status": "error",
        "errors": [str(e)],
        "elapsed_s": round(elapsed, 2)
    }}

with open(os.path.join("{args.output_dir}", "results.json"), "w") as f:
    json.dump(result, f, indent=2)

print(json.dumps(result, indent=2))
"""
    else:
        script = f"""#!/usr/bin/env python3
import sys
import os
import json
import time
import numpy as np

# Add ISSM paths
issm_dir = "{args.issm_dir}"
for subdir in ["classes", "solve", "mesh", "parameterization", "io",
               "boundaryconditions", "materials", "interp", "array",
               "geometry", "extrusion"]:
    sys.path.insert(0, os.path.join(issm_dir, "src", "m", subdir))

from model import model
from triangle import triangle
from setmask import setmask
from parameterize import parameterize
from setflowequation import setflowequation
from solve import solve
from generic import generic
from socket import gethostname

start_time = time.time()
try:
    # Step 1: Create model and mesh
    md = triangle(model(), '{args.domain}', {args.resolution})
    print(f"Mesh: {{md.mesh.numberofvertices}} vertices, {{md.mesh.numberofelements}} elements",
          file=sys.stderr)

    # Step 2: Set mask
    md = setmask(md, '{args.ocean_mask}', '{args.grounded_mask}')

    # Step 3: Parameterize
    md = parameterize(md, '{args.par_file}')

    # Step 4: Set flow equation
    md = setflowequation(md, '{args.flow_equation}', 'all')

    # Step 5: Configure solver
    md.cluster = generic('name', gethostname(), 'np', {args.nprocs})

    # Step 6: Solve
    md = solve(md, '{args.solution}')

    elapsed = time.time() - start_time

    # Extract results summary
    sol_name = '{args.solution}Solution'
    sol = getattr(md.results, sol_name, None)
    result_summary = {{"status": "success", "elapsed_s": round(elapsed, 2)}}

    if sol is not None:
        if hasattr(sol, 'Vel'):
            vel = np.array(sol.Vel)
            result_summary["velocity"] = {{
                "max": float(np.nanmax(vel)),
                "mean": float(np.nanmean(vel)),
                "units": "m/yr"
            }}
        if hasattr(sol, 'Thickness'):
            thk = np.array(sol.Thickness)
            result_summary["thickness"] = {{
                "max": float(np.nanmax(thk)),
                "mean": float(np.nanmean(thk)),
                "units": "m"
            }}

    # Save results
    os.makedirs("{args.output_dir}", exist_ok=True)
    with open(os.path.join("{args.output_dir}", "results.json"), "w") as f:
        json.dump(result_summary, f, indent=2)

    print(json.dumps(result_summary, indent=2))

except Exception as e:
    elapsed = time.time() - start_time
    result = {{
        "status": "error",
        "errors": [str(e)],
        "elapsed_s": round(elapsed, 2)
    }}
    os.makedirs("{args.output_dir}", exist_ok=True)
    with open(os.path.join("{args.output_dir}", "results.json"), "w") as f:
        json.dump(result, f, indent=2)
    print(json.dumps(result, indent=2))
    sys.exit(1)
"""

    with open(script_path, 'w') as f:
        f.write(script)
    os.chmod(script_path, 0o755)
    return script_path


def run_issm(args):
    """Execute the ISSM simulation."""
    os.makedirs(args.output_dir, exist_ok=True)

    # Generate run script
    script_path = os.path.join(args.output_dir, "_run_issm.py")
    generate_run_script(args, script_path)

    # Build environment with ISSM paths
    env = os.environ.copy()
    issm_dir = os.path.abspath(args.issm_dir)
    env["ISSM_DIR"] = issm_dir

    # Add ISSM Python paths
    python_paths = []
    for subdir in ["classes", "solve", "mesh", "parameterization", "io",
                   "boundaryconditions", "materials", "interp", "array",
                   "geometry", "extrusion", "partition", "consistency",
                   "modeldata", "qmu", "inversions", "export"]:
        path = os.path.join(issm_dir, "src", "m", subdir)
        if os.path.isdir(path):
            python_paths.append(path)

    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = ":".join(python_paths) + (":" + existing_pythonpath if existing_pythonpath else "")

    # Add ISSM bin to PATH
    bin_dir = os.path.join(issm_dir, "bin")
    if os.path.isdir(bin_dir):
        env["PATH"] = bin_dir + ":" + env.get("PATH", "")

    # Add lib paths
    lib_dir = os.path.join(issm_dir, "lib")
    if os.path.isdir(lib_dir):
        env["LD_LIBRARY_PATH"] = lib_dir + ":" + env.get("LD_LIBRARY_PATH", "")

    # Execute
    print(f"Running ISSM simulation...", file=sys.stderr)
    start = time.time()

    try:
        result = subprocess.run(
            [sys.executable, script_path],
            capture_output=True,
            text=True,
            timeout=args.timeout,
            env=env,
            cwd=args.output_dir
        )

        elapsed = time.time() - start

        if result.returncode == 0:
            print(result.stdout)
            if result.stderr:
                print(f"STDERR:\n{result.stderr[:1000]}", file=sys.stderr)
        else:
            error_result = {
                "status": "error",
                "errors": [f"ISSM exited with code {result.returncode}"],
                "stdout": result.stdout[:2000],
                "stderr": result.stderr[:2000],
                "elapsed_s": round(elapsed, 2)
            }
            print(json.dumps(error_result, indent=2))
            sys.exit(1)

    except subprocess.TimeoutExpired:
        error_result = {
            "status": "error",
            "errors": [f"ISSM timed out after {args.timeout} seconds"]
        }
        print(json.dumps(error_result, indent=2))
        sys.exit(1)

    # Validate outputs
    output_warnings = validate_outputs(args.output_dir)
    if output_warnings:
        for w in output_warnings:
            print(f"WARNING: {w}", file=sys.stderr)


# =============================================================================
# CLI
# =============================================================================
def main():
    parser = argparse.ArgumentParser(description="Execute ISSM simulation")

    parser.add_argument("--issm_dir", required=True, help="Path to ISSM installation")
    parser.add_argument("--example", help="Run a built-in example (e.g., SquareIceShelf)")

    parser.add_argument("--domain", help="Domain outline .exp file")
    parser.add_argument("--resolution", type=float, default=50000, help="Mesh resolution (m)")
    parser.add_argument("--par_file", help="Parameter file (.py or .par)")
    parser.add_argument("--ocean_mask", default="", help="Floating ice domain .exp file")
    parser.add_argument("--grounded_mask", default="", help="Grounded ice .exp file")
    parser.add_argument("--flow_equation", default="SSA",
                        choices=["SSA", "SIA", "HO", "FS", "L1L2", "MOLHO"])
    parser.add_argument("--solution", default="Stressbalance",
                        choices=["Stressbalance", "Masstransport", "Thermal", "Transient",
                                 "Balancethickness", "Hydrology", "DamageEvolution", "Steadystate"])
    parser.add_argument("--nprocs", type=int, default=2, help="Number of processors")
    parser.add_argument("--timeout", type=int, default=3600, help="Timeout in seconds")
    parser.add_argument("--output_dir", required=True, help="Output directory")

    args = parser.parse_args()
    validate_inputs(args)
    run_issm(args)


if __name__ == "__main__":
    main()
