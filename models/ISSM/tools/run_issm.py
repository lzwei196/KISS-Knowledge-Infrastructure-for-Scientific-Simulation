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
import shlex
import shutil
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
        # Run a COPY of the example in the output folder (never inside $ISSM_DIR/examples);
        # ISSM's own generic_settings.py hook (private folder, first on sys.path) moves the
        # cluster executionpath out of $ISSM_DIR/execution.
        example_dir = args.example_run_dir
        script = f"""#!/usr/bin/env python3
import sys
import os
import json
import time
import numpy as np

# ISSM generic_settings hook (executionpath) must be found before runme.py imports generic
sys.path.insert(0, {args.settings_dir!r})

# Add ISSM paths
issm_dir = {args.issm_dir!r}
sys.path.insert(0, os.path.join(issm_dir, "src", "m", "classes"))
sys.path.insert(0, os.path.join(issm_dir, "src", "m", "solve"))
sys.path.insert(0, os.path.join(issm_dir, "src", "m", "mesh"))
sys.path.insert(0, os.path.join(issm_dir, "src", "m", "parameterization"))
sys.path.insert(0, os.path.join(issm_dir, "src", "m", "io"))
sys.path.insert(0, os.path.join(issm_dir, "src", "m", "boundaryconditions"))

os.chdir({example_dir!r})

# Run the example
start_time = time.time()
rc = 0
try:
    exec(open("runme.py").read())
    elapsed = time.time() - start_time
    result = {{
        "status": "success",
        "example": {args.example!r},
        "elapsed_s": round(elapsed, 2),
        "output_dir": {args.output_dir!r},
        "example_run_dir": {example_dir!r},
        "execution_dir": {args.execution_dir!r}
    }}
except Exception as e:
    elapsed = time.time() - start_time
    result = {{
        "status": "error",
        "errors": [str(e)],
        "elapsed_s": round(elapsed, 2)
    }}
    rc = 1

with open(os.path.join({args.output_dir!r}, "results.json"), "w") as f:
    json.dump(result, f, indent=2)

print(json.dumps(result, indent=2))
sys.exit(rc)
"""
    else:
        script = f"""#!/usr/bin/env python3
import sys
import os
import json
import time
import numpy as np

# Add ISSM paths
issm_dir = {args.issm_dir!r}
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
    md = triangle(model(), {args.domain!r}, {args.resolution})
    print(f"Mesh: {{md.mesh.numberofvertices}} vertices, {{md.mesh.numberofelements}} elements",
          file=sys.stderr)

    # Step 2: Set mask
    md = setmask(md, {args.ocean_mask!r}, {args.grounded_mask!r})

    # Step 3: Parameterize
    md = parameterize(md, {args.par_file!r})

    # Step 4: Set flow equation
    md = setflowequation(md, {args.flow_equation!r}, 'all')

    # Step 5: Configure solver
    # executionpath: keep ISSM's run files out of $ISSM_DIR/execution
    md.cluster = generic('name', gethostname(), 'np', {args.nprocs},
                         'executionpath', {args.execution_dir!r})

    # Step 6: Solve
    md = solve(md, {args.solution!r})

    elapsed = time.time() - start_time

    # Extract results summary
    sol_name = {args.solution!r} + 'Solution'
    sol = getattr(md.results, sol_name, None)
    if sol is None:
        raise RuntimeError(f"ISSM finished but md.results has no {{sol_name}}")
    # ISSM's own result file (kept in the execution folder; the copy in the cwd is deleted
    # by loadresultsfromcluster) -> for tools/parse_issm_output.py --outbin
    outbin = os.path.join(md.cluster.executionpath, md.private.runtimename,
                          md.miscellaneous.name + '.outbin')
    if not os.path.isfile(outbin) or os.path.getsize(outbin) == 0:
        raise RuntimeError(f"ISSM result file missing or empty: {{outbin}}")
    result_summary = {{"status": "success", "elapsed_s": round(elapsed, 2),
                       "outbin": os.path.abspath(outbin), "yts": float(md.constants.yts)}}

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
    os.makedirs({args.output_dir!r}, exist_ok=True)
    with open(os.path.join({args.output_dir!r}, "results.json"), "w") as f:
        json.dump(result_summary, f, indent=2)

    print(json.dumps(result_summary, indent=2))

except Exception as e:
    elapsed = time.time() - start_time
    result = {{
        "status": "error",
        "errors": [str(e)],
        "elapsed_s": round(elapsed, 2)
    }}
    os.makedirs({args.output_dir!r}, exist_ok=True)
    with open(os.path.join({args.output_dir!r}, "results.json"), "w") as f:
        json.dump(result, f, indent=2)
    print(json.dumps(result, indent=2))
    sys.exit(1)
"""

    with open(script_path, 'w') as f:
        f.write(script)
    os.chmod(script_path, 0o755)
    return script_path


def fail(errors):
    """Print a JSON error and exit 1."""
    print(json.dumps({"status": "error", "errors": errors}, indent=2))
    sys.exit(1)


def normalize_paths(args):
    """Make every path absolute (relative to the caller's cwd, as validate_inputs checks them).

    The generated script runs with cwd=output_dir, so relative paths would otherwise resolve
    against the output folder. Mask arguments stay as given when they are 'all' / '' (ISSM
    keywords) or do not name an existing file.
    """
    args.issm_dir = os.path.abspath(args.issm_dir)
    args.output_dir = os.path.abspath(args.output_dir)
    for name in ("domain", "par_file"):
        val = getattr(args, name)
        if val:
            setattr(args, name, os.path.abspath(val))
    for name in ("ocean_mask", "grounded_mask"):
        val = getattr(args, name)
        if val and val != "all" and os.path.isfile(val):
            setattr(args, name, os.path.abspath(val))
    args.execution_dir = os.path.abspath(args.execution_dir or
                                         os.path.join(args.output_dir, "execution"))


def select_mpiexec(args):
    """MPI launcher for issm.exe: --mpiexec -> $ISSM_MPIEXEC -> $ISSM_DIR's PETSc MPICH.

    issm.exe is linked with PETSc's MPICH; another mpiexec on PATH (e.g. OpenMPI) starts N
    independent 1-rank copies instead of one N-rank run, so there is NO PATH fallback.
    """
    if args.mpiexec is not None:
        cand, source = args.mpiexec, "--mpiexec"
    elif os.environ.get("ISSM_MPIEXEC") is not None:
        cand, source = os.environ["ISSM_MPIEXEC"], "$ISSM_MPIEXEC"
    else:
        cand = os.path.join(args.issm_dir, "externalpackages", "petsc", "install", "bin", "mpiexec")
        source = "ISSM_DIR PETSc MPICH"
        if not os.path.isfile(cand):
            fail([f"No MPI launcher: {cand} not found. issm.exe must be started with the MPI it "
                  f"was built with; give it with --mpiexec PATH or $ISSM_MPIEXEC."])
    if not cand or not os.path.isfile(cand) or not os.access(cand, os.X_OK):
        fail([f"MPI launcher from {source} is not an executable file: {cand!r}"])
    return os.path.abspath(cand), source


def stage_example(args):
    """Copy $ISSM_DIR/examples/<name> into the output folder and write the settings hook."""
    src = os.path.join(args.issm_dir, "examples", args.example)
    args.example_run_dir = os.path.join(args.output_dir, f"example_{args.example}")
    if os.path.exists(args.example_run_dir):
        fail([f"Example copy already exists (not overwritten): {args.example_run_dir}"])
    shutil.copytree(src, args.example_run_dir, symlinks=True)
    # runme.py files use '../Data/...' (= $ISSM_DIR/examples/Data); give the copy the same view
    data_src = os.path.join(args.issm_dir, "examples", "Data")
    data_link = os.path.join(args.output_dir, "Data")
    if os.path.isdir(data_src):
        if os.path.islink(data_link) and os.path.realpath(data_link) == os.path.realpath(data_src):
            pass
        elif os.path.lexists(data_link):
            print(f"WARNING: {data_link} exists and is not a link to {data_src}; "
                  f"example paths '../Data/...' will read it", file=sys.stderr)
        else:
            os.symlink(data_src, data_link)
    # ISSM's own user hook for the generic cluster class: only sets executionpath
    args.settings_dir = os.path.join(args.output_dir, "_issm_settings")
    os.makedirs(args.settings_dir, exist_ok=True)
    with open(os.path.join(args.settings_dir, "generic_settings.py"), "w") as f:
        f.write("def generic_settings(c):\n"
                f"    c.executionpath = {args.execution_dir!r}\n"
                "    return c\n")


def run_issm(args):
    """Execute the ISSM simulation."""
    os.makedirs(args.output_dir, exist_ok=True)
    os.makedirs(args.execution_dir, exist_ok=True)
    mpiexec, mpi_source = select_mpiexec(args)
    print(f"ISSM MPI launcher: {mpiexec} (from {mpi_source}); run files in {args.execution_dir}",
          file=sys.stderr)
    # ISSM's generic cluster writes a literal `mpiexec -np N ...` into its .queue script:
    # a private wrapper named mpiexec, first on PATH, runs exactly the selected launcher.
    wrap_dir = os.path.join(args.output_dir, "_issm_mpi")
    os.makedirs(wrap_dir, exist_ok=True)
    wrapper = os.path.join(wrap_dir, "mpiexec")
    with open(wrapper, "w") as f:
        f.write("#!/bin/sh\nexec " + shlex.quote(mpiexec) + ' "$@"\n')
    os.chmod(wrapper, 0o755)
    if args.example:
        stage_example(args)

    # Generate run script
    script_path = os.path.join(args.output_dir, "_run_issm.py")
    generate_run_script(args, script_path)

    # Build environment with ISSM paths
    env = os.environ.copy()
    issm_dir = args.issm_dir
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

    # ISSM's built Python API (bin/*.py + lib/*_python.so), as preflight_check.py issm_env()
    for sub in ("bin", "lib", "scripts"):
        path = os.path.join(issm_dir, sub)
        if os.path.isdir(path):
            python_paths.append(path)

    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = ":".join(python_paths) + (":" + existing_pythonpath if existing_pythonpath else "")

    # PATH: MPI wrapper first, then ISSM bin
    bin_dir = os.path.join(issm_dir, "bin")
    path_parts = [wrap_dir] + ([bin_dir] if os.path.isdir(bin_dir) else [])
    env["PATH"] = ":".join(path_parts) + ":" + env.get("PATH", "")

    # Add lib paths (ISSM, PETSc, Triangle), as preflight_check.py issm_env()
    lib_parts = [os.path.join(issm_dir, "lib"),
                 os.path.join(issm_dir, "externalpackages", "petsc", "install", "lib"),
                 os.path.join(issm_dir, "externalpackages", "triangle", "install", "lib")]
    lib_parts = [d for d in lib_parts if os.path.isdir(d)]
    if lib_parts:
        env["LD_LIBRARY_PATH"] = ":".join(lib_parts) + ":" + env.get("LD_LIBRARY_PATH", "")

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
    parser.add_argument("--execution_dir", default=None,
                        help="Folder for ISSM's run files (.bin/.queue/.outbin); "
                             "default <output_dir>/execution (never $ISSM_DIR/execution)")
    parser.add_argument("--mpiexec", default=None,
                        help="MPI launcher issm.exe was built with; default $ISSM_MPIEXEC, "
                             "else $ISSM_DIR/externalpackages/petsc/install/bin/mpiexec")

    args = parser.parse_args()
    normalize_paths(args)
    validate_inputs(args)
    run_issm(args)


if __name__ == "__main__":
    main()
