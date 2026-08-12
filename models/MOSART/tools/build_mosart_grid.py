#!/usr/bin/env python3
"""Build a mosartwmpy domain grid NetCDF from a D8 flow-direction network.

THE MISSING GRID-BUILDER (added 2026-07-11, MOSART @ 唐乃亥/Tangnaihai, Yellow R).

Two prior real-case runs (Bengbu 2026-06-22, Bow@Banff 2026-06-21) failed for the
SAME reason: mosartwmpy needs a domain grid with a full river-network topology
(ID / dnID / channel geometry) that routes to the gauge cell, and the KI had NO
tool to build one. `convert_grid_parameters.py` only *validates* an existing grid;
the synthetic D8 the dissection produced over-accumulated and routed the main
channel away from the gauge, so discharge at the gauge cell was exactly 0.

This tool closes that gap. It converts a VALIDATED D8 flow-direction network — the
same ArcInfo-ASCII `*_direc.txt` (+ `*_xmask.txt` channel length, `*_frac.txt`
drainage fraction) that the VIC/Lohmann routing KI already builds and validates
(`s5_routing/build_routing_param.py`) — into a mosartwmpy grid domain file with all
20 REQUIRED_VARIABLES. Because the topology is inherited from a routing network that
was independently confirmed at the gauge (VIC+Lohmann NSE 0.63 at Tangnaihai), the
main channel provably reaches the gauge outlet cell — the exact property the Bengbu
synthetic grid lacked.

Direction convention (VIC/Lohmann `rout`): 1=N 2=NE 3=E 4=SE 5=S 6=SW 7=W 8=NW,
0=outside-basin, -88 (or any non-1..8 with frac>0) = basin outlet (dnID=-1).

Channel geometry is derived by downstream-area hydraulic-geometry relations
consistent with the validated-format Bengbu grid:
    rwid  = max(30, 2.7*sqrt(A_km2))          rwid0 = 5*rwid
    rdep  = max(1.0, 0.28*A_km2**0.39)         twid  = 0.3*rwid
    rlen  = per-cell channel length from xmask (falls back to cell N-S length)
    rslp  = max(1e-4, drop-to-downstream / rlen)   from per-cell mean elevation
    hslp  = max(5e-3, local elevation gradient)     tslp = max(1e-4, rslp)
    nh=0.15  nt=0.05  nr=0.035  gxr=1e-3       (Bengbu-consistent Manning/density)

Usage:
    python build_mosart_grid.py \
        --direc TNH_direc.txt --xmask TNH_xmask.txt --frac TNH_frac.txt \
        --elev-soil SOIL_PARAM_COMPLETE.txt --elev-cols 3,4,22 \
        --output mosart_grid.nc
"""

import argparse
import os
import sys
from pathlib import Path

import numpy as np
import xarray as xr

RADIUS_EARTH = 6.37122e6  # m (mosartwmpy Parameters.radius_earth)

# Lohmann/VIC direction code -> (d_i, d_j) in an ASCENDING-latitude mesh
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


def load_elevations(soil_path, cols):
    """Return dict {(round(lat,3), round(lon,3)): elev} from a whitespace table.

    cols = (lat_col, lon_col, elev_col), 1-indexed (VIC soil: 3,4,22).
    """
    lc, oc, ec = [c - 1 for c in cols]
    elev = {}
    for line in open(soil_path):
        p = line.split()
        if len(p) <= max(lc, oc, ec):
            continue
        try:
            lat, lon, e = float(p[lc]), float(p[oc]), float(p[ec])
        except ValueError:
            continue
        elev[(round(lat, 3), round(lon, 3))] = e
    return elev


def build_grid(direc_path, xmask_path, frac_path, output_path,
               elev_soil=None, elev_cols=(3, 4, 22),
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

    # Elevations onto the mesh
    elev = np.full((nlat, nlon), np.nan)
    if elev_soil:
        emap = load_elevations(elev_soil, elev_cols)
        for i in range(nlat):
            for j in range(nlon):
                e = emap.get((round(lat[i], 3), round(lon[j], 3)))
                if e is not None:
                    elev[i, j] = e
    # fill missing active-cell elevations with basin mean
    if np.isfinite(elev[active]).any():
        elev[np.isnan(elev)] = np.nanmean(elev[active])
    else:
        elev[:] = 0.0

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
                    if best is None or e < best[0]:
                        best = (e, ii, jj)
        if best is not None:
            _, si, sj = best
            active[si, sj] = True          # activate the sink cell
            dnID[si, sj] = -1              # sink drains to ocean
            frac[si, sj] = 0.0             # no runoff generated here
            dnID[oi, oj] = ID[si, sj]      # gauge now flows THROUGH to the sink
            scoring_cell = (float(lat[oi]), float(lon[oj]))
            scoring_idx = (oi, oj)
            print(f"[build_grid] outlet ({lat[oi]:.3f},{lon[oj]:.3f}) -> through-cell; "
                  f"terminal sink at ({lat[si]:.3f},{lon[sj]:.3f})")
        else:
            scoring_cell = (float(lat[oi]), float(lon[oj]))
            scoring_idx = (oi, oj)
            print(f"[build_grid] WARNING: no inactive neighbour to host a sink; "
                  f"score basin discharge at the cell UPSTREAM of "
                  f"({lat[oi]:.3f},{lon[oj]:.3f})")

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
    ap.add_argument('--elev-soil', default=None,
                    help='Whitespace table with per-cell elevation (e.g. VIC soil)')
    ap.add_argument('--elev-cols', default='3,4,22',
                    help='1-indexed lat,lon,elev columns in --elev-soil')
    ap.add_argument('--expected-area-km2', type=float, default=None,
                    help='Published station drainage area; if set, hard-fail '
                         'unless scoring-cell areaTotal matches within '
                         '--area-tol (guards against truncated D8 networks)')
    ap.add_argument('--area-tol', type=float, default=0.10,
                    help='Relative tolerance for --expected-area-km2 '
                         '(default 0.10)')
    args = ap.parse_args()
    cols = tuple(int(x) for x in args.elev_cols.split(','))
    try:
        build_grid(args.direc, args.xmask, args.frac, args.output,
                   args.elev_soil, cols,
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
