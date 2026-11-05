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

Engine Python: the tool itself may be started with any Python (e.g. python_env,
which has no porepy); the PorePy runs use --porepy-python, else $POREPY_PYTHON,
else the server PorePy venv (the same one preflight_check.py uses). An explicit
value that is empty or cannot import porepy + gmsh is an error (no fallback).

--example runs PorePy's own benchmark presets (official setups, see EXAMPLES)
and reports their numbers in "example_results".
Exit code: 0 only when the run succeeded; 1 otherwise (JSON is printed first).
"""

import argparse
import json
import os
import math
import subprocess
import sys
import tempfile
import time
import traceback
from typing import Any, Dict, List, Optional, Tuple


# Server PorePy engine (same default as preflight_check.py); python_env has no porepy.
DEFAULT_POREPY_PYTHON = (
    "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/PorePy/venv/bin/python"
)
IMPORT_PROBE_TIMEOUT_S = 300
RESULT_PREFIX = "POREPY_EXAMPLE_RESULTS="


def resolve_porepy_python(cli_value: Optional[str]) -> Tuple[Optional[str], str]:
    """--porepy-python, else $POREPY_PYTHON, else the server default venv.

    Returns (path or None, source). An explicit empty value gives None (error).
    The path is made absolute but symlinks are kept (a venv python must be run
    by its own path).
    """
    if cli_value is not None:
        value, source = cli_value, "--porepy-python"
    elif os.environ.get("POREPY_PYTHON") is not None:
        value, source = os.environ["POREPY_PYTHON"], "POREPY_PYTHON"
    else:
        value, source = DEFAULT_POREPY_PYTHON, "server default"
    if not value.strip():
        return None, source
    return os.path.abspath(value), source


def validate_inputs(args: argparse.Namespace) -> List[str]:
    """Preflight checks before running PorePy.

    Validates:
    - the engine Python exists and imports porepy and gmsh
    - Config file exists and has valid structure
    """
    errors = []

    # Check the engine Python (porepy + gmsh) — the runs use this interpreter
    py = args.porepy_python
    if py is None:
        errors.append(f"PorePy Python is set but empty (from {args.porepy_python_source}).")
    elif not (os.path.isfile(py) and os.access(py, os.X_OK)):
        errors.append(f"PorePy Python not found or not executable: {py} "
                      f"(from {args.porepy_python_source}).")
    else:
        try:
            probe = subprocess.run(
                [py, "-c", "import porepy, gmsh; print(porepy.__version__)"],
                capture_output=True, text=True, errors="replace",
                timeout=IMPORT_PROBE_TIMEOUT_S,
            )
            if probe.returncode != 0:
                last = (probe.stderr.strip().splitlines() or ["?"])[-1]
                errors.append(
                    f"PorePy Python {py} (from {args.porepy_python_source}) cannot "
                    f"import porepy and gmsh: {last}. Set --porepy-python or "
                    f"POREPY_PYTHON to a Python with porepy + gmsh "
                    f"(server default {DEFAULT_POREPY_PYTHON})."
                )
            else:
                args.porepy_version = probe.stdout.strip()
        except Exception as e:
            errors.append(f"PorePy Python {py} import check failed: {e}")

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


# Official PorePy benchmark presets for --example (porepy 1.12):
#  mandel_biot   = tests/functional/test_mandel.py `results` fixture
#  terzaghi_biot = tests/functional/test_terzaghi.py::test_pressure_and_consolidation_degree_errors
#  tracer_flow   = the `if __name__ == "__main__":` block of porepy/examples/tracer_flow.py
#                  (same params; plotting left out)
_EXAMPLE_HEAD = """
import dataclasses, json, time
import numpy as np
import porepy as pp
_t0 = time.time()
"""

EXAMPLES = {
    "mandel_biot": _EXAMPLE_HEAD + """
from porepy.examples.mandel_biot import (
    MandelModel, mandel_fluid_constants, mandel_solid_constants)
END_TIME = 50.0
params = {
    "material_constants": {
        "fluid": pp.FluidComponent(**mandel_fluid_constants),
        "solid": pp.SolidConstants(**mandel_solid_constants),
    },
    "time_manager": pp.TimeManager([0, 25, 50], 25, True),
    "times_to_export": [],
}
model = MandelModel(params)
pp.run_time_dependent_model(model)
""",
    "terzaghi_biot": _EXAMPLE_HEAD + """
from porepy.examples.terzaghi_biot import (
    TerzaghiModel, terzaghi_fluid_constants, terzaghi_solid_constants)
END_TIME = 0.3
params = {
    "material_constants": {
        "solid": pp.SolidConstants(**terzaghi_solid_constants),
        "fluid": pp.FluidComponent(**terzaghi_fluid_constants),
    },
    "time_manager": pp.TimeManager([0, 0.15, 0.3], 0.15, True),
    "num_cells": 10,
    "times_to_export": [],
}
model = TerzaghiModel(params)
pp.run_time_dependent_model(model)
""",
    "tracer_flow": _EXAMPLE_HEAD + """
from porepy.examples.tracer_flow import TracerFlowModel
dt_init = pp.MINUTE
T_end = 20 * pp.MINUTE
END_TIME = float(T_end)
dt_min_max = (0.1 * dt_init, 10 * pp.MINUTE)
max_iterations = 80
newton_tol = 1e-6
newton_tol_increment = newton_tol
time_manager = pp.TimeManager(
    schedule=[0, T_end],
    dt_init=dt_init,
    dt_min_max=dt_min_max,
    iter_max=max_iterations,
    iter_optimal_range=(2, 10),
    iter_relax_factors=(0.8, 1.2),
    recomp_factor=0.8,
    recomp_max=5,
)
params = {
    "material_constants": {
        "solid": pp.SolidConstants(
            porosity=0.1, permeability=1e-7, normal_permeability=1e-19
        ),
    },
    "fracture_indices": [0, 1],
    "eliminate_reference_phase": True,
    "eliminate_reference_component": True,
    "time_manager": time_manager,
    "nl_max_iterations": max_iterations,
    "nl_convergence_inc_atol": newton_tol_increment,
    "nl_convergence_res_atol": newton_tol,
    "meshing_arguments": {"cell_size": 0.05},
    "grid_type": "simplex",
}
model = TracerFlowModel(params)
pp.run_time_dependent_model(model, params)
""",
}

# Common tail: collect numbers and print ONE prefixed JSON line.
_EXAMPLE_TAIL = """
def _scalar(v):
    if isinstance(v, (bool, np.bool_)):
        return None
    if isinstance(v, (int, float, np.integer, np.floating)):
        return float(v)
    if isinstance(v, (tuple, list)) and v and all(
            isinstance(x, (int, float, np.integer, np.floating)) for x in v):
        return [float(x) for x in v]
    return None

rec = {
    "porepy_version": pp.__version__,
    "final_time": float(model.time_manager.time),
    "end_time": END_TIME,
    "n_cells": int(sum(sd.num_cells for sd in model.mdg.subdomains())),
    "n_subdomains": len(model.mdg.subdomains()),
}
results = []
for r in getattr(model, "results", []) or []:
    if dataclasses.is_dataclass(r):
        row = {}
        for f in dataclasses.fields(r):
            v = _scalar(getattr(r, f.name))
            if v is not None:
                row[f.name] = v
        results.append(row)
if results:
    rec["results"] = results
fields = {}
for var in model.equation_system.variables:
    if var.name in ("pressure", "z_tracer"):
        vals = np.asarray(model.equation_system.get_variable_values(
            variables=[var], time_step_index=0))
        if vals.size:
            f = fields.setdefault(var.name, {"n_values": 0, "n_nonfinite": 0})
            ok = np.isfinite(vals)
            f["n_values"] += int(vals.size)
            f["n_nonfinite"] += int((~ok).sum())
            if ok.any():
                lo, hi = float(vals[ok].min()), float(vals[ok].max())
                f["min"] = lo if "min" not in f else min(lo, f["min"])
                f["max"] = hi if "max" not in f else max(hi, f["max"])
if fields and not results:
    rec["fields"] = fields
rec["elapsed_s"] = round(time.time() - _t0, 2)
print(%r + json.dumps(rec))
"""


def _all_finite(obj: Any) -> bool:
    if isinstance(obj, dict):
        return all(_all_finite(v) for v in obj.values())
    if isinstance(obj, list):
        return all(_all_finite(v) for v in obj)
    if isinstance(obj, float):
        return math.isfinite(obj)
    return True


def _is_num(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _check_example_record(stdout: str) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    """Find the result line in the FULL stdout and check it."""
    lines = [l for l in stdout.splitlines() if l.startswith(RESULT_PREFIX)]
    if len(lines) != 1:
        return None, [f"expected one '{RESULT_PREFIX}' line in the engine output, found {len(lines)}"]
    try:
        rec = json.loads(lines[0][len(RESULT_PREFIX):])
    except json.JSONDecodeError as e:
        return None, [f"malformed result line: {e}"]
    problems = []
    if not _all_finite(rec):
        problems.append("result contains non-finite numbers")
    end = rec.get("end_time")
    ft = rec.get("final_time")
    if not isinstance(end, (int, float)) or not isinstance(ft, (int, float)) \
            or abs(ft - end) > 1e-9 * max(1.0, abs(end)):
        problems.append(f"run did not reach the end time: final_time={ft}, end_time={end}")
    results = rec.get("results")
    fields = rec.get("fields")
    if not results and not fields:
        problems.append("no result numbers (results/fields) in the engine output")
    if results is not None:
        if not isinstance(results, list) or not all(
                isinstance(r, dict) and _is_num(r.get("time")) and any(
                    k.startswith("error_") and (_is_num(v) or (
                        isinstance(v, list) and v and all(_is_num(x) for x in v)))
                    for k, v in r.items())
                for r in results):
            problems.append("results rows must each have a finite time and finite error_* values")
    if fields is not None:
        if not isinstance(fields, dict) or not fields or not all(
                isinstance(f, dict) and _is_num(f.get("min")) and _is_num(f.get("max"))
                and f.get("n_nonfinite") == 0 and isinstance(f.get("n_values"), int)
                and f["n_values"] > 0
                for f in fields.values()):
            problems.append("fields must each have finite min/max over all values "
                            "(no NaN/Inf in the solution)")
    return rec, problems


def run_example(example_name: str, python: str = sys.executable,
                work_dir: Optional[str] = None) -> Dict[str, Any]:
    """Run a built-in PorePy example with its official preset.

    Available examples: mandel_biot, terzaghi_biot, tracer_flow
    """
    if example_name not in EXAMPLES:
        return {
            "status": "error",
            "error": f"Unknown example '{example_name}'. "
                     f"Available: {list(EXAMPLES.keys())}",
        }

    script = EXAMPLES[example_name] + (_EXAMPLE_TAIL % RESULT_PREFIX)
    fd, script_path = tempfile.mkstemp(prefix=f"porepy_{example_name}_", suffix=".py")
    with os.fdopen(fd, "w") as f:
        f.write(script)
    start = time.time()
    try:
        result = subprocess.run(
            [python, script_path], capture_output=True, text=True, errors="replace",
            timeout=600, cwd=work_dir or os.getcwd(),
        )
        elapsed = time.time() - start
        out = {
            "status": "success" if result.returncode == 0 else "error",
            "example": example_name,
            "elapsed_s": round(elapsed, 2),
            "stdout": result.stdout[:2000],
            "stderr": result.stderr[:2000],
            "returncode": result.returncode,
        }
        if result.returncode == 0:
            rec, problems = _check_example_record(result.stdout)
            if rec is not None:
                out["example_results"] = rec
            if problems:
                out["status"] = "error"
                out["error"] = "; ".join(problems)
        return out
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": "Execution timed out (600s)"}
    except Exception as e:
        return {"status": "error", "error": str(e)}
    finally:
        try:
            os.unlink(script_path)
        except OSError:
            pass


def process(args: argparse.Namespace) -> Dict[str, Any]:
    """Main execution logic."""

    # Run built-in example
    if args.example:
        return run_example(args.example, args.porepy_python, args.work_dir)

    # Load config
    config = {}
    if args.config:
        with open(args.config) as f:
            config = json.load(f)

    model_type = args.model or config.get("model_type", "single_phase_flow")
    time_dep = args.time_dependent or config.get("time_dependent", False)

    # Generate and run script
    script = build_model_script(config, model_type, time_dep)

    # Write temp script (unique name; removed after the run)
    fd, script_path = tempfile.mkstemp(prefix="porepy_run_", suffix=".py")
    with os.fdopen(fd, "w") as f:
        f.write(script)

    start = time.time()
    try:
        result = subprocess.run(
            [args.porepy_python, script_path],
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
    finally:
        try:
            os.unlink(script_path)
        except OSError:
            pass


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
    parser.add_argument("--porepy-python", default=None,
                        help="Python with porepy + gmsh used for the runs "
                             "(default: $POREPY_PYTHON, else " + DEFAULT_POREPY_PYTHON + ")")
    args = parser.parse_args()
    args.porepy_python, args.porepy_python_source = resolve_porepy_python(args.porepy_python)
    args.porepy_version = None
    if args.work_dir:
        args.work_dir = os.path.abspath(args.work_dir)

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
    result["porepy_python"] = args.porepy_python
    result["porepy_python_source"] = args.porepy_python_source
    result["porepy_version"] = args.porepy_version

    print(json.dumps(result, indent=2))
    if result.get("status") != "success":
        sys.exit(1)


if __name__ == "__main__":
    main()
