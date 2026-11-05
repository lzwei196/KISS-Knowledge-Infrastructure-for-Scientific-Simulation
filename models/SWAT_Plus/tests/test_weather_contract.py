"""Strict multi-station forcing checks on artificial three-day fixtures."""
import copy,importlib.util,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
KI=Path(os.environ.get('KI_UNDER_TEST',Path(__file__).resolve().parents[1]))
spec=importlib.util.spec_from_file_location('weather',KI/'tools/s3/prepare_weather_files.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class Tests(unittest.TestCase):
 def forcing(self):
  return dict(dates=np.arange('2000-02-28','2000-03-02',dtype='datetime64[D]'),precip_mm=np.array([0.,2.,3.]),temp_max_c=np.ones(3)*20,temp_min_c=np.ones(3)*10,srad_wm2=np.ones(3)*100,wind_ms=np.ones(3)*2,shum_kgkg=np.ones(3)*.006,pres_pa=np.ones(3)*100000)
 def run_case(self,forcings,out,elevation=50,names=None):
  m.FORCING_SOURCE='nasa_power';m.FORCING_DIR='';m.STATION_COORDS=[[32,117]]*len(forcings);m.STATION_NAMES=names or [f'sta{i}' for i in range(len(forcings))];m.START_DATE='2000-02-28';m.END_DATE='2000-03-01';m.OUTPUT_DIR=str(out)
  with patch('ki_tools_common.load_forcing.load_daily_forcing_points',return_value=forcings),patch('ki_tools_common.terrain.get_terrain',return_value={'elevation':elevation}):return m.process()
 def test_all_fields_missing_or_nonfinite_stop_before_write(self):
  for field in list(self.forcing())[1:]:
   for value in [np.nan,np.inf]:
    with self.subTest(field=field,value=value),tempfile.TemporaryDirectory() as td:
     fc=self.forcing();fc[field][1]=value;out=Path(td)/'new'
     with self.assertRaises(ValueError):self.run_case([fc],out)
     self.assertFalse(out.exists())
 def test_missing_duplicate_or_partial_dates_fail(self):
  for dates in [np.array(['2000-02-28','2000-03-01']),np.array(['2000-02-28','2000-02-28','2000-03-01']),np.array(['2000-02-27','2000-02-28','2000-02-29'])]:
   with tempfile.TemporaryDirectory() as td:
    fc=self.forcing();fc['dates']=dates
    with self.assertRaises(ValueError):self.run_case([fc],Path(td)/'out')
 def test_later_station_failure_preserves_existing_files(self):
  with tempfile.TemporaryDirectory() as td:
   td=Path(td);old=td/'sta0.pcp';old.write_text('old artifact');fc=self.forcing();fc['wind_ms'][1]=np.nan
   with self.assertRaises(ValueError):self.run_case([self.forcing(),fc],td)
   self.assertEqual(old.read_text(),'old artifact');self.assertEqual(len(list(td.iterdir())),1)
 def test_terrain_failure_cannot_be_sea_level(self):
  with tempfile.TemporaryDirectory() as td:
   with self.assertRaises(ValueError):self.run_case([self.forcing()],Path(td)/'out',elevation=np.nan)
 def test_negative_physics_and_reversed_temperatures_fail(self):
  for field in ['precip_mm','srad_wm2','wind_ms','shum_kgkg','pres_pa','temp_max_c']:
   with tempfile.TemporaryDirectory() as td:
    fc=self.forcing();fc[field][1]=-1
    with self.subTest(field=field),self.assertRaises(ValueError):self.run_case([fc],Path(td)/'out')
 def test_good_values_leap_day_zero_and_names_preserved(self):
  with tempfile.TemporaryDirectory() as td:
   out=Path(td)/'out';result=self.run_case([self.forcing()],out,elevation=0,names=['sta01'])
   p=np.loadtxt(out/'sta01.pcp',skiprows=3);np.testing.assert_array_equal(p[:,1],[59,60,61]);np.testing.assert_array_equal(p[:,2],[0,2,3]);self.assertEqual(result['n_days'],3)
   np.testing.assert_allclose(np.loadtxt(out/'sta01.slr',skiprows=3)[:,2],8.64)
 def test_duplicate_names_fail(self):
  with tempfile.TemporaryDirectory() as td:
   with self.assertRaises(ValueError):self.run_case([self.forcing(),self.forcing()],Path(td)/'out',names=['same','same'])

if __name__=='__main__':unittest.main()
