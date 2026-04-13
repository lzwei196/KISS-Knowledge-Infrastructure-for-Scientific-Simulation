#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
============================================
Tool ID:      plot_crhm_results
Stage:        s5_execution
Description:  Generate diagnostic plots for CRHM output: SWE, discharge,
              sublimation, water balance components.

Plots generated:
  1. SWE time series (per HRU if multiple)
  2. Discharge/outflow time series
  3. Water balance: precip, ET, runoff, storage change
  4. Cold regions diagnostics: sublimation, blowing snow transport
  5. Soil moisture and infiltration

Inputs:
  --csv_path:    Parsed CRHM results CSV
  --output_dir:  Directory for plot PNGs
  --title:       Plot title prefix

Exit codes:
  0 -- success
  1 -- input error
  2 -- processing error
  3 -- output validation failed
"""

import sys
import os
import json
import logging
import argparse
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def parse_args():
    parser = argparse.ArgumentParser(description="Plot CRHM results")
    parser.add_argument("--csv_path", type=str, required=True, help="Parsed CRHM CSV")
    parser.add_argument("--output_dir", type=str, required=True, help="Output directory for plots")
    parser.add_argument("--title", type=str, default="CRHM Results", help="Plot title prefix")
    return parser.parse_args()


def validate_inputs(csv_path, output_dir):
    errors = []
    if not Path(csv_path).exists():
        errors.append(f"CSV file not found: {csv_path}")
    if not output_dir:
        errors.append("Output directory not set")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)


def process(csv_path, output_dir, title):
    """Generate plots from parsed CRHM output."""
    import pandas as pd
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(csv_path, parse_dates=["datetime"], index_col="datetime")
    logger.info(f"Loaded {len(df)} rows, {len(df.columns)} columns")

    # Identify available variable categories
    swe_cols = [c for c in df.columns if "SWE" in c.upper() or "swe" in c]
    discharge_cols = [c for c in df.columns if "outflow" in c.lower() or "WS_outflow" in c]
    snowmelt_cols = [c for c in df.columns if "snowmelt" in c.lower() or "melt" in c.lower()]
    subl_cols = [c for c in df.columns if "subl" in c.lower() or "Subl" in c]
    drift_cols = [c for c in df.columns if "drift" in c.lower()]
    soil_cols = [c for c in df.columns if "soil_moist" in c.lower()]
    et_cols = [c for c in df.columns if "ET" in c or "et_act" in c.lower()]
    infil_cols = [c for c in df.columns if "infil" in c.lower()]
    runoff_cols = [c for c in df.columns if "runoff" in c.lower()]

    plots_created = []

    # 1. SWE time series
    if swe_cols:
        fig, ax = plt.subplots(figsize=(12, 5))
        for col in swe_cols:
            ax.plot(df.index, df[col], label=col, linewidth=0.8)
        ax.set_ylabel("SWE (mm)")
        ax.set_title(f"{title} -- Snow Water Equivalent")
        ax.legend(fontsize=8, ncol=min(4, len(swe_cols)))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        path = out_dir / "swe_timeseries.png"
        fig.savefig(path, dpi=150)
        plt.close(fig)
        plots_created.append(str(path))
        logger.info(f"SWE plot: {path}")

    # 2. Discharge / outflow
    if discharge_cols:
        fig, ax = plt.subplots(figsize=(12, 5))
        for col in discharge_cols:
            ax.plot(df.index, df[col], label=col, linewidth=0.8)
        ax.set_ylabel("Outflow (m3/s)")
        ax.set_title(f"{title} -- Watershed Outflow")
        ax.legend(fontsize=8)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        path = out_dir / "discharge_timeseries.png"
        fig.savefig(path, dpi=150)
        plt.close(fig)
        plots_created.append(str(path))
        logger.info(f"Discharge plot: {path}")

    # 3. Water balance components
    wb_cols = snowmelt_cols + et_cols + runoff_cols + infil_cols
    if wb_cols:
        fig, axes = plt.subplots(len(wb_cols), 1, figsize=(12, 3 * len(wb_cols)), sharex=True)
        if len(wb_cols) == 1:
            axes = [axes]
        for ax, col in zip(axes, wb_cols):
            ax.plot(df.index, df[col], linewidth=0.8, color="steelblue")
            ax.set_ylabel(col)
            ax.grid(True, alpha=0.3)
        axes[0].set_title(f"{title} -- Water Balance Components")
        axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
        fig.tight_layout()
        path = out_dir / "water_balance.png"
        fig.savefig(path, dpi=150)
        plt.close(fig)
        plots_created.append(str(path))
        logger.info(f"Water balance plot: {path}")

    # 4. Cold regions diagnostics (sublimation, drift)
    cold_cols = subl_cols + drift_cols
    if cold_cols:
        fig, axes = plt.subplots(len(cold_cols), 1, figsize=(12, 3 * len(cold_cols)), sharex=True)
        if len(cold_cols) == 1:
            axes = [axes]
        for ax, col in zip(axes, cold_cols):
            ax.plot(df.index, df[col], linewidth=0.8, color="darkorange")
            ax.set_ylabel(col)
            ax.grid(True, alpha=0.3)
        axes[0].set_title(f"{title} -- Cold Regions Processes")
        axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
        fig.tight_layout()
        path = out_dir / "cold_regions_diagnostics.png"
        fig.savefig(path, dpi=150)
        plt.close(fig)
        plots_created.append(str(path))
        logger.info(f"Cold regions plot: {path}")

    # 5. Soil moisture
    if soil_cols:
        fig, ax = plt.subplots(figsize=(12, 5))
        for col in soil_cols:
            ax.plot(df.index, df[col], label=col, linewidth=0.8)
        ax.set_ylabel("Soil Moisture (mm)")
        ax.set_title(f"{title} -- Soil Moisture")
        ax.legend(fontsize=8)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        path = out_dir / "soil_moisture.png"
        fig.savefig(path, dpi=150)
        plt.close(fig)
        plots_created.append(str(path))
        logger.info(f"Soil moisture plot: {path}")

    if not plots_created:
        logger.warning("No recognized variables found for plotting")
        # Create a simple overview plot with whatever columns exist
        fig, ax = plt.subplots(figsize=(12, 5))
        for col in df.columns[:5]:
            ax.plot(df.index, df[col], label=col, linewidth=0.8)
        ax.set_title(f"{title} -- Overview")
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        path = out_dir / "overview.png"
        fig.savefig(path, dpi=150)
        plt.close(fig)
        plots_created.append(str(path))

    return plots_created


def validate_outputs(plot_paths):
    errors = []
    for path in plot_paths:
        if not Path(path).exists():
            errors.append(f"Plot not created: {path}")
        elif Path(path).stat().st_size == 0:
            errors.append(f"Plot file is empty: {path}")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(3)
    logger.info("Output validation passed.")


if __name__ == "__main__":
    args = parse_args()
    logger.info(f"Running tool: {os.path.basename(__file__)}")

    validate_inputs(args.csv_path, args.output_dir)

    try:
        plots = process(args.csv_path, args.output_dir, args.title)
    except SystemExit:
        raise
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(2)

    validate_outputs(plots)

    print(json.dumps({"status": "success", "plots": plots}))
    sys.exit(0)
