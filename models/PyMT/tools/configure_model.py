#!/usr/bin/env python3
"""Configure a PyMT model with parameter overrides and unit conversions.

Purpose:
    Generate model configuration files with custom parameter values.
    Handles unit conversion for forcing/input data so that values
    are in the units expected by the underlying BMI model.

Usage:
    python configure_model.py --model Waves --params '{"incoming_wave_height": 3.5}' --output /runs/test1
    python configure_model.py --model Hydrotrend --list-params

Critical Rules:
    - Parameter names must match exactly (case-sensitive)
    - Config file path returned by setup() is RELATIVE to the run directory
    - Always use model.setup() rather than hand-editing config files
    - Unit conversions happen at the get_value/set_value level, not config level
"""

import argparse
import json
import os
import sys


def validate_inputs(args):
    """Check preconditions for model configuration."""
    errors = []

    try:
        import pymt
    except ImportError:
        errors.append("PyMT is not installed")
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)

    if not args.model and not args.list_all:
        errors.append("--model is required (or use --list-all)")

    if args.params:
        try:
            json.loads(args.params)
        except json.JSONDecodeError as e:
            errors.append(f"Invalid JSON for --params: {e}")

    if args.output and os.path.isfile(args.output):
        errors.append(f"Output path {args.output} is a file, must be a directory")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)


def list_all_models():
    """List all available models."""
    from pymt import MODELS
    return {"status": "success", "models": list(MODELS)}


def list_parameters(model_name):
    """List parameters and their defaults for a model."""
    from pymt import MODELS
    model_cls = getattr(MODELS, model_name, None)
    if model_cls is None:
        return {"status": "error", "errors": [f"Model '{model_name}' not found"]}

    model = model_cls()
    params = []
    for name, value in model.parameters:
        params.append({"name": name, "default": value})

    return {
        "status": "success",
        "model": model_name,
        "parameters": params,
    }


def configure_and_setup(model_name, params_json, output_dir):
    """Configure model with parameter overrides and generate config files.

    Returns dict with config_file, config_dir, and parameter summary.
    """
    from pymt import MODELS

    model_cls = getattr(MODELS, model_name, None)
    if model_cls is None:
        return {"status": "error", "errors": [f"Model '{model_name}' not found"]}

    model = model_cls()

    # Parse parameter overrides
    overrides = {}
    if params_json:
        overrides = json.loads(params_json)

    # Validate parameter names
    valid_names = {name for name, _ in model.parameters}
    invalid = set(overrides.keys()) - valid_names
    if invalid:
        return {
            "status": "error",
            "errors": [f"Unknown parameters: {invalid}"],
            "valid_parameters": sorted(valid_names),
        }

    # Setup with overrides
    setup_kwargs = {}
    if output_dir:
        setup_kwargs["path"] = output_dir

    cfg_file, cfg_dir = model.setup(**setup_kwargs, **overrides)

    # Validate outputs
    cfg_path = os.path.join(cfg_dir, cfg_file)
    if not os.path.exists(cfg_path):
        return {
            "status": "error",
            "errors": [f"Config file not created: {cfg_path}"],
        }

    # Collect metadata
    result = {
        "status": "success",
        "model": model_name,
        "config_file": cfg_file,
        "config_dir": cfg_dir,
        "config_path": cfg_path,
        "overrides_applied": overrides,
        "input_var_names": list(model.input_var_names),
        "output_var_names": list(model.output_var_names),
    }

    # Read final parameters
    final_params = {}
    for name, value in model.parameters:
        final_params[name] = value
    result["final_parameters"] = final_params

    return result


def process(args):
    """Main processing logic."""
    validate_inputs(args)

    if args.list_all:
        return list_all_models()

    if args.list_params:
        return list_parameters(args.model)

    return configure_and_setup(args.model, args.params, args.output)


def main():
    parser = argparse.ArgumentParser(
        description="Configure a PyMT model with parameter overrides"
    )
    parser.add_argument("--model", "-m", type=str, help="Model name (e.g., Waves)")
    parser.add_argument(
        "--params", "-p", type=str, default=None,
        help='JSON dict of parameter overrides (e.g., \'{"wave_height": 3.5}\')'
    )
    parser.add_argument(
        "--output", "-o", type=str, default=None,
        help="Output directory for config files (default: temp dir)"
    )
    parser.add_argument(
        "--list-params", action="store_true",
        help="List parameters and defaults for the model"
    )
    parser.add_argument(
        "--list-all", action="store_true",
        help="List all available models"
    )
    parser.add_argument(
        "--format", choices=["json", "text"], default="json",
        help="Output format"
    )
    args = parser.parse_args()

    result = process(args)

    if args.format == "json":
        print(json.dumps(result, indent=2, default=str))
    else:
        if result["status"] == "error":
            print(f"ERROR: {result['errors']}")
        elif "models" in result:
            print("Available models:")
            for m in result["models"]:
                print(f"  - {m}")
        elif "parameters" in result:
            print(f"Parameters for {result['model']}:")
            for p in result["parameters"]:
                print(f"  {p['name']} = {p['default']}")
        else:
            print(f"Model: {result['model']}")
            print(f"Config: {result['config_path']}")
            print(f"Overrides: {result['overrides_applied']}")


if __name__ == "__main__":
    main()
