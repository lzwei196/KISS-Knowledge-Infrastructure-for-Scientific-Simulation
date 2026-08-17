#!/usr/bin/env python3
"""
convert_forcing_to_ldasin.py  --  WRF-Hydro Phase 3, Tool 1
==============================================================
Convert VIC forcing files (3-hourly, tab-separated ASCII) into hourly
LDASIN_DOMAIN1 NetCDF files expected by WRF-Hydro / NoahMP offline.

VIC forcing columns (3-hourly, tab-separated, no header):
  Col 0: Temperature   (deg C)     -> T2D   (K)         +273.15
  Col 1: Precipitation (mm/3hr)    -> RAINRATE (mm/s)    /10800
  Col 2: Pressure      (kPa)       -> PSFC  (Pa)         *1000
  Col 3: Shortwave     (W/m^2)     -> SWDOWN (W/m^2)     direct
  Col 4: Longwave      (W/m^2)     -> LWDOWN (W/m^2)     direct
  Col 5: Vapor press.  (kPa)       -> Q2D   (kg/kg)      formula
  Col 6: Wind speed    (m/s)       -> U2D, V2D (m/s)     wind*cos(45), wind*sin(45)

Temporal interpolation: VIC 3-hourly -> LDASIN hourly
  - RAINRATE & SWDOWN: step (constant within the 3-hour bracket)
  - T2D, PSFC, LWDOWN, Q2D, U2D, V2D: linear interpolation

Spatial interpolation: scatter lat/lon VIC cells -> LCC grid via
scipy.interpolate.griddata (linear, with nearest-neighbor fill).

Usage
-----
    python convert_forcing_to_ldasin.py \\
        --forcing_dir  outputs/chaohe_2000_2010_025deg/vic_temp/forcing/forcing_final \\
        --grid_nc      outputs/chaohe_2000_2010_025deg/vic_temp/grid/basin_grid.nc \\
        --geo_em       outputs/chaohe_wrf_test/DOMAIN/geo_em.d01.nc \\
        --domain_json  outputs/chaohe_wrf_test/domain_def.json \\
        --output_dir   outputs/chaohe_wrf_test/FORCING \\
        --start_date   2001-01-01 \\
        --end_date     2001-01-07 \\
        --source_timestep 10800
"""

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import netCDF4 as nc
import numpy as np
from scipy.interpolate import griddata
sys.path.insert(0, "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect")
from ki_tools_common.units import celsius_to_kelvin, kelvin_to_celsius


# ===================================================================
# Unit conversion helpers
# ===================================================================

def celsius_to_kelvin(t_c):
    return np.asarray(t_c) + 273.15


def precip_mm3hr_to_mmps(p):
    """mm per 3-hour period -> mm/s (= kg/m^2/s)."""
    return p / 10800.0


def kpa_to_pa(p):
    return p * 1000.0


def vapor_pressure_to_specific_humidity(vp_kpa, psfc_pa):
    """
    Convert vapor pressure (kPa) to specific humidity (kg/kg).
    q = 0.622 * e / (p - 0.378 * e)  where e and p in the same unit.
    """
    e_pa = vp_kpa * 1000.0  # kPa -> Pa
    q = 0.622 * e_pa / (psfc_pa - 0.378 * e_pa)
    return np.clip(q, 0.0, 0.05)  # sanity clamp


def wind_to_uv(wind):
    """Split scalar wind into U and V assuming 45-degree angle."""
    factor = np.sqrt(2.0) / 2.0  # 0.7071
    return wind * factor, wind * factor


# ===================================================================
# I/O helpers
# ===================================================================

def load_vic_forcing(forcing_dir, grid_nc_path, start_date, end_date, source_dt,
                     forcing_start_override=None):
    """
    Load all VIC forcing files into a structured dict.

    Returns
    -------
    lats : array (ncells,)
    lons : array (ncells,)
    data : dict  var_name -> array (ntimes, ncells)
    times_3hr : list of datetime objects for each 3-hourly step
    """
    # Read grid cell coordinates from basin_grid.nc
    ds = nc.Dataset(grid_nc_path)
    y_vals = ds.variables['y'][:]  # latitudes, descending
    x_vals = ds.variables['x'][:]  # longitudes, ascending
    mask = ds.variables['mask'][:]
    ds.close()

    # Build list of valid (lat, lon) pairs in the same order as cell_id
    cell_coords = []
    for iy in range(len(y_vals)):
        for ix in range(len(x_vals)):
            if not np.isnan(mask[iy, ix]) and mask[iy, ix] > 0:
                cell_coords.append((float(y_vals[iy]), float(x_vals[ix])))

    ncells = len(cell_coords)
    print(f"  Grid has {ncells} valid VIC cells")

    # Determine the forcing file start date — VIC forcing starts at
    # the beginning of the run (we read from config or infer from first
    # year in the file name pattern).
    # Scan forcing dir for files to find the prefix pattern
    forcing_dir = Path(forcing_dir)
    forcing_files = sorted(forcing_dir.iterdir())
    if not forcing_files:
        raise FileNotFoundError(f"No forcing files in {forcing_dir}")

    # Map (lat, lon) -> file path from filenames like chaohe_0.25deg_41.3750_115.3750
    file_map = {}
    for fp in forcing_files:
        parts = fp.name.rsplit('_', 2)  # prefix, lat, lon
        if len(parts) >= 3:
            try:
                lat = float(parts[-2])
                lon = float(parts[-1])
                file_map[(lat, lon)] = fp
            except ValueError:
                continue

    # We also need to know what the forcing file global start date is.
    # The VIC run config for chaohe was 2000-2010, so forcing starts
    # 2000-01-01 00:00.  We'll infer from the first year by reading
    # the soil param or just from the config.  Actually we need the user
    # to tell us, or we figure it out from the file length.
    # For robustness: compute from the oldest file's line count.
    # But the user should pass --forcing_start if ambiguous.
    # For now, we need to figure out the start from context.
    # The VIC forcing for chaohe starts 2000-01-01 (YEAR_START in config).
    # We'll detect it from the number of lines divided by steps/day.

    # Read one file to get total line count
    sample_file = list(file_map.values())[0]
    with open(sample_file) as f:
        total_lines = sum(1 for _ in f)

    steps_per_day = 86400 // source_dt  # 8 for 3-hourly
    total_days = total_lines // steps_per_day
    print(f"  Forcing files have {total_lines} lines = {total_days} days at {steps_per_day} steps/day")

    # Build the full time axis for the forcing files
    # Use override if provided, otherwise auto-detect
    forcing_start = None
    if forcing_start_override is not None:
        forcing_start = forcing_start_override
        forcing_end = forcing_start + timedelta(days=total_days)
        print(f"  Using user-specified forcing start: {forcing_start.date()}")
    else:
        pass  # Auto-detect below

    # Auto-detect: total_days starting from Jan 1 of some year should end at
    # Dec 31 of another year.  For 2000-2005 (6 years): 2192 days.
    # Try years:
    if forcing_start is None:
        for try_year in range(1979, 2030):
            d0 = datetime(try_year, 1, 1)
            d1 = d0 + timedelta(days=total_days)
            if d1.month == 1 and d1.day == 1:
                # Perfect: the forcing covers try_year to d1.year-1
                    if d0 <= start_date <= d1 and d0 <= end_date <= d1:
                        forcing_start = d0
                        forcing_end = d1
                        break
        if forcing_start is None:
            # Fallback
            for try_year in range(1979, 2030):
                d0 = datetime(try_year, 1, 1)
                d1 = d0 + timedelta(days=total_days)
                if d0 <= start_date and end_date <= d1:
                    forcing_start = d0
                    forcing_end = d1
                    break
    if forcing_start is None:
        raise RuntimeError(
            f"Cannot auto-detect forcing start date. "
            f"Total lines={total_lines}, total_days={total_days}, "
            f"requested period={start_date} to {end_date}"
        )

    print(f"  Auto-detected forcing period: {forcing_start.date()} to {(forcing_end - timedelta(days=1)).date()}")

    # Compute line offsets for the requested period
    offset_days = (start_date - forcing_start).days
    # We need data up to end_date + 1 day (to interpolate the last 3hr bracket)
    # but clamp to available data
    end_date_plus = end_date + timedelta(days=1)
    if end_date_plus > forcing_end:
        end_date_plus = forcing_end

    duration_days = (end_date_plus - start_date).days
    line_start = offset_days * steps_per_day
    line_count = duration_days * steps_per_day

    print(f"  Reading lines {line_start} to {line_start + line_count - 1} "
          f"({line_count} lines = {duration_days} days)")

    # Build 3-hourly time axis for the extracted period
    times_3hr = []
    t = start_date
    dt_step = timedelta(seconds=source_dt)
    for _ in range(line_count):
        times_3hr.append(t)
        t += dt_step

    # Read all cells
    # VIC cols: temp_C, precip_mm3h, pres_kPa, sw_wm2, lw_wm2, vp_kPa, wind_ms
    raw_data = np.zeros((line_count, ncells, 7), dtype=np.float32)

    missing_cells = []
    for ic, (lat, lon) in enumerate(cell_coords):
        # Round to match filename precision
        key = None
        for k in file_map:
            if abs(k[0] - lat) < 0.001 and abs(k[1] - lon) < 0.001:
                key = k
                break
        if key is None:
            missing_cells.append((lat, lon))
            continue

        fp = file_map[key]
        with open(fp) as f:
            lines = f.readlines()

        for it in range(line_count):
            idx = line_start + it
            if idx < len(lines):
                vals = lines[idx].strip().split()
                if len(vals) >= 7:
                    for j in range(7):
                        raw_data[it, ic, j] = float(vals[j])

    if missing_cells:
        print(f"  WARNING: {len(missing_cells)} cells not found in forcing dir: {missing_cells[:5]}...")

    lats = np.array([c[0] for c in cell_coords], dtype=np.float64)
    lons = np.array([c[1] for c in cell_coords], dtype=np.float64)

    return lats, lons, raw_data, times_3hr


def interpolate_to_lcc_grid(lats_vic, lons_vic, values_vic, xlat_2d, xlon_2d):
    """
    Scatter-interpolate VIC cell values onto the LCC grid.

    Parameters
    ----------
    lats_vic, lons_vic : 1D arrays of VIC cell centers (lat/lon)
    values_vic : 1D array of values at VIC cells
    xlat_2d, xlon_2d : 2D arrays of LCC grid lat/lon (south_north, west_east)

    Returns
    -------
    grid_2d : 2D array on the LCC grid
    """
    points = np.column_stack([lons_vic, lats_vic])
    xi = np.column_stack([xlon_2d.ravel(), xlat_2d.ravel()])

    # Linear interpolation, then fill remaining with nearest
    result = griddata(points, values_vic, xi, method='linear')
    mask_nan = np.isnan(result)
    if np.any(mask_nan):
        result_nn = griddata(points, values_vic, xi, method='nearest')
        result[mask_nan] = result_nn[mask_nan]

    return result.reshape(xlat_2d.shape)


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

    # Times variable — character array
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
        'T2D':      {'long_name': '2-m temperature',            'units': 'K'},
        'Q2D':      {'long_name': '2-m specific humidity',      'units': 'kg/kg'},
        'U2D':      {'long_name': '10-m U-component of wind',   'units': 'm/s'},
        'V2D':      {'long_name': '10-m V-component of wind',   'units': 'm/s'},
        'PSFC':     {'long_name': 'Surface pressure',           'units': 'Pa'},
        'SWDOWN':   {'long_name': 'Downward shortwave radiation flux', 'units': 'W/m^2'},
        'LWDOWN':   {'long_name': 'Downward longwave radiation flux',  'units': 'W/m^2'},
        'RAINRATE': {'long_name': 'Precipitation rate',         'units': 'mm s^-1'},
    }

    for vname in ['T2D', 'Q2D', 'U2D', 'V2D', 'PSFC', 'SWDOWN', 'LWDOWN', 'RAINRATE']:
        v = ds.createVariable(vname, 'f4', ('Time', 'south_north', 'west_east'),
                              fill_value=np.float32(1e20))
        v.missing_value = np.float32(1e20)
        for attr, val in var_meta[vname].items():
            setattr(v, attr, val)
        v[0, :, :] = data_dict[vname].astype(np.float32)

    ds.close()


# ===================================================================
# Temporal interpolation
# ===================================================================

def interpolate_hourly(raw_3hr, times_3hr, source_dt, start_date, end_date):
    """
    Interpolate 3-hourly VIC forcing to hourly.

    Parameters
    ----------
    raw_3hr : array (n3hr, ncells, 7)
    times_3hr : list of datetime (len n3hr)
    source_dt : int, seconds between VIC steps (10800)
    start_date, end_date : datetime

    Returns
    -------
    hourly_data : dict var_name -> array (nhours, ncells)
    hourly_times : list of datetime (len nhours)
    """
    # Build hourly time axis: start_date 00:00 to end_date 23:00
    hourly_times = []
    t = start_date
    end_exclusive = end_date + timedelta(days=1)
    while t < end_exclusive:
        hourly_times.append(t)
        t += timedelta(hours=1)
    nhours = len(hourly_times)
    ncells = raw_3hr.shape[1]

    print(f"  Generating {nhours} hourly LDASIN files for {ncells} cells")

    # Convert raw VIC columns to physical variables (still at 3-hourly)
    n3hr = raw_3hr.shape[0]
    temp_c  = raw_3hr[:, :, 0]
    precip  = raw_3hr[:, :, 1]  # mm/3hr
    pres_kpa = raw_3hr[:, :, 2]
    sw      = raw_3hr[:, :, 3]
    lw      = raw_3hr[:, :, 4]
    vp_kpa  = raw_3hr[:, :, 5]
    wind    = raw_3hr[:, :, 6]

    # Convert units at 3-hourly resolution
    t2d_3hr = celsius_to_kelvin(temp_c)
    rainrate_3hr = precip_mm3hr_to_mmps(precip)  # constant over 3hr bracket
    psfc_3hr = kpa_to_pa(pres_kpa)
    sw_3hr = sw
    lw_3hr = lw
    # Specific humidity requires pressure in Pa
    q2d_3hr = np.zeros_like(vp_kpa)
    for it in range(n3hr):
        q2d_3hr[it, :] = vapor_pressure_to_specific_humidity(vp_kpa[it, :], psfc_3hr[it, :])
    u2d_3hr, v2d_3hr = wind_to_uv(wind)

    # 3-hourly timestamps as fractional hours since start
    t0 = times_3hr[0]
    hrs_3hr = np.array([(t - t0).total_seconds() / 3600.0 for t in times_3hr])
    hrs_hourly = np.array([(t - t0).total_seconds() / 3600.0 for t in hourly_times])

    # Allocate output
    result = {
        'T2D':      np.zeros((nhours, ncells), dtype=np.float32),
        'PSFC':     np.zeros((nhours, ncells), dtype=np.float32),
        'LWDOWN':   np.zeros((nhours, ncells), dtype=np.float32),
        'Q2D':      np.zeros((nhours, ncells), dtype=np.float32),
        'U2D':      np.zeros((nhours, ncells), dtype=np.float32),
        'V2D':      np.zeros((nhours, ncells), dtype=np.float32),
        'SWDOWN':   np.zeros((nhours, ncells), dtype=np.float32),
        'RAINRATE': np.zeros((nhours, ncells), dtype=np.float32),
    }

    # For each hourly timestep, find the enclosing 3-hour bracket
    for ih in range(nhours):
        h = hrs_hourly[ih]
        # Find the bracket: i such that hrs_3hr[i] <= h < hrs_3hr[i+1]
        idx = np.searchsorted(hrs_3hr, h, side='right') - 1
        idx = max(0, min(idx, n3hr - 1))
        idx_next = min(idx + 1, n3hr - 1)

        # Fraction within the bracket [0, 1)
        if idx < idx_next:
            bracket_len = hrs_3hr[idx_next] - hrs_3hr[idx]
            frac = (h - hrs_3hr[idx]) / bracket_len if bracket_len > 0 else 0.0
        else:
            frac = 0.0

        # Linear interpolation for continuous variables
        result['T2D'][ih]    = t2d_3hr[idx]  + frac * (t2d_3hr[idx_next]  - t2d_3hr[idx])
        result['PSFC'][ih]   = psfc_3hr[idx] + frac * (psfc_3hr[idx_next] - psfc_3hr[idx])
        result['LWDOWN'][ih] = lw_3hr[idx]   + frac * (lw_3hr[idx_next]   - lw_3hr[idx])
        result['Q2D'][ih]    = q2d_3hr[idx]  + frac * (q2d_3hr[idx_next]  - q2d_3hr[idx])
        result['U2D'][ih]    = u2d_3hr[idx]  + frac * (u2d_3hr[idx_next]  - u2d_3hr[idx])
        result['V2D'][ih]    = v2d_3hr[idx]  + frac * (v2d_3hr[idx_next]  - v2d_3hr[idx])

        # Step (piecewise constant) for RAINRATE and SWDOWN
        result['SWDOWN'][ih]   = sw_3hr[idx]
        result['RAINRATE'][ih] = rainrate_3hr[idx]

    return result, hourly_times


# ===================================================================
# Main
# ===================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Convert VIC forcing to WRF-Hydro LDASIN_DOMAIN1 NetCDF files')
    parser.add_argument('--forcing_dir', required=True,
                        help='Directory containing VIC forcing ASCII files')
    parser.add_argument('--grid_nc', required=True,
                        help='basin_grid.nc with VIC cell coordinates')
    parser.add_argument('--geo_em', required=True,
                        help='geo_em.d01.nc with LCC grid lat/lon')
    parser.add_argument('--domain_json', required=True,
                        help='domain_def.json from Phase 1')
    parser.add_argument('--output_dir', required=True,
                        help='Output directory for LDASIN files')
    parser.add_argument('--start_date', required=True,
                        help='Start date YYYY-MM-DD')
    parser.add_argument('--end_date', required=True,
                        help='End date YYYY-MM-DD (inclusive)')
    parser.add_argument('--source_timestep', type=int, default=10800,
                        help='VIC forcing timestep in seconds (default 10800 = 3hr)')
    parser.add_argument('--forcing_start', type=str, default=None,
                        help='Override forcing start date YYYY-MM-DD (auto-detected if omitted)')
    args = parser.parse_args()

    start_date = datetime.strptime(args.start_date, '%Y-%m-%d')
    end_date = datetime.strptime(args.end_date, '%Y-%m-%d')
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("WRF-Hydro LDASIN Forcing Converter")
    print("=" * 60)
    print(f"  Period: {start_date.date()} to {end_date.date()}")
    duration_days = (end_date - start_date).days + 1
    nhours_expected = duration_days * 24
    print(f"  Duration: {duration_days} days -> {nhours_expected} hourly LDASIN files")

    # Read LCC grid coordinates and terrain from geo_em
    print("\n[1/4] Reading LCC grid from geo_em...")
    ds_geo = nc.Dataset(args.geo_em)
    xlat_2d = ds_geo.variables['XLAT_M'][0, :, :]  # (sn, we)
    xlon_2d = ds_geo.variables['XLONG_M'][0, :, :]
    hgt_1km = ds_geo.variables['HGT_M'][0, :, :] if 'HGT_M' in ds_geo.variables else None
    grid_sn, grid_we = xlat_2d.shape
    ds_geo.close()
    print(f"  LCC grid: {grid_sn} x {grid_we} = {grid_sn * grid_we} cells")
    print(f"  Lat range: [{xlat_2d.min():.4f}, {xlat_2d.max():.4f}]")
    print(f"  Lon range: [{xlon_2d.min():.4f}, {xlon_2d.max():.4f}]")
    if hgt_1km is not None:
        print(f"  HGT range: [{hgt_1km.min():.1f}, {hgt_1km.max():.1f}] m (for elevation correction)")

    # Read domain JSON for reference
    with open(args.domain_json) as f:
        domain = json.load(f)
    print(f"  Domain: {domain['e_we']}x{domain['e_sn']} @ {domain['dx']}m")

    # Load VIC forcing data
    print("\n[2/4] Loading VIC forcing data...")
    forcing_start_override = None
    if args.forcing_start:
        forcing_start_override = datetime.strptime(args.forcing_start, '%Y-%m-%d')

    lats_vic, lons_vic, raw_3hr, times_3hr = load_vic_forcing(
        args.forcing_dir, args.grid_nc, start_date, end_date, args.source_timestep,
        forcing_start_override=forcing_start_override,
    )
    print(f"  Loaded {raw_3hr.shape[0]} timesteps x {raw_3hr.shape[1]} cells")

    # Temporal interpolation to hourly
    print("\n[3/4] Temporal interpolation (3-hourly -> hourly)...")
    hourly_data, hourly_times = interpolate_hourly(
        raw_3hr, times_3hr, args.source_timestep, start_date, end_date
    )

    # Pre-compute VIC elevation interpolated to LCC grid (for elevation correction)
    hgt_vic_interp = None
    if hgt_1km is not None:
        # Estimate VIC cell elevations from the 1km DEM by averaging within each VIC cell
        # Simple approach: interpolate HGT_M at VIC cell locations
        from scipy.interpolate import griddata as gd_elev
        vic_elevs = []
        for lat, lon in zip(lats_vic, lons_vic):
            # Find nearest HGT value
            dist = np.sqrt((xlat_2d - lat)**2 + (xlon_2d - lon)**2)
            idx = np.unravel_index(dist.argmin(), dist.shape)
            vic_elevs.append(float(hgt_1km[idx]))
        vic_elevs = np.array(vic_elevs)
        hgt_vic_interp = interpolate_to_lcc_grid(lats_vic, lons_vic, vic_elevs, xlat_2d, xlon_2d)
        delta_z_max = np.abs(hgt_1km - hgt_vic_interp).max()
        print(f"  Elevation correction enabled: max Δz = {delta_z_max:.0f} m")

    # Write LDASIN files
    print(f"\n[4/4] Writing {len(hourly_times)} LDASIN files with spatial interpolation...")
    n_written = 0
    report_interval = max(1, len(hourly_times) // 20)

    for ih, t in enumerate(hourly_times):
        # Spatial interpolation for each variable
        grids = {}
        for vname in ['T2D', 'Q2D', 'U2D', 'V2D', 'PSFC', 'SWDOWN', 'LWDOWN', 'RAINRATE']:
            vals = hourly_data[vname][ih, :]
            grids[vname] = interpolate_to_lcc_grid(
                lats_vic, lons_vic, vals, xlat_2d, xlon_2d
            )

        # Enforce physical constraints
        grids['RAINRATE'] = np.maximum(grids['RAINRATE'], 0.0)
        grids['SWDOWN'] = np.clip(grids['SWDOWN'], 0.0, 1361.0)  # Cap at solar constant
        grids['Q2D'] = np.clip(grids['Q2D'], 0.0, 0.05)
        grids['PSFC'] = np.maximum(grids['PSFC'], 10000.0)

        # Elevation correction: adjust T2D and PSFC for terrain height difference
        # between the coarse VIC grid (~25km) and the fine WRF-Hydro grid (1km)
        # This prevents energy balance crashes at mountain cells (dt_v007)
        if hgt_1km is not None and hgt_vic_interp is not None:
            delta_z = hgt_1km - hgt_vic_interp  # meters
            grids['T2D'] = grids['T2D'] - 0.0065 * delta_z  # lapse rate 6.5 K/km
            Tv = grids['T2D'] * (1.0 + 0.61 * grids['Q2D'])
            Tv = np.maximum(Tv, 200.0)  # prevent division by zero
            grids['PSFC'] = grids['PSFC'] * np.exp(-9.80665 * delta_z / (287.0 * Tv))

        # Write file
        fname = t.strftime('%Y%m%d%H') + '.LDASIN_DOMAIN1'
        write_ldasin(output_dir / fname, t, grid_sn, grid_we, grids)
        n_written += 1

        if n_written % report_interval == 0 or ih == len(hourly_times) - 1:
            print(f"  [{n_written}/{len(hourly_times)}] Wrote {fname}")

    print(f"\nDone! Wrote {n_written} LDASIN files to {output_dir}")

    # Sanity checks
    print("\n--- Sanity check (first file) ---")
    first_file = output_dir / (hourly_times[0].strftime('%Y%m%d%H') + '.LDASIN_DOMAIN1')
    ds = nc.Dataset(str(first_file))
    for vname in ['T2D', 'Q2D', 'U2D', 'V2D', 'PSFC', 'SWDOWN', 'LWDOWN', 'RAINRATE']:
        arr = ds.variables[vname][0]
        print(f"  {vname:10s}: min={arr.min():.4f}  max={arr.max():.4f}  mean={arr.mean():.4f}")
    ds.close()

    return 0


if __name__ == '__main__':
    sys.exit(main())
