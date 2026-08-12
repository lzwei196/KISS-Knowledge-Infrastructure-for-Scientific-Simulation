#!/usr/bin/env python3
"""
build_cwatm_ancillary.py — 10-day crop-coefficient / interception-capacity stacks
and the relativeElevation (dzRel) map, on the grid defined by --static_dir.

CWatM reads `<cover>_cropCoefficientNC` and `<cover>_interceptCapNC` as 36+1
ten-day maps (period 0 repeats at index 36 so the model can interpolate across
the year end).  The curves below are the FAO-56 single-crop-coefficient shapes
for a Northern-Hemisphere growing season, applied uniformly in space; the
spatial variability of ET comes from the land-cover fractions and the forcing.

relativeElevation.nc is produced by build_cwatm_static.py (it needs the 3-arcsec
DEM) and is simply carried across here so that a case directory can point
[SOIL] relativeElevation at $(PathAnc).

Usage
-----
    python build_cwatm_ancillary.py --static_dir case/static --output_dir case/ancillary
"""
import argparse
import os
import shutil

import numpy as np
import netCDF4 as nc

# 37 ten-day values (36 periods + wrap).  Northern-Hemisphere season.
CURVES = {
    "cropCoefficientForest_10days": ("cropCoefficient", [
        0.800000, 0.800000, 0.806667, 0.813333, 0.820000, 0.840000, 0.860000,
        0.880000, 0.903333, 0.926667, 0.950000, 0.973333, 0.996667, 1.020000,
        1.030000, 1.040000, 1.050000, 1.050000, 1.050000, 1.050000, 1.043333,
        1.036667, 1.030000, 1.013333, 0.996667, 0.980000, 0.960000, 0.940000,
        0.920000, 0.896667, 0.873333, 0.850000, 0.833333, 0.816667, 0.800000,
        0.800000, 0.800000]),
    "cropCoefficientGrassland_10days": ("cropCoefficient", [
        0.560000, 0.550000, 0.560000, 0.570000, 0.580000, 0.613333, 0.646667,
        0.680000, 0.726667, 0.773333, 0.820000, 0.863333, 0.906667, 0.950000,
        0.966667, 0.983333, 1.000000, 1.000000, 1.000000, 1.000000, 0.993333,
        0.986667, 0.980000, 0.953333, 0.926667, 0.900000, 0.860000, 0.820000,
        0.780000, 0.736667, 0.693333, 0.650000, 0.626667, 0.603333, 0.580000,
        0.570000, 0.560000]),
    "cropCoefficientirrPaddy_10days": ("cropCoefficient", [
        0.500000, 0.500000, 0.500000, 0.500000, 0.500000, 0.516667, 0.533333,
        0.550000, 0.583333, 0.616667, 0.650000, 0.733333, 0.816667, 0.900000,
        0.966667, 1.033333, 1.100000, 1.100000, 1.100000, 1.100000, 1.083333,
        1.066667, 1.050000, 1.000000, 0.950000, 0.900000, 0.816667, 0.733333,
        0.650000, 0.606667, 0.563333, 0.520000, 0.513333, 0.506667, 0.500000,
        0.500000, 0.500000]),
    "cropCoefficientirrNonPaddy_10days": ("cropCoefficient", [
        0.733333, 0.750000, 0.760000, 0.770000, 0.780000, 0.820000, 0.860000,
        0.900000, 0.950000, 1.000000, 1.050000, 1.066667, 1.083333, 1.100000,
        1.033333, 0.966667, 0.900000, 0.933333, 0.966667, 1.000000, 1.033333,
        1.066667, 1.100000, 1.033333, 0.966667, 0.900000, 0.866667, 0.833333,
        0.800000, 0.766667, 0.733333, 0.700000, 0.700000, 0.700000, 0.700000,
        0.716667, 0.733333]),
    "interceptCapForest_10days": ("interceptCap", [
        0.001000, 0.001000, 0.001000, 0.001000, 0.001000, 0.001167, 0.001333,
        0.001500, 0.001667, 0.001833, 0.002000, 0.002167, 0.002333, 0.002500,
        0.002600, 0.002700, 0.002800, 0.002867, 0.002933, 0.003000, 0.002933,
        0.002867, 0.002800, 0.002700, 0.002600, 0.002500, 0.002333, 0.002167,
        0.002000, 0.001833, 0.001667, 0.001500, 0.001333, 0.001167, 0.001000,
        0.001000, 0.001000]),
    "interceptCapGrassland_10days": ("interceptCap", [
        0.000800, 0.000800, 0.000800, 0.000800, 0.000800, 0.000867, 0.000933,
        0.001000, 0.001100, 0.001200, 0.001300, 0.001400, 0.001500, 0.001600,
        0.001667, 0.001733, 0.001800, 0.001867, 0.001933, 0.002000, 0.001933,
        0.001867, 0.001800, 0.001700, 0.001600, 0.001500, 0.001400, 0.001300,
        0.001200, 0.001133, 0.001067, 0.001000, 0.000933, 0.000867, 0.000800,
        0.000800, 0.000800]),
}

UNITS = {"cropCoefficient": "-", "interceptCap": "m"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--static_dir", required=True)
    ap.add_argument("--output_dir", required=True)
    a = ap.parse_args()
    os.makedirs(a.output_dir, exist_ok=True)

    ref = nc.Dataset(os.path.join(a.static_dir, "MaskMap.nc"))
    lats = np.array(ref["lat"][:])
    lons = np.array(ref["lon"][:])
    ref.close()
    nlat, nlon = len(lats), len(lons)

    for fname, (var, curve) in CURVES.items():
        assert len(curve) == 37, fname
        path = os.path.join(a.output_dir, fname + ".nc")
        ds = nc.Dataset(path, "w", format="NETCDF4")
        ds.createDimension("lon", nlon)
        ds.createDimension("lat", nlat)
        ds.createDimension("time", 37)
        lv = ds.createVariable("lon", "f4", ("lon",)); lv[:] = lons; lv.units = "degrees_east"
        tv = ds.createVariable("lat", "f4", ("lat",)); tv[:] = lats; tv.units = "degrees_north"
        tt = ds.createVariable("time", "i4", ("time",)); tt[:] = np.arange(37)
        tt.units = "10-day period"
        v = ds.createVariable(var, "f4", ("time", "lat", "lon"), fill_value=-9999.0)
        v.units = UNITS[var]
        v[:] = np.broadcast_to(np.array(curve, dtype=np.float32)[:, None, None],
                               (37, nlat, nlon))
        ds.close()
        print(f"  wrote {fname}.nc  ({min(curve):.4g} .. {max(curve):.4g})", flush=True)

    src = os.path.join(a.static_dir, "relativeElevation.nc")
    if os.path.exists(src):
        shutil.copy(src, os.path.join(a.output_dir, "relativeElevation.nc"))
        print("  copied relativeElevation.nc from the static stack", flush=True)
    else:
        raise SystemExit(f"missing {src} — run build_cwatm_static.py first")


if __name__ == "__main__":
    main()
