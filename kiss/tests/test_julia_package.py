import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from kiss_cli import api, execution, jpackage, runnable

C=dict(name='Wflow',uuid='d48b7d99-76e7-47ae-b1d5-ff0c1cf9a818',version='1.1.0-dev',project='project',depot='depot',runtime='bin/julia',symbols=['Model','run'])

class JuliaPackageTests(unittest.TestCase):
    def test_fixed_install_load_only(self):
        with tempfile.TemporaryDirectory() as d:
            r=Path(d).resolve()
            for c in [None,C]:
                api._guard_installation_only_command(['julia',*jpackage.args(r/'project',r/'depot',c)],r,r)
            for a in [['-e','using Wflow; Wflow.run()'],['model.jl'],['--project='+str(r),'-e','using Pkg; Pkg.test()'],jpackage.args(r/'project',Path('/tmp/outside'),C)]:
                with self.subTest(a=a),self.assertRaises(api.ToolError):
                    api._guard_installation_only_command(['julia',*a],r,r)
    def test_invalid_contract_rejected(self):
        for k,v in [('uuid','bad'),('name','Wflow;run()'),('project','../escape'),('runtime','/bin/julia'),('depot',''),('symbols',['run()']),('version','latest')]:
            with self.subTest(k=k),self.assertRaises((ValueError,TypeError)):
                jpackage.validate({**C,k:v})
    def test_symlink_and_mismatched_project_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            r=Path(d).resolve();(r/'link').symlink_to('/tmp')
            a=jpackage.args(r/'project',r/'link',C)
            with self.assertRaises(ValueError):jpackage.guard(a,r,r)
            a=jpackage.args(r/'project',r/'depot',C);a[3]='--project='+str(r/'other')
            with self.assertRaises(ValueError):jpackage.guard(a,r,r)
    def test_receipt_requires_module_marker_and_clean_exit(self):
        with tempfile.TemporaryDirectory() as d:
            r=Path(d).resolve()
            for f in ['project/Project.toml','bin/julia','depot/packages/Wflow/a/src/Wflow.jl']:
                p=r/f;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('fixture')
            module=r/'depot/packages/Wflow/a/src/Wflow.jl'
            for rc,out,ok in [(0,jpackage.MARK+'\n'+str(module)+'\n',True),(0,'julia version 1.10.7',False),(1,jpackage.MARK+'\n'+str(module),False),(-9,jpackage.MARK+'\n'+str(module),False),(0,jpackage.MARK+'\n/tmp/escape.jl',False),(0,jpackage.MARK,False)]:
                with self.subTest(rc=rc,out=out),patch.object(runnable.subprocess,'run',return_value=subprocess.CompletedProcess([],rc,out,'')) as run:
                    v=runnable._check_julia_package(runnable.Verdict('wflow'),C,SimpleNamespace(root=r),25,{})
                    self.assertEqual(v.usable,ok)
                    self.assertEqual(run.call_args.kwargs['stdin'],subprocess.DEVNULL)
                    self.assertEqual(run.call_args.kwargs['env']['JULIA_DEPOT_PATH'],str(r/'depot'))
    def test_missing_project_is_not_interpreter_pass(self):
        with tempfile.TemporaryDirectory() as d:
            v=runnable._check_julia_package(runnable.Verdict('wflow'),C,SimpleNamespace(root=Path(d)),25,{})
            self.assertFalse(v.usable)

    def test_setup_accepts_fixed_probe_as_operation(self):
        import sys
        with tempfile.TemporaryDirectory() as d:
            r=Path(d).resolve()
            cfg=SimpleNamespace(root=r,roles={'binaries':r/'binaries'},python=sys.executable)
            with patch.object(execution,'run_process',return_value=execution.ProcessRun('succeeded',0,'ok','')):
                result=api.execute_tool('run_setup_command',{'argv':['julia',*jpackage.args(r/'project',r/'depot',C)]},SimpleNamespace(root=r/'ki'),cfg,setup_mode=True,setup_context={'installation_only':True})
                self.assertIn('exit_code=0',result)

    def test_import_budget_is_bounded_and_timeout_still_fails(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td).resolve()
            for path in ['project/Project.toml','bin/julia','depot/placeholder']:
                p=root/path;p.parent.mkdir(parents=True,exist_ok=True);p.touch()
            with patch.object(runnable.subprocess,'run',side_effect=subprocess.TimeoutExpired([],120)) as run:
                verdict=runnable._check_julia_package(runnable.Verdict('Ribasim'),C,SimpleNamespace(root=root),25,{})
                self.assertEqual(run.call_args.kwargs['timeout'],120)
                self.assertFalse(verdict.usable)
                self.assertTrue(verdict.probe_timed_out)

    def test_setup_normalizes_depot_and_preserves_both_output_streams(self):
        import sys
        with tempfile.TemporaryDirectory() as td:
            root=Path(td).resolve()
            cfg=SimpleNamespace(root=root,roles={'binaries':root/'binaries'},python=sys.executable)
            stdout=jpackage.MARK+'\n'+str(root/'depot/package/src.jl')+'\n'
            with patch.object(execution,'run_process',return_value=execution.ProcessRun('succeeded',0,stdout,'x'*60000)) as run:
                result=api.execute_tool('run_setup_command',{'argv':['julia',*jpackage.args(root/'project',root/'depot',C)],'env':{'JULIA_DEPOT_PATH':'/tmp/wrong','JULIA_LOAD_PATH':'@global'}},SimpleNamespace(root=root/'ki'),cfg,setup_mode=True,setup_context={'installation_only':True})
                self.assertIn(jpackage.MARK,result)
                self.assertIn('x'*100,result)
                self.assertEqual(run.call_args.kwargs['env']['JULIA_DEPOT_PATH'],str(root/'depot'))
                self.assertEqual(run.call_args.kwargs['env']['JULIA_LOAD_PATH'],jpackage.startup_env(root/'depot')['JULIA_LOAD_PATH'])
