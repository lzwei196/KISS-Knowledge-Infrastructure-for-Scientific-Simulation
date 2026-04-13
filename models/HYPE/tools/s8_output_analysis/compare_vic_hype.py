#!/usr/bin/env python3
"""
Compare VIC and HYPE discharge at a common outlet.

Reads VIC routing output and HYPE timeCOUT.txt, aligns them temporally,
and computes comparison metrics.

Usage:
    python compare_vic_hype.py \
        --vic_discharge outputs/vic_run/routing_param/rout_out/station.day \
        --hype_result_dir outputs/hype_run/resultdir/ \
        --hype_outlet_subid 3 \
        --obs_file data/obs/basin/observed.txt \
        --output outputs/comparison/vic_hype_comparison.png
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
from ki_tools_common.metrics import nse as calc_nse, kge as calc_kge, pbias as calc_pbias, rmse as calc_rmse


def read_vic_discharge(filepath):
    """Read VIC Lohmann routing output (.day file)."""
    # VIC routing output format: year month day flow
    df = pd.read_csv(filepath, sep=r'\s+', header=None,
                     names=['year', 'month', 'day', 'discharge'],
                     comment='#')
    df['date'] = pd.to_datetime(df[['year', 'month', 'day']])
    df = df.set_index('date')['discharge']
    return df


def read_hype_discharge(result_dir, outlet_subid):
    """Read HYPE timeCOUT.txt for a specific subbasin."""
    filepath = Path(result_dir) / 'timeCOUT.txt'
    df = pd.read_csv(filepath, sep='\t', comment='!', parse_dates=['DATE'], index_col='DATE')
    sid = str(outlet_subid)
    if sid not in df.columns:
        raise ValueError(f"SUBID {sid} not in timeCOUT.txt")
    series = pd.to_numeric(df[sid], errors='coerce')
    series[series == -9999] = np.nan
    return series


def read_obs_discharge(filepath):
    """Read HydroCraft observed discharge format (tab-separated: stcd dates z Q name)."""
    df = pd.read_csv(filepath, sep='\t', parse_dates=['dates'])
    df = df.set_index('dates')
    return df['Q']


def compute_metrics(sim, obs):
    """Compute NSE, KGE, PBIAS, RMSE."""
    common = sim.dropna().index.intersection(obs.dropna().index)
    if len(common) < 10:
        return {'NSE': np.nan, 'KGE': np.nan, 'PBIAS': np.nan, 'RMSE': np.nan}

    s = sim[common].values.astype(float)
    o = obs[common].values.astype(float)

    return {
        'NSE': calc_nse(o, s),
        'KGE': calc_kge(o, s),
        'PBIAS': calc_pbias(o, s),
        'RMSE': calc_rmse(o, s),
    }


def plot_comparison(vic_q, hype_q, obs_q, output_path, title="VIC vs HYPE"):
    """Plot VIC and HYPE discharge comparison."""
    fig, axes = plt.subplots(2, 1, figsize=(14, 8))

    ax1 = axes[0]
    ax1.plot(vic_q.index, vic_q.values, 'b-', linewidth=0.8, label='VIC', alpha=0.8)
    ax1.plot(hype_q.index, hype_q.values, 'g-', linewidth=0.8, label='HYPE', alpha=0.8)
    if obs_q is not None:
        ax1.plot(obs_q.index, obs_q.values, 'r-', linewidth=0.8, label='Observed', alpha=0.7)

    ax1.set_ylabel('Discharge (m$^3$/s)')
    ax1.set_title(title, fontsize=13, fontweight='bold')
    ax1.legend(loc='upper right')
    ax1.grid(True, alpha=0.3)

    # Metrics text
    metrics_lines = []
    if obs_q is not None:
        vic_metrics = compute_metrics(vic_q, obs_q)
        hype_metrics = compute_metrics(hype_q, obs_q)
        metrics_lines.append(f"VIC:  NSE={vic_metrics['NSE']:.3f}  KGE={vic_metrics['KGE']:.3f}  PBIAS={vic_metrics['PBIAS']:.1f}%")
        metrics_lines.append(f"HYPE: NSE={hype_metrics['NSE']:.3f}  KGE={hype_metrics['KGE']:.3f}  PBIAS={hype_metrics['PBIAS']:.1f}%")
    else:
        # Compare VIC vs HYPE directly
        common = vic_q.dropna().index.intersection(hype_q.dropna().index)
        if len(common) > 0:
            r = np.corrcoef(vic_q[common].values, hype_q[common].values)[0, 1]
            metrics_lines.append(f"VIC-HYPE correlation: r={r:.3f}")
            metrics_lines.append(f"VIC mean={vic_q[common].mean():.1f}, HYPE mean={hype_q[common].mean():.1f}")

    if metrics_lines:
        ax1.text(0.02, 0.95, '\n'.join(metrics_lines), transform=ax1.transAxes,
                fontsize=9, verticalalignment='top',
                bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8),
                family='monospace')

    # Panel 2: Monthly averages
    ax2 = axes[1]
    vic_monthly = vic_q.resample('M').mean()
    hype_monthly = hype_q.resample('M').mean()
    ax2.bar(vic_monthly.index, vic_monthly.values, width=20, alpha=0.5, color='blue', label='VIC monthly')
    ax2.bar(hype_monthly.index, hype_monthly.values, width=20, alpha=0.5, color='green', label='HYPE monthly')
    if obs_q is not None:
        obs_monthly = obs_q.resample('M').mean()
        ax2.plot(obs_monthly.index, obs_monthly.values, 'ro-', markersize=3, label='Obs monthly')
    ax2.set_ylabel('Monthly mean Q (m$^3$/s)')
    ax2.legend(loc='upper right', fontsize=8)
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Saved comparison plot: {output_path}")


def main():
    parser = argparse.ArgumentParser(description='Compare VIC vs HYPE discharge')
    parser.add_argument('--vic_discharge', required=True, help='VIC routing output file')
    parser.add_argument('--hype_result_dir', required=True, help='HYPE result directory')
    parser.add_argument('--hype_outlet_subid', type=int, required=True, help='HYPE outlet SUBID')
    parser.add_argument('--obs_file', help='Observed discharge file (optional)')
    parser.add_argument('--output', required=True, help='Output PNG path')
    parser.add_argument('--title', default='VIC vs HYPE Discharge Comparison')

    args = parser.parse_args()

    # Read VIC discharge
    vic_q = read_vic_discharge(args.vic_discharge)

    # Read HYPE discharge
    hype_q = read_hype_discharge(args.hype_result_dir, args.hype_outlet_subid)

    # Read observed (optional)
    obs_q = None
    if args.obs_file and os.path.exists(args.obs_file):
        obs_q = read_obs_discharge(args.obs_file)

    # Plot
    plot_comparison(vic_q, hype_q, obs_q, args.output, args.title)


if __name__ == '__main__':
    main()
