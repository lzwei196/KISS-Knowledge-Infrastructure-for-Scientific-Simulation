"""Authorized backend diagnostic, NOT a bypass of Desktop scientific approval.

Tiny raster jobs test the server where Desktop conservatively refuses estimates
without coverage metadata. No production project or approval artifacts modified.
"""
import hashlib
import json
import re
import time
import sys
import os
from pathlib import Path

import numpy as np
import rasterio
import netCDF4
from pyproj import CRS
from rasterio.warp import transform_bounds
from kiss_cli import obs_access as obs, obs_subset

ROOT=Path(os.environ.get('GEO_SUBSET_TEST_ROOT','output/geodata-subset-audit-2026-09-14')).resolve()
IDS=['china_dem_90m','hwsd_global','avhrr_landcover','dtb_china','hwsd_global_raster']


def main():
    if '--check-rasters' in sys.argv:
        return validate_saved_rasters()
    if '--check-existing' in sys.argv:
        return validate_saved_netcdf()
    client=obs.Client(timeout=50)
    results=[]
    netcdf_mode='--netcdf' in sys.argv
    selected=['crop_calendar_global','cn05.1_pre_daily_025'] if netcdf_mode else (os.environ.get('GEO_SUBSET_TEST_IDS','').split(',') if os.environ.get('GEO_SUBSET_TEST_IDS') else IDS)
    for dataset in selected:
        r={'dataset_id':dataset,'request':{'dataset_id':dataset,'bbox':[115,37,115.1,37.1],'variables':[]}}
        if netcdf_mode:r['request']['bbox']=[115,37,117,39]
        if dataset=='cn05.1_pre_daily_025':r['request'].update(start='1989-01-01',end='1989-01-07')
        if dataset=='soilgrids_global':r['request']['bbox']=[115,33,115.1,33.1]
        if os.environ.get('GEO_SUBSET_FRESH_PROBE'):
            if netcdf_mode:
                if dataset=='cn05.1_pre_daily_025':r['request'].update(start='1989-01-08',end='1989-01-14')
            else:r['request']['bbox']=[115.01,37.01,115.11,37.11]
        results.append(r)
        try:
            e=client._json('/subsets/estimate',method='POST',body=r['request'])
            r['estimate']={k:v for k,v in e.items() if k in obs_subset.PUBLIC}
            if e.get('subsettable') is not True or not isinstance(e.get('estimated_output_bytes'),int) or e['estimated_output_bytes']>8*1024**2:
                r['status']='skipped_not_small_or_unsupported';continue
            job=client._json('/subsets/jobs',method='POST',body=r['request']); jid=job['job_id']
            if not re.fullmatch(r'[\w-]+',jid):raise ValueError('invalid job id')
            r['job_id']=jid;route='/subsets/jobs/'+jid
            print(dataset,'job',jid,flush=True)
            for _ in range(100):
                job=client._json(route)
                if job['status'] not in ('queued','running'):break
                time.sleep(3)
            r['status']=job['status']
            if job['status']!='ready':continue
            m=client._json(route+'/manifest')
            if m.get('job_id')!=jid or m.get('dataset_id')!=dataset:raise ValueError('wrong manifest')
            parts=m['parts']
            if sum(p['bytes'] for p in parts)>16*1024**2:raise ValueError('output exceeded small-test budget')
            r['files']=[]
            for p in parts:
                if not re.fullmatch(r'[\w.-]+',p['name']) or p['name'] in ('.','..'):raise ValueError('unsafe filename')
                with client._request(route+'/parts/'+str(p['n'])) as response:
                    data=response.read(16*1024**2+1)
                    if len(data)!=p['bytes'] or hashlib.sha256(data).hexdigest()!=p['sha256'] or response.headers.get('X-Content-SHA256')!=p['sha256']:raise ValueError('checksum/size mismatch')
                target=ROOT/'rasters'/dataset/p['name'];target.parent.mkdir(parents=True,exist_ok=True)
                if target.exists():raise ValueError('test file exists; do not overwrite')
                target.write_bytes(data)
                if netcdf_mode:
                    with netCDF4.Dataset(target) as ds:
                        checks={'path':str(target),'bytes':len(data),'sha256':p['sha256'],
                                'dimensions':{k:len(v) for k,v in ds.dimensions.items()},'variables':{},
                                'manifest':{k:v for k,v in p.items() if k in ('time_range','n_time_steps','time_subset_applied','crs','bounds')}}
                        for name,v in ds.variables.items():
                            a=np.ma.asarray(v[:]);valid=a.compressed()
                            checks['variables'][name]={'shape':list(a.shape),'units':getattr(v,'units',None),
                                'valid_count':int(valid.size),'masked_count':int(np.ma.count_masked(a)),
                                'finite':bool(np.isfinite(valid).all()) if np.issubdtype(valid.dtype,np.number) else None}
                            if name=='time' and valid.size and getattr(v,'units',None):
                                dates=netCDF4.num2date(v[:],v.units,calendar=getattr(v,'calendar','standard'))
                                checks['time_first']=str(dates[0]);checks['time_last']=str(dates[-1])
                        checks['readable']=True
                        # Report contents, not an unverified scientific pass.
                        r['files'].append(checks)
                    continue
                with rasterio.open(target) as ds:
                    a=ds.read(masked=True);valid=a.compressed()
                    checks={'path':str(target),'bytes':len(data),'sha256':p['sha256'],'driver':ds.driver,
                            'crs':str(ds.crs),'shape':list(a.shape),'dtype':list(ds.dtypes),'bounds':list(ds.bounds),
                            'resolution':list(ds.res),'nodata':str(ds.nodata),'valid_pixels':int(valid.size),
                            'masked_pixels':int(np.ma.count_masked(a)),'finite':bool(np.isfinite(valid).all()),
                            'minimum':float(valid.min()) if valid.size else None,'maximum':float(valid.max()) if valid.size else None,
                            'integer_classes':bool(np.equal(valid,np.round(valid)).all()) if e.get('categorical') else None,
                            'manifest':{k:v for k,v in p.items() if k in ('bounds','crs','crs_source','variables','units','source_version_hash')}}
                    target_crs=p.get('crs') or e.get('target_crs') or e.get('native_crs')
                    checks['crs_matches']=bool(target_crs and CRS(ds.crs).equals(CRS(target_crs),ignore_axis_order=True))
                    expected=p.get('bounds') or e.get('snapped_output_bounds')
                    checks['bounds_match']=bool(expected and np.allclose(list(ds.bounds),expected,atol=max(ds.res)*.01,rtol=0))
                    checks['passed']=bool(valid.size and checks['finite'] and checks['crs_matches'] and checks['bounds_match'] and checks['integer_classes'] is not False)
                    r['files'].append(checks)
            if not netcdf_mode:r['passed']=bool(r['files']) and all(f['passed'] for f in r['files'])
        except obs.ObsAccessError as error:r.update(status='request_failed',http_status=error.status,error=error.code)
        except Exception as error:r.update(status='check_failed',error=str(error))
        finally:
            obs._atomic_json(ROOT/('netcdf-downloads.json' if netcdf_mode else 'raster-downloads.json'),{'items':results})
            print(dataset,r.get('status'),r.get('passed'),r.get('error',''),flush=True)
    if netcdf_mode:validate_saved_netcdf()
    else:validate_saved_rasters()


def validate_saved_rasters():
    path=ROOT/'raster-downloads.json';report=json.loads(path.read_text())
    for case in report['items']:
        for file in case.get('files',[]):
            with rasterio.open(file['path']) as ds:
                file['crs_matches']=CRS(ds.crs).equals(CRS(file['manifest']['crs']),ignore_axis_order=True)
                expected=transform_bounds('EPSG:4326',ds.crs,*case['request']['bbox'])
                file['requested_area_matches']=bool(np.allclose(list(ds.bounds),expected,atol=max(ds.res)*2,rtol=0))
                file['passed']=bool(file['valid_pixels'] and file['finite'] and file['crs_matches'] and file['bounds_match'] and file['requested_area_matches'] and file['integer_classes'] is not False)
        case['passed']=bool(case.get('files')) and all(f['passed'] for f in case['files'])
    obs._atomic_json(path,report)
    print([(c['dataset_id'],c['passed']) for c in report['items']],flush=True)


def validate_saved_netcdf():
    path=ROOT/'netcdf-downloads.json'
    report=json.loads(path.read_text())
    for case in report['items']:
        request=case['request'];box=request['bbox']
        for file in case.get('files',[]):
            with netCDF4.Dataset(file['path']) as ds:
                coords={name:np.asarray(ds[name][:]) for name in ['latitude','longitude','lat','lon'] if name in ds.variables}
                lat=coords.get('latitude',coords.get('lat'));lon=coords.get('longitude',coords.get('lon'))
                file['spatial_request_matches']=bool(lat is not None and lon is not None and lat.size and lon.size and lat.min()>=box[1] and lat.max()<=box[3] and lon.min()>=box[0] and lon.max()<=box[2])
                file['time_request_matches']=True
                if request.get('start') or request.get('end'):
                    first=file.get('time_first','')[:10];last=file.get('time_last','')[:10]
                    file['time_request_matches']=bool(first and last and (not request.get('start') or first>=request['start']) and (not request.get('end') or last<=request['end']))
                file['delivery_checks_passed']=file['spatial_request_matches'] and file['time_request_matches'] and file['readable']
        case['delivery_checks_passed']=bool(case.get('files')) and all(f['delivery_checks_passed'] for f in case['files'])
    obs._atomic_json(path,report)
    print([(c['dataset_id'],c['delivery_checks_passed']) for c in report['items']],flush=True)


if __name__=='__main__':main()
