"""A DEM with no CRS stops the tool unless EPSG:4326 is declared explicitly;
a declaration never overrides a CRS the file has, and no other CRS can be declared."""
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

KI = Path(os.environ.get('KI_UNDER_TEST', Path(__file__).resolve().parents[1]))
spec = importlib.util.spec_from_file_location('ef5_params_crs', KI / 'tools/convert_params_to_ef5.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

TR = from_origin(110.0, 31.0, 0.01, 0.01)


def write(path, value, crs, driver="GTiff"):
    # nodata set so an AAIGrid gets the NODATA_value header line EF5 needs
    kw = dict(driver=driver, height=4, width=5, count=1, dtype="float32", transform=TR,
              nodata=-9999.0)
    if crs:
        kw["crs"] = crs
    with rasterio.open(path, "w", **kw) as d:
        d.write(np.full((4, 5), value, dtype="float32"), 1)


class DeclaredCrs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.soil = self.d / "soil"
        self.soil.mkdir()
        write(self.soil / "sand.tif", 40.0, "EPSG:4326")
        write(self.soil / "clay.tif", 20.0, "EPSG:4326")
        write(self.soil / "silt.tif", 40.0, "EPSG:4326")
        m._DECLARED_CRS.clear()

    def tearDown(self):
        m._DECLARED_CRS.clear()
        self.tmp.cleanup()

    def run_convert(self, dem, **kw):
        # The fixture has no urban grid, so IM = 0 must be stated explicitly.
        kw.setdefault("impervious", "zero")
        return m.convert_params(str(self.soil), str(self.d / "out"), "crest", str(dem), 100, **kw)

    def test_dem_without_crs_stops_and_names_the_option(self):
        dem = self.d / "dem.asc"
        write(dem, 100.0, None, driver="AAIGrid")
        with self.assertRaisesRegex(ValueError, "--dem-crs"):
            m._read_spatial(str(dem))
        self.assertFalse(self.run_convert(dem))
        self.assertFalse((self.d / "out" / "wm.tif").exists())

    def test_declared_epsg4326_runs_and_outputs_carry_it(self):
        dem = self.d / "dem.asc"
        write(dem, 100.0, None, driver="AAIGrid")
        self.assertTrue(self.run_convert(dem, dem_crs="EPSG:4326"))
        with rasterio.open(self.d / "out" / "wm.tif") as w:
            self.assertEqual(w.crs, rasterio.crs.CRS.from_epsg(4326))

    def test_only_epsg4326_can_be_declared(self):
        dem = self.d / "dem.asc"
        write(dem, 100.0, None, driver="AAIGrid")
        with self.assertRaisesRegex(ValueError, "only EPSG:4326 can be declared"):
            m.declare_crs(str(dem), "EPSG:3857")

    def test_declaration_never_overrides_a_file_crs(self):
        dem = self.d / "dem_utm.tif"
        write(dem, 100.0, "EPSG:32650")
        m.declare_crs(str(dem), "EPSG:4326")
        with self.assertRaisesRegex(ValueError, "differs from declared"):
            m._read_spatial(str(dem))


if __name__ == "__main__":
    unittest.main(verbosity=2)
