#!/usr/bin/env python3
"""
run_simfire.py — Execution wrapper for SimFire wildfire simulation.

Creates or modifies a SimFire YAML config, runs the simulation via Python API,
and captures outputs (fire maps, GIF, spread graph, statistics).

CRITICAL NOTES (verified against simfire 2.0.1 source + official MITRE docs):
  - Headless mode MUST be true for server/batch runs; ALSO set
    SDL_VIDEODRIVER=dummy in the environment to suppress PyGame display init.
  - YAML wind.simple.speed is in **mph**, NOT ft/min. The loader at
    config.py:860 calls mph_to_ftpm internally. Same for
    wind.perlin.speed.range_min/max (config.py:897-901).
  - YAML wind.simple.direction is degrees clockwise from N, "TO direction"
    (90 = wind blows TOWARD east). NOT the meteorological "from" convention.
    See rothermel.py:104.
  - Moisture is a FRACTION (0.03 = 3%), not a percentage.
  - Pixel scale is in FEET per pixel (area.pixel_scale).
  - Operational area height/width is in METERS (not feet).

Output:
  - fire_map_final.npy: final burn status array (0=unburned, 1=burning, 2=burned)
  - simulation_stats.json: timing, burn area, spread rate statistics
  - simulation.gif (if record=true)
  - spread_graph.png (if draw_spread_graph=true)

Usage:
    python run_simfire.py --config configs/functional_config.yml --runtime "2h"
    python run_simfire.py --config configs/operational_config.yml --headless --runtime "6h"
    python run_simfire.py --quick-test  # Minimal functional test
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np


def validate_inputs(args):
    """Validate execution arguments.

    Checks config file existence, runtime format, output directory.
    """
    errors = []

    if not args.quick_test:
        if not args.config:
            errors.append("Must provide --config or use --quick-test")
        elif not os.path.isfile(args.config):
            errors.append(f"Config file not found: {args.config}")

    if args.runtime:
        # Validate runtime format (e.g., "1h", "30m", "1d 2h")
        valid_chars = set("0123456789dhm ")
        if not all(c in valid_chars for c in args.runtime):
            errors.append(f"Invalid runtime format '{args.runtime}'. Use e.g., '1h', '30m', '1d 2h'")

    if errors:
        print(json.dumps({"status": "error", "stage": "validate_inputs", "errors": errors}))
        sys.exit(1)


def generate_quick_test_config(output_dir):
    """Generate a minimal functional config for testing.

    Uses procedural terrain (no LandFire download needed),
    small grid, short runtime, headless mode.
    """
    config_content = """
area:
  screen_size: [50, 50]
  pixel_scale: 50

display:
  fire_size: 2
  control_line_size: 2
  agent_size: 4

simulation:
  update_rate: 1
  runtime: "30m"
  headless: true
  draw_spread_graph: false
  record: false
  save_data: false
  data_type: "npy"
  sf_home: "{sf_home}"

mitigation:
  ros_attenuation: true

terrain:
  topography:
    type: functional
    functional:
      function: flat
  fuel:
    type: functional
    functional:
      function: chaparral
      chaparral:
        seed: 42

fire:
  fire_initial_position:
    type: static
    static:
      position: (25, 25)
  max_fire_duration: 5
  diagonal_spread: true

environment:
  moisture: 0.03

wind:
  function: simple
  simple:
    speed: 7
    direction: 90.0
""".format(sf_home=os.path.join(output_dir, ".simfire"))

    config_path = os.path.join(output_dir, "quick_test_config.yml")
    with open(config_path, "w") as f:
        f.write(config_content)

    return config_path


def run_simulation(config_path, runtime=None, headless_override=None, output_dir=None):
    """Run SimFire simulation and collect results.

    Args:
        config_path: path to YAML config
        runtime: override runtime (e.g., "1h")
        headless_override: force headless mode if True
        output_dir: directory for outputs

    Returns:
        dict with fire_map, statistics, output paths
    """
    try:
        from simfire.sim.simulation import FireSimulation
        from simfire.utils.config import Config
    except ImportError as e:
        print(json.dumps({
            "status": "error",
            "errors": [f"SimFire not installed: {e}. Run: pip install simfire"]
        }))
        sys.exit(1)

    # Load config
    config = Config(config_path)

    # Override headless if requested
    if headless_override is not None:
        config.simulation.headless = headless_override

    # Create simulation
    t_start = time.time()
    sim = FireSimulation(config)

    # Run simulation
    run_duration = runtime if runtime else str(config.simulation.runtime) + "m"
    sim.run(run_duration)
    t_elapsed = time.time() - t_start

    # Collect results
    fire_map = sim.fire_map.copy()

    # Compute statistics
    total_pixels = fire_map.size
    burned = int(np.sum(fire_map == 2))     # BURNED
    burning = int(np.sum(fire_map == 1))    # BURNING
    unburned = int(np.sum(fire_map == 0))   # UNBURNED

    pixel_scale_ft = config.area.pixel_scale
    pixel_area_ft2 = pixel_scale_ft ** 2
    pixel_area_acres = pixel_area_ft2 / 43560.0  # 1 acre = 43560 ft²

    burned_area_acres = (burned + burning) * pixel_area_acres
    burned_area_ha = burned_area_acres * 0.404686  # 1 acre = 0.404686 ha

    stats = {
        "config_file": str(config_path),
        "runtime_requested": run_duration,
        "wall_time_seconds": round(t_elapsed, 2),
        "grid_shape": list(fire_map.shape),
        "pixel_scale_ft": pixel_scale_ft,
        "total_pixels": total_pixels,
        "burned_pixels": burned,
        "burning_pixels": burning,
        "unburned_pixels": unburned,
        "burned_fraction": round((burned + burning) / total_pixels, 4),
        "burned_area_acres": round(burned_area_acres, 2),
        "burned_area_ha": round(burned_area_ha, 2),
    }

    # Save outputs
    if output_dir:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        fire_map_path = out / "fire_map_final.npy"
        stats_path = out / "simulation_stats.json"

        np.save(str(fire_map_path), fire_map)
        with open(str(stats_path), "w") as f:
            json.dump(stats, f, indent=2)

        stats["fire_map_path"] = str(fire_map_path)
        stats["stats_path"] = str(stats_path)

        # Save GIF if recording was enabled
        try:
            if config.simulation.record:
                sim.save_gif()
                stats["gif_saved"] = True
        except Exception as e:
            stats["gif_error"] = str(e)

        # Save spread graph if enabled
        try:
            if config.simulation.draw_spread_graph:
                sim.save_spread_graph()
                stats["spread_graph_saved"] = True
        except Exception as e:
            stats["spread_graph_error"] = str(e)

    return stats, fire_map


def validate_outputs(stats, fire_map):
    """Post-execution validation of simulation results.

    Checks:
    - Fire actually spread (some burned pixels)
    - No numerical anomalies
    - Reasonable burn fraction for runtime
    """
    warnings = []

    if stats["burned_pixels"] == 0 and stats["burning_pixels"] == 0:
        warnings.append(
            "ZERO fire spread detected. Possible causes: "
            "(1) Fuel moisture M_f >= moisture of extinction M_x, "
            "(2) All pixels are non-burnable fuel type, "
            "(3) Wind speed is 0 and terrain is flat, "
            "(4) max_fire_duration too low."
        )

    if stats["burned_fraction"] > 0.95:
        warnings.append(
            "Over 95% of domain burned. Consider: "
            "(1) Longer domain, (2) Shorter runtime, (3) Higher moisture."
        )

    if stats["wall_time_seconds"] > 600:
        warnings.append(
            f"Simulation took {stats['wall_time_seconds']:.0f}s. "
            "Consider headless mode or smaller grid for faster runs."
        )

    return warnings


def process(args):
    """Main execution pipeline: configure → run → validate → report."""
    output_dir = args.output_dir or os.path.join(os.getcwd(), "simfire_output")

    if args.quick_test:
        config_path = generate_quick_test_config(output_dir)
        headless = True
        runtime = "30m"
    else:
        config_path = args.config
        headless = args.headless if args.headless else None
        runtime = args.runtime

    stats, fire_map = run_simulation(
        config_path, runtime=runtime,
        headless_override=headless, output_dir=output_dir,
    )

    warnings = validate_outputs(stats, fire_map)
    if warnings:
        stats["warnings"] = warnings

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Run SimFire wildfire simulation with config"
    )
    parser.add_argument("--config", type=str, default=None,
                        help="Path to SimFire YAML config file")
    parser.add_argument("--runtime", type=str, default=None,
                        help="Override simulation runtime (e.g., '1h', '30m')")
    parser.add_argument("--headless", action="store_true",
                        help="Force headless mode (no display)")
    parser.add_argument("--output-dir", type=str, default=None,
                        help="Output directory for results")
    parser.add_argument("--quick-test", action="store_true",
                        help="Run minimal functional test (no config needed)")

    args = parser.parse_args()
    validate_inputs(args)
    result = process(args)

    print(json.dumps({"status": "success", "output": result}, indent=2))


if __name__ == "__main__":
    main()
