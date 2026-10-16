"""In-memory checks of the TTUTIL-exact .swp reader and of run_swap's
switch logic (no files written). Rules: ttutil v4.2.7 src/rdsctb.for,
rdlex.for, recread.f90, rddata.for; SWAP src/swapoutput.f90."""
import importlib.util
import os
import sys
import unittest
from pathlib import Path

KI = Path(os.environ.get("KI_UNDER_TEST", Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(KI / "tools"))


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, KI / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rs = _load("run_swap", "tools/run_swap.py")
# the reader module run_swap itself imported (one MISSING object)
rd = sys.modules["_ttutil_swp_reader"]
assert Path(rd.__file__).resolve() == (KI / "tools/_ttutil_swp_reader.py").resolve()


def read(text):
    data = text.encode("latin-1") if isinstance(text, str) else text
    return rd.read_swp_bytes(data)


class ReaderSyntax(unittest.TestCase):
    def test_statement_terminators_and_layout(self):
        k = read("SWBAL=0;\nA = 1; B = 'x'; C = 2.5d0\nD =\n  7\n")
        self.assertEqual((k["swbal"], k["a"], k["b"], k["c"], k["d"]),
                         (0, 1, "x", 2.5, 7))

    def test_arrays_repeats_concat(self):
        k = read("A = 1, 2,\n 3\n 4\nX = 3*0.5\nS = 'ab' // 'cd'\n"
                 "C = 2*'maize'//'s'\n")
        self.assertEqual(k["a"], [1, 2, 3, 4])
        self.assertEqual(k["x"], [0.5, 0.5, 0.5])
        self.assertEqual(k["s"], "abcd")
        self.assertEqual(k["c"], ["maizes", "maizes"])

    def test_comments_and_case(self):
        k = read("* c\n! c\n\n  OutFil = 'Res!ult'  ! note\n")
        self.assertEqual(k["outfil"], "Res!ult")

    def test_tables(self):
        k = read("ISUB ISOIL H\n 1 1 10.0\n 2 1 20.0\nNEXT = 1\nA B = 1 2\n")
        self.assertEqual((k["isub"], k["isoil"], k["h"], k["next"], k["a"],
                          k["b"]), ([1, 2], [1, 1], [10.0, 20.0], 1, 1, 2))

    def test_record_ends_lf_cr_crlf_lfcr(self):
        for sep in ("\n", "\r", "\r\n", "\n\r"):
            with self.subTest(sep=repr(sep)):
                k = read(sep.join(["* head", "OUTFIL = 'r'", "SWBAL = 0", ""]))
                self.assertEqual((k["outfil"], k["swbal"]), ("r", 0))

    def test_dos_eof_mark_ends_file(self):
        k = read(b"OUTFIL = 'r'\nSWBAL = 0\n\x1a\n")
        self.assertEqual((k["outfil"], k["swbal"]), ("r", 0))
        k = read(b"A = 1\n\x1a junk = = =\nB = 2\n")
        self.assertEqual(k, {"a": 1})

    def test_missing_value(self):
        k = read("SWBAL = -\nA = 1, -, 3\n")
        self.assertIs(k["swbal"], rd.MISSING)
        self.assertEqual(k["a"][1], rd.MISSING)

    def test_errors_ttutil_would_stop_on(self):
        for bad in ("SWBAL = 0 SWWBA = 0\n", "SWBAL = 0\nswbal = 1\n",
                    "A = 1, 2.0\n", "A B\n 1 2\n 3\n", "A =\n",
                    "OUTFIL = result\n", "Q = 'it''s'\n"):
            with self.subTest(bad=bad), self.assertRaises(rd.SwpSyntaxError):
                read(bad)


class RunSwapSwitches(unittest.TestCase):
    def test_switch_values(self):
        k = read("SWBAL = -\nSWWBA = 0;\nSWX = 0.0\n")
        self.assertEqual(rs._switch(k, "swbal", 1), -99)   # TTUTIL IM_D
        self.assertEqual(rs._switch(k, "swwba", 1), 0)
        self.assertEqual(rs._switch(k, "absent", 1), 1)
        with self.assertRaises(rd.SwpSyntaxError):
            rs._switch(k, "swx", 0)

    def test_expected_outputs(self):
        k = read("SWBLC = 1; SWBAL = -; SWWBA = 0; SWINC = 1; SWVAP = 0\n"
                 "SWSOLU = 0; SWSBA = 1; SWHEA = 1; SWATE = 1\n")
        self.assertEqual(set(rs.expected_outputs(k)), {".blc", ".inc", ".tem"})

    def test_swap_argument(self):
        self.assertEqual(rs.swap_argument("case.swp.swp"), "case.swp.swp")
        self.assertEqual(rs.swap_argument("swap.swp"), "swap.swp")
        for bad in ("a" * 29 + ".swp", "case.txt", "Case.swp", ".swp", "case"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                rs.swap_argument(bad)
        self.assertEqual(rs.swap_argument("a" * 28 + ".swp"), "a" * 28 + ".swp")

    def test_swap_argument_counts_bytes(self):
        zh = "\u7ad9"                                  # 3 bytes in UTF-8
        ok = ["a" + zh * 9 + ".swp", zh * 9 + ".swp"]  # 32 and 31 bytes
        bad = ["aa" + zh * 9 + ".swp", zh * 10 + ".swp"]  # 33 and 34 bytes
        for name in ok:
            with self.subTest(ok=name):
                self.assertEqual(rs.swap_argument(name), name)
        for name in bad:
            with self.subTest(bad=name), self.assertRaises(ValueError):
                rs.swap_argument(name)
        # LOWERC changes A-Z only, so a non-ASCII capital is not refused
        self.assertEqual(rs.swap_argument("\u00c4.swp"), "\u00c4.swp")

    def test_met_name_limit(self):
        # TTUTIL strings are ASCII only (class-1 bytes refused), so bytes ==
        # characters here; non-ASCII in a string is a TTUTIL syntax error
        with self.assertRaises(rd.SwpSyntaxError):
            read("PATHATM = './\u7ad9/'\n".encode())
        with self.assertRaises(rd.SwpSyntaxError):
            read(b"PATHATM = './a\tb/'\n")
        for pathatm, over in (("./" + "a" * 72 + "/", False),   # 75+5 = 80
                              ("./" + "a" * 73 + "/", True)):   # 76+5 = 81
            k = read(("PATHATM = '" + pathatm + "'\nMETFIL = 'x.met'\n").encode())
            errors, warnings = [], []
            rs._check_referenced_files("/nonexistent_ki_test", k, errors, warnings)
            with self.subTest(over=over):
                self.assertEqual(any("bytes" in e and "80" in e for e in errors), over)

    def test_completion_proof(self):
        ok = {"returncode": 100,
              "stdout": "  running swap ....\n Swap normal completion!\n"}
        self.assertTrue(rs.swap_run_succeeded(ok, "/w"))
        # PROJECT echoed with SWSCRE = 2, then a fatal error (exit 0)
        echoed = {"returncode": 0, "stdout":
                  " SWAP normal completion regression\n Swap normal completion!"
                  " x\n Fatal irdat, no input date within simulation period\n"}
        self.assertFalse(rs.swap_run_succeeded(echoed, "/w"))
        early = {"returncode": 0, "stdout":
                 " Swap normal completion!\n Fatal error after it\n"}
        self.assertFalse(rs.swap_run_succeeded(early, "/w"))
        self.assertFalse(rs.swap_run_succeeded(
            {"returncode": 1, "stdout": " Swap normal completion!\n"}, "/w"))
        self.assertFalse(rs.swap_run_succeeded({"returncode": 100, "stdout": ""}, "/w"))

    def test_output_names(self):
        k = read("PATHWORK = './Out/  '\nOUTFIL = 'Result '\n")
        self.assertEqual(rs.output_path("/w", k, ".blc"), "/w/./out/result.blc")
        self.assertEqual(rs.output_path("/w", k, ".tem"), "/w/./Out/Result.tem")


if __name__ == "__main__":
    unittest.main()
