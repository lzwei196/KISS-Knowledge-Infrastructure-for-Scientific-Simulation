"""run_ef5.validate_output must turn EF5's zero-filled missing forcing into an error."""
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

TOOL = Path(__file__).resolve().parents[1] / "tools" / "run_ef5.py"
spec = importlib.util.spec_from_file_location("run_ef5", TOOL)
run_ef5 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run_ef5)


class ValidateOutputTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.control = Path(self.tmp.name) / "control.txt"
        self.control.write_text("[Basic]\nDEM=dem.tif\n")

    def tearDown(self):
        self.tmp.cleanup()

    def fake_stdout(self, steps=("2099-12-31 23:59",)):
        """What EF5 prints: 'Executing task <name>' per execution (ExecutionController.cpp:70) and one
        'YYYY-MM-DD HH:UU' line per time step (Simulator.cpp:1341/674/1730)."""
        secs = run_ef5.parse_control_file(str(self.control))
        out = ""
        for n in run_ef5.executed_task_names(secs):
            out += f"\x1b[32mINFO:ExecutionController.cpp(70): \x1b[0mExecuting task {n}\n"
            out += "".join(f"{s}\n" for s in steps)
        return out

    def errors(self, stdout, returncode=0, ran=True):
        if ran:
            stdout = self.fake_stdout() + stdout
        msgs = run_ef5.validate_output(str(self.control), stdout, "", returncode)
        return [m for m in msgs if m.startswith("[ERROR]")]

    def test_missing_forcing_is_error(self):
        for line in ("Missing precip file(/x/p.tif)... Assuming zeros.",
                     "Missing PET file(/x/e.tif)... Assuming zeros.",
                     "Missing Temp file(/x/t.tif)... Assuming zeros.",
                     "Unsupported precip format!"):
            with self.subTest(line=line):
                self.assertTrue(self.errors("20200101_0000 " + line + "\n"))

    def test_ef5_error_log_line_is_error(self):
        line = ("\x1b[31mERROR:Simulator.cpp(84): \x1b[0mThe time step for precip must be "
                "greater or equal to the overall time step.\n")
        self.assertTrue(self.errors(line))

    def test_empty_output_dir_is_error(self):
        out = Path(self.tmp.name) / "out"
        out.mkdir()
        self.control.write_text(f"[Task Simu]\nOUTPUT={out}\n")
        msgs = run_ef5.validate_output(str(self.control), self.fake_stdout(), "", 0)
        self.assertTrue(any(m.startswith("[ERROR] No model output files") for m in msgs))

    def _write(self, text):
        self.control.write_text(text)

    def test_only_executed_tasks_checked(self):
        root = Path(self.tmp.name)
        (root / "run_out").mkdir()
        (root / "run_out" / "ts.g1.crest.csv").write_text("Time,Discharge\n2020,1.0\n")
        (root / "unused_out").mkdir()
        self._write("[Task run]\nOUTPUT=run_out\n[Task unused]\nOUTPUT=unused_out\n"
                    "[Execute]\nTASK=run\n")
        self.assertEqual(self.errors(""), [])

    def test_repeated_execute_tasks_all_checked(self):
        root = Path(self.tmp.name)
        (root / "a").mkdir()
        (root / "a" / "ts.g.crest.csv").write_text("Time,Discharge\n2020,1.0\n")
        (root / "b").mkdir()
        self._write("[Task a]\nOUTPUT=a\n[Task b]\nOUTPUT=b\n[Execute]\nTASK=a\nTASK=b\n")
        errs = self.errors("")
        self.assertEqual(len([e for e in errs if "No model output files" in e]), 1)

    def test_relative_output_resolved_against_control_dir(self):
        root = Path(self.tmp.name)
        (root / "out").mkdir()
        (root / "out" / "ts.g.crest.csv").write_text("Time,Discharge\n2020,1.0\n")
        self._write("[Task t]\nOUTPUT=out\n[Execute]\nTASK=t\n")
        cwd = os.getcwd()
        other = tempfile.mkdtemp(dir=self.tmp.name)
        try:
            os.chdir(other)
            self.assertEqual(self.errors(""), [])
        finally:
            os.chdir(cwd)

    def test_housekeeping_only_is_error(self):
        root = Path(self.tmp.name)
        (root / "out").mkdir()
        (root / "out" / "results.json").write_text("{}")
        (root / "out" / "ts.g.crest.csv").mkdir()  # a directory where the CSV should be
        self._write("[Task t]\nOUTPUT=out\n[Execute]\nTASK=t\n")
        self.assertTrue(self.errors(""))

    def test_gauge_open_failure_is_error(self):
        self.assertTrue(self.errors('WARNING:Simulator.cpp(391): Failed to open gauge output file "x"\n'))

    def test_basin_avg_fallthrough_line_tolerated_once(self):
        root = Path(self.tmp.name)
        (root / "out").mkdir()
        (root / "out" / "precip.20200101.avg.tif").write_text("x")
        self._write("[Task avg]\nSTYLE=BASIN_AVG\nTIME_BEGIN=202001010000\nTIME_END=202001020000\nTIMESTEP=1h\nOUTPUT=out\n[Execute]\nTASK=avg\n")
        quirk = '\x1b[31mERROR:ExecutionController.cpp(96): \x1b[0mUnimplemented simulation run style "7"\n'
        self.assertEqual(self.errors(quirk), [])
        self.assertTrue(self.errors(quirk + quirk))
        self.assertTrue(self.errors(quirk + "ERROR:Simulator.cpp(84): bad time step\n"))

    def test_unimplemented_style_without_basin_avg_is_error(self):
        self.assertTrue(self.errors('ERROR:ExecutionController.cpp(96): Unimplemented simulation run style "9"\n'))

    def test_block_commented_task_ignored(self):
        root = Path(self.tmp.name)
        (root / "run").mkdir()
        (root / "run" / "ts.g.crest.csv").write_text("Time,Discharge\n2020,1.0\n")
        (root / "unused").mkdir()
        self._write("[Task run]\nOUTPUT=run\n[Task unused]\nOUTPUT=unused\n"
                    "[Execute]\nTASK=run\n/*\nTASK=unused\n*/\n")
        self.assertEqual(self.errors(""), [])

    def test_repeated_basin_avg_executions_counted(self):
        root = Path(self.tmp.name)
        (root / "out").mkdir()
        (root / "out" / "precip.avg.tif").write_text("x")
        (root / "out" / "ts.g.crest.csv").write_text("Time,Discharge(m^3 s^-1)\n")  # header only, normal here
        self._write("[Task avg]\nSTYLE=BASIN_AVG\nTIME_BEGIN=202001010000\nTIME_END=202001020000\nTIMESTEP=1h\nOUTPUT=out\n[Execute]\nTASK=avg\nTASK=avg\n")
        quirk = 'ERROR:ExecutionController.cpp(96): Unimplemented simulation run style "7"\n'
        self.assertEqual(self.errors(quirk + quirk), [])
        self.assertTrue(self.errors(quirk * 3))

    def test_header_only_gauge_csv_is_error(self):
        root = Path(self.tmp.name)
        (root / "out").mkdir()
        (root / "out" / "ts.g.crest.csv").write_text("Time,Discharge(m^3 s^-1)\n")
        self._write("[Gauge g]\nLAT=1\nLON=1\n[Basin A]\nGAUGE=g\n[Task t]\nSTYLE=SIMU\nTIME_BEGIN=202001010000\nTIME_END=202001020000\nTIMESTEP=1h\nMODEL=CREST\nBASIN=A\nOUTPUT=out\n[Execute]\nTASK=t\n")
        self.assertTrue(any("no data rows" in e for e in self.errors("")))

    def test_stale_files_not_counted(self):
        import time as _t
        root = Path(self.tmp.name)
        (root / "out").mkdir()
        old = root / "out" / "ts.g.crest.csv"
        old.write_text("Time,Discharge\n2020,1.0\n")
        os.utime(old, (_t.time() - 3600, _t.time() - 3600))
        self._write("[Task t]\nOUTPUT=out\n[Execute]\nTASK=t\n")
        msgs = run_ef5.validate_output(str(self.control), self.fake_stdout(), "", 0, run_start=_t.time())
        self.assertTrue(any(m.startswith("[ERROR] No model output files") for m in msgs))

    def test_combined_output_only_is_ok(self):
        root = Path(self.tmp.name)
        (root / "out").mkdir()
        (root / "co").mkdir()
        (root / "co" / "combined.csv").write_text("202001010000,g,1.5\n")
        self._write("[Gauge g]\nLAT=1\nLON=1\nOUTPUTTS=no\nWANTCO=yes\n[Basin A]\nGAUGE=g\n"
                    "[Task sim]\nSTYLE=SIMU\nTIME_BEGIN=202001010000\nTIME_END=202001020000\nTIMESTEP=1h\nMODEL=CREST\nBASIN=A\nOUTPUT=out\nCO_FILE=co/combined.csv\n"
                    "[Execute]\nTASK=sim\n")
        self.assertEqual(self.errors(""), [])
        (root / "co" / "combined.csv").write_text("")
        self.assertTrue(self.errors(""))

    def test_outputts_false_gauge_not_required(self):
        root = Path(self.tmp.name)
        (root / "out").mkdir()
        (root / "out" / "q.20200101_0000.crest.tif").write_text("x")
        (root / "out" / "ts.ga.crest.csv").write_text("Time,Discharge\n")  # stale header from elsewhere
        self._write("[Gauge ga]\nLAT=1\nLON=1\nOUTPUTTS=false\n[Basin A]\nGAUGE=ga\n"
                    "[Task sim]\nSTYLE=SIMU\nTIME_BEGIN=202001010000\nTIME_END=202001020000\nTIMESTEP=1h\nMODEL=CREST\nBASIN=A\nOUTPUT=out\n"
                    "[Execute]\nTASK=sim\n")
        self.assertEqual(self.errors(""), [])

    def test_missing_expected_gauge_csv_is_error(self):
        root = Path(self.tmp.name)
        (root / "out").mkdir()
        (root / "out" / "ts.ga.crest.csv").write_text("Time,Discharge\n2020,1.0\n")
        self._write("[Gauge ga]\nLAT=1\nLON=1\n[Gauge gb]\nLAT=99\nLON=99\n"
                    "[Basin A]\nGAUGE=ga\nGAUGE=gb\n"
                    "[Task sim]\nSTYLE=SIMU\nTIME_BEGIN=202001010000\nTIME_END=202001020000\nTIMESTEP=1h\nMODEL=CREST\nBASIN=A\nOUTPUT=out\n[Execute]\nTASK=sim\n")
        errs = self.errors('WARNING:BasicGrids.cpp(668): Gauge gb is outside the basic grid domain!\n')
        self.assertTrue(any("ts.gb.crest.csv" in e for e in errs))

    def test_outputts_no_spelling_honoured(self):
        root = Path(self.tmp.name)
        (root / "out").mkdir()
        (root / "out" / "q.20200101_0000.crest.tif").write_text("x")
        (root / "out" / "ts.ga.crest.csv").write_text("Time,Discharge\n")
        self._write("[Gauge ga]\nLAT=1\nLON=1\nOUTPUTTS=No\n[Basin A]\nGAUGE=ga\n"
                    "[Task sim]\nSTYLE=SIMU\nTIME_BEGIN=202001010000\nTIME_END=202001020000\nTIMESTEP=1h\nMODEL=CREST\nBASIN=A\nOUTPUT=out\n[Execute]\nTASK=sim\n")
        self.assertEqual(self.errors(""), [])

    def test_rapid_rerun_untouched_gauge_csv_is_error(self):
        import time as _t
        root = Path(self.tmp.name)
        (root / "out").mkdir()
        self._write("[Gauge ga]\nLAT=1\nLON=1\n[Gauge gb]\nLAT=2\nLON=2\n"
                    "[Basin A]\nGAUGE=ga\nGAUGE=gb\n"
                    "[Task sim]\nSTYLE=SIMU\nTIME_BEGIN=202001010000\nTIME_END=202001020000\nTIMESTEP=1h\nMODEL=CREST\nBASIN=A\nOUTPUT=out\n[Execute]\nTASK=sim\n")
        for g in ("ga", "gb"):
            (root / "out" / f"ts.{g}.crest.csv").write_text("Time,Discharge\n2020,1.0\n")
        pre = run_ef5.snapshot_gauge_csvs(str(self.control))
        start = _t.time()
        # the "run" rewrites only ga (gb dropped as out of domain); mtime of gb stays inside 1 s of start
        _t.sleep(0.01)
        (root / "out" / "ts.ga.crest.csv").write_text("Time,Discharge\n2021,2.0\n2021,3.0\n")
        msgs = run_ef5.validate_output(str(self.control), self.fake_stdout(), "", 0, run_start=start, pre_state=pre)
        errs = [m for m in msgs if m.startswith("[ERROR]")]
        self.assertTrue(any("ts.gb.crest.csv" in e for e in errs), errs)
        self.assertFalse(any("ts.ga.crest.csv" in e for e in errs), errs)

    def _co_case(self):
        root = Path(self.tmp.name)
        (root / "out").mkdir()
        (root / "co").mkdir()
        self._write("[Gauge ga]\nLAT=1\nLON=1\nOUTPUTTS=no\nWANTCO=yes\n[Basin A]\nGAUGE=ga\n"
                    "[Task sim]\nSTYLE=SIMU\nTIME_BEGIN=202001010000\nTIME_END=202001020000\nTIMESTEP=1h\nMODEL=CREST\nBASIN=A\nOUTPUT=out\nCO_FILE=co/combined.csv\n"
                    "[Execute]\nTASK=sim\n")
        return root / "co" / "combined.csv"

    def test_combined_output_quick_rerun_untouched_is_error(self):
        import time as _t
        co = self._co_case()
        co.write_text("20200101_0000,ga,1.500000\n")          # left by the previous run
        pre = run_ef5.snapshot_outputs(str(self.control))
        start = _t.time()                                      # rerun writes no rows (warm-up > end)
        msgs = run_ef5.validate_output(str(self.control), self.fake_stdout(), "", 0, run_start=start, pre_state=pre)
        self.assertTrue(any(m.startswith("[ERROR]") for m in msgs), msgs)

    def test_combined_output_appended_rows_ok(self):
        import time as _t
        co = self._co_case()
        co.write_text("20200101_0000,ga,1.500000\n")
        pre = run_ef5.snapshot_outputs(str(self.control))
        start = _t.time()
        with open(co, "a") as fh:
            fh.write("20200101_0100,ga,2.000000\n")
        msgs = run_ef5.validate_output(str(self.control), self.fake_stdout(), "", 0, run_start=start, pre_state=pre)
        self.assertEqual([m for m in msgs if m.startswith("[ERROR]")], [])

    def test_combined_output_touched_without_rows_is_error(self):
        import time as _t
        co = self._co_case()
        co.write_text("20200101_0000,ga,1.500000\n")
        pre = run_ef5.snapshot_outputs(str(self.control))
        start = _t.time()
        os.utime(co, None)                                     # opened for append, nothing written
        _t.sleep(0.01); os.utime(co, None)
        msgs = run_ef5.validate_output(str(self.control), self.fake_stdout(), "", 0, run_start=start, pre_state=pre)
        self.assertTrue(any(m.startswith("[ERROR]") for m in msgs), msgs)

    # --- fail-closed rule: executed tasks must not share OUTPUT or CO_FILE ---
    def test_shared_output_dir_is_conflict(self):
        self._write("[Task avg]\nSTYLE=BASIN_AVG\nTIME_BEGIN=202001010000\nTIME_END=202001020000\nTIMESTEP=1h\nMODEL=CREST\nOUTPUT=out\n"
                    "[Task sim]\nSTYLE=SIMU\nTIME_BEGIN=202001010000\nTIME_END=202001020000\nTIMESTEP=1h\nMODEL=SAC\nOUTPUT=./out/\n"
                    "[Execute]\nTASK=avg\nTASK=sim\n")
        c = run_ef5.shared_output_conflicts(str(self.control))
        self.assertEqual(len(c), 1)
        self.assertIn("avg", c[0]); self.assertIn("sim", c[0]); self.assertIn("OUTPUT", c[0])
        self.assertTrue(any("own OUTPUT" in e for e in self.errors("")))

    def test_shared_co_file_is_conflict(self):
        self._write("[Task ta]\nSTYLE=SIMU\nTIME_BEGIN=202001010000\nTIME_END=202001020000\nTIMESTEP=1h\nOUTPUT=outa\nCO_FILE=co/combined.csv\n"
                    "[Task tb]\nSTYLE=SIMU\nTIME_BEGIN=202001010000\nTIME_END=202001020000\nTIMESTEP=1h\nOUTPUT=outb\nCO_FILE=./co/../co/combined.csv\n"
                    "[Execute]\nTASK=ta\nTASK=tb\n")
        c = run_ef5.shared_output_conflicts(str(self.control))
        self.assertTrue(any("CO_FILE" in x and "ta" in x and "tb" in x for x in c), c)

    def test_co_file_inside_other_task_output_is_conflict(self):
        self._write("[Task ta]\nSTYLE=SIMU\nTIME_BEGIN=202001010000\nTIME_END=202001020000\nTIMESTEP=1h\nOUTPUT=outa\nCO_FILE=outb/combined.csv\n"
                    "[Task tb]\nSTYLE=SIMU\nTIME_BEGIN=202001010000\nTIME_END=202001020000\nTIMESTEP=1h\nOUTPUT=outb\n"
                    "[Execute]\nTASK=ta\nTASK=tb\n")
        self.assertTrue(run_ef5.shared_output_conflicts(str(self.control)))

    def test_unexecuted_or_repeated_task_is_not_conflict(self):
        self._write("[Task a]\nSTYLE=SIMU\nTIME_BEGIN=202001010000\nTIME_END=202001020000\nTIMESTEP=1h\nOUTPUT=out\n[Task b]\nSTYLE=SIMU\nTIME_BEGIN=202001010000\nTIME_END=202001020000\nTIMESTEP=1h\nOUTPUT=out\n"
                    "[Execute]\nTASK=a\nTASK=a\n")
        self.assertEqual(run_ef5.shared_output_conflicts(str(self.control)), [])

    def test_separate_dirs_basin_avg_and_simu_ok(self):
        root = Path(self.tmp.name)
        (root / "oavg").mkdir(); (root / "osim").mkdir()
        (root / "oavg" / "ts.ga.crest.csv").write_text("Time,Discharge\n")          # BASIN_AVG header only
        (root / "oavg" / "precip.20200101_0100.avg.tif").write_text("x")             # its real output
        (root / "osim" / "ts.gb.crest.csv").write_text("Time,Discharge\n2020,1.0\n")
        self._write("[Gauge ga]\nLAT=1\nLON=1\n[Gauge gb]\nLAT=2\nLON=2\n"
                    "[Basin A]\nGAUGE=ga\n[Basin B]\nGAUGE=gb\n"
                    "[Task avg]\nSTYLE=BASIN_AVG\nTIME_BEGIN=202001010000\nTIME_END=202001020000\nTIMESTEP=1h\nMODEL=CREST\nBASIN=A\nOUTPUT=oavg\n"
                    "[Task sim]\nSTYLE=SIMU\nTIME_BEGIN=202001010000\nTIME_END=202001020000\nTIMESTEP=1h\nMODEL=CREST\nBASIN=B\nOUTPUT=osim\n"
                    "[Execute]\nTASK=avg\nTASK=sim\n")
        quirk = 'ERROR:ExecutionController.cpp(96): Unimplemented simulation run style "7"\n'
        self.assertEqual(self.errors(quirk), [])

    def test_cli_refuses_shared_output_before_running(self):
        import subprocess, sys as _sys
        self._write("[Task a]\nSTYLE=SIMU\nTIME_BEGIN=202001010000\nTIME_END=202001020000\nTIMESTEP=1h\nOUTPUT=out\n[Task b]\nSTYLE=SIMU\nTIME_BEGIN=202001010000\nTIME_END=202001020000\nTIMESTEP=1h\nOUTPUT=out\n"
                    "[Execute]\nTASK=a\nTASK=b\n")
        marker = Path(self.tmp.name) / "ran"
        fake = Path(self.tmp.name) / "fake_ef5"
        fake.write_text(f"#!/bin/sh\ntouch {marker}\n")
        fake.chmod(0o755)
        r = subprocess.run([_sys.executable, str(TOOL), "--binary", str(fake), "--control",
                            str(self.control), "--skip-preflight"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn("own OUTPUT and CO_FILE", r.stderr)
        self.assertFalse(marker.exists())

    def test_hash_commented_block_markers_follow_engine(self):
        # EF5 ignores whole '#' lines, so '# /*' does not open a block comment and TASK=b runs
        self._write("[Task a]\nSTYLE=SIMU\nTIME_BEGIN=202001010000\nTIME_END=202001020000\nTIMESTEP=1h\nOUTPUT=out\n[Task b]\nSTYLE=SIMU\nTIME_BEGIN=202001010000\nTIME_END=202001020000\nTIMESTEP=1h\nOUTPUT=out\n"
                    "[Execute]\nTASK=a\n# /*\nTASK=b\n# */\n")
        secs = run_ef5.parse_control_file(str(self.control))
        self.assertEqual(run_ef5.executed_task_names(secs), ["a", "b"])
        self.assertTrue(run_ef5.shared_output_conflicts(str(self.control)))

    def test_comment_markers_inside_value_are_literal(self):
        self._write("[Task a]\nSTYLE=SIMU\nTIME_BEGIN=202001010000\nTIME_END=202001020000\nTIMESTEP=1h\nOUTPUT=out#x\n[Execute]\nTASK=a\n")
        secs = run_ef5.parse_control_file(str(self.control))
        self.assertEqual(secs["task:a"]["output"], "out#x")

    def test_max_raster_only_run_judged_by_stdout_steps(self):
        root = Path(self.tmp.name)
        (root / "out").mkdir()
        (root / "out" / "maxq.20200101.000000.tif").write_text("x")   # written after the loop
        self._write("[Gauge ga]\nLAT=1\nLON=1\nOUTPUTTS=no\n[Basin A]\nGAUGE=ga\n"
                    "[Task sim]\nSTYLE=SIMU\nTIME_BEGIN=202001010000\nTIME_END=202001020000\nTIMESTEP=1h\nMODEL=CREST\nBASIN=A\nOUTPUT=out\n"
                    "TIME_BEGIN=202001010000\nTIME_WARMEND=202001010000\nTIME_END=202001010200\n"
                    "TIMESTEP=1h\nOUTPUT_GRIDS=MAXSTREAMFLOW\n[Execute]\nTASK=sim\n")
        two_steps = self.fake_stdout(steps=("2020-01-01 01:00", "2020-01-01 02:00"))
        self.assertEqual(self.errors(two_steps, ran=False), [])            # valid MAX-only run
        zero = self.fake_stdout(steps=())
        self.assertTrue(any("ran no time step" in e for e in self.errors(zero, ran=False)))

    def test_steps_only_during_warmup_is_error(self):
        root = Path(self.tmp.name)
        (root / "out").mkdir()
        (root / "out" / "maxq.x.tif").write_text("x")
        self._write("[Task sim]\nSTYLE=SIMU\nTIME_BEGIN=202001010000\nTIME_END=202001020000\nTIMESTEP=1h\nMODEL=CREST\nOUTPUT=out\nTIME_BEGIN=202001010000\n"
                    "TIME_WARMEND=202001020000\nTIME_END=202001010300\nTIMESTEP=1h\n[Execute]\nTASK=sim\n")
        warm = self.fake_stdout(steps=("2020-01-01 01:00", "2020-01-01 02:00", "2020-01-01 03:00"))
        self.assertTrue(any("after warm-up" in e for e in self.errors(warm, ran=False)))

    def test_basin_avg_zero_step_is_error(self):
        root = Path(self.tmp.name)
        (root / "out").mkdir()
        (root / "out" / "ts.ga.crest.csv").write_text("Time,Discharge\n")      # header only
        self._write("[Task avg]\nSTYLE=BASIN_AVG\nTIME_BEGIN=202001010000\nTIME_END=202001020000\nTIMESTEP=1h\nMODEL=CREST\nOUTPUT=out\n[Execute]\nTASK=avg\n")
        quirk = 'ERROR:ExecutionController.cpp(96): Unimplemented simulation run style "7"\n'
        errs = self.errors(self.fake_stdout(steps=()) + quirk, ran=False)
        self.assertTrue(any("ran no time step" in e for e in errs), errs)
        self.assertTrue(any("precip.*.avg.tif" in e for e in errs), errs)

    def test_each_execution_needs_its_own_steps(self):
        root = Path(self.tmp.name)
        (root / "out").mkdir()
        (root / "out" / "q.20200101_0100.crest.tif").write_text("x")
        self._write("[Task sim]\nSTYLE=SIMU\nTIME_BEGIN=202001010000\nTIME_END=202001020000\nTIMESTEP=1h\nMODEL=CREST\nOUTPUT=out\n[Execute]\nTASK=sim\nTASK=sim\n")
        out = ("INFO: Executing task sim\n2099-01-01 00:00\n"
               "INFO: Executing task sim\n")                                   # 2nd run no steps
        self.assertTrue(any("ran no time step" in e for e in self.errors(out, ran=False)))

    def test_missing_executing_line_is_error(self):
        root = Path(self.tmp.name)
        (root / "out").mkdir()
        (root / "out" / "q.20200101_0100.crest.tif").write_text("x")
        self._write("[Task sim]\nSTYLE=SIMU\nTIME_BEGIN=202001010000\nTIME_END=202001020000\nTIMESTEP=1h\nMODEL=CREST\nOUTPUT=out\n[Execute]\nTASK=sim\n")
        self.assertTrue(any("no 'Executing task" in e for e in self.errors("", ran=False)))

    def test_requested_grid_missing_is_error(self):
        root = Path(self.tmp.name)
        (root / "out").mkdir()
        (root / "out" / "maxq.x.tif").write_text("x")
        self._write("[Task sim]\nSTYLE=SIMU\nTIME_BEGIN=202001010000\nTIME_END=202001020000\nTIMESTEP=1h\nMODEL=CREST\nOUTPUT=out\nOUTPUT_GRIDS=STREAMFLOW|MAXSTREAMFLOW\n"
                    "[Execute]\nTASK=sim\n")
        self.assertTrue(any("STREAMFLOW" in e and "q.*.tif" in e for e in self.errors("")))

    def test_calibration_zero_step_window_rejected_before_run(self):
        self._write("[Task cal]\nSTYLE=CALI_DREAM\nMODEL=CREST\nOUTPUT=out\nTIME_BEGIN=202001010000\n"
                    "TIME_WARMEND=202001010000\nTIME_END=202001010200\nTIMESTEP=3h\n[Execute]\nTASK=cal\n")
        self.assertTrue(run_ef5.zero_step_window_errors(str(self.control)))
        self._write("[Task cal]\nSTYLE=CALI_DREAM\nMODEL=CREST\nOUTPUT=out\nTIME_BEGIN=202001010000\n"
                    "TIME_WARMEND=202001010000\nTIME_END=202001010600\nTIMESTEP=3h\n[Execute]\nTASK=cal\n")
        self.assertEqual(run_ef5.zero_step_window_errors(str(self.control)), [])
        self._write("[Task cal]\nSTYLE=CALI_DREAM\nTIME_BEGIN=202001310000\nTIME_END=202002290000\n"
                    "TIMESTEP=1m\n[Execute]\nTASK=cal\n")       # Jan 31 + 1 month = Mar 2 (mktime) > end
        self.assertTrue(run_ef5.zero_step_window_errors(str(self.control)))

    def test_requested_combined_output_missing_is_error_despite_other_output(self):
        root = Path(self.tmp.name)
        (root / "out").mkdir(); (root / "co").mkdir()
        (root / "out" / "ts.ga.crest.csv").write_text("Time,Discharge\n2020,1.0\n")
        (root / "co" / "combined.csv").write_text("")
        self._write("[Gauge ga]\nLAT=1\nLON=1\n[Gauge gb]\nLAT=99\nLON=99\nOUTPUTTS=no\nWANTCO=yes\n"
                    "[Basin A]\nGAUGE=ga\nGAUGE=gb\n"
                    "[Task sim]\nSTYLE=SIMU\nTIME_BEGIN=202001010000\nTIME_END=202001020000\nTIMESTEP=1h\nMODEL=CREST\nBASIN=A\nOUTPUT=out\nCO_FILE=co/combined.csv\n"
                    "[Execute]\nTASK=sim\n")
        self.assertTrue(any("CO_FILE" in e for e in self.errors("")))

    def test_subminute_steps_judged_by_step_index(self):
        root = Path(self.tmp.name)
        (root / "out").mkdir()
        (root / "out" / "maxq.x.tif").write_text("x")
        base = ("[Gauge g]\nLAT=1\nLON=1\nOUTPUTTS=no\n[Basin A]\nGAUGE=g\n"
                "[Task sim]\nSTYLE=SIMU\nMODEL=CREST\nBASIN=A\nOUTPUT=out\nTIME_BEGIN=20200101000000\n"
                "TIMESTEP=30s\n{w}[Execute]\nTASK=sim\n")
        one_line = "INFO: Executing task sim\n2020-01-01 00:00\n"
        # warm-up ends 00:00:59, end 00:00:30: the one step (00:00:30) is still warm-up
        self._write(base.format(w="TIME_WARMEND=20200101000059\nTIME_END=20200101000030\n"))
        self.assertTrue(any("after warm-up" in e for e in self.errors(one_line, ran=False)))
        # warm-up end = end = 00:00:30: the one printed step IS post-warm-up (codex r18 case)
        self._write(base.format(w="TIME_WARMEND=20200101000030\nTIME_END=20200101000030\n"))
        self.assertEqual(self.errors(one_line, ran=False), [])

    def test_zero_or_bad_calibration_step_refused_quickly(self):
        import time as _t
        self._write("[Task cal]\nSTYLE=CALI_DREAM\nTIME_BEGIN=202001010000\nTIME_WARMEND=202001020000\n"
                    "TIME_END=202001030000\nTIMESTEP=0h\n[Execute]\nTASK=cal\n")
        t0 = _t.time()
        errs = run_ef5.zero_step_window_errors(str(self.control))
        self.assertTrue(errs and "positive" in errs[0])
        self.assertLess(_t.time() - t0, 1.0)
        # a 1-second step over ten years is computed directly, not by looping
        self._write("[Task cal]\nSTYLE=CALI_DREAM\nTIME_BEGIN=200001010000\nTIME_WARMEND=201001010000\n"
                    "TIME_END=201001010001\nTIMESTEP=1s\n[Execute]\nTASK=cal\n")
        t0 = _t.time()
        self.assertEqual(run_ef5.zero_step_window_errors(str(self.control)), [])
        self.assertLess(_t.time() - t0, 1.0)

    def test_every_wantco_gauge_needs_its_own_new_row(self):
        import time as _t
        root = Path(self.tmp.name)
        (root / "out").mkdir(); (root / "co").mkdir()
        co = root / "co" / "combined.csv"
        self._write("[Gauge ga]\nLAT=1\nLON=1\nOUTPUTTS=no\nWANTCO=yes\n"
                    "[Gauge gb]\nLAT=99\nLON=99\nOUTPUTTS=no\nWANTCO=yes\n[Basin A]\nGAUGE=ga\nGAUGE=gb\n"
                    "[Task sim]\nSTYLE=SIMU\nMODEL=CREST\nBASIN=A\nOUTPUT=out\nCO_FILE=co/combined.csv\n"
                    "TIME_BEGIN=202001010000\nTIME_END=202001020000\nTIMESTEP=1h\n[Execute]\nTASK=sim\n")
        pre = run_ef5.snapshot_outputs(str(self.control))
        start = _t.time()
        co.write_text("2020-01-01 01:00,ga,1.5\n")                     # gb dropped, no rows
        msgs = run_ef5.validate_output(str(self.control), self.fake_stdout(), "", 0,
                                       run_start=start, pre_state=pre)
        errs = [m for m in msgs if m.startswith("[ERROR]")]
        self.assertTrue(any("WANTCO gauge gb" in e for e in errs), errs)
        self.assertFalse(any("gauge ga" in e for e in errs), errs)

    def test_time_parsing_matches_timevar_loadtime(self):
        import datetime as _dt
        P = run_ef5._parse_ef5_time
        self.assertEqual(P("20200102"), _dt.datetime(2020, 1, 2))           # date only = midnight
        self.assertEqual(P("2020"), _dt.datetime(2020, 1, 1))
        self.assertEqual(P("202001021530"), _dt.datetime(2020, 1, 2, 15, 30))
        self.assertEqual(P("20200102153045"), _dt.datetime(2020, 1, 2, 15, 30, 45))
        self.assertEqual(P("202013"), _dt.datetime(2021, 1, 1))              # timegm normalisation
        self.assertEqual(P("20200132"), _dt.datetime(2020, 2, 1))
        with self.assertRaises(run_ef5.TimeParseError):
            P("abc")

    def test_explicit_unparseable_warmend_rejected_absent_defaults_to_begin(self):
        self._write("[Task sim]\nSTYLE=SIMU\nTIME_BEGIN=202001010000\nTIME_WARMEND=soon\n"
                    "TIME_END=202001020000\n[Execute]\nTASK=sim\n")
        self.assertTrue(run_ef5.time_errors(str(self.control)))
        self._write("[Task sim]\nSTYLE=SIMU\nTIME_BEGIN=202001010000\nTIME_END=202001020000\nTIMESTEP=1h\n"
                    "[Execute]\nTASK=sim\n")
        self.assertEqual(run_ef5.time_errors(str(self.control)), [])
        secs = run_ef5.parse_control_file(str(self.control))
        b, w, e = run_ef5.task_times(secs["task:sim"])
        self.assertEqual(w, b)

    def test_date_only_warmend_all_warmup_is_error(self):
        root = Path(self.tmp.name)
        (root / "out").mkdir()
        (root / "out" / "maxq.x.tif").write_text("x")
        self._write("[Gauge g]\nLAT=1\nLON=1\nOUTPUTTS=no\n[Basin A]\nGAUGE=g\n"
                    "[Task sim]\nSTYLE=SIMU\nMODEL=CREST\nBASIN=A\nOUTPUT=out\nTIME_BEGIN=20200101\n"
                    "TIME_WARMEND=20200102\nTIME_END=202001010100\nTIMESTEP=1h\n"
                    "OUTPUT_GRIDS=MAXSTREAMFLOW\n[Execute]\nTASK=sim\n")
        out = self.fake_stdout(steps=("2020-01-01 01:00",))
        self.assertTrue(any("after warm-up" in e for e in self.errors(out, ran=False)))
        cal = self.control.read_text().replace("STYLE=SIMU", "STYLE=CALI_DREAM")
        self._write(cal)
        self.assertTrue(run_ef5.zero_step_window_errors(str(self.control)))

    def test_dropped_gauge_warning_is_error(self):
        errs = self.errors('\x1b[33mWARNING:src/BasicGrids.cpp(668): \x1b[0mGauge gx is outside the '
                           'basic grid domain!\n')
        self.assertTrue(any("Gauge gx is outside" in e for e in errs), errs)

    def test_unresolved_basin_fails_closed(self):
        root = Path(self.tmp.name)
        (root / "out").mkdir()
        (root / "out" / "q.20200101_0100.crest.tif").write_text("x")
        self._write("[Task sim]\nSTYLE=SIMU\nMODEL=CREST\nBASIN=nobasin\nOUTPUT=out\n"
                    "TIME_BEGIN=202001010000\nTIME_END=202001020000\nTIMESTEP=1h\n[Execute]\nTASK=sim\n")
        self.assertTrue(any("cannot be resolved" in e for e in self.errors("")))

    def test_nonfinite_combined_discharge_is_error(self):
        import time as _t
        root = Path(self.tmp.name)
        (root / "out").mkdir(); (root / "co").mkdir()
        co = root / "co" / "combined.csv"
        self._write("[Gauge g]\nLAT=1\nLON=1\nOUTPUTTS=no\nWANTCO=yes\n[Basin A]\nGAUGE=g\n"
                    "[Task sim]\nSTYLE=SIMU\nMODEL=CREST\nBASIN=A\nOUTPUT=out\nCO_FILE=co/combined.csv\n"
                    "TIME_BEGIN=202001010000\nTIME_END=202001020000\nTIMESTEP=1h\n[Execute]\nTASK=sim\n")
        pre = run_ef5.snapshot_outputs(str(self.control))
        start = _t.time()
        co.write_text("2020-01-01 01:00,g,nan\n")
        msgs = run_ef5.validate_output(str(self.control), self.fake_stdout(), "", 0,
                                       run_start=start, pre_state=pre)
        self.assertTrue(any("non-finite" in m for m in msgs if m.startswith("[ERROR]")), msgs)

    def test_nonfinite_gauge_discharge_is_error(self):
        root = Path(self.tmp.name)
        (root / "out").mkdir()
        (root / "out" / "ts.g.crest.csv").write_text("Time,Discharge,Observed\n2020,nan,nan\n2020,1.0,nan\n")
        self._write("[Gauge g]\nLAT=1\nLON=1\n[Basin A]\nGAUGE=g\n"
                    "[Task sim]\nSTYLE=SIMU\nMODEL=CREST\nBASIN=A\nOUTPUT=out\n"
                    "TIME_BEGIN=202001010000\nTIME_END=202001020000\nTIMESTEP=1h\n[Execute]\nTASK=sim\n")
        self.assertTrue(any("non-finite Discharge" in e for e in self.errors("")))

    def test_preflight_accepts_date_only_times(self):
        self._write("[Basic]\nDEM=dem.tif\n[Task sim]\nSTYLE=SIMU\nTIME_BEGIN=20200101\nTIME_END=20200102\n"
                    "TIMESTEP=1h\n[Execute]\nTASK=sim\n")
        ok, msgs = run_ef5.preflight_check(str(self.control), "/nonexistent/ef5")
        self.assertFalse(any("time_begin" in m or "time_end" in m for m in msgs), msgs)

    def test_two_step_size_keys_refused(self):
        for extra in ("TIME_BEGIN_LR=202001010100\n", "TIMESTEP_LR=1u\n",
                      "TIME_BEGIN_LR=202001010100\nTIMESTEP_LR=2h\n"):
            with self.subTest(extra=extra):
                self._write("[Task sim]\nSTYLE=SIMU\nTIME_BEGIN=202001010000\nTIME_END=202001020000\n"
                            "TIMESTEP=1h\n" + extra + "[Execute]\nTASK=sim\n")
                errs = run_ef5.unsupported_step_key_errors(str(self.control))
                self.assertTrue(errs and "two-step-size" in errs[0], errs)
        # an unexecuted task with the keys is not a reason to refuse
        self._write("[Task a]\nSTYLE=SIMU\nTIMESTEP_LR=1u\n[Task b]\nSTYLE=SIMU\n[Execute]\nTASK=b\n")
        self.assertEqual(run_ef5.unsupported_step_key_errors(str(self.control)), [])

    def test_cli_refuses_two_step_size_before_running(self):
        import subprocess, sys as _sys
        self._write("[Task sim]\nSTYLE=SIMU\nOUTPUT=out\nTIME_BEGIN=202001010000\nTIME_END=202001020000\n"
                    "TIMESTEP=1h\nTIME_BEGIN_LR=202001010100\nTIMESTEP_LR=2h\n[Execute]\nTASK=sim\n")
        marker = Path(self.tmp.name) / "ran"
        fake = Path(self.tmp.name) / "fake_ef5"
        fake.write_text(f"#!/bin/sh\ntouch {marker}\n")
        fake.chmod(0o755)
        r = subprocess.run([_sys.executable, str(TOOL), "--binary", str(fake), "--control",
                            str(self.control), "--skip-preflight"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn("TIME_BEGIN_LR/TIMESTEP_LR", r.stderr)
        self.assertFalse(marker.exists())

    def test_ensemble_task_refused(self):
        self._write("[Task sim]\nSTYLE=SIMU\n[Execute]\nENSEMBLETASK=ens\n")
        self.assertTrue(any("ENSEMBLETASK" in e for e in run_ef5.unsupported_step_key_errors(str(self.control))))

    def test_clean_log_has_no_error(self):
        self.assertEqual(self.errors("20200101_0000\n"), [])

    def test_nonzero_exit_is_error(self):
        self.assertTrue(self.errors("", returncode=3))


if __name__ == "__main__":
    unittest.main()
