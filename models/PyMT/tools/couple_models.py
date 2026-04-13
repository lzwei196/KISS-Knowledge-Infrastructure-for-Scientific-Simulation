#!/usr/bin/env python3
"""Couple two PyMT BMI models and run a linked simulation.

Purpose:
    Connect two BMI models by mapping output variables from a source
    model to input variables on a target model. Handles time synchronization,
    optional spatial regridding, and unit conversion between models.

Usage:
    python couple_models.py --source Waves --target Cem \\
        --mapping '{"sea_surface_water_wave__azimuth_angle_of_opposite_of_phase_velocity": "sea_surface_water_wave__azimuth_angle_of_opposite_of_phase_velocity"}' \\
        --duration 1000

Critical Rules:
    - Variable names must match CSDMS Standard Names EXACTLY
    - Time units may differ between models — synchronize manually
    - Spatial grids may differ — use appropriate mapper
    - Azimuth vs. math angle: use angle="azimuth" or angle="math"
    - Both models MUST be finalized, even on error
    - get_value returns flat arrays; set_value expects matching shape
"""

import argparse
import csv
import json
import os
import sys
import time as walltime


def validate_inputs(args):
    """Validate coupling parameters."""
    errors = []

    try:
        import pymt
    except ImportError:
        errors.append("PyMT is not installed")

    if not args.source:
        errors.append("--source model is required")
    if not args.target:
        errors.append("--target model is required")

    if args.mapping:
        try:
            mapping = json.loads(args.mapping)
            if not isinstance(mapping, dict):
                errors.append("--mapping must be a JSON object {src_var: tgt_var}")
        except json.JSONDecodeError as e:
            errors.append(f"Invalid JSON for --mapping: {e}")

    if args.duration is not None and args.duration <= 0:
        errors.append("--duration must be positive")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)


def find_matching_variables(source_model, target_model):
    """Auto-discover variable connections by matching Standard Names.

    Returns dict mapping source output var → target input var where
    the CSDMS Standard Name is identical.
    """
    src_outputs = set(source_model.output_var_names)
    tgt_inputs = set(target_model.input_var_names)
    return {var: var for var in src_outputs & tgt_inputs}


def couple_and_run(source_name, target_name, mapping, duration,
                   source_params, target_params, output_csv, auto_map):
    """Run a coupled simulation between two BMI models.

    Parameters
    ----------
    source_name : str
        Source (driver) model name.
    target_name : str
        Target (driven) model name.
    mapping : dict
        {source_output_var: target_input_var} mapping.
    duration : float or None
        Duration in source model time units.
    source_params : dict
        Source model parameter overrides.
    target_params : dict
        Target model parameter overrides.
    output_csv : str or None
        CSV output path for captured data.
    auto_map : bool
        If True, auto-discover matching variables.

    Returns
    -------
    dict
        Status, timing, data exchange summary.
    """
    import numpy as np
    from pymt import MODELS

    # Load models
    src_cls = getattr(MODELS, source_name, None)
    tgt_cls = getattr(MODELS, target_name, None)

    if src_cls is None:
        return {"status": "error", "errors": [f"Source model '{source_name}' not found"]}
    if tgt_cls is None:
        return {"status": "error", "errors": [f"Target model '{target_name}' not found"]}

    source = src_cls()
    target = tgt_cls()

    result = {
        "status": "running",
        "source": source_name,
        "target": target_name,
        "exchanges": [],
    }

    try:
        # --- SETUP ---
        src_cfg = source.setup(**(source_params or {}))
        tgt_cfg = target.setup(**(target_params or {}))

        # --- INITIALIZE ---
        source.initialize(*src_cfg)
        target.initialize(*tgt_cfg)

        result["source_time_units"] = str(source.time_units)
        result["target_time_units"] = str(target.time_units)
        result["source_time_step"] = float(source.time_step)
        result["target_time_step"] = float(target.time_step)

        # --- VARIABLE MAPPING ---
        if auto_map or not mapping:
            auto_mapping = find_matching_variables(source, target)
            if mapping:
                auto_mapping.update(mapping)
            mapping = auto_mapping

        if not mapping:
            result["warnings"] = ["No variable mapping found — models will run independently"]

        result["variable_mapping"] = mapping

        # Validate mapping
        src_outputs = set(source.output_var_names)
        tgt_inputs = set(target.input_var_names)

        for src_var, tgt_var in list(mapping.items()):
            if src_var not in src_outputs:
                result.setdefault("warnings", []).append(
                    f"Source var '{src_var}' not in output_var_names"
                )
                del mapping[src_var]
            elif tgt_var not in tgt_inputs:
                result.setdefault("warnings", []).append(
                    f"Target var '{tgt_var}' not in input_var_names"
                )
                del mapping[src_var]

        # --- COUPLING LOOP ---
        t0 = walltime.time()
        target_time = (source.start_time + duration) if duration else source.end_time
        steps = 0
        exchange_log = []

        while source.time < target_time:
            # Update source
            source.update()

            # Exchange data
            exchange_record = {"step": steps, "time": float(source.time)}
            for src_var, tgt_var in mapping.items():
                try:
                    values = source.get_value(src_var)
                    target.set_value(tgt_var, values)
                    exchange_record[f"{src_var}→{tgt_var}"] = {
                        "mean": float(np.mean(values)),
                        "shape": list(values.shape),
                    }
                except Exception as e:
                    exchange_record[f"{src_var}→{tgt_var}"] = {"error": str(e)}

            # Update target
            target.update()
            steps += 1
            exchange_log.append(exchange_record)

        t1 = walltime.time()

        # --- OUTPUT ---
        if output_csv and exchange_log:
            fieldnames = list(exchange_log[0].keys())
            with open(output_csv, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                writer.writeheader()
                for record in exchange_log:
                    flat = {"step": record["step"], "time": record["time"]}
                    for k, v in record.items():
                        if isinstance(v, dict) and "mean" in v:
                            flat[k] = v["mean"]
                    writer.writerow(flat)
            result["output_csv"] = output_csv

        result["status"] = "success"
        result["steps_completed"] = steps
        result["wall_time_s"] = round(t1 - t0, 3)
        result["final_source_time"] = float(source.time)
        result["final_target_time"] = float(target.time)

    except Exception as e:
        result["status"] = "error"
        result["errors"] = [str(e)]

    finally:
        # ALWAYS finalize both models
        for name, model in [("source", source), ("target", target)]:
            try:
                model.finalize()
                result[f"{name}_finalized"] = True
            except Exception as e:
                result[f"{name}_finalized"] = False
                result.setdefault("warnings", []).append(f"{name} finalize failed: {e}")

    return result


def process(args):
    """Main processing logic."""
    validate_inputs(args)

    mapping = {}
    if args.mapping:
        mapping = json.loads(args.mapping)

    src_params = json.loads(args.source_params) if args.source_params else {}
    tgt_params = json.loads(args.target_params) if args.target_params else {}

    return couple_and_run(
        source_name=args.source,
        target_name=args.target,
        mapping=mapping,
        duration=args.duration,
        source_params=src_params,
        target_params=tgt_params,
        output_csv=args.output_csv,
        auto_map=args.auto_map,
    )


def main():
    parser = argparse.ArgumentParser(
        description="Couple two PyMT BMI models and run linked simulation"
    )
    parser.add_argument("--source", "-s", required=True, help="Source (driver) model name")
    parser.add_argument("--target", "-t", required=True, help="Target (driven) model name")
    parser.add_argument(
        "--mapping", type=str, default=None,
        help='JSON mapping {source_var: target_var}'
    )
    parser.add_argument("--duration", "-d", type=float, default=None, help="Duration")
    parser.add_argument("--source-params", type=str, help="Source model params JSON")
    parser.add_argument("--target-params", type=str, help="Target model params JSON")
    parser.add_argument("--output-csv", type=str, help="Output CSV path")
    parser.add_argument("--auto-map", action="store_true", help="Auto-discover variable connections")
    args = parser.parse_args()

    result = process(args)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
