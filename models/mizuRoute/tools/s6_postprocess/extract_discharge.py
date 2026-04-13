#!/usr/bin/env python3
"""extract_discharge.py — Extract discharge timeseries from mizuRoute output.

Reads mizuRoute output NetCDF, identifies the outlet reach (or user-specified reach),
extracts the routed discharge timeseries, computes performance metrics if observations
are available, and outputs in HydroCraft-compatible format.

Usage:
    python extract_discharge.py \\
        --mizuroute_output outputs/<run>/mizuroute_output/ \\
        --network_nc outputs/<run>/mizuroute_input/network_topology.nc \\
        --output outputs/<run>/mizuroute_discharge.csv \\
        --obs_file data/obs/<basin>/observed.txt \\
        --warmup_years 2
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta

import numpy as np
import netCDF4 as nc
import glob


def find_outlet_reach(network_nc_path, reach_id=None):
    """Find the outlet reach in the network topology.

    The outlet reach has tosegment = 0 (no downstream).
    If multiple outlets exist, select the one with the largest upstream area
    (most accumulated stream links).
    """
    with nc.Dataset(network_nc_path, 'r') as ds:
        seg_ids = ds.variables['seg_id'][:]
        tosegments = ds.variables['tosegment'][:]

    if reach_id is not None:
        if reach_id in seg_ids:
            return reach_id
        else:
            raise ValueError(f"Reach ID {reach_id} not found in network")

    # Find outlets (tosegment == 0)
    outlet_mask = tosegments == 0
    outlet_ids = seg_ids[outlet_mask]

    if len(outlet_ids) == 0:
        raise ValueError("No outlet reach found (all tosegments > 0, circular network?)")

    if len(outlet_ids) == 1:
        return int(outlet_ids[0])

    # Multiple outlets: return the first (user should specify)
    print(f"WARNING: {len(outlet_ids)} outlet reaches found. Using first: {outlet_ids[0]}. "
          f"Specify --reach_id to select a different one.")
    return int(outlet_ids[0])


def extract_timeseries(output_dir, reach_id):
    """Extract discharge timeseries for a given reach from mizuRoute output NetCDF files."""
    output_files = sorted(glob.glob(os.path.join(output_dir, '*.nc')))

    if not output_files:
        raise FileNotFoundError(f"No NetCDF files found in {output_dir}")

    all_times = []
    all_discharge = []

    for fpath in output_files:
        with nc.Dataset(fpath, 'r') as ds:
            # Find the discharge variable
            discharge_varname = None
            for vname in ['IRFroutedRunoff', 'dlayRunoff', 'KWTroutedRunoff',
                         'KWEroutedRunoff', 'MCroutedRunoff', 'DWroutedRunoff',
                         'instRunoff']:
                if vname in ds.variables:
                    discharge_varname = vname
                    break

            if discharge_varname is None:
                # Try any variable with 'runoff' or 'flow' in name
                for vname in ds.variables:
                    if 'runoff' in vname.lower() or 'flow' in vname.lower():
                        discharge_varname = vname
                        break

            if discharge_varname is None:
                print(f"WARNING: No discharge variable found in {fpath}")
                continue

            # Find reach index
            if 'reachID' in ds.variables:
                reach_ids = ds.variables['reachID'][:]
            elif 'seg_id' in ds.variables:
                reach_ids = ds.variables['seg_id'][:]
            else:
                print(f"WARNING: No reach ID variable found in {fpath}")
                continue

            reach_idx = np.where(reach_ids == reach_id)[0]
            if len(reach_idx) == 0:
                print(f"WARNING: Reach {reach_id} not found in {fpath}")
                continue
            reach_idx = reach_idx[0]

            # Read time
            time_var = ds.variables['time']
            time_units = time_var.units
            time_calendar = getattr(time_var, 'calendar', 'standard')
            times = nc.num2date(time_var[:], time_units, calendar=time_calendar)

            # Read discharge (m3/s)
            discharge = ds.variables[discharge_varname][:, reach_idx]

            all_times.extend(times)
            all_discharge.extend(discharge)

    if not all_times:
        raise ValueError("No discharge data extracted from any output file")

    return np.array(all_times), np.array(all_discharge, dtype=float)


def read_observations(obs_file, start_date, end_date):
    """Read observed discharge in HydroCraft format.

    Expected format: tab-separated with columns: stcd, dates, z, Q, name
    """
    import pandas as pd

    df = pd.read_csv(obs_file, sep='\t', parse_dates=['dates'])
    df = df[(df['dates'] >= start_date) & (df['dates'] <= end_date)]
    df = df.sort_values('dates')

    return df['dates'].values, df['Q'].values


def compute_metrics(sim, obs):
    """Compute standard hydrological performance metrics."""
    # Remove NaN
    mask = ~(np.isnan(sim) | np.isnan(obs))
    sim = sim[mask]
    obs = obs[mask]

    if len(sim) < 10:
        return {'n_valid': len(sim), 'warning': 'Too few valid data points'}

    # NSE (Nash-Sutcliffe Efficiency)
    ss_res = np.sum((obs - sim) ** 2)
    ss_tot = np.sum((obs - np.mean(obs)) ** 2)
    nse = 1 - ss_res / ss_tot if ss_tot > 0 else -999

    # RMSE
    rmse = calc_rmse(sim, obs)

    # PBIAS (%)
    pbias = calc_pbias(obs, sim)

    # Correlation
    r = np.corrcoef(sim, obs)[0, 1] if len(sim) > 1 else -999

    # KGE (Kling-Gupta Efficiency)
    r_val = r
    alpha = np.std(sim) / np.std(obs) if np.std(obs) > 0 else 1
    beta = np.mean(sim) / np.mean(obs) if np.mean(obs) > 0 else 1
    kge = 1 - np.sqrt((r_val - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2)

    return {
        'n_valid': int(len(sim)),
        'NSE': round(float(nse), 4),
        'RMSE': round(float(rmse), 2),
        'PBIAS': round(float(pbias), 2),
        'r': round(float(r), 4),
        'KGE': round(float(kge), 4),
        'sim_mean': round(float(np.mean(sim)), 2),
        'obs_mean': round(float(np.mean(obs)), 2),
        'sim_max': round(float(np.max(sim)), 2),
        'obs_max': round(float(np.max(obs)), 2),
    }


def process(args):
    # Find outlet reach
    print("Finding outlet reach...")
    outlet_id = find_outlet_reach(args.network_nc, args.reach_id)
    print(f"  Outlet reach ID: {outlet_id}")

    # Extract discharge
    print(f"Extracting discharge from {args.mizuroute_output}...")
    times, discharge = extract_timeseries(args.mizuroute_output, outlet_id)
    print(f"  Time steps: {len(times)}")
    print(f"  Discharge: mean={np.nanmean(discharge):.2f}, max={np.nanmax(discharge):.2f} m3/s")

    # Apply warmup
    if args.warmup_years > 0:
        warmup_end = times[0] + timedelta(days=args.warmup_years * 365)
        mask = np.array([t >= warmup_end for t in times])
        times = times[mask]
        discharge = discharge[mask]
        print(f"  After {args.warmup_years}-year warmup: {len(times)} timesteps")

    # Save to CSV
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, 'w') as f:
        f.write('date,discharge_m3s\n')
        for t, q in zip(times, discharge):
            date_str = t.strftime('%Y-%m-%d') if hasattr(t, 'strftime') else str(t)[:10]
            f.write(f'{date_str},{q:.4f}\n')
    print(f"  Saved to {args.output}")

    result = {
        'output_file': args.output,
        'reach_id': outlet_id,
        'n_timesteps': len(times),
        'mean_discharge_m3s': round(float(np.nanmean(discharge)), 2),
        'max_discharge_m3s': round(float(np.nanmax(discharge)), 2),
        'warmup_years': args.warmup_years,
    }

    # Compare with observations if available
    if args.obs_file and os.path.isfile(args.obs_file):
        print("\nComparing with observations...")
        try:
            obs_times, obs_q = read_observations(
                args.obs_file,
                str(times[0])[:10], str(times[-1])[:10]
            )

            # Align timeseries (match dates)
            import pandas as pd
            sim_df = pd.DataFrame({'date': [str(t)[:10] for t in times], 'sim_q': discharge})
            obs_df = pd.DataFrame({'date': [str(t)[:10] for t in obs_times], 'obs_q': obs_q})
            merged = pd.merge(sim_df, obs_df, on='date')

            if len(merged) > 0:
                metrics = compute_metrics(merged['sim_q'].values, merged['obs_q'].values)
                result['metrics'] = metrics
                print(f"  NSE: {metrics.get('NSE', 'N/A')}")
                print(f"  RMSE: {metrics.get('RMSE', 'N/A')} m3/s")
                print(f"  PBIAS: {metrics.get('PBIAS', 'N/A')}%")
                print(f"  KGE: {metrics.get('KGE', 'N/A')}")
            else:
                print("  WARNING: No overlapping dates between simulation and observations")
        except Exception as e:
            print(f"  WARNING: Could not process observations: {e}")

    return result


def main():
    parser = argparse.ArgumentParser(description='Extract mizuRoute discharge')
    parser.add_argument('--mizuroute_output', required=True, help='mizuRoute output directory')
    parser.add_argument('--network_nc', required=True, help='Network topology NetCDF')
    parser.add_argument('--output', required=True, help='Output CSV file')
    parser.add_argument('--reach_id', type=int, default=None,
                       help='Specific reach ID to extract (default: auto-detect outlet)')
    parser.add_argument('--obs_file', default=None, help='Observed discharge file')
    parser.add_argument('--warmup_years', type=int, default=2,
                       help='Years to skip as warmup (default: 2)')

    args = parser.parse_args()

    try:
        result = process(args)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(2)


if __name__ == '__main__':
    main()
