#!/usr/bin/env python
"""build_cwatm_waterbodies.py -- rasterize HydroLAKES onto the CWatM clone grid.

Emits the six NetCDFs that cwatm/hydrological_modules/lakes_reservoirs.py reads
via loadmap() when [OPTIONS] includeWaterBodies = True:

    waterBodyID    int   Hylak_id of the dominant water body in each cell (0 = none)
    waterBodyType  int   1 = lake, 2 = reservoir   (CWatM convention)
    waterBodyArea  float body surface area,   km2   (burned on every footprint cell)
    waterBodyDis   float long-term mean outflow, m3/s
    waterBodyYear  int   activation year (0 = active for the whole simulation)
    waterBodyVolRes float reservoir storage capacity, Mm3 (0 for natural lakes)

Rasterization is a pure FOOTPRINT operation: each HydroLAKES polygon is burned
onto a sub-grid (--subsample x finer than the clone cell), and each clone cell is
assigned the Hylak_id that covers the MOST of its area (the dominant body). A body
that is not the dominant body of any clone cell is DROPPED and counted -- there is
NO pour-point relocation, so an out-of-basin lake can never sink a spurious LDD pit
into the mainstem (lakes_reservoirs.py:373 sets ldd=5 on every waterBodyID cell).

Attribute maps are burned uniformly on every footprint cell of a kept body; CWatM
compresses them by waterBodyID internally. Natural lakes (Lake_type == 1) are written
with waterBodyVolRes = 0; CWatM then derives their volume from area
(lakes_reservoirs.py:479). Reservoir volume is taken from HydroLAKES Vol_total ONLY
for reservoir/regulated bodies (Lake_type in {2, 3}).

Usage:
    python build_cwatm_waterbodies.py \
        --clone   /path/static/MaskMap.nc \
        --hydrolakes /mnt/disk1/Hydrocraft_server/data/lakes/HydroLAKES_polys_v10.shp \
        --out_dir /path/static \
        [--subsample 20] [--min_area_km2 10.0]
"""
import argparse
import os
import sys
import numpy as np
import netCDF4 as nc
from osgeo import ogr, gdal

# HydroLAKES Lake_type -> CWatM waterBodyTyp
_LAKE = 1        # HydroLAKES natural lake      -> CWatM lake
_RESERVOIR = 2   # HydroLAKES reservoir         -> CWatM reservoir
_LAKE_CONTROL = 3  # HydroLAKES regulated lake  -> CWatM reservoir


def _read_clone(clone_path):
    """Return (lat, lon, dlat, dlon) of the clone grid; lat may be descending."""
    ds = nc.Dataset(clone_path)
    latn = "lat" if "lat" in ds.variables else "latitude"
    lonn = "lon" if "lon" in ds.variables else "longitude"
    lat = ds.variables[latn][:].astype(float)
    lon = ds.variables[lonn][:].astype(float)
    ds.close()
    dlat = float(lat[1] - lat[0])   # NEGATIVE when the axis is north-first
    dlon = float(lon[1] - lon[0])
    return lat, lon, dlat, dlon


def _write_map(out_path, varname, data, lat, lon):
    ds = nc.Dataset(out_path, "w", format="NETCDF4")
    ds.createDimension("lat", len(lat))
    ds.createDimension("lon", len(lon))
    vlat = ds.createVariable("lat", "f8", ("lat",)); vlat[:] = lat
    vlat.units = "degrees_north"; vlat.standard_name = "latitude"
    vlon = ds.createVariable("lon", "f8", ("lon",)); vlon[:] = lon
    vlon.units = "degrees_east"; vlon.standard_name = "longitude"
    dtype = "i4" if data.dtype.kind in "iu" else "f8"
    v = ds.createVariable(varname, dtype, ("lat", "lon"), zlib=True)
    v[:] = data
    ds.close()


def build(clone_path, shp_path, out_dir, subsample=20, min_area_km2=10.0):
    lat, lon, dlat, dlon = _read_clone(clone_path)
    ny, nx = len(lat), len(lon)
    # Cell EDGES (handle descending lat): edge[0] is the outer edge of cell 0.
    lat_top = lat[0] - dlat / 2.0            # dlat<0 -> this is the northern edge
    lon_left = lon[0] - dlon / 2.0
    # Fine sub-grid geotransform in gdal convention (origin = top-left, negative y-step)
    sub = int(subsample)
    fy, fx = ny * sub, nx * sub
    y_top = max(lat_top, lat_top + dlat)     # northern edge in absolute degrees
    x_left = lon_left
    px = abs(dlon) / sub
    py = abs(dlat) / sub
    gt = (x_left, px, 0.0, y_top, 0.0, -py)

    # --- spatial-filter HydroLAKES to the clone bbox, burn Hylak_id on the sub-grid ---
    src = ogr.Open(shp_path)
    if src is None:
        raise SystemExit("cannot open HydroLAKES: %s" % shp_path)
    lyr = src.GetLayer()
    minx, maxx = x_left, x_left + nx * abs(dlon)
    miny, maxy = y_top - ny * abs(dlat), y_top
    lyr.SetSpatialFilterRect(minx, miny, maxx, maxy)

    mem = gdal.GetDriverByName("MEM").Create("", fx, fy, 1, gdal.GDT_Int32)
    mem.SetGeoTransform(gt)
    mem.GetRasterBand(1).Fill(0)
    gdal.RasterizeLayer(mem, [1], lyr, options=["ATTRIBUTE=Hylak_id"])
    fine = mem.GetRasterBand(1).ReadAsArray()   # (fy, fx), Hylak_id or 0

    # attribute lookup for the filtered bodies
    attr = {}
    lyr.ResetReading()
    for feat in lyr:
        hid = int(feat.GetField("Hylak_id"))
        ltype = int(feat.GetField("Lake_type") or 1)
        attr[hid] = dict(
            typ=_RESERVOIR if ltype in (_RESERVOIR, _LAKE_CONTROL) else _LAKE,
            area=float(feat.GetField("Lake_area") or 0.0),          # km2
            dis=float(feat.GetField("Dis_avg") or 0.0),             # m3/s
            volres=float(feat.GetField("Vol_total") or 0.0)         # Mm3
            if ltype in (_RESERVOIR, _LAKE_CONTROL) else 0.0,
        )

    # --- dominant body per clone cell (majority of sub-cells), footprint only ---
    wbid = np.zeros((ny, nx), dtype=np.int32)
    dropped = 0
    kept = set()
    fine_r = fine.reshape(ny, sub, nx, sub)
    for j in range(ny):
        for i in range(nx):
            block = fine_r[j, :, i, :].ravel()
            block = block[block > 0]
            if block.size == 0:
                continue
            ids, counts = np.unique(block, return_counts=True)
            dom = int(ids[np.argmax(counts)])
            if attr.get(dom, {}).get("area", 0.0) < min_area_km2:
                continue
            wbid[j, i] = dom
            kept.add(dom)

    present = set(int(v) for v in np.unique(fine) if v > 0)
    dropped = len([h for h in present if h not in kept])

    # --- burn attributes uniformly on every footprint cell of each kept body ---
    typ = np.zeros((ny, nx), dtype=np.int32)
    area = np.zeros((ny, nx), dtype=np.float64)
    dis = np.zeros((ny, nx), dtype=np.float64)
    year = np.zeros((ny, nx), dtype=np.int32)   # 0 = active whole simulation
    volres = np.zeros((ny, nx), dtype=np.float64)
    for hid in kept:
        m = wbid == hid
        a = attr[hid]
        typ[m] = a["typ"]
        area[m] = a["area"]
        dis[m] = a["dis"]
        volres[m] = a["volres"]

    os.makedirs(out_dir, exist_ok=True)
    _write_map(os.path.join(out_dir, "waterBodyID.nc"), "waterBodyID", wbid, lat, lon)
    _write_map(os.path.join(out_dir, "waterBodyType.nc"), "waterBodyType", typ, lat, lon)
    _write_map(os.path.join(out_dir, "waterBodyArea.nc"), "waterBodyArea", area, lat, lon)
    _write_map(os.path.join(out_dir, "waterBodyDis.nc"), "waterBodyDis", dis, lat, lon)
    _write_map(os.path.join(out_dir, "waterBodyYear.nc"), "waterBodyYear", year, lat, lon)
    _write_map(os.path.join(out_dir, "waterBodyVolRes.nc"), "waterBodyVolRes", volres, lat, lon)

    nres = sum(1 for h in kept if attr[h]["typ"] == _RESERVOIR)
    print("[build_cwatm_waterbodies] kept=%d (reservoirs=%d, lakes=%d) dropped=%d "
          "cells_with_body=%d biggest_volres_Mm3=%.0f"
          % (len(kept), nres, len(kept) - nres, dropped, int((wbid > 0).sum()),
             float(volres.max()) if kept else 0.0))
    return dict(kept=len(kept), reservoirs=nres, dropped=dropped,
                cells=int((wbid > 0).sum()), max_volres=float(volres.max()) if kept else 0.0)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--clone", required=True, help="clone/MaskMap NetCDF defining the grid")
    ap.add_argument("--hydrolakes", required=True, help="HydroLAKES_polys_v10.shp")
    ap.add_argument("--out_dir", required=True, help="directory for the six NetCDFs (= PathMaps)")
    ap.add_argument("--subsample", type=int, default=20, help="sub-grid refinement per clone cell")
    ap.add_argument("--min_area_km2", type=float, default=10.0,
                    help="drop bodies smaller than this (km2)")
    a = ap.parse_args()
    build(a.clone, a.hydrolakes, a.out_dir, a.subsample, a.min_area_km2)


if __name__ == "__main__":
    main()
