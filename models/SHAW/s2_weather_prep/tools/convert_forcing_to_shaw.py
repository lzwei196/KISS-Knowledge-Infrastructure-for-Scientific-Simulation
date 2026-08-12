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


def read_daily_csv(filepath, start_year=None, end_year=None):
    """
    Read a pre-aggregated DAILY weather CSV into SHAW's record list.

    Designed for already-SHAW-ready daily sources such as the RISMA station
    bundle (weather_complete.csv: date,tmax_C,tmin_C,precip_mm,srad_MJ_m2,
    wind_m_s,rh_pct) and Environment-Canada / AAFC daily exports.

    Required columns (case-insensitive, flexible names):
        date (YYYY-MM-DD)         -> jday/year
        tmax_C / tmax             -> tmax (C)
        tmin_C / tmin             -> tmin (C)
        precip_mm / precip        -> precip (mm/day)
        srad_MJ_m2 / srad / solar -> shortwave; MJ/m2/day is auto-converted to W/m2
        wind_m_s / wind           -> wind (m/s)
        rh_pct / rh               -> relative humidity (%)

    Returns a list of per-day dicts with the same keys write_daily_weather()
    consumes (jday, year, tmax, tmin, tavg, wind, precip, swdown, rh).
    Solar is emitted in W/m2 so write_daily_weather can pass it through.

    Unit trap (triplet shaw_029): SHAW daily mode wants AVERAGE daily solar in
    W/m2.  Daily totals reported in MJ/m2/day are multiplied by 11.574
    (= 1e6 J / 86400 s).  Values that already look like W/m2 (mean > 60) are
    left untouched.
    """
    import csv as _csv

    def _pick(row, *names):
        for n in names:
            for k in row:
                if k and k.strip().lower() == n:
                    v = row[k]
                    if v is None or str(v).strip() == "":
                        return None
                    try:
                        return float(v)
                    except ValueError:
                        return None
        return None

    rows = []
    with open(filepath, newline="") as fh:
        rdr = _csv.DictReader(fh)
        for row in rdr:
            datestr = None
            for k in row:
                if k and k.strip().lower() in ("date", "datetime", "day"):
                    datestr = str(row[k]).strip()
                    break
            if not datestr:
                continue
            try:
                dt = datetime.strptime(datestr[:10], "%Y-%m-%d")
            except ValueError:
                continue
            if start_year and dt.year < start_year:
                continue
            if end_year and dt.year > end_year:
                continue
            tmax = _pick(row, "tmax_c", "tmax", "tmax_air", "maxair_t")
            tmin = _pick(row, "tmin_c", "tmin", "tmin_air", "minair_t")
            if tmax is None or tmin is None:
                continue
            precip = _pick(row, "precip_mm", "precip", "prcp", "rain_mm") or 0.0
            srad = _pick(row, "srad_mj_m2", "srad", "solar", "solar_mj", "totrs_mj")
            wind = _pick(row, "wind_m_s", "wind", "avgws", "windspeed")
            rh = _pick(row, "rh_pct", "rh", "avgrh", "humidity")
            # Solar -> W/m2 (auto-detect MJ/m2/day vs already-W/m2)
            if srad is None:
                swdown = 150.0
            elif srad <= 60.0:           # MJ/m2/day regime
                swdown = srad * 11.574
            else:                        # already W/m2
                swdown = srad
            rows.append({
                "jday": dt.timetuple().tm_yday,
                "year": dt.year,
                "tmax": tmax,
                "tmin": tmin,
                "tavg": 0.5 * (tmax + tmin),
                "wind": wind if wind is not None else 2.0,
                "precip": max(0.0, precip),
                "swdown": max(0.0, swdown),
                "rh": rh if rh is not None else 70.0,
            })

    # Sort by true calendar date and FILL GAPS. SHAW's DAY2HR aborts
    # ("ENCOUNTERED PROBLEMS READING DAILY WEATHER DATA") on any missing
    # calendar day, so the daily series must be strictly consecutive. Missing
    # days are linearly interpolated between the nearest present neighbours
    # (e.g. RISMA Ontario is missing 2017-10-14).
    by_date = {}
    for r in rows:
        d = datetime(r["year"], 1, 1) + timedelta(days=r["jday"] - 1)
        by_date[d.date()] = r
    if not by_date:
        return []
    keys = sorted(by_date)
    filled = []
    cur = keys[0]
    last = keys[-1]
    fields = ("tmax", "tmin", "tavg", "wind", "precip", "swdown", "rh")
    n_filled = 0
    while cur <= last:
        if cur in by_date:
            filled.append(by_date[cur])
        else:
            # find previous and next present days
            prev = cur - timedelta(days=1)
            while prev not in by_date:
                prev -= timedelta(days=1)
            nxt = cur + timedelta(days=1)
            while nxt not in by_date:
                nxt += timedelta(days=1)
            span = (nxt - prev).days
            w = (cur - prev).days / span
            rp, rn = by_date[prev], by_date[nxt]
            rec = {f: rp[f] * (1 - w) + rn[f] * w for f in fields}
            rec["precip"] = 0.0   # don't smear precip across a gap
            rec["jday"] = cur.timetuple().tm_yday
            rec["year"] = cur.year
            filled.append(rec)
            n_filled += 1
        cur += timedelta(days=1)
    if n_filled:
        print(f"  Filled {n_filled} missing calendar day(s) by interpolation")
    return filled


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
            # HydroCraft forcing_final column order (from global_param FORCE_TYPE):
            # AIR_TEMP(°C)  PREC(mm/ts)  PRESSURE(kPa)  SWDOWN(W/m²)
            # LWDOWN(W/m²)  VP(kPa)  WIND(m/s)  — 7 columns, no QAIR
            temp     = float(parts[0])                                    # °C
            precip   = float(parts[1])                                    # mm/timestep
            pressure = float(parts[2]) * 1000 if len(parts) > 2 else 101325.0  # kPa→Pa
            swdown   = float(parts[3]) if len(parts) > 3 else 200.0      # W/m²
            lwdown   = float(parts[4]) if len(parts) > 4 else 300.0      # W/m²
            vp_kpa   = float(parts[5]) if len(parts) > 5 else 0.01       # kPa
            wind     = float(parts[6]) if len(parts) > 6 else 2.0        # m/s

            # Convert VP → specific humidity for RH computation
            e_pa = vp_kpa * 1000.0
            qair = 0.622 * e_pa / max(pressure - 0.378 * e_pa, 1.0)  # kg/kg
            tmax = temp   # 3-hourly: same T each sub-step; write_daily_weather
            tmin = temp   # computes true daily max/min across 8 sub-steps
        except (ValueError, IndexError):
            continue

        jday = current_date.timetuple().tm_yday
        year = current_date.year
        hour = step_in_day * (24 // steps_per_day)

        tavg = temp
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
    parser.add_argument("--forcing_dir", type=str, default=None,
                        help="Directory with VIC/CMFD forcing files")
    parser.add_argument("--csv", type=str, default=None,
                        help="Pre-aggregated daily weather CSV (RISMA/EC/AAFC). "
                             "When given, --forcing_dir is ignored.")
    parser.add_argument("--lat", type=float, default=0.0, help="Target latitude")
    parser.add_argument("--lon", type=float, default=0.0, help="Target longitude")
    parser.add_argument("--start_year", type=int, default=None, help="Start year")
    parser.add_argument("--end_year", type=int, default=None, help="End year")
    parser.add_argument("--output", type=str, required=True, help="Output weather file")
    parser.add_argument("--mode", choices=["hourly", "daily"], default="daily",
                        help="Output format: hourly or daily")
    parser.add_argument("--steps_per_day", type=int, default=8,
                        help="VIC forcing steps per day (8=3-hourly, 24=hourly)")
    parser.add_argument("--prefix", type=str, default=None,
                        help="Forcing file prefix")

    args = parser.parse_args()

    data = None

    # Preferred path: a pre-aggregated daily CSV (RISMA/EC/AAFC daily exports)
    if args.csv:
        print(f"Reading daily CSV forcing: {args.csv}")
        data = read_daily_csv(args.csv, args.start_year, args.end_year)
        if not data:
            print("ERROR: no usable rows in --csv")
            sys.exit(1)
        print(f"Read {len(data)} daily records from CSV")
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        # CSV is already daily -> one record per day (steps_per_day=1)
        if args.mode == "hourly":
            print("WARNING: --csv is daily data; forcing --mode daily")
        write_daily_weather(data, str(output_path), steps_per_day=1)
        return

    if args.forcing_dir is None:
        print("ERROR: provide --csv or --forcing_dir")
        sys.exit(1)

    # Find forcing file — try VIC ASCII first, then CMFD NetCDF
    forcing_file = find_forcing_file(args.forcing_dir, args.lat, args.lon, args.prefix)

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
                    tavg = (tmax_c + tmin_c) / 2.0
                    # Back-compute RH from tdew so write_daily_weather's
                    # temp_to_dewpoint(tavg, rh) round-trips correctly.
                    _a, _b = 17.27, 237.7
                    _gd = _a * tdew / (_b + tdew) if (_b + tdew) != 0 else 0
                    _gt = _a * tavg / (_b + tavg) if (_b + tavg) != 0 else 0
                    rh = max(0.0, min(100.0, 100.0 * math.exp(_gd - _gt)))
                    data.append({'jday': jd, 'year': base.year,
                                 'tmax': tmax_c, 'tmin': tmin_c, 'tavg': tavg,
                                 'tdew': tdew, 'wind': wind,
                                 'precip': prec_mm, 'swdown': srad, 'rh': rh})
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
