#!/usr/bin/env python3
"""
convert_forcing_to_wflow.py — Convert CMFD/MSWX forcing to wflow NetCDF format.

wflow requires a single NetCDF forcing file with dimensions (time, y, x) and
variables: precip (mm/timestep), temp (degC), pet (mm/timestep).

This tool reads the forcing straight from the data source (CMFD, MSWX, NASA
POWER, GSWP3 through ki_tools_common.load_forcing) on the cells of the wflow
grid and writes it in wflow format.

CRITICAL UNIT CONVERSIONS:
  - Temperature: Kelvin -> Celsius (subtract 273.15)
  - Precipitation: mm/s or mm/3hr -> mm/day (multiply accordingly)
  - PET: calculated from T, radiation, wind, humidity using Hargreaves or
    Penman-Monteith. wflow can also compute PET internally if individual
    variables are provided.

Usage:
    python convert_forcing_to_wflow.py \
      --source cmfd \
      --forcing_dir KISSPATH_DATA/forcing/Data_forcing_03hr_010deg \
      --staticmaps_nc /path/to/wflow_project/staticmaps.nc \
      --start_year 2000 --end_year 2010 \
      --output /path/to/wflow_project/forcing.nc
"""

import argparse
import glob
import json
import os
import sys
import time
from pathlib import Path

# netCDF4 must be loaded BEFORE xarray. python_env holds two copies of the HDF5
# library (one in the netCDF4 wheel, one in the h5py wheel) and only the copy
# loaded first can open or write a file afterwards. xarray alone pulls in
# h5py's copy, and then the default engine fails on staticmaps.nc and on
# to_netcdf with "NetCDF: HDF error" (measured 2026-10-03).
import netCDF4  # noqa: F401
import numpy as np


def read_grid(path):
    import xarray as xr
    with xr.open_dataset(path) as ds:
        axes=[(y,x) for y,x in [("lat","lon"),("latitude","longitude"),("y","x")] if y in ds.dims and x in ds.dims]
        if not axes:raise ValueError("Missing geographic grid coordinates")
        yn,xn=axes[0]
        lats,lons=ds[yn].values,ds[xn].values
        if lats.ndim!=1 or lons.ndim!=1 or not np.isfinite(lats).all() or not np.isfinite(lons).all():
            raise ValueError("Grid requires finite one-dimensional geographic axes")
        if np.any(abs(lats)>90) or np.any(abs(lons)>180) or len(np.unique(lats))!=len(lats) or len(np.unique(lons))!=len(lons):
            raise ValueError("Grid coordinates must be unique geographic latitude/longitude")
        for name in ["spatial_ref","crs"]:
            if name in ds:
                from pyproj import CRS
                attrs=ds[name].attrs
                crs=attrs.get("crs_wkt",attrs.get("spatial_ref"))
                if crs and not CRS.from_user_input(crs).is_geographic:
                    raise ValueError("Projected grids must be reprojected explicitly before point lookup")
        if "wflow_subcatch" not in ds:
            raise ValueError("wflow_subcatch is required to distinguish active cells from padding")
        vals=ds.wflow_subcatch.transpose(yn,xn).values
        if np.isinf(vals).any() or np.any(np.isfinite(vals)&(vals<=0)):
            raise ValueError("wflow_subcatch must use positive IDs and NaN padding, never zero/negative IDs")
        active=np.isfinite(vals)&(vals>0)
        if not active.any():raise ValueError("No active basin cells")
    return lats,lons,active


def check_daily(times,start_year,end_year):
    import pandas as pd
    dates=pd.DatetimeIndex(times)
    expected=pd.date_range(f"{start_year}-01-01",f"{end_year}-12-31")
    if not dates.equals(expected):raise ValueError("Forcing calendar must match every requested day exactly in order")
    return dates


def valid(values,name,low,high):
    arr=np.asarray(values,dtype=float)
    if not arr.size or not np.isfinite(arr).all() or np.any(arr<low) or np.any(arr>high):
        raise ValueError(f"{name}: missing/nonfinite or outside [{low},{high}]; no filling")
    return arr


def hargreaves(tmin,tmax,tmean,lat,doy):
    if np.any(tmin>tmean) or np.any(tmean>tmax):raise ValueError("Require Tmin <= Tmean <= Tmax")
    dr=1+0.033*np.cos(2*np.pi*doy/365.)
    delta=0.4093*np.sin(2*np.pi*doy/365.-1.39)
    phi=np.radians(lat)
    ws=np.arccos(np.clip(-np.tan(phi)*np.tan(delta),-1,1))
    ra=np.maximum(24*60/np.pi*.0820*dr*(ws*np.sin(phi)*np.sin(delta)+np.cos(phi)*np.cos(delta)*np.sin(ws)),0)
    return np.maximum(0,.0023*(ra/2.45)*(tmean+17.8)*np.sqrt(tmax-tmin))


def read_cmfd_forcing_direct(forcing_dir,grid_path,start_year,end_year):
    """Validate every original CMFD substep before daily reduction (no SRad needed for HG)."""
    import pandas as pd
    import xarray as xr
    lats,lons,active=read_grid(grid_path)
    cells=np.argwhere(active);all_dates=[];all_p=[];all_t=[];all_pet=[]
    for year in range(start_year,end_year+1):
        for month in range(1,13):
            month_start=pd.Timestamp(year,month,1);month_end=month_start+pd.offsets.MonthBegin(1)
            raw={};stamp=None
            for folder,var in [("Prec","prec"),("Temp","temp")]:
                root=Path(forcing_dir)
                files=sorted((root/folder).glob(f"*{year}{month:02d}*.nc"))
                if not files:files=sorted(root.glob(f"*{var}*{year}{month:02d}*.nc"))
                if len(files)!=1:raise ValueError(f"Need exactly one {var} file for {year}-{month:02d}; found {len(files)}")
                with xr.open_dataset(files[0]) as ds:
                    if var not in ds:raise ValueError(f"Missing {var} in {files[0]}")
                    times=pd.DatetimeIndex(ds.time.values)
                    offset=times[0]-month_start if len(times) else pd.Timedelta(days=99)
                    expected=pd.date_range(month_start+offset,month_end,freq="3h",inclusive="left")
                    if not pd.Timedelta(0)<=offset<pd.Timedelta(hours=3) or not times.equals(expected) or len(times)!=(month_end-month_start).days*8:
                        raise ValueError(f"Incomplete, duplicate or unordered original substeps: {files[0]}")
                    if stamp is not None and not times.equals(stamp):raise ValueError("CMFD P/T source timestamps differ")
                    stamp=times
                    yn="lat" if "lat" in ds.coords else "latitude";xn="lon" if "lon" in ds.coords else "longitude"
                    y=ds[yn].values;x=ds[xn].values
                    dy=float(np.max(abs(np.diff(y))))/2 if len(y)>1 else 0
                    dx=float(np.max(abs(np.diff(x))))/2 if len(x)>1 else 0
                    # Coverage is checked on active cells only; NaN padding never needs forcing.
                    alat=lats[cells[:,0]];alon=lons[cells[:,1]]
                    if alat.min()<y.min()-dy or alat.max()>y.max()+dy or alon.min()<x.min()-dx or alon.max()>x.max()+dx:raise ValueError("Active basin cells outside source coverage")
                    iy=[int(np.argmin(abs(y-lats[j]))) for j,i in cells];ix=[int(np.argmin(abs(x-lons[i]))) for j,i in cells]
                    values=ds[var].isel({yn:xr.DataArray(iy,dims="cell"),xn:xr.DataArray(ix,dims="cell")}).transpose("time","cell").values
                    unit=ds[var].attrs.get("units","").lower().replace(" ","").replace("**","").replace("^","")
                    if var=="prec":
                        if unit not in {"kgm-2s-1","mm/s","mms-1"}:raise ValueError(f"Unsupported declared precipitation unit {unit}")
                        values=valid(values,"source precip rate",0,1000/10800.)
                    else:
                        if unit not in {"k","kelvin"}:raise ValueError(f"Unsupported declared temperature unit {unit}")
                        values=valid(values,"source temperature K",183.15,343.15)-273.15
                    raw[var]=values.reshape(-1,8,len(cells))
            dates=pd.date_range(month_start,month_end,inclusive="left")
            p=raw["prec"].sum(axis=1)*10800.;t=raw["temp"].mean(axis=1)
            et=hargreaves(raw["temp"].min(axis=1),raw["temp"].max(axis=1),t,lats[cells[:,0]][None,:],dates.dayofyear.to_numpy()[:,None])
            all_dates.extend(dates);all_p.append(p);all_t.append(t);all_pet.append(et)
    dates=check_daily(all_dates,start_year,end_year)
    arrays=[]
    for vals in [all_p,all_t,all_pet]:
        result=np.full((len(dates),len(lats),len(lons)),np.nan,dtype=np.float32)
        result[:,active]=np.concatenate(vals);arrays.append(result)
    return dates.values,lats,lons,*arrays


def read_forcing_via_ki_tools(source,grid_path,start_year,end_year,forcing_dir=None):
    """Validate the shared daily-loader result; upstream raw-gap reductions remain upstream."""
    from ki_tools_common.load_forcing import load_daily_forcing_points
    lats,lons,active=read_grid(grid_path)
    cells=np.argwhere(active);points=[(float(lats[j]),float(lons[i])) for j,i in cells]
    recs=load_daily_forcing_points(source,points,start_year,end_year,forcing_dir=forcing_dir)
    if len(recs)!=len(cells):raise ValueError("Loader record count must match active grid cells")
    dates=check_daily(recs[0]["dates"],start_year,end_year);nt=len(dates)
    arrays=[np.full((nt,len(lats),len(lons)),np.nan,dtype=np.float32) for _ in range(3)]
    for (j,i),rec in zip(cells,recs):
        check_daily(rec["dates"],start_year,end_year)
        values=[]
        for key,lo,hi in [("precip_mm",0,1000),("temp_mean_c",-90,70),("temp_min_c",-90,70),("temp_max_c",-90,70)]:
            if key not in rec:raise ValueError(f"Missing required {key}")
            arr=valid(rec[key],key,lo,hi)
            if arr.shape!=(nt,):raise ValueError(f"{key} length must match the full calendar")
            values.append(arr)
        p,tm,tn,tx=values
        arrays[0][:,j,i]=p;arrays[1][:,j,i]=tm
        arrays[2][:,j,i]=hargreaves(tn,tx,tm,lats[j],dates.dayofyear.to_numpy())
    return dates.values,lats,lons,*arrays


def validate_inputs(args):
    """Validate forcing data sources."""
    errors = []

    if not args.source and not args.forcing_dir:
        errors.append(
            "Must provide --source (cmfd, mswx, nasa_power, gswp3); "
            "--forcing_dir is then the dataset root"
        )

    if args.forcing_dir and not args.source and not os.path.isdir(args.forcing_dir):
        errors.append(f"Forcing directory not found: {args.forcing_dir}")

    if not args.grid_nc and not args.staticmaps_nc:
        errors.append("Must provide --grid_nc or --staticmaps_nc for grid definition")

    grid_path = args.grid_nc or args.staticmaps_nc
    if grid_path and not os.path.exists(grid_path):
        errors.append(f"Grid file not found: {grid_path}")

    # start_year == end_year is a legitimate single-year conversion — it is how
    # a long run is built one resumable year at a time.
    if args.start_year > args.end_year:
        errors.append(
            f"start_year ({args.start_year}) must be <= end_year ({args.end_year})"
        )

    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


def process(args):
    """Convert forcing data to wflow NetCDF format."""
    import xarray as xr

    start_time = time.time()

    print(f"Converting forcing data to wflow format...", file=sys.stderr)
    print(f"  Period: {args.start_year}-{args.end_year}", file=sys.stderr)

    grid_path = args.grid_nc or args.staticmaps_nc

    if args.source:
        times, lats, lons, precip, temp, pet = read_forcing_via_ki_tools(
            args.source, grid_path, args.start_year, args.end_year,
            forcing_dir=(args.forcing_dir or None)
        )
    elif args.forcing_dir:
        # No --source: only a CMFD store (Prec/, Temp/, SRad/ subdirectories) is
        # read here. Any other folder needs --source.
        forcing_dir = Path(args.forcing_dir)
        cmfd_subdirs = any((forcing_dir / d).exists() for d in ['Prec', 'Temp', 'SRad'])
        if not cmfd_subdirs:
            raise ValueError(
                f"{args.forcing_dir} is not a CMFD store (no Prec/, Temp/, SRad/). "
                "Name the data source with --source (cmfd, mswx, nasa_power, gswp3)."
            )
        print("  Reading CMFD NetCDF from subdirectories...", file=sys.stderr)
        times, lats, lons, precip, temp, pet = read_cmfd_forcing_direct(
            args.forcing_dir, grid_path, args.start_year, args.end_year
        )
    else:
        raise ValueError("--source is required")

    dates=check_daily(times,args.start_year,args.end_year)
    grid_lats,grid_lons,active=read_grid(grid_path)
    if not np.array_equal(lats,grid_lats) or not np.array_equal(lons,grid_lons):
        raise ValueError("Forcing grid differs from staticmaps")
    expected=(len(dates),len(lats),len(lons))
    checked=[]
    for arr,name,lo,hi in [(precip,"precip",0,1000),(temp,"temp",-90,70),(pet,"pet",0,100)]:
        arr=np.asarray(arr,dtype=float).copy()
        if arr.shape!=expected:raise ValueError(f"{name} shape differs from calendar/grid")
        valid(arr[:,active],name,lo,hi)
        arr[:,~active]=np.nan  # Explicitly masked padding, never inferred weather.
        checked.append(arr)
    precip,temp,pet=checked

    # Create wflow forcing NetCDF
    ds = xr.Dataset(
        {
            "precip": (
                ["time", "y", "x"],
                precip,
                {
                    "units": "mm",
                    "long_name": "Precipitation",
                    "standard_name": "atmosphere_water__precipitation_volume_flux",
                    "description": "Total precipitation per day",
                },
            ),
            "temp": (
                ["time", "y", "x"],
                temp,
                {
                    "units": "degC",
                    "long_name": "Air temperature",
                    "standard_name": "atmosphere_air__temperature",
                    "description": "Mean daily air temperature (Celsius)",
                },
            ),
            "pet": (
                ["time", "y", "x"],
                pet,
                {
                    "units": "mm",
                    "long_name": "Potential evapotranspiration",
                    "standard_name": "land_surface_water__potential_evaporation_volume_flux",
                    "description": "PET per day (Hargreaves method)",
                },
            ),
        },
        coords={
            "time": times,
            "y": lats,
            "x": lons,
        },
    )

    ds.attrs["Conventions"] = "CF-1.6"
    ds.attrs["title"] = "wflow forcing data converted from HydroCraft"
    ds.attrs["source"] = f"Converted from {args.forcing_dir or args.cmfd_dir or args.mswx_dir}"
    ds.attrs["timestep_seconds"] = 86400
    ds.attrs["active_cell_fill_count"] = 0
    ds.attrs["et_method"] = "Hargreaves; source extrema required; no temperature-range floor"
    ds.attrs["inactive_cells"] = "masked NaN; exclude from basin statistics"
    ds.attrs["validation_scope"] = "shared daily-loader output; upstream raw substeps not certified" if args.source else "all original CMFD 3-hourly P/T samples"


    # Write output
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    ds.to_netcdf(args.output, encoding={
        "precip": {"dtype": "float32", "zlib": True, "complevel": 4},
        "temp": {"dtype": "float32", "zlib": True, "complevel": 4},
        "pet": {"dtype": "float32", "zlib": True, "complevel": 4},
    })

    elapsed = time.time() - start_time

    return {
        "status": "success",
        "output_path": args.output,
        "size_mb": round(os.path.getsize(args.output) / 1e6, 1),
        "time_steps": len(times),
        "grid_shape": f"{len(lats)} x {len(lons)}",
        "variables": ["precip (mm/day)", "temp (degC)", "pet (mm/day)"],
        "elapsed_seconds": round(elapsed, 1),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Convert CMFD/MSWX forcing to wflow NetCDF format"
    )
    parser.add_argument("--source", type=str, default="",
                        choices=["", "cmfd", "mswx", "nasa_power", "gswp3"],
                        help="Load via ki_tools_common.load_forcing (PREFERRED). "
                             "--forcing_dir then means the dataset ROOT.")
    parser.add_argument("--forcing_dir", type=str, default="",
                        help="Dataset root of the source named with --source")
    parser.add_argument("--cmfd_dir", type=str, default="",
                        help="Raw CMFD NetCDF directory")
    parser.add_argument("--mswx_dir", type=str, default="",
                        help="Raw MSWX NetCDF directory")
    parser.add_argument("--grid_nc", type=str, default="",
                        help="Grid NetCDF with lat/lon (or y/x) axes; normally use --staticmaps_nc")
    parser.add_argument("--staticmaps_nc", type=str, default="",
                        help="wflow staticmaps.nc (alternative to grid_nc)")
    parser.add_argument("--start_year", type=int, required=True)
    parser.add_argument("--end_year", type=int, required=True)
    parser.add_argument("--output", type=str, required=True)
    args = parser.parse_args()

    validate_inputs(args)

    try:
        result = process(args)
    except Exception as e:
        print(json.dumps({"status": "failed", "error": str(e)}, indent=2))
        sys.exit(2)

    print(json.dumps(result, indent=2))
    sys.exit(0 if result["status"] == "success" else 2)


if __name__ == "__main__":
    main()
