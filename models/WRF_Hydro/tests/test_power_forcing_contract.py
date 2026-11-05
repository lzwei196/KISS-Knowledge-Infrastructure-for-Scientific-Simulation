"""Artificial API/grid fixtures; native tracer uses original NASA POWER responses."""
import importlib.util,json,tempfile,unittest
from pathlib import Path
from datetime import datetime,timedelta
from unittest.mock import patch
import numpy as np
import netCDF4
spec=importlib.util.spec_from_file_location('power',Path(__file__).resolve().parents[1]/'tools/s8_forcing/nasa_power_to_ldasin.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class Contract(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.r=Path(self.tmp.name)
  self.year=2001;self.start=datetime(2001,1,1);self.end=datetime(2001,1,1)
  self.times=[(self.start+timedelta(hours=i)).strftime('%Y%m%d%H') for i in range(8760)]
  values={'T2M':10.,'QV2M':5.,'PS':95.,'WS2M':2.,'WS10M':3.,'WD10M':270.,'PRECTOTCORR':0.,'ALLSKY_SFC_SW_DWN':2.,'ALLSKY_SFC_LW_DWN':300.}
  self.raw={k:np.full(8760,v) for k,v in values.items()}
  self.units={'T2M':'C','QV2M':'g/kg','PS':'kPa','WS10M':'m/s','WD10M':'Degrees','PRECTOTCORR':'mm/day','ALLSKY_SFC_SW_DWN':'Wh/m^2','ALLSKY_SFC_LW_DWN':'Wh/m^2'}
  self.raw['_metadata']={'timestamps':self.times,'time_standard':'UTC','units':self.units,'fill_value':-999.,'latitude':50.,'longitude':13.}
 def build(self):
  with patch.object(m,'fetch_power_point',return_value=self.raw),patch.object(m,'_load_npz_cache',return_value=self.raw):
   return m.build_hourly_grids(np.array([50.]),np.array([13.]),2001,self.start,self.end)
 def test_missing_required_weather_fails(self):
  for field in self.units:
   saved=self.raw[field].copy()
   for bad in [np.nan,np.inf,-999.]:
    self.raw[field][3]=bad
    with self.subTest(field=field,bad=bad),self.assertRaises(ValueError):self.build()
   self.raw[field]=saved
 def test_missing_field_or_short_arrays_fails(self):
  for field in self.units:
   saved=self.raw.pop(field)
   with self.subTest(field=field),self.assertRaises(ValueError):self.build()
   self.raw[field]=saved[:12]
   with self.subTest(field=field),self.assertRaises(ValueError):self.build()
   self.raw[field]=saved
 def test_hourly_calendar_is_verified(self):
  for times in [self.times[1:],self.times[::-1],[self.times[0]]+self.times[:-1]]:
   self.raw['_metadata']['timestamps']=times
   with self.assertRaises(ValueError):self.build()
 def test_utc_and_units_are_explicit(self):
  self.raw['_metadata']['time_standard']='LST'
  with self.assertRaises(ValueError):self.build()
  self.raw['_metadata']['time_standard']='UTC';self.units['PRECTOTCORR']='unknown'
  with self.assertRaises(ValueError):self.build()
 def test_physical_invalid_values_not_clipped(self):
  for field,value in [('T2M',-200),('QV2M',-1),('PS',0),('WS10M',-1),('WD10M',361),('PRECTOTCORR',-.1),('ALLSKY_SFC_SW_DWN',-.1),('ALLSKY_SFC_LW_DWN',-.1)]:
   saved=self.raw[field][0];self.raw[field][0]=value
   with self.subTest(field=field),self.assertRaises(ValueError):self.build()
   self.raw[field][0]=saved
 def test_complete_weather_preserves_zeros_and_low_radiation(self):
  self.raw['WS10M'][:]=0.;self.raw['ALLSKY_SFC_LW_DWN'][:]=0.;self.raw['PRECTOTCORR'][0]=.0001
  grid,times=self.build();self.assertEqual(len(times),24);np.testing.assert_equal(grid['SWDOWN'],2.)
  np.testing.assert_equal(grid['LWDOWN'],0.);np.testing.assert_equal(grid['U2D'],0.)
  self.assertAlmostEqual(float(grid['RAINRATE'][0,0,0]),.0001/86400,places=14)
 def test_real_wind_direction_and_height_used(self):
  grid,_=self.build();np.testing.assert_allclose(grid['U2D'],3.,atol=1e-6);np.testing.assert_allclose(grid['V2D'],0.,atol=1e-6)
 def test_declared_radiation_conversion(self):
  for key in ['ALLSKY_SFC_SW_DWN','ALLSKY_SFC_LW_DWN']:self.units[key]='MJ/m^2/hr'
  self.raw['ALLSKY_SFC_LW_DWN'][:]=1.
  grid,_=self.build();np.testing.assert_allclose(grid['SWDOWN'],2./.0036,rtol=1e-6);np.testing.assert_allclose(grid['LWDOWN'],1./.0036,rtol=1e-6)
 def test_legacy_cache_without_metadata_rejected(self):
  saved=m._config['cache_dir'];m._config['cache_dir']=self.r;self.addCleanup(m._config.update,{'cache_dir':saved})
  p=self.r/'50.0_13.0';p.mkdir();np.savez(p/'2001.npz',T2M=np.ones(8760))
  with self.assertRaises(ValueError):m._load_npz_cache(50.,13.,2001)
 def test_regrid_does_not_fill_nan_or_extrapolate(self):
  lat=np.array([0.,1.]);lon=lat.copy();target=np.array([[.5,2.]])
  with self.assertRaises(ValueError):m.regrid_to_lcc(lat,lon,np.ones((2,2)),target,target)
  data=np.ones((2,2));data[0,0]=np.nan
  with self.assertRaises(ValueError):m.regrid_to_lcc(lat,lon,data,np.array([[.5]]),np.array([[.5]]))
 def test_writer_rejects_invalid_before_overwriting(self):
  p=self.r/'test.LDASIN_DOMAIN1';p.write_text('existing')
  data={k:np.ones((1,1)) for k in ['T2D','Q2D','U2D','V2D','PSFC','SWDOWN','LWDOWN','RAINRATE']};data.update(T2D=np.full((1,1),283.15),Q2D=np.full((1,1),.005),PSFC=np.full((1,1),95000.));data['RAINRATE'][0,0]=np.nan
  with self.assertRaises(ValueError):m.write_ldasin(p,self.start,1,1,data)
  self.assertEqual(p.read_text(),'existing')
 def test_precipitation_hourly_and_daily_metadata(self):
  self.raw['PRECTOTCORR'][:]=1.
  self.units['PRECTOTCORR']='mm/hour';hourly,_=self.build()
  self.units['PRECTOTCORR']='mm/day';daily,_=self.build()
  np.testing.assert_allclose(hourly['RAINRATE'],1./3600.,rtol=1e-12)
  np.testing.assert_allclose(hourly['RAINRATE'],daily['RAINRATE']*24,rtol=1e-12)
 def test_api_response_requires_every_hour_and_location(self):
  fields={k:{t:float(v[i]) for i,t in enumerate(self.times[:24])} for k,v in self.raw.items() if k in self.units}
  response={'header':{'time_standard':'UTC','fill_value':-999},'geometry':{'coordinates':[13.,50.]},'parameters':{k:{'units':v} for k,v in self.units.items()},'properties':{'parameter':fields}}
  parsed=m._parse_response(response,50.,13.,self.start,self.end);self.assertEqual(len(parsed['T2M']),24)
  del fields['T2M'][self.times[1]]
  with self.assertRaises(ValueError):m._parse_response(response,50.,13.,self.start,self.end)
  with self.assertRaises(ValueError):m._parse_response(response,49.,13.,self.start,self.end)
 def test_grid_rotation_preserves_wind_speed(self):
  u=np.array([[3.]]);v=np.array([[4.]]);c=np.array([[0.]]);s=np.array([[1.]])
  ug,vg=m.rotate_wind_to_grid(u,v,c,s);np.testing.assert_equal(ug,4.);np.testing.assert_equal(vg,-3.)
  np.testing.assert_allclose(np.hypot(ug,vg),np.hypot(u,v))
if __name__=='__main__':unittest.main()
