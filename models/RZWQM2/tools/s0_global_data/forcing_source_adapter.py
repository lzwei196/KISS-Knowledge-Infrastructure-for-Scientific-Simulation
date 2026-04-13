#!/usr/bin/env python3
"""
forcing_source_adapter.py
=========================
Pluggable multi-backend meteorological forcing data retrieval for RZWQM2.

Produces a daily CSV in RZWQM2 format ready for generate_met_file.py:
    date, tmin, tmax, wind, radiation, epan, rh, par, rain

Units: tmin/tmax in C, wind in km/day, radiation in MJ/m2/day,
       epan in mm/day (estimated), rh in %, par in MJ/m2/day (estimated),
       rain in mm.

Supported sources:
    - cmfd:         CMFD NetCDF (China, 0.25 degree, 3-hourly)
    - vic_forcing:  VIC-format text files (space-delimited daily)
    - era5_api:     ERA5 via CDS API (global, requires cdsapi)
    - csv:          User-provided CSV (pass-through)

Inputs:
    lat             - Latitude in decimal degrees
    lon             - Longitude in decimal degrees
    start_date      - Start date (YYYY-MM-DD)
    end_date        - End date (YYYY-MM-DD)
    source          - Source identifier
    source_path     - Path to forcing data directory or CSV file
    output_csv      - Path for output CSV

Exit codes:
    0 - Success
    1 - Input validation error
    2 - Processing error
    3 - Output validation error
"""

import sys
import os
import csv
import json
import math
from datetime import datetime, timedelta

# ---------------------------------------------------------------------------
# INPUTS
# ---------------------------------------------------------------------------
LAT = ""
LON = ""
START_DATE = ""
END_DATE = ""
SOURCE = "csv"
SOURCE_PATH = ""
OUTPUT_CSV = ""

# ---------------------------------------------------------------------------
# Unit conversion constants
# ---------------------------------------------------------------------------
WIND_MS_TO_KMDAY = 86.4        # m/s -> km/day
SRAD_WM2_TO_MJ = 0.0864        # W/m2 -> MJ/m2/day (mean daily)
K_TO_C = -273.15                # Kelvin -> Celsius
PAR_FRACTION = 0.48             # PAR as fraction of total shortwave
EPAN_ET0_RATIO = 0.7            # E-pan ≈ 0.7 × ET0 (rough)

VALID_SOURCES = ['cmfd', 'mswx', 'vic_forcing', 'era5_api', 'csv']


def validate_inputs(lat_raw, lon_raw, start_raw, end_raw, source, source_path, output_csv):
    """Validate inputs."""
    errors = []

    lat = lon = None
    try:
        lat = float(lat_raw) if lat_raw else None
        if lat is None: errors.append("LAT is required.")
    except ValueError:
        errors.append(f"LAT must be numeric: {lat_raw}")
    try:
        lon = float(lon_raw) if lon_raw else None
        if lon is None: errors.append("LON is required.")
    except ValueError:
        errors.append(f"LON must be numeric: {lon_raw}")

    start_date = end_date = None
    try:
        start_date = datetime.strptime(start_raw.strip(), '%Y-%m-%d') if start_raw else None
        if not start_date: errors.append("START_DATE is required (YYYY-MM-DD).")
    except ValueError:
        errors.append(f"Invalid START_DATE: {start_raw}")
    try:
        end_date = datetime.strptime(end_raw.strip(), '%Y-%m-%d') if end_raw else None
        if not end_date: errors.append("END_DATE is required (YYYY-MM-DD).")
    except ValueError:
        errors.append(f"Invalid END_DATE: {end_raw}")

    if start_date and end_date and start_date >= end_date:
        errors.append(f"START_DATE >= END_DATE")

    source = source.strip().lower() if source else 'csv'
    if source not in VALID_SOURCES:
        errors.append(f"SOURCE must be one of {VALID_SOURCES}")

    if source in ('cmfd', 'mswx', 'vic_forcing', 'csv') and not source_path:
        errors.append(f"SOURCE_PATH is required for source '{source}'.")
    if source_path and source == 'csv' and not os.path.isfile(source_path):
        errors.append(f"SOURCE_PATH file not found: {source_path}")

    if not output_csv:
        errors.append("OUTPUT_CSV is required.")

    if errors:
        return False, "; ".join(errors), None

    return True, "", {
        'lat': lat, 'lon': lon,
        'start_date': start_date, 'end_date': end_date,
        'source': source, 'source_path': source_path,
        'output_csv': output_csv,
    }


def _saturation_vapor_pressure(temp_c):
    """Tetens formula: saturation vapor pressure (kPa) from temperature (C)."""
    return 0.6108 * math.exp(17.27 * temp_c / (temp_c + 237.3))


def _rh_from_specific_humidity(shum, temp_c, pres_pa):
    """Calculate RH from specific humidity, temperature, and pressure."""
    es = _saturation_vapor_pressure(temp_c) * 1000  # kPa -> Pa
    # ea = shum * pres_pa / (0.622 + 0.378 * shum)
    ea = shum * pres_pa / 0.622
    rh = (ea / es) * 100
    return max(0, min(100, rh))


def _estimate_epan(tmin, tmax, radiation_mj, wind_km_day, rh):
    """Rough Penman-Monteith ET0 estimate, then scale to E-pan."""
    tmean = (tmin + tmax) / 2.0
    es = _saturation_vapor_pressure(tmean)
    ea = es * rh / 100.0
    # Simplified Hargreaves ET0
    ra = radiation_mj  # approximate
    et0 = 0.0023 * (tmean + 17.8) * math.sqrt(max(0.1, tmax - tmin)) * ra
    et0 = max(0, et0)
    epan = et0 * EPAN_ET0_RATIO
    return round(epan, 2)


def _retrieve_csv(args):
    """Pass-through: read user CSV in the expected format."""
    source_path = args['source_path']
    output_csv = args['output_csv']

    import shutil
    shutil.copy2(source_path, output_csv)

    # Count records
    with open(output_csv) as f:
        reader = csv.DictReader(f)
        count = sum(1 for _ in reader)

    return count


def _read_cmfd_var(task):
    """Worker: read one CMFD monthly file, extract single pixel."""
    import netCDF4
    import numpy as np

    nc_file, lat_idx, lon_idx, var_name = task
    nc = netCDF4.Dataset(nc_file, 'r')
    var_keys = [v for v in nc.variables if v not in ('time', 'lat', 'lon')]
    if not var_keys:
        nc.close()
        return var_name, [], []
    pixel_ts = nc.variables[var_keys[0]][:, lat_idx, lon_idx]
    time_var = nc.variables['time']
    times = netCDF4.num2date(time_var[:], time_var.units,
                              calendar=getattr(time_var, 'calendar', 'standard'))
    nc.close()
    return var_name, times, pixel_ts


def _retrieve_cmfd(args):
    """Read CMFD NetCDF files and aggregate to daily RZWQM2 format.

    Uses multiprocessing to read 6 variables in parallel per month batch.
    """
    from multiprocessing import Pool
    import netCDF4
    import numpy as np

    lat = args['lat']
    lon = args['lon']
    source_path = args['source_path']
    start_date = args['start_date']
    end_date = args['end_date']
    output_csv = args['output_csv']

    cmfd_vars = {
        'temp': ('Temp', 'temp_CMFD_V0200_B-01_03hr_010deg_'),
        'prec': ('Prec', 'prec_CMFD_V0200_B-01_03hr_010deg_'),
        'wind': ('Wind', 'wind_CMFD_V0200_B-01_03hr_010deg_'),
        'srad': ('SRad', 'srad_CMFD_V0200_B-01_03hr_010deg_'),
        'shum': ('SHum', 'shum_CMFD_V0200_B-01_03hr_010deg_'),
        'pres': ('Pres', 'pres_CMFD_V0200_B-01_03hr_010deg_'),
    }

    # Find pixel indices from any file
    sample_file = None
    for var_name, (subdir, prefix) in cmfd_vars.items():
        var_dir = os.path.join(source_path, subdir)
        if os.path.isdir(var_dir):
            for f in sorted(os.listdir(var_dir)):
                if f.startswith(prefix) and f.endswith('.nc'):
                    sample_file = os.path.join(var_dir, f)
                    break
        if sample_file:
            break

    if not sample_file:
        raise RuntimeError(f"No CMFD NetCDF files found in {source_path}")

    nc0 = netCDF4.Dataset(sample_file, 'r')
    lats = nc0.variables['lat'][:]
    lons = nc0.variables['lon'][:]
    lat_idx = int(np.argmin(np.abs(lats - lat)))
    lon_idx = int(np.argmin(np.abs(lons - lon)))
    nc0.close()

    start_ym = start_date.year * 100 + start_date.month
    end_ym = end_date.year * 100 + end_date.month

    # Build task list: all (file, var) pairs
    tasks = []
    for var_name, (subdir, prefix) in cmfd_vars.items():
        var_dir = os.path.join(source_path, subdir)
        if not os.path.isdir(var_dir):
            var_dir = source_path
        for f in sorted(os.listdir(var_dir)):
            if not (f.startswith(prefix) and f.endswith('.nc')):
                continue
            ym_str = f.replace('.nc', '')[-6:]
            try:
                file_ym = int(ym_str)
                if file_ym < start_ym or file_ym > end_ym:
                    continue
            except ValueError:
                continue
            tasks.append((os.path.join(var_dir, f), lat_idx, lon_idx, var_name))

    # Read all files in parallel (6 vars × N months)
    daily_records = {}
    with Pool(processes=min(6, len(tasks))) as pool:
        results = pool.map(_read_cmfd_var, tasks)

    for var_name, times, pixel_ts in results:
        for t_idx in range(len(times)):
            ts = times[t_idx]
            day = ts.strftime('%Y-%m-%d') if hasattr(ts, 'strftime') else str(ts)[:10]
            val = float(pixel_ts[t_idx])
            if np.isnan(val):
                continue
            if day not in daily_records:
                daily_records[day] = {
                    'temps': [], 'prec': 0, 'winds': [],
                    'srads': [], 'shums': [], 'press': []
                }
            rec = daily_records[day]
            if var_name == 'temp':
                rec['temps'].append(val)
            elif var_name == 'prec':
                rec['prec'] += val * 10800  # kg/m2/s -> mm/3hr
            elif var_name == 'wind':
                rec['winds'].append(val)
            elif var_name == 'srad':
                rec['srads'].append(val)
            elif var_name == 'shum':
                rec['shums'].append(val)
            elif var_name == 'pres':
                rec['press'].append(val)

    # Write daily CSV
    count = 0
    with open(output_csv, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['date', 'tmin', 'tmax', 'wind', 'radiation', 'epan', 'rh', 'par', 'rain'])

        for day_str in sorted(daily_records.keys()):
            day_date = datetime.strptime(day_str, '%Y-%m-%d')
            if day_date < start_date or day_date > end_date:
                continue

            rec = daily_records[day_str]
            temps = rec['temps']
            if not temps:
                continue

            tmin = round(min(temps) + K_TO_C, 1)
            tmax = round(max(temps) + K_TO_C, 1)
            wind = round(sum(rec['winds']) / max(1, len(rec['winds'])) * WIND_MS_TO_KMDAY, 1)
            radiation = round(sum(rec['srads']) / max(1, len(rec['srads'])) * SRAD_WM2_TO_MJ, 2)
            rain = round(rec['prec'], 1)

            if rec['shums'] and rec['press']:
                tmean = (min(temps) + max(temps)) / 2 + K_TO_C
                shum_mean = sum(rec['shums']) / len(rec['shums'])
                pres_mean = sum(rec['press']) / len(rec['press'])
                rh = round(_rh_from_specific_humidity(shum_mean, tmean, pres_mean), 1)
            else:
                rh = 70.0

            epan = _estimate_epan(tmin, tmax, radiation, wind, rh)
            par = round(radiation * PAR_FRACTION, 2)

            if tmin > tmax:
                tmin, tmax = tmax, tmin

            writer.writerow([day_str, tmin, tmax, wind, radiation, epan, rh, par, rain])
            count += 1

    return count


def _retrieve_vic_forcing(args):
    """Read VIC forcing text files for a specific grid cell."""
    lat = args['lat']
    lon = args['lon']
    source_path = args['source_path']
    start_date = args['start_date']
    end_date = args['end_date']
    output_csv = args['output_csv']

    # Find the forcing file matching this lat/lon
    # VIC naming: prefix_LAT_LON (e.g., huai_01dy_025deg_31.1250_115.6250)
    best_file = None
    best_dist = float('inf')

    for fname in os.listdir(source_path):
        parts = fname.rsplit('_', 2)
        if len(parts) >= 3:
            try:
                f_lat = float(parts[-2])
                f_lon = float(parts[-1])
                dist = (f_lat - lat) ** 2 + (f_lon - lon) ** 2
                if dist < best_dist:
                    best_dist = dist
                    best_file = os.path.join(source_path, fname)
            except ValueError:
                continue

    if best_file is None:
        raise RuntimeError(f"No VIC forcing file found matching ({lat}, {lon}) in {source_path}")

    # Read VIC forcing: columns are typically [air_temp, precip, shortwave, longwave, pressure, vp, wind]
    records = []
    with open(best_file) as f:
        for line in f:
            parts = line.split()
            if len(parts) >= 7:
                records.append([float(p) for p in parts])

    # Write daily CSV
    num_days = (end_date - start_date).days + 1
    with open(output_csv, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['date', 'tmin', 'tmax', 'wind', 'radiation', 'epan', 'rh', 'par', 'rain'])

        for day_idx in range(min(num_days, len(records))):
            day_date = start_date + timedelta(days=day_idx)
            rec = records[day_idx]

            temp_c = rec[0]  # air temp (C or K)
            if temp_c > 100:
                temp_c += K_TO_C  # was in Kelvin
            tmin = round(temp_c - 3, 1)  # estimate diurnal range
            tmax = round(temp_c + 3, 1)
            rain = round(rec[1], 1)
            srad = rec[2] if len(rec) > 2 else 200
            wind = round(rec[6] * WIND_MS_TO_KMDAY if len(rec) > 6 else 100, 1)
            radiation = round(srad * SRAD_WM2_TO_MJ, 2)
            rh = 70.0  # default
            if len(rec) > 5:
                # vapor pressure (kPa) -> RH
                vp = rec[5]
                es = _saturation_vapor_pressure(temp_c)
                if es > 0:
                    rh = round(min(100, max(0, vp / es * 100)), 1)

            epan = _estimate_epan(tmin, tmax, radiation, wind, rh)
            par = round(radiation * PAR_FRACTION, 2)

            writer.writerow([day_date.strftime('%Y-%m-%d'), tmin, tmax, wind, radiation, epan, rh, par, rain])

    return min(num_days, len(records))


def _read_mswx_var(task):
    """Worker: read one MSWX variable file, extract single pixel, return (var_key, times, values)."""
    import netCDF4
    import numpy as np

    nc_path, nc_var, lat_idx, lon_idx, var_key = task
    nc = netCDF4.Dataset(nc_path, 'r')
    pixel_ts = nc.variables[nc_var][:, lat_idx, lon_idx]
    time_var = nc.variables['time']
    times = netCDF4.num2date(time_var[:], time_var.units,
                              calendar=getattr(time_var, 'calendar', 'standard'))
    nc.close()
    return var_key, times, pixel_ts


def _retrieve_mswx(args):
    """Read MSWX global 0.1deg 3-hourly NetCDF files and aggregate to daily RZWQM2 format.

    Uses multiprocessing to read all 6 variables per year in parallel.
    Each worker extracts a single pixel timeseries via netCDF4 direct indexed read.

    MSWX directory layout:
        {source_path}/Tair/Tair_YYYY.nc    -> air_temperature [deg C]
        {source_path}/P/P_YYYY.nc          -> precipitation [mm/3h]
        {source_path}/SWd/SWd_YYYY.nc      -> shortwave radiation [W/m2]
        {source_path}/wind/Wind_YYYY.nc    -> wind speed [m/s]
        {source_path}/Pres/Pres_YYYY.nc    -> surface pressure [Pa]
        {source_path}/spechum/spechum_YYYY.nc -> specific humidity [kg/kg]
    """
    from multiprocessing import Pool
    import netCDF4
    import numpy as np

    lat = args['lat']
    lon = args['lon']
    source_path = args['source_path']
    start_date = args['start_date']
    end_date = args['end_date']
    output_csv = args['output_csv']

    # MSWX variable mapping: (var_key, subdir, file_prefix, nc_var_name)
    mswx_vars = [
        ('temp',  'Tair',    'Tair',    'air_temperature'),
        ('prec',  'P',       'P',       'precipitation'),
        ('srad',  'SWd',     'SWd',     'downward_shortwave_radiation'),
        ('wind',  'wind',    'Wind',    'wind_speed'),
        ('pres',  'Pres',    'Pres',    'surface_pressure'),
        ('shum',  'spechum', 'spechum', 'specific_humidity'),
    ]

    years_needed = list(range(start_date.year, end_date.year + 1))

    # Find pixel indices once from any available file
    lat_idx = lon_idx = None
    for subdir, prefix, nc_var in [(v[1], v[2], v[3]) for v in mswx_vars]:
        sample_path = os.path.join(source_path, subdir, f'{prefix}_{years_needed[0]}.nc')
        if os.path.isfile(sample_path):
            nc = netCDF4.Dataset(sample_path, 'r')
            lats = nc.variables['lat'][:]
            lons = nc.variables['lon'][:]
            lat_idx = int(np.argmin(np.abs(lats - lat)))
            lon_idx = int(np.argmin(np.abs(lons - lon)))
            nc.close()
            break

    if lat_idx is None:
        raise RuntimeError("Could not find any MSWX file to determine grid indices.")

    # Build task list: all (file, var) pairs across all years
    tasks = []
    for year in years_needed:
        for var_key, subdir, prefix, nc_var in mswx_vars:
            nc_path = os.path.join(source_path, subdir, f'{prefix}_{year}.nc')
            if os.path.isfile(nc_path):
                tasks.append((nc_path, nc_var, lat_idx, lon_idx, var_key))

    # Read all files in parallel (6 vars × N years)
    daily_records = {}
    with Pool(processes=min(6, len(tasks))) as pool:
        results = pool.map(_read_mswx_var, tasks)

    for var_key, times, pixel_ts in results:
        for t_idx in range(len(times)):
            ts = times[t_idx]
            day = ts.strftime('%Y-%m-%d') if hasattr(ts, 'strftime') else str(ts)[:10]
            val = float(pixel_ts[t_idx])
            if np.isnan(val):
                continue

            if day not in daily_records:
                daily_records[day] = {
                    'temps': [], 'prec': 0,
                    'winds': [], 'srads': [],
                    'shums': [], 'press': []
                }
            rec = daily_records[day]
            if var_key == 'temp':
                rec['temps'].append(val)
            elif var_key == 'prec':
                rec['prec'] += val  # mm/3h, sum to daily
            elif var_key == 'wind':
                rec['winds'].append(val)
            elif var_key == 'srad':
                rec['srads'].append(val)
            elif var_key == 'shum':
                rec['shums'].append(val)
            elif var_key == 'pres':
                rec['press'].append(val)

    # Write daily CSV
    count = 0
    with open(output_csv, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['date', 'tmin', 'tmax', 'wind', 'radiation', 'epan', 'rh', 'par', 'rain'])

        for day_str in sorted(daily_records.keys()):
            day_date = datetime.strptime(day_str, '%Y-%m-%d')
            if day_date < start_date or day_date > end_date:
                continue

            rec = daily_records[day_str]
            temps = rec['temps']
            if not temps:
                continue

            # MSWX Tair is already in deg C (no Kelvin conversion needed)
            tmin = round(min(temps), 1)
            tmax = round(max(temps), 1)
            wind = round(sum(rec['winds']) / max(1, len(rec['winds'])) * WIND_MS_TO_KMDAY, 1)
            radiation = round(sum(rec['srads']) / max(1, len(rec['srads'])) * SRAD_WM2_TO_MJ, 2)
            rain = round(rec['prec'], 1)

            if rec['shums'] and rec['press']:
                tmean = (tmin + tmax) / 2
                shum_mean = sum(rec['shums']) / len(rec['shums'])
                pres_mean = sum(rec['press']) / len(rec['press'])
                rh = round(_rh_from_specific_humidity(shum_mean, tmean, pres_mean), 1)
            else:
                rh = 70.0

            epan = _estimate_epan(tmin, tmax, radiation, wind, rh)
            par = round(radiation * PAR_FRACTION, 2)

            if tmin > tmax:
                tmin, tmax = tmax, tmin

            writer.writerow([day_str, tmin, tmax, wind, radiation, epan, rh, par, rain])
            count += 1

    return count


def process(args):
    """
    Retrieve forcing data from the specified source.
    Returns (success, error_msg, summary).
    """
    source = args['source']

    try:
        record_count = 0

        if source == 'csv':
            record_count = _retrieve_csv(args)
        elif source == 'cmfd':
            record_count = _retrieve_cmfd(args)
        elif source == 'mswx':
            record_count = _retrieve_mswx(args)
        elif source == 'vic_forcing':
            record_count = _retrieve_vic_forcing(args)
        elif source == 'era5_api':
            return False, "era5_api backend not yet implemented (requires cdsapi package).", None

        summary = {
            'output_csv': args['output_csv'],
            'source': source,
            'record_count': record_count,
            'start_date': args['start_date'].strftime('%Y-%m-%d'),
            'end_date': args['end_date'].strftime('%Y-%m-%d'),
        }

        return True, "", summary

    except Exception as e:
        return False, f"Processing error: {e}", None


def validate_outputs(args):
    """Check output CSV exists and has data."""
    output_csv = args['output_csv']
    if not os.path.isfile(output_csv):
        return False, f"Output CSV was not created: {output_csv}"

    with open(output_csv) as f:
        reader = csv.reader(f)
        rows = list(reader)

    if len(rows) < 2:
        return False, "Output CSV has no data rows."

    return True, ""


def main():
    lat_raw = sys.argv[1] if len(sys.argv) > 1 else LAT
    lon_raw = sys.argv[2] if len(sys.argv) > 2 else LON
    start_raw = sys.argv[3] if len(sys.argv) > 3 else START_DATE
    end_raw = sys.argv[4] if len(sys.argv) > 4 else END_DATE
    source = sys.argv[5] if len(sys.argv) > 5 else SOURCE
    source_path = sys.argv[6] if len(sys.argv) > 6 else SOURCE_PATH
    output_csv = sys.argv[7] if len(sys.argv) > 7 else OUTPUT_CSV

    valid, err, args = validate_inputs(lat_raw, lon_raw, start_raw, end_raw, source, source_path, output_csv)
    if not valid:
        print(json.dumps({"status": "INPUT_ERROR", "message": err}))
        sys.exit(1)

    success, err, summary = process(args)
    if not success:
        print(json.dumps({"status": "PROCESSING_ERROR", "message": err}))
        sys.exit(2)

    valid, err = validate_outputs(args)
    if not valid:
        print(json.dumps({"status": "OUTPUT_ERROR", "message": err}))
        sys.exit(3)

    print(json.dumps({
        "status": "SUCCESS",
        "summary": summary,
        "message": (
            f"Retrieved {summary['record_count']} days of forcing data from {source} "
            f"({summary['start_date']} to {summary['end_date']}). Written to {summary['output_csv']}."
        )
    }))
    sys.exit(0)


if __name__ == '__main__':
    main()
