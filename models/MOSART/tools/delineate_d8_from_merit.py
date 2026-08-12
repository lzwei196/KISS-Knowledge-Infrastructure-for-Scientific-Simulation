#!/usr/bin/env python3
"""Delineate a gauge's FULL contributing area from MERIT Hydro and emit the
VIC/Lohmann ArcASCII triplet (direc / xmask / frac) that build_mosart_grid.py
consumes.

THE MISSING DELINEATOR (added 2026-07-19, MOSART @ 王家坝/Wangjiaba, Huai R).

The 2026-07 china_gaugeflux real-case scored a coherent-but-TRUNCATED network:
the inherited WJB_direc.txt (6x10 cells, yllcorner 31.25) clipped the entire
northern Hong/Ru headwaters, so gauge-cell areaTotal was 15,959 km2 = 52% of
the published 30,600 km2 — a passing NSE on half a basin. No KI tool could
CREATE a D8 network (build_mosart_grid.py only consumes one); this tool closes
that gap and hard-fails unless the delineated frac-weighted area matches the
published station drainage area.

Method (DRT-style hierarchical aggregation):
  1. Mosaic the MERIT Hydro 3-arcsec dir/upa tiles covering --bbox (tiles are
     pixel-CENTER-aligned to integer degrees — each tile's own transform is
     honored; centers sit on multiples of 1/1200 deg).
  2. Snap the gauge to the MERIT pixel whose upa (km2 — NOT m2) best matches
     --published-area-km2, growing the search radius until the relative
     mismatch is within --snap-tol.
  3. Trace the upstream basin mask on MERIT D8 (vectorized reverse-D8 BFS).
  4. Aggregate to --resolution: frac = basin pixel area / cell area; per-cell
     flow direction = trace the cell's max-upa basin pixel downstream on MERIT
     D8 until it enters a neighbouring coarse cell (with cycle repair by
     extending the trace to the next coarse crossing); xmask = center-to-
     center distance to the downstream cell (m), matching the existing
     WJB/TNH xmask convention.
  5. GATE: SystemExit(1) unless sum(frac*cell_area) is within --area-tol of
     --published-area-km2. No silent partial domains.

The gauge coarse cell is written as -88 (basin outlet) per the Lohmann
convention; build_mosart_grid.py's own sink redirection (triplet T021) then
turns it into a THROUGH-cell. This tool must NOT pre-empt that.

MERIT dir encoding: 1=E 2=SE 4=S 8=SW 16=W 32=NW 64=N 128=NE (uint8; 0=river
mouth, 247/255=nodata/inland). Output direc encoding (VIC/Lohmann `rout`):
1=N 2=NE 3=E 4=SE 5=S 6=SW 7=W 8=NW, 0=outside-basin, -88=basin outlet.

Usage:
    python delineate_d8_from_merit.py \
        --merit-dir /mnt/disk1/Hydrocraft_server/data/merit_hydro \
        --gauge-lat 32.43 --gauge-lon 115.60 --published-area-km2 30600 \
        --resolution 0.25 \
        --out-prefix /mnt/disk1/Hydrocraft_server/outputs/vic_wangjiaba_full_domain/WJB_full
"""

import argparse
import math
import sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio.windows import from_bounds

RADIUS_EARTH = 6.37122e6          # m, same constant as build_mosart_grid.py
FINE_RES = 1.0 / 1200.0           # MERIT Hydro 3 arcsec

# MERIT D8 code -> (drow, dcol) in a TOP-DOWN array (row 0 = north)
MERIT_OFFSET = {
    1: (0, 1),     # E
    2: (1, 1),     # SE
    4: (1, 0),     # S
    8: (1, -1),    # SW
    16: (0, -1),   # W
    32: (-1, -1),  # NW
    64: (-1, 0),   # N
    128: (-1, 1),  # NE
}

# (drow, dcol) between coarse cells (TOP-DOWN) -> VIC/Lohmann direction code
LOHMANN_CODE = {
    (-1, 0): 1,   # N
    (-1, 1): 2,   # NE
    (0, 1): 3,    # E
    (1, 1): 4,    # SE
    (1, 0): 5,    # S
    (1, -1): 6,   # SW
    (0, -1): 7,   # W
    (-1, -1): 8,  # NW
}

NODATA_DIR = 255  # fill for pixels outside the mosaic / MERIT nodata


def load_merit_mosaic(merit_dir, bbox):
    """Read dir+upa MERIT tiles intersecting bbox onto one fine grid.

    bbox = (west, south, east, north). Returns (dir_f, upa_f, lats, lons):
    top-down arrays; lats descending, lons ascending (pixel CENTERS, which
    sit on multiples of FINE_RES — MERIT tiles are center-aligned to integer
    degrees).
    """
    west, south, east, north = bbox
    # Fine-grid pixel-center index range (center = index * FINE_RES)
    c0 = int(math.ceil(west / FINE_RES))
    c1 = int(math.floor(east / FINE_RES))
    r0 = int(math.ceil(south / FINE_RES))
    r1 = int(math.floor(north / FINE_RES))
    lons = np.arange(c0, c1 + 1) * FINE_RES
    lats = np.arange(r1, r0 - 1, -1) * FINE_RES  # descending (top-down)
    ncol, nrow = len(lons), len(lats)
    dir_f = np.full((nrow, ncol), NODATA_DIR, dtype=np.uint8)
    upa_f = np.full((nrow, ncol), np.nan, dtype=np.float32)

    tiles = set()
    for lat in (south + 1e-9, north - 1e-9):
        for lon in (west + 1e-9, east - 1e-9):
            tiles.add((int(math.floor(lat / 5.0)) * 5,
                       int(math.floor(lon / 5.0)) * 5))
    n_loaded = 0
    for tlat, tlon in sorted(tiles):
        name = f"{'n' if tlat >= 0 else 's'}{abs(tlat):02d}" \
               f"{'e' if tlon >= 0 else 'w'}{abs(tlon):03d}"
        dpath = Path(merit_dir) / f"{name}_dir.tif"
        upath = Path(merit_dir) / f"{name}_upa.tif"
        if not dpath.exists():
            print(f"[delineate] tile {name} not on disk — skipping "
                  f"(bbox corner outside available tiles?)")
            continue
        with rasterio.open(dpath) as dds, rasterio.open(upath) as uds:
            b = dds.bounds
            iw, ie = max(west, b.left), min(east, b.right)
            is_, in_ = max(south, b.bottom), min(north, b.top)
            if iw >= ie or is_ >= in_:
                continue
            win = from_bounds(iw, is_, ie, in_, dds.transform)
            win = win.round_offsets().round_lengths()
            d = dds.read(1, window=win)
            u = uds.read(1, window=win)
            tr = dds.window_transform(win)
            # center of the window's upper-left pixel
            lon_ul, lat_ul = tr * (0.5, 0.5)
            j0 = int(round(lon_ul / FINE_RES)) - c0
            i0 = r1 - int(round(lat_ul / FINE_RES))
            h, w = d.shape
            si0, sj0 = max(i0, 0), max(j0, 0)
            si1, sj1 = min(i0 + h, nrow), min(j0 + w, ncol)
            if si0 >= si1 or sj0 >= sj1:
                continue
            dir_f[si0:si1, sj0:sj1] = d[si0 - i0:si1 - i0, sj0 - j0:sj1 - j0]
            uu = u[si0 - i0:si1 - i0, sj0 - j0:sj1 - j0].astype(np.float32)
            if uds.nodata is not None:
                uu = np.where(uu == uds.nodata, np.nan, uu)
            upa_f[si0:si1, sj0:sj1] = uu
            n_loaded += 1
            print(f"[delineate] loaded tile {name}: window {d.shape} "
                  f"-> mosaic[{si0}:{si1},{sj0}:{sj1}]")
    if n_loaded == 0:
        raise SystemExit(f"[delineate] FAIL: no MERIT tiles found in "
                         f"{merit_dir} intersecting bbox {bbox}")
    return dir_f, upa_f, lats, lons


def snap_gauge(upa_f, lats, lons, gauge_lat, gauge_lon, published_km2,
               snap_tol):
    """Grow the search radius until a pixel's upa matches published area.

    Memory-proven pattern: 'grow gauge snap radius until MERIT upa matches
    independent area'. MERIT upa is km2 (NOT m2).
    """
    gi = int(np.argmin(np.abs(lats - gauge_lat)))
    gj = int(np.argmin(np.abs(lons - gauge_lon)))
    nrow, ncol = upa_f.shape
    best = None
    for radius_px in (6, 12, 24, 60, 120, 240):
        i0, i1 = max(gi - radius_px, 0), min(gi + radius_px + 1, nrow)
        j0, j1 = max(gj - radius_px, 0), min(gj + radius_px + 1, ncol)
        sub = upa_f[i0:i1, j0:j1]
        rel = np.abs(sub - published_km2) / published_km2
        rel = np.where(np.isnan(rel), np.inf, rel)
        k = int(np.argmin(rel))
        ki, kj = np.unravel_index(k, rel.shape)
        cand = (float(rel[ki, kj]), i0 + ki, j0 + kj)
        if best is None or cand[0] < best[0]:
            best = cand
        print(f"[delineate] snap search r={radius_px}px "
              f"(~{radius_px * FINE_RES * 111:.1f} km): best rel-err "
              f"{best[0] * 100:.2f}% upa={upa_f[best[1], best[2]]:.0f} km2")
        if best[0] <= snap_tol:
            break
    rel_err, si, sj = best
    if rel_err > snap_tol:
        raise SystemExit(
            f"[delineate] FAIL: no MERIT pixel within {snap_tol * 100:.0f}% "
            f"of published {published_km2} km2 near "
            f"({gauge_lat},{gauge_lon}); best {rel_err * 100:.1f}%")
    print(f"[delineate] gauge snapped to ({lats[si]:.5f},{lons[sj]:.5f}) "
          f"upa={upa_f[si, sj]:.1f} km2 (published {published_km2}, "
          f"rel-err {rel_err * 100:.2f}%)")
    return si, sj


def trace_upstream_mask(dir_f, si, sj):
    """Vectorized reverse-D8 BFS: all pixels draining through (si, sj)."""
    nrow, ncol = dir_f.shape
    mask = np.zeros((nrow, ncol), dtype=bool)
    mask[si, sj] = True
    rr = np.array([si], dtype=np.int32)
    cc = np.array([sj], dtype=np.int32)
    it = 0
    while rr.size:
        new_r, new_c = [], []
        for code, (di, dj) in MERIT_OFFSET.items():
            # q flows with `code` into p  <=>  q = p - offset(code)
            qr, qc = rr - di, cc - dj
            ok = (qr >= 0) & (qr < nrow) & (qc >= 0) & (qc < ncol)
            qr, qc = qr[ok], qc[ok]
            sel = (dir_f[qr, qc] == code) & (~mask[qr, qc])
            qr, qc = qr[sel], qc[sel]
            mask[qr, qc] = True
            new_r.append(qr)
            new_c.append(qc)
        rr = np.concatenate(new_r)
        cc = np.concatenate(new_c)
        it += 1
    print(f"[delineate] upstream trace: {int(mask.sum()):,} MERIT pixels "
          f"in {it} BFS sweeps")
    edge = (mask[0, :].any() or mask[-1, :].any() or
            mask[:, 0].any() or mask[:, -1].any())
    if edge:
        raise SystemExit("[delineate] FAIL: basin mask touches the mosaic "
                         "edge — enlarge --bbox, the basin is clipped")
    return mask


def pixel_area_m2(lat_deg):
    d = math.radians(FINE_RES) * RADIUS_EARTH
    return d * d * np.cos(np.deg2rad(lat_deg))


def cell_area_m2(lat_deg, cellsize):
    d = math.radians(cellsize) * RADIUS_EARTH
    return d * d * math.cos(math.radians(lat_deg))


def center_dist_m(lat1, lon1, lat2, lon2):
    dlat = math.radians(lat2 - lat1) * RADIUS_EARTH
    mlat = math.radians((lat1 + lat2) / 2.0)
    dlon = math.radians(lon2 - lon1) * RADIUS_EARTH * math.cos(mlat)
    return math.hypot(dlat, dlon)


def trace_to_coarse_neighbor(dir_f, r, c, cell_of, want_crossings=1,
                             max_steps=200000):
    """Follow MERIT D8 from (r,c); return the want_crossings-th DISTINCT
    coarse cell entered (as (ci,cj)), or None if the trace ends first."""
    start = cell_of(r, c)
    seen = [start]
    steps = 0
    while steps < max_steps:
        code = int(dir_f[r, c])
        if code not in MERIT_OFFSET:
            return None
        di, dj = MERIT_OFFSET[code]
        r, c = r + di, c + dj
        if not (0 <= r < dir_f.shape[0] and 0 <= c < dir_f.shape[1]):
            return None
        cur = cell_of(r, c)
        if cur != seen[-1]:
            seen.append(cur)
            if len(seen) - 1 >= want_crossings:
                return cur
        steps += 1
    return None


def delineate(merit_dir, gauge_lat, gauge_lon, published_km2, resolution,
              bbox, out_prefix, snap_tol, area_tol, min_bbox=None):
    dir_f, upa_f, lats, lons = load_merit_mosaic(merit_dir, bbox)
    si, sj = snap_gauge(upa_f, lats, lons, gauge_lat, gauge_lon,
                        published_km2, snap_tol)
    mask = trace_upstream_mask(dir_f, si, sj)

    px_area = pixel_area_m2(lats)[:, None] * np.ones((1, len(lons)))
    basin_km2 = float((px_area * mask).sum()) / 1e6
    print(f"[delineate] MERIT basin area {basin_km2:,.1f} km2 "
          f"(gauge-pixel upa {upa_f[si, sj]:,.1f} km2)")

    # ---- coarse grid bounds: basin extent + 1-cell pad, 0.25-aligned ----
    mr, mc = np.where(mask)
    blat, blon = lats[mr], lons[mc]
    cs = resolution
    yll = math.floor(blat.min() / cs) * cs - cs
    xll = math.floor(blon.min() / cs) * cs - cs
    yur = math.ceil(blat.max() / cs) * cs + cs
    xur = math.ceil(blon.max() / cs) * cs + cs
    if min_bbox is not None:
        # guarantee the emitted coarse domain covers AT LEAST min_bbox
        # (expand only, never shrink; cells outside the basin stay frac=0)
        mw, ms, me, mn = min_bbox
        xll = min(xll, math.floor(mw / cs + 1e-9) * cs)
        yll = min(yll, math.floor(ms / cs + 1e-9) * cs)
        xur = max(xur, math.ceil(me / cs - 1e-9) * cs)
        yur = max(yur, math.ceil(mn / cs - 1e-9) * cs)
    nrows = int(round((yur - yll) / cs))
    ncols = int(round((xur - xll) / cs))
    print(f"[delineate] coarse grid {nrows}x{ncols} cells, "
          f"bbox {xll}-{xur}E {yll}-{yur}N @ {cs} deg")

    # top-down coarse indices for every basin pixel
    ci = (np.floor((yur - blat) / cs)).astype(int)
    cj = (np.floor((blon - xll) / cs)).astype(int)

    frac = np.zeros((nrows, ncols))
    np.add.at(frac, (ci, cj), px_area[mr, mc])
    cell_lat = yur - (np.arange(nrows) + 0.5) * cs
    cell_lon = xll + (np.arange(ncols) + 0.5) * cs
    carea = np.array([[cell_area_m2(cell_lat[i], cs) for _ in range(ncols)]
                      for i in range(nrows)])
    frac = np.clip(frac / carea, 0.0, 1.0)

    # max-upa basin pixel per coarse cell (the cell's main-channel pixel)
    cellid = ci * ncols + cj
    order = np.lexsort((upa_f[mr, mc], cellid))
    cid_sorted = cellid[order]
    last = np.r_[cid_sorted[1:] != cid_sorted[:-1], True]
    main_px = {int(cid_sorted[k]): (int(mr[order][k]), int(mc[order][k]))
               for k in np.where(last)[0]}

    def cell_of(r, c):
        return (int((yur - lats[r]) // cs), int((lons[c] - xll) // cs))

    gauge_cell = cell_of(si, sj)
    print(f"[delineate] gauge coarse cell (top-down idx) {gauge_cell} "
          f"center ({cell_lat[gauge_cell[0]]:.3f},"
          f"{cell_lon[gauge_cell[1]]:.3f})")

    # ---- per-cell D8 by downstream tracing, with cycle repair ----
    direc = np.zeros((nrows, ncols), dtype=int)
    crossings = {k: 1 for k in main_px}
    active_cells = [k for k in main_px]
    for repair_round in range(10):
        down = {}
        for k in active_cells:
            cell = (k // ncols, k % ncols)
            if cell == gauge_cell:
                continue
            r, c = main_px[k]
            nxt = trace_to_coarse_neighbor(dir_f, r, c, cell_of,
                                           want_crossings=crossings[k])
            if nxt is None:
                raise SystemExit(
                    f"[delineate] FAIL: trace from cell {cell} main pixel "
                    f"ended without reaching another coarse cell")
            dr, dc = nxt[0] - cell[0], nxt[1] - cell[1]
            if (dr, dc) not in LOHMANN_CODE:
                # extended trace skipped past a neighbour; clamp to the
                # adjacent cell in that direction
                dr = max(-1, min(1, dr))
                dc = max(-1, min(1, dc))
                nxt = (cell[0] + dr, cell[1] + dc)
            down[k] = nxt
        # cycle check: every active cell must drain to the gauge cell
        bad = []
        gk = gauge_cell[0] * ncols + gauge_cell[1]
        for k in active_cells:
            cur, hop = k, 0
            while cur != gk and hop <= len(active_cells) + 2:
                nxt = down.get(cur)
                if nxt is None:
                    break
                cur = nxt[0] * ncols + nxt[1]
                hop += 1
            if cur != gk:
                bad.append(k)
        if not bad:
            break
        for k in bad:
            crossings[k] += 1
        print(f"[delineate] cycle repair round {repair_round + 1}: "
              f"{len(bad)} cells re-traced with extended crossing")
    else:
        raise SystemExit("[delineate] FAIL: coarse D8 still cyclic after "
                         "10 repair rounds")

    for k, nxt in down.items():
        cell = (k // ncols, k % ncols)
        direc[cell] = LOHMANN_CODE[(nxt[0] - cell[0], nxt[1] - cell[1])]
    direc[gauge_cell] = -88

    # ---- xmask: center-to-center distance to downstream cell (m) ----
    xmask = np.zeros((nrows, ncols))
    ns_len = math.radians(cs) * RADIUS_EARTH
    for k in main_px:
        cell = (k // ncols, k % ncols)
        if cell == gauge_cell:
            xmask[cell] = ns_len
            continue
        nxt = down[k]
        xmask[cell] = center_dist_m(cell_lat[cell[0]], cell_lon[cell[1]],
                                    cell_lat[nxt[0]], cell_lon[nxt[1]])

    # ---- THE GATE: frac-weighted area vs published ----
    total_km2 = float((frac * carea).sum()) / 1e6
    rel = abs(total_km2 - published_km2) / published_km2
    print(f"[delineate] frac-weighted delineated area {total_km2:,.1f} km2 "
          f"vs published {published_km2:,.1f} km2 "
          f"({(total_km2 / published_km2 - 1) * 100:+.2f}%)")
    if rel > area_tol:
        raise SystemExit(
            f"[delineate] FAIL: delineated area off by {rel * 100:.1f}% "
            f"(> {area_tol * 100:.0f}% tolerance) — refusing to emit a "
            f"partial domain")

    # ---- write ArcASCII triplet ----
    out_prefix = Path(out_prefix)
    out_prefix.parent.mkdir(parents=True, exist_ok=True)

    def write_ascii(path, arr, fmt):
        with open(path, 'w') as f:
            f.write(f"ncols         {ncols}\n"
                    f"nrows         {nrows}\n"
                    f"xllcorner     {xll}\n"
                    f"yllcorner     {yll}\n"
                    f"cellsize      {cs}\n"
                    f"NODATA_value  0\n")
            for i in range(nrows):
                f.write(' '.join(fmt % v for v in arr[i]) + '\n')
        print(f"[delineate] wrote {path}")

    write_ascii(f"{out_prefix}_direc.txt", direc, '%d')
    write_ascii(f"{out_prefix}_xmask.txt", np.rint(xmask).astype(int), '%d')
    write_ascii(f"{out_prefix}_frac.txt", frac, '%.4f')

    n_cells = len(main_px)
    print(f"[delineate] SUCCESS: {n_cells} basin cells, gauge cell center "
          f"({cell_lat[gauge_cell[0]]:.4f},{cell_lon[gauge_cell[1]]:.4f}), "
          f"area {total_km2:,.1f} km2 "
          f"({(total_km2 / published_km2 - 1) * 100:+.2f}% vs published)")
    return {'n_cells': n_cells, 'area_km2': total_km2,
            'gauge_cell': (float(cell_lat[gauge_cell[0]]),
                           float(cell_lon[gauge_cell[1]]))}


def main():
    ap = argparse.ArgumentParser(
        description='Delineate full contributing area from MERIT Hydro -> '
                    'VIC/Lohmann ArcASCII direc/xmask/frac')
    ap.add_argument('--merit-dir', required=True)
    ap.add_argument('--gauge-lat', type=float, required=True)
    ap.add_argument('--gauge-lon', type=float, required=True)
    ap.add_argument('--published-area-km2', type=float, required=True)
    ap.add_argument('--resolution', type=float, default=0.25)
    ap.add_argument('--bbox', default=None,
                    help='west,south,east,north (deg); default: gauge '
                         '+/- generous margin')
    ap.add_argument('--out-prefix', required=True)
    ap.add_argument('--snap-tol', type=float, default=0.10,
                    help='max relative upa-vs-published mismatch at the '
                         'snapped gauge pixel')
    ap.add_argument('--area-tol', type=float, default=0.10,
                    help='max relative frac-weighted-area-vs-published '
                         'mismatch of the emitted domain')
    ap.add_argument('--min-bbox', default=None,
                    help='west,south,east,north (deg): minimum extent the '
                         'emitted coarse ArcASCII domain must cover; the '
                         'grid is expanded (never shrunk) to include it')
    args = ap.parse_args()
    if args.bbox:
        bbox = tuple(float(x) for x in args.bbox.split(','))
    else:
        # generous default: 2 deg south/east, 2.5 deg north, 3.5 deg west of
        # the gauge (headwaters usually lie west/north for east-flowing
        # Chinese rivers; Wangjiaba's Hong/Ru headwaters reach ~34N, 113.2E)
        bbox = (args.gauge_lon - 3.5, args.gauge_lat - 2.0,
                args.gauge_lon + 1.0, args.gauge_lat + 2.5)
    min_bbox = None
    if args.min_bbox:
        min_bbox = tuple(float(x) for x in args.min_bbox.split(','))
    print(f"[delineate] bbox {bbox} min_bbox {min_bbox}")
    delineate(args.merit_dir, args.gauge_lat, args.gauge_lon,
              args.published_area_km2, args.resolution, bbox,
              args.out_prefix, args.snap_tol, args.area_tol,
              min_bbox=min_bbox)


if __name__ == '__main__':
    main()
