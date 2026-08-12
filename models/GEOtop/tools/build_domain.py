#!/usr/bin/env python3
"""build_domain.py  --  GEOtop stage s1 (Domain / Grid Setup).

THE MISSING s1 TOOL.  Until 2026-06-21 the GEOtop KI shipped no tool to build
the distributed input maps (dem/slope/aspect/network/landcover/soiltype) that
GEOtop needs to produce *real* channel discharge.  The only documented chain
(convert_forcing + convert_soil + run_geotop + parse_output) supports 1D
PointSim runs only, and PointSim writes a discharge.txt whose Qtot is
identically 0 (no lateral routing / no channel).  As a result the prior
"validated" Bengbu discharge (NSE 0.39) was produced by an out-of-band Python
FAO-56 + Nash-cascade SURROGATE, not by the GEOtop binary -- a KDT-philosophy
violation (no silent Python fallbacks).

This tool closes that gap.  Given a DEM source and a pour point it:
  1. clips a window from a (global) DEM around the pour point,
  2. reprojects/resamples to a metric CRS at a chosen cell size,
  3. delineates the watershed with ki_tools_common.terrain_ops.delineate_basin
     (whitebox: fill -> d8 -> accumulation -> snap -> watershed -> streams),
  4. emits GEOtop ESRI-ASCII input maps on the basin grid:
        dem.asc, slope.asc, aspect.asc, network.asc, landcover.asc, soiltype.asc
     (cells outside the basin set to NoValue = -9999).

The resulting input_maps/ directory drops straight into a distributed
(PointSim=0) geotop.inpts and yields a non-zero Qtot at the outlet.

Usage:
    python build_domain.py \
        --dem /mnt/datasets/MERIT_DEM/n50w115_dem.tif \
        --lat 53.0368 --lon -113.3231 \
        --epsg 32612 --cellsize 1000 \
        --bbox -114.2,52.5,-112.6,53.5 \
        --stream-threshold 30 \
        --landcover 1 --soiltype 1 \
        --out /tmp/geotop_pipestone/input_maps
"""
import argparse, json, os, sys, tempfile

import numpy as np
import rasterio
from rasterio.warp import calculate_default_transform, reproject, Resampling
from rasterio.windows import from_bounds

NOVALUE = -9999.0


def clip_and_reproject(dem_path, bbox, dst_epsg, cellsize, tmpdir):
    """Clip DEM to geographic bbox, reproject to dst CRS at cellsize (m)."""
    with rasterio.open(dem_path) as src:
        minx, miny, maxx, maxy = bbox
        win = from_bounds(minx, miny, maxx, maxy, src.transform)
        data = src.read(1, window=win)
        win_transform = src.window_transform(win)
        src_crs = src.crs
        src_nodata = src.nodata if src.nodata is not None else -9999.0

    data = np.where(np.isfinite(data), data, src_nodata).astype("float32")
    dst_crs = rasterio.crs.CRS.from_epsg(dst_epsg)

    # Compute destination transform/size at the requested resolution.
    dst_transform, dst_w, dst_h = calculate_default_transform(
        src_crs, dst_crs, data.shape[1], data.shape[0],
        left=minx, bottom=miny, right=maxx, top=maxy,
        resolution=cellsize,
    )
    dst = np.full((dst_h, dst_w), src_nodata, dtype="float32")
    reproject(
        source=data, destination=dst,
        src_transform=win_transform, src_crs=src_crs,
        dst_transform=dst_transform, dst_crs=dst_crs,
        src_nodata=src_nodata, dst_nodata=src_nodata,
        resampling=Resampling.bilinear,
    )
    out_tif = os.path.join(tmpdir, "dem_proj.tif")
    with rasterio.open(
        out_tif, "w", driver="GTiff", height=dst_h, width=dst_w, count=1,
        dtype="float32", crs=dst_crs, transform=dst_transform, nodata=src_nodata,
    ) as d:
        d.write(dst, 1)
    return out_tif, src_nodata


def slope_aspect(dem, cellsize, mask):
    """Horn (1981) slope (deg) and aspect (deg from N, clockwise)."""
    z = dem.astype(float)
    dzdx = np.zeros_like(z)
    dzdy = np.zeros_like(z)
    # Horn (1981) 3x3 finite-difference kernels
    dzdx[1:-1, 1:-1] = (
        (z[:-2, 2:] + 2 * z[1:-1, 2:] + z[2:, 2:]) -
        (z[:-2, :-2] + 2 * z[1:-1, :-2] + z[2:, :-2])
    ) / (8 * cellsize)
    dzdy[1:-1, 1:-1] = (
        (z[2:, :-2] + 2 * z[2:, 1:-1] + z[2:, 2:]) -
        (z[:-2, :-2] + 2 * z[:-2, 1:-1] + z[:-2, 2:])
    ) / (8 * cellsize)
    slope = np.degrees(np.arctan(np.sqrt(dzdx ** 2 + dzdy ** 2)))
    aspect = np.degrees(np.arctan2(dzdy, -dzdx))
    aspect = np.where(aspect < 0, 90.0 - aspect, np.where(aspect > 90.0, 360.0 - aspect + 90.0, 90.0 - aspect))
    aspect = aspect % 360.0
    slope = np.where(mask, slope, NOVALUE)
    aspect = np.where(mask, aspect, NOVALUE)
    return slope.astype("float32"), aspect.astype("float32")


def write_asc(path, arr, transform, ncols, nrows, cellsize):
    """Write an ESRI ASCII grid GEOtop can read."""
    xll = transform.c
    yll = transform.f + transform.e * nrows  # transform.e is negative
    with open(path, "w") as f:
        f.write(f"ncols         {ncols}\n")
        f.write(f"nrows         {nrows}\n")
        f.write(f"xllcorner     {xll:.6f}\n")
        f.write(f"yllcorner     {yll:.6f}\n")
        f.write(f"cellsize      {cellsize:.6f}\n")
        f.write(f"NODATA_value  {int(NOVALUE)}\n")
        for row in arr:
            f.write(" ".join(
                (f"{int(NOVALUE)}" if v == NOVALUE else f"{v:.4f}") for v in row
            ) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dem", required=True, help="Source DEM .tif (e.g. a MERIT tile)")
    ap.add_argument("--lat", type=float, required=True)
    ap.add_argument("--lon", type=float, required=True)
    ap.add_argument("--bbox", required=True, help="minx,miny,maxx,maxy (deg) clip window")
    ap.add_argument("--epsg", type=int, required=True, help="metric CRS EPSG (e.g. 32612 UTM12N)")
    ap.add_argument("--cellsize", type=float, default=1000.0, help="grid cell size (m)")
    ap.add_argument("--stream-threshold", type=int, default=30,
                    help="flow-accum cells to qualify as a channel (scale to cellsize)")
    ap.add_argument("--snap-distance-m", type=float, default=3000.0)
    ap.add_argument("--landcover", type=int, default=1, help="uniform land-cover class id")
    ap.add_argument("--soiltype", type=int, default=1, help="uniform soil-type id")
    ap.add_argument("--out", required=True, help="output input_maps directory")
    args = ap.parse_args()

    bbox = tuple(float(v) for v in args.bbox.split(","))
    os.makedirs(args.out, exist_ok=True)
    tmpdir = tempfile.mkdtemp(prefix="geotop_dom_")

    # 1-2. clip + reproject
    dem_tif, src_nodata = clip_and_reproject(args.dem, bbox, args.epsg, args.cellsize, tmpdir)

    # 3. delineate
    from ki_tools_common.terrain_ops.delineate import delineate_basin
    res = delineate_basin(
        dem_path=dem_tif, pour_point=(args.lon, args.lat), output_dir=tmpdir,
        stream_threshold=args.stream_threshold, snap_distance_m=args.snap_distance_m,
        pour_point_crs="EPSG:4326", verbose=False,
    )

    with rasterio.open(dem_tif) as d:
        dem = d.read(1)
        transform = d.transform
        nrows, ncols = dem.shape
    with rasterio.open(res["basin_raster"]) as b:
        basin = b.read(1)
    with rasterio.open(res["streams_raster"]) as s:
        streams = s.read(1)

    mask = (basin == 1) & np.isfinite(dem) & (dem != src_nodata)
    if mask.sum() == 0:
        print(json.dumps({"status": "error", "error": "empty basin after delineation"}))
        sys.exit(1)

    dem_out = np.where(mask, dem, NOVALUE).astype("float32")
    slope, aspect = slope_aspect(np.where(mask, dem, 0.0), args.cellsize, mask)
    # GEOtop river network: channel cells get a positive id (1), others 0 inside basin,
    # NoValue outside.  streams raster is 1 on channel, NoData elsewhere.
    net = np.where(mask, np.where(streams == 1, 1.0, 0.0), NOVALUE).astype("float32")
    landcover = np.where(mask, float(args.landcover), NOVALUE).astype("float32")
    soiltype = np.where(mask, float(args.soiltype), NOVALUE).astype("float32")

    cs = abs(transform.a)
    write_asc(os.path.join(args.out, "dem.asc"), dem_out, transform, ncols, nrows, cs)
    write_asc(os.path.join(args.out, "slope.asc"), slope, transform, ncols, nrows, cs)
    write_asc(os.path.join(args.out, "aspect.asc"), aspect, transform, ncols, nrows, cs)
    write_asc(os.path.join(args.out, "network.asc"), net, transform, ncols, nrows, cs)
    write_asc(os.path.join(args.out, "landcover.asc"), landcover, transform, ncols, nrows, cs)
    write_asc(os.path.join(args.out, "soiltype.asc"), soiltype, transform, ncols, nrows, cs)

    report = {
        "status": "ok",
        "out_dir": args.out,
        "grid": {"ncols": ncols, "nrows": nrows, "cellsize_m": cs},
        "n_basin_cells": int(mask.sum()),
        "n_channel_cells": int(((net == 1.0)).sum()),
        "basin_area_km2_delineated": round(float(res["basin_area_km2"]), 2),
        "basin_area_km2_from_cells": round(float(mask.sum()) * cs * cs / 1e6, 2),
        "dem_min_m": round(float(dem_out[mask].min()), 1),
        "dem_max_m": round(float(dem_out[mask].max()), 1),
        "snapped_pour": res["snapped_pour"],
        "maps": ["dem", "slope", "aspect", "network", "landcover", "soiltype"],
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
