#!/usr/bin/env python3
"""
Extract CMFD 3-hourly weather data at Wangjiaba (32.43N, 115.6E)
and convert to PCSE CSV weather format.

Uses 3-hourly data to compute proper daily TMIN/TMAX.

UNIT CONVERSIONS (CMFD → PCSE):
  temp:  K → °C  (-273.15)
  srad:  W/m² → kJ/m²/day  (mean_W * 86.4)
  prec:  mm/3hr → cm/day  (sum_mm / 10)
  wind:  m/s → m/s  (no change)
  shum+pres → VAP (kPa)  (e = q*P / (0.622 + 0.378*q), P in Pa → kPa)
"""

import sys
import os
import numpy as np
import xarray as xr
from pathlib import Path
from datetime import date, timedelta

# Configuration
LAT = 32.43
LON = 115.6
START_YEAR = 1980
END_YEAR = 1990
CMFD_DIR = Path("/mnt/disk1/Hydrocraft_server/data/forcing/Data_forcing_03hr_010deg")
OUTPUT_DIR = Path("/mnt/disk1/Hydrocraft_server/models/WOFOST/knowledge_infrastructure/outputs/wangjiaba")

VARS = {
    'Temp': 'temp',
    'SRad': 'srad',
    'Prec': 'prec',
    'Wind': 'wind',
    'Pres': 'pres',
    'SHum': 'shum',
}


def extract_monthly(var_dir, var_name, year, month, lat, lon):
    """Extract 3-hourly data for one variable, one month, at one grid cell."""
    fname = f"{var_name}_CMFD_V0200_B-01_03hr_010deg_{year}{month:02d}.nc"
    fpath = CMFD_DIR / var_dir / fname
    if not fpath.exists():
        print(f"  WARNING: {fpath} not found, skipping")
        return None
    ds = xr.open_dataset(fpath)
    cell = ds[var_name].sel(lat=lat, lon=lon, method='nearest')
    return cell.values


def compute_daily_weather(year, month, lat, lon):
    """Extract all variables for a month, aggregate to daily."""
    # Extract all variables
    data = {}
    for var_dir, var_name in VARS.items():
        vals = extract_monthly(var_dir, var_name, year, month, lat, lon)
        if vals is None:
            return None
        data[var_name] = vals

    # Determine number of days
    n_steps = len(data['temp'])
    n_days = n_steps // 8

    rows = []
    for d in range(n_days):
        s, e = d * 8, (d + 1) * 8

        temp_k = data['temp'][s:e]
        tmin_c = float(np.min(temp_k)) - 273.15
        tmax_c = float(np.max(temp_k)) - 273.15

        # IRRAD: mean SW (W/m²) × 86.4 → kJ/m²/day
        sw_mean = float(np.mean(data['srad'][s:e]))
        irrad_kj = sw_mean * 86.4

        # RAIN: CMFD precip is in kg/m²/s → mm/3hr (×10800) → sum to mm/day
        # CSVWeatherDataProvider expects mm/day and converts to cm internally
        prec_kgm2s = data['prec'][s:e]
        rain_mm = float(np.sum(prec_kgm2s * 10800.0))  # each step is 3hr=10800s

        # WIND: mean m/s
        wind_ms = float(np.mean(data['wind'][s:e]))

        # VAP: from specific humidity + pressure
        # e = q * P / (0.622 + 0.378 * q), P in Pa, result in Pa → kPa (/1000)
        q = float(np.mean(data['shum'][s:e]))
        p = float(np.mean(data['pres'][s:e]))  # Pa
        vap_pa = q * p / (0.622 + 0.378 * q)
        vap_kpa = vap_pa / 1000.0

        day_date = date(year, month, 1) + timedelta(days=d)
        rows.append((day_date, irrad_kj, tmin_c, tmax_c, vap_kpa, wind_ms, rain_mm))

    return rows


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_csv = OUTPUT_DIR / "weather_wangjiaba.csv"

    all_rows = []
    for year in range(START_YEAR, END_YEAR + 1):
        print(f"Processing {year}...")
        for month in range(1, 13):
            rows = compute_daily_weather(year, month, LAT, LON)
            if rows:
                all_rows.extend(rows)

    print(f"Total days: {len(all_rows)}")

    # Write PCSE CSV — header values must be Python literals (strings quoted)
    # CSVWeatherDataProvider skips line 1, then reads key=value until '## Daily weather observations'
    # Built-in conversions: IRRAD kJ→J, RAIN mm→cm, VAP kPa→hPa
    with open(output_csv, 'w') as f:
        f.write("## Site Characteristics\n")
        f.write(f'Country = "China"; Station = "Wangjiaba_CMFD"; Description = "CMFD"\n')
        f.write(f'Source = "CMFD_3hr"; Contact = "hydrocraft"\n')
        f.write(f'Longitude = {LON}; Latitude = {LAT}; Elevation = 28\n')
        f.write('AngstromA = 0.18; AngstromB = 0.55; HasSunshine = False\n')
        f.write("## Daily weather observations\n")
        f.write("DAY,IRRAD,TMIN,TMAX,VAP,WIND,RAIN,SNOWDEPTH\n")

        for row in all_rows:
            day, irrad, tmin, tmax, vap, wind, rain = row
            f.write(f"{day},{irrad:.1f},{tmin:.1f},{tmax:.1f},{vap:.3f},{wind:.1f},{rain:.2f},0\n")

    print(f"Written: {output_csv}")

    # Quick validation
    irrad_vals = [r[1] for r in all_rows]
    rain_vals = [r[6] for r in all_rows]  # mm/day
    tmin_vals = [r[2] for r in all_rows]
    tmax_vals = [r[3] for r in all_rows]

    print(f"\nValidation:")
    print(f"  IRRAD range: {min(irrad_vals):.1f} - {max(irrad_vals):.1f} kJ/m²/day")
    print(f"  RAIN  range: {min(rain_vals):.2f} - {max(rain_vals):.2f} mm/day")
    print(f"  TMIN  range: {min(tmin_vals):.1f} - {max(tmin_vals):.1f} °C")
    print(f"  TMAX  range: {min(tmax_vals):.1f} - {max(tmax_vals):.1f} °C")
    print(f"  Annual precip: {sum(rain_vals)/((END_YEAR-START_YEAR+1)):.0f} mm/yr")


if __name__ == "__main__":
    main()
