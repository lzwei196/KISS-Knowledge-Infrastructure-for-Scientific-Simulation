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
if __name__=='__main__':unittest.main()
