import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from kiss_cli import runnable


class WindowsStartupStatusTests(unittest.TestCase):
    def check_native(self, rc, output="", marker=""):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            binary = root / "shaw.exe"
            binary.write_bytes(b"MZ")
            ki = SimpleNamespace(name="SHAW", root=root / "ki", meta={"language": "fortran"})
            cfg = SimpleNamespace(root=root, roles={"binaries": root}, python=sys.executable)
            man = SimpleNamespace(startup_marker=marker)
            with patch.object(runnable, "declared_imports", return_value=[]), \
                 patch.object(runnable, "find_binary", return_value=binary), \
                 patch.object(runnable, "_file_kind", return_value="pe"), \
                 patch.object(runnable.platform, "system", return_value="Windows"), \
                 patch.object(runnable.subprocess, "run", return_value=
                              subprocess.CompletedProcess([], rc, output, "")) as run:
                verdict = runnable.check(ki, man, cfg, python=sys.executable)
            # An abnormal exit is decisive; subsequent flags must not mask it.
            self.assertEqual(run.call_count, 1)
            self.assertEqual(verdict.probe_returncode, rc)
            self.assertEqual(verdict.probe_output, output.strip())
            return verdict

    def test_recorded_shaw_loader_failure_is_blocked(self):
        # The live installation-test.json said ready for this exact empty probe.
        verdict = self.check_native(3221225595)
        self.assertTrue(verdict.present)
        self.assertTrue(verdict.shaped)
        self.assertFalse(verdict.linked)
        self.assertFalse(verdict.responds)
        self.assertFalse(verdict.usable)
        self.assertEqual(verdict.state, "blocked")
        self.assertIn("0xC000007B", verdict.summary())
        self.assertIn("STATUS_INVALID_IMAGE_FORMAT", verdict.detail)

    def test_signed_and_unsigned_windows_failures_cannot_prove_startup(self):
        statuses = (
            0xC000007B, 0xC0000135, 0xC0000138, 0xC0000139, 0xC0000142,
            0xC0000005, 0xC000001D, 0xC0000094, 0xC00000FD, 0xC0000409,
            0xC000013A, 0x80000003, 0xE06D7363, 0xC0FFEE01,
        )
        for status in statuses:
            for rc in (status, status - (1 << 32)):
                with self.subTest(status=hex(status), rc=rc):
                    verdict = self.check_native(rc)
                    self.assertFalse(runnable._ran(rc))
                    self.assertFalse(verdict.responds)
                    self.assertFalse(verdict.usable)
                    self.assertEqual(verdict.as_dict()["state"], "blocked")
                    self.assertIn(f"0x{status:08X}", verdict.detail)
                    if status in runnable._WINDOWS_LOADER_FAILURES:
                        self.assertFalse(verdict.linked)
                        self.assertTrue(verdict.missing)

    def test_startup_banner_cannot_override_crash_or_loader_failure(self):
        marker = "SHAW MODEL VERSION 3.0"
        output = marker + "\nFortran runtime error: Cannot open file 'case.in': No such file or directory"
        for rc in (0xC000007B, -1073741819, 0x40000015, -11):
            with self.subTest(rc=rc):
                verdict = self.check_native(rc, output, marker)
                self.assertFalse(verdict.responds)
                self.assertFalse(verdict.usable)
        # The same evidence with a normal input-related exit remains eligible.
        self.assertTrue(self.check_native(1, output, marker).usable)

    def test_fatal_app_exit_is_blocked_despite_informational_status_severity(self):
        verdict = self.check_native(0x40000015, "SHAW MODEL VERSION 3.0")
        self.assertFalse(verdict.usable)
        self.assertFalse(verdict.responds)
        self.assertIn("0x40000015", verdict.detail)
        self.assertIn("STATUS_FATAL_APP_EXIT", verdict.detail)

    def test_normal_help_and_interactive_eof_exits_remain_eligible(self):
        for rc, output in (
            (0, "SHAW model version 3.0"),
            (1, "Usage: shaw [input file]"),
            (2, "Unrecognized option --version\nUsage: model INPUT"),
            (2, "SHAW MODEL VERSION 3.0\nEnter input file:\nFortran runtime error: End of file"),
            (131, "STOP 131: case input required"),
            (233, "STOP 233: case input required"),
        ):
            with self.subTest(rc=rc, output=output):
                self.assertTrue(self.check_native(rc, output).usable)

    def test_old_false_ready_flags_cannot_override_failed_process_evidence(self):
        for rc in (3221225595, -1073741701, 0xC0000005, -11):
            with self.subTest(rc=rc):
                verdict = runnable.Verdict(
                    model="SHAW", binary="shaw.exe", kind="pe", present=True,
                    shaped=True, linked=True, responds=True, probe_returncode=rc,
                    detail=f"exit {rc}, no output",
                )
                self.assertFalse(verdict.usable)
                self.assertEqual(verdict.state, "blocked")
                self.assertNotIn("runnable (pe)", verdict.summary())

    def test_old_cached_windows_pass_is_rechecked_and_new_failure_can_be_cached(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = runnable.cache_path(root, "SHAW")
            path.parent.mkdir()
            for rc in (3221225595, -1073741701, 0xC0000005, 0x40000015):
                with self.subTest(rc=rc):
                    path.write_text(json.dumps({"state": "ready", "probe_returncode": rc}), encoding="utf-8")
                    self.assertIsNone(runnable.load(root, "SHAW"))
            verdict = self.check_native(3221225595)
            runnable.save(root, verdict)
            cached = runnable.load(root, "SHAW")
            self.assertEqual(cached["state"], "blocked")
            self.assertEqual(cached["probe_returncode"], 3221225595)
            runnable.save(root, self.check_native(1, "Usage: shaw [input file]"))
            self.assertEqual(runnable.load(root, "SHAW")["state"], "ready")
