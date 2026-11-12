"""hyd.out parser: strict 'it Qobs Qsim' rows, no skipped or guessed lines."""
import importlib.util,os,subprocess,sys,tempfile,unittest
from pathlib import Path
import numpy as np
KI=Path(os.environ.get('KI_UNDER_TEST',Path(__file__).resolve().parents[1]))
TOOL=KI/'tools/parse_topmodel_output.py'
spec=importlib.util.spec_from_file_location('parse',TOOL);p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)
class ParseTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.hyd=Path(self.tmp.name)/'hyd.out'
    def test_valid_file_column_order(self):
        self.hyd.write_text('1 0.000100 0.000200\n2 0.000000 0.000300\n')
        ts,qs,qo=p.parse_hyd_out(str(self.hyd))
        self.assertEqual(ts.tolist(),[1,2]);np.testing.assert_allclose(qo,[1e-4,0.]);np.testing.assert_allclose(qs,[2e-4,3e-4])
    def test_broken_files_raise(self):
        for name,text in {'two fields':'1 0.1 0.2\n0.1 0.2\n','four fields':'1 0.1 0.2 0.3\n',
                          'cut-off last row':'1 0.1 0.2\n2 0.1','cut-off to 2 fields':'1 0.1 0.2\n2 0.1\n',
                          'non-numeric':'1 0.1 abc\n','float step':'1.0 0.1 0.2\n','blank line':'1 0.1 0.2\n\n2 0.1 0.2\n',
                          'no trailing newline':'1 0.1 0.2','empty':'',
                          'underscore step':'1_0 0.1 0.2\n','signed step':'+1 0.1 0.2\n',
                          'underscore float':'1 1_0.5 0.2\n','hex float':'1 0x1p-3 0.2\n',
                          'step not starting at 1':'2 0.1 0.2\n3 0.1 0.2\n','repeated step':'1 0.1 0.2\n1 0.1 0.2\n',
                          'skipped step':'1 0.1 0.2\n3 0.1 0.2\n'}.items():
            with self.subTest(name=name):
                self.hyd.write_text(text)
                with self.assertRaises(ValueError):p.parse_hyd_out(str(self.hyd))
    def test_wellformed_nan_is_returned_for_the_caller_to_reject(self):
        self.hyd.write_text('1 0.1 nan\n2 0.1 -nan\n3 1e-05 inf\n');ts,qs,qo=p.parse_hyd_out(str(self.hyd))
        self.assertTrue(np.isnan(qs[:2]).all());self.assertTrue(np.isinf(qs[2]));self.assertEqual(qo[2],1e-5)
    def cli(self,*extra):
        return subprocess.run([sys.executable,str(TOOL),'--hyd-file',str(self.hyd),'--output-csv',str(self.hyd.with_suffix('.csv')),*extra],
                              capture_output=True,text=True)
    def test_cli_refuses_nonfinite_and_empty_scores(self):
        for name,(text,extra,msg) in {
                'nan Qsim':('1 1.0 1.0\n2 2.0 nan\n3 3.0 3.0\n',(),'nonfinite Qsim'),
                'inf Qsim on a placeholder row':('1 1.0 1.0\n2 -9999.000000 inf\n3 3.0 3.0\n',(),'nonfinite Qsim'),
                'nan Qsim inside spin-up':('1 1.0 nan\n2 2.0 2.0\n3 3.0 3.0\n',('--spinup-steps','1'),'nonfinite Qsim'),
                'nan Qobs':('1 nan 1.0\n2 2.0 2.0\n3 3.0 3.0\n',(),'nonfinite Qobs'),
                'only placeholder rows':('1 -9999.000000 1.0\n2 -9999.000000 2.0\n',(),'no observed row'),
                'placeholder after spin-up':('1 1.0 1.0\n2 -9999.000000 2.0\n',('--spinup-steps','1'),'no observed row'),
                'spin-up eats every row':('1 1.0 1.0\n2 2.0 2.0\n',('--spinup-steps','2'),'leaves no row')}.items():
            with self.subTest(name=name):
                self.hyd.write_text(text);r=self.cli(*extra)
                self.assertEqual(r.returncode,2,r.stdout);self.assertIn('ERROR:',r.stderr);self.assertIn(msg,r.stderr)
                self.assertFalse(self.hyd.with_suffix('.csv').exists())
    def test_cli_exits_2_on_broken_file(self):
        self.hyd.write_text('1 0.1 0.2\n2 0.1\n');r=self.cli()
        self.assertEqual(r.returncode,2);self.assertIn('ERROR:',r.stderr);self.assertFalse(self.hyd.with_suffix('.csv').exists())
    def test_cli_does_not_score_placeholder_rows(self):
        self.hyd.write_text('1 1.000000 1.000000\n2 -9999.000000 5.000000\n3 3.000000 3.000000\n');r=self.cli()
        self.assertEqual(r.returncode,0,r.stderr);self.assertIn('NSE  = 1.0000',r.stdout);self.assertIn('1 rows hold',r.stdout)
        rows=self.hyd.with_suffix('.csv').read_text().splitlines()
        self.assertEqual(rows[2].split(',')[-1],'')
        self.hyd.write_text('1 1.000000 1.000000\n2 -5.000000 5.000000\n');self.assertEqual(self.cli().returncode,2)
class StepLengthTests(unittest.TestCase):
    """Step length comes from the converter's sidecar; no silent 1-hour default."""
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);d=Path(self.tmp.name)
        (d/'data').mkdir();self.hyd=d/'hyd.out';self.inp=d/'data'/'inputs.dat'
        self.hyd.write_text('1 0.001000 0.001000\n2 0.002000 0.002000\n')
        self.inp.write_text('2  1.0\n   0.001  0.0001  0.001\n   0.002  0.0001  0.002\n')
    def side(self,**kw):
        import hashlib,json
        info=dict(start_date='1980-01-01',physical_dt_hours=24.0,steps=2,
                  output_sha256=hashlib.sha256(self.inp.read_bytes()).hexdigest());info.update(kw)
        Path(str(self.inp)+'.provenance.json').write_text(json.dumps(info))
    def cli(self,*extra):
        out=self.hyd.with_suffix('.csv')
        r=subprocess.run([sys.executable,str(TOOL),'--hyd-file',str(self.hyd),'--output-csv',str(out),*extra],
                         capture_output=True,text=True)
        return r,out
    def test_daily_sidecar_sets_m3s(self):
        self.side();r,out=self.cli('--basin-area-km2','86.4')
        self.assertEqual(r.returncode,0,r.stderr);self.assertIn('Step length: 24 h',r.stdout)
        # 0.001 m/day over 86.4 km2 = 86400 m3/day = 1 m3/s (1-hour default would give 24)
        self.assertEqual(out.read_text().splitlines()[1].split(',')[-1],'1.0000')
    def test_explicit_dt_must_agree_with_sidecar(self):
        self.side();r,_=self.cli('--basin-area-km2','86.4','--dt-hours','1')
        self.assertEqual(r.returncode,2);self.assertIn('disagrees',r.stderr)
        r,_=self.cli('--basin-area-km2','86.4','--dt-hours','24');self.assertEqual(r.returncode,0,r.stderr)
    def test_start_date_must_agree_with_sidecar(self):
        self.side();r,_=self.cli('--start-date','1981-01-01');self.assertEqual(r.returncode,2);self.assertIn('disagrees',r.stderr)
        r,out=self.cli('--start-date','1980-01-01');self.assertEqual(r.returncode,0,r.stderr)
        self.assertIn('1980-01-02 00:00',out.read_text().splitlines()[2])
    def test_stale_sidecar_refused(self):
        self.side(output_sha256='0'*64);r,_=self.cli('--basin-area-km2','86.4')
        self.assertEqual(r.returncode,2);self.assertIn('does not match',r.stderr)
    def test_no_sidecar_needs_dt_for_m3s_or_dates(self):
        for extra in (('--basin-area-km2','86.4'),('--start-date','1980-01-01')):
            with self.subTest(extra=extra):
                r,_=self.cli(*extra);self.assertEqual(r.returncode,2);self.assertIn('--dt-hours',r.stderr)
        r,out=self.cli('--basin-area-km2','86.4','--dt-hours','24');self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(out.read_text().splitlines()[1].split(',')[-1],'1.0000')
        r,_=self.cli();self.assertEqual(r.returncode,0,r.stderr)   # metrics only: step length not needed
    def test_bad_dt_refused(self):
        for v in ('0','inf','nan','-24'):
            with self.subTest(v=v):r,_=self.cli('--dt-hours',v);self.assertEqual(r.returncode,2)
    def test_unchecked_sidecar_refused(self):
        self.side(output_sha256=None);r,_=self.cli();self.assertEqual(r.returncode,2);self.assertIn('cannot check',r.stderr)
        self.side();self.inp.unlink();r,_=self.cli();self.assertEqual(r.returncode,2);self.assertIn('cannot check',r.stderr)
    def test_broken_sidecar_names_file(self):
        Path(str(self.inp)+'.provenance.json').write_text('{not json');r,_=self.cli()
        self.assertEqual(r.returncode,2);self.assertIn('provenance.json',r.stderr)
    def test_row_count_must_match_sidecar(self):
        self.side(steps=5);r,_=self.cli();self.assertEqual(r.returncode,2);self.assertIn('steps=5',r.stderr)
        self.side(steps=2);r,_=self.cli();self.assertEqual(r.returncode,0,r.stderr)
    def test_bad_sidecar_values_refused(self):
        for kw in ({'steps':None},{'steps':2.0},{'steps':True},{'physical_dt_hours':True}):
            with self.subTest(kw=kw):
                self.side(**kw);r,_=self.cli();self.assertEqual(r.returncode,2,r.stdout)
    def test_same_day_written_differently_agrees(self):
        self.side();r,_=self.cli('--start-date','1980-1-1');self.assertEqual(r.returncode,0,r.stderr)
    def test_sidecar_without_start_date(self):
        self.side(start_date=None);r,out=self.cli('--start-date','1990-05-01');self.assertEqual(r.returncode,0,r.stderr)
        self.assertIn('1990-05-02 00:00',out.read_text().splitlines()[2])
    def test_relative_paths_and_inputs_file(self):
        self.side();d=self.hyd.parent
        r=subprocess.run([sys.executable,str(TOOL),'--hyd-file','hyd.out','--output-csv','rel.csv','--basin-area-km2','86.4'],
                         capture_output=True,text=True,cwd=str(d))
        self.assertEqual(r.returncode,0,r.stderr);self.assertEqual((d/'rel.csv').read_text().splitlines()[1].split(',')[-1],'1.0000')
        other=d/'other';other.mkdir();(other/'inputs.dat').write_bytes(self.inp.read_bytes())
        import json;info=json.loads(Path(str(self.inp)+'.provenance.json').read_text());info['physical_dt_hours']=1.0
        Path(str(other/'inputs.dat')+'.provenance.json').write_text(json.dumps(info))
        r,out=self.cli('--basin-area-km2','86.4','--inputs-file',str(other/'inputs.dat'))
        self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(out.read_text().splitlines()[1].split(',')[-1],'24.0000')
    def test_spinup_dates_follow_the_model_step(self):
        self.side();r,out=self.cli('--start-date','1980-01-01','--spinup-steps','1')
        self.assertEqual(r.returncode,0,r.stderr);self.assertIn('1980-01-02 00:00',out.read_text().splitlines()[1])
if __name__=='__main__':unittest.main()
