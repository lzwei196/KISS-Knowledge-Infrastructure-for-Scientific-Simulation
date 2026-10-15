"""Small artificial station records for SHAW converter regressions."""
import csv
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

KI=Path(os.environ.get('KI_UNDER_TEST',Path(__file__).resolve().parents[1]))
TOOL=KI/'s2_weather_prep/tools/convert_forcing_to_shaw.py'
spec=importlib.util.spec_from_file_location('shaw_weather',TOOL)
tool=importlib.util.module_from_spec(spec);spec.loader.exec_module(tool)


class WeatherTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.path=self.root/'weather.csv'
        self.fields=['date','tmax_c','tmin_c','precip_mm','srad_mj_m2','wind_m_s','rh_pct']
        self.rows=[['2020-01-01',20,10,0,15,2,60],['2020-01-02',21,11,8,16,3,65],['2020-01-03',22,12,12,17,4,70]]

    def write(self,rows=None,fields=None):
        with self.path.open('w',newline='') as f:
            w=csv.writer(f);w.writerow(fields or self.fields);w.writerows(self.rows if rows is None else rows)

    def test_complete_values_units_and_native_columns(self):
        self.write();records=tool.read_daily_csv(self.path)
        self.assertEqual([r['precip'] for r in records],[0.,8.,12.])
        self.assertAlmostEqual(records[0]['swdown'],15.*1e6/86400.)
        out=self.root/'test.wea';tool.write_daily_weather(records,out)
        rows=[line.split() for line in out.read_text().splitlines()]
        self.assertEqual(len(rows),3);self.assertTrue(all(len(r)==8 for r in rows))
        self.assertEqual(rows[0][:2],['1','20'])

    def test_required_field_missing_nonnumeric_or_nonfinite(self):
        for col in range(1,7):
            for value in ('','invalid','nan','inf'):
                rows=[r.copy() for r in self.rows];rows[1][col]=value;self.write(rows)
                with self.subTest(column=self.fields[col],value=value), self.assertRaisesRegex(tool.ForcingError,self.fields[col]):
                    tool.read_daily_csv(self.path)

    def test_missing_date_gap_duplicate_and_invalid_date(self):
        for rows in ([self.rows[0],self.rows[2]],self.rows+[self.rows[1]],self.rows[::-1],
                     [['bad']+self.rows[0][1:]]+self.rows[1:], [['']+self.rows[0][1:]]+self.rows[1:]):
            self.write(rows)
            with self.assertRaisesRegex(tool.ForcingError,'date|calendar'):
                tool.read_daily_csv(self.path)

    def test_requested_year_boundaries_are_required(self):
        self.write()
        with self.assertRaisesRegex(tool.ForcingError,'coverage|year|calendar'):
            tool.read_daily_csv(self.path,2020,2020)

    def test_negative_precip_wind_radiation_bad_humidity_and_extrema(self):
        for col,value in [(3,-1),(4,-1),(5,-1),(6,0),(6,101),(1,9)]:
            rows=[r.copy() for r in self.rows];rows[0][col]=value;self.write(rows)
            with self.subTest(col=col),self.assertRaises(tool.ForcingError):
                tool.read_daily_csv(self.path)

    def test_solar_units_follow_header_not_magnitude(self):
        fields=self.fields.copy();fields[4]='srad_wm2';self.write(fields=fields)
        self.assertEqual(tool.read_daily_csv(self.path)[0]['swdown'],15.)
        fields[4]='solar';self.write(fields=fields)
        with self.assertRaisesRegex(tool.ForcingError,'unit'):
            tool.read_daily_csv(self.path)
        self.assertEqual(tool.read_daily_csv(self.path,solar_units='wm2')[0]['swdown'],15.)

    def test_cli_failure_leaves_existing_output_untouched(self):
        self.write();out=self.root/'test.wea'
        cmd=[sys.executable,'-B',str(TOOL),'--csv',str(self.path),'--output',str(out)]
        good=subprocess.run(cmd,capture_output=True,text=True)
        self.assertEqual(good.returncode,0,good.stderr);before=out.read_bytes()
        self.rows[1][3]='';self.write()
        bad=subprocess.run(cmd,capture_output=True,text=True)
        self.assertNotEqual(bad.returncode,0)
        self.assertIn('2020-01-02',bad.stderr)
        self.assertEqual(out.read_bytes(),before)

    def test_setup_calendar_field_positions_match_fortran(self):
        spec=importlib.util.spec_from_file_location('shaw_setup',KI/'tools/s1_site_setup/setup_shaw_from_template.py')
        setup=importlib.util.module_from_spec(spec);spec.loader.exec_module(setup)
        sit=self.root/'case.sit'
        sit.write_text('test fixture\n2 0 15 364 19\n45 16 0 0 12 80\n')
        setup.update_sit_file(sit,start_doy=3,end_doy=5,year=16)
        # Shaw303.for: READ (11,*) JSTART,HRSTAR,YRSTAR,JEND,YREND
        self.assertEqual(sit.read_text().splitlines()[1].split(),['3','0','16','5','16'])


if __name__=='__main__':unittest.main(verbosity=2)
