#!/usr/bin/env python3
"""
SimPEG KI Tool — Execution Wrapper (Stage S5-S6)

Runs SimPEG forward modeling or inversion using configuration files
produced by build_mesh.py and initialize_model.py.

Usage (forward):
    python run_simpeg.py \
        --mode forward \
        --method gravity \
        --mesh-config mesh_config.json \
        --model-config model_config.json \
        --output results/

Usage (inversion):
    python run_simpeg.py \
        --mode inversion \
        --method gravity \
        --mesh-config mesh_config.json \
        --model-config model_config.json \
        --data-file gravity_data.csv \
        --relative-error 0.05 \
        --noise-floor 0.001 \
        --max-iter 30 \
        --output results/

UNIT TRAPS:
    - data-file units must match the method:
        gravity  → mGal (1e-5 m/s^2)
        magnetics → nT (1e-9 T)
        dc → apparent resistivity (Ohm-m) or voltage (V)
    - relative-error is a fraction (0.05 = 5%), NOT a percentage
    - noise-floor has same units as data
    - Setting noise-floor=0 causes data misfit to blow up on near-zero data
"""

import argparse
import json
import os
import sys
import time

import numpy as np


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

SUPPORTED_METHODS = [
    "gravity", "magnetics", "dc", "ip", "fdem", "tdem", "mt", "seismic", "flow"
]

SUPPORTED_MODES = ["forward", "inversion"]


def validate_inputs(args):
    """Validate all inputs before execution."""
    errors = []

    if args.mode not in SUPPORTED_MODES:
        errors.append(f"Mode must be one of {SUPPORTED_MODES}, got '{args.mode}'")

    if args.method not in SUPPORTED_METHODS:
        errors.append(f"Method must be one of {SUPPORTED_METHODS}")

    if not os.path.isfile(args.mesh_config):
        errors.append(f"Mesh config not found: {args.mesh_config}")

    if not os.path.isfile(args.model_config):
        errors.append(f"Model config not found: {args.model_config}")

    if args.mode == "inversion":
        if not args.data_file:
            errors.append("Inversion mode requires --data-file")
        elif not os.path.isfile(args.data_file):
            errors.append(f"Data file not found: {args.data_file}")

        if args.relative_error <= 0:
            errors.append(
                f"relative-error must be > 0, got {args.relative_error}. "
                f"Use fraction, e.g., 0.05 for 5%."
            )
        if args.relative_error >= 1.0:
            errors.append(
                f"relative-error={args.relative_error} looks like a percentage. "
                f"Use fraction: 0.05, not 5."
            )

        if args.noise_floor < 0:
            errors.append(f"noise-floor must be >= 0, got {args.noise_floor}")
        if args.noise_floor == 0:
            errors.append(
                "noise-floor=0 will cause infinite weight on near-zero data. "
                "Set a small positive value."
            )

    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)


# ---------------------------------------------------------------------------
# Mesh and model reconstruction from configs
# ---------------------------------------------------------------------------

def reconstruct_mesh(mesh_config):
    """Reconstruct a discretize mesh from config dict.

    Returns (mesh, active_cells) tuple.
    """
    try:
        from discretize import TensorMesh
    except ImportError:
        raise ImportError(
            "discretize is required: pip install discretize"
        )

    mc = mesh_config["mesh"]
    mesh = TensorMesh(
        [np.array(mc["hx"]), np.array(mc["hy"]), np.array(mc["hz"])],
        origin=mc["origin"],
    )

    # Active cells: all cells if no topography
    active_cells = np.ones(mesh.n_cells, dtype=bool)
    return mesh, active_cells


def reconstruct_model(model_config, mesh):
    """Reconstruct starting model and maps from config dict.

    Returns (m0, model_map, bounds) tuple.
    """
    from simpeg import maps

    mc = model_config
    n_active = mc["n_active"]

    # Load starting model
    m0_file = mc.get("starting_model_file")
    if m0_file and os.path.isfile(m0_file):
        m0 = np.load(m0_file)
    else:
        m0 = np.ones(n_active) * mc["background_si"]

    # Build map chain
    map_type = mc["map_type"]
    active_cells = np.ones(mesh.n_cells, dtype=bool)

    if map_type == "log":
        air_val = np.log(1e-8) if mc["property"] == "conductivity" else 0.0
        model_map = (
            maps.ExpMap(nP=n_active)
            * maps.InjectActiveCells(mesh, active_cells, air_val)
        )
    elif map_type == "reciprocal":
        model_map = (
            maps.ReciprocalMap(nP=n_active)
            * maps.InjectActiveCells(mesh, active_cells, 1e8)
        )
    else:
        air_val = 0.0
        model_map = maps.InjectActiveCells(mesh, active_cells, air_val)

    # Bounds
    bounds = None
    if mc.get("bounds"):
        lo, hi = mc["bounds"]
        bounds = [lo, hi]

    return m0, model_map, bounds


# ---------------------------------------------------------------------------
# Survey and simulation setup
# ---------------------------------------------------------------------------

def build_simulation(method, mesh, model_map, survey_config, active_cells):
    """Build the appropriate SimPEG simulation for the given method.

    Returns (simulation, survey) tuple.
    """
    receiver_locs = np.array(survey_config["receiver_locations"])

    if method == "gravity":
        from simpeg.potential_fields import gravity

        receivers = gravity.receivers.Point(receiver_locs, components="gz")
        source = gravity.sources.SourceField(receiver_list=[receivers])
        survey = gravity.survey.Survey(source_list=[source])
        sim = gravity.simulation.Simulation3DIntegral(
            mesh,
            survey=survey,
            rhoMap=model_map,
            active_cells=active_cells,
            store_sensitivities="forward_only",
        )

    elif method == "magnetics":
        from simpeg.potential_fields import magnetics

        receivers = magnetics.receivers.Point(receiver_locs, components="tmi")
        inducing = survey_config.get("inducing_field", {})
        source = magnetics.sources.UniformBackgroundField(
            receiver_list=[receivers],
            amplitude=inducing.get("amplitude", 50000.0),
            inclination=inducing.get("inclination", 60.0),
            declination=inducing.get("declination", 0.0),
        )
        survey = magnetics.survey.Survey(source_list=[source])
        sim = magnetics.simulation.Simulation3DIntegral(
            mesh,
            survey=survey,
            chiMap=model_map,
            active_cells=active_cells,
            store_sensitivities="forward_only",
        )

    elif method == "dc":
        from simpeg.electromagnetics.static import resistivity as dc

        # Simplified: single dipole-dipole pair
        source_list = []
        n = len(receiver_locs)
        for i in range(0, min(n - 3, 50)):
            rx = dc.receivers.Dipole(
                receiver_locs[i + 2:i + 3],
                receiver_locs[i + 3:i + 4] if i + 4 <= n else receiver_locs[i + 2:i + 3],
            )
            src = dc.sources.Dipole(
                [rx],
                location_a=receiver_locs[i],
                location_b=receiver_locs[i + 1],
            )
            source_list.append(src)

        if not source_list:
            raise ValueError("Not enough stations for DC survey (need >= 4)")

        survey = dc.survey.Survey(source_list)
        sim = dc.simulation.Simulation3DNodal(
            mesh, survey=survey, sigmaMap=model_map
        )

    else:
        raise NotImplementedError(
            f"Method '{method}' builder not yet implemented in KI wrapper. "
            f"Use the SimPEG API directly."
        )

    return sim, survey


# ---------------------------------------------------------------------------
# Forward modeling
# ---------------------------------------------------------------------------

def run_forward(sim, m0, output_dir):
    """Run forward simulation and save predicted data."""
    os.makedirs(output_dir, exist_ok=True)

    t0 = time.time()
    dpred = sim.dpred(m0)
    elapsed = time.time() - t0

    np.save(os.path.join(output_dir, "dpred.npy"), dpred)
    np.savetxt(os.path.join(output_dir, "dpred.csv"), dpred, delimiter=",",
               header="predicted_data")

    return {
        "n_data": len(dpred),
        "data_min": float(np.min(dpred)),
        "data_max": float(np.max(dpred)),
        "data_mean": float(np.mean(dpred)),
        "elapsed_s": round(elapsed, 2),
    }


# ---------------------------------------------------------------------------
# Inversion
# ---------------------------------------------------------------------------

def run_inversion(sim, m0, data_file, rel_error, noise_floor,
                  max_iter, max_iter_cg, bounds, mesh, active_cells,
                  output_dir):
    """Run SimPEG inversion and save results."""
    from simpeg import (
        data as simpeg_data,
        data_misfit,
        regularization,
        optimization,
        inverse_problem,
        inversion,
        directives,
    )

    os.makedirs(output_dir, exist_ok=True)

    # Load observed data
    dobs = np.loadtxt(data_file, delimiter=",", skiprows=1).ravel()
    if len(dobs) != sim.survey.nD:
        raise ValueError(
            f"Data length ({len(dobs)}) != survey nD ({sim.survey.nD}). "
            f"Check that data file matches survey geometry."
        )

    # Create data object with uncertainties
    data_obj = simpeg_data.Data(
        sim.survey,
        dobs=dobs,
        relative_error=rel_error,
        noise_floor=noise_floor,
    )

    # Data misfit
    dmis = data_misfit.L2DataMisfit(data=data_obj, simulation=sim)

    # Regularization
    reg = regularization.WeightedLeastSquares(
        mesh, active_cells=active_cells
    )

    # Optimization
    if bounds:
        opt = optimization.ProjectedGNCG(
            maxIter=max_iter,
            maxIterCG=max_iter_cg,
            upper=bounds[1],
            lower=bounds[0],
        )
    else:
        opt = optimization.InexactGaussNewton(
            maxIter=max_iter,
            maxIterCG=max_iter_cg,
        )

    # Inverse problem
    inv_prob = inverse_problem.BaseInvProblem(dmis, reg, opt)

    # Directives
    directive_list = directives.DirectiveList(
        directives.BetaEstimate_ByEig(beta0_ratio=1e0),
        directives.TargetMisfit(),
        directives.BetaSchedule(coolingFactor=5, coolingRate=1),
    )

    # Run inversion
    inv = inversion.BaseInversion(inv_prob, directiveList=directive_list)

    t0 = time.time()
    m_recovered = inv.run(m0)
    elapsed = time.time() - t0

    # Save results
    np.save(os.path.join(output_dir, "m_recovered.npy"), m_recovered)
    dpred = sim.dpred(m_recovered)
    np.save(os.path.join(output_dir, "dpred.npy"), dpred)

    # Compute convergence metrics
    residual = dobs - dpred
    phi_d = float(np.sum((residual / data_obj.standard_deviation) ** 2))
    rms = float(np.sqrt(np.mean(residual ** 2)))
    r_squared = float(1 - np.sum(residual ** 2) / np.sum((dobs - np.mean(dobs)) ** 2))

    # Save convergence log
    convergence = {
        "phi_d_final": phi_d,
        "n_data": len(dobs),
        "target_misfit": float(len(dobs)),
        "rms_misfit": rms,
        "r_squared": r_squared,
        "elapsed_s": round(elapsed, 2),
        "n_iterations": opt.iter,
    }

    np.savetxt(os.path.join(output_dir, "dpred.csv"), dpred, delimiter=",",
               header="predicted_data")
    np.savetxt(os.path.join(output_dir, "residuals.csv"), residual, delimiter=",",
               header="residual")

    with open(os.path.join(output_dir, "convergence.json"), "w") as f:
        json.dump(convergence, f, indent=2)

    return convergence


# ---------------------------------------------------------------------------
# Output validation
# ---------------------------------------------------------------------------

def validate_outputs(output_dir, mode):
    """Verify outputs exist and are reasonable."""
    warnings = []

    dpred_path = os.path.join(output_dir, "dpred.npy")
    if not os.path.isfile(dpred_path):
        warnings.append("Predicted data file not created")
        return warnings

    dpred = np.load(dpred_path)
    if np.any(np.isnan(dpred)):
        warnings.append(
            "Predicted data contains NaN — likely numerical instability. "
            "Check mesh quality and model bounds."
        )
    if np.any(np.isinf(dpred)):
        warnings.append(
            "Predicted data contains Inf — likely singular system. "
            "Check conductivity air values (dt_009)."
        )

    if mode == "inversion":
        conv_path = os.path.join(output_dir, "convergence.json")
        if os.path.isfile(conv_path):
            with open(conv_path) as f:
                conv = json.load(f)
            if conv.get("phi_d_final", 0) > 10 * conv.get("n_data", 1):
                warnings.append(
                    f"Final phi_d ({conv['phi_d_final']:.1f}) >> n_data "
                    f"({conv['n_data']}) — inversion did not converge. "
                    f"Try increasing max_iter or adjusting beta0_ratio."
                )
            if conv.get("r_squared", 0) < 0:
                warnings.append(
                    "R^2 < 0 — model is worse than mean. Check data "
                    "uncertainties and starting model."
                )

    return warnings


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def process(args):
    """Main execution pipeline."""
    # Load configs
    with open(args.mesh_config) as f:
        mesh_config = json.load(f)
    with open(args.model_config) as f:
        model_config = json.load(f)

    # Reconstruct mesh and model
    mesh, active_cells = reconstruct_mesh(mesh_config)
    m0, model_map, bounds_from_config = reconstruct_model(model_config, mesh)

    # Use CLI bounds if provided, else config bounds
    bounds = None
    if args.bounds:
        bounds = [float(x) for x in args.bounds.split(",")]
    elif bounds_from_config:
        bounds = bounds_from_config

    # Build simulation
    sim, survey = build_simulation(
        args.method, mesh, model_map,
        mesh_config["survey"], active_cells
    )

    # Execute
    output_dir = args.output
    if args.mode == "forward":
        metrics = run_forward(sim, m0, output_dir)
    else:
        metrics = run_inversion(
            sim, m0, args.data_file,
            args.relative_error, args.noise_floor,
            args.max_iter, args.max_iter_cg,
            bounds, mesh, active_cells, output_dir,
        )

    # Validate outputs
    warnings = validate_outputs(output_dir, args.mode)

    result = {
        "status": "success",
        "mode": args.mode,
        "method": args.method,
        "output_dir": output_dir,
        "metrics": metrics,
    }
    if warnings:
        result["warnings"] = warnings

    print(json.dumps(result, indent=2))


def main():
    parser = argparse.ArgumentParser(
        description="SimPEG KI — Execution Wrapper (Stages S5-S6)"
    )
    parser.add_argument("--mode", required=True, choices=SUPPORTED_MODES)
    parser.add_argument("--method", required=True, choices=SUPPORTED_METHODS)
    parser.add_argument("--mesh-config", required=True)
    parser.add_argument("--model-config", required=True)
    parser.add_argument("--data-file", default=None)
    parser.add_argument("--relative-error", type=float, default=0.05)
    parser.add_argument("--noise-floor", type=float, default=0.001)
    parser.add_argument("--max-iter", type=int, default=30)
    parser.add_argument("--max-iter-cg", type=int, default=30)
    parser.add_argument("--bounds", default=None, help="'lo,hi'")
    parser.add_argument("--output", default="results/")

    args = parser.parse_args()
    validate_inputs(args)
    process(args)


if __name__ == "__main__":
    main()
