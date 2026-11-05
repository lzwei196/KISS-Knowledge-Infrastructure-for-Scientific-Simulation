"""Contract tests: CMFD sub-daily completeness and run_gr4j honest exit codes.

No R or airGR is needed: Rscript is replaced by a mock.
"""
import sys, tempfile, unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import convert_forcing_to_gr4j as C  # noqa: E402
import run_gr4j as R  # noqa: E402


def cmfd(days=3):
    t = pd.date_range('2000-01-01', periods=8 * days, freq='3h')
    return pd.DataFrame({'date': t, 'temp': 288.15, 'prec': 1.0})


class CMFDCompleteness(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)

    def conv(self, df, **kw):
        p = Path(self.d.name) / 'in.csv'
        df.to_csv(p, index=False)
        return C.convert_cmfd_to_airgr(str(p), 32.0, str(Path(self.d.name) / 'out.csv'), **kw)

    def test_complete_days_sum_8_steps(self):
        self.assertEqual(self.conv(cmfd())['Precip_mm'].tolist(), [8.0, 8.0, 8.0])

    def test_missing_data_fails(self):
        cases = {}
        df = cmfd(); df.loc[8:15, 'prec'] = np.nan; cases['all-nan day'] = df
        df = cmfd(); df.loc[3, 'prec'] = np.nan; cases['one nan prec'] = df
        df = cmfd(); df.loc[3, 'temp'] = np.nan; cases['one nan temp'] = df
        cases['one step missing'] = cmfd().drop(index=[10])
        cases['whole day missing'] = cmfd().drop(index=range(8, 16))
        df = cmfd(); df.loc[3, 'date'] = df.loc[2, 'date']; cases['duplicate'] = df
        df = cmfd(); df.loc[3, 'date'] += pd.Timedelta(minutes=30); cases['off grid'] = df
        for name, df in cases.items():
            with self.subTest(name):
                with self.assertRaises(ValueError):
                    self.conv(df)
                self.assertFalse((Path(self.d.name) / 'out.csv').exists())

    def test_qobs_unknown_column_or_no_area_fails(self):
        q = Path(self.d.name) / 'q.csv'
        pd.DataFrame({'date': pd.date_range('2000-01-01', periods=3), 'flow': [1, 2, 3]}).to_csv(q, index=False)
        with self.assertRaises(ValueError):
            self.conv(cmfd(), area_km2=100, qobs_csv=str(q))
        pd.DataFrame({'date': pd.date_range('2000-01-01', periods=3), 'Q_m3s': [1, 2, 3]}).to_csv(q, index=False)
        with self.assertRaises(ValueError):
            self.conv(cmfd(), qobs_csv=str(q))
        out = self.conv(cmfd(), area_km2=86.4, qobs_csv=str(q))
        np.testing.assert_allclose(out['Qobs_mm'], [1, 2, 3])


class Proc:
    def __init__(self, rc, stdout=''):
        self.returncode, self.stdout, self.stderr = rc, stdout, 'mock stderr'


class RunnerExitCodes(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        self.out = Path(self.d.name) / 'sim.csv'
        self.argv = ['run_gr4j', '--forcing', 'f.csv', '--output', str(self.out),
                     '--x1', '300', '--x2', '0', '--x3', '80', '--x4', '2']

    def main(self, side_effect):
        with mock.patch.object(R.subprocess, 'run', side_effect=side_effect), \
             mock.patch.object(R, 'validate_inputs', return_value=[]), \
             mock.patch.object(sys, 'argv', self.argv):
            R.main()

    @staticmethod
    def tmp_out(cmd):
        # the R script writes to the temporary path named in write.csv(...)
        src = Path(cmd[-1]).read_text()
        return src.split('write.csv(results, "')[1].split('"')[0]

    def test_r_failure_exits_nonzero_and_keeps_old_output(self):
        self.out.write_text('old good result\n')
        with self.assertRaises(SystemExit) as cm:
            self.main(lambda *a, **k: Proc(1))
        self.assertEqual(cm.exception.code, 1)
        self.assertEqual(self.out.read_text(), 'old good result\n')
        self.assertEqual(sorted(p.name for p in Path(self.d.name).iterdir()), ['sim.csv'])

    def test_no_output_written_exits_nonzero(self):
        self.out.write_text('stale\n')
        with self.assertRaises(SystemExit) as cm:
            self.main(lambda *a, **k: Proc(0, 'OUTPUT_ROWS: 3\n'))
        self.assertEqual(cm.exception.code, 1)
        self.assertEqual(self.out.read_text(), 'stale\n')

    def test_success_replaces_output(self):
        self.out.write_text('stale\n')

        def ok(cmd, **k):
            pd.DataFrame({'Qsim_mm': [1.0, 2.0, 3.0]}).to_csv(self.tmp_out(cmd), index=False)
            return Proc(0, 'OUTPUT_ROWS: 3\n')
        self.main(ok)  # no SystemExit -> exit 0
        self.assertEqual(pd.read_csv(self.out)['Qsim_mm'].tolist(), [1.0, 2.0, 3.0])
        self.assertEqual(sorted(p.name for p in Path(self.d.name).iterdir()), ['sim.csv'])

    def test_leftover_temp_json_never_published(self):
        # A killed earlier run (same PID or not) may leave temp files behind.
        # This run writes a CSV but no metadata JSON -> must fail, not publish
        # the leftover JSON.
        for name in ('.meta.tmp%d.json' % R.os.getpid(), 'meta.json.tmp'):
            (Path(self.d.name) / name).write_text('{"param": "stale"}')
        meta = Path(self.d.name) / 'meta.json'
        self.argv += ['--meta-json', str(meta)]

        def csv_only(cmd, **k):
            pd.DataFrame({'Qsim_mm': [1.0, 2.0]}).to_csv(self.tmp_out(cmd), index=False)
            return Proc(0, 'OUTPUT_ROWS: 2\n')
        with self.assertRaises(SystemExit) as cm:
            self.main(csv_only)
        self.assertEqual(cm.exception.code, 1)
        self.assertFalse(meta.exists())
        self.assertFalse(self.out.exists())

    def test_nonfinite_qsim_fails(self):
        for vals in ([float('nan')] * 3, [1.0, float('inf'), 2.0], []):
            with self.subTest(vals=vals):
                def bad(cmd, **k):
                    pd.DataFrame({'Qsim_mm': vals}).to_csv(self.tmp_out(cmd), index=False)
                    return Proc(0, 'OUTPUT_ROWS: 3\n')
                with self.assertRaises(SystemExit) as cm:
                    self.main(bad)
                self.assertEqual(cm.exception.code, 1)
                self.assertFalse(self.out.exists())

    def test_clashing_paths_or_single_date_bound_rejected(self):
        cases = {
            'meta == output': ['--meta-json', str(self.out)],
            'output == forcing': ['--forcing', str(self.out)],
            'start only': ['--start', '2005-01-01'],
            'end only': ['--end', '2005-12-31'],
        }
        calls = []
        for name, extra in cases.items():
            with self.subTest(name):
                self.argv = ['run_gr4j', '--forcing', 'f.csv', '--output', str(self.out),
                             '--x1', '300', '--x2', '0', '--x3', '80', '--x4', '2'] + extra
                with self.assertRaises(ValueError):
                    self.main(lambda *a, **k: calls.append(1) or Proc(0))
        self.assertEqual(calls, [])  # R never started


if __name__ == '__main__':
    unittest.main()
