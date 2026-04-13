#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
============================================
Tool ID:      s6_calibrate_swatplus
Stage:        s6 (Calibration)
Description:  Run SWAT+ calibration using pySWATPlus multi-objective optimization (pymoo).

This script is a VALIDATED TOOL: an executable that the AI agent calls
rather than writes. It guarantees correctness independent of the language
model. The agent should never modify this script -- only call it.

Inputs:
  - --txtinout_dir:   Path to TxtInOut directory with SWAT+ binary (required)
  - --cal_dir:        Path for calibration working directory (required; created if absent)
  - --obs_file:       Path to observed data CSV (required; must have 'date' column)
  - --params_json:    JSON file or inline JSON with parameter bounds (required)
  - --n_gen:          Number of generations (default 50)
  - --pop_size:       Population size per generation (default 20)
  - --objective:      Objective function: NSE, KGE, RMSE, MSE, MARE (default NSE)
  - --sim_output:     SWAT+ output file to extract (default channel_sd_day.txt)
  - --sim_col:        Column name in sim_output for simulated values (default flo_out)
  - --obs_col:        Column name in obs_file for observed values (default discharge)
  - --date_format:    Date format in obs_file (default %Y-%m-%d)
  - --filter_json:    JSON dict for filtering sim output rows (optional)
  - --max_workers:    Number of parallel workers (default 4)
  - --algorithm:      Optimization algorithm: GA, DE, NSGA2 (default NSGA2)
  - --swat_binary:    Path to SWAT+ executable (optional; auto-detects)
  - --output_json:    Path to save result JSON (optional; defaults to cal_dir/calibration_result.json)

Outputs:
  - optimization_history.json in cal_dir
  - optimization_result.json in cal_dir
  - Custom output JSON with best parameters and metrics

Preconditions:
  - TxtInOut directory with valid SWAT+ project and executable
  - Observed data CSV with date column
  - pySWATPlus and pymoo installed

Postconditions:
  - Best parameter set identified
  - Result files saved to cal_dir

Usage:
  python calibrate_swatplus.py \\
    --txtinout_dir /path/to/TxtInOut \\
    --cal_dir /path/to/cal_workspace \\
    --obs_file /path/to/observed.csv \\
    --params_json '[{"name":"cn2","change_type":"pctchg","lower_bound":-30,"upper_bound":30}]' \\
    --n_gen 50 --pop_size 20 --objective NSE --max_workers 4

Exit codes:
  0 -- success
  1 -- input validation failed
  2 -- processing error
  3 -- output validation failed
"""

import sys
import os
import json
import shutil
import logging
import argparse
from pathlib import Path

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stderr
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
def parse_args():
    parser = argparse.ArgumentParser(
        description="Calibrate SWAT+ model parameters via pySWATPlus + pymoo"
    )
    parser.add_argument("--txtinout_dir", required=True)
    parser.add_argument("--cal_dir", required=True)
    parser.add_argument("--obs_file", required=True,
                        help="CSV with 'date' column and observed values")
    parser.add_argument("--params_json", required=True,
                        help="JSON file or string with parameter bounds")
    parser.add_argument("--n_gen", type=int, default=50)
    parser.add_argument("--pop_size", type=int, default=20)
    parser.add_argument("--objective", default="NSE",
                        choices=["NSE", "KGE", "RMSE", "MSE", "MARE"])
    parser.add_argument("--sim_output", default="channel_sd_day.txt",
                        help="SWAT+ output file to compare against obs")
    parser.add_argument("--sim_col", default="flo_out",
                        help="Column in sim_output with simulated values")
    parser.add_argument("--obs_col", default="discharge",
                        help="Column in obs_file with observed values")
    parser.add_argument("--date_format", default="%Y-%m-%d",
                        help="Date format in obs_file")
    parser.add_argument("--filter_json", default=None,
                        help="JSON dict for filtering sim rows, "
                             "e.g. '{\"gis_id\": [1]}'")
    parser.add_argument("--max_workers", type=int, default=4)
    parser.add_argument("--algorithm", default="NSGA2",
                        choices=["GA", "DE", "NSGA2"])
    parser.add_argument("--swat_binary", default=None)
    parser.add_argument("--output_json", default=None)
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def parse_parameters(params_json_arg):
    """Parse calibration parameter bounds from JSON file or string."""
    params_json_arg = params_json_arg.strip()

    if os.path.isfile(params_json_arg):
        logger.info(f"Reading parameters from file: {params_json_arg}")
        with open(params_json_arg, 'r') as f:
            params = json.load(f)
    else:
        try:
            params = json.loads(params_json_arg)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse params_json: {e}")
            sys.exit(1)

    if not isinstance(params, list) or len(params) == 0:
        logger.error("params_json must be a non-empty JSON array")
        sys.exit(1)

    required_keys = {'name', 'change_type', 'lower_bound', 'upper_bound'}
    valid_change_types = {'absval', 'abschg', 'pctchg'}

    for i, p in enumerate(params):
        if not isinstance(p, dict):
            logger.error(f"Parameter {i} is not a dict: {p}")
            sys.exit(1)
        missing = required_keys - set(p.keys())
        if missing:
            logger.error(f"Parameter {i} missing keys: {missing}")
            sys.exit(1)
        if p['change_type'] not in valid_change_types:
            logger.error(
                f"Parameter {i} invalid change_type: {p['change_type']}"
            )
            sys.exit(1)
        p['lower_bound'] = float(p['lower_bound'])
        p['upper_bound'] = float(p['upper_bound'])
        if p['upper_bound'] <= p['lower_bound']:
            logger.error(
                f"Parameter {i} ({p['name']}): upper_bound must > lower_bound"
            )
            sys.exit(1)

    return params


def ensure_executable_in_dir(txtinout_dir, swat_binary_arg):
    """Ensure exactly one ELF executable exists in TxtInOut dir."""
    txtinout_path = Path(txtinout_dir).resolve()

    existing_exes = []
    for f in txtinout_path.iterdir():
        if f.is_file() and os.access(f, os.X_OK):
            try:
                with open(f, 'rb') as fh:
                    if fh.read(4) == b'\x7fELF':
                        existing_exes.append(f)
            except OSError:
                pass

    if len(existing_exes) == 1:
        logger.info(f"Found SWAT+ executable: {existing_exes[0].name}")
        return False

    if len(existing_exes) > 1:
        logger.error(
            f"Multiple executables in TxtInOut: {[e.name for e in existing_exes]}"
        )
        sys.exit(1)

    # No executable -- try to link one
    if swat_binary_arg is None:
        default = Path(
            "/mnt/disk1/Hydrocraft_server/models/SWAT_Plus/"
            "test_rev59/swatplus_rev59"
        )
        if default.exists():
            swat_binary_arg = str(default)
            logger.info(f"Using default SWAT+ binary: {swat_binary_arg}")
        else:
            logger.error("No executable in TxtInOut and no --swat_binary given")
            sys.exit(1)

    binary_path = Path(swat_binary_arg).resolve()
    if not binary_path.exists() or not os.access(binary_path, os.X_OK):
        logger.error(f"SWAT+ binary not found or not executable: {binary_path}")
        sys.exit(1)

    link_path = txtinout_path / binary_path.name
    if link_path.exists():
        link_path.unlink()
    link_path.symlink_to(binary_path)
    logger.info(f"Created symlink: {link_path.name} -> {binary_path}")
    return True


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def validate_inputs(args):
    errors = []

    txtinout_dir = Path(args.txtinout_dir).resolve()
    if not txtinout_dir.is_dir():
        errors.append(f"TxtInOut directory not found: {txtinout_dir}")

    obs_file = Path(args.obs_file).resolve()
    if not obs_file.is_file():
        errors.append(f"Observed data file not found: {obs_file}")

    for fname in ['file.cio', 'time.sim', 'print.prt', 'cal_parms.cal']:
        if not (txtinout_dir / fname).exists():
            errors.append(f"Missing SWAT+ file: {fname}")

    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)

    logger.info("Input validation passed.")


def validate_outputs(cal_dir):
    cal_path = Path(cal_dir).resolve()
    errors = []

    result_file = cal_path / 'optimization_result.json'
    history_file = cal_path / 'optimization_history.json'

    if not result_file.exists():
        errors.append(f"optimization_result.json not found in {cal_path}")
    if not history_file.exists():
        errors.append(f"optimization_history.json not found in {cal_path}")

    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(3)

    logger.info("Output validation passed.")


# ---------------------------------------------------------------------------
# Core processing
# ---------------------------------------------------------------------------
def process(args):
    import pySWATPlus as psp

    txtinout_dir = Path(args.txtinout_dir).resolve()
    cal_dir = Path(args.cal_dir).resolve()
    obs_file = Path(args.obs_file).resolve()

    # Ensure executable
    ensure_executable_in_dir(txtinout_dir, args.swat_binary)

    # Parse parameters
    parameters = parse_parameters(args.params_json)

    # Prepare cal_dir (must exist and be empty for pySWATPlus)
    if cal_dir.exists():
        if any(cal_dir.iterdir()):
            logger.info(f"Clearing existing cal_dir: {cal_dir}")
            shutil.rmtree(cal_dir)
            cal_dir.mkdir(parents=True)
    else:
        cal_dir.mkdir(parents=True)

    # Build extract_data config
    extract_data = {
        args.sim_output: {
            'has_units': True
        }
    }

    # Add filter if provided
    if args.filter_json:
        try:
            apply_filter = json.loads(args.filter_json)
            extract_data[args.sim_output]['apply_filter'] = apply_filter
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse --filter_json: {e}")
            sys.exit(1)

    # Build observe_data config
    observe_data = {
        args.sim_output: {
            'obs_file': str(obs_file),
            'date_format': args.date_format
        }
    }

    # Build objective_config
    objective_config = {
        args.sim_output: {
            'sim_col': args.sim_col,
            'obs_col': args.obs_col,
            'indicator': args.objective
        }
    }

    logger.info(
        f"Starting calibration: {args.algorithm}, "
        f"{args.n_gen} generations x {args.pop_size} pop_size = "
        f"{args.n_gen * args.pop_size} total simulations"
    )
    logger.info(f"Objective: {args.objective} on {args.sim_col} vs {args.obs_col}")
    logger.info(f"Parameters: {[p['name'] for p in parameters]}")

    # Initialize Calibration
    cal = psp.Calibration(
        parameters=parameters,
        calsim_dir=str(cal_dir),
        txtinout_dir=str(txtinout_dir),
        extract_data=extract_data,
        observe_data=observe_data,
        objective_config=objective_config,
        algorithm=args.algorithm,
        n_gen=args.n_gen,
        pop_size=args.pop_size,
        max_workers=args.max_workers
    )

    # Run optimization
    opt_result = cal.parameter_optimization()

    # Process results
    var_names = cal.var_names
    variables = opt_result['variables']
    objectives = opt_result['objectives']

    # Handle single vs multi-objective results
    if variables.ndim == 1:
        # Single solution
        best_params = {
            var_names[i]: float(variables[i])
            for i in range(len(var_names))
        }
        best_objectives = {args.objective: float(objectives[0])}
    else:
        # Pareto front -- pick the best for the primary objective
        # For maximize (NSE, KGE): pick highest; for minimize: pick lowest
        maximize_indicators = {'NSE', 'KGE'}
        if args.objective in maximize_indicators:
            best_idx = objectives[:, 0].argmax()
        else:
            best_idx = objectives[:, 0].argmin()
        best_vars = variables[best_idx]
        best_params = {
            var_names[i]: float(best_vars[i])
            for i in range(len(var_names))
        }
        best_objectives = {args.objective: float(objectives[best_idx, 0])}

    result = {
        "status": "success",
        "algorithm": args.algorithm,
        "n_gen": args.n_gen,
        "pop_size": args.pop_size,
        "total_simulations": opt_result['total_simulation'],
        "time_sec": opt_result['time_sec'],
        "objective": args.objective,
        "best_objective_value": best_objectives[args.objective],
        "best_parameters": best_params,
        "cal_dir": str(cal_dir),
        "result_file": str(cal_dir / 'optimization_result.json'),
        "history_file": str(cal_dir / 'optimization_history.json')
    }

    # Save custom output
    output_json = args.output_json or str(
        cal_dir / 'calibration_result.json'
    )
    with open(output_json, 'w') as f:
        json.dump(result, f, indent=2)
    logger.info(f"Saved calibration result to: {output_json}")

    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    args = parse_args()

    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs(args)

    try:
        result = process(args)
    except Exception as e:
        logger.error(f"Calibration failed: {e}", exc_info=True)
        error_result = {
            "status": "error",
            "error": str(e),
            "cal_dir": str(Path(args.cal_dir).resolve())
        }
        print(json.dumps(error_result, indent=2))
        sys.exit(2)

    validate_outputs(result["cal_dir"])

    print(json.dumps(result, indent=2))
    logger.info("Calibration completed successfully.")
    sys.exit(0)
