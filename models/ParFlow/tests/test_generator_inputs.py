"""Artificial PFB fixtures test the generator contract, not hydrological skill."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import numpy as np
from parflow.tools.io import read_pfb, write_pfb

KI=Path(os.environ.get('KI_UNDER_TEST',Path(__file__).resolve().parents[1]))
spec=importlib.util.spec_from_file_location('generator',KI/'tools/s7_solver/generate_parflow_script.py')
g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g)

class GeneratorTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
  self.domain=self.root/'domain.json';self.domain.write_text(json.dumps({'grid':{'nx':2,'ny':2,'nz':2,'dx':10.,'dy':10.,'dz_layers_m':[1.,1.],'total_depth_m':2.}}))
  self.args=dict(domain_json=str(self.domain),run_name='test',output_dir=str(self.root/'out'),start_date='2000-01-01',end_date='2000-01-02',enable_clm=False,homogeneous_default_soil=True)
  for key,shape in [('ic_pfb',(2,2,2)),('slope_x_pfb',(1,2,2)),('slope_y_pfb',(1,2,2))]:
   path=self.root/(key+'.pfb');write_pfb(str(path),np.zeros(shape,dtype=np.float64),dx=10,dy=10,dz=1,dist=False);self.args[key]=str(path)
  # Fixture install (bin/parflow) so negative tests fail on the input they test, not on the install.
  pf=self.root/'pf';(pf/'bin').mkdir(parents=True);(pf/'bin'/'parflow').write_text('');self.args['parflow_dir']=str(pf)
 def fail_without_output(self,args,msg=None):
  with self.assertRaises((ValueError,FileNotFoundError)) as cm:g.process(**args)
  self.assertNotIn('ParFlow install not found',str(cm.exception))
  if msg:self.assertRegex(str(cm.exception),msg)
  self.assertFalse((self.root/'out').exists())
 def test_missing_required_inputs(self):
  for missing in [('ic_pfb',),('slope_x_pfb',),('slope_y_pfb',),('slope_x_pfb','slope_y_pfb')]:
   with self.subTest(missing=missing):self.fail_without_output({k:v for k,v in self.args.items() if k not in missing},msg=missing[0])
 def test_missing_path_does_not_overwrite_script(self):
  out=self.root/'out';out.mkdir();p=out/'run_test.py';p.write_text('previous valid script')
  with self.assertRaisesRegex((ValueError,FileNotFoundError),'ic_pfb'):g.process(**dict(self.args,ic_pfb=str(self.root/'absent.pfb')))
  self.assertEqual(p.read_text(),'previous valid script')
  self.assertEqual(list(out.iterdir()),[p])
 def test_bad_pfb(self):
  p=self.root/'invalid.pfb'
  for data in [None,np.zeros((1,1,1)),np.full((2,2,2),np.nan),np.full((2,2,2),np.inf)]:
   with self.subTest(data=str(data)):
    if data is None:p.write_bytes(b'invalid')
    else:write_pfb(str(p),data,dx=10,dy=10,dz=1,dist=False)
    self.fail_without_output(dict(self.args,ic_pfb=str(p)))
 def test_auxiliary_pair_and_clm_fail_before_writes(self):
  p=self.root/'params.json';p.write_text('{}')
  for extra in [dict(texture_params=str(p)),dict(indicator_pfb=self.args['ic_pfb']),dict(enable_clm=True),dict(enable_clm=True,clm_dir=str(self.root))]:
   with self.subTest(extra=extra):self.fail_without_output(dict(self.args,**extra))
 def test_valid_zero_slopes_and_initial_pressure_preserved(self):
  result=g.process(**self.args);self.assertEqual(result['status'],'success')
  script=Path(result['run_script']).read_text();compile(script,'generated','exec')
  self.assertNotIn('Value = -0.001',script)
  for key,dest in [('ic_pfb','ic_pressure.pfb'),('slope_x_pfb','slope_x.pfb'),('slope_y_pfb','slope_y.pfb')]:
   self.assertEqual(Path(self.args[key]).read_bytes(),(self.root/'out'/dest).read_bytes())
  # Sources already staged at canonical names are safe to reuse.
  a=dict(self.args,ic_pfb=str(self.root/'out/ic_pressure.pfb'),slope_x_pfb=str(self.root/'out/slope_x.pfb'),slope_y_pfb=str(self.root/'out/slope_y.pfb'))
  self.assertEqual(g.process(**a)['status'],'success')
 def test_cli_failure(self):
  cmd=[sys.executable,'-B',str(KI/'tools/s7_solver/generate_parflow_script.py'),'--domain_json',str(self.domain),'--run_name','test','--output_dir',str(self.root/'out'),'--no_clm','--homogeneous_default_soil','--parflow_dir',self.args['parflow_dir']]
  p=subprocess.run(cmd,capture_output=True,text=True);self.assertNotEqual(p.returncode,0);self.assertIn('ic_pfb',p.stderr+p.stdout);self.assertFalse((self.root/'out').exists())

 def test_texture_required_unless_explicit_homogeneous(self):
  self.fail_without_output(dict(self.args,homogeneous_default_soil=False))
  r=g.process(**self.args);prov=json.loads((self.root/'out'/'soil_provenance.json').read_text())
  self.assertIn('HOMOGENEOUS',prov['soil'])
 def test_indicator_value_without_class_fails(self):
  ind=self.root/'ind.pfb';write_pfb(str(ind),np.array([[[1,1],[1,2]],[[1,1],[1,1]]],dtype=np.float64),dx=10,dy=10,dz=1,dist=False)
  tp=self.root/'tp.json';tp.write_text(json.dumps({'1':{'ksat_m_hr':0.01,'porosity':0.4,'sres':0.05,'alpha_1m':2.0,'n':1.5}}))
  with self.assertRaises(ValueError):g.process(**dict(self.args,homogeneous_default_soil=False,texture_params=str(tp),indicator_pfb=str(ind)))
 def test_indicator_non_integer_value_fails(self):
  # 1.49 must not be rounded to class 1.
  ind=self.root/'ind.pfb';write_pfb(str(ind),np.array([[[1,1],[1,1.49]],[[1,1],[1,1]]],dtype=np.float64),dx=10,dy=10,dz=1,dist=False)
  tp=self.root/'tp.json';tp.write_text(json.dumps({'1':{'ksat_m_hr':0.01,'porosity':0.4,'sres':0.05,'alpha_1m':2.0,'n':1.5}}))
  with self.assertRaisesRegex(ValueError,'non-integer'):g.process(**dict(self.args,homogeneous_default_soil=False,texture_params=str(tp),indicator_pfb=str(ind)))
  self.assertFalse((self.root/'out').exists())
 def test_indicator_integer_classes_pass(self):
  ind=self.root/'ind.pfb';write_pfb(str(ind),np.array([[[1,1],[1,2]],[[1,1],[1,2]]],dtype=np.float64),dx=10,dy=10,dz=1,dist=False)
  prm={'ks_m_hr':0.01,'porosity':0.4,'sres':0.05,'alpha_1m':2.0,'n':1.5,'ss_1m':1e-4,'name':'x'}
  tp=self.root/'tp.json';tp.write_text(json.dumps({'1':prm,'2':prm}))
  self.assertEqual(g.process(**dict(self.args,homogeneous_default_soil=False,texture_params=str(tp),indicator_pfb=str(ind)))['status'],'success')

class StagingAndInstallTests(unittest.TestCase):
 setUp=GeneratorTests.setUp;fail_without_output=GeneratorTests.fail_without_output
 def _clm(self):
  clm=self.root/'clm';clm.mkdir()
  for fn in ('drv_clmin.dat','drv_vegm.dat','drv_vegp.dat'):(clm/fn).write_text('x '+fn)
  forc=self.root/'forc';forc.mkdir();(forc/'NLDAS.APCP.000001_to_000024.pfb').write_bytes(b'x')
  return clm,forc
 def test_failed_copy_keeps_old_run(self):
  # First a good run, then new inputs + an unreadable CLM driver: nothing in out may change.
  clm,forc=self._clm()
  ok=dict(self.args,enable_clm=True,clm_dir=str(clm),forcing_dir=str(forc))
  g.process(**ok);out=self.root/'out'
  before={p.name:p.read_bytes() for p in out.iterdir()}
  for key,shape in [('ic_pfb',(2,2,2)),('slope_x_pfb',(1,2,2)),('slope_y_pfb',(1,2,2))]:
   write_pfb(self.args[key],np.full(shape,0.5),dx=10,dy=10,dz=1,dist=False)
  bad=clm/'drv_vegp.dat';bad.chmod(0)
  self.addCleanup(bad.chmod,0o644)
  if os.access(bad,os.R_OK):self.skipTest('running as root: chmod 0 does not block reads')
  with self.assertRaises(OSError):g.process(**dict(ok,run_name='test'))
  self.assertEqual({p.name:p.read_bytes() for p in out.iterdir()},before)
  self.assertEqual([p for p in self.root.iterdir() if '.staging_' in p.name],[])
 def test_template_has_no_install_path_and_renderer_supplies_it(self):
  tmpl=Path(g.TEMPLATE).read_text()
  self.assertIn('{parflow_dir_repr}',tmpl)
  for bad in ('/mnt/'+'disk','/home/'+'server','/media/'+'server'):self.assertNotIn(bad,tmpl)  # split so the desktop port leaves them alone
  fake=Path(self.args['parflow_dir'])
  r=g.process(**self.args)
  script=Path(r['run_script']).read_text()
  self.assertIn('PARFLOW_DIR = os.environ.get("PARFLOW_DIR", %r)'%str(fake),script)
 def test_failure_during_publish_rolls_back(self):
  # The script rename (last step) fails after inputs and provenance were already moved in.
  from unittest import mock
  g.process(**self.args);out=self.root/'out'
  before={p.name:p.read_bytes() for p in out.iterdir()}
  for key,shape in [('ic_pfb',(2,2,2)),('slope_x_pfb',(1,2,2)),('slope_y_pfb',(1,2,2))]:
   write_pfb(self.args[key],np.full(shape,0.5),dx=10,dy=10,dz=1,dist=False)
  real=os.replace
  def flaky(src,dst):
   if os.path.basename(str(dst))=='run_test.py' and '.staging_' in str(src) and '_previous' not in str(src)+str(dst):
    raise PermissionError('simulated: script cannot be replaced')
   return real(src,dst)
  with mock.patch.object(g.os,'replace',side_effect=flaky):
   with self.assertRaises(PermissionError):g.process(**self.args)
  self.assertEqual({p.name:p.read_bytes() for p in out.iterdir()},before)
  self.assertEqual([p for p in self.root.iterdir() if '.staging_' in p.name],[])
 def test_failure_during_first_publish_leaves_no_output(self):
  from unittest import mock
  real=os.replace
  def flaky(src,dst):
   if os.path.basename(str(dst))=='run_test.py':raise PermissionError('simulated')
   return real(src,dst)
  with mock.patch.object(g.os,'replace',side_effect=flaky):
   with self.assertRaises(PermissionError):g.process(**self.args)
  self.assertFalse((self.root/'out').exists())
 def test_run_name_with_path_separator_rejected(self):
  for bad in ['nested/test','..','','a\\b']:
   with self.subTest(bad=bad):self.fail_without_output(dict(self.args,run_name=bad),msg='run_name')
 def test_missing_install_fails_clearly(self):
  with self.assertRaisesRegex(FileNotFoundError,'ParFlow install not found'):
   g.process(**dict(self.args,parflow_dir=str(self.root/'nope')))
  self.assertFalse((self.root/'out').exists())

if __name__=='__main__':unittest.main()
