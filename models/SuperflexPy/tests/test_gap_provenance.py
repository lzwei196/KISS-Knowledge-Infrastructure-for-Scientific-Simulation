"""Artificial Caravan and text fixtures; no synthetic observations used for scoring."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
import numpy as np
import pandas as pd
import xarray as xr

KI=Path(os.environ.get('KI_UNDER_TEST',Path(__file__).resolve().parents[1]))
spec=importlib.util.spec_from_file_location('sfp_forcing',KI/'tools/convert_forcing.py')
tool=importlib.util.module_from_spec(spec);spec.loader.exec_module(tool)


class GapTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.nc=self.root/'fixture.nc'
        self.args=SimpleNamespace(input=str(self.nc),start=None,end=None,pet_sign='asis',pet_min=None,
                                  fill_forcing_gaps=False,timestep=1.,area=None)

    def ncfile(self,p,pet=None,dates=None):
        ds=xr.Dataset({'total_precipitation_sum':('date',p),
                       'potential_evaporation_sum':('date',pet if pet is not None else np.ones(len(p)))},
                      coords={'date':dates if dates is not None else pd.date_range('2020-01-01',periods=len(p))})
        last=None
        for engine in os.environ.get('SFP_TEST_NC_ENGINES','netcdf4,h5netcdf,scipy').split(','):
            try:
                ds.to_netcdf(self.nc,engine=engine);return
            except Exception as exc:  # engine missing or broken here: try the next
                last=exc
        raise unittest.SkipTest(f'no working netCDF writer: {last}')

    def test_default_rejects_missing(self):
        self.ncfile([8.,np.nan,12.])
        self.assertEqual(tool.process_caravan(self.args)['status'],'error')

    def test_optin_preserves_values_and_records_every_fill(self):
        self.ncfile([8.,np.nan,12.],[1.,np.nan,3.]);self.args.fill_forcing_gaps=True
        r=tool.process_caravan(self.args)
        self.assertEqual(r['status'],'success');self.assertEqual(r['P'],[8.,10.,12.]);self.assertEqual(r['PET'],[1.,2.,3.])
        g=r['gap_filling'];self.assertEqual(g['counts'],{'P':1,'PET':1})
        self.assertEqual(g['masks']['P'],[False,True,False])
        self.assertEqual(len(g['records']),2)
        for event in g['records']:
            self.assertEqual(event['date'],'2020-01-02');self.assertEqual(event['original'],'NaN')
            self.assertEqual(event['left']['date'],'2020-01-01');self.assertEqual(event['right']['date'],'2020-01-03')
        self.assertEqual(r['statistics']['gap_filled_counts'],g['counts'])

    def test_edge_or_all_missing_not_extrapolated(self):
        self.args.fill_forcing_gaps=True
        for p in ([np.nan,1.,2.],[1.,2.,np.nan],[np.nan,np.nan,np.nan]):
            self.ncfile(p)
            with self.subTest(p=p):self.assertEqual(tool.process_caravan(self.args)['status'],'error')

    def test_negative_infinity_not_hidden_by_pet_floor(self):
        self.ncfile([1.,2.,3.],[1.,-np.inf,3.]);self.args.pet_min=0.
        self.assertEqual(tool.process_caravan(self.args)['status'],'error')
        self.args.fill_forcing_gaps=True
        result=tool.process_caravan(self.args)
        self.assertEqual(result['PET'],[1.,2.,3.])
        self.assertEqual(result['gap_filling']['records'][0]['original'],'-Inf')

    def test_sign_flip_keeps_true_source_value(self):
        self.ncfile([1.,2.,3.],[-1.,-np.inf,-3.]);self.args.pet_sign='flip';self.args.fill_forcing_gaps=True
        r=tool.process_caravan(self.args)
        self.assertEqual(r['status'],'success',r);self.assertEqual(r['PET'],[1.,2.,3.])
        rec=r['gap_filling']['records'][0]
        self.assertEqual(rec['original'],'-Inf');self.assertEqual(rec['after_transforms'],'+Inf')
        self.assertEqual(rec['left']['source_value'],-1.);self.assertEqual(rec['left']['value'],1.)
        self.assertIn('negated',r['conversions_applied']['PET_sign'])
        self.assertIn('negated',r['gap_filling']['transforms_before_interpolation']['PET_sign'])

    def test_flip_on_positive_pet_stops(self):
        self.ncfile([1.,2.,3.],[1.,2.,3.]);self.args.pet_sign='flip'
        self.assertEqual(tool.process_caravan(self.args)['status'],'error')

    def _text(self,text,*extra):
        path=self.root/'forcing.csv';out=self.root/'forcing.json'
        path.write_text(text)
        if out.exists():out.unlink()
        cmd=[sys.executable,'-B',str(KI/'tools/convert_forcing.py'),'--input',str(path),'--output',str(out),
             '--header-lines','0','--p-col','3','--pet-col','4','--q-col','5',*extra]
        run=subprocess.run(cmd,capture_output=True,text=True)
        return run,(json.loads(out.read_text()) if out.exists() else None)

    def test_text_volume_q_without_area_stops(self):
        rows='2020,1,1,1,1,10\n2020,1,2,2,1,20\n'
        for unit in ('m3/s','cms','l/s','bogus'):
            with self.subTest(unit=unit):
                run,res=self._text(rows,'--q-unit',unit)
                self.assertNotEqual(run.returncode,0);self.assertIsNone(res)
        run,res=self._text(rows,'--q-unit','m3/s','--area','86.4')
        self.assertEqual(run.returncode,0,run.stderr)
        self.assertAlmostEqual(res['Q_obs'][0],10.);self.assertIn('area',res['conversions_applied']['Q_obs'])

    def test_text_pet_floor_and_flip_applied(self):
        run,res=self._text('2020,1,1,1,-0.5,1\n2020,1,2,2,2,1\n','--pet-min','0')
        self.assertEqual(run.returncode,0,run.stderr);self.assertEqual(res['PET'],[0.,2.])
        self.assertIn('1 finite values clipped',res['conversions_applied']['PET_floor'])
        run,res=self._text('2020,1,1,1,-1,1\n2020,1,2,2,-2,1\n','--pet-sign','flip')
        self.assertEqual(run.returncode,0,run.stderr);self.assertEqual(res['PET'],[1.,2.])
        run,res=self._text('2020,1,1,1,-1,1\n2020,1,2,2,-2,1\n')
        self.assertNotEqual(run.returncode,0)

    def test_text_all_zero_pet_accepted_and_flip_refused(self):
        rows='2020,1,1,1,0,1\n2020,1,2,2,0,1\n'
        run,res=self._text(rows)
        self.assertEqual(run.returncode,0,run.stderr);self.assertEqual(res['PET'],[0.,0.])
        self.assertTrue(res['gap_filling']['transforms_before_interpolation']['PET_all_zero'])
        self.assertEqual(res['conversions_applied']['PET_sign'],'as in source')
        run,res=self._text(rows,'--pet-sign','flip')
        self.assertNotEqual(run.returncode,0);self.assertIsNone(res)

    def test_text_single_row(self):
        run,res=self._text('2020,1,1,3,2,1\n')
        self.assertEqual(run.returncode,0,run.stderr)
        self.assertEqual(res['P'],[3.]);self.assertEqual(res['PET'],[2.]);self.assertEqual(res['dates'],['2020-01-01'])
        path=self.root/'one.csv';path.write_text('1\n2\n')
        bad=subprocess.run([sys.executable,'-B',str(KI/'tools/convert_forcing.py'),'--input',str(path),
                            '--header-lines','0','--p-col','0','--pet-col','0'],capture_output=True,text=True)
        self.assertNotEqual(bad.returncode,0);self.assertIn('only one column',bad.stderr)

    def test_caravan_all_zero_pet_flip_refused(self):
        self.ncfile([1.,2.,3.],[0.,0.,0.]);self.args.pet_sign='flip'
        self.assertEqual(tool.process_caravan(self.args)['status'],'error')

    def test_subdaily_total_is_depth(self):
        rows=''.join(f'2020,1,1,1,0.1,1\n' for _ in range(24))
        run,res=self._text(rows,'--p-unit','mm/h','--pet-unit','mm/h','--timestep',str(1/24))
        self.assertEqual(run.returncode,0,run.stderr)
        self.assertEqual(res['P'][0],24.);self.assertAlmostEqual(res['statistics']['P_total'],24.)
        self.assertEqual(res['statistics']['P_total_unit'],'mm')

    def test_daily_axis_and_requested_coverage_required(self):
        self.ncfile([1.,2.,3.],dates=pd.to_datetime(['2020-01-01','2020-01-03','2020-01-04']))
        self.assertEqual(tool.process_caravan(self.args)['status'],'error')
        self.ncfile([1.,2.,3.]);self.args.start='2019-12-31'
        self.assertEqual(tool.process_caravan(self.args)['status'],'error')

    def test_genuine_zero_pet_and_rain_accepted(self):
        # zero rain and zero-PET days are real; PET positive on some day
        self.ncfile([0.,0.,0.],[0.,1.,0.])
        r=tool.process_caravan(self.args);self.assertEqual(r['status'],'success')
        self.assertEqual(r['P'],[0.,0.,0.]);self.assertEqual(r['PET'],[0.,1.,0.])

    def test_pet_never_positive_stops(self):
        # PET never > 0 in the window = wrong sign or empty field: stop
        self.ncfile([1.,2.,3.],[0.,0.,0.])
        self.assertEqual(tool.process_caravan(self.args)['status'],'error')

    def test_cli_error_exits_nonzero_preserving_prior_output(self):
        self.ncfile([8.,np.nan,12.]);out=self.root/'forcing.json';out.write_text('prior valid output')
        cmd=[sys.executable,'-B',str(KI/'tools/convert_forcing.py'),'--format','caravan','--input',str(self.nc),'--output',str(out)]
        bad=subprocess.run(cmd,capture_output=True,text=True)
        self.assertNotEqual(bad.returncode,0);self.assertEqual(out.read_text(),'prior valid output')
        good=subprocess.run(cmd+['--fill-forcing-gaps'],capture_output=True,text=True)
        self.assertEqual(good.returncode,0,good.stderr)
        self.assertEqual(json.loads(out.read_text())['gap_filling']['counts']['P'],1)

    def test_text_missing_pet_or_nan_fails(self):
        path=self.root/'forcing.csv';out=self.root/'forcing.json'
        cmd=[sys.executable,'-B',str(KI/'tools/convert_forcing.py'),'--input',str(path),
             '--output',str(out),'--header-lines','0','--p-col','3','--pet-col','4']
        for text in ('2020,1,1,1\n2020,1,2,2\n','2020,1,1,1,1\n2020,1,2,nan,1\n'):
            path.write_text(text)
            bad=subprocess.run(cmd,capture_output=True,text=True)
            self.assertNotEqual(bad.returncode,0);self.assertFalse(out.exists())


if __name__=='__main__':unittest.main(verbosity=2)
