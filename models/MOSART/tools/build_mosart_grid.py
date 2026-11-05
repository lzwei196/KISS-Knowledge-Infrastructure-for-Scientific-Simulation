#!/usr/bin/env python3
"""Build a mosartwmpy domain grid NetCDF from a D8 flow-direction network.

THE MISSING GRID-BUILDER (added 2026-07-11, MOSART @ 唐乃亥/Tangnaihai, Yellow R).

Two prior real-case runs (Bengbu 2026-06-22, Bow@Banff 2026-06-21) failed for the
SAME reason: mosartwmpy needs a domain grid with a full river-network topology
(ID / dnID / channel geometry) that routes to the gauge cell, and the KI had NO
tool to build one. `convert_grid_parameters.py` only *validates* an existing grid;
the synthetic D8 the dissection produced over-accumulated and routed the main
channel away from the gauge, so discharge at the gauge cell was exactly 0.

This tool closes that gap. It converts a D8 flow-direction network in the
Lohmann ArcInfo-ASCII form — `*_direc.txt` (+ `*_xmask.txt` channel length,
`*_frac.txt` drainage fraction), as written by `tools/delineate_d8_from_merit.py`
from MERIT Hydro — into a mosartwmpy grid domain file with all 20
REQUIRED_VARIABLES. The delineator gates the network on the published drainage
area of the gauge, so the main channel reaches the gauge outlet cell — the exact
property the Bengbu synthetic grid lacked.

Direction convention (Lohmann `rout`): 1=N 2=NE 3=E 4=SE 5=S 6=SW 7=W 8=NW,
0=outside-basin, -88 (or any non-1..8 with frac>0) = basin outlet (dnID=-1).

Cell elevation comes straight from a DEM (--dem): the mean of the DEM pixels whose
centres fall inside each grid cell (China 90 m DEM
`data/dem/china_dem_90m/china_dem_90m.tif` inside China, MERIT DEM tiles
`KISSPATH_DATA/MERIT_DEM/` elsewhere). An ACTIVE cell with no DEM value stops the
tool — there is no basin-mean fill. The DEM is read with `rasterio` if installed,
else GDAL's `osgeo.gdal`; with neither, the tool stops at start-up with an
install hint (KISSPATH_PYTHON_ENV/bin/python has both).

Channel geometry is derived by downstream-area hydraulic-geometry relations
consistent with the validated-format Bengbu grid:
    rwid  = max(30, 2.7*sqrt(A_km2))          rwid0 = 5*rwid
    rdep  = max(1.0, 0.28*A_km2**0.39)         twid  = 0.3*rwid
    rlen  = per-cell channel length from xmask (falls back to cell N-S length)
    rslp  = max(1e-4, drop-to-downstream / rlen)   from per-cell mean DEM elevation
    hslp  = max(5e-3, local elevation gradient)     tslp = max(1e-4, rslp)
    nh=0.15  nt=0.05  nr=0.035  gxr=1e-3       (Bengbu-consistent Manning/density)

Usage:
    python build_mosart_grid.py \
        --direc TNH_direc.txt --xmask TNH_xmask.txt --frac TNH_frac.txt \
        --dem KISSPATH_STATIC/china_dem_90m/china_dem_90m.tif \
        --output mosart_grid.nc
"""

import argparse
import os
import sys
from pathlib import Path

# DEM reader: rasterio if installed, else GDAL. Chosen HERE, before numpy /
# xarray load: on this server osgeo's _gdal fails with "cannot allocate memory
# in static TLS block" once xarray/netCDF4 is already imported.
try:
    import rasterio  # noqa: F401
    _DEM_BACKEND = 'rasterio'
except ImportError:
    try:
        from osgeo import gdal, osr  # noqa: F401
        _DEM_BACKEND = 'gdal'
    except ImportError:
        _DEM_BACKEND = None

import numpy as np
import xarray as xr

RADIUS_EARTH = 6.37122e6  # m (mosartwmpy Parameters.radius_earth)

# Lohmann direction code -> (d_i, d_j) in an ASCENDING-latitude mesh
# (i = latitude index increasing north, j = longitude index increasing east).
DIR_OFFSET = {
    1: (+1, 0),   # N
    2: (+1, +1),  # NE
    3: (0, +1),   # E
    4: (-1, +1),  # SE
    5: (-1, 0),   # S
    6: (-1, -1),  # SW
    7: (0, -1),   # W
    8: (+1, -1),  # NW
}


def read_ascii_grid(path):
    """Read an ArcInfo ASCII grid. Returns (array[nrows,ncols] top->bottom, header)."""
    hdr = {}
    data = []
    with open(path) as f:
        for line in f:
            parts = line.split()
            if not parts:
                continue
            key = parts[0].lower()
            if key in ('ncols', 'nrows'):
                hdr[key] = int(parts[1])
            elif key in ('xllcorner', 'yllcorner', 'cellsize', 'nodata_value'):
                hdr[key] = float(parts[1])
            else:
                data.append([float(x) for x in parts])
    arr = np.array(data, dtype=float)
    assert arr.shape == (hdr['nrows'], hdr['ncols']), \
        f"{path}: parsed {arr.shape} != header {(hdr['nrows'], hdr['ncols'])}"
    return arr, hdr


def to_ascending(arr):
    """Flip a top->bottom ASCII grid to ascending-latitude (row 0 = south)."""
    return arr[::-1, :].copy()


def cell_area_m2(lat_deg, cellsize):
    """Area of a cellsize x cellsize lat/lon cell centred at lat_deg (m^2)."""
    dlat = np.deg2rad(cellsize)
    dy = dlat * RADIUS_EARTH
    dx = np.deg2rad(cellsize) * RADIUS_EARTH * np.cos(np.deg2rad(lat_deg))
    return dx * dy


def dem_files(dem_args):
    """Expand --dem arguments: a raster file, or a directory of *.tif tiles."""
    files = []
    for a in dem_args:
        p = Path(a)
        if p.is_dir():
            files += sorted(str(f) for f in p.glob('*.tif'))
        elif p.is_file():
            files.append(str(p))
        else:
            raise SystemExit(f"[build_grid] --dem path not found: {a}")
    if not files:
        raise SystemExit(f"[build_grid] no DEM raster found in {dem_args}")
    return files


def dem_reader_backend():
    """Pick the raster library used to read --dem: 'rasterio' or 'gdal'.

    Either one reads the same pixels; neither importable is a hard error (no
    made-up elevations). Called from main() BEFORE any work so a missing
    dependency fails fast with an install hint, not a mid-run traceback.
    """
    if _DEM_BACKEND is None:
        raise SystemExit(
            "[build_grid] reading --dem needs a raster library, but neither "
            "'rasterio' nor GDAL's 'osgeo.gdal' imports in this Python "
            f"({sys.executable}). Install one (pip install rasterio), or run "
            "with KISSPATH_PYTHON_ENV/bin/python.")
    return _DEM_BACKEND


class _DemRaster:
    """Minimal read-only DEM view shared by the rasterio and GDAL backends.

    Exposes: bounds (left, bottom, right, top), transform (a, b, c, d, e, f)
    in rasterio/affine order, height, width, epsg (int or None), crs_text,
    read(r0, r1, c0, c1) -> 1-D float array of valid pixels (nodata removed).
    """

    def __init__(self, path, backend):
        self.path = path
        self.backend = backend
        if backend == 'rasterio':
            import rasterio
            self._src = rasterio.open(path)
            t = self._src.transform
            self.transform = (t.a, t.b, t.c, t.d, t.e, t.f)
            self.height, self.width = self._src.height, self._src.width
            crs = self._src.crs
            self.epsg = crs.to_epsg() if crs is not None else None
            self.crs_text = str(crs)
        else:
            from osgeo import gdal, osr
            gdal.UseExceptions()
            self._src = gdal.Open(path)
            gt = self._src.GetGeoTransform()
            # GDAL (c, a, b, f, d, e) -> affine (a, b, c, d, e, f)
            self.transform = (gt[1], gt[2], gt[0], gt[4], gt[5], gt[3])
            self.height, self.width = self._src.RasterYSize, self._src.RasterXSize
            self._band = self._src.GetRasterBand(1)
            self._nodata = self._band.GetNoDataValue()
            wkt = self._src.GetProjection()
            self.epsg = None
            self.crs_text = wkt or 'None'
            if wkt:
                srs = osr.SpatialReference(wkt=wkt)
                srs.AutoIdentifyEPSG()
                code = srs.GetAuthorityCode(None)
                self.epsg = int(code) if code else None
        a, _, c, _, e, f = self.transform
        self.bounds = (c, f + e * self.height, c + a * self.width, f)

    def read(self, r0, r1, c0, c1):
        if self.backend == 'rasterio':
            arr = self._src.read(1, window=((r0, r1), (c0, c1)), masked=True)
            v = arr.compressed().astype(float)
        else:
            v = self._band.ReadAsArray(c0, r0, c1 - c0, r1 - r0).astype(float).ravel()
            if self._nodata is not None:
                v = v[v != self._nodata]
        return v

    def close(self):
        if self.backend == 'rasterio':
            self._src.close()
        self._src = None
        self._band = None


def dem_cell_means(dem_paths, lat, lon, cs, backend=None):
    """Mean DEM elevation over each cs x cs cell centred at (lat[i], lon[j]).

    A DEM pixel counts for a cell when its CENTRE lies inside the cell. Pixels
    equal to the raster nodata value are ignored. Pass ONE DEM product (one
    file, or non-overlapping tiles of one product); overlapping rasters would
    be counted twice. Returns (mean[nlat,nlon] with NaN where no pixel, count).
    """
    backend = backend or dem_reader_backend()
    nlat, nlon = len(lat), len(lon)
    tot = np.zeros((nlat, nlon))
    cnt = np.zeros((nlat, nlon), dtype=np.int64)
    w_all, e_all = lon[0] - cs / 2, lon[-1] + cs / 2
    s_all, n_all = lat[0] - cs / 2, lat[-1] + cs / 2
    for path in dem_paths:
        src = _DemRaster(path, backend)
        try:
            left, bottom, right, top = src.bounds
            if right <= w_all or left >= e_all or top <= s_all or bottom >= n_all:
                continue
            ta, tb, tc, td, te, tf = src.transform
            if tb != 0 or td != 0 or te >= 0:
                raise SystemExit(f"[build_grid] DEM {path} is not a north-up "
                                 f"lat/lon raster (transform {src.transform})")
            if src.epsg not in (4326, None):
                raise SystemExit(f"[build_grid] DEM {path} CRS {src.crs_text} is not "
                                 f"EPSG:4326; the grid is in lat/lon degrees")
            rx, ry = ta, -te
            for i in range(nlat):
                s0, n0 = lat[i] - cs / 2, lat[i] + cs / 2
                # rows whose pixel centre lies in [s0, n0)
                r0 = max(0, int(np.ceil((tf - n0) / ry - 0.5)))
                r1 = min(src.height, int(np.ceil((tf - s0) / ry - 0.5)))
                if r1 <= r0:
                    continue
                for j in range(nlon):
                    w0, e0 = lon[j] - cs / 2, lon[j] + cs / 2
                    c0 = max(0, int(np.ceil((w0 - tc) / rx - 0.5)))
                    c1 = min(src.width, int(np.ceil((e0 - tc) / rx - 0.5)))
                    if c1 <= c0:
                        continue
                    v = src.read(r0, r1, c0, c1)
                    v = v[np.isfinite(v)]
                    if v.size:
                        tot[i, j] += v.sum()
                        cnt[i, j] += v.size
        finally:
            src.close()
    with np.errstate(invalid='ignore', divide='ignore'):
        mean = np.where(cnt > 0, tot / np.maximum(cnt, 1), np.nan)
    return mean, cnt


def build_grid(direc_path, xmask_path, frac_path, output_path, dem,
               expected_area_km2=None, area_tol=0.10):
    direc_a, H = read_ascii_grid(direc_path)
    xmask_a, _ = read_ascii_grid(xmask_path)
    frac_a, _ = read_ascii_grid(frac_path)

    nlat, nlon = H['nrows'], H['ncols']
    cs = H['cellsize']
    xll, yll = H['xllcorner'], H['yllcorner']

    # Ascending-latitude mesh (row 0 = southernmost), lon ascending.
    lon = xll + (np.arange(nlon) + 0.5) * cs
    lat = yll + (np.arange(nlat) + 0.5) * cs

    direc = to_ascending(direc_a)
    xmask = to_ascending(xmask_a)
    frac = to_ascending(frac_a)

    direc_i = np.rint(direc).astype(int)
    active = (frac > 0) | (np.isin(direc_i, list(DIR_OFFSET))) | (direc_i == -88)

    # Elevations onto the mesh: per-cell mean of the DEM. No fill — an active
    # cell without DEM pixels is a hard error (a made-up elevation would set a
    # made-up channel / hillslope slope).
    dem_paths = dem_files(dem if isinstance(dem, (list, tuple)) else [dem])
    elev, elev_npix = dem_cell_means(dem_paths, lat, lon, cs)
    missing = [(float(lat[i]), float(lon[j]))
               for i, j in zip(*np.where(active & ~np.isfinite(elev)))]
    if missing:
        raise SystemExit(
            f"[build_grid] DEM GAP: {len(missing)} active cell(s) have no DEM "
            f"value in {dem_paths}: {missing[:10]}{' ...' if len(missing) > 10 else ''}. "
            f"Pass a DEM that covers the whole basin (China 90 m DEM inside "
            f"China, MERIT DEM tiles elsewhere); no fill value is used.")
    print(f"[build_grid] DEM elevation: {int(active.sum())} active cells, "
          f"{int(elev_npix[active].min())}-{int(elev_npix[active].max())} DEM "
          f"pixels per cell, elev {np.nanmin(elev[active]):.0f}-"
          f"{np.nanmax(elev[active]):.0f} m (sources: {len(dem_paths)} raster(s))")

    # ID over the full grid (lat-major / C-order flatten), 1-based like NLDAS grids.
    ID = (np.arange(nlat * nlon).reshape(nlat, nlon) + 1).astype(np.int64)

    # Downstream ID from D8
    dnID = np.full((nlat, nlon), -1, dtype=np.int64)
    for i in range(nlat):
        for j in range(nlon):
            d = direc_i[i, j]
            if d in DIR_OFFSET:
                di, dj = DIR_OFFSET[d]
                ii, jj = i + di, j + dj
                if 0 <= ii < nlat and 0 <= jj < nlon and active[ii, jj]:
                    dnID[i, j] = ID[ii, jj]
                else:
                    dnID[i, j] = -1  # flows off the active network -> outlet
            else:
                dnID[i, j] = -1      # -88 / 0 / nodata

    # --- Make the basin outlet a THROUGH-cell, not the terminal ocean sink. ---
    # mosartwmpy reports RIVER_DISCHARGE_OVER_LAND_LIQ = 0 at a dnID==-1 cell (it
    # is treated as an ocean outlet), so the basin discharge would land one cell
    # upstream of the gauge. To score AT the gauge cell, redirect the primary
    # outlet to a steepest-descent INACTIVE neighbour, which becomes the new
    # terminal sink (frac=0, contributes no runoff, only passes flow to ocean).
    # The gauge cell then becomes an ordinary land cell whose channel_outflow IS
    # the basin discharge. (Interior gauges like Tangnaihai are not river mouths;
    # the physical Yellow River continues downstream past the station anyway.)
    outlet_cells = [(i, j) for i in range(nlat) for j in range(nlon)
                    if active[i, j] and dnID[i, j] == -1]
    scoring_cell = None
    scoring_idx = None
    if outlet_cells:
        # primary outlet = the one draining the most cells (fewest own basin exits)
        def n_upstream(i, j):
            return int(np.sum(dnID == ID[i, j]))
        oi, oj = max(outlet_cells, key=lambda c: n_upstream(*c))
        # pick steepest-descent inactive neighbour as the new terminal sink
        best = None
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                if di == 0 and dj == 0:
                    continue
                ii, jj = oi + di, oj + dj
                if 0 <= ii < nlat and 0 <= jj < nlon and not active[ii, jj]:
                    e = elev[ii, jj]
                    if not np.isfinite(e):
                        e = np.inf      # no DEM there: only used if nothing else
                    if best is None or e < best[0]:
                        best = (e, ii, jj)
        sacrificed_km2 = 0.0
        if best is None:
            # Every neighbour is active (a fine-scale delineation such as
            # delineate_d8_from_merit.py gives the cells around the gauge a
            # small basin fraction). Use the active HEADWATER neighbour (no cell
            # drains into it) with the least basin area as the sink: only its own
            # area leaves the gauge total, and the area gate below re-checks it.
            leaf = None
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    if di == 0 and dj == 0:
                        continue
                    ii, jj = oi + di, oj + dj
                    if (0 <= ii < nlat and 0 <= jj < nlon and active[ii, jj]
                            and n_upstream(ii, jj) == 0
                            and np.isfinite(elev[ii, jj])):
                        a_km2 = float(np.clip(frac[ii, jj], 0, 1)
                                      * cell_area_m2(lat[ii], cs)) / 1e6
                        if leaf is None or (a_km2, elev[ii, jj]) < leaf[:2]:
                            leaf = (a_km2, elev[ii, jj], ii, jj)
            if leaf is not None:
                sacrificed_km2, _, si, sj = leaf
                best = (elev[si, sj], si, sj)
                print(f"[build_grid] no inactive neighbour around the outlet; "
                      f"headwater neighbour ({lat[si]:.3f},{lon[sj]:.3f}) becomes "
                      f"the terminal sink, its {sacrificed_km2:,.1f} km2 no longer "
                      f"reaches the gauge")
        if best is not None:
            _, si, sj = best
            active[si, sj] = True          # activate the sink cell
            if not np.isfinite(elev[si, sj]):
                raise SystemExit(
                    f"[build_grid] DEM GAP: terminal sink cell "
                    f"({lat[si]:.3f},{lon[sj]:.3f}) has no DEM value; the gauge "
                    f"cell's channel slope would be made up. Pass a DEM that also "
                    f"covers the cells around the gauge.")
            dnID[si, sj] = -1              # sink drains to ocean
            frac[si, sj] = 0.0             # no runoff generated here
            dnID[oi, oj] = ID[si, sj]      # gauge now flows THROUGH to the sink
            scoring_cell = (float(lat[oi]), float(lon[oj]))
            scoring_idx = (oi, oj)
            print(f"[build_grid] outlet ({lat[oi]:.3f},{lon[oj]:.3f}) -> through-cell; "
                  f"terminal sink at ({lat[si]:.3f},{lon[sj]:.3f})")
        else:
            # The outlet would stay a dnID == -1 ocean cell whose discharge is
            # 0 (triplet T021); recording it as the scoring cell scores zeros.
            raise SystemExit(
                f"[build_grid] NO SINK: outlet ({lat[oi]:.3f},{lon[oj]:.3f}) has "
                f"no inactive neighbour and no active headwater neighbour to "
                f"host the terminal sink, so the gauge cell cannot be a "
                f"through-cell. Pad the direc/xmask/frac triplet with a 1-cell "
                f"0 (NODATA) border and rebuild.")

    # Local area & fractional contributing area
    area = cell_area_m2(lat[:, None] * np.ones((1, nlon)), cs)
    fr = np.clip(frac, 0.0, 1.0)
    local_contrib = area * fr

    # Upstream accumulation following dnID (topological, via id->index map)
    id_to_ij = {int(ID[i, j]): (i, j) for i in range(nlat) for j in range(nlon)}
    # in-degree for Kahn's algorithm
    indeg = np.zeros((nlat, nlon), dtype=int)
    for i in range(nlat):
        for j in range(nlon):
            if active[i, j] and dnID[i, j] > 0:
                di, dj = id_to_ij[int(dnID[i, j])]
                indeg[di, dj] += 1
    areaTotal = local_contrib.copy()
    from collections import deque
    q = deque([(i, j) for i in range(nlat) for j in range(nlon)
               if active[i, j] and indeg[i, j] == 0])
    processed = 0
    while q:
        i, j = q.popleft()
        processed += 1
        if dnID[i, j] > 0:
            di, dj = id_to_ij[int(dnID[i, j])]
            areaTotal[di, dj] += areaTotal[i, j]
            indeg[di, dj] -= 1
            if indeg[di, dj] == 0:
                q.append((di, dj))
    n_active = int(active.sum())
    if processed < n_active:
        print(f"[build_grid] WARNING: accumulation processed {processed}/{n_active} "
              f"active cells — possible cycle in D8 network")

    A_km2 = np.maximum(areaTotal, area) / 1e6

    # --- AREA GATE (added 2026-07-19 after Wangjiaba domain truncation) ---
    # A frac-weighted-coherent network can still be silently TRUNCATED (WJB
    # scored NSE 0.72 on 52% of the published basin). If the caller supplies
    # the published station drainage area, hard-fail unless the accumulated
    # areaTotal at the scoring (gauge) cell matches it. Reference standard:
    # Tangnaihai 123,042 vs published 121,972 km2 (+0.9%).
    if expected_area_km2 is not None:
        if scoring_idx is None:
            raise SystemExit(
                "[build_grid] AREA GATE FAILED: no scoring (gauge) cell was "
                "identified — the D8 network has no active outlet cell "
                "(no active cell with dnID == -1), so the expected-area "
                "check cannot be anchored to the gauge cell. Refusing to "
                "gate on a non-gauge cell's areaTotal (a malformed network "
                "could pass there). Fix the network topology "
                "(tools/delineate_d8_from_merit.py) before scoring.")
        got_km2 = float(areaTotal[scoring_idx]) / 1e6
        rel = abs(got_km2 - expected_area_km2) / expected_area_km2
        print(f"[build_grid] area gate: scoring-cell areaTotal "
              f"{got_km2:,.1f} km2 vs expected {expected_area_km2:,.1f} km2 "
              f"({(got_km2 / expected_area_km2 - 1) * 100:+.2f}%, "
              f"tol {area_tol * 100:.0f}%)")
        if rel > area_tol:
            raise SystemExit(
                f"[build_grid] AREA GATE FAILED: scoring-cell areaTotal "
                f"{got_km2:,.1f} km2 differs from expected "
                f"{expected_area_km2:,.1f} km2 by {rel * 100:.1f}% "
                f"(> {area_tol * 100:.0f}%) — the D8 network is likely "
                f"domain-truncated; re-delineate the full contributing area "
                f"(tools/delineate_d8_from_merit.py) before scoring.")

    # Channel geometry (downstream-area hydraulic geometry, Bengbu-consistent)
    rwid = np.maximum(30.0, 2.7 * np.sqrt(A_km2))
    rwid0 = 5.0 * rwid
    rdep = np.maximum(1.0, 0.28 * A_km2 ** 0.39)
    twid = 0.3 * rwid
    ns_len = np.deg2rad(cs) * RADIUS_EARTH
    rlen = np.where(xmask > 0, xmask, ns_len)

    # Slopes from elevation
    rslp = np.full((nlat, nlon), 1e-4)
    for i in range(nlat):
        for j in range(nlon):
            if active[i, j] and dnID[i, j] > 0:
                di, dj = id_to_ij[int(dnID[i, j])]
                drop = elev[i, j] - elev[di, dj]
                rslp[i, j] = max(1e-4, drop / max(rlen[i, j], 1.0))
    # hillslope slope = local max elevation gradient
    gy, gx = np.gradient(elev, ns_len)
    hslp = np.maximum(5e-3, np.sqrt(gx ** 2 + gy ** 2))
    hslp = np.where(np.isfinite(hslp), hslp, 5e-3)
    tslp = np.maximum(1e-4, rslp)

    nh = np.full((nlat, nlon), 0.15)
    nt = np.full((nlat, nlon), 0.05)
    nr = np.full((nlat, nlon), 0.035)
    gxr = np.full((nlat, nlon), 1e-3)
    fdir = np.where(np.isin(direc_i, list(DIR_OFFSET)), direc_i, 0).astype(np.int64)

    ds = xr.Dataset(
        data_vars=dict(
            ID=(['lat', 'lon'], ID),
            dnID=(['lat', 'lon'], dnID),
            fdir=(['lat', 'lon'], fdir),
            frac=(['lat', 'lon'], fr),
            land_frac=(['lat', 'lon'], fr),
            area=(['lat', 'lon'], area),
            areaTotal=(['lat', 'lon'], areaTotal),
            areaTotal2=(['lat', 'lon'], areaTotal),
            rlen=(['lat', 'lon'], rlen),
            rslp=(['lat', 'lon'], rslp),
            rwid=(['lat', 'lon'], rwid),
            rwid0=(['lat', 'lon'], rwid0),
            rdep=(['lat', 'lon'], rdep),
            twid=(['lat', 'lon'], twid),
            tslp=(['lat', 'lon'], tslp),
            hslp=(['lat', 'lon'], hslp),
            gxr=(['lat', 'lon'], gxr),
            nh=(['lat', 'lon'], nh),
            nt=(['lat', 'lon'], nt),
            nr=(['lat', 'lon'], nr),
            NLDAS_ID=(['lat', 'lon'], ID),
        ),
        coords=dict(lat=lat, lon=lon),
    )
    ds.attrs['created_by'] = 'mosartwmpy KI build_mosart_grid (D8->domain)'
    ds.attrs['direction_source'] = str(direc_path)
    ds.attrs['elevation_source'] = ';'.join(dem_paths) if len(dem_paths) <= 4 \
        else f"{len(dem_paths)} tiles in {Path(dem_paths[0]).parent}"
    ds.attrs['elevation_method'] = 'mean of DEM pixels with centre inside the cell'
    # per-cell elevation (m) used for rslp/hslp, kept for audit
    ds['elev'] = (['lat', 'lon'], np.where(np.isfinite(elev), elev, np.nan))
    ds.attrs['n_active_cells'] = n_active
    if scoring_cell is not None:
        # The gauge/basin-discharge cell to extract with parse_mosart_output.
        ds.attrs['scoring_lat'] = scoring_cell[0]
        ds.attrs['scoring_lon'] = scoring_cell[1]

    # terminal sink(s): active cells with dnID == -1
    sinks = [(float(lat[i]), float(lon[j]))
             for i in range(nlat) for j in range(nlon)
             if active[i, j] and dnID[i, j] == -1]

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    ds.to_netcdf(output_path)
    print(f"[build_grid] {int(active.sum())} active cells, grid {nlat}x{nlon}, "
          f"basin area = {float(areaTotal[active].max())/1e6:,.0f} km^2")
    print(f"[build_grid] scoring (gauge) cell: {scoring_cell}; terminal sinks: {sinks}")
    print(f"[build_grid] written to {output_path}")
    return {'n_active': int(active.sum()),
            'basin_area_km2': float(areaTotal[active].max()) / 1e6,
            'scoring_cell': scoring_cell,
            'sinks': sinks}


def main():
    ap = argparse.ArgumentParser(description='Build mosartwmpy grid from D8 network')
    ap.add_argument('--direc', required=True, help='ArcASCII D8 flow-direction file')
    ap.add_argument('--xmask', required=True, help='ArcASCII channel-length file (m)')
    ap.add_argument('--frac', required=True, help='ArcASCII drainage-fraction file')
    ap.add_argument('--output', required=True, help='Output grid NetCDF')
    ap.add_argument('--dem', required=True, nargs='+',
                    help='DEM raster(s) in EPSG:4326 for per-cell mean elevation: '
                         'a .tif, or a directory of .tif tiles of ONE product '
                         '(China: data/dem/china_dem_90m/china_dem_90m.tif; '
                         'elsewhere: KISSPATH_DATA/MERIT_DEM/)')
    ap.add_argument('--expected-area-km2', type=float, default=None,
                    help='Published station drainage area; if set, hard-fail '
                         'unless scoring-cell areaTotal matches within '
                         '--area-tol (guards against truncated D8 networks)')
    ap.add_argument('--area-tol', type=float, default=0.10,
                    help='Relative tolerance for --expected-area-km2 '
                         '(default 0.10)')
    args = ap.parse_args()
    backend = dem_reader_backend()  # fail fast if no raster library
    print(f'[build_grid] DEM reader: {backend}')
    try:
        build_grid(args.direc, args.xmask, args.frac, args.output,
                   args.dem,
                   expected_area_km2=args.expected_area_km2,
                   area_tol=args.area_tol)
        print('[build_grid] SUCCESS')
        sys.stdout.flush(); sys.stderr.flush()
        os._exit(0)
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f'[build_grid] FAILED: {e}', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
