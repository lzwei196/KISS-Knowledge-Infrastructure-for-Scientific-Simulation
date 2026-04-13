#!/usr/bin/env python3
"""
power_cache_to_rzwqm2.py
========================
Convert NASA POWER hourly cache (.npz) to RZWQM2 daily CSV format.

Cache format: {CACHE_DIR}/{lat:.1f}_{lon:.1f}/{year}.npz
Variables: T2M (°C), PRECTOTCORR (mm/hr), PS (kPa), ALLSKY_SFC_SW_DWN (MJ/m2/hr),
           ALLSKY_SFC_LW_DWN (MJ/m2/hr), QV2M (g/kg), WS2M (m/s)

Output CSV format (RZWQM2 ready):
    date, tmin, tmax, wind, radiation, epan, rh, par, rain

Units:
    tmin/tmax: °C
    wind: km/day
    radiation: MJ/m2/day (shortwave)
    epan: mm/day (estimated ~0.7 × ET0)
    rh: % (relative humidity)
    par: MJ/m2/day (estimated as 0.48 × shortwave)
    rain: mm/day

Usage:
    python power_cache_to_rzwqm2.py <lat> <lon> <start_date> <end_date> <cache_dir> <output_csv>
"""

import sys
import os
import csv
import json
import math
import numpy as np
from datetime import datetime, date, timedelta

CACHE_DIR_DEFAULT = "/mnt/disk1/Hydrocraft_server/data/nasa_power_cache/hourly"
PAR_FRACTION  = 0.48
EPAN_ET0_RATIO = 0.7

def nearest_power_point(lat, lon):
    """Snap to nearest 0.5° NASA POWER grid center."""
    return round(round(lat * 2) / 2, 1), round(round(lon * 2) / 2, 1)

def saturation_vapor_pressure(T_C):
    """Tetens formula: es in kPa."""
    return 0.6108 * math.exp(17.27 * T_C / (T_C + 237.3))

def specific_to_rh(qv_gkg, T_C, P_kPa):
    """Convert specific humidity (g/kg) to RH (%)."""
    q = qv_gkg / 1000.0   # kg/kg
    es = saturation_vapor_pressure(T_C)   # kPa
    # ea from specific humidity: ea = q * P / (0.622 + q)
    ea = q * P_kPa / (0.622 + q)
    rh = min(100.0, max(0.0, (ea / es) * 100.0))
    return rh

def et0_penman_simple(tmin, tmax, wind_ms, srad_mj, rh_pct):
    """Simple Hargreaves ET0 (mm/day)."""
    tmean = (tmin + tmax) / 2.0
    Ra = srad_mj  # use measured shortwave as proxy for extraterrestrial
    et0 = max(0, 0.0023 * (tmean + 17.8) * math.sqrt(max(0.1, tmax - tmin)) * srad_mj)
    return et0

def load_year(cache_dir, plat, plon, year):
    """Load one year of hourly NASA POWER data from cache.
    Returns dict of variable → numpy array (8760 or 8784 hours)."""
    path = os.path.join(cache_dir, f"{plat:.1f}_{plon:.1f}", f"{year}.npz")
    if not os.path.exists(path):
        return None
    f = np.load(path, allow_pickle=True)
    return {k: f[k] for k in f.keys()}

def process(lat, lon, start_date, end_date, cache_dir, output_csv):
    plat, plon = nearest_power_point(lat, lon)
    print(f"  Site: ({lat},{lon}) → POWER point ({plat},{plon})")

    start = datetime.strptime(start_date, '%Y-%m-%d').date()
    end   = datetime.strptime(end_date,   '%Y-%m-%d').date()

    rows = []
    current = start
    while current <= end:
        yr = current.year
        # Load year cache if needed
        if not hasattr(process, '_cache') or process._cache_yr != yr or \
           process._cache_pt != (plat, plon):
            data = load_year(cache_dir, plat, plon, yr)
            if data is None:
                print(f"  [WARN] No cache for {plat}_{plon}/{yr} — filling with NaN")
                # Fill with daily NaN row
                ndays = 366 if yr % 4 == 0 else 365
                process._cache = None
            else:
                process._cache = data
            process._cache_yr = yr
            process._cache_pt = (plat, plon)

        # Day-of-year → hourly slice
        doy = (current - date(yr, 1, 1)).days   # 0-based
        is_leap = (yr % 4 == 0 and (yr % 100 != 0 or yr % 400 == 0))
        hrs_in_year = 8784 if is_leap else 8760
        h_start = doy * 24
        h_end   = h_start + 24

        if process._cache is None or h_end > hrs_in_year:
            rows.append([current.isoformat(), -999, -999, -999, -999, -999, -999, -999, -999])
            current += timedelta(days=1)
            continue

        T2M    = process._cache['T2M'][h_start:h_end]        # °C, hourly
        PREC   = process._cache['PRECTOTCORR'][h_start:h_end]# mm/day rate (÷24 = actual mm/hr)
        PS     = process._cache['PS'][h_start:h_end]          # kPa
        SW     = process._cache['ALLSKY_SFC_SW_DWN'][h_start:h_end]  # MJ/m2/hr
        QV     = process._cache['QV2M'][h_start:h_end]        # g/kg
        WS     = process._cache['WS2M'][h_start:h_end]        # m/s

        # Daily aggregation
        tmin_v = float(np.nanmin(T2M))
        tmax_v = float(np.nanmax(T2M))
        tmean  = float(np.nanmean(T2M))
        rain_v = float(np.nansum(PREC)) / 24.0  # sum of 24 mm/day-rate values → actual mm/day
        srad_v = float(np.nansum(SW))         # MJ/m2/day (sum of hourly MJ/m2)
        wind_v = float(np.nanmean(WS)) * 86.4 # m/s → km/day

        # RH: use mean temperature and mean specific humidity
        ps_mean = float(np.nanmean(PS))
        qv_mean = float(np.nanmean(QV))
        rh_v = specific_to_rh(qv_mean, tmean, ps_mean)

        # Derived
        et0   = et0_penman_simple(tmin_v, tmax_v, float(np.nanmean(WS)), srad_v, rh_v)
        epan  = round(et0 * EPAN_ET0_RATIO, 2)
        par   = round(srad_v * PAR_FRACTION, 2)

        rows.append([
            current.isoformat(),
            round(tmin_v, 1), round(tmax_v, 1),
            round(wind_v, 1), round(srad_v, 2),
            epan, round(rh_v, 1), par, round(rain_v, 1)
        ])
        current += timedelta(days=1)

    os.makedirs(os.path.dirname(output_csv) or '.', exist_ok=True)
    with open(output_csv, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['date','tmin','tmax','wind','radiation','epan','rh','par','rain'])
        w.writerows(rows)

    result = {
        "status": "SUCCESS",
        "message": f"Wrote {len(rows)} days ({start_date}–{end_date}) for ({lat},{lon})",
        "output_csv": output_csv,
        "rows": len(rows),
    }
    print(json.dumps(result))
    return True

if __name__ == '__main__':
    if len(sys.argv) < 6:
        print("Usage: power_cache_to_rzwqm2.py <lat> <lon> <start_date> <end_date> <cache_dir> <output_csv>")
        sys.exit(1)
    lat   = float(sys.argv[1])
    lon   = float(sys.argv[2])
    start = sys.argv[3]
    end   = sys.argv[4]
    cache = sys.argv[5]
    out   = sys.argv[6]
    process(lat, lon, start, end, cache, out)
