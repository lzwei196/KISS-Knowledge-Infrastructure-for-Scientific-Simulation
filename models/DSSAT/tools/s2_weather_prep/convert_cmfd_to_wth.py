#!/usr/bin/env python3
"""
convert_cmfd_to_wth.py — Convert CMFD 3-hourly NetCDF to DSSAT .WTH weather file.

CMFD stores variables in subdirectories: Prec/, Temp/, SRad/, Wind/
Output: DSSAT weather file (.WTH) with columns:
    @DATE  SRAD  TMAX  TMIN  RAIN  WIND

UNIT CONVERSIONS (CRITICAL):
    - CMFD precip: kg/m²/s → mm/day (each 3-hourly value × 10800, then sum 8 steps)
    - CMFD temperature: K → °C (-273.15), compute daily Tmax/Tmin from 8 steps
    - CMFD solar: W/m² → MJ/m²/day (×0.0864)
    - CMFD wind: m/s → km/day (×86.4)

Usage:
    python convert_cmfd_to_wth.py \
        --forcing_dir KISSPATH_FORCING/Data_forcing_03hr_010deg \
        --lat 32.43 --lon 115.60 \
        --start_year 1980 --end_year 1990 \
        --output WJBA8001.WTH \
        --station_name WJBA
"""

import argparse
import os
import sys
import math
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta


def read_cmfd_point(forcing_dir, lat, lon, start_year, end_year):
    """Read CMFD 3-hourly data for a single point, aggregate to daily."""
    import xarray as xr

    forcing_dir = Path(forcing_dir)
    cmfd_vars = [
        ('Prec', 'prec'),
        ('Temp', 'temp'),
        ('SRad', 'srad'),
        ('Wind', 'wind'),
    ]

    daily = []

    for year in range(start_year, end_year + 1):
        for month in range(1, 13):
            month_data = {}
            for subdir, pattern in cmfd_vars:
                sd = forcing_dir / subdir
                nc_files = sorted(sd.glob(f"*{year}{month:02d}*")) if sd.exists() else []
                if not nc_files:
                    nc_files = sorted(forcing_dir.glob(f"*{pattern}*{year}{month:02d}*"))
                if nc_files:
                    # Engine portability: prefer h5netcdf, fall back to netcdf4
                    # then scipy so the tool works across conda envs that ship
                    # only one NetCDF backend.
                    ds = None
                    _last = None
                    for _eng in ('h5netcdf', 'netcdf4', 'scipy', None):
                        try:
                            ds = (xr.open_dataset(nc_files[0], engine=_eng)
                                  if _eng else xr.open_dataset(nc_files[0]))
                            break
                        except (ValueError, ImportError, OSError) as _e:
                            _last = _e
                            continue
                    if ds is None:
                        raise RuntimeError(f"No NetCDF engine could open {nc_files[0]}: {_last}")
                    dvar = [v for v in ds.data_vars if pattern in v.lower()] or list(ds.data_vars)
                    glats = ds['lat'].values if 'lat' in ds else ds['latitude'].values
                    glons = ds['lon'].values if 'lon' in ds else ds['longitude'].values
                    li = int(np.argmin(np.abs(glats - lat)))
                    lo = int(np.argmin(np.abs(glons - lon)))
                    month_data[pattern] = ds[dvar[0]][:, li, lo].values
                    ds.close()

            if 'prec' not in month_data:
                continue

            n_steps = len(month_data['prec'])
            n_days = n_steps // 8

            for d in range(n_days):
                s, e = d * 8, (d + 1) * 8
                date = datetime(year, month, 1) + timedelta(days=d)

                # Precipitation: CMFD stores kg/m²/s — multiply by 10800 (3hr in seconds) then sum
                rain = float(np.sum(month_data['prec'][s:e] * 10800))

                # Temperature: K → °C, compute Tmax/Tmin
                if 'temp' in month_data:
                    temp_k = month_data['temp'][s:e]
                    tmax = float(np.max(temp_k)) - 273.15
                    tmin = float(np.min(temp_k)) - 273.15
                else:
                    tmax, tmin = 25.0, 15.0

                # Solar radiation: W/m² mean → MJ/m²/day
                if 'srad' in month_data:
                    srad = float(np.mean(month_data['srad'][s:e])) * 0.0864
                else:
                    srad = 15.0

                # Wind: m/s mean → km/day
                if 'wind' in month_data:
                    wind = float(np.mean(month_data['wind'][s:e])) * 86.4
                else:
                    wind = 150.0

                daily.append({
                    'date': date,
                    'srad': max(0.0, srad),
                    'tmax': tmax,
                    'tmin': tmin,
                    'rain': max(0.0, rain),
                    'wind': max(0.0, wind),
                })

        print(f"  Year {year}: {sum(1 for d in daily if d['date'].year == year)} days")

    return daily


def compute_tav_amp(daily):
    """Compute TAV (annual avg temp) and AMP (monthly temp amplitude) for .WTH header."""
    if not daily:
        return 20.0, 10.0

    monthly_means = {}
    for d in daily:
        key = (d['date'].year, d['date'].month)
        if key not in monthly_means:
            monthly_means[key] = []
        monthly_means[key].append((d['tmax'] + d['tmin']) / 2.0)

    month_avgs = {}
    for (yr, mo), temps in monthly_means.items():
        if mo not in month_avgs:
            month_avgs[mo] = []
        month_avgs[mo].append(np.mean(temps))

    all_monthly = [np.mean(v) for v in month_avgs.values()]
    tav = np.mean(all_monthly)
    amp = max(all_monthly) - min(all_monthly)

    return float(tav), float(amp)


def _auto_elevation(lat, lon):
    """Look up elevation from ki_tools_common.terrain if available."""
    try:
        import sys
        for p in ['KISSPATH_KI_TOOLS_COMMON',
                  'KISSPATH_INTERNAL_NOT_SHIPPED/kdt-release']:
            if p not in sys.path:
                sys.path.insert(0, p)
        from ki_tools_common.terrain import get_terrain
        return get_terrain(lat, lon)['elevation']
    except Exception:
        return -99.0


def write_wth(daily, output_path, station_name, lat, lon, elev=-99.0):
    """Write DSSAT .WTH weather file.
    If elev=-99 (missing), auto-looks up from DEM via ki_tools_common.terrain.
    """
    if elev <= -99.0:
        elev = _auto_elevation(lat, lon)
    tav, amp = compute_tav_amp(daily)

    # The CMFD extraction above costs ~1.3 min per simulated year. A missing
    # parent directory used to raise here, AFTER all of that work, discarding
    # it — fatal once a driver writes many member files into per-member
    # subdirectories. Create the parent instead of failing on it.
    os.makedirs(os.path.dirname(os.path.abspath(output_path)) or '.', exist_ok=True)

    with open(output_path, 'w') as f:
        f.write(f"*WEATHER DATA : {station_name} - CMFD converted\n")
        f.write(f"@ INSI      LAT     LONG  ELEV   TAV   AMP REFHT WNDHT\n")
        f.write(f"  {station_name[:4]:4s} {lat:8.3f} {lon:8.3f} {elev:5.0f} {tav:5.1f} {amp:5.1f}   2.0  10.0\n")
        f.write(f"@DATE  SRAD  TMAX  TMIN  RAIN  WIND\n")

        for d in daily:
            yy = d['date'].year % 100
            jday = d['date'].timetuple().tm_yday
            date_str = f"{yy:02d}{jday:03d}"
            f.write(f"{date_str:5s}{d['srad']:6.1f}{d['tmax']:6.1f}{d['tmin']:6.1f}{d['rain']:6.1f}{d['wind']:6.1f}\n")

    print(f"Written: {output_path} ({len(daily)} days)")
    print(f"  TAV={tav:.1f}°C  AMP={amp:.1f}°C")
    print(f"  Mean precip: {np.mean([d['rain'] for d in daily]):.1f} mm/day")
    print(f"  Annual precip: {np.sum([d['rain'] for d in daily]) / max(1, len(set(d['date'].year for d in daily))):.0f} mm/yr")


def main():
    parser = argparse.ArgumentParser(description='Convert CMFD to DSSAT .WTH')
    parser.add_argument('--forcing_dir', required=True, help='CMFD root (with Prec/ Temp/ SRad/ subdirs)')
    parser.add_argument('--lat', type=float, required=True)
    parser.add_argument('--lon', type=float, required=True)
    parser.add_argument('--start_year', type=int, required=True)
    parser.add_argument('--end_year', type=int, required=True)
    parser.add_argument('--output', required=True, help='Output .WTH file path')
    parser.add_argument('--station_name', default='SITE', help='4-char station code')
    parser.add_argument('--elev', type=float, default=-99.0, help='Elevation (m)')
    args = parser.parse_args()

    print(f"Converting CMFD → DSSAT .WTH for ({args.lat}, {args.lon})")
    daily = read_cmfd_point(args.forcing_dir, args.lat, args.lon, args.start_year, args.end_year)

    if not daily:
        print("ERROR: No data extracted from CMFD")
        sys.exit(1)

    write_wth(daily, args.output, args.station_name, args.lat, args.lon, args.elev)


if __name__ == '__main__':
    main()
