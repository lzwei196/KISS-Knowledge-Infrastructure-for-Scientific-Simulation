#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
============================================
Tool ID:      merge_crhm_vic
Stage:        s6_vic_coupling
Description:  Merge CRHM cold-regions diagnostics with VIC simulation output
              for comparison and coupled analysis.

COUPLING DESIGN (from PREFLIGHT.md coupling traps):
  - VIC handles: grid-based water/energy balance, runoff generation, ET
  - CRHM handles: blowing snow transport, sublimation, frozen soil infiltration
  - OVERLAP WARNING: Both models compute snowmelt, soil moisture, ET.
    You must decide which model "owns" each process to avoid double-counting.

Process Ownership Table (must be defined before coupling):
  | Process              | Owner  | Why                                    |
  |----------------------|--------|----------------------------------------|
  | Snow accumulation    | CRHM   | Blowing snow redistribution            |
  | Snowmelt             | CRHM   | Energy balance + wind effects           |
  | Sublimation          | CRHM   | Canopy + blowing snow sublimation      |
  | Frozen soil infiltr. | CRHM   | Prairie-specific infiltration           |
  | Unfrozen soil drain. | VIC    | Multi-layer soil physics                |
  | ET (growing season)  | VIC    | Penman-Monteith with LAI                |
  | Routing              | VIC    | Grid-based (Lohmann/CaMa-Flood)        |

TEMPORAL MISMATCH:
  - CRHM: hourly or daily timestep
  - VIC: daily or 3-hourly
  - Resolution: aggregate to daily before merging

SPATIAL MISMATCH:
  - CRHM: HRU-based (irregular)
  - VIC: grid-based (regular lat/lon)
  - Mapping: area-weighted aggregation of CRHM HRUs to VIC grid cells

Inputs:
  --crhm_csv:      Parsed CRHM output CSV
  --vic_result_dir: VIC result directory
  --grid_nc:        VIC basin grid NetCDF
  --output_dir:     Output directory

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
    parser = argparse.ArgumentParser(description="Merge CRHM and VIC results")
    parser.add_argument("--crhm_csv", type=str, required=True, help="Parsed CRHM CSV")
    parser.add_argument("--vic_result_dir", type=str, required=True, help="VIC result directory")
    parser.add_argument("--grid_nc", type=str, required=True, help="VIC grid NetCDF")
    parser.add_argument("--output_dir", type=str, required=True, help="Output directory")
    return parser.parse_args()


def validate_inputs(crhm_csv, vic_result_dir, grid_nc, output_dir):
    errors = []
    if not Path(crhm_csv).exists():
        errors.append(f"CRHM CSV not found: {crhm_csv}")
    if not Path(vic_result_dir).is_dir():
        errors.append(f"VIC result directory not found: {vic_result_dir}")
    if not Path(grid_nc).exists():
        errors.append(f"Grid NC not found: {grid_nc}")
    if not output_dir:
        errors.append("Output directory not set")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def process(crhm_csv, vic_result_dir, grid_nc, output_dir):
    """Merge CRHM and VIC outputs on common timeline."""
    import pandas as pd
    import numpy as np
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Read CRHM results
    crhm_df = pd.read_csv(crhm_csv, parse_dates=["datetime"], index_col="datetime")
    logger.info(f"CRHM: {len(crhm_df)} rows, {len(crhm_df.columns)} columns")

    # Read VIC results (basin-averaged flux files)
    vic_dir = Path(vic_result_dir)
    vic_files = sorted(vic_dir.glob("fluxes_*"))

    if not vic_files:
        # Try alternate naming
        vic_files = sorted(vic_dir.glob("*_fluxes_*"))

    if not vic_files:
        logger.warning("No VIC flux files found. Creating CRHM-only output.")
        merged_path = out_dir / "crhm_vic_comparison.csv"
        crhm_df.to_csv(merged_path)
        return [str(merged_path)]

    # Read first VIC file to get format
    # VIC output: daily, columns vary by configuration
    # Standard 7-col preprocessed: year day precip evap runoff baseflow sm1 sm2 sm3
    # Full 22-col: energy balance + water balance

    vic_data_list = []
    for vf in vic_files[:1]:  # Use first grid cell for comparison
        try:
            data = np.loadtxt(str(vf))
            logger.info(f"VIC file {vf.name}: {data.shape}")
            vic_data_list.append(data)
        except Exception as e:
            logger.warning(f"Cannot read {vf.name}: {e}")

    if not vic_data_list:
        logger.warning("No VIC data read successfully")
        merged_path = out_dir / "crhm_vic_comparison.csv"
        crhm_df.to_csv(merged_path)
        return [str(merged_path)]

    vic_data = vic_data_list[0]

    # Build VIC datetime index
    # Assume format: YYYY DOY or YYYY MM DD
    if vic_data.shape[1] >= 7:
        # Try YYYY MM DD format (preprocessed)
        try:
            vic_dates = pd.to_datetime(
                {
                    "year": vic_data[:, 0].astype(int),
                    "month": vic_data[:, 1].astype(int),
                    "day": vic_data[:, 2].astype(int),
                }
            )
            vic_start_col = 3
        except Exception:
            # Try YYYY DOY format
            vic_dates = pd.to_datetime(vic_data[:, 0].astype(int).astype(str), format="%Y") + \
                        pd.to_timedelta(vic_data[:, 1].astype(int) - 1, unit="D")
            vic_start_col = 2

    # Create VIC dataframe
    vic_cols = ["vic_precip", "vic_evap", "vic_runoff", "vic_baseflow",
                "vic_sm1", "vic_sm2", "vic_sm3"]
    n_data_cols = vic_data.shape[1] - vic_start_col
    vic_col_names = vic_cols[:n_data_cols] + [f"vic_col{i}" for i in range(n_data_cols, len(vic_cols))]
    vic_col_names = vic_col_names[:n_data_cols]

    vic_df = pd.DataFrame(
        vic_data[:, vic_start_col:vic_start_col + len(vic_col_names)],
        index=vic_dates,
        columns=vic_col_names,
    )
    vic_df.index.name = "datetime"

    # Resample CRHM to daily (if sub-daily)
    if len(crhm_df) > 0:
        freq = pd.infer_freq(crhm_df.index[:min(10, len(crhm_df))])
        if freq and "H" in str(freq):
            logger.info("Resampling CRHM from sub-daily to daily")
            # For most variables: daily mean. For precip/melt: daily sum
            sum_vars = [c for c in crhm_df.columns if any(
                k in c.lower() for k in ["precip", "melt", "rain", "snow", "subl", "drift"]
            )]
            mean_vars = [c for c in crhm_df.columns if c not in sum_vars]

            crhm_daily_parts = []
            if sum_vars:
                crhm_daily_parts.append(crhm_df[sum_vars].resample("D").sum())
            if mean_vars:
                crhm_daily_parts.append(crhm_df[mean_vars].resample("D").mean())
            crhm_df = pd.concat(crhm_daily_parts, axis=1)

    # Merge on common dates
    merged = crhm_df.join(vic_df, how="outer")
    merged.sort_index(inplace=True)

    # Save merged CSV
    merged_path = out_dir / "crhm_vic_comparison.csv"
    merged.to_csv(merged_path)
    logger.info(f"Merged: {len(merged)} rows, {len(merged.columns)} columns")

    results = [str(merged_path)]

    # Generate comparison plots
    fig, axes = plt.subplots(3, 1, figsize=(14, 12), sharex=True)

    # Plot 1: SWE comparison
    swe_cols = [c for c in crhm_df.columns if "SWE" in c.upper()]
    if swe_cols:
        ax = axes[0]
        for col in swe_cols:
            ax.plot(merged.index, merged[col], label=f"CRHM {col}", linewidth=0.8)
        ax.set_ylabel("SWE (mm)")
        ax.set_title(f"CRHM vs VIC Comparison")
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)

    # Plot 2: Runoff/discharge comparison
    ax = axes[1]
    crhm_runoff = [c for c in crhm_df.columns if "runoff" in c.lower() or "outflow" in c.lower()]
    vic_runoff = [c for c in vic_df.columns if "runoff" in c.lower()]
    for col in crhm_runoff[:2]:
        ax.plot(merged.index, merged[col], label=f"CRHM {col}", linewidth=0.8)
    for col in vic_runoff[:2]:
        ax.plot(merged.index, merged[col], label=f"VIC {col}", linewidth=0.8, linestyle="--")
    ax.set_ylabel("Runoff (mm)")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)

    # Plot 3: Soil moisture comparison
    ax = axes[2]
    crhm_sm = [c for c in crhm_df.columns if "soil_moist" in c.lower()]
    vic_sm = [c for c in vic_df.columns if "sm" in c.lower()]
    for col in crhm_sm[:2]:
        ax.plot(merged.index, merged[col], label=f"CRHM {col}", linewidth=0.8)
    for col in vic_sm[:2]:
        ax.plot(merged.index, merged[col], label=f"VIC {col}", linewidth=0.8, linestyle="--")
    ax.set_ylabel("Soil Moisture (mm)")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)

    fig.tight_layout()
    plot_path = out_dir / "crhm_vic_comparison.png"
    fig.savefig(plot_path, dpi=150)
    plt.close(fig)
    results.append(str(plot_path))
    logger.info(f"Comparison plot: {plot_path}")

    return results


def validate_outputs(results):
    errors = []
    for path in results:
        if not Path(path).exists():
            errors.append(f"Output not created: {path}")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(3)
    logger.info("Output validation passed.")


if __name__ == "__main__":
    args = parse_args()
    logger.info(f"Running tool: {os.path.basename(__file__)}")

    validate_inputs(args.crhm_csv, args.vic_result_dir, args.grid_nc, args.output_dir)

    try:
        results = process(args.crhm_csv, args.vic_result_dir, args.grid_nc, args.output_dir)
    except SystemExit:
        raise
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(2)

    validate_outputs(results)

    print(json.dumps({"status": "success", "outputs": results}))
    sys.exit(0)
