#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
==========================================
Tool ID:      plot_head_map
Stage:        s9_postprocessing
Description:  Generate a water table contour map from MODFLOW 6 binary head file.
              Masks HDRY (1e30) cells. Optionally overlays basin boundary.

Inputs:
  - HDS_PATH: binary head file
  - MODEL_PATH: model workspace for grid info
  - OUTPUT_PNG: output image path
  - KSTPKPER: timestep/period to plot
  - SHAPEFILE_PATH: basin boundary for overlay (optional)

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import json
import logging
import numpy as np
from pathlib import Path

HDS_PATH = "KISSPATH_OUTPUTS/qinghai_lake_1951_2024/modflow6/workspace/gwf.hds"
MODEL_PATH = ""
OUTPUT_PNG = "KISSPATH_OUTPUTS/qinghai_lake_1951_2024/modflow6_head_map.png"
KSTPKPER = None  # None = last timestep
SHAPEFILE_PATH = ""
TITLE = "Water Table Elevation"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def validate_inputs():
    errors = []
    if not HDS_PATH or not Path(HDS_PATH).exists():
        errors.append(f"Head file not found: {HDS_PATH}")
    if not OUTPUT_PNG:
        errors.append("OUTPUT_PNG is not set")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)


def process():
    import flopy
    import flopy.utils.binaryfile as bf
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # Read heads
    hds = bf.HeadFile(HDS_PATH)
    if KSTPKPER:
        heads = hds.get_data(kstpkper=tuple(KSTPKPER))
    else:
        heads = hds.get_data(kstpkper=hds.get_kstpkper()[-1])

    # Mask HDRY
    heads_masked = np.where(heads > 0.9e30, np.nan, heads)

    # Get water table (top active layer)
    nlay, nrow, ncol = heads_masked.shape
    water_table = np.full((nrow, ncol), np.nan)
    for i in range(nrow):
        for j in range(ncol):
            for k in range(nlay):
                if not np.isnan(heads_masked[k, i, j]):
                    water_table[i, j] = heads_masked[k, i, j]
                    break

    # Plot
    fig, ax = plt.subplots(1, 1, figsize=(10, 8))

    # Contour fill
    wt_plot = np.ma.masked_invalid(water_table)
    if wt_plot.count() > 0:
        levels = np.linspace(np.nanmin(water_table), np.nanmax(water_table), 20)
        cs = ax.contourf(wt_plot, levels=levels, cmap="viridis")
        plt.colorbar(cs, ax=ax, label="Head (m)", shrink=0.8)
        ax.contour(wt_plot, levels=levels, colors="black", linewidths=0.3, alpha=0.5)

    # Overlay shapefile
    if SHAPEFILE_PATH and Path(SHAPEFILE_PATH).exists():
        try:
            import geopandas as gpd
            basin = gpd.read_file(SHAPEFILE_PATH)
            basin.boundary.plot(ax=ax, color="red", linewidth=2)
        except Exception as e:
            logger.warning(f"Could not overlay shapefile: {e}")

    ax.set_title(TITLE, fontsize=14)
    ax.set_xlabel("Column")
    ax.set_ylabel("Row")
    ax.set_aspect("equal")

    # Save
    output_path = Path(OUTPUT_PNG)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(output_path), dpi=150, bbox_inches="tight")
    plt.close(fig)

    logger.info(f"Water table map saved: {output_path}")
    return str(output_path)


def validate_outputs(output_path):
    if not Path(output_path).exists():
        logger.error(f"Output not created: {output_path}")
        sys.exit(3)
    if Path(output_path).stat().st_size < 1000:
        logger.warning("Output file is very small — plot may be empty")
    logger.info("Output validation passed.")


if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    if len(sys.argv) > 1:
        HDS_PATH = sys.argv[1]
    if len(sys.argv) > 2:
        OUTPUT_PNG = sys.argv[2]
    validate_inputs()
    try:
        output_path = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        sys.exit(2)
    validate_outputs(output_path)
    print(json.dumps({"output": output_path}))
    sys.exit(0)
