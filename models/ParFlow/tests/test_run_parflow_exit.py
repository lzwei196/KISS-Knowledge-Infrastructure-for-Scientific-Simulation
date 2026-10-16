"""s8 run_parflow.py: honest exit code, fresh-output success check, relative run_dir, PARFLOW_DIR (no solver run)."""
import importlib.util
import os
from pathlib import Path
import sys
import unittest
from unittest import mock

KI = Path(os.environ.get('KI_UNDER_TEST', Path(__file__).resolve().parents[1]))
spec = importlib.util.spec_from_file_location('run_parflow', KI / 'tools/s8_execution/run_parflow.py')
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)


class ExitCodeTests(unittest.TestCase):
    def _exit(self, status):
        with mock.patch.object(sys, 'argv', ['run_parflow.py', '--run_dir', '.', '--run_name', 'x']), \
                mock.patch.object(r, 'validate_inputs', return_value=[]), \
                mock.patch.object(r, 'process', return_value={'status': status}), \
                mock.patch('builtins.print'):
            with self.assertRaises(SystemExit) as cm:
                r.main()
        return cm.exception.code

    def test_error_exits_nonzero(self):
        self.assertEqual(self._exit('error'), 1)

    def test_success_exits_zero(self):
        self.assertEqual(self._exit('success'), 0)


class ProcessTests(unittest.TestCase):
    """Tiny fake run scripts (a few lines of Python), not ParFlow."""
    def setUp(self):
        import tempfile
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = Path(t.name)
        self.run = self.root / 'run'
        self.run.mkdir()

    def _script(self, body):
        (self.run / 'run_x.py').write_text('import os\n' + body + '\n')

    def test_old_pressure_file_does_not_count(self):
        old = self.run / 'x.out.press.00000.pfb'
        old.write_bytes(b'old')
        os.utime(old, (1e9, 1e9))
        self._script('pass')  # exits 0, writes nothing
        with mock.patch('builtins.print'):
            res = r.process(str(self.run), 'x')
        self.assertEqual(res['status'], 'error')
        self.assertEqual(res['output_files']['old_pressure_files_ignored'], 1)

    def test_unchanged_recent_or_future_pressure_file_does_not_count(self):
        import time
        for stamp in (time.time() - 0.5, time.time() + 3600):
            with self.subTest(stamp=stamp):
                old = self.run / 'x.out.press.00000.pfb'
                old.write_bytes(b'old')
                os.utime(old, (stamp, stamp))
                self._script('pass')
                with mock.patch('builtins.print'):
                    res = r.process(str(self.run), 'x')
                self.assertEqual(res['status'], 'error')
                self.assertEqual(res['output_files']['pressure'], 0)

    def test_rewritten_pressure_file_counts(self):
        old = self.run / 'x.out.press.00000.pfb'
        old.write_bytes(b'old')
        os.utime(old, (1e9, 1e9))
        self._script('open("x.out.press.00000.pfb", "wb").write(b"newer")')
        with mock.patch('builtins.print'):
            res = r.process(str(self.run), 'x')
        self.assertEqual(res['status'], 'success', res)

    def test_relative_run_dir_and_new_output_succeeds(self):
        self._script('open("x.out.press.00001.pfb", "wb").write(b"new")')
        cwd = os.getcwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, cwd)
        with mock.patch('builtins.print'):
            res = r.process('run', 'x')
        self.assertEqual(res['status'], 'success', res)
        self.assertEqual(res['output_files']['pressure'], 1)

    def test_script_keeps_its_own_parflow_dir_when_not_exported(self):
        self._script('open("pfdir.txt", "w").write(os.environ.get("PARFLOW_DIR", "<unset>"))')
        env = {k: v for k, v in os.environ.items() if k != 'PARFLOW_DIR'}
        with mock.patch.dict(os.environ, env, clear=True), mock.patch('builtins.print'):
            r.process(str(self.run), 'x')
        self.assertEqual((self.run / 'pfdir.txt').read_text(), '<unset>')
        with mock.patch.dict(os.environ, dict(env, PARFLOW_DIR='/chosen/pf'), clear=True), \
                mock.patch('builtins.print'):
            r.process(str(self.run), 'x')
        self.assertEqual((self.run / 'pfdir.txt').read_text(), '/chosen/pf')


if __name__ == '__main__':
    unittest.main()
