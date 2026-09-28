import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from kiss_cli import api, runnable


class InstallationIntegrityTests(unittest.TestCase):
    def test_discoverable_but_broken_import_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "broken_ki_package.py").write_text("raise ImportError('native dependency missing')")
            self.assertEqual(runnable.missing_imports(["broken_ki_package"], sys.executable, root), ["broken_ki_package"])

    def test_dead_interpreter_is_not_a_pass(self):
        self.assertEqual(runnable.missing_imports(["json"], "/nonexistent/python"), ["json"])

    def test_successful_import(self):
        self.assertEqual(runnable.missing_imports(["json"], sys.executable), [])

    def test_setup_children_require_venv_for_pip(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            script = root / "probe_environment.py"
            script.write_text("import os; print('pip_guard=' + os.environ.get('PIP_REQUIRE_VIRTUALENV', 'missing'))")
            cfg = SimpleNamespace(root=root, python=sys.executable, roles={"binaries": root / "binaries"})
            result = api.execute_tool("run_setup_command", {"argv": [sys.executable, str(script)]}, SimpleNamespace(root=root / "ki"), cfg, setup_mode=True, setup_context={"installation_only": True})
            self.assertIn("pip_guard=true", result)
            with self.assertRaises(api.ToolError):
                api.execute_tool("run_setup_command", {"argv": [sys.executable, str(script)], "env": {"PIP_REQUIRE_VIRTUALENV": "false"}}, SimpleNamespace(root=root / "ki"), cfg, setup_mode=True, setup_context={"installation_only": True})
