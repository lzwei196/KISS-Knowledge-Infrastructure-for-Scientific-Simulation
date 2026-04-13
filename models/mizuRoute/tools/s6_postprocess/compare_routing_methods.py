#!/usr/bin/env python3
"""compare_routing_methods.py — Run and compare multiple mizuRoute routing methods.

Executes mizuRoute with all 5 routing methods (IRF, KWT, KWE, MC, DW) on the same
basin and produces a comparison of discharge timeseries and metrics.

This is mizuRoute's unique capability in HydroCraft: method intercomparison.

Usage:
    python compare_routing_methods.py \\
        --control_template outputs/<run>/mizuroute_input/chaohe.control \\
        --exe model/mizuRoute/mizuRoute-main/route/bin/mizuroute.exe \\
        --network_nc outputs/<run>/mizuroute_input/network_topology.nc \\
        --output_dir outputs/<run>/mizuroute_comparison \\
        --obs_file data/obs/chaohe/observed.txt \\
        --methods IRF,KWE,MC
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np


METHODS = {
    'IRF': {'route_opt': 0, 'description': 'Impulse Response Function'},
    'KWT': {'route_opt': 1, 'description': 'Kinematic Wave Tracking (Lagrangian)'},
    'KWE': {'route_opt': 2, 'description': 'Kinematic Wave (Euler)'},
    'MC':  {'route_opt': 3, 'description': 'Muskingum-Cunge'},
    'DW':  {'route_opt': 4, 'description': 'Diffusive Wave'},
}


def modify_control_file(template_path, output_path, route_opt, output_dir):
    """Create a modified control file with different routing method and output dir."""
    with open(template_path, 'r') as f:
        content = f.read()

    # Replace route_opt
    content = re.sub(r'(<route_opt>\s+)\d+', rf'\g<1>{route_opt}', content)

    # Replace output_dir
    content = re.sub(r'(<output_dir>\s+).+', rf'\g<1>{output_dir}/', content)

    with open(output_path, 'w') as f:
        f.write(content)


def process(args):
    method_list = [m.strip().upper() for m in args.methods.split(',')]

    for m in method_list:
        if m not in METHODS:
            print(f"ERROR: Unknown method '{m}'. Valid: {list(METHODS.keys())}", file=sys.stderr)
            sys.exit(1)

    os.makedirs(args.output_dir, exist_ok=True)
    results = {}

    for method_name in method_list:
        method = METHODS[method_name]
        print(f"\n{'='*60}")
        print(f"Running {method_name}: {method['description']}")
        print(f"{'='*60}")

        # Create method-specific output directory
        method_outdir = os.path.join(args.output_dir, method_name)
        os.makedirs(method_outdir, exist_ok=True)

        # Create modified control file
        method_control = os.path.join(args.output_dir, f'control_{method_name}.txt')
        modify_control_file(args.control_template, method_control,
                           method['route_opt'], method_outdir)

        # Run mizuRoute
        start_time = time.time()
        try:
            result = subprocess.run(
                [args.exe, method_control],
                capture_output=True, text=True, timeout=3600,
                cwd=os.path.dirname(method_control),
            )
            elapsed = time.time() - start_time

            if result.returncode != 0:
                print(f"  FAILED (exit code {result.returncode})")
                if 'CFL' in result.stderr or 'CFL' in result.stdout:
                    print(f"  CFL violation — {method_name} may need smaller dt (dt_m009)")
                results[method_name] = {
                    'status': 'failed',
                    'returncode': result.returncode,
                    'elapsed_seconds': elapsed,
                    'error': result.stderr[:500],
                }
                continue

            print(f"  Completed in {elapsed:.1f}s")

            # Extract discharge at outlet
            from extract_discharge import find_outlet_reach, extract_timeseries

            outlet_id = find_outlet_reach(args.network_nc)
            times, discharge = extract_timeseries(method_outdir, outlet_id)

            results[method_name] = {
                'status': 'success',
                'route_opt': method['route_opt'],
                'elapsed_seconds': round(elapsed, 1),
                'mean_Q': round(float(np.nanmean(discharge)), 2),
                'max_Q': round(float(np.nanmax(discharge)), 2),
                'n_timesteps': len(times),
            }

            # Save timeseries CSV
            csv_path = os.path.join(args.output_dir, f'discharge_{method_name}.csv')
            with open(csv_path, 'w') as f:
                f.write('date,discharge_m3s\n')
                for t, q in zip(times, discharge):
                    date_str = t.strftime('%Y-%m-%d') if hasattr(t, 'strftime') else str(t)[:10]
                    f.write(f'{date_str},{q:.4f}\n')

            results[method_name]['csv_file'] = csv_path

        except subprocess.TimeoutExpired:
            elapsed = time.time() - start_time
            print(f"  TIMEOUT after {elapsed:.0f}s")
            results[method_name] = {
                'status': 'timeout',
                'elapsed_seconds': elapsed,
            }
        except Exception as e:
            elapsed = time.time() - start_time
            print(f"  ERROR: {e}")
            results[method_name] = {
                'status': 'error',
                'elapsed_seconds': elapsed,
                'error': str(e),
            }

    # Summary
    print(f"\n{'='*60}")
    print("COMPARISON SUMMARY")
    print(f"{'='*60}")
    print(f"{'Method':<8} {'Status':<10} {'Time(s)':<10} {'Mean Q':<12} {'Max Q':<12}")
    print("-" * 52)
    for m in method_list:
        r = results.get(m, {})
        status = r.get('status', 'unknown')
        elapsed = r.get('elapsed_seconds', 0)
        mean_q = r.get('mean_Q', '-')
        max_q = r.get('max_Q', '-')
        print(f"{m:<8} {status:<10} {elapsed:<10.1f} {str(mean_q):<12} {str(max_q):<12}")

    return {
        'methods_run': method_list,
        'results': results,
        'output_dir': args.output_dir,
    }


def main():
    parser = argparse.ArgumentParser(description='Compare mizuRoute routing methods')
    parser.add_argument('--control_template', required=True, help='Template control file')
    parser.add_argument('--exe', required=True, help='mizuroute.exe path')
    parser.add_argument('--network_nc', required=True, help='Network topology NetCDF')
    parser.add_argument('--output_dir', required=True, help='Output directory')
    parser.add_argument('--obs_file', default=None, help='Observed discharge')
    parser.add_argument('--methods', default='IRF,KWE,MC',
                       help='Comma-separated list of methods (default: IRF,KWE,MC)')

    args = parser.parse_args()

    try:
        result = process(args)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == '__main__':
    main()
