#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
==========================================
Tool ID:      create_csv_weather_file
Stage:        s3_weather_prep
Description:  Create a PCSE-compatible CSV weather file from generic daily
              weather data with proper header and units.

              PCSE CSV format requires:
                IRRAD: kJ/m2/day (NOT MJ)
                RAIN:  cm/day    (NOT mm)
                VAP:   kPa
                WIND:  m/s
                TMIN/TMAX: Celsius

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
RAIN_IS_MM = False          # True if precipitation is mm (divide by 10)
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

    if RAIN_IS_MM:
        df[COL_RAIN] = df[COL_RAIN] / 10.0
        logger.info("Converted RAIN: mm -> cm (/10)")

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

    # Validation
    max_irrad = df[COL_IRRAD].max()
    max_rain = df[COL_RAIN].max()
    if max_irrad < 100:
        logger.warning(f"IRRAD max={max_irrad:.1f} — suspiciously low, may be in MJ instead of kJ!")
    if max_rain > 50:
        logger.warning(f"RAIN max={max_rain:.1f} — suspiciously high, may be in mm instead of cm!")

    # Write PCSE CSV
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, 'w') as f:
        f.write("## Site Characteristics\n")
        f.write(f"Country    = unknown\n")
        f.write(f"Station    = custom\n")
        f.write(f"Description = Weather data converted for PCSE\n")
        f.write(f"Source     = {INPUT_CSV}\n")
        f.write(f"Contact    = \n")
        f.write(f"Longitude  = {LON}; decimal degrees\n")
        f.write(f"Latitude   = {LAT}; decimal degrees\n")
        f.write(f"Elevation  = {ELEV}; meters\n")
        f.write(f"AngstromA  = 0.18\n")
        f.write(f"AngstromB  = 0.55\n")
        f.write(f"HasSunshine = False\n")
        f.write(f"\n")
        f.write("## Daily weather observations\n")
        f.write("DAY,IRRAD,TMIN,TMAX,VAP,WIND,RAIN,SNOWDEPTH\n")

        for _, row in df.iterrows():
            day = row[COL_DATE].strftime('%Y-%m-%d') if hasattr(row[COL_DATE], 'strftime') else str(row[COL_DATE])
            f.write(f"{day},{row[COL_IRRAD]:.1f},{row[COL_TMIN]:.1f},{row[COL_TMAX]:.1f},"
                    f"{row[COL_VAP]:.3f},{row[COL_WIND]:.1f},{row[COL_RAIN]:.4f},-999\n")

    logger.info(f"Created: {OUTPUT_FILE} ({len(df)} days)")
    return OUTPUT_FILE


if __name__ == "__main__":
    if len(sys.argv) >= 5:
        INPUT_CSV = sys.argv[1]
        LAT = float(sys.argv[2])
        LON = float(sys.argv[3])
        OUTPUT_FILE = sys.argv[4]

    validate_inputs()
    try:
        result = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        sys.exit(2)

    print(json.dumps({"status": "success", "output_file": result}))
    sys.exit(0)
