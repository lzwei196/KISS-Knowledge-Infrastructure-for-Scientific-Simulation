#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
============================================
Tool ID:      s8_run_swatplus_with_params
Stage:        s8 (Model Execution)
Description:  Run SWAT+ simulation with user-specified parameter changes via pySWATPlus.

This script is a VALIDATED TOOL: an executable that the AI agent calls
rather than writes. It guarantees correctness independent of the language
model. The agent should never modify this script -- only call it.

Inputs:
  - --txtinout_dir:   Path to TxtInOut directory (required)
  - --sim_dir:        Path for simulation output (required; created if absent)
  - --params_json:    JSON file or inline JSON string with parameter list (optional)
  - --start_date:     Simulation start date DD-Mon-YYYY (optional)
  - --end_date:       Simulation end date DD-Mon-YYYY (optional)
  - --warmup_years:   Number of warmup years (optional, default 2)
  - --swat_binary:    Path to SWAT+ executable (optional; auto-detects if already in TxtInOut)
  - --print_objects:  Comma-separated list of objects to enable daily output for (optional)

Outputs:
  - SWAT+ simulation outputs in sim_dir
  - JSON summary to stdout: {status, sim_dir, outputs, parameters_applied}

Preconditions:
  - TxtInOut directory exists with all required SWAT+ input files
  - pySWATPlus installed in environment

Postconditions:
  - Simulation completes successfully (SWAT+ exit code 0)
  - Output files exist in sim_dir

Usage:
  python run_swatplus_with_params.py --txtinout_dir /path/to/TxtInOut --sim_dir /path/to/sim \\
    --params_json '[{"name":"cn2","change_type":"pctchg","value":-15}]' \\
    --start_date 01-Jan-2002 --end_date 31-Dec-2010 --warmup_years 2 \\
    --swat_binary /path/to/swatplus_rev59

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
        description="Run SWAT+ simulation with parameter changes via pySWATPlus"
    )
    parser.add_argument(
        "--txtinout_dir", required=True,
        help="Path to TxtInOut directory with SWAT+ input files"
    )
    parser.add_argument(
        "--sim_dir", required=True,
        help="Path for simulation output directory (created if absent)"
    )
    parser.add_argument(
        "--params_json", default=None,
        help="JSON file path or inline JSON string with parameter list. "
             "Each entry: {name, change_type (absval|abschg|pctchg), value, "
             "[units], [conditions]}"
    )
    parser.add_argument(
        "--start_date", default=None,
        help="Simulation start date in DD-Mon-YYYY format (e.g., 01-Jan-2002)"
    )
    parser.add_argument(
        "--end_date", default=None,
        help="Simulation end date in DD-Mon-YYYY format (e.g., 31-Dec-2010)"
    )
    parser.add_argument(
        "--warmup_years", type=int, default=None,
        help="Number of warmup years (default: use existing value in print.prt)"
    )
    parser.add_argument(
        "--swat_binary", default=None,
        help="Path to SWAT+ executable. If the TxtInOut dir already has one, "
             "this is optional."
    )
    parser.add_argument(
        "--print_objects", default=None,
        help="Comma-separated list of objects to enable daily output for "
             "(e.g., 'channel_sd,basin_wb')"
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def parse_parameters(params_json_arg):
    """Parse parameters from JSON file path or inline JSON string."""
    if params_json_arg is None:
        return None

    params_json_arg = params_json_arg.strip()

    # Try as file path first
    if os.path.isfile(params_json_arg):
        logger.info(f"Reading parameters from file: {params_json_arg}")
        with open(params_json_arg, 'r') as f:
            params = json.load(f)
    else:
        # Try as inline JSON string
        try:
            params = json.loads(params_json_arg)
        except json.JSONDecodeError as e:
            logger.error(
                f"Failed to parse params_json as file or JSON string: {e}"
            )
            sys.exit(1)

    if not isinstance(params, list):
        logger.error("params_json must be a JSON array of parameter dicts")
        sys.exit(1)

    # Validate each parameter dict
    required_keys = {'name', 'change_type', 'value'}
    valid_change_types = {'absval', 'abschg', 'pctchg'}
    for i, p in enumerate(params):
        if not isinstance(p, dict):
            logger.error(f"Parameter {i} is not a dict: {p}")
            sys.exit(1)
        missing = required_keys - set(p.keys())
        if missing:
            logger.error(
                f"Parameter {i} missing required keys: {missing}. Got: {p}"
            )
            sys.exit(1)
        if p['change_type'] not in valid_change_types:
            logger.error(
                f"Parameter {i} has invalid change_type '{p['change_type']}'. "
                f"Must be one of {valid_change_types}"
            )
            sys.exit(1)
        # Ensure value is numeric
        try:
            p['value'] = float(p['value'])
        except (ValueError, TypeError):
            logger.error(
                f"Parameter {i} 'value' must be numeric, got: {p['value']}"
            )
            sys.exit(1)

    return params


def ensure_executable_in_dir(txtinout_dir, swat_binary_arg):
    """
    pySWATPlus requires exactly one ELF executable in the TxtInOut directory.
    If none exists, create a symlink from the provided binary path.
    Returns True if a symlink was created (and should be cleaned up).
    """
    txtinout_path = Path(txtinout_dir).resolve()

    # Check for existing executables (ELF binaries with +x)
    existing_exes = []
    for f in txtinout_path.iterdir():
        if f.is_file() and os.access(f, os.X_OK):
            try:
                with open(f, 'rb') as fh:
                    header = fh.read(4)
                if header == b'\x7fELF':
                    existing_exes.append(f)
            except OSError:
                pass

    if len(existing_exes) == 1:
        logger.info(f"Found existing SWAT+ executable: {existing_exes[0].name}")
        return False  # No cleanup needed

    if len(existing_exes) > 1:
        logger.error(
            f"Multiple executables found in TxtInOut: "
            f"{[e.name for e in existing_exes]}. "
            f"pySWATPlus requires exactly one."
        )
        sys.exit(1)

    # No executable found -- need to create a symlink
    if swat_binary_arg is None:
        # Try default location
        default_binary = Path(
            "KISSPATH_KI_ROOT/SWAT_Plus/"
            "test_rev59/swatplus_rev59"
        )
        if default_binary.exists():
            swat_binary_arg = str(default_binary)
            logger.info(
                f"No --swat_binary provided; using default: {swat_binary_arg}"
            )
        else:
            logger.error(
                "No executable found in TxtInOut and no --swat_binary provided. "
                "Provide --swat_binary /path/to/swatplus"
            )
            sys.exit(1)

    binary_path = Path(swat_binary_arg).resolve()
    if not binary_path.exists():
        logger.error(f"SWAT+ binary not found: {binary_path}")
        sys.exit(1)

    if not os.access(binary_path, os.X_OK):
        logger.error(f"SWAT+ binary is not executable: {binary_path}")
        sys.exit(1)

    # Create symlink in TxtInOut dir
    link_path = txtinout_path / binary_path.name
    if link_path.exists():
        link_path.unlink()
    link_path.symlink_to(binary_path)
    logger.info(
        f"Created symlink: {link_path.name} -> {binary_path}"
    )
    return True  # Cleanup needed


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def validate_inputs(args):
    """Check that all preconditions are met before processing."""
    errors = []

    txtinout_dir = Path(args.txtinout_dir).resolve()
    if not txtinout_dir.is_dir():
        errors.append(f"TxtInOut directory not found: {txtinout_dir}")

    # Check for essential SWAT+ files
    essential_files = ['file.cio', 'time.sim', 'print.prt']
    for fname in essential_files:
        if not (txtinout_dir / fname).exists():
            errors.append(
                f"Essential SWAT+ file missing in TxtInOut: {fname}"
            )

    # Validate date pair
    if (args.start_date is None) != (args.end_date is None):
        errors.append(
            "Both --start_date and --end_date must be provided together"
        )

    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)

    logger.info("Input validation passed.")


def validate_outputs(sim_dir):
    """Check that postconditions are met after processing."""
    errors = []

    sim_path = Path(sim_dir).resolve()
    if not sim_path.is_dir():
        errors.append(f"Simulation directory not found: {sim_path}")
    else:
        # Check for at least some output files
        output_files = list(sim_path.glob("*_day.*")) + \
                       list(sim_path.glob("*_yr.*")) + \
                       list(sim_path.glob("*_mon.*")) + \
                       list(sim_path.glob("*_aa.*"))
        if not output_files:
            # Also check for .txt outputs
            txt_outputs = [
                f for f in sim_path.iterdir()
                if f.suffix in ('.txt', '.csv')
                and any(x in f.name for x in ['_day', '_yr', '_mon', '_aa'])
            ]
            if not txt_outputs:
                errors.append(
                    "No SWAT+ output files found in simulation directory. "
                    "Check the SWAT+ log for errors."
                )

    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(3)

    logger.info("Output validation passed.")


# ---------------------------------------------------------------------------
# Core processing
# ---------------------------------------------------------------------------
def process(args):
    """
    Main processing logic:
    1. Ensure SWAT+ binary is in TxtInOut dir
    2. Parse parameters
    3. Prepare sim_dir
    4. Run SWAT+ via pySWATPlus
    5. Return JSON summary
    """
    import pySWATPlus as psp

    txtinout_dir = Path(args.txtinout_dir).resolve()
    sim_dir = Path(args.sim_dir).resolve()

    # Step 1: Ensure executable is available
    created_symlink = ensure_executable_in_dir(
        txtinout_dir, args.swat_binary
    )
    symlink_path = None
    if created_symlink:
        # Track the symlink path for potential cleanup info
        if args.swat_binary:
            symlink_name = Path(args.swat_binary).name
        else:
            symlink_name = "swatplus_rev59"
        symlink_path = txtinout_dir / symlink_name

    # Step 2: Parse parameters
    parameters = parse_parameters(args.params_json)

    # Step 3: Prepare sim_dir
    if sim_dir.exists():
        # pySWATPlus requires empty dir for copy_required_files;
        # if sim_dir has files, remove and recreate
        if any(sim_dir.iterdir()):
            logger.info(
                f"sim_dir {sim_dir} is not empty; clearing it for fresh run"
            )
            shutil.rmtree(sim_dir)
            sim_dir.mkdir(parents=True)
    else:
        sim_dir.mkdir(parents=True)

    # Step 4: Initialize TxtinoutReader
    logger.info(f"Initializing TxtinoutReader from: {txtinout_dir}")
    reader = psp.TxtinoutReader(tio_dir=str(txtinout_dir))

    # Step 5: Build print_prt_control from --print_objects
    print_prt_control = None
    if args.print_objects:
        obj_list = [o.strip() for o in args.print_objects.split(',') if o.strip()]
        print_prt_control = {}
        for obj in obj_list:
            print_prt_control[obj] = {
                'daily': True, 'monthly': True,
                'yearly': True, 'avann': False
            }

    # Step 6: Run SWAT+
    logger.info("Starting SWAT+ simulation...")
    run_path = reader.run_swat(
        sim_dir=str(sim_dir),
        parameters=parameters,
        begin_date=args.start_date,
        end_date=args.end_date,
        warmup=args.warmup_years,
        print_prt_control=print_prt_control,
        skip_validation=True  # Skip HRU/unit validation for speed
    )

    logger.info(f"SWAT+ simulation completed. Output at: {run_path}")

    # Step 7: Collect output file list
    output_files = []
    run_path_obj = Path(run_path)
    for f in sorted(run_path_obj.iterdir()):
        if f.is_file() and any(
            x in f.name for x in ['_day', '_yr', '_mon', '_aa']
        ):
            output_files.append(f.name)

    # Build result
    result = {
        "status": "success",
        "sim_dir": str(run_path),
        "txtinout_dir": str(txtinout_dir),
        "parameters_applied": parameters if parameters else [],
        "start_date": args.start_date,
        "end_date": args.end_date,
        "warmup_years": args.warmup_years,
        "output_files": output_files[:50],  # Limit to first 50
        "total_output_files": len(output_files)
    }

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
        logger.error(f"Processing failed: {e}", exc_info=True)
        error_result = {
            "status": "error",
            "error": str(e),
            "sim_dir": str(Path(args.sim_dir).resolve())
        }
        print(json.dumps(error_result, indent=2))
        sys.exit(2)

    validate_outputs(result["sim_dir"])

    # Print JSON result to stdout
    print(json.dumps(result, indent=2))

    logger.info("Tool completed successfully.")
    sys.exit(0)
