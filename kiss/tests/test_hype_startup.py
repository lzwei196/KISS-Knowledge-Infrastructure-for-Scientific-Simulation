import unittest

from kiss_cli import runnable


class HypeStartupTests(unittest.TestCase):
    banner = "    HYPE version 5.35.0                  \n"
    diagnostic = "Fortran runtime error: Cannot open file '--versioninfo.txt': No such file or directory"

    def test_verified_hype_probe_reaches_case_configuration(self):
        self.assertEqual(runnable._runtime_gap(self.banner + self.diagnostic), "")

    def test_exception_requires_exact_model_version_and_case_filename(self):
        for output in [self.diagnostic,
                       self.banner.replace("5.35.0", "5.36.0") + self.diagnostic,
                       self.banner + self.diagnostic.replace("--versioninfo.txt", "license.txt"),
                       self.banner + self.diagnostic.replace("--versioninfo.txt", "info.txt")]:
            with self.subTest(output=output):
                self.assertTrue(runnable._runtime_gap(output))

    def test_other_runtime_errors_are_not_hidden(self):
        for extra in ["dyld: image not found",
                      "helper: No such file or directory"]:
            with self.subTest(extra=extra):
                self.assertTrue(runnable._runtime_gap(self.banner + self.diagnostic + "\n" + extra))
