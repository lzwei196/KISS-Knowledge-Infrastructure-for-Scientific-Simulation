import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from kiss_cli import runnable

class OptionalImportContractTests(unittest.TestCase):
    def test_only_explicit_optional_import_is_excluded(self):
        with tempfile.TemporaryDirectory() as directory:
            pre=Path(directory)/'preflight_check.py'
            pre.write_text("def check_import(checks, module, *, critical=True): pass\ncheck_import([], 'porepy', critical=True)\ncheck_import([], 'pypardiso', critical=False)\ncheck_import([], 'numpy')\ncheck_import([], 'unknown_dependency', critical=unknown_setting)\n")
            self.assertEqual(runnable.declared_imports(SimpleNamespace(preflight=pre)), ['porepy','numpy','unknown_dependency'])

    def test_module_level_import_contract_with_custom_subprocess_helper(self):
        with tempfile.TemporaryDirectory() as directory:
            pre = Path(directory) / 'preflight_check.py'
            pre.write_text("IMPORT_MODULES = ['lisflood', 'pcraster', 'osgeo.gdal']\ndef check_runtime_imports(): pass\n")
            self.assertEqual(runnable.declared_imports(SimpleNamespace(preflight=pre)), ['lisflood', 'pcraster', 'osgeo.gdal'])
