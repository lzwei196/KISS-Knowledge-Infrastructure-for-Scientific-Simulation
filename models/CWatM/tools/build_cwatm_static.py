#!/usr/bin/env python3
"""
build_cwatm_static.py — bootstrap the CWatM static stack for a NEW basin.

Inputs
------
MERIT-Hydro  3-arcsec `dir` (D8, ArcGIS codes), `upa` (km2), `elv` (m), `wth` (m)
ESA-CCI-LC   0.1 deg land-cover class map (LCCS codes)

Outputs (all NetCDF on the SAME lat/lon grid — every other CWatM input must match)
---------------------------------------------------------------------------------
MaskMap.nc  Ldd.nc  dem.nc  ElevationStD.nc  CellArea.nc
chanGrad.nc chanLength.nc chanWidth.nc chanDepth.nc chanMan.nc
fractionForest.nc fractionGrassland.nc fractionIrrPaddy.nc
fractionIrrNonPaddy.nc fractionSealed.nc fractionWater.nc
static_meta.json

Method
------
1. Snap the gauge to the local maximum of MERIT `upa` (window ``--snap_window_px``).
2. Trace the full 3-arcsec upstream basin from the snapped pixel (D8 reverse walk).
3. Upscale to ``--res`` with outlet-pixel tracing (COTAT-style):
   for every coarse cell, the basin pixel of maximum `upa` is the cell outlet;
   follow the fine D8 path downstream until it leaves the cell — the coarse cell
   it enters gives the coarse LDD direction (PCRaster 1-9, 5 = pit).
4. Mask = coarse cells with basin fraction >= 0.5, closed under the coarse LDD so
   every cell drains to the outlet cell, then pruned of cells that do not.

Self-verification
-----------------
Prints the MERIT upstream area at the snapped gauge pixel, the fine-scale traced
basin area and the summed coarse mask area, against ``--expected_area_km2``.
Agreement within a few percent means the LDD upscaling found the right river.

Usage
-----
    python build_cwatm_static.py --gauge_lon 115.98 --gauge_lat 29.73 \
        --bbox 24.0 36.0 90.0 117.0 --res 0.5 \
        --merit_dir /path/to/merit_hydro \
        --esa_lc /path/to/ESA_CCI_LC_global_2015_01deg.tif \
        --expected_area_km2 1488210 --out_dir case/static
"""
import argparse
import json
import os
import sys

import numpy as np
import netCDF4 as nc
from osgeo import gdal

gdal.UseExceptions()

# MERIT-Hydro `dir` is the ArcGIS D8 convention.  (dy, dx) with y increasing south.
D8_OFFSET = {1: (0, 1), 2: (1, 1), 4: (1, 0), 8: (1, -1),
             16: (0, -1), 32: (-1, -1), 64: (-1, 0), 128: (-1, 1)}

# PCRaster LDD:  7 8 9 / 4 5 6 / 1 2 3   (row increases southward)
PCR_CODE = {(-1, -1): 7, (-1, 0): 8, (-1, 1): 9,
            (0, -1): 4, (0, 0): 5, (0, 1): 6,
            (1, -1): 1, (1, 0): 2, (1, 1): 3}

# ESA-CCI-LC (LCCS) class -> CWatM cover type.  Everything not listed falls to
# grassland, which CWatM itself recomputes as 1 - sum(others).
LC_FOREST = {50, 60, 61, 62, 70, 71, 72, 80, 81, 82, 90, 100, 160, 170}
LC_IRR_PADDY = {20}                  # "cropland, irrigated or post-flooding"
LC_IRR_NONPADDY = {10, 11, 12, 30}   # rainfed cropland + cropland-dominated mosaic
LC_SEALED = {190}
LC_WATER = {210}

EARTH_R = 6371000.0


def log(*a):
    print(*a, flush=True)


# --------------------------------------------------------------------- MERIT I/O
def _tiles_for(bbox, merit_dir, var):
    """MERIT ships 5x5 degree tiles named nNNeEEE_<var>.tif."""
    lat_min, lat_max, lon_min, lon_max = bbox
    out = []
    for la in range(int(np.floor(lat_min / 5) * 5), int(np.ceil(lat_max / 5) * 5), 5):
        for lo in range(int(np.floor(lon_min / 5) * 5), int(np.ceil(lon_max / 5) * 5), 5):
            name = f"{'n' if la >= 0 else 's'}{abs(la):02d}{'e' if lo >= 0 else 'w'}{abs(lo):03d}_{var}.tif"
            p = os.path.join(merit_dir, name)
            if os.path.exists(p):
                out.append(p)
    if not out:
        sys.exit(f"no MERIT '{var}' tiles found in {merit_dir} for bbox {bbox}")
    return out


def read_merit(merit_dir, var, win):
    """Read `var` over the geographic window `win` = (lat_min, lat_max, lon_min, lon_max)."""
    vrt = gdal.BuildVRT("", _tiles_for(win, merit_dir, var))
    gt = vrt.GetGeoTransform()
    x0 = int(np.floor((win[2] - gt[0]) / gt[1]))
    x1 = int(np.ceil((win[3] - gt[0]) / gt[1]))
    y0 = int(np.floor((win[1] - gt[3]) / gt[5]))   # lat_max -> smallest row
    y1 = int(np.ceil((win[0] - gt[3]) / gt[5]))
    x0, y0 = max(x0, 0), max(y0, 0)
    x1, y1 = min(x1, vrt.RasterXSize), min(y1, vrt.RasterYSize)
    a = vrt.ReadAsArray(x0, y0, x1 - x0, y1 - y0)
    sub_gt = (gt[0] + x0 * gt[1], gt[1], 0.0, gt[3] + y0 * gt[5], 0.0, gt[5])
    del vrt
    return a, sub_gt


# --------------------------------------------------------------- delineation
def trace_basin(dirs, oy, ox):
    """Reverse D8 walk: every pixel draining to (oy, ox)."""
    ny, nx = dirs.shape
    mask = np.zeros((ny, nx), dtype=bool)
    mask[oy, ox] = True
    stack = [(oy, ox)]
    inflow = [(dy, dx, v) for v, (dy, dx) in D8_OFFSET.items()]
    while stack:
        y, x = stack.pop()
        for dy, dx, v in inflow:
            yy, xx = y - dy, x - dx      # (yy,xx) flows into (y,x) iff dirs[yy,xx] == v
            if 0 <= yy < ny and 0 <= xx < nx and not mask[yy, xx] and dirs[yy, xx] == v:
                mask[yy, xx] = True
                stack.append((yy, xx))
    return mask


def haversine(lat1, lon1, lat2, lon2):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp, dl = p2 - p1, np.radians(lon2 - lon1)
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * EARTH_R * np.arcsin(np.sqrt(a))


# ------------------------------------------------------------------ NetCDF out
def write_nc(path, var, data, lats, lons, units="", long_name=""):
    ds = nc.Dataset(path, "w", format="NETCDF4")
    # lon MUST be variable 0 and lat variable 1: CWatM's loadsetclone reads the
    # clone's coordinates by positional index, not by name.
    ds.createDimension("lon", len(lons))
    ds.createDimension("lat", len(lats))
    lv = ds.createVariable("lon", "f4", ("lon",)); lv[:] = lons; lv.units = "degrees_east"
    tv = ds.createVariable("lat", "f4", ("lat",)); tv[:] = lats; tv.units = "degrees_north"
    fill = -9999.0
    v = ds.createVariable(var, "f4", ("lat", "lon"), fill_value=fill)
    v.units, v.long_name = units, long_name
    out = np.array(data, dtype=np.float32)
    out[~np.isfinite(out)] = fill
    v[:] = out
    ds.close()
    log(f"  wrote {os.path.basename(path):<24} range=[{np.nanmin(data):.4g}, {np.nanmax(data):.4g}]")


def write_dzrel(path, dz, lats, lons):
    ds = nc.Dataset(path, "w", format="NETCDF4")
    ds.createDimension("lon", len(lons))
    ds.createDimension("lat", len(lats))
    lv = ds.createVariable("lon", "f4", ("lon",)); lv[:] = lons; lv.units = "degrees_east"
    tv = ds.createVariable("lat", "f4", ("lat",)); tv[:] = lats; tv.units = "degrees_north"
    for name, arr in dz.items():
        v = ds.createVariable(name, "f4", ("lat", "lon"), fill_value=-9999.0)
        v.units = "m"
        v.long_name = f"elevation above cell minimum at cumulative area percentile {name[5:]}"
        a = np.array(arr, dtype=np.float32)
        a[~np.isfinite(a)] = -9999.0
        v[:] = a
    ds.close()
    log(f"  wrote {os.path.basename(path):<24} ({len(dz)} percentile levels)")


# --------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gauge_lon", type=float, required=True)
    ap.add_argument("--gauge_lat", type=float, required=True)
    ap.add_argument("--bbox", type=float, nargs=4, required=True,
                    metavar=("LAT_MIN", "LAT_MAX", "LON_MIN", "LON_MAX"))
    ap.add_argument("--res", type=float, required=True)
    ap.add_argument("--merit_dir", required=True)
    ap.add_argument("--esa_lc", required=True)
    ap.add_argument("--expected_area_km2", type=float, default=None)
    ap.add_argument("--snap_window_px", type=int, default=40)
    ap.add_argument("--min_cell_fraction", type=float, default=0.5)
    ap.add_argument("--out_dir", required=True)
    a = ap.parse_args()

    os.makedirs(a.out_dir, exist_ok=True)
    lat_min, lat_max, lon_min, lon_max = a.bbox
    res = a.res

    # Delineate on a window one coarse cell larger than the model grid so we can
    # detect a basin that spills outside the requested bbox.
    win = (lat_min - res, lat_max + res, lon_min - res, lon_max + res)

    log("== reading MERIT-Hydro")
    dirs, gt = read_merit(a.merit_dir, "dir", win)
    dirs = dirs.astype(np.int16)          # -9/-1 nodata never match a D8 code
    upa, _ = read_merit(a.merit_dir, "upa", win)
    ny, nx = dirs.shape
    log(f"   fine grid {ny} x {nx} @ {gt[1]*3600:.1f} arcsec")

    flon = gt[0] + (np.arange(nx) + 0.5) * gt[1]
    flat = gt[3] + (np.arange(ny) + 0.5) * gt[5]

    # ---- 1. snap the gauge to the local max of upstream area
    gx = int(np.argmin(np.abs(flon - a.gauge_lon)))
    gy = int(np.argmin(np.abs(flat - a.gauge_lat)))
    w = a.snap_window_px
    sub = upa[gy - w:gy + w + 1, gx - w:gx + w + 1]
    dy, dx = np.unravel_index(np.nanargmax(sub), sub.shape)
    oy, ox = gy - w + dy, gx - w + dx
    upa_outlet = float(upa[oy, ox])
    log(f"== gauge ({a.gauge_lon}, {a.gauge_lat}) snapped to "
        f"({flon[ox]:.5f}, {flat[oy]:.5f})  MERIT upa = {upa_outlet:,.0f} km2")

    # ---- 2. fine-scale basin
    log("== tracing 3-arcsec basin")
    basin = trace_basin(dirs, oy, ox)
    fine_area = (111320.0 * abs(gt[1])) * (111320.0 * abs(gt[1]) * np.cos(np.radians(flat)))
    area_fine_km2 = float((basin * fine_area[:, None]).sum() / 1e6)
    log(f"   {basin.sum():,} pixels   traced area = {area_fine_km2:,.0f} km2")
    ys, xs = np.nonzero(basin)
    log(f"   basin extent lat {flat[ys.max()]:.3f}..{flat[ys.min()]:.3f}  "
        f"lon {flon[xs.min()]:.3f}..{flon[xs.max()]:.3f}")
    if ys.min() < 2 or ys.max() > ny - 3 or xs.min() < 2 or xs.max() > nx - 3:
        sys.exit("basin touches the delineation window edge — widen --bbox")

    # ---- 3. coarse grid + per-cell binning
    lats = np.arange(lat_max - res / 2, lat_min, -res)          # N -> S
    lons = np.arange(lon_min + res / 2, lon_max, res)           # W -> E
    nlat, nlon = len(lats), len(lons)
    log(f"== coarse grid {nlat} x {nlon} @ {res} deg")

    ri = np.floor((lat_max - flat) / res).astype(np.int64)
    ci = np.floor((flon - lon_min) / res).astype(np.int64)
    inside = ((ri[:, None] >= 0) & (ri[:, None] < nlat) &
              (ci[None, :] >= 0) & (ci[None, :] < nlon))
    cid = np.where(inside, ri[:, None] * nlon + ci[None, :], -1)

    sel = basin & (cid >= 0)
    if sel.sum() < basin.sum():
        log(f"   WARNING {basin.sum() - sel.sum():,} basin pixels fall outside the bbox")

    scid = cid[sel]
    counts = np.bincount(scid, minlength=nlat * nlon).astype(float)
    # pixels per coarse cell (lat-independent because both grids are regular in degrees)
    ppc = (res / abs(gt[1])) ** 2
    frac = (counts / ppc).reshape(nlat, nlon)

    elv, _ = read_merit(a.merit_dir, "elv", win)
    elv = np.where(elv > -9000, elv, np.nan)
    selv = elv[sel]
    good = np.isfinite(selv)
    s1 = np.bincount(scid[good], weights=selv[good], minlength=nlat * nlon)
    s2 = np.bincount(scid[good], weights=selv[good] ** 2, minlength=nlat * nlon)
    n1 = np.bincount(scid[good], minlength=nlat * nlon).astype(float)
    with np.errstate(invalid="ignore", divide="ignore"):
        dem = (s1 / n1).reshape(nlat, nlon)
        std = np.sqrt(np.maximum(s2 / n1 - (s1 / n1) ** 2, 0.0)).reshape(nlat, nlon)
    std = np.clip(std, 0.1, None)

    # dzRel: elevation above the cell minimum at cumulative-area percentiles
    pcts = [1, 5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    dz = {f"dzRel{p:04d}": np.full((nlat, nlon), np.nan) for p in pcts}
    order = np.argsort(scid[good], kind="stable")
    cid_s, elv_s = scid[good][order], selv[good][order]
    bounds = np.searchsorted(cid_s, np.arange(nlat * nlon + 1))
    for c in range(nlat * nlon):
        lo, hi = bounds[c], bounds[c + 1]
        if hi - lo < 1:
            continue
        e = np.sort(elv_s[lo:hi])
        base = e[0]
        for p in pcts:
            dz[f"dzRel{p:04d}"][c // nlon, c % nlon] = np.percentile(e, p) - base
    del elv, selv, s1, s2, cid_s, elv_s

    # cell outlet pixel = basin pixel of maximum upa (upa increases downstream,
    # so this is the last pixel before the flow leaves the cell)
    supa = upa[sel]
    fidx = np.flatnonzero(sel.ravel())
    o = np.lexsort((supa, scid))
    cid_o, fidx_o = scid[o], fidx[o]
    last = np.searchsorted(cid_o, np.arange(nlat * nlon + 1))[1:] - 1
    outlet_px = np.full(nlat * nlon, -1, dtype=np.int64)
    has = counts > 0
    outlet_px[has] = fidx_o[last[has]]
    del supa, fidx, cid_o, fidx_o, o

    # ---- 4. coarse LDD by tracing the fine flow path out of each cell
    gauge_cell = int(ri[oy] * nlon + ci[ox])
    ldd = np.zeros(nlat * nlon, dtype=np.int16)
    upa_c = np.full(nlat * nlon, np.nan)
    elv_out = np.full(nlat * nlon, np.nan)
    elv_full, _ = read_merit(a.merit_dir, "elv", win)

    for c in np.flatnonzero(has):
        p = int(outlet_px[c])
        y, x = p // nx, p % nx
        upa_c[c] = upa[y, x]
        elv_out[c] = elv_full[y, x]
        if c == gauge_cell:
            ldd[c] = 5
            continue
        cy, cx = y, x
        for _ in range(20000):
            d = int(dirs[cy, cx])
            if d not in D8_OFFSET:
                ldd[c] = 5          # river mouth / inland depression
                break
            ddy, ddx = D8_OFFSET[d]
            cy, cx = cy + ddy, cx + ddx
            if not (0 <= cy < ny and 0 <= cx < nx):
                ldd[c] = 5
                break
            c2 = int(cid[cy, cx])
            if c2 != c:
                if c2 < 0:
                    ldd[c] = 5
                else:
                    dr, dc = c2 // nlon - c // nlon, c2 % nlon - c % nlon
                    ldd[c] = PCR_CODE.get((int(np.sign(dr)), int(np.sign(dc))), 5)
                break
        else:
            ldd[c] = 5
    del elv_full, upa, dirs

    def downstream(c):
        code = int(ldd[c])
        if code == 5:
            return -1
        dr, dc = next(k for k, v in PCR_CODE.items() if v == code)
        r, cc = c // nlon + dr, c % nlon + dc
        if not (0 <= r < nlat and 0 <= cc < nlon):
            return -1
        return r * nlon + cc

    # ---- 5. mask: fraction >= threshold, closed under LDD, pruned to the outlet
    S = set(np.flatnonzero(frac.ravel() >= a.min_cell_fraction).tolist())
    S.add(gauge_cell)
    changed = True
    while changed:
        changed = False
        for c in list(S):
            d = downstream(c)
            if d >= 0 and d not in S and counts[d] > 0:
                S.add(d)
                changed = True

    keep = set()
    for c in S:
        path, cur = [], c
        while cur >= 0 and cur not in keep and cur != gauge_cell and len(path) < nlat * nlon:
            path.append(cur)
            cur = downstream(cur)
        if cur == gauge_cell or cur in keep:
            keep.update(path)
            keep.add(gauge_cell)
    dropped = len(S) - len(keep)
    if dropped:
        log(f"   pruned {dropped} coarse cells that do not drain to the gauge cell")

    mask = np.zeros(nlat * nlon, dtype=bool)
    mask[list(keep)] = True
    ldd[~mask] = 0
    ldd[gauge_cell] = 5
    mask2 = mask.reshape(nlat, nlon)

    cell_area = (np.radians(res) ** 2 * EARTH_R ** 2 *
                 np.abs(np.cos(np.radians(lats))))[:, None] * np.ones((1, nlon))
    area_coarse = float((cell_area * mask2).sum() / 1e6)
    log(f"== coarse mask {mask.sum()} cells   area = {area_coarse:,.0f} km2")
    if a.expected_area_km2:
        for lbl, v in (("MERIT upa at outlet", upa_outlet),
                       ("fine traced basin", area_fine_km2),
                       ("coarse mask", area_coarse)):
            log(f"   {lbl:<22} {v:12,.0f} km2   ({100*(v/a.expected_area_km2-1):+.2f}% vs expected)")

    # ---- 6. channel geometry
    wth, _ = read_merit(a.merit_dir, "wth", win)
    swth = wth[sel]
    chan = np.full(nlat * nlon, np.nan)
    okw = np.isfinite(swth) & (swth > 0)
    sw = np.bincount(scid[okw], weights=swth[okw], minlength=nlat * nlon)
    nw = np.bincount(scid[okw], minlength=nlat * nlon).astype(float)
    with np.errstate(invalid="ignore", divide="ignore"):
        chan = sw / nw
    # cells with no MERIT river pixel: hydraulic-geometry fallback on upstream area
    fb = ~np.isfinite(chan) & has
    chan[fb] = np.clip(1.5885 * np.sqrt(np.maximum(upa_c[fb], 1.0)), 5.0, None)
    chan = np.clip(chan, 5.0, None)
    del wth, swth

    depth = np.clip(0.27 * chan ** 0.545, 0.5, 30.0)
    man = 0.025 + 0.015 * np.minimum(50.0 / np.maximum(upa_c, 1.0), 1.0)

    length = np.full(nlat * nlon, np.nan)
    grad = np.full(nlat * nlon, np.nan)
    for c in np.flatnonzero(mask):
        d = downstream(c)
        if d < 0 or not mask[d]:
            # outlet cell: use the cell's own diagonal as the residual reach length
            length[c] = haversine(lats[c // nlon] - res / 2, lons[c % nlon] - res / 2,
                                  lats[c // nlon] + res / 2, lons[c % nlon] + res / 2)
            grad[c] = 1e-4
            continue
        length[c] = haversine(lats[c // nlon], lons[c % nlon],
                              lats[d // nlon], lons[d % nlon])
        grad[c] = max((elv_out[c] - elv_out[d]) / length[c], 1e-4)

    # ---- 7. land-cover fractions from the 0.1 deg ESA-CCI-LC map
    lc = gdal.Open(a.esa_lc)
    lgt = lc.GetGeoTransform()
    lx0 = int(np.floor((lon_min - lgt[0]) / lgt[1]))
    lx1 = int(np.ceil((lon_max - lgt[0]) / lgt[1]))
    ly0 = int(np.floor((lat_max - lgt[3]) / lgt[5]))
    ly1 = int(np.ceil((lat_min - lgt[3]) / lgt[5]))
    cls = lc.GetRasterBand(1).ReadAsArray(lx0, ly0, lx1 - lx0, ly1 - ly0)
    clon = lgt[0] + (np.arange(lx0, lx1) + 0.5) * lgt[1]
    clat = lgt[3] + (np.arange(ly0, ly1) + 0.5) * lgt[5]
    lri = np.floor((lat_max - clat) / res).astype(np.int64)
    lci = np.floor((clon - lon_min) / res).astype(np.int64)
    lok = ((lri[:, None] >= 0) & (lri[:, None] < nlat) &
           (lci[None, :] >= 0) & (lci[None, :] < nlon))
    lcid = np.where(lok, lri[:, None] * nlon + lci[None, :], -1)
    vc, vv = lcid[lok], cls[lok]
    ntot = np.bincount(vc, minlength=nlat * nlon).astype(float)

    def frac_of(codes):
        hit = np.isin(vv, list(codes))
        n = np.bincount(vc[hit], minlength=nlat * nlon).astype(float)
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.where(ntot > 0, n / np.maximum(ntot, 1), 0.0)

    f_for, f_pad = frac_of(LC_FOREST), frac_of(LC_IRR_PADDY)
    f_non, f_sea, f_wat = frac_of(LC_IRR_NONPADDY), frac_of(LC_SEALED), frac_of(LC_WATER)
    f_gra = np.clip(1.0 - (f_for + f_pad + f_non + f_sea + f_wat), 0.0, 1.0)

    # ---- 8. write
    log("== writing static stack")
    R = lambda v: np.where(mask2, v.reshape(nlat, nlon), np.nan)
    write_nc(f"{a.out_dir}/MaskMap.nc", "MaskMap", mask2.astype(float), lats, lons,
             "-", "Active cell mask (1=basin)")
    write_nc(f"{a.out_dir}/Ldd.nc", "Ldd", R(ldd.astype(float)), lats, lons,
             "-", "Local drain direction (PCRaster: 5=pit)")
    write_nc(f"{a.out_dir}/dem.nc", "dem", np.where(mask2, dem, np.nan), lats, lons,
             "m", "Elevation above sea level")
    write_nc(f"{a.out_dir}/ElevationStD.nc", "ElevationStD", np.where(mask2, std, np.nan),
             lats, lons, "m", "Elevation standard deviation per cell")
    write_nc(f"{a.out_dir}/CellArea.nc", "CellArea", np.where(mask2, cell_area, np.nan),
             lats, lons, "m2", "Grid cell area")
    write_nc(f"{a.out_dir}/chanGrad.nc", "chanGrad", R(grad), lats, lons, "-", "Channel gradient")
    write_nc(f"{a.out_dir}/chanLength.nc", "chanLength", R(length), lats, lons, "m", "Channel length")
    write_nc(f"{a.out_dir}/chanWidth.nc", "chanWidth", R(chan), lats, lons, "m", "Bankfull channel width")
    write_nc(f"{a.out_dir}/chanDepth.nc", "chanDepth", R(depth), lats, lons, "m", "Bankfull channel depth")
    write_nc(f"{a.out_dir}/chanMan.nc", "chanMan", R(man), lats, lons, "s m-1/3", "Manning roughness")
    for name, v in (("fractionForest", f_for), ("fractionGrassland", f_gra),
                    ("fractionIrrPaddy", f_pad), ("fractionIrrNonPaddy", f_non),
                    ("fractionSealed", f_sea), ("fractionWater", f_wat)):
        write_nc(f"{a.out_dir}/{name}.nc", name, R(v), lats, lons, "-", name)
    write_dzrel(f"{a.out_dir}/relativeElevation.nc",
                {k: np.where(mask2, v, np.nan) for k, v in dz.items()}, lats, lons)

    meta = {
        "gauge": [a.gauge_lon, a.gauge_lat],
        "gauge_cell": [gauge_cell // nlon, gauge_cell % nlon],
        "gauge_cell_centre": [float(lons[gauge_cell % nlon]), float(lats[gauge_cell // nlon])],
        "snapped_pixel": [float(flon[ox]), float(flat[oy])],
        "res": res, "nlat": nlat, "nlon": nlon, "bbox": list(a.bbox),
        "n_cells": int(mask.sum()),
        "area_km2": area_coarse,
        "area_fine_km2": area_fine_km2,
        "upa_outlet_km2": upa_outlet,
        "expected_area_km2": a.expected_area_km2,
    }
    with open(f"{a.out_dir}/static_meta.json", "w") as fh:
        json.dump(meta, fh, indent=2)
    log(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
