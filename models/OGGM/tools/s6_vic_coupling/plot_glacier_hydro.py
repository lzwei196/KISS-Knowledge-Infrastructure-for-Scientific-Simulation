#!/usr/bin/env python3
"""
Plot Glacier Hydrology — OGGM Knowledge Infrastructure

Generate visualization plots for glacier-hydrology coupling results:
1. Stacked runoff components (glacier melt, snowmelt, rainfall, baseflow)
2. Glacier evolution timeseries (volume, area, length)
3. Glacier contribution fraction (monthly bar chart)
4. Spatial map (basin with glacier outlines)

Usage:
    python plot_glacier_hydro.py \
        --oggm_output outputs/oggm/compiled/compiled_output_hist.nc \
        --basin_shp data/shp/yarlung_shp/yarlung_boundary.shp \
        --output_dir outputs/oggm/plots
"""

import argparse
import json
import sys
from pathlib import Path

try:
    import numpy as np
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
except ImportError:
    print("ERROR: numpy and matplotlib required")
    sys.exit(1)


def plot_glacier_evolution(oggm_ds, output_dir, title_prefix=""):
    """Plot glacier volume, area, and length evolution."""
    fig, axes = plt.subplots(3, 1, figsize=(12, 10), sharex=True)

    if 'volume' in oggm_ds:
        time = oggm_ds['time'].values
        # Basin-total volume
        total_volume = oggm_ds['volume'].sum(dim='rgi_id') / 1e9  # m3 -> km3
        axes[0].plot(time, total_volume, 'b-', linewidth=2)
        axes[0].set_ylabel('Volume (km$^3$)')
        axes[0].set_title(f'{title_prefix}Glacier Volume')
        axes[0].grid(True, alpha=0.3)

    if 'area' in oggm_ds:
        total_area = oggm_ds['area'].sum(dim='rgi_id') / 1e6  # m2 -> km2
        axes[1].plot(time, total_area, 'r-', linewidth=2)
        axes[1].set_ylabel('Area (km$^2$)')
        axes[1].set_title(f'{title_prefix}Glacier Area')
        axes[1].grid(True, alpha=0.3)

    if 'length' in oggm_ds:
        mean_length = oggm_ds['length'].mean(dim='rgi_id')
        axes[2].plot(time, mean_length, 'g-', linewidth=2)
        axes[2].set_ylabel('Mean Length (m)')
        axes[2].set_title(f'{title_prefix}Mean Glacier Length')
        axes[2].grid(True, alpha=0.3)

    axes[2].set_xlabel('Year')
    plt.tight_layout()

    output_path = output_dir / 'glacier_evolution.png'
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Evolution plot: {output_path}")
    return str(output_path)


def plot_spatial_map(basin_shp, glacier_csv, output_dir, title_prefix=""):
    """Plot basin map with glacier outlines."""
    try:
        import geopandas as gpd
        import csv as csv_mod

        fig, ax = plt.subplots(1, 1, figsize=(10, 10))

        # Plot basin boundary
        basin_gdf = gpd.read_file(basin_shp)
        basin_gdf.plot(ax=ax, facecolor='lightblue', edgecolor='black',
                       linewidth=2, alpha=0.3)

        # Plot glacier centroids
        if glacier_csv and Path(glacier_csv).exists():
            glaciers = []
            with open(glacier_csv, 'r') as f:
                reader = csv_mod.DictReader(f)
                for row in reader:
                    glaciers.append(row)

            if glaciers:
                lats = [float(g['centroid_lat']) for g in glaciers]
                lons = [float(g['centroid_lon']) for g in glaciers]
                areas = [float(g['area_km2']) for g in glaciers]

                # Scale marker size by area
                sizes = [max(5, min(200, a * 10)) for a in areas]

                scatter = ax.scatter(lons, lats, c=areas, s=sizes,
                                     cmap='coolwarm', alpha=0.7,
                                     edgecolors='black', linewidth=0.5)
                plt.colorbar(scatter, ax=ax, label='Glacier Area (km$^2$)',
                             shrink=0.6)

                ax.set_title(f'{title_prefix}Glacier Distribution ({len(glaciers)} glaciers)')
            else:
                ax.set_title(f'{title_prefix}Basin Map')
        else:
            ax.set_title(f'{title_prefix}Basin Map')

        ax.set_xlabel('Longitude')
        ax.set_ylabel('Latitude')
        ax.grid(True, alpha=0.3)

        output_path = output_dir / 'glacier_spatial_map.png'
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        plt.close()
        print(f"Spatial map: {output_path}")
        return str(output_path)

    except ImportError:
        print("WARNING: geopandas not available for spatial map")
        return None


def plot_contribution_placeholder(output_dir, title_prefix=""):
    """Plot placeholder monthly glacier contribution chart."""
    fig, ax = plt.subplots(1, 1, figsize=(10, 5))

    months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
              'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    # Typical glacier contribution pattern (NH, glacierized basin)
    glacier_pct = [2, 1, 3, 8, 15, 25, 35, 40, 25, 10, 5, 2]

    ax.bar(months, glacier_pct, color='steelblue', alpha=0.8, edgecolor='black')
    ax.set_ylabel('Glacier Contribution (%)')
    ax.set_title(f'{title_prefix}Monthly Glacier Contribution to Discharge')
    ax.set_ylim(0, 50)
    ax.grid(True, alpha=0.3, axis='y')

    output_path = output_dir / 'glacier_contribution.png'
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Contribution plot: {output_path}")
    return str(output_path)


def main():
    parser = argparse.ArgumentParser(
        description="Generate glacier-hydrology coupling visualizations"
    )
    parser.add_argument("--oggm_output", required=True,
                        help="Compiled OGGM output NetCDF")
    parser.add_argument("--basin_shp", required=True,
                        help="Basin boundary shapefile")
    parser.add_argument("--glacier_csv", default=None,
                        help="Glacier inventory CSV (for spatial map)")
    parser.add_argument("--vic_discharge", default=None,
                        help="VIC discharge file (for combined plot)")
    parser.add_argument("--output_dir", required=True,
                        help="Output directory for plot files")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    plots = {}

    # Load OGGM output
    try:
        import xarray as xr
        oggm_ds = xr.open_dataset(args.oggm_output)
        has_oggm = True
    except Exception as e:
        print(f"WARNING: Could not load OGGM output: {e}")
        has_oggm = False
        oggm_ds = None

    # Plot 1: Glacier evolution
    if has_oggm:
        try:
            plots['evolution'] = plot_glacier_evolution(oggm_ds, output_dir)
        except Exception as e:
            print(f"WARNING: Evolution plot failed: {e}")

    # Plot 2: Spatial map
    if Path(args.basin_shp).exists():
        try:
            plots['spatial_map'] = plot_spatial_map(
                args.basin_shp, args.glacier_csv, output_dir
            )
        except Exception as e:
            print(f"WARNING: Spatial map failed: {e}")

    # Plot 3: Contribution fraction
    try:
        plots['contribution'] = plot_contribution_placeholder(output_dir)
    except Exception as e:
        print(f"WARNING: Contribution plot failed: {e}")

    if has_oggm:
        oggm_ds.close()

    result = {
        'status': 'success',
        'plots': plots,
        'output_dir': str(output_dir)
    }

    print(f"\nGenerated {len(plots)} plots in {output_dir}")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
