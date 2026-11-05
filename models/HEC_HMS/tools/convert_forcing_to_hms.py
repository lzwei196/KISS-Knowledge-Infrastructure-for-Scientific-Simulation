#!/usr/bin/env python3
"""Convert complete daily CMFD weather and explicit PET to an HEC-HMS CSV.

No missing-value filling, magnitude-based unit guessing or automatic PET method
is used. --pet_csv must contain dated pet_mm values in mm/day from an identified
source/derivation. --temperature_mode unused omits T only for a model configured
without a temperature-dependent process. This converter does not run HEC-HMS.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import numpy as np
import pandas as pd


def _calendar(start_date, end_date):
    start,end=pd.Timestamp(start_date),pd.Timestamp(end_date)
    if any(pd.isna(x) or x.tz is not None or x!=x.normalize() for x in [start,end]) or start>end:
        raise ValueError('Expected start_date <= end_date as daily calendar dates')
    return pd.date_range(start,end,freq='D')


def _dates(values,label):
    dates=pd.DatetimeIndex(pd.to_datetime(values,errors='raise'))
    if dates.hasnans or dates.tz is not None:
        raise ValueError(f'{label}: invalid or timezone-bearing daily dates')
    # Daily CMFD timestamps may label the average at 10:30; retain their date.
    dates=dates.normalize()
    if dates.has_duplicates or not dates.is_monotonic_increasing:
        raise ValueError(f'{label}: daily dates must be unique and increasing')
    return dates


def _finite(values,label,minimum=None,maximum=None):
    arr=np.asarray(values,dtype=float)
    bad=~np.isfinite(arr)
    if minimum is not None:bad|=arr<minimum
    if maximum is not None:bad|=arr>maximum
    if bad.any():
        locations=np.argwhere(bad)[:5].tolist()
        raise ValueError(f'{label}: invalid/missing values at indices {locations}')
    return arr


def validate_inputs(args):
    _calendar(args.start_date,args.end_date)
    for path,kind in [(args.forcing_dir,'forcing directory'),(args.basin_shp,'basin geometry'),(args.pet_csv,'PET CSV')]:
        if not Path(path).exists():raise FileNotFoundError(f'{kind} not found: {path}')


def read_basin_mask(basin_shp,resolution=None):
    import geopandas as gpd
    gdf=gpd.read_file(basin_shp)
    if gdf.empty or gdf.crs is None or not gdf.geometry.is_valid.all() or gdf.geometry.is_empty.any():
        raise ValueError('Basin geometry must be nonempty and valid, with an explicit CRS')
    gdf=gdf.to_crs(4326)
    area=float(gdf.to_crs(6933).area.sum()/1e6)
    if not np.isfinite(area) or area<=0:raise ValueError('Invalid basin area')
    return gdf,gdf.total_bounds,area


def _coordinate(ds,names,standard_name,units):
    for name in names:
        if name in ds.coords and ds[name].ndim==1:
            coord=ds[name]
            declared=str(coord.attrs.get('units','')).strip().lower().replace(' ','')
            if name in ('x','y') and coord.attrs.get('standard_name')!=standard_name and declared not in units:
                continue
            # Selection and cos(latitude) weights assume degrees; never assume
            # an undeclared or non-degree (e.g. radian, projected) coordinate.
            if declared not in units:
                raise ValueError(f'{name}: coordinate units {coord.attrs.get("units")!r} are not declared {standard_name} degrees {sorted(units)}')
            values=_finite(coord.values,name)
            if len(values)<2 or not (np.all(np.diff(values)>0) or np.all(np.diff(values)<0)):
                raise ValueError(f'{name}: require a monotonic rectilinear geographic grid')
            return name
    raise ValueError(f'Missing one-dimensional geographic {standard_name} coordinate')


_DAY_FREQUENCIES={'day','1day','daily','1d','d'}


def _check_daily_support(ds,da,path):
    """Require each value to represent one whole calendar day.

    Declared time bounds must be midnight-aligned 24 h intervals on the labelled
    date. Without bounds, consecutive labels must be exactly 24 h apart (a single
    label needs a declared daily frequency). A declared time cell method must be
    a mean or sum. Partial-day support (e.g. one hourly mean per day) fails.
    """
    path=str(path);time=da['time']
    labels=pd.DatetimeIndex(pd.to_datetime(time.values,errors='raise'))
    methods=str(da.attrs.get('cell_methods',''))
    if 'time:' in methods:
        method=(methods.split('time:',1)[1].split() or [''])[0]
        if method not in ('mean','sum'):raise ValueError(f'{path}: time cell_methods {methods!r} is not a daily mean or sum')
    bounds_name=time.attrs.get('bounds') or time.encoding.get('bounds')
    if bounds_name:
        if bounds_name not in ds:raise ValueError(f'{path}: declared time bounds {bounds_name!r} are absent')
        bounds=np.asarray(ds[bounds_name].values)
        if bounds.shape!=(len(labels),2):raise ValueError(f'{path}: time bounds must have shape (time, 2)')
        start=pd.DatetimeIndex(pd.to_datetime(bounds[:,0],errors='raise'));end=pd.DatetimeIndex(pd.to_datetime(bounds[:,1],errors='raise'))
        bad=(end-start!=pd.Timedelta(days=1))|(start!=start.normalize())|(start!=labels.normalize())
        if bad.any():raise ValueError(f'{path}: time bounds do not cover whole labelled days; first bad interval {start[bad][0]} to {end[bad][0]}')
        return
    if len(labels)>1:
        steps=np.diff(labels.asi8)
        if (steps!=pd.Timedelta(days=1).value).any():raise ValueError(f'{path}: time step is not exactly one day and no daily time bounds are declared')
    elif str(ds.attrs.get('frequency','')).strip().lower() not in _DAY_FREQUENCIES:
        raise ValueError(f'{path}: one time value without daily time bounds or a daily frequency attribute')


def _check_valid_range(path,da,select,label):
    """Apply NetCDF valid_range/valid_min/valid_max to the selected values.

    Checked in the stored domain: raw packed integers when scale_factor/add_offset
    are present (CF packed-units rule), else values against limits cast to the
    stored float type, so declared endpoints are not rejected by rounding.
    """
    import xarray as xr
    attrs={**da.encoding,**da.attrs}
    low=high=None
    if 'valid_range' in attrs:
        rng=np.asarray(attrs['valid_range']).ravel()
        if rng.size!=2:raise ValueError(f'{label}: malformed valid_range {attrs["valid_range"]!r}')
        low,high=rng
    if 'valid_min' in attrs:low=np.asarray(attrs['valid_min']).ravel()[0]
    if 'valid_max' in attrs:high=np.asarray(attrs['valid_max']).ravel()[0]
    if low is None and high is None:return
    if 'scale_factor' in da.encoding or 'add_offset' in da.encoding:
        with xr.open_dataset(path,mask_and_scale=False) as raw:values=np.asarray(select(raw[da.name]))
        domain='packed'
    else:
        values=np.asarray(select(da));domain='stored'
        stored=np.dtype(da.encoding.get('dtype',values.dtype))
        if stored.kind=='f':
            low=None if low is None else np.asarray(low).astype(stored);high=None if high is None else np.asarray(high).astype(stored)
    bad=np.zeros(values.shape,dtype=bool)
    if low is not None:bad|=values<low
    if high is not None:bad|=values>high
    if bad.any():raise ValueError(f'{label}: values outside declared valid range [{low}, {high}] ({domain} units) at indices {np.argwhere(bad)[:5].tolist()}')


def read_cmfd_forcing(forcing_dir,bounds,start_date,end_date,*,basin_geometry=None,temperature_required=True):
    """Select complete daily source cells before an area-weighted basin average.

    Grid centers covered by the basin are active. Cell areas are proportional to
    cos(latitude) on a regular longitude/latitude grid. All active cells must be
    finite for every requested day; cells outside the basin are not required.
    With bounds only, the stated rectangle is the selection geometry.
    """
    import xarray as xr
    from shapely.geometry import box,Point
    calendar=_calendar(start_date,end_date)
    geometry=basin_geometry if basin_geometry is not None else box(*bounds)
    result={}
    for var in (['prec','temp'] if temperature_required else ['prec']):
        files=[]
        for year in sorted(set(calendar.year)):
            found=sorted(Path(forcing_dir).glob(f'{var}*{year}*.nc'))
            if not found:raise FileNotFoundError(f'{var}: no source NetCDF for {year} in {forcing_dir}')
            files.extend(found)
        parts=[];sources=[];unit=None
        for path in files:
            with xr.open_dataset(path) as ds:
                if var not in ds:raise ValueError(f'{path}: required variable {var} is absent')
                da=ds[var]
                current=da.attrs.get('units','')
                if not current or (unit is not None and current!=unit):raise ValueError(f'{path}: missing or inconsistent {var} units')
                unit=current
                lon=_coordinate(ds,['lon','longitude','x'],'longitude',{'degrees_east','degree_east','degrees_e','degree_e','degreese','degreee'})
                lat=_coordinate(ds,['lat','latitude','y'],'latitude',{'degrees_north','degree_north','degrees_n','degree_n','degreesn','degreen'})
                x,y=np.asarray(ds[lon].values),np.asarray(ds[lat].values)
                dx,dy=np.abs(np.diff(x)),np.abs(np.diff(y))
                if not np.allclose(dx,dx[0]) or not np.allclose(dy,dy[0]):raise ValueError(f'{path}: only regular geographic grids are supported')
                extent=box(x.min()-dx[0]/2,y.min()-dy[0]/2,x.max()+dx[0]/2,y.max()+dy[0]/2)
                if not extent.covers(geometry):raise ValueError(f'{path}: source grid does not cover the basin')
                xx,yy=np.meshgrid(x,y)
                mask=np.array([geometry.covers(Point(a,b)) for a,b in zip(xx.ravel(),yy.ravel())]).reshape(xx.shape)
                if not mask.any():raise ValueError(f'{path}: no source grid centers inside basin')
                _check_daily_support(ds,da,path)
                dates=_dates(da.time.values,str(path))
                selected=(dates>=calendar[0])&(dates<=calendar[-1])
                if not selected.any():continue
                if set(da.dims)!={'time',ds[lat].dims[0],ds[lon].dims[0]}:raise ValueError(f'{path}: unsupported data dimensions {da.dims}')
                select=lambda a:a.isel(time=np.flatnonzero(selected)).transpose('time',ds[lat].dims[0],ds[lon].dims[0]).values[:,mask]
                values=select(da)
                _finite(values,f'{path} {var} active cells, first date {dates[selected][0].date()}')
                _check_valid_range(path,da,select,f'{path} {var} active cells')
                # Validate physical values and declared units before averaging,
                # including negative sentinels that lack NetCDF fill metadata.
                convert_units({var:xr.DataArray(values,attrs={'units':unit})})
                weights=np.cos(np.deg2rad(yy[mask]))
                if not np.isfinite(weights).all() or (weights<=0).any():raise ValueError('Invalid geographic area weights')
                mean=np.average(values,axis=1,weights=weights)
                parts.append(xr.DataArray(mean,dims='time',coords={'time':dates[selected]},attrs={'units':unit}))
                sources.append(dict(path=str(path.resolve()),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),active_cells=int(mask.sum())))
        if not parts:raise ValueError(f'{var}: no requested daily values')
        combined=xr.concat(parts,dim='time')
        dates=_dates(combined.time.values,var)
        if not dates.equals(calendar):raise ValueError(f'{var}: source calendar must cover every requested date exactly; missing {calendar.difference(dates).strftime("%Y-%m-%d").tolist()[:10]}')
        combined.attrs.update(units=unit,sources=sources,spatial_method='cos(latitude)-weighted mean of basin-covered grid centers')
        result[var]=combined
    return result


def convert_units(data_dict):
    """Convert declared units only; small legitimate rain is never a rate guess."""
    converted={}
    for var,da in data_dict.items():
        if var not in ['prec','temp','srad']:continue
        unit=str(da.attrs.get('units','')).lower().replace(' ','').replace('**','').replace('^','')
        values=_finite(da.values,var)
        if var=='prec':
            _finite(values,var,minimum=0)
            if unit in ('kgm-2s-1','mm/s','mms-1'):values=values*86400
            elif unit not in ('mm/day','mmd-1','mmday-1','mm'):raise ValueError(f'prec: unsupported or absent daily units {unit!r}')
            converted['prec_mm']=values
        elif var=='temp':
            if unit in ('k','kelvin','degk'):values=values-273.15
            elif unit not in ('c','degc','celsius','degree_celsius','degrees_celsius'):raise ValueError(f'temp: unsupported or absent units {unit!r}')
            converted['temp_c']=_finite(values,var,minimum=-100,maximum=70)
        else:
            _finite(values,var,minimum=0)
            if unit in ('wm-2','w/m2'):values=values*.0864
            elif unit not in ('mjm-2d-1','mj/m2/day'):raise ValueError(f'srad: unsupported or absent units {unit!r}')
            converted['srad_mj']=values
    return converted


def load_pet_csv(path,start_date,end_date):
    df=pd.read_csv(path)
    if not {'date','pet_mm'}.issubset(df):raise ValueError(f'{path}: PET CSV requires date,pet_mm (mm/day)')
    dates=_dates(df.date,str(path));calendar=_calendar(start_date,end_date)
    series=pd.Series(pd.to_numeric(df.pet_mm,errors='raise').to_numpy(),index=dates)
    selected=series.reindex(calendar)
    _finite(selected.values,f'{path}: pet_mm on requested dates',minimum=0)
    return selected


def build_forcing_csv(data_dict,converted,pet,start_date,end_date,*,temperature_required=True):
    """Align arrays to their actual source dates; never truncate, pad or relabel."""
    calendar=_calendar(start_date,end_date);out=pd.DataFrame(index=calendar);out.index.name='date'
    fields=[('prec','prec_mm','precip_mm',0,None)]
    if temperature_required:fields.append(('temp','temp_c','temp_c',-100,70))
    for source,key,column,low,high in fields:
        if source not in data_dict or key not in converted:raise ValueError(f'Missing required {source}/{key}')
        dates=_dates(data_dict[source].time.values,source);values=np.asarray(converted[key],dtype=float)
        if values.shape!=(len(dates),):raise ValueError(f'{key}: array length does not match source dates')
        selected=pd.Series(values,index=dates).reindex(calendar)
        _finite(selected.values,f'{key}: requested dates {calendar[0].date()} to {calendar[-1].date()}',low,high)
        out[column]=selected
    if not isinstance(pet,pd.Series):raise ValueError('PET must be an explicit dated pandas Series in mm/day (use --pet_csv)')
    pet=pd.Series(pet.to_numpy(),index=_dates(pet.index,'PET'))
    selected=pet.reindex(calendar);_finite(selected.values,'pet_mm on requested dates',minimum=0);out['pet_mm']=selected
    return out


def validate_outputs(df,output_dir=None):
    for name in ['precip_mm','pet_mm']:
        if name not in df:raise ValueError(f'Missing output column {name}')
        _finite(df[name],name,minimum=0)
    if 'temp_c' in df:_finite(df.temp_c,'temp_c',-100,70)
    return []


def process(args):
    calendar=_calendar(args.start_date,args.end_date)
    pet=load_pet_csv(args.pet_csv,args.start_date,args.end_date)
    gdf,bounds,area=read_basin_mask(args.basin_shp)
    required=getattr(args,'temperature_mode','required')=='required'
    data=read_cmfd_forcing(args.forcing_dir,bounds,args.start_date,args.end_date,basin_geometry=gdf.geometry.union_all(),temperature_required=required)
    df=build_forcing_csv(data,convert_units(data),pet,args.start_date,args.end_date,temperature_required=required)
    validate_outputs(df)
    content=df.to_csv(float_format='%.17g')
    info=dict(area_km2=area,bounds=bounds.tolist(),start_date=str(calendar[0].date()),end_date=str(calendar[-1].date()),n_days=len(df),temperature_mode='required' if required else 'unused',fill_count=0,
              pet_source=str(Path(args.pet_csv).resolve()),pet_source_sha256=hashlib.sha256(Path(args.pet_csv).read_bytes()).hexdigest(),pet_method='provided daily pet_mm; no automatic method selection',
              forcing_sources={key:da.attrs for key,da in data.items()},output_sha256=hashlib.sha256(content.encode()).hexdigest())
    out=Path(args.output_dir);out.mkdir(parents=True,exist_ok=True)
    (out/'basin_avg_forcing.csv').write_text(content)
    (out/'basin_info.json').write_text(json.dumps(info,indent=2,allow_nan=False)+'\n')
    result=dict(status='success',output_csv=str(out/'basin_avg_forcing.csv'),n_days=len(df),area_km2=area,fill_count=0)
    print(json.dumps(result,indent=2));return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--forcing_dir',required=True)
    parser.add_argument('--basin_shp',required=True)
    parser.add_argument('--start_date',required=True)
    parser.add_argument('--end_date',required=True)
    parser.add_argument('--pet_csv',required=True,help='Explicit daily date,pet_mm file; retain its source/derivation')
    parser.add_argument('--temperature_mode',choices=['required','unused'],default='required',help='unused is only for a native model with no temperature-dependent process')
    parser.add_argument('--output_dir',required=True)
    args=parser.parse_args()
    try:
        validate_inputs(args);process(args)
    except (ValueError,OSError,KeyError) as exc:
        print(f'ERROR: {exc}',file=sys.stderr);return 2
    return 0


if __name__=='__main__':raise SystemExit(main())
