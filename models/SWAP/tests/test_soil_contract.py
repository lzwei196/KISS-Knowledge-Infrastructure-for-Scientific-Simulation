"""Artificial texture/CSV/raster fixtures; real US-Ne1 replay is separate."""
import importlib.util,json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
import numpy as np
KI=Path(os.environ.get('KI_UNDER_TEST',Path(__file__).resolve().parents[1]))
spec=importlib.util.spec_from_file_location('soil',KI/'tools/convert_soil_to_swap.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class Tests(unittest.TestCase):
 def test_missing_and_unknown_classes_fail(self):
  for kwargs in [{},{'texture_class':'laom'},{'sand_pct':40},{'texture_class':'sand','subsoil_texture_class':'cllay'}]:
   with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):m.get_mvg_params(**kwargs)
 def test_nonfinite_negative_and_bad_sum_fractions_fail(self):
  for fractions in [(np.nan,40,20),(40,np.inf,20),(-1,81,20),(40,40,0),(101,0,-1)]:
   with self.subTest(fractions=fractions),self.assertRaises(ValueError):m.classify_texture(*fractions)
 def test_known_texture_zero_fraction_and_valid_class(self):
  self.assertEqual(m.classify_texture(93,0,7),'sand')
  cases={'sand':(95,2,3),'loamy_sand':(80,15,5),'sandy_loam':(65,25,10),'loam':(40,40,20),'silt_loam':(20,65,15),'silt':(5,90,5),'sandy_clay_loam':(60,15,25),'clay_loam':(35,35,30),'silty_clay_loam':(10,55,35),'sandy_clay':(55,5,40),'silty_clay':(5,45,50),'clay':(20,20,60)}
  for name,fractions in cases.items():
   with self.subTest(name=name):self.assertEqual(m.classify_texture(*fractions),name)
  layers=m.get_mvg_params(texture_class='loam',n_layers=1)
  self.assertEqual(layers[0]['KSATFIT'],24.96);self.assertTrue(m.validate_outputs(layers))
 def test_no_unmeasured_subsoil_contrast(self):
  with self.assertRaises(ValueError):m.get_mvg_params(texture_class='loam',n_layers=2)
  layers=m.get_mvg_params(texture_class='loam',subsoil_texture_class='loam',n_layers=2)
  self.assertEqual(layers[0]['KSATFIT'],layers[1]['KSATFIT']);self.assertEqual(layers[0]['BDENS'],layers[1]['BDENS'])
 def test_invalid_layer_count_density_and_nan_output(self):
  for n in [0,-1,1.5]:
   with self.assertRaises(ValueError):m.get_mvg_params(texture_class='loam',n_layers=n)
  with self.assertRaises(ValueError):m.get_mvg_params(texture_class='loam',n_layers=1,bdens_override=np.nan)
  layers=m.get_mvg_params(texture_class='loam',n_layers=1);layers[0]['ALFA']=np.nan;self.assertFalse(m.validate_outputs(layers))
 def test_cli_failure_preserves_previous_artifact(self):
  with tempfile.TemporaryDirectory() as td:
   out=Path(td)/'s.json';out.write_text('previous')
   r=subprocess.run([sys.executable,str(KI/'tools/convert_soil_to_swap.py'),'--lat','40','--lon','10','--texture','wrong','--output',str(out)],capture_output=True)
   self.assertNotEqual(r.returncode,0);self.assertEqual(out.read_text(),'previous')
 def test_hwsd_with_manual_texture_is_an_error(self):
  with tempfile.TemporaryDirectory() as td:
   out=Path(td)/'s.txt'
   for extra in [['--texture','loam'],['--sand','40','--silt','40','--clay','20'],['--subsoil-texture','loam']]:
    r=subprocess.run([sys.executable,str(KI/'tools/convert_soil_to_swap.py'),'--hwsd','auto','--lat','40','--lon','10','--output',str(out),*extra],capture_output=True,text=True)
    with self.subTest(extra=extra):
     self.assertNotEqual(r.returncode,0);self.assertIn('cannot be combined with manual texture',r.stderr)
     self.assertFalse(out.exists());self.assertFalse(Path(str(out)+'.summary.json').exists())
 def test_hwsd_raw_missing_field_never_becomes_default(self):
  import pandas as pd,rasterio
  from rasterio.transform import from_origin
  with tempfile.TemporaryDirectory() as td:
   td=Path(td);raster=td/'soil.tif';csv=td/'soil.csv'
   with rasterio.open(raster,'w',driver='GTiff',height=1,width=1,count=1,dtype='int16',crs='EPSG:4326',transform=from_origin(10,41,1,1),nodata=0) as dst:dst.write(np.array([[7]],dtype='int16'),1)
   row=dict(MU_GLOBAL=7,SHARE=100,SEQ=1,T_SAND=40,T_SILT=40,T_CLAY=20,S_SAND=30,S_SILT=30,S_CLAY=40,T_REF_BULK_DENSITY=1.4,S_REF_BULK_DENSITY=1.5)
   pd.DataFrame([row]).to_csv(csv,index=False)
   good=m.read_hwsd_at_point(str(raster),40.5,10.5,hwsd_csv=str(csv));self.assertEqual(good['texture'],'loam');self.assertEqual(good['subsoil_texture'],'clay');self.assertEqual(good['subsoil_bdens'],1500)
   for key in ['T_SAND','S_CLAY','T_REF_BULK_DENSITY']:
    bad=dict(row);bad[key]=np.nan;pd.DataFrame([bad]).to_csv(csv,index=False)
    with self.subTest(key=key),self.assertRaises(ValueError):m.read_hwsd_at_point(str(raster),40.5,10.5,hwsd_csv=str(csv))
   pd.DataFrame([row]).to_csv(csv,index=False)
   with self.assertRaises(ValueError):m.read_hwsd_at_point(str(raster),40.5,10.5,hwsd_csv=str(csv),hwsd_crs='EPSG:3857')
   missing=td/'missing_crs.tif'
   with rasterio.open(missing,'w',driver='GTiff',height=1,width=1,count=1,dtype='int16',transform=from_origin(10,41,1,1),nodata=0) as dst:dst.write(np.array([[7]],dtype='int16'),1)
   with self.assertRaises(ValueError):m.read_hwsd_at_point(str(missing),40.5,10.5,hwsd_csv=str(csv))
   self.assertEqual(m.read_hwsd_at_point(str(missing),40.5,10.5,hwsd_csv=str(csv),hwsd_crs='EPSG:4326')['texture'],'loam')

if __name__=='__main__':unittest.main()
