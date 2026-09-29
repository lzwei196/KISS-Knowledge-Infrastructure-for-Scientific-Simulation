import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from kiss_cli import api


class _TimedOutChild:
    pid, returncode, stdout, stderr = 0, None, None, None

    def __init__(self, exc):
        self.exc = exc

    def communicate(self, timeout=None):
        if self.exc:
            exc, self.exc = self.exc, None
            raise exc
        return '', ''

    def kill(self):
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode

    def poll(self):
        return self.returncode


class TimeoutOutputTests(unittest.TestCase):
    def test_mixed_bytes_and_text_timeout_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve()
            cfg=SimpleNamespace(root=root, python=sys.executable, roles={'binaries':root/'binaries'})
            ki=SimpleNamespace(root=root/'ki', name='fixture')
            exc=subprocess.TimeoutExpired(['git','--version'], 1, output=b'partial output\xff', stderr='diagnostic')
            with mock.patch.object(api.subprocess, 'Popen', return_value=_TimedOutChild(exc)):
                result=api.execute_tool('run_setup_command', {'argv':['git','--version']}, ki, cfg, setup_mode=True, setup_context={'installation_only':True})
            self.assertIn('TIMEOUT', result)
            self.assertIn('partial output', result)
            self.assertIn('diagnostic', result)
