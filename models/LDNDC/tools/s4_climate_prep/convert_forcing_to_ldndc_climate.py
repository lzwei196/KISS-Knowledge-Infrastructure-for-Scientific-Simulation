#!/usr/bin/env python3
"""Complete source weather -> native LDNDC daily %data climate.

FLUXNET requires complete HH/HR intervals: actual daily extrema come from all
substeps, never daytime/nighttime means or assumed temperature ranges. An input
DD path resolves to a sibling HH/HR file when available; otherwise it fails.
Shared daily adapters are checked on return; their upstream raw gaps are not
certified here. Full calendar years are required for annual climate attributes.
Site elevation (m) is required: it is written to the climate.txt %attributes
block, and the LDNDC binary reads it (the climate reader has get_elevation; the
same binary carries an air-pressure synthesizer). There is no 0 m default.
Daily temperatures must already be Celsius (-100..70); values out of that
range stop the tool. Units are never guessed from magnitude.
"""
import hashlib,json,logging,os,sys,tempfile
from pathlib import Path
import numpy as np
import pandas as pd
FORCING_SOURCE='';FORCING_PATH='';LAT=0.;LON=0.;START_DATE='';END_DATE='';OUTPUT_PATH='';ELEVATION=None
PROVENANCE={}
logger=logging.getLogger(__name__)


def _period():
    start=pd.Timestamp(START_DATE);end=pd.Timestamp(END_DATE)
    if pd.isna(start) or pd.isna(end) or start>end or start.tzinfo or end.tzinfo:
        raise ValueError('Require valid increasing naive source-local calendar dates')
    if start!=pd.Timestamp(start.year,1,1) or end!=pd.Timestamp(end.year,12,31):
        raise ValueError('Full calendar years Jan 1 through Dec 31 required for climate attributes; no relabeling partial data as January')
    return pd.date_range(start,end,freq='D')


def _elevation():
    if ELEVATION is None or str(ELEVATION).strip()=='':
        raise ValueError('Site elevation_m is required (8th argument); no 0 m default. Give the real site elevation in metres')
    try:value=float(ELEVATION)
    except ValueError:raise ValueError(f'Site elevation_m must be a number in metres, got {ELEVATION!r}') from None
    if not np.isfinite(value):raise ValueError('Site elevation_m must be finite')
    return value


def validate_inputs():
    if FORCING_SOURCE not in ('fluxnet','fluxnet_fullset','cmfd','mswx','nasa_power'):raise ValueError('Unsupported forcing source')
    if not Path(FORCING_PATH).exists() or not OUTPUT_PATH:raise ValueError('Source path and output path required')
    _elevation()
    if not np.isfinite([LAT,LON]).all() or not -90<=LAT<=90 or not -180<=LON<=180:raise ValueError('Invalid site coordinates/elevation')
    _period()


def _load_via_ki_tools_common(source,lat,lon,start_year,end_year,forcing_dir):
    models_common=Path('KISSPATH_KI_TOOLS_COMMON')
    if models_common.is_dir():sys.path.insert(0,str(models_common))
    from ki_tools_common.load_forcing import load_daily_forcing
    return load_daily_forcing(source,lat,lon,start_year,end_year,forcing_dir=forcing_dir)


def _resolve_substep_path(path):
    """Map a FLUXNET daily (DD) file to its HH/HR sibling.

    The resolution is one underscore token in the name, either at the end
    (``..._DD.csv``) or inside an original FLUXNET2015 name such as
    ``FLX_CN-Din_FLUXNET2015_FULLSET_DD_2003-2005_1-4.csv``. Only that token is
    swapped, so site, product, years and version stay the same.
    """
    path=Path(path)
    if path.suffix.lower()!='.csv':return path
    tokens=path.stem.split('_')
    hits=[i for i,t in enumerate(tokens) if t=='DD']
    if not hits:return path
    if len(hits)!=1:raise ValueError(f'Ambiguous FLUXNET resolution token in {path.name}; supply the HH/HR file directly')
    i=hits[0]
    candidates=[path.with_name('_'.join(tokens[:i]+[res]+tokens[i+1:])+path.suffix) for res in ('HH','HR')]
    found=[p for p in candidates if p.exists()]
    if len(found)!=1:raise ValueError('Daily day/night averages are not extrema; supply an unambiguous complete FLUXNET HH/HR source (looked for '+', '.join(p.name for p in candidates)+')')
    return found[0]


def _fluxnet(forcing_file,fullset):
    dates=_period();path=_resolve_substep_path(forcing_file)
    fields=['TA_F_MDS','P_F','SW_IN_F','WS_F'] if fullset else ['TA_ERA','P_ERA','SW_IN_ERA','WS_ERA']
    required=['TIMESTAMP_START','TIMESTAMP_END',*fields]
    columns=pd.read_csv(path,nrows=0).columns
    if not set(required)<=set(columns):raise ValueError('Require HH/HR timestamp bounds and '+','.join(fields)+'; no daily-average/extrema substitution')
    df=pd.read_csv(path,usecols=required,dtype={'TIMESTAMP_START':str,'TIMESTAMP_END':str})
    start=pd.to_datetime(df.TIMESTAMP_START,format='%Y%m%d%H%M',errors='raise');end=pd.to_datetime(df.TIMESTAMP_END,format='%Y%m%d%H%M',errors='raise')
    selected=(start>=dates[0])&(start<dates[-1]+pd.Timedelta(days=1));df=df.loc[selected].copy();start=pd.DatetimeIndex(start[selected]);end=pd.DatetimeIndex(end[selected])
    if len(start)<2 or start.has_duplicates or start.hasnans or end.hasnans:raise ValueError('Empty/duplicate/missing source intervals')
    step=end[0]-start[0]
    if step not in (pd.Timedelta(minutes=30),pd.Timedelta(hours=1)):raise ValueError('FLUXNET source interval must be 30 or 60 minutes')
    expected=pd.date_range(dates[0],dates[-1]+pd.Timedelta(days=1),freq=step,inclusive='left')
    if not start.equals(expected) or not (end==start+step).all():raise ValueError('Incomplete, unordered or inconsistent HH/HR intervals; every substep required')
    a=df[fields].to_numpy(dtype=float)
    if not np.isfinite(a).all() or np.any(a==-9999):raise ValueError('FLUXNET missing/nonfinite source values; no local filling')
    if np.any((a[:,0]<-100)|(a[:,0]>70)) or np.any(a[:,1:]<0) or np.any(a[:,3]>120):raise ValueError('Invalid FLUXNET temperature/rain/radiation/wind; no clipping')
    df.index=start
    daily=pd.DataFrame(index=dates)
    daily['prec']=df[fields[1]].resample('D').sum()
    daily['tavg']=df[fields[0]].resample('D').mean()
    daily['tmax']=df[fields[0]].resample('D').max()
    daily['tmin']=df[fields[0]].resample('D').min()
    daily['grad']=df[fields[2]].resample('D').mean()
    daily['wind']=df[fields[3]].resample('D').mean()
    PROVENANCE.update(source_path=str(path.resolve()),source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        source_records=len(df),interval_minutes=step.total_seconds()/60,columns=fields,
        units={'TA':'degC','P':'mm/interval','SW':'W/m2','WS':'m/s'},time_standard='FLUXNET local standard time',
        source_product='Provider-filled FULLSET values retained without additional filling' if fullset else 'ERA-I reanalysis product',
        aggregation='P sum; temperature mean/max/min from every interval; radiation and wind mean')
    return daily


def _load_fluxnet_fullset(forcing_file):return _fluxnet(forcing_file,True)
def _load_fluxnet_erai(forcing_file):return _fluxnet(forcing_file,False)


def _validate_array(a,n):
    if a.shape!=(n,6) or not np.isfinite(a).all():raise ValueError('Missing/nonfinite daily weather or wrong shape')
    if np.any(a[:,[0,4,5]]<0) or np.any(a[:,5]>120):raise ValueError('Negative rain/radiation/wind or invalid wind')
    if np.any((a[:,1:4]<-100)|(a[:,1:4]>70)):raise ValueError('Daily temperatures must be Celsius, -100..70; no magnitude-based unit conversion')
    if np.any(a[:,3]>a[:,1]) or np.any(a[:,1]>a[:,2]):raise ValueError('Require tmin <= tavg <= tmax')


def _collect_daily_arrays(start_year,end_year):
    dates=_period()
    if (start_year,end_year)!=(dates[0].year,dates[-1].year):raise ValueError('Year arguments disagree with requested period')
    PROVENANCE.clear()
    if FORCING_SOURCE in ('fluxnet','fluxnet_fullset'):
        daily=_load_fluxnet_fullset(FORCING_PATH) if FORCING_SOURCE=='fluxnet_fullset' else _load_fluxnet_erai(FORCING_PATH)
        a=daily[['prec','tavg','tmax','tmin','grad','wind']].to_numpy()
    else:
        d=_load_via_ki_tools_common(FORCING_SOURCE,LAT,LON,start_year,end_year,FORCING_PATH)
        required=['dates','precip_mm','temp_mean_c','temp_max_c','temp_min_c','srad_wm2','wind_ms']
        if not set(required)<=set(d):raise ValueError('Shared adapter must supply explicit dates and all six weather fields')
        if not pd.DatetimeIndex(d['dates']).equals(dates):raise ValueError('Shared daily calendar incomplete, duplicated or unordered')
        arrays=[np.asarray(d[k],float) for k in required[1:]]
        if any(x.shape!=(len(dates),) for x in arrays):raise ValueError('Daily array length differs from complete calendar')
        a=np.column_stack(arrays)
        PROVENANCE.update(source_path=str(Path(FORCING_PATH).resolve()),source_product=FORCING_SOURCE,
            upstream_boundary='Shared daily values validated; raw substep gap-filling and extrema provenance require independent audit')
    _validate_array(a,len(dates))
    return len(dates),*[a[:,i] for i in range(6)]


def process():
    dates=_period()
    elevation=_elevation()
    if not np.isfinite([LAT,LON]).all():raise ValueError('Invalid metadata')
    n,*columns=_collect_daily_arrays(dates[0].year,dates[-1].year);a=np.column_stack(columns)
    annual_precip=float(a[:,0].sum()/(dates[-1].year-dates[0].year+1))
    monthly=pd.Series(a[:,1],index=dates).groupby(dates.month).mean()
    amp=float((monthly.max()-monthly.min())/2)
    attrs={'elevation':elevation,'latitude':LAT,'longitude':LON,'annual precipitation':annual_precip,'temperature average':float(a[:,1].mean()),'temperature amplitude':amp}
    header=f'%global\n\ttime = "{dates[0]:%Y-%m-%d}/1"\n\n%climate\n\tid = 0\n\n%attributes\n'
    header+=''.join(f'\t{k} = "{v:.17g}"\n' for k,v in attrs.items())
    header+='\n%data\nprec\ttavg\ttmax\ttmin\tgrad\twind\n'
    output=Path(OUTPUT_PATH);output.parent.mkdir(parents=True,exist_ok=True)
    sidecar=Path(str(output)+'.provenance.json')
    staged=[]
    try:
        with tempfile.NamedTemporaryFile(mode='w',dir=output.parent,prefix='.climate-',delete=False) as f:
            temp=Path(f.name);staged.append(temp);f.write(header);np.savetxt(f,a,fmt='%.17g',delimiter='\t')
        validate_outputs(temp,n,annual_precip)
        PROVENANCE.update(start=str(dates[0].date()),end=str(dates[-1].date()),days=n,locally_filled_values=0,
            daily_extrema='Actual complete substep extrema for FLUXNET; declared daily extrema for shared adapters',
            output_sha256=hashlib.sha256(temp.read_bytes()).hexdigest())
        with tempfile.NamedTemporaryFile(mode='w',dir=output.parent,prefix='.climate-prov-',delete=False) as f:
            ptemp=Path(f.name);staged.append(ptemp);f.write(json.dumps(PROVENANCE,indent=2)+'\n')
        _publish_pair([(temp,output),(ptemp,sidecar)])
    finally:
        for p in staged:
            if p.exists():p.unlink()
    return str(output),n,annual_precip


def _publish_pair(pairs):
    """Move staged files into place as one unit.

    Before anything is replaced, every existing destination is copied to a
    hidden backup in the same folder. If any step fails, all destinations are
    put back as they were (or removed if they did not exist), then the error is
    raised. So a failed run never leaves new climate with old provenance.
    If a restore itself fails, that backup file is KEPT (never deleted) and
    its path is given in the error so the old file can be put back by hand.
    """
    import shutil
    backups=[];keep=set()
    try:
        for _,dest in pairs:
            if dest.exists() or dest.is_symlink():
                if not dest.is_file():raise OSError(f'Destination is not a regular file: {dest}')
                fd,b=tempfile.mkstemp(dir=dest.parent,prefix='.climate-bak-');os.close(fd);b=Path(b)
                backups.append((dest,b));shutil.copy2(dest,b)
            else:backups.append((dest,None))
        done=[]
        try:
            for src,dest in pairs:
                os.replace(src,dest);done.append(dest)
        except BaseException:
            restore_errors=[]
            for dest,b in backups:
                try:
                    if b is not None:os.replace(b,dest)
                    elif dest in done and dest.exists():dest.unlink()
                except OSError as e:
                    if b is not None:
                        keep.add(b);restore_errors.append(f'{dest}: {e}; previous file kept at {b}')
                    else:restore_errors.append(f'{dest}: {e}; this new file has no matching pair, remove it')
            if restore_errors:raise OSError('Publish failed AND restore failed; fix by hand: '+'; '.join(restore_errors))
            raise
    finally:
        for _,b in backups:
            if b is not None and b not in keep and b.exists():b.unlink()


def validate_outputs(output_path,ndays,annual_precip):
    import io
    content=Path(output_path).read_text()
    if content.count('%data\n')!=1:raise ValueError('Missing/duplicate native %data block')
    body=content.split('%data\n')[1].splitlines()
    if not body or body[0].split()!=['prec','tavg','tmax','tmin','grad','wind']:raise ValueError('Invalid native columns')
    a=np.loadtxt(io.StringIO('\n'.join(body[1:])),ndmin=2);_validate_array(a,ndays)
    if not np.isfinite(annual_precip) or annual_precip<0:raise ValueError('Invalid annual precipitation')


def main():
    global FORCING_SOURCE,FORCING_PATH,LAT,LON,START_DATE,END_DATE,OUTPUT_PATH,ELEVATION
    if len(sys.argv)!=9:raise ValueError('Usage: source path lat lon YYYY-01-01 YYYY-12-31 output elevation_m (elevation is required; no 0 m default)')
    FORCING_SOURCE,FORCING_PATH=sys.argv[1:3];LAT,LON=map(float,sys.argv[3:5]);START_DATE,END_DATE,OUTPUT_PATH=sys.argv[5:8]
    ELEVATION=sys.argv[8]
    validate_inputs();path,n,p=process();print(json.dumps({'status':'success','climate_txt':path,'n_days':n,'annual_precip_mm':p}))
if __name__=='__main__':
    try:main()
    except (ValueError,OSError,KeyError) as exc:sys.exit(f'ERROR: {exc}')
