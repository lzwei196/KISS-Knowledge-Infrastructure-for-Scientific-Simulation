#!/usr/bin/env python3
"""Convert complete source weather to TOPMODEL per-step depths in metres.

Hargreaves requires actual daily Tmin/Tmax/Tmean and latitude/date-derived Ra.
Missing rain, temperatures or derived PET fail before output. Header dt is 1.0
for the NOAA-OWP BMI row-index convention; physical dt is recorded separately.
"""

import os
import sys
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from datetime import datetime, timedelta

def validate_inputs(forcing_dir, start_date, end_date, shapefile):
    """Validate that the forcing root and shapefile exist.

    Variable/file discovery is delegated to ki_tools_common.load_forcing, which
    knows each source's on-disk layout (CMFD subdirs, MSWX, NASA-POWER), so we
    no longer guess filenames here.
    """
    errors = []

    if forcing_dir and not os.path.isdir(forcing_dir):
        errors.append(f"Forcing directory not found: {forcing_dir}")

    if shapefile and not os.path.exists(shapefile):
        errors.append(f"Basin shapefile not found: {shapefile}")

    try:
        start=datetime.strptime(start_date,'%Y-%m-%d')
        end=datetime.strptime(end_date,'%Y-%m-%d')
        if start>end:errors.append('start_date must not be after end_date')
    except ValueError as exc:errors.append(str(exc))
    return errors


def _required(values,name,n=None,minimum=None,maximum=None):
    arr=np.asarray(values,dtype=float)
    if arr.ndim!=1 or not len(arr) or (n is not None and len(arr)!=n):
        raise ValueError(f'{name}: require {n if n is not None else "a nonempty array of"} daily values')
    bad=~np.isfinite(arr)
    if minimum is not None:bad|=arr<minimum
    if maximum is not None:bad|=arr>maximum
    if bad.any():raise ValueError(f'{name}: invalid/missing values at daily indices {np.flatnonzero(bad)[:10].tolist()}')
    return arr


def compute_pet_hargreaves(tmin_C, tmax_C, tmean_C, lat_deg, doy):
    """
    Compute PET using Hargreaves method.

    Returns PET in mm/day.
    """
    tmean_C=_required(tmean_C,'Tmean',minimum=-100,maximum=70)
    tmin_C=_required(tmin_C,'Tmin',len(tmean_C),-100,70)
    tmax_C=_required(tmax_C,'Tmax',len(tmean_C),-100,70)
    doy=_required(doy,'day of year',len(tmean_C),1,366)
    if not np.isfinite(lat_deg) or not -90<=lat_deg<=90:raise ValueError('Latitude must be finite and within [-90,90]')
    if ((tmin_C>tmean_C)|(tmean_C>tmax_C)).any():raise ValueError('Require Tmin <= Tmean <= Tmax on every day')
    # FAO-56 extraterrestrial radiation, including polar day/night.
    lat_rad = np.radians(lat_deg)
    dr = 1 + 0.033 * np.cos(2 * np.pi * doy / 365)
    delta = 0.409 * np.sin(2 * np.pi * doy / 365 - 1.39)
    ws = np.arccos(np.clip(-np.tan(lat_rad) * np.tan(delta), -1, 1))

    Gsc = 0.0820  # solar constant MJ/m²/min
    Ra_MJ = (24 * 60 / np.pi) * Gsc * dr * (
        ws * np.sin(lat_rad) * np.sin(delta) +
        np.cos(lat_rad) * np.cos(delta) * np.sin(ws)
    )
    Ra_MJ = np.maximum(Ra_MJ, 0)

    # Hargreaves (FAO-56) requires Ra in EQUIVALENT EVAPORATION (mm/day), not in
    # MJ/m²/day. Convert with the latent-heat factor 0.408 (= 1/2.45 MJ/kg).
    # Omitting this inflates PET by ~2.45x (e.g. ~2500 mm/yr instead of the
    # realistic ~1000 mm/yr for the Huai basin), which silently dries the model
    # and suppresses runoff.
    Ra_mm = Ra_MJ * 0.408

    # Hargreaves equation
    trange = tmax_C - tmin_C
    pet = 0.0023 * (tmean_C + 17.8) * np.sqrt(trange) * Ra_mm
    pet = np.maximum(pet, 0)

    return pet


def _declared_step_seconds(attrs,file):
    """Native CMFD cadence as DECLARED by the source, never inferred from the
    timestamps that happen to be present (a regularly thinned series would
    otherwise pass as complete at a coarser step).

    CMFD V0200 declares it in three places, e.g. for the 3-hourly 0.1 deg set:
      file name  prec_CMFD_V0200_B-01_03hr_010deg_198001.nc
      title      '3-hourly precipitation from the China Meteorological Forcing Dataset'
      description '... Category: B-01: 03hr, 0.10deg)'
    Every declaration found must agree; none found is an error.
    """
    import re
    found=set()
    m=re.search(r'_(\d+)hr_',Path(file).name)
    if m:found.add(int(m.group(1))*3600)
    m=re.search(r'(\d+)-hourly',str(attrs.get('title','')),re.I)
    if m:found.add(int(m.group(1))*3600)
    m=re.search(r'Category:[^:]*:\s*(\d+)hr',str(attrs.get('description','')))
    if m:found.add(int(m.group(1))*3600)
    if not found:raise ValueError(f'{file}: source does not declare its native time step (file name/title/description); cannot check completeness')
    if len(found)!=1:raise ValueError(f'{file}: conflicting declared native time steps {sorted(found)} s')
    step=found.pop()
    if not 0<step<86400 or 86400%step:raise ValueError(f'{file}: declared step {step} s is not a subdaily divisor of one day')
    return step


def _read_cmfd_point(forcing_dir,lat,lon,start_date,end_date):
    """Read original P/T samples at one source cell without daily NaN reduction.

    sources['step_seconds'] is the native step declared by every file read.
    """
    import pandas as pd
    import xarray as xr
    start,end=pd.Timestamp(start_date),pd.Timestamp(end_date)+pd.Timedelta(days=1)
    output={};sources={};declared=set()
    for var,subdir in [('prec','Prec'),('temp','Temp')]:
        parts=[];paths=[]
        for year in range(start.year,pd.Timestamp(end_date).year+1):
            files=sorted(Path(forcing_dir).glob(f'{var}*{year}*.nc'))
            if not files:files=sorted((Path(forcing_dir)/subdir).glob(f'{var}*{year}*.nc'))
            if not files:raise FileNotFoundError(f'CMFD {var}: missing source files for {year}')
            for file in files:
                with xr.open_dataset(file) as ds:
                    if var not in ds:raise ValueError(f'{file}: missing {var}')
                    unit=ds[var].attrs.get('units','').replace(' ','').lower()
                    expected=('kgm-2s-1','mm/s') if var=='prec' else ('k','kelvin')
                    if unit not in expected:raise ValueError(f'{file}: unsupported or absent CMFD {var} units {unit!r}')
                    lat_name=next((n for n in ['lat','latitude','y'] if n in ds.coords),None)
                    lon_name=next((n for n in ['lon','longitude','x'] if n in ds.coords),None)
                    if lat_name is None or lon_name is None:raise ValueError(f'{file}: missing geographic coordinates')
                    y,x=ds[lat_name],ds[lon_name]
                    if y.ndim!=1 or x.ndim!=1:raise ValueError('Expected rectilinear geographic CMFD grid')
                    if not (float(y.min())<=lat<=float(y.max()) and float(x.min())<=lon<=float(x.max())):
                        raise ValueError(f'{file}: representative point is outside source grid centers')
                    declared.add(_declared_step_seconds(ds.attrs,file))
                    dates=pd.DatetimeIndex(ds.time.values)
                    chosen=np.flatnonzero((dates>=start)&(dates<end))
                    if not len(chosen):continue
                    values=ds[var].isel({y.dims[0]:int(np.abs(y.values-lat).argmin()),x.dims[0]:int(np.abs(x.values-lon).argmin()),'time':chosen}).values
                    _required(values,f'{file}: {var}',len(chosen),minimum=0 if var=='prec' else 173.15,maximum=None if var=='prec' else 343.15)
                    parts.append(pd.Series(values,index=dates[chosen]));paths.append(str(file.resolve()))
        if not parts:raise ValueError(f'No requested {var} samples')
        joined=pd.concat(parts)
        if joined.index.hasnans or joined.index.has_duplicates or not joined.index.is_monotonic_increasing:raise ValueError(f'{var}: duplicate/invalid/unordered source dates')
        output[var]=joined;sources[var]=paths
    if not output['prec'].index.equals(output['temp'].index):raise ValueError('CMFD precipitation and temperature timestamps differ')
    if len(declared)!=1:raise ValueError(f'CMFD files declare different native time steps: {sorted(declared)} s')
    sources['step_seconds']=float(declared.pop())
    return output,sources


def extract_basin_mean_forcing(forcing_dir,shapefile,start_date,end_date,lat_center=None,lon_center=None,source='cmfd'):
    """Strict source route: native subdaily CMFD at the supplied representative point.

    Daily-mean-only temperature cannot supply Hargreaves extrema. Legacy shared
    daily adapters discard missing substeps or substitute extrema; those routes
    are rejected until they expose the original source samples/quality metadata.
    """
    import pandas as pd
    if source!='cmfd':raise ValueError('This strict converter supports native subdaily CMFD only; other source adapters require a raw-data audit before use')
    start,end=pd.Timestamp(start_date),pd.Timestamp(end_date)
    if pd.isna(start) or pd.isna(end) or start>end or start!=start.normalize() or end!=end.normalize():raise ValueError('Invalid daily period')
    if lat_center is None or lon_center is None or not np.isfinite([lat_center,lon_center]).all() or not (-90<=lat_center<=90 and -180<=lon_center<=180):raise ValueError('Supply valid geographic representative latitude/longitude')
    raw,sources=_read_cmfd_point(forcing_dir,lat_center,lon_center,start_date,end_date)
    dates=raw['temp'].index
    if dates.hasnans or dates.has_duplicates or not dates.is_monotonic_increasing or not dates.equals(raw['prec'].index):raise ValueError('Source sample dates must be valid, ordered and aligned')
    # Completeness is checked against the source's DECLARED native step, not a
    # step guessed from the surviving timestamps: dropping every other 3-hourly
    # sample must fail, not pass as a "complete" 6-hourly series.
    step=sources.get('step_seconds') if isinstance(sources,dict) else None
    if step is None:raise ValueError('Source native time step was not declared; cannot check that every substep is present')
    step=float(step)
    if not 0<step<86400 or not np.isclose(86400/step,round(86400/step)):raise ValueError('Hargreaves requires subdaily temperature samples; daily means are not extrema')
    differences=np.diff(dates.to_numpy(dtype='datetime64[s]').astype(np.int64))
    if not len(differences) or not np.all(differences==step):raise ValueError(f'Missing or irregular source substeps (declared native step {step:g} s)')
    nper=int(round(86400/step));requested=pd.date_range(start,end,freq='D')
    groups=dates.normalize()
    if not pd.DatetimeIndex(groups.unique()).equals(requested) or not (pd.Series(1,index=groups).groupby(level=0).sum()==nper).all():raise ValueError('Every requested day must have all source substeps')
    temp=_required(raw['temp'].to_numpy(),'CMFD temperature',len(dates),173.15,343.15)-273.15
    rain=_required(raw['prec'].to_numpy(),'CMFD precipitation rate',len(dates),minimum=0)
    temperature=pd.Series(temp,index=groups).groupby(level=0)
    return dict(prec_mm_day=pd.Series(rain*step,index=groups).groupby(level=0).sum().to_numpy(),
                temp_K=temperature.mean().to_numpy()+273.15,tmin_C=temperature.min().to_numpy(),tmax_C=temperature.max().to_numpy(),
                ndays=len(requested),start_date=str(start.date()),dates=requested.strftime('%Y-%m-%d').tolist(),
                source=dict(kind='cmfd',files={k:v for k,v in sources.items() if k!='step_seconds'},latitude=lat_center,longitude=lon_center,spatial_method='nearest source grid cell',source_step_seconds=step,source_step_basis='declared by source files',temperature_extrema='min/max of complete original subdaily samples'))


def load_obs_qmhr(obs_file,start_date,ndays,basin_area_km2,seconds_per_day=86400.0):
    """Observed Q (m3/s) → daily runoff depth (m); supplied data must be complete.

    With no observation file, zeros are native-format placeholders only and may
    not be scored as observations. The writer records that mode in provenance.
    """
    import pandas as pd
    if obs_file is None:return np.zeros(ndays)
    if not Path(obs_file).is_file():raise FileNotFoundError(f'Observation file not found: {obs_file}')
    if basin_area_km2 is None or not np.isfinite(basin_area_km2) or basin_area_km2<=0:
        raise ValueError('Observed discharge conversion requires a finite positive basin area')
    if not np.isfinite(seconds_per_day) or seconds_per_day<=0:raise ValueError('Invalid seconds_per_day')
    raw=Path(obs_file).read_bytes()
    for encoding in ('utf-8','gbk','gb18030'):
        try:
            text=raw.decode(encoding);break
        except UnicodeDecodeError:continue
    else:raise ValueError(f'Cannot decode observations: {obs_file}')
    import io
    df=pd.read_csv(io.StringIO(text),sep='\t')
    if not {'dates','Q'}.issubset(df):raise ValueError('Observation file requires dates and Q columns')
    dates=pd.DatetimeIndex(pd.to_datetime(df.dates,format='mixed',errors='raise'))
    if dates.hasnans or dates.tz is not None or not (dates==dates.normalize()).all() or dates.has_duplicates or not dates.is_monotonic_increasing:
        raise ValueError('Observation dates must be unique, ordered daily dates')
    requested=pd.date_range(start_date,periods=ndays,freq='D')
    q=pd.Series(pd.to_numeric(df.Q,errors='raise').to_numpy(),index=dates).reindex(requested)
    values=_required(q.to_numpy(),f'Observed Q ({start_date}, {ndays} days)',ndays,minimum=0)
    return values*seconds_per_day/(basin_area_km2*1e6)


def convert_to_topmodel_inputs(forcing_data, dt_hours, lat_center,
                                obs_file=None, basin_area_km2=None,
                                output_file='inputs.dat'):
    """Write validated per-step rain/PET/Q depths and a provenance sidecar."""
    ndays=forcing_data['ndays']
    if not isinstance(ndays,(int,np.integer)) or isinstance(ndays,bool) or ndays<=0:raise ValueError('ndays must be a positive integer')
    if not np.isfinite(dt_hours) or dt_hours<=0 or dt_hours>24 or not np.isclose(24/dt_hours,round(24/dt_hours)):
        raise ValueError('dt_hours must divide 24 into an integer number of steps')
    steps_per_day=int(round(24/dt_hours));nstep=ndays*steps_per_day
    prec_mm_day=_required(forcing_data.get('prec_mm_day'),'precipitation',ndays,minimum=0)
    temp_K=_required(forcing_data.get('temp_K'),'temperature K',ndays,173.15,343.15)
    temp_C=temp_K-273.15
    tmin_C=_required(forcing_data.get('tmin_C'),'Tmin',ndays,-100,70)
    tmax_C=_required(forcing_data.get('tmax_C'),'Tmax',ndays,-100,70)
    if 'dates' in forcing_data:
        expected=[(datetime.strptime(forcing_data['start_date'],'%Y-%m-%d')+timedelta(days=i)).strftime('%Y-%m-%d') for i in range(ndays)]
        if list(forcing_data['dates'])!=expected:raise ValueError('Forcing dates do not match the declared daily period')

    start_dt = datetime.strptime(forcing_data['start_date'], "%Y-%m-%d")
    doys = np.array([(start_dt + timedelta(days=i)).timetuple().tm_yday
                     for i in range(ndays)])

    pet_mm_day = compute_pet_hargreaves(tmin_C, tmax_C, temp_C, lat_center, doys)

    # CRITICAL UNIT CONVERSION.
    # The TOPMODEL C engine treats rain[it]/pe[it] as DEPTH PER TIMESTEP (m),
    # NOT a rate: see topmodel.c `*p=rain[it]; deficit_root_zone-=*p`. The
    # timestep dt (hours) is used only for rate conversions (infiltration p/dt,
    # uz drainage td*dt, channel routing chv*dt).
    #   daily depth (m) = mm/day / 1000
    #   per-step depth  = daily depth / steps_per_day
    # => at dt=1h  (24 steps/day): /1000/24 = /24000   (matches hourly convention)
    #    at dt=24h ( 1 step/day):  /1000               (daily convention)
    _required(pet_mm_day,'Hargreaves PET',ndays,minimum=0)
    daily_depth_m = prec_mm_day / 1000.0
    daily_pet_m = pet_mm_day / 1000.0
    prec_step = daily_depth_m / steps_per_day
    pet_step = daily_pet_m / steps_per_day

    # Observed discharge (per-step depth). Disaggregating obs the same way keeps
    # it on the same per-step footing as the simulated flow.
    qobs_daily = load_obs_qmhr(obs_file, forcing_data['start_date'], ndays,
                               basin_area_km2)
    qobs_step = qobs_daily / steps_per_day

    # Disaggregate daily to sub-daily (uniform within day)
    rain_hourly = np.repeat(prec_step, steps_per_day)
    pet_hourly = np.repeat(pet_step, steps_per_day)
    qobs_hourly = np.repeat(qobs_step, steps_per_day)

    # Header timestep MUST be 1.0. The NOAA-OWP standalone binary advances time
    # as `current_time_step += dt` (bmi_topmodel.c Update) and then uses
    # current_time_step as the 1-based index into rain[]/pe[]/Qobs[]. Any dt!=1
    # makes it index rain[dt], rain[2*dt], ... — skipping (dt-1)/dt of the data,
    # reading past the array end (SUMP collapses, eventually SIGSEGV). So one
    # model timestep == one input row, regardless of the physical step length.
    # For a daily run (steps_per_day=1) each step represents one day and the
    # rate parameters (t0, td, chv, rv) are therefore interpreted per-day.
    model_dt = 1.0
    if (rain_hourly>0.5).any():raise ValueError('Rainfall exceeds the existing 0.5 m/step validation ceiling')
    _required(qobs_hourly,'Qobs depth',nstep,minimum=0)
    with open(output_file, 'w') as f:
        f.write(f"{nstep}  {model_dt:.1f}\n")
        for i in range(nstep):
            f.write(f"   {rain_hourly[i]:.12g}  {pet_hourly[i]:.12g}  {qobs_hourly[i]:.12g}\n")

    provenance=dict(start_date=forcing_data['start_date'],days=ndays,steps=nstep,model_header_dt=model_dt,
                    physical_dt_hours=24.0/steps_per_day,units='m/step',fill_count=0,
                    daily_to_subdaily='uniform redistribution within each observed day' if steps_per_day>1 else 'one step per day',
                    pet_method='Hargreaves with source Tmin/Tmax/Tmean; latitude/date-derived FAO56 Ra in mm/day',
                    source=forcing_data.get('source'),
                    observation_mode='provided_complete' if obs_file else 'not_supplied_placeholder_not_for_scoring',
                    obs_file=str(Path(obs_file).resolve()) if obs_file else None,
                    obs_sha256=hashlib.sha256(Path(obs_file).read_bytes()).hexdigest() if obs_file else None,
                    output_sha256=hashlib.sha256(Path(output_file).read_bytes()).hexdigest())
    Path(str(output_file)+'.provenance.json').write_text(json.dumps(provenance,indent=2,allow_nan=False)+'\n')
    phys_hours = 24.0 / steps_per_day
    print(f"Wrote {output_file}: {nstep} steps (model dt=1.0, "
          f"1 step = {phys_hours:.1f} physical hours), "
          f"max rain/step={rain_hourly.max():.5f} m")
    return nstep


def validate_outputs(output_file, nstep):
    """Validate the generated inputs.dat file."""
    errors = []

    if not os.path.exists(output_file):
        errors.append(f"Output file not created: {output_file}")
        return errors

    with open(output_file, 'r') as f:
        lines = f.readlines()

    header = lines[0].split()
    file_nstep = int(header[0])
    file_dt = float(header[1])

    if file_nstep != nstep:
        errors.append(f"nstep mismatch: expected {nstep}, got {file_nstep}")

    data_lines = len(lines) - 1
    if data_lines != nstep:
        errors.append(f"Data lines mismatch: expected {nstep}, got {data_lines}")

    # Value-range checks are on PER-STEP DEPTH (m/step). The header dt is always
    # 1.0 (see convert_to_topmodel_inputs), so use a physically generous ceiling:
    # an extreme daily storm is ~250 mm = 0.25 m; allow some margin.
    rain_ceiling = 0.5
    for i, line in enumerate(lines[1:], 1):
        vals = line.split()
        if len(vals) != 3:
            errors.append(f"Line {i}: expected 3 values, got {len(vals)}")
            continue
        rain, pe, qobs = float(vals[0]), float(vals[1]), float(vals[2])

        if not np.isfinite([rain,pe,qobs]).all():
            errors.append(f'Line {i}: nonfinite rain/PET/Qobs')
            continue
        if qobs<0:errors.append(f'Line {i}: negative observed discharge')
        if rain > rain_ceiling:
            errors.append(f"Line {i}: rain={rain} m/step exceeds {rain_ceiling:.3f} m "
                          f"(implausible at dt={file_dt}h)")
        if rain < 0:
            errors.append(f"Line {i}: negative rainfall")
        if pe < 0:
            errors.append(f"Line {i}: negative PE")

    if not errors:
        print(f"VALIDATION PASSED: {output_file}")
    else:
        for e in errors[:10]:
            print(f"VALIDATION WARNING: {e}")

    return errors


def main():
    parser = argparse.ArgumentParser(description="Convert CMFD forcing to TOPMODEL inputs.dat")
    parser.add_argument('--forcing-dir', required=True, help='Forcing root directory (CMFD/MSWX)')
    parser.add_argument('--source', choices=['cmfd'], default='cmfd', help='Strict source route: native subdaily CMFD')
    parser.add_argument('--start-date', required=True, help='Start date YYYY-MM-DD')
    parser.add_argument('--end-date', required=True, help='End date YYYY-MM-DD')
    parser.add_argument('--lat', type=float, required=True, help='Basin center latitude')
    parser.add_argument('--lon', type=float, required=True, help='Basin center longitude')
    parser.add_argument('--dt-hours', type=float, default=1.0, help='Time step in hours')
    parser.add_argument('--shapefile', default=None, help='Optional reference basin geometry; extraction uses the supplied representative point')
    parser.add_argument('--obs-file', default=None, help='Observed discharge file')
    parser.add_argument('--basin-area-km2', type=float, default=None, help='Basin area in km²')
    parser.add_argument('--output', default='inputs.dat', help='Output file path')

    args = parser.parse_args()

    # Step 1: Validate inputs
    print("=== Step 1: Validating inputs ===")
    errors = validate_inputs(args.forcing_dir, args.start_date, args.end_date, args.shapefile)
    if errors:
        for e in errors:
            print(f"  ERROR: {e}")
        return 2

    # Step 2: Extract and convert
    print("=== Step 2: Extracting basin-mean forcing ===")
    forcing_data = extract_basin_mean_forcing(
        args.forcing_dir, args.shapefile, args.start_date, args.end_date,
        lat_center=args.lat, lon_center=args.lon, source=args.source
    )

    print("=== Step 3: Converting to TOPMODEL format ===")
    nstep = convert_to_topmodel_inputs(
        forcing_data, args.dt_hours, args.lat,
        obs_file=args.obs_file, basin_area_km2=args.basin_area_km2,
        output_file=args.output
    )

    # Step 3: Validate outputs
    print("=== Step 4: Validating outputs ===")
    errors=validate_outputs(args.output, nstep)
    return 2 if errors else 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError,OSError,KeyError) as exc:
        print(f'ERROR: {exc}',file=sys.stderr)
        raise SystemExit(2)
