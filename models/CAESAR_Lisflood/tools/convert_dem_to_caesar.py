#!/usr/bin/env python3
"""
Prepare an ESRI ASCII Grid DEM for HAIL-CAESAR (CAESAR-Lisflood).

This implements pipeline stage 1 (`convert_dem_to_caesar`) which was
documented in SKILL.md but previously missing from tools/.

What it does:
  1. Reads a source DEM (GeoTIFF etc., any CRS) via rasterio.
  2. Clips to a bounding box (WGS84 lon/lat) with optional buffer.
  3. Reprojects to a projected CRS in METRES (auto-picked UTM zone if not given)
     so that cellsize is in metres as HAIL-CAESAR requires.
  4. Resamples to the requested cellsize (default 250 m).
  5. Masks source-NODATA, optionally fills depressions (whitebox) so the
     domain drains, and sets NODATA = -9999.
  6. Writes a clean ESRI ASCII grid: exactly 6 header lines
     (ncols/nrows/xllcorner/yllcorner/cellsize/NODATA_value) + grid,
     Unix line endings, elevations in metres.

HAIL-CAESAR requirements honoured (see dag.yaml / docs/01_dem_preparation.md):
  - cellsize in metres (NOT degrees) -> reproject to UTM
  - NODATA_value -9999
  - read_fname must be given WITHOUT the .asc extension when wiring the param file
  - water exits through grid-edge cells; depression filling prevents
    spurious interior ponding.

Usage:
    python convert_dem_to_caesar.py \\
        --input /path/dem.tif \\
        --output /path/run/dem_tile.asc \\
        --bbox 118.5 32.5 119.5 33.5 \\
        --cellsize 250 \\
        --fill_sinks
"""

import argparse
import os
import sys
import numpy as np


def pick_utm_epsg(lon: float, lat: float) -> int:
    """Return the EPSG code of the UTM zone containing (lon, lat)."""
    zone = int((lon + 180.0) // 6.0) + 1
    return (32600 if lat >= 0 else 32700) + zone


def main():
    p = argparse.ArgumentParser(description="Prepare an ASCII DEM for HAIL-CAESAR")
    p.add_argument("--input", required=True, help="Source DEM (GeoTIFF, any CRS)")
    p.add_argument("--output", required=True, help="Output .asc path")
    p.add_argument("--bbox", nargs=4, type=float, metavar=("W", "S", "E", "N"),
                   help="Clip bbox in WGS84 lon/lat (W S E N)")
    p.add_argument("--buffer_deg", type=float, default=0.05,
                   help="Buffer added around bbox in degrees before clipping")
    p.add_argument("--cellsize", type=float, default=250.0,
                   help="Target cellsize in metres")
    p.add_argument("--dst_epsg", type=int, default=None,
                   help="Target projected CRS EPSG (default: auto UTM)")
    p.add_argument("--fill_sinks", action="store_true",
                   help="Fill depressions with whitebox so domain drains")
    p.add_argument("--src_nodata", type=float, default=None,
                   help="Override source NODATA value")
    # --- single-outlet catchment conditioning (docs/01 Step 4; dag caveat
    #     "Q is summed over ALL DEM edge cells; mask the DEM to a single
    #      outlet before comparing against a gauge") ---
    p.add_argument("--basin_shp", default=None,
                   help="Catchment polygon (shapefile/GeoJSON). Cells outside "
                        "become NODATA so the domain is the gauge's catchment.")
    p.add_argument("--basin_id_field", default=None,
                   help="Attribute field used to select one basin from --basin_shp")
    p.add_argument("--basin_id", default=None,
                   help="Value of --basin_id_field identifying the basin")
    p.add_argument("--outlet_lonlat", nargs=2, type=float, metavar=("LON", "LAT"),
                   default=None,
                   help="Gauge/outlet location in WGS84. The nearest valid cell "
                        "is used as THE outlet; without it the lowest valid cell is.")
    p.add_argument("--single_outlet", action="store_true",
                   help="Pad the domain with NODATA on all four sides and carve a "
                        "one-cell channel from the outlet to the nearest array edge, "
                        "so water leaves through EXACTLY ONE edge cell.")
    p.add_argument("--outlet_snap_cells", type=int, default=5,
                   help="Search radius (cells) used to snap --outlet_lonlat onto "
                        "the lowest (channel) cell rather than the geometrically "
                        "nearest one")
    p.add_argument("--pad_cells", type=int, default=3,
                   help="NODATA border width (cells) added by --single_outlet")
    p.add_argument("--outlet_slope", type=float, default=0.001,
                   help="Elevation drop per cell along the carved outlet channel "
                        "(should match slope_on_edge_cell in the .params file)")
    p.add_argument("--meta_json", default=None,
                   help="Write grid/outlet metadata JSON here (for the .params file)")
    args = p.parse_args()

    import rasterio
    from rasterio.warp import calculate_default_transform, reproject, Resampling
    from rasterio.windows import from_bounds

    NODATA = -9999.0

    # ---- basin polygon (optional): defines the mask AND the default bbox ----
    basin_geom_ll = None
    if args.basin_shp:
        import geopandas as gpd
        gdf = gpd.read_file(args.basin_shp)
        if args.basin_id_field and args.basin_id is not None:
            gdf = gdf[gdf[args.basin_id_field].astype(str) == str(args.basin_id)]
        if len(gdf) == 0:
            raise SystemExit(f"No basin matched in {args.basin_shp}")
        gdf = gdf.to_crs("EPSG:4326")
        basin_geom_ll = gdf.geometry.union_all() if hasattr(gdf.geometry, "union_all") \
            else gdf.geometry.unary_union
        if not args.bbox:
            W, S, E, N = basin_geom_ll.bounds
            args.bbox = [W, S, E, N]
            print(f"bbox taken from basin polygon: "
                  f"{W:.4f} {S:.4f} {E:.4f} {N:.4f}")

    with rasterio.open(args.input) as src:
        src_nodata = args.src_nodata if args.src_nodata is not None else src.nodata
        # 1+2. clip in source CRS (source assumed lon/lat or already projected)
        if args.bbox:
            W, S, E, N = args.bbox
            b = args.buffer_deg
            win = from_bounds(W - b, S - b, E + b, N + b, src.transform)
            win = win.round_offsets().round_lengths()
            data = src.read(1, window=win)
            win_transform = src.window_transform(win)
        else:
            data = src.read(1)
            win_transform = src.transform
        src_crs = src.crs

    data = data.astype("float32")
    if src_nodata is not None:
        data[data == src_nodata] = np.nan
    # guard against fill/ocean sentinels
    data[data > 9000] = np.nan
    data[data < -1000] = np.nan

    # 3. choose destination CRS
    if args.dst_epsg:
        dst_epsg = args.dst_epsg
    else:
        if args.bbox:
            clon = 0.5 * (args.bbox[0] + args.bbox[2])
            clat = 0.5 * (args.bbox[1] + args.bbox[3])
        else:
            clon, clat = 0.0, 0.0
        dst_epsg = pick_utm_epsg(clon, clat)
    dst_crs = rasterio.crs.CRS.from_epsg(dst_epsg)

    h, w = data.shape
    src_bounds = rasterio.transform.array_bounds(h, w, win_transform)  # (W,S,E,N)
    dst_transform, dst_w, dst_h = calculate_default_transform(
        src_crs, dst_crs, w, h, *src_bounds, resolution=args.cellsize)

    dst = np.full((dst_h, dst_w), np.nan, dtype="float32")
    reproject(
        source=data, destination=dst,
        src_transform=win_transform, src_crs=src_crs,
        dst_transform=dst_transform, dst_crs=dst_crs,
        src_nodata=np.nan, dst_nodata=np.nan,
        resampling=Resampling.bilinear,
    )

    # 4b. mask to the catchment polygon -> the model domain IS the gauge basin
    if basin_geom_ll is not None:
        from rasterio.features import geometry_mask
        from rasterio.warp import transform_geom
        geom_dst = transform_geom("EPSG:4326", dst_crs,
                                  basin_geom_ll.__geo_interface__)
        inside = ~geometry_mask([geom_dst], out_shape=(dst_h, dst_w),
                                transform=dst_transform, invert=False)
        n_before = int(np.sum(~np.isnan(dst)))
        dst = np.where(inside, dst, np.nan)
        n_after = int(np.sum(~np.isnan(dst)))
        print(f"Basin mask applied: {n_after} of {n_before} cells kept "
              f"({n_after * args.cellsize ** 2 / 1e6:.1f} km2)")
        if n_after == 0:
            raise SystemExit("Basin mask removed every cell -- check the polygon/CRS")

    # 5. optional depression fill
    if args.fill_sinks:
        try:
            import tempfile
            import whitebox
            wbt = whitebox.WhiteboxTools()
            wbt.set_verbose_mode(False)
            tmpd = tempfile.mkdtemp(prefix="caesar_dem_")
            tin = os.path.join(tmpd, "in.tif")
            tout = os.path.join(tmpd, "out.tif")
            prof = {
                "driver": "GTiff", "height": dst_h, "width": dst_w, "count": 1,
                "dtype": "float32", "crs": dst_crs, "transform": dst_transform,
                "nodata": NODATA,
            }
            tmp = dst.copy()
            tmp[np.isnan(tmp)] = NODATA
            with rasterio.open(tin, "w", **prof) as ds:
                ds.write(tmp, 1)
            wbt.fill_depressions(tin, tout)
            with rasterio.open(tout) as ds:
                filled = ds.read(1).astype("float32")
            filled[filled == NODATA] = np.nan
            # only keep fill where original was valid
            dst = np.where(np.isnan(dst), np.nan, filled)
            print(f"Depression fill applied (whitebox). "
                  f"raised {np.nansum(filled - tmp > 0.001)} cells")
        except Exception as e:
            print(f"WARNING: depression fill skipped ({e})")

    # 5b. single-outlet conditioning.
    #
    # HAIL-CAESAR lets water leave through EVERY grid-edge cell and reports the
    # SUM of those fluxes as the catchment hydrograph (dag caveat / triplet
    # T016). A basin-masked DEM whose ridge cells touch the array border
    # therefore leaks at many points and over-reports Q. Fix, per
    # docs/01_dem_preparation.md Step 4 ("pad the DEM with a narrow strip of
    # low-elevation cells leading to the edge"):
    #   1. pad NODATA on all four sides  -> no valid cell touches the border
    #   2. carve ONE channel from the outlet cell to the nearest border
    # so exactly one edge cell can discharge.
    outlet_rc = None
    if args.single_outlet:
        pad = max(1, int(args.pad_cells))
        dst = np.pad(dst, pad, mode="constant", constant_values=np.nan)
        dst_h, dst_w = dst.shape
        dst_transform = rasterio.Affine(
            dst_transform.a, dst_transform.b,
            dst_transform.c - pad * dst_transform.a,
            dst_transform.d, dst_transform.e,
            dst_transform.f - pad * dst_transform.e)

        if args.outlet_lonlat:
            # Snap the gauge to the LOWEST valid cell in a small window. The
            # geometrically nearest cell to a gauge coordinate is very often a
            # valley-SIDE cell, tens of metres above the channel (at 200 m the
            # Inangahua gauge snapped 48 m above the true thalweg), and carving
            # the outlet there leaves the real low point as an interior sink
            # that ponds forever (triplet T017).
            from rasterio.warp import transform as warp_xy
            ox, oy = warp_xy("EPSG:4326", dst_crs,
                             [args.outlet_lonlat[0]], [args.outlet_lonlat[1]])
            inv = ~dst_transform
            gc, gr = inv * (ox[0], oy[0])
            gr, gc = int(round(gr)), int(round(gc))
            k = max(1, int(args.outlet_snap_cells))
            r0, r1 = max(0, gr - k), min(dst_h, gr + k + 1)
            c0, c1 = max(0, gc - k), min(dst_w, gc + k + 1)
            win = dst[r0:r1, c0:c1]
            if np.all(np.isnan(win)):
                raise SystemExit(
                    f"No valid cell within {k} cells of the gauge -- is the "
                    f"gauge inside the basin polygon?")
            wr, wc = np.unravel_index(np.nanargmin(win), win.shape)
            r, c = r0 + int(wr), c0 + int(wc)
            print(f"Outlet snapped to lowest cell within {k} cells of the gauge: "
                  f"row {r} col {c}, elev {dst[r, c]:.1f} m "
                  f"(gauge cell was row {gr} col {gc}; snap distance "
                  f"{np.hypot(r - gr, c - gc) * args.cellsize:.0f} m)")
        else:
            flat = np.nanargmin(dst)
            r, c = np.unravel_index(flat, dst.shape)
            print(f"Outlet = lowest valid cell: row {r} col {c}")
        r, c = int(r), int(c)

        # The outlet MUST be the domain minimum, or water ponds elsewhere.
        zmin = float(np.nanmin(dst))
        if float(dst[r, c]) > zmin + 1e-6:
            lr, lc = np.unravel_index(np.nanargmin(dst), dst.shape)
            raise SystemExit(
                f"Chosen outlet ({r},{c}) at {dst[r, c]:.1f} m is ABOVE the "
                f"domain minimum ({zmin:.1f} m at {lr},{lc}); water would pond "
                f"there instead of leaving. Increase --outlet_snap_cells or "
                f"check the gauge coordinate against the basin polygon.")

        # nearest border, and the straight run of cells from the outlet to it
        dists = {"top": r, "bottom": dst_h - 1 - r,
                 "left": c, "right": dst_w - 1 - c}
        side = min(dists, key=dists.get)
        if side == "top":
            path = [(rr, c) for rr in range(r - 1, -1, -1)]
        elif side == "bottom":
            path = [(rr, c) for rr in range(r + 1, dst_h)]
        elif side == "left":
            path = [(r, cc) for cc in range(c - 1, -1, -1)]
        else:
            path = [(r, cc) for cc in range(c + 1, dst_w)]

        z = float(dst[r, c])
        drop = args.outlet_slope * args.cellsize
        for k, (rr, cc) in enumerate(path, start=1):
            dst[rr, cc] = z - k * drop
        print(f"Carved {len(path)}-cell outlet channel to the {side} edge "
              f"(drop {drop:.3f} m/cell); outlet elevation {z:.2f} m")
        outlet_rc = (r, c)

        # sanity: exactly one valid cell on the whole border
        border = np.concatenate([dst[0, :], dst[-1, :], dst[:, 0], dst[:, -1]])
        n_edge = int(np.sum(~np.isnan(border)))
        print(f"Valid cells on the domain border: {n_edge} (must be 1)")
        if n_edge != 1:
            raise SystemExit(
                f"single-outlet conditioning failed: {n_edge} border cells are "
                f"valid; Q would be summed over all of them")

    # 6. write ESRI ASCII
    grid = dst.copy()
    grid[np.isnan(grid)] = NODATA
    xll = dst_transform.c
    yll = dst_transform.f + dst_h * dst_transform.e  # transform.e is negative
    cell = dst_transform.a

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w", newline="\n") as f:
        f.write(f"ncols {dst_w}\n")
        f.write(f"nrows {dst_h}\n")
        f.write(f"xllcorner {xll:.6f}\n")
        f.write(f"yllcorner {yll:.6f}\n")
        f.write(f"cellsize {cell:.6f}\n")
        f.write(f"NODATA_value {int(NODATA)}\n")
        for row in grid:
            f.write(" ".join(f"{v:.3f}" for v in row) + "\n")

    valid = grid[grid != NODATA]
    print(f"Written {args.output}")
    print(f"  grid {dst_w} x {dst_h} cells @ {cell:.1f} m  (EPSG:{dst_epsg})")
    print(f"  elevation min/mean/max = "
          f"{valid.min():.1f}/{valid.mean():.1f}/{valid.max():.1f} m")
    print(f"  xllcorner {xll:.1f}  yllcorner {yll:.1f}  NODATA -9999")

    n_valid = int(np.sum(grid != NODATA))
    meta = {"epsg": dst_epsg, "ncols": int(dst_w), "nrows": int(dst_h),
            "cellsize": float(cell), "xllcorner": float(xll),
            "yllcorner": float(yll), "nodata": int(NODATA),
            "n_valid_cells": n_valid,
            "domain_area_km2": n_valid * cell * cell / 1e6,
            "outlet_row_col": list(outlet_rc) if outlet_rc else None,
            "elev_min_m": float(valid.min()), "elev_max_m": float(valid.max()),
            "single_outlet": bool(args.single_outlet)}
    print(f"  valid cells {n_valid} -> domain area {meta['domain_area_km2']:.1f} km2")
    if args.meta_json:
        import json
        with open(args.meta_json, "w") as f:
            json.dump(meta, f, indent=2)
        print(f"  metadata -> {args.meta_json}")
    # report metadata for downstream tools
    return meta


if __name__ == "__main__":
    main()
