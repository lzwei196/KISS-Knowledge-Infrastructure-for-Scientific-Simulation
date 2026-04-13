#!/usr/bin/env python3
"""
vic_forcing_converter.py
========================
Convert VIC forcing files to RZWQM2 daily meteorological CSV format.

Reads VIC forcing files (either CMFD NetCDF or processed VIC daily text)
for a specific grid cell and produces a CSV in RZWQM2 format:
    date, tmin, tmax, wind, radiation, epan, rh, par, rain

Key unit conversions:
    Temperature:  K -> C           (subtract 273.15)
    Radiation:    W/m2 -> MJ/m2/day (multiply by 0.0864)
    Wind:         m/s -> km/day    (multiply by 86.4)
    Humidity:     specific -> RH%  (ea/es * 100)
    E-pan:        estimated as 0.7 * ET0 (Hargreaves)
    PAR:          estimated as 0.48 * shortwave radiation

Inputs:
    vic_forcing_dir - Directory containing VIC forcing files
    lat             - Latitude in decimal degrees
    lon             - Longitude in decimal degrees
    start_date      - Start date (YYYY-MM-DD)
    end_date        - End date (YYYY-MM-DD)
    output_csv      - Path for output CSV
    forcing_format  - Format: "vic_text" or "cmfd_nc" (default: vic_text)

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
VIC_FORCING_DIR = ""    # Directory with VIC forcing files
LAT = ""
LON = ""
START_DATE = ""
END_DATE = ""
OUTPUT_CSV = ""
FORCING_FORMAT = "vic_text"  # "vic_text" or "cmfd_nc"

# Unit conversion constants
WIND_MS_TO_KMDAY = 86.4
SRAD_WM2_TO_MJ = 0.0864
K_TO_C = -273.15
PAR_FRACTION = 0.48


def validate_inputs(vic_dir, lat_raw, lon_raw, start_raw, end_raw, output_csv, fmt):
    """Validate inputs."""
    errors = []

    if not vic_dir:
        errors.append("VIC_FORCING_DIR is required.")
    elif not os.path.isdir(vic_dir):
        errors.append(f"VIC_FORCING_DIR not found: {vic_dir}")

    lat = lon = None
    try:
        lat = float(lat_raw) if lat_raw else None
        if lat is None: errors.append("LAT required.")
    except ValueError:
        errors.append(f"LAT must be numeric: {lat_raw}")
    try:
        lon = float(lon_raw) if lon_raw else None
        if lon is None: errors.append("LON required.")
    except ValueError:
        errors.append(f"LON must be numeric: {lon_raw}")

    start_date = end_date = None
    try:
        start_date = datetime.strptime(start_raw.strip(), '%Y-%m-%d') if start_raw else None
        if not start_date: errors.append("START_DATE required.")
    except ValueError:
        errors.append(f"Invalid START_DATE: {start_raw}")
    try:
        end_date = datetime.strptime(end_raw.strip(), '%Y-%m-%d') if end_raw else None
        if not end_date: errors.append("END_DATE required.")
    except ValueError:
        errors.append(f"Invalid END_DATE: {end_raw}")

    if not output_csv:
        errors.append("OUTPUT_CSV required.")

    fmt = fmt.strip().lower() if fmt else 'vic_text'
    if fmt not in ('vic_text', 'cmfd_nc'):
        errors.append(f"FORCING_FORMAT must be 'vic_text' or 'cmfd_nc', got: {fmt}")

    if errors:
        return False, "; ".join(errors), None

    return True, "", {
        'vic_dir': vic_dir, 'lat': lat, 'lon': lon,
        'start_date': start_date, 'end_date': end_date,
        'output_csv': output_csv, 'format': fmt,
    }


def _sat_vp(temp_c):
    """Saturation vapor pressure (kPa) from temperature (C)."""
    return 0.6108 * math.exp(17.27 * temp_c / (temp_c + 237.3))


def _find_nearest_file(vic_dir, lat, lon):
    """Find VIC forcing file closest to lat/lon."""
    best_file = None
    best_dist = float('inf')

    for fname in os.listdir(vic_dir):
        if fname.startswith('.'):
            continue
        parts = fname.rsplit('_', 2)
        if len(parts) >= 3:
            try:
                f_lat = float(parts[-2])
                f_lon = float(parts[-1])
                dist = (f_lat - lat) ** 2 + (f_lon - lon) ** 2
                if dist < best_dist:
                    best_dist = dist
                    best_file = os.path.join(vic_dir, fname)
            except ValueError:
                continue

    return best_file


def process(args):
    """
    Convert VIC forcing to RZWQM2 CSV.
    Returns (success, error_msg, summary).
    """
    vic_dir = args['vic_dir']
    lat = args['lat']
    lon = args['lon']
    start_date = args['start_date']
    end_date = args['end_date']
    output_csv = args['output_csv']
    fmt = args['format']

    try:
        if fmt == 'vic_text':
            forcing_file = _find_nearest_file(vic_dir, lat, lon)
            if not forcing_file:
                return False, f"No VIC forcing file found near ({lat}, {lon}) in {vic_dir}", None

            with open(forcing_file) as f:
                lines = [l.strip() for l in f if l.strip()]

            num_days = (end_date - start_date).days + 1
            record_count = 0

            with open(output_csv, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['date', 'tmin', 'tmax', 'wind', 'radiation', 'epan', 'rh', 'par', 'rain'])

                for day_idx in range(min(num_days, len(lines))):
                    parts = lines[day_idx].split()
                    if len(parts) < 4:
                        continue

                    day_date = start_date + timedelta(days=day_idx)

                    # VIC text format: air_temp, precip, swdown, lwdown, [pressure, vp, wind]
                    temp = float(parts[0])
                    if temp > 100:
                        temp += K_TO_C

                    rain = float(parts[1])
                    srad = float(parts[2]) if len(parts) > 2 else 200
                    wind_ms = float(parts[6]) if len(parts) > 6 else 2.0

                    tmin = round(temp - 4.0, 1)
                    tmax = round(temp + 4.0, 1)
                    wind = round(wind_ms * WIND_MS_TO_KMDAY, 1)
                    radiation = round(srad * SRAD_WM2_TO_MJ, 2)

                    # RH from vapor pressure if available
                    rh = 70.0
                    if len(parts) > 5:
                        vp_kpa = float(parts[5])
                        es = _sat_vp(temp)
                        if es > 0:
                            rh = round(min(100, max(0, vp_kpa / es * 100)), 1)

                    par = round(radiation * PAR_FRACTION, 2)
                    tmean = (tmin + tmax) / 2.0
                    et0 = max(0, 0.0023 * (tmean + 17.8) * math.sqrt(max(0.1, tmax - tmin)) * radiation)
                    epan = round(et0 * 0.7, 2)

                    if tmin > tmax:
                        tmin, tmax = tmax, tmin

                    writer.writerow([day_date.strftime('%Y-%m-%d'), tmin, tmax, wind, radiation, epan, rh, par, rain])
                    record_count += 1

        elif fmt == 'cmfd_nc':
            # Delegate to forcing_source_adapter CMFD backend
            from tools.s0_global_data.forcing_source_adapter import _retrieve_cmfd
            record_count = _retrieve_cmfd(args)

        summary = {
            'output_csv': output_csv,
            'record_count': record_count,
            'format': fmt,
        }

        return True, "", summary

    except Exception as e:
        return False, f"Processing error: {e}", None


def validate_outputs(args):
    """Check output CSV."""
    if not os.path.isfile(args['output_csv']):
        return False, f"Output CSV not created: {args['output_csv']}"
    return True, ""


def main():
    vic_dir = sys.argv[1] if len(sys.argv) > 1 else VIC_FORCING_DIR
    lat_raw = sys.argv[2] if len(sys.argv) > 2 else LAT
    lon_raw = sys.argv[3] if len(sys.argv) > 3 else LON
    start_raw = sys.argv[4] if len(sys.argv) > 4 else START_DATE
    end_raw = sys.argv[5] if len(sys.argv) > 5 else END_DATE
    output_csv = sys.argv[6] if len(sys.argv) > 6 else OUTPUT_CSV
    fmt = sys.argv[7] if len(sys.argv) > 7 else FORCING_FORMAT

    valid, err, args = validate_inputs(vic_dir, lat_raw, lon_raw, start_raw, end_raw, output_csv, fmt)
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
        "message": f"Converted {summary['record_count']} days of VIC forcing to RZWQM2 format."
    }))
    sys.exit(0)


if __name__ == '__main__':
    main()
