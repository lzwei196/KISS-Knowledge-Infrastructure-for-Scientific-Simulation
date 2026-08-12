#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
Tool ID:      delineate_basin_merit
Stage:        s1_domain
Description:  Delineate the TRUE catchment of a gauge from MERIT-Hydro D8 flow
              direction, snapping the outlet to the gauge's DOCUMENTED drainage
              area using MERIT's upstream-area raster (`upa`, km2).

WHY THIS TOOL EXISTS (dt_s09)
-----------------------------
A truncated domain is unfixable downstream: if the grid holds half the
contributing area, simulated discharge is ~half of observed and no parameter set
recovers it (good timing, r > 0.8, but a stubborn PBIAS ~ -50%).

Bare-earth D8 on a coarse DEM *reproduces* a truncated shapefile's error on flat,
leveed plains rather than exposing it -- two wrong methods agreeing is not
corroboration. MERIT-Hydro's flow direction is hydrologically corrected against
observed river networks and ships `upa`, so the outlet can be snapped to the
*documented* area instead of guessed.

MERIT-Hydro D8 encoding is exactly mHM's ArcGIS convention
(1=E, 2=SE, 4=S, 8=SW, 16=W, 32=NW, 64=N, 128=NE; 0 = river mouth,
-1 = inland depression, -9999 = nodata), so the `*_dir.tif` clip written here
feeds `prepare_morpho_data.py --fdir_source merit` directly.

Inputs:
  --outlet_lon/--outlet_lat  approximate gauge location (degrees)
  --target_area_km2          gauge's DOCUMENTED drainage area
  --bbox minx miny maxx maxy search/clip window (degrees)
  --snap_deg                 outlet search radius (degrees)
  --out_shp                  output basin shapefile

Outputs:
  <out_shp>                  basin polygon (EPSG:4326)
  <stem>_dir.tif             MERIT D8 clipped to bbox   (consumed by s2)
  <stem>_upa.tif             MERIT upstream area clipped to bbox
  <out_shp>.mask.tif         basin mask (1 = in basin)

Refuses to emit a basin more than --max_area_error_pct from the target.

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import os
import sys
import json
import math
import logging
from pathlib import Path

import numpy as np

try:
    import rasterio
    from rasterio.transform import from_origin, rowcol, xy
    from rasterio.features import shapes as rio_shapes
    import geopandas as gpd
    from shapely.geometry import shape as shapely_shape
except ImportError as e:  # pragma: no cover
    print(f"ERROR: Required packages: rasterio, geopandas, shapely. {e}")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

MERIT_ROOT = os.path.join(
    os.environ.get("HYDROCRAFT_ROOT", "/mnt/disk1/Hydrocraft_server"), "data/merit_hydro"
)
MERIT_RES = 1.0 / 1200.0  # 3 arc-seconds
EARTH_R = 6371007.181     # m, authalic radius

# ArcGIS / MERIT D8 code -> (row_offset, col_offset)
D8_OFFSET = {
    1: (0, 1), 2: (1, 1), 4: (1, 0), 8: (1, -1),
    16: (0, -1), 32: (-1, -1), 64: (-1, 0), 128: (-1, 1),
}


def parse_args():
    import argparse
    p = argparse.ArgumentParser(description="Delineate basin from MERIT-Hydro")
    p.add_argument("--outlet_lon", type=float, required=True)
    p.add_argument("--outlet_lat", type=float, required=True)
    p.add_argument("--target_area_km2", type=float, required=True)
    p.add_argument("--bbox", type=float, nargs=4, required=True,
                   metavar=("MINX", "MINY", "MAXX", "MAXY"))
    p.add_argument("--snap_deg", type=float, default=0.05)
    p.add_argument("--out_shp", required=True)
    p.add_argument("--merit_root", default=MERIT_ROOT)
    p.add_argument("--max_area_error_pct", type=float, default=10.0)
    return p.parse_args()


def _tiles_for_bbox(bbox):
    """MERIT tiles are 5x5 degrees, named e.g. n30e115."""
    minx, miny, maxx, maxy = bbox
    tiles = []
    for lat0 in range(int(math.floor(miny / 5.0) * 5), int(math.ceil(maxy / 5.0) * 5), 5):
        for lon0 in range(int(math.floor(minx / 5.0) * 5), int(math.ceil(maxx / 5.0) * 5), 5):
            ns = "n" if lat0 >= 0 else "s"
            ew = "e" if lon0 >= 0 else "w"
            tiles.append(f"{ns}{abs(lat0):02d}{ew}{abs(lon0):03d}")
    return tiles


def mosaic_clip(merit_root, bbox, kind, dtype, nodata):
    """Mosaic the MERIT tiles covering bbox and clip to it exactly."""
    minx, miny, maxx, maxy = bbox
    # snap bbox to the global MERIT grid so cell edges line up
    c0 = int(round(minx / MERIT_RES))
    r0 = int(round((90.0 - maxy) / MERIT_RES))
    ncols = int(round((maxx - minx) / MERIT_RES))
    nrows = int(round((maxy - miny) / MERIT_RES))
    xll = c0 * MERIT_RES
    yur = 90.0 - r0 * MERIT_RES
    transform = from_origin(xll, yur, MERIT_RES, MERIT_RES)

    out = np.full((nrows, ncols), nodata, dtype=dtype)
    found = 0
    for t in _tiles_for_bbox(bbox):
        fp = Path(merit_root) / f"{t}_{kind}.tif"
        if not fp.exists():
            logger.warning(f"MERIT tile missing: {fp}")
            continue
        found += 1
        with rasterio.open(fp) as src:
            a = src.read(1)
            # destination window of this tile inside the output grid
            tc0 = int(round((src.transform.c - xll) / MERIT_RES))
            tr0 = int(round((yur - src.transform.f) / MERIT_RES))
            dr0, dr1 = max(0, tr0), min(nrows, tr0 + a.shape[0])
            dc0, dc1 = max(0, tc0), min(ncols, tc0 + a.shape[1])
            if dr0 >= dr1 or dc0 >= dc1:
                continue
            out[dr0:dr1, dc0:dc1] = a[dr0 - tr0:dr1 - tr0, dc0 - tc0:dc1 - tc0]
    if found == 0:
        logger.error(f"No MERIT '{kind}' tiles found under {merit_root} for bbox {bbox}")
        sys.exit(1)
    return out, transform


def cell_area_km2(nrows, transform):
    """Per-row cell area (km2) on the sphere: R^2 * dlon * (sin p2 - sin p1)."""
    yur = transform.f
    rows = np.arange(nrows)
    lat_top = np.radians(yur - rows * MERIT_RES)
    lat_bot = np.radians(yur - (rows + 1) * MERIT_RES)
    dlon = math.radians(MERIT_RES)
    return (EARTH_R ** 2 * dlon * (np.sin(lat_top) - np.sin(lat_bot))) / 1e6


def downstream_index(fdir, nrows, ncols):
    """Flat index of each cell's D8 downstream neighbour; self-loop at sinks."""
    flat = np.arange(nrows * ncols, dtype=np.int32).reshape(nrows, ncols)
    ds = flat.copy()
    for code, (dr, dc) in D8_OFFSET.items():
        m = fdir == code
        if not m.any():
            continue
        r, c = np.nonzero(m)
        nr, nc = r + dr, c + dc
        ok = (nr >= 0) & (nr < nrows) & (nc >= 0) & (nc < ncols)
        # off-grid -> absorbing self-loop (never reaches the outlet)
        ds[r[ok], c[ok]] = flat[nr[ok], nc[ok]]
    return ds.ravel()


def trace_upstream(fdir, outlet_rc, nrows, ncols):
    """Basin mask via pointer jumping: every cell resolves to its terminal sink."""
    ds = downstream_index(fdir, nrows, ncols)
    outlet_flat = np.int32(outlet_rc[0] * ncols + outlet_rc[1])
    ds[outlet_flat] = outlet_flat  # make the outlet absorbing

    term = ds.copy()
    for _ in range(40):                      # 2^40 >> any real flow path
        nxt = term[term]
        if np.array_equal(nxt, term):
            break
        term = nxt
    return (term == outlet_flat).reshape(nrows, ncols)


def main():
    args = parse_args()
    out_shp = Path(args.out_shp)
    out_shp.parent.mkdir(parents=True, exist_ok=True)
    stem = out_shp.with_suffix("")

    logger.info(f"Mosaicking MERIT dir/upa over bbox {args.bbox}")
    fdir, transform = mosaic_clip(args.merit_root, args.bbox, "dir", np.int16, -9999)
    upa, _ = mosaic_clip(args.merit_root, args.bbox, "upa", np.float32, -9999.0)
    nrows, ncols = fdir.shape
    logger.info(f"MERIT grid: {ncols} x {nrows} @ {MERIT_RES:.6f} deg")

    # ---- snap the outlet to the documented drainage area -------------------
    r_c, c_c = rowcol(transform, args.outlet_lon, args.outlet_lat)
    rad = int(round(args.snap_deg / MERIT_RES))
    r0, r1 = max(0, r_c - rad), min(nrows, r_c + rad + 1)
    c0, c1 = max(0, c_c - rad), min(ncols, c_c + rad + 1)
    win = upa[r0:r1, c0:c1]
    valid = win > 0
    if not valid.any():
        logger.error("No valid MERIT upa cells within the snap window")
        sys.exit(2)
    err = np.where(valid, np.abs(win - args.target_area_km2), np.inf)
    ri, ci = np.unravel_index(np.argmin(err), err.shape)
    orow, ocol = r0 + ri, c0 + ci
    snap_upa = float(upa[orow, ocol])
    olon, olat = xy(transform, orow, ocol)
    logger.info(
        f"Outlet snapped ({args.outlet_lon:.4f},{args.outlet_lat:.4f}) -> "
        f"({olon:.4f},{olat:.4f}); MERIT upa = {snap_upa:.0f} km2, "
        f"target = {args.target_area_km2:.0f} km2 "
        f"({100.0 * (snap_upa - args.target_area_km2) / args.target_area_km2:+.1f}%)"
    )

    # ---- trace the contributing area ---------------------------------------
    logger.info("Tracing upstream contributing area ...")
    mask = trace_upstream(fdir, (orow, ocol), nrows, ncols)
    areas = cell_area_km2(nrows, transform)
    area_km2 = float((mask * areas[:, None]).sum())
    err_pct = 100.0 * (area_km2 - args.target_area_km2) / args.target_area_km2
    logger.info(f"Traced catchment: {area_km2:.0f} km2 ({err_pct:+.1f}% vs documented)")

    if abs(err_pct) > args.max_area_error_pct:
        logger.error(
            f"Traced area {area_km2:.0f} km2 deviates {err_pct:+.1f}% from the "
            f"documented {args.target_area_km2:.0f} km2 (limit "
            f"+/-{args.max_area_error_pct}%). Refusing to write a wrong domain "
            f"(dt_s09). Widen --snap_deg or check the outlet coordinates."
        )
        sys.exit(2)

    # ---- write mask, clips, polygon ----------------------------------------
    prof = dict(driver="GTiff", height=nrows, width=ncols, count=1,
                crs="EPSG:4326", transform=transform, compress="deflate")

    mask_tif = Path(str(out_shp) + ".mask.tif")
    with rasterio.open(mask_tif, "w", dtype="uint8", nodata=0, **prof) as d:
        d.write(mask.astype(np.uint8), 1)
    with rasterio.open(f"{stem}_dir.tif", "w", dtype="int16", **prof) as d:
        d.write(fdir, 1)
    with rasterio.open(f"{stem}_upa.tif", "w", dtype="float32", **prof) as d:
        d.write(upa, 1)

    geoms = [shapely_shape(g) for g, v in
             rio_shapes(mask.astype(np.uint8), mask=mask, transform=transform) if v == 1]
    if not geoms:
        logger.error("Polygonisation produced no geometry")
        sys.exit(3)
    gdf = gpd.GeoDataFrame(
        {"gauge_lon": [olon], "gauge_lat": [olat],
         "area_km2": [area_km2], "upa_km2": [snap_upa]},
        geometry=[max(geoms, key=lambda g: g.area)], crs="EPSG:4326")
    gdf.to_file(out_shp)

    result = {
        "status": "success",
        "out_shp": str(out_shp),
        "dir_tif": f"{stem}_dir.tif",
        "upa_tif": f"{stem}_upa.tif",
        "mask_tif": str(mask_tif),
        "snapped_outlet": {"lon": olon, "lat": olat},
        "merit_upa_km2": snap_upa,
        "traced_area_km2": area_km2,
        "target_area_km2": args.target_area_km2,
        "area_error_pct": err_pct,
        "bounds": list(gdf.total_bounds),
    }
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        import traceback; traceback.print_exc()
        sys.exit(2)
