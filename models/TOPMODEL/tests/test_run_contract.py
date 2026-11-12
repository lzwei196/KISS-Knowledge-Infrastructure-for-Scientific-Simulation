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
class ParamsDefaultTests(unittest.TestCase):
    def test_hourly_defaults_need_explicit_hourly_step(self):
        with tempfile.TemporaryDirectory() as d:
            p=os.path.join(d,'params.dat')
            for kw in ({},{'step_hours':24}):
                with self.subTest(kw=kw),self.assertRaises(ValueError):r.write_params_dat(p,**kw)
            self.assertFalse(os.path.exists(p))
            with redirect_stdout(io.StringIO()):r.write_params_dat(p,step_hours=1)
            self.assertIn('3600.0',Path(p).read_text())
            with redirect_stdout(io.StringIO()):r.write_params_dat(p,dict(szm=1,t0=2,td=3,chv=4,rv=5,srmax=6,Q0=7,sr0=8,infex=0,xk0=9,hf=10,dth=11))
if __name__=='__main__':unittest.main()
