import os
import platform
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from kiss_cli import api, runnable


@unittest.skipUnless(os.name == 'posix', 'POSIX executable fixture')
class IsolatedStartupTests(unittest.TestCase):
    def test_help_ignoring_executable_cannot_pick_up_bundled_case(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            binary = root / 'model'
            binary.write_text('#!' + sys.executable + '\nfrom pathlib import Path\nprint("INPUT_PRESENT" if Path("input.nml").exists() else "ISOLATED")\n')
            binary.chmod(0o755)
            (root / 'input.nml').write_text('unit test fixture, not scientific data')
            ki = SimpleNamespace(name='fixture', root=root / 'ki', preflight=None, meta={'language': 'fortran'})
            cfg = SimpleNamespace(root=root, python=sys.executable, roles={'binaries': root})
            result = api.execute_tool('run_setup_command', {'argv': [str(binary), '--version']}, ki, cfg, setup_mode=True, setup_context={'installation_only': True})
            self.assertIn('ISOLATED', result)
            self.assertNotIn('INPUT_PRESENT', result)
            # the probe only runs for a binary native to this platform (CI checks run on Linux)
            native = {'Darwin': 'macho', 'Linux': 'elf'}.get(platform.system(), 'elf')
            with mock.patch.object(runnable, 'find_binary', return_value=binary), mock.patch.object(runnable, '_file_kind', return_value=native), mock.patch.object(runnable, '_missing_libs', return_value=[]):
                verdict = runnable.check(ki, cfg=cfg)
            self.assertEqual(verdict.probe_output, 'ISOLATED')
