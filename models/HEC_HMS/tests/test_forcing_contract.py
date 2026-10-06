"""Artificial daily weather fixtures; never production forcing."""
import importlib.util,json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
import numpy as np
import pandas as pd
import xarray as xr
KI=Path(os.environ.get('KI_UNDER_TEST',Path(__file__).resolve().parents[1]))
TOOL=KI/'tools/convert_forcing_to_hms.py'
spec=importlib.util.spec_from_file_location('forcing',TOOL);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class ForcingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.dates=pd.date_range('2000-01-01',periods=5)
        self.data={v:xr.DataArray(values,dims='time',coords={'time':self.dates},attrs={'units':unit}) for v,values,unit in [
            ('prec',[0,.01,2,3,4],'mm/day'),('temp',[280,281,282,283,284],'K'),('srad',[100]*5,'W m-2')]}
        self.converted={'prec_mm':np.array([0,.01,2,3,4]),'temp_c':np.arange(5)+7.}
        self.pet=pd.Series([1.,2.,3.,4.,5.],index=self.dates)

    def build(self,**kw):
        return m.build_forcing_csv(kw.get('data',self.data),kw.get('converted',self.converted),kw.get('pet',self.pet),kw.get('start','2000-01-01'),kw.get('end','2000-01-05'))

    def test_full_period_and_midyear_alignment(self):
        df=self.build(start='2000-01-03',end='2000-01-05')
        np.testing.assert_array_equal(df.precip_mm,[2,3,4])
        np.testing.assert_array_equal(df.pet_mm,[3,4,5])
        self.assertEqual(df.index[0],pd.Timestamp('2000-01-03'))
        short=dict(self.converted,prec_mm=np.ones(3))
        with self.assertRaises(ValueError):self.build(converted=short)

    def test_missing_nonfinite_and_negative_values_fail(self):
        for name in ['prec_mm','temp_c','pet_mm']:
            for invalid in [np.nan,np.inf,-9999]:
                with self.subTest(name=name,invalid=invalid):
                    c={k:v.copy() for k,v in self.converted.items()};p=self.pet.copy()
                    if name=='pet_mm':p.iloc[2]=invalid
                    else:c[name][2]=invalid
                    with self.assertRaises(ValueError):self.build(converted=c,pet=p)
        with self.assertRaises(ValueError):self.build(pet=None)

    def test_calendar_duplicate_gap_and_shift_fail(self):
        for dates in [self.dates.delete(2),self.dates+pd.Timedelta(days=1),self.dates[[0,1,1,3,4]],self.dates[::-1]]:
            data={k:v.isel(time=slice(0,len(dates))).assign_coords(time=dates) for k,v in self.data.items()}
            with self.subTest(dates=dates),self.assertRaises(ValueError):self.build(data=data)

    def test_units_are_declared_not_guessed_from_magnitude(self):
        self.data['prec'].values[:]=.001
        out=m.convert_units(self.data)
        np.testing.assert_allclose(out['prec_mm'],.001)
        self.data['prec'].attrs['units']='kg m-2 s-1'
        np.testing.assert_allclose(m.convert_units(self.data)['prec_mm'],86.4)
        for unit in ['', 'mystery']:
            self.data['prec'].attrs['units']=unit
            with self.assertRaises(ValueError):m.convert_units(self.data)

    def grid_files(self,missing=False):
        for key,val,unit in [('prec',2.,'mm/day'),('temp',280.,'K')]:
            data=np.full((5,2,2),val)
            if missing and key=='prec':data[2,0,0]=np.nan
            da=xr.DataArray(data,dims=('time','lat','lon'),coords={'time':self.dates,'lat':('lat',[0,1],{'units':'degrees_north'}),'lon':('lon',[0,1],{'units':'degrees_east'})},attrs={'units':unit})
            da.to_dataset(name=key).to_netcdf(self.root/f'{key}_2000.nc')

    def prec_file(self,values=None,times=None,bounds=None,prec_attrs=None,coord_units=('degrees_north','degrees_east'),ds_attrs=None,encoding=None):
        """Write one prec_2000.nc (temperature not used) for coverage/validity/coordinate checks."""
        times=self.dates if times is None else times
        data=np.full((len(times),2,2),2.) if values is None else values
        coords={'time':('time',times,{'bounds':'time_bnds'} if bounds is not None else {}),'lat':('lat',[0.,1.],{'units':coord_units[0]}),'lon':('lon',[0.,1.],{'units':coord_units[1]})}
        ds=xr.Dataset({'prec':(('time','lat','lon'),data,dict({'units':'mm/day'},**(prec_attrs or {})))},coords=coords,attrs=ds_attrs or {})
        if bounds is not None:ds['time_bnds']=(('time','nv'),bounds)
        ds.to_netcdf(self.root/'prec_2000.nc',encoding=encoding or {})

    def read_prec(self,start='2000-01-01',end='2000-01-05',box=(-.4,-.4,1.4,1.4)):
        return m.read_cmfd_forcing(self.root,list(box),start,end,temperature_required=False)

    def test_partial_day_support_fails(self):
        # Codex P1: one hourly mean per day, bounded 00:00-01:00, at 1/3600 mm/s.
        t=self.dates+pd.Timedelta('30min')
        b=np.stack([self.dates,self.dates+pd.Timedelta('1h')],1)
        self.prec_file(values=np.full((5,2,2),1/3600),times=t,bounds=b,prec_attrs={'units':'mm/s'})
        with self.assertRaisesRegex(ValueError,'whole labelled days'):self.read_prec()
        # Subdaily steps without bounds.
        self.prec_file(times=pd.date_range('2000-01-01',periods=5,freq='6h'))
        with self.assertRaisesRegex(ValueError,'exactly one day'):self.read_prec(end='2000-01-01')
        # Point samples are not daily totals or means.
        self.prec_file(prec_attrs={'cell_methods':'time: point'})
        with self.assertRaisesRegex(ValueError,'cell_methods'):self.read_prec()
        # One label with no daily evidence.
        self.prec_file(values=np.full((1,2,2),2.),times=self.dates[:1])
        with self.assertRaisesRegex(ValueError,'daily frequency'):self.read_prec(end='2000-01-01')

    def test_whole_day_support_passes(self):
        b=np.stack([self.dates,self.dates+pd.Timedelta(days=1)],1)
        self.prec_file(values=np.full((5,2,2),1/86400),bounds=b,prec_attrs={'units':'kg m-2 s-1','cell_methods':'time: mean'})
        np.testing.assert_allclose(m.convert_units(self.read_prec())['prec_mm'],1)
        # CMFD style: one 10:30 label per day, no bounds.
        self.prec_file(times=self.dates+pd.Timedelta('10h30min'))
        np.testing.assert_allclose(m.convert_units(self.read_prec())['prec_mm'],2)
        self.prec_file(values=np.full((1,2,2),2.),times=self.dates[:1]+pd.Timedelta('10h30min'),ds_attrs={'frequency':'day'})
        self.assertEqual(len(self.read_prec(end='2000-01-01')['prec']),1)

    def test_values_outside_declared_valid_range_fail(self):
        # Codex P1: 9999 outside valid_range [0,100] in an active cell.
        v=np.full((5,2,2),2.);v[2,1,1]=9999
        for attrs in [{'valid_range':np.array([0.,100.])},{'valid_max':100.},{'valid_min':0.,'valid_max':100.}]:
            with self.subTest(attrs=attrs):
                self.prec_file(values=v,prec_attrs=attrs)
                with self.assertRaisesRegex(ValueError,'valid range'):self.read_prec()
        # Packed data: valid_range is in packed units (0..1000 * 0.1 = 0..100 mm/day).
        packed=np.full((5,2,2),2.);packed[2,1,1]=150.
        self.prec_file(values=packed,prec_attrs={'valid_range':np.array([0,1000],dtype='int16')},encoding={'prec':{'dtype':'int16','scale_factor':.1,'add_offset':0.}})
        with self.assertRaisesRegex(ValueError,'valid range'):self.read_prec()
        # Packed endpoints are valid (codex round 1: float32 unpacking must not reject 0.3 at valid_max).
        for packed_values in [np.full((5,2,2),.3,dtype='float32'),np.zeros((5,2,2))]:
            with self.subTest(packed=float(packed_values.flat[0])):
                self.prec_file(values=packed_values,prec_attrs={'valid_range':np.array([0,3],dtype='int16')},encoding={'prec':{'dtype':'int16','scale_factor':np.float32(.1),'add_offset':np.float32(0)}})
                self.assertTrue(np.isfinite(m.convert_units(self.read_prec())['prec_mm']).all())
        # Float32 stored endpoint equal to a float64 valid_max is valid.
        self.prec_file(values=np.full((5,2,2),.3,dtype='float32'),prec_attrs={'valid_max':.3},encoding={'prec':{'dtype':'float32'}})
        self.assertEqual(len(self.read_prec()['prec']),5)
        # Invalid value outside the basin is not an active cell.
        self.prec_file(values=v,prec_attrs={'valid_range':np.array([0.,100.])})
        np.testing.assert_allclose(m.convert_units(self.read_prec(box=(-.4,-.4,.4,.4)))['prec_mm'],2)
        self.prec_file(values=np.full((5,2,2),2.),prec_attrs={'valid_range':np.array([0.,100.])})
        np.testing.assert_allclose(m.convert_units(self.read_prec())['prec_mm'],2)

    def test_coordinate_units_must_be_degrees(self):
        # Codex P2: radians on lat/lon names must not be read as degrees.
        for units in [('radians','radians'),('degrees_north','radians'),('',''),('m','m')]:
            with self.subTest(units=units):
                self.prec_file(coord_units=units)
                with self.assertRaisesRegex(ValueError,'coordinate units'):self.read_prec()
        # x/y with matching standard_name but radian units.
        ds=xr.Dataset({'prec':(('time','y','x'),np.full((5,2,2),2.),{'units':'mm/day'})},coords={'time':self.dates,
            'y':('y',[0.,1.],{'standard_name':'latitude','units':'radians'}),'x':('x',[0.,1.],{'standard_name':'longitude','units':'radians'})})
        ds.to_netcdf(self.root/'prec_2000.nc')
        with self.assertRaisesRegex(ValueError,'coordinate units'):self.read_prec()
        ds['y'].attrs['units']='degrees_north';ds['x'].attrs['units']='degrees_east';ds.to_netcdf(self.root/'prec_2000.nc')
        np.testing.assert_allclose(m.convert_units(self.read_prec())['prec_mm'],2)

    def test_missing_active_grid_cell_and_missing_file_fail(self):
        self.grid_files(missing=True)
        with self.assertRaises(ValueError):m.read_cmfd_forcing(self.root,[-.4,-.4,1.4,1.4],'2000-01-01','2000-01-05')
        self.grid_files()
        (self.root/'temp_2000.nc').unlink()
        with self.assertRaises((ValueError,FileNotFoundError)):m.read_cmfd_forcing(self.root,[-.4,-.4,1.4,1.4],'2000-01-01','2000-01-05')

    def test_complete_grid_preserves_valid_precipitation(self):
        self.grid_files()
        data=m.read_cmfd_forcing(self.root,[-.4,-.4,1.4,1.4],'2000-01-02','2000-01-04')
        self.assertEqual(len(data['prec']),3)
        converted=m.convert_units(data)
        np.testing.assert_allclose(converted['prec_mm'],2)
        np.testing.assert_allclose(converted['temp_c'],6.85)

    def test_explicit_pet_csv_must_be_complete(self):
        file=self.root/'pet.csv'
        pd.DataFrame({'date':self.dates,'pet_mm':[0,1,2,3,4]}).to_csv(file,index=False)
        result=m.load_pet_csv(file,'2000-01-01','2000-01-05')
        np.testing.assert_array_equal(result,[0,1,2,3,4])
        pd.DataFrame({'date':self.dates.delete(2),'pet_mm':[0,1,3,4]}).to_csv(file,index=False)
        with self.assertRaises(ValueError):m.load_pet_csv(file,'2000-01-01','2000-01-05')

    def test_unused_temperature_is_explicit_and_omitted(self):
        data={'prec':self.data['prec']};converted={'prec_mm':self.converted['prec_mm']}
        with self.assertRaises(ValueError):self.build(data=data,converted=converted)
        df=m.build_forcing_csv(data,converted,self.pet,'2000-01-01','2000-01-05',temperature_required=False)
        self.assertEqual(list(df.columns),['precip_mm','pet_mm'])
        np.testing.assert_array_equal(df.precip_mm,converted['prec_mm'])

    def test_cli_requires_pet_source_before_writing(self):
        out=self.root/'out'
        proc=subprocess.run([sys.executable,str(TOOL),'--forcing_dir',str(self.root),'--basin_shp',str(self.root/'absent.shp'),'--start_date','2000-01-01','--end_date','2000-01-05','--output_dir',str(out)],capture_output=True,text=True)
        self.assertNotEqual(proc.returncode,0);self.assertIn('--pet_csv',proc.stderr);self.assertFalse(out.exists())

if __name__=='__main__':unittest.main()
