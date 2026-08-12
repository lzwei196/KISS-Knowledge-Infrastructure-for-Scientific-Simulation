#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
==========================================
Tool ID:      create_csv_weather_file
Stage:        s3_weather_prep
Description:  Create a PCSE-compatible CSV weather file from generic daily
              weather data with proper header and units.

              PCSE CSVWeatherDataProvider format requires (verified against
              pcse 6.0.12 csvweatherdataprovider.py obs_conversions):
                IRRAD: kJ/m2/day  (provider multiplies x1000 -> J/m2/day)
                RAIN:  mm/day     (provider divides /10 -> cm internally)
                VAP:   kPa        (provider multiplies x10 -> hPa internally)
                WIND:  m/s
                TMIN/TMAX: Celsius
                DAY column: YYYYMMDD (default dateformat '%Y%m%d')
                SNOWDEPTH missing value: NaN (not -999)
              Header string values MUST be quoted Python literals; the geo line
              must be a single ';'-separated line with NO trailing comments,
              because the provider runs ast.literal_eval on every header value.

Inputs:
  - INPUT_CSV: generic weather CSV (with date, radiation, temp, precip columns)
  - LAT, LON, ELEV: station coordinates
  - OUTPUT_FILE: output PCSE CSV path
  - Column mapping and unit conversion flags

Outputs:
  - PCSE-formatted CSV weather file

Exit codes:
  0 — success, 1 — input error, 2 — processing error, 3 — output error
"""

import sys
import os
import json
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

INPUT_CSV = ""
OUTPUT_FILE = ""
LAT = 52.0
LON = 5.5
ELEV = 10.0

# Column mapping (input column name → PCSE variable)
COL_DATE = "date"
COL_IRRAD = "IRRAD"       # input radiation column
COL_TMIN = "TMIN"
COL_TMAX = "TMAX"
COL_VAP = "VAP"
COL_WIND = "WIND"
COL_RAIN = "RAIN"

# Unit flags — set True if input needs conversion
IRRAD_IS_MJ = False        # True if radiation is MJ/m2/day (multiply by 1000)
IRRAD_IS_WM2 = False       # True if radiation is W/m2 (multiply by 86.4)
RAIN_IS_CM = False          # True if precipitation is cm (multiply by 10 -> mm).
                            # PCSE CSV must hold mm; load_forcing already gives mm.
TEMP_IS_KELVIN = False      # True if temperature is Kelvin (subtract 273.15)
VAP_IS_HPA = False          # True if vapor pressure is hPa/mbar (divide by 10)
WIND_IS_KMDAY = False       # True if wind is km/day (divide by 86.4)


def validate_inputs():
    errors = []
    if not INPUT_CSV or not Path(INPUT_CSV).exists():
        errors.append(f"INPUT_CSV not found: {INPUT_CSV}")
    if not OUTPUT_FILE:
        errors.append("OUTPUT_FILE not set")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)


def process():
    import pandas as pd

    df = pd.read_csv(INPUT_CSV, parse_dates=[COL_DATE])

    # Unit conversions
    if IRRAD_IS_MJ:
        df[COL_IRRAD] = df[COL_IRRAD] * 1000.0
        logger.info("Converted IRRAD: MJ/m2/day -> kJ/m2/day (x1000)")
    if IRRAD_IS_WM2:
        df[COL_IRRAD] = df[COL_IRRAD] * 86.4
        logger.info("Converted IRRAD: W/m2 -> kJ/m2/day (x86.4)")

    # PCSE CSVWeatherDataProvider expects RAIN in mm (it converts mm->cm itself).
    if RAIN_IS_CM:
        df[COL_RAIN] = df[COL_RAIN] * 10.0
        logger.info("Converted RAIN: cm -> mm (x10)")

    if TEMP_IS_KELVIN:
        df[COL_TMIN] = df[COL_TMIN] - 273.15
        df[COL_TMAX] = df[COL_TMAX] - 273.15
        logger.info("Converted TEMP: K -> C (-273.15)")

    if VAP_IS_HPA:
        df[COL_VAP] = df[COL_VAP] / 10.0
        logger.info("Converted VAP: hPa -> kPa (/10)")

    if WIND_IS_KMDAY:
        df[COL_WIND] = df[COL_WIND] / 86.4
        logger.info("Converted WIND: km/day -> m/s (/86.4)")

    # Validation (units are now: IRRAD kJ/m2/day, RAIN mm/day)
    max_irrad = df[COL_IRRAD].max()
    max_rain = df[COL_RAIN].max()
    if max_irrad < 100:
        logger.warning(f"IRRAD max={max_irrad:.1f} — suspiciously low, may be in MJ instead of kJ!")
    if max_rain > 500:
        logger.warning(f"RAIN max={max_rain:.1f} mm — suspiciously high, check units!")

    # Write PCSE CSV in the exact format CSVWeatherDataProvider expects.
    # The provider runs ast.literal_eval on every header value, so strings must
    # be quoted and the geo line must be a single ';'-separated statement list
    # with NO trailing comments. Dates are YYYYMMDD; missing SNOWDEPTH is NaN.
    os.makedirs(os.path.dirname(OUTPUT_FILE) or '.', exist_ok=True)
    src = str(INPUT_CSV).replace("'", "")
    with open(OUTPUT_FILE, 'w') as f:
        f.write("## Site Characteristics\n")
        f.write("Country = 'unknown'\n")
        f.write("Station = 'custom'\n")
        f.write("Description = 'Weather data converted for PCSE'\n")
        f.write(f"Source = '{src}'\n")
        f.write("Contact = 'HydroCraft'\n")
        f.write(f"Longitude = {LON}; Latitude = {LAT}; Elevation = {ELEV}; "
                f"AngstromA = 0.18; AngstromB = 0.55; HasSunshine = False\n")
        f.write("## Daily weather observations (missing values are NaN)\n")
        f.write("DAY,IRRAD,TMIN,TMAX,VAP,WIND,RAIN,SNOWDEPTH\n")

        for _, row in df.iterrows():
            dv = row[COL_DATE]
            day = dv.strftime('%Y%m%d') if hasattr(dv, 'strftime') else str(dv).replace('-', '')
            f.write(f"{day},{row[COL_IRRAD]:.1f},{row[COL_TMIN]:.1f},{row[COL_TMAX]:.1f},"
                    f"{row[COL_VAP]:.3f},{row[COL_WIND]:.1f},{row[COL_RAIN]:.4f},NaN\n")

    logger.info(f"Created: {OUTPUT_FILE} ({len(df)} days)")
    return OUTPUT_FILE


if __name__ == "__main__":
    if len(sys.argv) >= 5:
        INPUT_CSV = sys.argv[1]
        LAT = float(sys.argv[2])
        LON = float(sys.argv[3])
        OUTPUT_FILE = sys.argv[4]
    if len(sys.argv) >= 6:
        ELEV = float(sys.argv[5])

    # Unit-conversion flags are not positional; allow overriding via env so the
    # tool is usable for W/m2 + mm input (e.g. ki_tools_common.load_forcing
    # returns srad in W/m2 and precip in mm). "1"/"true"/"yes" enable a flag.
    def _envflag(name, default):
        v = os.environ.get(name)
        if v is None:
            return default
        return v.strip().lower() in ("1", "true", "yes", "on")
    IRRAD_IS_MJ = _envflag("WX_IRRAD_IS_MJ", IRRAD_IS_MJ)
    IRRAD_IS_WM2 = _envflag("WX_IRRAD_IS_WM2", IRRAD_IS_WM2)
    RAIN_IS_CM = _envflag("WX_RAIN_IS_CM", RAIN_IS_CM)
    TEMP_IS_KELVIN = _envflag("WX_TEMP_IS_KELVIN", TEMP_IS_KELVIN)
    VAP_IS_HPA = _envflag("WX_VAP_IS_HPA", VAP_IS_HPA)
    WIND_IS_KMDAY = _envflag("WX_WIND_IS_KMDAY", WIND_IS_KMDAY)

    validate_inputs()
    try:
        result = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        sys.exit(2)

    print(json.dumps({"status": "success", "output_file": result}))
    sys.exit(0)
