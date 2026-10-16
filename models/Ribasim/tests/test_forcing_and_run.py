"""Contract regressions. Artificial inputs/processes are not model simulations."""
import contextlib,importlib.util,io,json,os,sqlite3,subprocess,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
import pandas as pd
import xarray as xr
KI=Path(os.environ.get('KI_UNDER_TEST',Path(__file__).resolve().parents[1]))
def module(name):
 s=importlib.util.spec_from_file_location(name,KI/'tools'/f'{name}.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
b=module('build_network');r=module('run_ribasim')
FIELDS=['precipitation','potential_evaporation','drainage','infiltration','surface_runoff']
class ForcingTests(unittest.TestCase):
 def test_invalid_forcing(self):
  for frame in [pd.DataFrame({'node_id':[1]}),pd.DataFrame({'node_id':[1],'rainfall':[0]}),pd.DataFrame({'node_id':[],'precipitation':[]}),pd.DataFrame({'node_id':[1],'precipitation':[np.nan]}),pd.DataFrame({'node_id':[1],'precipitation':[np.inf]}),pd.DataFrame({'node_id':[1],'precipitation':['oops']}),pd.DataFrame({'node_id':[1],'precipitation':[-1e-8]}),pd.DataFrame({'node_id':[1.5],'precipitation':[0]})]:
   with self.subTest(frame=frame.to_dict()):self.assertTrue(b.validate_param_table('basin_static',frame))
 def test_time_errors(self):
  for times,values in [(['bad'],[0]),(['2020-01-02','2020-01-01'],[0,0]),(['2020-01-01']*2,[0,0]),(['2020-01-01','2020-01-02'],[0,np.nan])]:
   with self.subTest(times=times,values=values):self.assertTrue(b.validate_param_table('basin_time',pd.DataFrame({'node_id':[1]*len(times),'time':times,'precipitation':values})))
 def test_zero_forcing_and_optional_schema_nulls(self):
  df=pd.DataFrame({'node_id':[1],'precipitation':[0.]});self.assertEqual(b.validate_param_table('basin_static',df),[])
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'test.sqlite';b.write_param_table(p,'basin_static',df)
   with sqlite3.connect(p) as c:
    row=c.execute('SELECT precipitation, potential_evaporation FROM "Basin / static"').fetchone()
   self.assertEqual(row,(0.,None))
 def test_writer_refuses_invalid_table(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'test.sqlite'
   with self.assertRaises(ValueError):b.write_param_table(p,'basin_static',pd.DataFrame({'node_id':[1],'precipitaion':[0]}))
   self.assertFalse(p.exists())
 def test_effective_forcing_coverage(self):
  nodes=pd.DataFrame({'node_id':[1,2,3],'node_type':['Basin','Terminal','Basin']})
  static=pd.DataFrame({'node_id':[3],'precipitation':[0.]})
  timed=pd.DataFrame({'node_id':[1,1],'time':['2020-01-01','2020-01-03'],'precipitation':[0.,1e-8]})
  tables=[('basin_static',static),('basin_time',timed)]
  self.assertEqual(b.validate_basin_forcing(nodes,tables,'2020-01-01','2020-01-03'),[])
  for bad in [tables[:1],[tables[0],('basin_time',timed.assign(node_id=2))],[tables[0],('basin_time',timed.iloc[:1])],[('basin_static',pd.concat([static,static.assign(node_id=1)])),tables[1]]]:
   with self.subTest(tables=str(bad)):self.assertTrue(b.validate_basin_forcing(nodes,bad,'2020-01-01','2020-01-03'))

 def test_cyclic_forcing(self):
  nodes=pd.DataFrame({'node_id':[1],'node_type':['Basin'],'cyclic_time':[True]})
  timed=pd.DataFrame({'node_id':[1]*3,'time':['2020-01-01','2020-01-02','2020-01-03'],'precipitation':[1e-8,2e-8,1e-8]})
  self.assertEqual(b.validate_basin_forcing(nodes,[('basin_time',timed)],'2020-01-01','2020-01-10'),[])
  self.assertTrue(b.validate_basin_forcing(nodes.assign(cyclic_time=False),[('basin_time',timed)],'2020-01-01','2020-01-10'))
  self.assertTrue(b.validate_basin_forcing(nodes,[('basin_time',timed.assign(precipitation=[1e-8,2e-8,3e-8]))],'2020-01-01','2020-01-10'))
  self.assertTrue(b.validate_basin_forcing(nodes,[('basin_time',timed.iloc[:1])],'2020-01-01','2020-01-10'))
  us=timed.assign(time=['1/9/2020','1/10/2020','1/11/2020'])
  self.assertEqual(b.validate_basin_forcing(nodes,[('basin_time',us)],'2020-01-09','2020-01-20'),[])
  self.assertTrue(b.validate_basin_forcing(nodes,[('basin_time',us.assign(precipitation=[1e-8,1e-8,2e-8]))],'2020-01-09','2020-01-20'))
 def test_cyclic_time_parsing(self):
  df=pd.DataFrame({'node_id':[1,2,3,4],'cyclic_time':['False','true',0,1]})
  flags,errs=b.parse_cyclic_time(df);self.assertEqual(errs,[]);self.assertEqual(list(flags),[False,True,False,True])
  self.assertTrue(b.parse_cyclic_time(pd.DataFrame({'node_id':[1],'cyclic_time':[np.nan]}))[1])
  self.assertTrue(b.parse_cyclic_time(pd.DataFrame({'node_id':[1],'cyclic_time':['maybe']}))[1])
  gdf=b.build_node_geodataframe(pd.DataFrame({'node_id':[1],'node_type':['Basin'],'x':[0.],'y':[0.],'cyclic_time':['False']}),'EPSG:28992')
  self.assertFalse(bool(gdf.cyclic_time.iloc[0]))

class BatchTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.paths=[]
  for name in ['a','b']:
   d=self.root/name;d.mkdir();(d/'results').mkdir();p=d/'ribasim.toml';p.write_text('starttime = 2020-01-01T00:00:00\nendtime = 2020-01-02T00:00:00\ncrs = "EPSG:28992"\nresults_dir = "results"\n');self.paths.append(p);self.outputs(p)
  self.batch=self.root/'models.txt';self.batch.write_text('\n'.join(map(str,self.paths)))
  self.args=SimpleNamespace(toml_batch_file=str(self.batch),skip_preflight=True,ribasim_bin='/bin/false',threads=1,timeout=1)
 def outputs(self,p,only=None,times=('2020-01-01',)):
  # Native Ribasim: one row per saveat interval, labelled by its start; the
  # end time is not a row. A 1-day daily run therefore has ONE time row.
  for f in only or ['basin.nc','flow.nc','basin_state.nc']:
   if f=='basin_state.nc':ds=xr.Dataset({'level':('node_id',[1.])},coords={'node_id':[1]})
   else:ds=xr.Dataset({'level':('time',[1.]*len(times))},coords={'time':pd.to_datetime(list(times))})
   ds.to_netcdf(p.parent/'results'/f,engine='h5netcdf')
 def run_case(self,rc=0,refresh=(),timeout=False):
  def execute(*a,**kw):
   for index,files in refresh:self.outputs(self.paths[index],files)
   if timeout:raise subprocess.TimeoutExpired(['test'],1,output=b'partial',stderr=b'timed out')
   return subprocess.CompletedProcess(['test'],rc,'test stdout','test stderr')
  with patch.object(r.subprocess,'run',side_effect=execute),contextlib.redirect_stdout(io.StringIO()):
   try:r.run_batch(self.args);code=0
   except SystemExit as e:code=e.code
  return code,json.loads((self.root/'batch_run_report.json').read_text())
 def test_nonzero_exit_cannot_reuse_old_outputs(self):
  code,report=self.run_case(rc=2);self.assertNotEqual(code,0);self.assertEqual(report['n_success'],0);self.assertFalse(report['success']);self.assertIn('test stderr',report['stderr_tail'])
 def test_zero_exit_stale_outputs_fail(self):
  code,report=self.run_case();self.assertNotEqual(code,0);self.assertEqual(report['n_success'],0)
 def test_partial_and_partly_stale_fail(self):
  for refresh in [[(0,None)],[(0,None),(1,['basin.nc'])]]:
   with self.subTest(refresh=refresh):
    code,report=self.run_case(refresh=refresh);self.assertNotEqual(code,0);self.assertEqual(report['n_success'],1)
 def test_timeout_even_with_new_outputs_fails(self):
  code,report=self.run_case(refresh=[(0,None),(1,None)],timeout=True);self.assertNotEqual(code,0);self.assertEqual(report['n_success'],0)
 def test_single_run_rejects_old_results(self):
  with contextlib.redirect_stdout(io.StringIO()),patch('sys.argv',['run_ribasim.py','--toml_path',str(self.paths[0]),'--ribasim_bin','/bin/true','--skip_preflight']):
   with self.assertRaises(SystemExit) as error:r.main()
  self.assertEqual(error.exception.code,1)
  self.assertFalse(json.loads((self.paths[0].parent/'run_report.json').read_text())['success'])
 def test_expected_steps_from_config(self):
  import datetime as dt
  c={'starttime':dt.datetime(2020,1,1),'endtime':dt.datetime(2020,1,2)}
  self.assertEqual(r.expected_output_steps(c),1)
  self.assertEqual(r.expected_output_steps({**c,'endtime':dt.datetime(2020,1,11)}),10)
  self.assertEqual(r.expected_output_steps({**c,'solver':{'saveat':3600}}),24)
  self.assertEqual(r.expected_output_steps({**c,'endtime':dt.datetime(2020,1,2,12),'solver':{'saveat':86400}}),2)
  self.assertEqual(r.expected_output_steps({**c,'solver':{'saveat':float('inf')}}),1)
  self.assertIsNone(r.expected_output_steps({**c,'solver':{'saveat':0}}))
 def test_one_interval_run_valid(self):
  with contextlib.redirect_stdout(io.StringIO()):self.assertEqual(r.validate_output(self.paths[0]),[])
 def test_short_or_empty_time_axis_fails(self):
  p=self.paths[0];p.write_text(p.read_text().replace('2020-01-02T00','2020-01-03T00'))
  with contextlib.redirect_stdout(io.StringIO()):errs=r.validate_output(p)
  self.assertTrue(any('give 2' in e for e in errs),errs)
  self.outputs(p,times=())
  with contextlib.redirect_stdout(io.StringIO()):errs=r.validate_output(p)
  self.assertTrue(any('no timesteps' in e for e in errs),errs)
 def test_corrupt_outputs_fail(self):
  for f in ['flow.nc','basin_state.nc']:
   with self.subTest(f=f):
    self.outputs(self.paths[0]);(self.paths[0].parent/'results'/f).write_bytes(b'x'*500)
    with contextlib.redirect_stdout(io.StringIO()):errs=r.validate_output(self.paths[0])
    self.assertTrue(any(('Cannot read '+f) in e for e in errs),errs)
 def test_damaged_data_chunk_fails(self):
  # intact header, damaged compressed chunk: only reading the values finds it
  p=self.paths[0];f=p.parent/'results'/'flow.nc'
  import h5py
  ds=xr.Dataset({'flow_rate':(('link_id','time'),np.random.default_rng(0).random((4096,1)))},coords={'time':pd.to_datetime(['2020-01-01']),'link_id':np.arange(4096)})
  ds.to_netcdf(f,engine='h5netcdf',encoding={'flow_rate':{'zlib':True,'chunksizes':(4096,1)}})
  with h5py.File(f,'r') as h:off=h['flow_rate'].id.get_chunk_info(0).byte_offset
  raw=bytearray(f.read_bytes());raw[off+10:off+60]=b'\xff'*50;f.write_bytes(bytes(raw))
  with contextlib.redirect_stdout(io.StringIO()):errs=r.validate_output(p)
  self.assertTrue(any('Cannot read flow.nc' in e for e in errs),errs)
 def test_failed_single_run_replaces_old_success_report(self):
  rep=self.paths[0].parent/'run_report.json';rep.write_text(json.dumps({'success':True}))
  for binary in ['/bin/false','/nonexistent/ribasim']:
   with self.subTest(binary=binary):
    rep.write_text(json.dumps({'success':True}))
    with contextlib.redirect_stdout(io.StringIO()),patch('sys.argv',['run_ribasim.py','--toml_path',str(self.paths[0]),'--ribasim_bin',binary,'--skip_preflight']):
     with self.assertRaises(SystemExit) as error:r.main()
    self.assertNotEqual(error.exception.code,0)
    self.assertFalse(json.loads(rep.read_text())['success'])
 def test_single_run_timeout_replaces_old_success_report(self):
  rep=self.paths[0].parent/'run_report.json';rep.write_text(json.dumps({'success':True}))
  with patch.object(r.subprocess,'run',side_effect=subprocess.TimeoutExpired(['x'],1)),contextlib.redirect_stdout(io.StringIO()),patch('sys.argv',['run_ribasim.py','--toml_path',str(self.paths[0]),'--ribasim_bin','/bin/true','--skip_preflight']):
   with self.assertRaises(SystemExit) as error:r.main()
  self.assertEqual(error.exception.code,1)
  report=json.loads(rep.read_text());self.assertFalse(report['success']);self.assertIn('Timeout',report['stderr_tail'])
 def test_all_fresh_success(self):
  code,report=self.run_case(refresh=[(0,None),(1,None)]);self.assertEqual(code,0);self.assertEqual(report['n_success'],2);self.assertTrue(report['success'])

if __name__=='__main__':unittest.main()
