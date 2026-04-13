#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
==========================================
Tool ID:      extract_sfincs_results
Stage:        s8_postprocess
Description:  Parse SFINCS NetCDF output (sfincs_map.nc, sfincs_his.nc).
              Extract flood depth, extent, max water level, discharge at obs points.
              Compute flood statistics.

Inputs:
  --map_nc:      Path to sfincs_map.nc
  --his_nc:      Path to sfincs_his.nc (optional)
  --grid_info:   Path to grid_info.json
  --output_dir:  Output directory

Outputs:
  - flood_max_depth.tif:  Max flood depth raster (GeoTIFF)
  - flood_extent.tif:     Binary flood extent raster
  - flood_stats.json:     Flood statistics
  - timeseries.csv:       Time series at observation points (if his_nc provided)

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
    if not Path(args.map_nc).exists():
        errors.append(f"sfincs_map.nc not found: {args.map_nc}")
    if args.his_nc and not Path(args.his_nc).exists():
        errors.append(f"sfincs_his.nc not found: {args.his_nc}")
    if args.grid_info and not Path(args.grid_info).exists():
        errors.append(f"Grid info not found: {args.grid_info}")
    if not args.output_dir:
        errors.append("--output_dir is required")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def process(args):
    import xarray as xr

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # --- Load grid info ---
    grid = None
    if args.grid_info:
        with open(args.grid_info) as f:
            grid = json.load(f)

    # --- Read sfincs_map.nc ---
    logger.info(f"Reading: {args.map_nc}")
    ds = xr.open_dataset(args.map_nc)
    logger.info(f"Variables: {list(ds.data_vars)}")
    logger.info(f"Dimensions: {dict(ds.dims)}")

    # Find water depth variable
    # CRITICAL: 'hmax' = max water DEPTH (what we want for flood mapping)
    #           'zsmax' = max water SURFACE elevation (NOT depth — includes bed level)
    #           'h' = instantaneous water depth at each timestep
    # Priority: hmax > h > zsmax (zsmax needs bed level subtraction)
    depth_var = None
    for candidate in ["hmax", "h", "point_zs", "zs_max", "zsmax", "zs"]:
        if candidate in ds.data_vars:
            depth_var = candidate
            break

    if depth_var is None:
        # Use first available variable
        depth_var = list(ds.data_vars)[0]
        logger.warning(f"No standard depth variable found, using '{depth_var}'")

    data = ds[depth_var]
    logger.info(f"Using variable '{depth_var}': shape={data.shape}, dtype={data.dtype}")

    # --- Compute max flood depth ---
    if "time" in data.dims or "timemax" in data.dims:
        max_depth = data.max(dim=[d for d in data.dims if "time" in d.lower()]).values
    else:
        max_depth = data.values

    # Ensure 2D
    if max_depth.ndim == 1:
        # Point-based output, reshape if grid info available
        if grid:
            nmax = grid["nmax"]
            mmax = grid["mmax"]
            if len(max_depth) == nmax * mmax:
                max_depth = max_depth.reshape(nmax, mmax)
            else:
                logger.warning(f"Cannot reshape {len(max_depth)} values to {nmax}x{mmax}")
        else:
            logger.warning("1D output data without grid info — cannot create raster")
    elif max_depth.ndim > 2:
        max_depth = max_depth.squeeze()

    logger.info(f"Max depth shape: {max_depth.shape}")

    # Replace nodata/negative with 0
    max_depth = np.where(np.isnan(max_depth), 0, max_depth)
    max_depth = np.where(max_depth < 0, 0, max_depth)

    # --- Flood extent ---
    flood_threshold = 0.05  # 5cm minimum to count as flooded
    flood_extent = (max_depth >= flood_threshold).astype(np.uint8)

    # --- Statistics ---
    if grid:
        dx = grid["dx"]
        dy = grid["dy"]
        cell_area_m2 = dx * dy
    else:
        cell_area_m2 = 100 * 100  # default 100m

    flooded_cells = int(np.sum(flood_extent))
    flooded_area_km2 = flooded_cells * cell_area_m2 / 1e6
    total_cells = int(max_depth.size)

    # Depth classes
    depth_classes = {
        "0-0.3m": int(np.sum((max_depth >= 0.05) & (max_depth < 0.3))),
        "0.3-1.0m": int(np.sum((max_depth >= 0.3) & (max_depth < 1.0))),
        "1.0-3.0m": int(np.sum((max_depth >= 1.0) & (max_depth < 3.0))),
        ">3.0m": int(np.sum(max_depth >= 3.0)),
    }

    # Flood volume
    flood_volume_m3 = float(np.sum(max_depth * cell_area_m2))

    stats = {
        "status": "success",
        "total_cells": total_cells,
        "flooded_cells": flooded_cells,
        "flood_fraction": round(flooded_cells / max(total_cells, 1), 4),
        "flooded_area_km2": round(flooded_area_km2, 3),
        "max_depth_m": round(float(np.max(max_depth)), 3),
        "mean_depth_flooded_m": round(float(np.mean(max_depth[flood_extent == 1])), 3) if flooded_cells > 0 else 0,
        "flood_volume_million_m3": round(flood_volume_m3 / 1e6, 3),
        "depth_classes_cells": depth_classes,
        "cell_area_m2": cell_area_m2,
        "depth_variable": depth_var,
    }

    logger.info(f"Flooded area: {flooded_area_km2:.3f} km2 ({flooded_cells} cells)")
    logger.info(f"Max depth: {stats['max_depth_m']:.2f} m")
    logger.info(f"Flood volume: {stats['flood_volume_million_m3']:.3f} million m3")

    # --- Save max depth as GeoTIFF ---
    if max_depth.ndim == 2 and grid:
        try:
            import rasterio
            from rasterio.transform import from_origin
            from pyproj import CRS

            x0 = grid["x0"]
            y0 = grid["y0"]
            dx = grid["dx"]
            dy = grid["dy"]
            nmax, mmax = max_depth.shape
            epsg = grid["epsg"]

            y_top = y0 + nmax * dy
            transform = from_origin(x0, y_top, dx, dy)

            depth_tif = output_dir / "flood_max_depth.tif"
            with rasterio.open(
                str(depth_tif), "w", driver="GTiff",
                width=mmax, height=nmax, count=1,
                dtype=np.float32, crs=CRS.from_epsg(epsg),
                transform=transform, nodata=-9999
            ) as dst:
                dst.write(max_depth.astype(np.float32), 1)
            logger.info(f"Saved: {depth_tif}")
            stats["flood_max_depth_tif"] = str(depth_tif)

            extent_tif = output_dir / "flood_extent.tif"
            with rasterio.open(
                str(extent_tif), "w", driver="GTiff",
                width=mmax, height=nmax, count=1,
                dtype=np.uint8, crs=CRS.from_epsg(epsg),
                transform=transform, nodata=255
            ) as dst:
                dst.write(flood_extent, 1)
            logger.info(f"Saved: {extent_tif}")
            stats["flood_extent_tif"] = str(extent_tif)

        except ImportError:
            logger.warning("rasterio not available — skipping GeoTIFF output")

    # --- Save max depth as numpy ---
    np.save(str(output_dir / "flood_max_depth.npy"), max_depth)

    # --- Extract time series from sfincs_his.nc ---
    if args.his_nc and Path(args.his_nc).exists():
        logger.info(f"Reading observation time series: {args.his_nc}")
        ds_his = xr.open_dataset(args.his_nc)
        logger.info(f"His variables: {list(ds_his.data_vars)}")

        # Export to CSV
        ts_path = output_dir / "timeseries.csv"
        try:
            df = ds_his.to_dataframe()
            df.to_csv(str(ts_path))
            logger.info(f"Saved time series: {ts_path}")
            stats["timeseries_csv"] = str(ts_path)
        except Exception as e:
            logger.warning(f"Could not export time series: {e}")

        ds_his.close()

    ds.close()

    # --- Save stats ---
    stats_path = output_dir / "flood_stats.json"
    with open(stats_path, "w") as f:
        json.dump(stats, f, indent=2)

    print(json.dumps(stats, indent=2))
    return str(stats_path)


def validate_outputs(output_path):
    if not Path(output_path).exists():
        logger.error(f"Flood stats not created: {output_path}")
        sys.exit(3)
    with open(output_path) as f:
        data = json.load(f)
    if data.get("total_cells", 0) == 0:
        logger.error("No cells in output")
        sys.exit(3)
    logger.info("Output validation passed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract SFINCS flood results")
    parser.add_argument("--map_nc", required=True, help="Path to sfincs_map.nc")
    parser.add_argument("--his_nc", default=None, help="Path to sfincs_his.nc")
    parser.add_argument("--grid_info", default=None, help="Path to grid_info.json")
    parser.add_argument("--output_dir", required=True, help="Output directory")
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
