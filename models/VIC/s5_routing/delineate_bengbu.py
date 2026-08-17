#!/usr/bin/env python3
"""
Step s0 for the Bengbu verifier: crop china_dem_90m to the Huai envelope and
delineate the basin above gauge 51080 (蚌埠) with the KI's own
ki_tools_common.terrain_ops.delineate_basin, then polygonize the basin raster
into the boundary shapefile that s5_routing/build_routing_param.py requires
(it reads VIC_BASIN_SHP unconditionally).

Why the crop
------------
The shipped DEM is 53378x77306 (4.1e9 px) covering all of China. The 210-cell
VIC soil grid already bounds the basin (lon 111.875..117.375, lat
31.125..34.875), so a padded envelope is a safe delineation domain and cuts the
raster to ~4.2e7 px.

Why snap_distance_m=6000 and stream_threshold=1e6  (MEASURED, not guessed)
--------------------------------------------------------------------------
snap_pour_points snaps to the NEAREST cell flagged as stream, not the largest.
Interrogating flow_accum.tif around the published gauge (117.39E, 32.94N):

    within 0.5 km : max accum        118 px (~1 km2)
    within 2.3 km : max accum     21,532 px (~146 km2)   <- a tributary
    within 5.4 km : max accum 17,468,900 px (~118,231 km2) <- the Huai mainstem

The DEM's mainstem channel sits ~5.4 km from the published gauge coordinate, so
the KI default snap_distance_m=3000 cannot reach it and lands on the 146 km2
tributary -- delineating a 145 km2 "basin" instead of 121,330 km2. Raising
stream_threshold alone does NOT fix this: the snap radius is the binding
constraint. We therefore (a) open the radius to 6 km and (b) raise the stream
threshold to 1e6 px (~8,100 km2) so that ONLY trunk rivers are snap candidates
and the 146 km2 tributary is not one.

The area assertion below is the real guard: a silent mis-snap is the documented
failure mode here, so the run aborts unless the delineated area agrees with the
published 121,330 km2 to within +/-12%.

Idempotent: every artefact is skipped if it already exists.
"""
import os, sys, json

# NOTE: do NOT put python_env/lib/python3.12/site-packages on the path. It contains a
# Python-2-era pathlib.py backport (`from collections import Sequence`) that shadows the
# stdlib pathlib and breaks `import rasterio`. Every package needed here (rasterio,
# geopandas, fiona, shapely, whitebox) is already in ~/.local for the system python3.
sys.path.insert(0, "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect_multi_agent")

import numpy as np
import rasterio
from rasterio.windows import from_bounds
from rasterio.features import shapes as rio_shapes
import fiona
from shapely.geometry import shape as shp_shape, mapping
from shapely.ops import unary_union

ROOT = "KISSPATH_ROOT"
DEM_FULL = f"{ROOT}/data/dem/china_dem_90m/china_dem_90m.tif"
OUT = f"{ROOT}/outputs/bengbu_real_1980_1990/delineation"
DEM_CROP = f"{OUT}/dem_huai_90m.tif"
BASIN_DIR = f"{OUT}/basin"
SHP = f"{OUT}/bengbu_boundary.shp"
META = f"{OUT}/delineation.json"

# Gauge 51080 蚌埠 (Bengbu), Huai River. Published drainage area 121,330 km2.
OUTLET_LON, OUTLET_LAT = 117.39, 32.94
PUB_AREA_KM2 = 121330.0
TOL = 0.12

STREAM_THRESHOLD = 1_000_000    # px (~8,100 km2) -- trunk rivers only
SNAP_DIST_M = 6000.0            # must exceed the measured 5.41 km gauge->channel offset

PAD = 0.35
W, E = 111.875 - PAD, 117.375 + PAD
S, N = 31.125 - PAD, 34.875 + PAD


def crop_dem():
    if os.path.exists(DEM_CROP):
        print(f"[0a] crop exists -> {DEM_CROP}")
        return
    print(f"[0a] cropping DEM to lon {W}..{E} lat {S}..{N}")
    with rasterio.open(DEM_FULL) as src:
        win = from_bounds(W, S, E, N, src.transform)
        arr = src.read(1, window=win)
        prof = src.profile.copy()
        prof.update(height=arr.shape[0], width=arr.shape[1],
                    transform=src.window_transform(win),
                    compress="lzw", tiled=True, BIGTIFF="YES")
    with rasterio.open(DEM_CROP, "w", **prof) as dst:
        dst.write(arr, 1)
    print(f"[0a] cropped shape {arr.shape}")


def delineate():
    marker = f"{BASIN_DIR}/basin_area.json"
    if os.path.exists(marker):
        d = json.load(open(marker))
        print(f"[0b] delineation exists: area={d['area']:.0f} km2")
    else:
        from ki_tools_common.terrain_ops import delineate_basin
        os.makedirs(BASIN_DIR, exist_ok=True)
        print(f"[0b] delineate_basin thr={STREAM_THRESHOLD} snap={SNAP_DIST_M} m ...")
        r = delineate_basin(dem_path=DEM_CROP,
                            pour_point=(OUTLET_LON, OUTLET_LAT),
                            output_dir=BASIN_DIR,
                            stream_threshold=STREAM_THRESHOLD,
                            snap_distance_m=SNAP_DIST_M)
        d = {"area": float(r["basin_area_km2"]),
             "basin_raster": r["basin_raster"],
             "flow_accum": r["flow_accum"],
             "filled_dem": r["filled_dem"],
             "stream_threshold": STREAM_THRESHOLD,
             "snap_distance_m": SNAP_DIST_M}
        json.dump(d, open(marker, "w"), indent=2)

    err = abs(d["area"] - PUB_AREA_KM2) / PUB_AREA_KM2
    print(f"[0b] area={d['area']:.0f} km2 vs published {PUB_AREA_KM2:.0f} "
          f"(err {err*100:+.1f}%)")
    if err > TOL:
        raise RuntimeError(
            f"delineated area {d['area']:.0f} km2 is {err*100:.1f}% off the published "
            f"{PUB_AREA_KM2:.0f} km2 -- pour point almost certainly snapped to the "
            f"wrong channel; do NOT proceed with this basin")
    d["area_err_pct"] = err * 100.0
    return d


def polygonize(d):
    if os.path.exists(SHP):
        print(f"[0c] shapefile exists -> {SHP}")
        return
    print("[0c] polygonizing basin raster")
    with rasterio.open(d["basin_raster"]) as src:
        bas = src.read(1)
        nod = src.nodata if src.nodata is not None else 0
        mask = (bas > 0) & (bas != nod)
        geoms = [shp_shape(g) for g, v in rio_shapes(bas.astype("uint8"), mask=mask,
                                                     transform=src.transform) if v == 1]
        crs = src.crs
    poly = unary_union(geoms)
    parts = [poly] if poly.geom_type == "Polygon" else list(poly.geoms)
    schema = {"geometry": "Polygon", "properties": {"name": "str"}}
    with fiona.open(SHP, "w", driver="ESRI Shapefile", crs=crs, schema=schema) as dst:
        for p in parts:
            dst.write({"geometry": mapping(p), "properties": {"name": "bengbu"}})
    print(f"[0c] wrote {SHP} ({len(parts)} part(s))")


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    crop_dem()
    d = delineate()
    polygonize(d)
    json.dump(d, open(META, "w"), indent=2)
    print("\n[s0 DONE]")
    print(json.dumps(d, indent=2))
