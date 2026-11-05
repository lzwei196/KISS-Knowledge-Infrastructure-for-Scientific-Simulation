"""Calibration driver: which Qobs rows count as observed, and failed trials."""
import hashlib,importlib.util,json,os,subprocess,sys,tempfile,unittest
from datetime import datetime,timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
KI=Path(os.environ.get('KI_UNDER_TEST',Path(__file__).resolve().parents[1]))
TOOL=KI/'tools/calibrate_topmodel.py'
spec=importlib.util.spec_from_file_location('calib',TOOL);c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)
class CalibrateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.run=Path(self.tmp.name)
        (self.run/'data').mkdir();self.inp=self.run/'data/inputs.dat'
        self.inp.write_text('3  1.0\n 0.001 0.001 0.001\n 0.001 0.001 0.0\n 0.001 0.001 0.003\n')
    def sidecar(self,**kw):
        info=dict(start_date='2000-01-01',steps=3,physical_dt_hours=24.0,observation_mode='provided_complete',
                  output_sha256=hashlib.sha256(self.inp.read_bytes()).hexdigest());info.update(kw)
        Path(str(self.inp)+'.provenance.json').write_text(json.dumps(info))
    def test_legacy_inputs_without_provenance_or_mask_are_refused(self):
        with self.assertRaises(SystemExit):c.observation_mask(str(self.run),3)
    def test_bad_sidecars_are_refused(self):
        for kw in [dict(output_sha256='0'*64),dict(observation_mode='not_supplied_placeholder_not_for_scoring'),dict(physical_dt_hours=1.0),dict(steps=4)]:
            with self.subTest(kw=kw):
                self.sidecar(**kw)
                with self.assertRaises(SystemExit):c.observation_mask(str(self.run),3)
        self.sidecar()
        with self.assertRaises(SystemExit):c.observation_mask(str(self.run),3,start='1999-12-31')
    def test_verified_sidecar_keeps_true_zero(self):
        self.sidecar();mask,_=c.observation_mask(str(self.run),3,start='2000-01-01')
        self.assertTrue(mask.all())
    def test_mask_does_not_bypass_sidecar_checks(self):
        f=self.run/'mask.txt';f.write_text('1\n0\n1\n')
        for kw,start in [(dict(physical_dt_hours=1.0),'2000-01-01'),(dict(),'1999-12-31'),(dict(output_sha256='0'*64),'2000-01-01'),
                         (dict(observation_mode='not_supplied_placeholder_not_for_scoring'),'2000-01-01')]:
            with self.subTest(kw=kw,start=start):
                self.sidecar(**kw)
                with self.assertRaises(SystemExit):c.observation_mask(str(self.run),3,str(f),start=start)
        self.sidecar();mask,src=c.observation_mask(str(self.run),3,str(f),start='2000-01-01')
        self.assertEqual(mask.tolist(),[True,False,True]);self.assertIn('provenance',src)
    def test_skipped_or_truncated_output_rows_are_rejected(self):
        dates=[datetime(2000,1,1)+timedelta(days=i) for i in range(4)]
        for ts,qs,qo in [([2,3,4],[2.,3.,4.],[0.,3.,4.]),([1,2],[1.,2.],[1.,2.]),([1,2,2,4],[1.,2.,3.,4.],[1.,0.,3.,4.])]:
            with self.subTest(ts=ts),patch.object(c.subprocess,'run',return_value=SimpleNamespace(returncode=0)),patch.object(c,'write_params_dat'),\
                 patch.object(c,'parse_hyd_out',return_value=(np.array(ts),np.array(qs),np.array(qo))):
                self.assertIsNone(c.score(str(self.run),{},dates,'B',('2000-01-01','2000-01-04'),('2000-01-01','2000-01-04'),np.array([True,False,True,True])))
    def test_mask_file_excludes_legacy_zero(self):
        f=self.run/'mask.txt';f.write_text('1\n0\n1\n')
        mask,_=c.observation_mask(str(self.run),3,str(f));self.assertEqual(mask.tolist(),[True,False,True])
        for bad in ['1\n0\n','1\n2\n1\n','0\n0\n0\n']:
            f.write_text(bad)
            with self.subTest(bad=bad),self.assertRaises(SystemExit):c.observation_mask(str(self.run),3,str(f))
    def score(self,qs,qo,mask):
        dates=[datetime(2000,1,1)+timedelta(days=i) for i in range(len(qs))]
        with patch.object(c.subprocess,'run',return_value=SimpleNamespace(returncode=0)),patch.object(c,'write_params_dat'),\
             patch.object(c,'parse_hyd_out',return_value=(np.arange(1,len(qs)+1),qs,qo)):
            return c.score(str(self.run),{},dates,'B',('2000-01-01','2000-01-03'),('2000-01-01','2000-01-03'),np.array(mask))
    def test_nonfinite_simulation_is_rejected_not_scored(self):
        self.assertIsNone(self.score([1.,np.nan,3.],[1.,2.,3.],[True]*3))
        self.assertEqual(self.score([1.,2.,3.],[1.,2.,3.],[True]*3)['calibration']['NSE'],1.0)
    def test_masked_zero_not_scored_but_observed_zero_is(self):
        m1=self.score([1.,2.,3.],[1.,0.,3.],[True,False,True])['calibration']
        self.assertEqual((m1['n'],m1['NSE']),(2,1.0))
        m2=self.score([1.,2.,3.],[1.,0.,3.],[True,True,True])['calibration']
        self.assertEqual(m2['n'],3);self.assertLess(m2['NSE'],1.0)
        with self.assertRaises(SystemExit):self.score([1.,2.,3.],[1.,-99.9,3.],[True]*3)
    def gaps(self,rows=(2,),**kw):
        self.inp.write_text('3  1.0\n 0.001 0.001 0.001\n 0.001 0.001 -9999\n 0.001 0.001 0.0\n')
        self.sidecar(**dict(dict(observation_mode='provided_with_gaps',obs_placeholder_value=-9999.0,obs_missing_count_days=len(rows),
                                 obs_missing_rows=list(rows)),**kw))
    def test_gap_sidecar_masks_listed_rows_and_keeps_true_zero(self):
        self.gaps();mask,src=c.observation_mask(str(self.run),3,start='2000-01-01')
        self.assertEqual(mask.tolist(),[True,False,True]);self.assertIn('provided_with_gaps',src)
    def test_bad_gap_sidecars_are_refused(self):
        for rows,kw in [((3,),{}),((2,2),{}),((0,),{}),((4,),{}),((),{}),((2,),dict(obs_missing_count_days=2)),
                        ((2,),dict(obs_placeholder_value=0.0)),((2,),dict(obs_placeholder_value=-99.9))]:
            with self.subTest(rows=rows,kw=kw):
                self.gaps(rows,**kw)
                with self.assertRaises(SystemExit):c.observation_mask(str(self.run),3,start='2000-01-01')
        # an unlisted negative value in a verified file is refused, gaps or not
        self.inp.write_text('3  1.0\n 0.001 0.001 -9999\n 0.001 0.001 -9999\n 0.001 0.001 0.0\n')
        self.sidecar(observation_mode='provided_with_gaps',obs_placeholder_value=-9999.0,obs_missing_count_days=1,obs_missing_rows=[2])
        with self.assertRaises(SystemExit):c.observation_mask(str(self.run),3,start='2000-01-01')
        self.inp.write_text('3  1.0\n 0.001 0.001 0.001\n 0.001 0.001 -9999\n 0.001 0.001 0.0\n');self.sidecar()
        with self.assertRaises(SystemExit):c.observation_mask(str(self.run),3,start='2000-01-01')
    def test_mask_may_only_drop_rows(self):
        self.gaps();f=self.run/'mask.txt'
        f.write_text('1\n1\n1\n')
        with self.assertRaises(SystemExit):c.observation_mask(str(self.run),3,str(f),start='2000-01-01')
        f.write_text('1\n0\n0\n');mask,_=c.observation_mask(str(self.run),3,str(f),start='2000-01-01')
        self.assertEqual(mask.tolist(),[True,False,False])
    def test_unreadable_hyd_out_is_a_rejected_trial_with_reason(self):
        dates=[datetime(2000,1,1)+timedelta(days=i) for i in range(2)]
        for text in ['1 0.1 0.2\n2 0.1\n','1 0.1 0.2\n2 0.1 0.2','1 0.1 0.2\n2 x 0.2\n']:
            (self.run/'hyd.out').write_text(text)
            with self.subTest(text=text),patch.object(c.subprocess,'run',return_value=SimpleNamespace(returncode=0)),patch.object(c,'write_params_dat'):
                self.assertIsNone(c.score(str(self.run),{},dates,'B',('2000-01-01','2000-01-02'),('2000-01-01','2000-01-02'),np.array([True,True])))
                self.assertIn('hyd.out not readable',c.LAST_REJECT['reason'])
    def test_cli_help_has_no_unshipped_import(self):
        p=subprocess.run([sys.executable,str(TOOL),'--help'],capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertNotIn('from standard_calval',TOOL.read_text())
if __name__=='__main__':unittest.main()
