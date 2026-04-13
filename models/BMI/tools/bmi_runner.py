#!/usr/bin/env python3
"""BMI Model Execution Wrapper.

Runs any BMI-wrapped model through the standard Initialize → Run → Finalize
(IRF) lifecycle with optional data injection and extraction at each time step.

Pipeline stage: S3 — Model Execution
Pattern: validate_inputs → run_model → validate_outputs
"""

import csv
import logging
import os
import sys
import time
from typing import Any

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def validate_inputs(
    bmi_instance: Any,
    config_file: str,
    output_vars: list[str] | None = None,
    end_time: float | None = None,
    inject_schedule: dict | None = None,
) -> dict:
    """Validate inputs before model execution.

    Parameters
    ----------
    bmi_instance : object
        An uninitialized BMI model instance.
    config_file : str
        Path to the model configuration file.
    output_vars : list of str, optional
        Variable names to extract. If None, all output vars are used.
    end_time : float, optional
        Override the model's end time.
    inject_schedule : dict, optional
        Schedule of {time: {var_name: values}} for set_value injections.

    Returns
    -------
    dict
        Validated run parameters.

    Raises
    ------
    FileNotFoundError
        If config_file does not exist.
    AttributeError
        If bmi_instance lacks required BMI methods.
    """
    if not os.path.isfile(config_file):
        raise FileNotFoundError(f"Config file not found: {config_file}")

    # Check that the instance has minimum BMI methods
    required_methods = ["initialize", "update", "finalize", "get_current_time"]
    for method in required_methods:
        if not hasattr(bmi_instance, method) or not callable(
            getattr(bmi_instance, method)
        ):
            raise AttributeError(
                f"BMI instance missing required method: {method}"
            )

    return {
        "bmi": bmi_instance,
        "config_file": config_file,
        "output_vars": output_vars,
        "end_time": end_time,
        "inject_schedule": inject_schedule or {},
    }


def run_model(params: dict, output_csv: str | None = None) -> dict:
    """Execute BMI model through full IRF lifecycle.

    Parameters
    ----------
    params : dict
        Validated parameters from validate_inputs.
    output_csv : str, optional
        Path to write time series output CSV.

    Returns
    -------
    dict
        Run results including time series data and metadata.
    """
    bmi = params["bmi"]
    config_file = params["config_file"]
    inject_schedule = params["inject_schedule"]

    # -------------------------------------------------------------------------
    # INITIALIZE
    # -------------------------------------------------------------------------
    logger.info(f"Initializing model with config: {config_file}")
    t_start_wall = time.time()
    bmi.initialize(config_file)

    model_name = (
        bmi.get_component_name()
        if hasattr(bmi, "get_component_name")
        else "Unknown"
    )
    logger.info(f"Model: {model_name}")

    # Query time info
    start_time = bmi.get_start_time()
    model_end_time = bmi.get_end_time()
    dt = bmi.get_time_step()
    time_units = (
        bmi.get_time_units() if hasattr(bmi, "get_time_units") else "unknown"
    )

    end_time = params["end_time"] if params["end_time"] is not None else model_end_time

    logger.info(
        f"Time: {start_time} to {end_time} {time_units}, dt={dt}"
    )

    # Determine output variables
    if params["output_vars"]:
        output_var_names = params["output_vars"]
    elif hasattr(bmi, "get_output_var_names"):
        output_var_names = list(bmi.get_output_var_names())
    else:
        output_var_names = []

    logger.info(f"Tracking {len(output_var_names)} output variables")

    # Log variable info
    for var_name in output_var_names:
        try:
            units = bmi.get_var_units(var_name)
            var_type = bmi.get_var_type(var_name)
            grid_id = bmi.get_var_grid(var_name)
            grid_type = bmi.get_grid_type(grid_id)
            logger.info(
                f"  {var_name}: type={var_type}, units={units}, "
                f"grid={grid_id} ({grid_type})"
            )
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # RUN (Update Loop)
    # -------------------------------------------------------------------------
    results = {
        "model_name": model_name,
        "time_units": time_units,
        "dt": dt,
        "variables": {name: [] for name in output_var_names},
        "times": [],
        "n_steps": 0,
    }

    current_time = bmi.get_current_time()
    step = 0

    while current_time < end_time:
        # Check for value injections at this time
        for sched_time, injections in inject_schedule.items():
            if abs(current_time - float(sched_time)) < dt / 2:
                for var_name, values in injections.items():
                    logger.info(
                        f"Injecting {var_name} at t={current_time}"
                    )
                    bmi.set_value(var_name, np.asarray(values))

        # Advance one step
        bmi.update()
        current_time = bmi.get_current_time()
        step += 1

        # Extract output variables
        results["times"].append(current_time)
        for var_name in output_var_names:
            try:
                nbytes = bmi.get_var_nbytes(var_name)
                itemsize = bmi.get_var_itemsize(var_name)
                n_items = nbytes // itemsize
                dest = np.empty(n_items, dtype=float)
                bmi.get_value(var_name, dest)

                # Store scalar or summary statistics
                if n_items == 1:
                    results["variables"][var_name].append(float(dest[0]))
                else:
                    results["variables"][var_name].append(
                        {
                            "mean": float(np.mean(dest)),
                            "min": float(np.min(dest)),
                            "max": float(np.max(dest)),
                            "std": float(np.std(dest)),
                        }
                    )
            except Exception as e:
                results["variables"][var_name].append(None)
                if step == 1:
                    logger.warning(f"Cannot read {var_name}: {e}")

        # Progress logging
        if step % max(1, int((end_time - start_time) / dt / 10)) == 0:
            pct = 100 * (current_time - start_time) / (end_time - start_time)
            logger.info(f"Progress: {pct:.0f}% (t={current_time:.2f})")

    results["n_steps"] = step

    # -------------------------------------------------------------------------
    # FINALIZE
    # -------------------------------------------------------------------------
    bmi.finalize()
    elapsed = time.time() - t_start_wall
    results["wall_time_s"] = elapsed
    logger.info(
        f"Model completed: {step} steps in {elapsed:.2f}s "
        f"({step / elapsed:.0f} steps/s)"
    )

    # Write CSV if requested
    if output_csv and output_var_names:
        _write_csv(results, output_csv)

    return results


def _write_csv(results: dict, output_csv: str) -> None:
    """Write time series results to CSV."""
    os.makedirs(os.path.dirname(output_csv) or ".", exist_ok=True)

    with open(output_csv, "w", newline="") as f:
        writer = csv.writer(f)

        # Header
        header = ["time"]
        for var_name in results["variables"]:
            sample = results["variables"][var_name]
            if sample and isinstance(sample[0], dict):
                for stat in ["mean", "min", "max", "std"]:
                    header.append(f"{var_name}_{stat}")
            else:
                header.append(var_name)
        writer.writerow(header)

        # Data rows
        for i, t in enumerate(results["times"]):
            row = [t]
            for var_name in results["variables"]:
                val = results["variables"][var_name][i]
                if val is None:
                    row.append("")
                elif isinstance(val, dict):
                    for stat in ["mean", "min", "max", "std"]:
                        row.append(val[stat])
                else:
                    row.append(val)
            writer.writerow(row)

    logger.info(f"Results written to {output_csv}")


def validate_outputs(results: dict) -> bool:
    """Validate model run results.

    Parameters
    ----------
    results : dict
        Results from run_model.

    Returns
    -------
    bool
        True if results look reasonable.
    """
    if results["n_steps"] == 0:
        logger.error("Model ran zero time steps")
        return False

    if not results["times"]:
        logger.error("No time points recorded")
        return False

    # Check for monotonically increasing time
    times = results["times"]
    for i in range(1, len(times)):
        if times[i] <= times[i - 1]:
            logger.warning(
                f"Non-monotonic time at step {i}: "
                f"{times[i - 1]} -> {times[i]}"
            )

    # Check for all-null variables
    for var_name, values in results["variables"].items():
        non_null = [v for v in values if v is not None]
        if not non_null:
            logger.warning(f"Variable '{var_name}' has no valid values")

    logger.info(
        f"Validation passed: {results['n_steps']} steps, "
        f"{len(results['variables'])} variables tracked"
    )
    return True


def main():
    """CLI entry point for standalone execution."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Run a BMI model through the IRF lifecycle"
    )
    parser.add_argument(
        "module", help="Python module containing the BMI class"
    )
    parser.add_argument(
        "class_name", help="Name of the BMI class"
    )
    parser.add_argument(
        "config_file", help="Path to YAML config file"
    )
    parser.add_argument(
        "--output-csv",
        "-o",
        default="bmi_output.csv",
        help="Output CSV file path",
    )
    parser.add_argument(
        "--end-time",
        type=float,
        default=None,
        help="Override model end time",
    )
    parser.add_argument(
        "--vars",
        nargs="+",
        default=None,
        help="Output variable names to track",
    )

    args = parser.parse_args()

    # Import model class
    try:
        mod = importlib.import_module(args.module)
        bmi_class = getattr(mod, args.class_name)
        bmi_instance = bmi_class()
    except Exception as e:
        logger.error(f"Cannot load BMI class: {e}")
        sys.exit(1)

    import importlib

    # validate → process → validate
    params = validate_inputs(
        bmi_instance, args.config_file, args.vars, args.end_time
    )
    results = run_model(params, args.output_csv)
    validate_outputs(results)


if __name__ == "__main__":
    main()
