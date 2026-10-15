"""Artificial source fixtures; native tracer uses original FLUXNET records."""
import importlib.util,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np,pandas as pd
spec=importlib.util.spec_from_file_location('climate',Path(os.environ.get('KI_UNDER_TEST',Path(__file__).resolve().parents[1]))/'tools/s4_climate_prep/convert_forcing_to_ldndc_climate.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class Contract(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.r=Path(self.tmp.name)
  ts=pd.date_range('2001-01-01','2002-01-01',freq='h',inclusive='left');temp=np.tile(np.arange(24)-5.,365)
  self.df=pd.DataFrame({'TIMESTAMP_START':ts.strftime('%Y%m%d%H%M'),'TIMESTAMP_END':(ts+pd.Timedelta(hours=1)).strftime('%Y%m%d%H%M'),'TA_F_MDS':temp,'P_F':.0001,'SW_IN_F':1.,'WS_F':0.})
  m.FORCING_SOURCE='fluxnet_fullset';m.FORCING_PATH=str(self.r/'FULLSET_HR.csv');m.START_DATE='2001-01-01';m.END_DATE='2001-12-31';m.LAT=40.;m.LON=10.;m.ELEVATION='200';m.OUTPUT_PATH=str(self.r/'climate.txt')
 def convert(self):
  self.df.to_csv(m.FORCING_PATH,index=False);return m.process()
 def values(self):
  lines=Path(m.OUTPUT_PATH).read_text().split('%data\n')[1].splitlines();return np.array([[float(x) for x in l.split()] for l in lines[1:] if l.strip()])
 def test_hourly_extrema_and_totals_are_actual(self):
  self.convert();a=self.values();self.assertEqual(a.shape,(365,6));np.testing.assert_allclose(a[:,0],.0024,atol=1e-15);np.testing.assert_equal(a[:,1],6.5);np.testing.assert_equal(a[:,2],18.);np.testing.assert_equal(a[:,3],-5.);np.testing.assert_equal(a[:,5],0.)
 def test_missing_field_or_cell_fails_before_output(self):
  for k in ['TA_F_MDS','P_F','SW_IN_F','WS_F']:
   orig=self.df[k].copy();self.df.loc[17,k]=-9999
   with self.subTest(field=k),self.assertRaises(ValueError):self.convert()
   self.df[k]=orig
 def test_nonfinite_and_negative_not_clipped(self):
  for k,v in [('TA_F_MDS',np.nan),('P_F',-.1),('SW_IN_F',np.inf),('WS_F',-.1)]:
   old=self.df.loc[2,k];self.df.loc[2,k]=v
   with self.subTest(field=k),self.assertRaises(ValueError):self.convert()
   self.df.loc[2,k]=old
 def test_missing_duplicate_and_shifted_intervals_fail(self):
  base=self.df.copy()
  for df in [base.drop(index=8),pd.concat([base,base.iloc[:1]]),base.iloc[24:]]:
   self.df=df
   with self.subTest(rows=len(df)),self.assertRaises(ValueError):self.convert()
 def test_interval_end_must_match(self):
  self.df.loc[2,'TIMESTAMP_END']=self.df.loc[3,'TIMESTAMP_END']
  with self.assertRaises(ValueError):self.convert()
 def test_daily_day_night_means_not_used_as_extrema(self):
  self.df=pd.DataFrame({'TIMESTAMP':pd.date_range('2001-01-01','2001-12-31').strftime('%Y%m%d'),'TA_F_MDS':10.,'TA_F_MDS_DAY':12.,'TA_F_MDS_NIGHT':8.,'P_F':0.,'SW_IN_F':1.,'WS_F':1.});m.FORCING_PATH=str(self.r/'FULLSET_DD.csv')
  with self.assertRaises(ValueError):self.convert()
 def test_partial_year_does_not_get_jan1_header(self):
  m.START_DATE='2001-02-01'
  with self.assertRaises(ValueError):self.convert()
 def test_invalid_inputs_preserve_existing_file(self):
  Path(m.OUTPUT_PATH).write_text('previous');self.df.loc[4,'P_F']=np.nan
  with self.assertRaises(ValueError):self.convert()
  self.assertEqual(Path(m.OUTPUT_PATH).read_text(),'previous')
 def test_shared_daily_calendar_extrema_and_missing_data(self):
  m.FORCING_SOURCE='cmfd';n=365;d={'dates':pd.date_range('2001-01-01','2001-12-31'),'precip_mm':np.zeros(n),'temp_mean_c':np.ones(n)*10,'temp_max_c':np.ones(n)*15,'temp_min_c':np.ones(n)*5,'srad_wm2':np.ones(n),'wind_ms':np.ones(n)}
  with patch.object(m,'_load_via_ki_tools_common',return_value=d):
   d['temp_min_c'][0]=20
   with self.assertRaises(ValueError):m.process()
   d['temp_min_c'][0]=5;d['dates']=d['dates'][::-1]
   with self.assertRaises(ValueError):m.process()
 def test_missing_or_bad_elevation_stops(self):
  for bad in [None,'','nan','abc']:
   m.ELEVATION=bad
   with self.subTest(elevation=bad),self.assertRaisesRegex(ValueError,'elevation'):self.convert()
 def test_elevation_written_to_attributes(self):
  self.convert();self.assertIn('elevation = "200"',Path(m.OUTPUT_PATH).read_text())
 def test_validator_checks_values_and_exact_count(self):
  self.convert();p=Path(m.OUTPUT_PATH);s=p.read_text();p.write_text(s+'0 1 2 0 1 1\n')
  with self.assertRaises(ValueError):m.validate_outputs(p,365,.876)
 def test_original_fluxnet_dd_name_resolves_to_hh_sibling(self):
  dd=self.r/'FLX_CN-Din_FLUXNET2015_FULLSET_DD_2001-2001_1-4.csv';hh=self.r/'FLX_CN-Din_FLUXNET2015_FULLSET_HH_2001-2001_1-4.csv'
  pd.DataFrame({'TIMESTAMP':['20010101'],'TA_F_MDS':[1.]}).to_csv(dd,index=False);self.df.to_csv(hh,index=False)
  self.assertEqual(m._resolve_substep_path(dd),hh);m.FORCING_PATH=str(dd);m.process()
  import json;self.assertEqual(json.loads(Path(m.OUTPUT_PATH+'.provenance.json').read_text())['source_path'],str(hh.resolve()))
 def test_dd_name_without_sibling_fails(self):
  dd=self.r/'FLX_CN-Din_FLUXNET2015_FULLSET_DD_2001-2001_1-4.csv';dd.write_text('TIMESTAMP\n')
  with self.assertRaisesRegex(ValueError,'not extrema'):m._resolve_substep_path(dd)
 def test_failed_sidecar_publish_keeps_previous_pair(self):
  out=Path(m.OUTPUT_PATH);side=Path(m.OUTPUT_PATH+'.provenance.json');out.write_text('old climate');side.write_text('old prov')
  real=os.replace
  def flaky(src,dst):
   if Path(src).name.startswith('.climate-prov-'):raise PermissionError('sidecar unwritable')
   return real(src,dst)
  with patch.object(m.os,'replace',side_effect=flaky),self.assertRaises(PermissionError):self.convert()
  self.assertEqual(out.read_text(),'old climate');self.assertEqual(side.read_text(),'old prov')
  self.assertEqual(sorted(p.name for p in self.r.iterdir()),sorted(['FULLSET_HR.csv','climate.txt','climate.txt.provenance.json']))
 def test_failed_first_publish_leaves_nothing(self):
  real=os.replace
  def flaky(src,dst):
   if Path(src).name.startswith('.climate-prov-'):raise PermissionError('sidecar unwritable')
   return real(src,dst)
  with patch.object(m.os,'replace',side_effect=flaky),self.assertRaises(PermissionError):self.convert()
  self.assertFalse(Path(m.OUTPUT_PATH).exists());self.assertFalse(Path(m.OUTPUT_PATH+'.provenance.json').exists())
 def test_sidecar_hash_matches_published_climate(self):
  import hashlib,json;self.convert()
  self.assertEqual(json.loads(Path(m.OUTPUT_PATH+'.provenance.json').read_text())['output_sha256'],hashlib.sha256(Path(m.OUTPUT_PATH).read_bytes()).hexdigest())
 def test_standalone_validator_accepts_native_output(self):
  import subprocess,sys,json;self.convert()
  v=Path(spec.origin).with_name('validate_climate_file.py')
  r=subprocess.run([sys.executable,str(v),m.OUTPUT_PATH],capture_output=True,text=True);self.assertEqual(r.returncode,0,r.stderr)
  res=json.loads(r.stdout);self.assertEqual(res['columns'],['prec','tavg','tmax','tmin','grad','wind']);self.assertEqual(res['rows'],365)
  bad=self.r/'bad.txt';bad.write_text('%global\n\ttime = "2001-01-01/1"\n')
  self.assertEqual(subprocess.run([sys.executable,str(v),str(bad)],capture_output=True).returncode,3)
 def test_failed_restore_keeps_backup_and_names_it(self):
  out=Path(m.OUTPUT_PATH);side=Path(m.OUTPUT_PATH+'.provenance.json');out.write_text('old climate');side.write_text('old prov')
  real=os.replace
  def flaky(src,dst):
   n=Path(src).name
   if n.startswith('.climate-prov-'):raise PermissionError('sidecar unwritable')
   if n.startswith('.climate-bak-') and Path(dst)==out:raise PermissionError('restore blocked')
   return real(src,dst)
  with patch.object(m.os,'replace',side_effect=flaky),self.assertRaisesRegex(OSError,'previous file kept at') as cm:self.convert()
  kept=[p for p in self.r.iterdir() if p.name.startswith('.climate-bak-')]
  self.assertEqual(len(kept),1);self.assertEqual(kept[0].read_text(),'old climate');self.assertIn(str(kept[0]),str(cm.exception))
  self.assertEqual(side.read_text(),'old prov')
if __name__=='__main__':unittest.main()
