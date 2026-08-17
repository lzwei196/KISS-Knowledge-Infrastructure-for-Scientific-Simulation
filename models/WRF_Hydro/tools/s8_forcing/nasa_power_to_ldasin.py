#!/usr/bin/env python3
"""
nasa_power_to_ldasin.py  --  Gridded NASA POWER to WRF-Hydro LDASIN
====================================================================
Fetch NASA POWER hourly data on a 0.5-degree grid covering the WRF-Hydro
domain, spatially interpolate to the Lambert Conformal Conic (LCC) grid,
apply elevation corrections, and write hourly LDASIN_DOMAIN1 files.

Unlike the old single-point broadcast (cmfd_to_wrfhydro.py), this tool
fetches **multiple** NASA POWER grid points to create genuine spatial
variability across the WRF-Hydro domain.

Pipeline:
  1. Read geo_em.d01.nc -> XLAT_M, XLONG_M, HGT_M (target LCC grid)
  2. Compute unique NASA POWER 0.5-deg grid points covering the domain
  3. Fetch data for each grid point (cache-aware, rate-limited)
  4. Build 3-D arrays (time x lat x lon) on the 0.5-deg regular grid
  5. Interpolate to LCC grid with RegularGridInterpolator
  6. Apply elevation correction for T2D and PSFC
  7. Write hourly LDASIN files

NASA POWER -> LDASIN unit conversions:
  NASA POWER      | Raw Unit         | LDASIN var | Target Unit | Conversion
  ----------------|------------------|------------|-------------|---------------------------
  T2M             | deg C            | T2D        | K           | +273.15
  QV2M            | g/kg             | Q2D        | kg/kg       | /1000
  PS              | kPa              | PSFC       | Pa          | *1000
  WS2M            | m/s              | U2D, V2D   | m/s         | *0.7071 each (45-deg split)
  PRECTOTCORR     | mm/day rate/hr   | RAINRATE   | mm/s        | /86400
  ALLSKY_SFC_SW_DWN| W/m2 (API) or MJ/m2/hr (cache) | SWDOWN | W/m2 | auto-detect
  ALLSKY_SFC_LW_DWN| W/m2 (API) or MJ/m2/hr (cache) | LWDOWN | W/m2 | auto-detect

Usage:
    python nasa_power_to_ldasin.py \\
        --geo_em  DOMAIN/geo_em.d01.nc \\
        --output_dir FORCING/ \\
        --start_date 2010-10-01 \\
        --end_date 2011-12-31

Author: HydroCraft / Zhang Jianyun Team
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
# Constants
# ===================================================================

NASA_POWER_URL = "https://power.larc.nasa.gov/api/temporal/hourly/point"
NASA_POWER_PARAMS = "T2M,PRECTOTCORR,PS,ALLSKY_SFC_SW_DWN,ALLSKY_SFC_LW_DWN,QV2M,WS2M"
POWER_RESOLUTION = 0.5  # degrees
DEFAULT_CACHE_DIR = Path("KISSPATH_DATA/nasa_power_cache/hourly")
REQUEST_DELAY = 1.2  # seconds between API calls

FILL_VALUE = -999.0

# Mutable config so main() can override the cache dir
_config = {"cache_dir": DEFAULT_CACHE_DIR}


# ===================================================================
# Reused functions from cmfd_to_ldasin.py
# ===================================================================

def regrid_to_lcc(src_lats, src_lons, data_2d, xlat_2d, xlon_2d, method='linear'):
    """
    Regrid a 2D field from a regular lat/lon grid to the WRF-Hydro LCC grid
    using RegularGridInterpolator.

    Parameters
    ----------
    src_lats : 1D array, ascending latitudes of source grid
    src_lons : 1D array, ascending longitudes of source grid
    data_2d  : 2D array (nlat, nlon) on source grid
    xlat_2d  : 2D array of target latitudes (south_north, west_east)
    xlon_2d  : 2D array of target longitudes (south_north, west_east)
    method   : 'linear' or 'nearest'

    Returns
    -------
    result : 2D array on LCC grid (south_north, west_east)
    """
    interp = RegularGridInterpolator(
        (src_lats, src_lons), data_2d,
        method=method,
        bounds_error=False,
        fill_value=np.nan  # NaN for out-of-bounds, then fill with nearest
    )
    target_points = np.column_stack([xlat_2d.ravel(), xlon_2d.ravel()])
    result = interp(target_points).reshape(xlat_2d.shape)

    # Fill NaN (out-of-bounds cells) with nearest valid value
    nan_mask = np.isnan(result)
    if nan_mask.any() and (~nan_mask).any():
        from scipy.ndimage import distance_transform_edt
        _, nearest_idx = distance_transform_edt(nan_mask, return_distances=True, return_indices=True)
        result[nan_mask] = result[nearest_idx[0][nan_mask], nearest_idx[1][nan_mask]]

    return result.astype(np.float32)


def elevation_correction(t2d, psfc, q2d, hgt_target, hgt_source_interp):
    """
    Apply elevation-based corrections to temperature and pressure.

    Parameters
    ----------
    t2d : 2D array, temperature (K)
    psfc : 2D array, surface pressure (Pa)
    q2d : 2D array, specific humidity (kg/kg)
    hgt_target : 2D array, WRF-Hydro cell elevations (m)
    hgt_source_interp : 2D array, source elevation interpolated to WRF-Hydro grid (m)

    Returns
    -------
    t2d_corrected, psfc_corrected : 2D arrays
    """
    delta_z = hgt_target - hgt_source_interp  # m

    # Temperature lapse rate correction: -6.5 K/km
    t2d_corr = t2d - 0.0065 * delta_z

    # Pressure correction: hypsometric equation
    tv = t2d_corr * (1.0 + 0.61 * q2d)
    tv = np.maximum(tv, 200.0)
    psfc_corr = psfc * np.exp(-9.80665 * delta_z / (287.0 * tv))

    return t2d_corr.astype(np.float32), psfc_corr.astype(np.float32)


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


# ===================================================================
# NASA POWER grid point management
# ===================================================================

def compute_power_grid_points(lat_min, lat_max, lon_min, lon_max, buffer_deg=0.5):
    """
    Compute the unique NASA POWER 0.5-degree grid points that cover the domain
    (with buffer).

    Returns
    -------
    lats : 1D array of ascending latitudes
    lons : 1D array of ascending longitudes
    """
    lat_lo = np.floor((lat_min - buffer_deg) / POWER_RESOLUTION) * POWER_RESOLUTION
    lat_hi = np.ceil((lat_max + buffer_deg) / POWER_RESOLUTION) * POWER_RESOLUTION
    lon_lo = np.floor((lon_min - buffer_deg) / POWER_RESOLUTION) * POWER_RESOLUTION
    lon_hi = np.ceil((lon_max + buffer_deg) / POWER_RESOLUTION) * POWER_RESOLUTION

    lats = np.arange(lat_lo, lat_hi + POWER_RESOLUTION * 0.1, POWER_RESOLUTION)
    lons = np.arange(lon_lo, lon_hi + POWER_RESOLUTION * 0.1, POWER_RESOLUTION)

    return lats, lons


# ===================================================================
# NASA POWER data fetching (cache-aware)
# ===================================================================

def _load_npz_cache(lat, lon, year):
    """Try to load data from the legacy NPZ cache."""
    key = f"{lat:.1f}_{lon:.1f}"
    npz_path = _config["cache_dir"] / key / f"{year}.npz"
    if npz_path.exists():
        try:
            arrays = np.load(str(npz_path), allow_pickle=True)
            return {k: arrays[k] for k in arrays.files}
        except Exception:
            pass
    return None


def _save_npz_cache(lat, lon, year, data_dict):
    """Save raw hourly arrays to NPZ cache."""
    key = f"{lat:.1f}_{lon:.1f}"
    cache_subdir = _config["cache_dir"] / key
    cache_subdir.mkdir(parents=True, exist_ok=True)
    npz_path = cache_subdir / f"{year}.npz"
    np.savez(str(npz_path), **{k: v.astype(np.float32) for k, v in data_dict.items()})


def _fetch_nasa_power_api(lat, lon, year):
    """
    Fetch hourly data from NASA POWER API for one year.

    Returns dict of {param_name: ndarray(8760 or 8784,)} with RAW values
    (no unit conversions applied).
    """
    import requests

    start_date = f"{year}0101"
    end_date = f"{year}1231"

    params = {
        "start": start_date,
        "end": end_date,
        "latitude": lat,
        "longitude": lon,
        "community": "RE",
        "parameters": NASA_POWER_PARAMS,
        "format": "JSON",
        "header": "false",
        "time-standard": "UTC",
    }

    for attempt in range(5):
        try:
            resp = requests.get(NASA_POWER_URL, params=params, timeout=180)
            if resp.status_code == 429:
                wait = 10 * (attempt + 1)
                print(f"    Rate limited, waiting {wait}s...", flush=True)
                _time.sleep(wait)
                continue
            resp.raise_for_status()
            data = resp.json()
            break
        except Exception as e:
            if attempt < 4:
                wait = 5 * (attempt + 1)
                print(f"    API error ({e}), retry in {wait}s...", flush=True)
                _time.sleep(wait)
            else:
                raise

    if "properties" not in data or "parameter" not in data["properties"]:
        raise RuntimeError(
            f"NASA POWER API returned unexpected format for ({lat},{lon}) {year}."
        )

    params_data = data["properties"]["parameter"]

    # Build sorted hourly arrays for each parameter
    result = {}
    for pname in NASA_POWER_PARAMS.split(","):
        hr_dict = params_data.get(pname, {})
        keys = sorted(hr_dict.keys())
        values = []
        for k in keys:
            v = hr_dict[k]
            values.append(float(v) if v != FILL_VALUE and v is not None else np.nan)
        result[pname] = np.array(values, dtype=np.float32)

    return result


def fetch_power_point(lat, lon, year):
    """
    Get hourly data for one grid point and one year, using cache if available.

    Returns dict of {param_name: ndarray(nhours,)} with RAW values.
    """
    # Try NPZ cache first
    cached = _load_npz_cache(lat, lon, year)
    if cached is not None:
        return cached

    # Fetch from API
    print(f"    Fetching ({lat:.1f}, {lon:.1f}) {year} from NASA POWER API...",
          flush=True)
    raw = _fetch_nasa_power_api(lat, lon, year)

    # Save to cache
    _save_npz_cache(lat, lon, year, raw)

    return raw


# ===================================================================
# Build spatial grids from point data
# ===================================================================

def _detect_radiation_units(sw_arr):
    """
    Auto-detect whether shortwave radiation is in W/m2 (API direct) or
    MJ/m2/hr (cached raw).

    Heuristic: daytime SW in W/m2 is typically 100-1000.
               daytime SW in MJ/m2/hr is typically 0.5-4.0.
    Use median of positive values as discriminator.
    """
    positives = sw_arr[sw_arr > 0.01]
    if len(positives) == 0:
        return "wm2"  # no data, assume W/m2
    median_val = np.nanmedian(positives)
    if median_val < 10.0:
        # Values like 0.5-4.0 -> MJ/m2/hr
        return "mjm2hr"
    else:
        # Values like 100-1000 -> W/m2
        return "wm2"


def build_hourly_grids(power_lats, power_lons, year, start_dt, end_dt):
    """
    Fetch NASA POWER data for all grid points and assemble into
    3-D arrays (nhours, nlat, nlon) with unit conversions applied.

    Returns
    -------
    grids : dict of {ldasin_var: ndarray(nhours, nlat, nlon)}
    hourly_times : list of datetime
    """
    nlat = len(power_lats)
    nlon = len(power_lons)

    # Build the hourly time axis for this year within [start_dt, end_dt]
    year_start = datetime(year, 1, 1, 0)
    is_leap = (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0))
    nhours_year = 8784 if is_leap else 8760

    # Determine which hours from this year fall within our date range
    eff_start = max(start_dt, datetime(year, 1, 1))
    eff_end = min(end_dt + timedelta(days=1), datetime(year + 1, 1, 1))
    if eff_start >= eff_end:
        return {}, []

    # Hour indices within the year
    start_hour_idx = int((eff_start - year_start).total_seconds() / 3600)
    end_hour_idx = int((eff_end - year_start).total_seconds() / 3600)
    start_hour_idx = max(0, start_hour_idx)
    end_hour_idx = min(nhours_year, end_hour_idx)
    nhours = end_hour_idx - start_hour_idx

    if nhours <= 0:
        return {}, []

    hourly_times = [year_start + timedelta(hours=start_hour_idx + i)
                    for i in range(nhours)]

    # Allocate raw arrays on POWER grid
    raw_vars = NASA_POWER_PARAMS.split(",")
    raw_grids = {v: np.full((nhours, nlat, nlon), np.nan, dtype=np.float32)
                 for v in raw_vars}

    # Fetch each grid point
    n_points = nlat * nlon
    n_fetched = 0
    n_cached = 0
    fetch_t0 = _time.time()

    for i, lat in enumerate(power_lats):
        for j, lon in enumerate(power_lons):
            data = fetch_power_point(lat, lon, year)

            was_cached = _load_npz_cache(lat, lon, year) is not None

            for v in raw_vars:
                arr = data.get(v, np.full(nhours_year, np.nan))
                if len(arr) >= end_hour_idx:
                    raw_grids[v][:, i, j] = arr[start_hour_idx:end_hour_idx]
                elif len(arr) > start_hour_idx:
                    n_avail = min(len(arr), end_hour_idx) - start_hour_idx
                    raw_grids[v][:n_avail, i, j] = arr[start_hour_idx:start_hour_idx + n_avail]

            n_fetched += 1
            # Rate-limit API calls (only if not cached)
            if not was_cached:
                _time.sleep(REQUEST_DELAY)

            if n_fetched % 5 == 0 or n_fetched == n_points:
                elapsed = _time.time() - fetch_t0
                print(f"    [{n_fetched}/{n_points}] grid points processed "
                      f"({elapsed:.0f}s)", flush=True)

    # --- Radiation units ---
    # NASA POWER API returns SW/LW in W/m2 directly. No conversion needed.
    # NOTE: Old cache (purged 2026-04-03) stored MJ/m2/hr. If cache is rebuilt
    # from the API, values are always W/m2. The _detect_radiation_units() function
    # is kept as a safety check but should always return "wm2".
    sw_sample = raw_grids["ALLSKY_SFC_SW_DWN"].ravel()
    rad_unit = _detect_radiation_units(sw_sample)
    if rad_unit == "mjm2hr":
        print(f"    WARNING: Detected MJ/m2/hr in cache — converting x277.78. "
              f"Consider purging cache at {_config['cache_dir']}", flush=True)
        rad_factor = 277.78
    else:
        rad_factor = 1.0

    # --- Apply unit conversions ---
    # T2D: C -> K
    t2d = raw_grids["T2M"] + 273.15

    # Q2D: g/kg -> kg/kg
    q2d = raw_grids["QV2M"] / 1000.0

    # PSFC: kPa -> Pa
    psfc = raw_grids["PS"] * 1000.0

    # U2D, V2D: split scalar wind at 45 degrees
    factor = np.float32(np.sqrt(2.0) / 2.0)  # 0.7071
    u2d = raw_grids["WS2M"] * factor
    v2d = raw_grids["WS2M"] * factor

    # RAINRATE: PRECTOTCORR is mm/day rate at each hour -> mm/s
    # Divide by 86400 (seconds per day) to get mm/s
    rainrate = np.maximum(raw_grids["PRECTOTCORR"] / 86400.0, 0.0)

    # SWDOWN: apply radiation factor (1.0 for API W/m2, 277.78 for old cache MJ/m2/hr)
    swdown = np.clip(raw_grids["ALLSKY_SFC_SW_DWN"] * rad_factor, 0.0, 1361.0)

    # LWDOWN: same factor
    lwdown = np.maximum(raw_grids["ALLSKY_SFC_LW_DWN"] * rad_factor, 0.0)

    # Replace NaN with reasonable defaults to avoid WRF-Hydro crashes
    t2d = np.nan_to_num(t2d, nan=280.0)
    q2d = np.nan_to_num(q2d, nan=0.005)
    psfc = np.nan_to_num(psfc, nan=101325.0)
    u2d = np.nan_to_num(u2d, nan=0.0)
    v2d = np.nan_to_num(v2d, nan=0.0)
    rainrate = np.nan_to_num(rainrate, nan=0.0)
    swdown = np.nan_to_num(swdown, nan=0.0)
    lwdown = np.nan_to_num(lwdown, nan=300.0)

    grids = {
        'T2D': t2d, 'Q2D': q2d, 'U2D': u2d, 'V2D': v2d,
        'PSFC': psfc, 'SWDOWN': swdown, 'LWDOWN': lwdown, 'RAINRATE': rainrate,
    }

    return grids, hourly_times


def estimate_power_elevation(psfc_3d, t2d_3d):
    """
    Estimate NASA POWER grid cell elevations from surface pressure and
    temperature using the barometric formula.

    Parameters
    ----------
    psfc_3d : 3D array (ntime, nlat, nlon) in Pa
    t2d_3d : 3D array (ntime, nlat, nlon) in K

    Returns
    -------
    hgt : 2D array (nlat, nlon) estimated elevation in metres
    """
    p_mean = np.nanmean(psfc_3d, axis=0)
    t_mean = np.nanmean(t2d_3d, axis=0)

    p_mean = np.clip(p_mean, 10000.0, 110000.0)
    t_mean = np.clip(t_mean, 200.0, 350.0)

    exponent = 287.0 * 0.0065 / 9.80665  # ~0.19026
    hgt = (t_mean / 0.0065) * (1.0 - (p_mean / 101325.0) ** exponent)

    return hgt.astype(np.float32)


# ===================================================================
# Main
# ===================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Convert gridded NASA POWER data to WRF-Hydro LDASIN files "
                    "with proper spatial interpolation")
    parser.add_argument('--geo_em', required=True,
                        help='geo_em.d01.nc for target LCC grid')
    parser.add_argument('--output_dir', required=True,
                        help='Output directory for LDASIN files')
    parser.add_argument('--start_date', required=True,
                        help='Start date YYYY-MM-DD')
    parser.add_argument('--end_date', required=True,
                        help='End date YYYY-MM-DD (inclusive)')
    parser.add_argument('--cache_dir', type=str,
                        default=str(DEFAULT_CACHE_DIR),
                        help='NASA POWER cache directory')
    parser.add_argument('--no_elev_correct', action='store_true',
                        help='Disable elevation correction')
    args = parser.parse_args()

    _config["cache_dir"] = Path(args.cache_dir)

    start_date = datetime.strptime(args.start_date, '%Y-%m-%d')
    end_date = datetime.strptime(args.end_date, '%Y-%m-%d')
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    do_elev_correct = not args.no_elev_correct

    duration_days = (end_date - start_date).days + 1
    nhours_expected = duration_days * 24

    print("=" * 70)
    print("NASA POWER -> LDASIN Gridded Forcing Converter")
    print("=" * 70)
    print(f"  Period:      {start_date.date()} to {end_date.date()} ({duration_days} days)")
    print(f"  Expected:    {nhours_expected} hourly LDASIN files")
    print(f"  Elev corr:   {'enabled' if do_elev_correct else 'disabled'}")
    print(f"  Cache:       {_config['cache_dir']}")

    # ------------------------------------------------------------------
    # 1. Read WRF-Hydro target grid from geo_em
    # ------------------------------------------------------------------
    print(f"\n[1/4] Reading WRF-Hydro target grid from {args.geo_em}...")
    ds_geo = nc.Dataset(args.geo_em)
    xlat_2d = np.asarray(ds_geo.variables['XLAT_M'][0, :, :])
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

    # ------------------------------------------------------------------
    # 2. Compute NASA POWER grid points
    # ------------------------------------------------------------------
    power_lats, power_lons = compute_power_grid_points(
        float(xlat_2d.min()), float(xlat_2d.max()),
        float(xlon_2d.min()), float(xlon_2d.max()),
        buffer_deg=0.5
    )
    n_points = len(power_lats) * len(power_lons)
    print(f"\n[2/4] NASA POWER grid: {len(power_lats)} lats x {len(power_lons)} lons "
          f"= {n_points} points")
    print(f"  Lat: [{power_lats[0]:.1f}, {power_lats[-1]:.1f}]")
    print(f"  Lon: [{power_lons[0]:.1f}, {power_lons[-1]:.1f}]")

    # ------------------------------------------------------------------
    # 3. Process year by year
    # ------------------------------------------------------------------
    years = list(range(start_date.year, end_date.year + 1))
    print(f"\n[3/4] Fetching + regridding for {len(years)} year(s): {years}")

    n_written = 0
    wall_t0 = _time.time()
    power_hgt_interp = None  # elevation on LCC grid (computed once)

    for yi, year in enumerate(years):
        year_t0 = _time.time()
        print(f"\n  --- Year {year} ({yi+1}/{len(years)}) ---")

        # Fetch and build spatial grids
        grids, hourly_times = build_hourly_grids(
            power_lats, power_lons, year, start_date, end_date
        )

        if not hourly_times:
            print(f"    No hourly steps in range for {year}, skipping.")
            continue

        nhours = len(hourly_times)
        print(f"    {nhours} hourly steps to write "
              f"({hourly_times[0]} to {hourly_times[-1]})")

        # Estimate POWER grid elevation (once, from first year)
        if do_elev_correct and hgt_target is not None and power_hgt_interp is None:
            print("    Computing source elevation estimate from pressure...")
            power_hgt = estimate_power_elevation(grids['PSFC'], grids['T2D'])
            # Regrid source elevation to LCC grid
            power_hgt_interp = regrid_to_lcc(
                power_lats, power_lons, power_hgt,
                xlat_2d, xlon_2d, method='nearest'
            )
            delta_z = hgt_target - power_hgt_interp
            print(f"    Source elev range: [{power_hgt.min():.0f}, {power_hgt.max():.0f}] m")
            print(f"    Delta-z range:    [{delta_z.min():.0f}, {delta_z.max():.0f}] m")

        # Regrid each hourly step to LCC and write LDASIN
        report_every = max(1, nhours // 10)

        for ih in range(nhours):
            t = hourly_times[ih]

            # Regrid each variable from POWER 0.5-deg to LCC grid
            ldasin_data = {}
            for vname in ['T2D', 'Q2D', 'U2D', 'V2D', 'PSFC', 'SWDOWN', 'LWDOWN',
                          'RAINRATE']:
                ldasin_data[vname] = regrid_to_lcc(
                    power_lats, power_lons, grids[vname][ih],
                    xlat_2d, xlon_2d
                )

            # Elevation correction
            if (do_elev_correct and hgt_target is not None
                    and power_hgt_interp is not None):
                ldasin_data['T2D'], ldasin_data['PSFC'] = elevation_correction(
                    ldasin_data['T2D'], ldasin_data['PSFC'],
                    ldasin_data['Q2D'], hgt_target, power_hgt_interp
                )

            # Physical constraints
            ldasin_data['Q2D'] = np.clip(ldasin_data['Q2D'], 0.0, 0.05)
            ldasin_data['PSFC'] = np.maximum(ldasin_data['PSFC'], 10000.0)
            ldasin_data['SWDOWN'] = np.maximum(ldasin_data['SWDOWN'], 0.0)
            ldasin_data['LWDOWN'] = np.maximum(ldasin_data['LWDOWN'], 0.0)
            ldasin_data['RAINRATE'] = np.maximum(ldasin_data['RAINRATE'], 0.0)

            # Write LDASIN file
            fname = t.strftime('%Y%m%d%H') + '.LDASIN_DOMAIN1'
            write_ldasin(output_dir / fname, t, grid_sn, grid_we, ldasin_data)
            n_written += 1

            if (ih + 1) % report_every == 0 or ih == nhours - 1:
                elapsed = _time.time() - year_t0
                rate = (ih + 1) / elapsed if elapsed > 0 else 0
                print(f"    [{ih+1}/{nhours}] {fname}  ({rate:.1f} files/s)",
                      flush=True)

        # Free year data
        del grids

    wall_elapsed = _time.time() - wall_t0

    # ------------------------------------------------------------------
    # 4. Summary
    # ------------------------------------------------------------------
    print(f"\n[4/4] Summary")
    print(f"  LDASIN files written: {n_written}")
    print(f"  Output directory:     {output_dir}")
    print(f"  Wall time:            {wall_elapsed:.1f}s "
          f"({wall_elapsed/60:.1f} min)")
    if n_written > 0:
        print(f"  Rate:                 {n_written / wall_elapsed:.1f} files/s")

    if n_written != nhours_expected:
        print(f"  WARNING: Expected {nhours_expected} files but wrote {n_written}")
    else:
        print("  All expected files written successfully.")

    # Quick sanity check on the last file
    last_file = output_dir / (hourly_times[-1].strftime('%Y%m%d%H') + '.LDASIN_DOMAIN1')
    if last_file.exists():
        ds = nc.Dataset(str(last_file))
        t2d = ds['T2D'][0]
        swdown = ds['SWDOWN'][0]
        rainrate = ds['RAINRATE'][0]
        print(f"\n  Sanity check (last file {last_file.name}):")
        print(f"    T2D:      mean={t2d.mean():.1f} K, std={t2d.std():.2f}")
        print(f"    SWDOWN:   mean={swdown.mean():.1f} W/m2")
        print(f"    RAINRATE: mean={rainrate.mean():.6f} mm/s")
        if t2d.std() > 0:
            print(f"    SPATIAL VARIABILITY: YES (T2D std > 0)")
        else:
            print(f"    WARNING: T2D std = 0 -> no spatial variability!")
        ds.close()


if __name__ == '__main__':
    main()
