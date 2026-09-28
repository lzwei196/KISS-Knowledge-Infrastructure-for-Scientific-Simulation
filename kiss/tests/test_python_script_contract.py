import hashlib,json
from pathlib import Path
import subprocess,tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from kiss_cli import python_script,runnable,install
from kiss_cli.manifest import Manifest,Acquire

class PythonScriptContractTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.root=Path(self.tmp.name)
  self.ki=SimpleNamespace(name='HEC_HMS',root=self.root/'ki',meta={'impl_id':'hec-hms-python-equiv','language':'python'})
  self.script=self.ki.root/'tools/run_hec_hms.py';self.script.parent.mkdir(parents=True)
  self.script.write_text('print("usage: run_hec_hms.py")\n')
  self.contract=dict(implementation_id='hec-hms-python-equiv',path='tools/run_hec_hms.py',sha256=hashlib.sha256(self.script.read_bytes()).hexdigest())
  self.cfg=SimpleNamespace(root=self.root,python='python')
  self.man=Manifest('HEC_HMS',python_script=self.contract,python_deps=['numpy'],acquire=Acquire('bundled',produces=self.contract['path']))
 def probe(self,code=0,timed=False,create=False,workspace=True):
  def run(argv,**kw):
   if '-c' in argv:return subprocess.CompletedProcess(argv,0,json.dumps([str(self.root/'venv') if workspace else '/outside','/base']),'')
   self.assertEqual(argv[-1],'--help');self.assertEqual(kw['stdin'],subprocess.DEVNULL)
   if create:(Path(kw['cwd'])/'unexpected').touch()
   if timed:raise subprocess.TimeoutExpired(argv,1)
   return subprocess.CompletedProcess(argv,code,'usage: run_hec_hms.py','')
  with patch.object(python_script.subprocess,'run',side_effect=run):return python_script.check(runnable.Verdict('HEC_HMS'),self.ki,self.contract,self.cfg,'python')
 def test_clean_help_variant_only(self):
  v=self.probe();self.assertTrue(v.usable,v.detail);self.assertEqual(v.installation_scope,'declared-python-variant');self.assertFalse(v.official_upstream_verified)
 def test_bad_exit_timeout_files_and_outside_python(self):
  for kw in [dict(code=2),dict(code=-11),dict(timed=True),dict(create=True),dict(workspace=False)]:
   with self.subTest(kw=kw):self.assertFalse(self.probe(**kw).usable)
 def test_hash_identity_and_symlink(self):
  self.script.write_text('replacement')
  with self.assertRaisesRegex(ValueError,'SHA256 mismatch'):python_script.resolve(self.ki,self.contract)
  self.ki.meta['impl_id']='official-hec-hms'
  with self.assertRaisesRegex(ValueError,'metadata'):python_script.resolve(self.ki,self.contract)
  self.ki.meta['impl_id']='hec-hms-python-equiv';self.script.unlink();self.script.symlink_to('/bin/sh')
  with self.assertRaisesRegex(ValueError,'Symlink'):python_script.resolve(self.ki,self.contract)
 def test_path_and_missing_context(self):
  self.contract['path']='../python'
  with self.assertRaises(ValueError):python_script.resolve(self.ki,self.contract)
  step,binary=install.acquire(self.man,self.root/'binaries','python');self.assertFalse(step.ok);self.assertIsNone(binary)
 def test_bundled_ki_context(self):
  step,binary=install.acquire(self.man,self.root/'binaries','python',ki=self.ki);self.assertTrue(step.ok);self.assertEqual(binary,self.script)
 def test_manifest_imports_when_preflight_empty(self):
  with patch.object(runnable,'declared_imports',return_value=[]),patch.object(runnable,'select_python',return_value='python'),patch.object(runnable,'missing_imports',return_value=['numpy']) as check,patch.object(python_script,'check',side_effect=lambda v,*a:v):v=runnable.check(self.ki,self.man,python='python')
  self.assertFalse(v.usable);self.assertEqual(check.call_args.args[0],['numpy'])
