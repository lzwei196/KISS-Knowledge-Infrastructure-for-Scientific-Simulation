import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from kiss_cli import runnable


class NativeVersionFlagTests(unittest.TestCase):
    def test_generic_native_input_loop_timeout_is_not_an_installation_pass(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            binary = root / 'native'
            binary.touch(); binary.chmod(0o755)
            ki = SimpleNamespace(name='NativeFixture', root=root/'ki', meta={'language':'c++'})
            cfg = SimpleNamespace(root=root, roles={'binaries':root}, python=sys.executable)
            with patch.object(runnable,'declared_imports',return_value=[]), \
                 patch.object(runnable,'find_binary',return_value=binary), \
                 patch.object(runnable,'_file_kind',return_value='macho'), \
                 patch.object(runnable,'_missing_libs',return_value=[]), \
                 patch.object(runnable.platform,'system',return_value='Darwin'), \
                 patch.object(runnable.subprocess,'run',side_effect=subprocess.TimeoutExpired(
                     [],25,output=b'Name of input file?\\n',stderr='Cannot open file')):
                verdict = runnable.check(ki,cfg=cfg,python=sys.executable)
            self.assertFalse(verdict.usable)
            self.assertFalse(verdict.responds)
            self.assertTrue(verdict.probe_timed_out)
            self.assertIn('Name of input file?',verdict.probe_output)
            self.assertIn('Cannot open file',verdict.probe_output)

    def test_exact_flags_require_native_clean_version_and_reject_timeout(self):
        for name, flag, banner in [('PISM', '-version', 'PISM (2.3.0-79cae57 committed)'),
                                   ('BIOME_BGC', '-V', 'BiomeBGC version 4.2 (built today)'),
                                   ('PHREEQC', '--version', '* PHREEQC-3.8.6 *')]:
            with tempfile.TemporaryDirectory() as td:
                root = Path(td).resolve()
                binary = root / 'native'
                binary.touch(); binary.chmod(0o755)
                ki = SimpleNamespace(name=name, root=root/'ki', meta={'language':'c++'})
                cfg = SimpleNamespace(root=root, roles={'binaries':root}, python=sys.executable)
                for rc, output, expected in [(0,banner,True),(1,banner,False),(-11,banner,False),(0,'different version',False),(None,'',False)]:
                    with self.subTest(name=name,rc=rc,output=output), \
                         patch.object(runnable,'declared_imports',return_value=[]), \
                         patch.object(runnable,'find_binary',return_value=binary), \
                         patch.object(runnable,'_file_kind',return_value='macho'), \
                         patch.object(runnable,'_missing_libs',return_value=[]), \
                         patch.object(runnable.platform,'system',return_value='Darwin'), \
                         patch.object(runnable.subprocess,'run') as run:
                        if rc is None:
                            run.side_effect = subprocess.TimeoutExpired([],25)
                        else:
                            run.return_value = subprocess.CompletedProcess([],rc,output,'')
                        verdict = runnable.check(ki,cfg=cfg,python=sys.executable)
                        self.assertEqual(verdict.usable,expected,verdict.detail)
                        self.assertEqual(run.call_args.args[0],[str(binary),flag])
                        self.assertEqual(run.call_args.kwargs['stdin'],subprocess.DEVNULL)

    def test_phreeqc_records_created_paths_and_rejects_version_side_effects(self):
        for name, timeout, expected in [('PHREEQC', False, False),
                                        ('PHREEQC', True, False),
                                        ('BIOME_BGC', False, True)]:
            with self.subTest(name=name, timeout=timeout), tempfile.TemporaryDirectory() as td:
                root = Path(td).resolve()
                binary = root / 'native'
                binary.touch(); binary.chmod(0o755)
                ki = SimpleNamespace(name=name, root=root/'ki', meta={'language':'c++'})
                cfg = SimpleNamespace(root=root, roles={'binaries':root}, python=sys.executable)
                def probe(argv, **kwargs):
                    cwd = Path(kwargs['cwd'])
                    (cwd/'output').mkdir()
                    (cwd/'output'/'phreeqc.log').write_text('unexpected output')
                    if timeout:
                        raise subprocess.TimeoutExpired(argv, 25)
                    banner = '* PHREEQC-3.8.6 *' if name == 'PHREEQC' else 'BiomeBGC version 4.2 (built today)'
                    return subprocess.CompletedProcess(argv, 0, banner, '')
                with patch.object(runnable,'declared_imports',return_value=[]), \
                     patch.object(runnable,'find_binary',return_value=binary), \
                     patch.object(runnable,'_file_kind',return_value='macho'), \
                     patch.object(runnable,'_missing_libs',return_value=[]), \
                     patch.object(runnable.platform,'system',return_value='Darwin'), \
                     patch.object(runnable.subprocess,'run',side_effect=probe):
                    verdict = runnable.check(ki,cfg=cfg,python=sys.executable)
                self.assertEqual(verdict.usable, expected)
                self.assertEqual(verdict.probe_created_paths,
                                 ['output', 'output/phreeqc.log'] if name == 'PHREEQC' else [])
                self.assertEqual(verdict.as_dict()['probe_created_paths'], verdict.probe_created_paths)
                self.assertEqual(verdict.probe_timed_out, timeout)
                if name == 'PHREEQC' and not timeout:
                    self.assertIn('created unexpected', verdict.detail)
