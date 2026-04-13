#!/usr/bin/env python3
"""Execution wrapper for PorePy simulations.

This tool provides a standardized interface to run PorePy models with
preflight validation, execution monitoring, and post-run diagnostics.

CRITICAL REQUIREMENTS:
- All material properties must be in SI units
- Time scaling in pp.Units must remain 1 s (NotImplementedError otherwise)
- Gmsh must be installed and accessible
- pypardiso recommended for large systems; falls back to scipy_sparse

Usage:
    python run_porepy.py --model single_phase_flow --config config.json
    python run_porepy.py --model poromechanics --config config.json --time-dependent
    python run_porepy.py --example mandel_biot
"""

import argparse
import json
import os
import subprocess
import sys
import time
import traceback
from typing import Any, Dict, List, Optional


def validate_inputs(args: argparse.Namespace) -> List[str]:
    """Preflight checks before running PorePy.

    Validates:
    - Python environment has porepy installed
    - Config file exists and has valid structure
    - Required dependencies are available
    """
    errors = []

    # Check PorePy installation
    try:
        import porepy as pp
    except ImportError:
        errors.append(
            "PorePy not installed. Run: pip install porepy "
            "or pip install -e /path/to/porepy/source/repo"
        )

    # Check gmsh
    try:
        import gmsh
    except ImportError:
        errors.append(
            "gmsh not installed. Run: pip install gmsh. "
            "Required for mesh generation."
        )

    # Check config file
    if args.config and not os.path.isfile(args.config):
        errors.append(f"Config file not found: {args.config}")

    if args.config and os.path.isfile(args.config):
        try:
            with open(args.config) as f:
                config = json.load(f)
            # Validate required fields
            if "model_type" not in config and not args.model:
                errors.append("Config must specify 'model_type' or use --model flag")
        except json.JSONDecodeError as e:
            errors.append(f"Invalid JSON in config: {e}")

    # Check linear solver
    try:
        import pypardiso
    except ImportError:
        pass  # Not an error, will fall back to scipy

    return errors


def build_model_script(config: Dict[str, Any], model_type: str,
                       time_dependent: bool) -> str:
    """Generate a Python script to run the PorePy model.

    Returns:
        String containing executable Python code.
    """
    # Map model names to PorePy classes
    model_map = {
        "single_phase_flow": "pp.SinglePhaseFlow",
        "momentum_balance": "pp.MomentumBalance",
        "poromechanics": "pp.Poromechanics",
        "contact_mechanics": "pp.ContactMechanics",
        "thermoporomechanics": "pp.Thermoporomechanics",
    }

    model_class = model_map.get(model_type, "pp.SinglePhaseFlow")

    # Build script
    script = f'''
import numpy as np
import porepy as pp
import json
import time

# Load configuration
config = {json.dumps(config)}

# Set up units
units = pp.Units()

# Build model parameters
model_params = {{
    "units": units,
    "grid_type": config.get("grid_type", "cartesian"),
    "meshing_arguments": {{
        "cell_size": config.get("cell_size", 0.1),
    }},
    "folder_name": config.get("output_folder", "porepy_output"),
    "file_name": config.get("output_file", "results"),
}}

# Add time manager for transient problems
if {time_dependent}:
    t_end = config.get("end_time_s", 86400)
    dt = config.get("dt_s", 3600)
    model_params["time_manager"] = pp.TimeManager(
        schedule=[0, t_end],
        dt_init=dt,
        constant_dt=config.get("constant_dt", True),
    )

# Material constants
if "solid" in config:
    model_params["material_constants"] = {{
        "solid": pp.SolidConstants(**config["solid"]),
    }}
if "fluid" in config:
    if "material_constants" not in model_params:
        model_params["material_constants"] = {{}}
    model_params["material_constants"]["fluid"] = pp.FluidComponent(**config["fluid"])

# Solver parameters
solver_params = {{
    "nl_max_iterations": config.get("max_iterations", 10),
    "nl_convergence_res_atol": config.get("residual_tol", 1e-6),
    "nl_convergence_inc_atol": config.get("increment_tol", 1e-6),
}}

# Create and run model
model = {model_class}(model_params)

start = time.time()
if {time_dependent}:
    pp.run_time_dependent_model(model, solver_params)
else:
    pp.run_stationary_model(model, solver_params)
elapsed = time.time() - start

# Report
print(json.dumps({{
    "status": "success",
    "model_type": "{model_type}",
    "elapsed_s": round(elapsed, 2),
    "output_folder": config.get("output_folder", "porepy_output"),
    "time_dependent": {time_dependent},
}}))
'''
    return script


def run_example(example_name: str) -> Dict[str, Any]:
    """Run a built-in PorePy example.

    Available examples: mandel_biot, terzaghi_biot, tracer_flow
    """
    example_map = {
        "mandel_biot": "from porepy.examples.mandel_biot import MandelSetup; "
                       "import porepy as pp; "
                       "model = MandelSetup({}); "
                       "pp.run_time_dependent_model(model, {})",
        "terzaghi_biot": "from porepy.examples.terzaghi_biot import TerzaghiSetup; "
                         "import porepy as pp; "
                         "model = TerzaghiSetup({}); "
                         "pp.run_time_dependent_model(model, {})",
        "tracer_flow": "from porepy.examples.tracer_flow import TracerFlowSetup; "
                       "import porepy as pp; "
                       "model = TracerFlowSetup({}); "
                       "pp.run_time_dependent_model(model, {})",
    }

    if example_name not in example_map:
        return {
            "status": "error",
            "error": f"Unknown example '{example_name}'. "
                     f"Available: {list(example_map.keys())}",
        }

    cmd = [sys.executable, "-c", example_map[example_name]]
    start = time.time()
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=600
        )
        elapsed = time.time() - start
        return {
            "status": "success" if result.returncode == 0 else "error",
            "example": example_name,
            "elapsed_s": round(elapsed, 2),
            "stdout": result.stdout[:2000],
            "stderr": result.stderr[:2000],
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": "Execution timed out (600s)"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def process(args: argparse.Namespace) -> Dict[str, Any]:
    """Main execution logic."""

    # Run built-in example
    if args.example:
        return run_example(args.example)

    # Load config
    config = {}
    if args.config:
        with open(args.config) as f:
            config = json.load(f)

    model_type = args.model or config.get("model_type", "single_phase_flow")
    time_dep = args.time_dependent or config.get("time_dependent", False)

    # Generate and run script
    script = build_model_script(config, model_type, time_dep)

    # Write temp script
    script_path = "/tmp/porepy_run.py"
    with open(script_path, "w") as f:
        f.write(script)

    start = time.time()
    try:
        result = subprocess.run(
            [sys.executable, script_path],
            capture_output=True, text=True, timeout=600,
            cwd=args.work_dir or os.getcwd(),
        )
        elapsed = time.time() - start

        return {
            "status": "success" if result.returncode == 0 else "error",
            "model_type": model_type,
            "time_dependent": time_dep,
            "elapsed_s": round(elapsed, 2),
            "stdout": result.stdout[:2000],
            "stderr": result.stderr[:2000],
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": "Execution timed out (600s)"}
    except Exception as e:
        return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}


def validate_outputs(result: Dict[str, Any]) -> List[str]:
    """Post-run validation of model outputs."""
    warnings = []

    if result.get("status") == "error":
        stderr = result.get("stderr", "")
        if "NotImplementedError" in stderr and "time scaling" in stderr:
            warnings.append(
                "CRITICAL: Time unit scaling is not 1 second. "
                "PorePy requires pp.Units(s=1). Remove time scaling."
            )
        if "gmsh" in stderr.lower():
            warnings.append(
                "Gmsh error detected. Check fracture geometry for "
                "degeneracies or intersections outside domain."
            )
        if "Singular matrix" in stderr or "singular" in stderr.lower():
            warnings.append(
                "Singular matrix error. Check boundary conditions — "
                "pure Neumann without constraint causes singular system."
            )
        if "NaN" in stderr:
            warnings.append(
                "NaN detected in solution. Likely Newton divergence. "
                "Try smaller time step or relaxation."
            )

    return warnings


def main():
    parser = argparse.ArgumentParser(
        description="Run PorePy simulations with preflight validation.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--model", help="Model type to run",
                        choices=["single_phase_flow", "momentum_balance",
                                 "poromechanics", "contact_mechanics",
                                 "thermoporomechanics"])
    parser.add_argument("--config", help="JSON configuration file")
    parser.add_argument("--example", help="Run built-in example",
                        choices=["mandel_biot", "terzaghi_biot", "tracer_flow"])
    parser.add_argument("--time-dependent", action="store_true",
                        help="Run as time-dependent simulation")
    parser.add_argument("--work-dir", help="Working directory for execution")
    args = parser.parse_args()

    # Validate
    errors = validate_inputs(args)
    if errors:
        print(json.dumps({"status": "error", "errors": errors}, indent=2))
        sys.exit(1)

    # Run
    result = process(args)

    # Post-validate
    warnings = validate_outputs(result)
    result["warnings"] = warnings

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
