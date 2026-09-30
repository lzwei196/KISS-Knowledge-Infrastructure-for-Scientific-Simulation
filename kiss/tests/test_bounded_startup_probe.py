import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from kiss_cli import api, execution

class BoundedStartupProbeTests(unittest.TestCase):
    def test_native_help_cannot_inherit_stdin_or_a_build_timeout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            binary = root / 'binaries' / 'model'
            binary.parent.mkdir()
            binary.write_bytes(b'MZfixture')
            binary.chmod(0o755)
            cfg = SimpleNamespace(root=root, python='/usr/bin/python3', roles={'binaries': binary.parent})
            ki = SimpleNamespace(root=root / 'ki', name='fixture')
            with mock.patch.object(execution, 'run_process', return_value=execution.ProcessRun('succeeded', 0, 'usage', '')) as run:
                api.execute_tool('run_setup_command', {'argv': [str(binary), '--help'], 'timeout_seconds': 1800}, ki, cfg, setup_mode=True, setup_context={'installation_only': True})
            self.assertLessEqual(run.call_args.kwargs['timeout'], 25)
            self.assertGreater(run.call_args.kwargs['timeout'], 0)
            # The common subprocess-tree runner always closes stdin.
            self.assertNotEqual(Path(run.call_args.kwargs['cwd']), root)
