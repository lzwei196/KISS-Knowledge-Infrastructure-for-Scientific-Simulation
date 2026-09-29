import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from kiss_cli import api, execution, rpackage, runnable

CONTRACT = dict(name='airGR', version='1.7.8', library='library', dll='libs/airGR.so',
                fortran_symbol='frun_gr4j', function='RunModel_GR4J')


class RPackageTests(unittest.TestCase):
    def test_only_install_and_fixed_load_probe_are_allowed(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve()
            valid = [['R', 'CMD', 'INSTALL', '--library='+str(root/'library'), str(root/'source.tar.gz')],
                     ['Rscript', *rpackage.probe_args(root/'library', CONTRACT)]]
            for argv in valid:
                api._guard_installation_only_command(argv, root, root)
            invalid = [['Rscript', '--version'], ['Rscript','model.R'],
                       ['Rscript','-e','library(airGR); RunModel_GR4J()'],
                       ['R','CMD','INSTALL', '--library=/tmp/outside', str(root/'source')],
                       ['R','CMD','INSTALL','--library='+str(root/'lib'), '/tmp/outside'],
                       ['R','CMD','BATCH', str(root/'model.R')]]
            for argv in invalid:
                with self.subTest(argv=argv), self.assertRaises(api.ToolError):
                    api._guard_installation_only_command(argv, root, root)

    def test_setup_api_accepts_fixed_probe_and_rejects_scientific_r(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve()
            cfg = SimpleNamespace(root=root, roles={'binaries':root/'binaries'}, python=sys.executable)
            ki = SimpleNamespace(root=root/'ki')
            with patch.object(execution, 'run_process', return_value=execution.ProcessRun('succeeded',0,rpackage.MARK,'')) as run:
                result = api.execute_tool('run_setup_command',
                    {'argv':['Rscript', *rpackage.probe_args(root/'library',CONTRACT)]},
                    ki,cfg,setup_mode=True,setup_context={'installation_only':True})
                self.assertIn('exit_code=0',result)
                self.assertTrue(run.called)
            with self.assertRaises(api.ToolError):
                api.execute_tool('run_setup_command',{'argv':['Rscript','-e','RunModel_GR4J()']},
                    ki,cfg,setup_mode=True,setup_context={})

    def test_contract_rejects_injection_and_escape(self):
        for key, value in [('name','airGR);system("bad")'),('dll','../../outside'),('library','/tmp'),('version','latest')]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                rpackage.validate({**CONTRACT,key:value})

    def test_symlink_escape_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve()
            (root/'link').symlink_to('/tmp')
            with self.assertRaises(ValueError):
                rpackage.guard('r',['CMD','INSTALL','--library='+str(root/'link/lib'), str(root/'a')],root,root)

    def test_native_package_receipt_requires_load_marker_and_exit_zero(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve(); dll=root/'binaries/airGR/library/airGR/libs/airGR.so'
            dll.parent.mkdir(parents=True); dll.write_bytes(b'native fixture')
            cfg=SimpleNamespace(root=root, roles={'binaries':root/'binaries'}, python=sys.executable)
            man=SimpleNamespace(install_dir='airGR')
            for rc, out, expected in [(0,rpackage.MARK+'\n',True),(0,'R 4.5.1',False),(1,rpackage.MARK,False),(-9,rpackage.MARK,False)]:
                with self.subTest(rc=rc,out=out), patch.object(runnable.platform,'system',return_value='Darwin'), patch.object(runnable,'_file_kind',return_value='macho'), patch.object(runnable.shutil,'which',return_value='/usr/local/bin/Rscript'), patch.object(runnable.subprocess,'run',return_value=subprocess.CompletedProcess([],rc,out,'')) as run:
                    v=runnable._check_r_package(runnable.Verdict('GR4J'),CONTRACT,man,cfg,25,{})
                    self.assertEqual(v.usable,expected)
                    self.assertEqual(run.call_args.kwargs['stdin'],subprocess.DEVNULL)
                    self.assertIn('frun_gr4j',v.probe_command)
                    self.assertNotIn('RunModel_GR4J(',rpackage.PROBE)

    def test_library_root_selection_and_legacy_default(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve()
            cfg=SimpleNamespace(root=root,roles={'binaries':root/'binaries'})
            man=SimpleNamespace(install_dir='airGR')
            for setting, expected in [(None,root/'binaries/airGR/library'),
                                      ('model',root/'binaries/airGR/library'),
                                      ('workspace',root/'library')]:
                contract={**CONTRACT}
                if setting is not None:
                    contract['library_root']=setting
                with self.subTest(setting=setting):
                    v=runnable._check_r_package(runnable.Verdict('GR4J'),contract,man,cfg,25,{})
                    self.assertEqual(Path(v.binary),expected/'airGR/libs/airGR.so')
                    self.assertFalse(v.usable)

    def test_workspace_library_rejects_escape_and_unknown_roots(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve()
            (root/'outside').symlink_to('/tmp')
            cfg=SimpleNamespace(root=root,roles={'binaries':root/'binaries'})
            for contract in [{**CONTRACT,'library_root':'home'},
                             {**CONTRACT,'library_root':'workspace','library':'../library'},
                             {**CONTRACT,'library_root':'workspace','library':'outside/library'}]:
                with self.subTest(contract=contract):
                    v=runnable._check_r_package(runnable.Verdict('GR4J'),contract,SimpleNamespace(install_dir='airGR'),cfg,25,{})
                    self.assertFalse(v.usable)
                    self.assertIn('invalid/unavailable',v.detail)

    def test_missing_native_library_is_failure(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            v=runnable._check_r_package(runnable.Verdict('GR4J'),CONTRACT,SimpleNamespace(install_dir='airGR'),SimpleNamespace(root=root,roles={'binaries':root/'binaries'}),25,{})
            self.assertFalse(v.usable)
            self.assertFalse(v.present)
