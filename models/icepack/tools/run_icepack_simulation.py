#!/usr/bin/env python3
"""Execute an icepack glacier flow simulation.

This wrapper sets up and runs a diagnostic + prognostic simulation loop
for ice shelf, ice stream, or hybrid models. It handles mesh creation,
field interpolation, solver initialization, time-stepping, and checkpointing.

Pipeline stage: s4-s5 (diagnostic solve + prognostic solve)
Pattern: validate → process → validate
"""

import sys
import os
import json
import argparse
import logging
import time
from pathlib import Path

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def validate_inputs(config: dict) -> dict:
    """Validate simulation configuration.

    Parameters
    ----------
    config : dict
        Simulation configuration with keys:
        - model_type: 'ice_shelf', 'ice_stream', 'shallow_ice', 'hybrid'
        - mesh_type: 'rectangle', 'geojson'
        - mesh_params: dict with mesh-specific parameters
        - thickness: float or str (constant value or path to raster)
        - temperature: float (Kelvin, for rate factor computation)
        - dt: float (timestep in years)
        - num_steps: int
        - output_dir: str

    Returns
    -------
    dict
        Validated configuration.
    """
    errors = []

    valid_models = ("ice_shelf", "ice_stream", "shallow_ice", "hybrid")
    model_type = config.get("model_type", "ice_shelf")
    if model_type not in valid_models:
        errors.append(f"model_type '{model_type}' not in {valid_models}")

    T = config.get("temperature", 254.15)
    if T < 200 or T > 273.15:
        errors.append(f"Temperature {T} K out of range [200, 273.15]")

    dt = config.get("dt", 0.5)
    if dt <= 0:
        errors.append(f"dt must be positive, got {dt}")
    if dt > 10:
        logger.warning("dt = %.1f years is very large; typical range 0.01–1.0 yr", dt)

    num_steps = config.get("num_steps", 100)
    if num_steps <= 0:
        errors.append(f"num_steps must be positive, got {num_steps}")

    # IceStream and ShallowIce need surface elevation
    if model_type in ("ice_stream", "shallow_ice", "hybrid"):
        if "surface" not in config and "bed" not in config:
            logger.warning(
                "%s model needs surface elevation. Will compute from "
                "thickness + bed using flotation criterion.", model_type
            )

    if errors:
        for e in errors:
            logger.error(e)
        raise ValueError("; ".join(errors))

    logger.info(
        "Configuration validated: model=%s, T=%.1f K, dt=%.3f yr, steps=%d",
        model_type, T, dt, num_steps
    )
    return config


def setup_model(model_type: str):
    """Create the icepack physics model object.

    Parameters
    ----------
    model_type : str
        One of: 'ice_shelf', 'ice_stream', 'shallow_ice', 'hybrid'.

    Returns
    -------
    model
        An icepack model object (IceShelf, IceStream, etc.)
    """
    import icepack

    models = {
        "ice_shelf": icepack.models.IceShelf,
        "ice_stream": icepack.models.IceStream,
        "shallow_ice": icepack.models.ShallowIce,
        "hybrid": icepack.models.HybridModel,
    }
    model_cls = models[model_type]
    logger.info("Created model: %s", model_cls.__name__)
    return model_cls()


def create_mesh(mesh_config: dict):
    """Create a Firedrake mesh from configuration.

    Parameters
    ----------
    mesh_config : dict
        Mesh configuration.

    Returns
    -------
    firedrake.Mesh
    """
    import firedrake

    mesh_type = mesh_config.get("type", "rectangle")

    if mesh_type == "rectangle":
        Lx = mesh_config.get("Lx", 50e3)
        Ly = mesh_config.get("Ly", 50e3)
        nx = mesh_config.get("nx", 64)
        ny = mesh_config.get("ny", 64)
        mesh = firedrake.RectangleMesh(nx, ny, Lx, Ly)
        logger.info("Created rectangle mesh: %dx%d, %.0fx%.0f m", nx, ny, Lx, Ly)
        return mesh

    elif mesh_type == "geojson":
        import geojson
        import icepack.meshing

        geojson_path = mesh_config["geojson_path"]
        with open(geojson_path) as f:
            outline = geojson.load(f)

        lcar = mesh_config.get("lcar", 5000)
        mesh_geo = icepack.meshing.collection_to_gmsh(outline, lcar=lcar)
        msh_path = mesh_config.get("msh_path", "/tmp/glacier.msh")
        mesh_geo.write(msh_path)
        mesh = firedrake.Mesh(msh_path)
        logger.info("Created mesh from GeoJSON: %s (lcar=%d)", geojson_path, lcar)
        return mesh

    else:
        raise ValueError(f"Unsupported mesh type: {mesh_type}")


def process(config: dict) -> dict:
    """Run the icepack simulation.

    Parameters
    ----------
    config : dict
        Validated simulation configuration.

    Returns
    -------
    dict
        Simulation results including velocity/thickness time series.
    """
    import firedrake
    import icepack

    output_dir = config.get("output_dir", "./output")
    os.makedirs(output_dir, exist_ok=True)

    # Setup model
    model_type = config.get("model_type", "ice_shelf")
    model = setup_model(model_type)

    # Create mesh
    mesh_config = config.get("mesh_params", {"type": "rectangle"})
    mesh = create_mesh(mesh_config)

    # Function spaces
    degree = config.get("element_degree", 2)
    Q = firedrake.FunctionSpace(mesh, "CG", degree)
    V = firedrake.VectorFunctionSpace(mesh, "CG", degree)

    # Initialize fields
    h = firedrake.Function(Q, name="thickness")
    u = firedrake.Function(V, name="velocity")

    # Set thickness
    thickness_val = config.get("thickness", 500.0)
    if isinstance(thickness_val, (int, float)):
        Lx = mesh_config.get("Lx", 50e3)
        x, y = firedrake.SpatialCoordinate(mesh)
        dh = config.get("thickness_gradient", 100.0)
        h.interpolate(firedrake.Constant(thickness_val) - firedrake.Constant(dh) * x / Lx)
    else:
        import rasterio
        dataset = rasterio.open(thickness_val)
        h = icepack.interpolate(dataset, Q)

    # Set fluidity from temperature
    T = config.get("temperature", 254.15)
    A = firedrake.Function(Q, name="fluidity")
    A.interpolate(firedrake.Constant(icepack.rate_factor(T)))
    logger.info("Rate factor A(T=%.1f K) = %.4e MPa^-3 yr^-1", T, float(A.dat.data[0]))

    # Create solver
    dirichlet_ids = config.get("dirichlet_ids", [1])
    solver_kwargs = {"dirichlet_ids": dirichlet_ids}

    if model_type in ("ice_stream", "shallow_ice", "hybrid"):
        s = icepack.compute_surface(thickness=h, bed=firedrake.Function(Q))
        solver_kwargs["side_wall_ids"] = config.get("side_wall_ids", [])

    solver = icepack.solvers.FlowSolver(model, **solver_kwargs)

    # Diagnostic solve kwargs
    diag_kwargs = {"velocity": u, "thickness": h, "fluidity": A}
    if model_type in ("ice_stream", "shallow_ice", "hybrid"):
        diag_kwargs["surface"] = s
    if model_type == "ice_stream":
        C = firedrake.Function(Q, name="friction")
        C.interpolate(firedrake.Constant(config.get("friction", 0.01)))
        diag_kwargs["friction"] = C

    # Initial diagnostic solve
    logger.info("Running initial diagnostic solve...")
    t0 = time.time()
    u = solver.diagnostic_solve(**diag_kwargs)
    logger.info("Diagnostic solve completed in %.2f s", time.time() - t0)

    # Time stepping
    dt = config.get("dt", 0.5)
    num_steps = config.get("num_steps", 100)
    accumulation = firedrake.Function(Q, name="accumulation")
    accumulation.interpolate(firedrake.Constant(config.get("accumulation", 0.0)))

    results = {
        "times": [],
        "max_velocity": [],
        "mean_thickness": [],
        "min_thickness": [],
    }

    logger.info("Starting time stepping: %d steps of %.3f yr...", num_steps, dt)
    for step in range(num_steps):
        # Diagnostic
        diag_kwargs["velocity"] = u
        diag_kwargs["thickness"] = h
        u = solver.diagnostic_solve(**diag_kwargs)

        # Prognostic
        h = solver.prognostic_solve(
            dt, thickness=h, velocity=u, accumulation=accumulation
        )

        if model_type in ("ice_stream", "shallow_ice", "hybrid"):
            s = icepack.compute_surface(thickness=h, bed=firedrake.Function(Q))
            diag_kwargs["surface"] = s

        # Record metrics
        speed = np.sqrt(np.sum(u.dat.data_ro**2, axis=1))
        results["times"].append((step + 1) * dt)
        results["max_velocity"].append(float(speed.max()))
        results["mean_thickness"].append(float(h.dat.data_ro.mean()))
        results["min_thickness"].append(float(h.dat.data_ro.min()))

        if (step + 1) % max(1, num_steps // 10) == 0:
            logger.info(
                "Step %d/%d: t=%.1f yr, max|u|=%.1f m/yr, <h>=%.1f m",
                step + 1, num_steps, (step + 1) * dt,
                speed.max(), h.dat.data_ro.mean()
            )

    # Save results
    results_path = os.path.join(output_dir, "simulation_results.json")
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2)

    logger.info("Simulation complete. Results saved to %s", results_path)
    results["output_dir"] = output_dir
    results["results_path"] = results_path
    return results


def validate_outputs(results: dict) -> bool:
    """Validate simulation outputs for physical plausibility.

    Parameters
    ----------
    results : dict
        Simulation results.

    Returns
    -------
    bool
        True if outputs are valid.
    """
    ok = True

    max_v = results.get("max_velocity", [])
    if max_v:
        if max(max_v) > 20000:
            logger.warning(
                "Max velocity %.0f m/yr exceeds 20 km/yr — likely numerical blowup",
                max(max_v)
            )
            ok = False
        if max(max_v) < 0.001:
            logger.warning(
                "Max velocity %.6f m/yr — nearly zero. Check boundary conditions.",
                max(max_v)
            )

    min_h = results.get("min_thickness", [])
    if min_h:
        if min(min_h) < 0:
            logger.warning("Negative thickness detected — mass conservation violated")
            ok = False

    if any(np.isnan(v) for v in max_v):
        logger.error("NaN in velocity — solver diverged")
        ok = False

    if ok:
        logger.info("Output validation passed.")
    return ok


def main():
    parser = argparse.ArgumentParser(description="Run icepack glacier simulation")
    parser.add_argument("--config", required=True, help="Path to JSON config file")
    args = parser.parse_args()

    with open(args.config) as f:
        config = json.load(f)

    config = validate_inputs(config)
    results = process(config)
    valid = validate_outputs(results)

    if not valid:
        logger.error("Simulation output validation failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
