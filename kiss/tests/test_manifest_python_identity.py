import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from kiss_cli import runnable

class ManifestPythonIdentityTests(unittest.TestCase):
    def test_explicit_python_manifest_supplies_missing_language_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cfg = SimpleNamespace(root=root, python=sys.executable, roles={'binaries':root/'binaries'})
            man = SimpleNamespace(binary_type='Python', install_dir='fixture', acquire=SimpleNamespace(strategy='pip', produces='json', package='json'))
            for language, expected in [('', True), ('python', True), ('fortran', False), ('c++', False)]:
                ki = SimpleNamespace(root=root, name='fixture', meta={'language':language})
                with self.subTest(language=language), mock.patch.object(runnable, 'declared_imports', return_value=[]), mock.patch.object(runnable, 'declared', return_value=[]):
                    verdict = runnable.check(ki, man, cfg, python=sys.executable)
                self.assertEqual(verdict.usable, expected)
