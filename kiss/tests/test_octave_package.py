import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from kiss_cli import api, execution, octpackage, runnable

CLASSES=[f'm_{i:02d}_fixture' for i in range(1,48)]
FILES={'MARRMoT/Models/Model files/'+n+'.m':hashlib.sha256(n.encode()).hexdigest() for n in CLASSES+['MARRMoT_model']}
C=dict(runtime='runtime/bin/octave-cli',source='source',package_registry_root='packages',classes=CLASSES,source_files=FILES,packages=dict(optim='1.6.3',statistics='1.7.7',struct='1.0.18'))


def fixture(root):
    for rel in ['runtime/bin/octave-cli','packages/package-list','packages/optim/native.oct']:
        p=root/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'native test fixture')
    for rel in FILES:
        p=root/'source'/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(p.stem)
    script=root/'probe.m';script.write_text(octpackage.PROBE)
    return script


def output(root):
    return '\n'.join(['NATIVE_OK '+str(root/'packages/optim/native.oct'),*[f'CLASS_OK {n} '+str(root/'source/MARRMoT/Models/Model files'/(n+'.m')) for n in CLASSES],octpackage.MARK])+'\n'


class OctavePackageTests(unittest.TestCase):
    def test_fixed_script_guard_rejects_code_and_extra_flags(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve();script=fixture(root)
            args=octpackage.probe_args(script,root/'source',root/'packages',C)
            api._guard_installation_only_command(['octave-cli',*args],root,root)
            for bad in [['--eval','model_fun()'],[*args,'--persist'],['model.m'],args[:4]+['/tmp/outside.m']+args[5:]]:
                with self.subTest(bad=bad),self.assertRaises(api.ToolError):
                    api._guard_installation_only_command(['octave-cli',*bad],root,root)
            script.write_text(octpackage.PROBE+'\nmodel_fun();')
            with self.assertRaises(api.ToolError):api._guard_installation_only_command(['octave-cli',*args],root,root)
    def test_complete_class_and_hash_contract_required(self):
        bads=[{**C,'classes':CLASSES[:-1]},{**C,'classes':CLASSES[:-1]+[CLASSES[0]]},
              {**C,'source_files':{}},{**C,'source':'../escape'},{**C,'runtime':'/usr/bin/octave-cli'},
              {**C,'packages':dict(optim='latest',statistics='1.7.7',struct='1.0.18')}]
        for c in bads:
            with self.subTest(c=c),self.assertRaises(ValueError):octpackage.validate(c)
    def test_source_tampering_rejected_before_launch(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve();fixture(root)
            (root/'source'/next(iter(FILES))).write_text('changed model source')
            with patch.object(runnable,'_file_kind',return_value='macho'),patch.object(runnable.subprocess,'run') as run,patch.object(runnable.platform,'system',return_value='Darwin'):
                v=runnable._check_octave_package(runnable.Verdict('MARRMoT'),C,SimpleNamespace(root=root),25,{})
                self.assertFalse(v.usable);self.assertIn('checksum mismatch',v.detail);run.assert_not_called()
    def test_native_complete_receipt_required_and_empty_cwd(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve();fixture(root);good=output(root)
            for rc,out,ok in [(0,good,True),(0,'Octave10.3.0\n',False),(-11,good,False),(1,good,False),(0,octpackage.MARK+'\n',False),(0,good.replace('CLASS_OK '+CLASSES[0]+' ', 'CLASS_OK unexpected '),False),(0,good.replace(str(root/'packages/optim/native.oct'),'/tmp/escape.oct'),False),(0,good.replace(str(root/'source/MARRMoT/Models/Model files'/(CLASSES[0]+'.m')),str(root/'wrong.m')),False)]:
                with self.subTest(rc=rc,out=out[:80]),patch.object(runnable,'_file_kind',return_value='macho'),patch.object(runnable.platform,'system',return_value='Darwin'),patch.object(runnable.subprocess,'run',return_value=subprocess.CompletedProcess([],rc,out,'')) as run:
                    v=runnable._check_octave_package(runnable.Verdict('MARRMoT'),C,SimpleNamespace(root=root),25,{'TEST_API_KEY':'must-not-pass','OCTAVE_PATH':'/tmp/wrong'})
                    self.assertEqual(v.usable,ok)
                    kw=run.call_args.kwargs;self.assertEqual(kw['stdin'],subprocess.DEVNULL)
                    self.assertEqual(kw['env']['OCTAVE_HOME'],str(root/'runtime'))
                    self.assertNotIn('TEST_API_KEY',kw['env']);self.assertNotIn('OCTAVE_PATH',kw['env'])
                    self.assertEqual(kw['timeout'],25)
    def test_symlink_source_escape_rejected(self):
        with tempfile.TemporaryDirectory() as d,tempfile.TemporaryDirectory() as other:
            root=Path(d).resolve();fixture(root);p=root/'source'/next(iter(FILES));outside=Path(other)/p.name;outside.write_text(p.read_text());p.unlink();p.symlink_to(outside)
            with self.assertRaises(ValueError):octpackage.verify_source(root/'source',C,root)
    def test_setup_api_accepts_exact_probe(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve();script=fixture(root);cfg=SimpleNamespace(root=root,roles={'binaries':root/'binaries'},python=sys.executable)
            with patch.object(execution,'run_process',return_value=execution.ProcessRun('succeeded',0,'ok','')):
                result=api.execute_tool('run_setup_command',{'argv':['octave-cli',*octpackage.probe_args(script,root/'source',root/'packages',C)]},SimpleNamespace(root=root/'ki'),cfg,setup_mode=True,setup_context={'installation_only':True})
                self.assertIn('exit_code=0',result)
