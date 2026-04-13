#!/usr/bin/env python3
"""
convert_forcing_to_shaw.py — Convert CMFD/MSWX/NASA POWER forcing to SHAW weather format.

Supports:
- Hourly weather format (MTSTEP=0): JD JH JYR TA WIND HUM PRECIP SNODEN SUNHOR
- Daily weather format (MTSTEP=1): JD JYR TMAX TMIN TDEW WIND PRECIP SOLAR

Input: VIC forcing files (ASCII, space-separated) with format:
    PRECIP TMAX TMIN WIND QAIR SWdown LWdown PRESSURE
    (per day, one file per grid cell: forcing_prefix_lat_lon)

Or: NetCDF from forcing_1d.py output.

UNIT CONVERSIONS (CRITICAL):
    - VIC precip: mm/timestep -> SHAW: mm (same with IFLAGSI=1)
    - VIC temperature: C -> SHAW: C (same)
    - VIC wind: m/s -> SHAW: m/s (same with IFLAGSI=1)
    - VIC specific humidity: kg/kg -> SHAW: relative humidity (%)
    - VIC shortwave: W/m2 -> SHAW: W/m2 (same)
    - VIC pressure: Pa -> kPa (for humidity conversion)

Usage:
    python convert_forcing_to_shaw.py \
        --forcing_dir outputs/<run>/vic_temp/forcing/forcing_final \
        --lat 46.75 --lon -116.95 \
        --start_year 2005 --end_year 2005 \
        --output weather.wea \
        --mode daily    # or hourly
"""

import argparse
import sys
import os
import math
import glob
from pathlib import Path
from datetime import datetime, timedelta
import numpy as np


def specific_to_relative_humidity(q, T, P):
    """
    Convert specific humidity to relative humidity.

    Args:
        q: Specific humidity (kg/kg)
        T: Temperature (C)
        P: Pressure (Pa)

    Returns:
        RH: Relative humidity (%)
    """
    # Saturation vapor pressure (Pa) - Tetens formula
    es = 611.2 * math.exp(17.67 * T / (T + 243.5))
    # Actual vapor pressure from specific humidity
    ea = q * P / (0.622 + 0.378 * q)
    # Relative humidity
    rh = 100.0 * ea / es
    return max(0.0, min(100.0, rh))


def temp_to_dewpoint(T, RH):
    """
    Compute dew-point temperature from air temperature and relative humidity.

    Args:
        T: Air temperature (C)
        RH: Relative humidity (%)

    Returns:
        Td: Dew-point temperature (C)
    """
    rh_frac = max(RH / 100.0, 0.01)
    a = 17.27
    b = 237.7
    gamma = a * T / (b + T) + math.log(rh_frac)
    td = b * gamma / (a - gamma)
    return td


def find_forcing_file(forcing_dir, lat, lon, prefix=None):
    """Find the VIC forcing file for a given lat/lon."""
    forcing_dir = Path(forcing_dir)

    # Try various naming patterns
    patterns = [
        f"*_{lat:.4f}_{lon:.4f}",
        f"*_{lat:.2f}_{lon:.2f}",
        f"*{abs(lat):.4f}*{abs(lon):.4f}*",
    ]

    for pattern in patterns:
        matches = list(forcing_dir.glob(pattern))
        if matches:
            return matches[0]

    # Try finding closest file
    best_file = None
    best_dist = float('inf')
    for f in forcing_dir.iterdir():
        if f.is_file():
            parts = f.name.split('_')
            try:
                # Try to extract lat/lon from filename
                for i in range(len(parts) - 1):
                    try:
                        flat = float(parts[i])
                        flon = float(parts[i + 1])
                        dist = (flat - lat) ** 2 + (flon - lon) ** 2
                        if dist < best_dist:
                            best_dist = dist
                            best_file = f
                    except ValueError:
                        continue
            except Exception:
                continue

    if best_file and best_dist < 0.1:
        return best_file

    print(f"ERROR: No forcing file found for ({lat}, {lon}) in {forcing_dir}")
    return None


def read_vic_forcing(filepath, start_year, end_year, steps_per_day=8):
    """
    Read VIC forcing file (ASCII, space-separated).

    Expected columns (HydroCraft standard):
        PRECIP TMAX TMIN WIND QAIR SWdown LWdown PRESSURE

    For 3-hourly (8 steps/day) or daily (1 step/day).

    Returns: list of dicts with timestep data.
    """
    data = []
    with open(filepath, 'r') as f:
        lines = f.readlines()

    # Calculate expected number of days
    total_days = 0
    for year in range(start_year, end_year + 1):
        if (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0):
            total_days += 366
        else:
            total_days += 365

    total_steps = total_days * steps_per_day

    if len(lines) < total_steps:
        print(f"WARNING: Expected {total_steps} lines but got {len(lines)}. "
              f"Adjusting end date.")

    # Parse each line
    current_date = datetime(start_year, 1, 1)
    step_in_day = 0

    for line_idx, line in enumerate(lines):
        parts = line.strip().split()
        if len(parts) < 4:
            continue

        try:
            precip = float(parts[0])  # mm/timestep
            tmax = float(parts[1])    # C
            tmin = float(parts[2])    # C
            wind = float(parts[3])    # m/s

            qair = float(parts[4]) if len(parts) > 4 else 0.005   # kg/kg
            swdown = float(parts[5]) if len(parts) > 5 else 200.0  # W/m2
            lwdown = float(parts[6]) if len(parts) > 6 else 300.0  # W/m2
            pressure = float(parts[7]) if len(parts) > 7 else 101325.0  # Pa
        except (ValueError, IndexError):
            continue

        jday = current_date.timetuple().tm_yday
        year = current_date.year
        hour = step_in_day * (24 // steps_per_day)

        tavg = (tmax + tmin) / 2.0
        rh = specific_to_relative_humidity(qair, tavg, pressure)

        data.append({
            'jday': jday,
            'hour': hour,
            'year': year,
            'date': current_date,
            'tmax': tmax,
            'tmin': tmin,
            'tavg': tavg,
            'wind': wind,
            'rh': rh,
            'precip': precip,
            'swdown': swdown,
            'lwdown': lwdown,
            'pressure': pressure,
            'qair': qair,
        })

        step_in_day += 1
        if step_in_day >= steps_per_day:
            step_in_day = 0
            current_date += timedelta(days=1)

    return data


def write_hourly_weather(data, output_path, steps_per_day=8):
    """
    Write SHAW hourly weather file.
    Format: JD JH JYR TA WIND HUM PRECIP SNODEN SUNHOR
    """
    with open(output_path, 'w') as f:
        for rec in data:
            # Snow density: 0 = let model calculate from temperature
            snoden = 0.0
            f.write(
                f" {rec['jday']:3d} {rec['hour']:2d} {rec['year']:2d} "
                f"{rec['tavg']:6.1f} {rec['wind']:5.2f} {rec['rh']:5.1f} "
                f"{rec['precip']:5.1f} {snoden:3.1f} "
                f"{rec['swdown']:7.1f}\n"
            )

    print(f"Hourly weather file written: {output_path}")
    print(f"  Records: {len(data)}")
    print(f"  Period: day {data[0]['jday']}/{data[0]['year']} to day {data[-1]['jday']}/{data[-1]['year']}")


def write_daily_weather(data, output_path, steps_per_day=8):
    """
    Write SHAW daily weather file.
    Format: JD JYR TMAX TMIN TDEW WIND PRECIP SOLAR

    Aggregates sub-daily data to daily.
    """
    # Group by day
    daily = {}
    for rec in data:
        key = (rec['year'], rec['jday'])
        if key not in daily:
            daily[key] = {
                'jday': rec['jday'],
                'year': rec['year'],
                'tmax': -999,
                'tmin': 999,
                'wind_sum': 0,
                'precip_sum': 0,
                'sw_sum': 0,
                'rh_sum': 0,
                'tavg_sum': 0,
                'count': 0,
            }
        d = daily[key]
        d['tmax'] = max(d['tmax'], rec['tmax'])
        d['tmin'] = min(d['tmin'], rec['tmin'])
        d['wind_sum'] += rec['wind']
        d['precip_sum'] += rec['precip']
        d['sw_sum'] += rec['swdown']
        d['rh_sum'] += rec['rh']
        d['tavg_sum'] += rec['tavg']
        d['count'] += 1

    with open(output_path, 'w') as f:
        for key in sorted(daily.keys()):
            d = daily[key]
            n = d['count']
            wind_avg = d['wind_sum'] / n
            solar_avg = d['sw_sum'] / n
            rh_avg = d['rh_sum'] / n
            tavg = d['tavg_sum'] / n

            # Dew-point from average temp and RH
            tdew = temp_to_dewpoint(tavg, rh_avg)

            # Year as 2-digit (SHAW convention: 86 for 1986)
            yr = d['year'] % 100

            f.write(
                f" {d['jday']:3d} {yr:2d} "
                f"{d['tmax']:6.1f} {d['tmin']:6.1f} {tdew:6.1f} "
                f"{wind_avg:5.2f} {d['precip_sum']:6.1f} "
                f"{solar_avg:7.1f}\n"
            )

    print(f"Daily weather file written: {output_path}")
    print(f"  Days: {len(daily)}")
    first = sorted(daily.keys())[0]
    last = sorted(daily.keys())[-1]
    print(f"  Period: day {first[1]}/{first[0]} to day {last[1]}/{last[0]}")


def main():
    parser = argparse.ArgumentParser(description="Convert VIC forcing to SHAW weather format")
    parser.add_argument("--forcing_dir", type=str, required=True,
                        help="Directory with VIC forcing files")
    parser.add_argument("--lat", type=float, required=True, help="Target latitude")
    parser.add_argument("--lon", type=float, required=True, help="Target longitude")
    parser.add_argument("--start_year", type=int, required=True, help="Start year")
    parser.add_argument("--end_year", type=int, required=True, help="End year")
    parser.add_argument("--output", type=str, required=True, help="Output weather file")
    parser.add_argument("--mode", choices=["hourly", "daily"], default="daily",
                        help="Output format: hourly or daily")
    parser.add_argument("--steps_per_day", type=int, default=8,
                        help="VIC forcing steps per day (8=3-hourly, 24=hourly)")
    parser.add_argument("--prefix", type=str, default=None,
                        help="Forcing file prefix")

    args = parser.parse_args()

    # Find forcing file — try VIC ASCII first, then CMFD NetCDF
    forcing_file = find_forcing_file(args.forcing_dir, args.lat, args.lon, args.prefix)

    data = None
    if forcing_file is not None:
        print(f"Reading VIC forcing: {forcing_file}")
        data = read_vic_forcing(forcing_file, args.start_year, args.end_year, args.steps_per_day)

    if not data:
        # Try CMFD NetCDF direct read (subdirectories: Prec/, Temp/, etc.)
        print(f"No VIC ASCII found. Trying CMFD NetCDF from {args.forcing_dir}...")
        try:
            import xarray as xr
            forcing_dir = Path(args.forcing_dir)
            cmfd_vars = [
                ('Prec', 'prec'), ('Temp', 'temp'), ('Wind', 'wind'),
                ('SHum', 'shum'), ('SRad', 'srad'), ('LRad', 'lrad'), ('Pres', 'pres'),
            ]
            all_ts = {v: [] for _, v in cmfd_vars}
            for year in range(args.start_year, args.end_year + 1):
                for month in range(1, 13):
                    for subdir, pattern in cmfd_vars:
                        sd = forcing_dir / subdir
                        nc_files = sorted(sd.glob(f"*{year}{month:02d}*")) if sd.exists() else []
                        if not nc_files:
                            nc_files = sorted(forcing_dir.glob(f"*{pattern}*{year}{month:02d}*"))
                        if nc_files:
                            ds = xr.open_dataset(nc_files[0])
                            dvar = [v for v in ds.data_vars if pattern in v.lower()] or list(ds.data_vars)
                            glats = ds['lat'].values if 'lat' in ds else ds['latitude'].values
                            glons = ds['lon'].values if 'lon' in ds else ds['longitude'].values
                            li = int(np.argmin(np.abs(glats - args.lat)))
                            lo = int(np.argmin(np.abs(glons - args.lon)))
                            all_ts[pattern].extend(ds[dvar[0]][:, li, lo].values)
                            ds.close()
            if all_ts['prec']:
                min_len = min(len(v) for v in all_ts.values())
                n_days = min_len // 8
                data = []
                for d in range(n_days):
                    s = d * 8
                    e = s + 8
                    prec_mm = float(np.sum(all_ts['prec'][s:e]))
                    tmax_c = float(np.max(all_ts['temp'][s:e])) - 273.15
                    tmin_c = float(np.min(all_ts['temp'][s:e])) - 273.15
                    wind = float(np.mean(all_ts['wind'][s:e]))
                    srad = float(np.mean(all_ts['srad'][s:e]))
                    q = float(np.mean(all_ts['shum'][s:e]))
                    p_pa = float(np.mean(all_ts['pres'][s:e]))
                    # Compute dewpoint from specific humidity
                    vp = q * p_pa / (0.622 + 0.378 * q) / 1000  # kPa
                    tdew = (237.3 * math.log(vp / 0.6108)) / (17.27 - math.log(vp / 0.6108)) if vp > 0.001 else tmin_c
                    base = datetime(args.start_year, 1, 1) + timedelta(days=d)
                    jd = base.timetuple().tm_yday
                    data.append({'jd': jd, 'year': base.year, 'tmax': tmax_c, 'tmin': tmin_c,
                                 'tdew': tdew, 'wind': wind, 'prec': prec_mm, 'solar': srad})
                print(f"Read {len(data)} days from CMFD NetCDF")
        except Exception as ex:
            print(f"CMFD NetCDF read failed: {ex}")

    if not data:
        print("ERROR: No data from VIC ASCII or CMFD NetCDF")
        sys.exit(1)

    print(f"Read {len(data)} records")

    # Write SHAW weather
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if args.mode == "hourly":
        write_hourly_weather(data, str(output_path), args.steps_per_day)
    else:
        write_daily_weather(data, str(output_path), args.steps_per_day)


if __name__ == "__main__":
    main()
