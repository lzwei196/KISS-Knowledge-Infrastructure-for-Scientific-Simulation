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


def open_sfincs_nc(path):
    """Open a SFINCS NetCDF-4 output file, tolerating a broken netCDF4/HDF5 stack.

    dt_v016 (found 2026-08-02, Kangerlussuaq run): the HydroCraft venv ships
    netCDF4 1.7.4 bundling HDF5 1.14.6, which raises
        OSError: [Errno -101] NetCDF: HDF error
    on every file SFINCS writes with its own libnetcdff (HDF5 1.10). ncdump, GDAL,
    h5py and the h5netcdf engine in the SAME venv all read the file fine, so this is
    a library defect, NOT a corrupt output — do not re-run the model. Try the default
    engine first (fast path when the stack is healthy), then fall back to h5netcdf.
    """
    import xarray as xr
    try:
        return xr.open_dataset(path)
    except OSError as e:
        logger.warning("Default NetCDF engine failed on %s (%s). "
                       "Falling back to engine='h5netcdf' (dt_v016).", path, e)
        return xr.open_dataset(path, engine="h5netcdf")


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
    ds = open_sfincs_nc(args.map_nc)
    logger.info(f"Variables: {list(ds.data_vars)}")
    logger.info(f"Dimensions: {dict(ds.dims)}")

    zb = None  # initialise; may be set below if zsmax fallback is needed

    # Find water depth variable
    # CRITICAL: 'hmax' = max water DEPTH (what we want for flood mapping)
    #           'zsmax' = max water SURFACE elevation (NOT depth — includes bed level)
    #           'h' = instantaneous water depth at each timestep
    # Priority: hmax > h > zsmax (zsmax needs bed level subtraction)
    #
    # dt_v007 / dt_v015: NEVER use zsmax/zs directly as flood depth.
    # For terrain at 40m elevation, zsmax=40m even with 0.05m of water.
    # This produces the "40-80m flood depths in flat agricultural areas" bug.
    depth_var = None
    for candidate in ["hmax", "h", "point_zs", "zs_max"]:
        if candidate in ds.data_vars:
            depth_var = candidate
            break

    if depth_var is None:
        # zsmax / zs are water surface ELEVATION, not depth.
        # If we must fall back to them, we need to subtract bed level (zb).
        for candidate in ["zsmax", "zs"]:
            if candidate in ds.data_vars:
                depth_var = candidate
                break
        if depth_var is not None:
            logger.error(
                "CRITICAL: Only '%s' (water surface ELEVATION) found in output — "
                "this is NOT flood depth. It equals bed_level + water_depth. "
                "For a 40m-elevation cell with 5cm of water, %s=40.05m but depth=0.05m. "
                "Subtracting 'zb' (bed level) to recover actual depth. "
                "To fix permanently: ensure SFINCS writes 'hmax' by confirming "
                "the binary version supports it (v2.1+), or add storemax=1 to sfincs.inp.",
                depth_var, depth_var
            )
            if "zb" in ds.data_vars:
                zb = ds["zb"].values
                logger.info("Subtracting bed level (zb) from %s to get flood depth", depth_var)
            else:
                logger.error(
                    "Cannot subtract bed level — 'zb' not in output. "
                    "Results will be water surface elevation, not flood depth. "
                    "This is the root cause of the 50-100x depth bug (dt_v015)."
                )
                zb = None

    if depth_var is None:
        # Last resort: use first available variable
        depth_var = list(ds.data_vars)[0]
        logger.warning(f"No standard depth variable found, using '{depth_var}'")

    data = ds[depth_var]
    logger.info(f"Using variable '{depth_var}': shape={data.shape}, dtype={data.dtype}")

    # --- Compute max flood depth ---
    if "time" in data.dims or "timemax" in data.dims:
        max_depth = data.max(dim=[d for d in data.dims if "time" in d.lower()]).values
    else:
        max_depth = data.values

    # If we had to fall back to zsmax/zs, subtract bed level now
    # (dt_v015: zsmax = zb + h, so h = zsmax - zb)
    if depth_var in ("zsmax", "zs") and "zb" in locals() and zb is not None:
        zb_2d = zb.squeeze() if zb.ndim > 2 else zb
        max_depth = max_depth.squeeze() if max_depth.ndim > 2 else max_depth
        if max_depth.shape == zb_2d.shape:
            max_depth = max_depth - zb_2d
            logger.info("Applied zb subtraction: depth = zsmax - zb (dt_v015 workaround)")

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

    # --- Drop SFINCS fill values and inactive cells BEFORE any statistic ---
    # dt_v017 (found 2026-08-02, Kangerlussuaq run): SFINCS writes +9999 into hmax
    # (and -9999 into zb) for every cell outside the active mask. The old code only
    # clipped NEGATIVE values, so those +9999 sentinels survived and the tool reported
    # "max flood depth 9999 m" with a flood volume ~10^6 times too large — a silent,
    # confidently-wrong result. Mask them out, and mask msk==0 cells where available.
    max_depth = np.asarray(max_depth, dtype=np.float64)
    fill_hit = int(np.sum(np.abs(max_depth) >= 9998.0))
    if fill_hit:
        logger.warning("Masked %d cells carrying the +/-9999 SFINCS fill value (dt_v017)", fill_hit)
    max_depth = np.where(np.abs(max_depth) >= 9998.0, np.nan, max_depth)

    active_mask = None
    if "msk" in ds.data_vars:
        msk_arr = np.asarray(ds["msk"].values).squeeze()
        if msk_arr.shape == max_depth.shape:
            active_mask = msk_arr > 0
            n_inactive = int(np.sum(~active_mask))
            max_depth = np.where(active_mask, max_depth, np.nan)
            logger.info("Applied sfincs msk: %d inactive cells excluded from flood statistics",
                        n_inactive)

    # Remaining NaN/negative -> 0 (dry)
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
        ds_his = open_sfincs_nc(args.his_nc)
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
