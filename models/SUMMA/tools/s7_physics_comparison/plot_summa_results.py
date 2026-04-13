#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
============================================
Tool ID:      plot_summa_results
Stage:        s7_physics_comparison
Description:  Plot SUMMA results: time series, soil profiles, energy balance,
              multi-physics comparison panels.

Plot types:
  - timeseries:    runoff, ET, SWE time series for one run
  - soil_profile:  vertical soil moisture/temperature profile
  - energy_balance: radiation components, latent/sensible heat
  - comparison:    overlay results from multiple physics variants

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import json
import logging
import numpy as np
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
OUTPUT_NC = ""           # single file or comma-separated list
PLOT_TYPE = "timeseries" # timeseries, soil_profile, energy_balance, comparison
OUTPUT_PNG = ""
TITLE = "SUMMA Results"
LABELS = ""              # comma-separated labels for comparison plots

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

if len(sys.argv) > 1:
    import argparse
    parser = argparse.ArgumentParser(description="Plot SUMMA results")
    parser.add_argument("--output_nc", required=True,
                        help="SUMMA output NC (comma-separated for comparison)")
    parser.add_argument("--plot_type", default="timeseries",
                        choices=['timeseries', 'soil_profile', 'energy_balance', 'comparison'])
    parser.add_argument("--output_png", required=True)
    parser.add_argument("--title", default="SUMMA Results")
    parser.add_argument("--labels", default="", help="Comma-separated labels")
    args = parser.parse_args()
    OUTPUT_NC = args.output_nc
    PLOT_TYPE = args.plot_type
    OUTPUT_PNG = args.output_png
    TITLE = args.title
    LABELS = args.labels


def validate_inputs():
    errors = []
    files = OUTPUT_NC.split(',') if OUTPUT_NC else []
    for f in files:
        if not Path(f.strip()).exists():
            errors.append(f"Output NC not found: {f.strip()}")
    if not OUTPUT_PNG:
        errors.append("OUTPUT_PNG not set")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def validate_outputs(output_path):
    if not Path(output_path).exists():
        logger.error(f"Plot not created: {output_path}")
        sys.exit(3)
    logger.info("Output validation passed.")


def process():
    """Generate plots."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from netCDF4 import Dataset, num2date

    os.makedirs(os.path.dirname(OUTPUT_PNG) or '.', exist_ok=True)

    nc_files = [f.strip() for f in OUTPUT_NC.split(',')]
    labels = [l.strip() for l in LABELS.split(',')] if LABELS else \
             [Path(f).stem for f in nc_files]

    if PLOT_TYPE == 'timeseries':
        fig, axes = plt.subplots(3, 1, figsize=(14, 10), sharex=True)

        variables = [
            ('scalarTotalRunoff', 'Runoff (mm/day)', 86400 * 1000),  # m/s -> mm/day
            ('scalarTotalET', 'ET (mm/day)', 86400),  # kg/m2/s -> mm/day
            ('scalarSWE', 'SWE (mm)', 1.0),  # kg/m2 = mm
        ]

        for nc_file, label in zip(nc_files, labels):
            ds = Dataset(nc_file, 'r')
            time_var = ds.variables['time']
            times = num2date(time_var[:], time_var.units,
                             time_var.calendar if hasattr(time_var, 'calendar') else 'standard')

            for ax, (var_name, ylabel, scale) in zip(axes, variables):
                if var_name in ds.variables:
                    vals = ds.variables[var_name][:, 0] * scale  # first HRU
                    ax.plot(times, vals, label=label, alpha=0.8, linewidth=0.8)
                    ax.set_ylabel(ylabel)

            ds.close()

        for ax in axes:
            ax.legend(fontsize=8)
            ax.grid(True, alpha=0.3)
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
        axes[-1].set_xlabel('Date')
        axes[0].set_title(TITLE)

    elif PLOT_TYPE == 'comparison':
        # Bar chart comparison of mean values
        n_files = len(nc_files)
        variables = ['scalarTotalRunoff', 'scalarSWE', 'scalarTotalET']
        fig, axes = plt.subplots(1, len(variables), figsize=(5 * len(variables), 5))
        if len(variables) == 1:
            axes = [axes]

        means = {v: [] for v in variables}
        for nc_file in nc_files:
            ds = Dataset(nc_file, 'r')
            for var in variables:
                if var in ds.variables:
                    vals = ds.variables[var][:]
                    means[var].append(float(np.nanmean(vals)))
                else:
                    means[var].append(0)
            ds.close()

        x = np.arange(n_files)
        bar_labels = {'scalarTotalRunoff': 'Mean Runoff (m/s)',
                      'scalarSWE': 'Mean SWE (kg/m2)',
                      'scalarTotalET': 'Mean ET (kg/m2/s)'}
        colors = plt.cm.Set2(np.linspace(0, 1, n_files))

        for ax, var in zip(axes, variables):
            bars = ax.bar(x, means[var], color=colors, width=0.6)
            ax.set_xticks(x)
            ax.set_xticklabels(labels, rotation=45, ha='right', fontsize=8)
            ax.set_ylabel(bar_labels.get(var, var))
            ax.set_title(var)
            ax.grid(True, alpha=0.3, axis='y')

        fig.suptitle(TITLE, fontsize=14)

    elif PLOT_TYPE == 'soil_profile':
        fig, axes = plt.subplots(1, 2, figsize=(10, 6))

        for nc_file, label in zip(nc_files, labels):
            ds = Dataset(nc_file, 'r')
            if 'mLayerVolFracLiq' in ds.variables:
                liq = np.nanmean(ds.variables['mLayerVolFracLiq'][:, :, 0], axis=0)
                depths = np.cumsum(ds.variables['mLayerDepth'][:, 0])
                axes[0].plot(liq, -depths, 'o-', label=label, markersize=4)
                axes[0].set_xlabel('Vol. Liquid Fraction (-)')
                axes[0].set_ylabel('Depth (m)')
                axes[0].set_title('Soil Moisture Profile')
            if 'mLayerTemp' in ds.variables:
                temp = np.nanmean(ds.variables['mLayerTemp'][:, :, 0], axis=0) - 273.15
                depths = np.cumsum(ds.variables['mLayerDepth'][:, 0])
                axes[1].plot(temp, -depths, 'o-', label=label, markersize=4)
                axes[1].set_xlabel('Temperature (C)')
                axes[1].set_ylabel('Depth (m)')
                axes[1].set_title('Soil Temperature Profile')
            ds.close()

        for ax in axes:
            ax.legend()
            ax.grid(True, alpha=0.3)
        fig.suptitle(TITLE)

    elif PLOT_TYPE == 'energy_balance':
        fig, ax = plt.subplots(1, 1, figsize=(14, 6))
        energy_vars = [
            ('scalarNetRadiation', 'Net Radiation'),
            ('scalarLatHeatTotal', 'Latent Heat'),
            ('scalarSenHeatTotal', 'Sensible Heat'),
            ('scalarGroundHeatFlux', 'Ground Heat'),
        ]
        for nc_file in nc_files[:1]:  # just first file
            ds = Dataset(nc_file, 'r')
            time_var = ds.variables['time']
            times = num2date(time_var[:], time_var.units,
                             time_var.calendar if hasattr(time_var, 'calendar') else 'standard')
            for var_name, label in energy_vars:
                if var_name in ds.variables:
                    vals = ds.variables[var_name][:, 0]
                    # Monthly mean
                    ax.plot(times, vals, label=label, alpha=0.7, linewidth=0.5)
            ds.close()
        ax.set_ylabel('Energy Flux (W/m2)')
        ax.set_title(f'{TITLE} - Energy Balance')
        ax.legend()
        ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(OUTPUT_PNG, dpi=150, bbox_inches='tight')
    plt.close()

    logger.info(f"Plot saved: {OUTPUT_PNG}")
    print(json.dumps({
        "status": "success",
        "plot_type": PLOT_TYPE,
        "output": OUTPUT_PNG,
        "n_files": len(nc_files)
    }))

    return OUTPUT_PNG


if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs()
    try:
        output = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(2)
    validate_outputs(output)
    sys.exit(0)
