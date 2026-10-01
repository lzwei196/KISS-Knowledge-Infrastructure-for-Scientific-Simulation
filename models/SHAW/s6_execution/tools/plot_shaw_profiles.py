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
        [--depths 0 0.05 0.10 0.15 0.20 0.30 0.50 0.70 1.00 1.25 1.50]
"""

import argparse
import sys
from pathlib import Path

from parse_shaw_output import (parse_profile_file, parse_frost_file, parse_water_file,
                               parse_energy_file, read_profile_depths)

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
    """Read the same date/node layout used by CSV export."""
    rows = parse_profile_file(filepath)
    return ([datetime.fromisoformat(row["datetime"]) for row in rows],
            [[value for key, value in row.items() if key.startswith("value_node")] for row in rows])


def read_frost_data(filepath):
    rows = parse_frost_file(filepath)
    return ([datetime.fromisoformat(row["datetime"]) for row in rows],
            [row["frost_depth_cm"] for row in rows], [row["thaw_depth_cm"] for row in rows],
            [row["snow_depth_cm"] for row in rows])


def read_water_data(filepath):
    rows = parse_water_file(filepath)
    columns = {"precip": "precip_mm", "snowmelt": "snowmelt_mm", "et": "et_mm",
               "runoff": "runoff_mm", "drainage": "drainage_mm"}
    return ([datetime.fromisoformat(row["datetime"]) for row in rows],
            {key: [row[column] for row in rows] for key, column in columns.items()})


def read_energy_data(filepath):
    rows = parse_energy_file(filepath)
    return ([datetime.fromisoformat(row["datetime"]) for row in rows],
            {key: [row[key + "_wm2"] for row in rows] for key in ("rnet", "sensible", "latent", "ground")})


def _profile_depths(filepath, node_count, depths=None):
    """Use measured node depths in meters, never a fabricated uniform grid."""
    values = read_profile_depths(filepath) if depths is None else depths
    if not len(values):
        raise ValueError(f"{filepath}: no soil-depth header; supply --depths in meters")
    result = np.asarray(values, dtype=float)
    if result.ndim != 1 or len(result) != node_count:
        raise ValueError(f"{filepath}: depths must contain exactly {node_count} node values")
    if not np.all(np.isfinite(result)) or np.any(result < 0) or np.any(np.diff(result) <= 0):
        raise ValueError(f"{filepath}: depths must be finite, nonnegative, and strictly increasing in meters")
    return result


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
            depths_arr = _profile_depths(workdir / 'temp.out', n_nodes, depths)

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
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %d\n%Y'))
            plt.colorbar(im, ax=ax, label='Temperature (C)')
            ax_idx += 1

    # 2. Soil moisture heatmap
    if has_moist:
        times, profiles = read_profile_data(str(workdir / 'moist.out'))
        if times and profiles:
            ax = axes[ax_idx, 0]
            n_nodes = len(profiles[0])
            depths_arr = _profile_depths(workdir / 'moist.out', n_nodes, depths)

            profile_array = np.array(profiles)
            im = ax.pcolormesh(
                mdates.date2num(times), depths_arr, profile_array.T,
                cmap='YlGnBu', shading='auto', vmin=0, vmax=0.5
            )
            ax.invert_yaxis()
            ax.set_ylabel('Depth (m)')
            ax.set_title('Soil Water Content (m3/m3)')
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %d\n%Y'))
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
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %d\n%Y'))
            ax.axhline(0, color='gray', linestyle='-', linewidth=0.5)
            ax_idx += 1

    # 4. Water balance
    if has_water:
        times, wdata = read_water_data(str(workdir / 'water.out'))
        if times:
            ax = axes[ax_idx, 0]
            ax.bar(times, wdata['precip'], color='blue', alpha=0.5, label='Precipitation', width=1)
            ax.plot(times, wdata['snowmelt'], color='cyan', label='Snowmelt')
            ax.plot(times, wdata['et'], 'g-', linewidth=1, label='ET')
            ax.plot(times, wdata['runoff'], 'r-', linewidth=1, label='Runoff')
            ax.plot(times, wdata['drainage'], 'k--', linewidth=1, label='Drainage')
            ax.set_ylabel('Water (mm)')
            ax.set_title('Water Balance')
            ax.legend(loc='best', ncol=5, fontsize=8)
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %d\n%Y'))
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
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %d\n%Y'))
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
    parser.add_argument("--depths", type=float, nargs="+",
                        help="Explicit soil-node depths in meters, one per column; "
                             "by default read each profile's DY/DAY HR YR depth header")

    args = parser.parse_args()
    try:
        plot_all(args.workdir, args.output, args.depths)
    except ValueError as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
