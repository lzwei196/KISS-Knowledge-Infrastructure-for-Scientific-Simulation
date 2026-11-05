"""Artificial forcing/soil fixtures; real source/native tracer is separate."""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import netCDF4
import numpy as np
import pandas as pd
import xarray as xr
KI=Path(__file__).resolve().parents[1]
def load(name,rel):
    spec=importlib.util.spec_from_file_location(name,KI/rel);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod
f=load('forcing','tools/s2_forcing/convert_forcing_to_wflow.py');k=load('soil','tools/s6_sediment/derive_usle_k.py')
class Contracts(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.r=Path(self.tmp.name)
        self.grid=self.r/'grid.nc';xr.Dataset({'wflow_subcatch':(('y','x'),[[1.,np.nan]])},coords={'y':[32.5],'x':[114.,114.1]}).to_netcdf(self.grid)
        self.dates=pd.date_range('2000-01-01','2000-12-31')
        self.rec=dict(dates=self.dates,precip_mm=np.zeros(366),temp_mean_c=np.full(366,15.),temp_min_c=np.full(366,10.),temp_max_c=np.full(366,20.))
        self.args=SimpleNamespace(source='cmfd',forcing_dir='source',grid_nc=str(self.grid),staticmaps_nc='',start_year=2000,end_year=2000,output=str(self.r/'forcing.nc'),cmfd_dir='',mswx_dir='')
    def read(self):
        with patch('ki_tools_common.load_forcing.load_daily_forcing_points',return_value=[self.rec]):return f.read_forcing_via_ki_tools('cmfd',str(self.grid),2000,2000)
    def test_loader_rejects_missing_short_or_invalid_active_values(self):
        for key in ['precip_mm','temp_mean_c','temp_min_c','temp_max_c']:
            original=self.rec[key]
            for bad in [np.full(366,np.nan),np.full(366,np.inf),np.zeros(365)]:
                self.rec[key]=bad
                with self.subTest(key=key),self.assertRaises(ValueError):self.read()
            self.rec[key]=original
        self.rec['temp_min_c']=np.full(366,30.)
        with self.assertRaises(ValueError):self.read()
    def test_calendar_and_record_count_exact(self):
        for d in [self.dates[:-1],self.dates[::-1],self.dates.delete(1).append(self.dates[:1])]:
            self.rec['dates']=d
            with self.assertRaises(ValueError):self.read()
        with patch('ki_tools_common.load_forcing.load_daily_forcing_points',return_value=[]),self.assertRaises(ValueError):
            f.read_forcing_via_ki_tools('cmfd',str(self.grid),2000,2000)
    def test_valid_zeros_equal_extrema_and_inactive_mask(self):
        self.rec['temp_min_c']=self.rec['temp_mean_c'].copy();self.rec['temp_max_c']=self.rec['temp_mean_c'].copy()
        result=self.read();self.assertTrue((result[3][:,0,0]==0).all());self.assertTrue((result[5][:,0,0]==0).all())
        with patch.object(f,'read_forcing_via_ki_tools',return_value=result):f.process(self.args)
        with xr.open_dataset(self.args.output) as ds:
            self.assertTrue(np.isnan(ds.precip.values[:,:,1]).all());self.assertEqual(ds.attrs['active_cell_fill_count'],0)
    def test_process_rejects_bad_active_values_before_write(self):
        result=list(self.read());Path(self.args.output).write_text('old')
        for idx in [3,4,5]:
            bad=[v.copy() if hasattr(v,'copy') else v for v in result];bad[idx][20,0,0]=np.nan
            with patch.object(f,'read_forcing_via_ki_tools',return_value=tuple(bad)),self.assertRaises(ValueError):f.process(self.args)
            self.assertEqual(Path(self.args.output).read_text(),'old')
    def test_direct_cmfd_missing_month_fails(self):
        with self.assertRaises((ValueError,FileNotFoundError)):f.read_cmfd_forcing_direct(str(self.r/'absent'),str(self.grid),2000,2000)
    def test_soil_invalid_fractions_and_missing_oc_fail(self):
        for vals in [(40,40,20,np.nan),(-1,81,20,1),(40,40,10,1),(40,np.inf,20,1),(40,40,20,-1)]:
            with self.subTest(vals=vals),self.assertRaises(ValueError):k.compute_usle_k(*vals)
        with self.assertRaises((TypeError,ValueError)):k.compute_usle_k(40,40,20)
    def test_soil_valid_zero_and_original_equation(self):
        expected=((2.1e-4*((40+.2*40)*(100-20))**1.14*12)/100)*.1317
        self.assertAlmostEqual(float(k.compute_usle_k(40,40,20,0,struct_code=2,perm_class=3)),expected)
        self.assertTrue(np.isfinite(k.compute_usle_k(100,0,0,0)))
    def test_soilgrids_missing_files_fail(self):
        arrays=[np.full((1,1),np.nan) for _ in range(4)]
        with patch.object(k.os.path,'exists',return_value=False),self.assertRaises((ValueError,FileNotFoundError)):
            k._derive_k_from_soilgrids(np.array([32.5]),np.array([114.]),np.ones((1,1),bool),*arrays)
    def test_native_longitude_latitude_axes_supported(self):
        with xr.open_dataset(self.grid) as ds:d=ds.load().rename({'y':'latitude','x':'longitude'})
        d.to_netcdf(self.grid)
        lats,lons,mask=f.read_grid(self.grid)
        self.assertEqual(k._axes(d),('latitude','longitude'));self.assertEqual(int(mask.sum()),1)
    def test_zero_subcatchment_id_is_not_inactive_padding(self):
        with xr.open_dataset(self.grid) as ds:d=ds.load()
        d['wflow_subcatch'].values[0,1]=0;d.to_netcdf(self.grid)
        with self.assertRaises(ValueError):self.read()
    def test_raw_hwsd_missing_dominant_component_never_replaced(self):
        import rasterio
        from rasterio.transform import from_origin
        raster=self.r/'hwsd.tif';csv=self.r/'hwsd.csv'
        with rasterio.open(raster,'w',driver='GTiff',width=1,height=1,count=1,dtype='int16',crs='EPSG:4326',transform=from_origin(114,33,1,1),nodata=0) as src:src.write(np.array([[1]],dtype=np.int16),1)
        rows=pd.DataFrame(dict(MU_GLOBAL=[1,1],SHARE=[80,20],SEQ=[1,2],T_SAND=[40,40],T_SILT=[40,40],T_CLAY=[20,20],T_OC=[-9999,1.]))
        rows.to_csv(csv,index=False)
        with self.assertRaises(ValueError):k.lookup_hwsd_strict(32.5,114.5,str(raster),str(csv))
        rows.loc[0,'T_OC']=0.;rows.to_csv(csv,index=False)
        props=k.lookup_hwsd_strict(32.5,114.5,str(raster),str(csv));self.assertEqual(props['oc'],0.);self.assertEqual(props['source']['share_pct'],80.)
        rows['MU_GLOBAL']=2;rows.to_csv(csv,index=False)
        with self.assertRaises(ValueError):k.lookup_hwsd_strict(32.5,114.5,str(raster),str(csv))
    def test_non_soil_hwsd_unit_stops_and_lists_cells(self):
        import rasterio
        from rasterio.transform import from_origin
        raster=self.r/'hwsd_ws.tif';csv=self.r/'hwsd_ws.csv'
        with rasterio.open(raster,'w',driver='GTiff',width=2,height=1,count=1,dtype='int16',crs='EPSG:4326',transform=from_origin(114,33,1,1),nodata=0) as src:src.write(np.array([[7,8]],dtype=np.int16),1)
        pd.DataFrame(dict(MU_GLOBAL=[7,8],ISSOIL=[0,1],SHARE=[100,100],SEQ=[1,1],SU_SYM90=['WR','LP'],T_SAND=[np.nan,40],T_SILT=[np.nan,40],T_CLAY=[np.nan,20],T_OC=[np.nan,1.])).to_csv(csv,index=False)
        with self.assertRaisesRegex(k.NonSoilHWSDUnit,'symbol WR'):k.lookup_hwsd_strict(32.5,114.5,str(raster),str(csv))
        grid=self.r/'ws_grid.nc';xr.Dataset({'wflow_subcatch':(('y','x'),[[1.,1.]])},coords={'y':[32.5],'x':[114.5,115.5]}).to_netcdf(grid)
        with self.assertRaisesRegex(k.NonSoilHWSDUnit,r'(?s)1 active cell.*row 0 col 0'):k.derive_k_grid(str(grid),hwsd_raster=str(raster),hwsd_csv=str(csv))
    def test_direct_cmfd_rejects_missing_original_substep(self):
        times=pd.date_range('2000-01-01 01:30','2000-02-01',freq='3h',inclusive='left').delete(20)
        for folder,var,unit,value in [('Prec','prec','kg m-2 s-1',.0001),('Temp','temp','K',283.15)]:
            d=self.r/folder;d.mkdir()
            xr.Dataset({var:(('time','lat','lon'),np.full((len(times),1,2),value),{'units':unit})},coords={'time':times,'lat':[32.5],'lon':[114.,114.1]}).to_netcdf(d/f'{var}_200001.nc')
        with self.assertRaisesRegex(ValueError,'substeps'):f.read_cmfd_forcing_direct(str(self.r),str(self.grid),2000,2000)
    def test_patch_rejects_mismatched_coordinates(self):
        target=self.r/'target.nc';xr.Dataset({'wflow_subcatch':(('y','x'),[[1.,np.nan]])},coords={'y':[33.5],'x':[114.,114.1]}).to_netcdf(target)
        result=dict(K_array=np.array([[.03,np.nan]]),mask=np.array([[True,False]]),lats=np.array([32.5]),lons=np.array([114.,114.1]),stats={'soil_source':'fixture'})
        original=target.read_bytes()
        with self.assertRaises(ValueError):k.patch_netcdf(result,str(target))
        self.assertEqual(target.read_bytes(),original)
    def _hwsd(self,name,mus,table):
        import rasterio
        from rasterio.transform import from_origin
        raster=self.r/f'{name}.tif';csv=self.r/f'{name}.csv'
        with rasterio.open(raster,'w',driver='GTiff',width=len(mus[0]),height=len(mus),count=1,dtype='int16',crs='EPSG:4326',transform=from_origin(114,34,1,1),nodata=0) as src:src.write(np.array(mus,dtype=np.int16),1)
        pd.DataFrame(table).to_csv(csv,index=False);return str(raster),str(csv)
    def test_zero_share_unused_component_allowed(self):
        # Shape of real HWSD MU 12014: shares 40/30/20/10/0.
        raster,csv=self._hwsd('mu12014',[[1]],dict(MU_GLOBAL=[1]*5,SHARE=[40,30,20,10,0],SEQ=[1,2,3,4,5],T_SAND=[40,30,20,10,np.nan],T_SILT=[40,40,40,40,np.nan],T_CLAY=[20,30,40,50,np.nan],T_OC=[1.,1,1,1,np.nan]))
        props=k.lookup_hwsd_strict(33.5,114.5,raster,csv);self.assertEqual(props['source']['share_pct'],40.);self.assertEqual(props['sand'],40.)
        for bad in [[0,0,0,0,0],[40,30,20,10,-1],[40,30,20,10,np.nan]]:
            raster,csv=self._hwsd('bad',[[1]],dict(MU_GLOBAL=[1]*5,SHARE=bad,SEQ=[1,2,3,4,5],T_SAND=[40]*5,T_SILT=[40]*5,T_CLAY=[20]*5,T_OC=[1.]*5))
            k._HWSD_TABLES.clear()
            with self.assertRaisesRegex(ValueError,'shares'):k.lookup_hwsd_strict(33.5,114.5,raster,csv)
    def test_soil_mask_read_in_lat_lon_order(self):
        # Square grid stored as (x, y): active cell must be sampled at its own lat/lon.
        raster,csv=self._hwsd('xy',[[1,2],[3,4]],dict(MU_GLOBAL=[1,2,3,4],SHARE=[100]*4,SEQ=[1]*4,T_SAND=[10,20,30,40],T_SILT=[40]*4,T_CLAY=[50,40,30,20],T_OC=[1.]*4))
        k._HWSD_TABLES.clear()
        sub=np.full((2,2),np.nan);sub[1,0]=1.  # x index 1 (lon 115.5), y index 0 (lat 33.5) -> MU 2
        grid=self.r/'xy.nc';xr.Dataset({'wflow_subcatch':(('x','y'),sub)},coords={'y':[33.5,32.5],'x':[114.5,115.5]}).to_netcdf(grid)
        res=k.derive_k_grid(str(grid),hwsd_raster=raster,hwsd_csv=csv)
        self.assertEqual([(r['row'],r['column'],r['mu_id']) for r in res['source_records']],[(0,1,2)])
    def test_patch_rejects_zero_id_cell(self):
        target=self.r/'zero.nc';xr.Dataset({'wflow_subcatch':(('y','x'),[[1.,0.]])},coords={'y':[32.5],'x':[114.,114.1]}).to_netcdf(target)
        result=dict(K_array=np.array([[.03,np.nan]]),mask=np.array([[True,False]]),lats=np.array([32.5]),lons=np.array([114.,114.1]),stats={'soil_source':'fixture'})
        original=target.read_bytes()
        with self.assertRaisesRegex(ValueError,'positive IDs'):k.patch_netcdf(result,str(target))
        self.assertEqual(target.read_bytes(),original)
    def test_direct_cmfd_coverage_uses_active_cells_only(self):
        times=pd.date_range('2000-01-01 01:30','2001-01-01',freq='3h',inclusive='left')
        for folder,var,unit,value in [('Prec','prec','kg m-2 s-1',.0001),('Temp','temp','K',283.15)]:
            d=self.r/folder;d.mkdir()
            for m in range(1,13):
                t=times[times.month==m]
                xr.Dataset({var:(('time','lat','lon'),np.full((len(t),1,1),value),{'units':unit})},coords={'time':t,'lat':[32.5],'lon':[114.]}).to_netcdf(d/f'{var}_2000{m:02d}.nc')
        # Padding cell at lon 116 lies outside the one-cell source; the active cell is covered.
        grid=self.r/'pad.nc';xr.Dataset({'wflow_subcatch':(('y','x'),[[1.,np.nan]])},coords={'y':[32.5],'x':[114.,116.]}).to_netcdf(grid)
        dates,lats,lons,p,t,pet=f.read_cmfd_forcing_direct(str(self.r),str(grid),2000,2000)
        self.assertEqual(len(dates),366);self.assertTrue(np.isfinite(p[:,0,0]).all());self.assertTrue(np.isnan(p[:,0,1]).all())
        self.assertAlmostEqual(float(p[0,0,0]),.0001*10800*8,places=3)
        # Active cell outside coverage still fails.
        grid2=self.r/'out.nc';xr.Dataset({'wflow_subcatch':(('y','x'),[[np.nan,1.]])},coords={'y':[32.5],'x':[114.,116.]}).to_netcdf(grid2)
        with self.assertRaisesRegex(ValueError,'outside source coverage'):f.read_cmfd_forcing_direct(str(self.r),str(grid2),2000,2000)

if __name__=='__main__':unittest.main()
