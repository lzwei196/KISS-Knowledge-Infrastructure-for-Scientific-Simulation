#!/usr/bin/env python3
"""
run_pygimli.py — Execute pyGIMLi forward modelling or inversion.

Wrapper script that handles the complete workflow: load data, create mesh,
configure inversion parameters, run inversion/forward, and save results.

Usage:
    # ERT inversion
    python run_pygimli.py --data field.ohm --method ert --mode invert \
        --lambda 20 --max-iter 10 --output results/

    # ERT forward modelling
    python run_pygimli.py --data scheme.ohm --method ert --mode forward \
        --resistivity 100 --output results/

    # SRT inversion
    python run_pygimli.py --data picks.sgt --method srt --mode invert \
        --lambda 50 --output results/

    # With region config
    python run_pygimli.py --data field.ohm --method ert --mode invert \
        --regions regions.json --output results/

Prerequisites:
    - pygimli installed (pip install pygimli or conda install)
    - Input data in pyGIMLi format (.ohm, .dat, .sgt)

Output:
    results/model.npy          — Inverted model parameters
    results/mesh.bms           — Inversion mesh
    results/response.npy       — Forward response (predicted data)
    results/chi2_history.json  — Chi-squared per iteration
    results/result.json        — Summary metadata
"""

import argparse
import json
import os
import sys
import time
import numpy as np


def validate_inputs(args):
    """Validate arguments and check pyGIMLi availability."""
    errors = []

    if not os.path.isfile(args.data):
        errors.append(f"Data file not found: {args.data}")

    if args.method not in ("ert", "srt"):
        errors.append(f"Unsupported method: {args.method}")

    if args.mode not in ("forward", "invert"):
        errors.append(f"Invalid mode: {args.mode}. Use 'forward' or 'invert'.")

    if args.regions and not os.path.isfile(args.regions):
        errors.append(f"Region config not found: {args.regions}")

    # Check pyGIMLi availability
    try:
        import pygimli  # noqa: F401
    except ImportError:
        errors.append(
            "pygimli not installed. Install via: pip install pygimli "
            "or conda install -c gimli -c conda-forge pygimli"
        )

    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)


def run_ert_inversion(args):
    """Run ERT inversion using ERTManager."""
    import pygimli as pg
    from pygimli.physics import ert

    # Load data
    data = ert.load(args.data)
    print(f"Loaded ERT data: {data.size()} measurements, "
          f"{data.sensorCount()} electrodes", file=sys.stderr)

    # Error estimation if not present
    if not data.haveData("err"):
        data["err"] = ert.estimateError(
            data,
            relativeError=args.relative_error,
            absoluteUError=args.absolute_error,
        )
        print(f"Estimated errors: relative={args.relative_error}, "
              f"absoluteU={args.absolute_error} V", file=sys.stderr)

    # Create manager and run inversion
    mgr = ert.ERTManager(data)

    inv_kwargs = {
        "lam": args.lam,
        "maxIter": args.max_iter,
        "verbose": True,
    }

    if args.z_weight != 1.0:
        inv_kwargs["zWeight"] = args.z_weight

    if args.robust:
        inv_kwargs["robustData"] = True

    start_time = time.time()
    model = mgr.invert(**inv_kwargs)
    elapsed = time.time() - start_time

    # Extract results
    mesh = mgr.paraDomain
    response = mgr.inv.response
    chi2 = mgr.inv.chi2()

    return {
        "model": np.array(model),
        "mesh": mesh,
        "response": np.array(response),
        "chi2": float(chi2),
        "n_iterations": mgr.inv.iter,
        "elapsed_s": elapsed,
        "n_cells": mesh.cellCount(),
        "n_data": data.size(),
        "model_range": [float(np.min(model)), float(np.max(model))],
        "manager": mgr,
    }


def run_ert_forward(args):
    """Run ERT forward modelling."""
    import pygimli as pg
    from pygimli.physics import ert

    data = ert.load(args.data)
    mesh = pg.meshtools.createParaMesh2DGrid(data.sensors())
    res = args.resistivity or 100.0

    start_time = time.time()
    synth = ert.simulate(
        mesh, res=res, scheme=data,
        noiseLevel=args.relative_error,
        noiseAbs=args.absolute_error,
    )
    elapsed = time.time() - start_time

    return {
        "model": np.full(mesh.cellCount(), res),
        "mesh": mesh,
        "response": np.array(synth["rhoa"]),
        "chi2": 0.0,
        "n_iterations": 0,
        "elapsed_s": elapsed,
        "n_cells": mesh.cellCount(),
        "n_data": synth.size(),
        "model_range": [res, res],
        "manager": None,
    }


def run_srt_inversion(args):
    """Run SRT inversion using TravelTimeManager."""
    import pygimli as pg
    from pygimli.physics import traveltime as tt

    data = tt.load(args.data)
    print(f"Loaded SRT data: {data.size()} picks, "
          f"{data.sensorCount()} sensors", file=sys.stderr)

    mgr = tt.TravelTimeManager(data)

    inv_kwargs = {
        "lam": args.lam,
        "maxIter": args.max_iter,
        "verbose": True,
    }

    if args.z_weight != 1.0:
        inv_kwargs["zWeight"] = args.z_weight

    start_time = time.time()
    model = mgr.invert(**inv_kwargs)
    elapsed = time.time() - start_time

    # Model is slowness; convert to velocity for reporting
    velocity = 1.0 / np.array(model)

    mesh = mgr.paraDomain
    response = mgr.inv.response
    chi2 = mgr.inv.chi2()

    return {
        "model": np.array(model),
        "velocity": velocity,
        "mesh": mesh,
        "response": np.array(response),
        "chi2": float(chi2),
        "n_iterations": mgr.inv.iter,
        "elapsed_s": elapsed,
        "n_cells": mesh.cellCount(),
        "n_data": data.size(),
        "model_range": [float(np.min(velocity)), float(np.max(velocity))],
        "manager": mgr,
    }


def process(args):
    """Route to appropriate method and mode."""
    if args.method == "ert":
        if args.mode == "invert":
            return run_ert_inversion(args)
        else:
            return run_ert_forward(args)
    elif args.method == "srt":
        if args.mode == "invert":
            return run_srt_inversion(args)
        else:
            print(json.dumps({"status": "error",
                               "errors": ["SRT forward not yet supported"]}))
            sys.exit(1)


def validate_outputs(result):
    """Validate inversion/forward results."""
    warnings = []

    chi2 = result.get("chi2", 0)
    if chi2 > 5.0:
        warnings.append(
            f"Chi² = {chi2:.2f} >> 1. Data not well fit. "
            "Consider reducing lambda or increasing error estimate."
        )
    if 0 < chi2 < 0.5:
        warnings.append(
            f"Chi² = {chi2:.2f} << 1. Possible overfitting. "
            "Consider increasing lambda or decreasing error estimate."
        )

    model = result.get("model", np.array([]))
    if len(model) > 0:
        if np.any(np.isnan(model)):
            warnings.append("NaN values in model — inversion diverged.")
        if np.any(np.isinf(model)):
            warnings.append("Inf values in model — check data/transform.")

    if warnings:
        result["warnings"] = warnings

    return result


def save_results(result, output_dir):
    """Save all results to output directory."""
    import pygimli as pg

    os.makedirs(output_dir, exist_ok=True)

    # Save model
    np.save(os.path.join(output_dir, "model.npy"), result["model"])

    # Save velocity (SRT only)
    if "velocity" in result:
        np.save(os.path.join(output_dir, "velocity.npy"), result["velocity"])

    # Save response
    np.save(os.path.join(output_dir, "response.npy"), result["response"])

    # Save mesh
    if result["mesh"] is not None:
        result["mesh"].save(os.path.join(output_dir, "mesh.bms"))
        try:
            result["mesh"].exportVTK(os.path.join(output_dir, "mesh.vtk"))
        except Exception:
            pass

    # Save summary
    summary = {
        "status": "success",
        "chi2": result["chi2"],
        "n_iterations": result["n_iterations"],
        "elapsed_s": result["elapsed_s"],
        "n_cells": result["n_cells"],
        "n_data": result["n_data"],
        "model_range": result["model_range"],
        "warnings": result.get("warnings", []),
    }
    with open(os.path.join(output_dir, "result.json"), "w") as f:
        json.dump(summary, f, indent=2)

    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Execute pyGIMLi forward modelling or inversion."
    )
    parser.add_argument("--data", "-d", required=True,
                        help="Input data file (.ohm, .dat, .sgt)")
    parser.add_argument("--method", "-m", required=True,
                        choices=["ert", "srt"],
                        help="Geophysical method")
    parser.add_argument("--mode", default="invert",
                        choices=["forward", "invert"],
                        help="Execution mode (default: invert)")
    parser.add_argument("--output", "-o", default="results",
                        help="Output directory (default: results/)")
    parser.add_argument("--regions", default=None,
                        help="Region config JSON from convert_parameters.py")
    parser.add_argument("--lam", type=float, default=20.0,
                        help="Regularization parameter lambda (default: 20)")
    parser.add_argument("--max-iter", type=int, default=10,
                        help="Maximum iterations (default: 10)")
    parser.add_argument("--z-weight", type=float, default=1.0,
                        help="Vertical regularization weight (default: 1.0)")
    parser.add_argument("--relative-error", type=float, default=0.03,
                        help="Relative data error fraction (default: 0.03)")
    parser.add_argument("--absolute-error", type=float, default=5e-5,
                        help="Absolute voltage error in V (default: 5e-5)")
    parser.add_argument("--resistivity", type=float, default=None,
                        help="Homogeneous resistivity for forward mode (Ohm·m)")
    parser.add_argument("--robust", action="store_true",
                        help="Use robust (L1) data weighting")

    args = parser.parse_args()

    validate_inputs(args)
    result = process(args)
    result = validate_outputs(result)
    summary = save_results(result, args.output)

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
