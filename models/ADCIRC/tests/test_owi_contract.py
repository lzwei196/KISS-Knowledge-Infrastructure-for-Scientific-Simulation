"""Artificial weather fixtures only; separate native tracer uses actual POWER data."""
import importlib.util,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pandas as pd
import netCDF4 as nc
spec=importlib.util.spec_from_file_location('owi',Path(__file__).resolve().parents[1]/'tools/convert_forcing_to_adcirc.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class Contract(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.r=Path(self.tmp.name);self.src=self.r/'src';self.src.mkdir()
  self.df=pd.DataFrame([(t,y,x,0.,90.,1000.) for t in pd.date_range('2001-01-01',periods=25,freq='h') for y in [1.,1.5] for x in [2.,2.5]],columns=['time','lat','lon','u10','v10','pressure'])
  self.a=SimpleNamespace(input_dir=str(self.src),format='csv',domain_sw='1,2',domain_ne='1.5,2.5',resolution=.5,start_date='2001-01-01',end_date='2001-01-02',output_dir=str(self.r/'out'),step_seconds=3600,wind_unit='m/s',pressure_unit='mb')
 def run_convert(self):
  self.df.to_csv(self.src/'source.csv',index=False);m.process(self.a)
 def test_missing_wind_pressure_and_infinity_fail(self):
  for field in ['u10','v10','pressure']:
   for value in [np.nan,np.inf,-999.]:
    with self.subTest(field=field,value=value):
     saved=self.df[field].copy();self.df.loc[3,field]=value
     with self.assertRaises(ValueError):self.run_convert()
     self.df[field]=saved
 def test_pressure_required(self):
  self.df=self.df.drop(columns='pressure')
  with self.assertRaises(ValueError):self.run_convert()
 def test_incomplete_grid_duplicate_and_time_gap_fail(self):
  base=self.df.copy()
  for df in [base.drop(index=1),base.iloc[4:],base[base.time!=pd.Timestamp('2001-01-01 12:00')],pd.concat([base,base.iloc[:1]]),base[base.lon==2.]]:
   self.df=df
   with self.subTest(rows=len(df)),self.assertRaises(ValueError):self.run_convert()
 def test_decimal_csv_edge_roundoff_is_not_a_grid_gap(self):
  self.df.loc[self.df.lon==2.5,"lon"]=2.5+1e-14
  self.run_convert()
 def test_grid_resolution_mismatch_fails(self):
  self.a.resolution=.25
  with self.assertRaises(ValueError):self.run_convert()
 def test_zero_and_high_wind_preserved_no_unit_guess(self):
  self.run_convert();p=Path(self.a.output_dir);v=m._read_owi_values(p/'fort.222')
  self.assertEqual(np.max(v),90.);self.assertEqual(np.min(v),0.);self.assertEqual(v.size,25*4*2)
 def test_explicit_units(self):
  self.a.pressure_unit='Pa';self.df.pressure=100000.;self.a.wind_unit='km/h';self.df.v10=36.
  self.run_convert();p=Path(self.a.output_dir)
  np.testing.assert_allclose(m._read_owi_values(p/'fort.221'),1000.);self.assertEqual(max(m._read_owi_values(p/'fort.222')),10.)
 def test_native_fixed_width_headers_and_control(self):
  self.run_convert();p=Path(self.a.output_dir)
  self.assertEqual((p/'fort.22').read_text().split(),['1','0','1.0'])
  for fname in ['fort.221','fort.222']:
   lines=(p/fname).read_text().splitlines();self.assertEqual(lines[0][55:65],'2001010100');self.assertEqual(lines[0][70:80],'2001010200')
   heads=[l for l in lines if l.startswith('iLat=')];self.assertEqual(len(heads),25)
   h=heads[0];self.assertEqual(float(h[57:65]),2.);self.assertEqual(h[68:80],'200101010000')
 def test_bad_inputs_preserve_existing_outputs(self):
  p=Path(self.a.output_dir);p.mkdir();(p/'fort.221').write_text('previous');self.df.loc[3,'pressure']=np.nan
  with self.assertRaises(ValueError):self.run_convert()
  self.assertEqual((p/'fort.221').read_text(),'previous')
 def test_corrupt_output_cannot_pass_validator(self):
  self.run_convert();p=Path(self.a.output_dir);(p/'fort.222').write_text('bad data\n')
  with self.assertRaises(ValueError):m.validate_outputs(p)
 def test_nonfinite_or_out_of_bounds_geometry_rejected(self):
  self.run_convert();p=Path(self.a.output_dir);orig={n:(p/n).read_text() for n in ['fort.221','fort.222']}
  for col,width,bad in [((43,51),8,'     inf'),((57,65),8,'     nan'),((22,28),6,'   inf'),((43,51),8,' 95.0000'),((57,65),8,'200.0000')]:
   with self.subTest(bad=bad,col=col):
    for n,text in orig.items():
     lines=text.splitlines(True);lines=[l[:col[0]]+bad+l[col[1]:] if l.startswith('iLat=') else l for l in lines];(p/n).write_text(''.join(lines))
    with self.assertRaises(ValueError):m.validate_outputs(p)
 def test_second_conversion_into_same_folder_fails_and_keeps_first(self):
  self.run_convert();p=Path(self.a.output_dir);before={n:(p/n).read_bytes() for n in ['fort.22','fort.221','fort.222','forcing_provenance.json']}
  self.df.pressure=1001.
  with self.assertRaises(ValueError):self.run_convert()
  self.assertEqual({n:(p/n).read_bytes() for n in before},before)
 def test_reservation_is_exclusive_while_another_conversion_writes(self):
  # Simulate a race: another process created one destination name after the early check.
  p=Path(self.a.output_dir);real=m._reserve
  def racing(out,names):(out/'fort.222').write_text('other writer');return real(out,names)
  m._reserve=racing
  try:
   with self.assertRaises(ValueError):self.run_convert()
  finally:m._reserve=real
  self.assertEqual((p/'fort.222').read_text(),'other writer')
  for n in ['fort.22','fort.221','forcing_provenance.json']:self.assertFalse((p/n).exists(),n)
 def test_failure_after_reservation_leaves_no_placeholders(self):
  p=Path(self.a.output_dir);real=m.validate_outputs
  def boom(d):raise ValueError('forced')
  m.validate_outputs=boom
  try:
   with self.assertRaises(ValueError):self.run_convert()
  finally:m.validate_outputs=real
  self.assertEqual(sorted(x.name for x in p.iterdir()),[])
 def era(self,pressure='msl',units='Pa',gap=False):
  self.a.format='era5_nc'
  with nc.Dataset(self.src/'x.nc','w') as d:
   for k,n in [('time',27),('latitude',2),('longitude',2)]:d.createDimension(k,n)
   t=d.createVariable('time','f8',('time',));t.units='hours since 2000-12-31 23:00:00';t[:]=np.arange(27)
   for k,v in [('latitude',[1.5,1]),('longitude',[2.5,2])]:d.createVariable(k,'f8',(k,))[:]=v
   for k,u,v in [('u10','m s**-1',3.),('v10','m s**-1',4.),(pressure,units,100000.)]:
    x=d.createVariable(k,'f8',('time','latitude','longitude'),fill_value=-999.);x.units=u;x[:]=v
    if gap and k=='u10':x[3,0,0]=-999.
 def test_era_window_and_both_coordinate_directions(self):
  self.era();m.process(self.a);p=Path(self.a.output_dir)
  self.assertEqual(len(m._read_owi_values(p/'fort.221')),25*4)
  np.testing.assert_allclose(m._read_owi_values(p/'fort.221'),1000.)
 def test_era_field_order_matches_csv(self):
  # A field that differs at every point, stored with DESCENDING lat/lon in the
  # NetCDF: the OWI output must equal the CSV route on the same field, so a
  # flipped or transposed axis cannot pass (the uniform-field test above can't).
  val=lambda y,x,k:1000.+10.*y+x+0.01*k
  self.df['pressure']=[val(y,x,k) for k,(y,x) in zip(range(len(self.df)),[(r.lat,r.lon) for r in self.df.itertuples()])]
  self.df['pressure']=[val(r.lat,r.lon,0) for r in self.df.itertuples()]
  self.df['u10']=[r.lat*2.+r.lon for r in self.df.itertuples()]
  self.run_convert();csv_out=Path(self.a.output_dir);ref_p=m._read_owi_values(csv_out/'fort.221');ref_w=m._read_owi_values(csv_out/'fort.222')
  self.a.output_dir=str(self.r/'out_era');self.a.format='era5_nc'
  with nc.Dataset(self.src/'x.nc','w') as d:
   for k,n in [('time',27),('latitude',2),('longitude',2)]:d.createDimension(k,n)
   t=d.createVariable('time','f8',('time',));t.units='hours since 2000-12-31 23:00:00';t[:]=np.arange(27)
   lats,lons=[1.5,1.],[2.5,2.]
   for k,v in [('latitude',lats),('longitude',lons)]:d.createVariable(k,'f8',(k,))[:]=v
   grid=lambda f:np.array([[[f(y,x) for x in lons] for y in lats]]*27)
   for k,u,f in [('u10','m s**-1',lambda y,x:y*2.+x),('v10','m s**-1',lambda y,x:90.),('msl','Pa',lambda y,x:val(y,x,0)*100.)]:
    x=d.createVariable(k,'f8',('time','latitude','longitude'));x.units=u;x[:]=grid(f)
  (self.src/'source.csv').unlink()
  m.process(self.a);p=Path(self.a.output_dir)
  np.testing.assert_allclose(m._read_owi_values(p/'fort.221'),ref_p)
  np.testing.assert_allclose(m._read_owi_values(p/'fort.222'),ref_w)
  self.assertGreater(len(set(np.round(ref_p,3))),1)
 def test_era_surface_pressure_not_silently_used(self):
  self.era(pressure='sp')
  with self.assertRaises(ValueError):m.process(self.a)
 def test_era_masked_values_rejected(self):
  self.era(gap=True)
  with self.assertRaises(ValueError):m.process(self.a)
 def test_era_units_required(self):
  self.era(units='unknown')
  with self.assertRaises(ValueError):m.process(self.a)
if __name__=='__main__':unittest.main()
