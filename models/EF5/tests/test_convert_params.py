"""Artificial raster fixtures for input integrity; never production data."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
import rasterio
from rasterio.transform import from_origin, Affine

KI = Path(os.environ.get('KI_UNDER_TEST', Path(__file__).resolve().parents[1]))
spec = importlib.util.spec_from_file_location('ef5_params', KI/'tools/convert_params_to_ef5.py')
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


class ParameterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.soil = self.root/'soil'; self.soil.mkdir()
        self.out = self.root/'params'
        self.tr = from_origin(115., 31., .1, .1)
        self.dem = self.root/'dem.tif'
        self.tif(self.dem, 1.)

    def tif(self, path, values, transform=None, crs='EPSG:4326'):
        data = np.full((2, 2), values, dtype='float32') if np.isscalar(values) else np.asarray(values, dtype='float32')
        with rasterio.open(path, 'w', driver='GTiff', width=data.shape[1], height=data.shape[0],
                           count=1, dtype='float32', transform=transform or self.tr, crs=crs, nodata=-9999.) as ds:
            ds.write(data, 1)

    def soils(self, **kwargs):
        for key, value in [('sand', 60.), ('silt', 30.), ('clay', 10.)]:
            self.tif(self.soil/(key+'.tif'), value, **kwargs)

    def rejects_conversion(self):
        try:
            result = tool.convert_params(str(self.soil), str(self.out), dem_path=str(self.dem), impervious='zero')
        except (ValueError, FileNotFoundError):
            result = False
        self.assertFalse(result)
        self.assertFalse(list(self.out.glob('*.tif')))

    def test_complete_crest_and_sac_grids(self):
        self.soils()
        for model, count in [('crest', 4), ('sac', 8)]:
            out = self.root/model
            self.assertTrue(tool.convert_params(str(self.soil), str(out), model=model, dem_path=str(self.dem), impervious='zero'))
            self.assertEqual(len(list(out.glob('*.tif'))), count)
            for path in out.glob('*.tif'):
                with rasterio.open(path) as ds:
                    self.assertEqual(ds.crs, rasterio.crs.CRS.from_epsg(4326))
                    self.assertEqual(ds.transform, self.tr)
                    self.assertTrue(np.isfinite(ds.read(1)).all())
                    self.assertEqual(ds.dtypes, ('float32',))
                    self.assertFalse(ds.profile.get('tiled', False))

    def test_no_georeference_even_when_dem_same_shape(self):
        self.soils(transform=Affine.identity(), crs=None)
        self.rejects_conversion()

    def test_projected_crs_is_not_relabeled(self):
        self.soils(crs='EPSG:32650', transform=from_origin(500000., 3500000., 100., 100.))
        self.rejects_conversion()

    def test_misaligned_components(self):
        self.soils()
        self.tif(self.soil/'clay.tif', 10., transform=from_origin(116., 31., .1, .1))
        self.rejects_conversion()

    def test_active_missing_or_invalid_texture(self):
        for bad in (float('nan'), float('inf'), -1., 101., 45.):
            self.soils()
            self.tif(self.soil/'sand.tif', [[bad,60.],[60.,60.]])
            with self.subTest(bad=bad):
                self.rejects_conversion()

    def test_explicit_dem_nodata_is_not_filled(self):
        self.soils()
        self.tif(self.dem, [[-9999.,1.],[1.,1.]])
        for key, value in [('sand',60.),('silt',30.),('clay',10.)]:
            self.tif(self.soil/(key+'.tif'), [[-9999.,value],[value,value]])
        self.assertTrue(tool.convert_params(str(self.soil), str(self.out), dem_path=str(self.dem), impervious='zero'))
        with rasterio.open(self.out/'b.tif') as ds:
            self.assertTrue(ds.read(1, masked=True).mask[0,0])

    def test_soil_extent_must_cover_dem(self):
        self.soils(transform=from_origin(114., 31., .1, .1))
        self.rejects_conversion()

    def test_missing_silt_can_use_compositional_remainder(self):
        self.soils()
        (self.soil/'silt.tif').unlink()
        self.assertTrue(tool.convert_params(str(self.soil), str(self.out), dem_path=str(self.dem), impervious='zero'))

    def test_hwsd_missing_mapping_and_negative_texture_rejected(self):
        hw = self.root/'hwsd.tif'; self.tif(hw, 99.)
        table = self.root/'texture.csv'
        for rows in ('1,100,60,30,10', '99,100,-1,91,10', '99,100,60,60,10'):
            table.write_text('MU_GLOBAL,SHARE,T_SAND,T_SILT,T_CLAY\n'+rows+'\n')
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                tool.build_hwsd_texture_grids(str(self.dem), str(self.root/'hwsd_out'), str(hw), str(table), margin_deg=0)
            self.assertFalse(list((self.root/'hwsd_out').glob('*.tif')))

    def test_hwsd_zero_fraction_is_valid_and_unknown_outside_domain_is_ignored(self):
        hw = self.root/'hwsd.tif'; self.tif(hw, [[88.,99.],[99.,99.]])
        self.tif(self.dem, [[-9999.,1.],[1.,1.]])
        table = self.root/'texture.csv'
        table.write_text('MU_GLOBAL,SHARE,T_SAND,T_SILT,T_CLAY\n99,100,70,30,0\n')
        out = self.root/'hwsd_out'
        tool.build_hwsd_texture_grids(str(self.dem), str(out), str(hw), str(table), margin_deg=0)
        with rasterio.open(out/'clay.tif') as ds:
            values=ds.read(1, masked=True)
            self.assertTrue(values.mask[0,0])
            np.testing.assert_equal(values.compressed(), [0.,0.,0.])

    def test_validation_result_is_enforced(self):
        self.assertFalse(tool.validate_param_grid(np.array([[np.nan]]), 'b', (.01,2.)))
        self.assertFalse(tool.validate_param_grid(np.array([[3.]]), 'b', (.01,2.)))
        self.assertFalse(tool.validate_outputs(str(self.root/'missing')))
        self.soils()
        with patch.object(tool, 'validate_outputs', return_value=False):
            self.assertFalse(tool.convert_params(str(self.soil), str(self.out), dem_path=str(self.dem), impervious='zero'))

    def test_no_urban_grid_needs_explicit_zero(self):
        # IM = 0 everywhere is a stated choice, never a silent default
        self.soils()
        with self.assertRaises(ValueError):
            tool.compute_crest_params(*[__import__('numpy').array([40.])]*3, 100.)
        self.assertFalse(tool.convert_params(str(self.soil), str(self.out), dem_path=str(self.dem)))
        self.assertTrue(tool.convert_params(str(self.soil), str(self.out), dem_path=str(self.dem),
                                            impervious='zero'))
        import json
        prov = json.loads((self.out/'params_provenance.json').read_text())
        self.assertIn('zero', prov['im_source'])

    # --- active cells follow EF5's own lookup (src/Grid.h GetRefLoc/GetGridLoc):
    # node = DEM cell UPPER-LEFT corner, parameter cell = truncated float index.
    def finite_cells(self, path):
        with rasterio.open(path) as ds:
            return sorted(map(tuple, np.argwhere(~ds.read(1, masked=True).mask).tolist()))

    def test_active_cells_are_ef5_corner_cells_not_centres(self):
        # Reviewer case: 2x2 DEM, 4x4 soil over the same extent (binary-exact sizes).
        dem_tr, soil_tr = from_origin(115., 31., .125, .125), from_origin(115., 31., .0625, .0625)
        self.tif(self.dem, 1., transform=dem_tr)
        self.soils4(soil_tr)
        expected = [(0, 0), (0, 2), (2, 0), (2, 2)]  # centre rule would give rows/cols {1,3}
        for model in ('crest', 'sac'):
            out = self.root/model
            self.assertTrue(tool.convert_params(str(self.soil), str(out), model=model,
                                                dem_path=str(self.dem), impervious='zero'))
            for path in out.glob('*.tif'):
                self.assertEqual(self.finite_cells(path), expected, (model, path.name))

    def soils4(self, transform):
        for key, value in [('sand', 60.), ('silt', 30.), ('clay', 10.)]:
            self.tif(self.soil/(key+'.tif'), np.full((4, 4), value), transform=transform)

    def test_float_rounding_matches_ef5(self):
        # 0.1/0.05 deg: EF5's float32 corner 115.1 gives x index 1.99997 -> 1
        # (result taken from EF5's Grid.h compiled with g++).
        self.tif(self.dem, 1., transform=from_origin(115., 31., .1, .1))
        self.soils4(from_origin(115., 31., .05, .05))
        self.assertTrue(tool.convert_params(str(self.soil), str(self.out), model='sac',
                                            dem_path=str(self.dem)))
        self.assertEqual(self.finite_cells(self.out/'uzk.tif'), [(0, 0), (0, 1), (2, 0), (2, 1)])

    def test_soil_missing_where_ef5_reads_is_rejected(self):
        # Valid soil only at cell centres the old rule used; EF5 reads cell (0,0).
        dem_tr, soil_tr = from_origin(115., 31., .125, .125), from_origin(115., 31., .0625, .0625)
        self.tif(self.dem, 1., transform=dem_tr)
        self.soils4(soil_tr)
        self.assertEqual(tool._domain_mask((4, 4), soil_tr, rasterio.crs.CRS.from_epsg(4326),
                                           str(self.dem))[0, 0], True)
        sand = np.full((4, 4), 60.); sand[0, 0] = -9999.
        self.tif(self.soil/'sand.tif', sand, transform=soil_tr)
        self.rejects_conversion()

    def test_crest_same_shape_grid_must_share_dem_transform(self):
        # CREST reads a DEM-sized grid by row/column (CRESTModel.cpp IsSpatialMatch).
        self.soils(transform=from_origin(115.05, 31., .1, .1))
        self.rejects_conversion()

    def test_lookup_matches_compiled_ef5_grid_h(self):
        # Optional check against EF5's own code: set EF5_SOURCE_DIR to the EF5 repo.
        import shutil
        src = os.environ.get('EF5_SOURCE_DIR')
        if not (src and Path(src, 'src/Grid.h').is_file() and shutil.which('g++')):
            self.skipTest('EF5_SOURCE_DIR with src/Grid.h and g++ needed')
        cpp = self.root/'lookup.cpp'
        cpp.write_text('#include "Grid.h"\n#include <cstdio>\nint main(){Grid d,g;double a,b,c,e,f,h;long nr,nc,n;'
                       'if(scanf("%lf %lf %lf %lf %lf %lf %ld %ld %ld",&a,&b,&c,&e,&f,&h,&nr,&nc,&n)!=9)return 1;'
                       'd.extent.left=a;d.extent.top=b;d.cellSize=c;g.extent.left=e;g.extent.top=f;g.cellSize=h;'
                       'g.numRows=nr;g.numCols=nc;g.extent.bottom=f-(h*float(nr));g.extent.right=e+(h*float(nc));'
                       'for(long i=0;i<n;i++){long r,k;if(scanf("%ld %ld",&r,&k)!=2)return 1;RefLoc q;d.GetRefLoc(k,r,&q);'
                       'GridLoc p;int ok=g.GetGridLoc(q.x,q.y,&p);printf("%ld %ld %d\\n",p.y,p.x,ok);}}\n')
        exe = self.root/'lookup'
        subprocess.run(['g++', '-O2', '-I', str(Path(src, 'src')), str(cpp), '-o', str(exe)], check=True)
        rng = np.random.default_rng(1)
        for _ in range(200):
            dcs, gcs = rng.choice([1/120, .01, .05, .1, .125]), rng.choice([1/120, .01, .05, .1, 1/240])
            dl, dt = round(rng.uniform(-180, 170), 3), round(rng.uniform(-60, 80), 3)
            gl, gt = dl - rng.uniform(0, .3), dt + rng.uniform(0, .3)
            rows, cols = [a.ravel() for a in np.mgrid[0:12, 0:15]]
            shape = (int(12*dcs/gcs + .3/gcs) + 2, int(15*dcs/gcs + .3/gcs) + 2)
            text = f'{dl!r} {dt!r} {float(dcs)!r} {gl!r} {gt!r} {float(gcs)!r} {shape[0]} {shape[1]} {rows.size}\n' + \
                   ' '.join(f'{r} {c}' for r, c in zip(rows, cols))
            got = np.loadtxt(subprocess.run([str(exe)], input=text, capture_output=True, text=True,
                                            check=True).stdout.splitlines(), dtype=int)
            r, c, inside = tool._ef5_lookup(from_origin(dl, dt, dcs, dcs), rows, cols,
                                            from_origin(gl, gt, gcs, gcs), shape)
            np.testing.assert_array_equal(got, np.column_stack([r, c, inside.astype(int)]))

    # --- DEM origin must be read the way EF5 reads it (TifGrid.cpp / AscGrid.cpp)
    def test_pixel_is_point_dem_is_rejected(self):
        # Reviewer case: EF5 takes the raw tiepoint as the corner, rasterio shifts it.
        with rasterio.open(self.dem, 'w', driver='GTiff', width=2, height=2, count=1, dtype='float32',
                           transform=from_origin(115., 31., .125, .125), crs='EPSG:4326') as ds:
            ds.update_tags(AREA_OR_POINT='Point')
            ds.write(np.ones((2, 2), dtype='float32'), 1)
        with rasterio.open(self.dem) as ds:
            self.assertEqual(ds.tags().get('AREA_OR_POINT'), 'Point')
        self.soils4(from_origin(115., 31., .0625, .0625))
        self.rejects_conversion()

    def test_nonzero_raster_tiepoint_dem_is_rejected(self):
        # Reviewer case: tiepoint (1,1,0,115.125,30.875,0). GDAL maps it to origin
        # (115,31); EF5 (TifGrid.cpp) takes 115.125/30.875 as the corner.
        try:
            import tifffile
        except ImportError:
            self.skipTest('tifffile needed to write a raw tiepoint fixture')
        geokeys = (1, 1, 0, 3, 1024, 0, 1, 2, 1025, 0, 1, 1, 2048, 0, 1, 4326)
        def write(tie):
            tifffile.imwrite(self.dem, np.ones((2, 2), dtype='float32'), extratags=[
                (33550, 'd', 3, (.125, .125, 0.), True), (33922, 'd', 6, tie, True),
                (34735, 'H', len(geokeys), geokeys, True)])
        write((1., 1., 0., 115.125, 30.875, 0.))
        with rasterio.open(self.dem) as ds:  # GDAL hides the offset
            self.assertEqual((ds.transform.c, ds.transform.f), (115., 31.))
        for k in ('sand', 'silt', 'clay'):
            v = {'sand': 60., 'silt': 30., 'clay': 10.}[k]
            self.tif(self.soil/(k+'.tif'), np.full((6, 6), v), transform=from_origin(115., 31., .0625, .0625))
        self.rejects_conversion()
        write((0., 0., 0., 115., 31., 0.))  # same DEM, tiepoint at raster (0,0): accepted
        self.assertTrue(tool.convert_params(str(self.soil), str(self.out), model='sac',
                                            dem_path=str(self.dem)))

    def test_raw_tiff_reader_matches_gdal(self):
        for opts in ({}, {'BIGTIFF': 'YES'}):
            path = self.root/('d%d.tif' % len(opts))
            tr = from_origin(101.25, 44.5, 1/120, 1/120)
            with rasterio.open(path, 'w', driver='GTiff', width=3, height=2, count=1, dtype='float32',
                               transform=tr, crs='EPSG:4326', **opts) as ds:
                ds.write(np.ones((2, 3), dtype='float32'), 1)
            tie, scale, mt = tool._raw_tiff_georef(str(path))
            self.assertIsNone(mt)
            self.assertEqual(tie, (0., 0., 0., 101.25, 44.5, 0.))
            self.assertEqual(scale[:2], (1/120, 1/120))
            tool._check_ef5_dem_georef(str(path))

    def test_dem_internal_mask_is_ignored_like_ef5(self):
        # Reviewer case: 4 valid elevations, NoData -9999, internal mask hiding (0,0).
        # EF5 (TifGrid.cpp) reads the raw value and only compares with -9999.
        with rasterio.open(self.dem, 'w', driver='GTiff', width=2, height=2, count=1, dtype='float32',
                           transform=self.tr, crs='EPSG:4326', nodata=-9999.) as ds:
            ds.write(np.full((2, 2), 5., dtype='float32'), 1)
            ds.write_mask(np.array([[0, 255], [255, 255]], dtype='uint8'))
        with rasterio.open(self.dem) as ds:
            self.assertTrue(ds.read(1, masked=True).mask[0, 0])
        self.soils()
        self.assertTrue(tool.convert_params(str(self.soil), str(self.out), dem_path=str(self.dem),
                                            impervious='zero'))
        for path in self.out.glob('*.tif'):
            self.assertEqual(self.finite_cells(path), [(0, 0), (0, 1), (1, 0), (1, 1)], path.name)

    def test_dem_sidecar_nodata_is_ignored_like_ef5(self):
        # Reviewer case: TIFF tag NoData -9999, .aux.xml sidecar says NoData 5.
        # EF5 reads only the TIFF tag, so the elevation 5 at (0,0) is data.
        self.tif(self.dem, [[5., 1.], [1., 1.]])
        Path(str(self.dem) + '.aux.xml').write_text(
            '<PAMDataset><PAMRasterBand band="1"><NoDataValue>5</NoDataValue>'
            '</PAMRasterBand></PAMDataset>')
        with rasterio.open(self.dem) as ds:
            self.assertEqual(ds.nodata, 5.)  # GDAL follows the sidecar
        self.assertEqual(tool._raw_tiff_georef(str(self.dem), with_nodata=True)[3], '-9999')
        self.soils()
        self.assertTrue(tool.convert_params(str(self.soil), str(self.out), dem_path=str(self.dem),
                                            impervious='zero'))
        self.assertEqual(self.finite_cells(self.out/'wm.tif'), [(0, 0), (0, 1), (1, 0), (1, 1)])

    def test_ascii_dem_nodata_from_header(self):
        self.soils()
        dem = self.root/'dem.asc'
        dem.write_text('ncols 2\nnrows 2\nxllcorner 115.0\nyllcorner 30.8\ncellsize 0.1\n'
                       'NODATA_value -9999\n-9999 1\n1 1\n')
        self.assertEqual(tool._ef5_dem_valid(str(dem)).tolist(), [[False, True], [True, True]])

    def test_nonfinite_dem_value_ef5_counts_as_data_is_rejected(self):
        self.tif(self.dem, [[np.nan, 1.], [1., 1.]])  # NoData is -9999, so EF5 counts NaN as data
        self.soils()
        self.rejects_conversion()

    def asc_dem(self, header):
        dem = self.root/'dem.asc'
        dem.write_text(header + '1 1\n1 1\n')
        self.dem = dem
        return dem

    def test_ascii_dem_header_must_be_ef5_order_with_corners(self):
        self.soils()
        good = 'ncols 2\nnrows 2\nxllcorner 115.0\nyllcorner 30.8\ncellsize 0.1\nNODATA_value -9999\n'
        self.asc_dem(good)
        self.assertTrue(tool.convert_params(str(self.soil), str(self.out), dem_path=str(self.dem),
                                            dem_crs='EPSG:4326', impervious='zero'))
        for bad in (good.replace('xllcorner 115.0', 'xllcenter 115.05').replace('yllcorner 30.8', 'yllcenter 30.85'),
                    good.replace('NODATA_value -9999\n', '')):
            with self.subTest(bad=bad):
                tool._DECLARED_CRS.clear()
                self.asc_dem(bad)
                self.out = self.root/'bad'
                self.assertFalse(tool.convert_params(str(self.soil), str(self.out), dem_path=str(self.dem),
                                                     dem_crs='EPSG:4326', impervious='zero'))
                self.assertFalse(list(self.out.glob('*.tif')))
        tool._DECLARED_CRS.clear()

    def test_zero_impervious_provenance_states_ef5_scalar(self):
        # EF5 CRESTModel.cpp turns im_grid zeros into 0.01 before x scalar IM.
        self.soils()
        self.assertTrue(tool.convert_params(str(self.soil), str(self.out), dem_path=str(self.dem),
                                            impervious='zero'))
        import json
        prov = json.loads((self.out/'params_provenance.json').read_text())
        self.assertIn('IM=0', prov['ef5_config_required'])

    # --- --impervious zero is honoured even when an urban grid exists
    def test_impervious_zero_ignores_existing_urban_grid(self):
        self.soils()
        self.tif(self.soil/'urban.tif', 65.)
        self.assertTrue(tool.convert_params(str(self.soil), str(self.out), dem_path=str(self.dem),
                                            impervious='zero'))
        with rasterio.open(self.out/'im.tif') as ds:
            np.testing.assert_array_equal(ds.read(1), 0.)
        self.assertEqual(tool.compute_crest_params(*[np.array([40., 20., 40.])[[i]] for i in (0, 1, 2)],
                                                   100., urban_pct=np.array([65.]),
                                                   impervious='zero')['im'].tolist(), [0.])
        # 'grid' still uses it
        self.assertTrue(tool.convert_params(str(self.soil), str(self.root/'g'), dem_path=str(self.dem)))
        with rasterio.open(self.root/'g'/'im.tif') as ds:
            np.testing.assert_array_equal(ds.read(1), 65.)

    def test_unused_stale_urban_grid_does_not_block(self):
        self.soils()
        self.tif(self.soil/'urban.tif', 65., transform=from_origin(116., 31., .1, .1))  # misaligned
        self.assertTrue(tool.convert_params(str(self.soil), str(self.out), dem_path=str(self.dem),
                                            impervious='zero'))
        self.assertTrue(tool.convert_params(str(self.soil), str(self.root/'sac'), model='sac',
                                            dem_path=str(self.dem)))
        self.assertFalse(tool.convert_params(str(self.soil), str(self.root/'g'), dem_path=str(self.dem)))

    def test_cli_reports_failure_and_success(self):
        self.soils()
        cmd = [sys.executable, '-B', str(KI/'tools/convert_params_to_ef5.py'), '--soil-dir', str(self.soil),
               '--output-dir', str(self.out), '--dem', str(self.dem), '--impervious', 'zero']
        result = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.tif(self.soil/'sand.tif', float('nan'))
        before = {p.name: p.read_bytes() for p in self.out.glob('*.tif')}
        result = subprocess.run(cmd, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(before, {p.name:p.read_bytes() for p in self.out.glob('*.tif')})


if __name__ == '__main__':
    unittest.main(verbosity=2)
