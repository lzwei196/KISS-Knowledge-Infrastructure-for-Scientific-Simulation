#!/usr/bin/env python3
"""
Plot HYPE simulation results — discharge time series with optional observed data.

Usage:
    python plot_hype_results.py \
        --result_dir outputs/hype_run/resultdir/ \
        --outlet_subid 3 \
        --title "Test Basin HYPE Simulation" \
        --output outputs/hype_run/discharge_plot.png
"""

import argparse
import sys
import os
import warnings
warnings.filterwarnings('ignore')

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from pathlib import Path

sys.path.insert(0, "/home/server/knowledge-dissection-toolkit/auto_dissect")
from ki_tools_common.metrics import nse as calc_nse, kge as calc_kge, pbias as calc_pbias


def parse_hype_time_file(filepath):
    """Parse a HYPE time*.txt output file."""
    df = pd.read_csv(filepath, sep='\t', comment='!', parse_dates=['DATE'], index_col='DATE')
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors='coerce')
        df.loc[df[col] == -9999, col] = np.nan
    return df


def plot_discharge(result_dir, outlet_subid, title, output_path):
    """Plot discharge comparison: simulated vs observed."""
    result_dir = Path(result_dir)

    # Load simulated discharge
    cout_path = result_dir / 'timeCOUT.txt'
    if not cout_path.exists():
        print(f"ERROR: {cout_path} not found")
        sys.exit(1)

    sim_df = parse_hype_time_file(cout_path)
    sid = str(outlet_subid)

    if sid not in sim_df.columns:
        print(f"ERROR: SUBID {sid} not found in timeCOUT.txt")
        print(f"Available SUBIDs: {list(sim_df.columns)}")
        sys.exit(1)

    sim = sim_df[sid]

    # Load observed discharge if available
    rout_path = result_dir / 'timeROUT.txt'
    obs = None
    if rout_path.exists():
        obs_df = parse_hype_time_file(rout_path)
        if sid in obs_df.columns:
            obs = obs_df[sid].dropna()

    # Create figure
    fig, axes = plt.subplots(3, 1, figsize=(14, 10), gridspec_kw={'height_ratios': [3, 1, 1]})

    # Panel 1: Discharge time series
    ax1 = axes[0]
    ax1.plot(sim.index, sim.values, 'b-', linewidth=0.8, label='HYPE Simulated', alpha=0.9)
    if obs is not None and len(obs) > 0:
        ax1.plot(obs.index, obs.values, 'r-', linewidth=0.8, label='Observed', alpha=0.7)

    ax1.set_ylabel('Discharge (m$^3$/s)')
    ax1.set_title(title, fontsize=13, fontweight='bold')
    ax1.legend(loc='upper right')
    ax1.grid(True, alpha=0.3)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    ax1.xaxis.set_major_locator(mdates.MonthLocator(interval=3))

    # Panel 2: Cumulative discharge
    ax2 = axes[1]
    sim_cumul = np.nancumsum(sim.values)
    ax2.plot(sim.index, sim_cumul, 'b-', linewidth=1, label='Sim cumulative')
    if obs is not None and len(obs) > 0:
        obs_cumul = np.nancumsum(obs.values)
        ax2.plot(obs.index, obs_cumul, 'r-', linewidth=1, label='Obs cumulative')
    ax2.set_ylabel('Cumulative Q\n(m$^3$/s$\\cdot$day)')
    ax2.legend(loc='upper left', fontsize=8)
    ax2.grid(True, alpha=0.3)

    # Panel 3: Snow or additional variables
    snow_path = result_dir / 'timeSNOW.txt'
    if snow_path.exists():
        snow_df = parse_hype_time_file(snow_path)
        if sid in snow_df.columns:
            ax3 = axes[2]
            ax3.fill_between(snow_df.index, 0, snow_df[sid].values,
                           color='lightblue', alpha=0.7, label='SWE')
            ax3.set_ylabel('Snow (mm)')
            ax3.legend(loc='upper right', fontsize=8)
            ax3.grid(True, alpha=0.3)
    else:
        axes[2].set_visible(False)

    # Compute and display metrics
    if obs is not None and len(obs) > 10:
        common = sim.dropna().index.intersection(obs.dropna().index)
        if len(common) > 10:
            s = sim[common].values
            o = obs[common].values
            nse_val = calc_nse(o, s)
            kge_val = calc_kge(o, s)
            pbias_val = calc_pbias(o, s)

            metrics_text = f'NSE={nse_val:.3f}  KGE={kge_val:.3f}  PBIAS={pbias_val:.1f}%'
            ax1.text(0.02, 0.95, metrics_text, transform=ax1.transAxes,
                    fontsize=10, verticalalignment='top',
                    bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))

    plt.tight_layout()

    # Save
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Saved plot: {output_path}")


def main():
    parser = argparse.ArgumentParser(description='Plot HYPE results')
    parser.add_argument('--result_dir', required=True, help='HYPE result directory')
    parser.add_argument('--outlet_subid', type=int, required=True, help='Outlet subbasin ID')
    parser.add_argument('--title', default='HYPE Simulation', help='Plot title')
    parser.add_argument('--output', required=True, help='Output PNG path')

    args = parser.parse_args()
    plot_discharge(args.result_dir, args.outlet_subid, args.title, args.output)


if __name__ == '__main__':
    main()
