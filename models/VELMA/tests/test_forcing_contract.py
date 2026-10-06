"""Artificial weather/grid fixtures; native model tracer uses official example data."""
import importlib.util,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import netCDF4
import numpy as np
import pandas as pd
import xarray as xr
import geopandas as gpd
from shapely.geometry import box
spec=importlib.util.spec_from_file_location('converter',Path(__file__).resolve().parents[1]/'tools/convert_forcing_to_velma.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class Contract(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.r=Path(self.tmp.name);self.dates=pd.date_range('2000-01-01','2000-12-31')
  self.series=[pd.Series(np.full(366,v),index=self.dates) for v in [1.,283.15,150.]]
  self.shape=self.r/'basin.geojson';gpd.GeoDataFrame(geometry=[box(9.6,39.6,10.4,40.4)],crs='EPSG:4326').to_file(self.shape,driver='GeoJSON')
  self.args=SimpleNamespace(forcing_dir=str(self.r),shapefile=str(self.shape),years='2000-2000',prec_var='prec',temp_var='temp',srad_var='srad',file_pattern='{var}_{year}.nc',prec_unit='mm/d',temp_unit='K',srad_unit='W/m2',output=str(self.r/'out.json'),solar_mode='required')
 def process(self):
  with patch.object(m,'load_and_mask_cmfd',return_value=tuple(self.series)):return m.process(self.args,[])
 def test_missing_weather_never_filled(self):
  for i in range(3):
   saved=self.series[i]
   for bad in [None,pd.Series(np.full(366,np.nan),index=self.dates),pd.Series(np.full(366,np.inf),index=self.dates)]:
    self.series[i]=bad
    with self.subTest(field=i),self.assertRaises(ValueError):self.process()
   self.series[i]=saved
 def test_validation_failure_stops_conversion(self):
  for idx,value in [(0,-1.),(1,15.),(2,-10.)]:
   saved=self.series[idx].copy();self.series[idx].iloc[20]=value
   with self.subTest(field=idx),self.assertRaises(ValueError):self.process()
   self.series[idx]=saved
 def test_calendars_cannot_be_intersected_or_truncated(self):
  for dates in [self.dates[:-1],self.dates[::-1],self.dates+pd.Timedelta(days=1)]:
   self.series[1]=pd.Series(np.full(len(dates),283.15),index=dates)
   with self.assertRaises(ValueError):self.process()
 def test_zero_and_small_values_preserved(self):
  self.series[0][:]=0.;self.series[0].iloc[0]=.000000123456;self.series[2][:]=0.
  result=self.process()['output'];self.assertEqual(result['n_days'],366);self.assertEqual(result['prec_mm_d'][0],.000000123456);self.assertEqual(result['srad_Wm2'][0],0.);self.assertEqual(result['filled_values'],0)
 def test_native_unused_solar_is_explicit_and_omitted(self):
  self.args.solar_mode='unused';self.series[2]=None
  out=self.process()['output'];self.assertNotIn('srad_Wm2',out);self.assertEqual(out['solar_mode'],'unused')
 def write_grid(self,missing=False,offset=0):
  for var,val in [('prec',1.),('temp',283.15),('srad',150.)]:
   arr=np.full((366,1,1),val)
   if missing and var=='prec':arr[30,0,0]=np.nan
   xr.Dataset({var:(('time','lat','lon'),arr)},coords={'time':self.dates,'lat':[40.+offset],'lon':[10.+offset]}).to_netcdf(self.r/f'{var}_2000.nc')
 def read_grid(self):return m.load_and_mask_cmfd(str(self.r),str(self.shape),[2000],'prec','temp','srad','{var}_{year}.nc',[])
 def test_raw_active_cell_nan_is_not_dropped_from_spatial_mean(self):
  self.write_grid(missing=True)
  with self.assertRaises(ValueError):self.read_grid()
 def test_zero_polygon_cells_do_not_use_bounding_box(self):
  self.write_grid(offset=1.)
  with self.assertRaises(ValueError):self.read_grid()
 def test_missing_year_or_field_is_error(self):
  self.write_grid();(self.r/'srad_2000.nc').unlink()
  with self.assertRaises((ValueError,FileNotFoundError)):self.read_grid()
 def test_complete_grids_convert_without_changing_values(self):
  self.write_grid();series=self.read_grid();self.assertEqual(len(series[0]),366);np.testing.assert_equal(series[1].values,283.15)
 def test_subdaily_units_are_rejected(self):
  self.args.prec_unit='mm/3h'
  with self.assertRaises(ValueError):self.process()
 def test_invalid_raw_values_cannot_cancel_in_mean(self):
  self.write_grid()
  with xr.open_dataset(self.r/'prec_2000.nc') as ds: changed=ds.load()
  changed['prec'].values[1,0,0]=-1.
  changed.to_netcdf(self.r/'prec_2000.nc')
  with self.assertRaises(ValueError):m.process(self.args,[])
 def test_failed_cli_keeps_existing_output(self):
  import subprocess,sys
  self.write_grid(missing=True); out=self.r/'out.json';out.write_text('existing output')
  cmd=[sys.executable,'-B',str(Path(m.__file__)), '--forcing-dir',str(self.r),'--shapefile',str(self.shape),'--years','2000-2000','--file-pattern','{var}_{year}.nc','--prec-unit','mm/d','--output',str(out)]
  result=subprocess.run(cmd,capture_output=True,text=True)
  self.assertNotEqual(result.returncode,0);self.assertEqual(out.read_text(),'existing output');self.assertIn('active grid cell',result.stderr)
if __name__=='__main__':unittest.main()
