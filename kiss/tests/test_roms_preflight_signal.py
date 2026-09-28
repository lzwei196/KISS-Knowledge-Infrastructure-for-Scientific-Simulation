"""Verify startup classification without executing ROMS or model inputs."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


class ROMSPreflightSignalTests(unittest.TestCase):
    def test_banner_cannot_hide_signal_termination(self):
        source = Path(__file__).resolve().parents[2] / 'models/ROMS/preflight_check.py'
        spec = importlib.util.spec_from_file_location('roms_preflight', source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / 'romsS'
            binary.touch()
            binary.chmod(0o700)
            for code, accepted in [(-11, False), (-6, False), (0, True)]:
                with self.subTest(returncode=code):
                    result = subprocess.CompletedProcess([], code, b'ROMS version 4.3', b'')
                    checks = []
                    with patch.object(module.subprocess, 'run', return_value=result):
                        self.assertEqual(module.check_binary_starts(checks, binary), accepted)
                    self.assertEqual(checks[-1]['status'], 'pass' if accepted else 'fail')
