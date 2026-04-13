#!/usr/bin/env python3
"""
Parse TOPMODEL output files and compute validation metrics.

Reads hyd.out and topmod.out, converts to CSV, and computes:
- NSE (Nash-Sutcliffe Efficiency)
- KGE (Kling-Gupta Efficiency)
- PBIAS (Percent Bias)
- r (Pearson correlation)

Pipeline: validate → process → validate
"""

import os
import sys
import argparse
import numpy as np
from datetime import datetime, timedelta
import csv


def validate_inputs(hyd_file, topmod_file=None):
    """Validate output files exist and are non-empty."""
    errors = []

    if not os.path.exists(hyd_file):
        errors.append(f"hyd.out not found: {hyd_file}")
    elif os.path.getsize(hyd_file) == 0:
        errors.append(f"hyd.out is empty")

    if topmod_file and not os.path.exists(topmod_file):
        errors.append(f"topmod.out not found: {topmod_file}")

    return errors


def parse_hyd_out(hyd_file):
    """
    Parse hyd.out file.

    Format: timestep  Q_simulated  Q_observed  (all in m/hr)

    Returns:
        timesteps: array of timestep indices
        q_sim: simulated discharge (m/hr)
        q_obs: observed discharge (m/hr)
    """
    timesteps = []
    q_sim = []
    q_obs = []

    with open(hyd_file, 'r') as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) >= 3:
                try:
                    t = int(parts[0])
                    qs = float(parts[1])
                    qo = float(parts[2])
                    timesteps.append(t)
                    q_sim.append(qs)
                    q_obs.append(qo)
                except ValueError:
                    continue
            elif len(parts) == 2:
                try:
                    qs = float(parts[0])
                    qo = float(parts[1])
                    timesteps.append(len(timesteps) + 1)
                    q_sim.append(qs)
                    q_obs.append(qo)
                except ValueError:
                    continue

    return np.array(timesteps), np.array(q_sim), np.array(q_obs)


def parse_topmod_out(topmod_file):
    """
    Parse topmod.out file.

    Format: it  p  ep  Q[it]  quz  qb  sbar  qof
    All fluxes in m/hr, sbar in m.

    Returns dict of arrays.
    """
    results = {
        'timestep': [], 'p': [], 'ep': [], 'Q': [],
        'quz': [], 'qb': [], 'sbar': [], 'qof': []
    }

    with open(topmod_file, 'r') as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) == 8:
                try:
                    it = int(parts[0])
                    results['timestep'].append(it)
                    results['p'].append(float(parts[1]))
                    results['ep'].append(float(parts[2]))
                    results['Q'].append(float(parts[3]))
                    results['quz'].append(float(parts[4]))
                    results['qb'].append(float(parts[5]))
                    results['sbar'].append(float(parts[6]))
                    results['qof'].append(float(parts[7]))
                except ValueError:
                    continue

    for key in results:
        results[key] = np.array(results[key])

    return results


def convert_mhr_to_m3s(q_mhr, basin_area_km2):
    """
    Convert discharge from m/hr to m³/s.

    Q_m3s = Q_mhr * basin_area_m2 / 3600
    """
    basin_area_m2 = basin_area_km2 * 1e6
    return q_mhr * basin_area_m2 / 3600.0


def compute_nse(sim, obs):
    """Nash-Sutcliffe Efficiency."""
    if len(sim) == 0 or len(obs) == 0:
        return np.nan
    mean_obs = np.mean(obs)
    numerator = np.sum((sim - obs)**2)
    denominator = np.sum((obs - mean_obs)**2)
    if denominator == 0:
        return np.nan
    return 1.0 - numerator / denominator


def compute_kge(sim, obs):
    """Kling-Gupta Efficiency."""
    if len(sim) == 0 or len(obs) == 0:
        return np.nan

    r = np.corrcoef(sim, obs)[0, 1] if np.std(obs) > 0 and np.std(sim) > 0 else 0
    alpha = np.std(sim) / np.std(obs) if np.std(obs) > 0 else 0
    beta = np.mean(sim) / np.mean(obs) if np.mean(obs) > 0 else 0

    kge = 1.0 - np.sqrt((r - 1)**2 + (alpha - 1)**2 + (beta - 1)**2)
    return kge


def compute_pbias(sim, obs):
    """Percent Bias."""
    if len(sim) == 0 or np.sum(obs) == 0:
        return np.nan
    return 100.0 * np.sum(sim - obs) / np.sum(obs)


def compute_correlation(sim, obs):
    """Pearson correlation coefficient."""
    if len(sim) < 2 or np.std(sim) == 0 or np.std(obs) == 0:
        return np.nan
    return np.corrcoef(sim, obs)[0, 1]


def compute_all_metrics(sim, obs):
    """Compute all validation metrics."""
    # Filter out NaN values
    mask = ~(np.isnan(sim) | np.isnan(obs))
    sim = sim[mask]
    obs = obs[mask]

    return {
        'NSE': float(compute_nse(sim, obs)),
        'KGE': float(compute_kge(sim, obs)),
        'PBIAS': float(compute_pbias(sim, obs)),
        'r': float(compute_correlation(sim, obs)),
        'n_timesteps': int(len(sim)),
        'mean_sim': float(np.mean(sim)),
        'mean_obs': float(np.mean(obs)),
        'std_sim': float(np.std(sim)),
        'std_obs': float(np.std(obs)),
    }


def write_csv(output_file, timesteps, q_sim, q_obs, start_date=None, dt_hours=1.0,
              basin_area_km2=None):
    """Write results to CSV with optional date column and m³/s conversion."""

    with open(output_file, 'w', newline='') as f:
        writer = csv.writer(f)

        header = ['timestep']
        if start_date:
            header.append('date')
        header.extend(['Q_sim_mhr', 'Q_obs_mhr'])
        if basin_area_km2:
            header.extend(['Q_sim_m3s', 'Q_obs_m3s'])
        writer.writerow(header)

        for i in range(len(timesteps)):
            row = [int(timesteps[i])]
            if start_date:
                dt = start_date + timedelta(hours=dt_hours * i)
                row.append(dt.strftime('%Y-%m-%d %H:%M'))
            row.extend([f"{q_sim[i]:.8e}", f"{q_obs[i]:.8e}"])
            if basin_area_km2:
                q_sim_m3s = convert_mhr_to_m3s(q_sim[i], basin_area_km2)
                q_obs_m3s = convert_mhr_to_m3s(q_obs[i], basin_area_km2)
                row.extend([f"{q_sim_m3s:.4f}", f"{q_obs_m3s:.4f}"])
            writer.writerow(row)

    print(f"Wrote CSV: {output_file}")


def validate_metrics(metrics):
    """Validate that metrics are physically reasonable."""
    warnings = []

    if metrics['NSE'] < -1:
        warnings.append(f"NSE={metrics['NSE']:.3f} is very poor — check unit conversions")

    if abs(metrics['PBIAS']) > 50:
        warnings.append(f"PBIAS={metrics['PBIAS']:.1f}% — large volume bias, check forcing units")

    if metrics['r'] < 0:
        warnings.append(f"r={metrics['r']:.3f} — negative correlation, something is fundamentally wrong")

    if metrics['mean_sim'] > 100 * metrics['mean_obs'] and metrics['mean_obs'] > 0:
        warnings.append("Simulated mean >>100× observed — likely unit conversion error")

    return warnings


def main():
    parser = argparse.ArgumentParser(description="Parse TOPMODEL output and compute metrics")
    parser.add_argument('--hyd-file', default='hyd.out', help='Path to hyd.out')
    parser.add_argument('--topmod-file', default=None, help='Path to topmod.out')
    parser.add_argument('--output-csv', default='results.csv', help='Output CSV path')
    parser.add_argument('--start-date', default=None, help='Start date YYYY-MM-DD')
    parser.add_argument('--dt-hours', type=float, default=1.0, help='Time step hours')
    parser.add_argument('--basin-area-km2', type=float, default=None, help='Basin area km²')
    parser.add_argument('--spinup-steps', type=int, default=0, help='Steps to discard as spinup')

    args = parser.parse_args()

    # Step 1: Validate inputs
    print("=== Step 1: Validating inputs ===")
    errors = validate_inputs(args.hyd_file, args.topmod_file)
    if errors:
        for e in errors:
            print(f"  ERROR: {e}")
        sys.exit(1)

    # Step 2: Parse
    print("=== Step 2: Parsing output files ===")
    timesteps, q_sim, q_obs = parse_hyd_out(args.hyd_file)
    print(f"  Read {len(timesteps)} timesteps from hyd.out")

    if args.topmod_file:
        topmod_results = parse_topmod_out(args.topmod_file)
        print(f"  Read {len(topmod_results['timestep'])} timesteps from topmod.out")

    # Step 3: Discard spinup
    if args.spinup_steps > 0:
        idx = args.spinup_steps
        timesteps = timesteps[idx:]
        q_sim = q_sim[idx:]
        q_obs = q_obs[idx:]
        print(f"  After spinup removal: {len(timesteps)} timesteps")

    # Step 4: Compute metrics
    print("=== Step 3: Computing metrics ===")
    metrics = compute_all_metrics(q_sim, q_obs)

    print(f"  NSE  = {metrics['NSE']:.4f}")
    print(f"  KGE  = {metrics['KGE']:.4f}")
    print(f"  PBIAS = {metrics['PBIAS']:.2f}%")
    print(f"  r    = {metrics['r']:.4f}")

    if args.basin_area_km2:
        q_sim_m3s = convert_mhr_to_m3s(q_sim, args.basin_area_km2)
        q_obs_m3s = convert_mhr_to_m3s(q_obs, args.basin_area_km2)
        metrics_m3s = compute_all_metrics(q_sim_m3s, q_obs_m3s)
        print(f"\n  In m³/s:")
        print(f"  Mean sim = {metrics_m3s['mean_sim']:.2f} m³/s")
        print(f"  Mean obs = {metrics_m3s['mean_obs']:.2f} m³/s")

    # Step 5: Validate metrics
    print("=== Step 4: Validating metrics ===")
    warnings = validate_metrics(metrics)
    if warnings:
        for w in warnings:
            print(f"  WARNING: {w}")
    else:
        print("  Metrics look reasonable")

    # Step 6: Write CSV
    print("=== Step 5: Writing CSV ===")
    start_date = None
    if args.start_date:
        start_date = datetime.strptime(args.start_date, "%Y-%m-%d")

    write_csv(args.output_csv, timesteps, q_sim, q_obs,
              start_date=start_date, dt_hours=args.dt_hours,
              basin_area_km2=args.basin_area_km2)

    return metrics


if __name__ == '__main__':
    main()
