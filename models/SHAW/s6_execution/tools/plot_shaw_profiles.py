#!/usr/bin/env python3
"""
plot_shaw_profiles.py — Visualize SHAW soil temperature, moisture, ice content profiles.

Generates time-depth heatmaps and time series plots for key SHAW outputs:
- Soil temperature profile (with 0C isotherm = frost line)
- Soil moisture profile (total and liquid)
- Frost depth and snow depth time series
- Surface energy balance components
- Water balance summary

Usage:
    python plot_shaw_profiles.py \
        --workdir /path/to/shaw/run \
        --output /path/to/output/shaw_profiles.png \
        [--start_year 2005] [--end_year 2005]
"""

import argparse
import sys
from pathlib import Path

try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    import numpy as np
    from datetime import datetime, timedelta
except ImportError:
    print("ERROR: matplotlib and numpy required. Install with:")
    print("  pip install matplotlib numpy")
    sys.exit(1)


def read_profile_data(filepath):
    """Read SHAW profile output (temp.out or moist.out)."""
    times = []
    profiles = []

    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or any(c.isalpha() for c in line[:10]):
                continue
            parts = line.split()
            if len(parts) < 4:
                continue
            try:
                jday = int(parts[0])
                hour = int(parts[1])
                year = int(parts[2])
                year = year + (1900 if year > 50 else 2000)
                values = [float(v) for v in parts[3:]]

                dt = datetime(year, 1, 1) + timedelta(days=jday - 1, hours=hour)
                times.append(dt)
                profiles.append(values)
            except (ValueError, IndexError):
                continue

    return times, profiles


def read_frost_data(filepath):
    """Read frost.out data."""
    times = []
    frost_depths = []
    thaw_depths = []
    snow_depths = []

    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or any(c.isalpha() for c in line[:10]):
                continue
            parts = line.split()
            if len(parts) < 4:
                continue
            try:
                jday = int(parts[0])
                if len(parts) >= 7:
                    hour = int(parts[1])
                    year = int(parts[2])
                    frost = float(parts[3])
                    thaw = float(parts[4])
                    snow = float(parts[5])
                else:
                    hour = 12
                    year = int(parts[1])
                    frost = float(parts[2])
                    thaw = float(parts[3])
                    snow = float(parts[4]) if len(parts) > 4 else 0.0

                year = year + (1900 if year > 50 else 2000)
                dt = datetime(year, 1, 1) + timedelta(days=jday - 1, hours=hour)
                times.append(dt)
                frost_depths.append(frost)
                thaw_depths.append(thaw)
                snow_depths.append(snow)
            except (ValueError, IndexError):
                continue

    return times, frost_depths, thaw_depths, snow_depths


def read_water_data(filepath):
    """Read water.out data."""
    times = []
    data = {'rain': [], 'snow': [], 'et': [], 'runoff': [], 'drainage': []}

    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or any(c.isalpha() for c in line[:10]):
                continue
            parts = line.split()
            if len(parts) < 6:
                continue
            try:
                jday = int(parts[0])
                year = int(parts[1])
                year = year + (1900 if year > 50 else 2000)
                dt = datetime(year, 1, 1) + timedelta(days=jday - 1)
                times.append(dt)
                data['rain'].append(float(parts[2]))
                data['snow'].append(float(parts[3]) if len(parts) > 3 else 0)
                data['et'].append(float(parts[4]) if len(parts) > 4 else 0)
                data['runoff'].append(float(parts[5]) if len(parts) > 5 else 0)
                data['drainage'].append(float(parts[6]) if len(parts) > 6 else 0)
            except (ValueError, IndexError):
                continue

    return times, data


def read_energy_data(filepath):
    """Read energy.out data."""
    times = []
    data = {'rnet': [], 'sensible': [], 'latent': [], 'ground': []}

    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or any(c.isalpha() for c in line[:10]):
                continue
            parts = line.split()
            if len(parts) < 6:
                continue
            try:
                jday = int(parts[0])
                if len(parts) > 7:
                    hour = int(parts[1])
                    year = int(parts[2])
                    idx = 3
                else:
                    hour = 12
                    year = int(parts[1])
                    idx = 2

                year = year + (1900 if year > 50 else 2000)
                dt = datetime(year, 1, 1) + timedelta(days=jday - 1, hours=hour)
                times.append(dt)
                data['rnet'].append(float(parts[idx]))
                data['sensible'].append(float(parts[idx + 1]))
                data['latent'].append(float(parts[idx + 2]))
                data['ground'].append(float(parts[idx + 3]))
            except (ValueError, IndexError):
                continue

    return times, data


def plot_all(workdir, output_path, depths=None):
    """Generate comprehensive SHAW output visualization."""
    workdir = Path(workdir)

    # Determine which files exist
    has_temp = (workdir / 'temp.out').exists()
    has_moist = (workdir / 'moist.out').exists()
    has_frost = (workdir / 'frost.out').exists()
    has_water = (workdir / 'water.out').exists()
    has_energy = (workdir / 'energy.out').exists()

    n_plots = sum([has_temp, has_moist, has_frost, has_water, has_energy])
    if n_plots == 0:
        print("No output files found to plot.")
        return

    fig, axes = plt.subplots(n_plots, 1, figsize=(14, 4 * n_plots), squeeze=False)
    ax_idx = 0

    # 1. Soil temperature heatmap
    if has_temp:
        times, profiles = read_profile_data(str(workdir / 'temp.out'))
        if times and profiles:
            ax = axes[ax_idx, 0]
            n_nodes = len(profiles[0])
            if depths is None:
                depths_arr = np.linspace(0, 4.0, n_nodes)
            else:
                depths_arr = np.array(depths[:n_nodes])

            profile_array = np.array(profiles)
            im = ax.pcolormesh(
                mdates.date2num(times), depths_arr, profile_array.T,
                cmap='RdYlBu_r', shading='auto'
            )
            # Add 0C contour (frost line)
            try:
                ax.contour(
                    mdates.date2num(times), depths_arr, profile_array.T,
                    levels=[0.0], colors='black', linewidths=2
                )
            except Exception:
                pass
            ax.invert_yaxis()
            ax.set_ylabel('Depth (m)')
            ax.set_title('Soil Temperature (C) — black line = 0C (frost boundary)')
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
            plt.colorbar(im, ax=ax, label='Temperature (C)')
            ax_idx += 1

    # 2. Soil moisture heatmap
    if has_moist:
        times, profiles = read_profile_data(str(workdir / 'moist.out'))
        if times and profiles:
            ax = axes[ax_idx, 0]
            n_nodes = len(profiles[0])
            if depths is None:
                depths_arr = np.linspace(0, 4.0, n_nodes)
            else:
                depths_arr = np.array(depths[:n_nodes])

            profile_array = np.array(profiles)
            im = ax.pcolormesh(
                mdates.date2num(times), depths_arr, profile_array.T,
                cmap='YlGnBu', shading='auto', vmin=0, vmax=0.5
            )
            ax.invert_yaxis()
            ax.set_ylabel('Depth (m)')
            ax.set_title('Soil Water Content (m3/m3)')
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
            plt.colorbar(im, ax=ax, label='Water Content (m3/m3)')
            ax_idx += 1

    # 3. Frost and snow depth
    if has_frost:
        times, frost, thaw, snow = read_frost_data(str(workdir / 'frost.out'))
        if times:
            ax = axes[ax_idx, 0]
            ax.fill_between(times, 0, [-s for s in snow], alpha=0.3, color='cyan', label='Snow depth')
            ax.plot(times, frost, 'b-', linewidth=1.5, label='Frost depth (cm)')
            ax.plot(times, thaw, 'r--', linewidth=1.0, label='Thaw depth (cm)')
            ax.set_ylabel('Depth (cm)')
            ax.set_title('Frost Depth, Thaw Depth, and Snow Depth')
            ax.legend(loc='best')
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
            ax.axhline(0, color='gray', linestyle='-', linewidth=0.5)
            ax_idx += 1

    # 4. Water balance
    if has_water:
        times, wdata = read_water_data(str(workdir / 'water.out'))
        if times:
            ax = axes[ax_idx, 0]
            ax.bar(times, wdata['rain'], color='blue', alpha=0.5, label='Rain', width=1)
            ax.bar(times, wdata['snow'], bottom=wdata['rain'], color='cyan',
                   alpha=0.5, label='Snow', width=1)
            ax.plot(times, wdata['et'], 'g-', linewidth=1, label='ET')
            ax.plot(times, wdata['runoff'], 'r-', linewidth=1, label='Runoff')
            ax.plot(times, wdata['drainage'], 'k--', linewidth=1, label='Drainage')
            ax.set_ylabel('Water (mm)')
            ax.set_title('Water Balance')
            ax.legend(loc='best', ncol=5, fontsize=8)
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
            ax_idx += 1

    # 5. Energy balance
    if has_energy:
        times, edata = read_energy_data(str(workdir / 'energy.out'))
        if times:
            ax = axes[ax_idx, 0]
            ax.plot(times, edata['rnet'], 'k-', linewidth=1.5, label='Rnet')
            ax.plot(times, edata['sensible'], 'r-', linewidth=1, label='H (sensible)')
            ax.plot(times, edata['latent'], 'b-', linewidth=1, label='LE (latent)')
            ax.plot(times, edata['ground'], 'brown', linewidth=1, label='G (ground)')
            ax.set_ylabel('Energy Flux (W/m2)')
            ax.set_title('Surface Energy Balance')
            ax.legend(loc='best', ncol=4, fontsize=8)
            ax.axhline(0, color='gray', linestyle='-', linewidth=0.5)
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
            ax_idx += 1

    plt.tight_layout()

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(str(output_path), dpi=150, bbox_inches='tight')
    plt.close()

    print(f"Plot saved: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Plot SHAW output profiles")
    parser.add_argument("--workdir", type=str, required=True,
                        help="Directory with SHAW output files")
    parser.add_argument("--output", type=str, required=True,
                        help="Output image path")

    args = parser.parse_args()
    plot_all(args.workdir, args.output)


if __name__ == "__main__":
    main()
