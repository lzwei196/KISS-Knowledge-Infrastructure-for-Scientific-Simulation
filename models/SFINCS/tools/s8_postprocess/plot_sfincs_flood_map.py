#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
==========================================
Tool ID:      plot_sfincs_flood_map
Stage:        s8_postprocess
Description:  Generate flood inundation maps from SFINCS output. Publication-quality.

Inputs:
  --flood_depth:   Path to flood_max_depth.tif or flood_max_depth.npy
  --grid_info:     Path to grid_info.json
  --shp_path:      Basin shapefile for overlay (optional)
  --title:         Map title
  --output:        Output image path (PNG)

Outputs:
  - Flood map PNG with depth color scale, basin boundary, scale bar

Exit codes:
  0 — success, 1 — input error, 2 — processing error, 3 — output error
"""

import sys
import os
import json
import logging
import argparse
import numpy as np
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def validate_inputs(args):
    errors = []
    if not Path(args.flood_depth).exists():
        errors.append(f"Flood depth file not found: {args.flood_depth}")
    if args.grid_info and not Path(args.grid_info).exists():
        errors.append(f"Grid info not found: {args.grid_info}")
    if not args.output:
        errors.append("--output is required")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def process(args):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.colors as mcolors
    from matplotlib.patches import Patch

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Load flood depth data
    if args.flood_depth.endswith(".npy"):
        depth = np.load(args.flood_depth)
    elif args.flood_depth.endswith(".tif"):
        import rasterio
        with rasterio.open(args.flood_depth) as src:
            depth = src.read(1)
    else:
        logger.error(f"Unsupported format: {args.flood_depth}")
        sys.exit(2)

    # Replace nodata
    depth = np.where(depth < 0, np.nan, depth)
    depth = np.where(depth < 0.01, np.nan, depth)  # Ignore < 1cm

    # Load grid info for extent
    extent = None
    if args.grid_info:
        with open(args.grid_info) as f:
            grid = json.load(f)
        x0 = grid["x0"]
        y0 = grid["y0"]
        dx = grid["dx"]
        dy = grid["dy"]
        nmax, mmax = depth.shape if depth.ndim == 2 else (grid["nmax"], grid["mmax"])
        extent = [x0, x0 + mmax * dx, y0, y0 + nmax * dy]

    # --- Custom colormap for flood depth ---
    # 5 classes matching FEMA/SFINCS convention
    depth_levels = [0.01, 0.1, 0.3, 0.5, 1.0, 2.0, 5.0, 10.0]
    colors = [
        "#FFFFCC",  # 0.01-0.1: very shallow (yellow)
        "#C7E9B4",  # 0.1-0.3: shallow (light green)
        "#7FCDBB",  # 0.3-0.5: moderate (teal)
        "#41B6C4",  # 0.5-1.0: deep (blue-green)
        "#1D91C0",  # 1.0-2.0: very deep (blue)
        "#225EA8",  # 2.0-5.0: extreme (dark blue)
        "#0C2C84",  # >5.0: catastrophic (navy)
    ]

    cmap = mcolors.ListedColormap(colors)
    norm = mcolors.BoundaryNorm(depth_levels, cmap.N)

    # --- Plot ---
    fig, ax = plt.subplots(1, 1, figsize=(12, 10))

    if depth.ndim == 2:
        im = ax.imshow(depth, origin="lower", extent=extent, cmap=cmap, norm=norm,
                       interpolation="nearest", aspect="equal")
    else:
        logger.warning("1D depth data — creating simple bar plot")
        ax.bar(range(len(depth)), depth)

    # Colorbar
    cbar = plt.colorbar(im, ax=ax, shrink=0.7, pad=0.02)
    cbar.set_label("Flood Depth (m)", fontsize=12)

    # Legend patches
    legend_items = [
        Patch(facecolor="#FFFFCC", label="<0.1m (ankle)"),
        Patch(facecolor="#C7E9B4", label="0.1-0.3m (knee)"),
        Patch(facecolor="#7FCDBB", label="0.3-0.5m (waist)"),
        Patch(facecolor="#41B6C4", label="0.5-1.0m (chest)"),
        Patch(facecolor="#1D91C0", label="1.0-2.0m (head)"),
        Patch(facecolor="#225EA8", label="2.0-5.0m (building)"),
        Patch(facecolor="#0C2C84", label=">5.0m (severe)"),
    ]
    ax.legend(handles=legend_items, loc="lower right", fontsize=8,
              title="Depth Class", title_fontsize=9)

    # Basin outline
    if args.shp_path and Path(args.shp_path).exists():
        try:
            import geopandas as gpd
            gdf = gpd.read_file(args.shp_path)
            if args.grid_info:
                gdf = gdf.to_crs(f"EPSG:{grid['epsg']}")
            gdf.boundary.plot(ax=ax, color="red", linewidth=1.5, linestyle="--")
        except Exception as e:
            logger.warning(f"Could not overlay shapefile: {e}")

    # Labels
    title = args.title or "SFINCS Flood Inundation"
    ax.set_title(title, fontsize=14, fontweight="bold")
    ax.set_xlabel("Easting (m)", fontsize=11)
    ax.set_ylabel("Northing (m)", fontsize=11)

    # Stats annotation
    valid = depth[~np.isnan(depth)] if depth.ndim == 2 else depth[depth > 0]
    if len(valid) > 0:
        stats_text = (f"Max depth: {np.max(valid):.2f} m\n"
                      f"Flooded cells: {len(valid):,}\n"
                      f"Mean depth: {np.mean(valid):.2f} m")
        ax.text(0.02, 0.98, stats_text, transform=ax.transAxes,
                fontsize=9, verticalalignment="top",
                bbox=dict(boxstyle="round", facecolor="white", alpha=0.8))

    plt.tight_layout()
    plt.savefig(str(output_path), dpi=200, bbox_inches="tight")
    plt.close()

    logger.info(f"Saved flood map: {output_path}")
    print(json.dumps({"status": "success", "output": str(output_path)}))
    return str(output_path)


def validate_outputs(output_path):
    if not Path(output_path).exists():
        logger.error(f"Output not created: {output_path}")
        sys.exit(3)
    if Path(output_path).stat().st_size < 1000:
        logger.error("Output file suspiciously small")
        sys.exit(3)
    logger.info("Output validation passed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Plot SFINCS flood inundation map")
    parser.add_argument("--flood_depth", required=True, help="flood_max_depth.tif or .npy")
    parser.add_argument("--grid_info", default=None, help="Path to grid_info.json")
    parser.add_argument("--shp_path", default=None, help="Basin shapefile for overlay")
    parser.add_argument("--title", default=None, help="Map title")
    parser.add_argument("--output", required=True, help="Output PNG path")
    args = parser.parse_args()

    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs(args)

    try:
        output_path = process(args)
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(2)

    validate_outputs(output_path)
    sys.exit(0)
