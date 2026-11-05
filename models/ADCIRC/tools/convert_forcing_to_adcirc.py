#!/usr/bin/env python3
"""Strict CSV/ERA5 hourly wind and pressure to ADCIRC NWS=12 OWI.

CSV requires time,lat,lon,u10,v10,pressure, with UTC timestamps and declared
units (defaults m/s and mb). Dates are inclusive instants, not entire end days.
Every requested time/grid cell must exist. No filling, clipping, extrapolation
or magnitude-based unit guesses. ERA5 requires u10,v10,msl with unit metadata;
surface pressure is never silently substituted for mean sea-level pressure.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
import numpy as np
import pandas as pd

WIND_UNITS={'m/s':1.,'m s-1':1.,'m s**-1':1.,'knots':1852/3600,'km/h':1/3.6}
PRESSURE_UNITS={'mb':1.,'hPa':1.,'Pa':.01,'kPa':10.}


def _time(value):
    t=pd.Timestamp(value)
    if pd.isna(t):raise ValueError('Missing timestamp')
    if t.tzinfo is not None:t=t.tz_convert('UTC').tz_localize(None)
    if t.second or t.microsecond or t.nanosecond:raise ValueError('OWI timestamps require whole minutes')
    return t


def validate_inputs(args):
    if not Path(args.input_dir).is_dir():raise ValueError('Input directory missing')
    sw_lat,sw_lon=map(float,args.domain_sw.split(','));ne_lat,ne_lon=map(float,args.domain_ne.split(','))
    if not (-90<=sw_lat<ne_lat<=90 and -180<=sw_lon<ne_lon<=180):raise ValueError('Require increasing geographic lat/lon bounds; split dateline domains upstream')
    if not np.isfinite(args.resolution) or args.resolution<=0:raise ValueError('Resolution must be positive')
    start,end=_time(args.start_date),_time(args.end_date)
    step=getattr(args,'step_seconds',3600)
    if start>=end or not np.isfinite(step) or step<=0 or step%60:raise ValueError('Require start < end and positive whole-minute cadence')
    if (end-start).total_seconds()%step:raise ValueError('End must align to requested cadence')
    if args.format not in ('csv','era5_nc'):raise ValueError('Implemented formats: csv, era5_nc')
    return sw_lat,sw_lon,ne_lat,ne_lon,start,end


def _factor(units,mapping):
    if units not in mapping:raise ValueError(f'Unsupported or missing units: {units!r}; supported: {list(mapping)}')
    return mapping[units]


def _complete(df,sw_lat,sw_lon,ne_lat,ne_lon,start,end,step_seconds=3600):
    required=['time','lat','lon','u10','v10','pressure']
    if not set(required)<=set(df):raise ValueError('Required columns: '+','.join(required))
    df=df[required].copy()
    for c in required[1:]:df[c]=pd.to_numeric(df[c],errors='raise')
    if not np.isfinite(df[['lat','lon']].to_numpy()).all():raise ValueError('Missing/nonfinite coordinates')
    df.time=pd.to_datetime(df.time,utc=True,errors='raise').dt.tz_localize(None)
    if df.time.isna().any():raise ValueError('Missing timestamps')
    df=df[df.lat.between(sw_lat-1e-8,ne_lat+1e-8)&df.lon.between(sw_lon-1e-8,ne_lon+1e-8)&df.time.between(start,end)]
    if df.empty:raise ValueError('No data in requested domain/time')
    if df.duplicated(['time','lat','lon']).any():raise ValueError('Duplicate time/grid cell')
    lats=np.sort(df.lat.unique());lons=np.sort(df.lon.unique())
    for a,low,high in [(lats,sw_lat,ne_lat),(lons,sw_lon,ne_lon)]:
        if len(a)<2 or not np.allclose(np.diff(a),np.diff(a)[0],rtol=0,atol=1e-8) or not np.allclose([a[0],a[-1]],[low,high],rtol=0,atol=1e-8):
            raise ValueError('Complete uniform grid must include both declared domain edges')
    times=pd.date_range(start,end,freq=pd.Timedelta(seconds=step_seconds))
    index=pd.MultiIndex.from_product([times,lats,lons],names=['time','lat','lon'])
    ordered=df.set_index(['time','lat','lon'])
    if len(ordered)!=len(index) or not ordered.index.isin(index).all():raise ValueError('Missing or off-cadence time/grid cells')
    ordered=ordered.reindex(index)
    fields=[ordered[k].to_numpy().reshape(len(times),len(lats),len(lons)) for k in ['u10','v10','pressure']]
    _check_fields(*fields)
    return list(times),lats,lons,*fields


def _check_fields(u,v,p):
    if not all(np.isfinite(x).all() for x in [u,v,p]):raise ValueError('Missing/nonfinite weather; repair source without filling')
    if np.any(np.hypot(u,v)>120):raise ValueError('Wind exceeds 120 m/s; verify source units (never auto-converted)')
    if np.any((p<100)|(p>1200)):raise ValueError('Pressure outside 100..1200 mb; verify declared units/source')


def read_csv(input_dir,sw_lat,sw_lon,ne_lat,ne_lon,start,end,step_seconds=3600,wind_unit='m/s',pressure_unit='mb'):
    files=sorted(Path(input_dir).glob('*.csv'))
    if not files:raise ValueError('No CSV files')
    frames=[]
    for path in files:
        df=pd.read_csv(path)
        if not {'time','lat','lon','u10','v10','pressure'}<=set(df):raise ValueError(f'{path}: missing required columns')
        for k in ['u10','v10']:df[k]=pd.to_numeric(df[k],errors='raise')*_factor(wind_unit,WIND_UNITS)
        df.pressure=pd.to_numeric(df.pressure,errors='raise')*_factor(pressure_unit,PRESSURE_UNITS)
        frames.append(df)
    return _complete(pd.concat(frames,ignore_index=True),sw_lat,sw_lon,ne_lat,ne_lon,start,end,step_seconds)


def read_era5_nc(input_dir,sw_lat,sw_lon,ne_lat,ne_lon,start,end,step_seconds=3600):
    import netCDF4 as nc
    files=sorted(Path(input_dir).glob('*.nc'));frames=[];grid=None
    if not files:raise ValueError('No NetCDF files')
    for path in files:
        with nc.Dataset(path) as d:
            latname='latitude' if 'latitude' in d.variables else 'lat';lonname='longitude' if 'longitude' in d.variables else 'lon'
            if not {'time',latname,lonname,'u10','v10','msl'}<=set(d.variables):raise ValueError(f'{path}: require time, latitude/longitude, u10, v10 and msl (not sp)')
            lat=d[latname];lon=d[lonname];t=d['time']
            if len(lat.dimensions)!=1 or len(lon.dimensions)!=1 or len(t.dimensions)!=1:raise ValueError('Require 1D time and geographic axes')
            la=np.ma.filled(lat[:],np.nan);lo=np.ma.filled(lon[:],np.nan)
            if not np.isfinite(la).all() or not np.isfinite(lo).all():raise ValueError('Invalid NetCDF coordinates')
            li=np.where((la>=sw_lat-1e-8)&(la<=ne_lat+1e-8))[0];lj=np.where((lo>=sw_lon-1e-8)&(lo<=ne_lon+1e-8))[0]
            if len(li)<2 or len(lj)<2:raise ValueError('NetCDF does not cover declared grid')
            current=(np.sort(la[li]),np.sort(lo[lj]))
            if grid is not None and any(not np.array_equal(a,b) for a,b in zip(grid,current)):raise ValueError('NetCDF grids differ between files')
            grid=current
            if getattr(t,'calendar','standard') not in ['standard','gregorian','proleptic_gregorian']:raise ValueError('Require Gregorian UTC calendar')
            times=[_time(x.isoformat()) for x in nc.num2date(t[:],t.units,calendar=getattr(t,'calendar','standard'))]
            ti=[i for i,x in enumerate(times) if start<=x<=end]
            if not ti:continue
            arrays=[]
            for key,mapping in [('u10',WIND_UNITS),('v10',WIND_UNITS),('msl',PRESSURE_UNITS)]:
                var=d[key]
                if var.dimensions!=(t.dimensions[0],lat.dimensions[0],lon.dimensions[0]):raise ValueError(f'{key}: require time,lat,lon dimensions')
                a=np.ma.filled(var[ti,li,lj],np.nan).astype(float)*_factor(getattr(var,'units',None),mapping)
                arrays.append(a.flatten())
            index=pd.MultiIndex.from_product([[times[i] for i in ti],la[li],lo[lj]],names=['time','lat','lon'])
            df=index.to_frame(index=False)
            for key,a in zip(['u10','v10','pressure'],arrays):df[key]=a
            frames.append(df)
    if not frames:raise ValueError('No ERA5 data in requested period')
    return _complete(pd.concat(frames,ignore_index=True),sw_lat,sw_lon,ne_lat,ne_lon,start,end,step_seconds)


def _fixed(value,width):
    for places in [4,3,2,1,0]:
        s=f'{value:{width}.{places}f}'
        if len(s)==width and abs(float(s)-value)<1e-8:return s
    raise ValueError(f'Coordinate/spacing {value} not exactly representable in OWI width {width}')


def write_owi_header(f,basin_name,start,end):
    f.write(f'{("OWI "+basin_name)[:55]:55s}{start:%Y%m%d%H}     {end:%Y%m%d%H}\n')


def _snapshot_header(dt_obj,lats,lons):
    if len(lats)>9999 or len(lons)>9999:raise ValueError('Grid exceeds OWI i4 dimensions')
    return (f'iLat={len(lats):4d}iLong={len(lons):4d}DX={_fixed(lons[1]-lons[0],6)}'
            f'DY={_fixed(lats[1]-lats[0],6)}SWLat={_fixed(lats[0],8)}SWLon={_fixed(lons[0],8)}DT={dt_obj:%Y%m%d%H%M}\n')


def _write_values(f,field):
    values=np.asarray(field).ravel()
    for i in range(0,len(values),8):f.write(''.join(f'{v:10.4f}' for v in values[i:i+8])+'\n')


def write_owi_snapshot(f,dt_obj,lats,lons,field,values_per_line=8):
    if values_per_line!=8:raise ValueError('Native OWI format requires 8 values per line')
    f.write(_snapshot_header(dt_obj,lats,lons));_write_values(f,field)


def write_fort22_control(output_dir,start=None,end=None,n_snapshots=None):
    (Path(output_dir)/'fort.22').write_text('1\n0\n1.0\n')  # one overlay, no blank snaps, unit wind multiplier


def read_owi(filepath,components=1):
    """Read strict native fixed columns, including U and V under a single header."""
    times=[];fields=[];grid=None
    try:
        with open(filepath) as f:
            top=f.readline().rstrip('\n')
            start=pd.to_datetime(top[55:65],format='%Y%m%d%H');end=pd.to_datetime(top[70:80],format='%Y%m%d%H')
            while True:
                h=f.readline()
                if not h:break
                if not h.startswith('iLat='):raise ValueError('Expected OWI snapshot header')
                shape=(int(h[5:9]),int(h[15:19]));g=(*shape,float(h[22:28]),float(h[31:37]),float(h[43:51]),float(h[57:65]))
                if min(shape)<2 or not np.isfinite(g[2:]).all() or g[2]<=0 or g[3]<=0:raise ValueError('Invalid OWI grid: dimensions <2 or nonfinite/nonpositive spacing/corner')
                ne_lat=g[4]+(shape[0]-1)*g[3];ne_lon=g[5]+(shape[1]-1)*g[2]
                if not (-90<=g[4]<ne_lat<=90+1e-6 and -180<=g[5]<ne_lon<=180+1e-6):raise ValueError('OWI grid outside geographic bounds (lat -90..90, lon -180..180)')
                if grid is not None and g!=grid:raise ValueError('Changing OWI grids')
                grid=g;times.append(pd.to_datetime(h[68:80],format='%Y%m%d%H%M'));blocks=[]
                for _ in range(components):
                    vals=[];n=shape[0]*shape[1]
                    while len(vals)<n:
                        line=f.readline().rstrip('\n');want=min(8,n-len(vals))
                        if len(line)!=want*10:raise ValueError('Invalid OWI data record width/count')
                        vals.extend(float(line[j:j+10]) for j in range(0,len(line),10))
                    blocks.append(np.array(vals).reshape(shape))
                fields.append(blocks)
        if len(times)<2 or times[0].floor('h')!=start or times[-1].floor('h')!=end:raise ValueError('OWI header dates differ from data')
        gaps=np.diff(pd.DatetimeIndex(times).asi8)
        if np.any(gaps<=0) or np.any(gaps!=gaps[0]):raise ValueError('OWI cadence is not constant/increasing')
        a=np.array(fields)
        if not np.isfinite(a).all():raise ValueError('Nonfinite OWI data')
        return times,grid,a
    except (ValueError,IndexError,OverflowError) as exc:raise ValueError(f'{filepath}: invalid OWI: {exc}') from exc


def _read_owi_values(filepath):
    return read_owi(filepath,2 if Path(filepath).name=='fort.222' else 1)[2].ravel()


def validate_outputs(output_dir):
    p=Path(output_dir)
    if (p/'fort.22').read_text().split()!=['1','0','1.0']:raise ValueError('Invalid fort.22 control')
    t,g,pres=read_owi(p/'fort.221');tw,gw,wind=read_owi(p/'fort.222',2)
    if t!=tw or g!=gw:raise ValueError('Wind/pressure grid or timestamps differ')
    _check_fields(wind[:,0],wind[:,1],pres[:,0])


def _reserve(out,names):
    """Create every destination name with O_EXCL before staging; undo and fail if any already exists."""
    made=[]
    try:
        for name in names:
            fd=os.open(out/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o644);os.close(fd);made.append(out/name)
    except FileExistsError as exc:
        for path in made:path.unlink(missing_ok=True)
        raise ValueError(f'Output forcing exists or another conversion is writing {out}; choose a fresh output directory') from exc
    except BaseException:
        for path in made:path.unlink(missing_ok=True)
        raise
    return made


def process(args):
    domain=validate_inputs(args);step=getattr(args,'step_seconds',3600)
    if args.format=='csv':data=read_csv(args.input_dir,*domain,step,getattr(args,'wind_unit','m/s'),getattr(args,'pressure_unit','mb'))
    else:data=read_era5_nc(args.input_dir,*domain,step)
    times,lats,lons,u,v,p=data
    if not np.allclose([lats[1]-lats[0],lons[1]-lons[0]],args.resolution,rtol=0,atol=1e-8):raise ValueError('Resolution must equal both source grid spacings; resample explicitly upstream')
    _snapshot_header(times[0],lats,lons)  # validate exact coordinate serialization before writes
    out=Path(args.output_dir);names=['fort.22','fort.221','fort.222','forcing_provenance.json']
    if any((out/n).exists() for n in names):raise ValueError('Output forcing exists; choose a fresh output directory')
    sources=sorted(Path(args.input_dir).glob('*.csv' if args.format=='csv' else '*.nc'))
    provenance={'sources':[{'path':str(x.resolve()),'sha256':hashlib.sha256(x.read_bytes()).hexdigest()} for x in sources],
        'filled_values':0,'time_standard':'UTC','start':str(times[0]),'end_inclusive':str(times[-1]),'step_seconds':step,
        'units':{'wind':'m/s','pressure':'mb'},'input_units':{'wind':getattr(args,'wind_unit','m/s'),'pressure':getattr(args,'pressure_unit','mb')} if args.format=='csv' else 'NetCDF variable attributes',
        'grid_shape':[len(lats),len(lons)],'pressure_semantics':'CSV caller-supplied atmospheric pressure; ERA5 mean sea level only',
        'serialization':'OWI 8f10.4; absolute numeric rounding <= 0.00005; coordinates preserved',
        'native_requirement':('WTIMINC must equal step_seconds; fort.22 NWBS=0, so the FIRST snapshot is applied at the run time origin '
            '(NWS=+12: cold-start time, also on hot start; NWS=-12: hot-start time) whatever its DT stamp says; '
            'data must cover full run and grid strictly enclose mesh on N/E edges')}
    out.mkdir(parents=True,exist_ok=True)
    reserved=_reserve(out,names)  # exclusive create: a second conversion into the same folder fails here
    try:
        with tempfile.TemporaryDirectory(prefix='.owi-',dir=out.parent) as temp:
            stage=Path(temp)
            for name,arrays in [('fort.221',[p]),('fort.222',[u,v])]:
                with (stage/name).open('w') as f:
                    write_owi_header(f,'ADCIRC_Basin',times[0],times[-1])
                    for i,t in enumerate(times):
                        f.write(_snapshot_header(t,lats,lons))
                        for a in arrays:_write_values(f,a[i])
            write_fort22_control(stage);validate_outputs(stage)
            (stage/'forcing_provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')
            for name in names:os.replace(stage/name,out/name)
    except BaseException:
        for path in reserved:path.unlink(missing_ok=True)  # never leave empty or partial forcing behind
        raise
    print(f'Wrote {len(times)} snapshots; no filled values; WTIMINC={step} seconds')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for flag in ['input_dir','domain_sw','domain_ne','start_date','end_date','output_dir']:p.add_argument('--'+flag,required=True)
    p.add_argument('--format',choices=['csv','era5_nc'],required=True)
    p.add_argument('--resolution',type=float,default=.25,help='Source grid spacing in degrees; no implicit resampling')
    p.add_argument('--step_seconds',type=int,default=3600,help='Requested regular cadence; must equal native WTIMINC')
    p.add_argument('--wind_unit',choices=list(WIND_UNITS),default='m/s',help='CSV units only')
    p.add_argument('--pressure_unit',choices=list(PRESSURE_UNITS),default='mb',help='CSV units only')
    args=p.parse_args()
    try:process(args)
    except (ValueError,OSError,KeyError) as exc:p.exit(1,f'ERROR: {exc}\n')
if __name__=='__main__':main()
