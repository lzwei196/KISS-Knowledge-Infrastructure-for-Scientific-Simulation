"""Artificial weather fixtures for TOPMODEL input validation and units."""
import importlib.util,json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd
KI=Path(os.environ.get('KI_UNDER_TEST',Path(__file__).resolve().parents[1]))
TOOL=KI/'tools/convert_forcing_to_topmodel.py'
spec=importlib.util.spec_from_file_location('forcing',TOOL);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class ForcingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.out=self.root/'inputs.dat'
        self.data=dict(ndays=3,start_date='2000-01-01',prec_mm_day=np.array([0.,12.,24.]),temp_K=np.array([283.15]*3),tmin_C=np.array([5.]*3),tmax_C=np.array([15.]*3))
    def run_convert(self,data=None,dt=24,**kw):
        return m.convert_to_topmodel_inputs(self.data if data is None else data,dt,33.,output_file=str(self.out),**kw)
    def test_missing_extrema_and_nonfinite_forcing_fail_before_write(self):
        for key in ['prec_mm_day','temp_K','tmin_C','tmax_C']:
            for bad in [None,np.array([np.nan]*3),np.array([1.,np.inf,3.])]:
                with self.subTest(key=key,bad=bad):
                    data=dict(self.data);data[key]=bad;self.out.write_text('old valid output\n')
                    with self.assertRaises(ValueError):self.run_convert(data)
                    self.assertEqual(self.out.read_text(),'old valid output\n')
        data=dict(self.data);del data['tmin_C']
        with self.assertRaises(ValueError):self.run_convert(data)
    def test_invalid_range_lengths_and_timestep_fail(self):
        for key,value in [('prec_mm_day',[-1,2,3]),('tmin_C',[20,20,20]),('temp_K',[300,300,300]),('tmax_C',[10,10]),('ndays',2)]:
            with self.subTest(key=key),self.assertRaises(ValueError):self.run_convert(dict(self.data,**{key:value}))
        for dt in [0,-1,np.nan,25,7]:
            with self.subTest(dt=dt),self.assertRaises(ValueError):self.run_convert(dt=dt)
    def test_valid_depth_units_zero_and_provenance(self):
        for dt in [24,1]:
            self.run_convert(dt=dt);table=np.loadtxt(self.out,skiprows=1);steps=int(24/dt)
            self.assertEqual(len(table),3*steps)
            np.testing.assert_allclose(table[:,0].reshape(3,steps).sum(axis=1),[0,.012,.024],atol=1e-12)
            self.assertEqual(self.out.read_text().splitlines()[0],f'{3*steps}  1.0')
            info=json.loads(Path(str(self.out)+'.provenance.json').read_text())
            self.assertEqual(info['fill_count'],0);self.assertEqual(info['physical_dt_hours'],dt)
            self.assertEqual(info['observation_mode'],'not_supplied_placeholder_not_for_scoring')
    def test_equal_extrema_and_polar_radiation_are_valid(self):
        result=m.compute_pet_hargreaves(np.array([10.]),np.array([10.]),np.array([10.]),33.,np.array([180]))
        self.assertEqual(float(result[0]),0.)
        for day in [1,180]:
            result=m.compute_pet_hargreaves(np.array([5.]),np.array([15.]),np.array([10.]),89.,np.array([day]))
            self.assertTrue(np.isfinite(result).all())
    def test_selected_source_calendar_cannot_hide_duplicates(self):
        dates=pd.date_range('2000-01-01 01:30',periods=24,freq='3h')
        for changed in [dates[:8].append(dates[8:16]).append(dates[8:16]),dates+pd.Timedelta(days=1),dates.delete(4),pd.date_range('2000-01-01',periods=3)]:
            raw={'prec':pd.Series(.00001,index=changed),'temp':pd.Series(283.15,index=changed)}
            with self.subTest(dates=changed),patch.object(m,'_read_cmfd_point',return_value=(raw,{'step_seconds':10800.})),self.assertRaises(ValueError):
                m.extract_basin_mean_forcing(str(self.root),None,'2000-01-01','2000-01-03',lat_center=33,lon_center=117)
        raw={'prec':pd.Series(.00001,index=dates),'temp':pd.Series(np.tile([278.15,279.15,281.15,284.15,288.15,287.15,283.15,280.15],3),index=dates)}
        with patch.object(m,'_read_cmfd_point',return_value=(raw,{'step_seconds':10800.})):
            data=m.extract_basin_mean_forcing(str(self.root),None,'2000-01-01','2000-01-03',lat_center=33,lon_center=117)
        np.testing.assert_allclose(data['prec_mm_day'],.864)
        np.testing.assert_allclose(data['tmin_C'],5)
        raw['temp'].iloc[2]=np.nan
        with patch.object(m,'_read_cmfd_point',return_value=(raw,{'step_seconds':10800.})),self.assertRaises(ValueError):
            m.extract_basin_mean_forcing(str(self.root),None,'2000-01-01','2000-01-03',lat_center=33,lon_center=117)
    def test_regular_thinning_against_declared_step_fails(self):
        full=pd.date_range('2000-01-01',periods=24,freq='3h')
        thin=full[::2]
        raw={'prec':pd.Series(.00001,index=thin),'temp':pd.Series(np.tile([278.15,288.15,283.15,280.15],3),index=thin)}
        with patch.object(m,'_read_cmfd_point',return_value=(raw,{'step_seconds':10800.})),self.assertRaises(ValueError):
            m.extract_basin_mean_forcing(str(self.root),None,'2000-01-01','2000-01-03',lat_center=33,lon_center=117)
        with patch.object(m,'_read_cmfd_point',return_value=(raw,{})),self.assertRaises(ValueError):
            m.extract_basin_mean_forcing(str(self.root),None,'2000-01-01','2000-01-03',lat_center=33,lon_center=117)
    def test_declared_step_parsing(self):
        cmfd=dict(title='3-hourly precipitation from the China Meteorological Forcing Dataset',description='Data from China Meteorological Forcing Dataset (Version: 02.00.0000; Category: B-01: 03hr, 0.10deg)')
        self.assertEqual(m._declared_step_seconds(cmfd,'prec_CMFD_V0200_B-01_03hr_010deg_198001.nc'),10800)
        with self.assertRaises(ValueError):m._declared_step_seconds({},'prec_198001.nc')
        with self.assertRaises(ValueError):m._declared_step_seconds(cmfd,'prec_CMFD_V0200_B-01_06hr_010deg_198001.nc')
    def test_thinned_netcdf_files_fail_end_to_end(self):
        import xarray as xr
        attrs=lambda v:dict(title=f'3-hourly {v} from the China Meteorological Forcing Dataset',description='Category: B-01: 03hr, 0.10deg')
        times=pd.date_range('2000-01-01',periods=24,freq='3h')
        for keep in [slice(None),slice(None,None,2)]:
            d=self.root/f'cmfd_{keep.step}';(d/'Prec').mkdir(parents=True);(d/'Temp').mkdir()
            t=times[keep];lat=[32.95,33.05];lon=[116.95,117.05]
            for var,sub,val,unit in [('prec','Prec',.00001,'kg m-2 s-1'),('temp','Temp',283.15,'K')]:
                arr=np.full((len(t),2,2),val)
                if var=='temp':arr=arr+np.resize([-5.,5.],len(t))[:,None,None]
                ds=xr.Dataset({var:(('time','lat','lon'),arr,{'units':unit})},coords=dict(time=t,lat=lat,lon=lon),attrs=attrs(var))
                ds.to_netcdf(d/sub/f'{var}_CMFD_V0200_B-01_03hr_010deg_200001.nc')
            if keep.step is None:
                data=m.extract_basin_mean_forcing(str(d),None,'2000-01-01','2000-01-03',lat_center=33.,lon_center=117.)
                np.testing.assert_allclose(data['prec_mm_day'],.864);np.testing.assert_allclose(data['tmin_C'],5.);np.testing.assert_allclose(data['tmax_C'],15.)
                self.assertEqual(data['source']['source_step_seconds'],10800.)
            else:
                with self.assertRaises(ValueError):m.extract_basin_mean_forcing(str(d),None,'2000-01-01','2000-01-03',lat_center=33.,lon_center=117.)
    def test_supplied_observations_must_be_complete_and_preserve_zero(self):
        obs=self.root/'obs.tsv';dates=pd.date_range('2000-01-01',periods=3)
        pd.DataFrame({'dates':dates,'Q':[0.,2.,3.]}).to_csv(obs,sep='\t',index=False)
        depth,missing=m.load_obs_qmhr(str(obs),'2000-01-01',3,1)
        np.testing.assert_allclose(depth,[0,.1728,.2592]);self.assertFalse(missing.any())
        self.run_convert(obs_file=str(obs),basin_area_km2=1)
        info=json.loads(Path(str(self.out)+'.provenance.json').read_text())
        self.assertEqual(info['observation_mode'],'provided_complete');self.assertNotIn('obs_missing_rows',info)
        with self.assertRaises((ValueError,FileNotFoundError)):self.run_convert(obs_file=str(self.root/'absent'),basin_area_km2=1)
    def write_obs(self,text):
        obs=self.root/'obs.tsv';obs.write_text(text);return str(obs)
    def test_gap_rows_get_placeholder_and_sidecar_lists_them(self):
        # -99.9 sentinel, -99 sentinel, empty Q cell, and a date with no row at all
        obs=self.write_obs('dates\tQ\n2000-01-01\t-99.9\n2000-01-02\t2\n2000-01-03\t\n2000-01-04\t0\n2000-01-05\t-99\n')
        data=dict(ndays=6,start_date='2000-01-01',prec_mm_day=np.zeros(6),temp_K=np.full(6,283.15),tmin_C=np.full(6,5.),tmax_C=np.full(6,15.))
        for dt,steps in [(24,1),(12,2)]:
            with self.subTest(dt=dt):
                self.run_convert(data,dt=dt,obs_file=obs,basin_area_km2=1)
                q=np.loadtxt(self.out,skiprows=1)[:,2]
                info=json.loads(Path(str(self.out)+'.provenance.json').read_text())
                self.assertEqual(info['observation_mode'],'provided_with_gaps')
                self.assertEqual(info['obs_missing_days'],['2000-01-01','2000-01-03','2000-01-05','2000-01-06'])
                self.assertEqual(info['obs_missing_count_days'],4);self.assertEqual(info['obs_placeholder_value'],-9999.0)
                rows=[d*steps+k+1 for d in [0,2,4,5] for k in range(steps)]
                self.assertEqual(info['obs_missing_rows'],rows)
                self.assertTrue((q[np.array(rows)-1]==-9999).all())
                kept=np.delete(q,np.array(rows)-1)
                np.testing.assert_allclose(kept,np.repeat([.1728/steps,0.],steps))   # true zero kept
                self.assertEqual(m.validate_outputs(str(self.out),6*steps,rows),[])
                self.assertTrue(m.validate_outputs(str(self.out),6*steps))           # not listed -> error
                self.assertTrue(m.validate_outputs(str(self.out),6*steps,rows+[steps+1]))  # listed but real value (2000-01-02)
    def test_custom_sentinel_replaces_defaults(self):
        obs=self.write_obs('dates\tQ\n2000-01-01\t-1\n2000-01-02\t2\n2000-01-03\t3\n')
        depth,missing=m.load_obs_qmhr(obs,'2000-01-01',3,1,missing_values=[-1])
        self.assertEqual(missing.tolist(),[True,False,False])
        obs=self.write_obs('dates\tQ\n2000-01-01\t-99.9\n2000-01-02\t2\n2000-01-03\t3\n')
        with self.assertRaises(ValueError):m.load_obs_qmhr(obs,'2000-01-01',3,1,missing_values=[-1])
        for bad in [[0],[5.],[np.nan]]:
            with self.subTest(bad=bad),self.assertRaises(ValueError):m.load_obs_qmhr(obs,'2000-01-01',3,1,missing_values=bad)
    def test_bad_observations_are_refused(self):
        head='dates\tQ\n'
        cases={'junk':'2000-01-01\tabc\n2000-01-02\t2\n','other negative':'2000-01-01\t-5\n2000-01-02\t2\n',
               'written nan':'2000-01-01\tnan\n2000-01-02\t2\n','NA text':'2000-01-01\tNA\n2000-01-02\t2\n',
               'inf':'2000-01-01\tinf\n2000-01-02\t2\n','duplicate date':'2000-01-01\t1\n2000-01-01\t2\n',
               'unordered':'2000-01-02\t1\n2000-01-01\t2\n','time of day':'2000-01-01 06:00\t1\n2000-01-02\t2\n',
               'all missing':'2000-01-01\t-99.9\n2000-01-02\t\n',
               'date with no Q field':'2000-01-01\n2000-01-02\t2\n2000-01-03\t3\n'}
        for name,body in cases.items():
            with self.subTest(name=name):
                obs=self.write_obs(head+body);self.out.write_text('old valid output\n')
                with self.assertRaises(ValueError):self.run_convert(obs_file=obs,basin_area_km2=1)
                self.assertEqual(self.out.read_text(),'old valid output\n')
        obs=self.write_obs(head+'2000-01-01\t1\n2000-01-02\t2\n2000-01-03\t3\n')
        for area in [None,0,-1,np.nan]:
            with self.subTest(area=area),self.assertRaises(ValueError):self.run_convert(obs_file=obs,basin_area_km2=area)
    def test_short_row_is_refused_but_empty_cell_is_missing(self):
        # empty Q cell (tab present) = missing day; a row cut short (no tab, or a
        # missing trailing field) = refused, never a quiet gap
        depth,missing=m.load_obs_qmhr(self.write_obs('dates\tQ\n2000-01-01\t\n2000-01-02\t2\n'),'2000-01-01',2,1)
        self.assertEqual(missing.tolist(),[True,False])
        depth,missing=m.load_obs_qmhr(self.write_obs('dates\tQ\r\n2000-01-01\t\r\n2000-01-02\t2\r\n'),'2000-01-01',2,1)
        self.assertEqual(missing.tolist(),[True,False])                       # CRLF file
        for name,text in {'no tab':'dates\tQ\n2000-01-01\n2000-01-02\t2\n',
                          'three columns, last missing':'dates\tQ\tflag\n2000-01-01\t1\n2000-01-02\t2\tA\n'}.items():
            with self.subTest(name=name),self.assertRaisesRegex(ValueError,'fewer than'):
                m.load_obs_qmhr(self.write_obs(text),'2000-01-01',2,1)
        depth,missing=m.load_obs_qmhr(self.write_obs('dates\tQ\tflag\n2000-01-01\t\tA\n2000-01-02\t2\t\n'),'2000-01-01',2,1)
        self.assertEqual(missing.tolist(),[True,False])                       # all fields present
    def test_output_validator_uses_given_placeholder(self):
        obs=self.write_obs('dates\tQ\n2000-01-01\t-99.9\n2000-01-02\t2\n2000-01-03\t3\n')
        self.run_convert(obs_file=obs,basin_area_km2=1)
        self.assertEqual(m.validate_outputs(str(self.out),3,[1]),[])
        self.assertTrue(m.validate_outputs(str(self.out),3,[1],placeholder=-1.0))
    def test_output_validator_rejects_nonfinite_values(self):
        self.out.write_text('1  1.0\n nan 0.0 0.0\n')
        self.assertTrue(m.validate_outputs(str(self.out),1))
    def test_cli_stops_on_invalid_input(self):
        proc=subprocess.run([sys.executable,str(TOOL),'--forcing-dir',str(self.root/'absent'),'--start-date','2000-01-01','--end-date','2000-01-03','--lat','33','--lon','117','--output',str(self.out)],capture_output=True,text=True)
        self.assertNotEqual(proc.returncode,0);self.assertNotIn('Continuing with available data',proc.stdout)
        self.assertFalse(self.out.exists())
if __name__=='__main__':unittest.main()
