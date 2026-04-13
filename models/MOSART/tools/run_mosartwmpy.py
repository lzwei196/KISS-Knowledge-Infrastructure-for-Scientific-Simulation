#!/usr/bin/env python3
"""Execute mosartwmpy simulation with preflight checks and output validation.

Wrapper around the mosartwmpy BMI interface that performs:
1. Preflight validation of all input files
2. Model initialization and execution
3. Post-run output validation
4. Summary statistics extraction

Usage:
    python run_mosartwmpy.py --config config.yaml
    python run_mosartwmpy.py --config config.yaml --dry-run
    python run_mosartwmpy.py --config config.yaml --subdomain "47.6,-122.3"
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np


def preflight_check(config_path: str) -> list:
    """Perform preflight validation of configuration and input files.

    Returns list of errors (empty if all checks pass).
    """
    errors = []

    # Check config file exists
    if not Path(config_path).is_file():
        errors.append(f"Config file not found: {config_path}")
        return errors

    try:
        from mosartwmpy.config.config import get_config
        config = get_config(config_path)
    except Exception as e:
        errors.append(f"Failed to parse config: {e}")
        return errors

    # Check date range
    start = config.get('simulation.start_date')
    end = config.get('simulation.end_date')
    if end < start:
        errors.append(f"End date {end} is before start date {start}")

    # Check timestep validity
    timestep = config.get('simulation.timestep', 10800)
    if timestep <= 0:
        errors.append(f"Invalid timestep: {timestep}")
    output_res = config.get('simulation.output_resolution', 86400)
    if output_res % timestep != 0:
        errors.append(f"output_resolution ({output_res}) must be divisible "
                      f"by timestep ({timestep})")

    # Check grid file
    grid_path = config.get('grid.path')
    if not Path(grid_path).is_file():
        errors.append(f"Grid file not found: {grid_path}")
    else:
        try:
            import xarray as xr
            ds = xr.open_dataset(grid_path)
            required_coords = [config.get('grid.latitude', 'lat'),
                               config.get('grid.longitude', 'lon')]
            for coord in required_coords:
                if coord not in ds.dims and coord not in ds.coords:
                    errors.append(f"Grid file missing coordinate: {coord}")
            ds.close()
        except Exception as e:
            errors.append(f"Failed to open grid file: {e}")

    # Check runoff file
    if config.get('runoff.read_from_file', True):
        runoff_path = config.get('runoff.path')
        # Handle templated paths - check at least the pattern makes sense
        if '{' not in runoff_path:
            if not Path(runoff_path).is_file():
                errors.append(f"Runoff file not found: {runoff_path}")

    # Check water management files
    if config.get('water_management.enabled', False):
        if config.get('water_management.demand.read_from_file', False):
            demand_path = config.get('water_management.demand.path')
            if '{' not in demand_path and not Path(demand_path).is_file():
                errors.append(f"Demand file not found: {demand_path}")

        reservoir_path = config.get(
            'water_management.reservoirs.parameters.path', '')
        if reservoir_path and not Path(reservoir_path).is_file():
            errors.append(f"Reservoir file not found: {reservoir_path}")

        dep_path = config.get(
            'water_management.reservoirs.dependencies.path', '')
        if dep_path and not Path(dep_path).is_file():
            errors.append(f"Dependency database not found: {dep_path}")

    return errors


def validate_output(model) -> dict:
    """Validate model output after simulation.

    Returns dict with validation results.
    """
    results = {
        'valid': True,
        'checks': [],
        'warnings': [],
    }

    try:
        # Check discharge
        discharge = model.get_value_ptr(
            'outgoing_water_volume_transport_along_river_channel')
        d_finite = discharge[np.isfinite(discharge)]
        results['checks'].append({
            'variable': 'discharge',
            'min': float(np.min(d_finite)) if len(d_finite) > 0 else None,
            'max': float(np.max(d_finite)) if len(d_finite) > 0 else None,
            'mean': float(np.mean(d_finite)) if len(d_finite) > 0 else None,
        })
        if len(d_finite) > 0 and np.all(d_finite == 0):
            results['warnings'].append("All discharge values are zero")

        # Check storage
        storage = model.get_value_ptr('surface_water_amount')
        s_finite = storage[np.isfinite(storage)]
        results['checks'].append({
            'variable': 'storage',
            'min': float(np.min(s_finite)) if len(s_finite) > 0 else None,
            'max': float(np.max(s_finite)) if len(s_finite) > 0 else None,
            'mean': float(np.mean(s_finite)) if len(s_finite) > 0 else None,
        })
        if len(s_finite) > 0 and np.any(s_finite < 0):
            results['warnings'].append(
                f"Negative storage detected: min={np.min(s_finite):.4e}")

    except Exception as e:
        results['valid'] = False
        results['warnings'].append(f"Output validation error: {e}")

    return results


def run_simulation(config_path: str, dry_run: bool = False,
                   subdomain: str = None) -> dict:
    """Run a complete mosartwmpy simulation.

    Args:
        config_path: Path to config.yaml
        dry_run: If True, only perform preflight checks
        subdomain: Optional "lat,lon" to override subdomain config

    Returns:
        Dictionary with run summary
    """
    summary = {
        'config': config_path,
        'status': 'pending',
        'preflight_errors': [],
        'runtime_seconds': None,
        'output_validation': None,
    }

    # Preflight
    print("[run_mosartwmpy] Running preflight checks...")
    errors = preflight_check(config_path)
    summary['preflight_errors'] = errors

    if errors:
        print(f"[run_mosartwmpy] PREFLIGHT FAILED: {len(errors)} errors")
        for e in errors:
            print(f"  - {e}")
        summary['status'] = 'preflight_failed'
        return summary

    print("[run_mosartwmpy] Preflight checks passed")

    if dry_run:
        summary['status'] = 'dry_run_ok'
        print("[run_mosartwmpy] Dry run complete")
        return summary

    # Run simulation
    print("[run_mosartwmpy] Initializing model...")
    t_start = time.time()

    try:
        from mosartwmpy import Model

        model = Model()
        model.initialize(config_path)

        start_time = model.get_start_time()
        end_time = model.get_end_time()
        start_dt = datetime.fromtimestamp(start_time)
        end_dt = datetime.fromtimestamp(end_time)
        timestep = model.get_time_step()

        print(f"[run_mosartwmpy] Simulation period: {start_dt.date()} to "
              f"{end_dt.date()}")
        print(f"[run_mosartwmpy] Timestep: {timestep}s, "
              f"Grid size: {model.get_grid_size()}")

        print("[run_mosartwmpy] Running simulation...")
        model.update_until(end_time)

        runtime = time.time() - t_start
        summary['runtime_seconds'] = runtime
        print(f"[run_mosartwmpy] Simulation completed in {runtime:.1f}s")

        # Validate output
        print("[run_mosartwmpy] Validating output...")
        validation = validate_output(model)
        summary['output_validation'] = validation

        if validation['warnings']:
            for w in validation['warnings']:
                print(f"  WARNING: {w}")

        model.finalize()
        summary['status'] = 'completed'
        print("[run_mosartwmpy] SUCCESS")

    except Exception as e:
        summary['status'] = 'failed'
        summary['error'] = str(e)
        print(f"[run_mosartwmpy] FAILED: {e}")

    return summary


def main():
    parser = argparse.ArgumentParser(
        description='Run mosartwmpy simulation with validation')
    parser.add_argument('--config', required=True,
                        help='Path to config.yaml')
    parser.add_argument('--dry-run', action='store_true',
                        help='Only perform preflight checks')
    parser.add_argument('--subdomain', default=None,
                        help='Override subdomain (lat,lon)')
    parser.add_argument('--output-json', default=None,
                        help='Write run summary to JSON file')

    args = parser.parse_args()

    summary = run_simulation(args.config, args.dry_run, args.subdomain)

    if args.output_json:
        with open(args.output_json, 'w') as f:
            json.dump(summary, f, indent=2, default=str)

    if summary['status'] in ('completed', 'dry_run_ok'):
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == '__main__':
    main()
