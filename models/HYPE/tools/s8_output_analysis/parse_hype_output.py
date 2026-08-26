#!/usr/bin/env python3
"""
Parse HYPE output files (timeCOUT.txt, mapCOUT.txt) into pandas DataFrames.

Handles the HYPE tab-separated output format with comment header lines.

Usage:
    python parse_hype_output.py \
        --result_dir outputs/hype_run/resultdir/ \
        --output_csv outputs/hype_run/discharge.csv \
        --outlet_subid 3
"""

import argparse
import sys
import os
import warnings
warnings.filterwarnings('ignore')

import numpy as np
import pandas as pd
from pathlib import Path

sys.path.insert(0, "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect")
from ki_tools_common.metrics import nse as calc_nse, kge as calc_kge, pbias as calc_pbias, rmse as calc_rmse


def parse_hype_timeseries(filepath):
    """
    Parse a HYPE timeseries output file (timeCOUT.txt, timeROUT.txt, etc.).

    Returns:
        DataFrame with DATE index and SUBID columns
    """
    # Read header info
    with open(filepath) as f:
        first_line = f.readline()

    # Extract metadata from comment line
    metadata = {}
    if first_line.startswith('!!'):
        for part in first_line.strip('!! \n').split(';'):
            if '=' in part:
                key, val = part.split('=', 1)
                metadata[key.strip()] = val.strip()

    # Read data (skip comment lines)
    df = pd.read_csv(filepath, sep='\t', comment='!', parse_dates=['DATE'], index_col='DATE')

    # Convert to numeric (handle -9999 as NaN)
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors='coerce')
        df.loc[df[col] == -9999, col] = np.nan

    return df, metadata


def parse_hype_map_output(filepath):
    """
    Parse a HYPE map output file (mapCOUT.txt, mapROUT.txt, etc.).

    Returns:
        DataFrame with DATE index and SUBID columns (period averages)
    """
    return parse_hype_timeseries(filepath)


def compute_metrics(simulated, observed):
    """Compute NSE, KGE, PBIAS between simulated and observed."""
    # Align series
    common = simulated.dropna().index.intersection(observed.dropna().index)
    if len(common) < 10:
        return {'NSE': np.nan, 'KGE': np.nan, 'PBIAS': np.nan, 'RMSE': np.nan, 'N': len(common)}

    sim = simulated[common].values
    obs = observed[common].values

    return {
        'NSE': calc_nse(obs, sim),
        'KGE': calc_kge(obs, sim),
        'PBIAS': calc_pbias(obs, sim),
        'RMSE': calc_rmse(obs, sim),
        'N': len(common),
    }


def detect_outlet_subid(result_dir):
    """Auto-detect outlet SUBID from GeoData.txt (MAINDOWN=0).

    Searches in modeldir/ relative to resultdir/ (HYPE convention:
    resultdir and modeldir are siblings under the run directory).
    """
    result_dir = Path(result_dir)
    # GeoData.txt is typically in ../modelfiles/ relative to resultdir/
    for candidate in [
        result_dir.parent / 'modelfiles' / 'GeoData.txt',
        result_dir.parent / 'GeoData.txt',
        result_dir / 'GeoData.txt',
    ]:
        if candidate.exists():
            geo = pd.read_csv(candidate, sep='\t', comment='!')
            geo.columns = geo.columns.str.strip()
            outlet = geo[geo['MAINDOWN'] == 0]
            if len(outlet) > 0:
                sid = int(outlet.iloc[0]['SUBID'])
                print(f"  Auto-detected outlet: SUBID {sid} (from {candidate.name})")
                return sid
    return None


def main():
    parser = argparse.ArgumentParser(description='Parse HYPE output files')
    parser.add_argument('--result_dir', required=True, help='HYPE result directory')
    parser.add_argument('--output_csv', help='Output CSV for discharge')
    parser.add_argument('--outlet_subid', type=int, default=None,
                        help='Outlet subbasin ID (auto-detected from GeoData.txt if omitted)')
    parser.add_argument('--obs_file', default=None,
                        help='Observed discharge file (HydroCraft format: stcd/dates/z/Q/name)')
    parser.add_argument('--variable', default='cout', help='Output variable to parse')

    args = parser.parse_args()

    result_dir = Path(args.result_dir)

    # Parse computed output
    cout_path = result_dir / f'time{args.variable.upper()}.txt'
    if not cout_path.exists():
        print(f"ERROR: {cout_path} not found")
        sys.exit(1)

    df, metadata = parse_hype_timeseries(cout_path)
    print(f"Parsed {cout_path.name}: {len(df)} timesteps, {len(df.columns)} subbasins")
    print(f"  Metadata: {metadata}")
    print(f"  Date range: {df.index[0]} to {df.index[-1]}")

    # Auto-detect outlet if not specified
    outlet_subid = args.outlet_subid
    if outlet_subid is None:
        outlet_subid = detect_outlet_subid(result_dir)
    if outlet_subid is None:
        # Fallback: use the last column (often the outlet in HYPE convention)
        outlet_subid = int(df.columns[-1])
        print(f"  Fallback outlet: SUBID {outlet_subid} (last column)")

    sid = str(outlet_subid)

    # Summary statistics for outlet
    if sid in df.columns:
        valid = df[sid].dropna()
        print(f"\n  SUBID {sid}: mean={valid.mean():.2f}, max={valid.max():.2f}, "
              f"min={valid.min():.2f}, std={valid.std():.2f}")

    # Compare with external observations if provided
    if args.obs_file and sid in df.columns:
        obs_ext = pd.read_csv(args.obs_file, sep='\t', encoding='utf-8',
                              encoding_errors='replace')
        obs_ext['date'] = pd.to_datetime(obs_ext['dates'])
        obs_ext = obs_ext.set_index('date')[['Q']].astype(float)
        obs_ext = obs_ext[obs_ext['Q'] > 0]

        sim = df[[sid]].rename(columns={sid: 'sim'})
        merged = obs_ext.join(sim, how='inner').dropna()

        if len(merged) >= 10:
            metrics = compute_metrics(merged['sim'], merged['Q'])
            print(f"\nPerformance at outlet (SUBID {sid}) vs observations:")
            for key, val in metrics.items():
                if isinstance(val, float):
                    print(f"  {key}: {val:.4f}")
                else:
                    print(f"  {key}: {val}")

    # Also compare with HYPE internal routing output
    elif sid in df.columns:
        rout_path = result_dir / 'timeROUT.txt'
        if rout_path.exists():
            obs_df, _ = parse_hype_timeseries(rout_path)
            if sid in obs_df.columns:
                metrics = compute_metrics(df[sid], obs_df[sid])
                print(f"\nPerformance at outlet (SUBID {sid}) vs routing:")
                for key, val in metrics.items():
                    if isinstance(val, float):
                        print(f"  {key}: {val:.4f}")
                    else:
                        print(f"  {key}: {val}")

    # Save to CSV
    if args.output_csv:
        os.makedirs(os.path.dirname(args.output_csv) or '.', exist_ok=True)
        df.to_csv(args.output_csv)
        print(f"\nSaved to: {args.output_csv}")


if __name__ == '__main__':
    main()
