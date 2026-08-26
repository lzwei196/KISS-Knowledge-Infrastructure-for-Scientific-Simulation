#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
============================================
Tool ID:      s6_sensitivity_swatplus
Stage:        s6 (Calibration / Sensitivity Analysis)
Description:  Run Sobol sensitivity analysis on SWAT+ parameters via pySWATPlus.

This script is a VALIDATED TOOL: an executable that the AI agent calls
rather than writes. It guarantees correctness independent of the language
model. The agent should never modify this script -- only call it.

The tool supports two modes:
  1. Without observed data (--mode simulation): runs simulations and saves
     time series per sample. Use when you want to explore parameter effects.
  2. With observed data (--mode indices): runs simulations AND computes
     Sobol sensitivity indices (S1, ST) against observed data. Use when
     you want to rank parameters by influence on model performance.

Inputs:
  - --txtinout_dir:   Path to TxtInOut directory (required)
  - --sim_dir:        Path for sensitivity working directory (required; created if absent)
  - --params_json:    JSON file or string with parameter bounds (required)
  - --n_samples:      Sobol sample number N (generates 2^(N+1) * (D+1) samples) (default 2)
  - --max_workers:    Number of parallel workers (default 4)
  - --swat_binary:    Path to SWAT+ executable (optional)
  - --output_json:    Path to save result summary (optional)

  Simulation extraction (required):
  - --sim_output:     SWAT+ output file (default channel_sd_day.txt)
  - --sim_col:        Column in sim_output (default flo_out)
  - --filter_json:    JSON dict for filtering rows (optional)

  For --mode indices (observed data required):
  - --obs_file:       Path to observed data CSV (required if mode=indices)
  - --obs_col:        Column in obs_file (default discharge)
  - --date_format:    Date format in obs_file (default %Y-%m-%d)
  - --indicator:      Performance indicator: NSE, KGE, RMSE, MSE, MARE (default NSE)

  - --mode:           simulation or indices (default indices)

Outputs:
  - sensitivity_simulation.json (if mode=simulation)
  - sensitivity_indices.json, metric_values.json, time.json (if mode=indices)
  - Custom output JSON summary

Preconditions:
  - TxtInOut directory with valid SWAT+ project and executable
  - SALib and pySWATPlus installed

Postconditions:
  - All sample simulations completed
  - Sensitivity results saved

Usage:
  # Mode 1: Simulation only (no observed data)
  python sensitivity_swatplus.py \\
    --txtinout_dir /path/to/TxtInOut --sim_dir /path/to/sens \\
    --params_json '[{"name":"cn2","change_type":"pctchg","lower_bound":-30,"upper_bound":30}]' \\
    --n_samples 2 --mode simulation

  # Mode 2: Full sensitivity indices (with observed data)
  python sensitivity_swatplus.py \\
    --txtinout_dir /path/to/TxtInOut --sim_dir /path/to/sens \\
    --params_json params.json --obs_file obs.csv \\
    --n_samples 3 --indicator NSE --mode indices

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
        description="Sobol sensitivity analysis for SWAT+ via pySWATPlus"
    )
    parser.add_argument("--txtinout_dir", required=True)
    parser.add_argument("--sim_dir", required=True,
                        help="Working directory for sensitivity simulations")
    parser.add_argument("--params_json", required=True,
                        help="JSON file or string with parameter bounds")
    parser.add_argument("--n_samples", type=int, default=2,
                        help="Sobol sample exponent N; total = 2^(N+1)*(D+1)")
    parser.add_argument("--max_workers", type=int, default=4)
    parser.add_argument("--swat_binary", default=None)
    parser.add_argument("--output_json", default=None)
    parser.add_argument("--mode", default="indices",
                        choices=["simulation", "indices"])

    # Simulation extraction
    parser.add_argument("--sim_output", default="channel_sd_day.txt")
    parser.add_argument("--sim_col", default="flo_out")
    parser.add_argument("--filter_json", default=None)

    # Observed data (for mode=indices)
    parser.add_argument("--obs_file", default=None)
    parser.add_argument("--obs_col", default="discharge")
    parser.add_argument("--date_format", default="%Y-%m-%d")
    parser.add_argument("--indicator", default="NSE",
                        choices=["NSE", "KGE", "RMSE", "MSE", "MARE"])

    return parser.parse_args()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def parse_parameters(params_json_arg):
    """Parse parameter bounds from JSON file or string."""
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
            logger.error(f"Parameter {i} is not a dict")
            sys.exit(1)
        missing = required_keys - set(p.keys())
        if missing:
            logger.error(f"Parameter {i} missing keys: {missing}")
            sys.exit(1)
        if p['change_type'] not in valid_change_types:
            logger.error(f"Parameter {i} invalid change_type: {p['change_type']}")
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
        return False
    if len(existing_exes) > 1:
        logger.error(
            f"Multiple executables in TxtInOut: {[e.name for e in existing_exes]}"
        )
        sys.exit(1)

    if swat_binary_arg is None:
        default = Path(
            "KISSPATH_KI_ROOT/SWAT_Plus/"
            "test_rev59/swatplus_rev59"
        )
        if default.exists():
            swat_binary_arg = str(default)
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

    for fname in ['file.cio', 'time.sim', 'print.prt', 'cal_parms.cal']:
        if not (txtinout_dir / fname).exists():
            errors.append(f"Missing SWAT+ file: {fname}")

    if args.mode == "indices" and args.obs_file is None:
        errors.append(
            "--obs_file is required when --mode is 'indices'"
        )
    if args.obs_file and not Path(args.obs_file).is_file():
        errors.append(f"Observed data file not found: {args.obs_file}")

    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)

    logger.info("Input validation passed.")


def validate_outputs(sim_dir, mode):
    sim_path = Path(sim_dir).resolve()
    errors = []

    if mode == "simulation":
        if not (sim_path / 'sensitivity_simulation.json').exists():
            errors.append("sensitivity_simulation.json not found")
    elif mode == "indices":
        if not (sim_path / 'sensitivity_indices.json').exists():
            errors.append("sensitivity_indices.json not found")

    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(3)

    logger.info("Output validation passed.")


# ---------------------------------------------------------------------------
# Core processing
# ---------------------------------------------------------------------------
def process(args):
    import numpy as np
    import pySWATPlus as psp

    txtinout_dir = Path(args.txtinout_dir).resolve()
    sim_dir = Path(args.sim_dir).resolve()

    # Ensure executable
    ensure_executable_in_dir(txtinout_dir, args.swat_binary)

    # Parse parameters
    parameters = parse_parameters(args.params_json)
    n_params = len(parameters)

    # Calculate expected sample count
    n_samples_total = pow(2, args.n_samples + 1) * (n_params + 1)
    logger.info(
        f"Sobol sampling: N={args.n_samples}, D={n_params} -> "
        f"~{n_samples_total} samples (some may be deduplicated)"
    )

    # Prepare sim_dir (must be empty)
    if sim_dir.exists():
        if any(sim_dir.iterdir()):
            logger.info(f"Clearing existing sim_dir: {sim_dir}")
            shutil.rmtree(sim_dir)
            sim_dir.mkdir(parents=True)
    else:
        sim_dir.mkdir(parents=True)

    # Build extract_data
    extract_data = {
        args.sim_output: {
            'has_units': True,
            'usecols': [args.sim_col]
        }
    }
    if args.filter_json:
        try:
            apply_filter = json.loads(args.filter_json)
            extract_data[args.sim_output]['apply_filter'] = apply_filter
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse --filter_json: {e}")
            sys.exit(1)

    sa = psp.SensitivityAnalyzer()

    if args.mode == "simulation":
        # ---- Mode 1: Simulation only ----
        logger.info("Mode: simulation (no observed data)")

        sensim_output = sa.simulation_by_sample_parameters(
            parameters=parameters,
            sample_number=args.n_samples,
            sensim_dir=str(sim_dir),
            txtinout_dir=str(txtinout_dir),
            extract_data=extract_data,
            max_workers=args.max_workers,
            save_output=True,
            clean_setup=True
        )

        result = {
            "status": "success",
            "mode": "simulation",
            "n_samples_total": sensim_output['time']['sample_length'],
            "time_sec": sensim_output['time']['time_sec'],
            "time_per_sample_sec": sensim_output['time']['time_per_sample_sec'],
            "problem": {
                "num_vars": sensim_output['problem']['num_vars'],
                "names": sensim_output['problem']['names'],
            },
            "sim_dir": str(sim_dir),
            "output_file": str(sim_dir / 'sensitivity_simulation.json')
        }

    else:
        # ---- Mode 2: Simulation + Sobol indices ----
        logger.info("Mode: indices (with observed data)")

        obs_file = Path(args.obs_file).resolve()

        observe_data = {
            args.sim_output: {
                'obs_file': str(obs_file),
                'date_format': args.date_format
            }
        }

        metric_config = {
            args.sim_output: {
                'sim_col': args.sim_col,
                'obs_col': args.obs_col,
                'indicator': args.indicator
            }
        }

        # Remove usecols from extract_data -- simulation_and_indices
        # sets it internally from metric_config
        if 'usecols' in extract_data[args.sim_output]:
            del extract_data[args.sim_output]['usecols']

        sensitivity_indices = sa.simulation_and_indices(
            parameters=parameters,
            sample_number=args.n_samples,
            sensim_dir=str(sim_dir),
            txtinout_dir=str(txtinout_dir),
            extract_data=extract_data,
            observe_data=observe_data,
            metric_config=metric_config,
            max_workers=args.max_workers
        )

        # Read time stats
        time_file = sim_dir / 'time.json'
        if time_file.exists():
            with open(time_file, 'r') as f:
                time_stats = json.load(f)
        else:
            time_stats = {}

        # Read sensitivity indices JSON for structured output
        indices_file = sim_dir / 'sensitivity_indices.json'
        if indices_file.exists():
            with open(indices_file, 'r') as f:
                indices_data = json.load(f)
        else:
            indices_data = {}

        # Extract parameter names from the indices
        param_names = [p['name'] for p in parameters]

        # Build readable sensitivity summary
        sensitivity_summary = {}
        for output_key, idx_dict in indices_data.items():
            s1 = idx_dict.get('S1', [])
            st = idx_dict.get('ST', [])
            summary_params = {}
            for i, pname in enumerate(param_names):
                summary_params[pname] = {
                    "S1": round(s1[i], 4) if i < len(s1) else None,
                    "ST": round(st[i], 4) if i < len(st) else None,
                }
            sensitivity_summary[output_key] = summary_params

        result = {
            "status": "success",
            "mode": "indices",
            "indicator": args.indicator,
            "time_sec": time_stats.get('time_sec', 0),
            "n_samples_total": time_stats.get('sample_length', 0),
            "sensitivity_summary": sensitivity_summary,
            "sim_dir": str(sim_dir),
            "indices_file": str(indices_file),
            "metric_file": str(sim_dir / 'metric_values.json')
        }

    # Save output
    output_json = args.output_json or str(
        sim_dir / 'sensitivity_result.json'
    )
    with open(output_json, 'w') as f:
        json.dump(result, f, indent=2)
    logger.info(f"Saved result to: {output_json}")

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
        logger.error(f"Sensitivity analysis failed: {e}", exc_info=True)
        error_result = {
            "status": "error",
            "error": str(e),
            "sim_dir": str(Path(args.sim_dir).resolve())
        }
        print(json.dumps(error_result, indent=2))
        sys.exit(2)

    validate_outputs(result["sim_dir"], args.mode)

    print(json.dumps(result, indent=2))
    logger.info("Sensitivity analysis completed successfully.")
    sys.exit(0)
