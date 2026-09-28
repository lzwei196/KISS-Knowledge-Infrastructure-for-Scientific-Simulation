import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from kiss_cli import runnable


class ImportContractTests(unittest.TestCase):
    def contract(self, source):
        with tempfile.TemporaryDirectory() as directory:
            preflight = Path(directory) / 'preflight_check.py'
            preflight.write_text(source)
            return runnable.declared_imports(SimpleNamespace(preflight=preflight))

    def test_literal_loop_contract(self):
        self.assertEqual(self.contract('def main():\n for module in ["numpy", "netCDF4", "pandas"]:\n  check_import(module)\n'), ['numpy', 'netCDF4', 'pandas'])

    def test_module_argument_after_checks(self):
        self.assertEqual(self.contract('def check_import(checks, module):\n pass\ndef main():\n check_import([], "numpy")\n'), ['numpy'])

    def test_bound_method_preserved(self):
        self.assertEqual(self.contract('class Preflight:\n def check_import(self, module, label):\n  pass\ndef main():\n pf.check_import("pyswmm", "package")\n'), ['pyswmm'])

    def test_tuple_bindings_exclude_distribution_labels(self):
        self.assertEqual(self.contract('MODULES = [("PIL", "pillow"), ("yaml", "pyyaml")]\ndef main():\n for module, distribution in MODULES:\n  check_import(module, distribution)\n'), ['PIL', 'yaml'])

    def test_dynamic_contract_is_not_executed_or_guessed(self):
        self.assertEqual(self.contract('raise RuntimeError("must not execute preflight")\ncheck_import(dynamic_module)\n'), [])
