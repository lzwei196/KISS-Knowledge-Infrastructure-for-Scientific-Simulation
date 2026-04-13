#!/usr/bin/env python3
"""
plot_glm_results.py — Generate GLM output visualizations.

Produces:
  1. Temperature heatmap (depth vs time) — the signature GLM visualization
  2. Surface and bottom temperature time series
  3. Lake level time series
  4. Ice thickness (if present)

Usage:
    python plot_glm_results.py --output_nc output/output.nc \
        --lake_csv output/lake.csv --output glm_results.png \
        --title "Sparkling Lake GLM Simulation"
"""

import argparse
import json
import os
import sys

import numpy as np
import pandas as pd


def validate_inputs(args):
    """Validate inputs."""
    errors = []
    if args.output_nc and not os.path.exists(args.output_nc):
        errors.append(f"output.nc not found: {args.output_nc}")
    if args.lake_csv and not os.path.exists(args.lake_csv):
        errors.append(f"lake.csv not found: {args.lake_csv}")
    if not args.output_nc and not args.lake_csv:
        errors.append("Need at least --output_nc or --lake_csv")
    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)


def process(args):
    """Generate plots."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    # Determine number of subplots
    panels = []
    if args.output_nc and os.path.exists(args.output_nc):
        panels.append('temp_heatmap')
    if args.lake_csv and os.path.exists(args.lake_csv):
        lake_df = pd.read_csv(args.lake_csv)
        # Find time column
        time_col = None
        for col in lake_df.columns:
            if 'time' in col.lower() or 'date' in col.lower():
                time_col = col
                break
        if time_col:
            # GLM outputs "24:00:00" timestamps — fix before parsing
            lake_df[time_col] = lake_df[time_col].apply(
                lambda x: str(x).replace(' 24:00:00', ' 00:00:00')
                if ' 24:00:00' in str(x) else str(x))
            lake_df[time_col] = pd.to_datetime(lake_df[time_col], errors='coerce')
            lake_df = lake_df.rename(columns={time_col: 'time'})

        # Check what data is available
        temp_cols = [c for c in lake_df.columns
                     if 'temp' in c.lower() and c != 'time']
        level_cols = [c for c in lake_df.columns
                      if 'level' in c.lower() or 'lvl' in c.lower()]
        ice_cols = [c for c in lake_df.columns
                    if ('blue ice' in c.lower() and 'thick' in c.lower()) or
                    ('white ice' in c.lower() and 'thick' in c.lower())]

        if temp_cols:
            panels.append('surface_temp')
        if level_cols:
            panels.append('lake_level')
        if ice_cols and float(lake_df[ice_cols[0]].max()) > 0.01:
            panels.append('ice')

    n_panels = max(len(panels), 1)
    fig, axes = plt.subplots(n_panels, 1, figsize=(14, 4 * n_panels),
                             sharex=True if n_panels > 1 else False)
    if n_panels == 1:
        axes = [axes]

    panel_idx = 0

    # Panel 1: Temperature heatmap from output.nc
    if 'temp_heatmap' in panels:
        ax = axes[panel_idx]
        panel_idx += 1

        try:
            import netCDF4 as nc
            ds = nc.Dataset(args.output_nc)

            # Get temperature
            temp = None
            for vname in ['temp', 'temperature', 'TEMP']:
                if vname in ds.variables:
                    temp = ds.variables[vname][:]
                    break

            # Get time
            time_var = ds.variables.get('time')
            if time_var:
                try:
                    times = nc.num2date(time_var[:], time_var.units)
                    times = pd.DatetimeIndex([
                        pd.Timestamp(t.year, t.month, t.day, t.hour, t.minute)
                        for t in times
                    ])
                except Exception:
                    times = np.arange(temp.shape[0])

            # Get depth
            z = None
            for vname in ['z', 'NS', 'depth', 'heights']:
                if vname in ds.variables:
                    z = ds.variables[vname][:]
                    break

            ds.close()

            if temp is not None:
                # Temperature is typically (time, depth)
                if z is not None and len(z.shape) == 1:
                    depths = z
                else:
                    depths = np.arange(temp.shape[1]) if len(temp.shape) > 1 else np.arange(1)

                if len(temp.shape) == 2:
                    # Mask invalid values
                    temp_masked = np.ma.masked_where(
                        np.isnan(temp) | (temp > 50) | (temp < -5), temp)

                    im = ax.pcolormesh(times, depths, temp_masked.T,
                                       cmap='RdYlBu_r', shading='auto')
                    cbar = plt.colorbar(im, ax=ax, label='Temperature (degC)')
                    ax.set_ylabel('Depth (m)')
                    ax.set_title(f'{args.title} - Temperature Profile')
                    ax.invert_yaxis()
        except Exception as e:
            ax.text(0.5, 0.5, f'Could not plot heatmap:\n{e}',
                    transform=ax.transAxes, ha='center', va='center')
            ax.set_title('Temperature Heatmap (error)')

    # Panel 2: Surface temperature from lake.csv
    if 'surface_temp' in panels:
        ax = axes[panel_idx]
        panel_idx += 1

        for col in temp_cols:
            label = col.replace('_', ' ').title()
            ax.plot(lake_df['time'], lake_df[col], linewidth=0.7, label=label)
        ax.set_ylabel('Temperature (degC)')
        ax.set_title(f'{args.title} - Temperature')
        ax.legend(loc='upper right', fontsize=8)
        ax.grid(True, alpha=0.3)

    # Panel 3: Lake level
    if 'lake_level' in panels:
        ax = axes[panel_idx]
        panel_idx += 1

        for col in level_cols:
            ax.plot(lake_df['time'], lake_df[col], linewidth=0.7,
                    color='steelblue')
        ax.set_ylabel('Lake Level (m)')
        ax.set_title(f'{args.title} - Lake Level')
        ax.grid(True, alpha=0.3)

    # Panel 4: Ice
    if 'ice' in panels:
        ax = axes[panel_idx]
        panel_idx += 1

        for col in ice_cols:
            ax.fill_between(lake_df['time'], 0, lake_df[col],
                            alpha=0.5, color='lightblue', label='Ice Thickness')
            ax.plot(lake_df['time'], lake_df[col], linewidth=0.5,
                    color='blue')
        ax.set_ylabel('Ice Thickness (m)')
        ax.set_title(f'{args.title} - Ice Cover')
        ax.grid(True, alpha=0.3)

    # Format x-axis
    if n_panels > 1:
        axes[-1].xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
        axes[-1].xaxis.set_major_locator(mdates.YearLocator())
        axes[-1].set_xlabel('Date')

    plt.tight_layout()
    os.makedirs(os.path.dirname(args.output) or '.', exist_ok=True)
    plt.savefig(args.output, dpi=args.dpi, bbox_inches='tight')
    plt.close()

    print(f"Plot saved to {args.output}", file=sys.stderr)
    return {"status": "success", "output_file": args.output, "panels": panels}


def main():
    parser = argparse.ArgumentParser(
        description="Generate GLM output visualizations")
    parser.add_argument("--output_nc", type=str,
                        help="GLM output.nc path")
    parser.add_argument("--lake_csv", type=str,
                        help="GLM lake.csv path")
    parser.add_argument("--output", type=str, required=True,
                        help="Output plot file path (.png)")
    parser.add_argument("--title", type=str, default="GLM Simulation",
                        help="Plot title")
    parser.add_argument("--dpi", type=int, default=150,
                        help="Plot resolution (default: 150)")
    args = parser.parse_args()

    validate_inputs(args)
    result = process(args)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
