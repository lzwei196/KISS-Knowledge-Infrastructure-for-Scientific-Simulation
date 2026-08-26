#!/usr/bin/env python3
"""
Convert CMFD/MSWX forcing to ParFlow/CLM "3D" PFB forcing.

CLM 3D contract (shipped reference: parflow test/python/washita/LW_Test.py):
one file PER VARIABLE per chunk, <MetFileName>.<VAR>.<start>_to_<stop>.pfb,
VAR in {DSWR DLWR APCP Temp UGRD VGRD Press SPFH} ('Temp', NOT 'Tmp'), each
holding NT time-ascending (ny,nx) slices; Solver.CLM.MetForcing='3D',
MetFileNT=NT, IstepStart = first simulated hour (1-based).

The previous version wrote one 8-var stacked file per timestep (a layout CLM
never reads), and silently substituted synthetic defaults whenever the source
lookup failed -- which for MSWX was ALWAYS (CMFD monthly glob patterns vs
MSWX annual files). Missing source data is now a HARD ERROR.

Units (verified from file attrs, not docs): MSWX P 'mm 3h-1'->/10800,
Tair degC->+273.15, SWd/LWd W/m2, Pres Pa, spechum kg/kg, wind m/s scalar->
UGRD (VGRD=0). CMFD prec mm/hr->/3600, rest native.

MSWX reads reuse ki_tools_common.load_forcing helpers (_mswx_grid/
_mswx_read_box); per-(var,year) extractions cache as .npy under
<output_dir>/cache/ so relaunches resume instead of re-decompressing.

Author: Jianyun Zhang Research Group, Hohai University
"""

import argparse
import glob as _glob
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

try:
    import h5py
    from pyproj import Transformer
    from parflow.tools.io import write_pfb
except ImportError as e:
    print(json.dumps({"status": "error", "message": f"Missing dependency: {e}"}))
    sys.exit(1)

CLM_VARS = ["DSWR", "DLWR", "APCP", "Temp", "UGRD", "VGRD", "Press", "SPFH"]

# CLM var -> (MSWX subdir, expected units attr, scale, offset)
MSWX_VAR_MAP = {
    "DSWR": ("SWd", "W m-2", 1.0, 0.0),
    "DLWR": ("LWd", "W m-2", 1.0, 0.0),
    "APCP": ("P", "mm 3h-1", 1.0 / 10800.0, 0.0),   # mm/3h -> mm/s
    "Temp": ("Tair", "degree_Celsius", 1.0, 273.15),  # degC -> K
    "UGRD": ("wind", "m s-1", 1.0, 0.0),             # scalar speed -> U component
    "VGRD": (None, None, 0.0, 0.0),                  # no direction in store -> 0
    "Press": ("Pres", "Pa", 1.0, 0.0),
    "SPFH": ("spechum", "kg kg-1", 1.0, 0.0),
}

# CLM var -> (CMFD file pattern, scale, offset); CMFD units are documented in
# data_ki/CMFD/SKILL.md and were verified in the Chaohe/Bengbu BODY tests.
CMFD_VAR_MAP = {
    "DSWR": ("srad", 1.0, 0.0),
    "DLWR": ("lrad", 1.0, 0.0),
    "APCP": ("prec", 1.0 / 3600.0, 0.0),  # mm/hr -> mm/s
    "Temp": ("temp", 1.0, 0.0),
    "UGRD": ("wind", 1.0, 0.0),
    "VGRD": (None, 0.0, 0.0),
    "Press": ("pres", 1.0, 0.0),
    "SPFH": ("shum", 1.0, 0.0),
}

SRC_DT_HOURS = 3  # both MSWX and CMFD stores used here are 3-hourly


def cell_latlon(domain):
    grid = domain["grid"]
    nx, ny = grid["nx"], grid["ny"]
    dx, dy = grid["dx"], grid["dy"]
    ox, oy = domain["origin"]["x"], domain["origin"]["y"]
    tr = Transformer.from_crs(f"EPSG:{domain['crs']['epsg']}", "EPSG:4326",
                              always_xy=True)
    ii, jj = np.meshgrid(np.arange(nx), np.arange(ny))
    lons, lats = tr.transform(ox + (ii + 0.5) * dx, oy + (jj + 0.5) * dy)
    return np.asarray(lats), np.asarray(lons)


def _extract_mswx_year(forcing_dir, year, clm_var, lats, lons, cache_dir):
    """(n_src_steps, ny, nx) array for one CLM variable and year, cached.

    The heavy box read lives in ki_tools_common.load_forcing.load_mswx_year_box
    (shared with other gridded consumers); this wrapper adds the CLM variable
    mapping, a units-attr assertion, unit conversion, and the resume cache.
    """
    subdir, exp_units, scale, offset = MSWX_VAR_MAP[clm_var]
    cache_f = os.path.join(cache_dir, f"mswx_{clm_var}_{year}.npy")
    if os.path.exists(cache_f):
        return np.load(cache_f)
    if subdir is None:  # VGRD: store has scalar wind speed only
        n_steps = int((datetime(year + 1, 1, 1) - datetime(year, 1, 1)).days * 24 / SRC_DT_HOURS)
        arr = np.zeros((n_steps,) + lats.shape, dtype=np.float32)
        np.save(cache_f, arr)
        return arr
    from ki_tools_common.load_forcing import load_mswx_year_box
    ext, units = load_mswx_year_box(forcing_dir, year, subdir, lats, lons)
    if units.strip() != exp_units:
        raise ValueError(
            f"MSWX {subdir} units are '{units}', expected '{exp_units}'"
            " -- refusing to convert with wrong unit assumption (dt_pf_002/006 class)")
    ext = ext * scale + offset
    np.save(cache_f, ext.astype(np.float32))
    return ext


def _extract_cmfd_month(forcing_dir, year, month, clm_var, lats, lons):
    pattern, scale, offset = CMFD_VAR_MAP[clm_var]
    if pattern is None:
        return None  # caller fills zeros sized like APCP
    import xarray as xr
    fp = Path(forcing_dir)
    nc_files = []
    for sub in (pattern, pattern.capitalize(), pattern.upper()):
        d = fp / sub
        if d.exists():
            nc_files = sorted(d.glob(f"*{year}{month:02d}*"))
            break
    if not nc_files:
        nc_files = sorted(fp.glob(f"*{pattern}*{year}{month:02d}*"))
    if not nc_files:
        raise FileNotFoundError(
            f"CMFD source missing for {pattern} {year}-{month:02d} under {forcing_dir}")
    ds = xr.open_dataset(nc_files[0])
    dv = next((v for v in ds.data_vars if pattern in v.lower()), list(ds.data_vars)[0])
    glat = ds["lat"].values if "lat" in ds else ds["latitude"].values
    glon = ds["lon"].values if "lon" in ds else ds["longitude"].values
    raw = ds[dv].values
    r_idx = np.array([np.argmin(np.abs(glat - la)) for la in lats.ravel()])
    c_idx = np.array([np.argmin(np.abs(glon - lo)) for lo in lons.ravel()])
    ext = raw[:, r_idx, c_idx].reshape((raw.shape[0],) + lats.shape) * scale + offset
    ds.close()
    if np.isnan(ext).any():
        raise ValueError(f"CMFD {pattern} {year}-{month:02d}: NaN after extraction")
    return ext.astype(np.float32)


def process(domain_json, forcing_source, forcing_dir, start_date, end_date,
            output_dir, run_name="parflow_run", dt_hours=1, met_name="NLDAS",
            chunk_hours=24):
    os.makedirs(output_dir, exist_ok=True)
    cache_dir = os.path.join(output_dir, "cache")
    os.makedirs(cache_dir, exist_ok=True)

    if dt_hours != 1:
        raise ValueError("dt_hours must be 1: CLM consumes one met slice per "
                         "hourly ParFlow step; 3-hourly sources are repeated 3x")

    with open(domain_json) as f:
        domain = json.load(f)
    grid = domain["grid"]
    nx, ny = grid["nx"], grid["ny"]
    dx, dy = grid["dx"], grid["dy"]
    lats, lons = cell_latlon(domain)

    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    total_hours = int((end_dt - start_dt).total_seconds() // 3600)
    if total_hours % chunk_hours != 0:
        raise ValueError(f"period ({total_hours} h) must be a whole number of "
                         f"{chunk_hours}-hour chunks")
    n_chunks = total_hours // chunk_hours

    files_created = 0
    files_skipped = 0

    if forcing_source == "mswx":
        year_cache = {}

        def src_slice(var, when):
            y = when.year
            if (var, y) not in year_cache:
                year_cache.clear()  # hold one year per var set at a time
                # Each (var, year) costs a full-file gzip decompression (the
                # store is one global slab per timestep) -- fan the 7 real
                # variables across PROCESSES, mirroring
                # ki_tools_common.load_forcing._load_mswx_points.
                from concurrent.futures import ProcessPoolExecutor
                todo = [v for v in CLM_VARS if not os.path.exists(
                    os.path.join(cache_dir, f"mswx_{v}_{y}.npy"))]
                if todo:
                    with ProcessPoolExecutor(max_workers=len(todo)) as ex:
                        futs = {ex.submit(_extract_mswx_year, forcing_dir, y,
                                          v, lats, lons, cache_dir): v
                                for v in todo}
                        for fut, v in futs.items():
                            fut.result()  # re-raise extraction errors
                for v in CLM_VARS:
                    year_cache[(v, y)] = np.load(
                        os.path.join(cache_dir, f"mswx_{v}_{y}.npy"))
            idx = int((when - datetime(y, 1, 1)).total_seconds() // 3600) // SRC_DT_HOURS
            return year_cache[(var, y)][idx]
    elif forcing_source == "cmfd":
        month_cache = {}

        def src_slice(var, when):
            key = (when.year, when.month)
            if key not in month_cache or var not in month_cache[key]:
                data = {}
                for v in CLM_VARS:
                    data[v] = _extract_cmfd_month(forcing_dir, key[0], key[1], v, lats, lons)
                if data["VGRD"] is None:
                    data["VGRD"] = np.zeros_like(data["APCP"])
                month_cache.clear()
                month_cache[key] = data
            idx = int((when - datetime(when.year, when.month, 1)).total_seconds() // 3600) // SRC_DT_HOURS
            return month_cache[key][var][idx]
    else:
        raise ValueError(f"forcing_source '{forcing_source}' is not supported "
                         "(mswx | cmfd). No synthetic fallback exists by design.")

    for ci in range(n_chunks):
        h0 = ci * chunk_hours            # 0-based first hour of chunk
        s_num, e_num = h0 + 1, h0 + chunk_hours
        done = all(os.path.exists(os.path.join(
            output_dir, f"{met_name}.{v}.{s_num:06d}_to_{e_num:06d}.pfb"))
            for v in CLM_VARS)
        if done:
            files_skipped += len(CLM_VARS)
            continue
        stack = {v: np.empty((chunk_hours, ny, nx), dtype=np.float64)
                 for v in CLM_VARS}
        for hh in range(chunk_hours):
            when = start_dt + timedelta(hours=h0 + hh)
            for v in CLM_VARS:
                stack[v][hh] = src_slice(v, when)
        for v in CLM_VARS:
            out = os.path.join(output_dir,
                               f"{met_name}.{v}.{s_num:06d}_to_{e_num:06d}.pfb")
            write_pfb(out, stack[v], dx=dx, dy=dy, dz=1.0, x=0.0, y=0.0, z=0.0,
                      dist=False)
            files_created += 1

    apcp = sorted(_glob.glob(os.path.join(output_dir, f"{met_name}.APCP.*.pfb")))
    result = {
        "status": "success",
        "forcing_source": forcing_source,
        "output_dir": output_dir,
        "naming": f"{met_name}.<VAR>.<start>_to_<stop>.pfb (CLM MetForcing='3D')",
        "met_file_nt": chunk_hours,
        "variables": CLM_VARS,
        "files_created": files_created,
        "files_skipped_existing": files_skipped,
        "chunks_expected": n_chunks,
        "apcp_chunks_present": len(apcp),
        "total_timesteps": total_hours,
        "period": {"start": start_date, "end": end_date},
        "unit_conversions_applied": {
            "mswx": "P mm/3h->mm/s (/10800); Tair degC->K (+273.15); rest native",
            "cmfd": "prec mm/hr->mm/s (/3600); rest native",
        },
        "istep_note": "IstepStart=1 corresponds to the first hour after "
                      f"{start_date} 00:00; slice t of a chunk is hour t.",
    }
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Convert forcing to ParFlow/CLM 3D PFB forcing")
    parser.add_argument("--domain_json", required=True)
    parser.add_argument("--forcing_source", choices=["cmfd", "mswx"],
                        default="cmfd")
    parser.add_argument("--forcing_dir", required=True)
    parser.add_argument("--start_date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end_date", required=True,
                        help="YYYY-MM-DD (exclusive, midnight)")
    parser.add_argument("--output_dir", required=True)
    parser.add_argument("--run_name", default="parflow_run")
    parser.add_argument("--dt_hours", type=int, default=1)
    parser.add_argument("--met_name", default="NLDAS")
    parser.add_argument("--chunk_hours", type=int, default=24)
    args = parser.parse_args()

    if not os.path.exists(args.domain_json):
        print(json.dumps({"status": "error",
                          "errors": [f"Domain definition not found: {args.domain_json}"]}))
        sys.exit(1)
    if not os.path.exists(args.forcing_dir):
        print(json.dumps({"status": "error",
                          "errors": [f"Forcing directory not found: {args.forcing_dir}"]}))
        sys.exit(1)

    result = process(args.domain_json, args.forcing_source, args.forcing_dir,
                     args.start_date, args.end_date, args.output_dir,
                     args.run_name, args.dt_hours, args.met_name,
                     args.chunk_hours)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
