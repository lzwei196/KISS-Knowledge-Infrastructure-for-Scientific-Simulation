import sys
import tempfile
import unittest
from pathlib import Path
from kiss_cli import runnable, paths
from kiss_cli.catalog import KI


class ProbeRuntimeEnvironmentTests(unittest.TestCase):
    def test_bundled_library_is_visible_but_missing_dependency_still_fails(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            common = root / 'common'
            common.mkdir()
            (common / 'shared_runtime_contract_fixture.py').write_text('VALUE = 1')
            ki_root = root / 'ki'
            ki_root.mkdir()
            pre = ki_root / 'preflight_check.py'
            pre.write_text('check_import("shared_runtime_contract_fixture")\n')
            cfg = paths.KissConfig.default(root)
            cfg.python = sys.executable
            cfg.roles['ki_tools_common'] = common
            v = runnable.check(KI('contract', ki_root), cfg=cfg)
            self.assertTrue(v.imports_ok)
            pre.write_text('check_import("shared_runtime_contract_fixture")\ncheck_import("missing_external_contract_fixture")\n')
            v = runnable.check(KI('contract', ki_root), cfg=cfg)
            self.assertFalse(v.imports_ok)
            self.assertEqual(v.missing, ['missing_external_contract_fixture'])
