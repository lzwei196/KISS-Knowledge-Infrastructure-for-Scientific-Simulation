"""Generated FLUXNET-shaped fixtures test conversion, not observed weather."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd

KI = Path(os.environ.get('KI_UNDER_TEST', Path(__file__).resolve().parents[1]))
spec = importlib.util.spec_from_file_location('bgc_forcing', KI/'tools/convert_forcing_to_bgc.py')
tool = importlib.util.module_from_spec(spec); spec.loader.exec_module(tool)


class FluxnetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        dates = pd.date_range('2020-01-01','2020-12-31')
        self.dd = pd.DataFrame(dict(TIMESTAMP=dates.strftime('%Y%m%d'),
            TA_F_MDS_DAY=20., TA_F_MDS_NIGHT=10., P_F=1., VPD_F=10., SW_IN_F=150.))
        self.path = self.root/'FULLSET_DD.csv'

    def read(self, df=None):
        (self.dd if df is None else df).to_csv(self.path,index=False)
        return tool.read_fluxnet_forcing(str(self.path),2020,2020,use_hh=False)

    def hh(self):
        dates = pd.date_range('2020-01-01','2020-12-31 23:30',freq='30min')
        day = (dates.hour>=6)&(dates.hour<18)
        return pd.DataFrame(dict(TIMESTAMP_START=dates.strftime('%Y%m%d%H%M'),
            TA_F=np.where(day,20.,10.), P_F=.1, VPD_F=10., SW_IN_F=np.where(day,300.,0.),
            SW_IN_POT=np.where(day,500.,0.)))

    def read_hh(self, df):
        p=self.root/'FULLSET_HH.csv'; df.to_csv(p,index=False)
        return tool.read_fluxnet_forcing(str(p),2020,2020)

    def test_complete_dd_units_calendar_and_zero(self):
        self.dd.loc[0,'P_F']=0.
        records,meta=self.read()
        self.assertEqual(len(records),365)
        self.assertEqual([r['yday'] for r in records],list(range(1,366)))
        self.assertEqual(records[0]['prec_mm'],0.)
        row=tool.convert_to_bgc_met(records,45.)[1].split()
        self.assertEqual(float(row[5]),.1)
        self.assertEqual(float(row[6]),1000.)
        self.assertIn('PROXY',meta['tmax_tmin_basis'])

    def test_dd_gap_at_either_end_middle_duplicate_and_out_of_order(self):
        for df in (self.dd.iloc[1:],self.dd.iloc[:-1],self.dd.drop(index=100),
                   pd.concat([self.dd,self.dd.iloc[:1]]),self.dd.iloc[::-1]):
            with self.subTest(rows=len(df)),self.assertRaisesRegex(ValueError,'calendar|coverage|timestamp'):
                self.read(df)

    def test_dd_missing_values_are_not_copied_or_zeroed(self):
        for col in ('TA_F_MDS_DAY','TA_F_MDS_NIGHT','P_F','VPD_F','SW_IN_F'):
            for value in (-9999.,np.nan,np.inf):
                df=self.dd.copy();df.loc[2,col]=value
                with self.subTest(col=col,value=value),self.assertRaisesRegex(ValueError,col):
                    self.read(df)

    def test_hh_exact_aggregation(self):
        records,meta=self.read_hh(self.hh())
        self.assertEqual(len(records),365)
        self.assertEqual(records[0]['tmax'],20.)
        self.assertEqual(records[0]['tmin'],10.)
        self.assertAlmostEqual(records[0]['prec_mm'],4.8)
        self.assertEqual(records[0]['srad'],150.)
        self.assertEqual(records[0]['vpd_hpa'],10.)

    def test_hh_partial_day_duplicate_and_missing_sample_fail_before_aggregation(self):
        full=self.hh()
        for df in (full.drop(index=1),pd.concat([full,full.iloc[:1]])):
            with self.assertRaisesRegex(ValueError,'calendar|coverage|timestamp'):
                self.read_hh(df)
        for col in ('TA_F','P_F','SW_IN_F','VPD_F','SW_IN_POT'):
            df=full.copy();df.loc[20,col]=-9999.
            with self.subTest(col=col),self.assertRaisesRegex(ValueError,col):
                self.read_hh(df)

    def test_no_implicit_daylight_or_dd_proxy_fallback(self):
        with self.assertRaisesRegex(ValueError,'SW_IN_POT'):
            self.read_hh(self.hh().drop(columns='SW_IN_POT'))
        (self.root/'FULLSET_HH.csv').unlink()
        self.dd.to_csv(self.path,index=False)
        with self.assertRaisesRegex(ValueError,'HH|daily_only'):
            tool.read_fluxnet_forcing(str(self.path),2020,2020)

    def test_direct_source_regression(self):
        days=pd.date_range('2020-01-01','2020-12-31')
        d=dict(dates=days,temp_max_c=np.full(len(days),20.),temp_min_c=np.full(len(days),10.),
               precip_mm=np.ones(len(days)),srad_wm2=np.full(len(days),150.),
               shum_kgkg=np.full(len(days),.008),pres_pa=np.full(len(days),100000.))
        with patch.object(tool,'_load_daily',return_value=d):
            records,_=tool.read_direct_forcing('nasa_power',45.,10.,2020,2020)
            self.assertEqual(len(records),365)
            self.assertEqual(records[-1]['yday'],365)
            d['precip_mm'][2]=np.nan
            with self.assertRaisesRegex(ValueError,'precip_mm'):
                tool.read_direct_forcing('nasa_power',45.,10.,2020,2020)

    def test_cli_valid_then_missing_preserves_output_and_provenance(self):
        self.dd.to_csv(self.path,index=False);out=self.root/'met.txt'
        cmd=[sys.executable,'-B',str(KI/'tools/convert_forcing_to_bgc.py'),'--source','fluxnet',
             '--forcing_file',str(self.path),'--fluxnet_daily_only','--lat','45',
             '--start_year','2020','--end_year','2020','--output',str(out)]
        good=subprocess.run(cmd,capture_output=True,text=True)
        self.assertEqual(good.returncode,0,good.stdout+good.stderr)
        report=json.loads(good.stdout)
        self.assertEqual(report['additional_gap_filling'],'none')
        summary=Path(str(out)+'.summary.json')
        self.assertTrue(summary.is_file())
        before=(out.read_bytes(),summary.read_bytes())
        self.dd.loc[1,'P_F']=-9999.;self.dd.to_csv(self.path,index=False)
        bad=subprocess.run(cmd,capture_output=True,text=True)
        self.assertNotEqual(bad.returncode,0)
        self.assertIn('P_F',bad.stdout)
        self.assertEqual(before,(out.read_bytes(),summary.read_bytes()))


    def _cli(self, out, *extra):
        cmd=[sys.executable,'-B',str(KI/'tools/convert_forcing_to_bgc.py'),'--source','fluxnet',
             '--forcing_file',str(self.path),'--fluxnet_daily_only','--lat','45',
             '--start_year','2020','--end_year','2020','--output',str(out),*extra]
        return subprocess.run(cmd,capture_output=True,text=True)

    def test_cli_rejects_summary_on_met_path(self):
        self.dd.to_csv(self.path,index=False);out=self.root/'met.txt'
        out.write_text('old met\n')
        for extra in (['--summary_json',str(out)],
                      ['--summary_json',str(self.root/'.'/'met.txt')]):
            r=self._cli(out,*extra)
            self.assertEqual(r.returncode,1,r.stdout+r.stderr)
            self.assertIn('same file',r.stdout)
            self.assertEqual(out.read_text(),'old met\n')

    def test_cli_unwritable_summary_keeps_previous_pair(self):
        self.dd.to_csv(self.path,index=False);out=self.root/'met.txt'
        self.assertEqual(self._cli(out).returncode,0)
        summary=Path(str(out)+'.summary.json')
        before=(out.read_bytes(),summary.read_bytes())
        (self.root/'blocker').write_text('x')
        self.dd.loc[:,'P_F']=2.;self.dd.to_csv(self.path,index=False)
        r=self._cli(out,'--summary_json',str(self.root/'blocker'/'s.json'))
        self.assertEqual(r.returncode,3,r.stdout+r.stderr)
        self.assertEqual(before,(out.read_bytes(),summary.read_bytes()))
        self.assertEqual(sorted(p.name for p in self.root.iterdir()),
                         sorted(['FULLSET_DD.csv','blocker','met.txt','met.txt.summary.json']))

    def test_write_pair_restores_old_met_when_summary_replace_fails(self):
        met=self.root/'m.txt';summ=self.root/'m.json'
        met.write_text('old met');summ.write_text('old summary')
        real=os.replace;calls=[]
        def flaky(a,b):
            calls.append(b)
            if Path(b)==summ: raise OSError('injected')
            return real(a,b)
        with patch.object(tool.os,'replace',side_effect=flaky),self.assertRaises(OSError):
            tool._write_pair(met,'new met',summ,'new summary')
        self.assertEqual((met.read_text(),summ.read_text()),('old met','old summary'))
        self.assertEqual(sorted(p.name for p in self.root.iterdir()),['m.json','m.txt'])
        met.unlink();summ.unlink()
        with patch.object(tool.os,'replace',side_effect=flaky),self.assertRaises(OSError):
            tool._write_pair(met,'new met',summ,'new summary')
        self.assertEqual(list(self.root.iterdir()),[])

    def test_cli_rejects_nonfinite_or_out_of_range_lat(self):
        self.dd.to_csv(self.path,index=False);out=self.root/'met.txt'
        for lat in ('nan','inf','-inf','91'):
            cmd=[sys.executable,'-B',str(KI/'tools/convert_forcing_to_bgc.py'),'--source','fluxnet',
                 '--forcing_file',str(self.path),'--fluxnet_daily_only','--lat='+lat,
                 '--start_year','2020','--end_year','2020','--output',str(out)]
            r=subprocess.run(cmd,capture_output=True,text=True)
            with self.subTest(lat=lat):
                self.assertEqual(r.returncode,1,r.stdout+r.stderr)
                self.assertIn('--lat',r.stdout)
                self.assertFalse(out.exists())


    def test_write_pair_failed_rollback_keeps_backup_and_says_so(self):
        met=self.root/'m.txt';summ=self.root/'m.json'
        met.write_text('old met');summ.write_text('old summary')
        real=os.replace
        def flaky(a,b):
            if Path(b)==summ: raise OSError('injected summary')
            if str(a).endswith('.prev'): raise OSError('injected restore')
            return real(a,b)
        with patch.object(tool.os,'replace',side_effect=flaky):
            with self.assertRaises(tool.PairWriteError) as cm:
                tool._write_pair(met,'new met',summ,'new summary')
        msg=str(cm.exception)
        self.assertIn('do NOT match',msg)
        self.assertNotIn('kept',msg)
        prev=[p for p in self.root.iterdir() if p.name.endswith('.prev')]
        self.assertEqual(len(prev),1)
        self.assertIn(str(prev[0]),msg)
        self.assertEqual(prev[0].read_text(),'old met')

    def test_cli_refuses_to_write_over_fluxnet_inputs(self):
        self.dd.to_csv(self.path,index=False);before=self.path.read_bytes()
        hh=self.root/'FULLSET_HH.csv';out=self.root/'met.txt'
        for extra,o in ((['--summary_json',str(self.path)],out),
                        (['--summary_json',str(hh)],out),
                        ([],self.path),([],hh)):
            r=self._cli(o,*extra)
            with self.subTest(extra=extra,out=o):
                self.assertEqual(r.returncode,1,r.stdout+r.stderr)
                self.assertIn('FLUXNET input',r.stdout)
                self.assertEqual(self.path.read_bytes(),before)
                self.assertFalse(hh.exists());self.assertFalse(out.exists())


    def test_cli_refuses_output_inside_forcing_store(self):
        store=self.root/'store';store.mkdir()
        cmd=[sys.executable,'-B',str(KI/'tools/convert_forcing_to_bgc.py'),'--source','cmfd',
             '--forcing_dir',str(store),'--lat','32','--lon','115',
             '--start_year','2020','--end_year','2020','--output',str(store/'met.txt')]
        r=subprocess.run(cmd,capture_output=True,text=True)
        self.assertEqual(r.returncode,1,r.stdout+r.stderr)
        self.assertIn('forcing_dir',r.stdout)
        self.assertEqual(list(store.iterdir()),[])


    def test_kelvin_to_celsius_does_not_recurse(self):
        self.assertEqual(tool.kelvin_to_celsius(273.15),0.0)
        self.assertAlmostEqual(tool.kelvin_to_celsius(300.),26.85)


if __name__=='__main__':unittest.main(verbosity=2)
