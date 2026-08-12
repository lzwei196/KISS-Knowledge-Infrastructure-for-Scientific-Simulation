#!/usr/bin/env python3
"""S5 Stream-network builder for DHSVM (Linux-native, replaces arcpy
CreateStreamNetwork_PythonV/createstreamnetwork.py which hard-imports arcpy:18).
Uses pysheds for D8 conditioning + flow accumulation and pyflwdir for stream
segment extraction/topology, then writes the DHSVM triple:
  stream.network.dat  (seg_id class slope length order downstream;
                       fmt '%5d %3d %11.5f %17.5f %3d %7d' per arcpy line 379)
  stream.map.dat      (cell->segment mapping, headered)
  stream.class.dat    (hydraulic-class lookup; default = shipped Chiwawa table)
Not guaranteed to bit-reproduce Chiwawa's 493 segments (threshold-dependent);
success = a format-valid, DHSVM RouteChannel-parseable network.
"""
import argparse, os, numpy as np
# NumPy 2.x removed np.in1d (now np.isin); pysheds<=0.4 still calls np.in1d in
# _d8_accumulation -> AttributeError on numpy>=2.0. Restore the alias before
# importing pysheds so the D8 accumulation path works on this env (numpy 2.4).
if not hasattr(np, 'in1d'):
    np.in1d = np.isin
from pysheds.grid import Grid
import pyflwdir

CLASS_DAT = ("#ID W  D   n    inf\n"
  "1  2.0 0.400 0.0503 0.0\n2  5.0 0.603 0.03   0.0\n3  8.0 0.804 0.03   0.0\n"
  "4  15  1.004 0.03   0.0\n5  20  1.500 0.045  0.0\n6  25  2.000 0.045  0.0\n"
  "7  30  2.500 0.045  0.0\n8  35  3.000 0.045  0.0\n9  40  3.500 0.045  0.0\n"
  "10 45 4.000 0.045  0.0\n")

def classify(order):
    return int(min(max(order, 1), 10))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dem', required=True, help='conditioned/raw DEM GeoTIFF (projected, m)')
    ap.add_argument('--threshold', type=int, default=100,
                    help='min upstream cells to define a channel head')
    ap.add_argument('--outdir', required=True)
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)
    grid = Grid.from_raster(a.dem)
    dem = grid.read_raster(a.dem)
    pit = grid.fill_pits(dem); flo = grid.fill_depressions(pit)
    inflated = grid.resolve_flats(flo)
    fdir = grid.flowdir(inflated)              # default dirmap == ESRI D8 codes
    acc = grid.accumulation(fdir)
    # pysheds marks unresolved flats=-1 and pits=-2; pyflwdir's 'd8' parser only
    # accepts {1,2,4,...,128,0}. Coerce those (and any stray negatives) to 0
    # (pit/outlet) so from_array validates. Without this, valid steep basins
    # raise "flow direction data ... is invalid" and no network is written.
    fdir = np.where(np.asarray(fdir) > 0, np.asarray(fdir), 0).astype(np.uint8)
    flw = pyflwdir.from_array(np.asarray(fdir), ftype='d8',
                              transform=grid.affine, latlon=False, cache=True)
    order = flw.stream_order()
    streammask = np.asarray(acc) >= a.threshold
    feat = flw.streams(mask=streammask, strord=order)   # GeoJSON-like segments
    # assemble network table: id, class, slope, length(m), order, downstream id
    rows = []
    idmap = {}
    for i, f in enumerate(feat, start=1):
        idmap[f['properties'].get('idx', i)] = i
    for i, f in enumerate(feat, start=1):
        p = f['properties']
        sto = int(p.get('strord', 1))
        length = float(p.get('len', p.get('length', grid.affine.a)))
        slope = float(max(p.get('slope', 0.001), 1e-5))
        ds = idmap.get(p.get('idx_ds', -1), 0)
        rows.append((i, classify(sto), slope, length, sto, ds))
    arr = np.array(rows, float)
    np.savetxt(os.path.join(a.outdir, 'stream.network.dat'), arr,
               fmt='%5d %3d %11.5f %17.5f %3d %7d')
    # stream.map.dat: map channel cells to nearest segment id (simplified)
    seg_grid = np.zeros(streammask.shape, int)
    for i, f in enumerate(feat, start=1):
        for (x, y) in f['geometry']['coordinates']:
            r, c = grid.nearest_cell(x, y) if hasattr(grid, 'nearest_cell') else (None, None)
            if r is not None and 0 <= r < seg_grid.shape[0] and 0 <= c < seg_grid.shape[1]:
                seg_grid[r, c] = i
    with open(os.path.join(a.outdir, 'stream.map.dat'), 'w') as fh:
        fh.write('###### This file has been automatically generated #####\n')
        fh.write('######             EDIT WITH CARE!!!              #####\n')
        fh.write('# col row seg_id\n')
        rr, cc = np.nonzero(seg_grid)
        for r, c in zip(rr, cc):
            fh.write(f'{c+1:6d} {r+1:6d} {seg_grid[r,c]:6d}\n')
    with open(os.path.join(a.outdir, 'stream.class.dat'), 'w') as fh:
        fh.write(CLASS_DAT)
    print(f'OK segments={len(rows)} threshold={a.threshold} '
          f'wrote stream.network.dat/stream.map.dat/stream.class.dat in {a.outdir}')

if __name__ == '__main__':
    main()
