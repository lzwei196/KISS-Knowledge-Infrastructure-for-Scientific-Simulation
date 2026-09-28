import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from kiss_cli import api, runnable

class InstallVerdictGuardTests(unittest.TestCase):
    def test_interpreter_is_not_model_for_python_or_fortran(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            interpreter = root / 'python3.13'
            interpreter.touch()
            model = root / 'real_model.py'
            model.touch()
            for language in ('python', 'fortran'):
                ki = SimpleNamespace(name='fixture', meta={'language': language})
                with mock.patch.object(runnable, 'declared', return_value=[str(interpreter)]):
                    self.assertIsNone(runnable.find_binary(ki))
                with mock.patch.object(runnable, 'declared', return_value=[str(interpreter), str(model)]):
                    self.assertEqual(runnable.find_binary(ki), model)

    def test_language_runtime_version_is_not_a_model_product(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ki = SimpleNamespace(name='fixture', meta={'language': 'julia'})
            for name in ('julia', 'julia-1.10.7', 'java', 'R', 'Rscript', 'node', 'nodejs', 'octave-cli', 'python3.13.exe'):
                candidate = root / name
                candidate.touch()
                with self.subTest(name=name), mock.patch.object(runnable, 'declared', return_value=[str(candidate)]):
                    self.assertIsNone(runnable.find_binary(ki))

    def test_signal_termination_cannot_prove_startup(self):
        for code in (-9, -11, -6):
            self.assertFalse(runnable._ran(code))
        for code in (0, 2, 131, 233):
            self.assertTrue(runnable._ran(code))

    def test_compiled_ki_wrapper_cannot_substitute_for_engine(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            ki_root = root / 'ki'
            (ki_root / 'tools').mkdir(parents=True)
            wrapper = ki_root / 'tools' / 'run_amanzi.py'
            wrapper.write_text('import argparse\np = argparse.ArgumentParser()\np.add_argument("--xml_file", required=True)\np.parse_args()\n')
            copied = root / 'renamed_product.py'
            copied.write_bytes(wrapper.read_bytes())
            symlink = root / 'product.py'
            symlink.symlink_to(wrapper)
            ki = SimpleNamespace(name='Amanzi_ATS', root=ki_root, meta={'language': 'c++'})
            cfg = SimpleNamespace(root=root, python=sys.executable, roles={'binaries': root / 'binaries'})
            for product in (wrapper, copied, symlink):
                with self.subTest(product=product.name), \
                     mock.patch.object(runnable, 'declared_imports', return_value=[]), \
                     mock.patch.object(runnable, 'declared', return_value=[str(product)]), \
                     mock.patch.object(runnable.subprocess, 'run') as run:
                    verdict = runnable.check(ki, cfg=cfg, python=sys.executable)
                    self.assertFalse(verdict.usable)
                    self.assertTrue(verdict.present)
                    self.assertIn('KI helper script', verdict.detail)
                    run.assert_not_called()
            ki.meta['language'] = 'python'
            with mock.patch.object(runnable, 'declared_imports', return_value=[]), \
                 mock.patch.object(runnable, 'declared', return_value=[str(wrapper)]):
                verdict = runnable.check(ki, cfg=cfg, python=sys.executable)
            self.assertTrue(verdict.usable, verdict.detail)

    def test_installed_upstream_entry_point_remains_eligible(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            product = root / 'binaries' / 'ogs'
            product.parent.mkdir()
            product.write_text('#!/usr/bin/env python3\nprint("upstream entry point")\n')
            ki = SimpleNamespace(name='OpenGeoSys', root=root / 'ki', meta={'language': 'c++'})
            cfg = SimpleNamespace(root=root, python=sys.executable, roles={'binaries': product.parent})
            with mock.patch.object(runnable, 'declared_imports', return_value=[]), \
                 mock.patch.object(runnable, 'declared', return_value=[str(product)]):
                verdict = runnable.check(ki, cfg=cfg, python=sys.executable)
            self.assertTrue(verdict.usable, verdict.detail)
            self.assertIn('upstream entry point', verdict.probe_output)

    def test_suffixless_console_script_uses_selected_python(self):
        with tempfile.TemporaryDirectory() as directory:
            product = Path(directory) / 'ogs'
            for shebang in ('#!/usr/bin/env python3', '#!/missing/old/venv/bin/python3.13'):
                with self.subTest(shebang=shebang):
                    product.write_text(shebang + '\nprint("native package entry point")\n')
                    self.assertEqual(runnable._interpreter(product, sys.executable), [sys.executable])

    def test_full_preflight_blocked_in_installation_only_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            ki = SimpleNamespace(name='fixture', root=root/'ki')
            cfg = SimpleNamespace(root=root, python=sys.executable, roles={'binaries':root/'binaries'})
            with mock.patch('kiss_cli.install.run_preflight') as preflight:
                with self.assertRaisesRegex(api.ToolError, 'installation-only'):
                    api.execute_tool('run_preflight', {}, ki, cfg, setup_mode=True, setup_context={'installation_only':True})
                preflight.assert_not_called()
            with self.assertRaisesRegex(api.ToolError, "allowlisted tool name 'git'"):
                api.execute_tool('run_setup_command', {'argv':['/unavailable/external/bin/git','--version']}, ki, cfg, setup_mode=True, setup_context={'installation_only':True})

    def test_native_product_cannot_fall_back_to_upstream_setup_script(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            setup = root / 'create_newcase'
            setup.write_text('#!/usr/bin/env python3\nprint("setup help")\n')
            ki = SimpleNamespace(name='CTSM', root=root / 'ki', meta={'language':'fortran'})
            cfg = SimpleNamespace(root=root, python=sys.executable, roles={'binaries':root})
            man = SimpleNamespace(binary_type='Mach-O', install_dir='CTSM', acquire=SimpleNamespace(produces='ki-build/cesm.exe', strategy='build'))
            with mock.patch.object(runnable, 'declared', return_value=[str(setup)]):
                self.assertEqual(runnable.find_binary(ki, man, cfg), root/'CTSM/ki-build/cesm.exe')
            with mock.patch.object(runnable, 'find_binary', return_value=setup), mock.patch.object(runnable, 'declared_imports', return_value=[]), mock.patch.object(runnable.subprocess, 'run') as run:
                verdict = runnable.check(ki, man=man, cfg=cfg, python=sys.executable)
                self.assertFalse(verdict.usable)
                self.assertIn('native executable', verdict.detail)
                run.assert_not_called()
