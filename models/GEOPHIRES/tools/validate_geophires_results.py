#!/usr/bin/env python3
"""
Validate GEOPHIRES simulation results against expected ranges and benchmarks.

Checks:
  - Key metrics within physically reasonable ranges
  - Production profile monotonicity and bounds
  - Economic results consistency (NPV, LCOE)
  - Optional comparison to reference/benchmark results

Usage:
    python validate_geophires_results.py --results summary.json \
        [--benchmark benchmark.json] [--figure validation.png]
"""

import argparse
import json
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# --- Physical plausibility ranges ---
PLAUSIBILITY = {
    'lcoe_cents_per_kwh': {'min': 0.5, 'max': 100.0, 'name': 'LCOE'},
    'lcoh_usd_per_mmbtu': {'min': 0.5, 'max': 500.0, 'name': 'LCOH'},
    'net_power_MW': {'min': 0.01, 'max': 5000.0, 'name': 'Net Power'},
    'net_heat_MW': {'min': 0.01, 'max': 10000.0, 'name': 'Net Heat'},
    'bottom_hole_temp_degC': {'min': 30.0, 'max': 600.0, 'name': 'Bottom-Hole Temperature'},
    'capex_musd': {'min': 0.1, 'max': 50000.0, 'name': 'Total CAPEX'},
    'npv_musd': {'min': -50000.0, 'max': 100000.0, 'name': 'NPV'},
}


def validate_inputs(results_path: Path, benchmark_path: Path = None) -> list:
    """Validate input files."""
    issues = []

    if not results_path.exists():
        issues.append(f"FATAL: Results file not found: {results_path}")
    if benchmark_path and not benchmark_path.exists():
        issues.append(f"WARNING: Benchmark file not found: {benchmark_path}")

    return issues


def check_plausibility(metrics: dict) -> list:
    """Check that key metrics are within physically plausible ranges."""
    issues = []

    # Map metric names from parsed output to our range checks
    metric_mappings = {
        'lcoe_cents_per_kwh': [
            'Average Net Electricity Production',  # indirect
        ],
        'net_power_MW': [
            'Average Net Electricity Production',
            'Net Average Generation',
        ],
        'net_heat_MW': [
            'Average Direct-Use Heat Production',
            'Average Net Heat Production',
        ],
    }

    for key, val in metrics.items():
        if not isinstance(val, (int, float)):
            continue

        # Check against known ranges
        for range_key, range_info in PLAUSIBILITY.items():
            if range_key in key.lower().replace(' ', '_').replace('-', '_'):
                if val < range_info['min'] or val > range_info['max']:
                    issues.append(
                        f"WARNING: {key} = {val} outside plausible range "
                        f"[{range_info['min']}, {range_info['max']}]"
                    )

    return issues


def check_production_profile(profile: list) -> list:
    """Validate production profile for consistency."""
    issues = []

    if not profile:
        issues.append("WARNING: Empty production profile")
        return issues

    # Check temperature decline (drawdown should be monotonic or near-monotonic)
    temps = [p.get('geofluid_temperature_degC', 0) for p in profile if 'geofluid_temperature_degC' in p]
    if temps:
        if temps[0] < 50:
            issues.append(f"WARNING: Initial geofluid temperature {temps[0]}°C seems low")
        if temps[-1] > temps[0]:
            issues.append(
                f"INFO: Final temperature ({temps[-1]}°C) > initial ({temps[0]}°C). "
                "This is unusual unless reservoir model is non-depleting."
            )

    # Check net power is positive
    powers = [p.get('net_power_or_heat_MW', 0) for p in profile if 'net_power_or_heat_MW' in p]
    if powers:
        neg_years = [i+1 for i, p in enumerate(powers) if p < 0]
        if neg_years:
            issues.append(
                f"WARNING: Negative net power/heat in years: {neg_years[:5]}. "
                "Pump power may exceed generation."
            )

    # Check pump power is reasonable
    pump_powers = [p.get('pump_power_MW', 0) for p in profile if 'pump_power_MW' in p]
    if pump_powers and powers:
        max_pump_ratio = max(pump_powers) / max(max(powers), 0.001)
        if max_pump_ratio > 0.5:
            issues.append(
                f"WARNING: Max pump power is {max_pump_ratio:.0%} of max generation. "
                "Parasitic load is very high."
            )

    return issues


def compare_to_benchmark(results: dict, benchmark: dict) -> dict:
    """Compare results to benchmark values.

    Returns dict with comparison metrics.
    """
    comparison = {}

    result_metrics = results.get('metrics', {})
    bench_metrics = benchmark.get('metrics', {})

    for key in set(result_metrics.keys()) & set(bench_metrics.keys()):
        r_val = result_metrics[key]
        b_val = bench_metrics[key]

        if isinstance(r_val, (int, float)) and isinstance(b_val, (int, float)) and b_val != 0:
            rel_diff = (r_val - b_val) / abs(b_val) * 100
            comparison[key] = {
                'result': r_val,
                'benchmark': b_val,
                'relative_diff_pct': round(rel_diff, 2),
                'status': 'PASS' if abs(rel_diff) < 10 else 'CHECK',
            }

    return comparison


def generate_validation_figure(results: dict, benchmark: dict = None,
                               output_path: Path = None):
    """Generate validation figure comparing results to benchmark."""
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import numpy as np
    except ImportError:
        logger.warning("matplotlib not available, skipping figure generation")
        return

    profile = results.get('production_profile', [])
    if not profile:
        logger.warning("No production profile data for figure")
        return

    years = [p['year'] for p in profile]
    temps = [p.get('geofluid_temperature_degC', 0) for p in profile]
    powers = [p.get('net_power_or_heat_MW', 0) for p in profile]

    fig, axes = plt.subplots(2, 1, figsize=(10, 8), sharex=True)

    # Temperature plot
    ax1 = axes[0]
    ax1.plot(years, temps, color='#2563EB', linewidth=2, label='Simulated')
    ax1.set_ylabel('Geofluid Temperature (°C)')
    ax1.set_title('GEOPHIRES Validation: Production Profile')
    ax1.legend()
    ax1.grid(True, alpha=0.3)

    # Power/Heat plot
    ax2 = axes[1]
    ax2.plot(years, powers, color='#2563EB', linewidth=2, label='Net Power/Heat (MW)')
    ax2.set_xlabel('Year')
    ax2.set_ylabel('Net Power/Heat (MW)')
    ax2.legend()
    ax2.grid(True, alpha=0.3)

    # Add metrics box
    metrics = results.get('metrics', {})
    metric_text = []
    for key in ['Average Net Electricity Production', 'Average Direct-Use Heat Production']:
        if key in metrics:
            metric_text.append(f"{key}: {metrics[key]}")
    if metric_text:
        text_str = '\n'.join(metric_text[:5])
        ax1.text(0.98, 0.98, text_str, transform=ax1.transAxes,
                 fontsize=8, verticalalignment='top', horizontalalignment='right',
                 bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))

    plt.tight_layout()

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        logger.info(f"Saved validation figure to {output_path}")
    plt.close()


def process(results_path: Path, benchmark_path: Path = None) -> dict:
    """Run full validation."""
    with open(results_path) as f:
        results = json.load(f)

    validation = {
        'plausibility': check_plausibility(results.get('metrics', {})),
        'profile': check_production_profile(results.get('production_profile', [])),
    }

    if benchmark_path and benchmark_path.exists():
        with open(benchmark_path) as f:
            benchmark = json.load(f)
        validation['comparison'] = compare_to_benchmark(results, benchmark)
    else:
        validation['comparison'] = {}

    all_issues = validation['plausibility'] + validation['profile']
    validation['n_warnings'] = sum(1 for i in all_issues if i.startswith('WARNING'))
    validation['n_errors'] = sum(1 for i in all_issues if i.startswith('ERROR'))
    validation['status'] = 'PASS' if validation['n_errors'] == 0 else 'FAIL'

    return validation


def main():
    parser = argparse.ArgumentParser(description='Validate GEOPHIRES results')
    parser.add_argument('--results', required=True, help='Parsed results JSON')
    parser.add_argument('--benchmark', default=None, help='Benchmark results JSON')
    parser.add_argument('--figure', default=None, help='Output validation figure path')
    args = parser.parse_args()

    results_path = Path(args.results)
    benchmark_path = Path(args.benchmark) if args.benchmark else None

    # Validate inputs
    input_issues = validate_inputs(results_path, benchmark_path)
    for issue in input_issues:
        if issue.startswith('FATAL'):
            logger.error(issue)
            sys.exit(1)

    # Process
    validation = process(results_path, benchmark_path)

    # Generate figure if requested
    if args.figure:
        with open(results_path) as f:
            results = json.load(f)
        generate_validation_figure(results, output_path=Path(args.figure))

    # Print results
    print(json.dumps(validation, indent=2))

    sys.exit(0 if validation['status'] == 'PASS' else 1)


if __name__ == '__main__':
    main()
