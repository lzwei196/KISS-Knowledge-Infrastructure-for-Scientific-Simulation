"""Artificial observations for the strict observed-inflow contract."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np
import pandas as pd

KI = Path(os.environ.get('KI_UNDER_TEST', Path(__file__).resolve().parents[1]))
TOOL = KI / 'tools/s4_inflow/convert_obs_to_inflow.py'
spec = importlib.util.spec_from_file_location('observed_inflow', TOOL)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ObservedInflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.obs = self.root/'obs.tsv'
        self.out = self.root/'result/inflow.csv'
        self.dates = pd.date_range('2000-01-01', periods=121)

    def write(self, values=None, dates=None):
        dates = self.dates if dates is None else dates
        values = np.arange(len(dates), dtype=float) if values is None else values
        pd.DataFrame({'stcd':'TEST', 'dates':dates, 'z':0, 'Q':values,
                      'name':'人工测试站'}).to_csv(self.obs, sep='\t', index=False, encoding='gbk')

    def run_convert(self, **kw):
        return module.convert(str(self.obs), kw.pop('station_area_km2', None),
                              kw.pop('dam_area_km2', None),
                              str(self.dates[0].date()), str(self.dates[-1].date()),
                              str(self.out), **kw)

    def provenance(self):
        return json.loads(Path(str(self.out)+'.provenance.json').read_text())

    def test_missing_is_error_and_existing_output_untouched(self):
        self.write()
        frame = pd.read_csv(self.obs, sep='\t', encoding='gbk')
        frame.loc[5, 'Q'] = -9999
        frame.to_csv(self.obs, sep='\t', index=False, encoding='gbk')
        self.out.parent.mkdir()
        self.out.write_text('previous valid result\n')
        with self.assertRaises(ValueError): self.run_convert()
        self.assertEqual(self.out.read_text(), 'previous valid result\n')
        self.assertFalse(Path(str(self.out)+'.provenance.json').exists())

    def test_interpolation_is_explicit_and_auditable(self):
        values = np.arange(121, dtype=float); values[5:7] = -99
        self.write(values)
        self.run_convert(gap_fill='interpolate', station_area_km2=2, dam_area_km2=1)
        data = pd.read_csv(self.out)
        np.testing.assert_allclose(data.inflow_m3s, np.arange(121)/2)
        info = self.provenance()
        self.assertEqual(info['fill_count'], 2)
        first = info['fills'][0]
        self.assertEqual(first['date'], '2000-01-06')
        self.assertEqual(first['original_value'], '-99.0')
        self.assertEqual(first['method'], 'linear_interpolation')
        self.assertEqual(first['left']['date'], '2000-01-05')
        self.assertEqual(first['right']['date'], '2000-01-08')
        self.assertEqual(first['filled_Q_m3s'], 5)
        self.assertEqual(first['inflow_m3s'], 2.5)

    def test_unsupported_interpolation_never_falls_back(self):
        for indices in [slice(0,1), slice(120,121), slice(4,35), slice(0,121)]:
            with self.subTest(indices=indices):
                values=np.arange(121, dtype=float); values[indices]=-9999
                self.write(values)
                with self.assertRaises(ValueError): self.run_convert(gap_fill='interpolate')
                self.assertFalse(self.out.exists())

    def test_explicit_zero_records_absent_calendar_day(self):
        dates=self.dates.delete(2)
        self.write(np.ones(120), dates)
        self.run_convert(gap_fill='zero')
        self.assertEqual(pd.read_csv(self.out).inflow_m3s.iloc[2], 0)
        entry=self.provenance()['fills'][0]
        self.assertEqual(entry['original_value'], None)
        self.assertEqual(entry['reason'], 'absent_date')
        self.assertEqual(entry['method'], 'explicit_zero')

    def test_invalid_records_fail_before_output(self):
        for kind in ['inf', 'bad_number', 'bad_date', 'duplicate', 'unordered', 'negative', 'station']:
            with self.subTest(kind=kind):
                self.write()
                frame=pd.read_csv(self.obs,sep='\t',encoding='gbk',dtype=str)
                if kind=='inf': frame.loc[3,'Q']='inf'
                elif kind=='bad_number': frame.loc[3,'Q']='typo'
                elif kind=='bad_date': frame.loc[3,'dates']='bad-date'
                elif kind=='duplicate': frame.loc[3,'dates']=frame.loc[2,'dates']
                elif kind=='unordered': frame.loc[[2,3],'dates']=frame.loc[[3,2],'dates'].values
                elif kind=='negative': frame.loc[3,'Q']='-1'
                else: frame.loc[3,'stcd']='SECOND'
                frame.to_csv(self.obs,sep='\t',index=False,encoding='gbk')
                with self.assertRaises(ValueError): self.run_convert(gap_fill='zero')
                self.assertFalse(self.out.exists())

    def test_short_complete_record_preserves_values_and_zero(self):
        self.dates=self.dates[:3]
        self.write([0,0.0000123456789,2.123456789])
        self.run_convert()
        np.testing.assert_allclose(pd.read_csv(self.out).inflow_m3s,
                                   [0,0.0000123456789,2.123456789],rtol=1e-12)
        self.assertEqual(self.provenance()['fill_count'],0)

    def test_recorded_hash_matches_output_bytes(self):
        import hashlib
        self.write()
        self.run_convert()
        raw = self.out.read_bytes()
        # LF or CRLF (pandas uses the platform line end) is fine; the hash must match the bytes.
        self.assertEqual(hashlib.sha256(raw).hexdigest(), self.provenance()['output_sha256'])

    def test_area_arguments_must_be_paired_finite_positive(self):
        self.write()
        for a,b in [(None,2),(2,None),(0,2),(-1,2),(2,float('inf'))]:
            with self.subTest(a=a,b=b):
                with self.assertRaises(ValueError): self.run_convert(station_area_km2=a,dam_area_km2=b)
                self.assertFalse(self.out.exists())

    def test_cli_default_rejects_missing_day(self):
        self.write(dates=self.dates.delete(5))
        proc=subprocess.run([sys.executable,str(TOOL),'--obs_file',str(self.obs),
            '--start_date','2000-01-01','--end_date',str(self.dates[-1].date()),
            '--output',str(self.out)],capture_output=True,text=True)
        self.assertNotEqual(proc.returncode,0)
        self.assertIn('2000-01-06',proc.stderr)
        self.assertFalse(self.out.exists())


if __name__=='__main__': unittest.main()
