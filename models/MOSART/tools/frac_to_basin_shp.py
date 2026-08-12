#!/usr/bin/env python3
"""Emit a basin-boundary shapefile from a delineated Lohmann `<STA>_frac.txt`.

Why this exists
---------------
SKILL.md documents MOSART as the SECOND stage of a VIC->MOSART pipeline: you
must first run the VIC KI over the basin to get gridded runoff, then route it
here. `delineate_d8_from_merit.py` produces the routing triplet
(direc/xmask/frac) that defines the MOSART domain -- but the VIC KI's stage-1
tool (`s1_grid/make_basin_grid_nc.py`) is driven by a basin SHAPEFILE
(`VIC_BASIN_SHP`), not by an ArcASCII mask. Nothing in either KI bridged the
two, so the VIC domain and the MOSART domain had to be reconciled by hand --
which is exactly how the 2026-07-11 Wangjiaba run ended up routing over a
domain covering only 52% of the published basin area.

This tool closes that gap: frac (the authoritative delineated mask) -> the
shapefile VIC stage 1 consumes, so both stages provably cover the SAME cells.

Edge-touching trap
------------------
`make_basin_grid_nc.py` sets `USE_INTERSECTS = True`, so a cell whose boundary
merely TOUCHES the polygon is counted as in-basin. The exact union of active
cell boxes shares edges with every orthogonal neighbour, which would inflate
the VIC domain by a one-cell halo. Each cell box is therefore shrunk by
`--shrink` (a fraction of the cell size) before dissolving, so `intersects`
selects exactly the active cells and no more. `--shrink` is therefore required
to satisfy `0 < shrink < 0.5`: a non-positive inset would restore the halo and
silently push the VIC domain outside `frac > 0`, and >= 0.5 collapses the boxes.
"""
import argparse
import sys

import numpy as np


def read_arcascii(path):
    """Return (header dict, 2-D array). ArcASCII row 0 is the NORTHERNMOST row."""
    with open(path) as f:
        lines = f.readlines()
    hdr = {}
    n = 0
    for line in lines:
        parts = line.split()
        if len(parts) == 2 and parts[0].lower() in (
                'ncols', 'nrows', 'xllcorner', 'yllcorner', 'cellsize',
                'nodata_value'):
            hdr[parts[0].lower()] = float(parts[1])
            n += 1
        else:
            break
    arr = np.loadtxt(lines[n:])
    if arr.shape != (int(hdr['nrows']), int(hdr['ncols'])):
        raise SystemExit(
            f"[frac2shp] FAIL: {path} body is {arr.shape}, header declares "
            f"({int(hdr['nrows'])}, {int(hdr['ncols'])})")
    return hdr, arr


def active_cells(hdr, frac):
    """Active (frac > 0) cell centres as a list of (lat, lon)."""
    nrows, ncols = int(hdr['nrows']), int(hdr['ncols'])
    cs, xll, yll = hdr['cellsize'], hdr['xllcorner'], hdr['yllcorner']
    cells = []
    for i in range(nrows):
        lat = yll + (nrows - 1 - i + 0.5) * cs      # row 0 = north
        for j in range(ncols):
            if frac[i, j] > 0:
                cells.append((lat, xll + (j + 0.5) * cs))
    return cells, cs


def main():
    ap = argparse.ArgumentParser(
        description='Delineated Lohmann frac ArcASCII -> basin shapefile for '
                    'the VIC KI stage-1 grid builder (VIC_BASIN_SHP)')
    ap.add_argument('--frac', required=True, help='<STA>_frac.txt')
    ap.add_argument('--output', required=True, help='output .shp path')
    ap.add_argument('--shrink', type=float, default=0.02,
                    help='inset each cell box by this fraction of the cell '
                         'size before dissolving, so that the VIC grid '
                         "builder's `intersects` test does not pull in a "
                         'one-cell halo of edge-touching neighbours; must '
                         'satisfy 0 < shrink < 0.5 (default 0.02)')
    ap.add_argument('--dissolve', action='store_true', default=True,
                    help='dissolve cell boxes into a single geometry '
                         '(default on)')
    args = ap.parse_args()

    # A non-positive inset leaves the exact union of cell boxes, whose shared
    # edges make USE_INTERSECTS=True select a one-cell halo OUTSIDE frac>0 --
    # silently breaking the "both stages cover the same cells" guarantee this
    # tool exists to provide. >= 0.5 collapses the boxes to nothing.
    if not (0.0 < args.shrink < 0.5):
        raise SystemExit(
            f"[frac2shp] FAIL: --shrink {args.shrink} is out of range; "
            f"require 0 < shrink < 0.5. A shrink <= 0 leaves cell boxes "
            f"edge-touching, and the VIC grid builder's USE_INTERSECTS=True "
            f"would then select a one-cell halo of cells with frac == 0.")

    try:
        import geopandas as gpd
        from shapely.geometry import box
        from shapely.ops import unary_union
    except ImportError as e:  # pragma: no cover
        raise SystemExit(f"[frac2shp] FAIL: needs geopandas/shapely ({e})")

    hdr, frac = read_arcascii(args.frac)
    cells, cs = active_cells(hdr, frac)
    if not cells:
        raise SystemExit(f"[frac2shp] FAIL: no active (frac>0) cells in "
                         f"{args.frac}")

    d = args.shrink * cs
    boxes = [box(lon - cs / 2 + d, lat - cs / 2 + d,
                 lon + cs / 2 - d, lat + cs / 2 - d) for lat, lon in cells]
    geom = unary_union(boxes) if args.dissolve else boxes

    gdf = gpd.GeoDataFrame(
        {'name': ['basin']} if args.dissolve else
        {'name': [f'cell_{i}' for i in range(len(boxes))]},
        geometry=[geom] if args.dissolve else boxes, crs='EPSG:4326')
    import os
    parent = os.path.dirname(os.path.abspath(args.output))
    os.makedirs(parent, exist_ok=True)
    gdf.to_file(args.output)

    lats = [c[0] for c in cells]
    lons = [c[1] for c in cells]
    print(f"[frac2shp] {len(cells)} active cells from {args.frac}")
    print(f"[frac2shp] extent lat {min(lats):.4f}..{max(lats):.4f}  "
          f"lon {min(lons):.4f}..{max(lons):.4f}  cellsize {cs}")
    print(f"[frac2shp] wrote {args.output} (shrink={args.shrink} of cell)")
    return 0


if __name__ == '__main__':
    sys.exit(main())
