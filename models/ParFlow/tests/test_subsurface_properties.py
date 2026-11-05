"""Small temp-dir tests for s2 build_subsurface_properties.py.

Uses a tiny fake HWSD raster + CSV (artificial values, not real soils) to test
the tool's rules: every Box cell gets its own HWSD soil (inside and outside the
basin mask), no fill/default class, dominant row = largest SHARE, and the
exported saturations are fractions.
"""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import from_bounds
from pyproj import Transformer

KI = Path(os.environ.get('KI_UNDER_TEST', Path(__file__).resolve().parents[1]))
spec = importlib.util.spec_from_file_location(
    'subsurface', KI / 'tools/s2_subsurface/build_subsurface_properties.py')
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)

EPSG = 32650
ORIGIN = (500000.0, 3500000.0)
DX = 1000.0


class SubsurfaceTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = Path(t.name)
        (self.root / 'data/soil').mkdir(parents=True)
        self._old = (b.HYDROCRAFT_ROOT, b.HWSD_RASTER)
        self.addCleanup(self._restore)
        b.HYDROCRAFT_ROOT = str(self.root)
        b.HWSD_RASTER = str(self.root / 'data/soil/hwsd.tif')
        # Two cells in x (nx=2, ny=1); centres in lon/lat
        tr = Transformer.from_crs(f"EPSG:{EPSG}", "EPSG:4326", always_xy=True)
        self.lonlat = [tr.transform(ORIGIN[0] + (i + 0.5) * DX, ORIGIN[1] + 0.5 * DX)
                       for i in range(2)]
        self.domain = self.root / 'domain.json'
        self.domain.write_text(json.dumps({
            'grid': {'nx': 2, 'ny': 1, 'nz': 2, 'dx': DX, 'dy': DX},
            'origin': {'x': ORIGIN[0], 'y': ORIGIN[1]}, 'crs': {'epsg': EPSG}}))
        self.mask = self.root / 'mask.npy'
        m = np.zeros((2, 1, 2), dtype=np.int32)
        m[:, 0, 0] = 1  # cell 0 inside the basin, cell 1 outside
        np.save(self.mask, m)

    def _restore(self):
        b.HYDROCRAFT_ROOT, b.HWSD_RASTER = self._old

    def _raster(self, left_mu, right_mu):
        (l0, la0), (l1, la1) = self.lonlat
        mid = 0.5 * (l0 + l1)
        w = l1 - l0
        tf = from_bounds(mid - w, la0 - 0.01, mid + w, la0 + 0.01, 2, 1)
        with rasterio.open(b.HWSD_RASTER, 'w', driver='GTiff', width=2, height=1, count=1,
                           dtype='int32', crs='EPSG:4326', transform=tf, nodata=-1) as d:
            d.write(np.array([[left_mu, right_mu]], dtype=np.int32), 1)

    def _csv(self, rows):
        pd.DataFrame(rows, columns=['MU_GLOBAL', 'SEQ', 'SHARE', 'ISSOIL', 'T_SAND',
                                    'T_SILT', 'T_CLAY']).to_csv(
            self.root / 'data/soil/HWSD_DATA.csv', index=False)

    def test_outside_mask_cell_gets_its_own_soil_and_saturation_fractions(self):
        # MU 2: SEQ 1 = loamy sand 25 %, SEQ 3 = loam 30 % -> loam (largest SHARE)
        self._csv([(2, 1, 25, 1, 78, 12, 10), (2, 3, 30, 1, 42, 36, 22),
                   (1, 1, 100, 1, 92, 4, 4)])
        self._raster(2, 1)  # inside cell = MU 2 (loam), outside cell = MU 1 (sand)
        out = self.root / 'out'
        r = b.process(str(self.domain), str(self.mask), str(out))
        ind = np.load(out / 'texture_indicator.npy')
        names = list(b.ROSETTA_VAN_GENUCHTEN)
        loam, sand = names.index('loam') + 1, names.index('sand') + 1
        self.assertEqual(ind[0, 0].tolist(), [loam, sand])
        perm = np.load(out / 'permeability_x.npy')
        self.assertAlmostEqual(perm[0, 0, 1], b.ROSETTA_VAN_GENUCHTEN['sand'][4])
        sres = np.load(out / 'residual_saturation.npy')
        ssat = np.load(out / 'saturation_at_saturation.npy')
        self.assertAlmostEqual(sres[0, 0, 0], round(0.078 / 0.43, 4))
        self.assertTrue(np.all(ssat == 1.0))
        params = json.loads((out / 'texture_params.json').read_text())
        self.assertEqual(sorted(int(k) for k in params), sorted([loam, sand]))
        self.assertEqual(r['cells_outside_mask'], 1)
        self.assertNotIn('inactive_cell_indicator_code', r)

    def test_outside_mask_cell_without_soil_stops(self):
        self._csv([(2, 1, 100, 1, 42, 36, 22)])
        self._raster(2, 0)  # outside cell has no mapping unit (e.g. water)
        with self.assertRaisesRegex(ValueError, 'OUTSIDE basin mask'):
            b.process(str(self.domain), str(self.mask), str(self.root / 'out'))
        self.assertFalse((self.root / 'out' / 'texture_indicator.npy').exists())

    def test_dominant_row_is_largest_share_then_lowest_seq(self):
        df = pd.DataFrame({'MU_GLOBAL': [5, 5, 5, 6, 6], 'SEQ': [1, 2, 3, 2, 1],
                           'SHARE': [20, 40, 40, 50, 50]})
        d = b.dominant_hwsd_rows(df)
        self.assertEqual(int(d.loc[5, 'SEQ']), 2)
        self.assertEqual(int(d.loc[6, 'SEQ']), 1)


if __name__ == '__main__':
    unittest.main()
