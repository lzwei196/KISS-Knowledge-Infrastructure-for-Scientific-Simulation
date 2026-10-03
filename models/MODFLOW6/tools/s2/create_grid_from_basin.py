#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
==========================================
Tool ID:      create_grid_from_basin
Stage:        s2_grid_discretization
Description:  Generate a structured MODFLOW grid from a basin boundary shapefile.
              Computes NROW, NCOL from basin extent and cell size.
              Creates IDOMAIN mask from shapefile intersection.
              Optionally writes the grid NetCDF that the other KI tools read
              (tools/s2/build_layers_from_global.py, tools/s3/assign_k_from_glhymps.py,
              tools/s4/build_riv_from_cama.py all take it as --grid_nc).
              The grid is built straight from the domain definition — it does
              NOT come from another model's setup files (no VIC basin_grid.nc).

Inputs:
  - --shapefile: basin boundary .shp (default: SHAPEFILE_PATH below)
  - --cell_m: grid cell size in meters (default: CELL_SIZE below), or
    --cell_deg D | --cell_deg D_LON D_LAT: cell size in degrees
  - --nlay: number of model layers (default: NLAY)
  - --layer_bottoms: bottom elevations relative to surface, negative values
    (default: LAYER_BOTTOMS)
  - --dem: DEM raster for TOP elevation (optional; else --default_top)
  - --box LON_MIN LON_MAX LAT_MIN LAT_MAX --nrow N --ncol M (optional):
    fix the grid to this lat/lon box instead of the shapefile extent.
      * with --shapefile: IDOMAIN still comes from the shapefile intersection.
      * without --shapefile: the box rectangle IS the basin boundary polygon
        and goes through the same intersection rule (every cell lies fully
        inside it, so every cell is active). Use this only when the model
        domain really is the rectangle (e.g. the FrenchPiezo box runs).

IDOMAIN rule (same for every mode): a cell is active (1) in every layer when
the boundary polygon(s) cover MORE than --min_overlap (default 0.1 = 10 %) of
the cell area; otherwise 0. Cell areas are compared in degrees after the
boundary is put in EPSG:4326.

Grid placement:
  shapefile extent  origin at the basin's lower-left corner (xorigin, yorigin);
                    ncol = ceil(width / delr), nrow = ceil(height / delc);
                    row 0 = north: lat_i = yorigin + (nrow - i - 0.5) * delc
  --box             dlon = (LON_MAX - LON_MIN) / NCOL, lon_j = LON_MIN + (j + 0.5) * dlon
                    dlat = (LAT_MAX - LAT_MIN) / NROW, lat_i = LAT_MAX - (i + 0.5) * dlat
  --cell_m is turned into degrees at the basin's centre latitude
  (1 deg lat = 111,000 m; 1 deg lon = 111,000 * cos(lat) m).

Outputs:
  - JSON (stdout) with nlay, nrow, ncol, delr, delc, top, botm, idomain info:
    nlay, nrow, ncol, delr, delc, xorigin, yorigin, top_min, top_max,
    active_cells, total_cells (= nlay*nrow*ncol), layer_bottoms_relative,
    plus active_cells_per_layer, botm_min/botm_max, bounds and out_nc.
  - --out_nc (optional) grid NetCDF, NETCDF3_64BIT (a default NETCDF4/HDF5
    write on the disk1 mount produces a file that cannot be re-opened,
    "NetCDF: HDF error"):
      lat(lat)                   float64, cell-centre latitude, row 0 = NORTH
      lon(lon)                   float64, cell-centre longitude, west to east
      mask(lat, lon)             int32, 1 = active, 0 = inactive (= idomain layer 1)
      top(lat, lon)              float64, land surface (m)
      botm(layer, lat, lon)      float64, layer bottoms (m)
      idomain(layer, lat, lon)   int32, MODFLOW IDOMAIN
    global attributes nlay, nrow, ncol, delr, delc, xorigin, yorigin,
    layer_bottoms_relative, min_overlap.

Usage:
  python create_grid_from_basin.py --shapefile data/shp/<basin>.shp \
      --cell_m 5000 --nlay 2 --layer_bottoms -50 -200 \
      --dem data/dem/<dem>.tif --out_nc outputs/<case>/grid.nc
  python create_grid_from_basin.py --box -0.445 0.355 44.534 45.134 \
      --nrow 30 --ncol 40 --out_nc outputs/<case>/grid.nc

Exit codes:
  0 — success
  1 — input validation failed
  2 — processing error (bad shapefile/CRS, DEM cannot be read)
  3 — output validation failed (no active cell, grid too large, file cannot
      be re-read)
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# Configuration (defaults; every one can be set on the command line)
# ---------------------------------------------------------------------------
SHAPEFILE_PATH = "KISSPATH_DATA/shp/qinghai_lake_shp2/qinghai_lake_boundary_shp/qinghai_lake_boundary.shp"       # Basin boundary shapefile
CELL_SIZE = 25000          # Grid cell size in meters
NLAY = 2                  # Number of layers
LAYER_BOTTOMS = [-50, -200]  # Bottom elevations relative to surface (m)
DEM_PATH = ""             # Optional DEM for surface elevation
DEFAULT_TOP = 3194.0       # Default land surface elevation if no DEM
MIN_OVERLAP = 0.1          # Cell is active when the basin covers > 10% of it

M_PER_DEG = 111000.0
MAX_CELLS_PER_SIDE = 10000

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("create_grid_from_basin")


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Generate a structured MODFLOW grid (IDOMAIN from basin "
                    "intersection) and optionally write the grid NetCDF read "
                    "by the s2/s3/s4 tools.")
    p.add_argument("--shapefile", type=str, default=None,
                   help=f"Basin boundary polygon(s). Default: {SHAPEFILE_PATH} "
                        "(unless --box is given alone).")
    p.add_argument("--box", type=float, nargs=4,
                   metavar=("LON_MIN", "LON_MAX", "LAT_MIN", "LAT_MAX"),
                   help="Fix the grid to this lat/lon box (needs --nrow/--ncol). "
                        "Without --shapefile the box is the boundary polygon.")
    p.add_argument("--nrow", type=int, help="--box: number of rows (north to south).")
    p.add_argument("--ncol", type=int, help="--box: number of columns (west to east).")
    cs = p.add_mutually_exclusive_group()
    cs.add_argument("--cell_deg", type=float, nargs="+", metavar="DEG",
                    help="Cell size in degrees, one value (square) or two (D_LON D_LAT).")
    cs.add_argument("--cell_m", type=float,
                    help=f"Cell size in metres (default {CELL_SIZE}), converted to "
                         "degrees at the basin centre latitude.")
    p.add_argument("--nlay", type=int, default=NLAY, help="Number of model layers.")
    p.add_argument("--layer_bottoms", type=float, nargs="+", default=LAYER_BOTTOMS,
                   help="Layer bottoms relative to the surface (m, negative), one per layer.")
    p.add_argument("--dem", type=str, default=DEM_PATH,
                   help="DEM raster for TOP (sampled at cell centres).")
    p.add_argument("--default_top", type=float, default=DEFAULT_TOP,
                   help="Land surface (m) when no DEM is given / DEM is nodata.")
    p.add_argument("--min_overlap", type=float, default=MIN_OVERLAP,
                   help="Active when the basin covers MORE than this fraction of the cell.")
    p.add_argument("--out_nc", type=Path, default=None,
                   help="Write the grid NetCDF here (needed by the s2/s3/s4 tools).")
    args = p.parse_args(argv)
    if args.shapefile is None and args.box is None:
        args.shapefile = SHAPEFILE_PATH
    return args


def validate_inputs(args):
    errors = []
    if args.shapefile is not None and not Path(args.shapefile).exists():
        errors.append(f"Shapefile not found: {args.shapefile}")
    if args.box is not None:
        lon_min, lon_max, lat_min, lat_max = args.box
        if not (lon_max > lon_min and lat_max > lat_min):
            errors.append(f"--box needs LON_MIN < LON_MAX and LAT_MIN < LAT_MAX, got {args.box}")
        if not (-180 <= lon_min and lon_max <= 360 and -90 <= lat_min and lat_max <= 90):
            errors.append(f"--box is not in degrees: {args.box}")
        if not args.nrow or not args.ncol or args.nrow < 1 or args.ncol < 1:
            errors.append("--box needs --nrow and --ncol (>= 1)")
        if args.cell_deg or args.cell_m:
            errors.append("--box takes --nrow/--ncol, not a cell size")
    else:
        if args.nrow or args.ncol:
            errors.append("--nrow/--ncol only go with --box; the shapefile extent takes a cell size")
        if args.cell_deg and (len(args.cell_deg) > 2 or min(args.cell_deg) <= 0):
            errors.append(f"--cell_deg takes one or two positive values, got {args.cell_deg}")
        if args.cell_m is not None and args.cell_m <= 0:
            errors.append(f"Cell size must be positive: {args.cell_m}")
    if args.nlay < 1:
        errors.append(f"NLAY must be >= 1: {args.nlay}")
    if len(args.layer_bottoms) != args.nlay:
        errors.append(f"LAYER_BOTTOMS length ({len(args.layer_bottoms)}) must equal NLAY ({args.nlay})")
    lb = list(args.layer_bottoms)
    if any(b >= 0 for b in lb) or any(lb[k + 1] >= lb[k] for k in range(len(lb) - 1)):
        errors.append(f"LAYER_BOTTOMS must be negative and get deeper layer by layer, got {lb}")
    if args.dem and not Path(args.dem).exists():
        errors.append(f"DEM not found: {args.dem}")
    if not (0.0 <= args.min_overlap < 1.0):
        errors.append(f"--min_overlap must be in [0, 1), got {args.min_overlap}")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def read_basin_geometry(shapefile):
    """Union of the basin polygons, in EPSG:4326."""
    import geopandas as gpd

    basin = gpd.read_file(shapefile)
    logger.info("Basin CRS: %s", basin.crs)
    if basin.crs is None:
        raise ValueError(f"{shapefile} has no CRS (.prj); cannot place it on a lat/lon grid")
    if basin.crs.to_epsg() != 4326:
        logger.info("Reprojecting basin from %s to EPSG:4326", basin.crs)
        basin = basin.to_crs("EPSG:4326")
    geom = basin.geometry.union_all() if hasattr(basin.geometry, "union_all") \
        else basin.geometry.unary_union
    if geom.is_empty:
        raise ValueError(f"{shapefile} has no geometry")
    return geom


def grid_axes(args, geom):
    """Cell-centre axes (row 0 = north), cell size and lower-left origin."""
    if args.box is not None:
        lon_min, lon_max, lat_min, lat_max = args.box
        dlon = (lon_max - lon_min) / args.ncol
        dlat = (lat_max - lat_min) / args.nrow
        lons = lon_min + (np.arange(args.ncol) + 0.5) * dlon
        lats = lat_max - (np.arange(args.nrow) + 0.5) * dlat
        return lats, lons, dlat, dlon, lon_min, lat_min

    minx, miny, maxx, maxy = (float(v) for v in geom.bounds)
    logger.info("Basin bounds: (%.4f, %.4f) to (%.4f, %.4f)", minx, miny, maxx, maxy)
    if args.cell_deg:
        dlon = float(args.cell_deg[0])
        dlat = float(args.cell_deg[-1])
    else:
        cell_m = CELL_SIZE if args.cell_m is None else args.cell_m
        center_lat = (miny + maxy) / 2
        dlat = cell_m / M_PER_DEG
        dlon = cell_m / (M_PER_DEG * np.cos(np.radians(center_lat)))
    ncol = int(np.ceil((maxx - minx) / dlon))
    nrow = int(np.ceil((maxy - miny) / dlat))
    if nrow > MAX_CELLS_PER_SIDE or ncol > MAX_CELLS_PER_SIDE:
        logger.error("Grid too large: %dx%d. Increase cell size.", nrow, ncol)
        sys.exit(3)
    lons = minx + (np.arange(ncol) + 0.5) * dlon
    lats = miny + (nrow - np.arange(nrow) - 0.5) * dlat
    return lats, lons, dlat, dlon, minx, miny


def idomain_mask(geom, lats, lons, dlat, dlon, min_overlap):
    """1 where the boundary covers more than min_overlap of the cell area."""
    import shapely

    lon2d, lat2d = np.meshgrid(lons, lats)
    cells = shapely.box(lon2d - dlon / 2, lat2d - dlat / 2,
                        lon2d + dlon / 2, lat2d + dlat / 2)
    shapely.prepare(geom)
    hit = shapely.intersects(geom, cells)
    frac = np.zeros(cells.shape)
    if hit.any():
        frac[hit] = shapely.area(shapely.intersection(geom, cells[hit])) / shapely.area(cells[hit])
    return (hit & (frac > min_overlap)).astype(np.int32), frac


def surface_top(dem, lats, lons, default_top):
    """TOP (m) at cell centres from the DEM; nodata cells get default_top."""
    nrow, ncol = len(lats), len(lons)
    top = np.full((nrow, ncol), float(default_top))
    if not dem:
        logger.info("Using uniform TOP = %.1f m", default_top)
        return top, 0
    import rasterio

    lon2d, lat2d = np.meshgrid(lons, lats)
    xs, ys = lon2d.ravel(), lat2d.ravel()
    with rasterio.open(dem) as src:
        if src.crs is not None and not src.crs.is_geographic:
            from pyproj import Transformer
            xs, ys = Transformer.from_crs("EPSG:4326", src.crs, always_xy=True).transform(xs, ys)
        band = src.read(1, masked=True)
        rows, cols = rasterio.transform.rowcol(src.transform, xs, ys)
        rows, cols = np.asarray(rows), np.asarray(cols)
        inside = (rows >= 0) & (rows < src.height) & (cols >= 0) & (cols < src.width)
        vals = np.full(rows.shape, np.nan)
        got = band[rows[inside], cols[inside]]
        vals[inside] = np.ma.filled(got.astype(float), np.nan)
    vals = vals.reshape(nrow, ncol)
    ok = np.isfinite(vals)
    top[ok] = vals[ok]
    n_default = int((~ok).sum())
    if not ok.any():
        raise ValueError(f"DEM {dem} has no data over the grid")
    logger.info("TOP from DEM: %.1f to %.1f m (%d cells off-DEM/nodata -> %.1f m)",
                top[ok].min(), top[ok].max(), n_default, default_top)
    return top, n_default


def write_grid_nc(out_nc, lats, lons, top, botm, idomain, attrs):
    import xarray as xr
    out_nc = Path(out_nc)
    out_nc.parent.mkdir(parents=True, exist_ok=True)
    ds = xr.Dataset(
        {"mask": (("lat", "lon"), np.asarray(idomain[0], dtype=np.int32)),
         "top": (("lat", "lon"), np.asarray(top, dtype=np.float64)),
         "botm": (("layer", "lat", "lon"), np.asarray(botm, dtype=np.float64)),
         "idomain": (("layer", "lat", "lon"), np.asarray(idomain, dtype=np.int32))},
        coords={"lat": np.asarray(lats, dtype=np.float64),
                "lon": np.asarray(lons, dtype=np.float64)},
        attrs=attrs)
    ds.to_netcdf(out_nc, format="NETCDF3_64BIT")


def validate_outputs(result, out_nc):
    """Check the grid is reasonable; re-open the written file (a NETCDF4 write
    on this disk fails exactly here)."""
    errors = []
    if result["active_cells"] == 0:
        errors.append("No active cells — shapefile may not overlap grid "
                      "(make the cell size smaller than the basin)")
    if out_nc is not None:
        import xarray as xr
        try:
            with xr.open_dataset(out_nc) as ds:
                shape = ds["idomain"].shape
                n_active = int((ds["idomain"].values > 0).sum())
                nrow = ds.sizes["lat"]
                lat_desc = bool(np.all(np.diff(ds["lat"].values) < 0)) if nrow > 1 else True
        except Exception as e:
            logger.error("Written grid cannot be re-opened: %s", e)
            print(json.dumps(result, indent=2))
            sys.exit(3)
        want = (result["nlay"], result["nrow"], result["ncol"])
        if shape != want:
            errors.append(f"idomain shape {shape} != {want}")
        if n_active != result["active_cells"]:
            errors.append(f"idomain in file has {n_active} active cells, expected {result['active_cells']}")
        if not lat_desc:
            errors.append("lat is not north-to-south")
    if errors:
        for e in errors:
            logger.error(e)
        print(json.dumps(result, indent=2))
        sys.exit(3)
    logger.info("Output validation passed.")


def process(args):
    import shapely

    if args.shapefile is not None:
        geom = read_basin_geometry(args.shapefile)
        boundary = str(args.shapefile)
    else:
        lon_min, lon_max, lat_min, lat_max = args.box
        geom = shapely.box(lon_min, lat_min, lon_max, lat_max)
        boundary = f"box lon {lon_min}..{lon_max} lat {lat_min}..{lat_max}"

    lats, lons, dlat, dlon, xorigin, yorigin = grid_axes(args, geom)
    nlay, nrow, ncol = args.nlay, len(lats), len(lons)
    logger.info("Grid: %d layers x %d rows x %d cols = %d cells", nlay, nrow, ncol, nlay * nrow * ncol)

    mask2d, frac = idomain_mask(geom, lats, lons, dlat, dlon, args.min_overlap)
    idomain = np.broadcast_to(mask2d, (nlay, nrow, ncol)).astype(np.int32)

    top, n_top_default = surface_top(args.dem, lats, lons, args.default_top)
    botm = np.stack([top + float(b) for b in args.layer_bottoms])  # LAYER_BOTTOMS are negative

    active_cells = int((idomain > 0).sum())
    logger.info("Active cells: %d / %d", active_cells, nlay * nrow * ncol)

    result = {
        "nlay": nlay,
        "nrow": nrow,
        "ncol": ncol,
        "delr": float(dlon),
        "delc": float(dlat),
        "xorigin": float(xorigin),
        "yorigin": float(yorigin),
        "top_min": float(top.min()),
        "top_max": float(top.max()),
        "active_cells": active_cells,
        "total_cells": int(nlay * nrow * ncol),
        "layer_bottoms_relative": [float(b) for b in args.layer_bottoms],
        "botm_min": [float(b.min()) for b in botm],
        "botm_max": [float(b.max()) for b in botm],
        "active_cells_per_layer": int(mask2d.sum()),
        "idomain_rule": f"basin covers > {args.min_overlap:g} of the cell area",
        "cells_partly_covered_but_inactive": int(((frac > 0) & (mask2d == 0)).sum()),
        "boundary": boundary,
        "top_source": args.dem if args.dem else f"uniform {args.default_top}",
        "top_cells_default": n_top_default,
        "delr_m_approx": float(dlon * M_PER_DEG * np.cos(np.radians(float(np.mean(lats))))),
        "delc_m_approx": float(dlat * M_PER_DEG),
        "bounds_lon_lat": [float(xorigin), float(xorigin + ncol * dlon),
                           float(yorigin), float(yorigin + nrow * dlat)],
        "out_nc": str(args.out_nc) if args.out_nc else None,
    }

    if args.out_nc is not None:
        attrs = {"nlay": nlay, "nrow": nrow, "ncol": ncol,
                 "delr": float(dlon), "delc": float(dlat),
                 "xorigin": float(xorigin), "yorigin": float(yorigin),
                 "layer_bottoms_relative": np.asarray(args.layer_bottoms, dtype=np.float64),
                 "min_overlap": float(args.min_overlap),
                 "boundary": boundary,
                 "note": "row 0 = north; mask = idomain layer 1"}
        write_grid_nc(args.out_nc, lats, lons, top, botm, idomain, attrs)
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(argv=None):
    args = parse_args(argv)
    validate_inputs(args)

    try:
        result = process(args)
    except Exception as e:
        logger.error("Processing failed: %s", e)
        import traceback
        traceback.print_exc()
        sys.exit(2)

    validate_outputs(result, args.out_nc)

    print(json.dumps(result, indent=2))
    logger.info("Grid creation complete.")
    return 0


if __name__ == "__main__":
    logger.info("Running tool: %s", os.path.basename(__file__))
    rc = main()
    # Same exit pattern as the other s2/s3 raster tools: the geopandas/GDAL +
    # xarray teardown can segfault after the work is done.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(rc)
