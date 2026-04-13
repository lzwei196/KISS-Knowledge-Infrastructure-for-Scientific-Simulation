"""
Build MODFLOW layer geometry from DEM + global datasets.

Creates TOP and BOTM arrays for a 2-3 layer regional groundwater model
using DEM (surface elevation), water table depth estimates, and either
depth-to-bedrock data or uniform thickness assumptions.

Layer structure:
  Layer 1: Shallow unconfined (soil zone, 0-10m, ICELLTYPE=1)
  Layer 2: Intermediate (weathered rock/alluvium, 10-50m, ICELLTYPE=1)
  Layer 3: Deep confined (bedrock, 50-100m+, ICELLTYPE=0)

Data sources (priority order):
  - China DTB 100m (Yan/Shangguan 2020) — best for China
  - Pelletier regolith thickness — global
  - Uniform depth assumption — fallback

Usage:
    python build_layers_from_global.py \
        --grid_nc outputs/<basin>/vic_temp/grid/basin_grid.nc \
        --dem data/dem/china_dem_90m/china_dem_90m.tif \
        --output_dir outputs/<basin>/modflow/layers \
        --nlayers 3 \
        --basin_name bengbu
"""

import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("build_layers")

# Default layer thicknesses when no DTB data available
DEFAULT_LAYER_DEPTHS = {
    2: [10.0, 100.0],           # 2-layer: 10m shallow + 90m deep
    3: [10.0, 50.0, 100.0],     # 3-layer: 10m + 40m + 50m
}


def resample_raster_to_grid(raster_path: str, lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
    """Extract raster values at grid cell centers using rasterio."""
    import rasterio
    from rasterio.transform import rowcol

    with rasterio.open(raster_path) as src:
        data = src.read(1)
        nodata = src.nodata

        result = np.full((len(lats), len(lons)), np.nan)
        for i, lat in enumerate(lats):
            for j, lon in enumerate(lons):
                try:
                    row, col = rowcol(src.transform, lon, lat)
                    if 0 <= row < data.shape[0] and 0 <= col < data.shape[1]:
                        val = data[row, col]
                        if nodata is not None and val == nodata:
                            continue
                        result[i, j] = float(val)
                except Exception:
                    continue

    return result


def main():
    parser = argparse.ArgumentParser(description="Build MODFLOW layers from DEM + global datasets")
    parser.add_argument("--grid_nc", type=Path, required=True, help="Basin grid NetCDF")
    parser.add_argument("--dem", type=str, required=True, help="DEM raster (GeoTIFF)")
    parser.add_argument("--dtb_raster", type=str, default=None,
                        help="Depth-to-bedrock raster (m). If not provided, uses uniform depths.")
    parser.add_argument("--wtd_raster", type=str, default=None,
                        help="Water table depth raster (m) for initial heads")
    parser.add_argument("--nlayers", type=int, default=3, choices=[2, 3])
    parser.add_argument("--output_dir", type=Path, required=True)
    parser.add_argument("--basin_name", type=str, default="basin")
    args = parser.parse_args()

    import xarray as xr

    # Read grid
    ds = xr.open_dataset(args.grid_nc)
    lat_key = 'y' if 'y' in ds else 'lat'
    lon_key = 'x' if 'x' in ds else 'lon'
    lats = ds[lat_key].values
    lons = ds[lon_key].values
    mask = ds['mask'].values if 'mask' in ds else np.ones((len(lats), len(lons)))
    ds.close()

    nrow, ncol = len(lats), len(lons)
    logger.info("Grid: %d rows × %d cols, %d layers", nrow, ncol, args.nlayers)

    # Get DEM elevation
    logger.info("Reading DEM: %s", args.dem)
    top = resample_raster_to_grid(args.dem, lats, lons)
    nan_count = np.isnan(top).sum()
    if nan_count > 0:
        logger.warning("DEM has %d NaN cells (%.1f%%), filling with median",
                       nan_count, nan_count / top.size * 100)
        top[np.isnan(top)] = np.nanmedian(top)

    logger.info("DEM range: %.0f - %.0f m", np.nanmin(top), np.nanmax(top))

    # Get depth-to-bedrock (or use defaults)
    if args.dtb_raster:
        logger.info("Reading depth-to-bedrock: %s", args.dtb_raster)
        total_depth = resample_raster_to_grid(args.dtb_raster, lats, lons)
        total_depth[np.isnan(total_depth)] = DEFAULT_LAYER_DEPTHS[args.nlayers][-1]
        total_depth = np.clip(total_depth, 10.0, 500.0)  # reasonable range
        logger.info("DTB range: %.0f - %.0f m", np.nanmin(total_depth), np.nanmax(total_depth))
    else:
        logger.info("No DTB raster — using uniform depth of %.0f m",
                     DEFAULT_LAYER_DEPTHS[args.nlayers][-1])
        total_depth = np.full((nrow, ncol), DEFAULT_LAYER_DEPTHS[args.nlayers][-1])

    # Build layer bottoms
    botm = np.zeros((args.nlayers, nrow, ncol))
    if args.nlayers == 2:
        botm[0] = top - 10.0                    # Layer 1 bottom: 10m below surface
        botm[1] = top - total_depth              # Layer 2 bottom: bedrock
    elif args.nlayers == 3:
        botm[0] = top - 10.0                    # Layer 1: shallow (0-10m)
        frac_mid = 0.4                           # 40% of remaining depth for layer 2
        remaining = total_depth - 10.0
        remaining = np.maximum(remaining, 20.0)  # at least 20m for layers 2+3
        botm[1] = top - 10.0 - remaining * frac_mid  # Layer 2: intermediate
        botm[2] = top - total_depth              # Layer 3: deep

    # Ensure monotonically decreasing
    for k in range(1, args.nlayers):
        botm[k] = np.minimum(botm[k], botm[k-1] - 1.0)  # at least 1m thick

    # Build IDOMAIN from mask
    idomain = np.zeros((args.nlayers, nrow, ncol), dtype=int)
    for k in range(args.nlayers):
        idomain[k] = (mask > 0).astype(int)

    # Build initial heads from WTD (if available)
    if args.wtd_raster:
        logger.info("Reading water table depth: %s", args.wtd_raster)
        wtd = resample_raster_to_grid(args.wtd_raster, lats, lons)
        wtd[np.isnan(wtd)] = 5.0  # default 5m below surface
        wtd = np.clip(wtd, 0.0, total_depth - 1.0)
        strt = top - wtd
    else:
        # Default: water table at 5m below surface
        strt = top - 5.0

    # Ensure starting heads are within layer bounds
    strt = np.maximum(strt, botm[-1] + 0.5)
    strt = np.minimum(strt, top - 0.5)

    # Expand to 3D (nlay × nrow × ncol) — FloPy requires per-layer starting heads
    strt = np.broadcast_to(strt, (args.nlayers, nrow, ncol)).copy()

    # Save outputs
    args.output_dir.mkdir(parents=True, exist_ok=True)

    np.save(args.output_dir / "top.npy", top)
    np.save(args.output_dir / "botm.npy", botm)
    np.save(args.output_dir / "idomain.npy", idomain)
    np.save(args.output_dir / "strt.npy", strt)
    np.save(args.output_dir / "lats.npy", lats)
    np.save(args.output_dir / "lons.npy", lons)

    # Layer thickness stats
    for k in range(args.nlayers):
        upper = top if k == 0 else botm[k-1]
        thickness = upper - botm[k]
        logger.info("Layer %d: thickness %.0f-%.0f m (mean %.0f m)",
                     k+1, thickness.min(), thickness.max(), thickness.mean())

    # Summary JSON
    summary = {
        "basin": args.basin_name,
        "nrow": nrow, "ncol": ncol, "nlay": args.nlayers,
        "active_cells": int((idomain[0] > 0).sum()),
        "dem_range_m": [float(np.nanmin(top)), float(np.nanmax(top))],
        "total_depth_range_m": [float(total_depth.min()), float(total_depth.max())],
        "strt_range_m": [float(strt.min()), float(strt.max())],
        "dtb_source": str(args.dtb_raster) if args.dtb_raster else "uniform_default",
        "wtd_source": str(args.wtd_raster) if args.wtd_raster else "uniform_5m",
        "output_files": ["top.npy", "botm.npy", "idomain.npy", "strt.npy", "lats.npy", "lons.npy"],
    }
    with open(args.output_dir / "layer_summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    logger.info("Saved to %s", args.output_dir)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
