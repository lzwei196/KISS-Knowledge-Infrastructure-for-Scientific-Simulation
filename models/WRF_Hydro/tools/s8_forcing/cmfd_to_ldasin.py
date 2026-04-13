#!/usr/bin/env python3
"""
cmfd_to_ldasin.py  --  Option A: Direct CMFD-to-LDASIN Forcing Converter
=========================================================================
Read CMFD 0.1 degree NetCDF forcing data directly and produce hourly
LDASIN_DOMAIN1 files on the WRF-Hydro Lambert Conformal Conic grid.

This bypasses VIC entirely, avoiding the double-interpolation problem:
  Old:  CMFD 0.1deg -> VIC ASCII -> interpolate to 1km LCC -> LDASIN  (2 spatial interps)
  New:  CMFD 0.1deg -> RegularGridInterpolator to LCC -> LDASIN       (1 spatial interp)

CMFD variables and mapping to WRF-Hydro LDASIN:
  CMFD var   | Units        | LDASIN var | Units   | Conversion
  -----------|--------------|------------|---------|-----------------------------
  temp       | K            | T2D        | K       | direct
  shum       | kg/kg        | Q2D        | kg/kg   | direct
  wind       | m/s          | U2D, V2D   | m/s     | wind * 0.7071 each
  pres       | Pa           | PSFC       | Pa      | direct
  srad       | W/m^2        | SWDOWN     | W/m^2   | direct, cap at 1361
  lrad       | W/m^2        | LWDOWN     | W/m^2   | direct
  prec       | kg/m^2/s     | RAINRATE   | mm/s    | direct (1 kg/m^2/s = 1 mm/s)

IMPORTANT: CMFD precipitation is stored as kg/m^2/s (= mm/s), NOT mm/3hr.
The VIC pipeline converts CMFD prec * 10800 -> mm/3hr for VIC ASCII input.
For LDASIN, RAINRATE is in mm/s = kg/m^2/s, so CMFD prec maps directly.

CMFD file structure:
  Data_forcing_03hr_010deg/
    Temp/temp_CMFD_V0200_B-01_03hr_010deg_YYYYMM.nc
    Prec/prec_CMFD_V0200_B-01_03hr_010deg_YYYYMM.nc
    ...

Each NC file has dims (time, lat, lon), 3-hourly within month.
Coordinate variable names: lat, lon, time (detected automatically).

Usage
-----
    python cmfd_to_ldasin.py \\
        --cmfd_dir  data/forcing/Data_forcing_03hr_010deg \\
        --geo_em    outputs/bengbu_wrf_test/DOMAIN/geo_em.d01.nc \\
        --domain_json outputs/bengbu_wrf_test/domain_def.json \\
        --output_dir  outputs/bengbu_wrf_test/FORCING \\
        --start_date  2001-07-01 \\
        --end_date    2001-07-31
"""

import argparse
import json
import sys
import time as _time
from datetime import datetime, timedelta
from pathlib import Path

import netCDF4 as nc
import numpy as np
from scipy.interpolate import RegularGridInterpolator


# ===================================================================
# CMFD configuration
# ===================================================================

# (cmfd_var_name, subdirectory_name, file_prefix)
CMFD_VAR_MAP = [
    ("temp", "Temp", "temp"),
    ("prec", "Prec", "prec"),
    ("pres", "Pres", "pres"),
    ("srad", "SRad", "srad"),
    ("lrad", "LRad", "lrad"),
    ("shum", "SHum", "shum"),
    ("wind", "Wind", "wind"),
]

# File pattern: {prefix}_CMFD_V0200_B-01_03hr_010deg_{YYYYMM}.nc
CMFD_FILE_PATTERN = "{prefix}_CMFD_V0200_B-01_03hr_010deg_{yyyymm}.nc"


# ===================================================================
# Helpers
# ===================================================================

def find_cmfd_file(cmfd_dir, subdir, prefix, year, month):
    """Locate a CMFD monthly file, trying common naming patterns."""
    cmfd_dir = Path(cmfd_dir)
    yyyymm = f"{year:04d}{month:02d}"

    # Primary pattern
    fname = CMFD_FILE_PATTERN.format(prefix=prefix, yyyymm=yyyymm)
    path = cmfd_dir / subdir / fname
    if path.exists():
        return path

    # Fallback: search the subdirectory for any file matching the month
    search_dir = cmfd_dir / subdir
    if search_dir.is_dir():
        for f in sorted(search_dir.iterdir()):
            if yyyymm in f.name and f.suffix == '.nc':
                return f

    raise FileNotFoundError(
        f"CMFD file not found: {path}\n"
        f"  Searched in: {search_dir}\n"
        f"  Pattern: *{yyyymm}*.nc"
    )


def detect_cmfd_coords(nc_path):
    """
    Auto-detect coordinate variable names in a CMFD NetCDF file.
    Returns (time_name, lat_name, lon_name, data_var_name).
    """
    ds = nc.Dataset(str(nc_path))
    var_names = list(ds.variables.keys())
    dim_names = list(ds.dimensions.keys())
    ds.close()

    # Time coordinate
    time_name = None
    for candidate in ['time', 'Time', 'TIME']:
        if candidate in var_names or candidate in dim_names:
            time_name = candidate
            break
    if time_name is None:
        # First dimension is usually time
        time_name = dim_names[0]

    # Lat coordinate
    lat_name = None
    for candidate in ['latitude', 'lat', 'Latitude', 'LAT', 'y']:
        if candidate in var_names:
            lat_name = candidate
            break
    if lat_name is None:
        lat_name = dim_names[1] if len(dim_names) > 1 else 'latitude'

    # Lon coordinate
    lon_name = None
    for candidate in ['longitude', 'lon', 'Longitude', 'LON', 'x']:
        if candidate in var_names:
            lon_name = candidate
            break
    if lon_name is None:
        lon_name = dim_names[2] if len(dim_names) > 2 else 'longitude'

    # Data variable: the non-coordinate variable
    coord_names = {time_name, lat_name, lon_name}
    data_var = None
    for v in var_names:
        if v not in coord_names and v not in dim_names:
            data_var = v
            break
    if data_var is None:
        # The data variable might have the same name as a known CMFD var
        for v in ['temp', 'prec', 'pres', 'srad', 'lrad', 'shum', 'wind']:
            if v in var_names:
                data_var = v
                break

    return time_name, lat_name, lon_name, data_var


def read_cmfd_month(cmfd_dir, cmfd_var, year, month, lat_range=None, lon_range=None):
    """
    Read one month of one CMFD variable.

    Parameters
    ----------
    cmfd_dir : Path
        Root CMFD directory.
    cmfd_var : tuple (var_name, subdir_name, file_prefix)
    year, month : int
    lat_range : tuple (lat_min, lat_max) for spatial subsetting
    lon_range : tuple (lon_min, lon_max) for spatial subsetting

    Returns
    -------
    data : ndarray (ntime, nlat, nlon)
    times : list of datetime
    lats : 1D ndarray (ascending)
    lons : 1D ndarray (ascending)
    """
    var_name, subdir, prefix = cmfd_var
    nc_path = find_cmfd_file(cmfd_dir, subdir, prefix, year, month)

    ds = nc.Dataset(str(nc_path))
    time_name, lat_name, lon_name, data_var_name = detect_cmfd_coords(nc_path)

    # If data_var_name is None, use the known CMFD var name
    if data_var_name is None:
        data_var_name = var_name

    # Read coordinates
    lats_full = ds.variables[lat_name][:]
    lons_full = ds.variables[lon_name][:]

    # Read time
    time_var = ds.variables[time_name]
    time_units = getattr(time_var, 'units', f'hours since {year}-01-01 00:00:00')
    time_cal = getattr(time_var, 'calendar', 'standard')
    times = nc.num2date(time_var[:], time_units, time_cal)
    times = [datetime(t.year, t.month, t.day, t.hour, t.minute, t.second)
             for t in times]

    # Ensure lats ascending
    lat_ascending = lats_full[0] < lats_full[-1]
    if not lat_ascending:
        lats_full = lats_full[::-1]

    # Spatial subsetting for efficiency
    if lat_range is not None and lon_range is not None:
        lat_idx = np.where((lats_full >= lat_range[0]) & (lats_full <= lat_range[1]))[0]
        lon_idx = np.where((lons_full >= lon_range[0]) & (lons_full <= lon_range[1]))[0]

        if len(lat_idx) == 0 or len(lon_idx) == 0:
            ds.close()
            raise ValueError(
                f"No CMFD data in requested lat/lon range: "
                f"lat=[{lat_range[0]:.2f},{lat_range[1]:.2f}] "
                f"lon=[{lon_range[0]:.2f},{lon_range[1]:.2f}].\n"
                f"CMFD coverage: lat=[{lats_full.min():.2f},{lats_full.max():.2f}] "
                f"lon=[{lons_full.min():.2f},{lons_full.max():.2f}]"
            )

        lat_slice = slice(lat_idx[0], lat_idx[-1] + 1)
        lon_slice = slice(lon_idx[0], lon_idx[-1] + 1)
        lats = lats_full[lat_slice]
        lons = lons_full[lon_slice]

        # Read data with subsetting
        if lat_ascending:
            data = ds.variables[data_var_name][:, lat_slice, lon_slice]
        else:
            # Original file has descending lats -> flip index
            n_lat = len(lats_full)
            rev_lat_slice = slice(n_lat - lat_idx[-1] - 1, n_lat - lat_idx[0])
            data = ds.variables[data_var_name][:, rev_lat_slice, lon_slice]
            data = data[:, ::-1, :]  # flip to ascending
    else:
        lats = lats_full
        lons = lons_full
        if lat_ascending:
            data = ds.variables[data_var_name][:]
        else:
            data = ds.variables[data_var_name][:, ::-1, :]

    ds.close()

    # Convert masked array to regular array (fill NaN)
    if hasattr(data, 'filled'):
        data = data.filled(np.nan)

    return np.asarray(data, dtype=np.float32), times, np.asarray(lats), np.asarray(lons)


def build_month_list(start_date, end_date):
    """Return list of (year, month) tuples covering the date range."""
    months = []
    d = datetime(start_date.year, start_date.month, 1)
    while d <= end_date:
        months.append((d.year, d.month))
        if d.month == 12:
            d = datetime(d.year + 1, 1, 1)
        else:
            d = datetime(d.year, d.month + 1, 1)
    return months


def regrid_to_lcc(cmfd_lats, cmfd_lons, data_2d, xlat_2d, xlon_2d, method='linear'):
    """
    Regrid a 2D field from CMFD regular lat/lon to WRF-Hydro LCC grid
    using RegularGridInterpolator (fast for regular source grids).

    Parameters
    ----------
    cmfd_lats : 1D array, ascending latitudes
    cmfd_lons : 1D array, ascending longitudes
    data_2d : 2D array (nlat, nlon)
    xlat_2d : 2D array of target latitudes (south_north, west_east)
    xlon_2d : 2D array of target longitudes (south_north, west_east)
    method : 'linear' or 'nearest'

    Returns
    -------
    result : 2D array on LCC grid (south_north, west_east)
    """
    # Create interpolator on regular grid
    interp = RegularGridInterpolator(
        (cmfd_lats, cmfd_lons), data_2d,
        method=method,
        bounds_error=False,
        fill_value=None  # extrapolate using nearest
    )

    # Target points: (lat, lon) pairs
    target_points = np.column_stack([xlat_2d.ravel(), xlon_2d.ravel()])
    result = interp(target_points)

    return result.reshape(xlat_2d.shape).astype(np.float32)


def temporal_interpolate_3hr_to_hourly(data_3hr, times_3hr, hourly_times, var_type):
    """
    Interpolate a single variable from 3-hourly to hourly.

    Parameters
    ----------
    data_3hr : 3D array (ntime_3hr, nlat, nlon)
    times_3hr : list of datetime
    hourly_times : list of datetime
    var_type : 'linear' or 'step'
        'step' = piecewise constant (precip, SW radiation)
        'linear' = linear interpolation (temp, pressure, etc.)

    Returns
    -------
    data_hourly : 3D array (nhours, nlat, nlon)
    """
    n3hr = len(times_3hr)
    nhours = len(hourly_times)
    shape = data_3hr.shape[1:]  # (nlat, nlon)
    result = np.zeros((nhours, *shape), dtype=np.float32)

    # Convert to hours since first timestep
    t0 = times_3hr[0]
    hrs_3hr = np.array([(t - t0).total_seconds() / 3600.0 for t in times_3hr])
    hrs_hourly = np.array([(t - t0).total_seconds() / 3600.0 for t in hourly_times])

    for ih in range(nhours):
        h = hrs_hourly[ih]
        # Find bracket: idx such that hrs_3hr[idx] <= h < hrs_3hr[idx+1]
        idx = int(np.searchsorted(hrs_3hr, h, side='right')) - 1
        idx = max(0, min(idx, n3hr - 1))
        idx_next = min(idx + 1, n3hr - 1)

        if var_type == 'step':
            # Piecewise constant: use value at bracket start
            result[ih] = data_3hr[idx]
        else:
            # Linear interpolation
            if idx < idx_next and hrs_3hr[idx_next] > hrs_3hr[idx]:
                frac = (h - hrs_3hr[idx]) / (hrs_3hr[idx_next] - hrs_3hr[idx])
                frac = max(0.0, min(1.0, frac))
                result[ih] = (1.0 - frac) * data_3hr[idx] + frac * data_3hr[idx_next]
            else:
                result[ih] = data_3hr[idx]

    return result


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
    ds = nc.Dataset(str(filepath), 'w', format='NETCDF4')

    # Dimensions
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

    # Meteorological variables
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


def elevation_correction(t2d, psfc, q2d, hgt_target, hgt_source_interp):
    """
    Apply elevation-based corrections to temperature and pressure.

    When the WRF-Hydro grid is finer than CMFD, there can be significant
    elevation differences between the coarse CMFD cell mean elevation and
    the fine-resolution WRF-Hydro cell elevation.

    Parameters
    ----------
    t2d : 2D array, temperature (K)
    psfc : 2D array, surface pressure (Pa)
    q2d : 2D array, specific humidity (kg/kg)
    hgt_target : 2D array, WRF-Hydro cell elevations (m)
    hgt_source_interp : 2D array, CMFD elevation interpolated to WRF-Hydro grid (m)

    Returns
    -------
    t2d_corrected, psfc_corrected : 2D arrays
    """
    delta_z = hgt_target - hgt_source_interp  # m

    # Temperature lapse rate correction: -6.5 K/km
    t2d_corr = t2d - 0.0065 * delta_z

    # Pressure correction: hypsometric equation
    # P_target = P_source * exp(-g * dz / (R * Tv))
    # where Tv = T * (1 + 0.61 * q) is virtual temperature
    tv = t2d_corr * (1.0 + 0.61 * q2d)
    tv = np.maximum(tv, 200.0)  # prevent division by zero
    psfc_corr = psfc * np.exp(-9.80665 * delta_z / (287.0 * tv))

    return t2d_corr.astype(np.float32), psfc_corr.astype(np.float32)


def estimate_cmfd_elevation(cmfd_lats, cmfd_lons, pres_3hr, temp_3hr):
    """
    Estimate CMFD cell elevations from surface pressure using
    the barometric formula.

    z ~ (T / 0.0065) * (1 - (P / 101325)^(R*0.0065/g))
    where R*0.0065/g = 287 * 0.0065 / 9.80665 ~ 0.19026

    Uses time-averaged pressure and temperature for stability.

    Parameters
    ----------
    cmfd_lats : 1D array
    cmfd_lons : 1D array
    pres_3hr : 3D array (ntime, nlat, nlon) in Pa
    temp_3hr : 3D array (ntime, nlat, nlon) in K

    Returns
    -------
    hgt_cmfd : 2D array (nlat, nlon) estimated elevation in metres
    """
    # Time-average
    p_mean = np.nanmean(pres_3hr, axis=0)
    t_mean = np.nanmean(temp_3hr, axis=0)

    # Avoid issues with extreme values
    p_mean = np.clip(p_mean, 10000.0, 110000.0)
    t_mean = np.clip(t_mean, 200.0, 350.0)

    exponent = 287.0 * 0.0065 / 9.80665  # ~0.19026
    hgt = (t_mean / 0.0065) * (1.0 - (p_mean / 101325.0) ** exponent)

    return hgt.astype(np.float32)


# ===================================================================
# Main processing
# ===================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Convert CMFD NetCDF forcing directly to WRF-Hydro LDASIN files (Option A)')
    parser.add_argument('--cmfd_dir', type=str,
                        default='data/forcing/Data_forcing_03hr_010deg',
                        help='CMFD data root directory')
    parser.add_argument('--geo_em', required=True,
                        help='geo_em.d01.nc for target LCC grid (XLAT_M, XLONG_M, HGT_M)')
    parser.add_argument('--domain_json', required=True,
                        help='domain_def.json from define_lambert_domain.py')
    parser.add_argument('--output_dir', required=True,
                        help='Output directory for LDASIN files')
    parser.add_argument('--start_date', required=True,
                        help='Start date YYYY-MM-DD')
    parser.add_argument('--end_date', required=True,
                        help='End date YYYY-MM-DD (inclusive)')
    parser.add_argument('--resolution', type=float, default=0.1,
                        help='WRF-Hydro LSM resolution in degrees (default 0.1, info only)')
    parser.add_argument('--elev_correct', action='store_true', default=True,
                        help='Apply elevation correction (default: True)')
    parser.add_argument('--no_elev_correct', action='store_true',
                        help='Disable elevation correction')
    parser.add_argument('--buffer_deg', type=float, default=1.0,
                        help='Buffer around domain in degrees for CMFD clipping (default 1.0)')
    args = parser.parse_args()

    start_date = datetime.strptime(args.start_date, '%Y-%m-%d')
    end_date = datetime.strptime(args.end_date, '%Y-%m-%d')
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    cmfd_dir = Path(args.cmfd_dir)
    do_elev_correct = not args.no_elev_correct

    duration_days = (end_date - start_date).days + 1
    nhours_expected = duration_days * 24

    print("=" * 70)
    print("CMFD-to-LDASIN Direct Forcing Converter (Option A)")
    print("=" * 70)
    print(f"  CMFD dir:    {cmfd_dir}")
    print(f"  Period:      {start_date.date()} to {end_date.date()} ({duration_days} days)")
    print(f"  Expected:    {nhours_expected} hourly LDASIN files")
    print(f"  Elev corr:   {'enabled' if do_elev_correct else 'disabled'}")

    # ------------------------------------------------------------------
    # 1. Read WRF-Hydro target grid from geo_em
    # ------------------------------------------------------------------
    print(f"\n[1/5] Reading WRF-Hydro target grid from {args.geo_em}...")
    ds_geo = nc.Dataset(args.geo_em)
    xlat_2d = np.asarray(ds_geo.variables['XLAT_M'][0, :, :])   # (sn, we)
    xlon_2d = np.asarray(ds_geo.variables['XLONG_M'][0, :, :])
    hgt_target = None
    if 'HGT_M' in ds_geo.variables:
        hgt_target = np.asarray(ds_geo.variables['HGT_M'][0, :, :])
    grid_sn, grid_we = xlat_2d.shape
    ds_geo.close()

    print(f"  LCC grid:  {grid_sn} x {grid_we} = {grid_sn * grid_we} cells")
    print(f"  Lat range: [{xlat_2d.min():.4f}, {xlat_2d.max():.4f}]")
    print(f"  Lon range: [{xlon_2d.min():.4f}, {xlon_2d.max():.4f}]")
    if hgt_target is not None:
        print(f"  HGT range: [{hgt_target.min():.1f}, {hgt_target.max():.1f}] m")

    # Read domain JSON for info
    with open(args.domain_json) as f:
        domain = json.load(f)
    dx = domain.get('dx', 1000.0)
    print(f"  DX:        {dx:.0f} m ({dx/1000:.1f} km)")

    # Determine the CMFD clipping region (domain extent + buffer)
    buf = args.buffer_deg
    lat_range = (float(xlat_2d.min()) - buf, float(xlat_2d.max()) + buf)
    lon_range = (float(xlon_2d.min()) - buf, float(xlon_2d.max()) + buf)
    print(f"  CMFD clip: lat=[{lat_range[0]:.2f},{lat_range[1]:.2f}] "
          f"lon=[{lon_range[0]:.2f},{lon_range[1]:.2f}]")

    # ------------------------------------------------------------------
    # 2. Determine months to process
    # ------------------------------------------------------------------
    months_to_process = build_month_list(start_date, end_date)
    print(f"\n[2/5] Processing {len(months_to_process)} month(s): "
          f"{months_to_process[0]} to {months_to_process[-1]}")

    # ------------------------------------------------------------------
    # 3. Detect CMFD coordinate names from first file
    # ------------------------------------------------------------------
    print("\n[3/5] Auto-detecting CMFD coordinate names...")
    first_var = CMFD_VAR_MAP[0]  # temp
    first_file = find_cmfd_file(cmfd_dir, first_var[1], first_var[2],
                                months_to_process[0][0], months_to_process[0][1])
    time_name, lat_name, lon_name, data_var = detect_cmfd_coords(first_file)
    print(f"  Time: '{time_name}', Lat: '{lat_name}', Lon: '{lon_name}', "
          f"Data: '{data_var}'")

    # ------------------------------------------------------------------
    # 4. Process month by month
    # ------------------------------------------------------------------
    print(f"\n[4/5] Reading CMFD data and generating LDASIN files...")

    n_written = 0
    wall_t0 = _time.time()

    # Track elevation correction data across months
    cmfd_hgt_interp = None

    for mi, (year, month) in enumerate(months_to_process):
        month_t0 = _time.time()
        print(f"\n  --- {year}-{month:02d} (month {mi+1}/{len(months_to_process)}) ---")

        # 4a. Read all 7 CMFD variables for this month
        cmfd_data = {}
        cmfd_lats = None
        cmfd_lons = None
        cmfd_times = None

        for var_name, subdir, prefix in CMFD_VAR_MAP:
            data, times, lats, lons = read_cmfd_month(
                cmfd_dir, (var_name, subdir, prefix),
                year, month,
                lat_range=lat_range, lon_range=lon_range
            )
            cmfd_data[var_name] = data
            if cmfd_lats is None:
                cmfd_lats = lats
                cmfd_lons = lons
                cmfd_times = times

        ntime_3hr = len(cmfd_times)
        nlat_cmfd = len(cmfd_lats)
        nlon_cmfd = len(cmfd_lons)
        print(f"    CMFD: {ntime_3hr} 3-hourly steps, "
              f"{nlat_cmfd}x{nlon_cmfd} spatial cells")

        # 4b. Compute CMFD elevation estimate (for elevation correction)
        #     Do this once from the first month's pressure and temperature
        if do_elev_correct and hgt_target is not None and cmfd_hgt_interp is None:
            print("    Computing CMFD elevation estimate from pressure...")
            hgt_cmfd = estimate_cmfd_elevation(
                cmfd_lats, cmfd_lons,
                cmfd_data['pres'], cmfd_data['temp']
            )
            # Regrid CMFD elevation to WRF-Hydro grid
            cmfd_hgt_interp = regrid_to_lcc(
                cmfd_lats, cmfd_lons, hgt_cmfd,
                xlat_2d, xlon_2d, method='linear'
            )
            delta_z = hgt_target - cmfd_hgt_interp
            print(f"    CMFD elev range: [{hgt_cmfd.min():.0f}, {hgt_cmfd.max():.0f}] m")
            print(f"    Delta-z range:   [{delta_z.min():.0f}, {delta_z.max():.0f}] m")
            if np.abs(delta_z).max() < 50:
                print("    Delta-z < 50m everywhere; elevation correction will be minimal")

        # 4c. Determine hourly timesteps within this month that fall
        #     within the requested date range
        # Month boundaries
        month_start = datetime(year, month, 1)
        if month == 12:
            month_end_exclusive = datetime(year + 1, 1, 1)
        else:
            month_end_exclusive = datetime(year, month + 1, 1)

        # Clip to requested range
        eff_start = max(start_date, month_start)
        eff_end_exclusive = min(end_date + timedelta(days=1), month_end_exclusive)

        # Build hourly time axis for this month's chunk
        hourly_times = []
        t = eff_start
        while t < eff_end_exclusive:
            hourly_times.append(t)
            t += timedelta(hours=1)

        if not hourly_times:
            print(f"    No hourly steps in range for this month, skipping.")
            continue

        print(f"    Hourly output: {len(hourly_times)} steps "
              f"({hourly_times[0]} to {hourly_times[-1]})")

        # 4d. Temporal interpolation: 3-hourly -> hourly
        #     Step variables: precip, SWDOWN
        #     Linear variables: everything else
        interp_type = {
            'temp': 'linear',
            'prec': 'step',
            'pres': 'linear',
            'srad': 'step',
            'lrad': 'linear',
            'shum': 'linear',
            'wind': 'linear',
        }

        hourly_cmfd = {}
        for var_name in cmfd_data:
            hourly_cmfd[var_name] = temporal_interpolate_3hr_to_hourly(
                cmfd_data[var_name], cmfd_times, hourly_times, interp_type[var_name]
            )

        # Free 3-hourly data
        del cmfd_data

        # 4e. For each hourly timestep: regrid + convert + write
        report_every = max(1, len(hourly_times) // 10)

        for ih, t in enumerate(hourly_times):
            # Regrid each CMFD variable to LCC grid
            temp_lcc = regrid_to_lcc(cmfd_lats, cmfd_lons, hourly_cmfd['temp'][ih],
                                     xlat_2d, xlon_2d)
            prec_lcc = regrid_to_lcc(cmfd_lats, cmfd_lons, hourly_cmfd['prec'][ih],
                                     xlat_2d, xlon_2d)
            pres_lcc = regrid_to_lcc(cmfd_lats, cmfd_lons, hourly_cmfd['pres'][ih],
                                     xlat_2d, xlon_2d)
            srad_lcc = regrid_to_lcc(cmfd_lats, cmfd_lons, hourly_cmfd['srad'][ih],
                                     xlat_2d, xlon_2d)
            lrad_lcc = regrid_to_lcc(cmfd_lats, cmfd_lons, hourly_cmfd['lrad'][ih],
                                     xlat_2d, xlon_2d)
            shum_lcc = regrid_to_lcc(cmfd_lats, cmfd_lons, hourly_cmfd['shum'][ih],
                                     xlat_2d, xlon_2d)
            wind_lcc = regrid_to_lcc(cmfd_lats, cmfd_lons, hourly_cmfd['wind'][ih],
                                     xlat_2d, xlon_2d)

            # Unit conversions
            # T2D: CMFD temp is already in K
            t2d = temp_lcc
            # Q2D: CMFD shum is already kg/kg
            q2d = shum_lcc
            # U2D, V2D: split scalar wind at 45 degrees
            factor = np.float32(np.sqrt(2.0) / 2.0)  # 0.7071
            u2d = wind_lcc * factor
            v2d = wind_lcc * factor
            # PSFC: CMFD pres is already Pa
            psfc = pres_lcc
            # SWDOWN: direct, cap at solar constant
            swdown = np.clip(srad_lcc, 0.0, 1361.0)
            # LWDOWN: direct
            lwdown = lrad_lcc
            # RAINRATE: CMFD prec is already kg/m^2/s = mm/s
            rainrate = np.maximum(prec_lcc, 0.0)

            # Elevation correction
            if (do_elev_correct and hgt_target is not None
                    and cmfd_hgt_interp is not None):
                t2d, psfc = elevation_correction(
                    t2d, psfc, q2d, hgt_target, cmfd_hgt_interp
                )

            # Physical constraints
            q2d = np.clip(q2d, 0.0, 0.05)
            psfc = np.maximum(psfc, 10000.0)
            swdown = np.maximum(swdown, 0.0)
            lwdown = np.maximum(lwdown, 0.0)

            grids = {
                'T2D': t2d,
                'Q2D': q2d,
                'U2D': u2d,
                'V2D': v2d,
                'PSFC': psfc,
                'SWDOWN': swdown,
                'LWDOWN': lwdown,
                'RAINRATE': rainrate,
            }

            # Write LDASIN file
            fname = t.strftime('%Y%m%d%H') + '.LDASIN_DOMAIN1'
            write_ldasin(output_dir / fname, t, grid_sn, grid_we, grids)
            n_written += 1

            if (ih + 1) % report_every == 0 or ih == len(hourly_times) - 1:
                elapsed = _time.time() - month_t0
                rate = (ih + 1) / elapsed if elapsed > 0 else 0
                print(f"    [{ih+1}/{len(hourly_times)}] {fname}  "
                      f"({rate:.1f} files/s)")

        # Free hourly data
        del hourly_cmfd

    wall_elapsed = _time.time() - wall_t0

    # ------------------------------------------------------------------
    # 5. Summary and validation
    # ------------------------------------------------------------------
    print(f"\n[5/5] Summary")
    print(f"  Written:  {n_written} LDASIN files")
    print(f"  Expected: {nhours_expected}")
    print(f"  Time:     {wall_elapsed:.1f}s ({wall_elapsed/60:.1f} min)")
    if n_written > 0:
        print(f"  Rate:     {n_written / wall_elapsed:.1f} files/s")

    if n_written != nhours_expected:
        print(f"  WARNING: wrote {n_written} files but expected {nhours_expected}")

    # Sanity check first and last files
    for label, dt in [("First", start_date), ("Last", end_date + timedelta(hours=23))]:
        fname = dt.strftime('%Y%m%d%H') + '.LDASIN_DOMAIN1'
        fpath = output_dir / fname
        if fpath.exists():
            ds = nc.Dataset(str(fpath))
            print(f"\n  --- {label} file: {fname} ---")
            for vname in ['T2D', 'Q2D', 'U2D', 'V2D', 'PSFC', 'SWDOWN', 'LWDOWN', 'RAINRATE']:
                arr = ds.variables[vname][0]
                print(f"    {vname:10s}: min={arr.min():12.4f}  "
                      f"max={arr.max():12.4f}  mean={arr.mean():12.4f}")
            ds.close()
        else:
            print(f"\n  WARNING: {label} file not found: {fpath}")

    print(f"\nDone! LDASIN files in: {output_dir}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
