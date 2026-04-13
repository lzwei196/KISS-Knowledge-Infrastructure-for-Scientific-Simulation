#!/usr/bin/env python3
"""Execute a PyMT model through its full BMI lifecycle.

Purpose:
    Run a single BMI model: setup → initialize → update loop → finalize.
    Optionally captures output variables at each time step to CSV or NetCDF.
    Supports forcing injection via set_value at runtime.

Usage:
    python run_model.py --model Waves --duration 100
    python run_model.py --model Hydrotrend --params '{"run_duration": 365}' --capture "channel_exit_water__volume_flow_rate"
    python run_model.py --model Cem --duration 1000 --output-csv results.csv

Critical Rules:
    - Always call finalize() even if errors occur (use try/finally)
    - Time units differ between models — check model.time_units
    - get_value() returns FLAT numpy arrays — reshape if needed
    - Duration is in MODEL time units, not wall-clock time
    - Config path from setup() is RELATIVE to run dir
"""

import argparse
import csv
import json
import os
import sys
import time as walltime


def validate_inputs(args):
    """Validate execution parameters."""
    errors = []

    try:
        import pymt
    except ImportError:
        errors.append("PyMT is not installed")

    if not args.model:
        errors.append("--model is required")

    if args.duration is not None and args.duration <= 0:
        errors.append("--duration must be positive")

    if args.params:
        try:
            json.loads(args.params)
        except json.JSONDecodeError as e:
            errors.append(f"Invalid JSON for --params: {e}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)


def run_model(model_name, params, duration, capture_vars, output_csv, run_dir):
    """Execute a BMI model through its full lifecycle.

    Parameters
    ----------
    model_name : str
        Name of the PyMT model (must be installed as plugin).
    params : dict
        Parameter overrides for model.setup().
    duration : float or None
        Number of time steps to run. If None, runs to model.end_time.
    capture_vars : list of str
        Variable names to capture at each time step.
    output_csv : str or None
        Path to write captured data as CSV.
    run_dir : str or None
        Directory for model run files.

    Returns
    -------
    dict
        Status, timing, captured data summary.
    """
    import numpy as np
    from pymt import MODELS

    model_cls = getattr(MODELS, model_name, None)
    if model_cls is None:
        return {"status": "error", "errors": [f"Model '{model_name}' not found in MODELS"]}

    model = model_cls()
    result = {
        "status": "running",
        "model": model_name,
        "steps_completed": 0,
        "captured_variables": {},
    }

    try:
        # --- SETUP ---
        setup_kwargs = {}
        if run_dir:
            setup_kwargs["path"] = run_dir
        if params:
            setup_kwargs.update(params)

        t0 = walltime.time()
        cfg_file, cfg_dir = model.setup(**setup_kwargs)
        result["config_file"] = cfg_file
        result["config_dir"] = cfg_dir

        # --- INITIALIZE ---
        model.initialize(cfg_file, dir=cfg_dir)
        result["start_time"] = float(model.start_time)
        result["end_time"] = float(model.end_time)
        result["time_step"] = float(model.time_step)
        result["time_units"] = str(model.time_units)

        # Validate capture variables
        valid_outputs = set(model.output_var_names)
        for var in capture_vars:
            if var not in valid_outputs:
                result.setdefault("warnings", []).append(
                    f"Variable '{var}' not in output_var_names, skipping"
                )
        capture_vars = [v for v in capture_vars if v in valid_outputs]

        # Initialize capture storage
        captured_data = {var: [] for var in capture_vars}
        time_series = []

        # --- RUN ---
        if duration is not None:
            target_time = model.start_time + duration
        else:
            target_time = model.end_time

        steps = 0
        while model.time < target_time:
            model.update()
            steps += 1

            # Capture
            current_time = float(model.time)
            time_series.append(current_time)

            for var in capture_vars:
                val = model.get_value(var)
                # Store scalar or mean for series
                if val.size == 1:
                    captured_data[var].append(float(val.flat[0]))
                else:
                    captured_data[var].append(float(np.mean(val)))

        result["steps_completed"] = steps
        result["final_time"] = float(model.time)

        # --- OUTPUT ---
        if output_csv and capture_vars:
            with open(output_csv, "w", newline="") as f:
                writer = csv.writer(f)
                header = ["time"] + capture_vars
                writer.writerow(header)
                for i, t in enumerate(time_series):
                    row = [t] + [captured_data[var][i] for var in capture_vars]
                    writer.writerow(row)
            result["output_csv"] = output_csv

        # Summary stats
        for var in capture_vars:
            vals = captured_data[var]
            if vals:
                result["captured_variables"][var] = {
                    "n_values": len(vals),
                    "min": min(vals),
                    "max": max(vals),
                    "mean": sum(vals) / len(vals),
                    "units": str(model.var_units(var)),
                }

        t1 = walltime.time()
        result["wall_time_s"] = round(t1 - t0, 3)
        result["status"] = "success"

    except Exception as e:
        result["status"] = "error"
        result["errors"] = [str(e)]

    finally:
        # ALWAYS finalize
        try:
            model.finalize()
            result["finalized"] = True
        except Exception as e:
            result["finalized"] = False
            result.setdefault("warnings", []).append(f"Finalize failed: {e}")

    return result


def process(args):
    """Main processing logic."""
    validate_inputs(args)

    params = {}
    if args.params:
        params = json.loads(args.params)

    capture_vars = []
    if args.capture:
        capture_vars = [v.strip() for v in args.capture.split(",")]

    return run_model(
        model_name=args.model,
        params=params,
        duration=args.duration,
        capture_vars=capture_vars,
        output_csv=args.output_csv,
        run_dir=args.run_dir,
    )


def main():
    parser = argparse.ArgumentParser(
        description="Execute a PyMT model through its BMI lifecycle"
    )
    parser.add_argument("--model", "-m", required=True, help="Model name")
    parser.add_argument(
        "--duration", "-d", type=float, default=None,
        help="Duration in model time units (default: run to end_time)"
    )
    parser.add_argument(
        "--params", "-p", type=str, default=None,
        help="JSON parameter overrides"
    )
    parser.add_argument(
        "--capture", "-c", type=str, default=None,
        help="Comma-separated variable names to capture"
    )
    parser.add_argument(
        "--output-csv", type=str, default=None,
        help="Write captured data to CSV"
    )
    parser.add_argument(
        "--run-dir", type=str, default=None,
        help="Model run directory"
    )
    args = parser.parse_args()

    result = process(args)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
