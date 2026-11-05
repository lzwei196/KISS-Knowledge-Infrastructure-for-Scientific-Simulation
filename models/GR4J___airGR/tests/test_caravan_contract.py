"""Artificial Caravan fixtures; real native airGR replay is separate."""
import importlib.util,json,tempfile,unittest
from pathlib import Path
import numpy as np
import pandas as pd
import xarray as xr
spec=importlib.util.spec_from_file_location('forcing',Path(__file__).resolve().parents[1]/'tools/convert_forcing_to_gr4j.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class Contract(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.r=Path(self.tmp.name);self.src=self.r/'source.nc';self.out=self.r/'forcing.csv'
  self.dates=pd.date_range('2000-02-27',periods=5)
  self.ds=xr.Dataset({name:('date',np.full(5,value)) for name,value in [('total_precipitation_sum',1.),('temperature_2m_mean',10.),('potential_evaporation_sum',2.),('streamflow',.5)]},coords={'date':self.dates})
 def run_convert(self,method='oudin',**kw):
  self.ds.to_netcdf(self.src,engine='h5netcdf')
  return m.convert_caravan_to_airgr(str(self.src),45.,str(self.out),pe_method=method,**kw)
 def test_no_missing_negative_or_infinite_precip(self):
  for value in [np.nan,np.inf,-1.]:
   self.ds.total_precipitation_sum.values[2]=value;self.out.write_text('old')
   with self.subTest(value=value),self.assertRaises(ValueError):self.run_convert()
   self.assertEqual(self.out.read_text(),'old')
 def test_no_temperature_interpolation(self):
  for value in [np.nan,np.inf,-9999.,273.15]:
   self.ds.temperature_2m_mean.values[2]=value
   with self.subTest(value=value),self.assertRaises(ValueError):self.run_convert()
 def test_selected_pet_method_never_falls_back(self):
  for value in [np.nan,np.inf,-1.]:
   self.ds.potential_evaporation_sum.values[2]=value
   with self.subTest(value=value),self.assertRaises(ValueError):self.run_convert('era5land')
  self.ds=self.ds.drop_vars('potential_evaporation_sum')
  with self.assertRaises(ValueError):self.run_convert('era5land')
  with self.assertRaises(ValueError):self.run_convert('typo')
  self.assertEqual(len(self.run_convert('oudin')),5)
 def test_calendar_gaps_duplicates_and_order_fail(self):
  base=self.ds.copy(deep=True)
  for ds in [base.isel(date=[0,1,3,4]),base.assign_coords(date=[self.dates[0],self.dates[1],self.dates[1],self.dates[3],self.dates[4]]),base.isel(date=slice(None,None,-1))]:
   self.ds=ds
   with self.assertRaises(ValueError):self.run_convert()
 def test_requested_edges_cannot_be_silently_truncated(self):
  for kwargs in [dict(start_date='2000-02-26'),dict(end_date='2000-03-03'),dict(start_date='2001-01-01')]:
   with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):self.run_convert(**kwargs)
 def test_zero_small_values_and_missing_observations_preserved(self):
  self.ds.total_precipitation_sum.values[:2]=[0.,.000000123456]
  self.ds.potential_evaporation_sum.values[0]=0.;self.ds.streamflow.values[:2]=[np.nan,0.]
  result=self.run_convert('era5land');raw=pd.read_csv(self.out)
  self.assertEqual(raw.Precip_mm[0],0.);self.assertAlmostEqual(raw.Precip_mm[1],.000000123456,places=15)
  self.assertEqual(raw.PotEvap_mm[0],0.);self.assertTrue(np.isnan(raw.Qobs_mm[0]));self.assertEqual(raw.Qobs_mm[1],0.)
  self.assertIn('2000-02-29',result.Date.tolist())
  info=json.loads(Path(str(self.out)+'.provenance.json').read_text());self.assertEqual(info['filled_forcing_values'],0);self.assertEqual(info['pe_method'],'era5land')
 def test_missing_observation_variable_does_not_invent_observations(self):
  self.ds=self.ds.drop_vars('streamflow');result=self.run_convert();self.assertNotIn('Qobs_mm',result)
 def test_invalid_observations_are_not_scored_as_real(self):
  for value in [-99.,np.inf]:
   self.ds.streamflow.values[2]=value
   with self.assertRaises(ValueError):self.run_convert()
if __name__=='__main__':unittest.main()
