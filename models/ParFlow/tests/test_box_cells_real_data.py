"""Small temp-dir tests: every cell of the Box grid gets real data.

The s7 run script uses Box geometry, so ParFlow and CLM simulate every cell of
the rectangle, inside and outside the basin mask. These tests check that
s3 (slopes), s4 (CLM drv_vegm.dat) and s6 (initial pressure) give outside cells
their own values from the data, and stop when data is missing. The rasters are
tiny artificial test rasters (not real data).
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


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, KI / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


s3 = _load('slopes', 'tools/s3_topography/build_slopes.py')
s4 = _load('clm', 'tools/s4_clm/setup_clm_driver.py')
s6 = _load('ic', 'tools/s6_ic_bc/generate_initial_conditions.py')
s5 = _load('forcing', 'tools/s5_forcing/convert_forcing_to_pfb.py')

EPSG = 32650
ORIGIN = (500000.0, 3500000.0)
DX = 1000.0
NX, NY, NZ = 3, 2, 2


def _centres_lonlat():
    tr = Transformer.from_crs(f"EPSG:{EPSG}", "EPSG:4326", always_xy=True)
    return {(i, j): tr.transform(ORIGIN[0] + (i + 0.5) * DX, ORIGIN[1] + (j + 0.5) * DX)
            for j in range(NY) for i in range(NX)}


def _write_lonlat_raster(path, values, dtype, nodata=None, drop=None):
    """EPSG:4326 raster whose every pixel holds the value of the nearest cell
    centre (values: {(i, j): v}). drop = cell whose area is left out of the
    raster's extent is not possible for one cell, so 'drop' writes nodata."""
    c = _centres_lonlat()
    lons = [v[0] for v in c.values()]
    lats = [v[1] for v in c.values()]
    left, right = min(lons) - 0.01, max(lons) + 0.01
    bottom, top = min(lats) - 0.01, max(lats) + 0.01
    w, h = 200, 120
    tf = from_bounds(left, bottom, right, top, w, h)
    xs = left + (np.arange(w) + 0.5) * (right - left) / w
    ys = top - (np.arange(h) + 0.5) * (top - bottom) / h
    X, Y = np.meshgrid(xs, ys)
    keys = list(c)
    d2 = np.stack([(X - c[k][0]) ** 2 + (Y - c[k][1]) ** 2 for k in keys])
    near = np.argmin(d2, axis=0)
    arr = np.zeros((h, w), dtype=dtype)
    for n, k in enumerate(keys):
        v = values[k]
        if drop is not None and k == drop:
            v = nodata
        arr[near == n] = v
    with rasterio.open(path, 'w', driver='GTiff', width=w, height=h, count=1, dtype=dtype,
                       crs='EPSG:4326', transform=tf, nodata=nodata) as d:
        d.write(arr, 1)


class BoxCellBase(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = Path(t.name)
        self.domain = self.root / 'domain.json'
        self.domain.write_text(json.dumps({
            'grid': {'nx': NX, 'ny': NY, 'nz': NZ, 'dx': DX, 'dy': DX,
                     'dz_layers_m': [1.0, 1.0], 'total_depth_m': 2.0,
                     'terrain_following': True},
            'origin': {'x': ORIGIN[0], 'y': ORIGIN[1]}, 'crs': {'epsg': EPSG}}))
        m2 = np.zeros((NY, NX), dtype=np.int32)
        m2[0, 0] = 1  # only cell (0,0) is inside the basin
        self.mask2 = self.root / 'surface_mask.npy'
        np.save(self.mask2, m2)
        self.mask3 = self.root / 'domain_mask.npy'
        np.save(self.mask3, np.repeat(m2[np.newaxis], NZ, axis=0))


class ClmVegmTests(BoxCellBase):
    def setUp(self):
        super().setUp()
        (self.root / 'data/soil').mkdir(parents=True)
        old = {k: getattr(s4, k) for k in
               ('HYDROCRAFT_ROOT', 'AVHRR_FILE', 'HWSD_RASTER', 'SHIPPED_VEGP')}
        self.addCleanup(lambda: [setattr(s4, k, v) for k, v in old.items()])
        s4.HYDROCRAFT_ROOT = str(self.root)
        s4.AVHRR_FILE = str(self.root / 'avhrr.tif')
        s4.HWSD_RASTER = str(self.root / 'hwsd.tif')
        # stand-in for the shipped washita drv_vegp.dat (only copied by s4)
        s4.SHIPPED_VEGP = str(self.root / 'drv_vegp.dat')
        Path(s4.SHIPPED_VEGP).write_text('test stand-in vegp\n')
        # inside cell: cropland (UMD 11) on MU 2; outside cells: deciduous
        # broadleaf (UMD 4) on MU 1 / grassland (UMD 10) on MU 3
        self.lc = {(i, j): 4 for j in range(NY) for i in range(NX)}
        self.lc[(0, 0)] = 11
        self.lc[(2, 1)] = 10
        self.mu = {(i, j): 1 for j in range(NY) for i in range(NX)}
        self.mu[(0, 0)] = 2
        self.mu[(2, 1)] = 3
        pd.DataFrame([(1, 1, 100, 1, 70, 20, 10), (2, 1, 100, 1, 30, 40, 30),
                      (3, 1, 100, 1, 45, 35, 20)],
                     columns=['MU_GLOBAL', 'SEQ', 'SHARE', 'ISSOIL', 'T_SAND', 'T_SILT',
                              'T_CLAY']).to_csv(self.root / 'data/soil/HWSD_DATA.csv',
                                                index=False)

    def _run(self, soil_color=3, lc_drop=None, mu_drop=None):
        _write_lonlat_raster(s4.AVHRR_FILE, self.lc, 'uint8', nodata=255, drop=lc_drop)
        _write_lonlat_raster(s4.HWSD_RASTER, self.mu, 'int32', nodata=0, drop=mu_drop)
        return s4.process(str(self.domain), str(self.mask2), '2005-01-01', '2005-01-03',
                          str(self.root / 'clm'), soil_color=soil_color)

    def _rows(self):
        lines = (self.root / 'clm/drv_vegm.dat').read_text().splitlines()
        self.assertEqual(len(lines), 2 + NX * NY)
        return {(int(r.split()[0]) - 1, int(r.split()[1]) - 1): r.split() for r in lines[2:]}

    def test_every_cell_gets_its_own_soil_and_land_cover(self):
        r = self._run(soil_color=3)
        rows = self._rows()
        inside, outside, other = rows[(0, 0)], rows[(1, 0)], rows[(2, 1)]
        self.assertEqual([float(inside[4]), float(inside[5])], [0.30, 0.30])
        self.assertEqual([float(outside[4]), float(outside[5])], [0.70, 0.10])
        self.assertEqual([float(other[4]), float(other[5])], [0.45, 0.20])
        for row in rows.values():
            self.assertEqual(row[6], '3')
            fr = [float(x) for x in row[7:]]
            self.assertEqual(len(fr), 18)
            self.assertAlmostEqual(sum(fr), 1.0)
        self.assertEqual(float(inside[7 + 12 - 1]), 1.0)   # UMD 11 -> IGBP 12 cropland
        self.assertEqual(float(outside[7 + 4 - 1]), 1.0)   # UMD 4 -> IGBP 4, not water 17
        self.assertEqual(float(outside[7 + 17 - 1]), 0.0)
        self.assertEqual(float(other[7 + 10 - 1]), 1.0)
        self.assertEqual(r['provenance']['soil_color']['value'], 3)
        self.assertIn('user-supplied', r['provenance']['soil_color']['source'])
        self.assertEqual(r['provenance']['cells_outside_mask'], NX * NY - 1)
        self.assertTrue((self.root / 'clm/clm_provenance.json').exists())

    def test_outside_cell_without_soil_stops(self):
        with self.assertRaisesRegex(ValueError, r'(?s)HWSD gave no topsoil.*OUTSIDE basin mask'):
            self._run(mu_drop=(2, 1))
        self.assertFalse((self.root / 'clm/drv_vegm.dat').exists())

    def test_cell_without_land_cover_stops(self):
        self.lc[(1, 1)] = 200  # value with no IGBP mapping in this tool
        with self.assertRaisesRegex(ValueError, 'AVHRR gave no land-cover class'):
            self._run()
        self.assertFalse((self.root / 'clm/drv_vegm.dat').exists())

    def test_soil_color_has_no_default(self):
        for bad in (None, 0, 9, 2.5, True):
            with self.assertRaisesRegex(ValueError, 'soil_color'):
                self._run(soil_color=bad)


class SlopeTests(BoxCellBase):
    def _dem(self, cover_all=True):
        # Plane rising 2 m per km in x and 1 m per km in y, in the grid's own CRS
        path = self.root / 'dem.tif'
        w, h = NX * 10, NY * 10
        right = ORIGIN[0] + NX * DX if cover_all else ORIGIN[0] + (NX - 1) * DX
        w = w if cover_all else (NX - 1) * 10
        tf = from_bounds(ORIGIN[0], ORIGIN[1], right, ORIGIN[1] + NY * DX, w, h)
        xs = ORIGIN[0] + (np.arange(w) + 0.5) * (right - ORIGIN[0]) / w
        ys = ORIGIN[1] + NY * DX - (np.arange(h) + 0.5) * DX * NY / h
        X, Y = np.meshgrid(xs, ys)
        z = 100.0 + 0.002 * (X - ORIGIN[0]) + 0.001 * (Y - ORIGIN[1])
        with rasterio.open(path, 'w', driver='GTiff', width=w, height=h, count=1,
                           dtype='float64', crs=f'EPSG:{EPSG}', transform=tf,
                           nodata=-9999.0) as d:
            d.write(z, 1)
        return path

    def test_outside_cells_get_real_dem_slopes(self):
        out = self.root / 'topo'
        r = s3.process(str(self.domain), str(self._dem()), str(self.mask2), str(out),
                       fill_sinks=False)
        sx, sy = np.load(out / 'slope_x.npy'), np.load(out / 'slope_y.npy')
        self.assertTrue(np.allclose(sx, 0.002, atol=2e-4), sx)
        self.assertTrue(np.allclose(sy, 0.001, atol=2e-4), sy)
        self.assertEqual(r['cells_outside_mask'], NX * NY - 1)
        self.assertIsNotNone(r['outside_basin_mask'])

    def test_dem_gap_stops_without_fill(self):
        with self.assertRaisesRegex(ValueError, r'(?s)no value for .*OUTSIDE basin mask'):
            s3.process(str(self.domain), str(self._dem(cover_all=False)), str(self.mask2),
                       str(self.root / 'topo'), fill_sinks=False)
        self.assertFalse((self.root / 'topo' / 'slope_x.npy').exists())


class SinkFillTests(unittest.TestCase):
    def test_flat_multi_cell_depression_is_filled_and_drains(self):
        z = np.full((5, 5), 10.0)
        z[1:4, 1:4] = 0.0  # flat 3x3 pit inside a 10 m rim
        f = s3.fill_sinks_simple(z, np.ones((5, 5), dtype=np.int32))
        self.assertTrue(np.all(f[1:4, 1:4] > 10.0))
        # every interior cell has a strictly lower 4-neighbour
        for j in range(1, 4):
            for i in range(1, 4):
                nb = [f[j - 1, i], f[j + 1, i], f[j, i - 1], f[j, i + 1]]
                self.assertLess(min(nb), f[j, i])
        self.assertTrue(np.array_equal(f[0], z[0]))  # edges unchanged


class InitialPressureTests(BoxCellBase):
    def test_outside_cells_get_hydrostatic_pressure(self):
        elev = np.array([[100.0, 110.0, 120.0], [105.0, 115.0, 125.0]])
        ep = self.root / 'elev.npy'
        np.save(ep, elev)
        out = self.root / 'ic'
        s6.process(str(self.domain), str(self.mask3), str(out), method='hydrostatic',
                   wtd=1.5, elevation_npy=str(ep))
        p = np.load(out / 'initial_pressure.npy')
        # cell centres at surface - 1.5 (k=0) and surface - 0.5 (k=1); WT at surface - 1.5
        self.assertTrue(np.allclose(p[0], 0.0))
        self.assertTrue(np.allclose(p[1], -1.0))

    def test_missing_elevation_file_stops(self):
        with self.assertRaises(FileNotFoundError):
            s6.process(str(self.domain), str(self.mask3), str(self.root / 'ic'),
                       elevation_npy=str(self.root / 'nope.npy'))


class CmfdUnitsTests(unittest.TestCase):
    """CMFD V2.0 stores prec in kg m-2 s-1 (= mm/s) in folders named Prec,
    SRad, LRad, SHum ...; units come from the file, folder match ignores case."""

    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = Path(t.name)

    def _nc(self, folder, var, units, value):
        import xarray as xr
        d = self.root / folder
        d.mkdir(exist_ok=True)
        da = xr.DataArray(np.full((2, 2, 2), value, dtype=np.float32),
                          dims=('time', 'lat', 'lon'),
                          coords={'time': [0, 3], 'lat': [30.0, 30.1], 'lon': [110.0, 110.1]},
                          attrs={'units': units} if units is not None else {})
        da.to_dataset(name=var).to_netcdf(d / f'{var}_CMFD_V0200_B-01_03hr_010deg_201507.nc')

    def test_prec_mm_per_s_kept_and_mixed_case_folder_found(self):
        self._nc('Prec', 'prec', 'kg m-2 s-1', 2e-5)
        self._nc('SRad', 'srad', 'W m-2', 500.0)
        lats, lons = np.array([[30.0]]), np.array([[110.0]])
        p = s5._extract_cmfd_month(str(self.root), 2015, 7, 'APCP', lats, lons)
        self.assertAlmostEqual(float(p[0, 0, 0]), 2e-5, places=10)   # not /3600
        r = s5._extract_cmfd_month(str(self.root), 2015, 7, 'DSWR', lats, lons)
        self.assertAlmostEqual(float(r[0, 0, 0]), 500.0)

    def test_domain_outside_source_grid_stops(self):
        self._nc('Prec', 'prec', 'kg m-2 s-1', 2e-5)
        with self.assertRaisesRegex(ValueError, 'outside the source grid'):
            s5._extract_cmfd_month(str(self.root), 2015, 7, 'APCP',
                                   np.array([[50.0]]), np.array([[0.0]]))

    def test_prec_mm_per_hr_divided_and_unknown_units_stop(self):
        self._nc('Prec', 'prec', 'mm hr-1', 3.6)
        lats, lons = np.array([[30.0]]), np.array([[110.0]])
        p = s5._extract_cmfd_month(str(self.root), 2015, 7, 'APCP', lats, lons)
        self.assertAlmostEqual(float(p[0, 0, 0]), 0.001, places=7)
        self._nc('Temp', 'temp', None, 290.0)
        with self.assertRaisesRegex(ValueError, 'units'):
            s5._extract_cmfd_month(str(self.root), 2015, 7, 'Temp', lats, lons)


class ForcingStampTests(unittest.TestCase):
    def test_old_unstamped_chunks_stop(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            dom = root / 'domain.json'
            dom.write_text(json.dumps({
                'grid': {'nx': 1, 'ny': 1, 'dx': 1000.0, 'dy': 1000.0},
                'origin': {'x': 500000.0, 'y': 3500000.0}, 'crs': {'epsg': 32650}}))
            out = root / 'forcing'
            out.mkdir()
            (out / 'NLDAS.APCP.000001_to_000024.pfb').write_bytes(b'old')
            with self.assertRaisesRegex(ValueError, 'no conversion stamp'):
                s5.process(str(dom), 'cmfd', str(root), '2015-07-01', '2015-07-02', str(out))

    def test_cache_only_folder_without_stamp_stops(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            dom = root / 'domain.json'
            dom.write_text(json.dumps({
                'grid': {'nx': 1, 'ny': 1, 'dx': 1000.0, 'dy': 1000.0},
                'origin': {'x': 500000.0, 'y': 3500000.0}, 'crs': {'epsg': 32650}}))
            out = root / 'forcing'
            (out / 'cache').mkdir(parents=True)
            np.save(out / 'cache' / 'mswx_APCP_2015.npy', np.zeros((2, 1, 1)))
            with self.assertRaisesRegex(ValueError, 'no conversion stamp'):
                s5.process(str(dom), 'mswx', str(root), '2015-07-01', '2015-07-02', str(out))
            self.assertFalse((out / 'forcing_conversion.json').exists())

    def test_moved_domain_with_same_shape_stops(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            dom = root / 'domain.json'
            d = {'grid': {'nx': 1, 'ny': 1, 'dx': 1000.0, 'dy': 1000.0},
                 'origin': {'x': 500000.0, 'y': 3500000.0}, 'crs': {'epsg': 32650}}
            out = root / 'forcing'
            out.mkdir()
            (out / 'NLDAS.APCP.000001_to_000024.pfb').write_bytes(b'chunk')
            dom.write_text(json.dumps(d))
            stamp = {"conversion": s5.CONVERSION_ID, "forcing_source": 'cmfd',
                     "forcing_dir": os.path.abspath(str(root)), "start_date": '2015-07-01',
                     "met_name": 'NLDAS', "chunk_hours": 24, "nx": 1, "ny": 1,
                     "dx": 1000.0, "dy": 1000.0, "origin_x": 500000.0,
                     "origin_y": 3500000.0 - 1.0e6, "crs_epsg": 32650}  # grid 1000 km south
            (out / 'forcing_conversion.json').write_text(json.dumps(stamp))
            with self.assertRaisesRegex(ValueError, 'different conversion/source/start/grid'):
                s5.process(str(dom), 'cmfd', str(root), '2015-07-01', '2015-07-02', str(out))


if __name__ == '__main__':
    unittest.main()
