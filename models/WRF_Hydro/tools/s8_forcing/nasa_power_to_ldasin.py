#!/usr/bin/env python3
"""Strict NASA POWER hourly UTC weather -> WRF-Hydro LDASIN.

No missing weather, timestamp, unit or direction is inferred. Original JSON
responses are retained in a separate cache. Legacy NPZ lacks calendar/units and
is not consumed. POWER precipitation units have changed between API versions:
conversion follows each response's metadata, never a fixed assumed divisor.
Wind uses real WS10M/WD10M; interpolated Earth vectors are rotated using geo_em.
Spatial interpolation does not increase the source product's information content.
"""
import argparse
import hashlib
import json
import os
import shutil
import tempfile
import time as _time
from datetime import datetime,timedelta
from pathlib import Path
import netCDF4 as nc
import numpy as np
from scipy.interpolate import RegularGridInterpolator

NASA_POWER_URL='https://power.larc.nasa.gov/api/temporal/hourly/point'
NASA_POWER_PARAMS='T2M,PRECTOTCORR,PS,ALLSKY_SFC_SW_DWN,ALLSKY_SFC_LW_DWN,QV2M,WS10M,WD10M'
POWER_RESOLUTION=.5
DEFAULT_CACHE_DIR=Path('KISSPATH_DATA/nasa_power_cache/hourly')
_config={'cache_dir':DEFAULT_CACHE_DIR}
VARIABLES=('T2D','Q2D','U2D','V2D','PSFC','SWDOWN','LWDOWN','RAINRATE')


def validate_ldasin(data,shape=None):
    for name in VARIABLES:
        if name not in data:
            raise ValueError(f'Missing required LDASIN field {name}')
        arr=np.asanyarray(data[name])
        if np.ma.isMaskedArray(arr) and np.ma.getmaskarray(arr).any():
            raise ValueError(f'{name}: masked weather is not permitted')
        arr=np.asarray(arr,dtype=float)
        if not arr.size or not np.isfinite(arr).all() or (shape is not None and arr.shape!=shape):
            raise ValueError(f'{name}: shape mismatch or nonfinite weather')
        if not np.isfinite(arr.astype(np.float32)).all():
            raise ValueError(f'{name}: value exceeds native float32 range')
        if name=='T2D' and np.any((arr<173.15)|(arr>343.15)):
            raise ValueError('T2D outside -100 to 70 Celsius; verify units')
        if name=='Q2D' and np.any((arr<0)|(arr>0.1)):
            raise ValueError('Q2D outside [0,0.1] kg/kg; verify units')
        if name=='PSFC' and np.any((arr<1000)|(arr>120000)):
            raise ValueError('PSFC outside [1000,120000] Pa; verify units')
        if name in ('SWDOWN','LWDOWN','RAINRATE') and np.any(arr<0):
            raise ValueError(f'{name}: negative weather is not permitted')


def regrid_to_lcc(src_lats,src_lons,data_2d,xlat_2d,xlon_2d,method='linear'):
    data=np.asarray(data_2d,dtype=float)
    lat=np.asarray(src_lats,dtype=float);lon=np.asarray(src_lons,dtype=float)
    targets=np.column_stack([np.asarray(xlat_2d).ravel(),np.asarray(xlon_2d).ravel()])
    if data.shape!=(len(lat),len(lon)) or not np.isfinite(data).all() or not np.isfinite(targets).all():
        raise ValueError('Regridding requires complete finite source and target coordinates/values')
    if not np.isfinite(lat).all() or not np.isfinite(lon).all() or np.any(np.diff(lat)<=0) or np.any(np.diff(lon)<=0):
        raise ValueError('Source coordinates must be finite and strictly increasing')
    interp=RegularGridInterpolator((lat,lon),data,method=method,bounds_error=True)
    result=interp(targets).reshape(np.shape(xlat_2d))
    if not np.isfinite(result).all():raise ValueError('Interpolation produced missing weather')
    return result.astype(np.float32)


def rotate_wind_to_grid(u,v,cosalpha,sinalpha):
    c=np.asarray(cosalpha,dtype=float);s=np.asarray(sinalpha,dtype=float)
    if c.shape!=u.shape or s.shape!=u.shape or not np.isfinite(c).all() or not np.isfinite(s).all() or not np.allclose(c*c+s*s,1.,atol=1e-5):
        raise ValueError('Valid COSALPHA/SINALPHA matching target grid are required')
    return u*c+v*s, v*c-u*s


def elevation_correction(t2d,psfc,q2d,hgt_target,hgt_source_interp):
    """Explicit lapse-rate/hypsometric approximation; never a data-gap repair."""
    dz=np.asarray(hgt_target)-np.asarray(hgt_source_interp)
    if not np.isfinite(dz).all():raise ValueError('Elevation correction requires finite elevations')
    corrected=t2d-.0065*dz
    tv=corrected*(1.+.61*q2d)
    if np.any(tv<=0):raise ValueError('Invalid virtual temperature for pressure correction')
    return corrected,psfc*np.exp(-9.80665*dz/(287.*tv))


def estimate_power_elevation(psfc_3d,t2d_3d):
    """Optional barometric estimate assumes sea-level pressure 101325 Pa."""
    if not np.isfinite(psfc_3d).all() or not np.isfinite(t2d_3d).all() or np.any(psfc_3d<=0):
        raise ValueError('Barometric estimate requires complete valid P/T')
    return (np.mean(t2d_3d,axis=0)/.0065)*(1.-(np.mean(psfc_3d,axis=0)/101325.)**(287.*.0065/9.80665))


def compute_power_grid_points(lat_min,lat_max,lon_min,lon_max,buffer_deg=.5):
    if not (-90<=lat_min<=lat_max<=90 and -180<=lon_min<=lon_max<=180):
        raise ValueError('Invalid geographic bounds; antimeridian crossing requires a separate grid')
    latlo=max(-90,np.floor((lat_min-buffer_deg)/POWER_RESOLUTION)*POWER_RESOLUTION)
    lathi=min(90,np.ceil((lat_max+buffer_deg)/POWER_RESOLUTION)*POWER_RESOLUTION)
    lonlo=max(-180,np.floor((lon_min-buffer_deg)/POWER_RESOLUTION)*POWER_RESOLUTION)
    lonhi=min(180,np.ceil((lon_max+buffer_deg)/POWER_RESOLUTION)*POWER_RESOLUTION)
    return np.arange(latlo,lathi+.01,POWER_RESOLUTION),np.arange(lonlo,lonhi+.01,POWER_RESOLUTION)


def _load_npz_cache(lat,lon,year):
    """Legacy cache cannot establish units/UTC/hour keys; never use its arrays."""
    path=_config['cache_dir']/f'{lat:.1f}_{lon:.1f}'/f'{year}.npz'
    if path.exists():raise ValueError(f'Unverifiable legacy NPZ cache: {path}; refetch original JSON into the strict cache')
    return None


def _hour_keys(start,end):
    count=int((end-start).total_seconds()/3600)
    return [(start+timedelta(hours=i)).strftime('%Y%m%d%H') for i in range(count)]


def _parse_response(response,lat,lon,start,end):
    expected=_hour_keys(start,end+timedelta(days=1))
    header=response.get('header',{})
    if header.get('time_standard')!='UTC':raise ValueError('POWER response must explicitly declare UTC')
    coords=response.get('geometry',{}).get('coordinates',[])
    if len(coords)<2 or not np.allclose(coords[:2],[lon,lat],atol=1e-6,rtol=0):raise ValueError('POWER response location differs from requested point')
    if 'fill_value' not in header:raise ValueError('POWER response lacks missing-value metadata')
    values=response.get('properties',{}).get('parameter',{})
    meta=response.get('parameters',{})
    result={}
    for name in NASA_POWER_PARAMS.split(','):
        field=values.get(name)
        if not isinstance(field,dict) or sorted(field)!=expected:
            raise ValueError(f'{name}: response lacks exact requested hourly calendar')
        if name not in meta or not meta[name].get('units'):raise ValueError(f'{name}: missing source units')
        result[name]=np.array([field[key] if field[key] is not None else np.nan for key in expected],dtype=float)
    result['_metadata']={'timestamps':expected,'time_standard':'UTC','units':{k:meta[k]['units'] for k in NASA_POWER_PARAMS.split(',')},'fill_value':header['fill_value'],'latitude':lat,'longitude':lon}
    return result


def fetch_power_point(lat,lon,year,start_dt=None,end_dt=None):
    import requests
    start=start_dt or datetime(year,1,1);end=end_dt or datetime(year,12,31)
    cache=_config['cache_dir']/'strict_utc_10m'/f'{lat:.6f}_{lon:.6f}_{start:%Y%m%d}_{end:%Y%m%d}.json'
    if cache.exists():
        response=json.loads(cache.read_text())
    else:
        params={'start':start.strftime('%Y%m%d'),'end':end.strftime('%Y%m%d'),'latitude':float(lat),'longitude':float(lon),'community':'RE','parameters':NASA_POWER_PARAMS,'format':'JSON','header':'true','time-standard':'UTC'}
        for attempt in range(3):
            try:
                r=requests.get(NASA_POWER_URL,params=params,timeout=120);r.raise_for_status();response=r.json();break
            except requests.RequestException:
                if attempt==2:raise
                _time.sleep(2*(attempt+1))
        # Never store an unparseable/time-shifted response as a usable cache.
        _parse_response(response,lat,lon,start,end)
        cache.parent.mkdir(parents=True,exist_ok=True)
        with tempfile.NamedTemporaryFile(mode='w',dir=cache.parent,delete=False) as f:
            json.dump(response,f,allow_nan=False);pending=Path(f.name)
        pending.replace(cache)
    raw=_parse_response(response,lat,lon,start,end)
    raw['_metadata']['source_file']=str(cache.resolve())
    raw['_metadata']['source_sha256']=hashlib.sha256(cache.read_bytes()).hexdigest()
    return raw


def _convert_point(raw,times,lat,lon):
    meta=raw.get('_metadata',{})
    if meta.get('time_standard')!='UTC':raise ValueError('Explicit UTC metadata required; legacy arrays are not accepted')
    if not np.allclose([meta.get('latitude',np.nan),meta.get('longitude',np.nan)],[lat,lon],atol=1e-6,rtol=0):raise ValueError('Source location metadata mismatch')
    stamps=meta.get('timestamps',[])
    try:dates=[datetime.strptime(s,'%Y%m%d%H') for s in stamps]
    except (ValueError,TypeError):raise ValueError('Invalid hourly timestamp keys')
    if not dates or any(b-a!=timedelta(hours=1) for a,b in zip(dates,dates[1:])):raise ValueError('Source calendar must be unique, ordered and contiguous')
    positions={d:i for i,d in enumerate(dates)}
    if any(t not in positions for t in times):raise ValueError('Missing requested source hour')
    idx=[positions[t] for t in times]
    units=meta.get('units',{});data={}
    fill=meta.get('fill_value')
    if fill is None:raise ValueError('Missing source fill-value metadata')
    for name in NASA_POWER_PARAMS.split(','):
        if name not in raw:raise ValueError(f'Missing required POWER parameter {name}')
        arr=np.asarray(raw[name],dtype=float)
        if arr.ndim!=1 or len(arr)!=len(dates):raise ValueError(f'{name}: values do not match source calendar')
        arr=arr[idx]
        if not np.isfinite(arr).all() or np.any(arr==fill):raise ValueError(f'{name}: missing/nonfinite value at requested point/hour')
        unit=str(units.get(name,'')).lower().replace(' ','').replace('²','^2')
        if name=='T2M':
            if unit in ('c','degc'):arr=arr+273.15
            elif unit!='k':raise ValueError(f'{name}: unsupported units {unit}')
        elif name=='QV2M':
            if unit=='g/kg':arr=arr/1000.
            elif unit!='kg/kg':raise ValueError(f'{name}: unsupported units {unit}')
        elif name=='PS':
            if unit=='kpa':arr=arr*1000.
            elif unit=='hpa':arr=arr*100.
            elif unit!='pa':raise ValueError(f'{name}: unsupported units {unit}')
        elif name in ('WS10M','WD10M'):
            if unit not in (('m/s',) if name=='WS10M' else ('degrees','degree')):raise ValueError(f'{name}: unsupported units {unit}')
            if np.any(arr<0) or (name=='WD10M' and np.any(arr>360)):raise ValueError(f'{name}: invalid speed/direction')
        elif name=='PRECTOTCORR':
            if unit in ('mm/hour','mm/hr'):arr=arr/3600.
            elif unit=='mm/day':arr=arr/86400.
            elif unit not in ('mm/s','kg/m^2/s'):raise ValueError(f'{name}: unsupported units {unit}')
        else:
            if unit in ('w/m^2','wh/m^2'):pass # energy over each complete one-hour interval -> mean W/m2
            elif unit in ('mj/m^2/hr','mj/m^2/hour'):arr=arr/.0036
            else:raise ValueError(f'{name}: unsupported units {unit}')
        data[name]=arr
    direction=np.deg2rad(data['WD10M']);speed=data['WS10M']
    result={'T2D':data['T2M'],'Q2D':data['QV2M'],'PSFC':data['PS'],'U2D':-speed*np.sin(direction),'V2D':-speed*np.cos(direction),'RAINRATE':data['PRECTOTCORR'],'SWDOWN':data['ALLSKY_SFC_SW_DWN'],'LWDOWN':data['ALLSKY_SFC_LW_DWN']}
    validate_ldasin(result)
    return result


def build_hourly_grids(power_lats,power_lons,year,start_dt,end_dt):
    first=max(start_dt,datetime(year,1,1));last=min(end_dt,datetime(year,12,31))
    if first>last:return {},[]
    if first.hour or first.minute or first.second or last.hour or last.minute or last.second:raise ValueError('Requested start/end must be whole UTC dates')
    times=[datetime.strptime(s,'%Y%m%d%H') for s in _hour_keys(first,last+timedelta(days=1))]
    grids={v:np.empty((len(times),len(power_lats),len(power_lons)),dtype=float) for v in VARIABLES};sources=[]
    for i,lat in enumerate(power_lats):
        for j,lon in enumerate(power_lons):
            raw=fetch_power_point(lat,lon,year,start_dt=first,end_dt=last)
            converted=_convert_point(raw,times,lat,lon)
            for name in VARIABLES:grids[name][:,i,j]=converted[name]
            sources.append(raw['_metadata'])
    _config['last_sources']=sources
    return grids,times

def write_ldasin(filepath, time_dt, grid_sn, grid_we, data_dict):
    """
    Write a single LDASIN_DOMAIN1 NetCDF file.

    Parameters
    ----------
    filepath : Path
    time_dt  : datetime for this timestep
    grid_sn, grid_we : south_north and west_east dimensions
    data_dict : dict var_name -> 2D array (sn, we)
    """
    validate_ldasin(data_dict, (grid_sn, grid_we))
    ds = nc.Dataset(str(filepath), 'w', format='NETCDF4')
    ds.forcing_provenance = 'NASA POWER UTC; complete source calendar; metadata-driven units; zero filled values'
    ds.wind_source = '10-m WS10M and WD10M, meteorological direction; rotated to target grid when called by CLI'
    ds.filled_values = 0

    ds.createDimension('Time', 1)
    ds.createDimension('south_north', grid_sn)
    ds.createDimension('west_east', grid_we)
    ds.createDimension('DateStrLen', 20)

    # Times variable -- character array
    time_str = time_dt.strftime('%Y-%m-%d_%H:%M:%S') + '\x00'
    times_var = ds.createVariable('Times', 'S1', ('DateStrLen',))
    times_var[:] = np.array(list(time_str), dtype='S1')

    # valid_time
    vt = ds.createVariable('valid_time', 'f8', ('Time',))
    vt.units = 'seconds since 1970-01-01 00:00:00'
    vt.calendar = 'standard'
    epoch = datetime(1970, 1, 1)
    vt[0] = (time_dt - epoch).total_seconds()

    var_meta = {
        'T2D':      {'long_name': '2-m temperature',                  'units': 'K'},
        'Q2D':      {'long_name': '2-m specific humidity',            'units': 'kg/kg'},
        'U2D':      {'long_name': '10-m U-component of wind',         'units': 'm/s'},
        'V2D':      {'long_name': '10-m V-component of wind',         'units': 'm/s'},
        'PSFC':     {'long_name': 'Surface pressure',                  'units': 'Pa'},
        'SWDOWN':   {'long_name': 'Downward shortwave radiation flux', 'units': 'W/m^2'},
        'LWDOWN':   {'long_name': 'Downward longwave radiation flux',  'units': 'W/m^2'},
        'RAINRATE': {'long_name': 'Precipitation rate',                'units': 'mm s^-1'},
    }

    for vname in ['T2D', 'Q2D', 'U2D', 'V2D', 'PSFC', 'SWDOWN', 'LWDOWN', 'RAINRATE']:
        v = ds.createVariable(vname, 'f4', ('Time', 'south_north', 'west_east'),
                              fill_value=np.float32(1e20))
        v.missing_value = np.float32(1e20)
        for attr, val in var_meta[vname].items():
            setattr(v, attr, val)
        v[0, :, :] = data_dict[vname].astype(np.float32)

    ds.close()



def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--geo_em',required=True)
    parser.add_argument('--output_dir',required=True,help='New directory; existing output is never overwritten')
    parser.add_argument('--start_date',required=True)
    parser.add_argument('--end_date',required=True)
    parser.add_argument('--cache_dir',default=str(DEFAULT_CACHE_DIR))
    parser.add_argument('--elev-correction',choices=['none','barometric-estimate'],default='none',help='Explicit opt-in approximation; default leaves source T/P unchanged')
    parser.add_argument('--no_elev_correct',action='store_true',help='Compatibility alias for --elev-correction none')
    args=parser.parse_args()
    first=datetime.strptime(args.start_date,'%Y-%m-%d');last=datetime.strptime(args.end_date,'%Y-%m-%d')
    if first>last:raise ValueError('Start date exceeds end date')
    output=Path(args.output_dir)
    if output.exists():raise ValueError('Output directory already exists; choose a new directory')
    _config['cache_dir']=Path(args.cache_dir)
    with nc.Dataset(args.geo_em) as ds:
        def read(name):
            if name not in ds.variables:raise ValueError(f'geo_em lacks required {name}')
            value=np.ma.asarray(ds[name][0],dtype=float)
            if np.ma.getmaskarray(value).any() or not np.isfinite(value).all():raise ValueError(f'geo_em {name}: invalid grid values')
            return np.asarray(value)
        lat=read('XLAT_M');lon=read('XLONG_M');c=read('COSALPHA');s=read('SINALPHA')
        elev=read('HGT_M') if args.elev_correction=='barometric-estimate' and not args.no_elev_correct else None
    if lat.shape!=lon.shape or lat.ndim!=2:raise ValueError('Invalid target grid shape')
    rotate_wind_to_grid(np.zeros_like(lat),np.zeros_like(lat),c,s)
    src_lat,src_lon=compute_power_grid_points(float(lat.min()),float(lat.max()),float(lon.min()),float(lon.max()))
    output.parent.mkdir(parents=True,exist_ok=True)
    all_sources=[];count=0
    with tempfile.TemporaryDirectory(dir=output.parent,prefix='.power-staging-') as tmp:
        stage=Path(tmp)/'FORCING';stage.mkdir()
        for year in range(first.year,last.year+1):
            grids,times=build_hourly_grids(src_lat,src_lon,year,first,last)
            all_sources.extend(_config['last_sources'])
            source_elev=regrid_to_lcc(src_lat,src_lon,estimate_power_elevation(grids['PSFC'],grids['T2D']),lat,lon,method='nearest') if elev is not None else None
            for i,t in enumerate(times):
                data={name:regrid_to_lcc(src_lat,src_lon,grids[name][i],lat,lon) for name in VARIABLES}
                data['U2D'],data['V2D']=rotate_wind_to_grid(data['U2D'],data['V2D'],c,s)
                if elev is not None:data['T2D'],data['PSFC']=elevation_correction(data['T2D'],data['PSFC'],data['Q2D'],elev,source_elev)
                write_ldasin(stage/f'{t:%Y%m%d%H}.LDASIN_DOMAIN1',t,*lat.shape,data);count+=1
        assert count==((last-first).days+1)*24
        proof={'source':'NASA POWER hourly API','time_standard':'UTC','start':args.start_date,'end':args.end_date,'n_hours':count,'filled_values':0,'source_records':all_sources,'target_geo_em_sha256':hashlib.sha256(Path(args.geo_em).read_bytes()).hexdigest(),'wind':'WS10M/WD10M -> Earth U/V -> COSALPHA/SINALPHA target grid rotation','elevation_correction':'none' if elev is None else 'explicit barometric estimate, sea-level P=101325 Pa and lapse rate=.0065 K/m','spatial_method':'bilinear interpolation of sampled POWER points; no extrapolation or gap filling'}
        (stage/'forcing_provenance.json').write_text(json.dumps(proof,indent=2,allow_nan=False)+'\n')
        if output.exists():raise ValueError('Output appeared during conversion; refusing to overwrite')
        stage.rename(output)
    print(f'Wrote {count} validated hourly files to {output}; filled values: 0')

if __name__=='__main__':
    main()
