import tempfile
import unittest
from pathlib import Path
from kiss_cli import gui, paths

class SetupConfigReloadTests(unittest.TestCase):
    def test_saved_replacement_environment_reaches_independent_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            old = paths.KissConfig.default(root)
            updated = paths.KissConfig.default(root)
            updated.python = str(root / 'venv2/bin/python')
            updated.roles['python_env'] = root / 'venv2'
            (root / 'kiss.toml').write_text(updated.dumps())
            loaded = gui._installation_config_after_setup(old)
            self.assertEqual(loaded.python, updated.python)
            self.assertEqual(loaded.roles['python_env'], root / 'venv2')
            self.assertNotEqual(old.python, loaded.python)

    def test_changed_workspace_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            old = paths.KissConfig.default(root)
            changed = paths.KissConfig.default(root / 'other')
            (root / 'kiss.toml').write_text(changed.dumps())
            with self.assertRaisesRegex(ValueError, 'workspace root'):
                gui._installation_config_after_setup(old)
