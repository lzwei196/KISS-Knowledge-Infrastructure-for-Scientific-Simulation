#!/usr/bin/env python3
"""
run_landlab.py — Execute a Landlab landscape evolution simulation from YAML config

Reads a YAML configuration file specifying: grid setup, component selection,
parameters, boundary conditions, and time-stepping. Assembles and runs the
simulation, saving intermediate snapshots.

CRITICAL NOTES:
  - Component ORDER matters: FlowAccumulator MUST run before any erosion component.
  - All parameters must share consistent units (typically m, yr, m/yr, m²/yr).
  - Timestep must be consistent with parameter units (if K is in 1/yr, dt in yr).
  - LinearDiffuser handles CFL internally, but other explicit components may not.

Usage:
    python run_landlab.py --config config.yaml --output results/
    python run_landlab.py --config config.yaml --output results/ --save-interval 1000

Example config.yaml:
    grid:
      type: RasterModelGrid
      shape: [50, 50]
      spacing: 100.0
      boundary: open_south
    initial_topography:
      type: random
      amplitude: 1.0
      base_slope: 0.01
    components:
      flow_accumulator:
        flow_director: FlowDirectorD8
      stream_power_eroder:
        K_sp: 1.0e-5
        m_sp: 0.5
        n_sp: 1.0
      linear_diffuser:
        linear_diffusivity: 0.01
    time:
      dt: 500.0
      n_steps: 4000
      uplift_rate: 1.0e-3
    output:
      save_interval: 500
      fields: [topographic__elevation, drainage_area]
"""

import argparse
import json
import os
import sys
import time

import numpy as np
import yaml


def validate_inputs(args):
    """Validate command-line arguments and configuration."""
    errors = []

    if not os.path.exists(args.config):
        errors.append(f"Config file not found: {args.config}")
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)

    with open(args.config) as f:
        config = yaml.safe_load(f)

    # Validate required sections
    for section in ["grid", "components", "time"]:
        if section not in config:
            errors.append(f"Missing required config section: '{section}'")

    if "time" in config:
        tc = config["time"]
        if "dt" not in tc:
            errors.append("Missing 'dt' in time config")
        if "n_steps" not in tc:
            errors.append("Missing 'n_steps' in time config")

    # Validate component ordering
    if "components" in config:
        comp_names = list(config["components"].keys())
        erosion_comps = {"stream_power_eroder", "erosion_deposition", "space"}
        flow_comps = {"flow_accumulator"}
        has_erosion = any(c in erosion_comps for c in comp_names)
        has_flow = any(c in flow_comps for c in comp_names)
        if has_erosion and not has_flow:
            errors.append(
                "Erosion component present but no flow_accumulator. "
                "Erosion requires drainage_area from FlowAccumulator (dt_014)."
            )
        if has_erosion and has_flow:
            flow_idx = next(i for i, c in enumerate(comp_names) if c in flow_comps)
            erosion_idx = next(i for i, c in enumerate(comp_names) if c in erosion_comps)
            if erosion_idx < flow_idx:
                errors.append(
                    "Erosion component listed BEFORE flow_accumulator. "
                    "FlowAccumulator must run first each step (dt_014)."
                )

    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)

    return config


def process(config, output_dir, save_interval):
    """Build and run the Landlab simulation."""
    from landlab import RasterModelGrid
    from landlab.components import (
        FlowAccumulator,
        StreamPowerEroder,
        LinearDiffuser,
    )

    # --- Grid setup ---
    gc = config["grid"]
    grid_type = gc.get("type", "RasterModelGrid")

    if grid_type == "RasterModelGrid":
        shape = tuple(gc.get("shape", [50, 50]))
        spacing = gc.get("spacing", 100.0)
        mg = RasterModelGrid(shape, xy_spacing=spacing)
    else:
        raise ValueError(f"Unsupported grid type: {grid_type}")

    # --- Initial topography ---
    ic = config.get("initial_topography", {})
    topo_type = ic.get("type", "random")
    z = mg.add_zeros("topographic__elevation", at="node")

    if topo_type == "random":
        amplitude = ic.get("amplitude", 1.0)
        base_slope = ic.get("base_slope", 0.0)
        z += np.random.rand(mg.number_of_nodes) * amplitude
        z += mg.node_y * base_slope
    elif topo_type == "flat":
        z += ic.get("elevation", 0.0)
    elif topo_type == "from_file":
        filepath = ic["file"]
        data = np.loadtxt(filepath)
        z[:] = data.flatten()[:mg.number_of_nodes]

    # --- Boundary conditions ---
    bc = gc.get("boundary", "open_south")
    if bc == "open_south":
        mg.set_closed_boundaries_at_grid_edges(True, False, True, True)
    elif bc == "open_all":
        pass  # default
    elif bc == "closed_all_but_outlet":
        mg.set_closed_boundaries_at_grid_edges(True, True, True, True)
        boundary_nodes = mg.boundary_nodes
        lowest = boundary_nodes[np.argmin(z[boundary_nodes])]
        mg.status_at_node[lowest] = mg.BC_NODE_IS_FIXED_VALUE

    # --- Component instantiation ---
    cc = config["components"]
    components = []
    component_names = []

    for comp_name, comp_params in cc.items():
        params = comp_params or {}

        if comp_name == "flow_accumulator":
            comp = FlowAccumulator(mg, **params)
        elif comp_name == "stream_power_eroder":
            comp = StreamPowerEroder(mg, **params)
        elif comp_name == "linear_diffuser":
            comp = LinearDiffuser(mg, **params)
        else:
            # Try dynamic import
            try:
                from landlab.components import _COMPONENT_REGISTRY
                cls = None
                for registered_cls in _COMPONENT_REGISTRY:
                    if registered_cls.__name__.lower().replace("_", "") == \
                       comp_name.lower().replace("_", ""):
                        cls = registered_cls
                        break
                if cls:
                    comp = cls(mg, **params)
                else:
                    print(f"WARNING: Unknown component '{comp_name}', skipping",
                          file=sys.stderr)
                    continue
            except Exception as e:
                print(f"WARNING: Could not instantiate '{comp_name}': {e}",
                      file=sys.stderr)
                continue

        components.append(comp)
        component_names.append(comp_name)

    # --- Time stepping ---
    tc = config["time"]
    dt = tc["dt"]
    n_steps = tc["n_steps"]
    uplift_rate = tc.get("uplift_rate", 0.0)

    # Output configuration
    oc = config.get("output", {})
    save_fields = oc.get("fields", ["topographic__elevation"])
    if save_interval is None:
        save_interval = oc.get("save_interval", n_steps)

    os.makedirs(output_dir, exist_ok=True)

    # --- Main simulation loop ---
    t_start = time.time()
    core_nodes = mg.core_nodes
    snapshots_saved = 0

    for step in range(n_steps):
        # Apply uplift to core nodes
        if uplift_rate > 0:
            z[core_nodes] += uplift_rate * dt

        # Run all components in order
        for comp_name, comp in zip(component_names, components):
            if comp_name == "flow_accumulator":
                comp.run_one_step()
            else:
                comp.run_one_step(dt)

        # Save snapshot
        if (step + 1) % save_interval == 0 or step == n_steps - 1:
            snapshot = {"step": step + 1, "time": (step + 1) * dt}
            for field_name in save_fields:
                if field_name in mg.at_node:
                    snapshot[field_name] = {
                        "min": float(np.min(mg.at_node[field_name][core_nodes])),
                        "max": float(np.max(mg.at_node[field_name][core_nodes])),
                        "mean": float(np.mean(mg.at_node[field_name][core_nodes])),
                    }

            snap_path = os.path.join(output_dir, f"snapshot_{step+1:06d}.json")
            with open(snap_path, "w") as f:
                json.dump(snapshot, f, indent=2)
            snapshots_saved += 1

    t_elapsed = time.time() - t_start

    # Save final grid state
    final_path = os.path.join(output_dir, "final_grid.npz")
    save_dict = {}
    for field_name in save_fields:
        if field_name in mg.at_node:
            save_dict[field_name] = mg.at_node[field_name]
    save_dict["x_of_node"] = mg.x_of_node
    save_dict["y_of_node"] = mg.y_of_node
    np.savez(final_path, **save_dict)

    result = {
        "grid_shape": list(mg.shape),
        "n_steps": n_steps,
        "dt": dt,
        "total_time": n_steps * dt,
        "uplift_rate": uplift_rate,
        "components": component_names,
        "snapshots_saved": snapshots_saved,
        "wall_time_s": round(t_elapsed, 2),
        "final_grid": final_path,
        "output_dir": output_dir,
    }
    return result


def validate_outputs(result, config, output_dir):
    """Validate simulation outputs for physical plausibility."""
    warnings = []

    # Check that final grid exists
    if not os.path.exists(result["final_grid"]):
        warnings.append("CRITICAL: Final grid file was not written")

    # Load final snapshot and check
    final_snap = os.path.join(output_dir, f"snapshot_{result['n_steps']:06d}.json")
    if os.path.exists(final_snap):
        with open(final_snap) as f:
            snap = json.load(f)
        if "topographic__elevation" in snap:
            elev = snap["topographic__elevation"]
            if elev["max"] - elev["min"] < 0.1:
                warnings.append(
                    "WARNING: Very low relief (<0.1 m). Simulation may not "
                    "have reached interesting dynamics."
                )
            if elev["max"] > 1e6:
                warnings.append(
                    f"WARNING: Max elevation {elev['max']:.0f} m is extreme. "
                    "Check uplift rate and time units."
                )

    if result["wall_time_s"] > 3600:
        warnings.append(
            f"WARNING: Simulation took {result['wall_time_s']:.0f}s "
            "(>1 hour). Consider coarser grid or larger dt."
        )

    return warnings


def main():
    parser = argparse.ArgumentParser(
        description="Execute Landlab landscape evolution simulation from YAML config"
    )
    parser.add_argument("--config", type=str, required=True,
                        help="Path to YAML configuration file")
    parser.add_argument("--output", type=str, required=True,
                        help="Output directory for results")
    parser.add_argument("--save-interval", type=int, default=None,
                        help="Save snapshot every N steps (default: from config)")
    args = parser.parse_args()

    config = validate_inputs(args)
    result = process(config, args.output, args.save_interval)
    warnings = validate_outputs(result, config, args.output)

    result["warnings"] = warnings
    result["status"] = "success"
    print(json.dumps(result, indent=2), file=sys.stderr)


if __name__ == "__main__":
    main()
