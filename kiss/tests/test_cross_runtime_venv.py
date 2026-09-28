import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from kiss_cli import api


@unittest.skipUnless(os.name == 'posix', 'POSIX venv launchers')
class CrossRuntimeVenvTests(unittest.TestCase):
    def test_workspace_venv_is_valid_even_when_configured_base_differs(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            env = root / 'venv'
            subprocess.run([sys.executable, '-m', 'venv', '--without-pip', str(env)], check=True)
            probe = root / 'probe_environment.py'
            probe.write_text('import sys; print(sys.prefix)')
            cfg = SimpleNamespace(root=root, python='/different/configured/python', roles={'binaries': root / 'binaries'})
            result = api.execute_tool('run_setup_command', {'argv': [str(env / 'bin/python'), str(probe)]}, SimpleNamespace(root=root / 'ki'), cfg, setup_mode=True, setup_context={'installation_only': True})
            self.assertIn('exit_code=0', result)
            self.assertIn(str(env), result)

    def test_symlink_to_bare_system_python_does_not_count_as_workspace_venv(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            launcher = root / 'python'
            launcher.symlink_to(sys.executable)
            cfg = SimpleNamespace(root=root, python='/different/configured/python', roles={'binaries': root / 'binaries'})
            with self.assertRaises(api.ToolError):
                api.execute_tool('run_setup_command', {'argv': [str(launcher), '--version']}, SimpleNamespace(root=root / 'ki'), cfg, setup_mode=True, setup_context={'installation_only': True})
