#!/usr/bin/env python3
"""
run_superflexpy.py — Execute a SuperflexPy model and save outputs.

Wrapper that assembles a model from a configuration, loads forcing data,
runs the simulation, and saves streamflow + state time series.

Supports pre-built models (GR4J, HBV, HYMOD) and custom configurations.

Usage:
    python run_superflexpy.py --model gr4j --forcing forcing.json --output results.json
    python run_superflexpy.py --model gr4j --forcing forcing.json --params x1=300 x3=50 --output results.json
    python run_superflexpy.py --model hbv --forcing forcing.json --timestep 1.0 --output results.json
"""

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np


def validate_inputs(args):
    """Validate command-line arguments."""
    errors = []

    if args.forcing:
        forcing_path = Path(args.forcing)
        if not forcing_path.exists():
            errors.append(f"Forcing file not found: {args.forcing}")

    if args.model not in ("gr4j", "hbv", "hymod", "custom"):
        errors.append(
            f"Unknown model: {args.model}. "
            "Supported: gr4j, hbv, hymod, custom"
        )

    if args.timestep <= 0:
        errors.append(f"Timestep must be positive, got {args.timestep}")

    if args.solver not in ("implicit_euler", "explicit_euler", "runge_kutta"):
        errors.append(
            f"Unknown solver: {args.solver}. "
            "Supported: implicit_euler, explicit_euler, runge_kutta"
        )

    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)


def build_model(args):
    """Assemble the SuperflexPy model from configuration."""
    model_type = args.model
    solver_type = args.solver
    arch = args.architecture

    # Import framework components
    if solver_type == "implicit_euler":
        if arch == "numba":
            from superflexpy.implementation.numerical_approximators.implicit_euler import ImplicitEulerNumba as Solver
            from superflexpy.implementation.root_finders.pegasus import PegasusNumba as RootFinder
        else:
            from superflexpy.implementation.numerical_approximators.implicit_euler import ImplicitEulerPython as Solver
            from superflexpy.implementation.root_finders.pegasus import PegasusPython as RootFinder
        root_finder = RootFinder()
        num_app = Solver(root_finder=root_finder)
    elif solver_type == "explicit_euler":
        from superflexpy.implementation.numerical_approximators.explicit_euler import ExplicitEulerPython as Solver
        num_app = Solver()
    elif solver_type == "runge_kutta":
        from superflexpy.implementation.numerical_approximators.runge_kutta_4 import RungeKutta4Python as Solver
        num_app = Solver()

    if model_type == "gr4j":
        from superflexpy.framework.unit import Unit
        from superflexpy.implementation.elements.gr4j import (
            FluxAggregator,
            InterceptionFilter,
            ProductionStore,
            RoutingStore,
            UnitHydrograph1,
            UnitHydrograph2,
        )
        from superflexpy.implementation.elements.structure_elements import Junction, Splitter, Transparent

        x1, x2, x3, x4 = 350.0, 0.0, 90.0, 1.7

        interception_filter = InterceptionFilter(id="ir")
        production_store = ProductionStore(
            parameters={"x1": x1, "alpha": 2.0, "beta": 5.0, "ni": 4 / 9},
            states={"S0": 10.0},
            approximation=num_app,
            id="ps",
        )
        splitter = Splitter(weight=[[0.9], [0.1]], direction=[[0], [0]], id="spl")
        uh1 = UnitHydrograph1(parameters={"lag-time": x4}, states={"lag": None}, id="uh1")
        uh2 = UnitHydrograph2(parameters={"lag-time": 2 * x4}, states={"lag": None}, id="uh2")
        routing_store = RoutingStore(
            parameters={"x2": x2, "x3": x3, "gamma": 5.0, "omega": 3.5},
            states={"S0": 10.0},
            approximation=num_app,
            id="rs",
        )
        transparent = Transparent(id="tr")
        junction = Junction(direction=[[0, None], [1, None], [None, 0]], id="jun")
        flux_agg = FluxAggregator(id="fa")

        model = Unit(
            layers=[
                [interception_filter],
                [production_store],
                [splitter],
                [uh1, uh2],
                [routing_store, transparent],
                [junction],
                [flux_agg],
            ],
            id="gr4j",
        )
        input_order = "PET,P"

    elif model_type == "hbv":
        from superflexpy.framework.unit import Unit
        from superflexpy.implementation.elements.hbv import PowerReservoir, UnsaturatedReservoir

        ur = UnsaturatedReservoir(
            parameters={"Smax": 200.0, "Ce": 1.0, "m": 0.01, "beta": 2.0},
            states={"S0": 10.0},
            approximation=num_app,
            id="ur",
        )
        fr = PowerReservoir(
            parameters={"k": 0.05, "alpha": 2.5},
            states={"S0": 0.0},
            approximation=num_app,
            id="fr",
        )

        model = Unit(layers=[[ur], [fr]], id="hbv")
        input_order = "P,PET"

    elif model_type == "hymod":
        from superflexpy.implementation.models.hymod import model

        input_order = "P,PET"

    else:
        print(json.dumps({"status": "error", "errors": ["Custom model not yet supported via CLI"]}))
        sys.exit(1)

    return model, input_order


def process(args):
    """Load forcing, run model, collect outputs."""

    # Load forcing data
    with open(args.forcing, "r") as f:
        forcing = json.load(f)

    if forcing.get("status") != "success":
        return {"status": "error", "errors": ["Forcing file indicates error status"]}

    P = np.array(forcing["P"])
    PET = np.array(forcing["PET"])
    n_timesteps = len(P)

    # Build model
    model, input_order = build_model(args)

    # Set timestep
    model.set_timestep(args.timestep)

    # Override parameters if provided
    if args.params:
        param_names = model.get_parameters_name()
        for kv in args.params:
            key, val = kv.split("=")
            # Find the full prefixed name
            matched = [pn for pn in param_names if pn.endswith(key)]
            if matched:
                model.set_parameters({matched[0]: float(val)})
                print(f"Set {matched[0]} = {val}", file=sys.stderr)
            else:
                print(f"WARNING: Parameter '{key}' not found in model", file=sys.stderr)

    # Prepare input arrays
    if input_order == "PET,P":
        inputs = [PET, P]
    else:
        inputs = [P, PET]

    model.set_input(inputs)

    # Run simulation
    t_start = time.time()
    try:
        Q = model.get_output()
        t_elapsed = time.time() - t_start
    except Exception as e:
        return {
            "status": "error",
            "errors": [f"Model execution failed: {str(e)}"],
        }

    # Collect outputs
    Q_sim = Q[0] if isinstance(Q, list) else Q
    if isinstance(Q_sim, np.ndarray):
        Q_sim = Q_sim.tolist()

    # Get final states
    states = model.get_states()
    states_serializable = {k: float(v) if np.isscalar(v) else float(v) for k, v in states.items()}

    result = {
        "status": "success",
        "model": args.model,
        "n_timesteps": n_timesteps,
        "timestep_d": args.timestep,
        "solver": args.solver,
        "architecture": args.architecture,
        "runtime_s": round(t_elapsed, 3),
        "output_units": {"Q": "mm/d"},
        "Q_sim": Q_sim,
        "statistics": {
            "Q_mean": float(np.mean(Q_sim)),
            "Q_max": float(np.max(Q_sim)),
            "Q_min": float(np.min(Q_sim)),
            "Q_total": float(np.sum(Q_sim)),
            "P_total": float(np.sum(P)),
            "runoff_ratio": float(np.sum(Q_sim) / max(np.sum(P), 1e-10)),
        },
        "final_states": states_serializable,
    }

    # Include dates if available
    if "dates" in forcing:
        result["dates"] = forcing["dates"]

    # Include observed Q for comparison
    if "Q_obs" in forcing:
        result["Q_obs"] = forcing["Q_obs"]

    return result


def validate_outputs(result):
    """Validate model outputs for common problems."""
    if result["status"] != "success":
        return result

    warnings = []
    Q = np.array(result["Q_sim"])

    # Check for negative streamflow (dt_010)
    if np.any(Q < 0):
        n_neg = int(np.sum(Q < 0))
        warnings.append(
            f"WARNING: {n_neg} negative Q values detected — "
            "may indicate explicit solver instability (dt_010)"
        )

    # Check for NaN
    if np.any(np.isnan(Q)):
        warnings.append("WARNING: NaN values in simulated Q — solver may have diverged")

    # Check runoff ratio
    rr = result["statistics"]["runoff_ratio"]
    if rr > 1.5:
        warnings.append(
            f"WARNING: Runoff ratio = {rr:.2f} > 1.5 — "
            "model is generating more water than it receives"
        )
    if rr < 0.01:
        warnings.append(
            f"WARNING: Runoff ratio = {rr:.4f} — "
            "almost no runoff generated, check parameters"
        )

    # Check for unrealistic peaks
    if np.max(Q) > 1000:
        warnings.append(
            f"WARNING: Max Q = {np.max(Q):.1f} mm/d seems extreme — "
            "check input units and parameters"
        )

    if warnings:
        result["warnings"] = warnings
        for w in warnings:
            print(w, file=sys.stderr)

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Execute SuperflexPy model and save outputs"
    )
    parser.add_argument("--model", type=str, required=True, help="Model type: gr4j, hbv, hymod")
    parser.add_argument("--forcing", type=str, required=True, help="Path to forcing JSON file")
    parser.add_argument("--output", type=str, default=None, help="Output JSON file path")
    parser.add_argument("--timestep", type=float, default=1.0, help="Timestep in days")
    parser.add_argument("--solver", type=str, default="implicit_euler", help="ODE solver")
    parser.add_argument("--architecture", type=str, default="python", help="python or numba")
    parser.add_argument("--params", nargs="*", default=None, help="Parameter overrides as key=value")

    args = parser.parse_args()

    validate_inputs(args)
    result = process(args)
    result = validate_outputs(result)

    output_json = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        with open(args.output, "w") as f:
            f.write(output_json)
        print(f"Results written to {args.output}", file=sys.stderr)
    else:
        print(output_json)


if __name__ == "__main__":
    main()
