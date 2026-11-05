"""run_topmodel.validate_outputs: hyd.out columns are `it Qobs Qsim`."""
import importlib.util,io,os,tempfile,unittest
from contextlib import redirect_stdout
from pathlib import Path
KI=Path(os.environ.get('KI_UNDER_TEST',Path(__file__).resolve().parents[1]))
spec=importlib.util.spec_from_file_location('run_topmodel',KI/'tools/run_topmodel.py');r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)
class RunOutputTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.d=Path(self.tmp.name)
        (self.d/'topmod.out').write_text('x\n')
    def check(self,text):
        (self.d/'hyd.out').write_text(text);buf=io.StringIO()
        with redirect_stdout(buf):errors=r.validate_outputs(str(self.d))
        return errors,buf.getvalue()
    def test_reads_qsim_from_column_3(self):
        errors,out=self.check('1 -9999.000000 0.000058\n')     # missing day 1: col 2 is the placeholder
        self.assertEqual(errors,[]);self.assertIn('first Q_sim=5.800000e-05',out)
        errors,out=self.check('1 0.000100 5.000000\n')          # Qsim too high is caught, Qobs is not read as Qsim
        self.assertTrue(any('Q_sim=5.0' in e for e in errors))
        errors,out=self.check('1 5.000000 0.000100\n')
        self.assertEqual(errors,[])
    def test_short_first_line_is_an_error(self):
        errors,out=self.check('1 0.000100\n');self.assertTrue(any('expected 3' in e for e in errors))
if __name__=='__main__':unittest.main()
