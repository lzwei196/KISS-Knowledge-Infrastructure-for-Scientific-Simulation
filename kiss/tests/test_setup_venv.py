import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from kiss_cli import api


class SetupVenvTests(unittest.TestCase):
    def test_setup_command_preserves_venv_interpreter_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            env = root / "venv"
            subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(env)], check=True)
            interpreter = env / "bin" / "python"
            if not interpreter.is_symlink():
                self.skipTest("requires a POSIX symlink venv")
            probe = root / "probe_environment.py"
            probe.write_text("import sys; print(sys.prefix)")
            cfg = SimpleNamespace(root=root, python=sys.executable, roles={"binaries": root / "binaries"})
            result = api.execute_tool("run_setup_command", {"argv": [str(interpreter), str(probe)]},
                SimpleNamespace(root=root / "ki"), cfg, setup_mode=True,
                setup_context={"installation_only": True})
            self.assertIn("exit_code=0", result)
            self.assertIn(str(env), result)
