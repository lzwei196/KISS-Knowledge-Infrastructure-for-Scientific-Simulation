import unittest
from kiss_cli import runnable


class NamelistStartupTests(unittest.TestCase):
    def test_missing_project_namelist_is_not_a_missing_runtime(self):
        output = "At line 67 of file cmf_ctrl_nmlist_mod.F90 (unit = 11)\nFortran runtime error: Cannot open file 'input_cmf.nam': No such file or directory\n\nError termination. Backtrace:\n#0 0x104d42103"
        self.assertEqual(runnable._runtime_gap(output), '')
        self.assertTrue(runnable._runtime_gap(output + '\nhelper: No such file or directory'))

    def test_missing_libraries_interpreters_and_other_files_still_fail(self):
        for output in ["Fortran runtime error: Cannot open file 'license.dat': No such file or directory", 'dyld: image not found', '/usr/bin/env: python: No such file or directory']:
            with self.subTest(output=output):
                self.assertTrue(runnable._runtime_gap(output))
